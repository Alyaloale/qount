import unittest
from unittest.mock import patch

import numpy as np

from qount.research.market_daily_states import centered_daily_state
from qount.research.market_state_boundaries import swing_pivots, window_refinement
from qount.research_data.bars import Bar


class MarketBoundaryTests(unittest.TestCase):
    def flat(self):
        return [Bar(i,100,101,99,100) for i in range(28)]

    def evidence(self,state,ratio=.60):
        return dict(state=state,features=[.2,.05,ratio,3,.01,.001])

    def fake_local(self,window,state=3,ratio=.60,neighbors=None):
        labels=neighbors if neighbors is not None else [2,2,2,state,2,2,2]
        evidence=[self.evidence(state,ratio)]+[self.evidence(s,ratio) for s in labels]
        with patch('qount.research.market_state_boundaries.centered_window_evidence',side_effect=evidence):
            return window_refinement(window,14)

    def test_weak_short_nondirectional_island_is_absorbed(self):
        result=self.fake_local(self.flat())
        self.assertEqual(result['noise_only'],2)
        self.assertEqual(result['noise_reason'],'small_marginal_nondirectional_island')

    def test_short_but_large_price_move_is_not_removed_as_noise(self):
        window=self.flat();window[13]=Bar(13,100,111,99,110)
        result=self.fake_local(window)
        self.assertEqual(result['noise_only'],3)
        self.assertIsNone(result['noise_reason'])

    def test_strong_contraction_is_not_removed_just_for_being_short(self):
        result=self.fake_local(self.flat(),ratio=.4)
        self.assertEqual(result['noise_only'],3)

    def test_noise_filter_does_not_create_new_compression_inside_rotation(self):
        result=self.fake_local(self.flat(),state=2,neighbors=[3,3,3,2,3,3,3])
        self.assertEqual(result['noise_only'],2)

    def test_short_trend_is_not_subject_to_nondirectional_noise_filter(self):
        for state in (0,1):
            result=self.fake_local(self.flat(),state=state)
            self.assertEqual(result['noise_only'],state)

    def test_one_sided_boundary_is_not_a_confirmed_noise_sandwich(self):
        result=self.fake_local(self.flat(),neighbors=[3,3,3,3,2,2,2])
        self.assertEqual(result['noise_only'],3)

    def test_peak_day_belongs_to_preceding_leg_and_next_return_to_new_leg(self):
        _,legs=swing_pivots(np.log([100,104,108,112,108,104,100,104,108]),.03)
        def owner(day):
            return next(leg['side'] for leg in legs if leg['start']<day<=leg['end'])
        self.assertEqual(owner(3),1)
        self.assertEqual(owner(4),-1)
        self.assertEqual(owner(6),-1)
        self.assertEqual(owner(7),1)

    def peak_window(self):
        prices=100*np.exp(np.r_[np.arange(14)*.005,.065-np.arange(1,15)*.005])
        return [Bar(i,float(p),float(p*1.001),float(p*.999),float(p)) for i,p in enumerate(prices)]

    def test_price_pivot_cannot_create_trend_without_existing_evidence_core(self):
        result=self.fake_local(self.peak_window(),state=2,neighbors=[2]*7)
        self.assertEqual(result['boundary_only'],0)
        self.assertEqual(result['supported_boundary'],2)

    def test_clear_peak_can_extend_supported_preceding_trend(self):
        result=self.fake_local(self.peak_window(),state=2,neighbors=[0,0,0,2,1,1,1])
        self.assertEqual(result['supported_boundary'],0)

    def test_pair_boundary_only_relocates_an_existing_two_state_edge(self):
        result=self.fake_local(self.peak_window(),state=2,neighbors=[0,0,0,2,2,2,2])
        self.assertEqual(result['pair_boundary'],0)

    def test_pair_price_indices_do_not_overwrite_diagnostic_island_length(self):
        result=self.fake_local(self.peak_window(),state=2,neighbors=[0,0,0,2,2,2,2])
        self.assertEqual(result['bounded_run_length'],4)

    def test_pair_boundary_does_not_intervene_in_three_state_mix(self):
        result=self.fake_local(self.peak_window(),state=2,neighbors=[0,0,2,2,1,1,1])
        self.assertEqual(result['pair_boundary'],2)

    def test_flat_pause_does_not_have_a_price_extremum_boundary(self):
        result=self.fake_local(self.flat(),state=2,neighbors=[0,0,0,2,2,2,2])
        self.assertEqual(result['pair_boundary'],2)

    def test_baseline_geometry_matches_existing_labeler(self):
        window=self.peak_window()
        self.assertEqual(window_refinement(window,14)['baseline'],centered_daily_state(window,13,14)['state'])

    def test_incomplete_window_is_rejected(self):
        with self.assertRaises(ValueError):window_refinement(self.flat()[:-1],14)


if __name__=='__main__':unittest.main()
