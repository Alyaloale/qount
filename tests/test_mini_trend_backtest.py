from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from qount.grid.data import Bar
from qount.mini_trend.backtest import align_bars, research_filters, run_backtest, write_backtest_artifact
from qount.mini_trend.config import MiniTrendConfig

_T0 = 1_609_459_200_000
_D = 86_400_000


def _bars(closes: list[float]) -> list[Bar]:
    return [
        Bar(ts_ms=_T0 + i * _D, open=c, high=c * 1.01, low=c * 0.99, close=c, volume=1.0)
        for i, c in enumerate(closes)
    ]


class TestMiniTrendBacktest(unittest.TestCase):
    def _cfg(self, **over) -> MiniTrendConfig:
        kw = dict(
            universe=("BTCUSDT", "ETHUSDT"),
            gate_sma=5,
            trend_sma=5,
            fast_sma=2,
            slow_sma=3,
            vol_lookback=3,
            atr_lookback=3,
            corr_penalty=False,
            min_notional_coverage=0.5,
        )
        kw.update(over)
        return MiniTrendConfig(**kw)

    def test_align_bars_keeps_common_timestamps(self) -> None:
        a = _bars([1, 2, 3])
        b = _bars([9, 8, 7])[1:]
        aligned = align_bars({"BTCUSDT": a, "ETHUSDT": b}, ("BTCUSDT", "ETHUSDT"))
        self.assertEqual([x.ts_ms for x in aligned["BTCUSDT"]], [a[1].ts_ms, a[2].ts_ms])
        self.assertEqual([x.ts_ms for x in aligned["ETHUSDT"]], [b[0].ts_ms, b[1].ts_ms])

    def test_run_backtest_emits_scorecard_and_orders(self) -> None:
        cfg = self._cfg(capital_cap_usdt=400.0)
        up = [100 + i for i in range(18)]
        bars = {"BTCUSDT": _bars(up), "ETHUSDT": _bars([50 + i * 0.5 for i in range(18)])}
        res = run_backtest(
            bars,
            cfg,
            filters=research_filters(cfg.universe, min_notional=1.0),
            taker_fee=0.001,
            slippage=0.0,
        )
        self.assertEqual(res.summary["mode"], "backtest")
        self.assertGreater(res.summary["bars"], 0)
        self.assertGreater(res.summary["order_count"], 0)
        self.assertIn(res.scorecard.verdict, {"pass", "watch", "block"})
        self.assertEqual(res.scorecard.metrics["schema_error_count"], 0)

    def test_artifact_writer_outputs_replay_files(self) -> None:
        cfg = self._cfg()
        up = [100 + i for i in range(18)]
        bars = {"BTCUSDT": _bars(up), "ETHUSDT": _bars([50 + i for i in range(18)])}
        res = run_backtest(bars, cfg, filters=research_filters(cfg.universe, min_notional=1.0))
        with tempfile.TemporaryDirectory() as d:
            out = write_backtest_artifact(res, d)
            self.assertTrue((out / "summary.json").exists())
            self.assertTrue((out / "scorecard.json").exists())
            self.assertTrue((out / "orders.jsonl").exists())
            summary = json.loads((Path(d) / "summary.json").read_text())
        self.assertEqual(summary["strategy"], "MiniTrend-5")


if __name__ == "__main__":
    unittest.main()
