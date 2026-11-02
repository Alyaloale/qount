"""Geometric offsets, training-date nulls and causal probability shrinkage."""
import unittest

import numpy as np
from scipy.special import expit

from qount.research.market_probability_refinement import (
    fit_geometry_offset,predict_geometry_offset,permute_context_dates,volatility_context,discounted_probability_mix,
)
from qount.research.market_state_profiles import causal_shrink


class MarketProbabilityRefinementTest(unittest.TestCase):
    def test_zero_correction_retains_geometry_and_intercept_is_supported(self):
        fitted=fit_geometry_offset(np.empty((100,0)),np.array([0,1]*50),np.full(100,.5))
        np.testing.assert_allclose(predict_geometry_offset(fitted,np.empty((3,0)),np.array([.2,.5,.8]))[:,1],[.2,.5,.8])
        fitted=fit_geometry_offset(np.empty((100,0)),np.array([1]*90+[0]*10),np.full(100,.5))
        self.assertGreater(predict_geometry_offset(fitted,np.empty((1,0)),np.array([.5]))[0,1],.5)

    def test_offset_learns_known_residual_and_scaler_uses_only_training(self):
        rng=np.random.default_rng(77)
        values=rng.normal(size=(1000,2))
        truth=rng.random(1000)<expit(1.8*values[:,0])
        fitted=fit_geometry_offset(values[:700],truth[:700],np.full(700,.5))
        p=predict_geometry_offset(fitted,values[700:],np.full(300,.5))
        self.assertLess(np.mean((p[:,1]-truth[700:])**2),.25)
        self.assertGreater(fitted['coefficients'][1],.5)
        np.testing.assert_allclose(fitted['scaler'].mean_,values[:700].mean(axis=0))
        changed=values.copy();changed[700:]=1e8
        again=fit_geometry_offset(changed[:700],truth[:700],np.full(700,.5))
        np.testing.assert_array_equal(fitted['coefficients'],again['coefficients'])

    def test_invalid_geometry_and_nonbinary_targets_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'invalid_target_or_geometry'):
            fit_geometry_offset(np.zeros((2,1)),[0,2],[.5,.5])
        with self.assertRaisesRegex(ValueError,'invalid_target_or_geometry'):
            fit_geometry_offset(np.zeros((2,1)),[0,1],[0,.5])
        with self.assertRaisesRegex(ValueError,'invalid_target_or_geometry'):
            fit_geometry_offset(np.zeros((2,1)),[.5,1],[.5,.5])

    def test_context_permutation_is_synchronous_and_does_not_mutate_source(self):
        clock=np.repeat(np.arange(10),3)
        values=np.c_[np.arange(30),clock,clock*2]
        copy=values.copy()
        p=permute_context_dates(values,clock,np.array([1,2]))
        np.testing.assert_array_equal(values,copy)
        np.testing.assert_array_equal(p[:,0],values[:,0])
        self.assertFalse(np.array_equal(p[:,1],values[:,1]))
        for day in range(10):
            self.assertEqual(len(np.unique(p[clock==day,1])),1)
            np.testing.assert_array_equal(p[clock==day,2],2*p[clock==day,1])
        values[0,1]=-1
        with self.assertRaisesRegex(ValueError,'not_shared_by_date'):permute_context_dates(values,clock,np.array([1,2]))

    def test_binary_shrink_uses_only_mature_forecasts_and_equal_date_weight(self):
        rows=[dict(asset='BTCUSDT',category='crypto_major',known_at=i,mature_at=i+5,
            outcome=i%2,probabilities=[.5,.5]) for i in range(1,80)]
        expert=[dict(r,probabilities=[.2,.8]) for r in rows]
        a=causal_shrink(rows,expert)
        changed=[dict(r,outcome=1-r['outcome']) if r['mature_at']>=40 else r for r in rows]
        alternative=[dict(r,outcome=1-r['outcome']) if r['mature_at']>=40 else r for r in expert]
        b=causal_shrink(changed,alternative)
        for old,new in zip(a,b):
            if old['known_at']<=40:np.testing.assert_array_equal(old['probabilities'],new['probabilities'])
            self.assertTrue(old['weight_training_maturity'] is None or old['weight_training_maturity']<old['known_at'])
        duplicated=[dict(r,asset=asset) for r in rows for asset in ('BTCUSDT','ETHUSDT')]
        duplicated_expert=[dict(r,asset=asset) for r in expert for asset in ('BTCUSDT','ETHUSDT')]
        c=causal_shrink(duplicated,duplicated_expert)
        lookup={r['known_at']:r for r in a}
        for r in c:np.testing.assert_allclose(r['probabilities'],lookup[r['known_at']]['probabilities'],atol=1e-12)

    def test_weighted_offset_defaults_match_and_recent_weights_are_used(self):
        x=np.arange(100,dtype=float).reshape(-1,1)
        y=np.r_[np.zeros(70),np.ones(30)]
        base=fit_geometry_offset(x,y,np.full(100,.5))
        equal=fit_geometry_offset(x,y,np.full(100,.5),sample_weight=np.ones(100))
        np.testing.assert_allclose(base['coefficients'],equal['coefficients'],atol=1e-10)
        weighted=fit_geometry_offset(x,y,np.full(100,.5),sample_weight=np.r_[np.ones(70),np.full(30,5)])
        self.assertGreater(weighted['scaler'].mean_[0],base['scaler'].mean_[0])
        with self.assertRaisesRegex(ValueError,'invalid_sample_weight'):
            fit_geometry_offset(x,y,np.full(100,.5),sample_weight=np.zeros(100))

    def test_volatility_context_prefix_and_price_scale_are_invariant(self):
        from qount.research_data.bars import Bar
        rng=np.random.default_rng(111)
        p=100*np.exp(np.cumsum(rng.normal(0,.02,350)))
        bars=[Bar(i*86400,float(v),float(v*1.01),float(v*.99),float(v),100) for i,v in enumerate(p)]
        full=volatility_context(bars)
        np.testing.assert_allclose(full[:290],volatility_context(bars[:290]),equal_nan=True)
        changed=[Bar(b.t,b.o*100,b.h*100,b.l*100,b.c*100,b.v) for b in bars]
        np.testing.assert_allclose(full,volatility_context(changed),atol=1e-12,equal_nan=True)
        self.assertTrue(np.all((full[84:,1:3]>=0)&(full[84:,1:3]<=1)))

    def test_discounted_mix_ignores_current_and_future_labels_and_future_appends(self):
        rows=[dict(asset='BTCUSDT',category='crypto_major',context='low' if i%3 else 'high',known_at=i*86400,
            mature_at=(i+5)*86400,outcome=i%2,probabilities=[.5,.5]) for i in range(1,100)]
        expert=[dict(r,probabilities=[.2,.8]) for r in rows]
        a=discounted_probability_mix(rows,expert,conditional=True)
        changed=[dict(r,outcome=1-r['outcome']) if r['mature_at']>=40*86400 else r for r in rows]
        altered=[dict(r,outcome=1-r['outcome']) if r['mature_at']>=40*86400 else r for r in expert]
        b=discounted_probability_mix(changed,altered,conditional=True)
        for before,after in zip(a,b):
            if before['known_at']<=40*86400:np.testing.assert_array_equal(before['probabilities'],after['probabilities'])
            self.assertTrue(before['weight_training_maturity'] is None or before['weight_training_maturity']<before['known_at'])
            self.assertTrue(0<=before['expert_weight']<=1)
        short=discounted_probability_mix(rows[:60],expert[:60],conditional=True)
        for x,y in zip(a,short):np.testing.assert_array_equal(x['probabilities'],y['probabilities'])

    def test_discounted_mix_date_balance_and_forgetting(self):
        rows=[dict(asset='BTCUSDT',category='crypto_major',known_at=i*86400,mature_at=(i+1)*86400,
            outcome=1,probabilities=[.5,.5]) for i in range(1,20)]
        expert=[dict(r,probabilities=[.1,.9]) for r in rows]
        a=discounted_probability_mix(rows,expert)
        repeated=[dict(r,asset=s) for r in rows for s in ('BTCUSDT','ETHUSDT')]
        repeated_expert=[dict(r,asset=s) for r in expert for s in ('BTCUSDT','ETHUSDT')]
        b=discounted_probability_mix(repeated,repeated_expert)
        lookup={r['known_at']:r for r in a}
        for r in b:np.testing.assert_allclose(r['probabilities'],lookup[r['known_at']]['probabilities'],atol=1e-12)
        tail=dict(rows[-1],known_at=1000*86400,mature_at=1005*86400)
        decayed=discounted_probability_mix(rows+[tail],expert+[dict(tail,probabilities=[.1,.9])],half_life_days=10)
        self.assertLess(decayed[-1]['expert_weight'],1e-10)

    def test_multiscale_guard_is_causal_and_probability_weights_reconstruct(self):
        import sys
        from pathlib import Path
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/research'))
        from check_market_range_robustness import multiscale_runs
        sys.path.pop(0)
        base=[dict(index=i,asset='BTCUSDT',category='crypto_major',known_at=(i+1)*86400,
            mature_at=(i+6)*86400,outcome=i%2,probabilities=[.5,.5]) for i in range(80)]
        runs=dict(anchor=base,vol252_refit=[dict(r,probabilities=[.3,.7]) for r in base],
                  vol63=[dict(r,probabilities=[.4,.6]) for r in base])
        relative=np.linspace(-.6,.6,80)
        full=multiscale_runs(runs,relative)
        altered={k:[dict(r,outcome=1-r['outcome']) if r['mature_at']>=40*86400 else r for r in v] for k,v in runs.items()}
        changed=multiscale_runs(altered,relative)
        prefix=multiscale_runs({k:v[:40] for k,v in runs.items()},relative)
        for key,rows in full.items():
            for r,s in zip(rows,prefix[key]):np.testing.assert_array_equal(r['probabilities'],s['probabilities'])
            for r,s in zip(rows,changed[key]):
                if r['known_at']<=40*86400:np.testing.assert_array_equal(r['probabilities'],s['probabilities'])
        for r in full['multiscale_guarded']:
            expected=r['anchor_weight']*.5+(1-r['anchor_weight'])*((1-r['short_weight'])*.7+r['short_weight']*.6)
            self.assertAlmostEqual(r['probabilities'][1],expected)
            self.assertTrue(r['pair_training_maturity']<r['known_at'])


if __name__=='__main__':unittest.main()
