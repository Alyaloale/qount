import datetime as dt
import json
import math
import tempfile
import unittest
from pathlib import Path

from qount.dual_engine.contracts import G20_EXECUTION_TO_PROXY
from qount.dual_engine.strategy import build_g20_decision
from qount.research import c60_pit_universe as pit
from qount.research import dual_engine_optimization as study


def equity_fixture():
    dates = ("2018-01-29", "2018-01-30", "2018-01-31", "2018-02-01", "2018-02-02", "2018-02-05")
    prices = {s: (100.0,) * len(dates) for s in (*G20_EXECUTION_TO_PROXY, *G20_EXECUTION_TO_PROXY.values(), "BIL", "SPY")}
    return study.EquityPanel(dates, dict(prices), dict(prices), dict(prices))


def crypto_fixture():
    first = dt.date(2020, 8, 1)
    dates = tuple((first + dt.timedelta(days=i)).isoformat() for i in range(200))
    # All names have positive momentum and pass both gates initially.
    assets = {s: pit.Asset(s, s, 0, tuple(100 * math.exp(0.002 * i) for i in range(200)), (1e6,) * 200)
              for s in ("BTCUSDT", "ETHUSDT", "PAXGUSDT")}
    return pit.Axis(dates), assets


class EquityAccountingTests(unittest.TestCase):
    def test_next_open_does_not_capture_signal_to_fill_gap(self):
        panel = equity_fixture()
        panel.total_closes["TQQQ"] = (100.0, 100.0, 100.0, 200.0, 100.0, 100.0)
        panel.total_opens["TQQQ"] = panel.total_closes["TQQQ"]
        signals = {2: {"signal_date": panel.dates[2], "target": {"TQQQ": 0.2, "BIL": 0.8}}}
        base = study.replay_equity(panel, signals, start=panel.dates[2], cost_bps=0.0, delay=1)["records"]
        stress = study.replay_equity(panel, signals, start=panel.dates[2], cost_bps=0.0, delay=2)["records"]
        self.assertAlmostEqual(base[1]["return"], 0.0)  # no ownership of the +100% gap
        self.assertAlmostEqual(base[2]["return"], -0.1)
        self.assertAlmostEqual(stress[2]["return"], 0.0)  # late entry avoids that overnight drop
        self.assertEqual(base[1]["signal_date"], "2018-01-31")

    def test_monthly_holdings_drift_without_daily_turnover(self):
        panel = equity_fixture()
        panel.total_closes["TQQQ"] = (100.0, 100.0, 100.0, 200.0, 200.0, 200.0)
        signals = {2: {"signal_date": panel.dates[2], "target": {"TQQQ": 0.2, "BIL": 0.8}}}
        records = study.replay_equity(panel, signals, start=panel.dates[2], cost_bps=0.0, delay=1)["records"]
        self.assertAlmostEqual(records[1]["return"], 0.2)
        self.assertAlmostEqual(records[2]["weights"]["TQQQ"], 1 / 3)
        self.assertEqual(records[2]["turnover"], 0.0)

    def test_initial_purchase_and_both_sides_of_rotation_pay_cost(self):
        panel = equity_fixture()
        signals = {2: {"signal_date": panel.dates[2], "target": {"TQQQ": 0.2, "BIL": 0.8}}}
        records = study.replay_equity(panel, signals, start=panel.dates[2], cost_bps=20.0, delay=1)["records"]
        self.assertAlmostEqual(records[0]["cost_fraction"], 0.002)
        self.assertAlmostEqual(records[1]["turnover"], 0.4)
        self.assertAlmostEqual(records[1]["return"], -0.0008)

    def test_bil_distribution_total_return_is_earned(self):
        panel = equity_fixture()
        panel.total_closes["BIL"] = (100.0, 100.0, 100.0, 101.0, 102.01, 102.01)
        panel.total_opens["BIL"] = panel.total_closes["BIL"]
        records = study.replay_equity(panel, {}, start=panel.dates[2], cost_bps=0.0, delay=1)["records"]
        self.assertAlmostEqual(records[1]["return"], 0.01)
        self.assertAlmostEqual(records[2]["return"], 0.01)

    def test_frozen_proxy_selection_and_absolute_gate(self):
        first = dt.date(2017, 9, 1)
        dates = tuple((first + dt.timedelta(days=i)).isoformat() for i in range(200)
                      if (first + dt.timedelta(days=i)).weekday() < 5)
        closes = {s: tuple(100 * math.exp(-0.001 * (k + 1) * i) for i in range(len(dates)))
                  for k, s in enumerate(G20_EXECUTION_TO_PROXY.values())}
        panel = study.EquityPanel(dates, closes, {}, {})
        baseline = study.g20_signals(panel)
        candidate = study.g20_signals(panel, absolute_momentum=True)
        self.assertTrue(baseline)
        for i, signal in baseline.items():
            reference = build_g20_decision({s: v[i - 63:i + 1] for s, v in closes.items()})
            self.assertEqual(signal["target"], reference.target_weights)
            self.assertEqual(signal["selected"], reference.selected_symbol)
            self.assertEqual(candidate[i]["target"], {"BIL": 1.0})

    def test_source_hash_and_missing_session_rejected(self):
        contract = {"g20": {"data_start": "2017-09-01", "evaluation_end": "2018-07-01"}}
        first = dt.datetime(2017, 9, 1, 14, tzinfo=dt.timezone.utc)
        stamps = [int((first + dt.timedelta(days=i)).timestamp()) for i in range(130)]
        symbols = {*G20_EXECUTION_TO_PROXY, *G20_EXECUTION_TO_PROXY.values(), "BIL", "SPY"}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = {"files": {}}
            for symbol in symbols:
                result = {"meta": {"symbol": symbol}, "timestamp": stamps,
                          "indicators": {"quote": [{"open": [100.0] * 130, "close": [100.0] * 130}],
                                         "adjclose": [{"adjclose": [90.0] * 130}]}}
                path = root / f"{symbol}.source.json"
                study.write_json(path, {"chart": {"result": [result]}})
                manifest["files"][path.name] = study.file_hash(path)
            study.write_json(root / "manifest.json", manifest)
            panel, _ = study.load_equity(root, contract)
            self.assertEqual(panel.total_opens["BIL"][0], 90.0)
            path = root / "TQQQ.source.json"
            data = json.loads(path.read_text())
            data["chart"]["result"][0]["timestamp"].pop()
            study.write_json(path, data)
            with self.assertRaisesRegex(study.OptimizationStudyError, "hash_mismatch"):
                study.load_equity(root, contract)
            manifest["files"][path.name] = study.file_hash(path)
            study.write_json(root / "manifest.json", manifest)
            with self.assertRaisesRegex(study.OptimizationStudyError, "calendar_gap"):
                study.load_equity(root, contract)


class CryptoCausalityTests(unittest.TestCase):
    def test_future_gap_cannot_rename_prior_asset_or_change_targets(self):
        axis, assets = crypto_fixture()
        raw = {k: {d: [a.closes[i], a.quote[i]] for i, d in enumerate(axis.dates)} for k, a in assets.items()}
        del raw["ETHUSDT"]["2021-01-20"]
        full_axis, full_assets = study.build_crypto_assets(raw, end=axis.dates[-1])
        prefix_axis, prefix_assets = study.build_crypto_assets(raw, end="2021-01-15")
        prior_id = "ETHUSDT@2020-08-01"
        self.assertIn(prior_id, full_assets)
        self.assertIn(prior_id, prefix_assets)
        full, _ = study.c60_targets(full_axis, full_assets, universe="pit", confirmation=2)
        prefix, _ = study.c60_targets(prefix_axis, prefix_assets, universe="pit", confirmation=2)
        self.assertEqual(prefix, {k: full[k] for k in prefix})

    def test_unannounced_end_is_not_sold_in_advance(self):
        axis, assets = crypto_fixture()
        # The most liquid/winning candidate ends unexpectedly after 2021-01-02.
        end = axis.index("2021-01-02")
        old = assets["ETHUSDT"]
        assets["ETHUSDT"] = pit.Asset(old.asset_id, old.symbol, 0,
                                      tuple(100 * math.exp(0.004 * i) for i in range(end + 1)), (1e9,) * (end + 1))
        causal, _ = study.c60_targets(axis, assets, universe="pit")
        optimistic, _ = study.c60_targets(axis, assets, universe="pit", legacy_exit=True)
        self.assertIn("ETHUSDT", causal[end])
        self.assertNotIn("ETHUSDT", optimistic[end])
        run = study.replay_crypto(axis, assets, causal, cost_bps=0.0)
        record = next(r for r in run["records"] if r["date"] == "2021-01-03")
        self.assertEqual(record["missing_marks"], ["ETHUSDT"])
        self.assertAlmostEqual(record["writeoff_weight"], causal[end]["ETHUSDT"])
        self.assertLess(record["return"], -0.45)

    def test_future_truncation_does_not_change_past_targets(self):
        axis, assets = crypto_fixture()
        full, _ = study.c60_targets(axis, assets, universe="pit", confirmation=2)
        cut = axis.index("2021-01-15")
        shortened = {k: pit.Asset(k, a.symbol, a.start, a.closes[:cut + 1], a.quote[:cut + 1]) for k, a in assets.items()}
        prefix, _ = study.c60_targets(pit.Axis(axis.dates[:cut + 1]), shortened, universe="pit", confirmation=2)
        self.assertEqual(prefix, {k: full[k] for k in prefix})

    def test_confirmation_delays_entry_but_exits_immediately(self):
        axis, assets = crypto_fixture()
        t = axis.index("2021-01-05")
        old = assets["BTCUSDT"]
        values = list(old.closes)
        values[t] *= 0.5
        assets["BTCUSDT"] = pit.Asset(old.asset_id, old.symbol, 0, tuple(values), old.quote)
        base, _ = study.c60_targets(axis, assets, universe="btc")
        filtered, _ = study.c60_targets(axis, assets, universe="btc", confirmation=2)
        self.assertIn("BTCUSDT", filtered[t - 1])
        self.assertEqual(filtered[t], {})
        self.assertIn("BTCUSDT", base[t + 1])
        self.assertEqual(filtered[t + 1], {})
        self.assertIn("BTCUSDT", filtered[t + 2])

    def test_delay_has_same_dates_and_no_missing_fill(self):
        axis, assets = crypto_fixture()
        t = axis.index("2021-01-05")
        old = assets["ETHUSDT"]
        assets["ETHUSDT"] = pit.Asset(old.asset_id, old.symbol, 0, old.closes[:t + 1], old.quote[:t + 1])
        targets = {t: {"ETHUSDT": 0.5}}
        base = study.replay_crypto(axis, assets, targets, cost_bps=25.0)
        stress = study.replay_crypto(axis, assets, targets, cost_bps=50.0, delay=1)
        self.assertEqual([r["date"] for r in base["records"]], [r["date"] for r in stress["records"]])
        late = next(r for r in stress["records"] if r["date"] == "2021-01-07")
        self.assertEqual(late["weights"], {})
        self.assertEqual(late["turnover"], 0.0)

    def test_paxg_does_not_require_btc_gate(self):
        axis, assets = crypto_fixture()
        old = assets["BTCUSDT"]
        assets["BTCUSDT"] = pit.Asset(old.asset_id, old.symbol, 0,
                                      tuple(100 * math.exp(-0.003 * i) for i in range(200)), old.quote)
        targets, _ = study.c60_targets(axis, assets, universe="survivor", confirmation=2)
        t = axis.index("2021-01-05")
        self.assertIn("PAXGUSDT", targets[t])
        self.assertNotIn("ETHUSDT", targets[t])


class StudyEvidenceTests(unittest.TestCase):
    def test_drawdown_equality_ignores_machine_roundoff_without_changing_rejection(self):
        contract = study.read_contract(Path(__file__).resolve().parents[1] / "config/dual-engine-optimization-20261004.json")
        one = {"max_drawdown": -0.2, "cash_excess_sharpe": 0.5, "sharpe": 0.5, "cagr": 0.1,
               "annual_turnover": 20.0, "excluding_2021": {"sharpe": 0.5},
               "excluding_best_year": {"cagr": 0.1},
               "discovery_slices": [{"cash_excess_sharpe": 0.5, "sharpe": 0.5}] * 5}
        candidate = one | {"max_drawdown": -0.2 - 2e-16}
        results = {line: {"baseline": {"base": one, "stress": one},
                          "candidate": {"base": candidate, "stress": candidate},
                          "btc": {"base": one, "stress": one}} for line in ("g20", "c60")}
        decisions = study.candidate_gates(results, contract)
        for line in ("g20", "c60"):
            self.assertTrue(decisions[line]["gates"]["max_drawdown_not_worse"])
            self.assertEqual(decisions[line]["verdict"], "reject_discovery_candidate")

    def test_drawdown_includes_initial_cost_and_best_year_is_complete(self):
        first = dt.date(2020, 1, 1)
        records = [{"date": (first + dt.timedelta(days=i)).isoformat(), "return": -0.01 if i == 0 else 0.001,
                    "cash_return": 0.0, "gross": 1.0, "turnover": 0.1, "cost_fraction": 0.00025}
                   for i in range(800)]
        result = study.summarize({"records": records}, 365)
        self.assertAlmostEqual(result["max_drawdown"], -0.01)
        self.assertEqual(result["excluded_best_complete_year"], "2021")
        self.assertNotIn("2022", result["complete_years"])

    def test_paired_block_intervals_reject_date_mismatch(self):
        left = {"records": [{"date": str(i), "return": 0.01} for i in range(100)]}
        right = {"records": [{"date": str(i), "return": 0.0} for i in range(100)]}
        settings = {"block_lengths": [10], "draws": 40, "seed": 7}
        result = study.paired_intervals(left, right, annual=365, settings=settings)
        self.assertAlmostEqual(result["10"]["ci95"][0], math.log1p(0.01) * 365)
        right["records"][0]["date"] = "mismatch"
        with self.assertRaisesRegex(study.OptimizationStudyError, "paired_dates_mismatch"):
            study.paired_intervals(left, right, annual=365, settings=settings)

    def test_contract_guards(self):
        root = Path(__file__).resolve().parents[1]
        contract = study.read_contract(root / "config/dual-engine-optimization-20261004.json")
        self.assertFalse(contract["orders_authorized"])
        self.assertIsNone(contract["global_trial_count"])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "contract.json"
            study.write_json(path, contract | {"promotion_evidence": True})
            with self.assertRaisesRegex(study.OptimizationStudyError, "contract_invalid"):
                study.read_contract(path)


if __name__ == "__main__":
    unittest.main()
