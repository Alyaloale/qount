import datetime as dt
import hashlib
import io
import json
import math
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from qount.research import c60_execution_control as execution
from qount.research import c60_pit_universe as pit


def fixture(days=230):
    start = dt.date(2020, 8, 1)
    dates = tuple((start + dt.timedelta(days=i)).isoformat() for i in range(days))
    assets = {s: pit.Asset(s, s, 0, tuple(100.0 + i * speed for i in range(days)), (1e6,) * days)
              for s, speed in (("BTCUSDT", 0.1), ("ETHUSDT", 0.2), ("PAXGUSDT", 0.15))}
    opens = {s: {d: asset.closes[i] for i, d in enumerate(dates)} for s, asset in assets.items()}
    return pit.Axis(dates), assets, opens


def replace_close(assets, symbol, index, value):
    old = assets[symbol]
    values = list(old.closes)
    values[index] = value
    assets[symbol] = pit.Asset(old.asset_id, old.symbol, old.start, tuple(values), old.quote)


class WarmTargetTests(unittest.TestCase):
    def test_evaluation_inherits_previous_month_candidate(self):
        axis, assets, _ = fixture()
        targets, members = execution.warm_targets(axis, assets)
        first_eligible = axis.index("2020-11-08")
        month_end = axis.index("2020-11-30")
        self.assertEqual(targets[first_eligible], {})
        self.assertIn(month_end, members)
        self.assertTrue(targets[axis.index("2020-12-05")])
        self.assertTrue(targets[axis.index("2021-01-01")])

    def test_monthly_btc_carries_momentum_eligibility_until_refresh(self):
        axis, assets, _ = fixture()
        t = axis.index("2021-01-08")
        # A historical bump kills only today's 90-day momentum; current gates stay open.
        replace_close(assets, "BTCUSDT", t - 90, 1000.0)
        daily, _ = execution.warm_targets(axis, assets, universe="btc")
        monthly, _ = execution.warm_targets(axis, assets, universe="btc_monthly")
        self.assertEqual(daily[t], {})
        self.assertIn("BTCUSDT", monthly[t])

    def test_monthly_paxg_gate_does_not_require_btc_pass(self):
        axis, assets, _ = fixture()
        old = assets["BTCUSDT"]
        assets["BTCUSDT"] = pit.Asset(old.asset_id, old.symbol, 0,
                                      tuple(200.0 - i * 0.1 for i in range(len(axis.dates))), old.quote)
        targets, _ = execution.warm_targets(axis, assets)
        target = targets[axis.index("2021-01-05")]
        self.assertIn("PAXGUSDT", target)
        self.assertNotIn("ETHUSDT", target)

    def test_truncated_tail_does_not_create_a_month_end(self):
        axis, assets, _ = fixture()
        full, members = execution.warm_targets(axis, assets, confirmation=2)
        cut = axis.index("2021-01-15")
        prefix_assets = {s: pit.Asset(s, a.symbol, 0, a.closes[:cut + 1], a.quote[:cut + 1])
                         for s, a in assets.items()}
        prefix, prefix_members = execution.warm_targets(pit.Axis(axis.dates[:cut + 1]), prefix_assets,
                                                         confirmation=2)
        self.assertEqual(prefix, {t: full[t] for t in prefix})
        self.assertEqual(prefix_members, {t: value for t, value in members.items() if t <= cut})
        self.assertNotIn(cut, prefix_members)


class OpenAccountingTests(unittest.TestCase):
    def test_fresh_cash_does_not_own_signal_close_to_first_open_gap(self):
        axis, assets, opens = fixture()
        t = axis.index("2021-01-01")
        replace_close(assets, "ETHUSDT", t - 1, 100.0)
        opens["ETHUSDT"][axis.dates[t]] = 200.0
        replace_close(assets, "ETHUSDT", t, 220.0)
        run = execution.replay_crypto_open(axis, assets, opens, {t - 1: {"ETHUSDT": 0.5}},
                                           start=axis.dates[t], cost_bps=0.0)
        first = run["records"][0]
        self.assertAlmostEqual(first["return"], 0.05)
        self.assertEqual(first["overnight_factor"], 1.0)
        self.assertEqual(first["signal_date"], axis.dates[t - 1])

    def test_existing_position_owns_overnight_before_open_exit(self):
        axis, assets, opens = fixture()
        t = axis.index("2021-01-01")
        opens["ETHUSDT"][axis.dates[t]] = 100.0
        replace_close(assets, "ETHUSDT", t, 100.0)
        opens["ETHUSDT"][axis.dates[t + 1]] = 200.0
        targets = {t - 1: {"ETHUSDT": 0.5}, t: {}}
        records = execution.replay_crypto_open(axis, assets, opens, targets, start=axis.dates[t],
                                               cost_bps=0.0)["records"]
        self.assertAlmostEqual(records[1]["return"], 0.5)
        self.assertEqual(records[1]["weights"], {})
        self.assertAlmostEqual(records[1]["pretrade_weights"]["ETHUSDT"], 2.0 / 3.0)

    def test_delay_uses_older_completed_target_on_same_calendar(self):
        axis, assets, opens = fixture()
        t = axis.index("2021-01-01")
        targets = {t - 2: {"ETHUSDT": 0.25}, t - 1: {"ETHUSDT": 0.5}}
        base = execution.replay_crypto_open(axis, assets, opens, targets, cost_bps=0.0)
        delayed = execution.replay_crypto_open(axis, assets, opens, targets, cost_bps=0.0, delay=1)
        self.assertEqual([r["date"] for r in base["records"]], [r["date"] for r in delayed["records"]])
        self.assertEqual(delayed["records"][0]["signal_date"], axis.dates[t - 2])
        self.assertEqual(base["records"][0]["weights"], {"ETHUSDT": 0.5})
        self.assertEqual(delayed["records"][0]["weights"], {"ETHUSDT": 0.25})

    def test_stale_filter_uses_yesterday_close_and_ignores_open_for_decision(self):
        axis, assets, opens = fixture()
        t = axis.index("2021-01-01")
        replace_close(assets, "ETHUSDT", t - 1, 1.0)
        opens["ETHUSDT"][axis.dates[t]] = 1000.0  # Strong open cannot revive the closed-bar intent.
        targets = {t - 2: {"ETHUSDT": 0.5}}
        record = execution.replay_crypto_open(axis, assets, opens, targets, cost_bps=25.0,
                                              delay=1, cancel_stale=True)["records"][0]
        self.assertEqual(record["weights"], {})
        self.assertEqual(record["canceled_buys"], {"ETHUSDT": 0.5})
        self.assertEqual(record["cost_fraction"], 0.0)
        self.assertEqual(record["validation_date"], axis.dates[t - 1])

    def test_low_execution_open_does_not_supply_a_new_gate(self):
        axis, assets, opens = fixture()
        t = axis.index("2021-01-01")
        opens["ETHUSDT"][axis.dates[t]] = 1.0
        targets = {t - 2: {"ETHUSDT": 0.5}}
        record = execution.replay_crypto_open(axis, assets, opens, targets, cost_bps=0.0,
                                              delay=1, cancel_stale=True)["records"][0]
        self.assertEqual(record["weights"], {"ETHUSDT": 0.5})
        self.assertEqual(record["canceled_buys"], {})

    def test_filter_retains_old_position_but_does_not_increase_it(self):
        axis, assets, opens = fixture()
        t = axis.index("2021-01-01")
        # First entry valid; the next closed bar invalidates the later increase.
        opens["ETHUSDT"][axis.dates[t]] = 100.0
        replace_close(assets, "ETHUSDT", t, 100.0)
        opens["ETHUSDT"][axis.dates[t + 1]] = 100.0
        targets = {t - 2: {"ETHUSDT": 0.25}, t - 1: {"ETHUSDT": 0.75}}
        records = execution.replay_crypto_open(axis, assets, opens, targets, cost_bps=0.0,
                                               delay=1, cancel_stale=True)["records"]
        self.assertEqual(records[0]["weights"], {"ETHUSDT": 0.25})
        self.assertEqual(records[1]["weights"], {"ETHUSDT": 0.25})
        self.assertEqual(records[1]["canceled_buys"], {"ETHUSDT": 0.5})
        self.assertEqual(records[1]["turnover"], 0.0)

    def test_requested_sale_target_is_unchanged_when_latest_gate_fails(self):
        axis, assets, opens = fixture()
        t = axis.index("2021-01-01")
        opens["ETHUSDT"][axis.dates[t]] = 100.0
        replace_close(assets, "ETHUSDT", t, 100.0)
        opens["ETHUSDT"][axis.dates[t + 1]] = 100.0
        targets = {t - 2: {"ETHUSDT": 0.5}, t - 1: {"ETHUSDT": 0.1}}
        records = execution.replay_crypto_open(axis, assets, opens, targets, cost_bps=25.0,
                                               delay=1, cancel_stale=True)["records"]
        self.assertEqual(records[1]["weights"], {"ETHUSDT": 0.1})
        self.assertEqual(records[1]["canceled_buys"], {})
        self.assertLess(records[1]["nominal_trades"]["ETHUSDT"], 0.0)

    def test_paxg_stale_validation_ignores_btc_gate(self):
        axis, assets, opens = fixture()
        t = axis.index("2021-01-01")
        replace_close(assets, "BTCUSDT", t - 1, 1.0)
        targets = {t - 2: {"PAXGUSDT": 0.5, "ETHUSDT": 0.5}}
        record = execution.replay_crypto_open(axis, assets, opens, targets, cost_bps=0.0,
                                              delay=1, cancel_stale=True)["records"][0]
        self.assertEqual(record["weights"], {"PAXGUSDT": 0.5})
        self.assertEqual(record["canceled_buys"], {"ETHUSDT": 0.5})

    def test_no_delay_filter_is_exact_noop(self):
        axis, assets, opens = fixture()
        t = axis.index("2021-01-01")
        replace_close(assets, "ETHUSDT", t - 1, 1.0)
        targets = {t - 1: {"ETHUSDT": 0.5}}
        left = execution.replay_crypto_open(axis, assets, opens, targets, cost_bps=50.0)
        right = execution.replay_crypto_open(axis, assets, opens, targets, cost_bps=50.0, cancel_stale=True)
        self.assertEqual(left, right)

    def test_missing_open_new_position_is_not_filled(self):
        axis, assets, opens = fixture()
        t = axis.index("2021-01-01")
        del opens["ETHUSDT"][axis.dates[t]]
        record = execution.replay_crypto_open(axis, assets, opens, {t - 1: {"ETHUSDT": 0.5}},
                                              cost_bps=25.0)["records"][0]
        self.assertEqual(record["weights"], {})
        self.assertEqual(record["no_fills"], ["ETHUSDT"])
        self.assertEqual(record["return"], 0.0)

    def test_held_missing_open_is_written_off_without_invented_sale(self):
        axis, assets, opens = fixture()
        t = axis.index("2021-01-01")
        opens["ETHUSDT"][axis.dates[t]] = 100.0
        replace_close(assets, "ETHUSDT", t, 100.0)
        del opens["ETHUSDT"][axis.dates[t + 1]]
        records = execution.replay_crypto_open(axis, assets, opens,
                                               {t - 1: {"ETHUSDT": 0.5}, t: {}},
                                               cost_bps=0.0)["records"]
        self.assertAlmostEqual(records[1]["return"], -0.5)
        self.assertEqual(records[1]["missing_marks"], ["ETHUSDT"])
        self.assertEqual(records[1]["turnover"], 0.0)

    def test_close_missing_after_valid_open_is_not_used_to_cancel_fill(self):
        axis, assets, opens = fixture()
        t = axis.index("2021-01-01")
        asset = assets["ETHUSDT"]
        assets["ETHUSDT"] = pit.Asset(asset.asset_id, asset.symbol, 0, asset.closes[:t], asset.quote[:t])
        record = execution.replay_crypto_open(axis, assets, opens, {t - 1: {"ETHUSDT": 0.5}},
                                              cost_bps=0.0)["records"][0]
        self.assertEqual(record["weights"], {"ETHUSDT": 0.5})
        self.assertEqual(record["intraday_missing_marks"], ["ETHUSDT"])
        self.assertAlmostEqual(record["return"], -0.5)

    def test_future_prices_do_not_change_previous_records(self):
        axis, assets, opens = fixture()
        targets, _ = execution.warm_targets(axis, assets)
        full = execution.replay_crypto_open(axis, assets, opens, targets, cost_bps=25.0,
                                            delay=1, cancel_stale=True)
        cut = axis.index("2021-01-15")
        prefix_axis = pit.Axis(axis.dates[:cut + 1])
        prefix_assets = {s: pit.Asset(s, a.symbol, 0, a.closes[:cut + 1], a.quote[:cut + 1])
                         for s, a in assets.items()}
        prefix_opens = {s: {d: p for d, p in values.items() if d <= axis.dates[cut]}
                        for s, values in opens.items()}
        prefix = execution.replay_crypto_open(prefix_axis, prefix_assets, prefix_opens, targets,
                                              cost_bps=25.0, delay=1, cancel_stale=True)
        self.assertEqual(prefix["records"], full["records"][:len(prefix["records"])])


class FeeTests(unittest.TestCase):
    def test_purchase_rotation_and_sale_are_self_financing(self):
        for pre, target in (({}, {"A": 1.0}), ({"A": 1.0}, {"B": 1.0}), ({"A": 0.5}, {})):
            fee = execution.solve_cost(pre, target, 100.0)
            self.assertAlmostEqual(fee["cost_fraction"], 0.01 * sum(abs(v) for v in fee["nominal_trades"].values()))
            ending_assets = sum((1.0 - fee["cost_fraction"]) * w for w in target.values())
            self.assertAlmostEqual(ending_assets + fee["post_fee_cash"] + fee["cost_fraction"], 1.0)
            self.assertAlmostEqual(fee["fee_residual"], 0.0)
        self.assertAlmostEqual(execution.solve_cost({}, {"A": 1.0}, 100.0)["cost_fraction"], 0.01 / 1.01)
        self.assertAlmostEqual(execution.solve_cost({"A": 1.0}, {"B": 1.0}, 100.0)["cost_fraction"], 0.02 / 1.01)

    def test_zero_trade_has_no_fee_and_legacy_fee_is_explicit(self):
        fee = execution.solve_cost({"A": 0.5}, {"A": 0.5}, 25.0)
        self.assertAlmostEqual(fee["turnover"], 0.0)
        self.assertAlmostEqual(fee["cost_fraction"], 0.0)
        legacy = execution.solve_cost({}, {"A": 1.0}, 100.0, exact=False)
        self.assertAlmostEqual(legacy["cost_fraction"], 0.01)
        self.assertNotEqual(legacy["fee_residual"], 0.0)


class ArchiveTests(unittest.TestCase):
    @staticmethod
    def archive(day="2021-01-01"):
        stamp = int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
        data = f"{stamp},100,110,90,105,3,{stamp + 86399999},315,1,1,1,0\n"
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("BTCUSDT-1d-2021-01.csv", data)
        return buffer.getvalue()

    def test_archive_hash_and_original_rows_bind_new_opens(self):
        raw = self.archive()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cache = root / "cache"
            cache.mkdir()
            original = {"rows": {"2021-01-01": [105.0, 315.0]},
                        "files": {"2021-01": hashlib.sha256(raw).hexdigest()}}
            (cache / "BTCUSDT.json").write_text(json.dumps(original))
            out = root / "new"
            with patch.object(execution, "_check_acquisition_storage"), patch.object(execution, "_get_archive", return_value=raw):
                manifest = execution.acquire_opens(cache, out, symbols=["BTCUSDT"], workers=1)
            self.assertEqual(json.loads((out / "opens.json").read_text()), {"BTCUSDT": {"2021-01-01": 100.0}})
            self.assertEqual(manifest["files"]["archives/BTCUSDT-1d-2021-01.zip"], hashlib.sha256(raw).hexdigest())
            self.assertTrue((out / "manifest.json").is_file())

    def test_archive_revision_or_row_mismatch_never_publishes_manifest(self):
        raw = self.archive()
        for digest, close, expected_error in (("0" * 64, 105.0, "hash_mismatch"),
                                               (hashlib.sha256(raw).hexdigest(), 104.0, "row_mismatch")):
            with self.subTest(expected_error=expected_error), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                cache = root / "cache"
                cache.mkdir()
                (cache / "BTCUSDT.json").write_text(json.dumps({"rows": {"2021-01-01": [close, 315.0]},
                                                                "files": {"2021-01": digest}}))
                out = root / "new"
                with patch.object(execution, "_check_acquisition_storage"), patch.object(execution, "_get_archive", return_value=raw):
                    with self.assertRaisesRegex(execution.C60ExecutionError, expected_error):
                        execution.acquire_opens(cache, out, symbols=["BTCUSDT"], workers=1)
                self.assertFalse((out / "manifest.json").exists())

    def test_sparse_request_retains_valid_extra_archive_and_its_opens(self):
        january, february = self.archive(), self.archive("2021-02-01")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cache = root / "cache"
            cache.mkdir()
            (cache / "BTCUSDT.json").write_text(json.dumps({
                "rows": {"2021-01-01": [105.0, 315.0], "2021-02-01": [105.0, 315.0]},
                "files": {"2021-01": hashlib.sha256(january).hexdigest(),
                          "2021-02": hashlib.sha256(february).hexdigest()}}))
            out = root / "partial"
            (out / "archives").mkdir(parents=True)
            retained = out / "archives/BTCUSDT-1d-2021-01.zip"
            retained.write_bytes(january)
            with patch.object(execution, "_check_acquisition_storage"), patch.object(execution, "_get_archive", return_value=february) as getter:
                manifest = execution.acquire_opens(cache, out, months_by_symbol={"BTCUSDT": ["2021-02"]}, workers=1)
            self.assertEqual(getter.call_count, 1)
            self.assertTrue(getter.call_args.args[0].endswith("2021-02.zip"))
            self.assertEqual(retained.read_bytes(), january)
            self.assertEqual(manifest["archive_count"], 2)
            self.assertEqual(manifest["requested_archive_count"], 1)
            self.assertEqual(manifest["requested_months"], {"BTCUSDT": ["2021-02"]})
            self.assertEqual(json.loads((out / "opens.json").read_text()),
                             {"BTCUSDT": {"2021-01-01": 100.0, "2021-02-01": 100.0}})

    def test_valid_requested_partial_archive_reuses_without_network(self):
        raw = self.archive()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cache = root / "cache"
            cache.mkdir()
            (cache / "BTCUSDT.json").write_text(json.dumps({"rows": {"2021-01-01": [105.0, 315.0]},
                                                            "files": {"2021-01": hashlib.sha256(raw).hexdigest()}}))
            out = root / "partial"
            (out / "archives").mkdir(parents=True)
            (out / "archives/BTCUSDT-1d-2021-01.zip").write_bytes(raw)
            with patch.object(execution, "_check_acquisition_storage"), patch.object(execution, "_get_archive", side_effect=AssertionError("no download")):
                manifest = execution.acquire_opens(cache, out, months_by_symbol={"BTCUSDT": ["2021-01"]}, workers=1)
            self.assertEqual(manifest["reused_requested_archive_count"], 1)
            self.assertEqual(manifest["downloaded_archive_count"], 0)
            with patch.object(execution, "_check_acquisition_storage"):
                with self.assertRaisesRegex(execution.C60ExecutionError, "completed_acquisition_is_immutable"):
                    execution.acquire_opens(cache, out, months_by_symbol={"BTCUSDT": ["2021-01"]})

    def test_corrupted_surplus_archive_prevents_resume_without_overwrite(self):
        raw = self.archive()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cache = root / "cache"
            cache.mkdir()
            (cache / "BTCUSDT.json").write_text(json.dumps({"rows": {"2021-01-01": [105.0, 315.0]},
                                                            "files": {"2021-01": hashlib.sha256(raw).hexdigest()}}))
            out = root / "partial"
            (out / "archives").mkdir(parents=True)
            path = out / "archives/BTCUSDT-1d-2021-01.zip"
            path.write_bytes(b"corrupt")
            with patch.object(execution, "_check_acquisition_storage"), patch.object(execution, "_get_archive", side_effect=AssertionError("no download")):
                with self.assertRaisesRegex(execution.C60ExecutionError, "original_archive_hash_mismatch"):
                    execution.acquire_opens(cache, out, months_by_symbol={"BTCUSDT": ["2021-01"]})
            self.assertEqual(path.read_bytes(), b"corrupt")
            self.assertFalse((out / "manifest.json").exists())

    def test_surplus_symbol_has_complete_archive_and_open_lineage(self):
        raw = self.archive()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cache = root / "cache"
            cache.mkdir()
            for symbol in ("BTCUSDT", "ETHUSDT"):
                (cache / (symbol + ".json")).write_text(json.dumps({
                    "rows": {"2021-01-01": [105.0, 315.0]},
                    "files": {"2021-01": hashlib.sha256(raw).hexdigest()}}))
            out = root / "partial"
            (out / "archives").mkdir(parents=True)
            (out / "archives/ETHUSDT-1d-2021-01.zip").write_bytes(raw)
            with patch.object(execution, "_check_acquisition_storage"), patch.object(execution, "_get_archive", return_value=raw):
                manifest = execution.acquire_opens(cache, out, months_by_symbol={"BTCUSDT": ["2021-01"]}, workers=1)
            self.assertEqual(manifest["archive_symbols"], ["BTCUSDT", "ETHUSDT"])
            self.assertEqual(manifest["symbols"], ["BTCUSDT", "ETHUSDT"])
            self.assertEqual(manifest["requested_symbols"], ["BTCUSDT"])
            self.assertEqual(set(manifest["cache_sha256"]), {"BTCUSDT.json", "ETHUSDT.json"})
            self.assertEqual(set(json.loads((out / "opens.json").read_text())), {"BTCUSDT", "ETHUSDT"})


if __name__ == "__main__":
    unittest.main()
