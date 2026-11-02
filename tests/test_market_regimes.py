import math
import random
import unittest
from types import SimpleNamespace

import numpy as np

from qount.research.market_regimes import (
    SCHEMA, REGIMES, compatible_strategy, environment_entry, environment_probabilities,
    DURATION_BINS, duration_bucket, duration_probabilities, environment_rows, select_environment, select_structure, structural_candidates, window_regime,
)
from qount.research.market_stages import market_state_machine
from qount.research_data.bars import Bar


class MarketRegimeTests(unittest.TestCase):
    def features(self):
        return dict(efficiency20=.1, direction=0, direction_confirmed=True, close=100, ema20=100, ema50=100,
            slope50_atr=0., relative_volatility=1., width5_over20=.9, anchor_drift=.05,
            containment20=1., anchor_position=.2, lower_visits20=3, upper_visits20=3,
            midpoint_crosses20=4, anchor_width_atr=5.)

    def test_low_efficiency_alone_does_not_define_a_tradable_range(self):
        f=self.features(); self.assertEqual(select_structure(f),'rotation')
        for key,value in (('upper_visits20',0),('midpoint_crosses20',0),('anchor_drift',.8),('containment20',.6),('slope50_atr',.3)):
            changed=dict(f,**{key:value}); self.assertNotEqual(select_structure(changed),'rotation',key)
        self.assertEqual(select_structure(dict(f,upper_visits20=0)),'low_efficiency_chop')

    def test_trend_compression_and_rotation_are_mutually_exclusive(self):
        rng=random.Random(17)
        for _ in range(2000):
            f=self.features(); f.update(efficiency20=rng.random(),direction=rng.choice([-1,0,1]),
                slope50_atr=rng.uniform(-1,1),close=rng.uniform(95,105),ema20=rng.uniform(95,105),
                relative_volatility=rng.uniform(.3,2),width5_over20=rng.random())
            self.assertLessEqual(sum(structural_candidates(f).values()),1)
        f=self.features(); f.update(relative_volatility=.6,width5_over20=.4)
        self.assertEqual(select_structure(f),'compression')
        f.update(efficiency20=.27); self.assertEqual(select_structure(f),'transition')

    def test_window_target_keeps_short_state_occupancy_and_marks_mixed_windows(self):
        self.assertEqual(window_regime(['uptrend','uptrend','uptrend','transition','downtrend']),'uptrend')
        self.assertEqual(window_regime(['uptrend','uptrend','downtrend','downtrend','compression']),'transition')
        with self.assertRaises(ValueError):window_regime(['uptrend','unknown'])

    def test_duration_target_is_capped_and_rejects_unknown(self):
        self.assertEqual(duration_bucket(['uptrend','uptrend','downtrend']),2)
        self.assertEqual(duration_bucket(['uptrend']*20),10)
        with self.assertRaises(ValueError):duration_bucket(['uptrend','unknown'])

    def test_duration_probabilities_cover_all_buckets(self):
        class Fake:
            def __getitem__(self,key): return SimpleNamespace(classes_=np.array([0,9]))
            def predict_proba(self,x): return np.array([[.8,.2]])
        bundle=dict(duration_classifiers={'5':Fake()},duration_uniform_prior_mix=.01)
        values=duration_probabilities(bundle,np.zeros((1,1)),5)[0]
        self.assertEqual(len(values),len(DURATION_BINS));self.assertAlmostEqual(sum(values.values()),1.)
        self.assertTrue(all(value>0 for value in values.values()))

    def test_past_environments_and_anchors_never_change_when_future_arrives(self):
        # Coherent OHLC: the previous/current close are both inside each candle.
        bars=[]; price=100.; rng=random.Random(31)
        for i in range(330):
            close=price*math.exp(rng.gauss(0,.012)); bars.append(Bar(i*86400,price,max(price,close)*1.005,min(price,close)*.995,close,1000)); price=close
        prefix=environment_rows(bars[:300]); full=environment_rows(bars)
        self.assertEqual(prefix,{t:r for t,r in full.items() if t<300*86400})
        for row in full.values(): self.assertIn(row['regime'],REGIMES+('unknown',))

    def test_event_and_risk_do_not_overwrite_structural_class(self):
        # Classify the exact same structural history with separately supplied
        # event/risk annotations: regime must remain the same.
        bars=[]
        for i in range(280):
            c=100+4*math.sin(i*math.pi/3); bars.append(Bar(i*86400,c,c+1,c-1,c,1000))
        old=market_state_machine(bars); base=environment_rows(bars,old)
        self.assertIn(base[bars[-1].t]['regime'],('rotation','low_efficiency_chop'))
        modified={t:dict(v) for t,v in old.items()}; t=bars[-1].t
        modified[t].update(action_state='shock',event=dict(status='failed',side=1,observed_at=t))
        altered=environment_rows(bars,modified)
        self.assertEqual(base[t]['regime'],altered[t]['regime'])
        self.assertTrue(altered[t]['risk']['block_new']); self.assertEqual(altered[t]['event']['status'],'failed')
        self.assertIsNone(compatible_strategy(altered[t]))

    def test_clear_trends_are_recognized_instead_of_abstaining_everywhere(self):
        for side,label in ((1,'uptrend'),(-1,'downtrend')):
            bars=[]
            for i in range(280):
                close=100+side*.2*i+.1*math.sin(i)
                bars.append(Bar(i*86400,close,close+1,close-1,close,1000))
            rows=environment_rows(bars)
            self.assertTrue(all(rows[b.t]['regime']==label for b in bars[205:]))

    def test_opposing_breakout_never_routes_a_trend_strategy(self):
        env=dict(regime='uptrend',event=dict(status='confirmed',side=-1),risk=dict(block_new=False))
        self.assertIsNone(compatible_strategy(env))
        env['event']['side']=1;self.assertEqual(compatible_strategy(env),'confirmed_breakout_long')
        env['regime']='rotation';self.assertIsNone(compatible_strategy(env))
        env['event']['status']='failed';self.assertIsNone(compatible_strategy(env))

    def test_probability_schema_and_exact_threshold(self):
        p=dict(zip(REGIMES,[.35,.0,.35,.1,.1,.1])); self.assertIsNone(select_environment(p))
        with self.assertRaises(ValueError): select_environment({'range':1.})
        with self.assertRaises(ValueError): environment_probabilities({'state_names':['range']},np.zeros((1,1)))
        class Fake:
            def __getitem__(self,key): return SimpleNamespace(classes_=np.array([0,5]))
            def predict_proba(self,x): return np.array([[.8,.2]])
        values=environment_probabilities(dict(schema=SCHEMA,state_names=REGIMES,classifier=Fake()),np.zeros((1,1)))
        self.assertEqual(set(values[0]),set(REGIMES));self.assertEqual(select_environment(values[0]),'uptrend')
        self.assertTrue(all(value>0 for value in values[0].values()))
        self.assertAlmostEqual(sum(values[0].values()),1.)

    def test_strategy_uses_validated_anchor_and_still_requires_entry_setup(self):
        env=dict(schema=SCHEMA,regime='rotation',event=None,
            risk=dict(block_new=False,high_volatility=False),features=dict(anchor_low=90.,anchor_high=110.))
        legacy=dict(action_state='range',atr14=2.,ema20=100.,ema50=100.,previous_low20=80.,previous_high20=120.,event=None)
        bar=SimpleNamespace(o=91.,c=92.,l=90.,h=93.)
        self.assertIsNone(environment_entry(env,bar,legacy))
        probabilities=dict(zip(REGIMES,[.8,0.,0.,0.,0.,.2]))
        self.assertIsNone(environment_entry(env,bar,legacy,probabilities=probabilities))
        self.assertIsNone(environment_entry(env,SimpleNamespace(o=100.,c=101.,l=99.,h=102.),legacy))

    def test_failed_break_in_box_requires_edge_and_targets_its_midpoint(self):
        event=dict(side=-1,status='failed',boundary=91.)
        env=dict(schema=SCHEMA,regime='rotation',event=event,
            risk=dict(block_new=False,high_volatility=False),features=dict(anchor_low=90.,anchor_high=110.))
        legacy=dict(action_state='failed_down_breakout',atr14=2.,ema20=100.,ema50=100.,previous_low20=80.,previous_high20=120.,event=event)
        self.assertIsNone(environment_entry(env,SimpleNamespace(o=91.,c=92.,l=89.5,h=93.),legacy))
        self.assertIsNone(environment_entry(env,SimpleNamespace(o=100.,c=101.,l=99.,h=102.),legacy))


if __name__=='__main__': unittest.main()
