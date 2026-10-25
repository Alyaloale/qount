from dataclasses import replace
from datetime import date, timedelta
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("g20_review", ROOT / "scripts/research/analyze_g20_risk_budget.py")
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def fixture():
    days = [date(2020, 1, 1) + timedelta(days=i) for i in range(500)]
    dates = tuple(d.isoformat() for d in days if d.weekday() < 5)
    raw, total, opens = {}, {}, {}
    for s in {*review.G20_EXECUTION_TO_PROXY, *review.G20_EXECUTION_TO_PROXY.values(), "BIL"}:
        raw[s] = tuple(100 * (1.002 if s == "QQQ" else 1.001) ** i for i in range(len(dates)))
        if s in review.G20_EXECUTION_TO_PROXY:
            values = [100.0]
            for i in range(1, len(dates)):
                values.append(values[-1] * (1.10 if i % 2 else .91))
            total[s] = tuple(values)
        else:
            total[s] = tuple(100 * (1.003 if s == "XLV" else 1.002 if s == "QQQ" else 1.0001) ** i
                             for i in range(len(dates)))
        opens[s] = total[s]
    return review.EquityPanel(dates, raw, total, opens)


class G20RiskSynthesisTests(unittest.TestCase):
    def test_adjusted_selector_matches_production_basis(self):
        p = fixture()
        raw, adjusted = review.monthly_signals(p, basis="raw"), review.monthly_signals(p)
        self.assertTrue(raw)
        for i in raw:
            self.assertEqual(raw[i]["selected"], "TQQQ")
            self.assertEqual(adjusted[i]["selected"], "CURE")

    def test_risk_cap_never_expands_twenty_percent_budget(self):
        p = fixture()
        cap, control = review.targets(p, "weekly_cap15"), review.targets(p, "weekly20")
        self.assertEqual(set(cap), set(control))
        for i, target in cap.items():
            self.assertAlmostEqual(sum(target.values()), 1)
            self.assertGreater(target["CURE"], 0)
            self.assertLess(target["CURE"], .2)
            self.assertEqual(control[i], {"CURE": .2, "BIL": .8})

    def test_future_prices_do_not_change_prior_orders_or_nav(self):
        p = fixture()
        cut = 220
        changed = replace(p, total_closes={s:v[:cut] + tuple(x * 5 for x in v[cut:]) for s,v in p.total_closes.items()},
                          closes={s:v[:cut] + tuple(x * 5 for x in v[cut:]) for s,v in p.closes.items()},
                          total_opens={s:v[:cut] + tuple(x * 5 for x in v[cut:]) for s,v in p.total_opens.items()})
        runs = []
        for panel in (p, changed):
            closes, opens = review.prices(panel)
            runs.append(review.replay_units(panel.dates, closes, opens, review.targets(panel, "weekly_cap15"),
                                           start=panel.dates[100], lag=1, cost_bps=20, cash_asset="BIL"))
        self.assertEqual([r for r in runs[0]["records"] if r["date"] < p.dates[cut]],
                         [r for r in runs[1]["records"] if r["date"] < p.dates[cut]])

    def test_equal_capital_combination_preserves_identical_book(self):
        p = fixture()
        closes, opens = review.prices(p)
        run = review.replay_units(p.dates, closes, opens, review.targets(p, "weekly_cap15"),
                                 start=p.dates[100], lag=1, cost_bps=20, cash_asset="BIL")
        mix = review.equal_capital_combination(run["records"], run["records"])
        self.assertEqual([r["nav"] for r in mix["nav"]], [r["nav"] for r in run["records"]])
        self.assertAlmostEqual(mix["metrics"]["total_return"], run["records"][-1]["nav"] - 1)
        self.assertAlmostEqual(mix["final_left_capital_fraction"], .5)
        with self.assertRaises(ValueError):
            review.equal_capital_combination(run["records"], run["records"][1:])


if __name__ == "__main__":
    unittest.main()
