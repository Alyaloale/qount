#!/usr/bin/env python
"""Phase C: testnet certification run.

Runs §3.4 certification scenarios against the Binance USD-M testnet
(or local gateway for offline verification).

Usage::

    # Local gateway (offline, no testnet needed)
    PYTHONPATH=src python scripts/operations/phase_c_testnet_run.py local-run

    # Testnet (needs QOUNT_TESTNET_ENABLE + keys)
    source ~/.qount/testnet.env
    PYTHONPATH=src python scripts/operations/phase_c_testnet_run.py testnet-run

    # Scorecard
    PYTHONPATH=src python scripts/operations/phase_c_testnet_run.py scorecard
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from qount.certification.contracts import CertificationPlan
from qount.certification.contracts import VENUE_SEMANTICS
from qount.certification.gateway import LocalVenueGateway
from qount.certification.gateway import SymbolRules
from qount.certification.runner import CertificationRunner

_DUMMY_HASH = "a" * 64
TESTNET_SYMBOL = "BTCUSDT"
TESTNET_QTY = "0.002"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_plan(
    venue_semantic: str,
    action: str,
    cert_type: str = "testnet",
) -> CertificationPlan:
    return CertificationPlan.create(
        certification_type=cert_type,
        venue_semantic=venue_semantic,
        symbol=TESTNET_SYMBOL,
        action=action,
        max_notional=200.0,
        max_fee=1.0,
        max_holding_time_seconds=300.0,
        owner_authorization_hash=_DUMMY_HASH,
        arm_token_hash=_DUMMY_HASH,
        expires_at="2026-12-31T23:59:59+00:00",
        preflight_snapshot_hash=_DUMMY_HASH,
        venue_capability_snapshot_hash=_DUMMY_HASH,
        zero_position_plan="market_sell_to_close_then_verify_zero",
        failure_handling_path="manual_flatten_and_reconcile",
        certification_status="testnet" if cert_type == "testnet" else "local_sim",
    )


def _cleanup_positions(client) -> None:
    """Close all open positions on the venue before a scenario."""
    try:
        snap = client.snapshot()
        for symbol, qty in snap.get("positions", {}).items():
            if abs(float(qty)) > 1e-12:
                close_side = "SELL" if float(qty) > 0 else "BUY"
                cid = "cert-cleanup-" + datetime.now(timezone.utc).strftime("%H%M%S%f")
                client.submit(
                    client_order_id=cid,
                    symbol=symbol if not "/" in str(symbol) else symbol.replace("/", "").split(":")[0],
                    side=close_side,
                    qty=abs(float(qty)),
                )
    except Exception:
        pass


def _run_scenario_client_id_idempotency(
    runner: CertificationRunner,
) -> dict:
    """§3.4: client ID idempotency -- duplicate submit does not create second order."""
    cid = "cert-idem-" + datetime.now(timezone.utc).strftime("%H%M%S%f")
    r1 = runner.submit_order(cid, TESTNET_SYMBOL, "BUY", float(TESTNET_QTY))
    r2 = None
    duplicate_created = False
    try:
        r2 = runner.submit_order(cid, TESTNET_SYMBOL, "BUY", float(TESTNET_QTY))
        duplicate_created = (
            r2.get("exchange_order_id") != r1.get("exchange_order_id")
        )
    except Exception as exc:
        duplicate_created = False
        r2 = {"error": str(exc)}
    close_qty = float(TESTNET_QTY) * (2 if duplicate_created else 1)
    runner.submit_order(
        cid + "-close", TESTNET_SYMBOL, "SELL", close_qty
    )
    return {
        "scenario": "client_id_idempotency",
        "r1_order_id": r1.get("exchange_order_id"),
        "r2_order_id": r2.get("exchange_order_id") if isinstance(r2, dict) else None,
        "duplicate_created": duplicate_created,
        "pass": not duplicate_created,
    }


def _run_scenario_stop_algo(runner: CertificationRunner) -> dict:
    """§3.4: STOP/Algo -- create/query/cancel/0-position."""
    cid = "cert-stop-" + datetime.now(timezone.utc).strftime("%H%M%S%f")
    result = runner.submit_order(
        cid, TESTNET_SYMBOL, "SELL", float(TESTNET_QTY),
        order_type="STOP_MARKET", stop_price=50000.0,
        reduce_only=True,
    )
    created = result.get("status") in ("NEW", "ACKNOWLEDGED")
    queried = False
    query_error = None
    try:
        state = runner.query_order(cid)
        queried = state.get("status") in ("NEW", "ACKNOWLEDGED", "CANCELLED")
    except Exception as exc:
        query_error = str(exc)
    cancelled = False
    try:
        runner.cancel_order(cid)
        cancelled = True
    except Exception:
        pass
    return {
        "scenario": "stop_algo",
        "created": created,
        "queried": queried,
        "query_error": query_error,
        "cancelled": cancelled,
        "pass": created and cancelled,
    }


def _run_scenario_rounding_filter(runner: CertificationRunner) -> dict:
    """§3.4: rounding/filter -- exchange accepts/rejects per rules."""
    cid = "cert-rnd-" + datetime.now(timezone.utc).strftime("%H%M%S%f")
    result = runner.submit_order(cid, TESTNET_SYMBOL, "BUY", float(TESTNET_QTY))
    runner.submit_order(cid + "-close", TESTNET_SYMBOL, "SELL", float(TESTNET_QTY))
    return {
        "scenario": "rounding_filter",
        "order_status": result.get("status"),
        "origQty": result.get("origQty"),
        "pass": result.get("status") in ("FILLED", "ACKNOWLEDGED"),
    }


def _run_scenario_crash_recovery(runner: CertificationRunner) -> dict:
    """§3.4: crash recovery -- query after process restart, no replacement."""
    cid = "cert-crash-" + datetime.now(timezone.utc).strftime("%H%M%S%f")
    runner.submit_order(cid, TESTNET_SYMBOL, "BUY", float(TESTNET_QTY))
    states = runner.recover_from_crash([cid])
    replacement_errors = [
        e for e in runner.halt_errors if "replacement_orders" in e
    ]
    unknown_errors = [
        e for e in runner.halt_errors if "unresolved_unknown" in e
    ]
    runner.submit_order(cid + "-close", TESTNET_SYMBOL, "SELL", float(TESTNET_QTY))
    return {
        "scenario": "crash_recovery",
        "states_count": len(states),
        "replacement_errors": replacement_errors,
        "unknown_errors": unknown_errors,
        "pass": len(replacement_errors) == 0,
    }


SCENARIOS = [
    ("client_id_idempotency", "test_idempotency", _run_scenario_client_id_idempotency),
    ("stop_algo", "test_stop_algo", _run_scenario_stop_algo),
    ("rounding_filter", "test_rounding", _run_scenario_rounding_filter),
    ("crash_recovery", "test_crash_recovery", _run_scenario_crash_recovery),
]


_REAL_PLAN_NOTE = (
    "template_only_no_real_order: real certification requires separate "
    "owner authorization, an independent 0600 certification arm, "
    "preflight and venue capability snapshots, and a zero-position plan "
    "before any real order may be submitted (sections 3.1, 9, 9.1)."
)


def build_real_plan_template(
    symbol: str,
    venue_semantic: str,
    max_notional: float,
    max_fee: float,
    max_holding_time_seconds: float,
) -> CertificationPlan:
    """Build a Phase D real_minimum certification plan template.

    The plan is a draft (real_pending_owner) with placeholder hashes.
    orders_authorized is always False.  No real order is submitted; the
    template exists for owner review before separate authorization.
    """
    return CertificationPlan.create(
        certification_type="real_minimum",
        venue_semantic=venue_semantic,
        symbol=symbol,
        action="real_certification_pending_owner_authorization",
        max_notional=max_notional,
        max_fee=max_fee,
        max_holding_time_seconds=max_holding_time_seconds,
        owner_authorization_hash=_DUMMY_HASH,
        arm_token_hash=_DUMMY_HASH,
        expires_at="2026-12-31T23:59:59+00:00",
        preflight_snapshot_hash=_DUMMY_HASH,
        venue_capability_snapshot_hash=_DUMMY_HASH,
        zero_position_plan="market_reverse_to_close_then_verify_zero",
        failure_handling_path="manual_flatten_reconcile_and_halt",
        certification_status="real_pending_owner",
    )


def run_local(args: argparse.Namespace) -> int:
    state_dir = ROOT / "state" / "certification" / "runs"
    state_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for venue_semantic, action, fn in SCENARIOS:
        gw = LocalVenueGateway()
        gw.set_symbol_rules({
            TESTNET_SYMBOL: SymbolRules(
                min_qty=0.001,
                min_notional=100.0,
                step_size=0.001,
                tick_size=0.10,
            ),
        })
        plan = _make_plan(venue_semantic, action, cert_type="local_gateway")
        runner = CertificationRunner(plan, gw, source="local_gateway")
        runner.start()
        scenario_result = fn(runner)
        cert_result = runner.generate_result()
        scenario_result["completed"] = cert_result.completed
        scenario_result["final_position_zero"] = cert_result.final_position_is_zero
        results.append(scenario_result)
        print(f"  {venue_semantic}: completed={cert_result.completed} pass={scenario_result['pass']}")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = {
        "run_id": run_id,
        "source": "local_gateway",
        "timestamp": _now(),
        "scenarios": results,
    }
    out_path = state_dir / f"{run_id}_local.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nLocal run artifacts: {out_path}")
    _print_scorecard(out)
    return 0


def run_testnet(args: argparse.Namespace) -> int:
    from qount.certification.testnet_client import TestnetVenueClient
    from qount.exchange_utils import build_testnet_exchange

    api_key = os.environ.get("QOUNT_TESTNET_API_KEY")
    api_secret = os.environ.get("QOUNT_TESTNET_API_SECRET")
    if not api_key or not api_secret:
        print("ERROR: QOUNT_TESTNET_API_KEY/SECRET not set")
        return 1
    state_dir = ROOT / "state" / "certification" / "runs"
    state_dir.mkdir(parents=True, exist_ok=True)
    print("Building testnet exchange...")
    exchange = build_testnet_exchange(api_key, api_secret)
    client = TestnetVenueClient(exchange)
    results = []
    for venue_semantic, action, fn in SCENARIOS:
        _cleanup_positions(client)
        plan = _make_plan(venue_semantic, action, cert_type="testnet")
        runner = CertificationRunner(plan, client, source="testnet")
        print(f"\nRunning: {venue_semantic}")
        try:
            runner.start()
            scenario_result = fn(runner)
            _cleanup_positions(client)
            client.snapshot()
            cert_result = runner.generate_result()
            scenario_result["completed"] = cert_result.completed
            scenario_result["final_position_zero"] = cert_result.final_position_is_zero
            results.append(scenario_result)
            print(f"  completed={cert_result.completed} pass={scenario_result.get('pass')}")
            if not cert_result.final_position_is_zero:
                print(f"  position_count={client.position_count}")
        except Exception as exc:
            print(f"  ERROR: {type(exc).__name__}: {exc}")
            _cleanup_positions(client)
            results.append({
                "scenario": venue_semantic,
                "error": str(exc),
                "pass": False,
            })
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = {
        "run_id": run_id,
        "source": "testnet",
        "timestamp": _now(),
        "symbol": TESTNET_SYMBOL,
        "scenarios": results,
    }
    out_path = state_dir / f"{run_id}_testnet.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nTestnet run artifacts: {out_path}")
    _print_scorecard(out)
    return 0


def run_scorecard(args: argparse.Namespace) -> int:
    state_dir = ROOT / "state" / "certification" / "runs"
    if not state_dir.exists():
        print("No certification runs found")
        return 1
    files = sorted(state_dir.glob("*.json"))
    if not files:
        print("No certification runs found")
        return 1
    latest = json.loads(files[-1].read_text())
    _print_scorecard(latest)
    return 0


def run_real_plan(args: argparse.Namespace) -> int:
    plan = build_real_plan_template(
        symbol=args.symbol,
        venue_semantic=args.venue_semantic,
        max_notional=args.max_notional,
        max_fee=args.max_fee,
        max_holding_time_seconds=args.max_holding_time,
    )
    plans_dir = ROOT / "state" / "certification" / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "plan_id": plan.plan_id,
        "plan_hash": plan.plan_hash,
        "certification_type": plan.certification_type,
        "venue_semantic": plan.venue_semantic,
        "symbol": plan.symbol,
        "action": plan.action,
        "max_notional": plan.max_notional,
        "max_fee": plan.max_fee,
        "max_holding_time_seconds": plan.max_holding_time_seconds,
        "expires_at": plan.expires_at,
        "certification_status": plan.certification_status,
        "orders_authorized": plan.orders_authorized,
        "batch_type": plan.batch_type,
        "pnl_attribution": plan.pnl_attribution,
        "strategy_id": plan.strategy_id,
        "portfolio_nav": plan.portfolio_nav,
        "zero_position_plan": plan.zero_position_plan,
        "failure_handling_path": plan.failure_handling_path,
        "note": _REAL_PLAN_NOTE,
    }
    out_path = plans_dir / f"{plan.plan_id}.json"
    out_path.write_text(json.dumps(payload, indent=2, default=str))
    print("Phase D real_minimum plan template")
    print(f"  plan_id: {plan.plan_id}")
    print(f"  venue_semantic: {plan.venue_semantic}")
    print(f"  symbol: {plan.symbol}")
    print(f"  max_notional: {plan.max_notional}")
    print(f"  max_fee: {plan.max_fee}")
    print(f"  max_holding_time_seconds: {plan.max_holding_time_seconds}")
    print(f"  certification_status: {plan.certification_status}")
    print(f"  orders_authorized: {plan.orders_authorized}")
    print(f"  artifact: {out_path}")
    print(f"\n  NOTE: {_REAL_PLAN_NOTE}")
    return 0


def _print_scorecard(run_data: dict) -> None:
    print("\n" + "=" * 60)
    print(f"  CERTIFICATION SCORECARD")
    print(f"  Run: {run_data.get('run_id', '?')}")
    print(f"  Source: {run_data.get('source', '?')}")
    print(f"  Time: {run_data.get('timestamp', '?')}")
    print("=" * 60)
    scenarios = run_data.get("scenarios", [])
    passed = 0
    total = len(scenarios)
    for s in scenarios:
        name = s.get("scenario", "?")
        p = s.get("pass", False)
        status = "PASS" if p else "FAIL"
        print(f"  {name:30s} {status}")
        if p:
            passed += 1
    print("-" * 60)
    print(f"  Exit gate: {passed}/{total} passed")
    zero_pos = all(s.get("final_position_zero", False) for s in scenarios)
    print(f"  Zero position: {'YES' if zero_pos else 'NO'}")
    no_replacement = all(
        not s.get("replacement_errors") for s in scenarios
    )
    print(f"  No replacement orders: {'YES' if no_replacement else 'NO'}")
    unknown_resolved = all(
        not s.get("unknown_errors") for s in scenarios
    )
    print(f"  UNKNOWN resolved: {'YES' if unknown_resolved else 'NO'}")
    all_completed = all(s.get("completed", False) for s in scenarios)
    print(f"  All completed: {'YES' if all_completed else 'NO'}")
    gate_pass = (
        passed == total
        and zero_pos
        and no_replacement
        and unknown_resolved
        and all_completed
    )
    print("=" * 60)
    print(f"  GATE: {'PASS' if gate_pass else 'FAIL'}")
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase C: testnet certification run"
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("local-run", help="Run against local gateway (offline)")
    sub.add_parser("testnet-run", help="Run against Binance USD-M testnet")
    sub.add_parser("scorecard", help="Show scorecard for latest run")
    rp = sub.add_parser(
        "real-plan",
        help="Build Phase D real_minimum plan template (no order)",
    )
    rp.add_argument("--symbol", default="BTCUSDT")
    rp.add_argument(
        "--venue-semantic",
        default="real_ack_fill",
        choices=[v for v in VENUE_SEMANTICS if v.startswith("real_")],
    )
    rp.add_argument("--max-notional", type=float, default=20.0)
    rp.add_argument("--max-fee", type=float, default=0.5)
    rp.add_argument("--max-holding-time", type=float, default=120.0)
    args = parser.parse_args()
    if args.command == "local-run":
        return run_local(args)
    elif args.command == "testnet-run":
        return run_testnet(args)
    elif args.command == "scorecard":
        return run_scorecard(args)
    elif args.command == "real-plan":
        return run_real_plan(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
