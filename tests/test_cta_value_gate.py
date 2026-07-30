"""V-GATE unit tests (docs/archive/legacy/line-a/cta-r-value-gate-plan.md, step 1).

The valuation filter is a single new layer on the validated CTA-R engine. These tests pin
the contract BEFORE any data/API work: (1) gate off == byte-identical to the current engine,
(2) gate on zeroes "expensive" equity sleeves, (3) non-equity sleeves (no PE/PB) pass through,
(4) a data hole passes through and is never silently treated as cheap/expensive.
"""

from __future__ import annotations

import sys
import types
import unittest

# Match the import-stub convention of test_cta_sim.py (the qount chain can touch ccxt/openai).
if "ccxt" not in sys.modules:
    class _StubExchange:
        def __init__(self, options=None) -> None:
            self.options = options or {}

    sys.modules["ccxt"] = types.SimpleNamespace(binance=_StubExchange, binanceus=_StubExchange)

from qount.cta_sim import SimConfig
from qount.cta_sim import _percentile_rank
from qount.cta_sim import _target_weights
from qount.cta_sim import _value_gated
from qount.cta_sim import run_paper_sim


def _rets_from_prices(prices: dict[str, list[float]]) -> dict[str, list[float | None]]:
    rets: dict[str, list[float | None]] = {}
    for name, series in prices.items():
        out: list[float | None] = [None]
        for t in range(1, len(series)):
            prev = series[t - 1]
            out.append(series[t] / prev - 1.0 if prev > 0 else None)
        rets[name] = out
    return rets


def _uptrend(start: float, step: float, n: int) -> list[float]:
    """Strictly increasing price series -> trend sign = +1 over every lookback."""
    return [start + step * i for i in range(n)]


def _ramp(lo: float, hi: float, n: int) -> list[float]:
    """Linear ramp from lo to hi (inclusive); last value is the series max if hi>lo."""
    return [lo + (hi - lo) * i / (n - 1) for i in range(n)]


class PercentileRankTest(unittest.TestCase):
    def test_empty_window_is_cheap(self) -> None:
        self.assertEqual(_percentile_rank([], 5.0), 0.0)

    def test_top_value_ranks_one(self) -> None:
        self.assertEqual(_percentile_rank([1.0, 2.0, 3.0], 3.0), 1.0)

    def test_bottom_value_ranks_low(self) -> None:
        # only the value itself is <= 1.0 -> 1/3.
        self.assertAlmostEqual(_percentile_rank([1.0, 2.0, 3.0], 1.0), 1.0 / 3.0)


class ValueGatedTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = SimConfig(value_gate=True, value_gate_pct=0.80, value_gate_lookback_days=756)
        self.t = 199

    def test_no_valuation_series_passes_through(self) -> None:
        # gold/bond/QDII: name absent from the valuation panel.
        gated, status = _value_gated(None, "518880.SH", self.t, self.cfg)
        self.assertFalse(gated)
        self.assertEqual(status, "no_data")
        gated, status = _value_gated({"510300.SH": {"pe": _ramp(10, 30, 200)}},
                                     "518880.SH", self.t, self.cfg)
        self.assertFalse(gated)
        self.assertEqual(status, "no_data")

    def test_expensive_is_gated(self) -> None:
        # PE rising to its trailing max -> percentile 1.0 >= 0.80 -> gated.
        val = {"510300.SH": {"pe": _ramp(10, 30, 200)}}
        gated, status = _value_gated(val, "510300.SH", self.t, self.cfg)
        self.assertTrue(gated)
        self.assertEqual(status, "expensive")

    def test_cheap_is_kept(self) -> None:
        # PE falling to its trailing min -> low percentile -> kept.
        val = {"510300.SH": {"pe": _ramp(30, 10, 200)}}
        gated, status = _value_gated(val, "510300.SH", self.t, self.cfg)
        self.assertFalse(gated)
        self.assertEqual(status, "ok")

    def test_missing_value_passes_through(self) -> None:
        # series exists but today's value is a hole -> never silently cheap/expensive.
        series = _ramp(10, 30, 200)
        series[self.t] = None
        gated, status = _value_gated({"510300.SH": {"pe": series}}, "510300.SH", self.t, self.cfg)
        self.assertFalse(gated)
        self.assertEqual(status, "missing")

    def test_pb_alone_can_gate(self) -> None:
        # PE missing, PB rich -> OR logic still gates.
        val = {"510300.SH": {"pe": [None] * 200, "pb": _ramp(1.0, 3.0, 200)}}
        gated, status = _value_gated(val, "510300.SH", self.t, self.cfg)
        self.assertTrue(gated)
        self.assertEqual(status, "expensive")


class TargetWeightsValueGateTest(unittest.TestCase):
    """Gate behaviour inside _target_weights (the place it actually reweights the book)."""

    def setUp(self) -> None:
        n = 300
        # Four equity sleeves (all uptrending -> all in the raw book) + one gold sleeve.
        self.prices = {
            "510300.SH": _uptrend(10.0, 0.03, n),
            "510500.SH": _uptrend(8.0, 0.02, n),
            "159915.SZ": _uptrend(2.0, 0.01, n),
            "510050.SH": _uptrend(3.0, 0.015, n),
            "518880.SH": _uptrend(4.0, 0.012, n),  # gold: no PE/PB
        }
        self.rets = _rets_from_prices(self.prices)
        self.t = 270
        # 159915 is "expensive" (PE rising to max); the rest are cheap (PE falling to min).
        self.valuation = {
            "510300.SH": {"pe": _ramp(30, 10, n)},
            "510500.SH": {"pe": _ramp(28, 12, n)},
            "159915.SZ": {"pe": _ramp(10, 40, n)},
            "510050.SH": {"pe": _ramp(25, 11, n)},
            # 518880 (gold) deliberately absent -> pass through.
        }

    def test_gate_off_passthrough_identical(self) -> None:
        cfg_off = SimConfig(long_only=True)
        base = _target_weights(self.prices, self.rets, self.t, cfg_off, 1.0, 1.0)
        # Passing a valuation panel with the gate OFF must change nothing.
        same = _target_weights(self.prices, self.rets, self.t, cfg_off, 1.0, 1.0,
                               None, self.valuation)
        self.assertEqual(base, same)

    def test_gate_zeroes_expensive_equity(self) -> None:
        cfg_on = SimConfig(long_only=True, value_gate=True, value_gate_pct=0.80)
        w = _target_weights(self.prices, self.rets, self.t, cfg_on, 1.0, 1.0, None, self.valuation)
        # The expensive sleeve is dropped from the book entirely.
        self.assertNotIn("159915.SZ", w)
        # Survivors still form a real book.
        self.assertGreater(sum(abs(v) for v in w.values()), 0.0)

    def test_gate_passes_through_nonequity(self) -> None:
        cfg_on = SimConfig(long_only=True, value_gate=True, value_gate_pct=0.80)
        w = _target_weights(self.prices, self.rets, self.t, cfg_on, 1.0, 1.0, None, self.valuation)
        # Gold has no PE/PB -> it must survive the gate.
        self.assertIn("518880.SH", w)
        self.assertGreater(w["518880.SH"], 0.0)

    def test_missing_data_sleeve_not_gated(self) -> None:
        # Wipe 510500's PE at the decision day: a hole must NOT remove it from the book.
        val = {k: {m: list(s) for m, s in v.items()} for k, v in self.valuation.items()}
        val["510500.SH"]["pe"][self.t] = None
        cfg_on = SimConfig(long_only=True, value_gate=True, value_gate_pct=0.80)
        w = _target_weights(self.prices, self.rets, self.t, cfg_on, 1.0, 1.0, None, val)
        self.assertIn("510500.SH", w)


class RunPaperSimValueGateTest(unittest.TestCase):
    """End-to-end: gate off is byte-identical; gate on changes the equity curve."""

    def setUp(self) -> None:
        n = 320
        self.prices = {
            "510300.SH": _uptrend(10.0, 0.03, n),
            "510500.SH": _uptrend(8.0, 0.02, n),
            "159915.SZ": _uptrend(2.0, 0.01, n),
        }
        self.valuation = {
            "510300.SH": {"pe": _ramp(30, 10, n)},
            "510500.SH": {"pe": _ramp(28, 12, n)},
            "159915.SZ": {"pe": _ramp(10, 40, n)},  # expensive
        }

    def test_gate_off_identical_with_or_without_valuation(self) -> None:
        cfg = SimConfig(long_only=True)
        base = run_paper_sim(self.prices, cfg)
        with_val = run_paper_sim(self.prices, cfg, valuation=self.valuation)
        self.assertEqual(base["final_equity"], with_val["final_equity"])
        self.assertEqual(base["net_daily_returns"], with_val["net_daily_returns"])

    def test_gate_on_changes_equity_curve(self) -> None:
        cfg_off = SimConfig(long_only=True)
        cfg_on = SimConfig(long_only=True, value_gate=True, value_gate_pct=0.80)
        off = run_paper_sim(self.prices, cfg_off, valuation=self.valuation)
        on = run_paper_sim(self.prices, cfg_on, valuation=self.valuation)
        # Dropping the expensive sleeve must move the realized equity.
        self.assertNotEqual(off["final_equity"], on["final_equity"])


if __name__ == "__main__":
    unittest.main()
