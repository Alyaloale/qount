"""Independent behavioral regressions for opening causality and stale marks."""
import unittest

from qount.research.ashare_backtest_data import rows_to_series
from qount.research.ashare_strategy import Book, Position, fill_quote


class StrategyReviewTests(unittest.TestCase):
    def fixture(self, **changes):
        days = ('20260901', '20260902', '20260903')
        rows = [dict(ts_code='X', trade_date=day, open=10, high=11, low=9,
                     close=10, pre_close=10, adj_factor=1, adj_open=10,
                     adj_close=10, amount=100000, vol=100000) for day in days]
        rows[1].update(changes)
        return rows_to_series('X', rows, days)

    def test_future_closing_data_cannot_cancel_available_open(self):
        baseline = self.fixture()
        damaged_close = self.fixture(close='', adj_close='')
        self.assertEqual(fill_quote(baseline, 1, 'buy', .001),
                         fill_quote(damaged_close, 1, 'buy', .001))

    def test_future_intraday_range_cannot_cancel_available_open(self):
        baseline = self.fixture()
        damaged_high = self.fixture(high=5)
        self.assertEqual(fill_quote(baseline, 1, 'sell', .001),
                         fill_quote(damaged_high, 1, 'sell', .001))

    def test_unqualified_mark_does_not_erase_staleness(self):
        item = self.fixture(adj_factor='')
        book = Book('sector_base', {'X': {'industry': 'A'}})
        book.positions['X'] = Position(100, 0, 1000, 10, 10, 0, 0)
        row = book.mark(1, '20260902', {'X': item})
        self.assertTrue(row['provisional'])
        self.assertEqual(row['max_stale_sessions'], 1)
        self.assertEqual(row['missing_mark_value_cny'], 1000)


if __name__ == '__main__':
    unittest.main()
