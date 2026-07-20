"""Manifest-last persistence and replay for one complete decision batch."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from qount.contracts import ArtifactReference
from qount.contracts import DecisionBatchManifest
from qount.contracts import MarketSnapshot
from qount.contracts import OrderPlan
from qount.contracts import PortfolioTarget
from qount.contracts import RiskDecision
from qount.contracts import StrategyIntent
from qount.contracts import validate_decision_batch
from qount.contracts.trace import aware_datetime
from qount.persistence.codec import artifact_envelope
from qount.persistence.immutable_json import read_immutable_artifact
from qount.persistence.immutable_json import write_immutable_artifact


class DecisionBatchError(ValueError):
    """Raised when a decision batch cannot be built or verified."""


class DecisionBatchIncompleteError(DecisionBatchError):
    """Raised when the manifest-last completion marker is absent."""


@dataclass(frozen=True)
class VerifiedDecisionBatch:
    manifest: DecisionBatchManifest
    snapshot: MarketSnapshot
    intents: tuple[StrategyIntent, ...]
    target: PortfolioTarget
    risk: RiskDecision
    plan: OrderPlan


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _completed_directory(path: Path) -> Path:
    if path.name.endswith((".tmp", ".partial")):
        raise DecisionBatchError("decision_batch_path_is_temporary")
    if path.is_symlink():
        raise DecisionBatchError("decision_batch_directory_symlink_forbidden")
    return path


def _require_directory_mode(path: Path) -> None:
    if stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode) != 0o700:
        raise DecisionBatchError("decision_batch_directory_mode_invalid")


def _require_artifact_mode(path: Path) -> None:
    if stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode) != 0o600:
        raise DecisionBatchError(
            f"decision_batch_artifact_mode_invalid:{path.name}"
        )


def _reference(value: object, *, file_name: str) -> ArtifactReference:
    envelope = artifact_envelope(value)
    return ArtifactReference.create(
        artifact_type=str(envelope["artifact_type"]),
        object_id=str(envelope["object_id"]),
        payload_hash=str(envelope["payload_hash"]),
        artifact_hash=str(envelope["artifact_hash"]),
        file_name=file_name,
    )


def _reference_errors(
    reference: ArtifactReference,
    value: object,
) -> tuple[str, ...]:
    envelope = artifact_envelope(value)
    expected = {
        "artifact_type": str(envelope["artifact_type"]),
        "object_id": str(envelope["object_id"]),
        "payload_hash": str(envelope["payload_hash"]),
        "artifact_hash": str(envelope["artifact_hash"]),
    }
    errors = [
        f"decision_batch_reference_{name}_mismatch:{reference.file_name}"
        for name, expected_value in expected.items()
        if getattr(reference, name) != expected_value
    ]
    return tuple(errors)


def build_decision_batch_manifest(
    *,
    snapshot: MarketSnapshot,
    intents: Sequence[StrategyIntent],
    target: PortfolioTarget,
    risk: RiskDecision,
    plan: OrderPlan,
    created_at: str,
) -> DecisionBatchManifest:
    """Build a completion manifest after validating the complete trace chain."""

    normalized_intents = tuple(intents)
    errors = list(
        validate_decision_batch(snapshot, normalized_intents, target, risk, plan)
    )
    try:
        if aware_datetime(created_at) < aware_datetime(plan.created_at):
            errors.append("decision_batch_manifest_created_before_order_plan")
    except (AttributeError, TypeError, ValueError):
        errors.append("decision_batch_manifest_created_at_invalid")
    if errors:
        raise DecisionBatchError(f"decision_batch_invalid:{','.join(errors)}")
    return DecisionBatchManifest.create(
        batch_id=risk.batch_id,
        created_at=created_at,
        market_snapshot=_reference(
            snapshot,
            file_name="market_snapshot.json",
        ),
        strategy_intents=tuple(
            _reference(
                intent,
                file_name=f"strategy_intent.{intent.decision_id}.json",
            )
            for intent in normalized_intents
        ),
        portfolio_target=_reference(
            target,
            file_name="portfolio_target.json",
        ),
        risk_decision=_reference(
            risk,
            file_name="risk_decision.json",
        ),
        order_plan=_reference(
            plan,
            file_name="order_plan.json",
        ),
    )


def publish_decision_batch(
    directory: str | Path,
    *,
    snapshot: MarketSnapshot,
    intents: Sequence[StrategyIntent],
    target: PortfolioTarget,
    risk: RiskDecision,
    plan: OrderPlan,
    created_at: str,
) -> VerifiedDecisionBatch:
    """Write immutable members first and the completion manifest last."""

    target_directory = _completed_directory(Path(directory))
    normalized_intents = tuple(intents)
    manifest = build_decision_batch_manifest(
        snapshot=snapshot,
        intents=normalized_intents,
        target=target,
        risk=risk,
        plan=plan,
        created_at=created_at,
    )
    if target_directory.name != manifest.batch_id:
        raise DecisionBatchError("decision_batch_directory_name_mismatch")
    target_directory.parent.mkdir(parents=True, exist_ok=True)
    target_directory.mkdir(mode=0o700)
    os.chmod(target_directory, 0o700)
    _fsync_directory(target_directory.parent)
    by_file_name = _batch_members(
        snapshot=snapshot,
        intents=normalized_intents,
        target=target,
        risk=risk,
        plan=plan,
    )
    _complete_decision_batch_directory(
        target_directory,
        manifest=manifest,
        by_file_name=by_file_name,
        allow_verified_existing=False,
    )
    return read_decision_batch(target_directory)


def _batch_members(
    *,
    snapshot: MarketSnapshot,
    intents: Sequence[StrategyIntent],
    target: PortfolioTarget,
    risk: RiskDecision,
    plan: OrderPlan,
) -> dict[str, object]:
    return {
        "market_snapshot.json": snapshot,
        **{
            f"strategy_intent.{intent.decision_id}.json": intent
            for intent in intents
        },
        "portfolio_target.json": target,
        "risk_decision.json": risk,
        "order_plan.json": plan,
    }


def _complete_decision_batch_directory(
    directory: Path,
    *,
    manifest: DecisionBatchManifest,
    by_file_name: dict[str, object],
    allow_verified_existing: bool,
) -> None:
    try:
        for reference in manifest.artifact_references():
            path = directory / reference.file_name
            if path.exists() and allow_verified_existing:
                existing = _read_reference(directory, reference)
                expected = by_file_name[reference.file_name]
                if artifact_envelope(existing) != artifact_envelope(expected):
                    raise DecisionBatchError(
                        "decision_batch_existing_artifact_mismatch:"
                        f"{reference.file_name}"
                    )
                continue
            write_immutable_artifact(path, by_file_name[reference.file_name])
        if (directory / "manifest.json").exists():
            raise DecisionBatchError("decision_batch_manifest_already_exists")
        write_immutable_artifact(directory / "manifest.json", manifest)
        _fsync_directory(directory)
    except Exception:
        _fsync_directory(directory)
        raise


def resume_incomplete_decision_batch(
    directory: str | Path,
    *,
    snapshot: MarketSnapshot,
    intents: Sequence[StrategyIntent],
    target: PortfolioTarget,
    risk: RiskDecision,
    plan: OrderPlan,
    created_at: str,
) -> VerifiedDecisionBatch:
    """Complete a manifest-less batch without replacing any existing member."""

    target_directory = _completed_directory(Path(directory))
    if not target_directory.is_dir():
        raise DecisionBatchIncompleteError("decision_batch_directory_missing")
    _require_directory_mode(target_directory)
    if (target_directory / "manifest.json").exists():
        raise DecisionBatchError("decision_batch_manifest_already_exists")
    normalized_intents = tuple(intents)
    manifest = build_decision_batch_manifest(
        snapshot=snapshot,
        intents=normalized_intents,
        target=target,
        risk=risk,
        plan=plan,
        created_at=created_at,
    )
    if target_directory.name != manifest.batch_id:
        raise DecisionBatchError("decision_batch_directory_name_mismatch")
    expected_members = {
        reference.file_name for reference in manifest.artifact_references()
    }
    actual_members = {path.name for path in target_directory.iterdir()}
    unexpected = actual_members - expected_members
    if unexpected:
        raise DecisionBatchIncompleteError(
            "decision_batch_resume_unexpected_files:"
            f"{','.join(sorted(unexpected))}"
        )
    _complete_decision_batch_directory(
        target_directory,
        manifest=manifest,
        by_file_name=_batch_members(
            snapshot=snapshot,
            intents=normalized_intents,
            target=target,
            risk=risk,
            plan=plan,
        ),
        allow_verified_existing=True,
    )
    return read_decision_batch(target_directory)


def _read_reference(
    directory: Path,
    reference: ArtifactReference,
) -> object:
    path = directory / reference.file_name
    if path.is_symlink():
        raise DecisionBatchError(
            f"decision_batch_artifact_symlink_forbidden:{reference.file_name}"
        )
    if not path.is_file():
        raise DecisionBatchIncompleteError(
            f"decision_batch_artifact_missing:{reference.file_name}"
        )
    _require_artifact_mode(path)
    value = read_immutable_artifact(
        path,
        expected_artifact_type=reference.artifact_type,
    )
    errors = _reference_errors(reference, value)
    if errors:
        raise DecisionBatchError(f"decision_batch_invalid:{','.join(errors)}")
    return value


def read_decision_batch(directory: str | Path) -> VerifiedDecisionBatch:
    """Read a completed directory and replay every lineage assertion."""

    source = _completed_directory(Path(directory))
    if not source.exists():
        raise FileNotFoundError(source)
    if not source.is_dir():
        raise DecisionBatchError("decision_batch_path_not_directory")
    _require_directory_mode(source)
    manifest_path = source / "manifest.json"
    if manifest_path.is_symlink():
        raise DecisionBatchError("decision_batch_manifest_symlink_forbidden")
    if not manifest_path.is_file():
        raise DecisionBatchIncompleteError("decision_batch_manifest_missing")
    _require_artifact_mode(manifest_path)
    manifest = read_immutable_artifact(
        manifest_path,
        expected_artifact_type="decision_batch_manifest",
    )
    if not isinstance(manifest, DecisionBatchManifest):
        raise DecisionBatchError("decision_batch_manifest_type_invalid")
    if source.name != manifest.batch_id:
        raise DecisionBatchError("decision_batch_directory_name_mismatch")
    expected_files = {
        "manifest.json",
        *(reference.file_name for reference in manifest.artifact_references()),
    }
    actual_files = {path.name for path in source.iterdir()}
    if actual_files != expected_files:
        missing = ",".join(sorted(expected_files - actual_files)) or "none"
        unexpected = ",".join(sorted(actual_files - expected_files)) or "none"
        raise DecisionBatchIncompleteError(
            "decision_batch_files_mismatch:"
            f"missing={missing}:unexpected={unexpected}"
        )

    snapshot = _read_reference(source, manifest.market_snapshot)
    intents = tuple(
        _read_reference(source, reference)
        for reference in manifest.strategy_intents
    )
    target = _read_reference(source, manifest.portfolio_target)
    risk = _read_reference(source, manifest.risk_decision)
    plan = _read_reference(source, manifest.order_plan)
    if not isinstance(snapshot, MarketSnapshot):
        raise DecisionBatchError("decision_batch_snapshot_type_invalid")
    if any(not isinstance(intent, StrategyIntent) for intent in intents):
        raise DecisionBatchError("decision_batch_intent_type_invalid")
    if not isinstance(target, PortfolioTarget):
        raise DecisionBatchError("decision_batch_target_type_invalid")
    if not isinstance(risk, RiskDecision):
        raise DecisionBatchError("decision_batch_risk_type_invalid")
    if not isinstance(plan, OrderPlan):
        raise DecisionBatchError("decision_batch_plan_type_invalid")
    errors = list(validate_decision_batch(snapshot, intents, target, risk, plan))
    if manifest.batch_id != risk.batch_id:
        errors.append("decision_batch_manifest_batch_id_mismatch")
    try:
        if aware_datetime(manifest.created_at) < aware_datetime(plan.created_at):
            errors.append("decision_batch_manifest_created_before_order_plan")
    except (AttributeError, TypeError, ValueError):
        errors.append("decision_batch_manifest_created_at_invalid")
    if errors:
        raise DecisionBatchError(f"decision_batch_invalid:{','.join(errors)}")
    return VerifiedDecisionBatch(
        manifest=manifest,
        snapshot=snapshot,
        intents=intents,
        target=target,
        risk=risk,
        plan=plan,
    )


def inspect_decision_batch(directory: str | Path) -> dict[str, object]:
    """Return a read-only completion status without treating partial state as valid."""

    source = Path(directory)
    if not source.exists():
        return {"status": "missing", "path": str(source)}
    found = (
        tuple(sorted(path.name for path in source.iterdir()))
        if source.is_dir()
        else ()
    )
    if source.is_dir() and "manifest.json" not in found:
        return {
            "status": "incomplete",
            "path": str(source),
            "found_files": found,
            "reason": "decision_batch_manifest_missing",
        }
    try:
        batch = read_decision_batch(source)
    except DecisionBatchIncompleteError as exc:
        return {
            "status": "incomplete",
            "path": str(source),
            "found_files": found,
            "reason": str(exc),
        }
    except Exception as exc:
        return {
            "status": "invalid",
            "path": str(source),
            "found_files": found,
            "reason": type(exc).__name__,
        }
    return {
        "status": "complete",
        "path": str(source),
        "batch_id": batch.manifest.batch_id,
        "manifest_id": batch.manifest.decision_batch_manifest_id,
        "artifact_count": len(batch.manifest.artifact_references()),
    }
