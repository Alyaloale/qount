"""Machine-readable Phase B cycle and non-blocking observation evidence."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from qount.contracts.hashing import canonical_hash


PHASE_B_PROGRESS_SCHEMA_VERSION = 2
PHASE_B_OBSERVATION_TARGET = 30


class PhaseBProgressError(ValueError):
    """Raised when a Phase B progress artifact is invalid or unsafe."""


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii") + b"\n"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_immutable(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _canonical_bytes(payload)
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = -1
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    _fsync_directory(path.parent)
    if path.read_bytes() != raw:
        raise PhaseBProgressError("phase_b_progress_readback_mismatch")


def _replace_projection(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _canonical_bytes(payload)
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
            raise PhaseBProgressError("phase_b_progress_projection_mismatch")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhaseBProgressError(
            f"phase_b_progress_json_invalid:{path}"
        ) from exc
    if not isinstance(value, dict):
        raise PhaseBProgressError(
            f"phase_b_progress_object_invalid:{path}"
        )
    return value


def _verify_hashed_record(
    value: Mapping[str, Any],
    *,
    hash_field: str,
    error_code: str,
) -> None:
    expected = value.get(hash_field)
    core = {key: item for key, item in value.items() if key != hash_field}
    if expected != canonical_hash(core):
        raise PhaseBProgressError(error_code)


def initialize_phase_b_baseline(
    state_dir: str | os.PathLike[str],
    *,
    exclude_run_dirs: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Freeze legacy pre-cycle runs once, before the new cycle format starts."""

    root = Path(state_dir)
    baseline_path = root / "phase_b_progress_baseline.json"
    if baseline_path.is_file():
        baseline = _load_json(baseline_path)
        _verify_hashed_record(
            baseline,
            hash_field="baseline_hash",
            error_code="phase_b_progress_baseline_tampered",
        )
        return baseline
    shadow_root = root / "shadow_accounting" / "runs"
    valid: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    ordered_runs: list[dict[str, Any]] = []
    excluded = {str(Path(path).resolve()) for path in exclude_run_dirs}
    for run_path in sorted(shadow_root.glob("*/shadow_run.json")):
        if str(run_path.parent.resolve()) in excluded:
            continue
        run = _load_json(run_path)
        record = {
            "run_id": run.get("run_id"),
            "observed_at": run.get("observed_at"),
            "shadow_run_sha256": _sha256(run_path),
            "watermark_hash": run.get("watermark_hash"),
            "has_blocking_diff": bool(run.get("has_blocking_diff", True)),
            "unknown_income_count": int(run.get("unknown_income_count", 0)),
        }
        manifest_path = run_path.parent / "archive_manifest.json"
        if manifest_path.is_file():
            manifest = _load_json(manifest_path)
            files = manifest.get("files")
            trades = files.get("trades.jsonl") if isinstance(files, dict) else None
            trade_count = (
                int(trades.get("record_count", 0))
                if isinstance(trades, dict)
                else 0
            )
            record["real_trade_coverage"] = {
                "available": trade_count > 0,
                "trade_record_count": trade_count,
                "archive_manifest_sha256": _sha256(manifest_path),
            }
        record["valid"] = bool(
            not record["has_blocking_diff"]
            and record["unknown_income_count"] == 0
        )
        ordered_runs.append(record)
        if record["valid"]:
            valid.append(record)
        else:
            invalid.append(record)
    core = {
        "schema_version": PHASE_B_PROGRESS_SCHEMA_VERSION,
        "artifact_type": "phase_b_progress_baseline",
        "policy_mode": "non_blocking_observation",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "acceptance_basis": "pre_cycle_shadow_archives_and_documented_venue_halt_results",
        "legacy_runs": ordered_runs,
        "legacy_valid_runs": valid,
        "legacy_invalid_runs": invalid,
        "blocks_local_progress": False,
        "orders_authorized": False,
    }
    baseline = core | {"baseline_hash": canonical_hash(core)}
    _write_immutable(baseline_path, baseline)
    return baseline


def _cycle_is_valid(results: Mapping[str, Any]) -> tuple[bool, list[str]]:
    blockers: list[str] = []
    shadow = results.get("shadow")
    venue = results.get("venue")
    halt = results.get("halt")
    if not isinstance(shadow, Mapping):
        blockers.append("shadow_result_missing")
    else:
        if bool(shadow.get("has_blocking_diff", True)):
            blockers.append("shadow_blocking_diff")
        if int(shadow.get("unknown_income_count", 0)) != 0:
            blockers.append("shadow_unknown_income")
    if not isinstance(venue, Mapping):
        blockers.append("venue_result_missing")
    else:
        if venue.get("compatibility") != "pass":
            blockers.append("venue_not_compatible")
        if venue.get("blockers"):
            blockers.append("venue_blockers_present")
    if not isinstance(halt, Mapping):
        blockers.append("halt_result_missing")
    elif int(halt.get("event_count", 0)) != 0:
        blockers.append("halt_events_present")
    for name in ("shadow_error", "venue_error", "halt_error"):
        if name in results:
            blockers.append(name)
    return not blockers, blockers


def _real_trade_coverage(results: Mapping[str, Any]) -> dict[str, Any]:
    shadow = results.get("shadow")
    if not isinstance(shadow, Mapping):
        return {"available": False, "trade_record_count": 0}
    run_dir = shadow.get("run_dir")
    if not isinstance(run_dir, str):
        return {"available": False, "trade_record_count": 0}
    manifest_path = Path(run_dir) / "archive_manifest.json"
    if not manifest_path.is_file():
        return {"available": False, "trade_record_count": 0}
    manifest = _load_json(manifest_path)
    files = manifest.get("files")
    trades = files.get("trades.jsonl") if isinstance(files, dict) else None
    count = int(trades.get("record_count", 0)) if isinstance(trades, dict) else 0
    return {
        "available": count > 0,
        "trade_record_count": count,
        "archive_manifest_sha256": _sha256(manifest_path),
    }


def record_phase_b_cycle(
    state_dir: str | os.PathLike[str],
    results: Mapping[str, Any],
    *,
    observation_target: int = PHASE_B_OBSERVATION_TARGET,
    required_valid_streak: int | None = None,
) -> dict[str, Any]:
    """Archive one cycle and update non-blocking observation progress.

    ``required_valid_streak`` remains as a compatibility keyword for callers
    written against schema v1.  It selects an observation milestone only and
    never gates local research, allocator development, or authority.
    """

    if required_valid_streak is not None:
        if (
            observation_target != PHASE_B_OBSERVATION_TARGET
            and observation_target != required_valid_streak
        ):
            raise PhaseBProgressError("phase_b_observation_target_conflict")
        observation_target = required_valid_streak
    if observation_target <= 0:
        raise PhaseBProgressError("phase_b_observation_target_invalid")
    root = Path(state_dir)
    current_shadow = results.get("shadow")
    current_run_dir = (
        str(current_shadow.get("run_dir"))
        if isinstance(current_shadow, Mapping)
        and isinstance(current_shadow.get("run_dir"), str)
        else None
    )
    baseline = initialize_phase_b_baseline(
        root,
        exclude_run_dirs=((current_run_dir,) if current_run_dir else ()),
    )
    valid, blockers = _cycle_is_valid(results)
    source_hashes: dict[str, str] = {}
    shadow = results.get("shadow")
    if isinstance(shadow, Mapping) and isinstance(shadow.get("run_dir"), str):
        shadow_path = Path(str(shadow["run_dir"])) / "shadow_run.json"
        if shadow_path.is_file():
            source_hashes["shadow_run"] = _sha256(shadow_path)
    venue = results.get("venue")
    if isinstance(venue, Mapping) and isinstance(venue.get("archive_path"), str):
        venue_path = Path(str(venue["archive_path"]))
        if venue_path.is_file():
            source_hashes["venue_snapshot"] = _sha256(venue_path)
    cycle_core = {
        "schema_version": PHASE_B_PROGRESS_SCHEMA_VERSION,
        "artifact_type": "phase_b_readonly_cycle",
        "policy_mode": "non_blocking_observation",
        "started_at": results.get("started_at"),
        "completed_at": results.get("completed_at"),
        "symbols": list(results.get("symbols", [])),
        "valid": valid,
        "blockers": blockers,
        "shadow": dict(shadow) if isinstance(shadow, Mapping) else None,
        "venue": dict(venue) if isinstance(venue, Mapping) else None,
        "halt": (
            dict(results["halt"])
            if isinstance(results.get("halt"), Mapping)
            else None
        ),
        "source_hashes": source_hashes,
        "real_trade_coverage": _real_trade_coverage(results),
        "blocks_local_progress": False,
        "orders_authorized": False,
    }
    cycle_id = canonical_hash(cycle_core)
    cycle = cycle_core | {"cycle_id": cycle_id}
    _write_immutable(root / "cycles" / f"{cycle_id}.json", cycle)

    cycles = [
        _load_json(path)
        for path in sorted((root / "cycles").glob("*.json"))
    ]
    cycles.sort(
        key=lambda item: (
            str(item.get("completed_at") or ""),
            str(item.get("cycle_id") or ""),
        )
    )
    legacy_valid = list(baseline.get("legacy_valid_runs", []))
    legacy_invalid = list(baseline.get("legacy_invalid_runs", []))
    legacy_runs = baseline.get("legacy_runs")
    streak = 0
    if isinstance(legacy_runs, list):
        for recorded in legacy_runs:
            if isinstance(recorded, Mapping) and bool(recorded.get("valid")):
                streak += 1
            else:
                streak = 0
    else:
        # Compatibility for a baseline frozen by the first local schema draft.
        streak = len(legacy_valid)
    verified_cycles: list[dict[str, Any]] = []
    for recorded in cycles:
        _verify_hashed_record(
            recorded,
            hash_field="cycle_id",
            error_code="phase_b_progress_cycle_tampered",
        )
        verified_cycles.append(recorded)
        if bool(recorded.get("valid")):
            streak += 1
        else:
            streak = 0
    valid_cycle_count = sum(bool(item.get("valid")) for item in verified_cycles)
    invalid_cycle_count = len(verified_cycles) - valid_cycle_count
    legacy_trade_coverage = any(
        bool(item.get("real_trade_coverage", {}).get("available"))
        for item in baseline.get("legacy_valid_runs", [])
        if isinstance(item, Mapping)
    )
    cycle_trade_coverage = any(
        bool(item.get("real_trade_coverage", {}).get("available"))
        for item in verified_cycles
        if isinstance(item, Mapping)
    )
    has_real_trade_coverage = legacy_trade_coverage or cycle_trade_coverage
    remaining = max(observation_target - streak, 0)
    latest_shadow = cycle.get("shadow") or {}
    latest_venue = cycle.get("venue") or {}
    latest_halt = cycle.get("halt") or {}
    progress_core = {
        "schema_version": PHASE_B_PROGRESS_SCHEMA_VERSION,
        "artifact_type": "phase_b_observation_progress",
        "policy_mode": "non_blocking_observation",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "observation_target": observation_target,
        "valid_streak": streak,
        "remaining_observation_cycles": remaining,
        "legacy_valid_count": len(legacy_valid),
        "legacy_invalid_count": len(legacy_invalid),
        "recorded_cycle_count": len(cycles),
        "valid_cycle_count": valid_cycle_count,
        "invalid_cycle_count": invalid_cycle_count,
        "valid_batch_count": len(legacy_valid) + valid_cycle_count,
        "failed_batch_count": len(legacy_invalid) + invalid_cycle_count,
        "latest_cycle_id": cycle_id,
        "latest_watermark_hash": latest_shadow.get("watermark_hash"),
        "latest_has_blocking_diff": latest_shadow.get("has_blocking_diff"),
        "latest_venue_compatibility": latest_venue.get("compatibility"),
        "latest_halt_event_count": latest_halt.get("event_count"),
        "real_trade_coverage": cycle["real_trade_coverage"],
        "has_real_trade_coverage": has_real_trade_coverage,
        "observation_target_reached": streak >= observation_target,
        "blocks_local_progress": False,
        "blocks_research": False,
        "blocks_allocator_development": False,
        "orders_authorized": False,
        "automatic_authority_change": False,
        "authority_effect": "none",
        "baseline_hash": baseline.get("baseline_hash"),
    }
    progress_hash = canonical_hash(progress_core)
    progress = progress_core | {"progress_hash": progress_hash}
    progress_path = root / "progress" / f"{progress_hash}.json"
    _write_immutable(progress_path, progress)
    _replace_projection(root / "latest_progress.json", progress)
    if progress["observation_target_reached"]:
        milestone_path = (
            root / "milestones" / "phase_b_observation_target.json"
        )
        if not milestone_path.exists():
            _write_immutable(milestone_path, progress)
    return progress
