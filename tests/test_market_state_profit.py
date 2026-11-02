import unittest

import numpy as np

from qount.research.market_state_profit import execution_schedule,replay

DAY=86400000


class StateProfitTests(unittest.TestCase):
    def bars(self,n=1):
        data=np.ones((n+1,9));data[:,:4]=100;data[:,5]=1e9
        return data

    def run_case(self,data,weight,*,rate_time=(),rate=(),adverse=False,minimum=0):
        n=len(weight);clock=np.arange(n+1)*DAY
        rules=dict(fee=0,slippage=0,tick=0,step=.001,min_qty=.001,min_notional=minimum,max_qty=1e9)
        return replay(data,clock,np.array(weight),clock[:-1]-60000,np.full(n,1e9),rate_time,rate,
            initial=100,rules=rules,adverse_funding=adverse)

    def test_after_close_plus_minute_cannot_fill_the_already_passed_next_open(self):
        bar=np.array([0,DAY]);decision=bar+DAY+60000
        np.testing.assert_array_equal(execution_schedule(decision,bar),bar+2*DAY)
        with self.assertRaises(ValueError):execution_schedule(bar+DAY-1,bar)

    def test_signed_quantity_pnl_and_terminal_gap_are_reconciled(self):
        data=self.bars();data[0,:4]=[100,112,95,110];data[1,:4]=111
        long=self.run_case(data,[1]);short=self.run_case(data,[-1])
        self.assertAlmostEqual(long['nav'][-1],111);self.assertAlmostEqual(short['nav'][-1],89)
        self.assertEqual(len(long['orders']),2)

    def test_opening_settlement_is_owned_by_old_position_not_new_entry(self):
        stamps=np.arange(7)*8*3600000;rates=np.full(7,.01)
        result=self.run_case(self.bars(2),[1,1],rate_time=stamps,rate=rates)
        self.assertAlmostEqual(result['nav'][-1],94.09)
        self.assertAlmostEqual(result['components']['funding_pnl'],-5.91)

    def test_adverse_funding_includes_settlement_window_and_price_uncertainty(self):
        data=self.bars();data[0,1]=120;data[0,2]=80;stamps=np.arange(4)*8*3600000;rates=np.full(4,.01)
        base=self.run_case(data,[1],rate_time=stamps,rate=rates)
        stress=self.run_case(data,[1],rate_time=stamps,rate=rates,adverse=True)
        self.assertAlmostEqual(base['nav'][-1],97)
        self.assertAlmostEqual(stress['nav'][-1],95.6)

    def test_too_small_target_is_cash_and_missing_funding_is_rejected(self):
        data=self.bars();data[1,:4]=200
        result=self.run_case(data,[.001],minimum=5)
        self.assertAlmostEqual(result['nav'][-1],100);self.assertEqual(len(result['orders']),0)
        with self.assertRaises(ValueError):self.run_case(data,[1],rate_time=[0,DAY],rate=[.01,.01])

    def test_intraday_solvency_failure_is_reported_not_dropped(self):
        data=self.bars();data[0,1]=220
        result=self.run_case(data,[-1])
        self.assertTrue(result['solvency_failure']);self.assertEqual(result['nav'][-1],0)
        self.assertEqual(len(result['nav']),2);self.assertEqual(len(result['samples']),5)

    def test_positive_funding_credits_an_existing_short(self):
        stamps=np.arange(7)*8*3600000
        result=self.run_case(self.bars(2),[-1,-1],rate_time=stamps,rate=np.full(7,.01))
        self.assertAlmostEqual(result['nav'][-1],106.09)
        self.assertAlmostEqual(result['components']['funding_pnl'],6.09)

    def test_flat_price_round_trip_loses_both_sides_fees_and_slippage(self):
        rules=dict(fee=.001,slippage=.002,tick=.01,step=.001,min_qty=.001,min_notional=0,max_qty=1e9)
        result=replay(self.bars(),np.array([0,DAY]),np.array([1.]),np.array([-60000]),np.array([1e9]),[],[],initial=100,rules=rules)
        self.assertAlmostEqual(result['nav'][-1],99.4018)
        self.assertAlmostEqual(result['components']['price_pnl'],0)
        self.assertAlmostEqual(result['components']['fees']+result['components']['slippage_and_rounding'],.5982)


if __name__=='__main__':unittest.main()
