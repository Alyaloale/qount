from dataclasses import replace
from datetime import date, timedelta
import unittest

from qount.research.etf_risk_budget import Costs, simulate, target_schedule
from qount.research.personal_trading_assistant import AssistantBar, CorporateAction, ETFAssetMeta


def fixture():
    days = [date(2020, 1, 1) + timedelta(days=i) for i in range(350)]
    days = [d for d in days if d.weekday() < 5]
    bars = []
    for i, d in enumerate(days):
        p = 10 + i * 0.03 + (0.2 if i % 2 else -0.2)
        bars.append(AssistantBar(d.strftime("%Y%m%d"), p, p * 1.02, p * .98, p * 1.001))
    meta = ETFAssetMeta("TEST", "Test", "Test", "20200101", False, 0)
    return bars, meta, bars[130].trade_date


class ETFRiskBudgetTests(unittest.TestCase):
    def test_future_prices_do_not_change_prefix(self):
        bars, meta, start = fixture()
        first = simulate(bars, meta, "vol15", start=start)
        changed = bars[:190] + [replace(b, open=b.open * 10, high=b.high * 10,
                                       low=b.low * 10, close=b.close * 10) for b in bars[190:]]
        second = simulate(changed, meta, "vol15", start=start)
        self.assertEqual(first["nav"][:60], second["nav"][:60])
        self.assertEqual([t for t in first["trades"] if t["date"] < bars[190].trade_date],
                         [t for t in second["trades"] if t["date"] < bars[190].trade_date])

    def test_close_cannot_change_same_open_order(self):
        bars, meta, start = fixture()
        first = simulate(bars, meta, "vol15", start=start)
        idx = next(i for i, b in enumerate(bars) if i > 150 and any(t["date"] == b.trade_date for t in first["trades"]))
        changed = list(bars)
        changed[idx] = replace(bars[idx], close=bars[idx].high)
        second = simulate(changed, meta, "vol15", start=start)
        self.assertEqual([t for t in first["trades"] if t["date"] == bars[idx].trade_date],
                         [t for t in second["trades"] if t["date"] == bars[idx].trade_date])

    def test_cash_units_and_equity_reconcile(self):
        bars, meta, start = fixture()
        result = simulate(bars, meta, "vol15", start=start, initial_capital=10_000)
        self.assertTrue(result["trades"])
        by_date = {b.trade_date: b for b in bars}
        for row in result["nav"]:
            self.assertGreaterEqual(row["cash"], -1e-7)
            self.assertAlmostEqual(row["equity"], row["cash"] + row["shares"] * by_date[row["date"]].close)
        for trade in result["trades"]:
            self.assertAlmostEqual(trade["quantity"] % 100, 0)
            self.assertGreaterEqual(trade["commission"], 5)
            self.assertLess(trade["decision_date"], trade["date"])

    def test_split_preserves_equity_and_decisions(self):
        bars, meta, start = fixture()
        costs = Costs(commission_bps=0, slippage_bps=0, minimum_commission=0, lot_size=0)
        reference = simulate(bars, meta, "buy_hold", start=start, costs=costs)
        idx = 180
        split = bars[:idx] + [replace(b, open=b.open / 5, high=b.high / 5, low=b.low / 5,
                                     close=b.close / 5) for b in bars[idx:]]
        split_meta = replace(meta, corporate_actions=(CorporateAction(bars[idx].trade_date, 5),))
        candidate = simulate(split, split_meta, "buy_hold", start=start, costs=costs)
        for a, b in zip(reference["nav"], candidate["nav"]):
            self.assertAlmostEqual(a["equity"], b["equity"], places=7)
        a = target_schedule(bars, meta, "vol15")
        b = target_schedule(split, split_meta, "vol15")
        for x, y in zip(a, b):
            if x is None:
                self.assertIsNone(y)
            else:
                self.assertAlmostEqual(x, y)

    def test_single_price_day_defers_and_delay_is_explicit(self):
        bars, meta, start = fixture()
        idx = 130
        bars[idx] = replace(bars[idx], high=bars[idx].open, low=bars[idx].open, close=bars[idx].open)
        result = simulate(bars, meta, "buy_hold", start=start)
        self.assertEqual(result["trades"][0]["date"], bars[idx + 1].trade_date)
        self.assertEqual(result["metrics"]["blocked_single_price_sessions"], 1)
        delayed = simulate(bars, meta, "vol15", start=start, delay=2)
        indices = {b.trade_date: i for i, b in enumerate(bars)}
        for t in delayed["trades"]:
            self.assertGreaterEqual(indices[t["date"]] - indices[t["decision_date"]], 2)

    def test_split_on_nontrading_day_is_applied_before_next_valuation(self):
        bars, meta, start = fixture()
        costs = Costs(commission_bps=0, slippage_bps=0, minimum_commission=0, lot_size=0)
        reference = simulate(bars, meta, "buy_hold", start=start, costs=costs)
        idx = next(i for i in range(170, len(bars)) if
                   (date.fromisoformat(bars[i].trade_date) - date.fromisoformat(bars[i - 1].trade_date)).days > 1)
        action_date = (date.fromisoformat(bars[idx - 1].trade_date) + timedelta(days=1)).strftime("%Y%m%d")
        split = bars[:idx] + [replace(b, open=b.open / 5, high=b.high / 5,
                                     low=b.low / 5, close=b.close / 5) for b in bars[idx:]]
        candidate = simulate(split, replace(meta, corporate_actions=(CorporateAction(action_date, 5),)),
                             "buy_hold", start=start, costs=costs)
        for a, b in zip(reference["nav"], candidate["nav"]):
            self.assertAlmostEqual(a["equity"], b["equity"], places=7)

    def test_invalid_inputs_fail(self):
        bars, meta, start = fixture()
        for kwargs in ({"delay": 0}, {"initial_capital": 0}, {"constant_weight": 2}):
            with self.assertRaises(ValueError):
                simulate(bars, meta, "vol15", start=start, **kwargs)
        with self.assertRaises(ValueError):
            simulate([replace(bars[0], is_complete=False)] + bars[1:], meta, "vol15", start=start)
        with self.assertRaises(ValueError):
            simulate(bars, replace(meta, is_index_proxy=True), "vol15", start=start)
        for value in (-1, float("nan"), 10000):
            with self.assertRaises(ValueError):
                Costs(slippage_bps=value)


if __name__ == "__main__":
    unittest.main()
