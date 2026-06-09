import unittest

from qount.cta_portfolio import (
    apply_fill,
    equity_curve_stats,
    paper_execute,
    parse_sina_quote,
    splice_daily,
    rebalance_due,
    rebalance_orders,
    target_book,
    trading_days_since,
    value_holdings,
)


class EquityCurveStatsTest(unittest.TestCase):
    def test_return_and_drawdown(self) -> None:
        rows = [
            {"date": "2026-06-09", "equity": 1_000_000},
            {"date": "2026-06-10", "equity": 1_050_000},
            {"date": "2026-06-11", "equity": 980_000},   # trough after peak
            {"date": "2026-06-12", "equity": 1_020_000},
        ]
        s = equity_curve_stats(rows)
        self.assertEqual(s["n_days"], 4)
        self.assertAlmostEqual(s["total_return_pct"], 0.02)            # 1.02M/1.00M - 1
        self.assertAlmostEqual(s["max_drawdown"], 980_000 / 1_050_000 - 1.0)  # -6.67%
        self.assertEqual(s["peak_equity"], 1_050_000)

    def test_empty(self) -> None:
        self.assertIsNone(equity_curve_stats([]))


class PaperExecuteTest(unittest.TestCase):
    def test_paper_fills_orders_at_ref_price(self) -> None:
        pos = {"cash": 1_000_000.0, "holdings": {}}
        orders = [
            {"symbol": "A", "side": "BUY", "shares": 50000, "limit_ref": 10.0},
            {"symbol": "B", "side": "BUY", "shares": 20000, "limit_ref": 5.0},
        ]
        paper_execute(pos, orders)
        self.assertEqual(pos["holdings"]["A"]["shares"], 50000)
        self.assertAlmostEqual(pos["holdings"]["A"]["avg_cost"], 10.0)
        self.assertEqual(pos["cash"], 1_000_000.0 - 50000 * 10.0 - 20000 * 5.0)


class SpliceDailyTest(unittest.TestCase):
    def test_splices_by_raw_return_at_anchor(self) -> None:
        cache = {"2026-06-01": 6.0, "2026-06-02": 6.254}      # adjusted level
        raw = {"2026-06-02": 4.936, "2026-06-03": 4.965, "2026-06-04": 4.926}  # raw closes
        out, n = splice_daily(cache, raw)
        self.assertEqual(n, 2)
        self.assertAlmostEqual(out["2026-06-03"], 6.254 * 4.965 / 4.936, places=4)  # seam-free
        self.assertAlmostEqual(out["2026-06-04"], 6.254 * 4.926 / 4.936, places=4)
        self.assertEqual(out["2026-06-02"], 6.254)            # existing untouched

    def test_no_overlap_no_change(self) -> None:
        out, n = splice_daily({"2026-06-02": 6.0}, {"2026-07-01": 5.0})
        self.assertEqual(n, 0)
        self.assertEqual(out, {"2026-06-02": 6.0})


class SinaQuoteTest(unittest.TestCase):
    def test_parse_etf_line(self) -> None:
        line = 'var hq_str_sh510300="沪深300ETF,4.764,4.739,4.826,4.828,4.741,4.826,4.827,436164482,2085";'
        secid, price, prev = parse_sina_quote(line)
        self.assertEqual(secid, "sh510300")
        self.assertAlmostEqual(price, 4.826)        # idx3 = current
        self.assertAlmostEqual(prev, 4.739)         # idx2 = prev close

    def test_preopen_falls_back_to_prev_close(self) -> None:
        line = 'var hq_str_sz159915="创业板ETF,0,2.500,0,0,0,0,0";'
        _secid, price, prev = parse_sina_quote(line)
        self.assertEqual(price, 2.500)              # current 0 -> prev close
        self.assertEqual(prev, 2.500)

    def test_empty_line_none(self) -> None:
        self.assertIsNone(parse_sina_quote('var hq_str_sh510300="";'))


class ApplyFillTest(unittest.TestCase):
    def test_buy_blends_cost_and_debits_cash(self) -> None:
        pos = {"cash": 100000.0, "holdings": {"A": {"shares": 1000, "avg_cost": 10.0}}}
        apply_fill(pos, "A", "buy", 1000, 12.0)
        self.assertEqual(pos["holdings"]["A"]["shares"], 2000)
        self.assertAlmostEqual(pos["holdings"]["A"]["avg_cost"], 11.0)  # (10000+12000)/2000
        self.assertEqual(pos["cash"], 100000.0 - 12000.0)

    def test_sell_frees_cash_and_keeps_cost(self) -> None:
        pos = {"cash": 0.0, "holdings": {"A": {"shares": 2000, "avg_cost": 11.0}}}
        apply_fill(pos, "A", "sell", 500, 13.0)
        self.assertEqual(pos["holdings"]["A"]["shares"], 1500)
        self.assertAlmostEqual(pos["holdings"]["A"]["avg_cost"], 11.0)
        self.assertEqual(pos["cash"], 6500.0)

    def test_full_sell_removes_position(self) -> None:
        pos = {"cash": 0.0, "holdings": {"A": {"shares": 500, "avg_cost": 11.0}}}
        apply_fill(pos, "A", "sell", 500, 13.0)
        self.assertNotIn("A", pos["holdings"])
        self.assertEqual(pos["cash"], 6500.0)


class ValueHoldingsTest(unittest.TestCase):
    def test_pnl_and_weights(self) -> None:
        st = value_holdings(
            {"510300.SH": {"shares": 1000, "avg_cost": 10.0}},
            cash=5000.0,
            latest_px={"510300.SH": 12.0},
        )
        r = st["rows"][0]
        self.assertEqual(r["market_value"], 12000.0)
        self.assertEqual(r["cost_basis"], 10000.0)
        self.assertEqual(r["pnl"], 2000.0)
        self.assertAlmostEqual(r["pnl_pct"], 0.20)
        self.assertEqual(st["equity"], 17000.0)
        self.assertAlmostEqual(r["weight"], 12000.0 / 17000.0)
        self.assertEqual(st["total_pnl"], 2000.0)


class RebalanceOrdersTest(unittest.TestCase):
    def test_buy_from_cash(self) -> None:
        orders = rebalance_orders({}, {"A": 0.5}, {"A": 10.0}, equity=1_000_000.0)
        self.assertEqual(len(orders), 1)
        o = orders[0]
        self.assertEqual(o["side"], "BUY")
        self.assertEqual(o["shares"], 50000)  # 500k/10 = 50000 shares = 500 lots
        self.assertEqual(o["lots"], 500)

    def test_sell_overweight(self) -> None:
        orders = rebalance_orders(
            {"A": {"shares": 52000, "avg_cost": 9.0}}, {"A": 0.5}, {"A": 10.0}, equity=1_000_000.0,
        )
        self.assertEqual(orders[0]["side"], "SELL")
        self.assertEqual(orders[0]["lots"], 20)  # 52000 -> 50000 = -2000 = 20 lots

    def test_no_order_when_on_target(self) -> None:
        orders = rebalance_orders(
            {"A": {"shares": 50000, "avg_cost": 9.0}}, {"A": 0.5}, {"A": 10.0}, equity=1_000_000.0,
        )
        self.assertEqual(orders, [])


class RebalanceDueTest(unittest.TestCase):
    def _dates(self, n: int) -> list[str]:
        return [f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n)]

    def test_due_on_cadence(self) -> None:
        dates = self._dates(60)
        last = dates[30]  # 29 trading days after
        d = rebalance_due(dates, last, {"A": 0.5}, {"A": 0.5})  # no drift
        self.assertTrue(d["due"])
        self.assertGreaterEqual(d["trading_days_elapsed"], 21)

    def test_due_on_drift(self) -> None:
        dates = self._dates(60)
        last = dates[-3]  # only 2 days after -> cadence not met
        d = rebalance_due(dates, last, {"A": 0.20}, {"A": 0.40})  # 20% drift
        self.assertTrue(d["due"])
        self.assertTrue(any("漂移" in r for r in d["reasons"]))

    def test_not_due(self) -> None:
        dates = self._dates(60)
        last = dates[-3]
        d = rebalance_due(dates, last, {"A": 0.40}, {"A": 0.41})  # 1% drift, 2 days
        self.assertFalse(d["due"])

    def test_trading_days_since(self) -> None:
        dates = ["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06"]
        self.assertEqual(trading_days_since(dates, "2026-01-02"), 2)


class TargetBookTest(unittest.TestCase):
    def test_long_only_nonneg_weights_on_uptrend(self) -> None:
        # one ETF trends up, one flat; long-only target should weight the up one, never short.
        n = 320
        prices = {
            "510300.SH": [10.0 * (1.0 + 0.002) ** t for t in range(n)],  # steady uptrend
            "518880.SH": [10.0 for _ in range(n)],                        # flat
        }
        w = target_book(prices, "conservative")
        self.assertTrue(all(v >= 0.0 for v in w.values()))
        self.assertGreater(w.get("510300.SH", 0.0), 0.0)


if __name__ == "__main__":
    unittest.main()
