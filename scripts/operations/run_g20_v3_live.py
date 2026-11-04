#!/usr/bin/env python3
"""Run one G20-LP v3 daily resize cycle; --check never submits orders.

Owner authorization for the live switch is recorded in docs/current.md
(2026-11-03).  Real orders still require the runtime gates: QOUNT_LIVE_ENABLE,
QOUNT_PRIMARY_STRATEGY=g20_leveraged_pool_v3, --execute and confirmed=True.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path

import ccxt

from qount.execution.binance_usdm import BinanceExecutionStore, BinanceUsdMExecution
from qount.execution.g20_v3_live import STRATEGY_ID, V3PoolLive
from qount.research_data.macro_live import write_json


def _exchange():
    return ccxt.binance({"enableRateLimit": True, "timeout": 10000,
                         "options": {"defaultType": "future", "fetchCurrencies": False},
                         "apiKey": os.environ.get("QOUNT_BINANCE_API_KEY", ""),
                         "secret": os.environ.get("QOUNT_BINANCE_API_SECRET", "")})


def run_cycle(exchange, *, output, store_path, halt_path, state_path, execute=False, now=None):
    output, store_path, halt_path = Path(output), Path(store_path), Path(halt_path)
    state_path = Path(state_path or output.with_name("g20-v3-state.json"))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.with_name("g20-v3-cycle.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            result = dict(strategy_id=STRATEGY_ID, auto_action="BLOCKED",
                          execution_blocker="another_v3_cycle_running")
            write_json(output, result)
            return result
        try:
            previous = json.loads(output.read_text())
        except (OSError, ValueError):
            previous = {}
        try:
            state = json.loads(state_path.read_text())
        except (OSError, ValueError):
            state = {}
        try:
            if halt_path.exists():
                raise SystemExit("owner_halt_exists")
            store = BinanceExecutionStore(store_path)
            execution = BinanceUsdMExecution(exchange, store)
            live = V3PoolLive(exchange, execution, state=state)
            result = live.cycle(execute=execute, now=now)
            # Plan-only runs never consume the schedule: only executed cycles
            # advance cycle_count / last_signal_date.
            if execute and result.get("auto_action") != "BLOCKED":
                write_json(state_path, live.state)
        except SystemExit as exc:
            result = dict(strategy_id=STRATEGY_ID, auto_action="BLOCKED",
                          execution_blocker=str(exc) or "owner_halt_exists")
        except Exception as exc:
            # Exchange exceptions can contain signed URLs. Never serialize messages.
            result = dict(strategy_id=STRATEGY_ID, auto_action="BLOCKED",
                          execution_blocker=f"input_or_exchange_error:{type(exc).__name__}")
        if result.get("auto_action") in {"RESIZE", "NO_ACTION"}:
            result["last_decision"] = {key: result.get(key) for key in (
                "created_at", "auto_action", "signal_date", "capital_usdt",
                "scheduled_resize", "drift_breach", "order_counts")}
        elif isinstance(previous, dict) and previous.get("strategy_id") == STRATEGY_ID:
            result["last_decision"] = previous.get("last_decision")
        write_json(output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--store", type=Path,
                        default=Path(os.environ.get("QOUNT_G20V3_EXECUTION_STORE",
                                                    "/var/lib/qount/g20-v3/execution.sqlite3")))
    parser.add_argument("--halt", type=Path,
                        default=Path(os.environ.get("QOUNT_G20V3_HALT_PATH",
                                                    "/var/lib/qount/g20-v3/HALT")))
    parser.add_argument("--state", type=Path)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--execute", action="store_true")
    group.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = run_cycle(_exchange(), output=args.output, store_path=args.store,
                       halt_path=args.halt, state_path=args.state, execute=args.execute)
    print(json.dumps({k: result.get(k) for k in
                      ("strategy_id", "auto_action", "execution_blocker",
                       "signal_date", "created_at")}, ensure_ascii=False))
    return 2 if result["auto_action"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
