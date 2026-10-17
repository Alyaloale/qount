#!/usr/bin/env python3
"""
CLI Runner for QOUNT Universal Regime Expectancy Strategy — Binance Futures Interface

Usage:
    # 1. Safe Dry-Run Analysis on Binance Live Market (Default: 100 USDT, Dynamic 2.5X)
    PYTHONPATH=src ./.venv/bin/python scripts/research/run_binance_regime_execution.py --equity 100

    # 2. Conservative Spot/1X Mode
    PYTHONPATH=src ./.venv/bin/python scripts/research/run_binance_regime_execution.py --equity 1000 --mode 1X_SPOT

    # 3. Output as JSON for automated pipelines
    PYTHONPATH=src ./.venv/bin/python scripts/research/run_binance_regime_execution.py --json
"""

import argparse
import json
import sys
from typing import Any, Dict

from qount.research.binance_regime_execution import (
    BINANCE_SYMBOL_MAPPING,
    BinanceFuturesClient,
    BinanceRegimeExecutionEngine,
)


def run_binance_regime_evaluation(
    equity: float = 100.0,
    mode: str = "DYNAMIC_BULL_2_5X",
    dry_run: bool = True,
    orders_authorized: bool = False,
    output_json: bool = False,
) -> Dict[str, Any]:
    # This research runner can evaluate a plan only. CLI flags are not an
    # owner authorization source and therefore can never enable live orders.
    orders_authorized = False
    dry_run = True
    client = BinanceFuturesClient()
    engine = BinanceRegimeExecutionEngine(
        client=client,
        mode=mode,
        dry_run=dry_run,
        orders_authorized=orders_authorized,
        max_positions=1 if mode == "DYNAMIC_BULL_2_5X" else 2,
        risk_budget_pct=0.08 if mode == "DYNAMIC_BULL_2_5X" else 0.04,
    )

    if not output_json:
        print("=" * 95)
        print("QOUNT Universal Regime Expectancy Strategy — Binance Futures Execution Engine")
        print("=" * 95)
        print(f"[*] Account Equity: ${equity:.2f} USDT")
        print(f"[*] Execution Mode: {mode}")
        print(f"[*] Safety Status: dry_run={dry_run} | orders_authorized={orders_authorized}")
        print(f"[*] Fetching live daily candles from Binance USDⓈ-M Futures (fapi.binance.com)...")

    plan = engine.evaluate_live_decision_plan(account_equity=equity, fetch_missing=True)
    execution_result = engine.execute_plan(plan)

    if output_json:
        result_bundle = {
            "plan": plan,
            "execution": execution_result,
            "universe_mapping": BINANCE_SYMBOL_MAPPING,
        }
        print(json.dumps(result_bundle, indent=2))
        return result_bundle

    print("\n" + "-" * 95)
    print(f"DECISION VERDICT: {plan.get('decision')}")
    print("-" * 95)

    if plan.get("decision") == "EXECUTE_TRADE":
        print(f"  Target Symbol    : {plan['symbol']}")
        print(f"  Setup Trigger    : {plan['setup_type']}")
        print(f"  Expectancy Score : {plan['score']:.2f}")
        print(f"  Target Leverage  : {plan['effective_leverage']:.1f}X")
        print("\n  Executable Orders Generated:")
        for idx, o in enumerate(plan["orders"], start=1):
            if o["role"] == "ENTRY":
                print(f"    [{idx}] {o['role']:<12}: BUY  {o['quantity']} {o['symbol']} @ MARKET ~${o['entry_price']:.2f} (Notional: ${o['notional']:.2f} U, Lev: {o['leverage']}X)")
            elif o["role"] == "STOP_LOSS":
                print(f"    [{idx}] {o['role']:<12}: SELL {o['symbol']} STOP_MARKET @ ${o['stop_price']:.2f} (Close Position: True)")
            elif o["role"] == "TAKE_PROFIT":
                print(f"    [{idx}] {o['role']:<12}: SELL {o['symbol']} TAKE_PROFIT_MARKET @ ${o['stop_price']:.2f} (Close Position: True)")
    else:
        print(f"  Reason: {plan.get('reason')}")
        print(f"  Macro Leverage Cap: {plan.get('effective_leverage', 0.0):.1f}X")

    print("\n" + "-" * 95)
    print(f"EXECUTION STATUS: {execution_result.get('status')} ({execution_result.get('mode', 'N/A')})")
    print("=" * 95)
    return {"plan": plan, "execution": execution_result}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--equity", type=float, default=100.0, help="Account equity in USDT (default: 100.0)")
    parser.add_argument("--mode", type=str, default="DYNAMIC_BULL_2_5X", choices=["DYNAMIC_BULL_2_5X", "1X_SPOT", "TRADIFI_MARGIN_2X"], help="Strategy leverage mode")
    parser.add_argument("--live", action="store_true", help="Rejected: live execution requires an existing owner authorization")
    parser.add_argument("--confirm-live-orders", action="store_true", help="Rejected: CLI confirmation is not authorization")
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    args = parser.parse_args()

    if args.live or args.confirm_live_orders:
        print("[ERROR] CLI flags cannot authorize Binance orders; evaluation remains dry-run.", file=sys.stderr)

    run_binance_regime_evaluation(
        equity=args.equity,
        mode=args.mode,
        dry_run=dry_run,
        orders_authorized=orders_authorized,
        output_json=args.json,
    )


if __name__ == "__main__":
    main()
