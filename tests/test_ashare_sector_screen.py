import copy
import datetime as dt
import math
import unittest

from qount.research.ashare_sector_screen import build_queue, features, window_inputs


class SectorScreenTests(unittest.TestCase):
    def setUp(self):
        self.sessions = [(dt.date(2025, 1, 1)+dt.timedelta(days=i)).strftime('%Y%m%d') for i in range(260)]
        self.rows = []
        for i, day in enumerate(self.sessions):
            p = 10*math.exp(.001*i)
            self.rows.append(dict(ts_code='600000.SH', trade_date=day, open=str(p), high=str(p),
                low=str(p), close=str(p), adj_close=str(p), adj_factor='1', amount='20000', vol='100'))

    def inputs(self, rows=None):
        return window_inputs(self.rows if rows is None else rows, '600000.SH', self.sessions, self.sessions[-1])

    def test_closed_prefix_and_exact_endpoints(self):
        f = features(self.inputs())
        self.assertAlmostEqual(f['change60'], math.exp(.06)-1)
        self.assertAlmostEqual(f['change20'], math.exp(.02)-1)
        self.assertAlmostEqual(f['vol60_annualized'], 0, places=12)
        self.assertEqual(f['median_amount20_cny'], 20_000_000)
        future = dict(self.rows[-1], trade_date='20270101', adj_close='999999')
        self.assertEqual(self.inputs(), self.inputs(self.rows+[future]))

    def test_gap_not_compressed(self):
        self.assertEqual(features(self.inputs(self.rows[:-25]+self.rows[-24:]))['status'], 'calendar_window_missing')

    def test_missing_adjustment_not_filled(self):
        rows = copy.deepcopy(self.rows); rows[-10]['adj_factor'] = ''
        self.assertEqual(features(self.inputs(rows))['status'], 'price_or_adjustment_invalid')

    def test_halt_and_missing_activity_not_pseudolowvol(self):
        for key, value in [('amount','0'), ('vol','0'), ('amount','')]:
            rows = copy.deepcopy(self.rows); rows[-35][key] = value
            self.assertEqual(features(self.inputs(rows))['status'], 'activity_missing_or_nonpositive')

    def test_liquidity_floor_units_and_maturity(self):
        rows = copy.deepcopy(self.rows)
        for row in rows[-20:]: row['amount']='19999'
        self.assertEqual(features(self.inputs(rows))['status'], 'below_liquidity_floor')
        self.assertEqual(features(self.inputs(self.rows[-61:]))['status'], 'history_insufficient')

    def test_identity_and_order_rejected(self):
        rows = copy.deepcopy(self.rows); rows[-1]['ts_code']='600001.SH'
        with self.assertRaises(ValueError): self.inputs(rows)
        with self.assertRaises(ValueError): self.inputs(self.rows+[self.rows[-1]])

    def queue_fixture(self):
        signals, metadata = [], {}
        for sector, strength in [('A',.3), ('B',.2), ('C',.1)]:
            for i in range(10):
                symbol = f'{sector}{i:02}'
                signals.append(dict(symbol=symbol,status='signal_available',change20=.01,
                    change60=strength,vol60_annualized=.5,median_amount20_cny=30_000_000))
                metadata[symbol]=dict(name=symbol,industry=sector,list_status='L',market='主板')
        return signals, metadata

    def test_sector_medians_breadth_and_deterministic_ties(self):
        signals, metadata=self.queue_fixture()
        sectors, queue, rows=build_queue(list(reversed(signals)),metadata)
        self.assertEqual([x['symbol'] for x in queue],['A00','A01','B00','B01','C00','C01'])
        self.assertEqual([x['members'] for x in sectors],[10]*3)
        self.assertTrue(all(x['eligibility'].startswith('pending_') for x in queue))
        self.assertEqual(len(rows),30)

    def test_thin_sector_weak_breadth_and_missing_industry(self):
        signals, metadata=self.queue_fixture()
        metadata['A00']['industry']=None
        for s in signals:
            if s['symbol'].startswith('B'): s['change20']=-.1
        sectors, queue, rows=build_queue(signals,metadata)
        self.assertEqual([x['symbol'] for x in queue],['C00','C01'])
        self.assertEqual({x['status'] for x in sectors},{'insufficient_members','weak_recent_breadth','sector_available'})
        self.assertEqual(rows[0]['status'],'industry_descriptor_missing')

    def test_descriptor_exclusion_is_explicit(self):
        signals, metadata=self.queue_fixture(); metadata['A00']['name']='*ST测试'
        sectors, queue, rows=build_queue(signals,metadata)
        self.assertEqual(rows[0]['status'],'descriptor_risk_warning_excluded')
        self.assertNotIn('A00',[x['symbol'] for x in queue])

    def test_exact_breadth_and_median_boundaries(self):
        signals, metadata=self.queue_fixture()
        for s in signals:
            if s['symbol'].startswith('A'):
                s['change20']=-.01 if int(s['symbol'][1:]) < 5 else .02
        sectors, queue, _=build_queue(signals,metadata)
        sector=next(x for x in sectors if x['industry']=='A')
        self.assertEqual(sector['positive20_fraction'],.5)
        self.assertEqual(sector['status'],'sector_available')
        for s in signals:
            if s['symbol'].startswith('A') and s['change20'] > 0: s['change20']=.01
        sectors, queue, _=build_queue(signals,metadata)
        self.assertEqual(next(x for x in sectors if x['industry']=='A')['status'],'weak_recent_breadth')

    def test_duplicate_not_double_counted(self):
        signals, metadata=self.queue_fixture()
        with self.assertRaises(ValueError): build_queue(signals+[signals[0]],metadata)


if __name__ == '__main__':
    unittest.main()
