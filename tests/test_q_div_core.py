import unittest

from qount.research.q_div_cash import CashDividend
from qount.research.q_div_core import (
    CandidateMetric,
    compute_performance_metrics,
    fill_quote,
    percentile_rank_ties,
    score_and_rank_candidates,
    select_rebalance_portfolio,
    standard_a_share_dividend_tax,
    standard_costs,
)


class QDivCoreTests(unittest.TestCase):
    def test_percentile_rank_ties_and_direction(self):
        # Descending (higher is better, top gets 1.0)
        vals = [10.0, 30.0, 20.0]
        pcts = percentile_rank_ties(vals, descending=True)
        self.assertAlmostEqual(pcts[1], 1.0)   # 30.0 -> highest -> 1.0
        self.assertAlmostEqual(pcts[2], 0.5)   # 20.0 -> middle -> 0.5
        self.assertAlmostEqual(pcts[0], 0.0)   # 10.0 -> lowest -> 0.0

        # Ascending (lower is better, top gets 1.0)
        pcts_asc = percentile_rank_ties(vals, descending=False)
        self.assertAlmostEqual(pcts_asc[0], 1.0)   # 10.0 -> lowest vol -> 1.0
        self.assertAlmostEqual(pcts_asc[2], 0.5)   # 20.0 -> middle -> 0.5
        self.assertAlmostEqual(pcts_asc[1], 0.0)   # 30.0 -> highest vol -> 0.0

        # Ties
        ties = [10.0, 20.0, 20.0, 30.0]
        pcts_ties = percentile_rank_ties(ties, descending=True)
        # Unique sorted desc: 30 (rank 1), 20 (ranks 2,3 avg 2.5), 10 (rank 4)
        # n = 4. 1.0 - (avg_rank - 1)/(n - 1)
        # for 30: 1.0 - 0/3 = 1.0
        # for 20: 1.0 - (1.5)/3 = 0.5
        # for 10: 1.0 - 3/3 = 0.0
        self.assertAlmostEqual(pcts_ties[3], 1.0)
        self.assertAlmostEqual(pcts_ties[1], 0.5)
        self.assertAlmostEqual(pcts_ties[2], 0.5)
        self.assertAlmostEqual(pcts_ties[0], 0.0)

        # Single item
        self.assertEqual(percentile_rank_ties([5.0]), [0.0])
        self.assertEqual(percentile_rank_ties([]), [])

    def test_standard_costs(self):
        # Commission min 5 CNY
        fee_buy = standard_costs(1000.0, "buy", "20200101", scale=1.0)
        # notional 1000 * 0.0003 = 0.3 < 5 -> 5.0. transfer = 1000 * 0.00002 = 0.02. total = 5.02
        self.assertAlmostEqual(fee_buy, 5.02)

        # Stamp duty on sell before 20230828 (0.1%)
        fee_sell = standard_costs(100000.0, "sell", "20200101", scale=1.0)
        # comm = 30, transfer = 2, stamp = 100 -> total = 132
        self.assertAlmostEqual(fee_sell, 132.0)

        # Double cost scale = 2.0
        fee_sell_double = standard_costs(100000.0, "sell", "20200101", scale=2.0)
        self.assertAlmostEqual(fee_sell_double, 264.0)

    def test_standard_a_share_dividend_tax(self):
        ev = CashDividend("ev1", "000001.SZ", "20200501", "20200510", "20200511", "20200515", 1.0)
        # <= 30 days
        self.assertEqual(standard_a_share_dividend_tax(ev, "20200501", "20200520"), 0.20)
        # <= 365 days
        self.assertEqual(standard_a_share_dividend_tax(ev, "20200501", "20201001"), 0.10)
        # > 365 days
        self.assertEqual(standard_a_share_dividend_tax(ev, "20200501", "20210601"), 0.00)

    def test_fill_quote_guards(self):
        # Limit up guard on buy (>= 1.0499)
        px, status = fill_quote(10.5, 10.0, "buy", 0.001, 1000.0)
        self.assertIsNone(px)
        self.assertEqual(status, "opening_limit_up_guard")

        # Limit down guard on sell (<= 0.9501)
        px, status = fill_quote(9.5, 10.0, "sell", 0.001, 1000.0)
        self.assertIsNone(px)
        self.assertEqual(status, "opening_limit_down_guard")

        # Normal execution
        px, status = fill_quote(10.0, 10.0, "buy", 0.001, 1000.0)
        self.assertAlmostEqual(px, 10.01)
        self.assertEqual(status, "available")

    def test_selection_and_industry_caps(self):
        # Create 5 candidates in Industry A, 2 in Industry B
        cands = [
            CandidateMetric("A1", "IndA", 10.0, 5e7, 0.2, 0.05, 0.12, 1.0, 0.5, True, True, True, True),
            CandidateMetric("A2", "IndA", 10.0, 5e7, 0.2, 0.04, 0.12, 1.0, 0.5, True, True, True, True),
            CandidateMetric("A3", "IndA", 10.0, 5e7, 0.2, 0.03, 0.12, 1.0, 0.5, True, True, True, True),
            CandidateMetric("A4", "IndA", 10.0, 5e7, 0.2, 0.02, 0.12, 1.0, 0.5, True, True, True, True),
            CandidateMetric("A5", "IndA", 10.0, 5e7, 0.2, 0.01, 0.12, 1.0, 0.5, True, True, True, True),
            CandidateMetric("B1", "IndB", 10.0, 5e7, 0.2, 0.04, 0.12, 1.0, 0.5, True, True, True, True),
            CandidateMetric("B2", "IndB", 10.0, 5e7, 0.2, 0.03, 0.12, 1.0, 0.5, True, True, True, True),
        ]
        ranked = score_and_rank_candidates(cands)
        # Select with industry_slots = 3, max_positions = 4
        targets, exits = select_rebalance_portfolio(
            set(),
            ranked,
            max_positions=4,
            industry_slots=3,
            retention_rank=30,
        )
        # IndA should have at most 3 slots, remaining slot filled by IndB
        ind_a_count = sum(1 for s in targets if s.startswith("A"))
        self.assertLessEqual(ind_a_count, 3)
        self.assertIn("B1", targets)
        self.assertEqual(len(targets), 4)

    def test_compute_performance_metrics(self):
        records = [
            {"date": "20200102", "nav": 1000000.0},
            {"date": "20200630", "nav": 1100000.0},
            {"date": "20201231", "nav": 1200000.0},
        ]
        trades = [
            {"side": "buy", "shares": 1000, "raw_price": 10.0},
            {"side": "sell", "shares": 1000, "raw_price": 12.0},
        ]
        m = compute_performance_metrics(records, trades)
        self.assertAlmostEqual(m["cagr"], 0.20, places=1)
        self.assertGreater(m["one_way_annual_turnover"], 0.0)
        self.assertIn("2020", m["annual_returns"])


if __name__ == "__main__":
    unittest.main()
