#!/usr/bin/env python3
"""Build a fresh, order-free Dual-Engine 2026 YTD paper state and curve."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence

from qount.contracts import canonical_hash
from qount.dual_engine import DualEngineMarketConfig
from qount.dual_engine import YTD_REPLAY_START
from qount.dual_engine import collect_ytd_replay
from qount.dual_engine import run_paper_cycle
from qount.dual_engine.market_data import JsonGetter
from qount.dual_engine.market_data import _public_json_get


def _read_object(path: Path) -> Mapping[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate_key:{key}")
            result[key] = value
        return result

    value = json.loads(path.read_bytes(), object_pairs_hook=reject_duplicates)
    if not isinstance(value, Mapping):
        raise ValueError("config_must_be_object")
    return value


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        + b"\n"
    )


def _archive_cycle(root: Path, cycle: Mapping[str, Any]) -> None:
    directory = root / "inputs"
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    destination = directory / f"{cycle['cycle_hash']}.json"
    if destination.exists():
        raise ValueError("paper_ytd_cycle_archive_collision")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=directory,
        prefix=".cycle.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical_bytes(cycle))
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = -1
        os.replace(temporary, destination)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


class _CachedPublicGetter:
    """Keep secret-free raw public responses so a failed replay can resume."""

    def __init__(
        self,
        root: Path,
        *,
        upstream: JsonGetter = _public_json_get,
    ) -> None:
        self.root = root
        self.upstream = upstream
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        os.chmod(self.root, 0o700)

    def __call__(
        self,
        url: str,
        headers: Mapping[str, str],
        timeout_seconds: int,
    ) -> tuple[Any, str]:
        url_hash = canonical_hash({"url": url})
        path = self.root / f"{url_hash}.json"
        if path.exists():
            value = _read_object(path)
            if set(value) != {
                "schema_version", "url_hash", "payload_hash", "payload"
            } or value["schema_version"] != 1 or value["url_hash"] != url_hash:
                raise ValueError("paper_ytd_download_cache_invalid")
            if canonical_hash(
                {"url_path": url.split("?", 1)[0], "payload": value["payload"]}
            ) != value["payload_hash"]:
                raise ValueError("paper_ytd_download_cache_hash_invalid")
            return value["payload"], str(value["payload_hash"])
        payload, payload_hash = self.upstream(url, headers, timeout_seconds)
        _archive_download(
            path,
            {
                "schema_version": 1,
                "url_hash": url_hash,
                "payload_hash": payload_hash,
                "payload": payload,
            },
        )
        return payload, payload_hash


def _archive_download(path: Path, value: Mapping[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=".download.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = -1
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument(
        "--start-date",
        type=dt.date.fromisoformat,
        default=YTD_REPLAY_START,
    )
    parser.add_argument("--end-date", type=dt.date.fromisoformat, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    last_complete = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)
    if args.end_date > last_complete:
        raise ValueError("paper_ytd_end_date_not_complete")
    state_root = args.state_root.resolve()
    if state_root == Path("/") or not state_root.is_absolute():
        raise ValueError("paper_ytd_state_root_invalid")
    if state_root.exists():
        unexpected = {
            path.name for path in state_root.iterdir()
        } - {"download-cache"}
        if unexpected:
            raise ValueError("paper_ytd_state_root_not_empty")
    state_root.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(state_root, 0o700)
    config = DualEngineMarketConfig.from_dict(_read_object(args.config.resolve()))
    replay = collect_ytd_replay(
        config,
        start_date=args.start_date,
        end_date=args.end_date,
        getter=_CachedPublicGetter(state_root / "download-cache"),
    )
    snapshot = None
    for cycle in replay.cycles:
        _archive_cycle(state_root, cycle.as_dict())
        snapshot = run_paper_cycle(state_root, cycle)
    if snapshot is None:
        raise ValueError("paper_ytd_snapshot_missing")
    point_counts = {
        str(portfolio["label"]): len(portfolio["nav"]["points"])
        for portfolio in snapshot.portfolios
    }
    print(
        json.dumps(
            {
                "status": "paper_ytd_replay_published",
                "start_date": replay.start_date,
                "end_date": replay.end_date,
                "cycle_count": len(replay.cycles),
                "point_counts": point_counts,
                "snapshot_hash": snapshot.snapshot_hash,
                "orders_authorized": False,
                "private_api_used": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
