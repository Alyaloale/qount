from __future__ import annotations

import unittest

from qount.grid.data import Bar
from qount.mini_trend.config import MiniTrendConfig
from qount.mini_trend.signals import target_weights

_T0 = 1_609_459_200_000
_D = 86_400_000


def _bars(closes: list[float]) -> list[Bar]:
    return [
        Bar(ts_ms=_T0 + i * _D, open=c, high=c * 1.01, low=c * 0.99, close=c, volume=1.0)
        for i, c in enumerate(closes)
    ]


class TestMiniTrendSignals(unittest.TestCase):
    def _cfg(self, **over) -> MiniTrendConfig:
        kw = dict(
            universe=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
            gate_sma=5,
            trend_sma=5,
            fast_sma=2,
            slow_sma=3,
            vol_lookback=3,
            atr_lookback=3,
            corr_penalty=False,
        )
        kw.update(over)
        return MiniTrendConfig(**kw)

    def test_risk_off_returns_zero_targets(self) -> None:
        cfg = self._cfg(breadth_gate=0.8)
        bars = {
            "BTCUSDT": _bars([10, 9, 8, 7, 6, 5]),
            "ETHUSDT": _bars([9, 8, 7, 6, 5, 4]),
            "SOLUSDT": _bars([8, 7, 6, 5, 4, 3]),
        }
        res = target_weights(bars, cfg)
        self.assertFalse(res.gate.risk_on)
        self.assertTrue(all(w == 0.0 for w in res.targets.values()))

    def test_breadth_or_opens_risk_when_btc_gate_closed(self) -> None:
        cfg = self._cfg(breadth_gate=0.5)
        up = [1, 2, 3, 4, 5, 6, 7]
        bars = {
            "BTCUSDT": _bars([10, 9, 8, 7, 6, 5, 4]),
            "ETHUSDT": _bars(up),
            "SOLUSDT": _bars([x * 2 for x in up]),
        }
        res = target_weights(bars, cfg)
        self.assertFalse(res.gate.btc_gate)
        self.assertTrue(res.gate.breadth_gate)
        self.assertGreater(res.targets["ETHUSDT"], 0.0)
        self.assertGreater(res.targets["SOLUSDT"], 0.0)
        self.assertEqual(res.targets["BTCUSDT"], 0.0)

    def test_targets_are_deterministic_long_only_and_gross_clamped(self) -> None:
        cfg = self._cfg(max_gross=0.6, breadth_gate=0.5)
        bars_a = {
            "SOLUSDT": _bars([2, 3, 4, 5, 6, 7, 8]),
            "ETHUSDT": _bars([1, 2, 3, 4, 5, 6, 7]),
            "BTCUSDT": _bars([1, 2, 3, 4, 5, 6, 7]),
        }
        bars_b = dict(reversed(list(bars_a.items())))
        a = target_weights(bars_a, cfg)
        b = target_weights(bars_b, cfg)
        self.assertEqual(a.targets, b.targets)
        self.assertTrue(all(w >= 0.0 for w in a.targets.values()))
        self.assertLessEqual(sum(a.targets.values()), cfg.max_gross + 1e-9)


if __name__ == "__main__":
    unittest.main()
