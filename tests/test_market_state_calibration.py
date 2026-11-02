import unittest

import numpy as np

from qount.research.market_state_calibration import apply_calibration,fit_calibration,identity_calibration,mature_calibration_rows


class ProbabilityCalibrationTests(unittest.TestCase):
    def test_identity_and_class_order_are_preserved(self):
        p=np.array([[.1,.2,.7],[.4,.5,.1]])
        np.testing.assert_allclose(apply_calibration(p,identity_calibration(3)),p)

    def test_current_period_and_unmatured_previous_answers_are_excluded(self):
        decision=np.array([10,20,30,40]);available=np.array([20,35,40,50]);p=np.full((4,3),1/3)
        np.testing.assert_array_equal(mature_calibration_rows(decision,available,p,35),[0])
        changed=p.copy();changed[1:]=[.8,.1,.1]
        np.testing.assert_array_equal(mature_calibration_rows(decision,available,changed,35),[0])

    def test_calibration_reduces_a_known_probability_level_bias(self):
        probability=np.tile([.2,.8],(1000,1));actual=np.r_[np.ones(200,int),np.zeros(800,int)]
        fitted=fit_calibration(probability,actual);calibrated=apply_calibration(probability,fitted)
        before=np.mean((probability[:,1]-actual)**2);after=np.mean((calibrated[:,1]-actual)**2)
        self.assertLess(after,before-.1)
        np.testing.assert_allclose(calibrated.sum(1),1)


if __name__=='__main__':unittest.main()
