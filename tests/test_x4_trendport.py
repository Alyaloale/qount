"""Unit tests for S7-TREND-PORT: multi-coin trend portfolio + master gate (线 D §19).

The thesis (§19): diversify the *validated* trend signal (S3) across coins, risk-combine -- NOT
cross-sectional selection (§16.1 XMOM falsified). These pin the engine contract before the research
run: per-symbol sleeve fidelity, inverse-vol combination delegation, the BTC master gate's causal
risk-off behaviour, and input validation. No network.
"""

from __future__ import annotations

import unittest

from qount.grid.data import Bar
from qount.x4.backtest import run_directional, run_trend_portfolio
from qount.x4.portfolio import combine
from qount.x4.strategies import TrendFollow, sma_regime_mask, sma_slope_up_mask

# Small windows so synthetic series stay short. Zero fees + no vol-parity -> clean, exact curves.
_PARAMS = dict(fast=2, slow=4, regime_sma=5, vol_target=0.0, max_leverage=1.0,
               rebalance_band=0.0, chandelier_mult=0.0, taker_fee=0.0, slippage=0.0)
_DAY_MS = 86_400_000


def _bars(closes: list[float]) -> list[Bar]:
    # high/low == close (chandelier off, vol-parity off -> only closes matter); ascending ts.
    return [Bar(ts_ms=i * _DAY_MS, open=c, high=c, low=c, close=c, volume=1.0)
            for i, c in enumerate(closes)]


def _rising(n: int = 40, base: float = 100.0, step: float = 1.0) -> list[Bar]:
    return _bars([base + step * i for i in range(n)])


def _falling(n: int = 40, base: float = 200.0, step: float = 1.0) -> list[Bar]:
    return _bars([base - step * i for i in range(n)])


class TestSmaRegimeMask(unittest.TestCase):
    def test_basic_above_below(self) -> None:
        # rising series: once warm, close is above its trailing SMA -> True
        mask = sma_regime_mask([1, 2, 3, 4, 5, 6], window=3)
        self.assertEqual(mask[:2], [False, False])   # warm-up region is False
        self.assertTrue(all(mask[2:]))               # rising -> above SMA

    def test_falling_series_below(self) -> None:
        mask = sma_regime_mask([6, 5, 4, 3, 2, 1], window=3)
        self.assertEqual(mask[:2], [False, False])
        self.assertFalse(any(mask[2:]))              # falling -> below SMA

    def test_no_lookahead(self) -> None:
        # mask[t] must depend only on closes[:t+1]; appending future bars can't change earlier values
        closes = [1, 3, 2, 5, 4, 6, 5]
        full = sma_regime_mask(closes, window=3)
        for t in range(len(closes)):
            self.assertEqual(sma_regime_mask(closes[:t + 1], window=3), full[:t + 1])

    def test_window_disabled(self) -> None:
        self.assertEqual(sma_regime_mask([5, 1, 9], window=0), [True, True, True])


class TestSmaSlopeUpMask(unittest.TestCase):
    """T3-4: master-gate slope confirmation — is the SMA itself rising vs `lookback` bars ago?"""

    def test_rising_sma_is_true_once_warm(self) -> None:
        # SMA3 of [1..6] = [_,_,2,3,4,5] -> rising; mask[t]=sma[t]>=sma[t-1]
        mask = sma_slope_up_mask([1, 2, 3, 4, 5, 6], window=3, lookback=1)
        self.assertEqual(mask, [False, False, False, True, True, True])

    def test_falling_sma_is_false(self) -> None:
        mask = sma_slope_up_mask([6, 5, 4, 3, 2, 1], window=3, lookback=1)
        self.assertFalse(any(mask))   # SMA monotonically falling -> never rising

    def test_lookback_disabled(self) -> None:
        self.assertEqual(sma_slope_up_mask([5, 1, 9], window=3, lookback=0), [True, True, True])

    def test_no_lookahead(self) -> None:
        closes = [1, 3, 2, 5, 4, 6, 5, 7]
        full = sma_slope_up_mask(closes, window=3, lookback=2)
        for t in range(len(closes)):
            self.assertEqual(sma_slope_up_mask(closes[: t + 1], window=3, lookback=2), full[: t + 1])

    def test_flat_sma_counts_as_rising(self) -> None:
        # constant series -> SMA flat -> sma[t] >= sma[t-lookback] holds (>=, not >)
        mask = sma_slope_up_mask([5, 5, 5, 5, 5], window=2, lookback=1)
        self.assertTrue(all(mask[2:]))


class TestMasterGateSlope(unittest.TestCase):
    """T3-4: the master_gate_slope switch (0 = off, preserves behavior; >0 = AND slope into BTC gate)."""

    def test_slope_zero_is_noop(self) -> None:
        univ = {"BTCUSDT": _rising(40), "ALTUSDT": _rising(40, base=50.0)}
        base = run_trend_portfolio(univ, master_gate_sym="BTCUSDT", master_gate_sma=5, **_PARAMS)
        slope0 = run_trend_portfolio(univ, master_gate_sym="BTCUSDT", master_gate_sma=5,
                                     master_gate_slope=0, **_PARAMS)
        for a, b in zip(base.equity_curve, slope0.equity_curve):
            self.assertAlmostEqual(a, b, places=9)

    def test_slope_never_increases_gate_active(self) -> None:
        # ANDing a slope mask can only REMOVE risk-on bars, never add -> active fraction <= no-slope.
        univ = {"BTCUSDT": _rising(30) + _falling(20, base=170.0), "ALTUSDT": _rising(50, base=50.0)}
        no_slope = run_trend_portfolio(univ, master_gate_sym="BTCUSDT", master_gate_sma=5, **_PARAMS)
        with_slope = run_trend_portfolio(univ, master_gate_sym="BTCUSDT", master_gate_sma=5,
                                         master_gate_slope=5, **_PARAMS)
        self.assertLessEqual(with_slope.extra["gate_active_frac"], no_slope.extra["gate_active_frac"])


class TestTrendPortfolio(unittest.TestCase):
    def test_single_symbol_fidelity(self) -> None:
        # 1 sleeve, no master gate -> portfolio curve == the standalone run_directional curve.
        bars = _rising()
        port = run_trend_portfolio({"ALTUSDT": bars}, master_gate_sym=None, **_PARAMS)
        solo = run_directional(
            bars, TrendFollow(fast=2, slow=4, allow_short=False, regime_sma=5),
            initial_capital=100_000.0, taker_fee=0.0, slippage=0.0, rebalance_band=0.0,
            vol_target=0.0, max_leverage=1.0, chandelier_mult=0.0)
        self.assertEqual(len(port.equity_curve), len(solo.equity_curve))
        for a, b in zip(port.equity_curve, solo.equity_curve):
            self.assertAlmostEqual(a, b, places=6)

    def test_funding_drag_reduces_long_returns(self) -> None:
        # positive funding -> a held long pays funding -> portfolio ends strictly below the no-funding run
        bars = _rising()
        gross = run_trend_portfolio({"ALTUSDT": bars}, master_gate_sym=None, **_PARAMS)
        net = run_trend_portfolio({"ALTUSDT": bars}, master_gate_sym=None,
                                  funding_by_sym={"ALTUSDT": lambda b: 0.01}, **_PARAMS)
        self.assertLess(net.equity_curve[-1], gross.equity_curve[-1])

    def test_inverse_vol_delegates_to_combine(self) -> None:
        # 2 sleeves, no master gate -> portfolio == combine(per-sleeve curves, inverse_vol).
        univ = {"AUSDT": _rising(step=1.0), "BUSDT": _rising(step=2.0)}
        port = run_trend_portfolio(univ, master_gate_sym=None, weighting="inverse_vol",
                                   vol_lookback=10, **_PARAMS)
        sleeves = {
            s: run_directional(
                b, TrendFollow(fast=2, slow=4, allow_short=False, regime_sma=5),
                initial_capital=100_000.0, taker_fee=0.0, slippage=0.0, rebalance_band=0.0,
                vol_target=0.0, max_leverage=1.0, chandelier_mult=0.0).equity_curve
            for s, b in univ.items()
        }
        expect = combine(sleeves, scheme="inverse_vol", vol_lookback=10, initial_capital=100_000.0)
        self.assertEqual(port.extra["sleeves"].keys(), sleeves.keys())
        for a, b in zip(port.equity_curve, expect):
            self.assertAlmostEqual(a, b, places=6)

    def test_master_gate_flattens_when_leader_below_sma(self) -> None:
        # BTC falling (gate off the whole post-warmup span) while ALT rises (sleeve would profit).
        # Master gate => the whole portfolio sits in cash => equity never moves off initial capital.
        univ = {"BTCUSDT": _falling(), "ALTUSDT": _rising()}
        gated = run_trend_portfolio(univ, master_gate_sym="BTCUSDT", master_gate_sma=5, **_PARAMS)
        self.assertTrue(all(abs(e - 100_000.0) < 1e-6 for e in gated.equity_curve))
        # Sanity: without the gate the rising ALT sleeve does move the portfolio.
        ungated = run_trend_portfolio(univ, master_gate_sym=None, **_PARAMS)
        self.assertGreater(ungated.equity_curve[-1], 100_000.0 + 1.0)

    def test_master_gate_active_when_leader_above_sma(self) -> None:
        # BTC rising too -> gate active throughout (post warm-up) -> matches the ungated portfolio.
        univ = {"BTCUSDT": _rising(step=1.5), "ALTUSDT": _rising(step=1.0)}
        gated = run_trend_portfolio(univ, master_gate_sym="BTCUSDT", master_gate_sma=5, **_PARAMS)
        ungated = run_trend_portfolio(univ, master_gate_sym=None, **_PARAMS)
        # Gate only zeroes the warm-up steps (a tiny prefix); final equity should match closely
        # and the active fraction should be high.
        self.assertGreater(gated.extra["gate_active_frac"], 0.8)
        self.assertAlmostEqual(gated.equity_curve[-1], ungated.equity_curve[-1], delta=1.0)

    def test_extra_diagnostics(self) -> None:
        univ = {"BTCUSDT": _rising(), "ALTUSDT": _rising(step=2.0)}
        res = run_trend_portfolio(univ, master_gate_sym="BTCUSDT", master_gate_sma=5, **_PARAMS)
        self.assertEqual(res.name, "S7-TREND-PORT")
        self.assertEqual(res.extra["n_syms"], 2)
        self.assertEqual(set(res.extra["sleeves"]), {"BTCUSDT", "ALTUSDT"})
        self.assertTrue(0.0 <= res.extra["gate_active_frac"] <= 1.0)

    def test_misaligned_lengths_raise(self) -> None:
        with self.assertRaises(ValueError):
            run_trend_portfolio({"AUSDT": _rising(30), "BUSDT": _rising(31)},
                                master_gate_sym=None, **_PARAMS)

    def test_missing_master_gate_symbol_raises(self) -> None:
        with self.assertRaises(ValueError):
            run_trend_portfolio({"AUSDT": _rising()}, master_gate_sym="BTCUSDT", **_PARAMS)

    def test_empty_universe_raises(self) -> None:
        with self.assertRaises(ValueError):
            run_trend_portfolio({}, master_gate_sym=None, **_PARAMS)


class TestBreadthGate(unittest.TestCase):
    """§21.B breadth gate: risk-on if BTC>SMA OR enough of the universe is in uptrend."""

    def test_breadth_or_keeps_alt_when_btc_down(self) -> None:
        # BTC falling (BTC-only gate would flatten), but ALTs rising -> breadth>0.5 -> OR keeps on.
        univ = {"BTCUSDT": _falling(), "AUSDT": _rising(step=1.0), "BUSDT": _rising(step=2.0)}
        btc_only = run_trend_portfolio(univ, master_gate_sym="BTCUSDT", master_gate_sma=5, **_PARAMS)
        breadth_or = run_trend_portfolio(univ, master_gate_sym="BTCUSDT", master_gate_sma=5,
                                         breadth_gate=0.5, breadth_combine="or", **_PARAMS)
        # BTC-only sits in cash; OR-breadth captures the rising ALTs -> strictly more terminal equity.
        self.assertAlmostEqual(btc_only.equity_curve[-1], 100_000.0, delta=1.0)
        self.assertGreater(breadth_or.equity_curve[-1], btc_only.equity_curve[-1] + 1.0)

    def test_breadth_and_stricter_than_btc_only(self) -> None:
        # AND requires BOTH BTC up and breadth broad -> active fraction <= BTC-only.
        univ = {"BTCUSDT": _rising(step=1.5), "AUSDT": _falling(), "BUSDT": _falling()}
        btc_only = run_trend_portfolio(univ, master_gate_sym="BTCUSDT", master_gate_sma=5, **_PARAMS)
        breadth_and = run_trend_portfolio(univ, master_gate_sym="BTCUSDT", master_gate_sma=5,
                                          breadth_gate=0.5, breadth_combine="and", **_PARAMS)
        self.assertLessEqual(breadth_and.extra["gate_active_frac"],
                             btc_only.extra["gate_active_frac"] + 1e-9)

    def test_breadth_only_ignores_btc(self) -> None:
        univ = {"BTCUSDT": _falling(), "AUSDT": _rising(), "BUSDT": _rising(step=2.0)}
        res = run_trend_portfolio(univ, master_gate_sym="BTCUSDT", master_gate_sma=5,
                                  breadth_gate=0.5, breadth_combine="breadth", **_PARAMS)
        # ALTs (2/3 of universe) rising -> breadth gate open despite BTC down.
        self.assertGreater(res.equity_curve[-1], 100_000.0 + 1.0)


class TestAdxFilter(unittest.TestCase):
    """§21.C ADX chop filter on TrendFollow."""

    def test_adx_high_threshold_suppresses_entry(self) -> None:
        # An impossibly high ADX floor blocks every long -> flat -> equity stays at initial capital.
        univ = {"AUSDT": _rising(step=1.0), "BUSDT": _rising(step=2.0)}
        res = run_trend_portfolio(univ, master_gate_sym=None, adx_min=200.0, **_PARAMS)
        self.assertTrue(all(abs(e - 100_000.0) < 1e-6 for e in res.equity_curve))

    def test_adx_zero_is_baseline(self) -> None:
        univ = {"AUSDT": _rising(step=1.0), "BUSDT": _rising(step=2.0)}
        base = run_trend_portfolio(univ, master_gate_sym=None, **_PARAMS)
        adx0 = run_trend_portfolio(univ, master_gate_sym=None, adx_min=0.0, **_PARAMS)
        for a, b in zip(base.equity_curve, adx0.equity_curve):
            self.assertAlmostEqual(a, b, places=6)

    def test_adx_trend_passes_strong_move(self) -> None:
        # A clean monotone uptrend has high ADX -> a modest floor lets the long through.
        bars = _bars([100.0 * (1.02 ** i) for i in range(60)])
        tf = TrendFollow(fast=2, slow=4, allow_short=False, regime_sma=5, adx_min=20.0, adx_period=14)
        sig = [tf.on_bar(b) for b in bars]
        self.assertEqual(sig[-1], 1.0)  # strong trend -> ADX clears 20 -> long


class TestCorrPenaltyWeighting(unittest.TestCase):
    """§21.D correlation-penalty weighting in combine."""

    def test_corr_penalty_runs_and_normalizes(self) -> None:
        univ = {"AUSDT": _rising(step=1.0), "BUSDT": _rising(step=2.0), "CUSDT": _rising(step=1.5)}
        res = run_trend_portfolio(univ, master_gate_sym=None, weighting="inverse_vol_corr",
                                  vol_lookback=10, **_PARAMS)
        self.assertEqual(len(res.equity_curve), len(_rising()))
        self.assertGreater(res.equity_curve[-1], 0.0)

    def test_corr_penalty_single_sleeve_equals_inverse_vol(self) -> None:
        # one sleeve -> nothing to penalize -> identical to plain inverse_vol
        univ = {"AUSDT": _rising(step=1.0)}
        a = run_trend_portfolio(univ, master_gate_sym=None, weighting="inverse_vol_corr",
                                vol_lookback=10, **_PARAMS)
        b = run_trend_portfolio(univ, master_gate_sym=None, weighting="inverse_vol",
                                vol_lookback=10, **_PARAMS)
        for x, y in zip(a.equity_curve, b.equity_curve):
            self.assertAlmostEqual(x, y, places=6)


if __name__ == "__main__":
    unittest.main()
