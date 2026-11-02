import unittest
from unittest.mock import patch

import numpy as np

from qount.research.market_state_transition import phase_targets


class TransitionTargetsTests(unittest.TestCase):
    def test_initial_unknown_age_and_short_spells_are_not_invented_or_removed(self):
        state=np.array([2,2,0,0,2,1,1,1,1]);previous=np.r_[2,state[:-1]]
        t=phase_targets(np.array(['A']*len(state)),state,previous)
        self.assertEqual(t['phase'].tolist(),[0,0,1,1,3,2,2,2,0])
        self.assertEqual(t['phase_valid'].tolist(),[False,False,True,True,True,True,True,True,True])

    def test_future_label_changes_do_not_change_earlier_phase_supervision(self):
        state=np.array([2,0,0,0,2,2]);previous=np.r_[2,state[:-1]];asset=np.array(['A']*6)
        before=phase_targets(asset,state,previous)
        changed=state.copy();changed[4:]=1;after=phase_targets(asset,changed,np.r_[2,changed[:-1]])
        for name in ('phase','phase_valid','age'):np.testing.assert_array_equal(before[name][:4],after[name][:4])

    def test_mixture_is_three_normalized_states_without_true_prior_state_input(self):
        import torch
        from qount.research.market_state_transition import TypedTransitionGRU
        model=TypedTransitionGRU(7).eval()
        p,phase,reg,cont=model(torch.zeros(5,14,9),torch.zeros(5,dtype=torch.long))
        self.assertEqual(tuple(p.shape),(5,3));self.assertEqual(tuple(phase.shape),(5,4));self.assertEqual(tuple(reg.shape),(5,2))
        torch.testing.assert_close(p.sum(1),torch.ones(5))
        torch.testing.assert_close(p,phase[:,:1]*cont+phase[:,1:])

    def test_independent_phase_model_cannot_change_state_probability(self):
        import torch
        from qount.research.market_state_neural import OHLCVGRU,forecast
        from qount.research.market_state_transition import TypedTransitionGRU,infer_state_with_transition
        torch.manual_seed(17);base=OHLCVGRU(7,channels=9);typed=TypedTransitionGRU(7)
        cp=dict(architecture='state_with_transition_gru',model=base.state_dict(),transition_model=typed.state_dict(),
            mean=np.zeros(9,np.float32),scale=np.ones(9,np.float32),target_mean=np.zeros(2,np.float32),
            target_scale=np.ones(2,np.float32),assets=7,hidden=32,input_channels=9,input_length=14)
        x=np.zeros((2,14,9),np.float32);asset=np.array([0,1],np.int64)
        expected=forecast(base,torch.from_numpy(x),torch.from_numpy(asset))
        output=infer_state_with_transition(cp,x,asset)
        np.testing.assert_array_equal(output['state_probabilities'],expected)
        np.testing.assert_allclose(output['phase_probabilities'].sum(1),1,atol=1e-6)
        self.assertIsNone(output['early_trend_alert'])

    def test_target_context_is_reconstructed_from_retained_bundle_windows(self):
        from qount.research.market_state_transition import label_price_context
        bars=np.ones((4,9));bars[:,:4]=np.arange(100,104)[:,None]
        data=dict(two_n_source_rows=np.array([[0,1,2]]),two_n_raw_market=bars[None,:3],
            label_context_source_rows=np.array([[0,1,2,3]]))
        latest=dict(two_n_source_rows=np.array([[1,2,3]]),two_n_raw_market=bars[None,1:])
        with patch('qount.research.market_state_transition.validate_market_inputs'):
            np.testing.assert_array_equal(label_price_context(data,latest),bars[None,:,:4])
            latest['two_n_raw_market']=latest['two_n_raw_market'].copy();latest['two_n_raw_market'][0,0,:4]+=1
            with self.assertRaisesRegex(ValueError,'conflicting'):label_price_context(data,latest)

    def test_missing_future_target_prices_are_rejected_not_filled(self):
        from qount.research.market_state_transition import label_price_context
        data=dict(two_n_source_rows=np.array([[0,1]]),two_n_raw_market=np.ones((1,2,9)),
            label_context_source_rows=np.array([[0,1,2]]))
        latest=dict(two_n_source_rows=np.array([[0,1]]),two_n_raw_market=np.ones((1,2,9)))
        with patch('qount.research.market_state_transition.validate_market_inputs'):
            with self.assertRaisesRegex(ValueError,'incomplete'):label_price_context(data,latest)


if __name__=='__main__':unittest.main()
