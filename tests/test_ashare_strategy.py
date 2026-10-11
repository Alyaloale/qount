import copy
import math
import unittest
from array import array
from qount.research.ashare_backtest_data import Series
from qount.research.ashare_strategy import Book,Position,Features,make_features,select,costs,fill_quote,metrics


def series(n=280,price=10):
    values={k:array('d',[price])*n for k in ('raw_open','raw_close','raw_high','raw_low','pre_close','adj_open','adj_close')}
    return Series('X',**values,factor=array('d',[1])*n,amount_cny=array('d',[100_000_000])*n,
        volume=array('d',[100000])*n,history=array('I',range(1,n+1)),valid=bytearray([1])*n,source_kind='original_zip')


class StrategyTests(unittest.TestCase):
    def test_features_exact_lag_and_window(self):
        s=series()
        for j in range(280):s.adj_close[j]=10*math.exp(j*.002)
        f=make_features(s)
        self.assertAlmostEqual(f.momentum[279],math.exp(.2)-1)
        self.assertAlmostEqual(f.change20[279],math.exp(.04)-1)
        self.assertAlmostEqual(f.ma60[279],sum(s.adj_close[220:280])/60)
        self.assertFalse(f.eligible[250]);self.assertTrue(f.eligible[251])

    def test_missing_session_not_compressed(self):
        s=series();s.valid[100]=0
        self.assertFalse(make_features(s).eligible[-1])

    def test_future_prices_do_not_change_past_features(self):
        s=series();first=make_features(s);s.adj_close[-1]=999999
        later=make_features(s)
        self.assertEqual(first.momentum[270],later.momentum[270]);self.assertEqual(first.ma200[270],later.ma200[270])

    def test_cost_boundaries_and_minimum(self):
        self.assertAlmostEqual(costs(10000,'sell','20230825')-costs(10000,'sell','20230828'),5)
        self.assertAlmostEqual(costs(100000,'buy','20220428')-costs(100000,'buy','20220429'),1)
        self.assertGreater(costs(100000,'buy','20150731'),costs(100000,'buy','20150803'))
        self.assertGreaterEqual(costs(1,'buy','20260930'),5)
        self.assertAlmostEqual(costs(1000,'buy','20260930',2),2*costs(1000,'buy','20260930'))

    def test_opening_guard_does_not_peek_high_low(self):
        s=series();s.raw_high[1]=1000;s.raw_low[1]=.01
        self.assertIsNotNone(fill_quote(s,1,'buy',.001)[0])
        s.raw_open[1]=10.5
        self.assertEqual(fill_quote(s,1,'buy',.001)[1],'conservative_opening_guard')

    def test_buy_quantity_reserved_at_signal_and_cash(self):
        b=Book('sector_base',{'X':{'industry':'A'}});s=series()
        b.plan(0,'X','buy','monthly_entry',raw_shares=10000,budget_cny=100000,adv20=100_000_000)
        s.raw_open[1]=10.1;s.adj_open[1]=10.1
        b.execute(1,'20260901',{'X':s})
        t=b.trades[0];self.assertLessEqual(t['notional_cny']+t['fees_cny'],100000)
        self.assertEqual(round(t['units'])%100,0);self.assertGreaterEqual(b.cash,0)
        self.assertEqual(b.positions['X'].peak,0)

    def test_gap_down_does_not_upsize_reserved_quantity(self):
        b=Book('sector_base',{'X':{'industry':'A'}});s=series();s.raw_open[1]=9.8;s.adj_open[1]=9.8
        b.plan(0,'X','buy','monthly_entry',raw_shares=100,budget_cny=100000,adv20=100_000_000)
        b.execute(1,'20260901',{'X':s});self.assertEqual(b.trades[0]['units'],100)

    def test_blocked_buy_expires_no_replacement(self):
        b=Book('sector_base',{});s=series();s.raw_open[1]=11
        b.plan(0,'X','buy','monthly_entry',raw_shares=100,budget_cny=100000,adv20=100_000_000)
        b.execute(1,'20260901',{'X':s});b.execute(2,'20260902',{'X':s})
        self.assertEqual(b.positions,{});self.assertEqual(b.pending,[])

    def test_blocked_exit_persists(self):
        b=Book('sector_base',{});s=series();b.positions['X']=Position(100,0,1000,10,10,0,0)
        b.plan(0,'X','sell','age126',adv20=100_000_000);s.raw_open[1]=9
        b.execute(1,'20260901',{'X':s});self.assertIn('X',b.pending_sells)
        b.execute(2,'20260902',{'X':s});self.assertNotIn('X',b.positions)
        self.assertEqual(b.closed[0]['reason'],'age126')

    def test_synthetic_split_preserves_value_and_allows_tail_exit(self):
        b=Book('sector_base',{});s=series();b.positions['X']=Position(101.5,0,1015,10,10,0,0)
        s.raw_open[1]=5;s.pre_close[1]=5;s.adj_open[1]=10;s.adj_close[1]=10
        row=b.mark(1,'20260901',{'X':s});self.assertAlmostEqual(row['nav_carry_proxy_cny'],1001015)
        b.plan(1,'X','sell','test',adv20=100_000_000);s.raw_open[2]=5;s.pre_close[2]=5;s.adj_open[2]=10
        b.execute(2,'20260902',{'X':s});self.assertNotIn('X',b.positions)
        self.assertAlmostEqual(b.trades[0]['units'],101.5)

    def test_adjusted_dividend_does_not_false_stop(self):
        b=Book('sector_base',{});s=series();b.positions['X']=Position(100,0,1000,10,10,0,0)
        s.raw_close[1]=9;s.adj_close[1]=10
        f=make_features(s);f.ma60[1]=9.9
        b.mark(1,'20260901',{'X':s});b.decisions(1,'20260901',{'X':s},{'X':f},{'market_on':False,'sector_rank':[]},False,279)
        self.assertEqual(b.pending,[])

    def test_missing_mark_interval_keeps_holding(self):
        b=Book('sector_base',{});s=series();b.positions['X']=Position(100,0,1000,10,10,0,0)
        s.adj_close[1]=math.nan;b.mark(1,'20260901',{'X':s})
        m=metrics(b.curve,[]);self.assertEqual(m['provisional_mark_days'],1)
        self.assertAlmostEqual(m['total_return_carry_proxy']-m['final_unknown_zero_recovery_return'],.001)
        self.assertIn('X',b.positions)

    def test_full_book_industry_and_cluster_caps(self):
        meta={f'X{i}':{'industry':'房产服务' if i<2 else '全国地产'} for i in range(5)}
        b=Book('sector_base',meta)
        for i in range(4):b.positions[f'X{i}']=Position(100,0,1000,10,10,0,0)
        self.assertFalse(b.slots_allow('X4'))
        self.assertTrue(Book('price_control',meta).slots_allow('X4'))

    def test_close_stop_executes_later_not_at_stop_level(self):
        b=Book('sector_base',{});s=series();b.positions['X']=Position(100,0,1000,20,10,0,0)
        f=make_features(s);f.adv20[1]=100_000_000
        b.decisions(1,'20260901',{'X':s},{'X':f},{'market_on':False,'sector_rank':[]},False,279)
        self.assertEqual(b.pending[0]['due_j'],2)
        self.assertEqual(b.pending[0]['reason'],'trailing15_close')
        s.raw_open[2]=8;s.pre_close[2]=8;s.adj_open[2]=8
        b.execute(2,'20260902',{'X':s});self.assertAlmostEqual(b.trades[0]['raw_price_with_slippage'],7.992)

    def test_monthly_exit_not_immediately_rebought(self):
        b=Book('sector_base',{'X':{'industry':'A'}});s=series();b.positions['X']=Position(100,0,1000,20,10,0,0)
        f=make_features(s);f.adv20[1]=100_000_000
        b.decisions(1,'20260901',{'X':s},{'X':f},{'market_on':True,'sector_rank':['X']},True,279)
        self.assertEqual([i['side'] for i in b.pending],['sell'])

    def test_delay_and_double_cost_schedules(self):
        b=Book('sector_extra_day',{});b.plan(7,'X','sell','test',adv20=1)
        self.assertEqual(b.pending[0]['due_j'],9)
        self.assertEqual(Book('sector_double_cost',{}).scale,2)

if __name__=='__main__':unittest.main()
