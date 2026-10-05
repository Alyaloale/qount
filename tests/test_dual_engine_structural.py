import datetime as dt
import json
import math
from pathlib import Path
import unittest

from qount.dual_engine.contracts import G20_EXECUTION_TO_PROXY
from qount.research.dual_engine_optimization import EquityPanel
from qount.research.dual_engine_structural import (
    G20_CANDIDATES, G20_CONTROLS, C60_CANDIDATES, C60_CONTROLS,
    crypto_targets, daily_returns, equity_targets, portfolio_sigma,
    read_contract, relative_strength, replay_units, trend_score,
)
from qount.research.dual_engine_optimization import build_crypto_assets


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "config/dual-engine-structural-20261004.json"


def equity_fixture(n=210):
    dates, day = [], dt.date(2019, 1, 1)
    while len(dates) < n:
        if day.weekday() < 5:
            dates.append(day.isoformat())
        day += dt.timedelta(days=1)
    names = sorted({*G20_EXECUTION_TO_PROXY, *G20_EXECUTION_TO_PROXY.values(), "BIL", "SPY"})
    prices = {s: tuple(100 * math.exp((0.0001 if s == "BIL" else 0.001) * i
                                     + (0.0 if s == "BIL" else 0.01 * math.sin(i / 3))) for i in range(n)) for s in names}
    return EquityPanel(tuple(dates), prices, prices, prices)


def crypto_fixture(end="2021-03-31"):
    dates = [(dt.date(2020, 1, 1) + dt.timedelta(days=i)).isoformat()
             for i in range((dt.date.fromisoformat(end) - dt.date(2020, 1, 1)).days + 1)]
    raw = {s: {d: (100 * math.exp(speed * i + 0.02 * math.sin(i / 5)), 1e8)
               for i, d in enumerate(dates)}
           for s, speed in (("BTCUSDT", .001), ("ETHUSDT", .002), ("SOLUSDT", .003), ("PAXGUSDT", .0001))}
    return build_crypto_assets(raw, end=end)


class StructuralSignalTests(unittest.TestCase):
    def test_contract_inventory_counts_every_candidate_and_control(self):
        c = read_contract(CONTRACT)
        self.assertEqual(c["new_candidate_trials"], len(G20_CANDIDATES) + len(C60_CANDIDATES))
        self.assertEqual(c["planned_curves"], 4 * (len(G20_CANDIDATES + G20_CONTROLS) + len(C60_CANDIDATES + C60_CONTROLS)))

    def test_trend_scale_invariance_and_falling_market_is_cash(self):
        prices = [math.exp(.005 * i + .001 * math.sin(i)) for i in range(100)]
        self.assertGreater(trend_score(prices, [20, 60, 90]), .9)
        self.assertAlmostEqual(trend_score(prices, [20, 60, 90]), trend_score([p * 77 for p in prices], [20, 60, 90]))
        self.assertEqual(trend_score(list(reversed(prices)), [20, 60, 90]), 0.0)

    def test_relative_strength_removes_common_market_beta(self):
        market = [math.exp(.002 * i + .01 * math.sin(i)) for i in range(100)]
        relative = relative_strength([p ** 2 for p in market], market)
        self.assertAlmostEqual(relative["beta"], 2.0)
        self.assertAlmostEqual(relative["residual_log_90"], 0.0)
        self.assertGreater(relative_strength([p ** 2 * math.exp(.001 * i) for i, p in enumerate(market)], market)["score"], 0.0)

    def test_portfolio_risk_counts_correlation(self):
        returns = {"a": [-.1, .1] * 30, "b": [-.1, .1] * 30}
        full = portfolio_sigma(returns, {"a": 1.0}, 365)
        split = portfolio_sigma(returns, {"a": .5, "b": .5}, 365)
        self.assertAlmostEqual(full, split)

    def test_equity_prefix_invariant_and_long_cash(self):
        panel = equity_fixture()
        truncated = EquityPanel(panel.dates[:180], *({s: v[:180] for s, v in p.items()}
                                for p in (panel.closes, panel.total_closes, panel.total_opens)))
        c = read_contract(CONTRACT)
        for rule in G20_CANDIDATES + G20_CONTROLS[1:]:
            full = equity_targets(panel, c["g20"], rule)
            short = equity_targets(truncated, c["g20"], rule)
            self.assertEqual(short, {i: v for i, v in full.items() if i < 179})
            for target in full.values():
                self.assertAlmostEqual(sum(target.values()), 1.0)
                self.assertTrue(all(w >= 0.0 for w in target.values()))

    def test_crypto_prefix_invariant_and_no_leverage(self):
        axis, assets = crypto_fixture()
        short_axis, short_assets = crypto_fixture("2021-02-17")
        c = read_contract(CONTRACT)
        for rule in C60_CANDIDATES + C60_CONTROLS:
            full, _ = crypto_targets(axis, assets, c["c60"], rule)
            short, _ = crypto_targets(short_axis, short_assets, c["c60"], rule)
            self.assertEqual(short, {i: v for i, v in full.items() if i < len(short_axis.dates)})
            self.assertTrue(all(0.0 <= sum(w.values()) <= 1.0 + 1e-12 for w in full.values()))

    def test_satellite_zero_is_exact_core_only_ablation(self):
        axis, assets = crypto_fixture()
        settings = read_contract(CONTRACT)["c60"] | {"satellite_weight": 0.0}
        with_satellite, _ = crypto_targets(axis, assets, settings, "core_satellite")
        core, _ = crypto_targets(axis, assets, settings, "core_only")
        self.assertEqual(with_satellite, core)

    def test_partial_and_full_share_the_same_aim(self):
        axis, assets = crypto_fixture()
        settings = read_contract(CONTRACT)["c60"]
        self.assertEqual(crypto_targets(axis, assets, settings, "core_satellite"),
                         crypto_targets(axis, assets, settings, "core_satellite_partial"))


class UnitAccountingTests(unittest.TestCase):
    def run_prices(self, prices, targets, **kwargs):
        dates = tuple(f"2021-01-{i:02d}" for i in range(1, len(prices) + 1))
        closes = {"x": dict(zip(dates, prices, strict=True))}
        opens = {"x": dict(zip(dates, kwargs.pop("opens", prices), strict=True))}
        return replay_units(dates, closes, opens, targets,
                            start=dates[1], lag=1, cost_bps=kwargs.pop("cost_bps", 0.0), **kwargs)["records"]

    def test_future_gap_belongs_to_old_units(self):
        rows = self.run_prices([100., 100., 200., 200.], {0: {"x": .5}, 1: {}})
        self.assertAlmostEqual(rows[1]["return"], .5)
        self.assertEqual(rows[1]["units"], {})

    def test_self_financing_fees_and_cash(self):
        rows = self.run_prices([100.] * 4, {0: {"x": 1.0}, 1: {}}, cost_bps=50)
        nav_after_entry = 1.0 / 1.005
        self.assertAlmostEqual(rows[0]["nav"], nav_after_entry)
        self.assertAlmostEqual(rows[1]["nav"], nav_after_entry * .995)
        self.assertAlmostEqual(rows[1]["cash"], rows[1]["nav"])

    def test_partial_target_uses_prior_close_not_today_open(self):
        targets = {0: {"x": .5}, 1: {"x": .5}}
        low = self.run_prices([100.] * 4, targets, opens=[100., 100., 50., 100.], adjustment=.25)
        high = self.run_prices([100.] * 4, targets, opens=[100., 100., 200., 100.], adjustment=.25)
        self.assertEqual(low[1]["target_weights"], high[1]["target_weights"])
        self.assertAlmostEqual(low[1]["target_weights"]["x"], .21875)

    def test_partial_exit_is_immediate_and_risk_cap_cannot_linger(self):
        rows = self.run_prices([100.] * 5, {0: {"x": .8}, 1: {"x": .1}, 2: {}}, adjustment=.25)
        self.assertAlmostEqual(rows[1]["target_weights"]["x"], .1)
        self.assertEqual(rows[2]["units"], {})

    def test_delayed_fill_observes_only_available_aim(self):
        dates = tuple(f"2021-01-{i:02d}" for i in range(1, 5))
        prices = {"x": dict(zip(dates, [100.] * 4, strict=True))}
        run = replay_units(dates, prices, prices, {0: {"x": .5}, 1: {}, 2: {}},
                           start=dates[2], lag=2, cost_bps=0.0)
        self.assertEqual(run["records"][0]["target_weights"], {"x": .5})
        self.assertEqual(run["records"][0]["signal_date"], dates[0])

    def test_missing_input_open_rejects_instead_of_erasing_trade(self):
        dates = ("2021-01-01", "2021-01-02")
        prices = {"x": {d: 100. for d in dates}}
        with self.assertRaisesRegex(ValueError, "required_open_missing"):
            replay_units(dates, prices, {"x": {}}, {0: {"x": .5}}, start=dates[1], lag=1, cost_bps=0.0)

    def test_missing_held_market_marks_zero_without_advance_exit(self):
        dates = ("2021-01-01", "2021-01-02", "2021-01-03")
        prices = {"x": {d: 100. for d in dates[:2]}}
        rows = replay_units(dates, prices, prices, {0: {"x": .5}}, start=dates[1], lag=1, cost_bps=0.0)["records"]
        self.assertEqual(rows[0]["missing_marks"], [])
        self.assertAlmostEqual(rows[1]["return"], -.5)
        self.assertEqual(rows[1]["missing_marks"], ["x"])

    def test_replay_prefix_is_unchanged_by_future_prices(self):
        rows = self.run_prices([100., 100., 110., 90., 200.], {0: {"x": .5}, 1: {"x": .6}, 3: {}})
        prefix = self.run_prices([100., 100., 110., 90.], {0: {"x": .5}, 1: {"x": .6}})
        self.assertEqual(rows[:3], prefix)


if __name__ == "__main__":
    unittest.main()
