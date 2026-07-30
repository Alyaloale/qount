from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from datetime import timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import shutil
import subprocess
from typing import Any

from qount.alpha_agents.live_collector import _config_hash
from qount.alpha_agents.live_collector import _sha256_file
from qount.alpha_agents.live_collector import audit_event_file
from qount.alpha_agents.live_collector_session import _collector_config_from_payload
from qount.alpha_agents.live_collector_session import _resolved_child_path
from qount.alpha_agents.live_collector_session import _summarize_segments
from qount.alpha_agents.live_collector_session import LIVE_COLLECTOR_SESSION_VERSION
from qount.alpha_agents.live_collector_session import SESSION_PATH_CONTRACT


OFFLOAD_RECEIPT_VERSION = "alpha_agent_live_collector_offload_receipt_v0.1"
LOCAL_RECEIPTS_FILENAME = "alpha_collector_offload_receipts.jsonl"
REMOTE_RECEIPTS_FILENAME = "offload_receipts.jsonl"
_SAFE_HOST = re.compile(r"^[A-Za-z0-9_.:@-]+$")
_SAFE_SESSION_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
_SAFE_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                value = json.loads(line)
                if isinstance(value, dict):
                    events.append(value)
    return events


@contextmanager
def _exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _validated_remote_session_dir(value: str) -> str:
    path = PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("remote session directory must be an absolute path without parent traversal")
    if any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in path.parts if part != "/"):
        raise ValueError("remote session directory contains unsupported characters")
    return path.as_posix()


def _validated_host(value: str) -> str:
    if not _SAFE_HOST.fullmatch(value):
        raise ValueError("remote host contains unsupported characters")
    return value


def _session_id(manifest: dict[str, Any]) -> str:
    value = str(manifest.get("session_id") or "")
    if not _SAFE_SESSION_ID.fullmatch(value):
        raise ValueError("collector manifest has an invalid session_id")
    return value


def _receipt_id(session_id: str, segment_index: int, raw_sha256: str) -> str:
    raw = f"{session_id}:{segment_index}:{raw_sha256}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _segment_paths(
    session_dir: Path,
    segment: dict[str, Any],
) -> tuple[Path, Path, str]:
    artifact_path, artifact_safe = _resolved_child_path(session_dir, segment.get("artifact_path"))
    raw_path, raw_safe = _resolved_child_path(session_dir, segment.get("raw_event_path"))
    if artifact_path is None or raw_path is None or not artifact_safe or not raw_safe:
        raise ValueError("segment paths must stay inside the session directory")
    if artifact_path.name != "alpha_agent_live_collector.json" or raw_path.name != "events.jsonl.gz":
        raise ValueError("segment paths use unexpected filenames")
    if artifact_path.parent != raw_path.parent:
        raise ValueError("segment artifact and raw data must share one directory")
    relative_dir = artifact_path.parent.relative_to(session_dir.resolve()).as_posix()
    if not re.fullmatch(r"segments/[0-9]{4}-[A-Za-z0-9_.-]+", relative_dir):
        raise ValueError("segment directory does not match the collector allocation contract")
    return artifact_path, raw_path, relative_dir


def verify_offload_segment(
    session_dir: str | Path,
    manifest: dict[str, Any],
    segment_index: int,
) -> dict[str, Any]:
    resolved_dir = Path(session_dir).expanduser().resolve()
    blockers: list[str] = []

    def block(reason: str) -> None:
        if reason not in blockers:
            blockers.append(reason)

    segments = manifest.get("segments") if isinstance(manifest.get("segments"), list) else []
    if segment_index < 0 or segment_index >= len(segments):
        raise IndexError(f"segment index out of range: {segment_index}")
    segment = segments[segment_index]
    if not isinstance(segment, dict) or segment.get("index") != segment_index:
        raise ValueError("segment manifest entry is invalid")
    collector_payload = manifest.get("collector_config")
    if not isinstance(collector_payload, dict):
        raise ValueError("collector_config must be an object")
    collector_config = _collector_config_from_payload(collector_payload)
    requested_duration = int(segment.get("requested_duration_seconds") or 0)
    segment_config = collector_config.__class__(
        **{
            **collector_config.to_dict(),
            "symbols": tuple(collector_config.symbols),
            "streams": tuple(collector_config.streams),
            "duration_seconds": requested_duration,
        }
    )
    segment_config.validate()
    artifact_path, raw_path, relative_dir = _segment_paths(resolved_dir, segment)
    if not artifact_path.is_file():
        block("artifact_missing")
    if not raw_path.is_file():
        block("raw_missing")
    artifact: dict[str, Any] = {}
    if not blockers:
        try:
            value = json.loads(artifact_path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("artifact must be an object")
            artifact = value
        except (OSError, ValueError, json.JSONDecodeError):
            block("artifact_invalid")
    artifact_meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
    if artifact and artifact_meta.get("path_contract") != "segment_relative_v1":
        block("artifact_not_relocatable")
    if artifact and (artifact_path.parent / str(artifact.get("artifact_relpath") or "")).resolve() != artifact_path:
        block("artifact_self_path_mismatch")
    if artifact and (artifact_path.parent / str(artifact.get("raw_event_relpath") or "")).resolve() != raw_path:
        block("raw_self_path_mismatch")
    expected_sha = str(segment.get("raw_sha256") or "")
    actual_sha: str | None = None
    actual_bytes: int | None = None
    if raw_path.is_file():
        actual_bytes = raw_path.stat().st_size
        actual_sha = _sha256_file(raw_path)
        if actual_sha != expected_sha or artifact_meta.get("raw_sha256") != expected_sha:
            block("raw_sha256_mismatch")
        if actual_bytes != int(segment.get("raw_bytes") or -1) or actual_bytes != int(
            artifact_meta.get("raw_bytes") or -1
        ):
            block("raw_bytes_mismatch")
    if artifact:
        if (artifact.get("meta") or {}).get("config_hash") != _config_hash(segment_config):
            block("config_hash_mismatch")
        if artifact.get("audit") != segment.get("audit"):
            block("audit_manifest_mismatch")
        if artifact.get("audit", {}).get("verdict") != "pass_data_smoke":
            block("audit_verdict_not_pass")
        if artifact.get("audit", {}).get("blockers") or segment.get("blockers"):
            block("audit_declared_blockers")
    replay_match: bool | None = None
    if raw_path.is_file() and artifact:
        try:
            replay = audit_event_file(raw_path, segment_config)
        except (EOFError, OSError, ValueError, json.JSONDecodeError):
            block("deep_replay_failed")
        else:
            replay_match = replay == artifact.get("audit")
            if not replay_match:
                block("deep_replay_mismatch")
    return {
        "schema_version": "alpha_agent_live_collector_offload_verification_v0.1",
        "session_id": _session_id(manifest),
        "segment_index": segment_index,
        "segment_dir": relative_dir,
        "raw_sha256": actual_sha,
        "raw_bytes": actual_bytes,
        "deep_replay_match": replay_match,
        "verdict": "pass_offload" if not blockers else "block_offload",
        "blockers": blockers,
    }


def _write_local_manifest_snapshot(session_dir: Path, manifest: dict[str, Any]) -> None:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for segment in manifest.get("segments") or []:
        grouped.setdefault(str(segment["utc_day"]), []).append(segment)
    days_by_key = {
        str(day["utc_day"]): day
        for day in manifest.get("days") or []
        if isinstance(day, dict) and day.get("utc_day")
    }
    for utc_day, segments in grouped.items():
        day = days_by_key.get(utc_day)
        if day is None:
            raise ValueError(f"daily index missing for {utc_day}")
        daily_path, safe = _resolved_child_path(session_dir, day.get("artifact_path"))
        if daily_path is None or not safe:
            raise ValueError(f"daily path is unsafe for {utc_day}")
        payload = {
            "schema_version": LIVE_COLLECTOR_SESSION_VERSION,
            "session_artifact_path": manifest["artifact_path"],
            "daily_artifact_path": day["artifact_path"],
            "utc_day": utc_day,
            "closed": day.get("closed") is True,
            "contract_hash": manifest["contract_hash"],
            "segments": segments,
            "aggregate": _summarize_segments(segments),
        }
        _atomic_write_json(daily_path, payload)
    _atomic_write_json(session_dir / "alpha_agent_live_collector_session.json", manifest)


def _ssh_base(remote_host: str, connect_timeout_seconds: int) -> list[str]:
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={connect_timeout_seconds}",
        remote_host,
    ]


def _fetch_remote_manifest(
    remote_host: str,
    remote_session_dir: str,
    connect_timeout_seconds: int,
) -> dict[str, Any]:
    command = _ssh_base(remote_host, connect_timeout_seconds) + [
        "cat",
        f"{remote_session_dir}/alpha_agent_live_collector_session.json",
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise ValueError("remote collector manifest is not an object")
    if value.get("schema_version") != LIVE_COLLECTOR_SESSION_VERSION:
        raise ValueError("remote collector session is not relocatable")
    if (value.get("meta") or {}).get("path_contract") != SESSION_PATH_CONTRACT:
        raise ValueError("remote collector path contract is not relocatable")
    return value


def _rsync_segment(
    remote_host: str,
    remote_session_dir: str,
    segment_dir: str,
    local_session_dir: Path,
) -> None:
    destination = local_session_dir / segment_dir
    destination.mkdir(parents=True, exist_ok=True)
    command = [
        "rsync",
        "-az",
        "--partial",
        "--exclude=*.partial",
        f"{remote_host}:{remote_session_dir}/{segment_dir}/",
        f"{destination}/",
    ]
    subprocess.run(command, check=True)


def _remote_ack(
    remote_host: str,
    remote_session_dir: str,
    segment_index: int,
    raw_sha256: str,
    receipt_id: str,
    connect_timeout_seconds: int,
    remote_python: str,
    remote_cli: str,
) -> None:
    command = _ssh_base(remote_host, connect_timeout_seconds) + [
        remote_python,
        remote_cli,
        "remote-ack",
        "--session-dir",
        remote_session_dir,
        "--segment-index",
        str(segment_index),
        "--raw-sha256",
        raw_sha256,
        "--receipt-id",
        receipt_id,
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)


def pull_offloaded_segments(
    *,
    remote_host: str,
    remote_session_dir: str,
    local_archive_root: str | Path,
    delete_remote: bool,
    min_local_free_bytes: int = 20 * 1024**3,
    connect_timeout_seconds: int = 15,
    remote_python: str = "/root/qount-alpha/.venv/bin/python",
    remote_cli: str = "/root/qount-alpha/scripts/research/alpha_agents/alpha_agent_collector_offload.py",
) -> dict[str, Any]:
    remote_host = _validated_host(remote_host)
    remote_session_dir = _validated_remote_session_dir(remote_session_dir)
    archive_root = Path(local_archive_root).expanduser().resolve()
    archive_root.mkdir(parents=True, exist_ok=True)
    with _exclusive_lock(archive_root / ".alpha-collector-offload.lock"):
        manifest = _fetch_remote_manifest(remote_host, remote_session_dir, connect_timeout_seconds)
        session_id = _session_id(manifest)
        local_session_dir = archive_root / session_id
        local_session_dir.mkdir(parents=True, exist_ok=True)
        receipts_path = local_session_dir / LOCAL_RECEIPTS_FILENAME
        receipt_events = _read_jsonl(receipts_path)
        phases_by_receipt: dict[str, set[str]] = {}
        for event in receipt_events:
            phases_by_receipt.setdefault(str(event.get("receipt_id") or ""), set()).add(
                str(event.get("phase") or "")
            )
        copied = 0
        verified = 0
        remote_deleted = 0
        for segment in manifest.get("segments") or []:
            index = int(segment["index"])
            expected_sha = str(segment.get("raw_sha256") or "")
            if not _SAFE_SHA256.fullmatch(expected_sha):
                raise ValueError(f"segment {index} has an invalid raw sha256")
            artifact_path, raw_path, segment_dir = _segment_paths(local_session_dir, segment)
            receipt_id = _receipt_id(session_id, index, expected_sha)
            phases = phases_by_receipt.setdefault(receipt_id, set())
            if "remote_deleted" in phases:
                continue
            if not artifact_path.is_file() or not raw_path.is_file() or "verified" not in phases:
                required_bytes = int(segment.get("raw_bytes") or 0)
                free_bytes = shutil.disk_usage(archive_root).free
                if free_bytes - required_bytes < min_local_free_bytes:
                    raise RuntimeError(
                        "local disk guard tripped: "
                        f"free_bytes={free_bytes} incoming={required_bytes} minimum={min_local_free_bytes}"
                    )
                _rsync_segment(remote_host, remote_session_dir, segment_dir, local_session_dir)
                copied += 1
                verification = verify_offload_segment(local_session_dir, manifest, index)
                if verification["verdict"] != "pass_offload":
                    raise RuntimeError(
                        f"segment {index} offload verification failed: {','.join(verification['blockers'])}"
                    )
                _append_jsonl(
                    receipts_path,
                    {
                        "schema_version": OFFLOAD_RECEIPT_VERSION,
                        "receipt_id": receipt_id,
                        "phase": "verified",
                        "verified_at_utc": _utc_now(),
                        "session_id": session_id,
                        "segment_index": index,
                        "segment_dir": segment_dir,
                        "raw_sha256": expected_sha,
                        "raw_bytes": int(segment["raw_bytes"]),
                        "deep_replay_match": True,
                        "remote_host": remote_host,
                        "remote_session_dir": remote_session_dir,
                    },
                )
                phases.add("verified")
                verified += 1
            if delete_remote:
                _remote_ack(
                    remote_host,
                    remote_session_dir,
                    index,
                    expected_sha,
                    receipt_id,
                    connect_timeout_seconds,
                    remote_python,
                    remote_cli,
                )
                _append_jsonl(
                    receipts_path,
                    {
                        "schema_version": OFFLOAD_RECEIPT_VERSION,
                        "receipt_id": receipt_id,
                        "phase": "remote_deleted",
                        "deleted_at_utc": _utc_now(),
                        "session_id": session_id,
                        "segment_index": index,
                        "raw_sha256": expected_sha,
                    },
                )
                phases.add("remote_deleted")
                remote_deleted += 1
        _write_local_manifest_snapshot(local_session_dir, manifest)
        return {
            "schema_version": "alpha_agent_live_collector_offload_run_v0.1",
            "session_id": session_id,
            "local_session_dir": str(local_session_dir),
            "remote_segment_count": len(manifest.get("segments") or []),
            "copied_segment_count": copied,
            "verified_segment_count": verified,
            "remote_deleted_segment_count": remote_deleted,
            "delete_remote": delete_remote,
            "status": "pass_offload",
        }


def remote_ack_segment(
    session_dir: str | Path,
    segment_index: int,
    raw_sha256: str,
    receipt_id: str,
) -> dict[str, Any]:
    if not _SAFE_SHA256.fullmatch(raw_sha256) or not _SAFE_SHA256.fullmatch(receipt_id):
        raise ValueError("raw_sha256 and receipt_id must be lowercase sha256 values")
    resolved_dir = Path(session_dir).expanduser().resolve()
    manifest_path = resolved_dir / "alpha_agent_live_collector_session.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    session_id = _session_id(manifest)
    segments = manifest.get("segments") if isinstance(manifest.get("segments"), list) else []
    if segment_index < 0 or segment_index >= len(segments):
        raise IndexError(f"segment index out of range: {segment_index}")
    segment = segments[segment_index]
    if not isinstance(segment, dict) or int(segment.get("index", -1)) != segment_index:
        raise ValueError("segment manifest entry is invalid")
    if str(segment.get("raw_sha256") or "") != raw_sha256:
        raise ValueError("requested sha256 does not match the session manifest")
    if receipt_id != _receipt_id(session_id, segment_index, raw_sha256):
        raise ValueError("receipt_id does not match the segment contract")
    _, raw_path, segment_dir = _segment_paths(resolved_dir, segment)
    receipts_path = resolved_dir / REMOTE_RECEIPTS_FILENAME
    with _exclusive_lock(resolved_dir / ".offload-ack.lock"):
        events = _read_jsonl(receipts_path)
        phases = {
            str(event.get("phase") or "")
            for event in events
            if event.get("receipt_id") == receipt_id
        }
        if "deleted" in phases and not raw_path.exists():
            return {
                "status": "already_deleted",
                "receipt_id": receipt_id,
                "segment_index": segment_index,
            }
        if raw_path.is_file():
            actual_sha = _sha256_file(raw_path)
            if actual_sha != raw_sha256:
                raise RuntimeError("remote raw sha256 changed before deletion")
            if raw_path.stat().st_size != int(segment.get("raw_bytes") or -1):
                raise RuntimeError("remote raw byte size changed before deletion")
            if "verified" not in phases:
                _append_jsonl(
                    receipts_path,
                    {
                        "schema_version": OFFLOAD_RECEIPT_VERSION,
                        "receipt_id": receipt_id,
                        "phase": "verified",
                        "verified_at_utc": _utc_now(),
                        "session_id": session_id,
                        "segment_index": segment_index,
                        "segment_dir": segment_dir,
                        "raw_sha256": raw_sha256,
                        "raw_bytes": int(segment["raw_bytes"]),
                    },
                )
            raw_path.unlink()
            directory_fd = os.open(raw_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        elif "verified" not in phases:
            raise FileNotFoundError("remote raw data is missing without a verified offload receipt")
        if "deleted" not in phases:
            _append_jsonl(
                receipts_path,
                {
                    "schema_version": OFFLOAD_RECEIPT_VERSION,
                    "receipt_id": receipt_id,
                    "phase": "deleted",
                    "deleted_at_utc": _utc_now(),
                    "session_id": session_id,
                    "segment_index": segment_index,
                    "segment_dir": segment_dir,
                    "raw_sha256": raw_sha256,
                },
            )
        return {
            "status": "deleted",
            "receipt_id": receipt_id,
            "segment_index": segment_index,
            "raw_sha256": raw_sha256,
        }
