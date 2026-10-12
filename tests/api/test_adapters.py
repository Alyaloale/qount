"""Unit tests for research line adapters."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from qount.api.adapters import get_adapter, list_adapters
from qount.api.schemas import PaperLine

FIXTURE_SNAPSHOT = os.path.join(
    os.path.dirname(__file__), "fixtures", "dual_engine"
)


class TestAdapters(unittest.TestCase):
    def test_adapter_discovery(self) -> None:
        adapters = list_adapters()
        self.assertIn("personal_assistant", adapters)
        self.assertIn("binance_macro", adapters)
        self.assertIn("ashare_master", adapters)
        self.assertIn("dual_engine", adapters)

    def test_unknown_adapter_returns_none(self) -> None:
        self.assertIsNone(get_adapter("non_existent_adapter_name"))

    def test_personal_assistant_adapter(self) -> None:
        adapter = get_adapter("personal_assistant")
        self.assertIsNotNone(adapter)
        line: PaperLine = adapter(
            line_id="personal_assistant",
            name="个人量化交易助手",
            config={"run": "state/research_runs/personal_assistant_reconciled_20261012"},
        )
        self.assertIsInstance(line, PaperLine)
        self.assertEqual(line.line_id, "personal_assistant")
        self.assertEqual(line.status, "ACTIVE_PAPER")
        self.assertEqual(line.category, "assistant")
        self.assertEqual(line.freshness, "FRESH")
        self.assertGreater(len(line.nav_series), 0)
        self.assertGreaterEqual(len(line.positions), 1)
        self.assertEqual(line.positions[0].symbol, "513100.SH")
        self.assertEqual(line.safety.research_only, True)
        self.assertEqual(line.safety.orders_authorized, False)

    def test_binance_macro_adapter(self) -> None:
        adapter = get_adapter("binance_macro")
        self.assertIsNotNone(adapter)
        line: PaperLine = adapter(
            line_id="binance_macro",
            name="币安全球多资产合约",
            config={"run": "state/research_runs/binance_global_macro_20261011"},
        )
        self.assertIsInstance(line, PaperLine)
        self.assertEqual(line.line_id, "binance_macro")
        self.assertEqual(line.status, "ARCHIVED")
        self.assertEqual(line.category, "macro")
        self.assertEqual(line.freshness, "STALE")
        self.assertEqual(line.metrics.cagr_pct, 41.29)
        self.assertEqual(line.metrics.max_drawdown_pct, 36.63)
        self.assertGreater(len(line.nav_series), 0)

    def test_ashare_master_adapter(self) -> None:
        adapter = get_adapter("ashare_master")
        self.assertIsNotNone(adapter)
        line: PaperLine = adapter(
            line_id="ashare_master",
            name="A股赛道动量突破(麒麟)",
            config={"run": "state/research_runs/ashare_sector_momentum_20261011"},
        )
        self.assertIsInstance(line, PaperLine)
        self.assertEqual(line.line_id, "ashare_master")
        self.assertEqual(line.status, "STOPPED")
        self.assertEqual(line.category, "equity")
        self.assertEqual(line.freshness, "FRESH")
        self.assertGreater(len(line.nav_series), 0)

    def test_dual_engine_adapter_parses_real_snapshot(self) -> None:
        """The adapter must mirror the snapshot, not invent figures."""
        adapter = get_adapter("dual_engine")
        self.assertIsNotNone(adapter)
        line: PaperLine = adapter(
            line_id="dual_g20",
            name="美股轮动 (G20)",
            config={"account": "g20", "root": FIXTURE_SNAPSHOT},
        )
        self.assertIsInstance(line, PaperLine)
        self.assertIsNone(line.error)
        self.assertEqual(line.status, "ACTIVE_PAPER")
        self.assertEqual(line.category, "equity")
        # Values below come from the fixture snapshot, which itself mirrors the live snapshot shape.
        self.assertEqual(line.as_of, "2026-10-09")
        self.assertAlmostEqual(line.metrics.ytd_return_pct, 15.26, places=2)
        self.assertAlmostEqual(line.metrics.max_drawdown_pct, -16.33, places=2)
        self.assertAlmostEqual(line.metrics.signal_nav, 1.157073, places=6)
        self.assertAlmostEqual(line.metrics.executable_nav, 1.152573, places=6)
        self.assertEqual(len(line.nav_series), 3)
        self.assertAlmostEqual(line.nav_series[-1].nav, 1.152573, places=6)
        self.assertAlmostEqual(line.nav_series[-1].signal_nav, 1.157073, places=6)
        # Benchmark comes from the snapshot's benchmark block, not a constant.
        self.assertAlmostEqual(line.nav_series[-1].benchmark_nav, 1.041, places=3)
        # Holdings mirror the snapshot and are ordered by weight, largest first.
        symbols = [p.symbol for p in line.positions]
        self.assertEqual(symbols, ["BIL", "ERX"])
        self.assertAlmostEqual(line.positions[0].weight, 0.7781, places=4)
        self.assertIsNotNone(line.source.sha256)

    def test_dual_engine_all_four_accounts_resolve(self) -> None:
        adapter = get_adapter("dual_engine")
        expected = {
            "g20": ("equity", "BIL"),
            "c60": ("crypto", "DOTUSDT"),
            "gc5": ("mixed", "BIL"),
            "d15": ("mixed", "BIL"),
        }
        for account, (category, top_symbol) in expected.items():
            with self.subTest(account=account):
                line = adapter(
                    line_id=f"dual_{account}",
                    name=account,
                    config={"account": account, "root": FIXTURE_SNAPSHOT},
                )
                self.assertIsNone(line.error)
                self.assertEqual(line.category, category)
                self.assertEqual(line.positions[0].symbol, top_symbol)
                self.assertGreater(len(line.nav_series), 0)

    def test_dual_engine_missing_snapshot_reports_no_figures(self) -> None:
        """Regression: an unreadable source must never be filled in with placeholder numbers.

        The previous implementation returned a hand-written NAV series and a hardcoded 12.3%
        return when the snapshot was absent, which is indistinguishable from real performance
        in the UI. It must now report MISSING with no metrics at all.
        """
        adapter = get_adapter("dual_engine")
        line = adapter(
            line_id="dual_g20",
            name="美股轮动 (G20)",
            config={"account": "g20", "root": os.path.join(FIXTURE_SNAPSHOT, "does-not-exist")},
        )
        self.assertEqual(line.status, "MISSING")
        self.assertEqual(line.freshness, "MISSING")
        self.assertIsNotNone(line.error)
        self.assertIn("SNAPSHOT_NOT_FOUND", line.error)
        self.assertIsNone(line.metrics, "missing source must not carry any performance figure")
        self.assertEqual(line.nav_series, [])
        self.assertEqual(line.positions, [])

    def test_dual_engine_unknown_account_rejected(self) -> None:
        """C20 / G60 do not exist; an unknown account must be rejected, not silently mapped."""
        adapter = get_adapter("dual_engine")
        for bogus in ("c20", "g60"):
            with self.subTest(account=bogus):
                line = adapter(
                    line_id=f"dual_{bogus}",
                    name=bogus,
                    config={"account": bogus, "root": FIXTURE_SNAPSHOT},
                )
                self.assertEqual(line.status, "MISSING")
                self.assertIsNotNone(line.error)
                self.assertIn("UNKNOWN_ACCOUNT", line.error)
                self.assertIsNone(line.metrics)

    def test_dual_engine_accepts_real_snapshot_point_keys(self) -> None:
        """Regression: the live snapshot names its NAV fields "executable" and "signal".

        An earlier revision read "executable_nav"/"signal_nav" and therefore found no usable
        points in the real 291-point series, reporting every account as MISSING. This test
        feeds the real key names so the field contract cannot drift unnoticed.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            current = os.path.join(tmpdir, "current")
            os.makedirs(current)
            snapshot = {
                "generated_at": "2026-10-10T22:30:07Z",
                "data_cutoff": "2026-10-09T23:59:59Z",
                "portfolios": [
                    {
                        "portfolio_id": "dual-engine-paper-g20",
                        "label": "G20",
                        "initial_capital": 10000.0,
                        "nav": {
                            "signal": 1.1570733266660154,
                            "executable": 1.152573307,
                            "since_start_return_fraction": 0.15257330699999994,
                            "max_drawdown_fraction": -0.1632937017544871,
                            "current_drawdown_fraction": -0.1211,
                            "points": [
                                {
                                    "marked_at": "2026-01-02T15:00:30+00:00",
                                    "executable": 0.998029002,
                                    "signal": 1.0,
                                    "executable_equity": 9980.29002,
                                },
                                {
                                    "marked_at": "2026-10-10T22:30:07.903153+00:00",
                                    "executable": 1.152573307,
                                    "signal": 1.1570733266660154,
                                    "executable_equity": 11525.73307,
                                },
                            ],
                        },
                        "holdings": [
                            {
                                "symbol": "BIL",
                                "quantity": 98.0,
                                "mark_price": 91.51,
                                "market_value": 8967.98,
                                "actual_weight": 0.7780832633841313,
                            }
                        ],
                    }
                ],
                "benchmarks": [],
            }
            with open(os.path.join(current, "paper_program_snapshot.json"), "w") as fh:
                json.dump(snapshot, fh)

            adapter = get_adapter("dual_engine")
            line = adapter(
                line_id="dual_g20",
                name="美股轮动 (G20)",
                config={"account": "g20", "root": tmpdir},
            )

        self.assertIsNone(line.error)
        self.assertEqual(len(line.nav_series), 2)
        self.assertAlmostEqual(line.nav_series[-1].nav, 1.152573307, places=8)
        self.assertAlmostEqual(line.nav_series[-1].signal_nav, 1.1570733266660154, places=8)
        self.assertAlmostEqual(line.metrics.ytd_return_pct, 15.26, places=2)
        self.assertEqual(line.positions[0].symbol, "BIL")
        # No benchmark block means no benchmark line: absent, never spliced or defaulted to a
        # made-up series.
        self.assertEqual(line.nav_series[-1].benchmark_nav, 1.0)


if __name__ == "__main__":
    unittest.main()
