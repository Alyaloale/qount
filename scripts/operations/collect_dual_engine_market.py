#!/usr/bin/env python3
"""Collect one scheduled public-data event and advance Dual-Engine paper state."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from qount.dual_engine import DualEngineMarketConfig
from qount.dual_engine import NoScheduledPaperEvent
from qount.dual_engine import collect_market_cycle
from qount.dual_engine import run_paper_cycle
from qount.dual_engine.market_data import TIINGO_BASE_URL
from qount.dual_engine.market_data import _public_json_get
from qount.dual_engine.reference_data import refresh_public_reference


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


def _archive_cycle(root: Path, cycle: Mapping[str, Any]) -> Path:
    directory = root / "inputs"
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    path = directory / f"{cycle['cycle_hash']}.json"
    raw = _canonical_bytes(cycle)
    if path.exists():
        if path.is_symlink() or path.read_bytes() != raw:
            raise ValueError("paper_cycle_archive_collision")
        return path
    descriptor, temporary_name = tempfile.mkstemp(
        dir=directory,
        prefix=".cycle.",
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
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()
    return path


def _metered_getter(
    state_root: Path,
    *,
    event: str,
    observed_at: str,
    counter: dict[str, int],
):
    """Count and persist each Tiingo request attempt without recording credentials."""

    state_root.mkdir(parents=True, mode=0o700, exist_ok=True)
    ledger_path = state_root / "tiingo-request-attempts.jsonl"

    def get_json(url: str, headers: Mapping[str, str], timeout_seconds: int):
        if url.startswith(f"{TIINGO_BASE_URL}/"):
            counter["tiingo"] += 1
            parsed = urlsplit(url)
            record = {
                "event": event,
                "observed_at": observed_at,
                "url_path": parsed.path,
                "query": parsed.query,
                "attempt": counter["tiingo"],
            }
            raw = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            descriptor = os.open(
                ledger_path,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o600,
            )
            try:
                os.fchmod(descriptor, 0o600)
                os.write(descriptor, raw)
            finally:
                os.close(descriptor)
        return _public_json_get(url, headers, timeout_seconds)

    return get_json


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--event", choices=("daily-close", "g20-open"), required=True)
    parser.add_argument("--observed-at")
    parser.add_argument("--refresh-reference", action="store_true")
    parser.add_argument("--reference-only", action="store_true")
    parser.add_argument("--equity-source", choices=("tiingo_public", "yahoo_public"), default="tiingo_public")
    parser.add_argument("--initialize-cash", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    observed_at = args.observed_at or dt.datetime.now(dt.timezone.utc).isoformat()
    config = DualEngineMarketConfig.from_dict(_read_object(args.config.resolve()))
    state_root = args.state_root.resolve()
    def refresh_cash_account():
        if (state_root/"g20-cash/forward.json").exists():
            from qount.dual_engine.g20_cash import refresh
            refresh(state_root,policy_path=Path(__file__).resolve().parents[2]/"config/g20-cash-distributions.json",
                    observed_at=observed_at)
    request_counter = {"tiingo": 0}
    getter = _metered_getter(
        state_root,
        event=args.event,
        observed_at=observed_at,
        counter=request_counter,
    )
    if args.equity_source == "yahoo_public":
        from qount.research_data.paper_daily import yahoo_dual_getter
        getter = yahoo_dual_getter(state_root / "market-cache" / "yahoo-public",
                                  dt.datetime.fromisoformat(observed_at), _public_json_get)
    if args.reference_only:
        reference = refresh_public_reference(
            state_root,
            config,
            observed_at=observed_at,
            getter=getter,
        )
        print(json.dumps({"status": "public_reference_refreshed", "reference_hash": reference["reference_hash"],
                          "tiingo_request_count": request_counter["tiingo"],
                          "orders_authorized": False}, sort_keys=True))
        return 0
    try:
        cycle = collect_market_cycle(
            config,
            observed_at=observed_at,
            event=args.event,
            getter=getter,
            cache_root=state_root / "market-cache" / ("tiingo-daily" if args.equity_source=="tiingo_public" else "yahoo-daily"),
            equity_source=args.equity_source,
        )
    except NoScheduledPaperEvent as exc:
        print(json.dumps({"status": "skipped", "reason": str(exc),
                          "tiingo_request_count": request_counter["tiingo"]}, sort_keys=True))
        return 0
    state_path=state_root/"state"/"program.json"
    if state_path.exists():
        state=_read_object(state_path)
        if state.get("last_data_cutoff")==cycle.data_cutoff:
            refresh_cash_account()
            print(json.dumps({"status":"skipped","reason":"no_new_closed_inputs","orders_authorized":False}))
            return 0
    input_path = _archive_cycle(state_root, cycle.as_dict())
    snapshot = run_paper_cycle(state_root, cycle, initialize_cash=args.initialize_cash)
    refresh_cash_account()
    reference_status = "not_requested"
    if args.refresh_reference and args.equity_source == "tiingo_public":
        try:
            refresh_public_reference(
                state_root,
                config,
                observed_at=observed_at,
                getter=getter,
                reuse_if_fresh_seconds=18 * 60 * 60 if args.event == "g20-open" else None,
            )
            reference_status = "refreshed"
        except (OSError, ValueError, TypeError, KeyError):
            # Optional reference failure must not undo a completed accounting cycle.
            # Its previous timestamp is retained; the source probe will show it stale.
            reference_status = "unavailable"
    print(
        json.dumps(
            {
                "status": "paper_cycle_published",
                "event": args.event,
                "cycle_hash": cycle.cycle_hash,
                "snapshot_hash": snapshot.snapshot_hash,
                "input_path": str(input_path),
                "orders_authorized": False,
                "reference_status": reference_status,
                "tiingo_request_count": request_counter["tiingo"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
