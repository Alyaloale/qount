import unittest
import numpy as np

from qount.research.market_daily_states import LOCAL_STATES, centered_daily_state, daily_targets, local_daily_state, state_chunks, summarize_state_probabilities, training_mask
from qount.research_data.bars import Bar


class DailyStateTests(unittest.TestCase):
    def inputs(self, labels):
        return np.array(['BTC']*len(labels)),np.array(labels),np.arange(len(labels))*100+100

    def test_three_down_days_and_ten_up_days_are_not_forced_into_five(self):
        asset,state,clock=self.inputs([1]*3+[0]*10+[2])
        spells,chunks=state_chunks(asset,state,clock,maximum=5)
        self.assertEqual([c['length'] for c in chunks],[3,5,5,1])
        self.assertEqual([c['state'] for c in chunks],[1,0,0,2])
        self.assertEqual(chunks[1]['spell_id'],chunks[2]['spell_id'])
        self.assertEqual(spells[1]['length'],10)
        self.assertEqual(chunks[0]['available_at'],clock[3])

    def test_future_path_preserves_the_actual_switch_inside_a_window(self):
        asset,state,clock=self.inputs([2,1,1,1,0,0,0])
        targets=daily_targets(asset,state,clock,maximum=5)
        self.assertEqual(targets['future_state'][0].tolist(),[1,1,1,0,0])

    def test_incomplete_tail_is_masked_without_repeating_last_state(self):
        asset,state,clock=self.inputs([1,1,0])
        targets=daily_targets(asset,state,clock,maximum=5)
        self.assertEqual(targets['future_state'][0].tolist(),[1,0,-1,-1,-1])
        self.assertEqual(targets['future_mask'][0].tolist(),[True,True,False,False,False])
        spells,chunks=state_chunks(asset,state,clock,maximum=5)
        self.assertTrue(spells[-1]['right_censored'])
        self.assertIsNone(spells[-1]['completed_at'])

    def test_assets_are_never_connected_as_one_time_series(self):
        asset=np.array(['A','B','A','B']); state=np.array([0,1,2,3]); clock=np.array([100,100,200,200])
        target=daily_targets(asset,state,clock,maximum=3)
        self.assertEqual(target['future_state'][0].tolist(),[2,-1,-1])
        self.assertEqual(target['future_state'][1].tolist(),[3,-1,-1])

    def test_loss_mask_purges_each_target_by_its_actual_maturity(self):
        asset,state,clock=self.inputs([0,1,2,3,4])
        targets=daily_targets(asset,state,clock,maximum=4)
        self.assertEqual(training_mask(targets,350,horizon=4)[0].tolist(),[True,True,False,False])

    def test_completed_full_chunk_does_not_change_with_future_arrivals(self):
        asset,state,clock=self.inputs([0]*12)
        _,prefix=state_chunks(asset[:7],state[:7],clock[:7],maximum=5)
        _,full=state_chunks(asset,state,clock,maximum=5)
        self.assertEqual(prefix[0],full[0])

    def price_bars(self, returns):
        bars=[Bar(0,100,100.1,99.9,100)]
        for i,r in enumerate(returns,1):
            old=bars[-1].c;close=old*np.exp(r)
            bars.append(Bar(i*86400,old,max(old,close)*1.0001,min(old,close)*.9999,close))
        return bars

    def test_literal_local_window_has_n_plus_two_bars_and_ignores_outside(self):
        bars=self.price_bars([.01,-.02,.03,-.01,.02]*8)
        label=local_daily_state(bars,30,7)
        self.assertEqual((label['first_index'],label['last_index'],label['window_bars']),(22,30,9))
        changed=[Bar(b.t,b.o*3,b.h*3,b.l*3,b.c*3) if i<22 or i>30 else b for i,b in enumerate(bars)]
        self.assertEqual(label,local_daily_state(changed,30,7))

    def test_nearby_price_evidence_outweighs_the_same_old_evidence(self):
        first=self.price_bars([.15]+[-.02]*7)
        last=self.price_bars([-.02]*7+[.15])
        old=local_daily_state(first,8,7);recent=local_daily_state(last,8,7)
        self.assertEqual(LOCAL_STATES[old['state']],'downtrend')
        self.assertEqual(LOCAL_STATES[recent['state']],'uptrend')

    def test_not_enough_local_history_keeps_unknown(self):
        bars=self.price_bars([.01]*10)
        self.assertEqual(local_daily_state(bars,7,7)['state'],-1)
        self.assertGreaterEqual(local_daily_state(bars,8,7)['state'],0)

    def test_centered_label_reads_exactly_two_n_bars(self):
        bars=self.price_bars([.01,-.02,.03,-.01,.02]*12)
        label=centered_daily_state(bars,30,7)
        self.assertEqual((label['first_index'],label['last_index'],label['window_bars']),(24,37,14))
        self.assertEqual(label['mature_index'],37)
        changed=[Bar(b.t,b.o*4,b.h*4,b.l*4,b.c*4) if i<24 or i>37 else b for i,b in enumerate(bars)]
        self.assertEqual(label,centered_daily_state(changed,30,7))

    def test_future_context_is_allowed_only_in_labels_not_causal_inputs(self):
        bars=self.price_bars([.01]*60)
        changed=bars[:31]+self.price_bars([-.03]*30)[1:]
        self.assertEqual(local_daily_state(bars,30,7),local_daily_state(changed,30,7))
        self.assertNotEqual(centered_daily_state(bars,30,7)['features'],centered_daily_state(changed,30,7)['features'])

    def test_centered_tail_waits_for_future_confirmation(self):
        bars=self.price_bars([.01]*40)
        self.assertEqual(centered_daily_state(bars,34,7)['state'],-1)
        label=centered_daily_state(bars,33,7)
        self.assertGreaterEqual(label['state'],0)
        next_period=centered_daily_state(bars,26+7,7)
        self.assertEqual(next_period['mature_index'],26+14)

    def test_spells_accept_unmatured_labels_at_cache_tail(self):
        asset,state,clock=self.inputs([-1,0,0,1,-1,-1])
        maturity=np.where(state>=0,clock+100,0)
        spells,chunks=state_chunks(asset,state,maturity,maximum=5)
        self.assertTrue(spells[-1]['right_censored'])
        self.assertEqual(sum(c['length'] for c in chunks),3)

    def test_large_wicks_and_tiny_drift_are_observed_chop_not_uncertainty(self):
        bars=self.price_bars([.001]*60)
        bars=[Bar(b.t,b.o,max(b.o,b.c)*1.08,min(b.o,b.c)*.92,b.c) for b in bars]
        self.assertNotIn('transition',LOCAL_STATES)
        self.assertEqual(len(LOCAL_STATES),5)
        self.assertEqual(LOCAL_STATES[centered_daily_state(bars,30,7)['state']],'low_efficiency_chop')
        self.assertEqual(LOCAL_STATES[local_daily_state(bars,30,7)['state']],'low_efficiency_chop')

    def test_uncertain_forecast_is_output_status_and_preserves_five_classes(self):
        probabilities=dict(zip(LOCAL_STATES,[.30,.25,.20,.15,.10]))
        result=summarize_state_probabilities(probabilities)
        self.assertEqual(result['status'],'uncertain')
        self.assertIsNone(result['predicted_state'])
        self.assertEqual(len(probabilities),5)
        self.assertEqual(sum(probabilities.values()),1.)

    def test_confident_forecast_and_legacy_probability_schema(self):
        probabilities=dict(zip(LOCAL_STATES,[.80,.05,.05,.05,.05]))
        result=summarize_state_probabilities(probabilities)
        self.assertEqual(result['status'],'confident')
        self.assertEqual(result['predicted_state'],'uptrend')
        with self.assertRaises(ValueError):
            summarize_state_probabilities(dict(probabilities,transition=0.))


if __name__=='__main__':
    unittest.main()
