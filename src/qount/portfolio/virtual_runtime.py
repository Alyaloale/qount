"""Standard multi-sleeve runtime executed against a deterministic virtual venue."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import stat
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from qount.contracts import MarketSnapshot
from qount.contracts import StrategyIntent
from qount.contracts import canonical_hash
from qount.execution import build_portfolio_order_plan
from qount.ledger import RuntimeLedger
from qount.ledger import RuntimeLedgerSnapshot
from qount.ledger import build_runtime_ledger_snapshot
from qount.ledger import reconcile_three_way
from qount.persistence import VerifiedDecisionBatch
from qount.persistence import build_decision_batch_manifest
from qount.persistence import publish_decision_batch
from qount.persistence import read_decision_batch
from qount.portfolio.allocator import allocate_strategy_intents
from qount.portfolio.allocator import portfolio_target_from_allocation
from qount.portfolio.models import NavAttribution
from qount.portfolio.models import SleeveRiskBudget
from qount.risk import build_portfolio_risk_decision


VIRTUAL_RUNTIME_SCHEMA_VERSION = 1
VIRTUAL_RUNTIME_EVIDENCE_CLASS = "research_sandbox_virtual_integration"


class MultiSleeveVirtualRuntimeError(ValueError):
    """Raised when a virtual runtime input or accounting result is invalid."""


class MultiSleeveVirtualArtifactError(MultiSleeveVirtualRuntimeError):
    """Raised when a persisted virtual runtime bundle cannot be verified."""


class MultiSleeveVirtualArtifactIncompleteError(MultiSleeveVirtualArtifactError):
    """Raised when the manifest-last completion marker is absent."""


@dataclass(frozen=True)
class VirtualExecutionCostModel:
    model_version: str
    taker_fee_rate: float
    slippage_bps: float
    funding_multiplier: float
    model_hash: str

    @classmethod
    def create(
        cls,
        *,
        model_version: str,
        taker_fee_rate: float,
        slippage_bps: float,
        funding_multiplier: float = 1.0,
    ) -> "VirtualExecutionCostModel":
        core = {
            "model_version": model_version,
            "taker_fee_rate": taker_fee_rate,
            "slippage_bps": slippage_bps,
            "funding_multiplier": funding_multiplier,
        }
        model = cls(**core, model_hash=canonical_hash(core))
        errors = model.validate()
        if errors:
            raise MultiSleeveVirtualRuntimeError(
                "virtual_cost_model_invalid:" + ",".join(errors)
            )
        return model

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.model_version:
            errors.append("model_version_empty")
        for name in ("taker_fee_rate", "slippage_bps", "funding_multiplier"):
            try:
                value = float(getattr(self, name))
            except (TypeError, ValueError):
                value = math.nan
            if not math.isfinite(value) or value < 0.0:
                errors.append(f"{name}_invalid")
        if self.taker_fee_rate > 0.1:
            errors.append("taker_fee_rate_implausible")
        if self.slippage_bps > 10_000.0:
            errors.append("slippage_bps_implausible")
        core = {
            "model_version": self.model_version,
            "taker_fee_rate": self.taker_fee_rate,
            "slippage_bps": self.slippage_bps,
            "funding_multiplier": self.funding_multiplier,
        }
        if self.model_hash != canonical_hash(core):
            errors.append("model_hash_invalid")
        return tuple(errors)


@dataclass(frozen=True)
class VerifiedMultiSleeveVirtualArtifact:
    directory: Path
    batch: VerifiedDecisionBatch
    ledger_snapshot: RuntimeLedgerSnapshot
    virtual_execution: Mapping[str, Any]
    sleeve_nav: Mapping[str, Any]
    result: Mapping[str, Any]
    manifest: Mapping[str, Any]


def _time(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise MultiSleeveVirtualRuntimeError("virtual_runtime_time_invalid") from exc
    if parsed.tzinfo is None:
        raise MultiSleeveVirtualRuntimeError("virtual_runtime_time_naive")
    return parsed.astimezone(dt.timezone.utc)


def _at(start: dt.datetime, seconds: int) -> str:
    return (start + dt.timedelta(seconds=seconds)).isoformat()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii") + b"\n"


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_once(path: Path, value: Any) -> None:
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
        raise MultiSleeveVirtualArtifactError(
            f"virtual_artifact_readback_mismatch:{path.name}"
        )
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise MultiSleeveVirtualArtifactError(
            f"virtual_artifact_file_mode_invalid:{path.name}"
        )


def _payload_envelope(
    artifact_type: str,
    payload: Mapping[str, Any] | Sequence[Any],
) -> dict[str, Any]:
    payload_hash = canonical_hash({"payload": payload})
    core = {
        "schema_version": VIRTUAL_RUNTIME_SCHEMA_VERSION,
        "artifact_type": artifact_type,
        "object_id": canonical_hash(
            {"artifact_type": artifact_type, "payload_hash": payload_hash}
        ),
        "payload": payload,
        "payload_hash": payload_hash,
    }
    return core | {"artifact_hash": canonical_hash(core)}


def _verify_payload_envelope(
    value: object,
    *,
    artifact_type: str,
) -> Mapping[str, Any] | Sequence[Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version",
        "artifact_type",
        "object_id",
        "payload",
        "payload_hash",
        "artifact_hash",
    }:
        raise MultiSleeveVirtualArtifactError(
            f"virtual_artifact_envelope_invalid:{artifact_type}"
        )
    if (
        value.get("schema_version") != VIRTUAL_RUNTIME_SCHEMA_VERSION
        or value.get("artifact_type") != artifact_type
    ):
        raise MultiSleeveVirtualArtifactError(
            f"virtual_artifact_envelope_identity_invalid:{artifact_type}"
        )
    payload = value.get("payload")
    payload_hash = canonical_hash({"payload": payload})
    core = {key: item for key, item in value.items() if key != "artifact_hash"}
    if (
        value.get("payload_hash") != payload_hash
        or value.get("object_id")
        != canonical_hash(
            {"artifact_type": artifact_type, "payload_hash": payload_hash}
        )
        or value.get("artifact_hash") != canonical_hash(core)
    ):
        raise MultiSleeveVirtualArtifactError(
            f"virtual_artifact_envelope_hash_invalid:{artifact_type}"
        )
    return payload


def _snapshot_payload(snapshot: RuntimeLedgerSnapshot) -> dict[str, Any]:
    return {
        "schema_version": snapshot.schema_version,
        "batch_id": snapshot.batch_id,
        "manifest_hash": snapshot.manifest_hash,
        "order_plan_id": snapshot.order_plan_id,
        "plan_hash": snapshot.plan_hash,
        "captured_at": snapshot.captured_at,
        "source_updated_at": snapshot.source_updated_at,
        "positions": dict(snapshot.positions),
        "position_details": [dict(row) for row in snapshot.position_details],
        "orders": [dict(row) for row in snapshot.orders],
        "order_events": [dict(row) for row in snapshot.order_events],
        "fills": [dict(row) for row in snapshot.fills],
        "cash_events": [dict(row) for row in snapshot.cash_events],
        "recoveries": [dict(row) for row in snapshot.recoveries],
        "open_order_ids": list(snapshot.open_order_ids),
        "unresolved_order_ids": list(snapshot.unresolved_order_ids),
        "account": dict(snapshot.account),
        "nav_history": [dict(row) for row in snapshot.nav_history],
        "nav": dict(snapshot.nav),
        "reconciliation": dict(snapshot.reconciliation),
        "audit_last_hash": snapshot.audit_last_hash,
        "audit_row_count": snapshot.audit_row_count,
        "snapshot_hash": snapshot.snapshot_hash,
    }


def _snapshot_from_payload(payload: Mapping[str, Any]) -> RuntimeLedgerSnapshot:
    snapshot = RuntimeLedgerSnapshot(
        schema_version=int(payload["schema_version"]),
        batch_id=str(payload["batch_id"]),
        manifest_hash=str(payload["manifest_hash"]),
        order_plan_id=str(payload["order_plan_id"]),
        plan_hash=str(payload["plan_hash"]),
        captured_at=str(payload["captured_at"]),
        source_updated_at=str(payload["source_updated_at"]),
        positions=dict(payload["positions"]),
        position_details=tuple(dict(row) for row in payload["position_details"]),
        orders=tuple(dict(row) for row in payload["orders"]),
        order_events=tuple(dict(row) for row in payload["order_events"]),
        fills=tuple(dict(row) for row in payload["fills"]),
        cash_events=tuple(dict(row) for row in payload["cash_events"]),
        recoveries=tuple(dict(row) for row in payload["recoveries"]),
        open_order_ids=tuple(payload["open_order_ids"]),
        unresolved_order_ids=tuple(payload["unresolved_order_ids"]),
        account=dict(payload["account"]),
        nav_history=tuple(dict(row) for row in payload["nav_history"]),
        nav=dict(payload["nav"]),
        reconciliation=dict(payload["reconciliation"]),
        audit_last_hash=str(payload["audit_last_hash"]),
        audit_row_count=int(payload["audit_row_count"]),
        snapshot_hash=str(payload["snapshot_hash"]),
    )
    snapshot.validate()
    return snapshot


def _audit_rows(path: Path) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    with path.open(encoding="ascii") as handle:
        for line in handle:
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, Mapping):
                    raise MultiSleeveVirtualRuntimeError(
                        "virtual_runtime_audit_row_invalid"
                    )
                rows.append(dict(value))
    return rows


def _verify_audit_rows(
    rows: Sequence[object],
    *,
    expected_count: int,
    expected_last_hash: str,
) -> None:
    expected_fields = {
        "schema_version",
        "sequence",
        "event_id",
        "event_type",
        "entity_type",
        "entity_id",
        "occurred_at",
        "payload",
        "previous_hash",
        "row_hash",
    }
    if len(rows) != expected_count:
        raise MultiSleeveVirtualArtifactError(
            "virtual_artifact_audit_count_mismatch"
        )
    previous_hash = "0" * 64
    previous_time: dt.datetime | None = None
    event_ids: set[str] = set()
    for sequence, raw_row in enumerate(rows, start=1):
        if not isinstance(raw_row, Mapping) or set(raw_row) != expected_fields:
            raise MultiSleeveVirtualArtifactError(
                f"virtual_artifact_audit_row_invalid:{sequence}"
            )
        row = dict(raw_row)
        if row.get("schema_version") != 1 or row.get("sequence") != sequence:
            raise MultiSleeveVirtualArtifactError(
                f"virtual_artifact_audit_sequence_invalid:{sequence}"
            )
        if row.get("previous_hash") != previous_hash:
            raise MultiSleeveVirtualArtifactError(
                f"virtual_artifact_audit_chain_invalid:{sequence}"
            )
        row_core = {key: value for key, value in row.items() if key != "row_hash"}
        if row.get("row_hash") != canonical_hash(row_core):
            raise MultiSleeveVirtualArtifactError(
                f"virtual_artifact_audit_row_hash_invalid:{sequence}"
            )
        event_id = row.get("event_id")
        if not isinstance(event_id, str) or event_id in event_ids:
            raise MultiSleeveVirtualArtifactError(
                f"virtual_artifact_audit_event_id_invalid:{sequence}"
            )
        occurred_at = _time(str(row.get("occurred_at")))
        if previous_time is not None and occurred_at < previous_time:
            raise MultiSleeveVirtualArtifactError(
                f"virtual_artifact_audit_time_regression:{sequence}"
            )
        event_ids.add(event_id)
        previous_hash = str(row["row_hash"])
        previous_time = occurred_at
    if previous_hash != expected_last_hash:
        raise MultiSleeveVirtualArtifactError(
            "virtual_artifact_audit_last_hash_mismatch"
        )


def _member_references(directory: Path) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path == directory / "manifest.json":
            continue
        raw = path.read_bytes()
        references.append(
            {
                "path": path.relative_to(directory).as_posix(),
                "size_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return references


def _publish_bundle(
    directory: Path,
    *,
    batch: VerifiedDecisionBatch,
    ledger_snapshot: RuntimeLedgerSnapshot,
    audit_rows: Sequence[Mapping[str, Any]],
    virtual_execution: Mapping[str, Any],
    sleeve_nav: Mapping[str, Any],
    result: Mapping[str, Any],
) -> VerifiedMultiSleeveVirtualArtifact:
    if directory.exists():
        raise MultiSleeveVirtualArtifactError(
            "virtual_artifact_directory_already_exists"
        )
    if directory.name != batch.manifest.batch_id:
        raise MultiSleeveVirtualArtifactError(
            "virtual_artifact_directory_batch_id_mismatch"
        )
    directory.parent.mkdir(parents=True, exist_ok=True)
    directory.mkdir(mode=0o700)
    os.chmod(directory, 0o700)
    _fsync_directory(directory.parent)
    decision_root = directory / "decision_batch"
    decision_root.mkdir(mode=0o700)
    os.chmod(decision_root, 0o700)
    publish_decision_batch(
        decision_root / batch.manifest.batch_id,
        snapshot=batch.snapshot,
        intents=batch.intents,
        target=batch.target,
        risk=batch.risk,
        plan=batch.plan,
        created_at=batch.manifest.created_at,
    )
    payloads = {
        "runtime_snapshot.json": _payload_envelope(
            "runtime_ledger_snapshot", _snapshot_payload(ledger_snapshot)
        ),
        "runtime_audit.json": _payload_envelope(
            "runtime_audit_journal", list(audit_rows)
        ),
        "virtual_execution.json": _payload_envelope(
            "virtual_execution", virtual_execution
        ),
        "sleeve_nav.json": _payload_envelope("sleeve_nav", sleeve_nav),
        "result.json": _payload_envelope("virtual_runtime_result", result),
    }
    for file_name, payload in payloads.items():
        _write_once(directory / file_name, payload)
    member_files = _member_references(directory)
    manifest_core = {
        "schema_version": VIRTUAL_RUNTIME_SCHEMA_VERSION,
        "artifact_type": "multi_sleeve_virtual_runtime_bundle",
        "run_id": batch.manifest.batch_id,
        "batch_id": batch.manifest.batch_id,
        "created_at": result["completed_at"],
        "decision_batch_manifest_hash": batch.manifest.manifest_hash,
        "runtime_snapshot_hash": ledger_snapshot.snapshot_hash,
        "result_hash": result["result_hash"],
        "orders_authorized": False,
        "orders_routed": False,
        "member_files": member_files,
    }
    manifest = manifest_core | {"manifest_hash": canonical_hash(manifest_core)}
    _write_once(directory / "manifest.json", manifest)
    _fsync_directory(directory)
    return read_multi_sleeve_virtual_artifact(directory)


def read_multi_sleeve_virtual_artifact(
    directory: str | os.PathLike[str],
) -> VerifiedMultiSleeveVirtualArtifact:
    source = Path(directory)
    if source.is_symlink() or not source.is_dir():
        raise MultiSleeveVirtualArtifactError("virtual_artifact_directory_invalid")
    if stat.S_IMODE(source.stat().st_mode) != 0o700:
        raise MultiSleeveVirtualArtifactError(
            "virtual_artifact_directory_mode_invalid"
        )
    manifest_path = source / "manifest.json"
    if not manifest_path.is_file():
        raise MultiSleeveVirtualArtifactIncompleteError(
            "virtual_artifact_manifest_missing"
        )
    if stat.S_IMODE(manifest_path.stat().st_mode) != 0o600:
        raise MultiSleeveVirtualArtifactError(
            "virtual_artifact_manifest_mode_invalid"
        )
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    if not isinstance(manifest, Mapping) or set(manifest) != {
        "schema_version",
        "artifact_type",
        "run_id",
        "batch_id",
        "created_at",
        "decision_batch_manifest_hash",
        "runtime_snapshot_hash",
        "result_hash",
        "orders_authorized",
        "orders_routed",
        "member_files",
        "manifest_hash",
    }:
        raise MultiSleeveVirtualArtifactError("virtual_artifact_manifest_invalid")
    manifest_core = {
        key: value for key, value in manifest.items() if key != "manifest_hash"
    }
    if manifest.get("manifest_hash") != canonical_hash(manifest_core):
        raise MultiSleeveVirtualArtifactError(
            "virtual_artifact_manifest_hash_invalid"
        )
    if (
        source.name != manifest.get("batch_id")
        or manifest.get("run_id") != manifest.get("batch_id")
        or manifest.get("orders_authorized") is not False
        or manifest.get("orders_routed") is not False
    ):
        raise MultiSleeveVirtualArtifactError(
            "virtual_artifact_manifest_authority_or_identity_invalid"
        )
    expected_references = manifest.get("member_files")
    if not isinstance(expected_references, list):
        raise MultiSleeveVirtualArtifactError(
            "virtual_artifact_manifest_members_invalid"
        )
    actual_references = _member_references(source)
    if actual_references != expected_references:
        raise MultiSleeveVirtualArtifactError(
            "virtual_artifact_member_hash_or_set_mismatch"
        )
    for path in source.rglob("*"):
        if path.is_symlink():
            raise MultiSleeveVirtualArtifactError(
                "virtual_artifact_symlink_forbidden"
            )
        expected_mode = 0o700 if path.is_dir() else 0o600
        if stat.S_IMODE(path.stat().st_mode) != expected_mode:
            raise MultiSleeveVirtualArtifactError(
                f"virtual_artifact_member_mode_invalid:{path.name}"
            )

    batch = read_decision_batch(
        source / "decision_batch" / str(manifest["batch_id"])
    )

    def read_payload(file_name: str, artifact_type: str) -> Any:
        value = json.loads((source / file_name).read_text(encoding="ascii"))
        return _verify_payload_envelope(value, artifact_type=artifact_type)

    snapshot_payload = read_payload(
        "runtime_snapshot.json", "runtime_ledger_snapshot"
    )
    if not isinstance(snapshot_payload, Mapping):
        raise MultiSleeveVirtualArtifactError(
            "virtual_artifact_runtime_snapshot_payload_invalid"
        )
    ledger_snapshot = _snapshot_from_payload(snapshot_payload)
    audit_payload = read_payload("runtime_audit.json", "runtime_audit_journal")
    virtual_execution = read_payload("virtual_execution.json", "virtual_execution")
    sleeve_nav = read_payload("sleeve_nav.json", "sleeve_nav")
    result = read_payload("result.json", "virtual_runtime_result")
    if not isinstance(audit_payload, list):
        raise MultiSleeveVirtualArtifactError(
            "virtual_artifact_audit_payload_invalid"
        )
    _verify_audit_rows(
        audit_payload,
        expected_count=ledger_snapshot.audit_row_count,
        expected_last_hash=ledger_snapshot.audit_last_hash,
    )
    if not all(isinstance(value, Mapping) for value in (virtual_execution, sleeve_nav, result)):
        raise MultiSleeveVirtualArtifactError(
            "virtual_artifact_payload_type_invalid"
        )
    if (
        batch.manifest.manifest_hash != manifest["decision_batch_manifest_hash"]
        or ledger_snapshot.snapshot_hash != manifest["runtime_snapshot_hash"]
        or result.get("result_hash") != manifest["result_hash"]
        or result.get("orders_authorized") is not False
        or result.get("orders_routed") is not False
        or result.get("reconciliation_passed") is not True
        or result.get("accounting_passed") is not True
    ):
        raise MultiSleeveVirtualArtifactError(
            "virtual_artifact_result_linkage_invalid"
        )
    result_core = {key: value for key, value in result.items() if key != "result_hash"}
    if result.get("result_hash") != canonical_hash(result_core):
        raise MultiSleeveVirtualArtifactError(
            "virtual_artifact_result_hash_invalid"
        )
    return VerifiedMultiSleeveVirtualArtifact(
        directory=source,
        batch=batch,
        ledger_snapshot=ledger_snapshot,
        virtual_execution=virtual_execution,
        sleeve_nav=sleeve_nav,
        result=result,
        manifest=manifest,
    )


def run_multi_sleeve_virtual_runtime(
    output_directory: str | os.PathLike[str],
    *,
    snapshot: MarketSnapshot,
    intents: Sequence[StrategyIntent],
    budgets: Sequence[SleeveRiskBudget],
    opening_cash_usdt: float,
    current_positions: Mapping[str, float],
    symbol_rules: Mapping[str, Mapping[str, float]],
    cost_model: VirtualExecutionCostModel,
    allowed_strategy_ids: Sequence[str],
    maximum_weight_by_symbol: Mapping[str, float] | None = None,
    maximum_portfolio_gross: float = 1.0,
) -> VerifiedMultiSleeveVirtualArtifact:
    """Run a complete standard decision and accounting chain locally."""

    if cost_model.validate():
        raise MultiSleeveVirtualRuntimeError("virtual_cost_model_invalid")
    try:
        cash = float(opening_cash_usdt)
    except (TypeError, ValueError) as exc:
        raise MultiSleeveVirtualRuntimeError(
            "virtual_opening_cash_invalid"
        ) from exc
    if not math.isfinite(cash) or cash < 0.0:
        raise MultiSleeveVirtualRuntimeError("virtual_opening_cash_invalid")
    positions = {str(symbol): float(quantity) for symbol, quantity in current_positions.items()}
    symbols = sorted(set(positions) | {symbol for intent in intents for symbol in intent.target_weights})
    opening_equity = cash
    for symbol, quantity in positions.items():
        if not math.isfinite(quantity) or quantity < 0.0 or symbol not in snapshot.prices:
            raise MultiSleeveVirtualRuntimeError(
                f"virtual_opening_position_invalid:{symbol}"
            )
        opening_equity += quantity * float(snapshot.prices[symbol])
    if opening_equity <= 0.0:
        raise MultiSleeveVirtualRuntimeError("virtual_opening_equity_invalid")

    minimum_notionals = {
        symbol: float((symbol_rules.get(symbol) or {}).get("minimum_notional", 0.0))
        for symbol in symbols
    }
    allocation = allocate_strategy_intents(
        intents,
        budgets,
        account_equity_usdt=opening_equity,
        allowed_strategy_ids=allowed_strategy_ids,
        minimum_notional_by_symbol=minimum_notionals,
        maximum_weight_by_symbol=maximum_weight_by_symbol,
        maximum_portfolio_gross=maximum_portfolio_gross,
    )
    target = portfolio_target_from_allocation(intents, allocation)
    risk = build_portfolio_risk_decision(
        snapshot,
        target,
        current_positions=positions,
        account_equity_usdt=opening_equity,
        maximum_portfolio_gross=maximum_portfolio_gross,
        maximum_weight_by_symbol=maximum_weight_by_symbol,
        risk_source_hashes={
            "cost_model": cost_model.model_hash,
            "symbol_rules": canonical_hash({"symbol_rules": symbol_rules}),
        },
    )
    plan = build_portfolio_order_plan(
        snapshot,
        target,
        risk,
        current_positions=positions,
        account_equity_usdt=opening_equity,
        symbol_rules=symbol_rules,
    )
    if not target.allocatable or not risk.approved or not plan.executable:
        blockers = tuple(target.blockers) + tuple(risk.violations) + tuple(plan.blockers)
        raise MultiSleeveVirtualRuntimeError(
            "virtual_runtime_decision_blocked:" + ",".join(blockers or ("unknown",))
        )
    manifest = build_decision_batch_manifest(
        snapshot=snapshot,
        intents=intents,
        target=target,
        risk=risk,
        plan=plan,
        created_at=plan.created_at,
    )
    batch = VerifiedDecisionBatch(
        manifest=manifest,
        snapshot=snapshot,
        intents=tuple(intents),
        target=target,
        risk=risk,
        plan=plan,
    )

    start = _time(snapshot.decision_time)
    with tempfile.TemporaryDirectory(prefix="qount-virtual-runtime-") as temporary:
        temporary_root = Path(temporary)
        ledger = RuntimeLedger(
            temporary_root / "runtime.sqlite3",
            audit_path=temporary_root / "runtime.audit.jsonl",
        )
        ledger.record_verified_batch(batch, recorded_at=snapshot.decision_time)
        for symbol in symbols:
            quantity = positions.get(symbol, 0.0)
            source_hash = canonical_hash(
                {
                    "event": "virtual_opening_position",
                    "symbol": symbol,
                    "quantity": quantity,
                    "price": snapshot.prices[symbol],
                }
            )
            ledger.record_position_snapshot(
                symbol=symbol,
                quantity=quantity,
                average_cost=float(snapshot.prices[symbol]) if quantity > 0.0 else 0.0,
                realized_trading_pnl=0.0,
                occurred_at=snapshot.decision_time,
                source_hash=source_hash,
            )

        cursor = 0
        virtual_cash = cash
        trading_pnl = 0.0
        total_fees = 0.0
        executions: list[dict[str, Any]] = []
        for order in plan.orders:
            quantity = float(order.quantity or 0.0)
            reference_price = float(snapshot.prices[order.symbol])
            slippage_fraction = cost_model.slippage_bps / 10_000.0
            fill_price = reference_price * (
                1.0 + slippage_fraction
                if order.side == "buy"
                else 1.0 - slippage_fraction
            )
            fee = quantity * fill_price * cost_model.taker_fee_rate
            exchange_order_id = f"virtual-{order.client_order_id}"
            cursor += 1
            submitted_at = _at(start, cursor)
            submit_hash = canonical_hash(
                {
                    "event": "virtual_submit",
                    "client_order_id": order.client_order_id,
                    "cost_model_hash": cost_model.model_hash,
                }
            )
            ledger.transition_order(
                order.client_order_id,
                "SUBMITTING",
                event_at=submitted_at,
                source_hash=submit_hash,
            )
            cursor += 1
            acknowledged_at = _at(start, cursor)
            ack_hash = canonical_hash(
                {
                    "event": "virtual_ack",
                    "client_order_id": order.client_order_id,
                    "exchange_order_id": exchange_order_id,
                }
            )
            ledger.transition_order(
                order.client_order_id,
                "ACKNOWLEDGED",
                event_at=acknowledged_at,
                source_hash=ack_hash,
                exchange_order_id=exchange_order_id,
                reason="deterministic_virtual_ack",
            )
            cursor += 1
            filled_at = _at(start, cursor)
            fill_hash = canonical_hash(
                {
                    "event": "virtual_fill",
                    "client_order_id": order.client_order_id,
                    "quantity": quantity,
                    "price": fill_price,
                    "fee": fee,
                    "cost_model_hash": cost_model.model_hash,
                }
            )
            ledger.transition_order(
                order.client_order_id,
                "FILLED",
                event_at=filled_at,
                source_hash=fill_hash,
                exchange_order_id=exchange_order_id,
                executed_quantity=quantity,
                average_price=fill_price,
                reason="deterministic_virtual_fill",
            )
            ledger.record_fill(
                client_order_id=order.client_order_id,
                exchange_trade_id=f"trade-{order.client_order_id}",
                quantity=quantity,
                price=fill_price,
                fee=fee,
                fee_asset="USDT",
                occurred_at=filled_at,
                source_hash=fill_hash,
            )
            signed_notional = quantity * fill_price
            if order.side == "buy":
                virtual_cash -= signed_notional + fee
                trading_pnl += quantity * (reference_price - fill_price)
            else:
                virtual_cash += signed_notional - fee
                trading_pnl += quantity * (fill_price - reference_price)
            total_fees += fee
            executions.append(
                {
                    "client_order_id": order.client_order_id,
                    "exchange_order_id": exchange_order_id,
                    "symbol": order.symbol,
                    "side": order.side,
                    "phase": order.phase,
                    "quantity": quantity,
                    "reference_price": reference_price,
                    "fill_price": fill_price,
                    "fee_usdt": fee,
                    "submitted_at": submitted_at,
                    "acknowledged_at": acknowledged_at,
                    "filled_at": filled_at,
                    "source_hash": fill_hash,
                }
            )

        final_positions = ledger.position_quantities()
        funding_total = 0.0
        for symbol, quantity in sorted(final_positions.items()):
            if quantity <= 0.0:
                continue
            if symbol not in snapshot.funding:
                raise MultiSleeveVirtualRuntimeError(
                    f"virtual_funding_input_missing:{symbol}"
                )
            amount = (
                -quantity
                * float(snapshot.prices[symbol])
                * float(snapshot.funding[symbol])
                * cost_model.funding_multiplier
            )
            if amount == 0.0:
                amount = 0.0
            cursor += 1
            occurred_at = _at(start, cursor)
            funding_hash = canonical_hash(
                {
                    "event": "virtual_funding",
                    "symbol": symbol,
                    "quantity": quantity,
                    "rate": snapshot.funding[symbol],
                    "amount": amount,
                    "cost_model_hash": cost_model.model_hash,
                }
            )
            ledger.record_cash_event(
                event_key=f"virtual-funding:{batch.manifest.batch_id}:{symbol}",
                event_type="funding",
                amount=amount,
                asset="USDT",
                symbol=symbol,
                occurred_at=occurred_at,
                source_hash=funding_hash,
            )
            virtual_cash += amount
            funding_total += amount

        gross_notional = sum(
            quantity * float(snapshot.prices[symbol])
            for symbol, quantity in final_positions.items()
        )
        final_equity = virtual_cash + gross_notional
        expected_equity = opening_equity + trading_pnl + funding_total - total_fees
        if not math.isclose(final_equity, expected_equity, abs_tol=1e-9, rel_tol=0.0):
            raise MultiSleeveVirtualRuntimeError(
                "virtual_runtime_equity_components_mismatch"
            )
        cursor += 1
        marked_at = _at(start, cursor)
        accounting_hash = canonical_hash(
            {
                "event": "virtual_nav_mark",
                "batch_id": batch.manifest.batch_id,
                "opening_equity": opening_equity,
                "final_equity": final_equity,
                "trading_pnl": trading_pnl,
                "funding": funding_total,
                "fees": total_fees,
            }
        )
        nav = ledger.record_nav_mark(
            marked_at=marked_at,
            opening_equity=opening_equity,
            equity=final_equity,
            trading_pnl=trading_pnl,
            residual_tolerance=1e-9,
            signal_nav=1.0,
            standalone_executable_nav=final_equity / opening_equity,
            source_hash=accounting_hash,
        )
        ledger.record_account_observation(
            batch_id=batch.manifest.batch_id,
            observed_at=marked_at,
            quote_asset="USDT",
            wallet_balance=final_equity,
            available_balance=max(0.0, virtual_cash),
            actual_gross_notional=gross_notional,
            margin_used=0.0,
            source_id=canonical_hash(
                {"virtual_account": batch.manifest.batch_id}
            ),
            source_hash=accounting_hash,
        )
        cursor += 1
        reconciled_at = _at(start, cursor)
        reconciliation = reconcile_three_way(
            batch_id=batch.manifest.batch_id,
            reconciled_at=reconciled_at,
            phase="post_dispatch",
            target_positions=dict(plan.expected_positions),
            ledger_positions=final_positions,
            exchange_positions=final_positions,
            position_tolerances=dict(plan.reconciliation_tolerance),
            ledger_open_order_ids=ledger.open_order_ids(),
            exchange_open_order_ids=(),
            equity_residual=nav.residual,
            equity_residual_tolerance=nav.residual_tolerance,
        )
        ledger.record_reconciliation(reconciliation)
        cursor += 1
        completed_at = _at(start, cursor)
        ledger_snapshot = build_runtime_ledger_snapshot(
            ledger,
            batch,
            captured_at=completed_at,
        )
        audit_rows = _audit_rows(ledger.audit_path)

        sleeve_rows: list[dict[str, Any]] = []
        for intent in intents:
            weights = target.sleeve_contributions[intent.strategy_id]
            sleeve_cost = 0.0
            sleeve_funding = 0.0
            for symbol, weight in weights.items():
                notional = opening_equity * float(weight)
                sleeve_cost += notional * (
                    cost_model.taker_fee_rate
                    + cost_model.slippage_bps / 10_000.0
                )
                sleeve_funding -= (
                    notional
                    * float(snapshot.funding.get(symbol, 0.0))
                    * cost_model.funding_multiplier
                )
            standalone_nav = 1.0 + (sleeve_funding - sleeve_cost) / opening_equity
            attribution = NavAttribution(
                strategy_id=intent.strategy_id,
                signal_nav=1.0,
                standalone_executable_nav=standalone_nav,
                portfolio_realized_nav=final_equity / opening_equity,
            )
            errors = attribution.validate()
            if errors:
                raise MultiSleeveVirtualRuntimeError(
                    "virtual_sleeve_nav_invalid:" + ",".join(errors)
                )
            sleeve_rows.append(
                asdict(attribution)
                | {
                    "scaled_target_weights": dict(weights),
                    "estimated_execution_cost_usdt": sleeve_cost,
                    "estimated_funding_usdt": sleeve_funding,
                }
            )

        virtual_execution_core = {
            "schema_version": VIRTUAL_RUNTIME_SCHEMA_VERSION,
            "cost_model": asdict(cost_model),
            "opening_cash_usdt": cash,
            "opening_equity_usdt": opening_equity,
            "final_cash_usdt": virtual_cash,
            "final_equity_usdt": final_equity,
            "trading_pnl_usdt": trading_pnl,
            "funding_usdt": funding_total,
            "fees_usdt": total_fees,
            "executions": executions,
            "orders_authorized": False,
            "orders_routed": False,
        }
        virtual_execution = virtual_execution_core | {
            "execution_hash": canonical_hash(virtual_execution_core)
        }
        sleeve_nav_core = {
            "schema_version": VIRTUAL_RUNTIME_SCHEMA_VERSION,
            "nav_semantics": {
                "signal_nav": "same-mark no-cost target fixture",
                "standalone_executable_nav": "independent sleeve fee/slippage/funding fixture",
                "portfolio_realized_nav": "shared virtual account after deterministic execution",
            },
            "sleeves": sleeve_rows,
            "promotion_evidence": False,
        }
        sleeve_nav = sleeve_nav_core | {
            "sleeve_nav_hash": canonical_hash(sleeve_nav_core)
        }
        result_core = {
            "schema_version": VIRTUAL_RUNTIME_SCHEMA_VERSION,
            "evidence_class": VIRTUAL_RUNTIME_EVIDENCE_CLASS,
            "run_id": batch.manifest.batch_id,
            "batch_id": batch.manifest.batch_id,
            "completed_at": completed_at,
            "sleeve_count": len(intents),
            "strategy_ids": sorted(intent.strategy_id for intent in intents),
            "order_count": len(plan.orders),
            "fill_count": len(ledger_snapshot.fills),
            "reduce_before_increase": [order.phase for order in plan.orders]
            == sorted(
                (order.phase for order in plan.orders),
                key=lambda value: 0 if value == "reduce" else 1,
            ),
            "accounting_passed": nav.passed,
            "accounting_residual_usdt": nav.residual,
            "reconciliation_passed": reconciliation.passed,
            "reconciliation_hash": reconciliation.report_hash,
            "decision_batch_manifest_hash": batch.manifest.manifest_hash,
            "runtime_snapshot_hash": ledger_snapshot.snapshot_hash,
            "cost_model_hash": cost_model.model_hash,
            "orders_authorized": False,
            "orders_routed": False,
            "production_authority_changed": False,
            "promotion_evidence": False,
        }
        result = result_core | {"result_hash": canonical_hash(result_core)}
        target_directory = Path(output_directory)
        if target_directory.name != batch.manifest.batch_id:
            target_directory = target_directory / batch.manifest.batch_id
        return _publish_bundle(
            target_directory,
            batch=batch,
            ledger_snapshot=ledger_snapshot,
            audit_rows=audit_rows,
            virtual_execution=virtual_execution,
            sleeve_nav=sleeve_nav,
            result=result,
        )
