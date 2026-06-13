"""Unit tests for X4 §12 dynamic-parameter optimizations: ATR + volatility-parity sizing (线 D).

ATR is the shared incremental indicator; ``run_directional(vol_target=...)`` scales the position so
each trade carries roughly constant risk (small in high vol, large/capped in low vol).
"""

from __future__ import annotations

import unittest

from qount.grid.data import Bar
from qount.x4.backtest import run_directional
from qount.x4.indicators import ATR

_T0 = 1_609_459_200_000
_D = 86_400_000


def _bar(i: int, close: float, *, high: float | None = None, low: float | None = None) -> Bar:
    h = close if high is None else high
    lo = close if low is None else low
    return Bar(ts_ms=_T0 + i * _D, open=close, high=max(h, close), low=min(lo, close),
               close=close, volume=1.0)


class TestATR(unittest.TestCase):
    def test_warmup_returns_none(self) -> None:
        a = ATR(lookback=3)
        self.assertIsNone(a.update(_bar(0, 100.0, high=101, low=99)))
        self.assertIsNone(a.update(_bar(1, 100.0, high=101, low=99)))
        self.assertIsNotNone(a.update(_bar(2, 100.0, high=101, low=99)))

    def test_constant_range_atr_equals_range(self) -> None:
        a = ATR(lookback=3)
        v = None
        for i in range(3):
            v = a.update(_bar(i, 100.0, high=102.0, low=98.0))  # TR ~ 4 each bar
        self.assertAlmostEqual(v, 4.0)

    def test_true_range_uses_prev_close_gap(self) -> None:
        a = ATR(lookback=1)
        a.update(_bar(0, 100.0, high=100.0, low=100.0))  # prev_close = 100
        # next bar gaps up: high 110 low 108, TR = max(2, |110-100|, |108-100|) = 10
        self.assertAlmostEqual(a.update(_bar(1, 109.0, high=110.0, low=108.0)), 10.0)


class _AlwaysLong:
    name = "always-long"

    def on_bar(self, bar: Bar) -> float:
        return 1.0


class TestVolSizing(unittest.TestCase):
    def test_high_vol_shrinks_position_vs_low_vol(self) -> None:
        # two regimes: a low-vol stretch then a high-vol stretch; vol-sizing should hold a smaller
        # base in the high-vol stretch (risk parity). Measure realized position via a price shock.
        low = [_bar(i, 100.0, high=100.5, low=99.5) for i in range(20)]      # ATR% ~ 1%
        r_low = run_directional(low, _AlwaysLong(), initial_capital=100_000.0, taker_fee=0.0,
                                slippage=0.0, vol_target=0.02, vol_lookback=5, max_leverage=5.0)
        high = [_bar(i, 100.0, high=104.0, low=96.0) for i in range(20)]     # ATR% ~ 8%
        r_high = run_directional(high, _AlwaysLong(), initial_capital=100_000.0, taker_fee=0.0,
                                 slippage=0.0, vol_target=0.02, vol_lookback=5, max_leverage=5.0)
        # final positions: low-vol scaled up (toward cap), high-vol scaled down
        self.assertGreater(r_low.equity_curve[-1] - 100_000.0, -1.0)  # ~flat price, ~no pnl
        # compare leverage via a probe: re-run with a terminal up-move and check pnl magnitude
        low2 = low + [_bar(20, 110.0, high=110.0, low=100.0)]
        high2 = high + [_bar(20, 110.0, high=110.0, low=100.0)]
        p_low = run_directional(low2, _AlwaysLong(), initial_capital=100_000.0, taker_fee=0.0,
                                slippage=0.0, vol_target=0.02, vol_lookback=5, max_leverage=5.0)
        p_high = run_directional(high2, _AlwaysLong(), initial_capital=100_000.0, taker_fee=0.0,
                                 slippage=0.0, vol_target=0.02, vol_lookback=5, max_leverage=5.0)
        gain_low = p_low.equity_curve[-1] - p_low.equity_curve[-2]
        gain_high = p_high.equity_curve[-1] - p_high.equity_curve[-2]
        self.assertGreater(gain_low, gain_high)  # bigger position in low vol -> bigger pnl on shock

    def test_vol_target_zero_is_unchanged_1x(self) -> None:
        bars = [_bar(0, 100.0), _bar(1, 110.0)]
        r = run_directional(bars, _AlwaysLong(), initial_capital=100_000.0, taker_fee=0.0,
                            slippage=0.0, vol_target=0.0)
        self.assertAlmostEqual(r.equity_curve[-1], 110_000.0, places=2)  # plain 1x

    def test_max_leverage_caps_low_vol_upsizing(self) -> None:
        # very low vol => vol_target/atr_pct huge, but capped at max_leverage=1.0 (=> ~1x)
        bars = [_bar(i, 100.0, high=100.01, low=99.99) for i in range(10)] + [_bar(10, 110.0)]
        r = run_directional(bars, _AlwaysLong(), initial_capital=100_000.0, taker_fee=0.0,
                            slippage=0.0, vol_target=0.02, vol_lookback=5, max_leverage=1.0)
        # capped at 1x: a +10% move from ~100 to 110 gives ~+10% (not leveraged)
        self.assertLess(r.equity_curve[-1], 112_000.0)


if __name__ == "__main__":
    unittest.main()
