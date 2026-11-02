"""Category/state ablations and mature-label folds must stay comparable."""
from pathlib import Path
import sys
import unittest

import numpy as np

from qount.research.market_learning import model_matrix
from qount.research.market_learning_data import ALL_FEATURES
from qount.research.market_feature_enrichment import NEW_NAMES,QUALITY,UNVERIFIED
from qount.research.market_state_profiles import CATEGORIES,KEYS

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/research'))
from compare_market_feature_sets import fold_indices,matrices,taxonomy
sys.path.pop(0)


def data_fixture():
    names=np.array(ALL_FEATURES+NEW_NAMES)
    assets=np.array(sorted(CATEGORIES))
    states=np.array([KEYS[i%len(KEYS)] for i in range(len(assets))])
    return dict(X=np.ones((len(assets),len(names))),missing=np.zeros((len(assets),len(names)),bool),
        feature_names=names,asset=assets,economic_category=np.array([CATEGORIES[a] for a in assets]),state=states,
        default_feature_mask=np.array([n not in UNVERIFIED|QUALITY|{'top_position_account_log_ratio'} for n in names]))


class MarketFeatureComparisonTest(unittest.TestCase):
    def test_taxonomy_has_disjoint_economic_ids_and_twelve_fourteen_states(self):
        d=data_fixture();t=taxonomy(d)
        self.assertEqual(len(t['economic_categories']),7)
        self.assertEqual(t['possible_coarse_states'],12)
        self.assertEqual(t['possible_state_codes'],14)
        d['economic_category'][0]='oil'
        with self.assertRaisesRegex(ValueError,'category_mismatch'):taxonomy(d)

    def test_state_detail_collapses_pending_confirmed_only_in_coarse_arm(self):
        d=data_fixture()
        d['asset'][:2]='BTCUSDT';d['economic_category'][:2]='crypto_major'
        d['state'][:2]=['up_breakout:pending','up_breakout:confirmed']
        coarse=model_matrix(d,state_detail='coarse');fine=model_matrix(d)
        np.testing.assert_array_equal(coarse[0],coarse[1])
        self.assertFalse(np.array_equal(fine[0],fine[1]))
        self.assertEqual(fine.shape[1]-coarse.shape[1],2)

    def test_numeric_arm_cannot_see_category_asset_state_tokens(self):
        d=data_fixture()
        before=model_matrix(d,include_asset=False,include_category=False,state_detail=None)
        d['state'][:]='shock';d['asset'][:]='BTCUSDT';d['economic_category'][:]='crypto_major'
        np.testing.assert_array_equal(before,model_matrix(d,include_asset=False,include_category=False,state_detail=None))

    def test_micro_ablation_keeps_old_and_new_oi_separate(self):
        d=data_fixture();m,counts=matrices(d)
        self.assertEqual(counts,dict(legacy=44,enriched=89,broad=75,old_oi=4))
        self.assertEqual(m['micro_old_oi'].shape[1]-m['micro_no_values'].shape[1],8)
        changed={**d,'X':d['X'].copy()}
        names=list(d['feature_names']);changed['X'][:,names.index('oi_quantity_growth_intraday')]=999
        m2,_=matrices(changed)
        np.testing.assert_array_equal(m['micro_old_oi'],m2['micro_old_oi'])
        self.assertFalse(np.array_equal(m['micro_all_values'],m2['micro_all_values']))

    def test_fold_excludes_exact_cutoff_maturity_and_censored_target(self):
        d=dict(known_at=np.array([1,2,3,4,10,11]),maturity=np.array([[5],[9],[10],[0],[15],[16]]),
               y=np.array([[0],[1],[0],[-1],[0],[1]]))
        train,test=fold_indices(d,np.ones(6,bool),0,10,[4,5],minimum=2)
        np.testing.assert_array_equal(train,[0,1]);np.testing.assert_array_equal(test,[4,5])
        d['y'][2]=999
        np.testing.assert_array_equal(fold_indices(d,np.ones(6,bool),0,10,[4,5],minimum=2)[0],train)

    def test_source_group_additions_preserve_same_legacy_inputs(self):
        d=data_fixture();m,_=matrices(d,feature_groups=True)
        additions=dict(price_path=12,peer_context=3,crypto_activity=6,macro_context=6,
                       global_context=5,calendar=3,microstructure=10)
        for group,count in additions.items():
            self.assertEqual(m['add_'+group].shape[1]-m['legacy_tree'].shape[1],2*count)
        changed={**d,'X':d['X'].copy()}
        changed['X'][:,list(d['feature_names']).index('cash_proxy_total_return20')]=999
        other,_=matrices(changed,feature_groups=True)
        np.testing.assert_array_equal(m['add_price_path'],other['add_price_path'])
        self.assertFalse(np.array_equal(m['add_global_context'],other['add_global_context']))


if __name__=='__main__':unittest.main()
