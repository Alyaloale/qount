"""Unit tests for the X4 forward paper-sim engine (线 D §18, B2).

The engine must (a) deploy exactly the 3 validated sleeves (S2 excluded), (b) reproduce the standalone
backtests bit-for-bit (fidelity by construction), (c) match the portfolio combiner, (d) emit a usable
snapshot. Pure/offline (synthetic bars, no network).
"""

from __future__ import annotations

import unittest

from qount.research_data.market_data import Bar
from qount.legacy.x4.backtest import run_directional, run_grid
from qount.legacy.x4.papersim import DEPLOYED_SLEEVES, PaperConfig, run_paper
from qount.legacy.x4.portfolio import combine
from qount.legacy.x4.strategies import GridStrategy, MomentumBreakout, TrendFollow

_T0 = 1_609_459_200_000
_D = 86_400_000


def _bars(n: int) -> list[Bar]:
    # a noisy uptrend so the directional sleeves actually take positions
    out = []
    px = 100.0
    for i in range(n):
        px *= 1.0 + (0.02 if i % 3 else -0.015)
        out.append(Bar(ts_ms=_T0 + i * _D, open=px, high=px * 1.02, low=px * 0.98, close=px, volume=1.0))
    return out


class TestPaperEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.bars = _bars(420)  # enough for SMA200 warm-up
        self.cfg = PaperConfig()

    def test_excludes_s2(self) -> None:
        self.assertEqual(set(DEPLOYED_SLEEVES), {"S1-GRID", "S3-CTA", "S4-MOM"})
        r = run_paper(self.bars, config=self.cfg)
        self.assertEqual(set(r.sleeve_curves), {"S1-GRID", "S3-CTA", "S4-MOM"})

    def test_fidelity_sleeves_match_standalone_backtests(self) -> None:
        r = run_paper(self.bars, config=self.cfg)
        s3 = run_directional(self.bars, TrendFollow(fast=20, slow=100, allow_short=False, regime_sma=200),
                             initial_capital=self.cfg.initial_capital, taker_fee=self.cfg.taker_fee,
                             slippage=self.cfg.slippage, rebalance_band=0.25, vol_target=0.03,
                             max_leverage=2.0, periods_per_year=365.0)
        s1 = run_grid(self.bars, GridStrategy(), initial_capital=self.cfg.initial_capital,
                      taker_fee=self.cfg.taker_fee, slippage=self.cfg.slippage, atr_mult=5.0,
                      periods_per_year=365.0)
        self.assertEqual(r.sleeve_curves["S3-CTA"], s3.equity_curve)  # bit-for-bit
        self.assertEqual(r.sleeve_curves["S1-GRID"], s1.equity_curve)

    def test_portfolio_matches_combiner(self) -> None:
        r = run_paper(self.bars, config=self.cfg)
        expected = combine(r.sleeve_curves, scheme="equal", initial_capital=self.cfg.initial_capital)
        self.assertEqual(r.portfolio_curve, expected)

    def test_snapshot_shape(self) -> None:
        r = run_paper(self.bars, config=self.cfg)
        snap = r.snapshot
        self.assertEqual(snap["date"], self.bars[-1].date)
        self.assertEqual(set(snap["sleeves"]), {"S1-GRID", "S3-CTA", "S4-MOM"})
        for m in snap["sleeves"].values():
            self.assertIn("sharpe", m)
            self.assertIn("max_drawdown", m)
        self.assertIn("equity", snap["portfolio"])
        self.assertIn("S3-CTA", snap["positions"])

    def test_curves_aligned_length(self) -> None:
        r = run_paper(self.bars, config=self.cfg)
        n = len(self.bars)
        for c in r.sleeve_curves.values():
            self.assertEqual(len(c), n)
        self.assertEqual(len(r.portfolio_curve), n)

    def test_incremental_equals_full_rerun(self) -> None:
        # appending one bar and re-running == running on the longer series up to that bar (causal)
        full = run_paper(self.bars, config=self.cfg)
        upto = run_paper(self.bars[:-1], config=self.cfg)
        # the shorter run's last equity must equal the full run's second-to-last (same bar history)
        self.assertAlmostEqual(upto.portfolio_curve[-1], full.portfolio_curve[-2], places=6)


if __name__ == "__main__":
    unittest.main()
