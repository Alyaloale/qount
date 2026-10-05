import datetime as dt
import json
import math
from pathlib import Path
import tempfile
import unittest

from qount.research import dual_engine_expansion as e
from qount.research.dual_engine_expansion_data import network_growth, load_rates
from qount.research.dual_engine_optimization import EquityPanel, build_crypto_assets, write_json, file_hash
from qount.research.dual_engine_execution_study import paired_diagnostics
from qount.research.dual_engine_structural import crypto_targets as prior_targets, replay_units
from test_dual_engine_structural import equity_fixture

CONTRACT = Path(__file__).resolve().parents[1] / "config/dual-engine-expansion-20261004.json"


def network_fixture(day="2021-03-31"):
    end = dt.date.fromisoformat(day)
    return {(end - dt.timedelta(days=i)).isoformat():
            {"AdrActCnt": 100 + 70 - i, "FeeTotNtv": 10 + (70 - i) / 10} for i in range(80)}


def crypto_fixture(end="2021-03-31"):
    first, last = dt.date(2020, 1, 1), dt.date.fromisoformat(end)
    dates = [(first + dt.timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]
    names = ["BTCUSDT"] + [f"N{i:02}USDT" for i in range(24)]
    raw = {s: {d: [100 * math.exp(.001 * i + .02 * math.sin(i / 5)
                    + (0 if s == "BTCUSDT" else .00002 * (k + 1) * i)), 1e8 / (k + 1)]
               for i, d in enumerate(dates)} for k, s in enumerate(names)}
    return build_crypto_assets(raw, end=end)


def macro_fixture():
    p = equity_fixture(240)
    data = dict(p.closes)
    for s in e.MACRO:
        data[s] = tuple(100 * math.exp(.0005 * i + .001 * math.sin(i)) for i in range(240))
    return EquityPanel(p.dates, data, data, data)


class ExpansionTests(unittest.TestCase):
    def test_inventory_counts_candidates_and_all_controls(self):
        c = e.read_contract(CONTRACT)
        self.assertEqual(c["new_candidate_trials"], len(e.C60_CANDIDATES + e.G20_CANDIDATES))
        self.assertEqual(c["planned_curves"], 4 * len(e.C60_CANDIDATES + e.C60_CONTROLS + e.G20_CANDIDATES + e.G20_CONTROLS))

    def test_rank_ties_are_equal_and_monotone(self):
        self.assertEqual(e.percentile({"a": 1, "b": 1, "c": 3}), {"a": 1 / 3, "b": 1 / 3, "c": 5 / 6})

    def test_network_feature_ignores_recent_and_future_rows(self):
        rows = network_fixture()
        a = network_growth(rows, "2021-03-31")
        self.assertIsNotNone(a)
        for d in rows:
            if d > "2021-03-24":
                rows[d] = {"AdrActCnt": 1e15, "FeeTotNtv": 1e15}
        self.assertEqual(network_growth(rows, "2021-03-31"), a)

    def test_network_gaps_and_nonpositive_fees_are_not_filled(self):
        rows = network_fixture()
        del rows["2021-03-20"]
        self.assertIsNone(network_growth(rows, "2021-03-31"))
        rows = network_fixture()
        rows["2021-03-20"]["FeeTotNtv"] = 0
        self.assertIsNone(network_growth(rows, "2021-03-31"))

    def test_network_scale_invariant(self):
        rows = network_fixture()
        scaled = {d: {m: v * 77 for m, v in r.items()} for d, r in rows.items()}
        for k, v in network_growth(rows, "2021-03-31").items():
            self.assertAlmostEqual(v, network_growth(scaled, "2021-03-31")[k])

    def test_rates_lag_and_staleness(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for s in ("DFII10", "T10YIE"):
                (root / f"{s}.csv").write_text(f"observation_date,{s}\n2021-01-01,1\n2021-01-04,99\n")
            write_json(root / "manifest.json", {"files": {p.name: file_hash(p) for p in root.glob("*.csv")}})
            dates = ["2021-01-01", "2021-01-04", "2021-01-05", "2021-01-06", "2021-01-20"]
            self.assertEqual(load_rates(root, dates)["DFII10"], [None, None, 1, 99, None])

    def test_four_and_wide_positions_break_two_position_limit(self):
        axis, assets = crypto_fixture()
        market = next(a for a in assets.values() if a.symbol == "BTCUSDT").window(len(axis.dates) - 1)
        selected, small = e.select_satellites(assets, len(axis.dates) - 1, market, axis.dates[-1], "residual4_8", {})
        self.assertEqual(len(selected), 4)
        _, wide = e.select_satellites(assets, len(axis.dates) - 1, market, axis.dates[-1], "equal_positive20", {})
        self.assertEqual(len(small["universe"]), 8)
        self.assertEqual(len(wide["universe"]), 20)
        self.assertGreater(len(wide["selected"]), 4)

    def test_crypto_control_matches_prior_targets_exactly(self):
        axis, assets = crypto_fixture()
        c = e.read_contract(CONTRACT)
        self.assertEqual(e.crypto_targets(axis, assets, c["c60"], "residual2", {}), prior_targets(axis, assets, c["c60"], "core_satellite"))

    def test_all_crypto_rules_are_prefix_causal_and_long_cash(self):
        axis, assets = crypto_fixture()
        short, short_assets = crypto_fixture("2021-02-17")
        c = e.read_contract(CONTRACT)
        for rule in e.C60_CANDIDATES + e.C60_CONTROLS:
            full, _ = e.crypto_targets(axis, assets, c["c60"], rule, {})
            partial, _ = e.crypto_targets(short, short_assets, c["c60"], rule, {})
            self.assertEqual(partial, {i: v for i, v in full.items() if i < len(short.dates)}, rule)
            self.assertTrue(all(all(w >= 0 for w in row.values()) and sum(row.values()) <= 1 + 1e-12 for row in full.values()), rule)

    def test_random_control_reproducible_and_seed_distinct(self):
        axis, assets = crypto_fixture()
        t = len(axis.dates) - 1
        market = next(a for a in assets.values() if a.symbol == "BTCUSDT").window(t)
        a = e.select_satellites(assets, t, market, axis.dates[t], "random_positive2_s11", {})
        self.assertEqual(a, e.select_satellites(assets, t, market, axis.dates[t], "random_positive2_s11", {}))
        self.assertNotEqual(a[0], e.select_satellites(assets, t, market, axis.dates[t], "random_positive2_s29", {})[0])

    def test_fundamentals_use_same_coverage_and_gate_rejects_bad_growth(self):
        axis, assets = crypto_fixture()
        t = len(axis.dates) - 1
        market = next(a for a in assets.values() if a.symbol == "BTCUSDT").window(t)
        rows = network_fixture(axis.dates[t])
        network = {a.symbol: rows for a in assets.values()}
        covered, info = e.select_satellites(assets, t, market, axis.dates[t], "coverage4", network)
        # Give the price leader sharply falling chain activity before the lag cutoff.
        leader = assets[covered[0]].symbol
        reverse = {d: {m: 300 - v for m, v in row.items()} for d, row in rows.items()}
        network[leader] = reverse
        _, coverage = e.select_satellites(assets, t, market, axis.dates[t], "coverage4", network)
        ranked, fundamental = e.select_satellites(assets, t, market, axis.dates[t], "fundamental4", network)
        gated, gate = e.select_satellites(assets, t, market, axis.dates[t], "usage_gate4", network)
        self.assertEqual(coverage["covered"], fundamental["covered"])
        self.assertEqual(coverage["covered"], gate["covered"])
        self.assertNotIn(covered[0], gated)
        self.assertNotEqual(covered, ranked)

    def test_macro_positive_slots_do_not_spend_missing_budget(self):
        scores = {s: -1 for s in e.MACRO}
        scores["GLD"] = 1
        self.assertEqual(e.macro_allocation(scores), {"GLD": .15})
        self.assertAlmostEqual(sum(e.macro_allocation(scores, static=True).values()), .45)

    def test_equity_signals_are_prefix_causal_and_can_have_many_positions(self):
        p = macro_fixture()
        partial = EquityPanel(p.dates[:210], *({s: v[:210] for s, v in mapping.items()}
                             for mapping in (p.closes, p.total_closes, p.total_opens)))
        rates = {s: [.5] * len(p.dates) for s in ("DFII10", "T10YIE")}
        c = e.read_contract(CONTRACT)
        for rule in e.G20_CANDIDATES + e.G20_CONTROLS:
            full, _ = e.equity_targets(p, c["g20"], rule, rates)
            short, _ = e.equity_targets(partial, c["g20"], rule, rates)
            self.assertEqual(short, {i: v for i, v in full.items() if i < 209}, rule)
            self.assertTrue(all(abs(sum(v.values()) - 1) < 1e-12 and min(v.values()) >= 0 for v in full.values()), rule)
        wide, _ = e.equity_targets(p, c["g20"], "multi3_macro", rates)
        self.assertGreater(max(len(v) for v in wide.values()), 2)

    def test_crisis_classifies_inflation_and_preserves_hysteresis(self):
        p = macro_fixture()
        values = dict(p.total_closes)
        t = 200
        spy, ief = list(values["SPY"]), list(values["IEF"])
        for i in range(t - 5, t + 1):
            spy[i] = spy[t - 6] * (1 - .025 * (i - (t - 5) + 1))
        ief[t] = ief[t - 63] * .95
        values["SPY"], values["IEF"] = tuple(spy), tuple(ief)
        p = EquityPanel(p.dates, values, values, values)
        rates = {s: [i / 100 for i in range(240)] for s in ("DFII10", "T10YIE")}
        self.assertEqual(e.crisis_state(p, t, "normal", rates), "inflation")
        self.assertEqual(e.crisis_state(p, t, "deflation", rates), "deflation")

    def test_pnl_oracle_handles_overnight_rotation_and_fees(self):
        dates = ("2021-01-01", "2021-01-02", "2021-01-03")
        closes = {"a": dict(zip(dates, (10., 12., 15.))), "b": dict(zip(dates, (10., 11., 12.)))}
        opens = {"a": dict(zip(dates, (10., 11., 14.))), "b": dict(zip(dates, (10., 10.5, 11.5)))}
        run = replay_units(dates, closes, opens, {0: {"a": .6}, 1: {"b": .4}}, start=dates[1], lag=1, cost_bps=50)
        report = e.contributions(run, dates, closes, opens, annual=365, market="a")
        self.assertLess(report["wealth_reconciliation_error"], 1e-12)
        self.assertGreater(report["fee_initial_nav_units"], 0)

    def test_vectorized_bootstrap_matches_existing_algorithm(self):
        try:
            import numpy
        except ImportError:
            self.skipTest("research numpy unavailable")
        a = {"records": [{"date": str(i), "return": .002 * math.sin(i) + .001, "cash_return": .0001} for i in range(50)]}
        b = {"records": [{"date": str(i), "return": .003 * math.cos(i), "cash_return": .0001} for i in range(50)]}
        settings = {"block_lengths": [10, 20], "draws": 20, "seed": 20261004}
        old, fast = paired_diagnostics(a, b, annual=365, settings=settings), e.paired_fast(a, b, annual=365, settings=settings)
        for block in old:
            for key in ("log_growth_ci95", "sharpe_ci95"):
                for x, y in zip(old[block][key], fast[block][key]):
                    self.assertAlmostEqual(x, y, places=12)

    def test_single_year_crisis_window_needs_no_year_exclusion(self):
        run = {"records": [{"date": d, "return": r, "cash_return": 0, "risk_gross": .5, "turnover": 0}
                           for d, r in (("2021-01-01", -.1), ("2021-12-31", .2))]}
        report = e.window_summary(run, "2021-01-01", "2021-12-31", 365)
        self.assertAlmostEqual(report["total_return"], .08)
        self.assertNotIn("cagr", report)
        self.assertEqual(e.window_summary(run, "2022-01-01", "2022-12-31", 365), {"status": "outside_evaluation"})


if __name__ == "__main__":
    unittest.main()
