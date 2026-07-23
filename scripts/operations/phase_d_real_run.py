#!/usr/bin/env python
"""Phase D: real minimum certification run.

Runs a single real certification test against the live Binance USD-M
production endpoint.  Each run validates exactly one venue semantic
(section 3.2) and is gated by an independent, single-use CertificationArm
(section 3.1).

Usage::

    # 1. Build a real_minimum plan bound to owner authorization
    PYTHONPATH=src python scripts/operations/phase_d_real_run.py make-plan \\
        --owner-hash <sha256> --symbol BTCUSDT --venue-semantic real_ack_fill

    # 2. Mint an independent certification arm (0600, single-use, time-limited)
    PYTHONPATH=src python scripts/operations/phase_d_real_run.py make-arm \\
        --plan-path state/certification/plans/<plan_id>.json \\
        --arm-token-hash <sha256> --ttl-hours 1

    # 3. Offline dry-run against the local gateway (no real order)
    PYTHONPATH=src python scripts/operations/phase_d_real_run.py dry-run

    # 4. Real run (needs production keys + owner present; section 3.1, 9, 11)
    PYTHONPATH=src python scripts/operations/phase_d_real_run.py run \\
        --plan-path state/certification/plans/<plan_id>.json \\
        --arm-path state/certification/arms/<arm_id>.json

    # 5. Scorecard
    PYTHONPATH=src python scripts/operations/phase_d_real_run.py scorecard
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from qount.certification.arm import CertificationArm
from qount.certification.contracts import CertificationPlan
from qount.certification.contracts import VENUE_SEMANTICS
from qount.certification.gateway import LocalVenueGateway
from qount.certification.gateway import SymbolRules
from qount.certification.runner import CertificationRunner

_DUMMY_HASH = "a" * 64
DEFAULT_SYMBOL = "BTCUSDT"
DEFAULT_QTY = 0.001
DEFAULT_MAX_NOTIONAL = 120.0
DEFAULT_MAX_FEE = 1.0
DEFAULT_MAX_HOLDING = 120.0
DEFAULT_TTL_HOURS = 1


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _plan_fields(plan: CertificationPlan) -> dict:
    return {
        "schema_version": plan.schema_version,
        "plan_id": plan.plan_id,
        "certification_type": plan.certification_type,
        "venue_semantic": plan.venue_semantic,
        "symbol": plan.symbol,
        "action": plan.action,
        "max_notional": plan.max_notional,
        "max_fee": plan.max_fee,
        "max_holding_time_seconds": plan.max_holding_time_seconds,
        "owner_authorization_hash": plan.owner_authorization_hash,
        "arm_token_hash": plan.arm_token_hash,
        "expires_at": plan.expires_at,
        "preflight_snapshot_hash": plan.preflight_snapshot_hash,
        "venue_capability_snapshot_hash": plan.venue_capability_snapshot_hash,
        "zero_position_plan": plan.zero_position_plan,
        "failure_handling_path": plan.failure_handling_path,
        "certification_status": plan.certification_status,
        "batch_type": plan.batch_type,
        "pnl_attribution": plan.pnl_attribution,
        "strategy_id": plan.strategy_id,
        "portfolio_nav": plan.portfolio_nav,
        "orders_authorized": plan.orders_authorized,
        "plan_hash": plan.plan_hash,
    }


def _arm_fields(arm: CertificationArm) -> dict:
    return {
        "schema_version": arm.schema_version,
        "arm_id": arm.arm_id,
        "plan_id": arm.plan_id,
        "authorized_at": arm.authorized_at,
        "expires_at": arm.expires_at,
        "owner_authorization_hash": arm.owner_authorization_hash,
        "arm_token_hash": arm.arm_token_hash,
        "status": arm.status,
        "arm_hash": arm.arm_hash,
    }


def _write_0600(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))
    os.chmod(path, 0o600)


def _load_plan(path: str) -> CertificationPlan:
    data = json.loads(Path(path).read_text())
    plan = CertificationPlan(**data)
    errors = plan.validate()
    if errors:
        raise ValueError(f"certification_plan_load_invalid:{','.join(errors)}")
    return plan


def _load_arm(path: str) -> CertificationArm:
    data = json.loads(Path(path).read_text())
    arm = CertificationArm(**data)
    errors = arm.validate()
    if errors:
        raise ValueError(f"certification_arm_load_invalid:{','.join(errors)}")
    return arm


def _make_real_plan(
    symbol: str,
    venue_semantic: str,
    max_notional: float,
    max_fee: float,
    max_holding_time: float,
    owner_hash: str,
    ttl_hours: float,
) -> CertificationPlan:
    return CertificationPlan.create(
        certification_type="real_minimum",
        venue_semantic=venue_semantic,
        symbol=symbol,
        action="real_certification_pending_owner_authorization",
        max_notional=max_notional,
        max_fee=max_fee,
        max_holding_time_seconds=max_holding_time,
        owner_authorization_hash=owner_hash,
        arm_token_hash=_DUMMY_HASH,
        expires_at=_iso(_now() + timedelta(hours=ttl_hours)),
        preflight_snapshot_hash=_DUMMY_HASH,
        venue_capability_snapshot_hash=_DUMMY_HASH,
        zero_position_plan="market_reverse_to_close_then_verify_zero",
        failure_handling_path="manual_flatten_reconcile_and_halt",
        certification_status="real_pending_owner",
    )


def run_make_plan(args: argparse.Namespace) -> int:
    plan = _make_real_plan(
        symbol=args.symbol,
        venue_semantic=args.venue_semantic,
        max_notional=args.max_notional,
        max_fee=args.max_fee,
        max_holding_time=args.max_holding_time,
        owner_hash=args.owner_hash,
        ttl_hours=args.ttl_hours,
    )
    out = ROOT / "state" / "certification" / "plans" / f"{plan.plan_id}.json"
    _write_0600(out, _plan_fields(plan))
    print("Phase D real_minimum plan")
    print(f"  plan_id: {plan.plan_id}")
    print(f"  venue_semantic: {plan.venue_semantic}")
    print(f"  symbol: {plan.symbol}")
    print(f"  max_notional: {plan.max_notional}")
    print(f"  max_fee: {plan.max_fee}")
    print(f"  max_holding_time_seconds: {plan.max_holding_time_seconds}")
    print(f"  owner_authorization_hash: {plan.owner_authorization_hash}")
    print(f"  certification_status: {plan.certification_status}")
    print(f"  orders_authorized: {plan.orders_authorized}")
    print(f"  artifact (0600): {out}")
    print(
        "\n  Next: make-arm --plan-path <above> --arm-token-hash <sha256>"
    )
    return 0


def run_make_arm(args: argparse.Namespace) -> int:
    plan = _load_plan(args.plan_path)
    arm = CertificationArm.create(
        plan_id=plan.plan_id,
        authorized_at=_iso(_now()),
        expires_at=_iso(_now() + timedelta(hours=args.ttl_hours)),
        owner_authorization_hash=plan.owner_authorization_hash,
        arm_token_hash=args.arm_token_hash,
    )
    out = ROOT / "state" / "certification" / "arms" / f"{arm.arm_id}.json"
    _write_0600(out, _arm_fields(arm))
    print("Phase D certification arm (0600, single-use, time-limited)")
    print(f"  arm_id: {arm.arm_id}")
    print(f"  plan_id: {arm.plan_id}")
    print(f"  status: {arm.status}")
    print(f"  authorized_at: {arm.authorized_at}")
    print(f"  expires_at: {arm.expires_at}")
    print(f"  arm_token_hash: {arm.arm_token_hash}")
    print(f"  orders_authorized: {arm.orders_authorized}")
    print(f"  artifact (0600): {out}")
    print(
        "\n  WARNING: this arm authorizes ONE real certification run. "
        "It is consumed (status=used) after a single run and cannot be reused."
    )
    return 0


def _execute_run(
    runner: CertificationRunner,
    symbol: str,
    qty: float,
    label: str,
) -> dict:
    cid_buy = f"phase-d-{label}-buy-" + _now().strftime("%H%M%S%f")
    cid_sell = cid_buy + "-close"
    runner.submit_order(cid_buy, symbol, "BUY", qty)
    runner.submit_order(cid_sell, symbol, "SELL", qty)
    return runner.generate_result()


def run_dry_run(args: argparse.Namespace) -> int:
    gw = LocalVenueGateway()
    gw.set_symbol_rules({
        DEFAULT_SYMBOL: SymbolRules(
            min_qty=0.001,
            min_notional=100.0,
            step_size=0.001,
            tick_size=0.10,
        ),
    })
    plan = _make_real_plan(
        symbol=DEFAULT_SYMBOL,
        venue_semantic="real_ack_fill",
        max_notional=DEFAULT_MAX_NOTIONAL,
        max_fee=DEFAULT_MAX_FEE,
        max_holding_time=DEFAULT_MAX_HOLDING,
        owner_hash=_DUMMY_HASH,
        ttl_hours=DEFAULT_TTL_HOURS,
    )
    runner = CertificationRunner(plan, gw, source="local_gateway")
    runner.start()
    result = _execute_run(runner, DEFAULT_SYMBOL, DEFAULT_QTY, "dryrun")
    run_id = _now().strftime("%Y%m%dT%H%M%SZ")
    out = {
        "run_id": run_id,
        "source": "local_gateway",
        "timestamp": _iso(_now()),
        "symbol": DEFAULT_SYMBOL,
        "completed": result.completed,
        "final_position_is_zero": result.final_position_is_zero,
        "artifact_member_count": len(result.artifact_members),
    }
    state_dir = ROOT / "state" / "certification" / "runs"
    state_dir.mkdir(parents=True, exist_ok=True)
    out_path = state_dir / f"{run_id}_phase_d_dryrun.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"Phase D dry-run (local gateway, no real order)")
    print(f"  completed: {result.completed}")
    print(f"  final_position_is_zero: {result.final_position_is_zero}")
    print(f"  artifact_members: {len(result.artifact_members)}")
    print(f"  artifact: {out_path}")
    return 0 if result.completed else 1


def run_real(args: argparse.Namespace) -> int:
    from qount.certification.real_client import RealVenueClient
    from qount.exchange_utils import build_exchange
    from qount.settings import Settings

    plan = _load_plan(args.plan_path)
    arm = _load_arm(args.arm_path)
    if not arm.orders_authorized:
        print("ERROR: arm is not in real_authorized status (used or invalid)")
        return 1
    if arm.plan_id != plan.plan_id:
        print("ERROR: arm plan_id does not match plan")
        return 1
    settings = Settings.from_env()
    if not settings.binance_api_key or not settings.binance_api_secret:
        print("ERROR: QOUNT_BINANCE_API_KEY/SECRET not set")
        return 1
    print("Building real Binance USD-M exchange...")
    exchange = build_exchange(settings, private=True)
    client = RealVenueClient(exchange, arm)
    if not client.orders_authorized:
        print("ERROR: certification arm is expired or not valid at this time")
        return 1
    runner = CertificationRunner(plan, client, source="real")
    runner.start()
    print(f"Real certification run: {plan.venue_semantic} on {plan.symbol}")
    print(f"  arm_id: {arm.arm_id}")
    print(f"  expires_at: {arm.expires_at}")
    print("  Submitting real MARKET buy -> sell (section 3.2 real_ack_fill)...")
    try:
        result = _execute_run(runner, plan.symbol, DEFAULT_QTY, "real")
    except Exception as exc:
        print(f"  RUN FAILED: {type(exc).__name__}: {exc}")
        print("  Arm NOT consumed. Attempt manual zero-out and reconciliation.")
        _persist_failed_run(runner, plan, arm)
        return 1
    used_arm = arm.mark_used()
    arm_path = Path(args.arm_path)
    _write_0600(arm_path, _arm_fields(used_arm))
    print(f"  Arm consumed (status=used): {arm_path}")
    run_id = _now().strftime("%Y%m%dT%H%M%SZ")
    out = {
        "run_id": run_id,
        "source": "real",
        "timestamp": _iso(_now()),
        "symbol": plan.symbol,
        "venue_semantic": plan.venue_semantic,
        "plan_id": plan.plan_id,
        "arm_id": arm.arm_id,
        "completed": result.completed,
        "final_position_is_zero": result.final_position_is_zero,
        "artifact_member_count": len(result.artifact_members),
    }
    state_dir = ROOT / "state" / "certification" / "runs"
    state_dir.mkdir(parents=True, exist_ok=True)
    out_path = state_dir / f"{run_id}_phase_d_real.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"  completed: {result.completed}")
    print(f"  final_position_is_zero: {result.final_position_is_zero}")
    print(f"  artifact_members: {len(result.artifact_members)}")
    print(f"  artifact: {out_path}")
    if not result.final_position_is_zero:
        print(
            "  WARNING: non-zero final position! Manual zero-out required. "
            "Do NOT leave residual certification position as Base."
        )
    return 0 if result.completed else 1


def _persist_failed_run(
    runner: CertificationRunner,
    plan: CertificationPlan,
    arm: CertificationArm,
) -> None:
    run_id = _now().strftime("%Y%m%dT%H%M%SZ")
    out = {
        "run_id": run_id,
        "source": "real",
        "status": "failed",
        "timestamp": _iso(_now()),
        "symbol": plan.symbol,
        "plan_id": plan.plan_id,
        "arm_id": arm.arm_id,
        "event_count": len(runner.events),
        "halt_errors": list(runner.halt_errors),
    }
    state_dir = ROOT / "state" / "certification" / "runs"
    state_dir.mkdir(parents=True, exist_ok=True)
    out_path = state_dir / f"{run_id}_phase_d_failed.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"  Failed run evidence: {out_path}")


def run_scorecard(args: argparse.Namespace) -> int:
    state_dir = ROOT / "state" / "certification" / "runs"
    files = sorted(state_dir.glob("*phase_d*.json"))
    if not files:
        print("No Phase D runs found")
        return 1
    latest = json.loads(files[-1].read_text())
    print("=" * 60)
    print(f"  PHASE D CERTIFICATION SCORECARD")
    print(f"  Run: {latest.get('run_id', '?')}")
    print(f"  Source: {latest.get('source', '?')}")
    print(f"  Time: {latest.get('timestamp', '?')}")
    print("=" * 60)
    print(f"  venue_semantic: {latest.get('venue_semantic', '?')}")
    print(f"  symbol: {latest.get('symbol', '?')}")
    print(f"  completed: {latest.get('completed', '?')}")
    print(f"  final_position_is_zero: {latest.get('final_position_is_zero', '?')}")
    print(f"  artifact_members: {latest.get('artifact_member_count', '?')}")
    if latest.get("status") == "failed":
        print(f"  status: FAILED")
        print(f"  halt_errors: {latest.get('halt_errors', [])}")
    print("=" * 60)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase D: real minimum certification run"
    )
    sub = parser.add_subparsers(dest="command")

    mp = sub.add_parser("make-plan", help="Build a real_minimum plan (0600)")
    mp.add_argument("--owner-hash", required=True, help="owner authorization sha256")
    mp.add_argument("--symbol", default=DEFAULT_SYMBOL)
    mp.add_argument(
        "--venue-semantic",
        default="real_ack_fill",
        choices=[v for v in VENUE_SEMANTICS if v.startswith("real_")],
    )
    mp.add_argument("--max-notional", type=float, default=DEFAULT_MAX_NOTIONAL)
    mp.add_argument("--max-fee", type=float, default=DEFAULT_MAX_FEE)
    mp.add_argument("--max-holding-time", type=float, default=DEFAULT_MAX_HOLDING)
    mp.add_argument("--ttl-hours", type=float, default=DEFAULT_TTL_HOURS)

    ma = sub.add_parser("make-arm", help="Mint a certification arm (0600, single-use)")
    ma.add_argument("--plan-path", required=True)
    ma.add_argument("--arm-token-hash", required=True, help="independent arm token sha256")
    ma.add_argument("--ttl-hours", type=float, default=DEFAULT_TTL_HOURS)

    sub.add_parser("dry-run", help="Offline dry-run against local gateway")

    rp = sub.add_parser("run", help="Real certification run (needs keys + owner)")
    rp.add_argument("--plan-path", required=True)
    rp.add_argument("--arm-path", required=True)

    sub.add_parser("scorecard", help="Show scorecard for latest Phase D run")

    args = parser.parse_args()
    if args.command == "make-plan":
        return run_make_plan(args)
    elif args.command == "make-arm":
        return run_make_arm(args)
    elif args.command == "dry-run":
        return run_dry_run(args)
    elif args.command == "run":
        return run_real(args)
    elif args.command == "scorecard":
        return run_scorecard(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
