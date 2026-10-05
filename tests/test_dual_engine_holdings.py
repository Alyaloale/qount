import unittest
from qount.research.dual_engine_holdings import analyze_units


class HoldingTests(unittest.TestCase):
    def fixture(self):
        days=['2021-01-01','2021-01-02','2021-01-03','2021-01-04']
        closes={'X':dict(zip(days,[10,11,9,9]))};opens={'X':dict(zip(days,[10,10,10,9]))}
        rows=[dict(date=days[1],signal_date=days[0],return_=.08,returnx=.08,nav=1.08,units={'X':.08},cash=.2,cost_fraction=0,weights={'X':.88/1.08}),
              dict(date=days[2],signal_date=days[1],nav=.93,units={'X':.06},cash=.39,cost_fraction=.01,weights={'X':.54/.93}),
              dict(date=days[3],signal_date=days[2],nav=.9246,units={},cash=.9246,cost_fraction=.0054/.93,weights={})]
        for i,r in enumerate(rows):r['return']=r['nav']/(1 if i==0 else rows[i-1]['nav'])-1
        return {'records':rows},days,closes,opens

    def test_episode_and_wealth_net_fee_reconciliation(self):
        run,days,close,opn=self.fixture();r=analyze_units(run,days,close,opn,market='X')
        self.assertAlmostEqual(r['source_net_pnl'],-.0754)
        self.assertEqual(len(r['episodes']),1)
        self.assertEqual(r['episodes'][0]['status'],'closed')
        self.assertAlmostEqual(r['assets']['X']['allocated_fees'],.0154)
        self.assertEqual(r['assets']['X']['closed_losing_episodes'],1)
        self.assertLess(r['max_daily_pnl_error'],1e-12)

    def test_open_position_is_censored_not_realized_win(self):
        run,days,close,opn=self.fixture();run['records']=run['records'][:1]
        r=analyze_units(run,days,close,opn,market='X')
        self.assertEqual(r['episodes'][0]['status'],'open_censored')
        self.assertEqual(r['assets']['X']['closed_profitable_episodes'],0)
        self.assertEqual(r['assets']['X']['open_censored_episodes'],1)

    def test_corrupt_cash_unit_ledger_rejected(self):
        run,days,close,opn=self.fixture();run['records'][1]['nav']+=.1
        with self.assertRaises(ValueError):analyze_units(run,days,close,opn,market='X')

    def test_weights_only_reports_limitation_without_inventing_episodes(self):
        run,days,close,opn=self.fixture()
        for row in run['records']:del row['units']
        r=analyze_units(run,days,close,opn,market='X')
        self.assertEqual(r['status'],'weights_only_ledger');self.assertNotIn('episodes',r)

    def test_missing_execution_price_rejected_explicitly(self):
        run,days,close,opn=self.fixture();del opn['X'][days[1]]
        with self.assertRaisesRegex(ValueError,'attribution_missing_open'):analyze_units(run,days,close,opn,market='X')
