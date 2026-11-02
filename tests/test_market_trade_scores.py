import unittest

import numpy as np
from qount.research.market_model_profit import position_size

from qount.research.market_trade_scores import (
    outcome_code,context_matrix,fit_trade_heads,predict_trade_heads,
    fit_score_calibration,calibrated_score,
)


class MarketTradeScoresTests(unittest.TestCase):
    def history(self,n=80):
        return [dict(known_at=i,maturity=i+2,raw=.1+i/100,actual=-.5+i/200) for i in range(n)]

    def test_outcome_definitions_include_cost_and_unusual_funding(self):
        self.assertEqual(outcome_code(dict(filled=False,net_unit=0,reason='no_fill')),0)
        self.assertEqual(outcome_code(dict(filled=True,net_unit=-1,reason='stop_both')),1)
        self.assertEqual(outcome_code(dict(filled=True,net_unit=1,reason='target')),2)
        self.assertEqual(outcome_code(dict(filled=True,net_unit=1,reason='stop')),3)
        self.assertEqual(outcome_code(dict(filled=True,net_unit=-1,reason='target')),4)

    def test_context_does_not_use_future_fill_metadata(self):
        d=dict(side=1,stop=90,target=120,max_bars=5)
        rules=dict(fee=.0005,slippage=.0002)
        a=context_matrix(np.zeros(63),100,d,0,rules,2)
        b=context_matrix(np.zeros(63),100,dict(d,entry_price=1e9,exit_price=0,outcome=4),0,rules,2)
        np.testing.assert_array_equal(a,b);self.assertEqual(len(a),75)

    def test_execution_r_matches_sizing_after_entry_gap(self):
        # Signal at 100 very close to a 99.99 stop; actual entry gaps to110.
        entry=110.;stop=99.99;rules=dict(fee=.0005,slippage=.0002,step=1e-8,min_qty=1e-8,min_notional=0.)
        per_unit_risk=abs(entry-stop)+entry*(2*rules['fee']+2*rules['slippage'])
        qty=position_size(1000,entry,stop,1.,rules,1e9)
        net_unit=2.;realized_R=net_unit/per_unit_risk
        self.assertAlmostEqual(qty*net_unit/(1000*.01),realized_R,places=7)
        self.assertLess(realized_R,1.)

    def test_calibration_excludes_unmatured_outcomes(self):
        hist=self.history();before=fit_score_calibration(hist,100)
        after=fit_score_calibration(hist+[dict(known_at=1,maturity=100,raw=100,actual=1000),
            dict(known_at=2,maturity=101,raw=100,actual=1000)],100)
        self.assertEqual(before,after)

    def test_repeated_assets_are_not_independent_calibration_dates(self):
        rows=[dict(known_at=1,maturity=2,raw=.5,actual=1)]*500
        self.assertFalse(fit_score_calibration(rows,3)['ready'])
        original=self.history();a=fit_score_calibration(original,100);b=fit_score_calibration(original*3,100)
        np.testing.assert_allclose(a['coefficients'],b['coefficients'],rtol=1e-12,atol=1e-12)

    def test_calibration_blocks_optimistic_raw_scores_and_caps_extrapolation(self):
        model=fit_score_calibration(self.history(),100)
        mean,lower=calibrated_score(model,np.array([.8,10.,100.]))
        self.assertTrue(np.all(mean<0));self.assertTrue(np.all(lower<=mean))
        self.assertEqual(mean[1],mean[2])

    def test_empty_calibration_abstains(self):
        mean,lower=calibrated_score(fit_score_calibration([],100),np.array([100.]))
        self.assertTrue(np.isnan(mean[0]));self.assertTrue(np.isnan(lower[0]))

    def test_positive_supported_tail_can_qualify_but_unsupported_tail_cannot(self):
        history=[dict(known_at=i,maturity=i+1,raw=i/100,actual=.5+i/100) for i in range(120)]
        supported=fit_score_calibration(history,200,threshold=.7)
        self.assertTrue(supported['tail_ready']);self.assertGreaterEqual(supported['tail_dates'],20)
        mean,lower=calibrated_score(supported,np.array([1.]))
        self.assertGreater(mean[0],.1);self.assertGreater(lower[0],0)
        unsupported=fit_score_calibration(history,200,threshold=1.15)
        self.assertFalse(unsupported['tail_ready'])

    def test_trade_distribution_and_expected_payoffs_are_consistent(self):
        rng=np.random.default_rng(17);n=180;x=rng.normal(size=(n,75));actions=np.arange(n)%3;outcomes=np.arange(n)%5
        returns=np.select([outcomes==0,outcomes==1,outcomes==2,outcomes==3],[0.,-1.,1.5,.5],default=-.3)
        model=fit_trade_heads(x,returns,outcomes,actions,np.arange(n)//3)
        p=predict_trade_heads(model,x[:12],actions[:12]);np.testing.assert_allclose(p['probabilities'].sum(1),1)
        np.testing.assert_allclose(p['path_mean'],np.sum(p['probabilities']*p['conditional_net_R'],axis=1))
        self.assertTrue(np.all(p['conditional_net_R'][:,0]==0))
        self.assertTrue(np.all(p['conditional_net_R'][:,[1,4]]<=0))
        self.assertTrue(np.all(p['conditional_net_R'][:,[2,3]]>=0))


if __name__=='__main__':unittest.main()
