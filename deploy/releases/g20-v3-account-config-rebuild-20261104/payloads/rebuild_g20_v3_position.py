#!/usr/bin/env python3
"""Owner-directed G20-LP v3 position rebuild (one-off catch-up orders).

2026-11-04: the owner flattened the wallet after the XRPUSDT liquidation
incident and directed a rebuild after the fixes ("修复完重新下单补单").  The
daily executor cannot place these orders itself: its order identity is keyed
to the signal date and the 2026-11-03 claims already exist in the execution
store, so a re-run would reconcile instead of ordering.  This script submits
the identical full-pool resize through the same idempotent BinanceUsdMExecution
stack with a distinct identity tag ("...R") and writes the standard receipt.

Real orders require the usual gates (QOUNT_LIVE_ENABLE=true AND
QOUNT_PRIMARY_STRATEGY=g20_leveraged_pool_v3) PLUS --execute PLUS
--confirm OWNER_REBUILD.  Without the confirm flag it is plan-only.
State (g20-v3-state.json) is never written: the daily schedule keeps its own
bookkeeping, and the 2026-11-03 signal stays marked processed.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import ccxt

from qount.execution.binance_usdm import BinanceExecutionStore, BinanceUsdMExecution
from qount.execution.g20_v3_live import POOL, STRATEGY_ID, V3PoolLive, _rule, plan_legs
from qount.research_data.macro_live import write_json


def _exchange():
    return ccxt.binance({"enableRateLimit": True, "timeout": 10000,
                         "options": {"defaultType": "future", "fetchCurrencies": False},
                         "apiKey": os.environ.get("QOUNT_BINANCE_API_KEY", ""),
                         "secret": os.environ.get("QOUNT_BINANCE_API_SECRET", "")})


def rebuild(exchange, *, output: Path, store_path: Path, execute: bool) -> dict:
    store = BinanceExecutionStore(store_path)
    execution = BinanceUsdMExecution(exchange, store)
    live = V3PoolLive(exchange, execution, state={})
    if execute and not execution.authorized_for(STRATEGY_ID):
        raise SystemExit("orders_not_authorized")
    if execute:
        live.ensure_account_config()
    live.check_isolated_liq()
    day, prices = live.signal_prices()
    signal_date = time.strftime("%Y-%m-%d", time.gmtime(day / 1000))
    tag = signal_date.replace("-", "") + "R"
    equity = live.balance()
    held = live.positions()
    if any(symbol not in POOL for symbol in held):
        raise SystemExit("positions_outside_pool")
    rules = {s: _rule(exchange, s) for s in POOL}
    plan = plan_legs(equity=equity, prices=prices, held=held, rules=rules)
    results = []
    blocker = None
    for leg in plan:
        if leg["action"] not in {"BUY", "SELL", "CLOSE"}:
            continue
        side = "buy" if leg["action"] == "BUY" else "sell"
        intent = "b" if side == "buy" else ("c" if leg["action"] == "CLOSE" else "s")
        try:
            results.append(live._submit_leg(
                leg, side=side, client_order_id=f"v3-{tag}-{leg['symbol']}-{intent}",
                signal_date=tag, execute=execute, price=prices[leg["symbol"]]))
        except Exception as exc:  # keep partial receipts; re-runs reconcile claims
            blocker = f"input_or_exchange_error:{type(exc).__name__}"
            break
    receipt = dict(
        strategy_id=STRATEGY_ID,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        execution_mode="auto_live" if execute else "plan_only",
        orders_authorized=bool(execute and execution.authorized_for(STRATEGY_ID)),
        research_only=not execute,
        auto_action="RESIZE",
        signal_date=signal_date,
        capital_usdt=equity,
        cycle_count=0,
        scheduled_resize=True,
        drift_breach=False,
        positions={s: q for s, q in held.items()},
        plan=plan,
        orders=results,
        order_counts={
            "submitted": sum(1 for r in results if r["status"] in {"SUBMITTING", "NEW", "PARTIALLY_FILLED", "FILLED"}),
            "skipped_rule": sum(1 for r in results if r["status"] == "SKIPPED_RULE"),
            "planned_only": sum(1 for r in results if r["status"] == "PLANNED")},
        note="owner_directed_rebuild_after_manual_flatten",
    )
    if blocker is not None:
        receipt["auto_action"] = "BLOCKED"
        receipt["execution_blocker"] = blocker
    write_json(output, receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--store", type=Path, default=Path("/var/lib/qount/g20-v3/execution.sqlite3"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    execute = args.execute and args.confirm == "OWNER_REBUILD"
    if args.execute and not execute:
        raise SystemExit("confirm_required")
    result = rebuild(_exchange(), output=args.output, store_path=args.store, execute=execute)
    print(json.dumps({k: result.get(k) for k in
                      ("auto_action", "signal_date", "execution_mode", "orders_authorized",
                       "capital_usdt", "order_counts")}))
    print(json.dumps([{k: o.get(k) for k in ("symbol", "action", "status", "executed_quantity")}
                      for o in result.get("orders", [])]))


if __name__ == "__main__":
    main()
