import unittest

from qount.research.q_div_universe import PointInTimeUniverse
from qount.research.q_div_cash import CashBook, CashDividend


class UniverseTests(unittest.TestCase):
    def setUp(self):
        self.masters = [
            {"ts_code": "600900.SH", "list_date": "20031118", "delist_date": None, "market": "主板"},
            {"ts_code": "000001.SZ", "list_date": "19910403", "delist_date": None, "market": "主板"},
            {"ts_code": "600000.SH", "list_date": "19991110", "delist_date": "20250601", "market": "主板"},
            {"ts_code": "300001.SZ", "list_date": "20260101", "delist_date": None, "market": "创业板"},
        ]
        # 300 daily sessions spanning 2025 to 2026
        self.calendar = [f"2025{m:02d}{d:02d}" for m in range(1, 13) for d in (10, 20, 28)]
        self.calendar += [f"2026{m:02d}{d:02d}" for m in range(1, 11) for d in (10, 20, 28)]
        self.calendar = sorted(self.calendar)

        self.members = [
            # 600900.SH in SW2014 utilities, then SW2021 utilities
            {"ts_code": "600900.SH", "l1_code": "801160.SI", "l1_name": "公用事业", "in_date": "20031118", "out_date": None, "is_new": "N"},
            {"ts_code": "600900.SH", "l1_code": "801160.SI", "l1_name": "公用事业", "in_date": "20031118", "out_date": None, "is_new": "Y"},
            # 000001.SZ in SW2014 bank, then SW2021 bank
            {"ts_code": "000001.SZ", "l1_code": "801780.SI", "l1_name": "银行", "in_date": "19910403", "out_date": None, "is_new": "N"},
            {"ts_code": "000001.SZ", "l1_code": "801780.SI", "l1_name": "银行", "in_date": "19910403", "out_date": None, "is_new": "Y"},
            # 600000.SH transition: industry changes on 2021-12-13
            {"ts_code": "600000.SH", "l1_code": "801780.SI", "l1_name": "旧银行", "in_date": "19991110", "out_date": "20211212", "is_new": "N"},
            {"ts_code": "600000.SH", "l1_code": "801780.SI", "l1_name": "新银行", "in_date": "20211213", "out_date": None, "is_new": "Y"},
        ]

        self.namechanges = [
            {"ts_code": "000001.SZ", "name": "ST平安", "start_date": "20250101", "end_date": "20250630"},
            {"ts_code": "000001.SZ", "name": "平安银行", "start_date": "20250701", "end_date": None},
        ]
        self.st_records = [
            {"ts_code": "600000.SH", "trade_date": "20250310", "type": "ST"},
        ]

        self.universe = PointInTimeUniverse(
            masters=self.masters,
            calendar_days=self.calendar,
            members=self.members,
            namechanges=self.namechanges,
            st_records=self.st_records,
        )

    def test_calendar_and_month_ends(self):
        self.assertTrue(self.universe.is_trading_day("20250110"))
        self.assertFalse(self.universe.is_trading_day("20250115"))
        # Last session of 202501 is 20250128
        self.assertTrue(self.universe.is_month_end("20250128"))
        self.assertFalse(self.universe.is_month_end("20250120"))
        ends = self.universe.month_ends("20250101", "20250331")
        self.assertEqual(ends, ["20250128", "20250228", "20250328"])

    def test_listing_and_maturity(self):
        # 600900.SH listed since 2003, mature on 20250110
        self.assertTrue(self.universe.is_listed_and_mature("600900.SH", "20250110", min_sessions=20))
        # 300001.SZ listed 20260101, not mature on 20260110 for 252 sessions
        self.assertFalse(self.universe.is_listed_and_mature("300001.SZ", "20260110", min_sessions=252))
        # 600000.SH delisted on 20250601, mature on 20250528, not listed on 20250628
        self.assertTrue(self.universe.is_listed_and_mature("600000.SH", "20250528", min_sessions=10))
        self.assertFalse(self.universe.is_listed_and_mature("600000.SH", "20250628", min_sessions=10))

    def test_st_detection(self):
        # 000001.SZ is ST during 20250101-20250630 via namechange
        self.assertTrue(self.universe.is_st("000001.SZ", "20250228"))
        self.assertFalse(self.universe.is_st("000001.SZ", "20250728"))
        # 600000.SH is ST on 20250310 via stock_st record
        self.assertTrue(self.universe.is_st("600000.SH", "20250310"))
        self.assertFalse(self.universe.is_st("600000.SH", "20250320"))
        # 600900.SH is never ST
        self.assertFalse(self.universe.is_st("600900.SH", "20250110"))

    def test_point_in_time_industry(self):
        # 600900.SH utilities in both
        self.assertEqual(self.universe.industry_l1("600900.SH", "20210601"), ("801160.SI", "公用事业"))
        self.assertEqual(self.universe.industry_l1("600900.SH", "20220601"), ("801160.SI", "公用事业"))
        # 600000.SH transition across 20211213
        self.assertEqual(self.universe.industry_l1("600000.SH", "20211210"), ("801780.SI", "旧银行"))
        self.assertEqual(self.universe.industry_l1("600000.SH", "20211213"), ("801780.SI", "新银行"))
        # absent symbol
        self.assertIsNone(self.universe.industry_l1("999999.SH", "20250110"))

    def test_eligible_universe_filter(self):
        # On 20250228: 000001.SZ is ST, 300001.SZ is not listed yet
        eligible = self.universe.eligible_universe("20250228", min_sessions=10, exclude_st=True, require_sw1=True)
        self.assertIn("600900.SH", eligible)
        self.assertIn("600000.SH", eligible)
        self.assertNotIn("000001.SZ", eligible)
        self.assertNotIn("300001.SZ", eligible)

    def test_cash_book_share_distribution(self):
        sessions = ["20260601", "20260602", "20260603"]
        industries = {"600900.SH": "公用事业"}
        book = CashBook(sessions, industries, capital=100000.0,
                        fee_model=lambda n, side, d: 5.0,
                        tax_rate=lambda e, entry, exit: 0.1)
        # Session 0: review close generates signal (signal_j=0)
        book.open_session("20260601")
        book.close_session({"600900.SH": 10.0})

        # Session 1: Buy 1000 shares at open on due session (self.j == 1 == signal_j + 1)
        book.open_session("20260602")
        book.buy_once("buy1", "600900.SH", 1000, signal_j=0, raw_price=10.0,
                      prior_adv=10000000.0, execution_allowed=True, delay=0)
        book.close_session({"600900.SH": 10.0})
        self.assertEqual(len(book.lots), 1)
        self.assertEqual(book.lots[0].shares, 1000)

        # Session 2: 10送5 (ratio 0.5) share distribution on ex-day
        book.open_session("20260603")
        book.apply_share_distribution("600900.SH", 0.5, "20260603")
        self.assertEqual(book.lots[0].shares, 1500)
        # Price adjusted to 6.6667, market value conserved
        book.close_session({"600900.SH": 6.6667})
        self.assertAlmostEqual(book.lots[0].shares * 6.6667, 10000.05, delta=1.0)


if __name__ == "__main__":
    unittest.main()
