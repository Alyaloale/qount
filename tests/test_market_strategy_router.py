import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from qount.research.market_strategy_router import state_probabilities,route_strategy,traditional_entry,STATE_NAMES

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/research'))
from study_market_strategy_router import model_route,known_time


class FakeClassifier:
    def __getitem__(self,key):return SimpleNamespace(classes_=np.array([0,1,5]))
    def predict_proba(self,x):return np.tile([.1,.2,.7],(len(x),1))


class MarketStrategyRouterTests(unittest.TestCase):
    def probabilities(self,state):
        p={s:0. for s in STATE_NAMES[:-1]};p[state]=.8;p['transition']+=.2;return p

    def features(self):
        return dict(action_state='up_trend',atr14=2.,ema20=100.,ema50=98.,previous_low20=90.,previous_high20=110.,event=None)

    def test_model_interface_has_probabilities_only(self):
        values=state_probabilities(FakeClassifier(),np.zeros((2,3)))
        self.assertEqual(len(values),2);self.assertNotIn('unknown',values[0]);self.assertNotIn('strategy',values[0])
        self.assertEqual(set(values[0]),set(STATE_NAMES[:-1]));self.assertAlmostEqual(sum(values[0].values()),1)
        self.assertAlmostEqual(values[0]['up_trend'],.7)

    def test_exact_state_threshold_does_not_sum_different_states(self):
        p={'range':.35,'compression':.35,'wide_range':.3}
        self.assertIsNone(route_strategy(p).strategy)
        self.assertEqual(route_strategy(self.probabilities('up_trend')).strategy,'trend_pullback_long')

    def test_probability_permission_still_requires_strategy_setup(self):
        route=route_strategy(self.probabilities('up_trend'));f=self.features()
        self.assertIsNone(traditional_entry(route,SimpleNamespace(o=103,h=105,l=102,c=104),f))
        entry=traditional_entry(route,SimpleNamespace(o=100,h=102,l=99.8,c=101),f)
        self.assertEqual(entry['side'],1);self.assertEqual(entry['stop'],97)

    def test_protection_and_wait_states_do_not_open_positions(self):
        for state in ('compression','transition','shock'):
            p={state:.9,'range':.1};self.assertIsNone(route_strategy(p).strategy)
        f=self.features();f['action_state']='shock'
        self.assertIsNone(traditional_entry(route_strategy(self.probabilities('up_trend')),SimpleNamespace(o=100,h=102,l=99,c=101),f))

    def test_failed_break_requires_observed_failure(self):
        route=route_strategy(self.probabilities('failed_down_breakout'));f=self.features()
        f['action_state']='failed_down_breakout';f['event']=dict(side=-1,status='pending',boundary=100)
        bar=SimpleNamespace(o=100,h=103,l=99,c=102)
        self.assertIsNone(traditional_entry(route,bar,f))
        f['event']['status']='failed';self.assertEqual(traditional_entry(route,bar,f)['side'],1)

    def test_cash_etf_cannot_take_short_strategy(self):
        f=self.features();f.update(action_state='down_trend',ema20=100.,ema50=102.)
        route=route_strategy(self.probabilities('down_trend'));bar=SimpleNamespace(o=100,h=101,l=98,c=99)
        self.assertIsNone(traditional_entry(route,bar,f,allow_short=False))
        self.assertEqual(traditional_entry(route,bar,f,allow_short=True)['side'],-1)

    def test_model_messages_must_be_available_and_unexpired(self):
        bars=[SimpleNamespace(t=(i+1)*86400-1) for i in range(7)];known=known_time(bars[0],'crypto')
        p=np.zeros((1,len(STATE_NAMES)));p[0,STATE_NAMES.index('up_trend')]=1
        book=dict(known_at=np.array([known]),bar_index=np.array([0]),probabilities=p)
        self.assertIsNone(model_route(book,known-1,bars,'crypto',.7)[0].strategy)
        self.assertEqual(model_route(book,known,bars,'crypto',.7)[0].strategy,'trend_pullback_long')
        self.assertIsNone(model_route(book,known_time(bars[5],'crypto'),bars,'crypto',.7)[0].strategy)

    def test_invalid_probability_vector_is_rejected(self):
        with self.assertRaises(ValueError):route_strategy({'range':.7})
        with self.assertRaises(ValueError):route_strategy({'range':1.1,'shock':-.1})


if __name__=='__main__':unittest.main()
