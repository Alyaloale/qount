"""Unit tests for RV-C dated-basis cash-and-carry backtest (线 C). Plan: §3/§4.

Covers: decomposition sums to net, basis convergence captured as positive carry, the roll gap
is not booked as PnL, and the liquidation tail门 (reused from H3 §8.6) fires + is bounded.
"""

from __future__ import annotations

import unittest

from qount.grid.data import Bar
from qount.rv.basis import ActiveBar
from qount.rv.backtest import run_basis_carry

_DAY_MS = 86_400_000
_T0 = 1_609_459_200_000  # 2021-01-01 UTC


def _bar(ts: int, close: float, *, high: float | None = None, open_: float | None = None) -> Bar:
    o = close if open_ is None else open_
    h = max(o, close) if high is None else high
    return Bar(ts_ms=ts, open=o, high=h, low=min(o, close) * 0.999, close=close, volume=1.0)


def _ab(ts: int, s: float, d: float, *, is_roll: bool = False, d_high: float | None = None,
        s_open: float | None = None, d_open: float | None = None) -> ActiveBar:
    return ActiveBar(
        spot=_bar(ts, s, open_=s_open),
        dated=_bar(ts, d, high=d_high, open_=d_open),
        expiry_ms=ts + 100 * _DAY_MS,
        is_roll=is_roll,
    )


class TestDecompositionSums(unittest.TestCase):
    def test_components_sum_to_net(self) -> None:
        # contango converging: spot flat at 100, dated 105 -> 100 over 5 bars
        dated = [105.0, 104.0, 103.0, 102.0, 100.0]
        active = [_ab(_T0 + i * _DAY_MS, 100.0, d) for i, d in enumerate(dated)]
        r = run_basis_carry(active, liq_leverage=None)
        recomposed = r.carry_pnl - r.roll_cost - r.fee_cost - r.liq_cost
        self.assertAlmostEqual(recomposed, r.net_return, places=10)

    def test_decomposition_with_all_frictions(self) -> None:
        dated = [108.0, 106.0, 104.0, 110.0, 100.0]  # includes a pump bar
        active = []
        for i, d in enumerate(dated):
            roll = (i == 3)
            active.append(_ab(_T0 + i * _DAY_MS, 100.0, d, is_roll=roll, d_high=d * 1.5))
        r = run_basis_carry(active, liq_leverage=3.0)
        recomposed = r.carry_pnl - r.roll_cost - r.fee_cost - r.liq_cost
        self.assertAlmostEqual(recomposed, r.net_return, places=10)


class TestBasisConvergenceEdge(unittest.TestCase):
    def test_frictionless_flat_spot_captures_basis(self) -> None:
        # spot dead flat, dated drifts from +5% to 0 -> carry ~ +5% of notional, net ~ +5%
        n = 6
        dated = [105.0 - i for i in range(n)]  # 105..100
        active = [_ab(_T0 + i * _DAY_MS, 100.0, d) for i, d in enumerate(dated)]
        r = run_basis_carry(active, liq_leverage=None, spot_taker=0.0, dated_taker=0.0,
                            rebalance_bars=10_000)  # no rebalance churn
        self.assertGreater(r.carry_pnl, 0.04)
        self.assertAlmostEqual(r.net_return, r.carry_pnl)  # no frictions
        self.assertGreater(r.entry_basis_ann, 0.0)

    def test_backwardation_bleeds(self) -> None:
        # backwardation: dated below spot (95) converging UP to spot (100) at expiry. The short
        # loses as F rises to meet S -> carry negative. Spot flat keeps it delta-neutral.
        dated = [95.0, 96.0, 97.0, 98.0, 99.0, 100.0]
        active = [_ab(_T0 + i * _DAY_MS, 100.0, d) for i, d in enumerate(dated)]
        r = run_basis_carry(active, liq_leverage=None, spot_taker=0.0, dated_taker=0.0,
                            rebalance_bars=10_000)
        self.assertLess(r.carry_pnl, 0.0)
        self.assertLess(r.entry_basis_ann, 0.0)


class TestRollGapNotBooked(unittest.TestCase):
    def test_roll_gap_excluded_from_carry(self) -> None:
        # bar 2 rolls from a near contract (~100) to a far one (~115). The +15 gap must NOT be a
        # carry loss; only the two-leg roll fee is charged.
        active = [
            _ab(_T0 + 0 * _DAY_MS, 100.0, 100.0),
            _ab(_T0 + 1 * _DAY_MS, 100.0, 100.0),
            _ab(_T0 + 2 * _DAY_MS, 100.0, 115.0, is_roll=True, d_open=115.0),  # new far contract
            _ab(_T0 + 3 * _DAY_MS, 100.0, 115.0),
        ]
        r = run_basis_carry(active, liq_leverage=None, spot_taker=0.0, dated_taker=0.0001,
                            rebalance_bars=10_000)
        self.assertEqual(r.roll_count, 1)
        self.assertGreater(r.roll_cost, 0.0)
        # carry should be ~0 (flat spot, no within-contract drift), NOT ~ -15% from the gap
        self.assertGreater(r.carry_pnl, -0.01)


class TestLiquidationTail(unittest.TestCase):
    def test_pump_triggers_liquidation(self) -> None:
        # a violent intrabar pump on the dated short past 1/3 - mm -> liquidation fires
        active = [
            _ab(_T0 + 0 * _DAY_MS, 100.0, 100.0),
            _ab(_T0 + 1 * _DAY_MS, 150.0, 150.0, d_high=200.0),  # +100% intrabar high
        ]
        r = run_basis_carry(active, liq_leverage=3.0, mm_rate=0.005, liq_penalty=0.015,
                            rebalance_bars=10_000)
        self.assertGreaterEqual(r.liq_events, 1)
        self.assertGreater(r.liq_cost, 0.0)

    def test_no_liq_when_disabled(self) -> None:
        active = [
            _ab(_T0 + 0 * _DAY_MS, 100.0, 100.0),
            _ab(_T0 + 1 * _DAY_MS, 150.0, 150.0, d_high=300.0),
        ]
        r = run_basis_carry(active, liq_leverage=None)
        self.assertEqual(r.liq_events, 0)
        self.assertEqual(r.liq_cost, 0.0)

    def test_catastrophic_gap_wipes_then_flattens(self) -> None:
        # A gap far past the liq price can wipe equity past zero (conservative full-gap charge,
        # the honest H3 tail). The invariant that matters: once equity <= 0 the leg flattens and
        # no further liq/charge repeats (the H3 stale-ref repeat-charge fix carried over).
        active = [_ab(_T0 + i * _DAY_MS, 100.0, 100.0, d_high=500.0) for i in range(3)]
        r = run_basis_carry(active, liq_leverage=3.0)
        self.assertEqual(r.liq_events, 1)  # exactly one catastrophic liq, then flat
        self.assertLess(r.final_equity, 0.0)


class TestMakerFees(unittest.TestCase):
    """S2 fee model: maker on open/roll/rebalance lowers fee_cost; liq-reopen stays taker."""

    def _series(self):
        # flat spot, dated converging 105->100 over 6 bars, one roll at bar 3
        dated = [105.0, 104.0, 103.0, 102.0, 101.0, 100.0]
        out = []
        for i, d in enumerate(dated):
            out.append(_ab(_T0 + i * _DAY_MS, 100.0, d, is_roll=(i == 3), d_open=d))
        return out

    def test_maker_lowers_fee_and_lifts_net(self) -> None:
        active = self._series()
        taker = run_basis_carry(active, liq_leverage=None,
                                spot_taker=0.0010, dated_taker=0.0005)
        maker = run_basis_carry(active, liq_leverage=None,
                                spot_taker=0.0010, dated_taker=0.0005,
                                spot_maker=0.00075, dated_maker=0.0002,
                                maker_open=True, maker_roll=True, maker_rebalance=True)
        self.assertLess(maker.fee_cost, taker.fee_cost)
        self.assertLess(maker.roll_cost, taker.roll_cost)
        self.assertGreater(maker.net_return, taker.net_return)

    def test_carry_fee_invariant_without_rebalance(self) -> None:
        # with no rebalance churn (fixed bases), the basis-convergence carry is exactly
        # independent of the fee model; only fees/net move.
        active = self._series()
        kw = dict(liq_leverage=None, rebalance_bars=10_000)
        taker = run_basis_carry(active, spot_taker=0.0010, dated_taker=0.0005, **kw)
        maker = run_basis_carry(active, spot_taker=0.0010, dated_taker=0.0005,
                                spot_maker=0.00075, dated_maker=0.0002,
                                maker_open=True, maker_roll=True, maker_rebalance=True, **kw)
        self.assertAlmostEqual(maker.carry_pnl, taker.carry_pnl, places=12)
        self.assertGreater(maker.net_return, taker.net_return)

    def test_default_is_all_taker(self) -> None:
        # maker rates default to the taker rates -> flags off changes nothing
        active = self._series()
        a = run_basis_carry(active, liq_leverage=None)
        b = run_basis_carry(active, liq_leverage=None, maker_open=True, maker_roll=True,
                            maker_rebalance=True)  # but maker rates == taker defaults
        self.assertAlmostEqual(a.net_return, b.net_return, places=12)

    def test_decomposition_still_sums_with_maker(self) -> None:
        active = self._series()
        r = run_basis_carry(active, liq_leverage=3.0, spot_maker=0.00075, dated_maker=0.0002,
                            maker_open=True, maker_roll=True, maker_rebalance=True)
        recomposed = r.carry_pnl - r.roll_cost - r.fee_cost - r.liq_cost
        self.assertAlmostEqual(recomposed, r.net_return, places=10)


class TestBasisConditional(unittest.TestCase):
    """A1: deploy only while annualized basis is fat; stand flat in cash otherwise."""

    def test_none_is_byte_identical_to_always_deployed(self) -> None:
        # min_ann_basis=None must reproduce the always-deployed path exactly.
        dated = [105.0, 104.0, 103.0, 102.0, 101.0, 100.0]
        active = [_ab(_T0 + i * _DAY_MS, 100.0, d) for i, d in enumerate(dated)]
        base = run_basis_carry(active, liq_leverage=3.0)
        same = run_basis_carry(active, liq_leverage=3.0, min_ann_basis=None)
        self.assertEqual(base.net_return, same.net_return)
        self.assertEqual(base.deployed_fraction, 1.0)

    def test_low_threshold_deploys_high_threshold_stays_flat(self) -> None:
        # dated converging from a ~+5% premium; annualized basis is high early, ~0 near expiry.
        dated = [105.0, 104.0, 103.0, 102.0, 101.0, 100.0]
        active = [_ab(_T0 + i * _DAY_MS, 100.0, d) for i, d in enumerate(dated)]
        lo = run_basis_carry(active, liq_leverage=None, min_ann_basis=0.0)   # always fat enough
        hi = run_basis_carry(active, liq_leverage=None, min_ann_basis=10.0)  # never fat enough
        self.assertGreater(lo.deployed_fraction, 0.0)
        self.assertEqual(hi.deployed_fraction, 0.0)      # never deploys
        self.assertEqual(hi.net_return, 0.0)             # flat cash -> no PnL, no fees

    def test_skips_backwardation_drag(self) -> None:
        # first half fat contango (carry+), second half backwardation (carry-). A threshold that
        # holds only in contango should beat always-on, by skipping the bleed.
        spot = [100.0] * 8
        dated = [108.0, 106.0, 104.0, 102.0, 96.0, 97.0, 98.0, 99.0]  # rich then converging UP
        active = [_ab(_T0 + i * _DAY_MS, s, d) for i, (s, d) in enumerate(zip(spot, dated))]
        always = run_basis_carry(active, liq_leverage=None, spot_taker=0.0, dated_taker=0.0,
                                 rebalance_bars=10_000)
        cond = run_basis_carry(active, liq_leverage=None, spot_taker=0.0, dated_taker=0.0,
                               rebalance_bars=10_000, min_ann_basis=0.0)  # only when basis>0
        self.assertLess(cond.deployed_fraction, 1.0)
        self.assertGreaterEqual(cond.net_return, always.net_return)

    def test_decomposition_sums_when_gated(self) -> None:
        dated = [106.0, 104.0, 99.0, 100.5, 101.0, 100.0]
        active = [_ab(_T0 + i * _DAY_MS, 100.0, d) for i, d in enumerate(dated)]
        r = run_basis_carry(active, liq_leverage=3.0, min_ann_basis=0.05)
        recomposed = r.carry_pnl - r.roll_cost - r.fee_cost - r.liq_cost
        self.assertAlmostEqual(recomposed, r.net_return, places=10)


class TestInverseHardening(unittest.TestCase):
    """RV-C #1 hole: COIN-M dated is an inverse contract. Under daily rebalancing the USD
    directional PnL is first-order identical; the material difference is a *later* liq trigger."""

    def test_carry_identical_under_daily_rebalance_no_pump(self) -> None:
        # no pump -> no liq path taken; linear and inverse must agree to floating precision
        dated = [105.0, 104.0, 103.0, 102.0, 101.0, 100.0]
        active = [_ab(_T0 + i * _DAY_MS, 100.0, d) for i, d in enumerate(dated)]
        lin = run_basis_carry(active, liq_leverage=3.0, inverse=False)
        inv = run_basis_carry(active, liq_leverage=3.0, inverse=True)
        self.assertAlmostEqual(lin.carry_pnl, inv.carry_pnl, places=10)
        self.assertAlmostEqual(lin.net_return, inv.net_return, places=10)
        self.assertEqual((lin.liq_events, inv.liq_events), (0, 0))

    def test_inverse_liquidates_later_than_linear(self) -> None:
        # a +40% intrabar pump: liquidates the LINEAR short (trigger +32.8%) but NOT the
        # inverse short (trigger +49.3%) at L=3 -- coin collateral cushions the pump.
        active = [
            _ab(_T0 + 0 * _DAY_MS, 100.0, 100.0),
            _ab(_T0 + 1 * _DAY_MS, 100.0, 100.0, d_high=140.0),  # +40% high, closes back at 100
        ]
        lin = run_basis_carry(active, liq_leverage=3.0, mm_rate=0.005, inverse=False,
                              rebalance_bars=10_000)
        inv = run_basis_carry(active, liq_leverage=3.0, mm_rate=0.005, inverse=True,
                              rebalance_bars=10_000)
        self.assertGreaterEqual(lin.liq_events, 1)
        self.assertEqual(inv.liq_events, 0)
        self.assertGreater(inv.net_return, lin.net_return)  # inverse spared the tail

    def test_inverse_still_liquidates_on_extreme_pump(self) -> None:
        # a +60% pump exceeds even the inverse trigger (+49.3%) -> inverse liquidates too
        active = [
            _ab(_T0 + 0 * _DAY_MS, 100.0, 100.0),
            _ab(_T0 + 1 * _DAY_MS, 100.0, 100.0, d_high=160.0),
        ]
        inv = run_basis_carry(active, liq_leverage=3.0, mm_rate=0.005, inverse=True,
                              rebalance_bars=10_000)
        self.assertGreaterEqual(inv.liq_events, 1)


if __name__ == "__main__":
    unittest.main()
