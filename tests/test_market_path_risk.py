"""Coarse edge uncertainty, exact minute refinement and continuous geometry."""
import unittest
import numpy as np
from scipy.special import ndtr

from qount.research.market_path_risk import (
    HOUR_MS,MINUTE_MS,aligned_path_label,validate_candle,continuous_range_probability,
)


def candle(t,interval=HOUR_MS,high=101.,low=99.,open_=100.,close=100.):
    return np.array([t,open_,high,low,close,10,t+interval-1],float)


class MarketPathRiskTest(unittest.TestCase):
    def test_predecision_and_posthorizon_extremes_are_uncertain_not_false_labels(self):
        hours={i*HOUR_MS:candle(i*HOUR_MS) for i in range(3)}
        hours[0][2]=120;hours[2*HOUR_MS][3]=80
        result=aligned_path_label(hours,MINUTE_MS,2*HOUR_MS+MINUTE_MS,90,110)
        self.assertTrue(result['complete']);self.assertEqual(result['label'],-1)
        minutes={t:candle(t,MINUTE_MS) for t in range(0,3*HOUR_MS,MINUTE_MS)}
        minutes[0][2]=120  # Before the decision, hence excluded.
        minutes[2*HOUR_MS+MINUTE_MS][3]=80  # After the horizon, also excluded.
        fine=aligned_path_label(hours,MINUTE_MS,2*HOUR_MS+MINUTE_MS,90,110,minutes=minutes)
        self.assertEqual(fine['label'],1);self.assertEqual(fine['refined_cells'],2)
        self.assertEqual(fine['available_at'],3*3600+60)

    def test_full_future_breach_and_observed_edge_endpoint_certify_failure(self):
        hours={i*HOUR_MS:candle(i*HOUR_MS) for i in range(3)}
        hours[HOUR_MS][2]=120
        self.assertEqual(aligned_path_label(hours,MINUTE_MS,2*HOUR_MS+MINUTE_MS,90,110)['label'],0)
        hours[HOUR_MS][2]=101;hours[2*HOUR_MS][1]=115;hours[2*HOUR_MS][2]=116
        self.assertEqual(aligned_path_label(hours,MINUTE_MS,2*HOUR_MS+MINUTE_MS,90,110)['label'],0)

    def test_missing_horizon_stays_missing_even_if_an_earlier_breach_is_seen(self):
        hours={0:candle(0,high=120)}
        result=aligned_path_label(hours,MINUTE_MS,3*HOUR_MS,90,110)
        self.assertFalse(result['complete']);self.assertEqual(result['label'],-1)
        self.assertEqual(result['reason'],'missing_hours')

    def test_whole_hour_schedule_needs_no_guess_and_future_append_does_not_change_it(self):
        hours={i*HOUR_MS:candle(i*HOUR_MS) for i in range(5)}
        result=aligned_path_label(hours,HOUR_MS,4*HOUR_MS,90,110)
        self.assertEqual(result['label'],1)
        hours[4*HOUR_MS][2]=1000
        self.assertEqual(result,aligned_path_label(hours,HOUR_MS,4*HOUR_MS,90,110))

    def test_candle_clock_validation_rejects_incomplete_or_bad_ohlc(self):
        bad=candle(0);bad[6]-=1
        with self.assertRaisesRegex(ValueError,'clock'):validate_candle(bad,HOUR_MS)
        bad=candle(0);bad[2]=90
        with self.assertRaisesRegex(ValueError,'prices'):validate_candle(bad,HOUR_MS)

    def test_absorbing_geometry_matches_symmetric_series_and_one_sided_limit(self):
        p=continuous_range_probability(1,1,horizon=1)
        n=np.arange(1,50,2)
        expected=4/np.pi*np.sum((-1.)**((n-1)//2)/n*np.exp(-n*n*np.pi*np.pi/8))
        self.assertAlmostEqual(p,expected,places=12)
        self.assertAlmostEqual(continuous_range_probability(1,1000,horizon=5),2*ndtr(1/np.sqrt(5))-1,places=12)
        self.assertAlmostEqual(continuous_range_probability(2,3),continuous_range_probability(3,2),places=12)
        self.assertLess(continuous_range_probability(1,1),continuous_range_probability(2,2))

    def test_continuous_survival_is_below_discrete_monitoring_and_wait_is_future_uncertainty(self):
        from qount.research.market_learning import range_geometry_from_distances
        for a,b in ((2,3),(3,3),(1,4)):
            p=continuous_range_probability(a,b)
            self.assertLess(p,range_geometry_from_distances(a,b)+.02)
            self.assertAlmostEqual(continuous_range_probability(a,b,wait_days=1/24),
                                   continuous_range_probability(b,a,wait_days=1/24),places=12)
        self.assertTrue(.001<=continuous_range_probability(-.01,3,wait_days=1/24)<=.999)


if __name__=='__main__':unittest.main()
