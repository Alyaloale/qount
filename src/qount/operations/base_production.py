"""Persistent evidence for the Base standard-production runtime.

The MiniTrend-named shell and venue adapter remain compatibility entrypoints,
but live authority comes from the verified standard decision batch.  This
store makes that migration explicit and retains the first naturally generated
fill attribution independently of rotating forward-run directories.
"""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from qount.certification import ExecutionAttributionReport
from qount.contracts import canonical_hash
from qount.contracts import is_sha256
from qount.contracts import validate_decision_batch
from qount.governance import StrategyRegistry
from qount.ledger import RuntimeLedgerSnapshot
from qount.mini_trend.live_pilot import LIVE_PILOT_CONTRACT
from qount.persistence import VerifiedDecisionBatch
from qount.strategies import BASE_STRATEGY_VERSION


BASE_STANDARD_PRODUCTION_SCHEMA_VERSION = 1
BASE_STANDARD_PRODUCTION_MODE = "standard_production"
BASE_STANDARD_PRODUCTION_CHAIN = (
    "MarketSnapshot",
    "StrategyIntent",
    "allocator",
    "RiskDecision",
    "OrderPlan",
    "RuntimeLedger",
    "reconciliation",
    "ExecutionAttributionReport",
)
_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|secret|password|passphrase|private[_-]?key|"
    r"access[_-]?token|bearer[_-]?token|listen[_-]?key|"
    r"authorization|credential|signature)$",
    re.IGNORECASE,
)


class BaseStandardProductionError(ValueError):
    """Raised when standard-production evidence cannot be proven or stored."""


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            dict(value),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
        + b"\n"
    )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _secure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise BaseStandardProductionError(
            f"base_standard_production_directory_symlink:{path.name}"
        )
    os.chmod(path, 0o700)
    if stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode) != 0o700:
        raise BaseStandardProductionError(
            f"base_standard_production_directory_mode:{path.name}"
        )


def _scan_sensitive(value: Any, *, path: str = "payload") -> None:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key)
            if _SENSITIVE_KEY.search(key):
                hash_value = key.lower().endswith("_hash") and is_sha256(item)
                redacted = item == "[REDACTED]"
                if not hash_value and not redacted:
                    raise BaseStandardProductionError(
                        f"base_standard_production_sensitive_field:{path}.{key}"
                    )
            _scan_sensitive(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _scan_sensitive(item, path=f"{path}[{index}]")


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise BaseStandardProductionError(
            f"base_standard_production_artifact_exists:{path.name}"
        )
    _scan_sensitive(value)
    raw = _canonical_bytes(value)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = -1
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if path.read_bytes() != raw:
        raise BaseStandardProductionError(
            f"base_standard_production_readback_mismatch:{path.name}"
        )
    if stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode) != 0o600:
        raise BaseStandardProductionError(
            f"base_standard_production_file_mode:{path.name}"
        )
    _fsync_directory(path.parent)


def _write_status(path: Path, value: Mapping[str, Any]) -> None:
    _scan_sensitive(value)
    raw = _canonical_bytes(value)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = -1
        os.replace(temporary, path)
        _fsync_directory(path.parent)
        if path.read_bytes() != raw:
            raise BaseStandardProductionError(
                "base_standard_production_status_readback_mismatch"
            )
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise BaseStandardProductionError(
            f"base_standard_production_artifact_invalid:{path.name}"
        )
    if stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode) != 0o600:
        raise BaseStandardProductionError(
            f"base_standard_production_file_mode:{path.name}"
        )
    try:
        value = json.loads(path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BaseStandardProductionError(
            f"base_standard_production_json_invalid:{path.name}"
        ) from exc
    if not isinstance(value, dict):
        raise BaseStandardProductionError(
            f"base_standard_production_object_required:{path.name}"
        )
    return value


def _hash_valid(value: Mapping[str, Any], *, field: str) -> bool:
    core = {key: item for key, item in value.items() if key != field}
    return value.get(field) == canonical_hash(core)


def _standard_authority(
    batch: VerifiedDecisionBatch,
    ledger_snapshot: RuntimeLedgerSnapshot,
    registry: StrategyRegistry,
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    contract_errors = validate_decision_batch(
        batch.snapshot,
        batch.intents,
        batch.target,
        batch.risk,
        batch.plan,
    )
    if contract_errors:
        raise BaseStandardProductionError(
            "base_standard_production_batch_invalid:" + ",".join(contract_errors)
        )
    standard = plan.get("standard_execution")
    if not isinstance(standard, Mapping):
        raise BaseStandardProductionError(
            "base_standard_production_standard_execution_missing"
        )
    entries = tuple(
        entry
        for entry in registry.entries
        if entry.strategy_id == LIVE_PILOT_CONTRACT.strategy
    )
    entry = entries[0] if len(entries) == 1 else None
    reconciliation = ledger_snapshot.reconciliation
    checks = {
        "batch_id": standard.get("batch_id") == batch.manifest.batch_id,
        "manifest_hash": standard.get("manifest_hash") == batch.manifest.manifest_hash,
        "order_plan_id": standard.get("order_plan_id") == batch.plan.order_plan_id,
        "plan_hash": standard.get("plan_hash") == batch.plan.plan_hash,
        "ledger_snapshot_hash": standard.get("pre_dispatch_ledger_snapshot_hash")
        == ledger_snapshot.snapshot_hash,
        "reconciliation_hash": standard.get("pre_dispatch_reconciliation_hash")
        == reconciliation.get("report_hash"),
        "registry_hash": standard.get("registry_hash") == registry.registry_hash,
        "registry_entry": entry is not None,
        "minimal_live": bool(entry and entry.promotion_status == "minimal_live"),
        "owner_authorization": bool(entry and entry.owner_authorization_hash),
        "parity": standard.get("parity_matches") is True
        and not standard.get("parity_differences"),
        "reconciliation": reconciliation.get("passed") is True
        and reconciliation.get("halt_required") is False,
        "ledger_resolved": not ledger_snapshot.unresolved_order_ids,
    }
    failed = tuple(name for name, passed in checks.items() if not passed)
    if failed:
        raise BaseStandardProductionError(
            "base_standard_production_authority_mismatch:" + ",".join(failed)
        )
    return {
        "batch_id": batch.manifest.batch_id,
        "manifest_hash": batch.manifest.manifest_hash,
        "snapshot_id": batch.snapshot.snapshot_id,
        "intent_ids": [intent.decision_id for intent in batch.intents],
        "portfolio_target_id": batch.target.portfolio_target_id,
        "risk_decision_id": batch.risk.risk_decision_id,
        "order_plan_id": batch.plan.order_plan_id,
        "plan_hash": batch.plan.plan_hash,
        "runtime_ledger_snapshot_hash": ledger_snapshot.snapshot_hash,
        "reconciliation_hash": reconciliation["report_hash"],
        "registry_hash": registry.registry_hash,
        "registry_entry_id": entry.registry_entry_id if entry else None,
        "owner_authorization_hash": entry.owner_authorization_hash if entry else None,
        "standard_order_count": len(batch.plan.orders),
        "standard_cancellation_count": len(batch.plan.cancellations),
        "legacy_parity_matches": True,
    }


def _release_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    required = ("git_commit", "version", "source_tree_hash", "provenance_hash")
    if not all(isinstance(value.get(name), str) for name in required):
        raise BaseStandardProductionError(
            "base_standard_production_release_identity_invalid"
        )
    if not re.fullmatch(r"[0-9a-f]{40}", str(value["git_commit"])) or not all(
        is_sha256(value[name]) for name in ("source_tree_hash", "provenance_hash")
    ):
        raise BaseStandardProductionError(
            "base_standard_production_release_identity_invalid"
        )
    return {name: value[name] for name in required}


def _migration_record(
    *,
    observed_at: str,
    authority: Mapping[str, Any],
    release: Mapping[str, Any],
) -> dict[str, Any]:
    core = {
        "schema_version": BASE_STANDARD_PRODUCTION_SCHEMA_VERSION,
        "artifact_type": "base_standard_production_migration",
        "migrated_at": observed_at,
        "runtime_mode": BASE_STANDARD_PRODUCTION_MODE,
        "strategy_id": LIVE_PILOT_CONTRACT.strategy,
        "strategy_version": BASE_STRATEGY_VERSION,
        "authoritative_chain": list(BASE_STANDARD_PRODUCTION_CHAIN),
        "authority": dict(authority),
        "release": dict(release),
        "fixed_scope": {
            "capital_usdt": LIVE_PILOT_CONTRACT.canary_capital_usdt,
            "symbols": list(LIVE_PILOT_CONTRACT.universe),
            "direction": "long_cash",
            "position_mode": "one_way",
            "margin_mode": "isolated",
            "leverage": 1,
            "maximum_gross": 1.0,
        },
        "compatibility": {
            "mini_trend_projection_role": "strategy_intent_input_adapter",
            "mini_trend_dispatch_role": "venue_adapter_with_required_standard_parity",
            "order_authority": "verified_standard_decision_batch_and_registry",
            "legacy_client_order_ids_authoritative": False,
        },
        "claims": {
            "orders_forced_for_sampling": False,
            "permissions_expanded": False,
            "additional_live_sleeves_enabled": False,
        },
    }
    migration_hash = canonical_hash(core)
    return core | {"migration_id": migration_hash, "migration_hash": migration_hash}


def _report(value: Mapping[str, Any]) -> ExecutionAttributionReport:
    try:
        report = ExecutionAttributionReport(**dict(value))
    except TypeError as exc:
        raise BaseStandardProductionError(
            "base_standard_production_attribution_schema_invalid"
        ) from exc
    errors = report.validate()
    if errors or report.attribution_source != "real_fill":
        raise BaseStandardProductionError(
            "base_standard_production_attribution_invalid:"
            + ",".join(errors or ("not_real_fill",))
        )
    return report


def _matching_response(
    responses: Sequence[object], report_id: str
) -> Mapping[str, Any]:
    for raw in responses:
        if not isinstance(raw, Mapping):
            continue
        attribution = raw.get("execution_attribution")
        if isinstance(attribution, Mapping) and attribution.get("report_id") == report_id:
            evidence = raw.get("raw_exchange_evidence")
            if isinstance(evidence, Mapping) and is_sha256(evidence.get("source_hash")):
                return evidence
    raise BaseStandardProductionError(
        "base_standard_production_exchange_evidence_missing"
    )


def _sample_record(
    *,
    observed_at: str,
    authority: Mapping[str, Any],
    report: ExecutionAttributionReport,
    raw_exchange_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    core = {
        "schema_version": BASE_STANDARD_PRODUCTION_SCHEMA_VERSION,
        "artifact_type": "base_natural_fill_attribution_sample",
        "captured_at": observed_at,
        "strategy_id": LIVE_PILOT_CONTRACT.strategy,
        "runtime_mode": BASE_STANDARD_PRODUCTION_MODE,
        "natural_fill": True,
        "forced_for_sampling": False,
        "batch_id": authority["batch_id"],
        "order_plan_id": authority["order_plan_id"],
        "report": dict(report.__dict__),
        "raw_exchange_evidence": dict(raw_exchange_evidence),
    }
    sample_hash = canonical_hash(core)
    return core | {"sample_id": sample_hash, "sample_hash": sample_hash}


def _verified_migration(path: Path) -> dict[str, Any]:
    value = _read_json(path)
    core = {
        key: item
        for key, item in value.items()
        if key not in {"migration_id", "migration_hash"}
    }
    if (
        value.get("artifact_type") != "base_standard_production_migration"
        or value.get("migration_id") != value.get("migration_hash")
        or value.get("migration_hash") != canonical_hash(core)
    ):
        raise BaseStandardProductionError(
            "base_standard_production_migration_hash_invalid"
        )
    return value


def _verified_sample(path: Path) -> dict[str, Any]:
    value = _read_json(path)
    core = {
        key: item
        for key, item in value.items()
        if key not in {"sample_id", "sample_hash"}
    }
    if (
        value.get("artifact_type") != "base_natural_fill_attribution_sample"
        or value.get("sample_id") != value.get("sample_hash")
        or value.get("sample_hash") != canonical_hash(core)
    ):
        raise BaseStandardProductionError(
            "base_standard_production_sample_hash_invalid"
        )
    _report(value.get("report") or {})
    return value


def read_base_standard_production_status(root: str | os.PathLike[str]) -> dict[str, Any]:
    """Read and hash-verify the current machine-readable production status."""

    source = Path(root)
    value = _read_json(source / "status.json")
    if (
        value.get("artifact_type") != "base_standard_production_status"
        or not _hash_valid(value, field="status_hash")
    ):
        raise BaseStandardProductionError(
            "base_standard_production_status_hash_invalid"
        )
    migration = _verified_migration(
        source / "migrations" / f"{value['release']['git_commit']}.json"
    )
    if migration.get("migration_id") != value.get("migration_id"):
        raise BaseStandardProductionError(
            "base_standard_production_status_migration_mismatch"
        )
    first_sample_id = value.get("first_sample_id")
    if first_sample_id is not None:
        sample = _verified_sample(source / "samples" / f"{first_sample_id}.json")
        if sample.get("sample_id") != first_sample_id:
            raise BaseStandardProductionError(
                "base_standard_production_first_sample_mismatch"
            )
    return value


def prepare_base_standard_production_store(
    root: str | os.PathLike[str],
) -> Path:
    """Create and permission-check the observer store before live execution."""

    target = Path(root)
    _secure_directory(target)
    _secure_directory(target / "migrations")
    _secure_directory(target / "samples")
    probe = target / ".write-probe"
    try:
        _write_exclusive(
            probe,
            {
                "schema_version": BASE_STANDARD_PRODUCTION_SCHEMA_VERSION,
                "artifact_type": "base_standard_production_write_probe",
            },
        )
    finally:
        if probe.exists() and not probe.is_symlink():
            probe.unlink()
            _fsync_directory(target)
    return target


def record_base_standard_production_cycle(
    root: str | os.PathLike[str],
    *,
    batch: VerifiedDecisionBatch,
    ledger_snapshot: RuntimeLedgerSnapshot,
    registry: StrategyRegistry,
    plan: Mapping[str, Any],
    dispatch: Mapping[str, Any],
    release_identity: Mapping[str, Any],
    observed_at: str,
) -> dict[str, Any]:
    """Persist one standard Base cycle and any natural real-fill samples."""

    target = prepare_base_standard_production_store(root)
    migrations = target / "migrations"
    samples = target / "samples"
    authority = _standard_authority(batch, ledger_snapshot, registry, plan)
    release = _release_identity(release_identity)
    migration = _migration_record(
        observed_at=observed_at,
        authority=authority,
        release=release,
    )
    migration_path = migrations / f"{release['git_commit']}.json"
    if migration_path.exists():
        existing_migration = _verified_migration(migration_path)
        for name in ("runtime_mode", "strategy_id", "strategy_version", "release"):
            if existing_migration.get(name) != migration.get(name):
                raise BaseStandardProductionError(
                    "base_standard_production_migration_identity_conflict"
                )
        migration = existing_migration
    else:
        _write_exclusive(migration_path, migration)

    raw_reports = dispatch.get("execution_attribution_reports") or ()
    responses = dispatch.get("responses") or ()
    if not isinstance(raw_reports, (list, tuple)) or not isinstance(
        responses, (list, tuple)
    ):
        raise BaseStandardProductionError(
            "base_standard_production_dispatch_evidence_invalid"
        )
    new_sample_ids: list[str] = []
    for raw_report in raw_reports:
        if not isinstance(raw_report, Mapping):
            raise BaseStandardProductionError(
                "base_standard_production_attribution_not_object"
            )
        report = _report(raw_report)
        exchange_evidence = _matching_response(responses, report.report_id)
        sample = _sample_record(
            observed_at=observed_at,
            authority=authority,
            report=report,
            raw_exchange_evidence=exchange_evidence,
        )
        sample_path = samples / f"{sample['sample_id']}.json"
        if sample_path.exists():
            existing = _verified_sample(sample_path)
            if existing != sample:
                raise BaseStandardProductionError(
                    "base_standard_production_sample_identity_conflict"
                )
        else:
            _write_exclusive(sample_path, sample)
        new_sample_ids.append(str(sample["sample_id"]))

    all_samples = tuple(
        _verified_sample(path)
        for path in sorted(samples.glob("*.json"))
        if path.is_file() and not path.is_symlink()
    )
    first_sample = min(
        all_samples,
        key=lambda value: (str(value["captured_at"]), str(value["sample_id"])),
    ) if all_samples else None
    status_core = {
        "schema_version": BASE_STANDARD_PRODUCTION_SCHEMA_VERSION,
        "artifact_type": "base_standard_production_status",
        "updated_at": observed_at,
        "runtime_mode": BASE_STANDARD_PRODUCTION_MODE,
        "strategy_id": LIVE_PILOT_CONTRACT.strategy,
        "strategy_version": BASE_STRATEGY_VERSION,
        "migration_id": migration["migration_id"],
        "release": release,
        "timer": {
            "unit": "qount-mini-trend-live.timer",
            "cadence": "daily_03:20_utc_with_up_to_10m_random_delay",
            "purpose": "natural_base_decision_and_first_fill_capture",
        },
        "first_fill_observation": (
            "captured" if first_sample is not None else "awaiting_natural_fill"
        ),
        "first_sample_id": (
            first_sample["sample_id"] if first_sample is not None else None
        ),
        "sample_count": len(all_samples),
        "new_sample_ids": sorted(set(new_sample_ids)),
        "latest_authority": authority,
        "latest_cycle": {
            "dispatch_status": dispatch.get("status"),
            "exchange_mutation_attempted": bool(
                dispatch.get("exchange_mutation_attempted")
            ),
            "attribution_report_count": len(raw_reports),
            "orders_forced_for_sampling": False,
        },
    }
    status = status_core | {"status_hash": canonical_hash(status_core)}
    _write_status(target / "status.json", status)
    return read_base_standard_production_status(target)


__all__ = [
    "BASE_STANDARD_PRODUCTION_CHAIN",
    "BASE_STANDARD_PRODUCTION_MODE",
    "BASE_STANDARD_PRODUCTION_SCHEMA_VERSION",
    "BaseStandardProductionError",
    "prepare_base_standard_production_store",
    "read_base_standard_production_status",
    "record_base_standard_production_cycle",
]
