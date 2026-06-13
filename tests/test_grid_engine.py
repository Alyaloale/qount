"""Unit tests for the GRID-B baseline grid engine (线 B, isolated from line A)."""

from __future__ import annotations

import math
import unittest

from qount.grid.engine import GridConfigError
from qount.grid.engine import GridLadder
from qount.grid.engine import build_grid
from qount.grid.engine import count_for_step
from qount.grid.engine import geometric_ratio
from qount.grid.engine import grid_prices
from qount.grid.engine import net_per_grid
from qount.grid.engine import validate_step


class TestGeometry(unittest.TestCase):
    def test_ratio_and_prices_span_the_range(self) -> None:
        lower, upper, n = 30_000.0, 60_000.0, 10
        q = geometric_ratio(lower, upper, n)
        self.assertAlmostEqual(q, (upper / lower) ** (1 / n))
        prices = grid_prices(lower, upper, n)
        self.assertEqual(len(prices), n + 1)
        self.assertAlmostEqual(prices[0], lower)
        self.assertAlmostEqual(prices[-1], upper)
        # geometric => constant ratio between consecutive lines
        ratios = [prices[k + 1] / prices[k] for k in range(n)]
        for r in ratios:
            self.assertAlmostEqual(r, q)

    def test_count_for_step_never_overshoots_target(self) -> None:
        lower, upper, step = 30_000.0, 60_000.0, 0.01
        n = count_for_step(lower, upper, step)
        # the realized step at this n must be <= the requested step
        realized = geometric_ratio(lower, upper, n) - 1.0
        self.assertLessEqual(realized, step + 1e-12)
        # one fewer grid would overshoot
        realized_coarser = geometric_ratio(lower, upper, n - 1) - 1.0
        self.assertGreater(realized_coarser, step)

    def test_count_for_step_matches_closed_form(self) -> None:
        n = count_for_step(30_000.0, 60_000.0, 0.01)
        self.assertEqual(n, math.ceil(math.log(2.0) / math.log(1.01) - 1e-12))

    def test_bad_bounds_rejected(self) -> None:
        with self.assertRaises(GridConfigError):
            geometric_ratio(0.0, 10.0, 5)
        with self.assertRaises(GridConfigError):
            geometric_ratio(10.0, 10.0, 5)
        with self.assertRaises(GridConfigError):
            geometric_ratio(10.0, 20.0, 0)


class TestNetGate(unittest.TestCase):
    def test_net_subtracts_both_legs_and_slippage(self) -> None:
        net = net_per_grid(0.01, maker_fee=0.00075, slippage=0.0005)
        self.assertAlmostEqual(net, 0.01 - 2 * 0.00075 - 0.0005)

    def test_default_1pct_step_clears_floor(self) -> None:
        # v0.1 §5: step 1% with BNB maker => net ~0.85%, well above 0.30% floor
        net = validate_step(0.01, maker_fee=0.00075)
        self.assertAlmostEqual(net, 0.0085)

    def test_too_thin_step_rejected(self) -> None:
        # step 0.3% cannot clear the 0.30% net floor after fees
        with self.assertRaises(GridConfigError):
            validate_step(0.003, maker_fee=0.00075)

    def test_taker_fees_break_a_marginal_grid(self) -> None:
        # a 0.48% step survives maker (net 0.33%) but dies if both legs go taker
        # (0.10% each => net 0.28%, under the 0.30% floor) -- the §0 maker-wall in miniature
        self.assertAlmostEqual(validate_step(0.0048, maker_fee=0.00075), 0.0033)
        with self.assertRaises(GridConfigError):
            validate_step(0.0048, maker_fee=0.0010)


class TestBuildGrid(unittest.TestCase):
    def test_step_and_n_are_mutually_exclusive(self) -> None:
        with self.assertRaises(GridConfigError):
            build_grid(lower=30_000, upper=60_000, grid_capital=1000, n=10, step=0.01)
        with self.assertRaises(GridConfigError):
            build_grid(lower=30_000, upper=60_000, grid_capital=1000)

    def test_equal_quote_buys_more_base_lower_down(self) -> None:
        spec = build_grid(lower=30_000, upper=60_000, grid_capital=70_000, n=70)
        self.assertEqual(spec.n, 70)
        self.assertAlmostEqual(spec.per_grid_quote, 1000.0)
        # equal USDT per line => base qty rises as price falls (average-down behaviour)
        self.assertGreater(spec.base_qty(0), spec.base_qty(spec.n - 1))
        self.assertAlmostEqual(spec.base_qty(0), 1000.0 / spec.prices[0])

    def test_build_from_step_derives_count(self) -> None:
        spec = build_grid(lower=30_000, upper=60_000, grid_capital=70_000, step=0.01)
        self.assertEqual(spec.n, count_for_step(30_000, 60_000, 0.01))
        self.assertLessEqual(spec.step, 0.01 + 1e-12)

    def test_build_rejects_grid_that_fails_net_gate(self) -> None:
        # a tiny range with many grids => step too thin to clear the net floor
        with self.assertRaises(GridConfigError):
            build_grid(lower=30_000, upper=30_300, grid_capital=1000, n=50)


class TestGridLadder(unittest.TestCase):
    def _spec(self) -> "object":
        # 4-interval grid 100..~104.06 (q ~1.01), big capital so per_grid_quote=1000
        return build_grid(lower=100.0, upper=100.0 * (1.01 ** 4),
                          grid_capital=4000.0, n=4)

    def test_completed_round_realizes_positive_net(self) -> None:
        spec = self._spec()
        ladder = GridLadder(spec=spec, maker_fee=0.00075)
        buy_fee = ladder.apply_buy_fill(0)
        self.assertGreater(buy_fee, 0)
        self.assertTrue(ladder.cells[0].holding)
        self.assertAlmostEqual(ladder.inventory_cost_quote, spec.per_grid_quote)
        net = ladder.apply_sell_fill(0)
        # net should equal gross spread (step * notional) minus both fees, ~ net_per_grid
        self.assertGreater(net, 0)
        self.assertFalse(ladder.cells[0].holding)
        self.assertAlmostEqual(ladder.inventory_base, 0.0, places=9)
        # Exact: gross spread minus both legs' fees (sell fee is on the larger proceeds).
        # spec.net_per_grid is the first-order approx (both fees on the buy notional), so
        # the exact realized is a touch lower by the sell-leg fee on the extra step.
        buy_notional = spec.per_grid_quote
        sell_proceeds = spec.base_qty(0) * spec.prices[1]
        exact = (sell_proceeds - buy_notional) - ladder.maker_fee * (buy_notional + sell_proceeds)
        self.assertAlmostEqual(ladder.realized_quote, exact, places=6)
        approx = spec.per_grid_quote * spec.net_per_grid
        self.assertAlmostEqual(ladder.realized_quote, approx, delta=0.02)

    def test_idempotent_double_fill_ignored(self) -> None:
        spec = self._spec()
        ladder = GridLadder(spec=spec)
        ladder.apply_buy_fill(1)
        self.assertEqual(ladder.apply_buy_fill(1), 0.0)  # already holding
        self.assertEqual(ladder.buy_fills, 1)
        ladder.apply_sell_fill(1)
        self.assertEqual(ladder.apply_sell_fill(1), 0.0)  # nothing to sell
        self.assertEqual(ladder.sell_fills, 1)

    def test_inventory_accumulates_as_price_falls(self) -> None:
        spec = self._spec()
        ladder = GridLadder(spec=spec)
        for k in range(spec.n):
            ladder.apply_buy_fill(k)
        # all cells holding => full inventory, cost == full grid capital
        self.assertAlmostEqual(ladder.inventory_cost_quote, spec.per_grid_quote * spec.n)
        self.assertGreater(ladder.inventory_base, 0)
        # marked at the buy lines, equity is just negative fees (no spread captured yet)
        self.assertLess(ladder.realized_quote, 0)  # only fees booked

    def test_equity_marks_unrealized_inventory(self) -> None:
        spec = self._spec()
        ladder = GridLadder(spec=spec, maker_fee=0.0)  # zero fee to isolate marking
        ladder.apply_buy_fill(0)
        qty = spec.base_qty(0)
        # mark up 10% => unrealized = qty * 0.1 * price
        mark = spec.prices[0] * 1.10
        self.assertAlmostEqual(ladder.equity(mark), qty * (mark - spec.prices[0]))

    def test_cell_index_bounds(self) -> None:
        spec = self._spec()
        ladder = GridLadder(spec=spec)
        with self.assertRaises(GridConfigError):
            ladder.apply_buy_fill(spec.n)
        with self.assertRaises(GridConfigError):
            ladder.apply_sell_fill(-1)


if __name__ == "__main__":
    unittest.main()
