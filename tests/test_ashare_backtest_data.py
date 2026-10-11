import copy
import math
import unittest

from qount.research.ashare_backtest_data import rows_to_series


class BacktestDataTests(unittest.TestCase):
    def setUp(self):
        self.sessions = ('20140102', '20140103', '20140106', '20140107')
        self.symbol = '600000.SH'
        self.rows = [self.row(day) for day in ('20131231',) + self.sessions]

    def row(self, day, **kwargs):
        return dict(ts_code='600000.SH', trade_date=day, open='10', high='12',
                    low='9', close='11', pre_close='10.5', adj_factor='2',
                    adj_open='20', adj_close='22', amount='20000', vol='123', **kwargs)

    def series(self, rows=None, **kwargs):
        return rows_to_series(self.symbol, self.rows if rows is None else rows, self.sessions, **kwargs)

    def test_raw_adjusted_units_and_maturity(self):
        item = self.series()
        self.assertEqual(list(item.history), [2, 3, 4, 5])
        self.assertEqual(list(item.valid), [1, 1, 1, 1])
        self.assertEqual(item.raw_open[0], 10)
        self.assertEqual(item.raw_close[0], 11)
        self.assertEqual(item.raw_high[0], 12)
        self.assertEqual(item.raw_low[0], 9)
        self.assertEqual(item.pre_close[0], 10.5)
        self.assertEqual(item.factor[0], 2)
        self.assertEqual(item.adj_open[0], 20)
        self.assertEqual(item.adj_close[0], 22)
        self.assertEqual(item.amount_cny[0], 20_000_000)
        self.assertEqual(item.volume[0], 123)

    def test_gap_is_not_compressed_or_filled(self):
        item = self.series(self.rows[:2] + self.rows[3:])
        self.assertEqual(list(item.valid), [1, 0, 1, 1])
        self.assertEqual(list(item.history), [2, 2, 3, 4])
        self.assertTrue(math.isnan(item.raw_close[1]))
        self.assertTrue(math.isnan(item.adj_close[1]))
        self.assertTrue(math.isnan(item.amount_cny[1]))

    def test_future_prices_never_affect_earlier_maturity(self):
        earlier = rows_to_series(self.symbol, self.rows, self.sessions[:2])
        self.assertEqual(list(earlier.history), [2, 3])
        rows = copy.deepcopy(self.rows)
        rows[-1]['close'] = '9999999'
        later = self.series(rows)
        self.assertEqual(list(later.history)[:2], list(earlier.history))
        self.assertEqual(list(later.valid)[:2], list(earlier.valid))
        # No access to ts_code or price payload beyond the frozen endpoint.
        future = {'trade_date': '20270101'}
        self.assertEqual(list(self.series(self.rows + [future]).history), [2, 3, 4, 5])

    def test_retired_uses_exact_same_day_factor(self):
        factors = dict(zip(self.sessions, (1, 2, 3, 4)))
        item = self.series(source_kind='tushare_retired', factors=factors)
        self.assertEqual(list(item.factor), [1, 2, 3, 4])
        self.assertEqual(list(item.adj_open), [10, 20, 30, 40])
        self.assertEqual(list(item.adj_close), [11, 22, 33, 44])
        self.assertEqual(item.source_kind, 'tushare_retired')

    def test_missing_retired_factor_not_forward_filled(self):
        factors = {self.sessions[0]: 2, self.sessions[2]: 3, self.sessions[3]: 3}
        item = self.series(source_kind='tushare_retired', factors=factors)
        self.assertEqual(list(item.valid), [1, 0, 1, 1])
        self.assertTrue(math.isnan(item.adj_open[1]))
        self.assertEqual(list(item.history), [2, 3, 4, 5])

    def test_invalid_raw_price_or_ohlc_does_not_count_maturity(self):
        for key, value in [('close', '0'), ('open', ''), ('high', '9'), ('low', '12')]:
            with self.subTest(key=key, value=value):
                rows = copy.deepcopy(self.rows)
                rows[2][key] = value
                item = self.series(rows)
                self.assertEqual(list(item.valid), [1, 0, 1, 1])
                self.assertEqual(list(item.history), [2, 2, 3, 4])

    def test_missing_activity_or_adjustment_stays_in_raw_maturity(self):
        for key, value in [('vol', '0'), ('amount', '0'), ('amount', ''),
                           ('adj_open', ''), ('adj_close', '-1'), ('adj_factor', 'nan')]:
            with self.subTest(key=key, value=value):
                rows = copy.deepcopy(self.rows)
                rows[2][key] = value
                item = self.series(rows)
                self.assertEqual(list(item.valid), [1, 0, 1, 1])
                self.assertEqual(list(item.history), [2, 3, 4, 5])

    def test_no_filter_by_current_status_or_future_exit(self):
        rows = copy.deepcopy(self.rows[:3])
        for row in rows:
            row.update(name='*ST旧公司', list_status='D', delist_date='20140106')
        item = self.series(rows)
        self.assertEqual(list(item.valid), [1, 1, 0, 0])
        self.assertEqual(list(item.history), [2, 3, 3, 3])
        self.assertEqual(item.symbol, self.symbol)

    def test_identity_duplicate_date_and_unsorted_rows_rejected(self):
        rows = copy.deepcopy(self.rows)
        rows[2]['ts_code'] = '600001.SH'
        for invalid in (rows, self.rows + [self.rows[-1]], list(reversed(self.rows))):
            with self.assertRaises(ValueError):
                self.series(invalid)

    def test_non_exchange_session_in_frozen_range_rejected(self):
        rows = self.rows[:3] + [self.row('20140104')] + self.rows[3:]
        with self.assertRaisesRegex(ValueError, 'outside_frozen_calendar'):
            self.series(rows)

    def test_nonfinite_values_do_not_become_valid(self):
        for key in ('open', 'adj_factor', 'adj_open', 'amount', 'vol'):
            rows = copy.deepcopy(self.rows)
            rows[1][key] = float('inf')
            self.assertEqual(self.series(rows).valid[0], 0)

    def test_source_and_calendar_contract_validation(self):
        with self.assertRaises(ValueError):
            self.series(source_kind='baostock_retired')
        with self.assertRaises(ValueError):
            self.series(source_kind='tushare_retired')
        with self.assertRaises(ValueError):
            rows_to_series(self.symbol, self.rows, tuple(reversed(self.sessions)))


if __name__ == '__main__':
    unittest.main()
