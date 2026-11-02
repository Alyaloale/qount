import tempfile
import unittest
from pathlib import Path

import numpy as np

from qount.research.market_state_dataset import ATTRIBUTE_NAMES,DAY_MS,SCHEMA,STATE_NAMES,CurrentStateDataset,validate_arrays
from qount.research.market_state_flows import MARKET_CHANNELS,normalize_market_windows
from qount.research.market_state_sequence import fold_scale


def fixture():
    source=np.arange(10,16);n=3;close=np.arange(100.,140.)
    raw=np.c_[close-.2,close+1,close-1,close,np.full(40,100),close*100,np.full(40,20),np.full(40,60),close*60]
    nrows=source[:,None]+np.arange(-n+1,1);two=source[:,None]+np.arange(-2*n+1,1)
    state=np.array([0,2,1,1,0,2]);previous=np.array([0,0,2,1,1,0]);decision=(source+1)*DAY_MS+60000
    return dict(schema=np.array(SCHEMA),research_only=np.array(True),orders_authorized=np.array(False),
        target_mode=np.array('current'),target_offset_sessions=np.array(0),reference_sessions=np.array(n),
        asset=np.array(['BTCUSDT']*len(source)),market_names=np.array(MARKET_CHANNELS),state_names=np.array(STATE_NAMES),
        attribute_names=np.array(ATTRIBUTE_NAMES),source_row=source,market=raw[source],
        n_raw_market=raw[nrows],two_n_raw_market=raw[two],n_source_rows=nrows,two_n_source_rows=two,
        n_scaled_market=normalize_market_windows(raw[nrows]),two_n_scaled_market=normalize_market_windows(raw[two]),
        state=state,previous_state_label=previous,switch_label=state!=previous,
        attributes=np.tile([.8,0,.01,.4],(len(source),1)),
        bar_open_at=source*DAY_MS,bar_close_at=(source+1)*DAY_MS-1,decision_at=decision,
        market_available_at=decision,label_available_at=decision+n*DAY_MS,
        label_context_source_rows=source[:,None]+np.arange(-n+1,n+1))


class CompleteDatasetTests(unittest.TestCase):
    def test_complete_current_state_contract_and_nine_channel_scaling(self):
        d=fixture();self.assertEqual(validate_arrays(d)['channels'],9)
        mean,scale=fold_scale(d['n_scaled_market'][:2])
        self.assertEqual(mean.shape,(9,));self.assertTrue(np.isfinite(scale).all())

    def test_missing_daily_fields_or_window_values_are_rejected(self):
        for key,index in [('market',(0,5)),('n_raw_market',(0,0,5)),('attributes',(0,2))]:
            d=fixture();d[key][index]=np.nan
            with self.assertRaises(ValueError):validate_arrays(d)

    def test_next_cycle_target_and_early_label_maturity_are_rejected(self):
        d=fixture();d['target_offset_sessions']=np.array(3)
        with self.assertRaises(ValueError):validate_arrays(d)
        d=fixture();d['label_available_at'][0]=d['decision_at'][0]
        with self.assertRaises(ValueError):validate_arrays(d)

    def test_future_window_reference_cannot_enter_inputs(self):
        d=fixture();d['n_source_rows'][0,-1]+=1
        with self.assertRaises(ValueError):validate_arrays(d)

    def test_switch_is_an_output_not_a_fourth_state_or_input(self):
        d=fixture();d['switch_label'][0]=True
        with self.assertRaises(ValueError):validate_arrays(d)
        with tempfile.TemporaryDirectory() as tmp:
            np.savez_compressed(Path(tmp)/'dataset.npz',**fixture());ds=CurrentStateDataset(tmp)
            self.assertEqual(set(ds.inputs([0])),{'market','asset_index'})
            self.assertEqual(ds.inputs([0])['market'].shape,(1,3,9))
            self.assertIn('changed',ds.targets([0]))
            with self.assertRaisesRegex(ValueError,'assumed'):ds.funding([0])

    def test_training_split_excludes_unmatured_same_day_labels(self):
        d=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            np.savez_compressed(Path(tmp)/'dataset.npz',**d);ds=CurrentStateDataset(tmp)
            train,test=ds.split(int(d['decision_at'][4]),int(d['decision_at'][5])+1)
            self.assertEqual(train.tolist(),[0]);self.assertEqual(test.tolist(),[4,5])

    def test_historical_schema_cannot_be_silently_used_as_current(self):
        d=fixture();d['schema']=np.array('daily_native_market_flow_candidate_v1')
        with self.assertRaisesRegex(ValueError,'schema'):validate_arrays(d)

    def test_missing_index_cannot_wrap_around_to_a_future_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            np.savez_compressed(Path(tmp)/'dataset.npz',**fixture());ds=CurrentStateDataset(tmp)
            for rows in ([-1],[99],[1.5]):
                with self.assertRaises(IndexError):ds.inputs(rows)
            self.assertEqual(ds.inputs(0)['market'].shape,(1,3,9))

    def test_latest_complete_inputs_do_not_require_future_labels(self):
        d=fixture()
        fields=('asset','source_row','market','n_raw_market','n_scaled_market','n_source_rows',
                'two_n_raw_market','two_n_scaled_market','two_n_source_rows','bar_open_at',
                'bar_close_at','decision_at','market_available_at')
        latest={key:d[key][-1:] for key in fields}
        latest.update(schema=np.array(SCHEMA+'_inputs'),research_only=True,orders_authorized=False,
                      reference_sessions=d['reference_sessions'],market_names=d['market_names'])
        with tempfile.TemporaryDirectory() as tmp:
            np.savez_compressed(Path(tmp)/'dataset.npz',**d)
            np.savez_compressed(Path(tmp)/'latest_inputs.npz',**latest);ds=CurrentStateDataset(tmp)
            result=ds.latest_inputs();self.assertEqual(result['market'].shape,(1,3,9))
            self.assertNotIn('state',result)
            latest['state']=np.array([0]);np.savez_compressed(Path(tmp)/'latest_inputs.npz',**latest)
            with self.assertRaisesRegex(ValueError,'retrospective'):ds.latest_inputs()


if __name__=='__main__':unittest.main()
