from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import hashlib
import json
import math
import os
from pathlib import Path
import socket
from typing import Any

from qount.alpha_agents.live_collector import _config_hash
from qount.alpha_agents.live_collector import _sha256_file
from qount.alpha_agents.live_collector import LIVE_COLLECTOR_VERSION
from qount.alpha_agents.live_collector import LiveCollectorConfig
from qount.alpha_agents.live_collector import audit_event_file
from qount.alpha_agents.live_collector import run_live_collector_segments
from qount.artifacts import persistent_research_dir
from qount.settings import Settings


LIVE_COLLECTOR_SESSION_VERSION = "alpha_agent_live_collector_session_v0.3"
LEGACY_LIVE_COLLECTOR_SESSION_VERSIONS = ("alpha_agent_live_collector_session_v0.2",)
LIVE_COLLECTOR_VERIFICATION_VERSION = "alpha_agent_live_collector_verification_v0.1"
SESSION_PATH_CONTRACT = "session_relative_v1"
S3_REQUIRED_SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
S3_REQUIRED_STREAMS = ("bookTicker", "aggTrade", "depth", "forceOrder")


@dataclass(frozen=True)
class LiveCollectorSessionConfig:
    total_duration_seconds: int = 7 * 24 * 60 * 60
    segment_duration_seconds: int = 24 * 60 * 60

    def validate(self) -> None:
        if self.total_duration_seconds <= 0:
            raise ValueError("total_duration_seconds must be positive")
        if self.segment_duration_seconds <= 0:
            raise ValueError("segment_duration_seconds must be positive")


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _utc_iso(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def _utc_day(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).date().isoformat()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _resolved_child_path(session_dir: Path, value: Any) -> tuple[Path | None, bool]:
    if not value:
        return None, False
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = session_dir / path
    resolved = path.resolve()
    try:
        resolved.relative_to(session_dir.resolve())
    except ValueError:
        return resolved, False
    return resolved, True


def _relative_child_path(session_dir: Path, value: Any) -> str:
    resolved, safe = _resolved_child_path(session_dir, value)
    if resolved is None or not safe:
        raise ValueError(f"collector path must stay inside session: {value}")
    return resolved.relative_to(session_dir.resolve()).as_posix()


def _process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextmanager
def _session_lock(session_dir: Path):
    lock_path = session_dir / ".collector-session.lock"
    hostname = socket.gethostname()
    if lock_path.exists():
        try:
            existing = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
        existing_pid = int(existing.get("pid") or 0)
        existing_host = str(existing.get("hostname") or "")
        if existing_host and existing_host != hostname:
            raise RuntimeError(f"collector session is locked by host {existing_host}")
        if _process_is_alive(existing_pid):
            raise RuntimeError(f"collector session is already running under pid {existing_pid}")
        stale_path = session_dir / f".collector-session.lock.stale-{_now_ms()}"
        os.replace(lock_path, stale_path)

    lock_payload = {
        "pid": os.getpid(),
        "hostname": hostname,
        "acquired_at_ms": _now_ms(),
    }
    descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(lock_payload, handle, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _resolve_session_dir(settings: Settings, explicit_output_dir: str | None, *, resume: bool) -> Path:
    if explicit_output_dir is None:
        if resume:
            raise ValueError("resume requires an explicit session directory")
        return persistent_research_dir(settings, "alpha-agent-live-collector-session")
    session_dir = Path(explicit_output_dir).expanduser()
    if not session_dir.is_absolute():
        session_dir = settings.project_root / session_dir
    if resume and not session_dir.is_dir():
        raise FileNotFoundError(f"collector session directory does not exist: {session_dir}")
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def _collector_contract(config: LiveCollectorConfig) -> dict[str, Any]:
    payload = config.to_dict()
    payload.pop("duration_seconds", None)
    return payload


def _contract_hash(config: LiveCollectorConfig, session_config: LiveCollectorSessionConfig) -> str:
    return _contract_hash_from_payload(config.to_dict(), session_config)


def _contract_hash_from_payload(
    collector_payload: dict[str, Any],
    session_config: LiveCollectorSessionConfig,
) -> str:
    collector_contract = dict(collector_payload)
    collector_contract.pop("duration_seconds", None)
    payload = {
        "collector": collector_contract,
        "session": asdict(session_config),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _collector_config_from_payload(payload: dict[str, Any]) -> LiveCollectorConfig:
    values = dict(payload)
    values["symbols"] = tuple(values.get("symbols") or ())
    values["streams"] = tuple(values.get("streams") or ())
    return LiveCollectorConfig(**values)


def _segment_duration_seconds(segment_limit: int, remaining: int, now_ms: int) -> int:
    now = datetime.fromtimestamp(now_ms / 1000, timezone.utc)
    next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    until_midnight = max(1, math.ceil((next_midnight - now).total_seconds()))
    return min(segment_limit, remaining, until_midnight)


def _allocate_segment_dir(session_dir: Path, index: int, now_ms: int) -> Path:
    stamp = datetime.fromtimestamp(now_ms / 1000, timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = session_dir / "segments"
    root.mkdir(parents=True, exist_ok=True)
    stem = f"{index:04d}-{stamp}"
    for collision_index in range(1000):
        suffix = "" if collision_index == 0 else f"-{collision_index:02d}"
        candidate = root / f"{stem}{suffix}"
        try:
            candidate.mkdir(exist_ok=False)
        except FileExistsError:
            continue
        return candidate
    raise RuntimeError(f"unable to allocate collector segment directory for {stem}")


def _segment_entry(
    result: dict[str, Any],
    requested_duration_seconds: int,
    index: int,
    *,
    session_dir: Path | None = None,
) -> dict[str, Any]:
    capture = result["capture"]
    audit = result["audit"]
    started_at_ms = int(capture["started_at_ms"])
    ended_at_ms = int(capture["ended_at_ms"])
    route_coverage = {
        str(route["route"]): {
            "first_market_event_at_ms": route.get("first_market_event_at_ms"),
            "last_market_event_at_ms": route.get("last_market_event_at_ms"),
        }
        for route in capture.get("routes") or []
    }
    entry = {
        "index": index,
        "utc_day": _utc_day(started_at_ms),
        "requested_duration_seconds": requested_duration_seconds,
        "started_at_ms": started_at_ms,
        "started_at_utc": _utc_iso(started_at_ms),
        "ended_at_ms": ended_at_ms,
        "ended_at_utc": _utc_iso(ended_at_ms),
        "wall_duration_seconds": max(0.0, (ended_at_ms - started_at_ms) / 1000),
        "market_event_started_at_ms": capture.get("market_event_started_at_ms"),
        "market_event_ended_at_ms": capture.get("market_event_ended_at_ms"),
        "route_coverage": route_coverage,
        "connection_ids_at_start": dict(capture.get("connection_ids_at_start") or {}),
        "connection_ids_at_end": dict(capture.get("connection_ids_at_end") or {}),
        "segment_connection_mode": str(capture.get("segment_connection_mode") or "restart_per_segment"),
        "sequence_boundaries": {
            str(route["route"]): dict(route.get("sequence_boundaries") or {})
            for route in capture.get("routes") or []
        },
        "artifact_path": result["artifact_path"],
        "raw_event_path": result["raw_event_path"],
        "config_hash": result["meta"]["config_hash"],
        "raw_sha256": result["meta"]["raw_sha256"],
        "raw_bytes": result["meta"]["raw_bytes"],
        "market_events": int(capture["market_events"]),
        "verdict": audit["verdict"],
        "blockers": list(audit["blockers"]),
        "audit": audit,
    }
    if session_dir is not None:
        entry["artifact_path"] = _relative_child_path(session_dir, entry["artifact_path"])
        entry["raw_event_path"] = _relative_child_path(session_dir, entry["raw_event_path"])
    return entry


def _boundary_gap(previous: dict[str, Any], current: dict[str, Any]) -> tuple[int, dict[str, int]]:
    previous_routes = previous.get("route_coverage") or {}
    current_routes = current.get("route_coverage") or {}
    gaps: dict[str, int] = {}
    for route in sorted(set(previous_routes) & set(current_routes)):
        previous_end = previous_routes[route].get("last_market_event_at_ms")
        current_start = current_routes[route].get("first_market_event_at_ms")
        if previous_end is None or current_start is None:
            continue
        gaps[route] = max(0, int(current_start) - int(previous_end))
    if gaps:
        return max(gaps.values()), gaps
    fallback = max(0, int(current["started_at_ms"]) - int(previous["ended_at_ms"]))
    return fallback, {"capture_fallback": fallback}


def _boundary_connection_restarts(previous: dict[str, Any], current: dict[str, Any]) -> list[str] | None:
    previous_connections = previous.get("connection_ids_at_end")
    current_connections = current.get("connection_ids_at_start")
    if not previous_connections or not current_connections:
        return None
    routes = sorted(set(previous_connections) | set(current_connections))
    return [route for route in routes if previous_connections.get(route) != current_connections.get(route)]


def _boundary_sequence_breaks(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, list[str]]:
    previous_routes = previous.get("sequence_boundaries") or {}
    current_routes = current.get("sequence_boundaries") or {}
    breaks: dict[str, list[str]] = {"trades": [], "book_ticker": [], "depth": []}
    for route in sorted(set(previous_routes) & set(current_routes)):
        previous_sequence = previous_routes[route]
        current_sequence = current_routes[route]
        previous_trades = previous_sequence.get("trades") or {}
        current_trades = current_sequence.get("trades") or {}
        for key in sorted(set(previous_trades) & set(current_trades)):
            previous_id = int(previous_trades[key]["last"])
            current_id = int(current_trades[key]["first"])
            if current_id != previous_id + 1:
                breaks["trades"].append(f"{route}:{key}:{previous_id}->{current_id}")
        previous_books = previous_sequence.get("book_ticker") or {}
        current_books = current_sequence.get("book_ticker") or {}
        for key in sorted(set(previous_books) & set(current_books)):
            previous_id = int(previous_books[key]["last"])
            current_id = int(current_books[key]["first"])
            if current_id <= previous_id:
                breaks["book_ticker"].append(f"{route}:{key}:{previous_id}->{current_id}")
        previous_depth = previous_sequence.get("depth") or {}
        current_depth = current_sequence.get("depth") or {}
        for key in sorted(set(previous_depth) & set(current_depth)):
            previous_id = previous_depth[key]["last"].get("final_update_id")
            current_previous_id = current_depth[key]["first"].get("previous_final_update_id")
            if previous_id is not None and current_previous_id is not None and int(current_previous_id) != int(previous_id):
                breaks["depth"].append(f"{route}:{key}:{previous_id}->{current_previous_id}")
    return breaks


def _summarize_segments(segments: list[dict[str, Any]]) -> dict[str, Any]:
    blocked = [segment for segment in segments if segment["verdict"] != "pass_data_smoke"]
    boundary_gaps = [int(segment.get("boundary_gap_ms") or 0) for segment in segments[1:]]
    return {
        "segment_count": len(segments),
        "passed_segment_count": len(segments) - len(blocked),
        "blocked_segment_count": len(blocked),
        "market_events": sum(int(segment["market_events"]) for segment in segments),
        "raw_bytes": sum(int(segment["raw_bytes"]) for segment in segments),
        "requested_duration_seconds": sum(int(segment["requested_duration_seconds"]) for segment in segments),
        "boundary_gap_total_ms": sum(boundary_gaps),
        "boundary_gap_max_ms": max(boundary_gaps, default=0),
        "connection_restart_count": sum(
            1
            for segment in segments[1:]
            if segment.get("connection_restarted_routes") is None or segment.get("connection_restarted_routes")
        ),
        "connection_restart_routes": sum(
            len(segment.get("connection_restarted_routes") or []) for segment in segments[1:]
        ),
        "boundary_trade_sequence_breaks": sum(
            len((segment.get("boundary_sequence_breaks") or {}).get("trades") or [])
            for segment in segments[1:]
        ),
        "boundary_book_ticker_sequence_breaks": sum(
            len((segment.get("boundary_sequence_breaks") or {}).get("book_ticker") or [])
            for segment in segments[1:]
        ),
        "boundary_depth_sequence_breaks": sum(
            len((segment.get("boundary_sequence_breaks") or {}).get("depth") or [])
            for segment in segments[1:]
        ),
        "snapshot_retries": sum(int(segment["audit"]["snapshots"].get("retries") or 0) for segment in segments),
        "snapshot_errors": sum(int(segment["audit"]["snapshots"].get("errors") or 0) for segment in segments),
        "trade_missing_ids": sum(int(segment["audit"]["trades"].get("missing_ids") or 0) for segment in segments),
        "depth_sequence_breaks": sum(
            int(segment["audit"]["depth"].get("sequence_breaks") or 0) for segment in segments
        ),
        "depth_replay_updates": sum(
            int(segment["audit"]["depth"].get("replay_updates") or 0) for segment in segments
        ),
        "depth_invalid_levels": sum(
            int(segment["audit"]["depth"].get("invalid_levels") or 0) for segment in segments
        ),
        "depth_empty_books": sum(
            int(segment["audit"]["depth"].get("empty_books") or 0) for segment in segments
        ),
        "depth_crossed_books": sum(
            int(segment["audit"]["depth"].get("crossed_books") or 0) for segment in segments
        ),
        "event_time_missing": sum(
            int(segment["audit"]["event_time"].get("missing") or 0) for segment in segments
        ),
        "event_time_future": sum(int(segment["audit"]["event_time"].get("future") or 0) for segment in segments),
        "event_time_stale": sum(int(segment["audit"]["event_time"].get("stale") or 0) for segment in segments),
        "blocked_segments": [int(segment["index"]) for segment in blocked],
    }


def _find_orphan_files(session_dir: Path, segments: list[dict[str, Any]]) -> list[str]:
    known: set[str] = set()
    for segment in segments:
        for value in (segment.get("artifact_path"), segment.get("raw_event_path")):
            resolved, safe = _resolved_child_path(session_dir, value)
            if resolved is not None and safe:
                known.add(str(resolved))
    segment_root = session_dir / "segments"
    if not segment_root.exists():
        return []
    candidates = [
        path
        for path in segment_root.rglob("*")
        if path.is_file()
        and (path.name.endswith(".partial") or path.name in {"events.jsonl.gz", "alpha_agent_live_collector.json"})
    ]
    return sorted(
        path.resolve().relative_to(session_dir.resolve()).as_posix()
        for path in candidates
        if str(path.resolve()) not in known
    )


def _refresh_manifest(manifest: dict[str, Any], session_dir: Path) -> None:
    segments = manifest["segments"]
    session = manifest["session"]
    manifest["meta"]["boundary_gaps_fail_closed"] = True
    aggregate = _summarize_segments(segments)
    completed = int(aggregate["requested_duration_seconds"])
    total = int(session["total_duration_seconds"])
    session["completed_duration_seconds"] = completed
    session["remaining_duration_seconds"] = max(0, total - completed)
    session["updated_at_ms"] = _now_ms()
    session["updated_at_utc"] = _utc_iso(session["updated_at_ms"])
    manifest["aggregate"] = aggregate
    orphan_files = _find_orphan_files(session_dir, segments)
    manifest["orphan_files"] = orphan_files
    blockers: list[str] = []
    if aggregate["blocked_segment_count"]:
        blockers.append("segment_data_blocked")
    if aggregate["boundary_gap_total_ms"]:
        blockers.append("boundary_gap_present")
    if aggregate["boundary_trade_sequence_breaks"]:
        blockers.append("boundary_trade_sequence_break")
    if aggregate["boundary_book_ticker_sequence_breaks"]:
        blockers.append("boundary_book_ticker_sequence_break")
    if aggregate["boundary_depth_sequence_breaks"]:
        blockers.append("boundary_depth_sequence_break")
    if orphan_files:
        blockers.append("orphan_files_present")
    if session["status"] == "error":
        blockers.append("session_error")
    session["blockers"] = blockers
    session["continuous_gate_eligible"] = session["status"] == "complete" and not blockers
    if session["status"] not in {"complete", "error"}:
        session["verdict"] = "incomplete"
    elif blockers:
        session["verdict"] = "block_data"
    else:
        session["verdict"] = "pass_data_smoke"

    grouped: dict[str, list[dict[str, Any]]] = {}
    for segment in segments:
        grouped.setdefault(str(segment["utc_day"]), []).append(segment)
    last_day = max(grouped, default=None)
    days: list[dict[str, Any]] = []
    for utc_day, day_segments in sorted(grouped.items()):
        daily_path = session_dir / "daily" / f"{utc_day}.json"
        daily_relpath = _relative_child_path(session_dir, daily_path)
        daily_payload = {
            "schema_version": LIVE_COLLECTOR_SESSION_VERSION,
            "session_artifact_path": manifest["artifact_path"],
            "daily_artifact_path": daily_relpath,
            "utc_day": utc_day,
            "closed": session["status"] == "complete" or utc_day != last_day,
            "contract_hash": manifest["contract_hash"],
            "segments": day_segments,
            "aggregate": _summarize_segments(day_segments),
        }
        _atomic_write_json(daily_path, daily_payload)
        days.append(
            {
                "utc_day": utc_day,
                "artifact_path": daily_relpath,
                "closed": daily_payload["closed"],
                "aggregate": daily_payload["aggregate"],
            }
        )
    manifest["days"] = days


def _write_manifest(manifest: dict[str, Any], session_dir: Path) -> None:
    _refresh_manifest(manifest, session_dir)
    _atomic_write_json(session_dir / "alpha_agent_live_collector_session.json", manifest)


def _new_manifest(
    session_dir: Path,
    collector_config: LiveCollectorConfig,
    session_config: LiveCollectorSessionConfig,
) -> dict[str, Any]:
    started_at_ms = _now_ms()
    frozen_collector = replace(collector_config, duration_seconds=session_config.segment_duration_seconds)
    artifact_path = "alpha_agent_live_collector_session.json"
    return {
        "schema_version": LIVE_COLLECTOR_SESSION_VERSION,
        "artifact_path": artifact_path,
        "session_dir": ".",
        "session_id": session_dir.name,
        "contract_hash": _contract_hash(frozen_collector, session_config),
        "meta": {
            "research_only": True,
            "private_exchange_data": False,
            "orders_allowed": False,
            "training_allowed": False,
            "holdout_role": "forward_research_data_only",
            "utc_boundary_clipping": True,
            "atomic_segment_close": True,
            "resumable": True,
            "segment_connection_mode": "continuous_in_stream_rotation",
            "boundary_gaps_fail_closed": True,
            "path_contract": SESSION_PATH_CONTRACT,
        },
        "collector_config": frozen_collector.to_dict(),
        "session": {
            "status": "running",
            "verdict": "incomplete",
            "started_at_ms": started_at_ms,
            "started_at_utc": _utc_iso(started_at_ms),
            "updated_at_ms": started_at_ms,
            "updated_at_utc": _utc_iso(started_at_ms),
            "total_duration_seconds": session_config.total_duration_seconds,
            "segment_duration_seconds": session_config.segment_duration_seconds,
            "completed_duration_seconds": 0,
            "remaining_duration_seconds": session_config.total_duration_seconds,
            "resume_count": 0,
            "blockers": [],
            "continuous_gate_eligible": False,
        },
        "segments": [],
        "days": [],
        "aggregate": _summarize_segments([]),
        "orphan_files": [],
        "error_history": [],
    }


def _continue_session(
    settings: Settings,
    session_dir: Path,
    manifest: dict[str, Any],
    *,
    max_segments: int,
) -> dict[str, Any]:
    if max_segments < 0:
        raise ValueError("max_segments must be non-negative")
    collector_config = _collector_config_from_payload(manifest["collector_config"])
    session = manifest["session"]
    segments_run = 0
    session["status"] = "running"
    session.pop("last_error", None)
    _write_manifest(manifest, session_dir)
    try:
        planned_segments: list[tuple[LiveCollectorConfig, str]] = []
        planned_metadata: list[dict[str, int]] = []
        planned_remaining = int(session["remaining_duration_seconds"])
        planned_now_ms = _now_ms()
        while planned_remaining > 0:
            if max_segments and len(planned_segments) >= max_segments:
                break
            requested_duration = _segment_duration_seconds(
                int(session["segment_duration_seconds"]),
                planned_remaining,
                planned_now_ms,
            )
            segment_index = len(manifest["segments"]) + len(planned_segments)
            segment_dir = _allocate_segment_dir(session_dir, segment_index, planned_now_ms)
            segment_config = replace(collector_config, duration_seconds=requested_duration)
            planned_segments.append((segment_config, str(segment_dir)))
            planned_metadata.append(
                {"index": segment_index, "requested_duration_seconds": requested_duration}
            )
            planned_remaining -= requested_duration
            planned_now_ms += requested_duration * 1000

        def segment_completed(result: dict[str, Any]) -> None:
            nonlocal segments_run
            metadata = planned_metadata[segments_run]
            segment_index = int(metadata["index"])
            requested_duration = int(metadata["requested_duration_seconds"])
            entry = _segment_entry(
                result,
                requested_duration,
                segment_index,
                session_dir=session_dir,
            )
            if manifest["segments"]:
                previous = manifest["segments"][-1]
                market_gap_ms, market_gap_by_route_ms = _boundary_gap(previous, entry)
                connection_restarts = _boundary_connection_restarts(previous, entry)
                entry["boundary_market_inter_event_ms"] = market_gap_ms
                entry["boundary_market_inter_event_by_route_ms"] = market_gap_by_route_ms
                entry["connection_restarted_routes"] = connection_restarts
                entry["boundary_sequence_breaks"] = _boundary_sequence_breaks(previous, entry)
                entry["boundary_gap_ms"] = market_gap_ms if connection_restarts is None or connection_restarts else 0
                entry["boundary_gap_by_route_ms"] = (
                    market_gap_by_route_ms if connection_restarts is None or connection_restarts else {}
                )
            else:
                entry["boundary_gap_ms"] = 0
                entry["boundary_gap_by_route_ms"] = {}
                entry["boundary_market_inter_event_ms"] = 0
                entry["boundary_market_inter_event_by_route_ms"] = {}
                entry["connection_restarted_routes"] = []
                entry["boundary_sequence_breaks"] = {"trades": [], "book_ticker": [], "depth": []}
            manifest["segments"].append(entry)
            segments_run += 1
            completed = sum(int(item["requested_duration_seconds"]) for item in manifest["segments"])
            if completed >= int(session["total_duration_seconds"]):
                session["status"] = "complete"
            elif max_segments and segments_run >= max_segments:
                session["status"] = "paused"
            _write_manifest(manifest, session_dir)

        if planned_segments:
            run_live_collector_segments(
                settings,
                planned_segments,
                on_segment_complete=segment_completed,
            )
        if session["status"] == "running":
            session["status"] = "complete" if planned_remaining == 0 else "paused"
        _write_manifest(manifest, session_dir)
        return manifest
    except BaseException as exc:
        session["status"] = "error"
        error_at_ms = _now_ms()
        error = {
            "at_ms": error_at_ms,
            "at_utc": _utc_iso(error_at_ms),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        session["last_error"] = error
        manifest["error_history"].append(error)
        _write_manifest(manifest, session_dir)
        raise


def run_live_collector_session(
    settings: Settings,
    collector_config: LiveCollectorConfig,
    session_config: LiveCollectorSessionConfig,
    *,
    explicit_output_dir: str | None = None,
    max_segments: int = 0,
) -> dict[str, Any]:
    collector_config.validate()
    session_config.validate()
    session_dir = _resolve_session_dir(settings, explicit_output_dir, resume=False)
    artifact_path = session_dir / "alpha_agent_live_collector_session.json"
    if artifact_path.exists():
        raise FileExistsError(f"collector session already exists: {artifact_path}")
    with _session_lock(session_dir):
        manifest = _new_manifest(session_dir, collector_config, session_config)
        _write_manifest(manifest, session_dir)
        return _continue_session(settings, session_dir, manifest, max_segments=max_segments)


def resume_live_collector_session(
    settings: Settings,
    session_dir: str,
    *,
    max_segments: int = 0,
) -> dict[str, Any]:
    resolved_dir = _resolve_session_dir(settings, session_dir, resume=True)
    artifact_path = resolved_dir / "alpha_agent_live_collector_session.json"
    with _session_lock(resolved_dir):
        manifest = json.loads(artifact_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != LIVE_COLLECTOR_SESSION_VERSION:
            raise ValueError("unsupported collector session schema")
        collector_config = _collector_config_from_payload(manifest["collector_config"])
        session_config = LiveCollectorSessionConfig(
            total_duration_seconds=int(manifest["session"]["total_duration_seconds"]),
            segment_duration_seconds=int(manifest["session"]["segment_duration_seconds"]),
        )
        if manifest.get("contract_hash") != _contract_hash(collector_config, session_config):
            raise ValueError("collector session contract hash mismatch")
        if manifest["session"]["status"] == "complete":
            _write_manifest(manifest, resolved_dir)
            return manifest
        manifest["session"]["resume_count"] = int(manifest["session"].get("resume_count") or 0) + 1
        return _continue_session(settings, resolved_dir, manifest, max_segments=max_segments)


def mark_live_collector_session_superseded(
    session_dir: str | Path,
    replacement_session_id: str,
) -> dict[str, Any]:
    resolved_dir = Path(session_dir).expanduser().resolve()
    artifact_path = resolved_dir / "alpha_agent_live_collector_session.json"
    manifest = json.loads(artifact_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") not in (
        LIVE_COLLECTOR_SESSION_VERSION,
        *LEGACY_LIVE_COLLECTOR_SESSION_VERSIONS,
    ):
        raise ValueError("unsupported collector session schema")
    session = manifest.get("session") if isinstance(manifest.get("session"), dict) else {}
    if session.get("status") == "complete":
        raise ValueError("a complete collector session cannot be superseded")
    lock_path = resolved_dir / ".collector-session.lock"
    if lock_path.exists():
        try:
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            lock = {}
        if _process_is_alive(int(lock.get("pid") or 0)):
            raise RuntimeError("collector session is still running")
        stale_path = resolved_dir / f".collector-session.lock.superseded-{_now_ms()}"
        os.replace(lock_path, stale_path)
    stopped_at_ms = _now_ms()
    session.update(
        {
            "status": "superseded",
            "verdict": "incomplete",
            "updated_at_ms": stopped_at_ms,
            "updated_at_utc": _utc_iso(stopped_at_ms),
            "stopped_at_ms": stopped_at_ms,
            "stopped_at_utc": _utc_iso(stopped_at_ms),
            "continuous_gate_eligible": False,
            "blockers": ["superseded_by_replacement_session"],
        }
    )
    manifest["supersession"] = {
        "replacement_session_id": replacement_session_id,
        "raw_segments_must_not_be_concatenated": True,
        "reason": "collector_migrated_to_vps",
        "recorded_at_ms": stopped_at_ms,
        "recorded_at_utc": _utc_iso(stopped_at_ms),
    }
    _atomic_write_json(artifact_path, manifest)
    return manifest


def verify_live_collector_session(
    session_dir: str | Path,
    *,
    minimum_duration_seconds: int = 7 * 24 * 60 * 60,
    required_symbols: tuple[str, ...] = S3_REQUIRED_SYMBOLS,
    required_streams: tuple[str, ...] = S3_REQUIRED_STREAMS,
    deep_replay: bool = True,
) -> dict[str, Any]:
    """Verify a closed S3 session without mutating its manifests or raw data."""

    if minimum_duration_seconds <= 0:
        raise ValueError("minimum_duration_seconds must be positive")
    resolved_dir = Path(session_dir).expanduser().resolve()
    manifest_path = resolved_dir / "alpha_agent_live_collector_session.json"
    blockers: list[str] = []

    def block(reason: str) -> None:
        if reason not in blockers:
            blockers.append(reason)

    def checked_int(value: Any, reason: str, *, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            block(reason)
            return default

    report: dict[str, Any] = {
        "schema_version": LIVE_COLLECTOR_VERIFICATION_VERSION,
        "session_dir": str(resolved_dir),
        "session_artifact_path": str(manifest_path),
        "minimum_duration_seconds": minimum_duration_seconds,
        "required_symbols": list(required_symbols),
        "required_streams": list(required_streams),
        "deep_replay": deep_replay,
        "verdict": "block_data",
        "blockers": blockers,
        "contract": {},
        "segments": [],
        "days": [],
    }
    if not deep_replay:
        block("deep_replay_required")
    if not manifest_path.is_file():
        block("session_manifest_missing")
        return report
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        block("session_manifest_invalid_json")
        return report
    if not isinstance(manifest, dict):
        block("session_manifest_not_object")
        return report

    session_schema = str(manifest.get("schema_version") or "")
    schema_ok = session_schema in (LIVE_COLLECTOR_SESSION_VERSION, *LEGACY_LIVE_COLLECTOR_SESSION_VERSIONS)
    if not schema_ok:
        block("session_schema_unsupported")
    artifact_path, artifact_path_safe = _resolved_child_path(resolved_dir, manifest.get("artifact_path"))
    if not artifact_path_safe or artifact_path != manifest_path:
        block("session_artifact_path_mismatch")
    declared_dir, declared_dir_safe = _resolved_child_path(resolved_dir, manifest.get("session_dir"))
    if not declared_dir_safe or declared_dir != resolved_dir:
        block("session_dir_mismatch")

    meta = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}
    expected_meta = {
        "research_only": True,
        "private_exchange_data": False,
        "orders_allowed": False,
        "training_allowed": False,
        "holdout_role": "forward_research_data_only",
        "utc_boundary_clipping": True,
        "atomic_segment_close": True,
        "segment_connection_mode": "continuous_in_stream_rotation",
        "boundary_gaps_fail_closed": True,
    }
    if session_schema == LIVE_COLLECTOR_SESSION_VERSION:
        expected_meta["path_contract"] = SESSION_PATH_CONTRACT
    meta_mismatches = sorted(key for key, expected in expected_meta.items() if meta.get(key) != expected)
    if meta_mismatches:
        block("session_meta_mismatch")

    session = manifest.get("session") if isinstance(manifest.get("session"), dict) else {}
    status = str(session.get("status") or "unknown")
    total_duration = checked_int(session.get("total_duration_seconds"), "session_numeric_fields_invalid")
    completed_duration = checked_int(session.get("completed_duration_seconds"), "session_numeric_fields_invalid")
    remaining_duration = checked_int(session.get("remaining_duration_seconds"), "session_numeric_fields_invalid")
    resume_count = checked_int(session.get("resume_count"), "session_numeric_fields_invalid")
    if status != "complete":
        block("session_not_complete")
    if status == "superseded":
        block("session_superseded")
    if session.get("verdict") != "pass_data_smoke":
        block("session_verdict_not_pass")
    if session.get("continuous_gate_eligible") is not True:
        block("session_not_continuous_gate_eligible")
    declared_session_blockers = list(session.get("blockers") or [])
    expected_supersession = status == "superseded" and declared_session_blockers == [
        "superseded_by_replacement_session"
    ]
    if declared_session_blockers and not expected_supersession:
        block("session_declared_blockers")
    if resume_count:
        block("session_resumed")
    if manifest.get("error_history"):
        block("session_error_history_present")
    if total_duration < minimum_duration_seconds:
        block("minimum_duration_not_met")
    if completed_duration != total_duration or remaining_duration != 0:
        block("session_duration_incomplete")

    collector_payload = manifest.get("collector_config")
    collector_config: LiveCollectorConfig | None = None
    session_config: LiveCollectorSessionConfig | None = None
    contract_hash_expected: str | None = None
    try:
        if not isinstance(collector_payload, dict):
            raise ValueError("collector_config must be an object")
        collector_config = _collector_config_from_payload(collector_payload)
        collector_config.validate()
        session_config = LiveCollectorSessionConfig(
            total_duration_seconds=total_duration,
            segment_duration_seconds=int(session.get("segment_duration_seconds") or 0),
        )
        session_config.validate()
        if session_schema == LIVE_COLLECTOR_SESSION_VERSION:
            contract_hash_expected = _contract_hash(collector_config, session_config)
        else:
            contract_hash_expected = _contract_hash_from_payload(collector_payload, session_config)
    except (TypeError, ValueError):
        block("session_contract_invalid")
    contract_hash_actual = str(manifest.get("contract_hash") or "")
    if contract_hash_expected is not None and contract_hash_actual != contract_hash_expected:
        block("session_contract_hash_mismatch")
    if collector_config is not None:
        if tuple(collector_config.symbols) != tuple(required_symbols):
            block("required_symbols_mismatch")
        if tuple(collector_config.streams) != tuple(required_streams):
            block("required_streams_mismatch")
        strict_thresholds = (
            collector_config.depth_speed_ms == 100
            and collector_config.depth_limit == 1000
            and collector_config.snapshot_interval_seconds <= 30
            and collector_config.future_tolerance_ms <= 1_000
            and collector_config.stale_event_ms <= 5_000
            and collector_config.max_stale_event_rate <= 0.01
            and collector_config.max_trade_gap_rate <= 0.0001
            and collector_config.max_depth_sequence_breaks == 0
            and collector_config.max_connection_errors <= 3
            and collector_config.max_snapshot_error_rate <= 0.01
        )
        if not strict_thresholds:
            block("collector_thresholds_not_strict")
    report["contract"] = {
        "schema_ok": schema_ok,
        "hash_actual": contract_hash_actual,
        "hash_expected": contract_hash_expected,
        "hash_match": contract_hash_expected is not None and contract_hash_actual == contract_hash_expected,
        "meta_mismatches": meta_mismatches,
        "status": status,
        "total_duration_seconds": total_duration,
        "completed_duration_seconds": completed_duration,
        "remaining_duration_seconds": remaining_duration,
        "resume_count": resume_count,
    }

    segments = manifest.get("segments") if isinstance(manifest.get("segments"), list) else []
    if not segments:
        block("session_segments_missing")
    if [segment.get("index") for segment in segments if isinstance(segment, dict)] != list(range(len(segments))):
        block("segment_indices_not_contiguous")
    recomputed_aggregate: dict[str, Any] | None = None
    try:
        recomputed_aggregate = _summarize_segments(segments)
    except (KeyError, TypeError, ValueError):
        block("session_segments_invalid")
    if recomputed_aggregate is not None and manifest.get("aggregate") != recomputed_aggregate:
        block("session_aggregate_mismatch")
    if recomputed_aggregate is not None and int(recomputed_aggregate["requested_duration_seconds"]) != total_duration:
        block("segment_duration_sum_mismatch")

    dynamic_orphans = (
        _find_orphan_files(resolved_dir, segments)
        if resolved_dir.is_dir() and all(isinstance(segment, dict) for segment in segments)
        else []
    )
    declared_orphans = sorted(str(path) for path in (manifest.get("orphan_files") or []))
    if status == "complete" and (dynamic_orphans or declared_orphans):
        block("orphan_files_present")
    if status == "complete" and (resolved_dir / ".collector-session.lock").exists():
        block("session_lock_present_after_completion")
    report["dynamic_orphan_files"] = dynamic_orphans
    report["declared_orphan_files"] = declared_orphans
    report["session_lock_present"] = (resolved_dir / ".collector-session.lock").exists()

    for position, segment in enumerate(segments):
        segment_blockers: list[str] = []

        def segment_block(reason: str) -> None:
            code = f"segment_{position}_{reason}"
            if code not in segment_blockers:
                segment_blockers.append(code)
            block(code)

        segment_report: dict[str, Any] = {
            "index": position,
            "artifact_path": segment.get("artifact_path") if isinstance(segment, dict) else None,
            "raw_event_path": segment.get("raw_event_path") if isinstance(segment, dict) else None,
            "deep_replay_match": None,
            "blockers": segment_blockers,
        }
        report["segments"].append(segment_report)
        if not isinstance(segment, dict):
            segment_block("manifest_entry_invalid")
            continue
        artifact_file, artifact_safe = _resolved_child_path(resolved_dir, segment.get("artifact_path"))
        raw_file, raw_safe = _resolved_child_path(resolved_dir, segment.get("raw_event_path"))
        if not artifact_safe:
            segment_block("artifact_path_outside_session")
        if not raw_safe:
            segment_block("raw_path_outside_session")
        if artifact_file is None or not artifact_file.is_file():
            segment_block("artifact_missing")
        if raw_file is None or not raw_file.is_file():
            segment_block("raw_missing")
        if segment_blockers:
            continue
        try:
            artifact = json.loads(artifact_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            segment_block("artifact_invalid_json")
            continue
        if not isinstance(artifact, dict):
            segment_block("artifact_not_object")
            continue
        if artifact.get("schema_version") != LIVE_COLLECTOR_VERSION:
            segment_block("artifact_schema_mismatch")
        try:
            artifact_config = _collector_config_from_payload(artifact["config"])
            artifact_config.validate()
        except (KeyError, TypeError, ValueError):
            segment_block("config_invalid")
            continue
        try:
            requested_duration = int(segment.get("requested_duration_seconds"))
        except (TypeError, ValueError):
            segment_block("duration_invalid")
            continue
        try:
            wall_duration = float(segment.get("wall_duration_seconds"))
            market_events = int(segment.get("market_events"))
        except (TypeError, ValueError):
            segment_block("capture_numeric_fields_invalid")
            continue
        if wall_duration < max(0, requested_duration - 2):
            segment_block("wall_duration_too_short")
        if market_events <= 0:
            segment_block("market_events_missing")
        if artifact_config.duration_seconds != requested_duration:
            segment_block("duration_config_mismatch")
        if collector_config is not None and _collector_contract(artifact_config) != _collector_contract(collector_config):
            segment_block("collector_contract_mismatch")
        computed_config_hash = _config_hash(artifact_config)
        if (
            segment.get("config_hash") != computed_config_hash
            or (artifact.get("meta") or {}).get("config_hash") != computed_config_hash
        ):
            segment_block("config_hash_mismatch")
        artifact_meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
        if artifact_meta.get("path_contract") == "segment_relative_v1":
            artifact_self = (artifact_file.parent / str(artifact.get("artifact_relpath") or "")).resolve()
            raw_self = (artifact_file.parent / str(artifact.get("raw_event_relpath") or "")).resolve()
        else:
            artifact_self = Path(str(artifact.get("artifact_path") or "")).resolve()
            raw_self = Path(str(artifact.get("raw_event_path") or "")).resolve()
        if artifact_self != artifact_file:
            segment_block("artifact_self_path_mismatch")
        if raw_self != raw_file:
            segment_block("raw_self_path_mismatch")
        actual_bytes = raw_file.stat().st_size
        expected_artifact_meta = {
            "research_only": True,
            "private_exchange_data": False,
            "orders_allowed": False,
            "training_allowed": False,
            "holdout_role": "forward_research_data_only",
            "point_in_time": True,
            "event_time_audited": True,
            "replayable": True,
        }
        if any(artifact_meta.get(key) != value for key, value in expected_artifact_meta.items()):
            segment_block("artifact_meta_mismatch")
        try:
            segment_raw_bytes = int(segment.get("raw_bytes"))
            artifact_raw_bytes = int(artifact_meta.get("raw_bytes"))
        except (TypeError, ValueError):
            segment_block("raw_bytes_invalid")
            segment_raw_bytes = artifact_raw_bytes = -1
        if actual_bytes != segment_raw_bytes or actual_bytes != artifact_raw_bytes:
            segment_block("raw_bytes_mismatch")
        try:
            actual_sha = _sha256_file(raw_file)
        except OSError:
            segment_block("raw_sha256_failed")
            continue
        expected_sha = str(segment.get("raw_sha256") or "")
        if actual_sha != expected_sha or artifact_meta.get("raw_sha256") != expected_sha:
            segment_block("raw_sha256_mismatch")
        if artifact.get("audit") != segment.get("audit"):
            segment_block("audit_manifest_mismatch")
        if artifact.get("audit", {}).get("verdict") != "pass_data_smoke" or segment.get("verdict") != "pass_data_smoke":
            segment_block("audit_verdict_not_pass")
        if artifact.get("audit", {}).get("blockers") or segment.get("blockers"):
            segment_block("audit_declared_blockers")
        audit = artifact.get("audit") if isinstance(artifact.get("audit"), dict) else {}
        strict_audit_values = {
            "connection_errors": (audit.get("connections") or {}).get("errors"),
            "snapshot_errors": (audit.get("snapshots") or {}).get("errors"),
            "trade_missing_ids": (audit.get("trades") or {}).get("missing_ids"),
            "trade_out_of_order": (audit.get("trades") or {}).get("out_of_order"),
            "book_ticker_out_of_order": (audit.get("book_ticker") or {}).get("out_of_order"),
            "depth_sequence_breaks": (audit.get("depth") or {}).get("sequence_breaks"),
            "depth_snapshot_resyncs": (audit.get("depth") or {}).get("snapshot_resyncs"),
            "depth_buffer_overflows": (audit.get("depth") or {}).get("buffer_overflows"),
            "depth_invalid_levels": (audit.get("depth") or {}).get("invalid_levels"),
            "depth_empty_books": (audit.get("depth") or {}).get("empty_books"),
            "depth_crossed_books": (audit.get("depth") or {}).get("crossed_books"),
            "event_time_missing": (audit.get("event_time") or {}).get("missing"),
            "event_time_future": (audit.get("event_time") or {}).get("future"),
            "event_time_stale": (audit.get("event_time") or {}).get("stale"),
        }
        if any(value != 0 for value in strict_audit_values.values()):
            segment_block("strict_audit_nonzero")
        if (audit.get("depth") or {}).get("unanchored_symbols"):
            segment_block("depth_unanchored")
        by_symbol = audit.get("by_symbol") if isinstance(audit.get("by_symbol"), dict) else {}
        snapshots_by_symbol = (audit.get("snapshots") or {}).get("by_symbol") or {}
        for symbol in required_symbols:
            symbol_counts = by_symbol.get(symbol) or {}
            try:
                stream_missing = any(
                    int(symbol_counts.get(event_type) or 0) <= 0
                    for event_type in ("bookTicker", "aggTrade", "depthUpdate")
                )
                snapshot_missing = int(snapshots_by_symbol.get(symbol) or 0) <= 0
            except (TypeError, ValueError):
                segment_block(f"required_symbol_counts_invalid_{symbol}")
                continue
            if stream_missing:
                segment_block(f"required_symbol_stream_missing_{symbol}")
            if snapshot_missing:
                segment_block(f"required_symbol_snapshot_missing_{symbol}")
        if segment.get("segment_connection_mode") != "continuous_in_stream_rotation":
            segment_block("connection_mode_mismatch")
        sequence_boundaries = (
            segment.get("sequence_boundaries") if isinstance(segment.get("sequence_boundaries"), dict) else {}
        )
        public_boundaries = (
            sequence_boundaries.get("public") if isinstance(sequence_boundaries.get("public"), dict) else {}
        )
        market_boundaries = (
            sequence_boundaries.get("market") if isinstance(sequence_boundaries.get("market"), dict) else {}
        )
        public_books = public_boundaries.get("book_ticker") or {}
        public_depth = public_boundaries.get("depth") or {}
        market_trades = market_boundaries.get("trades") or {}
        for symbol in required_symbols:
            if symbol not in public_books:
                segment_block(f"boundary_book_ticker_missing_{symbol}")
            if symbol not in public_depth:
                segment_block(f"boundary_depth_missing_{symbol}")
            if f"{symbol}:aggTrade" not in market_trades:
                segment_block(f"boundary_agg_trade_missing_{symbol}")
        try:
            artifact_for_entry = dict(artifact)
            if session_schema == LIVE_COLLECTOR_SESSION_VERSION:
                artifact_for_entry["artifact_path"] = segment.get("artifact_path")
                artifact_for_entry["raw_event_path"] = segment.get("raw_event_path")
            rebuilt_entry = _segment_entry(
                artifact_for_entry,
                requested_duration,
                position,
                session_dir=resolved_dir if session_schema == LIVE_COLLECTOR_SESSION_VERSION else None,
            )
        except (KeyError, TypeError, ValueError):
            segment_block("manifest_rebuild_failed")
        else:
            for key, value in rebuilt_entry.items():
                if segment.get(key) != value:
                    segment_block(f"manifest_field_mismatch_{key}")
        if deep_replay:
            try:
                replay_audit = audit_event_file(raw_file, artifact_config)
            except (EOFError, OSError, ValueError, json.JSONDecodeError):
                segment_block("deep_replay_failed")
            else:
                replay_match = replay_audit == artifact.get("audit")
                segment_report["deep_replay_match"] = replay_match
                if not replay_match:
                    segment_block("deep_replay_mismatch")
        segment_report["raw_bytes"] = actual_bytes
        segment_report["raw_sha256"] = actual_sha

    for position, segment in enumerate(segments):
        if not isinstance(segment, dict):
            continue
        if position == 0:
            expected_boundary = {
                "boundary_gap_ms": 0,
                "boundary_gap_by_route_ms": {},
                "boundary_market_inter_event_ms": 0,
                "boundary_market_inter_event_by_route_ms": {},
                "connection_restarted_routes": [],
                "boundary_sequence_breaks": {"trades": [], "book_ticker": [], "depth": []},
            }
        else:
            previous = segments[position - 1]
            if not isinstance(previous, dict):
                continue
            try:
                market_gap_ms, market_gap_by_route_ms = _boundary_gap(previous, segment)
                connection_restarts = _boundary_connection_restarts(previous, segment)
                sequence_breaks = _boundary_sequence_breaks(previous, segment)
            except (KeyError, TypeError, ValueError):
                block(f"segment_{position}_boundary_invalid")
                continue
            expected_boundary = {
                "boundary_market_inter_event_ms": market_gap_ms,
                "boundary_market_inter_event_by_route_ms": market_gap_by_route_ms,
                "connection_restarted_routes": connection_restarts,
                "boundary_sequence_breaks": sequence_breaks,
                "boundary_gap_ms": market_gap_ms if connection_restarts is None or connection_restarts else 0,
                "boundary_gap_by_route_ms": (
                    market_gap_by_route_ms if connection_restarts is None or connection_restarts else {}
                ),
            }
        for key, value in expected_boundary.items():
            if segment.get(key) != value:
                block(f"segment_{position}_boundary_mismatch_{key}")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for segment in segments:
        if isinstance(segment, dict):
            grouped.setdefault(str(segment.get("utc_day") or ""), []).append(segment)
    day_entries = manifest.get("days") if isinstance(manifest.get("days"), list) else []
    if [str(day.get("utc_day") or "") for day in day_entries if isinstance(day, dict)] != sorted(grouped):
        block("daily_index_mismatch")
    for day in day_entries:
        if not isinstance(day, dict):
            block("daily_manifest_entry_invalid")
            continue
        utc_day = str(day.get("utc_day") or "")
        day_blockers: list[str] = []

        def day_block(reason: str) -> None:
            code = f"day_{utc_day}_{reason}"
            day_blockers.append(code)
            block(code)

        day_report = {"utc_day": utc_day, "artifact_path": day.get("artifact_path"), "blockers": day_blockers}
        report["days"].append(day_report)
        day_file, day_safe = _resolved_child_path(resolved_dir, day.get("artifact_path"))
        if not day_safe:
            day_block("path_outside_session")
        if day_file is None or not day_file.is_file():
            day_block("artifact_missing")
            continue
        try:
            day_payload = json.loads(day_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            day_block("artifact_invalid_json")
            continue
        expected_segments = grouped.get(utc_day, [])
        try:
            expected_aggregate = _summarize_segments(expected_segments)
        except (KeyError, TypeError, ValueError):
            day_block("segments_invalid")
            continue
        if day_payload.get("schema_version") != session_schema:
            day_block("schema_mismatch")
        daily_self, daily_self_safe = _resolved_child_path(resolved_dir, day_payload.get("daily_artifact_path"))
        if not daily_self_safe or daily_self != day_file:
            day_block("self_path_mismatch")
        session_self, session_self_safe = _resolved_child_path(
            resolved_dir,
            day_payload.get("session_artifact_path"),
        )
        if not session_self_safe or session_self != manifest_path:
            day_block("session_path_mismatch")
        if day_payload.get("contract_hash") != contract_hash_actual:
            day_block("contract_hash_mismatch")
        if day_payload.get("segments") != expected_segments:
            day_block("segments_mismatch")
        if day_payload.get("aggregate") != expected_aggregate or day.get("aggregate") != expected_aggregate:
            day_block("aggregate_mismatch")
        if status == "complete" and (day_payload.get("closed") is not True or day.get("closed") is not True):
            day_block("not_closed")

    report["aggregate"] = recomputed_aggregate
    expected_incomplete_blockers = {
        "session_not_complete",
        "session_verdict_not_pass",
        "session_not_continuous_gate_eligible",
        "session_duration_incomplete",
        "session_segments_missing",
        "segment_duration_sum_mismatch",
        "session_superseded",
    }
    if status != "complete" and set(blockers).issubset(expected_incomplete_blockers):
        report["verdict"] = "incomplete"
    elif not blockers:
        report["verdict"] = "pass_data_gate"
    return report
