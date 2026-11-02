import unittest

import numpy as np


class SwitchInputTests(unittest.TestCase):
    def test_change_features_use_only_observed_windows_and_are_unit_invariant(self):
        from qount.research.market_state_switch_models import change_features
        rng=np.random.default_rng(17);raw=np.ones((3,14,9))
        c=np.exp(np.cumsum(rng.normal(0,.02,(3,14)),axis=1));raw[:,:,:4]=c[:,:,None]
        raw[:,:,1]*=1.03;raw[:,:,2]*=.97
        raw[:,:,4:7]=rng.uniform(100,200,(3,14,3));raw[:,:,7:]=raw[:,:,4:6]*.49
        first=change_features(raw[:1]);all_=change_features(raw)
        np.testing.assert_array_equal(first,all_[:1]);self.assertTrue(np.isfinite(all_).all())
        changed=raw*np.array([3,3,3,3,7,21,5,7,21])
        np.testing.assert_allclose(change_features(changed),all_,atol=2e-5)

    def test_switch_architecture_never_requires_previous_true_state(self):
        import torch
        from qount.research.market_state_switch_models import CHANGE_FEATURES,SwitchGRU
        for name in ('uniform_replay','switch_replay','switch_weighted','aux_switch','attention','change_features'):
            model=SwitchGRU(7,name);logits,aux=model(torch.zeros(4,14,9),torch.zeros(4,dtype=torch.long),torch.zeros(4,len(CHANGE_FEATURES)))
            self.assertEqual(tuple(logits.shape),(4,3))
            self.assertEqual(aux is not None,name=='aux_switch')

    def test_shared_encoder_initialization_and_plain_forward_match_baseline(self):
        import torch
        from qount.research.market_state_neural import OHLCVGRU
        from qount.research.market_state_switch_models import SwitchGRU
        torch.manual_seed(17);baseline=OHLCVGRU(7,channels=9).eval()
        for name in ('uniform_replay','switch_replay','switch_weighted','aux_switch','attention','change_features'):
            torch.manual_seed(17);model=SwitchGRU(7,name).eval()
            for k,v in baseline.state_dict().items():
                if k.startswith(('encoder.','asset.')):torch.testing.assert_close(v,model.state_dict()[k],rtol=0,atol=0)
            if name=='uniform_replay':
                x=torch.zeros(2,14,9);a=torch.zeros(2,dtype=torch.long)
                torch.testing.assert_close(baseline(x,a),model(x,a)[0],rtol=0,atol=0)


if __name__=='__main__':unittest.main()
