"""Category semantics, shared origins, future-invariant features and training."""
import datetime as dt
import math
import random
import unittest

import numpy as np

from qount.research.market_state_profiles import (
    FEATURE_NAMES, category, category_probabilities, causal_shrink, profile_samples, quarterly_predictions,
)
from qount.research.market_stages import market_state_machine
from qount.research_data.bars import Bar


class MarketStateProfilesTest(unittest.TestCase):
    def book(self,count):
        book={}
        for asset,seed in (("BTCUSDT",10),("ETHUSDT",20)):
            rng=random.Random(seed)
            bars,price=[],100.
            for i in range(count):
                close=price*math.exp(rng.gauss(.0002,.015))
                bars.append(Bar(i*86400,price,max(price,close)*1.005,min(price,close)*.995,close,1000))
                price=close
            book[asset]=bars
        return book,{s:market_state_machine(bars) for s,bars in book.items()}

    def test_energy_equity_is_not_crude_and_unknown_does_not_silently_map(self):
        self.assertNotEqual(category("XLEUSDT"),category("CLUSDT"))
        self.assertNotEqual(category("XAUUSDT"),category("COPPERUSDT"))
        with self.assertRaises(ValueError):category("NEWUSDT")

    def test_horizons_share_origins_and_future_append_keeps_features(self):
        book,states=self.book(340)
        a=profile_samples(book,states,"crypto",5)
        b=profile_samples(book,states,"crypto",20)
        self.assertEqual([(s['asset'],s['known_at']) for s in a],[(s['asset'],s['known_at']) for s in b])
        self.assertEqual([s['features'] for s in a],[s['features'] for s in b])
        prefix,short_states=self.book(300)
        short=profile_samples(prefix,short_states,"crypto",5)
        index={(s['asset'],s['known_at']):s for s in a}
        for row in short:
            self.assertEqual(row['features'],index[row['asset'],row['known_at']]['features'])
            self.assertEqual(len(row['features']),len(FEATURE_NAMES))

    def test_benchmark_calendar_mismatch_is_rejected(self):
        book,states=self.book(260)
        book['ETHUSDT']=book['ETHUSDT'][1:]
        with self.assertRaises(ValueError):profile_samples(book,states,"crypto",5)

    def test_category_probabilities_do_not_use_unmatured_outcomes(self):
        samples=[dict(asset='BTCUSDT',category='crypto_major',key='range',known_at=i,
                      mature_at=i+5,outcome=i%3) for i in range(1,100)]
        a=category_probabilities(samples)
        changed=[dict(r,outcome=(r['outcome']+1)%3) if r['mature_at']>=50 else r for r in samples]
        b=category_probabilities(changed)
        for old,new in zip(a,b):
            if old['known_at']<=50:self.assertEqual(old['probabilities'],new['probabilities'])

    def test_phase_tasks_keep_binary_probability_shape_and_valid_normalization(self):
        samples=[dict(asset='XAUUSDT',category='gold',key='range',known_at=i,
                      mature_at=i+5,outcome=i%2) for i in range(1,50)]
        rows=category_probabilities(samples,classes=2)
        self.assertTrue(all(len(r['probabilities'])==2 for r in rows))
        self.assertTrue(all(abs(sum(r['probabilities'])-1)<1e-12 for r in rows))

    def test_adaptive_weight_ignores_its_own_unmatured_label(self):
        baseline=[dict(asset='BTCUSDT',category='crypto_major',key='range',known_at=i,
                       mature_at=i+5,outcome=i%3,probabilities=[.3,.4,.3]) for i in range(1,80)]
        expert=[dict(r,probabilities=[.2,.3,.5]) for r in baseline]
        a=causal_shrink(baseline,expert,category_aware=True)
        b0=[dict(r,outcome=(r['outcome']+1)%3) if r['mature_at']>=40 else r for r in baseline]
        b1=[dict(r,outcome=(r['outcome']+1)%3) if r['mature_at']>=40 else r for r in expert]
        b=causal_shrink(b0,b1,category_aware=True)
        for old,new in zip(a,b):
            if old['known_at']<=40:
                self.assertEqual(old['probabilities'],new['probabilities'])
                self.assertEqual(old['expert_weight'],new['expert_weight'])
            self.assertTrue(old['weight_training_maturity'] is None or old['weight_training_maturity']<old['known_at'])
            self.assertAlmostEqual(sum(old['probabilities']),1)

    def test_quarterly_scaling_and_model_ignore_future_features_and_labels(self):
        start=int(dt.datetime(2010,1,1,tzinfo=dt.timezone.utc).timestamp())
        samples=[]
        for i in range(640):
            samples.append(dict(asset='BTCUSDT',category='crypto_major',key='range',
                known_at=start+i*86400,mature_at=start+(i+5)*86400,outcome=i%3,
                features=[math.sin(i/(j+2)) for j in range(len(FEATURE_NAMES))],
                actionable=False,route_class=None,fixed_prediction=None))
        cutoff=int(dt.datetime(2011,5,1,tzinfo=dt.timezone.utc).timestamp())
        a,fits=quarterly_predictions(samples,'2011-01-01',categorical=True)
        changed=[dict(r,outcome=(r['outcome']+1)%3,features=[100.]*len(FEATURE_NAMES))
                 if r['known_at']>cutoff else r for r in samples]
        b,_=quarterly_predictions(changed,'2011-01-01',categorical=True)
        for x,y in zip(a,b):
            if x['known_at']<=cutoff:np.testing.assert_allclose(x['probabilities'],y['probabilities'],atol=1e-12)
        self.assertTrue(all(f['last_training_maturity']<f['cutoff'] for f in fits))


if __name__=='__main__':unittest.main()
