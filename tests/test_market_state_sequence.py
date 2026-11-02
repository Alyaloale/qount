import unittest

import numpy as np

from qount.research.market_state_sequence import fold_scale,model_window,raw_window,same_day_targets
from qount.research.market_state_factorization import purged_quarter


class RawSequenceTests(unittest.TestCase):
    def bars(self):
        c=np.arange(100.,120.)
        return np.c_[c-.2,c+1,c-1,c,np.arange(20.)*100]

    def test_exact_n_completed_bars_in_chronological_order(self):
        data=self.bars();window=raw_window(data,12,7)
        np.testing.assert_array_equal(window,data[6:13])
        window[0,0]=1
        self.assertNotEqual(data[6,0],1)
        self.assertIsNone(raw_window(data,5,7))

    def test_future_prices_and_volumes_cannot_change_input(self):
        data=self.bars();altered=data.copy();altered[13:]*=1000
        np.testing.assert_array_equal(model_window(raw_window(data,12,7)),
                                      model_window(raw_window(altered,12,7)))

    def test_scaling_preserves_all_five_channels_and_price_relations(self):
        raw=self.bars()[:7];x=model_window(raw)
        np.testing.assert_allclose(np.exp(x[:,:4])*raw[0,3],raw[:,:4],rtol=1e-6)
        np.testing.assert_allclose(np.expm1(x[:,4]),raw[:,4],rtol=1e-6)
        self.assertEqual(x[0,4],0)

    def test_train_scaler_does_not_use_held_out_observations(self):
        train=np.stack([model_window(self.bars()[:7]),model_window(self.bars()[1:8])])
        mean,scale=fold_scale(train)
        shifted=train+100
        self.assertFalse(np.allclose(mean,fold_scale(shifted)[0]))
        np.testing.assert_allclose(((train-mean)/scale).mean((0,1)),0,atol=2e-5)
        self.assertTrue(np.isfinite(scale).all())

    def test_invalid_prices_or_volume_are_not_silently_filled(self):
        raw=self.bars()[:7];raw[0,3]=0
        with self.assertRaises(ValueError):model_window(raw)

    def test_same_day_target_stays_at_k_and_keeps_future_confirmation(self):
        state=np.array([-1,0,2,1,0,-1]);known=np.arange(6)*10+10
        maturity=known+20;attributes=np.ones((6,4))
        result=same_day_targets(state,attributes,maturity)
        np.testing.assert_array_equal(result['target_main_state'],state)
        self.assertEqual(result['target_row'].tolist(),[-1,1,2,3,4,-1])
        self.assertEqual(result['target_available_at'][2],maturity[2])
        self.assertEqual(result['target_main_state'][2],2)
        members=np.flatnonzero(result['target_mask'])
        train,test=purged_quarter(members,known,result['target_available_at'],50,70)
        self.assertEqual(train.tolist(),[1])
        self.assertEqual(test.tolist(),[4])
        self.assertTrue(np.isnan(result['target_attributes'][0]).all())

    def test_confirmed_state_requires_real_label_maturity(self):
        with self.assertRaises(ValueError):same_day_targets([0],np.ones((1,4)),[0])
        raw=self.bars()[:7];raw[1,4]=-1
        with self.assertRaises(ValueError):model_window(raw)


if __name__=='__main__':unittest.main()
