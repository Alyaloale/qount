import math
import unittest

from qount.research.dual_engine_optimization import EquityPanel, OptimizationStudyError, replay_equity
from qount.research.g20_drift_control import replay_equity_control


def panel_fixture():
    dates = ("2020-01-29", "2020-01-30", "2020-01-31", "2020-02-03", "2020-02-04",
             "2020-02-05", "2020-02-06", "2020-02-07", "2020-02-10", "2020-02-11")
    prices = {symbol: (100.0,) * len(dates) for symbol in ("TQQQ", "SOXL", "BIL", "SPY")}
    return EquityPanel(dates, dict(prices), dict(prices), dict(prices))


def signal(panel, index, symbol="TQQQ"):
    return {"signal_date": panel.dates[index], "selected": symbol,
            "target": {"BIL": 0.8, symbol: 0.2}}


def run(panel, signals, **kwargs):
    settings = {"start": panel.dates[2], "cost_bps": 0.0, "delay": 1}
    return replay_equity_control(panel, signals, **(settings | kwargs))


class DriftControlTests(unittest.TestCase):
    def test_next_open_assigns_gap_to_old_holding(self):
        panel = panel_fixture()
        panel.total_closes["TQQQ"] = (100., 100., 100., 200., 100., 100., 100., 100., 100., 100.)
        panel.total_opens["TQQQ"] = panel.total_closes["TQQQ"]
        early = run(panel, {2: signal(panel, 2)})["records"]
        late = run(panel, {2: signal(panel, 2)}, delay=2)["records"]
        self.assertAlmostEqual(early[1]["return"], 0.0)
        self.assertAlmostEqual(early[2]["return"], -0.1)
        self.assertAlmostEqual(late[2]["return"], 0.0)

    def test_original_monthly_drift_is_preserved_without_control(self):
        panel = panel_fixture()
        panel.total_closes["TQQQ"] = (100., 100., 100., 200., 200., 200., 200., 200., 200., 200.)
        rows = run(panel, {2: signal(panel, 2)})["records"]
        self.assertAlmostEqual(rows[1]["risk_exposure_post_open"], 0.2)
        self.assertAlmostEqual(rows[1]["risk_exposure_close"], 1 / 3)
        self.assertAlmostEqual(rows[2]["risk_exposure_close"], 1 / 3)
        self.assertEqual(rows[2]["turnover"], 0.0)

    def test_reduce_is_generated_after_close_and_never_sells_early(self):
        panel = panel_fixture()
        panel.total_closes["TQQQ"] = (100., 100., 100., 200., 200., 200., 200., 200., 200., 200.)
        panel.total_opens["TQQQ"] = (100., 100., 100., 100., 200., 200., 200., 200., 200., 200.)
        result = run(panel, {2: signal(panel, 2)}, reduce_only=True)
        rows = result["records"]
        self.assertAlmostEqual(rows[1]["return"], 0.2)
        self.assertAlmostEqual(rows[1]["risk_exposure_close"], 1 / 3)
        self.assertEqual(rows[1]["reduce_intent_scheduled"]["execution_index"], 4)
        self.assertEqual(rows[2]["trade_kind"], "reduce")
        self.assertAlmostEqual(rows[2]["risk_exposure_post_open"], 0.2)
        self.assertEqual(result["reduce_events"][0]["status"], "executed")

    def test_pending_reduction_after_down_gap_does_not_buy_to_cap(self):
        panel = panel_fixture()
        panel.total_closes["TQQQ"] = (100., 100., 100., 200., 50., 50., 50., 50., 50., 50.)
        panel.total_opens["TQQQ"] = (100., 100., 100., 100., 50., 50., 50., 50., 50., 50.)
        rows = run(panel, {2: signal(panel, 2)}, reduce_only=True)["records"]
        self.assertLess(rows[2]["risk_exposure_pre_trade"], 0.2)
        self.assertEqual(rows[2]["reduce_status"], "skipped_below_cap")
        self.assertEqual(rows[2]["turnover"], 0.0)
        self.assertEqual(rows[2]["pre_trade_weights"], rows[2]["post_open_weights"])

    def test_monthly_fill_cancels_old_asset_reduction(self):
        panel = panel_fixture()
        panel.total_closes["TQQQ"] = (100., 100., 100., 200., 200., 200., 200., 200., 200., 200.)
        panel.total_opens["TQQQ"] = (100., 100., 100., 100., 200., 200., 200., 200., 200., 200.)
        signals = {2: signal(panel, 2), 3: signal(panel, 3, "SOXL")}
        result = run(panel, signals, reduce_only=True)
        row = result["records"][2]
        self.assertEqual(row["trade_kind"], "monthly")
        self.assertEqual(row["reduce_cancelled_count"], 1)
        self.assertEqual(row["reduce_status"], "monthly_cancelled")
        self.assertEqual(row["weights"], {"BIL": 0.8, "SOXL": 0.2})
        self.assertTrue(all(event["status"] != "executed" for event in result["reduce_events"]))

    def test_delay_two_duplicate_intent_rechecks_current_exposure(self):
        panel = panel_fixture()
        panel.total_closes["TQQQ"] = (100., 100., 100., 100., 200., 200., 200., 200., 200., 200.)
        panel.total_opens["TQQQ"] = (100., 100., 100., 100., 100., 200., 200., 200., 200., 200.)
        result = run(panel, {2: signal(panel, 2)}, reduce_only=True, delay=2)
        rows = result["records"]
        self.assertEqual(rows[2]["trade_kind"], "monthly")
        self.assertEqual(rows[3]["turnover"], 0.0)
        self.assertEqual(rows[4]["reduce_status"], "executed")
        self.assertEqual(rows[5]["reduce_status"], "skipped_below_cap")
        self.assertEqual(rows[5]["turnover"], 0.0)

    def test_delay_two_monthly_fill_cancels_same_day_and_future_intents(self):
        panel = panel_fixture()
        panel.total_closes["TQQQ"] = (100., 100., 100., 100., 200., 200., 200., 200., 200., 200.)
        panel.total_opens["TQQQ"] = (100., 100., 100., 100., 100., 200., 200., 200., 200., 200.)
        result = run(panel, {2: signal(panel, 2), 4: signal(panel, 4, "SOXL")},
                     reduce_only=True, delay=2)
        monthly = result["records"][4]
        self.assertEqual(monthly["trade_kind"], "monthly")
        self.assertEqual(monthly["reduce_cancelled_count"], 2)
        self.assertEqual(result["records"][5]["reduce_status"], None)
        self.assertEqual(result["records"][5]["weights"], {"BIL": 0.8, "SOXL": 0.2})

    def test_prefix_and_changed_future_marks_leave_past_records_unchanged(self):
        panel = panel_fixture()
        panel.total_closes["TQQQ"] = (100., 100., 100., 200., 210., 220., 250., 280., 320., 400.)
        panel.total_opens["TQQQ"] = (100., 100., 100., 100., 200., 210., 220., 250., 280., 320.)
        signals = {2: signal(panel, 2), 7: signal(panel, 7, "SOXL")}
        full = run(panel, signals, reduce_only=True, delay=2, cost_bps=20.)
        cut = 6
        prefix = EquityPanel(panel.dates[:cut],
                             {s: p[:cut] for s, p in panel.closes.items()},
                             {s: p[:cut] for s, p in panel.total_closes.items()},
                             {s: p[:cut] for s, p in panel.total_opens.items()})
        short = run(prefix, {k: v for k, v in signals.items() if k < cut},
                    reduce_only=True, delay=2, cost_bps=20.)
        self.assertEqual(short["records"], full["records"][:cut - 2])
        changed = EquityPanel(panel.dates, panel.closes,
                              {s: p[:cut] + (1_000.,) * (len(p) - cut) for s, p in panel.total_closes.items()},
                              {s: p[:cut] + (500.,) * (len(p) - cut) for s, p in panel.total_opens.items()})
        changed_run = run(changed, signals, reduce_only=True, delay=2, cost_bps=20.)
        self.assertEqual(short["records"], changed_run["records"][:cut - 2])

    def test_g10_and_benchmark_keep_frozen_winner_and_reference_weights(self):
        panel = panel_fixture()
        signals = {2: signal(panel, 2, "SOXL")}
        g10 = run(panel, signals, risk_weight=0.1)["records"][1]
        benchmark = run(panel, signals, benchmark=True)["records"][1]
        self.assertEqual(g10["post_open_weights"], {"BIL": 0.9, "SOXL": 0.1})
        self.assertEqual(benchmark["post_open_weights"], {"SPY": 0.6, "BIL": 0.4})


class SelfFinancingTests(unittest.TestCase):
    def test_initial_purchase_fee_is_paid_from_cash(self):
        panel = panel_fixture()
        row = run(panel, {}, cost_bps=100.)["records"][0]
        self.assertAlmostEqual(row["nav_after_fee_ratio"], 1 / 1.01)
        self.assertAlmostEqual(row["turnover"], 1 / 1.01)
        self.assertAlmostEqual(row["cost_fraction"], 0.01 / 1.01)

    def test_rotating_shares_oracle_matches_exact_fee_and_position_value(self):
        panel = panel_fixture()
        row = run(panel, {2: signal(panel, 2)}, cost_bps=100.)["records"][1]
        # Before the trade one dollar is BIL. Buy .2*x of TQQQ, sell
        # 1-.8*x of BIL, and pay 1% of their total dollar turnover.
        expected_x = (1 - 0.01) / (1 - 0.01 * 0.6)
        buy_dollars = 0.2 * expected_x
        sell_dollars = 1 - 0.8 * expected_x
        fee = 0.01 * (buy_dollars + sell_dollars)
        self.assertAlmostEqual(row["nav_after_fee_ratio"], expected_x)
        self.assertAlmostEqual(row["turnover"], buy_dollars + sell_dollars)
        self.assertAlmostEqual(row["cost_fraction"], fee)
        self.assertAlmostEqual(sell_dollars - buy_dollars, fee)
        self.assertAlmostEqual(1 - sell_dollars + buy_dollars, expected_x)
        self.assertAlmostEqual(buy_dollars / expected_x, row["post_open_weights"]["TQQQ"])

    def test_reduce_only_exact_fee_never_buys_risk_dollars(self):
        panel = panel_fixture()
        panel.total_closes["TQQQ"] = (100., 100., 100., 200., 200., 200., 200., 200., 200., 200.)
        panel.total_opens["TQQQ"] = (100., 100., 100., 100., 200., 200., 200., 200., 200., 200.)
        row = run(panel, {2: signal(panel, 2)}, reduce_only=True, cost_bps=100.)["records"][2]
        risk_before = row["pre_trade_weights"]["TQQQ"]
        bil_before = row["pre_trade_weights"]["BIL"]
        x = row["nav_after_fee_ratio"]
        self.assertLess(x * row["post_open_weights"]["TQQQ"], risk_before)
        self.assertGreater(x * row["post_open_weights"]["BIL"], bil_before)
        traded = abs(risk_before - 0.2 * x) + abs(bil_before - 0.8 * x)
        self.assertAlmostEqual(row["turnover"], traded)
        self.assertAlmostEqual(x + 0.01 * traded, 1.0)

    def test_legacy_approximation_matches_existing_ledger_keys(self):
        panel = panel_fixture()
        panel.total_closes["TQQQ"] = (100., 100., 100., 120., 125., 100., 115., 119., 130., 140.)
        panel.total_opens["TQQQ"] = (100., 100., 100., 110., 120., 105., 111., 115., 125., 130.)
        signals = {2: signal(panel, 2), 6: signal(panel, 6, "SOXL")}
        old = replay_equity(panel, signals, start=panel.dates[2], cost_bps=20., delay=2)["records"]
        new = run(panel, signals, cost_bps=20., delay=2, exact_fees=False)["records"]
        for left, right in zip(old, new, strict=True):
            for key, expected in left.items():
                if isinstance(expected, float):
                    self.assertAlmostEqual(expected, right[key], places=14)
                else:
                    self.assertEqual(expected, right[key])

    def test_adjusted_units_handle_distribution_and_split_without_extra_cash(self):
        panel = panel_fixture()
        # A synthetic distribution and two-for-one raw split leave total
        # return units intact. Raw prices are not used for the execution book.
        panel.closes["TQQQ"] = (100., 100., 100., 100., 50., 50., 50., 50., 50., 50.)
        panel.total_closes["TQQQ"] = (100., 100., 100., 100., 100., 100., 100., 100., 100., 100.)
        panel.total_opens["TQQQ"] = panel.total_closes["TQQQ"]
        panel.closes["BIL"] = (100., 100., 100., 99., 98., 98., 98., 98., 98., 98.)
        panel.total_closes["BIL"] = (100., 100., 100., 101., 102.01, 102.01, 102.01, 102.01, 102.01, 102.01)
        panel.total_opens["BIL"] = panel.total_closes["BIL"]
        rows = run(panel, {2: signal(panel, 2)})["records"]
        self.assertAlmostEqual(rows[1]["return"], 0.01)  # overnight belongs to old BIL
        self.assertAlmostEqual(rows[2]["return"], 0.008)
        self.assertAlmostEqual(rows[2]["cash_return"], 0.01)
        self.assertEqual(rows[2]["turnover"], 0.0)

    def test_invalid_settings_fail_closed(self):
        panel = panel_fixture()
        for settings in ({"delay": 0}, {"risk_weight": math.nan}, {"cost_bps": 10_000.},
                         {"reduce_only": True, "benchmark": True}):
            with self.assertRaises(OptimizationStudyError):
                run(panel, {}, **settings)


if __name__ == "__main__":
    unittest.main()
