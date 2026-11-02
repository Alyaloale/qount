import unittest

import numpy as np

from qount.research.market_model_profit import replay_asset
from qount.research.market_state_scores import STATE_NAMES,FEATURES,action_scores,action_probability_scores,state_feature_matrix,past_score_threshold,payoff_table,unit_payoff


class MarketStateScoresTests(unittest.TestCase):
    def test_full_distribution_and_payoff_magnitude_determine_action(self):
        p=np.zeros((1,len(STATE_NAMES)));p[0,0]=.9;p[0,1]=.1
        mu=np.zeros((len(STATE_NAMES),2));mu[0]=[.1,.3];mu[1]=[-2.,-.1]
        expected,score=action_scores(p,dict(mean=mu,error=np.zeros_like(mu)))
        self.assertLess(expected[0,0],0);self.assertGreater(score[0,1],0)
        with self.assertRaises(ValueError):action_scores(p*.5,dict(mean=mu,error=np.zeros_like(mu)))

    def test_threshold_uses_only_prior_forecasts_and_requires_support(self):
        scores=np.arange(40)/100;times=np.arange(40)
        cut=past_score_threshold(scores,times,40)
        other=past_score_threshold(np.r_[scores,999],np.r_[times,40],40)
        self.assertEqual(cut,other);self.assertGreaterEqual(cut,.1)
        self.assertTrue(np.isinf(past_score_threshold(scores,times,10)))

    def test_state_probability_scores_do_not_call_shock_an_entry_state(self):
        p=np.zeros((2,len(STATE_NAMES)));p[0,STATE_NAMES.index('up_trend')]=.6
        p[0,STATE_NAMES.index('failed_down_breakout')]=.2;p[0,STATE_NAMES.index('shock')]=.2
        p[1,STATE_NAMES.index('shock')]=1.
        v=action_probability_scores(p);self.assertAlmostEqual(v[0,0],80.)
        np.testing.assert_array_equal(v[1],np.zeros(3))

    def test_inference_needs_no_future_labels_and_rejects_future_features(self):
        parent=dict(feature_names=np.array(FEATURES),X=np.zeros((1,len(FEATURES))),asset=np.array(['BTCUSDT']),
            state=np.array(['range']),known_at=np.array([10]),feature_available_at=np.zeros((1,len(FEATURES)),int))
        matrix=state_feature_matrix(parent,[0],['BTCUSDT']);self.assertEqual(matrix.shape[0],1)
        parent['feature_available_at'][0,0]=11
        with self.assertRaisesRegex(ValueError,'future_feature'):state_feature_matrix(parent,[0],['BTCUSDT'])

    def test_same_date_duplicates_do_not_create_independent_payoff_evidence(self):
        states=np.array([0,1,0,1]);returns=np.array([[1.],[2.],[2.],[3.]]);times=np.array([1,1,2,2])
        a=payoff_table(states,returns,times)
        b=payoff_table(np.tile(states,10),np.tile(returns,(10,1)),np.tile(times,10))
        np.testing.assert_allclose(a['mean'],b['mean']);np.testing.assert_equal(a['date_counts'],b['date_counts'])

    def test_unit_label_matches_portfolio_trade_and_waits_for_full_horizon(self):
        bars=np.array([[0,100,101,99,100,100,999],[1000,100,101,99,100,100,1999],
                       [2000,110,111,109,110,100,2999],[3000,110,111,109,110,100,3999]],float)
        d=dict(known_at=500,entry_at=1000,side=1,stop=90,target=None,fraction=1.,max_bars=1,capacity=10000)
        rules=dict(fee=.0005,slippage=.0002,tick=.01,step=.01,min_qty=.01,min_notional=5.)
        events=(np.array([1500,2000]),np.array([1.,1.1]))
        value=unit_payoff(bars,1,d,events,rules)
        funding=[dict(fundingTime=int(t),fundingRate=str(v/100),markPrice='100') for t,v in zip(*events)]
        trade=replay_asset(bars,[d],funding,initial=1000,rules=rules)['trades'][0]
        self.assertAlmostEqual(value['net_unit'],trade['net_pnl']/trade['quantity'])
        self.assertEqual(value['available_at'],2999+60001)

    def test_bad_delayed_entry_is_zero_not_removed(self):
        bars=np.array([[0,100,101,99,100,100,999],[1000,80,81,79,80,100,1999],
                       [2000,80,81,79,80,100,2999]],float)
        d=dict(side=1,stop=90,target=110,max_bars=1)
        v=unit_payoff(bars,1,d,(np.array([],int),np.array([])),dict(fee=.0005,slippage=.0002,tick=.01))
        self.assertEqual(v['net_unit'],0);self.assertFalse(v['filled'])


if __name__=='__main__':unittest.main()
