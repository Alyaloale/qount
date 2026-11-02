import unittest
import numpy as np
from qount.research.wallet_consensus import consensus,persistent_asset_profile,position_votes,relative_addition_targets,snapshot_anchored_states,target_signals


class WalletConsensusTest(unittest.TestCase):
    def test_relative_ranking_abstains_on_ties_and_missing_activity(self):
        target,_=relative_addition_targets([[5,5,0],[3,5,3],[1,1,1]],[[1,1,0],[1,1,1],[1,1,1]])
        np.testing.assert_array_equal(target,[[1,0,0],[0,0,0],[-1,0,0]])

    def test_relative_ranking_does_not_normalize_with_future_observations(self):
        positive=[[5,1],[2,8],[1,1]];negative=[[1,1],[1,1],[1,4]]
        old,_=relative_addition_targets(np.asarray(positive)[:,:1],np.asarray(negative)[:,:1])
        full,_=relative_addition_targets(positive,negative)
        np.testing.assert_array_equal(old,full[:,:1])

    def test_snapshot_gap_withdraws_votes_at_observation_not_before(self):
        rows=[dict(time_ms=10,coin='BTC',before='2',after='3'),
              dict(time_ms=30,coin='BTC',before='9',after='10')]
        anchored,failures=snapshot_anchored_states(dict(states=rows,errors=[]),{'BTC':2},0)
        votes,held,valid=position_votes(anchored,[10,20,30,40],lookback_ms=10)
        np.testing.assert_array_equal(votes,[1,0,0,0])
        np.testing.assert_array_equal(held,[1,1,0,0])
        np.testing.assert_array_equal(valid,[True,True,False,False])
        self.assertEqual(failures[0]['time_ms'],30)
        prefix,_=snapshot_anchored_states(dict(states=rows[:1],errors=[]),{'BTC':2},0)
        for a,b in zip(position_votes(prefix,[10,20],lookback_ms=10),position_votes(anchored,[10,20],lookback_ms=10)):
            np.testing.assert_array_equal(a,b)

    def test_later_start_position_cannot_override_snapshot(self):
        rows=[dict(time_ms=20,coin='BTC',before='9',after='10')]
        anchored,failures=snapshot_anchored_states(dict(states=rows,errors=[]),{'BTC':2},0)
        self.assertEqual(anchored[0]['after'],'2')
        self.assertEqual(len(failures),1)

    def test_reductions_are_not_new_risk_and_flips_are(self):
        states=[dict(time_ms=0,after="-10"),dict(time_ms=10,after="-5"),
                dict(time_ms=20,after="2"),dict(time_ms=30,after="1")]
        votes,holdings,valid=position_votes(states,[10,20,30],lookback_ms=10)
        np.testing.assert_array_equal(votes,[0,1,0])
        np.testing.assert_array_equal(holdings,[-1,1,1])
        self.assertTrue(valid.all())

    def test_unknown_past_is_not_a_flat_position(self):
        votes,holdings,valid=position_votes([dict(time_ms=10,after="2")],[10,20],lookback_ms=20)
        np.testing.assert_array_equal(votes,[0,0])
        self.assertFalse(valid.any())
        np.testing.assert_array_equal(holdings,[1,1])

    def test_two_votes_and_strict_majority_required(self):
        target,_,_=consensus([[1,1,1,-1],[0,1,1,-1],[0,0,-1,1],[0,0,-1,0]])
        np.testing.assert_array_equal(target,[0,1,0,-1])

    def test_appending_future_states_does_not_change_past_votes(self):
        old=[dict(time_ms=0,after="0"),dict(time_ms=10,after="2")]
        full=old+[dict(time_ms=100,after="-99")]
        for a,b in zip(position_votes(old,[20,30],lookback_ms=10),position_votes(full,[20,30],lookback_ms=10)):
            np.testing.assert_array_equal(a,b)

    def test_only_target_changes_emit_orders(self):
        signals=target_signals([0,1,2,3,4],[0,1,1,0,-1])
        self.assertEqual([(s["time_ms"],s["target"]) for s in signals],[(0,0),(1,1),(3,0),(4,-1)])

    def test_unclosed_position_has_observed_duration_without_future_exit(self):
        day=86400000
        states=[dict(time_ms=day,before="2",after="3"),dict(time_ms=10*day,before="3",after="4")]
        p=persistent_asset_profile(states,start_ms=0,split_ms=28*day)
        self.assertTrue(p["eligible"])
        self.assertEqual(p["right_censored_hours"],27*24)
        future=states+[dict(time_ms=29*day,before="4",after="0")]
        self.assertEqual(p,persistent_asset_profile(future,start_ms=0,split_ms=28*day))

    def test_recent_first_observation_is_not_long_history(self):
        day=86400000
        p=persistent_asset_profile([dict(time_ms=27*day,before="2",after="3")],start_ms=0,split_ms=28*day)
        self.assertFalse(p["eligible"])
        self.assertEqual(p["observed_days"],1)


if __name__=="__main__":
    unittest.main()
