import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/research'))
from analyze_market_state_edge import conditioned_matrix,regress_payoffs,transition_payoffs
from qount.research.market_state_scores import STATE_NAMES


class MarketStateEdgeTests(unittest.TestCase):
    def test_conditioned_matrix_preserves_known_context(self):
        x=np.arange(126,dtype=float).reshape(2,63)
        values=conditioned_matrix(x,np.array([0,5]),np.array([5,1]))
        self.assertEqual(values.shape,(2,243));np.testing.assert_array_equal(values[:,:63],x)
        self.assertEqual(values[0,63+5],1);self.assertEqual(values[1,63+1],1)

    def test_payoff_regression_does_not_read_test_states_or_returns(self):
        rng=np.random.default_rng(31);n=122
        data=dict(X=rng.normal(size=(n,63)),current_state=rng.integers(0,11,n),outcome=rng.integers(0,11,n),
                  known_at=np.arange(n),return_available=np.ones((n,3),np.int64))
        returns=rng.normal(size=(n,3));train=np.arange(100);test=np.arange(100,n)
        before,_=regress_payoffs(data,returns,train,test,conditioned=True)
        data['outcome'][test]=999;returns[test]=999999
        after,_=regress_payoffs(data,returns,train,test,conditioned=True)
        np.testing.assert_allclose(before,after,rtol=0,atol=0)

    def test_transition_payoff_ignores_unmatured_test_returns(self):
        data=dict(current_state=np.zeros(5,int),outcome=np.zeros(5,int),known_at=np.array([1,1,2,2,3]))
        values=np.ones((5,3));base=dict(mean=np.zeros((len(STATE_NAMES),3)))
        a=transition_payoffs(data,values,base,np.arange(4),np.array([4]))
        values[4]=1e8
        b=transition_payoffs(data,values,base,np.arange(4),np.array([4]))
        np.testing.assert_array_equal(a,b)
        self.assertAlmostEqual(a[0,0,0],2/52)


if __name__=='__main__':unittest.main()
