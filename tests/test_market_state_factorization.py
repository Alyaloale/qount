import unittest

import numpy as np

from qount.research.market_state_factorization import (
    causal_inputs, factored_window, merge_five, project_five_probabilities, purged_quarter,
)
from qount.research_data.bars import Bar


class StateFactorizationTests(unittest.TestCase):
    def bars(self,length=100):
        price=100.;result=[]
        for i in range(length):
            close=price*np.exp(.003+.004*np.sin(i*.7))
            result.append(Bar(i*86400,price,max(price,close)*1.005,min(price,close)*.995,close))
            price=close
        return result

    def test_merge_and_probability_projection_define_the_same_coarse_task(self):
        self.assertEqual(merge_five([-1,0,1,2,3,4]).tolist(),[-1,0,1,2,2,2])
        projected=project_five_probabilities(np.array([[.1,.2,.3,.15,.25]]))
        np.testing.assert_allclose(projected,[[.1,.2,.7]])
        self.assertAlmostEqual(float(projected.sum()),1.)

    def test_upward_and_compression_can_coexist(self):
        bars=[];price=100.
        for i in range(28):
            close=price*np.exp(.003);wick=.0001 if abs(i-13)<=5 else .02
            bars.append(Bar(i,price,close*(1+wick),price*(1-wick),close));price=close
        label=factored_window(bars,14)
        self.assertEqual(label['state'],0)
        self.assertEqual(label['attributes'][1],1.)
        self.assertTrue(0<=label['attributes'][3]<=1)

    def test_efficiency_gate_does_not_silently_reenter_main_state(self):
        bars=self.bars(28)
        first=factored_window(bars,14,efficiency_threshold=.01)
        second=factored_window(bars,14,efficiency_threshold=.8)
        self.assertEqual(first['state'],second['state'])
        np.testing.assert_allclose(first['attributes'],second['attributes'])

    def test_future_price_changes_cannot_change_model_inputs(self):
        bars=self.bars();changed=bars[:51]+[Bar(b.t,b.o*2,b.h*2,b.l*2,b.c*2) for b in bars[51:]]
        np.testing.assert_array_equal(causal_inputs(bars,50,14),causal_inputs(changed,50,14))
        self.assertNotEqual(factored_window(bars[37:65],14)['attributes'].tolist(),
                            factored_window(changed[37:65],14)['attributes'].tolist())

    def test_past_two_n_history_is_required_without_filling(self):
        bars=self.bars()
        self.assertIsNone(causal_inputs(bars,26,14))
        self.assertTrue(np.isfinite(causal_inputs(bars,27,14)).all())

    def test_quarters_purge_unmatured_targets_and_do_not_overlap(self):
        rows=np.arange(6);known=np.array([10,20,30,40,50,60]);maturity=known+15
        train,test=purged_quarter(rows,known,maturity,40,60)
        self.assertEqual(train.tolist(),[0,1])
        self.assertEqual(test.tolist(),[3,4])
        _,next_test=purged_quarter(rows,known,maturity,60,80)
        self.assertEqual(len(np.intersect1d(test,next_test)),0)

    def test_projection_rejects_invalid_probabilities(self):
        with self.assertRaises(ValueError):project_five_probabilities([[.1,.2,.3,-.1,.5]])


if __name__=='__main__':unittest.main()
