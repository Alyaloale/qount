import math
import unittest
from qount.research.ashare_statistics import calendar_block_mean_interval, decision_mask

class AshareStatisticsTests(unittest.TestCase):
    def test_uniform_terminal_maturity_uses_latest_exit(self):
        self.assertEqual(decision_mask(23),[True]+[False]*22)
        self.assertFalse(any(decision_mask(22)))
    def test_exact_exit_boundary_is_purged(self):
        mask=decision_mask(200,[100])
        self.assertTrue(mask[77]);self.assertFalse(mask[78]);self.assertFalse(mask[99])
    def test_embargo_covers_boundary_through_plus_21(self):
        mask=decision_mask(200,[100])
        self.assertFalse(mask[100]);self.assertFalse(mask[121]);self.assertTrue(mask[122])
    def test_boundary_validation(self):
        for boundaries in [[0],[200],[100,100]]:
            with self.assertRaises(ValueError):decision_mask(200,boundaries)
    def test_unknown_calendar_positions_are_not_compressed(self):
        r=calendar_block_mean_interval([1,None,None,None,2,None],block_sessions=2,samples=100,seed=2)
        self.assertEqual(r['calendar_positions'],6);self.assertEqual(r['unknown_positions'],4)
        self.assertLess(r['nonempty_draws'],100)
        self.assertFalse(r['unknown_gate_resolved_by_interval'])
    def test_constant_series_interval(self):
        r=calendar_block_mean_interval([.1]*120,samples=100)
        self.assertAlmostEqual(r['mean_observed'],.1)
        for v in r['mean_95pct_interval_conditional']:self.assertAlmostEqual(v,.1)
    def test_all_unknown_preserves_requested_draw_count(self):
        r=calendar_block_mean_interval([None]*100,samples=20)
        self.assertEqual(r['nonempty_draws'],0);self.assertIsNone(r['mean_95pct_interval_conditional'])
        self.assertEqual(r['unknown_positions'],100)
    def test_nonfinite_values_count_as_unknown(self):
        r=calendar_block_mean_interval([1,float('nan'),float('inf'),None],block_sessions=2,samples=20)
        self.assertEqual(r['observed_positions'],1);self.assertEqual(r['unknown_positions'],3)
    def test_seed_determinism(self):
        values=[math.sin(i) for i in range(100)]
        self.assertEqual(calendar_block_mean_interval(values,samples=100),calendar_block_mean_interval(values,samples=100))
    def test_frozen_full_width_does_not_resample_stock_rows(self):
        r=calendar_block_mean_interval([1,2,3],block_sessions=60,samples=20)
        self.assertEqual(r['mean_95pct_interval_conditional'],[2,2]);self.assertEqual(r['effective_block_sessions'],3)
        self.assertFalse(r['complete_plan_can_be_certified_from_interval_alone'])
    def test_invalid_sample_and_block_shape(self):
        for kwargs in [{'samples':0},{'block_sessions':0}]:
            with self.assertRaises(ValueError):calendar_block_mean_interval([1],**kwargs)
        with self.assertRaises(ValueError):calendar_block_mean_interval([])

if __name__=='__main__':unittest.main()
