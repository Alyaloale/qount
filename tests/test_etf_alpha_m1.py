from __future__ import annotations

import csv
import datetime as dt
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

from qount.research.etf_alpha.artifacts import new_directory, sha256, verify_files
from qount.research.etf_alpha.data import Panel, load_public_panel, total_return_index
from qount.research.etf_alpha.execution import ExecutionInputs, simulate
from qount.research.etf_alpha.features import build_features, trailing_normalize
from qount.research.etf_alpha.labels import build_labels, opening_label_oracle
from qount.research.etf_alpha.splits import expanding_folds
from qount.research.etf_trader.costs import CostParams
from qount.research.etf_trader.env import Decision
from qount.research.etf_trader.universe import US_ACCOUNT


def fixture(T=80, first="2019-01-02", seed=4):
    rng = np.random.default_rng(seed)
    days = np.busday_offset(first, np.arange(T), roll="forward").astype(str)
    close = 100 * np.cumprod(1 + rng.normal(0.0002, 0.008, (T, 9)), axis=0)
    opn = close * (1 + rng.normal(0, 0.001, (T, 9)))
    return Panel(tuple(days), US_ACCOUNT.symbols, opn, np.maximum(close, opn) * 1.01,
                 np.minimum(close, opn) * .99, close, rng.uniform(1e5, 1e6, (T, 9)),
                 np.zeros((T, 9)), np.ones((T, 9)), np.cumprod(np.full(T, 1.0001)),
                 np.cumprod(np.full(T, 1.0001)), {})


def flat_fixture(T=8):
    panel = fixture(T)
    values = np.full((T, 9), 100.0)
    return replace(panel, open=values.copy(), close=values.copy(), high=values.copy(), low=values.copy(),
                   cash_open=np.ones(T), cash_close=np.ones(T))


def prepared(panel, spread=0):
    return ExecutionInputs(np.full(panel.open.shape, 1e9), np.full(panel.open.shape, .01),
                           np.full(panel.open.shape, spread), np.zeros(panel.open.shape, bool),
                           np.r_[0, panel.cash_close[1:] / panel.cash_close[:-1] - 1])


ZERO_COSTS = CostParams(0, 0, 0, 0, 0, (0,) * 9, 0, 0)
NATURAL = replace(US_ACCOUNT, single_cap=1, group_cap=1)
SPY = np.array([1., 0, 0, 0, 0, 0, 0, 0, 0])


class ArtifactTests(unittest.TestCase):
    def test_missing_disk_and_existing_run_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                new_directory(root / "missing/artifacts/etf_alpha_p3/run", external_root=root / "missing")
            out = root / "artifacts/etf_alpha_p3/run"
            new_directory(out, external_root=root)
            with self.assertRaises(FileExistsError):
                new_directory(out, external_root=root)
            with self.assertRaises(ValueError):
                new_directory(root / "elsewhere", external_root=root)

    def test_hash_corruption_and_manifest_traversal_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "evidence.json"
            path.write_text("original")
            digest = sha256(path)
            self.assertEqual(verify_files(root, {path.name: digest})[path.name], digest)
            path.write_text("modified")
            with self.assertRaises(ValueError):
                verify_files(root, {path.name: digest})
            with self.assertRaises(ValueError):
                verify_files(root, {"../private": digest})


class SourceTests(unittest.TestCase):
    def source(self, root):
        T = 10
        times = [int(dt.datetime.fromisoformat(f"2020-01-{day:02d}T14:30:00+00:00").timestamp())
                 for day in (2, 3, 6, 7, 8, 9, 10, 13, 14, 15)]
        manifest = {"source": "fixture", "start": "2020-01-02", "end": "2020-01-15",
                    "observed_at": "2020-01-16T00:00:00Z", "research_only": True,
                    "orders_authorized": False, "files": {}}
        for s in (*US_ACCOUNT.symbols, "BIL"):
            quote = {k: [100.] * T for k in ("open", "close", "high", "low")}
            quote["volume"] = [100000] * T
            raw = {"meta": {"symbol": s, "exchangeTimezoneName": "America/New_York"},
                   "timestamp": times, "events": {},
                   "indicators": {"quote": [quote], "adjclose": [{"adjclose": [80.] * T}]}}
            rp = root / f"{s}.source.json"
            rp.write_text(json.dumps(raw))
            cp = root / f"{s}_daily.csv"
            with cp.open("w", newline="") as stream:
                writer = csv.writer(stream); writer.writerow(["Date", "Open", "Close", "Adj Close", "Volume"])
                for timestamp in times:
                    writer.writerow([dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).date().isoformat(),
                                     100, 100, 80, 100000])
            manifest["files"][s] = {"file": cp.name, "sha256": sha256(cp), "raw_file": rp.name,
                                     "raw_sha256": sha256(rp), "split_events": 0, "missing_dates": []}
        (root / "manifest.json").write_text(json.dumps(manifest))

    def test_raw_sources_are_readback_and_calendar_is_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.source(root)
            panel = load_public_panel(root)
            self.assertEqual(len(panel.dates), 10)
            self.assertEqual(panel.audit["excluded_calendar_dates"], [])
            (root / "SPY.source.json").write_text("{}")
            with self.assertRaises(ValueError):
                load_public_panel(root)

    def test_same_hash_valid_missing_session_is_not_silently_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.source(root)
            p = root / "QQQ.source.json"; raw = json.loads(p.read_text())
            raw["timestamp"].pop(4)
            for arr in raw["indicators"]["quote"][0].values(): arr.pop(4)
            raw["indicators"]["adjclose"][0]["adjclose"].pop(4)
            p.write_text(json.dumps(raw))
            manifest = json.loads((root / "manifest.json").read_text())
            manifest["files"]["QQQ"]["raw_sha256"] = sha256(p)
            (root / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaises(ValueError): load_public_panel(root)

    def test_unsorted_calendar_and_unknown_split_are_rejected(self):
        panel = fixture()
        with self.assertRaises(ValueError): replace(panel, dates=tuple(reversed(panel.dates)))
        splits = panel.splits.copy(); splits[10, 0] = np.nan
        with self.assertRaises(ValueError): replace(panel, splits=splits)


class FeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = fixture(1450, first="2009-01-02")
        cls.features = build_features(cls.panel)

    def test_schema_has_38_and_value_is_removed(self):
        f = self.features
        self.assertEqual(len(f.names), 38)
        self.assertEqual(f.raw.shape, (1450, 9, 38))
        self.assertFalse(f.schema["value_enabled"])
        self.assertTrue(f.available[-1].all())
        self.assertTrue(np.isnan(f.normalized[0]).all())

    def test_appending_future_cannot_change_existing_features_or_scales(self):
        early = build_features(self.panel.prefix(1350))
        np.testing.assert_allclose(early.raw, self.features.raw[:1350], equal_nan=True)
        np.testing.assert_allclose(early.normalized, self.features.normalized[:1350], equal_nan=True)
        np.testing.assert_allclose(early.market_normalized, self.features.market_normalized[:1350], equal_nan=True)
        np.testing.assert_allclose(early.covariance_annual, self.features.covariance_annual[:1350], equal_nan=True)

    def test_asset_reordering_preserves_features_and_covariance_rows_columns(self):
        order = [8, 0, 6, 4, 2, 1, 5, 3, 7]
        reordered = build_features(self.panel.reordered(tuple(self.panel.symbols[i] for i in order)))
        np.testing.assert_allclose(reordered.normalized, self.features.normalized[:, order], atol=1e-8, equal_nan=True)
        np.testing.assert_allclose(reordered.market_raw, self.features.market_raw, atol=1e-10, equal_nan=True)
        np.testing.assert_allclose(reordered.covariance_annual, self.features.covariance_annual[:, order][:, :, order], atol=1e-12, equal_nan=True)

    def test_missing_close_is_masked_in_return_windows(self):
        close = self.panel.close.copy(); close[1360, 0] = np.nan
        changed = build_features(replace(self.panel, close=close))
        self.assertTrue(np.isnan(changed.raw[1365, 0, changed.names.index("return20")]))
        self.assertFalse(changed.available[1365, 0, changed.names.index("return20")])

    def test_constant_normalizer_and_future_extreme_use_only_past(self):
        x = np.ones((20, 1)); x[-1] = 1e6
        z, mask = trailing_normalize(x, window=5)
        np.testing.assert_array_equal(z[4:19], 0)
        self.assertTrue(mask[4:19].all())
        self.assertTrue(np.isnan(z[:4]).all())

    def test_covariance_is_symmetric_psd_and_annualized(self):
        cov = self.features.covariance_annual[-1]
        np.testing.assert_allclose(cov, cov.T)
        self.assertGreaterEqual(np.linalg.eigvalsh(cov).min(), -1e-12)
        self.assertGreater(np.trace(cov), 0)


class LabelTests(unittest.TestCase):
    def test_ex_date_entry_exit_and_split_match_independent_share_oracle(self):
        panel = flat_fixture(80)
        opn = panel.open.copy(); opn[4:] = 50
        split = panel.splits.copy(); split[4] = 2
        dividends = panel.dividends.copy(); dividends[1] = 10; dividends[4] = 1; dividends[6] = 2
        panel = replace(panel, open=opn, splits=split, dividends=dividends)
        labels = build_labels(panel)
        self.assertEqual(labels.start_rows[0], 1)
        self.assertEqual(labels.end_rows[5][0], 6)
        expected = (1 + 1 / 50) * (1 + 2 / 50) - 1
        self.assertAlmostEqual(labels.values["mu5"][0, 0], expected)
        for horizon in (5, 20, 60):
            self.assertAlmostEqual(labels.values[f"mu{horizon}"][0, 0], opening_label_oracle(panel, 0, 1, horizon + 1))

    def test_each_horizon_has_its_own_tail_mask(self):
        labels = build_labels(fixture(90))
        self.assertTrue(labels.available["mu5"][-7].all())
        self.assertFalse(labels.available["mu20"][-7].any())
        self.assertFalse(labels.available["mu60"][-7].any())
        self.assertEqual(labels.end_rows[5][-1], -1)
        np.testing.assert_array_equal(labels.values["q10"], labels.values["mu20"])

    def test_missing_open_inside_label_is_not_bridged(self):
        panel = fixture(90); opn = panel.open.copy(); opn[10, 0] = np.nan
        labels = build_labels(replace(panel, open=opn))
        self.assertFalse(labels.available["mu20"][0, 0])
        self.assertTrue(labels.available["mu5"][0, 0])

    def test_future_cash_is_only_in_labels(self):
        panel = fixture(90); later_cash = panel.cash_open.copy(); later_cash[30:] *= 2
        left, right = build_labels(panel), build_labels(replace(panel, cash_open=later_cash))
        np.testing.assert_allclose(left.values["mu20"], right.values["mu20"], equal_nan=True)
        self.assertNotEqual(left.values["cash60"][0, 0], right.values["cash60"][0, 0])


class FoldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = fixture(4650, first="2009-01-02")
        cls.labels = build_labels(cls.panel)
        cls.folds = expanding_folds(cls.panel.dates, cls.labels, np.ones(4650, bool))

    def test_train_validation_labels_finish_before_next_partition_and_embargo(self):
        dates = np.asarray(self.panel.dates)
        self.assertEqual(len(self.folds), 7)
        for fold in self.folds:
            va, te = np.searchsorted(dates, [fold.validation_start, fold.test_start])
            self.assertTrue((self.labels.end_rows[60][fold.train_rows] < va - 5).all())
            self.assertTrue((self.labels.end_rows[60][fold.validation_rows] < te - 5).all())
            self.assertTrue((dates[fold.train_rows] < fold.validation_start).all())

    def test_test_execution_days_are_neither_purged_nor_dropped_at_label_tail(self):
        all_test = np.concatenate([fold.test_rows for fold in self.folds])
        expected = np.flatnonzero((np.asarray(self.panel.dates) >= "2020-01-01") & (np.asarray(self.panel.dates) < "2027-01-01"))
        np.testing.assert_array_equal(all_test, expected)
        self.assertEqual(len(set(all_test)), len(all_test))


class AccountingTests(unittest.TestCase):
    def run_sim(self, panel, policy, **kwargs):
        return simulate(panel, policy, start=kwargs.pop("start", 0), account=NATURAL, costs=ZERO_COSTS,
                        initial_equity=1000, inputs=prepared(panel), **kwargs)

    def test_first_fill_is_next_open_and_has_no_same_close_trade(self):
        panel = flat_fixture()
        opn = panel.open.copy(); opn[1, 0] = 125
        result = self.run_sim(replace(panel, open=opn), lambda obs: Decision(SPY) if obs.t == 0 else Decision(None))
        self.assertEqual(result.shares[0, 0], 0)
        self.assertEqual(result.executed_shares[1, 0], 8)
        self.assertEqual(result.equity[1], 800)

    def test_dividend_belongs_to_holder_selling_at_ex_open(self):
        panel = flat_fixture(); d = panel.dividends.copy(); d[2, 0] = 2
        opn, close = panel.open.copy(), panel.close.copy(); opn[2:, 0] = 98; close[2:, 0] = 98
        panel = replace(panel, dividends=d, open=opn, close=close)
        policy = lambda obs: Decision(SPY if obs.t == 0 else np.zeros(9))
        result = self.run_sim(panel, policy)
        self.assertEqual(result.distributions[2], 20)
        self.assertEqual(result.shares[2, 0], 0)
        self.assertAlmostEqual(result.cash[2], 1000)

    def test_buyer_at_ex_open_does_not_receive_prior_entitlement(self):
        panel = flat_fixture(); d = panel.dividends.copy(); d[2, 0] = 10
        result = self.run_sim(replace(panel, dividends=d), lambda obs: Decision(SPY) if obs.t == 1 else Decision(None))
        self.assertEqual(result.distributions[2], 0)
        self.assertEqual(result.equity[2], 1000)

    def test_split_changes_shares_without_creating_wealth(self):
        panel = flat_fixture(); splits = panel.splits.copy(); splits[3, 0] = 2
        opn, close = panel.open.copy(), panel.close.copy(); opn[3:, 0] = 50; close[3:, 0] = 50
        result = self.run_sim(replace(panel, splits=splits, open=opn, close=close),
                              lambda obs: Decision(SPY) if obs.t == 0 else Decision(None))
        self.assertEqual(result.shares[3, 0], 20)
        self.assertEqual(result.equity[3], 1000)

    def test_costs_cannot_create_a_cash_loan_and_budget_records_actual_fill(self):
        panel = flat_fixture()
        result = simulate(panel, lambda obs: Decision(SPY) if obs.t == 0 else Decision(None), start=0,
                          account=NATURAL, costs=ZERO_COSTS, initial_equity=1000, inputs=prepared(panel, spread=.01))
        self.assertEqual(result.shares[1, 0], 9)
        self.assertGreaterEqual(np.nanmin(result.cash), 0)
        self.assertAlmostEqual(result.voluntary_turnover[1], .45)
        self.assertAlmostEqual(result.equity[1], 991)

    def test_contiguous_rerun_carries_holdings_cash_dd_and_turnover(self):
        panel = flat_fixture(); close = panel.close.copy(); close[2:4, 0] = 80; close[4:, 0] = 85
        panel = replace(panel, close=close)
        policy = lambda obs: Decision(SPY)
        whole = self.run_sim(panel, policy)
        first = self.run_sim(panel, policy, stop=3)
        second = self.run_sim(panel, policy, start=3, state=first.state)
        for name in ("equity", "shares", "cash", "gross_cap"):
            np.testing.assert_allclose(getattr(whole, name)[3:], getattr(second, name)[3:])
        # Boundary-day fills belong to the first segment, not the next segment.
        for name in ("costs", "voluntary_turnover", "forced_turnover", "returns", "distributions"):
            joined = np.r_[getattr(first, name)[:4], getattr(second, name)[4:]]
            np.testing.assert_allclose(getattr(whole, name), joined)
        self.assertEqual(whole.state.derisk.peak, second.state.derisk.peak)
        self.assertEqual(whole.state.budget.used_voluntary, second.state.budget.used_voluntary)

    def test_capacity_uses_the_decision_day_adv(self):
        panel = flat_fixture(); inputs = prepared(panel); inputs.adv[0, 0] = 1000
        result = simulate(panel, lambda obs: Decision(SPY), start=0, account=NATURAL, costs=ZERO_COSTS,
                          initial_equity=1000, inputs=inputs)
        self.assertEqual(result.executed_shares[1, 0], 0)  # $50 capacity cannot buy one $100 share


if __name__ == "__main__":
    unittest.main()
