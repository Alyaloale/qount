import datetime as dt
import unittest
from qount.research.dual_engine_books import changed_scopes,settle_book,replay_books
from qount.research.dual_engine_structural import replay_units


class BooksTests(unittest.TestCase):
    def fixture(self):
        days=[(dt.date(2021,1,1)+dt.timedelta(days=i)).isoformat() for i in range(18)]
        closes={k:{d:100*(1+r)**i for i,d in enumerate(days)} for k,r in [('X',.02),('Y',-.01),('BIL',.0001)]}
        opens={k:{d:closes[k][d]*(1+.001*(i%3-1)) for i,d in enumerate(days)} for k in closes}
        targets={i:{'X':.2,'Y':.2,'BIL':.6} for i in (0,3,6,9,12,15)}
        return days,closes,opens,targets

    def test_full_refresh_reproduces_original_account(self):
        days,close,opn,targets=self.fixture()
        a=replay_units(days,close,opn,targets,start=days[1],lag=1,cost_bps=40,cash_asset='BIL')
        b=replay_books(days,close,opn,targets,start=days[1],lag=1,cost_bps=40,cash_asset='BIL')
        for x,y in zip(a['records'],b['records']):
            for k in ('return','nav','cash','turnover','cost_fraction'):self.assertAlmostEqual(x[k],y[k],places=12)

    def test_scoped_changes_keep_other_units_exact(self):
        days,close,opn,targets=self.fixture();targets[3]={'X':.05,'Y':.2,'BIL':.75}
        scopes=changed_scopes(targets,{0,6,9,12,15})
        self.assertEqual(scopes[3],('X',))
        b=replay_books(days,close,opn,targets,start=days[1],lag=1,cost_bps=40,cash_asset='BIL',scopes=scopes)
        rows={r['date']:r for r in b['records']}
        self.assertEqual(rows[days[3]]['units']['Y'],rows[days[4]]['units']['Y'])
        self.assertEqual(rows[days[4]]['untouched_units_max_error'],0)

    def test_funding_and_fee_equations(self):
        units={'X':.2,'Y':.1,'BIL':.7};marks={'X':1.1,'Y':.9,'BIL':1.}
        new,cash,fee,w,cap=settle_book(1.01,0,units,marks,{'X':.05,'Y':.2,'BIL':.75},cost_bps=40,scope=('X',),cash_asset='BIL')
        turnover=sum(abs(new.get(k,0)-units.get(k,0))*marks[k] for k in set(new)|set(units))
        self.assertAlmostEqual(fee,.004*turnover)
        self.assertAlmostEqual(cash+sum(new[k]*marks[k] for k in new)+fee,1.01)
        self.assertEqual(new['Y'],units['Y']);self.assertAlmostEqual(sum(w.values()),1.)

    def test_unfunded_target_resizes_without_touching_frozen_units(self):
        units={'X':.1,'Y':.9};marks={'X':1.,'Y':1.}
        new,cash,fee,w,cap=settle_book(1,0,units,marks,{'X':.8,'Y':.2},cost_bps=40,scope=('X',))
        self.assertTrue(cap);self.assertEqual(new['Y'],.9);self.assertGreaterEqual(cash,-1e-12)
        self.assertLessEqual(new['X'],.1+1e-12)

    def test_reductions_cannot_buy_after_open_gap(self):
        new,cash,fee,w,cap=settle_book(1.,.8,{'X':.2},{'X':1.}, {'X':.5},cost_bps=25,sell_only=True)
        self.assertLessEqual(new['X'],.2);self.assertAlmostEqual(cash,.8)

    def test_weekly_clock_has_zero_buys_on_reduction_days(self):
        days,close,opn,targets=self.fixture();targets={i:{'X':.3} for i in range(len(days))}
        b=replay_books(days,close,opn,targets,start=days[2],lag=1,cost_bps=25,weekly=True)
        reduced=[r for r in b['records'] if r['trade_clock']=='reduce_only']
        self.assertTrue(reduced)
        self.assertTrue(all(r['risk_buy_notional']<1e-12 for r in reduced))
        self.assertTrue(all(e['full_refresh']==(dt.date.fromisoformat(e['date']).weekday()==6) for e in b['decisions']))

    def test_pending_buys_cancel_using_latest_closed_gate(self):
        days,close,opn,targets=self.fixture();targets={0:{'X':.3},1:{}}
        b=replay_books(days,close,opn,targets,start=days[2],lag=2,cost_bps=25,cancel_stale=True)
        self.assertEqual(b['records'][0]['cancelled_stale'],['X'])
        self.assertEqual(b['records'][0]['units'],{})

    def test_later_prices_cannot_change_earlier_account(self):
        days,close,opn,targets=self.fixture();targets={i:{'X':.3} for i in range(len(days))}
        altered={k:{d:v if i<10 else v*50 for i,(d,v) in enumerate(series.items())} for k,series in close.items()}
        a=replay_books(days,close,opn,targets,start=days[2],lag=2,cost_bps=50,weekly=True)
        b=replay_books(days,altered,opn,targets,start=days[2],lag=2,cost_bps=50,weekly=True)
        self.assertEqual(a['records'][:8],b['records'][:8])
