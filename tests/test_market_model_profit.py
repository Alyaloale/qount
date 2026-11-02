import unittest

import numpy as np

from qount.research.market_model_profit import bracket_exit,execution_price,position_size,replay_asset,summarize_portfolio


class MarketModelProfitTests(unittest.TestCase):
    def setUp(self):
        self.rules=dict(fee=.0005,slippage=.0002,tick=.01,step=.01,min_qty=.01,min_notional=5.)

    def test_stop_priority_and_gap_for_both_sides(self):
        self.assertEqual(bracket_exit([0,100,115,85,102,1,999],1,90,110),(90,'stop_both'))
        self.assertEqual(bracket_exit([0,100,115,85,102,1,999],-1,110,90),(110,'stop_both'))
        self.assertEqual(bracket_exit([0,80,100,75,90,1,999],1,90,110),(80.,'stop_gap'))

    def test_adverse_execution_and_lot_risk(self):
        self.assertGreater(execution_price(100,1,opening=True,slippage=.0002,tick=.01),100)
        self.assertLess(execution_price(100,1,opening=False,slippage=.0002,tick=.01),100)
        q=position_size(1000,100,90,1,self.rules,10000)
        self.assertLessEqual(q*(10+100*.0014),10+1e-9)
        self.assertEqual(position_size(1,100,90,1,self.rules,10000),0)

    def test_cash_funding_and_horizon_accounting(self):
        bars=np.array([[0,100,101,99,100,100,999],[1000,100,101,99,100,100,1999],
                       [2000,110,111,109,110,100,2999],[3000,110,111,109,110,100,3999]],float)
        ds=[dict(known_at=500,entry_at=1000,side=1,stop=90,target=None,fraction=1.,max_bars=1,capacity=10000)]
        funding=[dict(fundingTime=1000,fundingRate='.01',markPrice='100'),
                 dict(fundingTime=1500,fundingRate='.01',markPrice='100'),
                 dict(fundingTime=2000,fundingRate='.01',markPrice='110')]
        s=replay_asset(bars,ds,funding,initial=1000,rules=self.rules);trade=s['trades'][0]
        self.assertEqual(trade['exit_at'],2000);self.assertEqual(trade['reason'],'horizon')
        self.assertAlmostEqual(trade['funding'],-trade['quantity']*2.1)
        self.assertAlmostEqual(s['nav'][-1]-1000,trade['net_pnl'])
        s['start_at']=0
        summary,_,_,_=summarize_portfolio({'X':s},1000,continuous=False)
        self.assertAlmostEqual(summary['components']['net_pnl'],summary['final_equity']-1000)

    def test_exit_bar_does_not_collect_uncertain_funding_credit(self):
        bars=[[0,100,101,99,100,100,999],[1000,100,115,85,105,100,1999]]
        ds=[dict(known_at=500,entry_at=1000,side=1,stop=90,target=110,fraction=1.,max_bars=5,capacity=10000)]
        funding=[dict(fundingTime=1500,fundingRate='-.01',markPrice='100'),
                 dict(fundingTime=1600,fundingRate='.02',markPrice='100')]
        s=replay_asset(bars,ds,funding,initial=1000,rules=self.rules);t=s['trades'][0]
        self.assertEqual(t['reason'],'stop_both');self.assertAlmostEqual(t['funding'],-2*t['quantity'])

    def test_rejects_clock_and_missing_price_crossing(self):
        bars=[[0,100,101,99,100,100,999],[3000,100,101,99,100,100,3999]]
        d=dict(known_at=-1,entry_at=0,side=1,stop=90,target=None,fraction=1.,max_bars=5,capacity=10000)
        with self.assertRaisesRegex(ValueError,'missing_prices'):
            replay_asset(bars,[d],[],initial=1000,rules=self.rules)
        with self.assertRaisesRegex(ValueError,'decision_clock'):
            replay_asset(bars,[dict(d,known_at=0)],[],initial=1000,rules=self.rules)

    def test_cash_session_gap_is_not_a_missing_crypto_bar(self):
        bars=[[0,100,101,99,100,100,999],[3000,100,101,99,100,100,3999]]
        d=dict(known_at=-1,entry_at=0,side=1,stop=90,target=None,fraction=1.,max_bars=1,capacity=10000)
        result=replay_asset(bars,[d],[],initial=1000,rules=dict(self.rules,continuous_clock=False))
        self.assertEqual(result['trades'][0]['exit_at'],3000)


if __name__=='__main__':unittest.main()
