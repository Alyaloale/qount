import copy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/research'))
from diagnose_market_regime_bottlenecks import annotate, forecast_endpoint_indices, latest_message
from qount.research.market_regimes import REGIMES
from study_market_regimes import available_forecast, forecast_target_index
from study_market_strategy_router import known_time,open_time


class MarketRegimeBottleneckTests(unittest.TestCase):
    def test_last_held_bar_matches_execution_delay_and_holding_period(self):
        self.assertEqual(forecast_endpoint_indices(10,'crypto'),16)
        self.assertEqual(forecast_endpoint_indices(10,'etf_proxy'),15)
        self.assertEqual(forecast_target_index(10,'crypto'),16)
        self.assertEqual(forecast_target_index(10,'etf_proxy'),15)
        with self.assertRaises(ValueError):forecast_endpoint_indices(0,'crypto',0)
        with self.assertRaises(ValueError):forecast_target_index(0,'unknown')

    def test_primary_forecast_remains_valid_through_last_held_bar(self):
        bars=[SimpleNamespace(t=(i+1)*86400-1) for i in range(12)]
        for group,endpoint in (('crypto',6),('etf_proxy',5)):
            book=dict(known_at=np.array([known_time(bars[0],group)]),bar_index=np.array([0]))
            target_known=known_time(bars[endpoint],group)
            self.assertEqual(available_forecast(book,target_known-1,bars,group),0)
            self.assertIsNone(available_forecast(book,target_known,bars,group))

    def test_latest_message_never_reads_the_next_forecast(self):
        book=dict(known_at=np.array([100,200]))
        self.assertIsNone(latest_message(book,99));self.assertEqual(latest_message(book,199),0)
        self.assertEqual(latest_message(book,200),1)

    def test_expired_prediction_target_is_detected_without_using_future_labels_to_gate(self):
        bars=[SimpleNamespace(t=(i+1)*86400-1) for i in range(12)]
        market={'crypto':{'X':bars}}
        up=np.array([.8,0.,0.,0.,0.,.2]);down=np.array([0.,.8,0.,0.,0.,.2])
        old={'X':dict(known_at=np.array([known_time(bars[0],'crypto')]),bar_index=np.array([0]),probabilities=up[None,:])}
        fresh=dict(known_at=np.array([known_time(bars[4],'crypto'),known_time(bars[6],'crypto')]),
            bar_index=np.array([4,6]),probabilities=np.array([up,down]))
        books={'daily70':{'X':fresh},'aligned70':{'X':fresh}}
        row=dict(group='crypto',asset='X',known_at=known_time(bars[4],'crypto'),entry_at=open_time(bars[6],'crypto'),
            max_bars=5,regime='uptrend',masks={'model70':True})
        environments={'crypto':{'X':{b.t:dict(regime='uptrend') for b in bars}}}
        result=annotate([row],books,old,market,environments)[0]
        self.assertTrue(result['forecasts']['stale70']['target_closed_before_entry'])
        self.assertEqual(result['forecasts']['stale70']['last_held_minus_target'],5)
        self.assertEqual(result['forecasts']['aligned70']['last_held_minus_target'],0)
        self.assertTrue(result['masks']['aligned70'])
        changed=copy.deepcopy(environments)
        for b in bars:changed['crypto']['X'][b.t]['regime']='downtrend'
        again=annotate([row],books,old,market,changed)[0]
        self.assertEqual(result['masks'],again['masks'])
        self.assertNotEqual(result['forecasts']['aligned70']['actual'],again['forecasts']['aligned70']['actual'])


if __name__=='__main__':unittest.main()
