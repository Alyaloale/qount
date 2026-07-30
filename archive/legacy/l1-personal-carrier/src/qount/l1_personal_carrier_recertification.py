"""Frozen L1-S2 personal-carrier registration and cache-only evaluation.

The evaluator deliberately lives beside the preregistration rather than in the live
strategy code.  It only reads the pinned cache files, verifies their manifests before
calculating performance, and cannot produce orders or a paper/live eligibility claim.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any, Mapping

from qount.contracts import StrategyIntent
from qount.contracts import canonical_hash
from qount.contracts import is_sha256
from qount.models import utc_now


L1_S2_SOURCE_COMMIT = "ae6caeb2f2e18a55381a97c51dece72c6050d32d"
L1_S2_UNIVERSE = (
    "SPY", "EFA", "EEM", "TLT", "IEF", "LQD", "HYG", "GLD", "SLV", "DBC", "USO", "UUP", "VNQ",
    "IWM", "EWJ", "FXI", "SHY", "EMB", "TIP", "UNG", "DBA",
)

# The declared L1-S2 contract below is a 21-ETF, four-lookback variant.  The
# commit it claimed to re-certify contains only this 13-ETF/default-lookback
# baseline.  Keep the source profile explicit so a content hash cannot be
# mistaken for proof that the declared strategy was the implementation run.
L1_S2_SOURCE_COMMIT_UNIVERSE = (
    "SPY", "EFA", "EEM", "TLT", "IEF", "LQD", "HYG", "GLD", "SLV", "DBC", "USO", "UUP", "VNQ",
)
L1_S2_SOURCE_COMMIT_LOOKBACK_WEEKS = (13, 26, 52)

L1_PERSONAL_CARRIER_EVALUATION_VERSION = "l1_personal_carrier_recertification_v0.1"
L1_PERSONAL_CARRIER_INTENT_VERSION = "l1_personal_carrier_research_intent_v0.1"
L1_PERSONAL_CARRIER_PREREGISTRATION_VERSION = (
    "l1_personal_carrier_recertification_preregistration_v0.1"
)
L1_PERSONAL_CARRIER_IMMEDIATE_PREREGISTRATION_VERSION = (
    "l1_personal_carrier_recertification_preregistration_v0.2"
)
L1_PERSONAL_CARRIER_STRATEGY_ID = "l1_personal_carrier_frozen_s2"
# This must remain SemVer so the frozen signal can use the standard strategy
# registry.  Artifact schema versions intentionally remain separate above.
L1_PERSONAL_CARRIER_STRATEGY_VERSION = "0.1.0"
L1_PERSONAL_CARRIER_IMMEDIATE_STRATEGY_VERSION = "0.1.1"
L1_PERSONAL_CARRIER_TIINGO_CACHE_AUDIT_VERSION = "l1_personal_carrier_tiingo_cache_audit_v0.1"
L1_PERSONAL_CARRIER_TIINGO_PREPARATION_VERSION = "l1_personal_carrier_tiingo_cache_preparation_v0.1"
L1_PERSONAL_CARRIER_RECERTIFICATION_CONSUMPTION_VERSION = (
    "l1_personal_carrier_recertification_consumption_v0.1"
)
_WEEK_SECONDS = 7 * 24 * 60 * 60
_WEEKS_PER_YEAR = 365.25 / 7.0


@dataclass(frozen=True)
class PricePoint:
    """One adjusted close at an observed UTC timestamp."""

    timestamp_ms: int
    value: float


def frozen_l1_s2_signal() -> dict[str, Any]:
    """The final 21-ETF L1-S2 ensemble, without a performance claim."""
    return {
        "family": "l1_tsmom",
        "source_commit": L1_S2_SOURCE_COMMIT,
        "universe": list(L1_S2_UNIVERSE),
        "frequency": "weekly",
        "signal": "equal_weight_mean(sign(trailing_return_lookback_weeks))",
        "lookback_weeks_grid": [13, 26, 39, 52],
        "volatility_lookback_weeks": 26,
        "position_sizing": "inverse_realized_weekly_volatility_then_unit_gross_normalization",
        "holding_period_weeks": 1,
        "rebalance": "weekly",
        "cost_per_side_fraction": 0.0006,
        "n_time_folds": 5,
        "parameter_tuning_allowed": False,
    }


def personal_carrier_source_parity(
    preregistration: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the source-identity check for the quarantined L1-S2 contract.

    A SHA-256 over ``l1_cross_asset.py`` proves the source file was available,
    but it does not prove that a later 21-ETF/four-lookback parameter override
    was the strategy contained in that commit.  The historical source baseline
    is recorded here so callers can fail closed instead of treating the legacy
    artifact as an exact re-certification.
    """

    contract = preregistration.get("contract")
    signal = contract.get("signal") if isinstance(contract, Mapping) else None
    if not isinstance(signal, Mapping):
        raise ValueError("personal_carrier_source_parity_signal_missing")

    declared_universe = signal.get("universe")
    declared_lookbacks = signal.get("lookback_weeks_grid")
    source_universe = list(L1_S2_SOURCE_COMMIT_UNIVERSE)
    source_lookbacks = list(L1_S2_SOURCE_COMMIT_LOOKBACK_WEEKS)
    mismatches: list[str] = []
    if declared_universe != source_universe:
        mismatches.append("universe")
    if declared_lookbacks != source_lookbacks:
        mismatches.append("lookback_weeks_grid")
    return {
        "source_commit": L1_S2_SOURCE_COMMIT,
        "source_strategy": {
            "universe": source_universe,
            "lookback_weeks_grid": source_lookbacks,
            "volatility_lookback_weeks": 26,
            "frequency": "weekly",
            "rebalance": "weekly",
        },
        "declared_strategy": {
            "universe": declared_universe,
            "lookback_weeks_grid": declared_lookbacks,
            "volatility_lookback_weeks": signal.get("volatility_lookback_weeks"),
            "frequency": signal.get("frequency"),
            "rebalance": signal.get("rebalance"),
        },
        "matches": not mismatches,
        "mismatches": mismatches,
    }


def assert_personal_carrier_source_parity(
    preregistration: Mapping[str, Any],
) -> None:
    """Prevent the legacy 21-ETF variant from being treated as source-exact."""

    parity = personal_carrier_source_parity(preregistration)
    if parity["matches"] is not True:
        raise ValueError(
            "personal_carrier_source_strategy_mismatch:" + ",".join(parity["mismatches"])
        )


def build_personal_carrier_preregistration(*, l1_source_sha256: str) -> dict[str, Any]:
    if len(l1_source_sha256) != 64:
        raise ValueError("L1 source SHA-256 must be 64 hex characters")
    signal = frozen_l1_s2_signal()
    contract = {
        "signal": signal,
        "source_integrity": {
            "path": "src/qount/l1_cross_asset.py",
            "commit": L1_S2_SOURCE_COMMIT,
            "sha256": l1_source_sha256,
        },
        "evaluation_only_change": "benchmarks_and_acceptance_gates_only",
        "benchmarks": {
            "sixty_forty": {
                "assets": {"SPY": 0.60, "TLT": 0.40},
                "rebalance": "weekly_at_same_completed_anchor",
                "cost_per_side_fraction": 0.0006,
            },
            "btc_full": {
                "asset": "BTCUSDT",
                "weight": 1.0,
                "rebalance": "buy_and_hold_after_initial_entry",
                "cost_per_side_fraction": 0.0006,
            },
        },
        "metrics": {
            "annual_return": "geometric_CAGR_on_each_common_evaluation_window",
            "max_drawdown": "peak_to_trough_on_compounded_equity_curve",
        },
        "acceptance_gate": {
            "apply_independently_to_each_benchmark": True,
            "strategy_absolute_max_drawdown_at_most_fraction_of_benchmark": 0.5,
            "strategy_annual_return_not_lower_than_benchmark_by_more_than_percentage_points": 2.0,
            "pass_requires_all_benchmarks": True,
        },
        "data_admission": {
            "tiingo": {
                "required_raw_cache": "one pre-existing adjusted-close cache file for every frozen 21-ETF ticker",
                "network_download_allowed": False,
                "manifest_before_results": "record path, SHA-256, first/last date and row count before evaluation",
            },
            "btc": {
                "required_cache": "pre-existing public BTCUSDT daily cache with a recorded source manifest",
                "network_download_allowed": False,
                "manifest_before_results": "record path, SHA-256, first/last date and row count before evaluation",
            },
            "window": "each benchmark uses its own strategy-and-benchmark common completed dates; no date or ticker may be selected from performance",
        },
        "result_controls": {
            "not_before_utc": "2026-07-31T00:00:00+00:00",
            "historical_role": "consumed_discovery_recertification_only",
            "orders_authorized": False,
            "paper_or_live_allowed": False,
            "promotion_evidence": False,
            "failure_disposition": "accept_buy_and_hold_plus_rebalance_as_sleeve_1_terminal_state_without_parameter_rescue",
            "forbidden_after_registration": [
                "change_signal_or_universe",
                "change_costs_or_rebalance_schedule",
                "change_benchmarks_or_acceptance_gates",
                "run_parameter_search",
                "use_results_to_authorize_execution",
            ],
        },
    }
    return {
        "schema_version": L1_PERSONAL_CARRIER_PREREGISTRATION_VERSION,
        "artifact_type": "l1_personal_carrier_recertification_preregistration",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "strategy_results_evaluated": False,
            "orders_authorized": False,
            "paper_or_live_allowed": False,
        },
        "contract": contract,
        "contract_hash": canonical_hash(contract),
    }


def build_personal_carrier_immediate_recertification_preregistration(
    *,
    superseded_preregistration: Mapping[str, Any],
    l1_source_sha256: str,
    authorized_at: datetime,
) -> dict[str, Any]:
    """Create an owner-directed successor without mutating the frozen contract.

    This path is intentionally narrow: it keeps the signal, caches, benchmarks,
    gates, costs, and execution prohibitions byte-for-byte equivalent.  It only
    replaces the future embargo with an explicit owner-directed result window,
    while retaining the superseded contract hash as permanent provenance.
    """

    validate_personal_carrier_preregistration(superseded_preregistration)
    if superseded_preregistration.get("schema_version") != L1_PERSONAL_CARRIER_PREREGISTRATION_VERSION:
        raise ValueError("personal_carrier_supersession_requires_original_preregistration")
    if authorized_at.tzinfo is None:
        raise ValueError("personal_carrier_supersession_authorized_at_timezone_required")
    authorized_at = authorized_at.astimezone(timezone.utc)
    original_contract = superseded_preregistration["contract"]
    original_embargo = _parse_utc_datetime(
        str(original_contract["result_controls"]["not_before_utc"]),
        error_code="personal_carrier_preregistration_embargo_invalid",
    )
    if authorized_at >= original_embargo:
        raise ValueError("personal_carrier_supersession_not_needed_after_original_embargo")
    if l1_source_sha256 != original_contract["source_integrity"]["sha256"]:
        raise ValueError("frozen_l1_source_hash_mismatch")

    # JSON preserves this all-JSON contract while avoiding mutation of the source
    # artifact held as evidence for the original, unconsumed result window.
    contract = json.loads(json.dumps(original_contract))
    contract["result_controls"]["not_before_utc"] = authorized_at.isoformat()
    contract["result_controls"]["historical_role"] = (
        "owner_authorized_immediate_superseding_recertification_only"
    )
    contract["supersession"] = {
        "superseded_preregistration_contract_hash": superseded_preregistration["contract_hash"],
        "original_not_before_utc": original_embargo.isoformat(),
        "owner_directive": "owner_authorized_immediate_recertification",
        "authorized_at": authorized_at.isoformat(),
        "results_read_before_supersession": False,
        "scope": "embargo_timing_only_signal_costs_benchmarks_gates_and_execution_prohibitions_unchanged",
    }
    return {
        "schema_version": L1_PERSONAL_CARRIER_IMMEDIATE_PREREGISTRATION_VERSION,
        "artifact_type": "l1_personal_carrier_recertification_preregistration",
        "created_at": authorized_at.isoformat(),
        "meta": {
            "research_only": True,
            "strategy_results_evaluated": False,
            "orders_authorized": False,
            "paper_or_live_allowed": False,
            "supersedes_frozen_embargo_contract": True,
        },
        "contract": contract,
        "contract_hash": canonical_hash(contract),
    }


def validate_personal_carrier_preregistration(payload: Mapping[str, Any]) -> None:
    contract = payload.get("contract")
    if not isinstance(contract, Mapping):
        raise ValueError("personal-carrier preregistration contract missing")
    meta = payload.get("meta")
    if not isinstance(meta, Mapping) or any(
        meta.get(field) is not expected
        for field, expected in (
            ("research_only", True),
            ("strategy_results_evaluated", False),
            ("orders_authorized", False),
            ("paper_or_live_allowed", False),
        )
    ):
        raise ValueError("personal-carrier preregistration authority invalid")
    if payload.get("contract_hash") != canonical_hash(contract):
        raise ValueError("personal-carrier preregistration contract hash mismatch")
    if contract.get("signal") != frozen_l1_s2_signal():
        raise ValueError("L1-S2 signal is not frozen")
    schema_version = payload.get("schema_version")
    result_controls = contract.get("result_controls")
    if not isinstance(result_controls, Mapping):
        raise ValueError("personal-carrier preregistration result controls missing")
    if schema_version == L1_PERSONAL_CARRIER_PREREGISTRATION_VERSION:
        if result_controls.get("not_before_utc") != "2026-07-31T00:00:00+00:00":
            raise ValueError("personal-carrier preregistration evaluation date changed")
        return
    if schema_version != L1_PERSONAL_CARRIER_IMMEDIATE_PREREGISTRATION_VERSION:
        raise ValueError("personal-carrier preregistration version invalid")
    if meta.get("supersedes_frozen_embargo_contract") is not True:
        raise ValueError("personal_carrier_supersession_authority_invalid")
    supersession = contract.get("supersession")
    if not isinstance(supersession, Mapping):
        raise ValueError("personal_carrier_supersession_missing")
    if (
        not is_sha256(str(supersession.get("superseded_preregistration_contract_hash") or ""))
        or supersession.get("original_not_before_utc") != "2026-07-31T00:00:00+00:00"
        or supersession.get("owner_directive") != "owner_authorized_immediate_recertification"
        or supersession.get("results_read_before_supersession") is not False
        or supersession.get("scope")
        != "embargo_timing_only_signal_costs_benchmarks_gates_and_execution_prohibitions_unchanged"
    ):
        raise ValueError("personal_carrier_supersession_invalid")
    authorized_at = _parse_utc_datetime(
        str(supersession.get("authorized_at") or ""),
        error_code="personal_carrier_supersession_authorized_at_invalid",
    )
    not_before = _parse_utc_datetime(
        str(result_controls.get("not_before_utc") or ""),
        error_code="personal_carrier_preregistration_embargo_invalid",
    )
    if authorized_at != not_before or authorized_at >= datetime(2026, 7, 31, tzinfo=timezone.utc):
        raise ValueError("personal_carrier_supersession_result_window_invalid")
    baseline = build_personal_carrier_preregistration(
        l1_source_sha256=str(contract.get("source_integrity", {}).get("sha256") or "")
    )["contract"]
    for field in ("signal", "source_integrity", "evaluation_only_change", "benchmarks", "metrics", "acceptance_gate", "data_admission"):
        if contract.get(field) != baseline[field]:
            raise ValueError("personal_carrier_supersession_scope_changed")
    expected_controls = dict(baseline["result_controls"])
    expected_controls["not_before_utc"] = authorized_at.isoformat()
    expected_controls["historical_role"] = (
        "owner_authorized_immediate_superseding_recertification_only"
    )
    if result_controls != expected_controls:
        raise ValueError("personal_carrier_supersession_controls_changed")


def personal_carrier_strategy_version(preregistration: Mapping[str, Any]) -> str:
    """Map the frozen and owner-superseded contracts to distinct SemVer entries."""

    validate_personal_carrier_preregistration(preregistration)
    if preregistration["schema_version"] == L1_PERSONAL_CARRIER_PREREGISTRATION_VERSION:
        return L1_PERSONAL_CARRIER_STRATEGY_VERSION
    return L1_PERSONAL_CARRIER_IMMEDIATE_STRATEGY_VERSION


def _parse_utc_datetime(value: str, *, error_code: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise ValueError(error_code) from error
    if parsed.tzinfo is None:
        raise ValueError(error_code)
    return parsed.astimezone(timezone.utc)


def assert_personal_carrier_result_window(
    preregistration: Mapping[str, Any], *, checked_at: datetime | None = None
) -> datetime:
    """Reject result disclosure before the preregistered embargo expires."""

    validate_personal_carrier_preregistration(preregistration)
    now = checked_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("personal_carrier_result_time_timezone_required")
    now = now.astimezone(timezone.utc)
    embargo = _parse_utc_datetime(
        preregistration["contract"]["result_controls"]["not_before_utc"],
        error_code="personal_carrier_preregistration_embargo_invalid",
    )
    if now < embargo:
        raise ValueError(f"evaluation_not_allowed_before:{embargo.isoformat()}")
    return now


def assert_personal_carrier_cache_collection_window(
    preregistration: Mapping[str, Any], *, checked_at: datetime | None = None
) -> datetime:
    """Allow Tiingo cache intake only before the results embargo expires.

    The re-certification evaluator is cache-only.  This separate gate prevents a
    missing cache discovered after result disclosure becomes an excuse to fetch
    fresh data and change the admissible input set.
    """

    validate_personal_carrier_preregistration(preregistration)
    now = checked_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("personal_carrier_cache_collection_time_timezone_required")
    now = now.astimezone(timezone.utc)
    embargo = _parse_utc_datetime(
        preregistration["contract"]["result_controls"]["not_before_utc"],
        error_code="personal_carrier_preregistration_embargo_invalid",
    )
    if now >= embargo:
        raise ValueError(f"cache_collection_not_allowed_on_or_after:{embargo.isoformat()}")
    return now


def _parse_timestamp_ms(value: Any) -> int | None:
    if isinstance(value, (int, float)) and math.isfinite(value) and value > 0:
        raw = int(value)
        return raw if raw >= 100_000_000_000 else raw * 1000
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def _timestamp_iso(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_points(rows: Any, *, timestamp_fields: tuple[str, ...], value_fields: tuple[str, ...]) -> list[PricePoint]:
    if not isinstance(rows, list):
        raise ValueError("price cache must contain a JSON list")
    by_timestamp: dict[int, float] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        timestamp = next((_parse_timestamp_ms(row.get(field)) for field in timestamp_fields if row.get(field) is not None), None)
        raw_value = next((row.get(field) for field in value_fields if row.get(field) is not None), None)
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if timestamp is None or not math.isfinite(value) or value <= 0.0:
            continue
        by_timestamp[timestamp] = value
    return [PricePoint(timestamp_ms=timestamp, value=by_timestamp[timestamp]) for timestamp in sorted(by_timestamp)]


def load_tiingo_adjusted_close_cache(path: str | Path) -> list[PricePoint]:
    """Read a pre-existing Tiingo raw adjusted-close cache without touching the network."""
    cache_path = Path(path)
    try:
        rows = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid_tiingo_cache:{cache_path}") from error
    points = _normalize_points(rows, timestamp_fields=("date",), value_fields=("adjClose",))
    if not points:
        raise ValueError(f"tiingo_cache_has_no_adjusted_closes:{cache_path}")
    return points


def _json_row_count(path: Path) -> int:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid_json_cache:{path}") from error
    if not isinstance(rows, list):
        raise ValueError(f"json_cache_not_a_list:{path}")
    return len(rows)


def load_btc_daily_close_cache(path: str | Path) -> list[PricePoint]:
    """Read a sealed ``date,close`` BTC daily cache.

    The evaluation intentionally accepts a small, explicit CSV surface.  Converting
    exchange archives into this cache is a separate data-preparation step, so a result
    never silently splices or downloads market data.
    """
    cache_path = Path(path)
    try:
        with cache_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ValueError("btc_cache_header_missing")
            fields = {field.strip().lower(): field for field in reader.fieldnames if field}
            timestamp_field = next((fields[name] for name in ("date", "timestamp", "opened_at_utc") if name in fields), None)
            close_field = fields.get("close")
            if timestamp_field is None or close_field is None:
                raise ValueError("btc_cache_requires_date_and_close")
            rows = list(reader)
    except OSError as error:
        raise ValueError(f"invalid_btc_cache:{cache_path}") from error
    points = _normalize_points(rows, timestamp_fields=(timestamp_field,), value_fields=(close_field,))
    if not points:
        raise ValueError(f"btc_cache_has_no_closes:{cache_path}")
    return points


def _csv_row_count(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return sum(1 for _ in csv.DictReader(handle))
    except OSError as error:
        raise ValueError(f"invalid_csv_cache:{path}") from error


def load_btc_source_manifest(path: str | Path, *, btc_cache_path: str | Path) -> dict[str, Any]:
    """Validate the provenance manifest for the sealed BTC daily cache."""
    manifest_path = Path(path)
    cache_path = Path(btc_cache_path)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid_btc_source_manifest:{manifest_path}") from error
    if not isinstance(payload, dict):
        raise ValueError("btc_source_manifest_not_an_object")
    core = {key: value for key, value in payload.items() if key != "manifest_hash"}
    if payload.get("manifest_hash") != canonical_hash(core):
        raise ValueError("btc_source_manifest_hash_invalid")
    cache = payload.get("daily_cache")
    archives = payload.get("source_archives")
    if not isinstance(cache, Mapping) or not isinstance(archives, list) or not archives:
        raise ValueError("btc_source_manifest_incomplete")
    if payload.get("asset") != "BTCUSDT" or payload.get("frequency") != "1d":
        raise ValueError("btc_source_manifest_instrument_invalid")
    if cache.get("sha256") != _sha256_file(cache_path):
        raise ValueError("btc_source_manifest_cache_hash_mismatch")
    return payload


def _cache_manifest_entry(
    *, label: str, path: Path, points: list[PricePoint], parser: str, raw_row_count: int
) -> dict[str, Any]:
    return {
        "label": label,
        "path": str(path.resolve()),
        "sha256": _sha256_file(path),
        "parser": parser,
        "raw_row_count": raw_row_count,
        "normalized_point_count": len(points),
        "first_observation_utc": _timestamp_iso(points[0].timestamp_ms),
        "last_observation_utc": _timestamp_iso(points[-1].timestamp_ms),
    }


def audit_personal_carrier_tiingo_cache(
    *, tiingo_cache_dir: str | Path
) -> dict[str, Any]:
    """Report the frozen Tiingo cache's admission status without evaluating it.

    This intentionally reports only cache integrity and observation coverage.  It
    never derives returns, targets, or performance metrics, so it is safe to run
    before the embargo expires.
    """

    cache_dir = Path(tiingo_cache_dir)
    entries: list[dict[str, Any]] = []
    missing_tickers: list[str] = []
    invalid_caches: list[dict[str, str]] = []
    for ticker in L1_S2_UNIVERSE:
        cache_path = cache_dir / f"tiingo_{ticker}.json"
        if not cache_path.is_file():
            missing_tickers.append(ticker)
            continue
        try:
            points = load_tiingo_adjusted_close_cache(cache_path)
            entries.append(
                _cache_manifest_entry(
                    label=ticker,
                    path=cache_path,
                    points=points,
                    parser="tiingo_raw_json_adjClose_v1",
                    raw_row_count=_json_row_count(cache_path),
                )
            )
        except ValueError as error:
            invalid_caches.append(
                {
                    "ticker": ticker,
                    "path": str(cache_path.resolve()),
                    "error": str(error),
                }
            )
    core = {
        "schema_version": L1_PERSONAL_CARRIER_TIINGO_CACHE_AUDIT_VERSION,
        "artifact_type": "l1_personal_carrier_tiingo_cache_audit",
        "cache_dir": str(cache_dir.resolve()),
        "required_tickers": list(L1_S2_UNIVERSE),
        "tiingo_adjusted_close_caches": entries,
        "missing_tickers": missing_tickers,
        "invalid_caches": invalid_caches,
        "complete": not missing_tickers and not invalid_caches,
        "meta": {
            "research_only": True,
            "strategy_results_evaluated": False,
            "orders_authorized": False,
            "paper_or_live_allowed": False,
        },
    }
    return core | {"cache_audit_hash": canonical_hash(core)}


def _load_complete_personal_carrier_tiingo_cache(
    *, tiingo_cache_dir: str | Path
) -> tuple[list[dict[str, Any]], dict[str, list[PricePoint]]]:
    """Load every required Tiingo file after cache-admission checks succeed."""

    audit = audit_personal_carrier_tiingo_cache(tiingo_cache_dir=tiingo_cache_dir)
    if audit["missing_tickers"]:
        ticker = str(audit["missing_tickers"][0])
        path = Path(tiingo_cache_dir) / f"tiingo_{ticker}.json"
        raise ValueError(f"required_tiingo_cache_missing:{ticker}:{path}")
    if audit["invalid_caches"]:
        error = str(audit["invalid_caches"][0]["error"])
        raise ValueError(error)
    by_ticker = {
        ticker: load_tiingo_adjusted_close_cache(
            Path(tiingo_cache_dir) / f"tiingo_{ticker}.json"
        )
        for ticker in L1_S2_UNIVERSE
    }
    return list(audit["tiingo_adjusted_close_caches"]), by_ticker


def validate_personal_carrier_tiingo_cache_preparation(
    payload: Mapping[str, Any], *, preregistration: Mapping[str, Any]
) -> None:
    """Verify the pre-embargo Tiingo cache-admission artifact.

    This binds the evaluator to the cache set inspected before result disclosure.
    It is evidence of input admission only, never a performance or promotion artifact.
    """

    if not isinstance(payload, Mapping):
        raise ValueError("personal_carrier_tiingo_preparation_not_an_object")
    validate_personal_carrier_preregistration(preregistration)
    if payload.get("schema_version") != L1_PERSONAL_CARRIER_TIINGO_PREPARATION_VERSION:
        raise ValueError("personal_carrier_tiingo_preparation_version_invalid")
    if payload.get("artifact_type") != "l1_personal_carrier_tiingo_cache_preparation":
        raise ValueError("personal_carrier_tiingo_preparation_type_invalid")
    if payload.get("artifact_hash") != canonical_hash(
        {key: value for key, value in payload.items() if key != "artifact_hash"}
    ):
        raise ValueError("personal_carrier_tiingo_preparation_hash_invalid")
    preparation_contract_hash = payload.get("preregistration_contract_hash")
    expected_contract_hash = preregistration["contract_hash"]
    carried_from_superseded_contract = False
    if preparation_contract_hash != expected_contract_hash:
        supersession = preregistration["contract"].get("supersession")
        if (
            preregistration.get("schema_version")
            == L1_PERSONAL_CARRIER_IMMEDIATE_PREREGISTRATION_VERSION
            and isinstance(supersession, Mapping)
            and preparation_contract_hash
            == supersession.get("superseded_preregistration_contract_hash")
        ):
            carried_from_superseded_contract = True
        else:
            raise ValueError("personal_carrier_tiingo_preparation_preregistration_mismatch")
    meta = payload.get("meta")
    if not isinstance(meta, Mapping) or any(
        meta.get(field) is not expected
        for field, expected in (
            ("research_only", True),
            ("strategy_results_evaluated", False),
            ("orders_authorized", False),
            ("paper_or_live_allowed", False),
        )
    ):
        raise ValueError("personal_carrier_tiingo_preparation_authority_invalid")
    prepared_at = _parse_utc_datetime(
        str(payload.get("prepared_at") or ""),
        error_code="personal_carrier_tiingo_preparation_time_invalid",
    )
    preparation_embargo = (
        preregistration["contract"]["supersession"]["original_not_before_utc"]
        if carried_from_superseded_contract
        else preregistration["contract"]["result_controls"]["not_before_utc"]
    )
    embargo = _parse_utc_datetime(
        preparation_embargo,
        error_code="personal_carrier_preregistration_embargo_invalid",
    )
    if prepared_at >= embargo:
        raise ValueError("personal_carrier_tiingo_preparation_after_embargo")
    collection = payload.get("collection")
    if not isinstance(collection, Mapping) or collection.get("existing_cache_files_refreshed") is not False:
        raise ValueError("personal_carrier_tiingo_preparation_collection_invalid")
    audit = payload.get("cache_audit")
    if not isinstance(audit, Mapping):
        raise ValueError("personal_carrier_tiingo_preparation_audit_missing")
    if audit.get("schema_version") != L1_PERSONAL_CARRIER_TIINGO_CACHE_AUDIT_VERSION:
        raise ValueError("personal_carrier_tiingo_preparation_audit_version_invalid")
    if audit.get("artifact_type") != "l1_personal_carrier_tiingo_cache_audit":
        raise ValueError("personal_carrier_tiingo_preparation_audit_type_invalid")
    if audit.get("cache_audit_hash") != canonical_hash(
        {key: value for key, value in audit.items() if key != "cache_audit_hash"}
    ):
        raise ValueError("personal_carrier_tiingo_preparation_audit_hash_invalid")
    if (
        audit.get("required_tickers") != list(L1_S2_UNIVERSE)
        or audit.get("complete") is not True
        or audit.get("missing_tickers") != []
        or audit.get("invalid_caches") != []
        or len(audit.get("tiingo_adjusted_close_caches") or ()) != len(L1_S2_UNIVERSE)
    ):
        raise ValueError("personal_carrier_tiingo_preparation_audit_incomplete")


def assert_personal_carrier_tiingo_preparation_matches_inputs(
    preparation: Mapping[str, Any], *, input_manifest: Mapping[str, Any]
) -> None:
    """Reject cache replacement between pre-embargo admission and evaluation."""

    expected = preparation["cache_audit"]["tiingo_adjusted_close_caches"]
    actual = input_manifest.get("tiingo_adjusted_close_caches")
    if actual != expected:
        raise ValueError("prepared_tiingo_cache_does_not_match_evaluation")


def build_personal_carrier_input_manifest(
    *, tiingo_cache_dir: str | Path, btc_cache_path: str | Path, btc_source_manifest_path: str | Path
) -> tuple[dict[str, Any], dict[str, list[PricePoint]], list[PricePoint]]:
    """Load and hash every preregistered cache before an evaluation begins."""
    entries, by_ticker = _load_complete_personal_carrier_tiingo_cache(
        tiingo_cache_dir=tiingo_cache_dir
    )

    btc_path = Path(btc_cache_path)
    if not btc_path.is_file():
        raise ValueError(f"required_btc_cache_missing:{btc_path}")
    btc_points = load_btc_daily_close_cache(btc_path)
    btc_source_manifest_path = Path(btc_source_manifest_path)
    btc_source_manifest = load_btc_source_manifest(
        btc_source_manifest_path,
        btc_cache_path=btc_path,
    )
    btc_entry = _cache_manifest_entry(
        label="BTCUSDT",
        path=btc_path,
        points=btc_points,
        parser="sealed_btc_daily_csv_date_close_v1",
        raw_row_count=_csv_row_count(btc_path),
    )
    manifest = {
        "schema_version": "l1_personal_carrier_input_manifest_v0.1",
        "network_download_attempted": False,
        "tiingo_adjusted_close_caches": entries,
        "btc_daily_close_cache": btc_entry,
        "btc_daily_close_source_manifest": {
            "path": str(btc_source_manifest_path.resolve()),
            "sha256": _sha256_file(btc_source_manifest_path),
            "manifest_hash": btc_source_manifest["manifest_hash"],
            "source_archive_count": len(btc_source_manifest["source_archives"]),
        },
    }
    return manifest, by_ticker, btc_points


def _asof(points: list[PricePoint], timestamp_ms: int) -> float | None:
    chosen: float | None = None
    for point in points:
        if point.timestamp_ms <= timestamp_ms:
            chosen = point.value
        else:
            break
    return chosen


def _std_sample(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return (sum((value - mean) ** 2 for value in values) / (len(values) - 1)) ** 0.5


def _common_weekly_anchors(by_ticker: Mapping[str, list[PricePoint]]) -> list[int]:
    starts = [points[0].timestamp_ms for points in by_ticker.values() if points]
    ends = [points[-1].timestamp_ms for points in by_ticker.values() if points]
    if len(starts) != len(L1_S2_UNIVERSE) or len(ends) != len(L1_S2_UNIVERSE):
        raise ValueError("l1_s2_universe_cache_incomplete")
    start = max(starts)
    end = min(ends)
    anchors: list[int] = []
    cursor = start
    while cursor + _WEEK_SECONDS * 1000 <= end:
        anchors.append(cursor)
        cursor += _WEEK_SECONDS * 1000
    if len(anchors) <= max(frozen_l1_s2_signal()["lookback_weeks_grid"]):
        raise ValueError("l1_s2_common_window_too_short")
    return anchors


def _frozen_trend_targets(
    by_ticker: Mapping[str, list[PricePoint]], anchors: list[int]
) -> tuple[dict[str, list[float | None]], list[dict[str, float]]]:
    signal = frozen_l1_s2_signal()
    grid = list(signal["lookback_weeks_grid"])
    max_lookback = max(grid)
    vol_lookback = int(signal["volatility_lookback_weeks"])
    prices_at = {
        ticker: [_asof(by_ticker[ticker], anchor) for anchor in anchors]
        for ticker in L1_S2_UNIVERSE
    }
    returns: dict[str, list[float | None]] = {}
    for ticker in L1_S2_UNIVERSE:
        weekly: list[float | None] = []
        for index in range(len(anchors) - 1):
            previous = prices_at[ticker][index]
            current = prices_at[ticker][index + 1]
            weekly.append(current / previous - 1.0 if previous and current and previous > 0.0 else None)
        returns[ticker] = weekly

    targets: list[dict[str, float]] = []
    # The final target is known at the final completed anchor but has no return in
    # this cache yet.  Replays deliberately stop one interval earlier; retaining
    # it here makes the same frozen calculation available for a research intent.
    for index in range(len(anchors)):
        raw_weights: dict[str, float] = {}
        if index >= max_lookback and index >= vol_lookback:
            for ticker in L1_S2_UNIVERSE:
                now = prices_at[ticker][index]
                signs: list[float] = []
                for lookback in grid:
                    then = prices_at[ticker][index - lookback]
                    if now and then and then > 0.0:
                        trailing = now / then - 1.0
                        signs.append(1.0 if trailing > 0.0 else (-1.0 if trailing < 0.0 else 0.0))
                ensemble_signal = sum(signs) / len(signs) if signs else 0.0
                vol_values = [
                    value for value in returns[ticker][index - vol_lookback:index]
                    if value is not None
                ]
                volatility = _std_sample(vol_values)
                if ensemble_signal != 0.0 and volatility > 0.0:
                    raw_weights[ticker] = ensemble_signal / volatility
        gross = sum(abs(weight) for weight in raw_weights.values())
        targets.append({ticker: weight / gross for ticker, weight in raw_weights.items()} if gross > 0.0 else {})
    return returns, targets


def _replay_target_weights(
    *,
    anchors: list[int],
    returns_by_symbol: Mapping[str, list[float | None]],
    targets: list[dict[str, float]],
    cost_per_side_fraction: float,
    start_index: int,
    end_index: int,
) -> list[dict[str, Any]]:
    """Replay the frozen L1 state-free turnover convention over a closed interval."""
    previous_weights: dict[str, float] = {}
    periods: list[dict[str, Any]] = []
    for index in range(start_index, end_index):
        target = targets[index]
        portfolio_return = 0.0
        priced = False
        for symbol, weight in target.items():
            value = returns_by_symbol[symbol][index]
            if value is not None:
                portfolio_return += weight * value
                priced = True
        if not priced and not previous_weights:
            continue
        turnover = sum(
            abs(target.get(symbol, 0.0) - previous_weights.get(symbol, 0.0))
            for symbol in set(target) | set(previous_weights)
        )
        net_return = portfolio_return - cost_per_side_fraction * turnover
        periods.append(
            {
                "start_utc": _timestamp_iso(anchors[index]),
                "end_utc": _timestamp_iso(anchors[index + 1]),
                "net_return": net_return,
                "turnover": turnover,
                "gross_exposure": sum(abs(weight) for weight in target.values()),
            }
        )
        previous_weights = target
    return periods


def _summary(periods: list[dict[str, Any]]) -> dict[str, Any]:
    if not periods:
        raise ValueError("evaluation_window_has_no_completed_periods")
    equity = 1.0
    peak = 1.0
    maximum_drawdown = 0.0
    returns: list[float] = []
    for period in periods:
        value = float(period["net_return"])
        if value <= -1.0:
            raise ValueError("portfolio_return_loses_all_capital")
        equity *= 1.0 + value
        peak = max(peak, equity)
        maximum_drawdown = max(maximum_drawdown, (peak - equity) / peak)
        returns.append(value)
    cagr = equity ** (_WEEKS_PER_YEAR / len(returns)) - 1.0
    mean_turnover = sum(float(period["turnover"]) for period in periods) / len(periods)
    return {
        "first_period_start_utc": periods[0]["start_utc"],
        "last_period_end_utc": periods[-1]["end_utc"],
        "completed_week_count": len(periods),
        "final_equity": equity,
        "geometric_cagr": cagr,
        "max_drawdown_fraction": maximum_drawdown,
        "average_weekly_turnover": mean_turnover,
        "net_return_series_hash": canonical_hash([round(value, 12) for value in returns]),
    }


def _benchmark_interval(
    *, anchors: list[int], start_ms: int, end_ms: int
) -> tuple[int, int]:
    valid = [
        index for index in range(len(anchors) - 1)
        if anchors[index] >= start_ms and anchors[index + 1] <= end_ms
    ]
    if not valid:
        raise ValueError("benchmark_has_no_common_completed_weeks")
    if valid != list(range(valid[0], valid[-1] + 1)):
        raise ValueError("benchmark_common_window_is_not_contiguous")
    return valid[0], valid[-1] + 1


def _benchmark_returns(points: list[PricePoint], anchors: list[int]) -> list[float | None]:
    prices = [_asof(points, anchor) for anchor in anchors]
    return [
        current / previous - 1.0 if previous and current and previous > 0.0 else None
        for previous, current in zip(prices, prices[1:])
    ]


def _comparison(strategy: Mapping[str, Any], benchmark: Mapping[str, Any]) -> dict[str, Any]:
    max_drawdown_limit = float(benchmark["max_drawdown_fraction"]) * 0.5
    return_gap = float(strategy["geometric_cagr"]) - float(benchmark["geometric_cagr"])
    return {
        "strategy_max_drawdown": strategy["max_drawdown_fraction"],
        "benchmark_max_drawdown": benchmark["max_drawdown_fraction"],
        "strategy_max_drawdown_limit": max_drawdown_limit,
        "max_drawdown_pass": float(strategy["max_drawdown_fraction"]) <= max_drawdown_limit,
        "strategy_geometric_cagr": strategy["geometric_cagr"],
        "benchmark_geometric_cagr": benchmark["geometric_cagr"],
        "annual_return_difference_percentage_points": return_gap * 100.0,
        "annual_return_pass": return_gap >= -0.02,
        "pass": (
            float(strategy["max_drawdown_fraction"]) <= max_drawdown_limit
            and return_gap >= -0.02
        ),
    }


def _evaluation_hash(payload: Mapping[str, Any]) -> str:
    return canonical_hash({key: value for key, value in payload.items() if key != "evaluation_hash"})


def validate_personal_carrier_evaluation(
    payload: Mapping[str, Any],
    *,
    preregistration: Mapping[str, Any],
    frozen_source_sha256: str,
) -> None:
    """Validate a sealed result before it is used as research evidence.

    This is an integrity check for research artifacts, not an execution approval.
    It prevents a target builder from accepting an evaluation from another signal,
    cache set, source revision, or an artifact accidentally edited after it ran.
    """

    validate_personal_carrier_preregistration(preregistration)
    if payload.get("schema_version") != L1_PERSONAL_CARRIER_EVALUATION_VERSION:
        raise ValueError("personal_carrier_evaluation_version_invalid")
    if payload.get("artifact_type") != "l1_personal_carrier_recertification_evaluation":
        raise ValueError("personal_carrier_evaluation_type_invalid")
    if payload.get("evaluation_hash") != _evaluation_hash(payload):
        raise ValueError("personal_carrier_evaluation_hash_invalid")
    meta = payload.get("meta")
    if not isinstance(meta, Mapping) or meta.get("research_only") is not True or any(
        meta.get(field) is not False
        for field in (
            "network_download_attempted",
            "orders_authorized",
            "paper_or_live_allowed",
            "promotion_evidence",
        )
    ):
        raise ValueError("personal_carrier_evaluation_authority_invalid")
    if payload.get("preregistration_contract_hash") != preregistration["contract_hash"]:
        raise ValueError("personal_carrier_evaluation_preregistration_mismatch")
    if payload.get("frozen_source_sha256") != frozen_source_sha256:
        raise ValueError("personal_carrier_evaluation_source_mismatch")
    input_manifest = payload.get("input_manifest")
    if not isinstance(input_manifest, Mapping) or payload.get("input_manifest_hash") != canonical_hash(input_manifest):
        raise ValueError("personal_carrier_evaluation_input_manifest_invalid")

    evaluated_at = _parse_utc_datetime(
        str(payload.get("evaluated_at") or ""),
        error_code="personal_carrier_evaluation_time_invalid",
    )
    embargo = _parse_utc_datetime(
        preregistration["contract"]["result_controls"]["not_before_utc"],
        error_code="personal_carrier_preregistration_embargo_invalid",
    )
    if evaluated_at < embargo:
        raise ValueError("personal_carrier_evaluation_before_embargo")

    benchmarks = payload.get("benchmarks")
    if not isinstance(benchmarks, Mapping) or set(benchmarks) != {"sixty_forty", "btc_full"}:
        raise ValueError("personal_carrier_evaluation_benchmarks_invalid")
    benchmark_passes: list[bool] = []
    for benchmark_id, result in benchmarks.items():
        if not isinstance(result, Mapping) or result.get("benchmark_id") != benchmark_id:
            raise ValueError("personal_carrier_evaluation_benchmark_invalid")
        gate = result.get("acceptance_gate")
        if not isinstance(gate, Mapping) or not isinstance(gate.get("pass"), bool):
            raise ValueError("personal_carrier_evaluation_gate_invalid")
        benchmark_passes.append(gate["pass"])

    acceptance_gate = payload.get("acceptance_gate")
    if not isinstance(acceptance_gate, Mapping):
        raise ValueError("personal_carrier_evaluation_acceptance_invalid")
    all_pass = all(benchmark_passes)
    if acceptance_gate.get("pass_requires_all_benchmarks") is not True:
        raise ValueError("personal_carrier_evaluation_gate_rule_invalid")
    if acceptance_gate.get("all_benchmarks_pass") is not all_pass:
        raise ValueError("personal_carrier_evaluation_gate_mismatch")
    expected_decision = (
        "research_pass_not_promotion"
        if all_pass else "accept_buy_and_hold_plus_rebalance_as_sleeve_1_terminal_state"
    )
    if acceptance_gate.get("decision") != expected_decision:
        raise ValueError("personal_carrier_evaluation_decision_invalid")


def _write_json_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    """Write one research receipt without relying on hard links.

    The WSL data root can be ExFAT/DrvFS, where the repository's immutable
    hard-link writer is not available.  ``O_EXCL`` still gives this small
    consumption ledger its required no-overwrite property on that filesystem.
    """

    raw = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise ValueError(f"personal_carrier_consumption_artifact_exists:{path.name}") from error
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            parent_descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(parent_descriptor)
            finally:
                os.close(parent_descriptor)
        except OSError:
            # ExFAT/DrvFS does not consistently implement directory fsync.
            pass
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _read_json_object(path: Path, *, error_code: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(error_code) from error
    if not isinstance(payload, dict):
        raise ValueError(error_code)
    return payload


def _consumption_core(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in {"receipt_hash", "completion_hash"}}


def _personal_carrier_recertification_consumption_path(
    *, state_dir: str | Path, preregistration: Mapping[str, Any]
) -> Path:
    """Return the fixed consumption path without creating it."""

    validate_personal_carrier_preregistration(preregistration)
    return (
        Path(state_dir).expanduser()
        / "research_runs"
        / "l1-personal-carrier-recertification-consumption"
        / str(preregistration["contract_hash"])
    )


def assert_personal_carrier_recertification_claim(
    *,
    state_dir: str | Path,
    preregistration: Mapping[str, Any],
    tiingo_cache_preparation: Mapping[str, Any],
    frozen_source_sha256: str,
) -> Path:
    """Require an active, verified one-shot claim before market inputs are read."""

    validate_personal_carrier_preregistration(preregistration)
    validate_personal_carrier_tiingo_cache_preparation(
        tiingo_cache_preparation,
        preregistration=preregistration,
    )
    directory = _personal_carrier_recertification_consumption_path(
        state_dir=state_dir,
        preregistration=preregistration,
    )
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("personal_carrier_consumption_claim_missing")
    completion_path = directory / "completion.json"
    if completion_path.exists():
        raise ValueError("personal_carrier_consumption_already_completed")
    attempt_path = directory / "attempt.json"
    if attempt_path.is_symlink() or not attempt_path.is_file():
        raise ValueError("personal_carrier_consumption_claim_missing")
    attempt = _read_json_object(
        attempt_path,
        error_code="personal_carrier_consumption_attempt_invalid",
    )
    if attempt.get("receipt_hash") != canonical_hash(_consumption_core(attempt)):
        raise ValueError("personal_carrier_consumption_attempt_hash_invalid")
    if (
        attempt.get("schema_version") != L1_PERSONAL_CARRIER_RECERTIFICATION_CONSUMPTION_VERSION
        or attempt.get("artifact_type") != "l1_personal_carrier_recertification_consumption"
        or attempt.get("status") != "started"
        or attempt.get("preregistration_contract_hash") != preregistration["contract_hash"]
        or attempt.get("tiingo_cache_preparation_hash")
        != tiingo_cache_preparation["artifact_hash"]
        or attempt.get("frozen_source_sha256") != frozen_source_sha256
    ):
        raise ValueError("personal_carrier_consumption_claim_mismatch")
    return directory


def personal_carrier_recertification_consumption_dir(
    *, state_dir: str | Path, preregistration: Mapping[str, Any]
) -> Path:
    """Return the one-shot ledger directory for one preregistered contract."""

    validate_personal_carrier_preregistration(preregistration)
    directory = _personal_carrier_recertification_consumption_path(
        state_dir=state_dir,
        preregistration=preregistration,
    )
    directory.mkdir(parents=True, exist_ok=True)
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("personal_carrier_consumption_directory_invalid")
    try:
        os.chmod(directory, 0o700)
    except OSError:
        # DrvFS may not expose POSIX modes; its O_EXCL publication still applies.
        pass
    return directory


def claim_personal_carrier_recertification(
    *,
    state_dir: str | Path,
    preregistration: Mapping[str, Any],
    tiingo_cache_preparation: Mapping[str, Any],
    frozen_source_sha256: str,
    claimed_at: datetime | None = None,
) -> dict[str, Any]:
    """Claim the historical result window exactly once.

    A ``started`` receipt is intentionally permanent.  If a process dies after
    claiming but before publishing the evaluation, a second run cannot become a
    hidden second look at the same result; the receipt requires manual research
    governance review instead.
    """

    validate_personal_carrier_preregistration(preregistration)
    assert_personal_carrier_source_parity(preregistration)
    now = assert_personal_carrier_result_window(preregistration, checked_at=claimed_at)
    validate_personal_carrier_tiingo_cache_preparation(
        tiingo_cache_preparation,
        preregistration=preregistration,
    )
    if frozen_source_sha256 != preregistration["contract"]["source_integrity"]["sha256"]:
        raise ValueError("frozen_l1_source_hash_mismatch")
    directory = personal_carrier_recertification_consumption_dir(
        state_dir=state_dir,
        preregistration=preregistration,
    )
    attempt_path = directory / "attempt.json"
    completion_path = directory / "completion.json"
    preparation_hash = str(tiingo_cache_preparation["artifact_hash"])

    if completion_path.exists():
        completion = _read_json_object(
            completion_path,
            error_code="personal_carrier_consumption_completion_invalid",
        )
        if (
            completion.get("schema_version")
            != L1_PERSONAL_CARRIER_RECERTIFICATION_CONSUMPTION_VERSION
            or completion.get("artifact_type")
            != "l1_personal_carrier_recertification_consumption"
            or completion.get("status") != "completed"
        ):
            raise ValueError("personal_carrier_consumption_completion_invalid")
        if completion.get("completion_hash") != canonical_hash(_consumption_core(completion)):
            raise ValueError("personal_carrier_consumption_completion_hash_invalid")
        if completion.get("preregistration_contract_hash") != preregistration["contract_hash"]:
            raise ValueError("personal_carrier_consumption_contract_mismatch")
        if completion.get("tiingo_cache_preparation_hash") != preparation_hash:
            raise ValueError("personal_carrier_consumption_preparation_mismatch")
        if not attempt_path.is_file():
            raise ValueError("personal_carrier_consumption_attempt_missing")
        attempt = _read_json_object(
            attempt_path,
            error_code="personal_carrier_consumption_attempt_invalid",
        )
        if attempt.get("receipt_hash") != canonical_hash(_consumption_core(attempt)):
            raise ValueError("personal_carrier_consumption_attempt_hash_invalid")
        if (
            attempt.get("schema_version")
            != L1_PERSONAL_CARRIER_RECERTIFICATION_CONSUMPTION_VERSION
            or attempt.get("artifact_type")
            != "l1_personal_carrier_recertification_consumption"
            or attempt.get("status") != "started"
            or attempt.get("frozen_source_sha256") != frozen_source_sha256
        ):
            raise ValueError("personal_carrier_consumption_attempt_invalid")
        if completion.get("attempt_receipt_hash") != attempt.get("receipt_hash"):
            raise ValueError("personal_carrier_consumption_attempt_mismatch")
        evaluation_path = directory / "evaluation.json"
        evaluation = _read_json_object(
            evaluation_path,
            error_code="personal_carrier_consumption_evaluation_missing",
        )
        if completion.get("evaluation_hash") != evaluation.get("evaluation_hash"):
            raise ValueError("personal_carrier_consumption_evaluation_hash_mismatch")
        if completion.get("evaluation_file_sha256") != _sha256_file(evaluation_path):
            raise ValueError("personal_carrier_consumption_evaluation_file_hash_mismatch")
        if evaluation.get("tiingo_cache_preparation_hash") != preparation_hash:
            raise ValueError("personal_carrier_consumption_evaluation_preparation_mismatch")
        validate_personal_carrier_evaluation(
            evaluation,
            preregistration=preregistration,
            frozen_source_sha256=frozen_source_sha256,
        )
        return {
            "status": "completed",
            "directory": directory,
            "evaluation_path": evaluation_path,
            "evaluation": evaluation,
        }

    if attempt_path.exists():
        attempt = _read_json_object(
            attempt_path,
            error_code="personal_carrier_consumption_attempt_invalid",
        )
        if attempt.get("receipt_hash") != canonical_hash(_consumption_core(attempt)):
            raise ValueError("personal_carrier_consumption_attempt_hash_invalid")
        if (
            attempt.get("schema_version")
            != L1_PERSONAL_CARRIER_RECERTIFICATION_CONSUMPTION_VERSION
            or attempt.get("artifact_type")
            != "l1_personal_carrier_recertification_consumption"
            or attempt.get("status") != "started"
        ):
            raise ValueError("personal_carrier_consumption_attempt_invalid")
        if attempt.get("preregistration_contract_hash") != preregistration["contract_hash"]:
            raise ValueError("personal_carrier_consumption_contract_mismatch")
        if (
            attempt.get("tiingo_cache_preparation_hash") != preparation_hash
            or attempt.get("frozen_source_sha256") != frozen_source_sha256
        ):
            raise ValueError("personal_carrier_consumption_preparation_mismatch")
        raise ValueError(
            "personal_carrier_recertification_already_started_without_terminal_artifact"
        )

    core = {
        "schema_version": L1_PERSONAL_CARRIER_RECERTIFICATION_CONSUMPTION_VERSION,
        "artifact_type": "l1_personal_carrier_recertification_consumption",
        "status": "started",
        "claimed_at": now.isoformat(),
        "preregistration_contract_hash": preregistration["contract_hash"],
        "tiingo_cache_preparation_hash": preparation_hash,
        "frozen_source_sha256": frozen_source_sha256,
        "meta": {
            "research_only": True,
            "network_download_attempted": False,
            "orders_authorized": False,
            "paper_or_live_allowed": False,
            "promotion_evidence": False,
        },
    }
    _write_json_exclusive(attempt_path, core | {"receipt_hash": canonical_hash(core)})
    return {"status": "claimed", "directory": directory, "attempt_path": attempt_path}


def complete_personal_carrier_recertification(
    *,
    state_dir: str | Path,
    preregistration: Mapping[str, Any],
    tiingo_cache_preparation: Mapping[str, Any],
    frozen_source_sha256: str,
    evaluation: Mapping[str, Any],
    completed_at: datetime | None = None,
) -> dict[str, Any]:
    """Publish the evaluation and its terminal receipt without replacement."""

    assert_personal_carrier_source_parity(preregistration)
    validate_personal_carrier_tiingo_cache_preparation(
        tiingo_cache_preparation,
        preregistration=preregistration,
    )
    validate_personal_carrier_evaluation(
        evaluation,
        preregistration=preregistration,
        frozen_source_sha256=frozen_source_sha256,
    )
    directory = personal_carrier_recertification_consumption_dir(
        state_dir=state_dir,
        preregistration=preregistration,
    )
    attempt_path = directory / "attempt.json"
    if not attempt_path.is_file():
        raise ValueError("personal_carrier_consumption_attempt_missing")
    attempt = _read_json_object(
        attempt_path,
        error_code="personal_carrier_consumption_attempt_invalid",
    )
    if attempt.get("receipt_hash") != canonical_hash(_consumption_core(attempt)):
        raise ValueError("personal_carrier_consumption_attempt_hash_invalid")
    preparation_hash = str(tiingo_cache_preparation["artifact_hash"])
    if (
        attempt.get("schema_version")
        != L1_PERSONAL_CARRIER_RECERTIFICATION_CONSUMPTION_VERSION
        or attempt.get("artifact_type")
        != "l1_personal_carrier_recertification_consumption"
        or attempt.get("status") != "started"
        or attempt.get("preregistration_contract_hash") != preregistration["contract_hash"]
        or attempt.get("tiingo_cache_preparation_hash") != preparation_hash
        or attempt.get("frozen_source_sha256") != frozen_source_sha256
    ):
        raise ValueError("personal_carrier_consumption_preparation_mismatch")
    if evaluation.get("tiingo_cache_preparation_hash") != preparation_hash:
        raise ValueError("personal_carrier_consumption_evaluation_preparation_mismatch")
    resolved_completed_at = completed_at or datetime.now(timezone.utc)
    if resolved_completed_at.tzinfo is None:
        raise ValueError("personal_carrier_consumption_completion_time_timezone_required")
    evaluation_path = directory / "evaluation.json"
    _write_json_exclusive(evaluation_path, evaluation)
    core = {
        "schema_version": L1_PERSONAL_CARRIER_RECERTIFICATION_CONSUMPTION_VERSION,
        "artifact_type": "l1_personal_carrier_recertification_consumption",
        "status": "completed",
        "completed_at": resolved_completed_at.astimezone(timezone.utc).isoformat(),
        "preregistration_contract_hash": preregistration["contract_hash"],
        "tiingo_cache_preparation_hash": preparation_hash,
        "attempt_receipt_hash": attempt["receipt_hash"],
        "evaluation_hash": evaluation["evaluation_hash"],
        "evaluation_file_sha256": _sha256_file(evaluation_path),
        "meta": {
            "research_only": True,
            "network_download_attempted": False,
            "orders_authorized": False,
            "paper_or_live_allowed": False,
            "promotion_evidence": False,
        },
    }
    try:
        _write_json_exclusive(
            directory / "completion.json",
            core | {"completion_hash": canonical_hash(core)},
        )
    except ValueError:
        # Never replace a terminal receipt; leave the original evidence intact.
        raise
    return {"status": "completed", "directory": directory, "evaluation_path": evaluation_path}


def _serialize_strategy_intent(intent: StrategyIntent) -> dict[str, Any]:
    return {
        "schema_version": intent.schema_version,
        "strategy_id": intent.strategy_id,
        "strategy_version": intent.strategy_version,
        "decision_id": intent.decision_id,
        "snapshot_id": intent.snapshot_id,
        "decision_time": intent.decision_time,
        "data_cutoff": intent.data_cutoff,
        "target_weights": dict(intent.target_weights),
        "expected_holding_bars": intent.expected_holding_bars,
        "target_stress_loss_fraction": intent.target_stress_loss_fraction,
        "reason_codes": list(intent.reason_codes),
        "evidence_hash": intent.evidence_hash,
        "state_hash": intent.state_hash,
        "intent_hash": intent.intent_hash,
    }


def _venue_capability_readiness(venue_capability: Mapping[str, Any] | None) -> dict[str, Any]:
    if venue_capability is None:
        return {
            "supplied": False,
            "venue_id": None,
            "approved_for_research": False,
            "supports_all_l1_instruments": False,
            "supports_long_positions": False,
            "supports_short_positions": False,
            "capability_evidence_hash": None,
            "short_capability_verified": False,
        }
    if not isinstance(venue_capability, Mapping):
        raise ValueError("venue_capability_invalid")
    venue_id = venue_capability.get("venue_id")
    if not isinstance(venue_id, str) or not venue_id.strip():
        raise ValueError("venue_capability_venue_id_invalid")
    capability_evidence_hash = venue_capability.get("capability_evidence_hash")
    flags = {
        field: venue_capability.get(field)
        for field in (
            "approved_for_research",
            "supports_all_l1_instruments",
            "supports_long_positions",
            "supports_short_positions",
        )
    }
    if any(not isinstance(value, bool) for value in flags.values()):
        raise ValueError("venue_capability_flags_invalid")
    if any(flags.values()) and not is_sha256(str(capability_evidence_hash or "")):
        raise ValueError("venue_capability_evidence_hash_invalid")
    short_capability_verified = bool(
        all(flags.values()) and is_sha256(str(capability_evidence_hash or ""))
    )
    return {
        "supplied": True,
        "venue_id": venue_id.strip(),
        **flags,
        "capability_evidence_hash": capability_evidence_hash,
        "short_capability_verified": short_capability_verified,
    }


def _make_intent_artifact(payload: dict[str, Any]) -> dict[str, Any]:
    payload["intent_artifact_hash"] = canonical_hash(payload)
    return payload


def build_personal_carrier_research_intent(
    *,
    preregistration: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    frozen_source_sha256: str,
    tiingo_cache_dir: str | Path | None = None,
    btc_cache_path: str | Path | None = None,
    btc_source_manifest_path: str | Path | None = None,
    venue_capability: Mapping[str, Any] | None = None,
    decision_time: datetime | None = None,
    built_at: datetime | None = None,
) -> dict[str, Any]:
    """Build the frozen weekly research target without creating an order pathway.

    A failed re-certification never creates a replacement trend signal.  A passing
    re-certification can create a signed ``StrategyIntent`` for research review only;
    its deliberately conservative stress loss and permanent authorization blockers
    keep it outside the runtime and order-planning paths.
    """

    assert_personal_carrier_source_parity(preregistration)
    assert_personal_carrier_result_window(preregistration, checked_at=built_at)
    validate_personal_carrier_evaluation(
        evaluation,
        preregistration=preregistration,
        frozen_source_sha256=frozen_source_sha256,
    )
    evaluation_hash = str(evaluation["evaluation_hash"])
    if evaluation["acceptance_gate"]["all_benchmarks_pass"] is not True:
        return _make_intent_artifact(
            {
                "schema_version": L1_PERSONAL_CARRIER_INTENT_VERSION,
                "artifact_type": "l1_personal_carrier_research_intent",
                "status": "terminal_passive_fallback",
                "meta": {
                    "research_only": True,
                    "orders_authorized": False,
                    "paper_or_live_allowed": False,
                    "promotion_evidence": False,
                },
                "preregistration_contract_hash": preregistration["contract_hash"],
                "evaluation_hash": evaluation_hash,
                "execution_blockers": [
                    "RECERTIFICATION_NOT_PASSED",
                    "ORDERS_NOT_AUTHORIZED",
                    "PAPER_OR_LIVE_NOT_AUTHORIZED",
                ],
                "passive_fallback": {
                    "disposition": preregistration["contract"]["result_controls"]["failure_disposition"],
                    "timing_rule": "none",
                    "required_next_record": "separate long-only strategic allocation and rebalance policy",
                },
                "strategy_intent": None,
            }
        )

    if tiingo_cache_dir is None or btc_cache_path is None or btc_source_manifest_path is None:
        raise ValueError("sealed_input_paths_required_after_recertification_pass")
    input_manifest, by_ticker, _ = build_personal_carrier_input_manifest(
        tiingo_cache_dir=tiingo_cache_dir,
        btc_cache_path=btc_cache_path,
        btc_source_manifest_path=btc_source_manifest_path,
    )
    input_manifest_hash = canonical_hash(input_manifest)
    if input_manifest_hash != evaluation["input_manifest_hash"]:
        raise ValueError("sealed_inputs_do_not_match_evaluation")
    anchors = _common_weekly_anchors(by_ticker)
    _, targets = _frozen_trend_targets(by_ticker, anchors)
    current_target = targets[-1]
    if not current_target:
        raise ValueError("frozen_l1_s2_current_target_empty")
    current_gross = sum(abs(weight) for weight in current_target.values())
    if not math.isclose(current_gross, 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("frozen_l1_s2_current_target_gross_invalid")

    resolved_decision_time = decision_time or datetime.now(timezone.utc)
    if resolved_decision_time.tzinfo is None:
        raise ValueError("research_intent_decision_time_timezone_required")
    resolved_decision_time = resolved_decision_time.astimezone(timezone.utc)
    data_cutoff = _timestamp_iso(anchors[-1])
    if resolved_decision_time < _parse_utc_datetime(
        data_cutoff,
        error_code="research_intent_data_cutoff_invalid",
    ):
        raise ValueError("research_intent_decision_before_data_cutoff")

    contains_short_target = any(weight < 0.0 for weight in current_target.values())
    venue = _venue_capability_readiness(venue_capability)
    target_state = {
        "signal": frozen_l1_s2_signal(),
        "input_manifest_hash": input_manifest_hash,
        "data_cutoff": data_cutoff,
        "target_weights": current_target,
    }
    strategy_intent = StrategyIntent.create(
        strategy_id=L1_PERSONAL_CARRIER_STRATEGY_ID,
        strategy_version=personal_carrier_strategy_version(preregistration),
        snapshot_id=input_manifest_hash,
        decision_time=resolved_decision_time.isoformat(),
        data_cutoff=data_cutoff,
        target_weights=current_target,
        expected_holding_bars=1,
        # No stress model has been certified for this carrier.  One represents an
        # unknown full-loss bound and prevents this research intent from receiving
        # an operational risk allocation by accident.
        target_stress_loss_fraction=1.0,
        reason_codes=(
            "L1_RECERTIFICATION_PASSED",
            "L1_FROZEN_WEEKLY_TARGET",
            "L1_SHORT_CAPABILITY_REQUIRED",
            "L1_ORDERS_UNAUTHORIZED",
            "L1_RISK_MODEL_UNCERTIFIED",
        ),
        evidence_hash=evaluation_hash,
        state_hash=canonical_hash(target_state),
    )
    blockers = [
        "ORDERS_NOT_AUTHORIZED",
        "PAPER_OR_LIVE_NOT_AUTHORIZED",
        "PROMOTION_REQUIRES_PIT_DATA_CERTIFIED_COSTS_VENUE_AND_NEW_TIME_EVIDENCE_OWNER_AUTHORIZATION",
    ]
    if not venue["short_capability_verified"]:
        blockers.insert(0, "VENUE_SHORT_CAPABILITY_UNVERIFIED")
    return _make_intent_artifact(
        {
            "schema_version": L1_PERSONAL_CARRIER_INTENT_VERSION,
            "artifact_type": "l1_personal_carrier_research_intent",
            "status": (
                "blocked_venue_short_capability"
                if not venue["short_capability_verified"]
                else "research_target_ready_execution_still_blocked"
            ),
            "meta": {
                "research_only": True,
                "orders_authorized": False,
                "paper_or_live_allowed": False,
                "promotion_evidence": False,
            },
            "preregistration_contract_hash": preregistration["contract_hash"],
            "evaluation_hash": evaluation_hash,
            "input_manifest_hash": input_manifest_hash,
            "data_cutoff": data_cutoff,
            "requires_short_capability": True,
            "contains_short_target": contains_short_target,
            "venue_capability": venue,
            "execution_blockers": blockers,
            "strategy_intent": _serialize_strategy_intent(strategy_intent),
        }
    )


def evaluate_personal_carrier_recertification(
    *,
    preregistration: Mapping[str, Any],
    tiingo_cache_dir: str | Path,
    btc_cache_path: str | Path,
    btc_source_manifest_path: str | Path,
    frozen_source_sha256: str,
    tiingo_cache_preparation: Mapping[str, Any],
    state_dir: str | Path,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate the frozen long-horizon trend sleeve against its two fixed baselines.

    ``evaluated_at`` exists for deterministic tests.  The CLI always uses the current
    UTC time, so it cannot bypass the preregistration's result embargo.
    """
    assert_personal_carrier_source_parity(preregistration)
    contract = preregistration["contract"]
    expected_source_hash = contract["source_integrity"]["sha256"]
    if frozen_source_sha256 != expected_source_hash:
        raise ValueError("frozen_l1_source_hash_mismatch")
    now = assert_personal_carrier_result_window(preregistration, checked_at=evaluated_at)
    assert_personal_carrier_recertification_claim(
        state_dir=state_dir,
        preregistration=preregistration,
        tiingo_cache_preparation=tiingo_cache_preparation,
        frozen_source_sha256=frozen_source_sha256,
    )

    input_manifest, by_ticker, btc_points = build_personal_carrier_input_manifest(
        tiingo_cache_dir=tiingo_cache_dir,
        btc_cache_path=btc_cache_path,
        btc_source_manifest_path=btc_source_manifest_path,
    )
    assert_personal_carrier_tiingo_preparation_matches_inputs(
        tiingo_cache_preparation,
        input_manifest=input_manifest,
    )
    anchors = _common_weekly_anchors(by_ticker)
    trend_returns, trend_targets = _frozen_trend_targets(by_ticker, anchors)
    first_strategy_index = next(
        (index for index, target in enumerate(trend_targets) if target),
        None,
    )
    if first_strategy_index is None:
        raise ValueError("frozen_l1_s2_signal_never_produced_a_target")
    cost = float(contract["signal"]["cost_per_side_fraction"])

    def evaluate_against(
        *, benchmark_id: str, benchmark_returns_by_symbol: Mapping[str, list[float | None]],
        benchmark_targets: list[dict[str, float]], benchmark_points: list[PricePoint],
    ) -> dict[str, Any]:
        start_index, end_index = _benchmark_interval(
            anchors=anchors,
            start_ms=benchmark_points[0].timestamp_ms,
            end_ms=benchmark_points[-1].timestamp_ms,
        )
        start_index = max(start_index, first_strategy_index)
        if start_index >= end_index:
            raise ValueError("strategy_and_benchmark_have_no_common_completed_weeks")
        strategy_periods = _replay_target_weights(
            anchors=anchors,
            returns_by_symbol=trend_returns,
            targets=trend_targets,
            cost_per_side_fraction=cost,
            start_index=start_index,
            end_index=end_index,
        )
        benchmark_periods = _replay_target_weights(
            anchors=anchors,
            returns_by_symbol=benchmark_returns_by_symbol,
            targets=benchmark_targets,
            cost_per_side_fraction=cost,
            start_index=start_index,
            end_index=end_index,
        )
        strategy_summary = _summary(strategy_periods)
        benchmark_summary = _summary(benchmark_periods)
        return {
            "benchmark_id": benchmark_id,
            "evaluation_window": {
                "first_anchor_utc": _timestamp_iso(anchors[start_index]),
                "last_completed_anchor_utc": _timestamp_iso(anchors[end_index]),
            },
            "strategy": strategy_summary,
            "benchmark": benchmark_summary,
            "acceptance_gate": _comparison(strategy_summary, benchmark_summary),
        }

    sixty_forty_returns = {ticker: trend_returns[ticker] for ticker in ("SPY", "TLT")}
    sixty_forty_targets = [{"SPY": 0.60, "TLT": 0.40} for _ in range(len(anchors) - 1)]
    sixty_forty_points = [
        PricePoint(
            timestamp_ms=max(by_ticker["SPY"][0].timestamp_ms, by_ticker["TLT"][0].timestamp_ms),
            value=1.0,
        ),
        PricePoint(
            timestamp_ms=min(by_ticker["SPY"][-1].timestamp_ms, by_ticker["TLT"][-1].timestamp_ms),
            value=1.0,
        ),
    ]
    btc_returns = _benchmark_returns(btc_points, anchors)
    btc_targets = [{"BTCUSDT": 1.0} for _ in range(len(anchors) - 1)]

    benchmark_results = {
        "sixty_forty": evaluate_against(
            benchmark_id="sixty_forty",
            benchmark_returns_by_symbol=sixty_forty_returns,
            benchmark_targets=sixty_forty_targets,
            benchmark_points=sixty_forty_points,
        ),
        "btc_full": evaluate_against(
            benchmark_id="btc_full",
            benchmark_returns_by_symbol={"BTCUSDT": btc_returns},
            benchmark_targets=btc_targets,
            benchmark_points=btc_points,
        ),
    }
    all_pass = all(result["acceptance_gate"]["pass"] for result in benchmark_results.values())
    result = {
        "schema_version": L1_PERSONAL_CARRIER_EVALUATION_VERSION,
        "artifact_type": "l1_personal_carrier_recertification_evaluation",
        "evaluated_at": now.astimezone(timezone.utc).isoformat(),
        "meta": {
            "research_only": True,
            "network_download_attempted": False,
            "orders_authorized": False,
            "paper_or_live_allowed": False,
            "promotion_evidence": False,
        },
        "preregistration_contract_hash": preregistration["contract_hash"],
        "frozen_source_sha256": frozen_source_sha256,
        "input_manifest": input_manifest,
        "input_manifest_hash": canonical_hash(input_manifest),
        "replay_method": {
            "signal": "frozen_l1_s2_weekly_ensemble",
            "target_weight_turnover": "same state-free target-weight convention as frozen L1 source",
            "terminal_liquidation_cost": "not charged; all windows end after their final completed weekly return",
        },
        "anchor_count": len(anchors),
        "benchmarks": benchmark_results,
        "acceptance_gate": {
            "pass_requires_all_benchmarks": True,
            "all_benchmarks_pass": all_pass,
            "decision": (
                "research_pass_not_promotion"
                if all_pass else "accept_buy_and_hold_plus_rebalance_as_sleeve_1_terminal_state"
            ),
        },
    }
    result["tiingo_cache_preparation_hash"] = tiingo_cache_preparation["artifact_hash"]
    result["evaluation_hash"] = _evaluation_hash(result)
    return result
