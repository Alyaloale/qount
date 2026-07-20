"""Immutable raw collection contract for Equity Mapping forward research."""

from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qsl, urlsplit

from qount.mini_trend.equity_mapping import EquityMappingG0Config
from qount.mini_trend.equity_mapping import NEW_YORK
from qount.mini_trend.futures_recovery import canonical_hash
from qount.models import utc_now


EQUITY_MAPPING_COLLECTION_VERSION = "equity_mapping_raw_collection_v0.1"
_ASSET_ROLES = frozenset(
    {
        "instrument_mapping",
        "mapped_quote",
        "cash_premarket_quote",
        "corporate_action",
        "event_context",
    }
)
_GLOBAL_ROLES = frozenset(
    {"usdt_usd_quote", "cash_calendar", "stress_scenario"}
)
_QUOTE_ROLES = frozenset(
    {"mapped_quote", "cash_premarket_quote", "usdt_usd_quote"}
)
_ALL_ROLES = _ASSET_ROLES | _GLOBAL_ROLES
_MAX_CAPTURE_BYTES = 2 * 1024 * 1024
_MAX_BATCH_BYTES = 16 * 1024 * 1024
_SAFE_LABEL = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "access_key",
        "apikey",
        "api_key",
        "authorization",
        "key",
        "secret",
        "signature",
        "token",
    }
)


def _timestamp(value: object) -> dt.datetime:
    if not isinstance(value, str):
        raise ValueError("equity_mapping_collection_timestamp_invalid")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("equity_mapping_collection_timestamp_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("equity_mapping_collection_timestamp_naive")
    return parsed.astimezone(dt.UTC)


def _iso_utc(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).isoformat()


def _collection_window(
    cash_trading_date: str,
    config: EquityMappingG0Config,
) -> tuple[dt.datetime, dt.datetime]:
    try:
        date_value = dt.date.fromisoformat(cash_trading_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("equity_mapping_collection_cash_date_invalid") from exc
    start = dt.datetime.combine(
        date_value,
        dt.time.fromisoformat(config.reference_window_start_local),
        NEW_YORK,
    ).astimezone(dt.UTC)
    decision = dt.datetime.combine(
        date_value,
        dt.time.fromisoformat(config.decision_time_local),
        NEW_YORK,
    ).astimezone(dt.UTC)
    return start, decision


def build_equity_mapping_collection_readiness(
    cash_trading_date: str,
    *,
    as_of: dt.datetime | None = None,
    config: EquityMappingG0Config | None = None,
) -> dict[str, Any]:
    """Describe the frozen capture window without claiming a market observation."""

    config = config or EquityMappingG0Config()
    start, decision = _collection_window(cash_trading_date, config)
    current = (as_of or utc_now()).astimezone(dt.UTC)
    if current < start:
        status = "await_collection_window"
    elif current <= decision:
        status = "capture_window_open"
    else:
        status = "collection_window_closed"
    return {
        "schema_version": EQUITY_MAPPING_COLLECTION_VERSION,
        "artifact_type": "equity_mapping_collection_readiness",
        "created_at": utc_now().isoformat(),
        "cash_trading_date": cash_trading_date,
        "reference_window_start": _iso_utc(start),
        "decision_time": _iso_utc(decision),
        "as_of": _iso_utc(current),
        "status": status,
        "required_asset_roles": sorted(_ASSET_ROLES),
        "required_global_roles": sorted(_GLOBAL_ROLES),
        "maximum_cross_leg_skew_seconds": config.maximum_quote_skew_seconds,
        "meta": {
            "research_only": True,
            "raw_collection_only": True,
            "market_evidence_present": False,
            "future_return_evaluated": False,
            "pnl_evaluated": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
    }


def _validate_source_url(raw: object, allowlist: frozenset[str]) -> str:
    if not isinstance(raw, str):
        raise ValueError("equity_mapping_collection_source_url_invalid")
    parsed = urlsplit(raw)
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.port not in {None, 443}
    ):
        raise ValueError("equity_mapping_collection_source_url_unsafe")
    if hostname not in allowlist:
        raise ValueError("equity_mapping_collection_source_host_not_allowlisted")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise ValueError("equity_mapping_collection_source_ip_literal_forbidden")
    query_keys = {key.casefold() for key, _ in parse_qsl(parsed.query)}
    if query_keys & _SENSITIVE_QUERY_KEYS:
        raise ValueError("equity_mapping_collection_source_url_contains_secret")
    return raw


def _content_suffix(content_type: str) -> str:
    normalized = content_type.split(";", 1)[0].strip().casefold()
    if normalized == "application/json":
        return ".json"
    if normalized in {"text/csv", "application/csv"}:
        return ".csv"
    if normalized.startswith("text/"):
        return ".txt"
    return ".bin"


def _read_capture(path_value: object, *, base_dir: Path) -> tuple[Path, bytes]:
    if not isinstance(path_value, str) or not path_value:
        raise ValueError("equity_mapping_collection_raw_path_invalid")
    source_path = Path(path_value).expanduser()
    if not source_path.is_absolute():
        source_path = base_dir / source_path
    source_path = source_path.resolve()
    if not source_path.is_file():
        raise ValueError("equity_mapping_collection_raw_file_missing")
    raw = source_path.read_bytes()
    if not raw:
        raise ValueError("equity_mapping_collection_raw_file_empty")
    if len(raw) > _MAX_CAPTURE_BYTES:
        raise ValueError("equity_mapping_collection_raw_file_too_large")
    return source_path, raw


def build_equity_mapping_collection_batch(
    payload: Mapping[str, Any],
    *,
    base_dir: Path,
    config: EquityMappingG0Config | None = None,
) -> tuple[dict[str, Any], tuple[tuple[Path, bytes], ...]]:
    """Validate raw bodies and return a deterministic, sealable batch."""

    config = config or EquityMappingG0Config()
    if payload.get("schema_version") != EQUITY_MAPPING_COLLECTION_VERSION:
        raise ValueError("equity_mapping_collection_schema_invalid")
    dataset_role = str(payload.get("dataset_role", ""))
    if dataset_role not in {"point_in_time_forward_collection", "synthetic_fixture"}:
        raise ValueError("equity_mapping_collection_dataset_role_invalid")
    cash_trading_date = str(payload.get("cash_trading_date", ""))
    start, decision = _collection_window(cash_trading_date, config)

    raw_allowlist = payload.get("source_allowlist")
    if not isinstance(raw_allowlist, list) or not raw_allowlist:
        raise ValueError("equity_mapping_collection_source_allowlist_invalid")
    allowlist = frozenset(str(item).strip().lower() for item in raw_allowlist)
    if any(not host or ":" in host or "/" in host for host in allowlist):
        raise ValueError("equity_mapping_collection_source_allowlist_invalid")

    raw_captures = payload.get("captures")
    if not isinstance(raw_captures, list) or not raw_captures:
        raise ValueError("equity_mapping_collection_captures_invalid")

    prepared: list[tuple[dict[str, Any], Path, bytes, dt.datetime | None]] = []
    keys: set[tuple[str, str]] = set()
    total_bytes = 0
    for index, raw_capture in enumerate(raw_captures):
        if not isinstance(raw_capture, Mapping):
            raise ValueError(f"equity_mapping_collection_capture_not_object:{index}")
        role = str(raw_capture.get("role", ""))
        asset_key = str(raw_capture.get("asset_key", ""))
        source_id = str(raw_capture.get("source_id", ""))
        content_type = str(raw_capture.get("content_type", ""))
        if role not in _ALL_ROLES:
            raise ValueError("equity_mapping_collection_role_invalid")
        if not _SAFE_LABEL.fullmatch(asset_key) or not _SAFE_LABEL.fullmatch(source_id):
            raise ValueError("equity_mapping_collection_identity_invalid")
        if role in _GLOBAL_ROLES and asset_key != "GLOBAL":
            raise ValueError("equity_mapping_collection_global_asset_key_invalid")
        if role in _ASSET_ROLES and asset_key == "GLOBAL":
            raise ValueError("equity_mapping_collection_asset_key_invalid")
        key = (role, asset_key)
        if key in keys:
            raise ValueError("equity_mapping_collection_duplicate_role_asset")
        keys.add(key)
        if not content_type or any(ord(char) < 32 for char in content_type):
            raise ValueError("equity_mapping_collection_content_type_invalid")
        if raw_capture.get("raw_scope") != "response_body_only":
            raise ValueError("equity_mapping_collection_raw_scope_invalid")

        source_url = _validate_source_url(raw_capture.get("source_url"), allowlist)
        observed_at = _timestamp(raw_capture.get("observed_at"))
        available_at = _timestamp(raw_capture.get("available_at"))
        if observed_at > available_at:
            raise ValueError("equity_mapping_collection_observed_after_available")
        if available_at > decision:
            raise ValueError("equity_mapping_collection_available_after_decision")

        source_event_raw = raw_capture.get("source_event_at")
        source_event_at = (
            _timestamp(source_event_raw) if source_event_raw is not None else None
        )
        if role in _QUOTE_ROLES:
            if source_event_at is None:
                raise ValueError("equity_mapping_collection_quote_event_time_missing")
            if not start <= source_event_at <= decision:
                raise ValueError("equity_mapping_collection_quote_outside_window")
            if not start <= observed_at <= available_at <= decision:
                raise ValueError("equity_mapping_collection_quote_capture_outside_window")
            if source_event_at > available_at:
                raise ValueError("equity_mapping_collection_quote_available_before_event")
        elif source_event_at is not None and source_event_at > available_at:
            raise ValueError("equity_mapping_collection_source_available_before_event")

        source_path, raw = _read_capture(raw_capture.get("path"), base_dir=base_dir)
        total_bytes += len(raw)
        if total_bytes > _MAX_BATCH_BYTES:
            raise ValueError("equity_mapping_collection_batch_too_large")
        capture = {
            "role": role,
            "asset_key": asset_key,
            "source_id": source_id,
            "source_url": source_url,
            "content_type": content_type,
            "raw_scope": "response_body_only",
            "source_event_at": (
                _iso_utc(source_event_at) if source_event_at is not None else None
            ),
            "observed_at": _iso_utc(observed_at),
            "available_at": _iso_utc(available_at),
            "byte_count": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        prepared.append((capture, source_path, raw, source_event_at))

    assets_by_role = {
        role: {asset for candidate_role, asset in keys if candidate_role == role}
        for role in _ASSET_ROLES
    }
    asset_sets = list(assets_by_role.values())
    if not asset_sets or not asset_sets[0] or any(
        assets != asset_sets[0] for assets in asset_sets[1:]
    ):
        raise ValueError("equity_mapping_collection_asset_role_coverage_incomplete")
    if any((role, "GLOBAL") not in keys for role in _GLOBAL_ROLES):
        raise ValueError("equity_mapping_collection_global_role_coverage_incomplete")

    quote_times = [
        source_event_at
        for capture, _, _, source_event_at in prepared
        if capture["role"] in _QUOTE_ROLES and source_event_at is not None
    ]
    quote_skew_seconds = (max(quote_times) - min(quote_times)).total_seconds()
    if quote_skew_seconds > config.maximum_quote_skew_seconds:
        raise ValueError("equity_mapping_collection_cross_leg_skew_exceeded")

    prepared.sort(key=lambda item: (item[0]["asset_key"], item[0]["role"]))
    captures: list[dict[str, Any]] = []
    sources: list[tuple[Path, bytes]] = []
    for index, (capture, source_path, raw, _) in enumerate(prepared):
        stored_filename = (
            f"{index:03d}-{capture['asset_key']}-{capture['role']}"
            f"{_content_suffix(capture['content_type'])}"
        )
        captures.append({**capture, "stored_filename": stored_filename})
        sources.append((source_path, raw))

    batch = {
        "schema_version": EQUITY_MAPPING_COLLECTION_VERSION,
        "dataset_role": dataset_role,
        "synthetic_fixture": dataset_role == "synthetic_fixture",
        "cash_trading_date": cash_trading_date,
        "reference_window_start": _iso_utc(start),
        "decision_time": _iso_utc(decision),
        "maximum_cross_leg_skew_seconds": config.maximum_quote_skew_seconds,
        "actual_cross_leg_skew_seconds": quote_skew_seconds,
        "source_allowlist": sorted(allowlist),
        "asset_keys": sorted(asset_sets[0]),
        "captures": captures,
        "total_byte_count": total_bytes,
    }
    batch_hash = canonical_hash(batch)
    report = {
        "schema_version": EQUITY_MAPPING_COLLECTION_VERSION,
        "artifact_type": "equity_mapping_immutable_raw_collection",
        "created_at": utc_now().isoformat(),
        "batch_hash": batch_hash,
        "batch": batch,
        "capture_count": len(captures),
        "asset_count": len(asset_sets[0]),
        "source_hashes": sorted(capture["sha256"] for capture in captures),
        "verdict": "ready_to_seal_raw_collection",
        "meta": {
            "research_only": True,
            "raw_collection_only": True,
            "market_evidence_present": dataset_role == "point_in_time_forward_collection",
            "future_return_evaluated": False,
            "pnl_evaluated": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
    }
    return report, tuple(sources)


def _verify_existing_bundle(path: Path, expected: Mapping[str, Any]) -> str:
    manifest_path = path / "manifest.json"
    try:
        raw_manifest = manifest_path.read_bytes()
        manifest = json.loads(raw_manifest)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("equity_mapping_collection_existing_manifest_invalid") from exc
    if manifest.get("batch_hash") != expected.get("batch_hash"):
        raise ValueError("equity_mapping_collection_existing_batch_mismatch")
    batch = manifest.get("batch")
    if not isinstance(batch, Mapping):
        raise ValueError("equity_mapping_collection_existing_batch_invalid")
    if canonical_hash(batch) != expected.get("batch_hash"):
        raise ValueError("equity_mapping_collection_existing_batch_hash_invalid")
    captures = batch.get("captures")
    if not isinstance(captures, list):
        raise ValueError("equity_mapping_collection_existing_captures_invalid")
    for capture in captures:
        if not isinstance(capture, Mapping):
            raise ValueError("equity_mapping_collection_existing_capture_invalid")
        stored_filename = str(capture.get("stored_filename", ""))
        if not _SAFE_LABEL.fullmatch(stored_filename):
            raise ValueError("equity_mapping_collection_existing_filename_invalid")
        raw_path = path / "raw" / stored_filename
        if not raw_path.is_file():
            raise ValueError("equity_mapping_collection_existing_raw_missing")
        if hashlib.sha256(raw_path.read_bytes()).hexdigest() != capture["sha256"]:
            raise ValueError("equity_mapping_collection_existing_raw_hash_mismatch")
    return hashlib.sha256(raw_manifest).hexdigest()


def load_verified_equity_mapping_collection_manifest(
    manifest_path: Path,
) -> dict[str, Any]:
    """Read a sealed manifest and verify every raw response by content hash."""

    resolved = manifest_path.expanduser().resolve()
    if resolved.name != "manifest.json":
        raise ValueError("equity_mapping_collection_manifest_filename_invalid")
    try:
        manifest = json.loads(resolved.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("equity_mapping_collection_manifest_invalid") from exc
    if not isinstance(manifest, Mapping):
        raise ValueError("equity_mapping_collection_manifest_not_object")
    if manifest.get("verdict") != "sealed_raw_collection":
        raise ValueError("equity_mapping_collection_manifest_not_sealed")
    manifest_hash = _verify_existing_bundle(resolved.parent, manifest)
    return {
        **manifest,
        "verification": {
            "manifest_sha256": manifest_hash,
            "raw_readback_verified": True,
        },
    }


def seal_equity_mapping_collection_batch(
    payload: Mapping[str, Any],
    *,
    input_base_dir: Path,
    raw_root: Path,
    config: EquityMappingG0Config | None = None,
) -> dict[str, Any]:
    """Seal one batch without overwriting an existing content-addressed bundle."""

    report, sources = build_equity_mapping_collection_batch(
        payload,
        base_dir=input_base_dir,
        config=config,
    )
    date_root = raw_root.expanduser().resolve() / report["batch"]["cash_trading_date"]
    date_root.mkdir(parents=True, exist_ok=True)
    final_path = date_root / report["batch_hash"]
    if final_path.exists():
        manifest_hash = _verify_existing_bundle(final_path, report)
        return {
            **report,
            "bundle_path": str(final_path),
            "manifest_sha256": manifest_hash,
            "idempotent_existing_bundle": True,
            "verdict": "sealed_raw_collection",
        }

    temporary = Path(tempfile.mkdtemp(prefix=".equity-mapping-", dir=date_root))
    try:
        raw_dir = temporary / "raw"
        raw_dir.mkdir()
        for capture, (_, raw) in zip(report["batch"]["captures"], sources):
            target = raw_dir / capture["stored_filename"]
            target.write_bytes(raw)
            if hashlib.sha256(target.read_bytes()).hexdigest() != capture["sha256"]:
                raise OSError("equity_mapping_collection_raw_readback_failed")
        sealed_report = {**report, "verdict": "sealed_raw_collection"}
        manifest_path = temporary / "manifest.json"
        manifest_path.write_text(
            json.dumps(sealed_report, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        try:
            os.replace(temporary, final_path)
        except OSError:
            if not final_path.exists():
                raise
            manifest_hash = _verify_existing_bundle(final_path, report)
        return {
            **sealed_report,
            "bundle_path": str(final_path),
            "manifest_sha256": manifest_hash,
            "idempotent_existing_bundle": False,
        }
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def collection_source_hashes(manifests: Sequence[Mapping[str, Any]]) -> set[str]:
    """Return hashes from verified collection manifests for G0 lineage checks."""

    hashes: set[str] = set()
    for manifest in manifests:
        batch = manifest.get("batch")
        if not isinstance(batch, Mapping):
            raise ValueError("equity_mapping_collection_manifest_batch_invalid")
        if canonical_hash(batch) != manifest.get("batch_hash"):
            raise ValueError("equity_mapping_collection_manifest_hash_invalid")
        captures = batch.get("captures")
        if not isinstance(captures, list):
            raise ValueError("equity_mapping_collection_manifest_captures_invalid")
        for capture in captures:
            if not isinstance(capture, Mapping):
                raise ValueError("equity_mapping_collection_manifest_capture_invalid")
            value = str(capture.get("sha256", ""))
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError("equity_mapping_collection_manifest_source_hash_invalid")
            hashes.add(value)
    return hashes
