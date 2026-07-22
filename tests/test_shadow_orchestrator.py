from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from qount.shadow_accounting import run_shadow_accountant


class _MockExchange:
    """Minimal mock exchange for orchestrator tests."""

    def __init__(self) -> None:
        self._trades: dict[str, list[dict[str, Any]]] = {}
        self._income: list[dict[str, Any]] = []
        self._open_orders: list[dict[str, Any]] = []

    def set_trades(self, symbol: str, trades: list[dict[str, Any]]) -> None:
        self._trades[symbol] = trades

    def set_income(self, income: list[dict[str, Any]]) -> None:
        self._income = income

    def set_open_orders(self, orders: list[dict[str, Any]]) -> None:
        self._open_orders = orders

    def fetch_my_trades(
        self, symbol: str, *, start_time: int, end_time: int, limit: int = 1000
    ) -> list[dict[str, Any]]:
        all_trades = self._trades.get(symbol, [])
        return [t for t in all_trades if start_time <= t.get("time", 0) <= end_time][:limit]

    def fetch_income_history(
        self, *, start_time: int, end_time: int, limit: int = 1000
    ) -> list[dict[str, Any]]:
        return [i for i in self._income if start_time <= i.get("time", 0) <= end_time][:limit]

    def fetch_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        if symbol is None:
            return list(self._open_orders)
        return [o for o in self._open_orders if o.get("symbol") == symbol]


def _make_trade(symbol: str, price: str, qty: str, time: int) -> dict[str, Any]:
    return {
        "symbol": symbol, "side": "BUY", "price": price,
        "qty": qty, "commission": "0.04", "realizedPnl": "0",
        "time": time,
    }


def _make_income(income_type: str, amount: str, time: int) -> dict[str, Any]:
    return {
        "symbol": "BTCUSDT", "incomeType": income_type,
        "income": amount, "asset": "USDT", "time": time,
    }


class OrchestratorEmptyStateTest(unittest.TestCase):
    """Test the 0-trade / 0-income case (current production state)."""

    def test_empty_state_diff_passes(self) -> None:
        exchange = _MockExchange()
        primary_snapshot = {
            "positions": {},
            "nav": {
                "equity": 486.16,
                "realized_pnl": 0.0,
                "unrealized_pnl": None,
                "funding": 0.0,
                "commission": 0.0,
                "transfer": 0.0,
            },
        }
        now = dt.datetime.now(dt.timezone.utc)
        live_completed = now.isoformat()
        run = run_shadow_accountant(
            exchange=exchange,
            symbols=["BTCUSDT", "ETHUSDT", "BNBUSDT"],
            start_ms=0,
            end_ms=int(now.timestamp() * 1000),
            primary_snapshot=primary_snapshot,
            initial_equity=486.16,
            current_equity=486.16,
            live_cycle_completed_at=live_completed,
            min_delay_seconds=0.0,
            max_retries=0,
            retry_delay_seconds=0,
        )
        self.assertFalse(run.has_blocking_diff)
        self.assertEqual(run.unknown_income_count, 0)
        self.assertEqual(run.venue, "binance_usdm")

    def test_empty_state_with_archive(self) -> None:
        exchange = _MockExchange()
        primary_snapshot = {
            "positions": {},
            "nav": {
                "equity": 486.16, "realized_pnl": 0.0,
                "unrealized_pnl": None, "funding": 0.0,
                "commission": 0.0, "transfer": 0.0,
            },
        }
        now = dt.datetime.now(dt.timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run1"
            run = run_shadow_accountant(
                exchange=exchange,
                symbols=["BTCUSDT"],
                start_ms=0,
                end_ms=int(now.timestamp() * 1000),
                primary_snapshot=primary_snapshot,
                initial_equity=486.16,
                current_equity=486.16,
                live_cycle_completed_at=now.isoformat(),
                run_dir=run_dir,
                min_delay_seconds=0.0,
                max_retries=0,
                retry_delay_seconds=0,
            )
            self.assertTrue((run_dir / "raw" / "trades.jsonl").is_file())
            self.assertTrue((run_dir / "raw" / "income_history.jsonl").is_file())
            self.assertTrue((run_dir / "raw" / "open_orders.jsonl").is_file())
            self.assertTrue((run_dir / "archive_manifest.json").is_file())
            self.assertTrue((run_dir / "shadow_positions.json").is_file())
            self.assertTrue((run_dir / "shadow_nav.json").is_file())
            self.assertTrue((run_dir / "reconciliation_diff.json").is_file())
            self.assertTrue((run_dir / "shadow_run.json").is_file())
            self.assertTrue((run_dir / "watermark.json").is_file())
            self.assertTrue((run_dir / "coverage_window.json").is_file())

            run_data = json.loads(
                (run_dir / "shadow_run.json").read_text(encoding="ascii")
            )
            self.assertEqual(run_data["run_hash"], run.run_hash)
            self.assertFalse(run_data["has_blocking_diff"])


class OrchestratorWithTradesTest(unittest.TestCase):
    """Test with actual trades and income to verify rebuild + diff."""

    def test_matching_positions_and_nav(self) -> None:
        exchange = _MockExchange()
        exchange.set_trades("BTCUSDT", [
            _make_trade("BTCUSDT", "100000", "0.001", 1000),
        ])
        exchange.set_income([
            _make_income("COMMISSION", "-0.04", 1000),
        ])
        primary_snapshot = {
            "positions": {
                "BTCUSDT": {"quantity": 0.001, "average_cost": 100000.0,
                            "realized_trading_pnl": 0.0},
            },
            "nav": {
                "equity": 486.12,
                "realized_pnl": 0.0,
                "unrealized_pnl": None,
                "funding": 0.0,
                "commission": 0.04,
                "transfer": 0.0,
            },
        }
        now = dt.datetime.now(dt.timezone.utc)
        run = run_shadow_accountant(
            exchange=exchange,
            symbols=["BTCUSDT"],
            start_ms=0,
            end_ms=100000,
            primary_snapshot=primary_snapshot,
            initial_equity=486.16,
            current_equity=486.12,
            mark_prices={"BTCUSDT": 100000.0},
            live_cycle_completed_at=now.isoformat(),
            min_delay_seconds=0.0,
            max_retries=0,
            retry_delay_seconds=0,
        )
        self.assertFalse(run.has_blocking_diff)

    def test_mismatched_positions_block(self) -> None:
        exchange = _MockExchange()
        exchange.set_trades("BTCUSDT", [
            _make_trade("BTCUSDT", "100000", "0.002", 1000),
        ])
        primary_snapshot = {
            "positions": {
                "BTCUSDT": {"quantity": 0.001, "average_cost": 100000.0,
                            "realized_trading_pnl": 0.0},
            },
            "nav": {
                "equity": 486.16, "realized_pnl": 0.0,
                "unrealized_pnl": None, "funding": 0.0,
                "commission": 0.0, "transfer": 0.0,
            },
        }
        now = dt.datetime.now(dt.timezone.utc)
        run = run_shadow_accountant(
            exchange=exchange,
            symbols=["BTCUSDT"],
            start_ms=0,
            end_ms=100000,
            primary_snapshot=primary_snapshot,
            initial_equity=486.16,
            current_equity=486.16,
            live_cycle_completed_at=now.isoformat(),
            min_delay_seconds=0.0,
            max_retries=0,
            retry_delay_seconds=0,
        )
        self.assertTrue(run.has_blocking_diff)

    def test_unknown_income_detected(self) -> None:
        exchange = _MockExchange()
        exchange.set_income([
            _make_income("WEIRD_NEW_FEE", "1.5", 1000),
        ])
        primary_snapshot = {
            "positions": {},
            "nav": {
                "equity": 486.16, "realized_pnl": 0.0,
                "unrealized_pnl": None, "funding": 0.0,
                "commission": 0.0, "transfer": 0.0,
            },
        }
        now = dt.datetime.now(dt.timezone.utc)
        run = run_shadow_accountant(
            exchange=exchange,
            symbols=["BTCUSDT"],
            start_ms=0,
            end_ms=100000,
            primary_snapshot=primary_snapshot,
            initial_equity=486.16,
            current_equity=486.16,
            live_cycle_completed_at=now.isoformat(),
            min_delay_seconds=0.0,
            max_retries=0,
            retry_delay_seconds=0,
        )
        self.assertEqual(run.unknown_income_count, 1)

    def test_watermark_delay_not_satisfied(self) -> None:
        exchange = _MockExchange()
        primary_snapshot = {
            "positions": {},
            "nav": {
                "equity": 486.16, "realized_pnl": 0.0,
                "unrealized_pnl": None, "funding": 0.0,
                "commission": 0.0, "transfer": 0.0,
            },
        }
        now = dt.datetime.now(dt.timezone.utc)
        run = run_shadow_accountant(
            exchange=exchange,
            symbols=["BTCUSDT"],
            start_ms=0,
            end_ms=100000,
            primary_snapshot=primary_snapshot,
            initial_equity=486.16,
            current_equity=486.16,
            live_cycle_completed_at=now.isoformat(),
            min_delay_seconds=3600.0,
            max_retries=0,
            retry_delay_seconds=0,
        )
        self.assertFalse(run.has_blocking_diff)


class OrchestratorGoldenTest(unittest.TestCase):
    """End-to-end golden: trades + income + mark -> rebuild -> diff."""

    def test_golden_run_with_archive_and_verify(self) -> None:
        exchange = _MockExchange()
        exchange.set_trades("BTCUSDT", [
            _make_trade("BTCUSDT", "100000", "0.001", 1000),
            _make_trade("BTCUSDT", "110000", "0.001", 2000),
            {"symbol": "BTCUSDT", "side": "SELL", "price": "115000",
             "qty": "0.001", "commission": "0.046", "realizedPnl": "10.0",
             "time": 3000},
        ])
        exchange.set_income([
            _make_income("COMMISSION", "-0.04", 1000),
            _make_income("COMMISSION", "-0.044", 2000),
            _make_income("COMMISSION", "-0.046", 3000),
            _make_income("FUNDING_FEE", "0.02", 4000),
        ])
        primary_snapshot = {
            "positions": {
                "BTCUSDT": {"quantity": 0.001, "average_cost": 105000.0,
                            "realized_trading_pnl": 10.0},
            },
            "nav": {
                "equity": 506.05,
                "realized_pnl": 10.0,
                "unrealized_pnl": None,
                "funding": 0.02,
                "commission": 0.13,
                "transfer": 0.0,
            },
        }
        now = dt.datetime.now(dt.timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "golden"
            run = run_shadow_accountant(
                exchange=exchange,
                symbols=["BTCUSDT"],
                start_ms=0,
                end_ms=100000,
                primary_snapshot=primary_snapshot,
                initial_equity=486.16,
                current_equity=506.05,
                mark_prices={"BTCUSDT": 115000.0},
                live_cycle_completed_at=now.isoformat(),
                run_dir=run_dir,
                min_delay_seconds=0.0,
                max_retries=0,
                retry_delay_seconds=0,
            )
            self.assertFalse(run.has_blocking_diff)
            self.assertEqual(run.unknown_income_count, 0)

            from qount.shadow_accounting import verify_archive
            manifest = verify_archive(run_dir)
            self.assertIn("trades.jsonl", manifest["files"])
            self.assertEqual(
                manifest["files"]["trades.jsonl"]["record_count"], 3
            )


if __name__ == "__main__":
    unittest.main()
