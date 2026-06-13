"""Unit tests for GRID-B H3 delta-neutral carry primitives (线 B, isolated from line A).

H3 plan: ``docs/grid-binance-h3-plan.md``. This file is Increment 1 -- the *pure* perp
hedge + funding ledger (``grid/perp.py``), which is where the 6 hardening holes live:

  洞5  test_delta_neutral_offset_*  : harvest(θ) and rehedge(½Γ(dS)²) cancel; discrete
                                      hedging of short gamma is a *net loss* (≤ 0), not ≈0.
  洞3  test_funding_on_varying_notional / test_funding_accumulation : funding accrues on the
                                      *time-varying* short notional, sign = short receives when rate>0.
  洞1  test_short_shrinks_when_price_rises : the grid's inventory (hence the hedge short) is
                                      anti-correlated with price -> anti-phase with funding.
  洞4  test_basis_dislocation_hit / test_adl_simulation : perp priced on its own market;
                                      a dislocated fill / an ADL cover bleeds for real.

``test_delisting_terminal_loss`` (洞6) is a spot+orchestration concern -> Increment 2 (run_h3).
"""

from __future__ import annotations

import math
import unittest

from qount.grid.backtest import run_h3
from qount.grid.backtest import run_h3_carry
from qount.grid.data import Bar
from qount.grid.data import Funding
from qount.grid.engine import GridLadder
from qount.grid.engine import build_grid
from qount.grid.perp import PerpHedgeLeg

_HOUR_MS = 3_600_000
_T0 = 1_609_459_200_000  # 2021-01-01 00:00 UTC


def _flat_leg(**kw) -> PerpHedgeLeg:
    """A frictionless leg (no fee, no slippage) for isolating the offset theorem."""
    kw.setdefault("taker_fee", 0.0)
    kw.setdefault("slippage", 0.0)
    return PerpHedgeLeg(**kw)


class TestFundingAccrual(unittest.TestCase):
    def test_short_receives_when_rate_positive(self) -> None:
        leg = _flat_leg()
        leg.rehedge(target_short_base=2.0, fill_price=100.0)  # short 2 @ 100
        amt = leg.accrue_funding(funding_rate=0.0010, mark_price=100.0)
        # short receives funding when rate>0 (longs pay shorts): +rate*notional
        self.assertAlmostEqual(amt, 0.0010 * 2.0 * 100.0)
        self.assertAlmostEqual(leg.funding_pnl, 0.20)

    def test_short_pays_when_rate_negative(self) -> None:
        leg = _flat_leg()
        leg.rehedge(target_short_base=2.0, fill_price=100.0)
        amt = leg.accrue_funding(funding_rate=-0.0010, mark_price=100.0)
        self.assertLess(amt, 0.0)
        self.assertAlmostEqual(leg.funding_pnl, -0.20)

    def test_funding_on_varying_notional(self) -> None:
        """洞3: funding base is the *current* short notional, not a fixed one."""
        leg = _flat_leg()
        leg.rehedge(target_short_base=1.0, fill_price=100.0)
        a_small = leg.accrue_funding(funding_rate=0.0010, mark_price=100.0)
        leg.rehedge(target_short_base=5.0, fill_price=100.0)  # short grew (price fell, grid bought)
        a_big = leg.accrue_funding(funding_rate=0.0010, mark_price=100.0)
        self.assertAlmostEqual(a_small, 0.0010 * 1.0 * 100.0)
        self.assertAlmostEqual(a_big, 0.0010 * 5.0 * 100.0)
        self.assertAlmostEqual(a_big, 5.0 * a_small)

    def test_funding_accumulation_no_double_count(self) -> None:
        leg = _flat_leg()
        leg.rehedge(target_short_base=1.0, fill_price=100.0)
        total = 0.0
        for rate in (0.0010, -0.0005, 0.0008):
            total += leg.accrue_funding(funding_rate=rate, mark_price=100.0)
        self.assertAlmostEqual(leg.funding_pnl, total)
        self.assertAlmostEqual(leg.funding_pnl, (0.0010 - 0.0005 + 0.0008) * 100.0)

    def test_flat_leg_accrues_zero(self) -> None:
        leg = _flat_leg()
        amt = leg.accrue_funding(funding_rate=0.0010, mark_price=100.0)
        self.assertEqual(amt, 0.0)
        self.assertEqual(leg.equity(mark_price=100.0), 0.0)


class TestShortPnL(unittest.TestCase):
    def test_short_gains_as_price_falls(self) -> None:
        leg = _flat_leg()
        leg.rehedge(target_short_base=1.0, fill_price=100.0)
        self.assertAlmostEqual(leg.equity(mark_price=80.0), 20.0)   # short wins on a drop
        self.assertAlmostEqual(leg.equity(mark_price=120.0), -20.0)  # loses on a rip

    def test_cover_realizes_against_avg(self) -> None:
        leg = _flat_leg()
        leg.rehedge(target_short_base=2.0, fill_price=100.0)  # short 2 @ 100
        leg.rehedge(target_short_base=0.0, fill_price=90.0)   # cover 2 @ 90 -> +20
        self.assertAlmostEqual(leg.realized_pnl, 2.0 * (100.0 - 90.0))
        self.assertAlmostEqual(leg.short_base, 0.0)
        self.assertAlmostEqual(leg.equity(mark_price=12345.0), 20.0)  # flat: mark irrelevant

    def test_average_price_on_scaling_in(self) -> None:
        leg = _flat_leg()
        leg.rehedge(target_short_base=1.0, fill_price=100.0)
        leg.rehedge(target_short_base=3.0, fill_price=120.0)  # +2 @ 120
        self.assertAlmostEqual(leg.short_base, 3.0)
        self.assertAlmostEqual(leg.short_avg_price, (1 * 100 + 2 * 120) / 3)

    def test_short_shrinks_when_price_rises(self) -> None:
        """洞1: hedge short tracks spot inventory, which falls as price rises -> anti-phase."""
        ladder, leg = _grid_with_hedge()
        for k in (2, 1, 0):   # price falling: grid buys, inventory up -> hedge short up
            _buy(ladder, leg, k)
        short_low = leg.short_base
        for k in (0, 1, 2):   # price rising: grid sells, inventory down -> hedge short shrinks
            _sell(ladder, leg, k)
        self.assertGreater(short_low, leg.short_base)
        self.assertAlmostEqual(leg.short_base, ladder.inventory_base)


class TestDeltaNeutralOffset(unittest.TestCase):
    """洞5: the offset theorem -- spot harvest and perp hedge cancel; discreteness loses."""

    def test_offset_exact_frictionless(self) -> None:
        ladder, leg = _grid_with_hedge()
        # one full V over cells 0..2: buy down at each P_k, sell up at each P_{k+1},
        # rehedging the perp to spot inventory at *each* fill's line price.
        for k in (2, 1, 0):
            _buy(ladder, leg, k)
        for k in (0, 1, 2):
            _sell(ladder, leg, k)
        start_price = ladder.spec.prices[0]
        net = ladder.equity(mark_price=start_price) + leg.equity(mark_price=start_price)
        # harvest(spot) + hedge-loss(perp) cancel to ~0 with perfect-price rehedge, no fees
        self.assertAlmostEqual(net, 0.0, places=8)
        self.assertGreater(ladder.realized_quote, 0.0)   # spot really did harvest
        self.assertLess(leg.realized_pnl, 0.0)           # perp really did pay it back

    def test_offset_is_net_loss_with_fees(self) -> None:
        ladder = _make_ladder()
        leg = PerpHedgeLeg(taker_fee=0.0005, slippage=0.0)  # real perp taker
        for k in (2, 1, 0):
            _buy(ladder, leg, k)
        for k in (0, 1, 2):
            _sell(ladder, leg, k)
        p0 = ladder.spec.prices[0]
        net = ladder.equity(mark_price=p0) + leg.equity(mark_price=p0)
        # discrete delta-hedge of short gamma + fees => strictly a loss, not ≈ 0
        self.assertLess(net, 0.0)


class TestTailRisk(unittest.TestCase):
    def test_basis_dislocation_hit(self) -> None:
        """洞4: covering at a perp price dislocated from spot bleeds for real."""
        leg = _flat_leg()
        leg.rehedge(target_short_base=1.0, fill_price=100.0)   # short 1 @ 100 (spot~100)
        # spot unchanged ~100 but perp spikes 15% above -> forced cover at 115 = big loss
        leg.rehedge(target_short_base=0.0, fill_price=115.0)
        self.assertAlmostEqual(leg.realized_pnl, 1.0 * (100.0 - 115.0))
        self.assertLess(leg.realized_pnl, -10.0)

    def test_adl_simulation(self) -> None:
        """洞4: an ADL hit force-covers part of the short at a punitive (high) price."""
        leg = PerpHedgeLeg(taker_fee=0.0, slippage=0.0)
        leg.rehedge(target_short_base=4.0, fill_price=100.0)
        leg.adl_cover(fraction=0.5, fill_price=130.0)   # violent +30% up bar
        self.assertAlmostEqual(leg.short_base, 2.0)
        self.assertEqual(leg.adl_events, 1)
        self.assertAlmostEqual(leg.realized_pnl, 2.0 * (100.0 - 130.0))  # forced loss

    def test_adl_noop_when_flat(self) -> None:
        leg = _flat_leg()
        leg.adl_cover(fraction=0.5, fill_price=130.0)
        self.assertEqual(leg.short_base, 0.0)
        self.assertEqual(leg.adl_events, 0)


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------


def _bars(prices: list[float], *, highs=None, lows=None) -> list[Bar]:
    """Aligned hourly bars from a close-price path (OHLC flat unless highs/lows given)."""
    out = []
    for i, p in enumerate(prices):
        hi = highs[i] if highs else p
        lo = lows[i] if lows else p
        out.append(Bar(ts_ms=_T0 + i * _HOUR_MS, open=p, high=hi, low=lo, close=p, volume=1.0))
    return out


def _funding_at(bar_indices, rate: float) -> list[Funding]:
    return [Funding(ts_ms=_T0 + i * _HOUR_MS, rate=rate) for i in bar_indices]


class TestRunH3Static(unittest.TestCase):
    def test_pure_funding_positive(self) -> None:
        """Flat price, positive funding -> net = funding − fees > 0; no harvest, hedge flat."""
        spot = _bars([100.0] * 10)
        perp = _bars([100.0] * 10)
        fund = _funding_at([2, 5, 8], 0.0010)  # 3 settlements, short receives
        r = run_h3(spot, perp, fund, mode="static",
                   capital=1.0, spot_taker=0.0010, perp_taker=0.0005)
        self.assertEqual(r.harvest_pnl, 0.0)
        self.assertAlmostEqual(r.funding_pnl, 3 * 0.0010, places=6)   # 3 * rate * notional(=cap)
        self.assertAlmostEqual(r.offset_residual, 0.0, places=9)       # flat price -> delta-neutral
        # fees: spot buy 0.0010*cap + perp open 0.0005*cap = 0.0015
        self.assertAlmostEqual(r.fee_cost, 0.0015, places=6)
        self.assertAlmostEqual(r.net_return, 0.0030 - 0.0015, places=6)
        self.assertGreater(r.net_return, 0.0)

    def test_negative_funding_loses(self) -> None:
        spot = _bars([100.0] * 10)
        perp = _bars([100.0] * 10)
        fund = _funding_at([2, 5, 8], -0.0010)  # short pays
        r = run_h3(spot, perp, fund, mode="static")
        self.assertLess(r.funding_pnl, 0.0)
        self.assertLess(r.net_return, 0.0)

    def test_decomposition_sums_to_net(self) -> None:
        # zig-zag price so spot_inventory and perp_directional are both non-trivial
        path = [100, 90, 110, 95, 105, 100]
        spot = _bars([float(x) for x in path])
        perp = _bars([float(x) for x in path])
        fund = _funding_at([1, 3], 0.0008)
        r = run_h3(spot, perp, fund, mode="static")
        s = (r.harvest_pnl + r.spot_inventory_pnl + r.perp_directional_pnl
             + r.funding_pnl - r.fee_cost)
        self.assertAlmostEqual(s, r.net_return, places=9)
        # delta-neutral: spot directional offset by perp (no basis here)
        self.assertAlmostEqual(r.offset_residual, 0.0, places=6)

    def test_funding_applied_once_per_settlement(self) -> None:
        spot = _bars([100.0] * 6)
        perp = _bars([100.0] * 6)
        r = run_h3(spot, perp, _funding_at([2, 4], 0.0010), mode="static")
        self.assertAlmostEqual(r.funding_pnl, 2 * 0.0010, places=6)


class TestRunH3Grid(unittest.TestCase):
    def test_grid_is_no_free_lunch(self) -> None:
        """Oscillate and return to start, zero funding: grid harvests but perp cancels it
        -> net <= ~0 (only fees), harvest is real but eaten. (洞5 at the run level.)"""
        path = [100, 96, 100, 96, 100, 96, 100]
        spot = _bars([float(x) for x in path], highs=[x + 0.5 for x in path],
                     lows=[x - 0.5 for x in path])
        perp = _bars([float(x) for x in path], highs=[x + 0.5 for x in path],
                     lows=[x - 0.5 for x in path])
        r = run_h3(spot, perp, [], mode="grid", step=0.01, lower=80.0, upper=120.0)
        self.assertGreater(r.harvest_pnl, 0.0)        # grid genuinely harvested
        self.assertLessEqual(r.net_return, 1e-6)      # but it is not free money
        s = (r.harvest_pnl + r.spot_inventory_pnl + r.perp_directional_pnl
             + r.funding_pnl - r.fee_cost)
        self.assertAlmostEqual(s, r.net_return, places=9)

    def test_grid_hedge_tracks_inventory(self) -> None:
        # falling price: grid accumulates, the rehedge fires repeatedly
        path = [110, 108, 106, 104, 102, 100]
        spot = _bars([float(x) for x in path], lows=[x - 0.5 for x in path])
        perp = _bars([float(x) for x in path], lows=[x - 0.5 for x in path])
        r = run_h3(spot, perp, [], mode="grid", step=0.01, lower=90.0, upper=120.0)
        self.assertGreater(r.rehedge_count, 0)


class TestRunH3Tail(unittest.TestCase):
    def test_adl_triggers_when_enabled(self) -> None:
        # bar 3 perp spikes +25% intrabar -> ADL force-cover the short (opt-in)
        closes = [100.0, 100.0, 100.0, 125.0, 125.0]
        highs = [100.0, 100.0, 100.0, 130.0, 125.0]
        spot = _bars(closes, highs=highs)
        perp = _bars(closes, highs=highs)
        r = run_h3(spot, perp, [], mode="static", enable_adl=True, adl_up_threshold=0.20)
        self.assertGreaterEqual(r.adl_events, 1)

    def test_adl_off_by_default(self) -> None:
        # same violent bar, but ADL is the deferred tail stress -> no events by default
        closes = [100.0, 100.0, 100.0, 125.0, 125.0]
        highs = [100.0, 100.0, 100.0, 130.0, 125.0]
        r = run_h3(_bars(closes, highs=highs), _bars(closes, highs=highs), [], mode="static")
        self.assertEqual(r.adl_events, 0)

    def test_basis_dislocation_recorded(self) -> None:
        spot = _bars([100.0] * 5)
        perp = _bars([100.0, 100.0, 115.0, 100.0, 100.0])  # one basis-dislocated bar
        r = run_h3(spot, perp, [], mode="static")
        self.assertGreater(r.worst_basis, 0.10)

    def test_alignment_required(self) -> None:
        with self.assertRaises(ValueError):
            run_h3(_bars([100.0, 100.0]), _bars([100.0]), [], mode="static")


class TestRunH3Liquidation(unittest.TestCase):
    def test_no_liquidation_by_default(self) -> None:
        # violent +50% bar, but liq gate off (upper bound) -> no liq cost
        closes = [100.0, 100.0, 160.0]
        highs = [100.0, 100.0, 170.0]
        r = run_h3(_bars(closes, highs=highs), _bars(closes, highs=highs), [], mode="static")
        self.assertEqual(r.liq_events, 0)
        self.assertEqual(r.liq_cost, 0.0)

    def test_liquidation_triggers_on_intrabar_pump(self) -> None:
        # L=3 -> buffer ~0.328; a +50% intrabar high blows the short past liq price
        closes = [100.0, 100.0, 160.0]
        highs = [100.0, 100.0, 170.0]
        r = run_h3(_bars(closes, highs=highs), _bars(closes, highs=highs), [],
                   mode="static", liq_leverage=3.0)
        self.assertGreaterEqual(r.liq_events, 1)
        self.assertGreater(r.liq_cost, 0.0)
        self.assertLess(r.net_return, 0.0)  # the tail bites

    def test_calm_market_no_liquidation(self) -> None:
        closes = [100.0, 101.0, 100.5, 101.5, 100.0]
        highs = [100.5, 101.5, 101.0, 102.0, 100.5]
        r = run_h3(_bars(closes, highs=highs), _bars(closes, highs=highs), [],
                   mode="static", liq_leverage=3.0)
        self.assertEqual(r.liq_events, 0)

    def test_higher_leverage_more_liquidation(self) -> None:
        # a +22% intrabar bar: clears L=5 buffer (~0.195) but not L=3 (~0.328)
        closes = [100.0, 100.0, 122.0]
        highs = [100.0, 100.0, 122.0]
        r3 = run_h3(_bars(closes, highs=highs), _bars(closes, highs=highs), [],
                    mode="static", liq_leverage=3.0)
        r5 = run_h3(_bars(closes, highs=highs), _bars(closes, highs=highs), [],
                    mode="static", liq_leverage=5.0)
        self.assertEqual(r3.liq_events, 0)
        self.assertGreaterEqual(r5.liq_events, 1)

    def test_decomposition_sums_with_liq(self) -> None:
        path = [100, 95, 140, 110, 130]
        highs = [101, 96, 150, 112, 135]
        spot = _bars([float(x) for x in path], highs=[float(x) for x in highs])
        perp = _bars([float(x) for x in path], highs=[float(x) for x in highs])
        r = run_h3(spot, perp, _funding_at([1, 3], 0.0006), mode="static", liq_leverage=4.0)
        s = (r.harvest_pnl + r.spot_inventory_pnl + r.perp_directional_pnl
             + r.funding_pnl - r.fee_cost - r.liq_cost)
        self.assertAlmostEqual(s, r.net_return, places=9)


class TestRunH3Carry(unittest.TestCase):
    """Equity-normalized delta-neutral carry: notional rebalanced to k×equity (§8.5 fix)."""

    def test_flat_price_pure_funding(self) -> None:
        spot = _bars([100.0] * 50)
        perp = _bars([100.0] * 50)
        fund = _funding_at([10, 20, 30], 0.0010)
        r = run_h3_carry(spot, perp, fund, capital=1.0, k_gross=1.0, rebalance_hours=24)
        # notional = k*E ≈ 1; funding ≈ 3 * rate * notional = 0.003 (bounded, not inflated)
        self.assertAlmostEqual(r.funding_pnl, 0.003, places=4)
        self.assertGreater(r.net_return, 0.0)
        self.assertAlmostEqual(r.offset_residual, 0.0, places=9)  # flat -> delta-neutral exact

    def test_equity_stays_positive_through_pump(self) -> None:
        # brutal 20x pump with liquidations -- equity must never go negative (the §8.5 fix)
        path = [100.0 * (1.0 + i * 0.5) for i in range(40)]   # ramp up ~20x
        highs = [p * 1.4 for p in path]                        # violent intrabar
        spot = _bars(path, highs=highs)
        perp = _bars(path, highs=highs)
        r = run_h3_carry(spot, perp, [], k_gross=1.0, liq_leverage=3.0, rebalance_hours=24)
        self.assertGreater(r.net_return, -1.0)         # > -100%: can't lose more than capital
        self.assertTrue(all(v > 0 for v in r.curve))   # equity positive throughout

    def test_notional_bounded_after_pump(self) -> None:
        # after a big pump + daily rebalances, notional is trimmed back to ~k*equity,
        # not ballooned to 20x (the disease §8.5 diagnosed)
        path = [100.0 * (1.0 + i * 0.5) for i in range(48)]
        spot = _bars(path)
        perp = _bars(path)
        r = run_h3_carry(spot, perp, [], k_gross=1.0, liq_leverage=3.0, rebalance_hours=24)
        self.assertLess(abs(r.final_notional / r.final_equity - 1.0), 0.6)  # ~k=1, not 20x

    def test_decomposition_sums(self) -> None:
        path = [100, 110, 95, 130, 105, 120]
        highs = [105, 115, 100, 140, 110, 125]
        spot = _bars([float(x) for x in path], highs=[float(x) for x in highs])
        perp = _bars([float(x) for x in path], highs=[float(x) for x in highs])
        r = run_h3_carry(spot, perp, _funding_at([1, 3], 0.0006),
                         k_gross=1.0, liq_leverage=4.0, rebalance_hours=2)
        s = (r.harvest_pnl + r.spot_inventory_pnl + r.perp_directional_pnl
             + r.funding_pnl - r.fee_cost - r.liq_cost)
        self.assertAlmostEqual(s, r.net_return, places=9)


def _make_ladder() -> GridLadder:
    spec = build_grid(lower=80.0, upper=120.0, grid_capital=1000.0, step=0.01,
                      maker_fee=0.0)
    return GridLadder(spec=spec, maker_fee=0.0)


def _grid_with_hedge() -> tuple[GridLadder, PerpHedgeLeg]:
    return _make_ladder(), _flat_leg()


def _buy(ladder: GridLadder, leg: PerpHedgeLeg, k: int) -> None:
    """Spot buys cell k at its line P_k; rehedge perp short to the new inventory at P_k."""
    ladder.apply_buy_fill(k)
    leg.rehedge(target_short_base=ladder.inventory_base, fill_price=ladder.spec.prices[k])


def _sell(ladder: GridLadder, leg: PerpHedgeLeg, k: int) -> None:
    """Spot sells cell k at its line P_{k+1}; rehedge perp short down at P_{k+1}."""
    ladder.apply_sell_fill(k)
    leg.rehedge(target_short_base=ladder.inventory_base, fill_price=ladder.spec.prices[k + 1])


if __name__ == "__main__":
    unittest.main()
