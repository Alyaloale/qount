import copy
import datetime as dt
import hashlib
import io
import json
import math
import tempfile
import unittest
import zipfile
from pathlib import Path

from qount.research.dual_engine_optimization import EquityPanel
from qount.research.g20_drift_control import replay_equity_control
from qount.research.dual_engine_execution_verify import (
    ExecutionVerificationError, crypto_prices, equity_prices, independent_metrics,
    _required_open_months, _verify_archive_bridge,
    verify_bound_files, verify_ledger, verify_manifest,
)


def panel_fixture():
    dates = ("2021-01-28", "2021-01-29", "2021-02-01", "2021-02-02", "2021-02-03")
    opens = {"BIL": (100., 100., 100.1, 100.2, 100.3),
             "TQQQ": (100., 100., 105., 120., 90.),
             "TMF": (100., 100., 102., 99., 102.)}
    closes = {"BIL": (100., 100.1, 100.2, 100.3, 100.4),
              "TQQQ": (100., 100., 110., 115., 95.),
              "TMF": (100., 100., 101., 103., 99.)}
    return EquityPanel(dates, closes, closes, opens)


def equity_run(*, exact=True):
    panel = panel_fixture()
    signals = {1: {"signal_date": panel.dates[1], "selected": "TQQQ", "target": {"BIL": .8, "TQQQ": .2}},
               3: {"signal_date": panel.dates[3], "selected": "TMF", "target": {"BIL": .8, "TMF": .2}}}
    result = replay_equity_control(panel, signals, start=panel.dates[1], cost_bps=40,
                                   delay=1, reduce_only=True, exact_fees=exact)
    return result, equity_prices(panel)


class CashUnitOracleTests(unittest.TestCase):
    def test_c60_open_accounts_have_independent_units_and_cash_oracle(self):
        from qount.research.c60_execution_control import replay_crypto_open, warm_targets
        from qount.research.c60_pit_universe import Axis, Asset
        first = dt.date(2020, 8, 1)
        dates = tuple((first + dt.timedelta(days=i)).isoformat() for i in range(180))
        assets = {s: Asset(s, s, 0, tuple(100. + i * speed for i in range(180)), (1e6,) * 180)
                  for s, speed in (("BTCUSDT", .1), ("ETHUSDT", .2), ("PAXGUSDT", .15))}
        axis = Axis(dates)
        opens = {s: {d: a.closes[i] * 1.001 for i, d in enumerate(dates)} for s, a in assets.items()}
        targets, _ = warm_targets(axis, assets)
        run = replay_crypto_open(axis, assets, opens, targets, start="2021-01-01", cost_bps=50,
                                 delay=1, cancel_stale=True)
        check = verify_ledger(run, crypto_prices(axis, assets, opens), 365, cost_bps=50)
        self.assertTrue(check["verified"])
        self.assertAlmostEqual(check["final_nav"], math.prod(1 + r["return"] for r in run["records"]))

    def test_independent_cash_units_reproduce_gap_intraday_rotation_and_cost(self):
        run, prices = equity_run()
        result = verify_ledger(run, prices, 252, cost_bps=40)
        self.assertTrue(result["verified"])
        nav = math.prod(1 + r["return"] for r in run["records"])
        self.assertAlmostEqual(result["final_nav"], nav)
        self.assertAlmostEqual(result["total_return"], nav - 1)
        self.assertLess(result["max_identity_errors"]["return"], 1e-12)
        self.assertLess(result["max_actual_fee_residual"], 1e-12)

    def test_tampered_daily_return_is_detected_independently(self):
        run, prices = equity_run()
        run["records"][1]["return"] += .0001
        with self.assertRaisesRegex(ExecutionVerificationError, "identity_mismatch:return"):
            verify_ledger(run, prices, 252, cost_bps=40)

    def test_tampered_weight_and_tampered_fee_fail_separately(self):
        original, prices = equity_run()
        run = copy.deepcopy(original)
        run["records"][2]["pre_trade_weights"]["BIL"] -= .001
        with self.assertRaisesRegex(ExecutionVerificationError, "identity_mismatch:pretrade_weights"):
            verify_ledger(run, prices, 252, cost_bps=40)
        run = copy.deepcopy(original)
        run["records"][1]["turnover"] += .001
        with self.assertRaisesRegex(ExecutionVerificationError, "identity_mismatch:turnover"):
            verify_ledger(run, prices, 252, cost_bps=40)

    def test_mark_price_tampering_does_not_pass_using_reported_weights(self):
        run, prices = equity_run()
        prices["closes"]["TQQQ"]["2021-02-01"] *= 1.01
        with self.assertRaisesRegex(ExecutionVerificationError, "identity_mismatch"):
            verify_ledger(run, prices, 252, cost_bps=40)

    def test_approximate_fee_is_labelled_and_actual_notional_error_reported(self):
        run, prices = equity_run(exact=False)
        result = verify_ledger(run, prices, 252, cost_bps=40)
        self.assertTrue(result["verified"])
        self.assertGreater(result["max_actual_fee_residual"], 0)
        run["fee_model"] = "exact_self_financing"
        with self.assertRaisesRegex(ExecutionVerificationError, "identity_mismatch:turnover"):
            verify_ledger(run, prices, 252, cost_bps=40)

    def test_handwritten_partial_cash_account_and_missing_mark_writeoff(self):
        # One unit of A worth .5, with .5 cash. On the next open its entire
        # mark disappears and units are removed; a later quote cannot revive it.
        dates = ("2021-01-01", "2021-01-02", "2021-01-03")
        prices = {"dates": dates, "opens": {"A": {dates[0]: .5, dates[2]: 2.}},
                  "closes": {"A": {dates[0]: .5, dates[2]: 2.}}, "cash_asset": None}
        rows = [
            {"date": dates[0], "return": 0., "cash_return": 0., "turnover": .5, "cost_fraction": 0.,
             "pretrade_weights": {}, "weights": {"A": .5}, "close_weights": {"A": .5},
             "missing_marks": [], "writeoff_weight": 0.},
            {"date": dates[1], "return": -.5, "cash_return": 0., "turnover": 0., "cost_fraction": 0.,
             "pretrade_weights": {}, "weights": {}, "close_weights": {},
             "overnight_missing_marks": ["A"], "intraday_missing_marks": [],
             "missing_marks": ["A"], "writeoff_weight": .5},
            {"date": dates[2], "return": 0., "cash_return": 0., "turnover": 0., "cost_fraction": 0.,
             "pretrade_weights": {}, "weights": {}, "close_weights": {},
             "missing_marks": [], "writeoff_weight": 0.},
        ]
        result = verify_ledger({"records": rows}, prices, 365, cost_bps=0.)
        self.assertEqual(result["final_nav"], .5)
        self.assertEqual(result["max_drawdown"], -.5)
        self.assertAlmostEqual(result["annual_turnover"], .5 * 365 / 3)

    def test_first_fresh_cash_row_cannot_earn_previous_overnight_gap(self):
        prices = {"dates": ("2020-12-31", "2021-01-01"),
                  "opens": {"A": {"2021-01-01": 200.}},
                  "closes": {"A": {"2020-12-31": 100., "2021-01-01": 200.}},
                  "cash_asset": None}
        row = {"date": "2021-01-01", "return": 0., "cash_return": 0., "turnover": 1.,
               "cost_fraction": 0., "pretrade_weights": {}, "weights": {"A": 1.},
               "close_weights": {"A": 1.}}
        result = verify_ledger({"records": [row]}, prices, 365, cost_bps=0)
        self.assertEqual(result["final_nav"], 1.)
        row["return"] = 1.
        with self.assertRaisesRegex(ExecutionVerificationError, "identity_mismatch:return"):
            verify_ledger({"records": [row]}, prices, 365, cost_bps=0)

    def test_unknown_date_and_skipped_axis_day_fail(self):
        run, prices = equity_run()
        del run["records"][1]
        with self.assertRaisesRegex(ExecutionVerificationError, "ledger_axis_gap_or_unknown"):
            verify_ledger(run, prices, 252, cost_bps=40)

    def test_metrics_include_initial_loss_and_cash_excess(self):
        values = (-.01, .02, -.03, .04)
        result = independent_metrics(values, 252, (.001,) * 4)
        self.assertAlmostEqual(result["total_return"], math.prod(1 + r for r in values) - 1)
        self.assertAlmostEqual(result["max_drawdown"], -.03)
        self.assertNotEqual(result["cash_excess_sharpe"], result["sharpe"])


class ArtifactIntegrityTests(unittest.TestCase):
    def test_sparse_bridge_checks_requested_and_surplus_zips_and_every_open(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "archives").mkdir()
            rows, opens, files = {}, {}, {}
            for month, day in (("2025-01", "2025-01-01"), ("2025-02", "2025-02-01")):
                # Explicit microsecond timestamps exercise an independent parser.
                stamp = int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.timezone.utc).timestamp()) * 1_000_000
                stream = io.BytesIO()
                with zipfile.ZipFile(stream, "w") as archive:
                    archive.writestr("bars.csv", f"{stamp},9,11,8,10,1,0,100\n")
                name = f"archives/BTCUSDT-1d-{month}.zip"
                (root / name).write_bytes(stream.getvalue())
                files[name] = hashlib.sha256(stream.getvalue()).hexdigest()
                rows[day], opens[day] = [10., 100.], 9.
            (root / "opens.json").write_text(json.dumps({"BTCUSDT": opens}))
            cache = {"BTCUSDT": {"rows": rows, "files": {name[-11:-4]: h for name, h in files.items()}}}
            manifest = {"symbols": ["BTCUSDT"], "archive_symbols": ["BTCUSDT"],
                        "requested_months": {"BTCUSDT": ["2025-01"]}, "files": files | {"opens.json": "unused"}}
            result = _verify_archive_bridge(root, cache, manifest, needed_months={"BTCUSDT": ["2025-01"]})
            self.assertEqual(result["archives"], 2)
            self.assertEqual(result["requested_archives"], 1)
            self.assertEqual(result["rows"], 2)
            # A valid surplus ZIP must also have all its opens preserved.
            del opens["2025-02-01"]
            (root / "opens.json").write_text(json.dumps({"BTCUSDT": opens}))
            with self.assertRaisesRegex(ExecutionVerificationError, "archive_bridge_open_value_or_calendar_mismatch"):
                _verify_archive_bridge(root, cache, manifest)

    def test_required_months_include_delayed_first_entry_and_next_day_mark(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dates = ("2020-12-30", "2020-12-31", "2021-01-01", "2021-01-02", "2021-01-03")
            for rule in ("pit", "confirmation", "btc_daily", "btc_monthly"):
                weights = {"ETHUSDT@2020-01-01": .5} if rule == "pit" else {}
                (root / f"c60-{rule}-warm-targets.json").write_text(json.dumps({"0": weights}))
            prices = {"dates": dates, "closes": {"ETHUSDT@2020-01-01": {}}}
            cache = {"ETHUSDT": {"files": {"2021-01": "hash"}}, "BTCUSDT": {"files": {"2021-01": "hash"}}}
            contract = {"c60": {"start": "2021-01-01", "end": "2021-01-03", "delays": [0, 1]}}
            required = _required_open_months(root, prices, cache, contract)
            self.assertEqual(required, {"BTCUSDT": ["2021-01"], "ETHUSDT": ["2021-01"]})

    def test_manifest_checks_exact_fileset_and_content(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "curve.json").write_text('{"value": 1}\n')
            digest = hashlib.sha256((root / "curve.json").read_bytes()).hexdigest()
            (root / "manifest.json").write_text(json.dumps({"files": {"curve.json": digest}}))
            self.assertTrue(verify_manifest(root)["verified"])
            (root / "undeclared.json").write_text("extra")
            with self.assertRaisesRegex(ExecutionVerificationError, "manifest_fileset_mismatch"):
                verify_manifest(root)
            (root / "undeclared.json").unlink()
            (root / "curve.json").write_text("modified")
            with self.assertRaisesRegex(ExecutionVerificationError, "manifest_hash_mismatch"):
                verify_manifest(root)

    def test_manifest_cannot_escape_root_or_follow_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "real").write_text("data")
            digest = hashlib.sha256(b"data").hexdigest()
            (root / "linked").symlink_to(root / "real")
            for name in ("../elsewhere", "linked", str(root / "real")):
                with self.assertRaisesRegex(ExecutionVerificationError, "manifest_path_invalid_or_missing"):
                    verify_bound_files(root, {name: digest})


if __name__ == "__main__":
    unittest.main()
