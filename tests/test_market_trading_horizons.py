import math
import unittest

import numpy as np

from qount.research.market_trading_horizons import (
    STATES, horizon_observation, path_state, quarterly_masks, trading_decision,
)
from qount.research_data.bars import Bar


class TradingHorizonTests(unittest.TestCase):
    def bars(self):
        result=[]; price=200.
        for i in range(160):
            close=price*math.exp(-.008+.002*math.sin(i))
            result.append(Bar((i+1)*86400-1,price,max(price,close)*1.003,
                              min(price,close)*.997,close,10000))
            price=close
        return result

    def test_short_upward_window_can_exist_inside_a_long_decline(self):
        bars=self.bars(); entry=bars[102].o
        for i in range(102,105):
            close=entry*(1+.02*(i-101))
            bars[i]=Bar(bars[i].t,entry if i==102 else bars[i-1].c,
                        close*1.001,(entry if i==102 else bars[i-1].c)*.999,close,10000)
        outcome=path_state(bars[102:105],entry,bars[104].c,.02)
        self.assertEqual(outcome['state'],'upward')
        self.assertLess(bars[104].c,bars[80].c)

    def test_features_do_not_change_when_future_is_replaced(self):
        bars=self.bars(); before=horizon_observation(bars,100,'crypto',7)
        changed=bars[:101]+[Bar(b.t,b.o*2,b.h*2,b.l*2,b.c*2,b.v) for b in bars[101:]]
        after=horizon_observation(changed,100,'crypto',7)
        self.assertEqual(before['x'],after['x'])
        self.assertEqual(before['sigma'],after['sigma'])
        self.assertEqual(before['current'],after['current'])

    def test_target_expiry_and_trade_expiry_use_the_same_clock(self):
        bars=self.bars(); r=horizon_observation(bars,100,'crypto',14)
        self.assertEqual(r['entry_index'],102)
        self.assertEqual(r['exit_index'],116)
        self.assertLess(r['known_at'],r['entry_at'])
        self.assertGreater(r['mature_at'],r['exit_at'])
        d=trading_decision(r,bars,'crypto',0)
        self.assertEqual(d['entry_at'],r['entry_at'])
        self.assertEqual(d['max_bars'],14)

    def test_unmatured_tail_is_not_a_fake_completed_target(self):
        bars=self.bars(); r=horizon_observation(bars,150,'crypto',30)
        self.assertEqual(r['y'],-1)
        self.assertEqual(r['mature_at'],0)
        self.assertIsNone(trading_decision(r,bars,'crypto',0))

    def test_one_daily_bar_does_not_claim_observed_two_sided_sequence(self):
        state=path_state([Bar(0,100,110,90,100)],100,100,.02)
        self.assertNotEqual(state['state'],'two_sided')

    def test_same_window_envelope_does_not_depend_on_daily_bar_count(self):
        single=[Bar(0,100,112,98,110)]
        subdivided=[Bar(i,100,112,98,100) for i in range(8)]+[Bar(8,100,112,98,110)]
        first=path_state(single,100,110,.02)
        second=path_state(subdivided,100,110,.02/3)
        self.assertAlmostEqual(first['efficiency'],second['efficiency'])
        self.assertAlmostEqual(first['amplitude'],second['amplitude'])
        self.assertEqual(first['state'],second['state'])

    def test_quarter_tests_are_disjoint_and_training_is_purged(self):
        rows=[dict(y=0,known_at=t,mature_at=t+15) for t in range(0,100,10)]
        train,test=quarterly_masks(rows,50,80)
        self.assertTrue(all(rows[i]['mature_at']<50 for i in train))
        self.assertEqual(test.tolist(),[5,6,7])
        _,later=quarterly_masks(rows,80,110)
        self.assertEqual(len(np.intersect1d(test,later)),0)


if __name__=='__main__':
    unittest.main()
