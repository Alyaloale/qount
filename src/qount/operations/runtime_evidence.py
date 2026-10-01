"""Bounded, read-only checks of public collection artifacts, without research imports."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any

from qount.contracts.trace import aware_datetime


MAX_BYTES = 2 * 1024 * 1024
_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
_HASH = re.compile(r"[0-9a-f]{64}")


def _object(raw: bytes) -> dict[str, Any]:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate_key")
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise ValueError("object_required")
    return value


def _read(path: Path, *, tail: bool = False) -> bytes:
    # Reject symlinks and special files before opening; never follow metadata
    # into credentials or block on a FIFO. Roots must be trusted operator paths.
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("symlink_forbidden")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("regular_file_required")
        if tail and info.st_size > MAX_BYTES:
            handle.seek(-MAX_BYTES, os.SEEK_END)
            raw = handle.read(MAX_BYTES)
            return raw.partition(b"\n")[2]
        raw = handle.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("artifact_too_large")
        return raw


def _check(name: str, status: str, detail: str, value=None) -> dict[str, object]:
    return {
        "check_id": f"runtime:{name}",
        "status": status,
        "detail": detail,
        "impact_scopes": ("observation",),
        "blocks_execution": False,
        "observed_value": value,
    }


def _age(now: float, timestamp: object, *, milliseconds: bool = False) -> float:
    if milliseconds:
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            raise ValueError("timestamp_invalid")
        seconds = timestamp / 1000
    else:
        seconds = aware_datetime(timestamp).timestamp()
    age = now - seconds
    if not math.isfinite(age) or age < -5:
        raise ValueError("timestamp_invalid")
    return max(0.0, age)


def probe_forward(root: Path, *, observed_at: str) -> list[dict[str, object]]:
    """Verify the published head and its record; this is not a full chain audit."""
    try:
        head = _object(_read(root / "metadata/current.json"))
        relative = Path(head["last_record_path"])
        if (
            relative.is_absolute() or ".." in relative.parts
            or len(relative.parts) != 5 or relative.parts[0] != "records"
            or relative.parts[-1] != "cycles.jsonl"
        ):
            raise ValueError("record_path_invalid")
        expected = head["last_record_hash"]
        if not isinstance(expected, str) or not _HASH.fullmatch(expected):
            raise ValueError("head_hash_invalid")
        raw = _read(root / relative, tail=True)
        record = None
        # A writer may have fsynced a new row but not yet replaced the head.
        # Accept its preceding published row; never ignore a changed head hash.
        for line in reversed(raw.splitlines()[-2:]):
            candidate = _object(line)
            if candidate.get("record_hash") == expected:
                record = candidate
                break
        if record is None:
            raise ValueError("head_record_missing")
        core = {key: value for key, value in record.items() if key != "record_hash"}
        digest = hashlib.sha256(json.dumps(
            core, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")).hexdigest()
        if (
            digest != expected or head.get("status") != "running"
            or head["last_observed_at_utc"] != record["observed_at_utc"]
            or record.get("research_only") is not True
            or record.get("orders_authorized") is not False
            or record.get("pnl_evaluated") is not False
        ):
            raise ValueError("record_invalid")
        age = _age(aware_datetime(observed_at).timestamp(), record["observed_at_utc"])
        checks = [_check("forward", "pass" if age <= 1800 else "warn",
                         "forward_head_fresh" if age <= 1800 else "forward_head_stale", age)]
        plugins = record["plugins"]
        if not isinstance(plugins, dict) or not plugins:
            raise ValueError("plugins_missing")
        for name, result in sorted(plugins.items()):
            if not _NAME.fullmatch(name) or not isinstance(result, dict):
                raise ValueError("plugin_invalid")
            checks.append(_check(f"plugin_{name}", "pass" if result.get("status") == "valid" else "warn",
                                 "source_available" if result.get("status") == "valid" else "source_incomplete"))
            if name == "research_lines":
                sources = result.get("payload", {}).get("sources", {})
                if not isinstance(sources, dict) or not sources:
                    raise ValueError("sources_missing")
                for source, item in sorted(sources.items()):
                    if not _NAME.fullmatch(source) or not isinstance(item, dict):
                        raise ValueError("source_invalid")
                    checks.append(_check(f"source_{source}", "pass" if item.get("status") == "valid" else "warn",
                                         "source_available" if item.get("status") == "valid" else "source_incomplete"))
        return checks
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return [_check("forward", "unavailable", "forward_evidence_unavailable")]


def probe_liquidation(root: Path, *, observed_at: str) -> list[dict[str, object]]:
    try:
        value = _object(_read(root / "metadata/current.json"))
        now = aware_datetime(observed_at).timestamp()
        status_age = _age(now, value.get("updated_at_ms"), milliseconds=True)
        stream_age = _age(now, value.get("last_stream_message_at_ms"), milliseconds=True)
        guards = value.get("research_guards")
        if not isinstance(guards, dict) or any(guards.get(key) is not False for key in (
            "orders_authorized", "private_api_used", "pnl_evaluated", "read_results_before_window",
        )):
            return [_check("liquidation", "unavailable", "liquidation_guards_invalid")]
        fresh = max(status_age, stream_age) <= 180
        running = value.get("status") == "running" and value.get("stopped_at_ms") is None
        return [_check("liquidation", "pass" if fresh and running else "warn",
                       "liquidation_stream_fresh" if fresh and running else "liquidation_stream_stale_or_stopped",
                       max(status_age, stream_age))]
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        return [_check("liquidation", "unavailable", "liquidation_evidence_unavailable")]
