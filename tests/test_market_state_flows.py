import unittest

import numpy as np

from qount.research.market_state_flows import asof_indices,center_asset_activity,gather_windows,normalize_market_windows,relative_activity_windows,trading_flows


class MarketStateFlowTests(unittest.TestCase):
    def test_aggressive_flow_identity_is_not_a_cash_deposit_estimate(self):
        raw=np.array([[10,11,9,10,100,1000,20,60,650],[10,11,9,10,100,np.nan,np.nan,np.nan,np.nan]])
        flow=trading_flows(raw)
        np.testing.assert_allclose(flow[0],[60,40,650,350,300])
        self.assertTrue(np.isnan(flow[1]).all())
        raw[0,7]=101
        with self.assertRaises(ValueError):trading_flows(raw)

    def test_publication_delay_and_staleness_prevent_future_or_stale_joins(self):
        observed=np.array([100,200,300]);available=observed+50
        ix=asof_indices(observed,available,[149,150,249,250,351,1000],max_age_ms=100)
        self.assertEqual(ix.tolist(),[-1,0,-1,1,2,-1])

    def test_future_event_changes_cannot_change_an_earlier_join(self):
        first=asof_indices([100,200],[110,210],[150])
        extended=asof_indices([100,200,300],[110,210,310],[150])
        np.testing.assert_array_equal(first,extended)

    def test_missing_channels_and_storage_padding_remain_missing(self):
        raw=np.array([[10,11,9,10,100,1000,20,60,650],[11,12,10,11,120,np.nan,np.nan,np.nan,np.nan]])
        windows,mask=gather_windows(raw,[[-1,0,1]])
        scaled=normalize_market_windows(windows)
        self.assertTrue(np.isnan(scaled[0,0]).all())
        self.assertTrue(np.isnan(scaled[0,2,5:]).all())
        np.testing.assert_allclose(np.exp(scaled[0,1:,:4])*10,raw[:,:4],rtol=1e-6)
        np.testing.assert_array_equal(mask,np.isfinite(windows))

    def test_relative_activity_is_invariant_to_asset_units_and_scale(self):
        raw=np.array([[[10,11,9,10,100,1000,20,60,650],
                       [11,12,10,11,200,2200,50,80,900],
                       [12,13,11,12,150,1800,30,90,1000]]],float)
        changed=raw*np.array([3,3,3,3,7,21,5,7,21])
        np.testing.assert_allclose(relative_activity_windows(raw),relative_activity_windows(changed),atol=1e-6)

    def test_relative_activity_preserves_taker_share_and_price_volatility(self):
        raw=np.array([[[10,11,9,10,100,1000,20,60,650],
                       [11,12,10,11,200,2200,50,80,900]]],float)
        scaled=relative_activity_windows(raw)
        np.testing.assert_array_equal(scaled[:,:,:4],normalize_market_windows(raw)[:,:,:4])
        np.testing.assert_allclose(np.exp(scaled[:,:,7]-scaled[:,:,4]),raw[:,:,7]/raw[:,:,4],rtol=1e-6)
        np.testing.assert_allclose(np.exp(scaled[:,:,8]-scaled[:,:,5]),raw[:,:,8]/raw[:,:,5],rtol=1e-6)
        # Only the supplied observed window determines scaling, regardless of
        # other samples (including later dates) passed alongside it.
        extended=np.concatenate([raw,raw*4])
        np.testing.assert_array_equal(relative_activity_windows(extended)[:1],scaled)

    def test_relative_activity_rejects_incomplete_or_zero_activity(self):
        for value in (np.nan,0,-1):
            raw=np.ones((1,2,9));raw[0,0,5]=value
            with self.assertRaises(ValueError):relative_activity_windows(raw)

    def test_asset_centering_uses_training_only_and_preserves_shared_references(self):
        seq=np.arange(4*2*9,dtype=np.float32).reshape(4,2,9)/10
        asset=np.array([0,1,0,1]);train=np.array([0,1])
        scaled,centers=center_asset_activity(seq,asset,train)
        future_changed=seq.copy();future_changed[2:]+=100
        changed,future_centers=center_asset_activity(future_changed,asset,train)
        np.testing.assert_array_equal(centers,future_centers)
        np.testing.assert_array_equal(scaled[:2],changed[:2])
        np.testing.assert_array_equal(seq[:,:,:4],scaled[:,:,:4])
        np.testing.assert_allclose(scaled[:,:,8]-scaled[:,:,5],seq[:,:,8]-seq[:,:,5],atol=1e-6)
        np.testing.assert_allclose(scaled[:2,:,4:7].mean(1),0,atol=1e-6)

    def test_asset_centering_requires_a_training_reference_for_every_asset(self):
        with self.assertRaises(ValueError):center_asset_activity(np.ones((2,2,9)),np.array([0,1]),np.array([0]))


if __name__=='__main__':unittest.main()
