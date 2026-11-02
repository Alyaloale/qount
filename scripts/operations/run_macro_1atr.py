#!/usr/bin/env python3
"""Run the selected macro strategy; --check never submits or changes margin settings."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import time
from pathlib import Path

import ccxt

from qount.execution.macro_live import MacroBlocked, MacroLive
from qount.research_data.macro_live import MacroInputError, MacroLiveInputs, write_json
from qount.strategies.macro_1atr import RISK_FRACTION, STRATEGY_ID


def _exchange():
    return ccxt.binance({"enableRateLimit": True, "timeout": 10000,
                         "options": {"defaultType": "future", "fetchCurrencies": False},
                         "apiKey": os.environ.get("QOUNT_BINANCE_API_KEY", ""),
                         "secret": os.environ.get("QOUNT_BINANCE_API_SECRET", "")})


def run_cycle(exchange, *, output, store_path, halt_path, state_path=None,
              config_path=Path("config/macro-1atr.json"), execute=False, inputs=None,
              now=None, **unused):
    output, store_path, halt_path = Path(output), Path(store_path), Path(halt_path)
    state_path = Path(state_path or output.with_name("macro-state.json"))
    config = json.loads(Path(config_path).read_text())
    if config["strategy_id"] != STRATEGY_ID:
        raise MacroBlocked("config_strategy_mismatch")
    stamp = int(time.time()) if now is None else now
    result = dict(strategy_id=STRATEGY_ID,
                  created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stamp)),
                  execution_mode="auto_live" if execute else "plan_only",
                  orders_authorized=execute and os.environ.get("QOUNT_LIVE_ENABLE", "").lower() == "true"
                      and os.environ.get("QOUNT_PRIMARY_STRATEGY") == STRATEGY_ID,
                  research_only=not execute, selected=None,
                  decision_clock="America/New_York 10:00 regular session",
                  risk_fraction=RISK_FRACTION, gross_cap=20, maximum_leverage=50,
                  protection_check={"status": "UNKNOWN"})
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.with_name("macro-cycle.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise MacroBlocked("another_macro_cycle_running") from None
        try:
            previous = json.loads(output.read_text())
        except (OSError, ValueError):
            previous = {}
        try:
            if halt_path.exists():
                raise MacroBlocked("owner_halt_exists")
            live = MacroLive(exchange, inputs or MacroLiveInputs(exchange, output.with_name("market-cache")),
                             store_path=store_path, state_path=state_path, handover=config["handover"], execute=execute)
            result.update(live.cycle(stamp//3600*3600))
        except MacroInputError as exc:
            result.update(auto_action="BLOCKED", execution_blocker="input_unavailable:"+exc.details["code"],
                          input_error=exc.details)
        except MacroBlocked as exc:
            result.update(auto_action="BLOCKED", execution_blocker=str(exc))
        except Exception as exc:
            # Exchange exceptions can contain signed URLs. Never serialize their messages.
            result.update(auto_action="BLOCKED", execution_blocker=f"input_or_exchange_error:{type(exc).__name__}")
        if "candidate_count" in result:
            result["last_decision"] = {key: result.get(key) for key in (
                "created_at", "auto_action", "candidate_count", "rejections", "capital_usdt", "selected")}
        elif isinstance(previous, dict) and previous.get("strategy_id") == STRATEGY_ID:
            result["last_decision"] = previous.get("last_decision")
        write_json(output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--store", type=Path, default=Path(os.environ.get("QOUNT_1ATR_EXECUTION_STORE", "/var/lib/qount/1atr/execution.sqlite3")))
    parser.add_argument("--halt", type=Path, default=Path(os.environ.get("QOUNT_1ATR_HALT_PATH", "/var/lib/qount/1atr/HALT")))
    parser.add_argument("--state", type=Path)
    parser.add_argument("--config", type=Path, default=Path("config/macro-1atr.json"))
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--execute", action="store_true")
    group.add_argument("--check", action="store_true")
    group.add_argument("--warm-inputs", action="store_true", help="public data only; prepare causal inputs without account access")
    args = parser.parse_args()
    if args.warm_inputs:
        exchange = _exchange()
        exchange.apiKey = exchange.secret = ""
        inputs = MacroLiveInputs(exchange, args.output.with_name("market-cache"))
        now = int(time.time())//3600*3600
        features = inputs.features(now)
        data, _ = inputs.snapshot(now, entry=True)
        print(json.dumps({"public_only": True, "feature_dates": {s: rows[-1]["date"] for s, rows in features.items()},
                          "hour_counts": {s: len(d["trade"]) for s, d in data.items()}}))
        return 0
    result = run_cycle(_exchange(), output=args.output, store_path=args.store, halt_path=args.halt,
                       state_path=args.state, config_path=args.config, execute=args.execute)
    print(json.dumps({k: result.get(k) for k in ("strategy_id", "auto_action", "execution_blocker", "handover", "created_at")}, ensure_ascii=False))
    return 2 if result["auto_action"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
