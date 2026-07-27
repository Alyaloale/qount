#!/usr/bin/env python3
"""Freeze a pre-event range and print order-free fade plans (no orders)."""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import statistics
import sys
from pathlib import Path
from typing import Sequence

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.small_account.event_signal import CompletedCandle  # noqa: E402
from qount.small_account.fomc_adapter import DEFAULT_FOMC_COSTS  # noqa: E402
from qount.small_account.fomc_adapter import DEFAULT_FOMC_STOP_GAP_RATE  # noqa: E402
from qount.small_account.range_signal import DEFAULT_RANGE_FADE_POLICY  # noqa: E402
from qount.small_account.range_signal import evaluate_range_fade_signal  # noqa: E402
from qount.small_account.risk import size_linear_usdt_futures  # noqa: E402


CANARY_RISK_BUDGET_USDT = 5.0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--range-id", required=True)
    parser.add_argument(
        "--cash-cutoff",
        required=True,
        help="ISO UTC hard deadline; the account must be flat before it.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("freeze", help="Freeze H0/L0/ATR0/V20 once, immutably.")
    scan = subparsers.add_parser("scan", help="Evaluate both fade sides, plan only.")
    scan.add_argument("--risk-budget", type=float, default=CANARY_RISK_BUDGET_USDT)
    return parser


def _utc(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise SystemExit("cash cutoff must be timezone aware")
    return parsed.astimezone(dt.timezone.utc)


def _completed_candles(
    raw: Sequence[Sequence[float]], *, interval_minutes: int, now: dt.datetime
) -> list[CompletedCandle]:
    candles: list[CompletedCandle] = []
    for opened_ms, open_, high, low, close, volume in raw:
        closed_at = dt.datetime.fromtimestamp(
            opened_ms / 1000.0, tz=dt.timezone.utc
        ) + dt.timedelta(minutes=interval_minutes)
        if closed_at > now:
            continue
        candles.append(
            CompletedCandle(
                interval_minutes=interval_minutes,
                closed_at=closed_at,
                open=float(open_),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=float(volume),
            )
        )
    return candles


def _fetch(symbol: str, now: dt.datetime) -> tuple[list[CompletedCandle], list[CompletedCandle], dict]:
    import ccxt

    exchange = ccxt.binanceusdm({"enableRateLimit": True})
    markets = exchange.load_markets()
    market = markets[symbol]
    hourly = _completed_candles(
        exchange.fetch_ohlcv(symbol, "1h", limit=100), interval_minutes=60, now=now
    )
    fifteen = _completed_candles(
        exchange.fetch_ohlcv(symbol, "15m", limit=100), interval_minutes=15, now=now
    )
    return hourly, fifteen, market


def _freeze_path(state_root: Path, range_id: str) -> Path:
    return state_root / "pre_event_range" / range_id / "freeze.json"


def _summary(value: dict[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True))


def _freeze(args: argparse.Namespace) -> int:
    now = dt.datetime.now(dt.timezone.utc)
    hourly, fifteen, _ = _fetch(args.symbol, now)
    if len(hourly) < 73 or len(fifteen) < 20:
        raise SystemExit("insufficient completed candle history for freeze")
    range_bars = hourly[-72:]
    atr_bars = hourly[-15:]
    true_ranges = [
        max(
            current.high - current.low,
            abs(current.high - previous.close),
            abs(current.low - previous.close),
        )
        for previous, current in zip(atr_bars, atr_bars[1:])
    ]
    core = {
        "range_id": args.range_id,
        "symbol": args.symbol,
        "frozen_at": now.isoformat(),
        "cash_cutoff_at": _utc(args.cash_cutoff).isoformat(),
        "h0": max(candle.high for candle in range_bars),
        "l0": min(candle.low for candle in range_bars),
        "atr0": sum(true_ranges) / len(true_ranges),
        "v20_15m": statistics.median(candle.volume for candle in fifteen[-20:]),
        "hourly_last_closed_at": hourly[-1].closed_at.isoformat(),
        "fifteen_last_closed_at": fifteen[-1].closed_at.isoformat(),
    }
    core["freeze_hash"] = hashlib.sha256(
        json.dumps(core, sort_keys=True).encode("utf-8")
    ).hexdigest()
    path = _freeze_path(args.state_root, args.range_id)
    if path.exists():
        raise SystemExit(f"freeze already exists and is immutable: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(core, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    _summary(core | {"freeze_file": str(path), "exchange_mutation_attempted": False})
    return 0


def _scan(args: argparse.Namespace) -> int:
    path = _freeze_path(args.state_root, args.range_id)
    if not path.exists():
        raise SystemExit(f"no freeze artifact at {path}; run freeze first")
    freeze = json.loads(path.read_text(encoding="utf-8"))
    now = dt.datetime.now(dt.timezone.utc)
    _, fifteen, market = _fetch(freeze["symbol"], now)
    recent = fifteen[-24:]
    if not recent:
        raise SystemExit("no completed 15m candles available")
    if now - recent[-1].closed_at > dt.timedelta(minutes=16):
        raise SystemExit("fifteen minute data stale; refusing to plan")
    planned_entry = recent[-1].close
    quantity_step = float(
        (market.get("precision") or {}).get("amount") or 0.001
    )
    if quantity_step >= 1.0:
        quantity_step = 10.0 ** -quantity_step
    minimum_notional = float(
        ((market.get("limits") or {}).get("cost") or {}).get("min") or 0.0
    )
    cutoff = _utc(freeze["cash_cutoff_at"])
    result: dict[str, object] = {
        "range_id": freeze["range_id"],
        "symbol": freeze["symbol"],
        "freeze_hash": freeze["freeze_hash"],
        "evaluated_at": now.isoformat(),
        "planned_entry_price": planned_entry,
        "orders_authorized": False,
        "exchange_mutation_attempted": False,
        "sides": {},
    }
    exit_code = 2
    for side in ("long", "short"):
        decision = evaluate_range_fade_signal(
            side=side,
            h0=float(freeze["h0"]),
            l0=float(freeze["l0"]),
            atr0=float(freeze["atr0"]),
            v20_15m=float(freeze["v20_15m"]),
            recent_15m=recent,
            planned_entry_price=planned_entry,
            cash_cutoff_at=cutoff,
            evaluated_at=now,
            policy=DEFAULT_RANGE_FADE_POLICY,
        )
        side_report: dict[str, object] = {
            "state": decision.state,
            "reasons": list(decision.reasons),
            "entry_zone_line": decision.entry_zone_line,
            "break_line": decision.break_line,
            "target_price": decision.target_price,
            "structural_stop_price": decision.structural_stop_price,
        }
        if decision.armed:
            sizing = size_linear_usdt_futures(
                side=side,
                entry_price=planned_entry,
                stop_price=float(decision.structural_stop_price),
                target_price=float(decision.target_price),
                stop_gap_rate=DEFAULT_FOMC_STOP_GAP_RATE,
                quantity_step=quantity_step,
                costs=DEFAULT_FOMC_COSTS,
                risk_budget_usdt=args.risk_budget,
                minimum_notional_usdt=minimum_notional,
                protective_cycle_verified=False,
            )
            side_report["sizing"] = dataclasses.asdict(sizing)
            if sizing.allowed:
                exit_code = 0
        result["sides"][side] = side_report
    _summary(result)
    return exit_code


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "freeze":
        return _freeze(args)
    return _scan(args)


if __name__ == "__main__":
    raise SystemExit(main())
