#!/usr/bin/env python3
"""Phase B read-only parallel run: shadow accountant + venue snapshot + HALT observer.

Runs after each live cycle to independently verify positions, NAV,
venue capabilities, and HALT classification.  Does NOT modify the
dispatcher, orders, HALT file, or any production state.

Usage on VPS::

    PYTHONPATH=src ./.venv/bin/python scripts/operations/phase_b_readonly_run.py \\
        --mode all \\
        --symbols BTCUSDT ETHUSDT BNBUSDT \\
        --runtime-ledger-path /root/qount/state/mini_trend/forward/latest/runtime.sqlite3 \\
        --halt-path /root/qount/state/mini_trend/HALT \\
        --state-dir /root/qount/state/phase_b \\
        --live-cycle-completed-at 2026-07-23T00:00:00+00:00
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.exchange_utils import build_exchange  # noqa: E402
from qount.settings import Settings  # noqa: E402


SYMBOLS_DEFAULT = ("BTCUSDT", "ETHUSDT", "BNBUSDT")
CHANGELOG_URL = (
    "https://developers.binance.com/en/docs/products/"
    "derivatives-trading-usds-futures/change-log"
)


class CcxtShadowExchangeAdapter:
    """Adapter wrapping ccxt exchange for shadow accountant data fetching.

    Uses ccxt's implicit API methods to fetch raw Binance USD-M
    responses (not ccxt-standardized objects) so that shadow
    rebuild functions can consume them directly.
    """

    def __init__(self, exchange: Any) -> None:
        self._exchange = exchange

    def fetch_my_trades(
        self, symbol: str, *, start_time: int, end_time: int, limit: int = 1000
    ) -> list[dict[str, Any]]:
        result = self._exchange.fapiPrivateGetUserTrades(
            {"symbol": symbol, "startTime": start_time, "endTime": end_time, "limit": limit}
        )
        return result if isinstance(result, list) else []

    def fetch_income_history(
        self, *, start_time: int, end_time: int, limit: int = 1000
    ) -> list[dict[str, Any]]:
        result = self._exchange.fapiPrivateGetIncome(
            {"startTime": start_time, "endTime": end_time, "limit": limit}
        )
        return result if isinstance(result, list) else []

    def fetch_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        result = self._exchange.fapiPrivateGetOpenOrders(params)
        return result if isinstance(result, list) else []


class CcxtVenueDataFetcher:
    """Adapter wrapping ccxt exchange for venue data fetching."""

    def __init__(self, exchange: Any) -> None:
        self._exchange = exchange

    def fetch_exchange_info(self) -> dict[str, Any]:
        result = self._exchange.fapiPublicGetExchangeInfo()
        return result if isinstance(result, dict) else {}

    def fetch_server_time_ms(self) -> int:
        result = self._exchange.fapiPublicGetTime()
        return int(result.get("serverTime", 0)) if isinstance(result, dict) else 0

    def fetch_changelog_body(self) -> tuple[str, str]:
        observed_at = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            req = urllib.request.Request(
                CHANGELOG_URL,
                headers={"User-Agent": "qount-phase-b/0.1"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return body, observed_at


def _get_account_equity(exchange: Any) -> float:
    """Fetch current USDT wallet balance from Binance USD-M."""
    try:
        balance = exchange.fetch_balance()
        usdt = balance.get("USDT", {}) if isinstance(balance, dict) else {}
        return float(usdt.get("total", 0.0))
    except Exception:
        return 0.0


def _run_shadow(
    exchange: Any,
    symbols: list[str],
    runtime_ledger_path: str,
    state_dir: str,
    live_cycle_completed_at: str,
) -> dict[str, Any]:
    from qount.primary_snapshot import extract_primary_snapshot
    from qount.shadow_accounting import run_shadow_accountant

    primary_snapshot = extract_primary_snapshot(runtime_ledger_path)
    current_equity = _get_account_equity(exchange)
    primary_equity = primary_snapshot.get("nav", {}).get("equity")
    initial_equity = float(primary_equity) if primary_equity is not None else current_equity

    now_ms = int(time.time() * 1000)
    lookback_ms = 24 * 60 * 60 * 1000
    start_ms = now_ms - lookback_ms

    adapter = CcxtShadowExchangeAdapter(exchange)
    run_dir = Path(state_dir) / "shadow_accounting" / "runs" / dt.datetime.now(
        dt.timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")

    run = run_shadow_accountant(
        exchange=adapter,
        symbols=symbols,
        start_ms=start_ms,
        end_ms=now_ms,
        primary_snapshot=primary_snapshot,
        initial_equity=initial_equity,
        current_equity=current_equity,
        live_cycle_completed_at=live_cycle_completed_at,
        run_dir=str(run_dir),
        min_delay_seconds=0.0,
        max_retries=3,
        retry_delay_seconds=1.0,
    )

    return {
        "run_id": run.run_id,
        "has_blocking_diff": run.has_blocking_diff,
        "unknown_income_count": run.unknown_income_count,
        "watermark_hash": run.watermark_hash,
        "run_dir": str(run_dir),
    }


def _run_venue(
    exchange: Any,
    symbols: list[str],
    state_dir: str,
) -> dict[str, Any]:
    from qount.venue import run_venue_snapshot

    archive_dir = Path(state_dir) / "venue_snapshots"
    fetcher = CcxtVenueDataFetcher(exchange)

    snapshot = run_venue_snapshot(
        fetcher=fetcher,
        symbols=symbols,
        archive_dir=str(archive_dir),
    )
    archive_path = Path(archive_dir) / (
        dt.datetime.fromisoformat(snapshot.observed_at).strftime(
            "%Y%m%dT%H%M%SZ"
        )
        + ".json"
    )

    return {
        "snapshot_id": snapshot.snapshot_id,
        "compatibility": snapshot.compatibility,
        "blockers": list(snapshot.blockers),
        "archive_path": str(archive_path),
    }


def _run_halt(
    runtime_ledger_path: str,
    halt_path: str | None,
    state_dir: str,
) -> dict[str, Any]:
    from qount.halt import observe_halt_state
    from qount.primary_snapshot import extract_runtime_state

    runtime_state = extract_runtime_state(runtime_ledger_path)
    archive_dir = Path(state_dir) / "halt_observations"

    events = observe_halt_state(
        halt_path=halt_path,
        unknown_order_count=runtime_state["unknown_order_count"],
        reconciliation_halt_required=runtime_state.get(
            "reconciliation_halt_required", False
        ),
        reconciliation_passed=runtime_state.get("reconciliation_passed"),
        data_quality_blockers=runtime_state.get("data_quality_blockers", 0),
        archive_dir=str(archive_dir),
    )

    return {
        "event_count": len(events),
        "halt_types": [e.halt_type for e in events],
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("shadow", "venue", "halt", "all"),
        default="all",
    )
    parser.add_argument("--symbols", nargs="+", default=list(SYMBOLS_DEFAULT))
    parser.add_argument("--runtime-ledger-path", required=True)
    parser.add_argument("--halt-path", default=None)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument(
        "--live-cycle-completed-at",
        default=None,
        help="ISO timestamp of live cycle completion",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    os.environ.setdefault("QOUNT_EXCHANGE_BYPASS_PROXY", "true")
    os.environ.setdefault("http_proxy", "")
    os.environ.setdefault("https_proxy", "")
    os.environ.setdefault("all_proxy", "")

    settings = Settings.from_env()
    exchange = build_exchange(settings, private=True)

    live_completed = args.live_cycle_completed_at or dt.datetime.now(
        dt.timezone.utc
    ).isoformat()

    results: dict[str, Any] = {
        "mode": args.mode,
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "symbols": args.symbols,
    }

    if args.mode in ("shadow", "all"):
        try:
            results["shadow"] = _run_shadow(
                exchange,
                args.symbols,
                args.runtime_ledger_path,
                args.state_dir,
                live_completed,
            )
        except Exception as exc:
            results["shadow_error"] = str(exc)

    if args.mode in ("venue", "all"):
        try:
            results["venue"] = _run_venue(
                exchange,
                args.symbols,
                args.state_dir,
            )
        except Exception as exc:
            results["venue_error"] = str(exc)

    if args.mode in ("halt", "all"):
        try:
            results["halt"] = _run_halt(
                args.runtime_ledger_path,
                args.halt_path,
                args.state_dir,
            )
        except Exception as exc:
            results["halt_error"] = str(exc)

    results["completed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()

    try:
        from qount.shadow_accounting.progress import record_phase_b_cycle

        results["progress"] = record_phase_b_cycle(args.state_dir, results)
    except Exception as exc:
        results["progress_error"] = str(exc)
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return 1

    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
