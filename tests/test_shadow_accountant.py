from __future__ import annotations

import unittest

from qount.shadow_accounting import ShadowNavMark
from qount.shadow_accounting import ShadowPosition
from qount.shadow_accounting import apply_mark_prices
from qount.shadow_accounting import detect_unknown_income_halt_candidates
from qount.shadow_accounting import diff_nav
from qount.shadow_accounting import diff_positions
from qount.shadow_accounting import has_blocking_diff
from qount.shadow_accounting import rebuild_cash_events
from qount.shadow_accounting import rebuild_nav
from qount.shadow_accounting import rebuild_positions
from qount.shadow_accounting import verify_coverage_window


class RebuildPositionsTest(unittest.TestCase):
    def test_buy_builds_long_position(self):
        trades = [
            {
                "symbol": "BTCUSDT",
                "side": "BUY",
                "price": "100000.0",
                "qty": "0.001",
                "commission": "0.04",
                "realizedPnl": "0",
                "time": 1721712000000,
            },
        ]
        positions = rebuild_positions(trades)
        self.assertIn("BTCUSDT", positions)
        pos = positions["BTCUSDT"]
        self.assertAlmostEqual(pos.quantity, 0.001)
        self.assertAlmostEqual(pos.cost_basis, 100000.0)
        self.assertAlmostEqual(pos.realized_pnl, 0.0)

    def test_average_cost_on_multiple_buys(self):
        trades = [
            {"symbol": "BTCUSDT", "side": "BUY", "price": "100000.0",
             "qty": "0.001", "commission": "0.04", "realizedPnl": "0",
             "time": 1721712000000},
            {"symbol": "BTCUSDT", "side": "BUY", "price": "110000.0",
             "qty": "0.001", "commission": "0.044", "realizedPnl": "0",
             "time": 1721712100000},
        ]
        positions = rebuild_positions(trades)
        pos = positions["BTCUSDT"]
        self.assertAlmostEqual(pos.quantity, 0.002)
        self.assertAlmostEqual(pos.cost_basis, 105000.0)

    def test_sell_realizes_pnl(self):
        trades = [
            {"symbol": "BTCUSDT", "side": "BUY", "price": "100000.0",
             "qty": "0.002", "commission": "0.08", "realizedPnl": "0",
             "time": 1721712000000},
            {"symbol": "BTCUSDT", "side": "SELL", "price": "105000.0",
             "qty": "0.001", "commission": "0.042", "realizedPnl": "5.0",
             "time": 1721712100000},
        ]
        positions = rebuild_positions(trades)
        pos = positions["BTCUSDT"]
        self.assertAlmostEqual(pos.quantity, 0.001)
        self.assertAlmostEqual(pos.realized_pnl, 5.0)

    def test_sell_to_zero_does_not_go_short(self):
        trades = [
            {"symbol": "BTCUSDT", "side": "BUY", "price": "100000.0",
             "qty": "0.001", "commission": "0.04", "realizedPnl": "0",
             "time": 1721712000000},
            {"symbol": "BTCUSDT", "side": "SELL", "price": "105000.0",
             "qty": "0.002", "commission": "0.084", "realizedPnl": "5.0",
             "time": 1721712100000},
        ]
        positions = rebuild_positions(trades)
        pos = positions["BTCUSDT"]
        self.assertAlmostEqual(pos.quantity, 0.0)
        self.assertAlmostEqual(pos.cost_basis, 0.0)

    def test_mark_prices_compute_unrealized(self):
        trades = [
            {"symbol": "BTCUSDT", "side": "BUY", "price": "100000.0",
             "qty": "0.001", "commission": "0.04", "realizedPnl": "0",
             "time": 1721712000000},
        ]
        positions = rebuild_positions(trades)
        positions = apply_mark_prices(positions, {"BTCUSDT": 105000.0})
        pos = positions["BTCUSDT"]
        self.assertAlmostEqual(pos.unrealized_pnl, 5.0)


class RebuildNavTest(unittest.TestCase):
    def test_identity_equation_verified(self):
        trades = [
            {"symbol": "BTCUSDT", "side": "BUY", "price": "100000.0",
             "qty": "0.001", "commission": "0.04", "realizedPnl": "0",
             "time": 1721712000000},
        ]
        positions = rebuild_positions(trades)
        positions = apply_mark_prices(positions, {"BTCUSDT": 105000.0})
        income = [
            {"symbol": "BTCUSDT", "incomeType": "COMMISSION",
             "income": "-0.04", "asset": "USDT", "time": 1721712000000},
            {"symbol": "BTCUSDT", "incomeType": "FUNDING_FEE",
             "income": "0.01", "asset": "USDT", "time": 1721712100000},
        ]
        cash_events = rebuild_cash_events(income)
        initial_equity = 486.16
        realized = sum(p.realized_pnl for p in positions.values())
        unrealized = sum(p.unrealized_pnl for p in positions.values())
        funding = 0.01
        commission = 0.04
        current_equity = (
            initial_equity + realized + unrealized + funding - commission
        )
        nav = rebuild_nav(
            positions=positions,
            cash_events=cash_events,
            initial_equity=initial_equity,
            current_equity=current_equity,
        )
        self.assertTrue(nav.identity_verified)
        self.assertAlmostEqual(nav.residual, 0.0, places=8)
    def test_identity_equation_fails_on_mismatch(self):
        nav = rebuild_nav(
            positions={},
            cash_events=[],
            initial_equity=100.0,
            current_equity=200.0,
        )
        self.assertFalse(nav.identity_verified)
        self.assertNotEqual(nav.residual, 0.0)


class RebuildCashEventsTest(unittest.TestCase):
    def test_known_income_types_classified(self):
        income = [
            {"symbol": "BTCUSDT", "incomeType": "COMMISSION",
             "income": "-0.04", "asset": "USDT", "time": 1721712000000},
            {"symbol": "BTCUSDT", "incomeType": "FUNDING_FEE",
             "income": "0.01", "asset": "USDT", "time": 1721712100000},
        ]
        events = rebuild_cash_events(income)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].event_type, "commission")
        self.assertEqual(events[1].event_type, "funding")

    def test_unknown_income_type_flagged(self):
        income = [
            {"symbol": "BTCUSDT", "incomeType": "NEW_TYPE",
             "income": "1.5", "asset": "USDT", "time": 1721712000000},
        ]
        events = rebuild_cash_events(income)
        self.assertEqual(events[0].event_type, "unknown_income")
        self.assertEqual(events[0].income_type, "NEW_TYPE")

    def test_unknown_nonzero_income_forms_halt_candidate(self):
        income = [
            {"symbol": "BTCUSDT", "incomeType": "WEIRD_FEE",
             "income": "1.5", "asset": "USDT", "time": 1721712000000},
            {"symbol": "BTCUSDT", "incomeType": "OTHER",
             "income": "0.0", "asset": "USDT", "time": 1721712100000},
        ]
        events = rebuild_cash_events(income)
        halt_candidates = detect_unknown_income_halt_candidates(events)
        self.assertEqual(len(halt_candidates), 1)
        self.assertAlmostEqual(halt_candidates[0].amount, 1.5)


class CoverageWindowTest(unittest.TestCase):
    def test_no_gaps_continuous(self):
        windows = [
            ("2026-07-01T00:00:00+00:00", "2026-07-01T12:00:00+00:00"),
            ("2026-07-01T12:00:00+00:00", "2026-07-02T00:00:00+00:00"),
        ]
        coverage = verify_coverage_window(windows)
        self.assertEqual(len(coverage.gaps), 0)

    def test_gap_detected(self):
        windows = [
            ("2026-07-01T00:00:00+00:00", "2026-07-01T06:00:00+00:00"),
            ("2026-07-01T12:00:00+00:00", "2026-07-02T00:00:00+00:00"),
        ]
        coverage = verify_coverage_window(windows)
        self.assertEqual(len(coverage.gaps), 1)
        self.assertEqual(coverage.gaps[0][0], "2026-07-01T06:00:00+00:00")
        self.assertEqual(coverage.gaps[0][1], "2026-07-01T12:00:00+00:00")

    def test_empty_windows(self):
        coverage = verify_coverage_window([])
        self.assertEqual(coverage.earliest_recoverable_time, "")


class DiffTest(unittest.TestCase):
    def test_matching_positions_pass(self):
        positions = {
            "BTCUSDT": ShadowPosition.create(
                symbol="BTCUSDT", quantity=0.001,
                cost_basis=100000.0, realized_pnl=0.0, unrealized_pnl=0.0,
            ),
        }
        primary = {"BTCUSDT": {"quantity": 0.001}}
        diffs = diff_positions(positions, primary)
        self.assertTrue(all(d.blocking_level == "pass" for d in diffs))

    def test_mismatched_positions_block(self):
        positions = {
            "BTCUSDT": ShadowPosition.create(
                symbol="BTCUSDT", quantity=0.002,
                cost_basis=100000.0, realized_pnl=0.0, unrealized_pnl=0.0,
            ),
        }
        primary = {"BTCUSDT": {"quantity": 0.001}}
        diffs = diff_positions(positions, primary)
        self.assertTrue(any(d.blocking_level == "block" for d in diffs))

    def test_missing_symbol_in_shadow(self):
        positions = {}
        primary = {"BTCUSDT": {"quantity": 0.001}}
        diffs = diff_positions(positions, primary)
        self.assertTrue(any(d.blocking_level == "block" for d in diffs))

    def test_nav_diff_passes_when_matching(self):
        nav = ShadowNavMark.create(
            equity=500.97, initial_equity=486.0,
            realized_pnl=5.0, unrealized_pnl=10.0,
            funding=0.01, commission=0.04, transfer=0.0,
        )
        primary = {
            "equity": 500.97,
            "realized_pnl": 5.0,
            "unrealized_pnl": 10.0,
            "funding": 0.01,
            "commission": 0.04,
            "transfer": 0.0,
        }
        diffs = diff_nav(nav, primary)
        self.assertTrue(all(d.blocking_level == "pass" for d in diffs))

    def test_nav_diff_blocks_on_identity_failure(self):
        nav = ShadowNavMark.create(
            equity=200.0, initial_equity=100.0,
            realized_pnl=0.0, unrealized_pnl=0.0,
            funding=0.0, commission=0.0, transfer=0.0,
        )
        diffs = diff_nav(nav, {"equity": 200.0})
        self.assertTrue(has_blocking_diff(diffs))
        identity_diff = next(
            d for d in diffs if d.field == "nav:identity_verified"
        )
        self.assertEqual(identity_diff.blocking_level, "block")

    def test_has_blocking_diff(self):
        from qount.shadow_accounting import ShadowReconciliationDiff
        diffs_pass = [
            ShadowReconciliationDiff.create(
                field="x", primary_value=1.0, shadow_value=1.0,
                blocking_level="pass",
            ),
        ]
        diffs_block = [
            ShadowReconciliationDiff.create(
                field="x", primary_value=1.0, shadow_value=2.0,
                blocking_level="block",
            ),
        ]
        self.assertFalse(has_blocking_diff(diffs_pass))
        self.assertTrue(has_blocking_diff(diffs_block))


class ShadowGoldenRebuildTest(unittest.TestCase):
    """End-to-end golden test: rebuild from known raw data and verify."""

    def test_golden_rebuild(self):
        trades = [
            {"symbol": "BTCUSDT", "side": "BUY", "price": "100000.0",
             "qty": "0.001", "commission": "0.04", "realizedPnl": "0",
             "time": 1721712000000},
            {"symbol": "BTCUSDT", "side": "BUY", "price": "110000.0",
             "qty": "0.001", "commission": "0.044", "realizedPnl": "0",
             "time": 1721712100000},
            {"symbol": "BTCUSDT", "side": "SELL", "price": "115000.0",
             "qty": "0.001", "commission": "0.046", "realizedPnl": "10.0",
             "time": 1721712200000},
        ]
        income = [
            {"symbol": "BTCUSDT", "incomeType": "COMMISSION",
             "income": "-0.04", "asset": "USDT", "time": 1721712000000},
            {"symbol": "BTCUSDT", "incomeType": "COMMISSION",
             "income": "-0.044", "asset": "USDT", "time": 1721712100000},
            {"symbol": "BTCUSDT", "incomeType": "COMMISSION",
             "income": "-0.046", "asset": "USDT", "time": 1721712200000},
            {"symbol": "BTCUSDT", "incomeType": "FUNDING_FEE",
             "income": "0.02", "asset": "USDT", "time": 1721712300000},
        ]
        positions = rebuild_positions(trades)
        positions = apply_mark_prices(positions, {"BTCUSDT": 115000.0})
        cash_events = rebuild_cash_events(income)

        pos = positions["BTCUSDT"]
        self.assertAlmostEqual(pos.quantity, 0.001)
        self.assertAlmostEqual(pos.cost_basis, 105000.0)
        self.assertAlmostEqual(pos.realized_pnl, 10.0)
        self.assertAlmostEqual(pos.unrealized_pnl, 10.0)

        initial_equity = 486.16
        realized = 10.0
        unrealized = 10.0
        funding = 0.02
        commission = 0.13
        current_equity = (
            initial_equity + realized + unrealized + funding - commission
        )
        nav = rebuild_nav(
            positions=positions,
            cash_events=cash_events,
            initial_equity=initial_equity,
            current_equity=current_equity,
        )
        self.assertTrue(nav.identity_verified)

        primary_nav = {
            "equity": current_equity,
            "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "funding": funding,
            "commission": commission,
            "transfer": 0.0,
        }
        diffs = diff_nav(nav, primary_nav)
        self.assertFalse(has_blocking_diff(diffs))


if __name__ == "__main__":
    unittest.main()
