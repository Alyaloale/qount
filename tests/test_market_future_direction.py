import unittest
import numpy as np

from qount.research.market_future_direction import direction_patterns,long_profit_targets,mature_split,price_targets,slope_targets
from qount.research.market_state_dataset import DAY_MS


class FutureDirectionTests(unittest.TestCase):
    def test_same_anchor_and_actual_prices_not_adjacent_comparisons(self):
        clock=np.arange(20,dtype=np.int64)*DAY_MS
        close=np.full(20,100.);close[[3,5,7,9,11,13]]=[110,99,98,97,96,95]
        t=price_targets(clock,close,np.array([0]))
        np.testing.assert_array_equal(t['above'],[[1,0,0,0,0,0,0]])
        np.testing.assert_allclose(t['returns'],[[.1,-.01,-.02,-.03,-.04,-.05,0.]])
        self.assertEqual(t['available_at'][0,0],4*DAY_MS+60000)

    def test_ties_and_missing_future_are_not_fabricated(self):
        clock=np.arange(16,dtype=np.int64)*DAY_MS
        t=price_targets(clock,np.full(16,100.),clock[[0,15]])
        self.assertTrue(t['observed'][0].all());self.assertFalse(t['valid'].any())
        self.assertFalse(t['observed'][1].any());self.assertTrue(np.isnan(t['future_close'][1]).all())
        t14=price_targets(clock,np.full(16,100.),clock[:1],horizons=(3,14))
        self.assertTrue(t14['observed'][0,-1])

    def test_future_suffix_does_not_change_reference_or_shorter_labels(self):
        clock=np.arange(30,dtype=np.int64)*DAY_MS;close=np.arange(30,dtype=float)+100
        a=price_targets(clock,close,clock[:3]);close[12:]=50
        b=price_targets(clock,close,clock[:3])
        np.testing.assert_array_equal(a['reference_close'],b['reference_close'])
        np.testing.assert_array_equal(a['above'][:,:3],b['above'][:,:3])
        self.assertFalse(np.array_equal(a['above'][:,-1],b['above'][:,-1]))

    def test_mean_is_forward_average_not_endpoint_or_previous_average(self):
        clock=np.arange(20,dtype=np.int64)*DAY_MS;close=np.full(20,100.)
        close[1:4]=[110,110,90]
        t=price_targets(clock,close,clock[:1])
        self.assertFalse(t['above'][0,0]);self.assertTrue(t['mean_above'][0,0])
        self.assertAlmostEqual(t['mean_close'][0,0],310/3)

    def test_slope_uses_ordered_next_seven_closes_and_masks_flat(self):
        clock=np.arange(16,dtype=np.int64)*DAY_MS
        close=np.arange(100,116,dtype=float)
        t=slope_targets(clock,close,clock[[0,1]],horizon=7)
        self.assertTrue(t['up'][0]);self.assertTrue(t['valid'][0]);self.assertTrue(t['observed'][0])
        flat=slope_targets(clock,np.full(16,100.),clock[[0]],horizon=7)
        self.assertFalse(flat['valid'][0]);self.assertFalse(flat['up'][0])

    def test_profit_uses_later_entry_roundtrip_and_historical_funding(self):
        clock=np.arange(25,dtype=np.int64)*DAY_MS;bars=np.ones((25,9))*100
        ft=np.arange(0,25*DAY_MS,8*3600000,dtype=np.int64)+2;rates=np.full(len(ft),.001)
        t=long_profit_targets(clock,bars,clock[:1]+DAY_MS+60000,ft,rates,horizons=(3,))
        self.assertEqual(t['entry_at'][0],2*DAY_MS);self.assertEqual(t['exit_at'][0,0],5*DAY_MS)
        self.assertAlmostEqual(t['funding_proxy_returns'][0,0],.009)
        self.assertAlmostEqual(t['net_returns'][0,0],-.0014-.009)
        self.assertFalse(t['profitable'][0,0])

    def test_split_requires_last_head_mature_and_patterns_keep_order(self):
        decision=np.arange(40,dtype=np.int64)*DAY_MS+60000
        available=decision[:,None]+np.array([3,13])*DAY_MS
        train,test=mature_split(decision,available,np.ones((40,2),bool),25*DAY_MS,30*DAY_MS)
        self.assertTrue((available[train].max(1)<25*DAY_MS).all())
        np.testing.assert_array_equal(test,np.arange(25,30))
        np.testing.assert_array_equal(direction_patterns([[1,1,1],[0,0,0],[1,0,0],
            [0,0,1],[1,0,1],[0,1,0]]),np.arange(6))


if __name__=='__main__':unittest.main()
