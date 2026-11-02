"""Dataset clocks, censoring, source masks, behavior fit and neural boundaries."""
import csv
import datetime as dt
import io
from pathlib import Path
import tempfile
import unittest
import zipfile

import numpy as np

from qount.research.market_learning import behavior_features, fit_behavior, fit_candidate, model_matrix, range_geometry_probability
from qount.research.market_learning_data import ALL_FEATURES, EXTRA_NAMES, additional_features, build_dataset, metric_snapshots
from qount.research.market_state_validation import causal_probabilities
from qount.research.market_stages import market_state_machine
from qount.research_data.bars import Bar


def fixture(count):
    rng=np.random.default_rng(31)
    price=100*np.exp(np.cumsum(rng.normal(0,.01,count)))
    bars=[Bar((i+1)*86400-1,float(p),float(p*1.01),float(p*.99),float(p),1000) for i,p in enumerate(price)]
    states=market_state_machine(bars)
    panel=dict(quote=np.full((count,1),1e8),daily_rate=np.full((count,1),.0001),taker=np.full((count,1),5.5e7))
    return bars,states,panel


class MarketLearningTest(unittest.TestCase):
    def test_metrics_publication_and_staleness_are_enforced(self):
        fields=['create_time','symbol','sum_open_interest','sum_open_interest_value',
                'count_toptrader_long_short_ratio','sum_toptrader_long_short_ratio']
        buffer=io.StringIO()
        writer=csv.DictWriter(buffer,fieldnames=fields)
        writer.writeheader()
        for clock,oi in [('21:00:00',1),('23:50:00',2),('23:55:00',999)]:
            writer.writerow(dict(zip(fields,[f'2025-01-03 {clock}','BTCUSDT',oi,1000,1.1,1.2])))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'BTCUSDT-metrics-2025-01-03.zip'
            with zipfile.ZipFile(path,'w') as archive:archive.writestr('metrics.csv',buffer.getvalue())
            values,_=metric_snapshots(directory)
        available,data=values['BTCUSDT','2025-01-03']
        self.assertEqual(data[0],2)
        self.assertEqual(available,int(dt.datetime(2025,1,3,23,55,tzinfo=dt.timezone.utc).timestamp()))

    def test_feature_prefix_is_invariant_and_absent_oi_remains_nan(self):
        bars,states,panel=fixture(300)
        a=additional_features(bars,states,bars,panel['quote'][:,0],panel['daily_rate'][:,0],panel['taker'][:,0])
        short=bars[:270]
        b=additional_features(short,market_state_machine(short),short,panel['quote'][:270,0],
            panel['daily_rate'][:270,0],panel['taker'][:270,0])
        for key in b:
            np.testing.assert_allclose(a[key][0],b[key][0],equal_nan=True)
            oi=[EXTRA_NAMES.index(k) for k in ('oi_contract_change1d','oi_contract_change7d',
                'oi_price_divergence7d','top_position_account_log_ratio','oi_notional_turnover20')]
            self.assertTrue(np.all(np.isnan(b[key][0][oi])))

    def test_tail_labels_and_minute_availability_are_explicit(self):
        bars,states,panel=fixture(230)
        data=build_dataset({'crypto':{'BTCUSDT':bars}},{'crypto':{'BTCUSDT':states}},panel,{},etf_cache='unused')
        self.assertEqual(data['X'].shape,(25,len(ALL_FEATURES)))
        self.assertEqual(data['known_at'][-1],230*86400+60)
        self.assertTrue(np.all(data['y'][-5:,0]==-1))
        self.assertTrue(np.all(data['maturity'][-5:,0]==0))
        self.assertTrue(np.array_equal(data['missing'],~np.isfinite(data['X'])))
        self.assertEqual(data['previous_row'][0],-1)
        self.assertEqual(data['next_row'][-1],-1)
        self.assertTrue(np.all(data['maturity'][:5,0]>data['known_at'][:5]))
        with self.assertRaises(ValueError):
            causal_probabilities([dict(known_at=1,mature_at=0,outcome=-1,asset='A',key='range')],3)

    def test_behavior_fit_does_not_use_future_and_can_reject_outliers(self):
        rng=np.random.default_rng(7)
        data=dict(X=rng.normal(size=(160,len(ALL_FEATURES))),asset=np.array(['BTCUSDT','ETHUSDT']*80))
        train=np.arange(100)
        a=fit_behavior(data,train)
        changed=dict(data,X=data['X'].copy())
        changed['X'][100:]=1e6
        b=fit_behavior(changed,train)
        np.testing.assert_allclose(a['centers'],b['centers'])
        _,labels=behavior_features(changed,np.arange(100,160),b)
        self.assertTrue(np.all(labels==-1))

    def test_targets_cannot_enter_model_matrix(self):
        data=dict(X=np.ones((2,len(ALL_FEATURES))),missing=np.zeros((2,len(ALL_FEATURES)),bool),
                  asset=np.array(['BTCUSDT','ETHUSDT']),economic_category=np.array(['crypto_major']*2),
                  state=np.array(['range']*2),y=np.zeros((2,4)))
        a=model_matrix(data)
        data['y'][:]=999
        np.testing.assert_array_equal(a,model_matrix(data))

    def test_neural_pilot_is_reproducible_without_random_validation(self):
        rng=np.random.default_rng(4)
        X=rng.normal(size=(160,4))
        y=(X[:,0]>0).astype(int)
        a,info=fit_candidate('mlp',X,y,seed=17)
        b,_=fit_candidate('mlp',X,y,seed=17)
        self.assertFalse(a[-1].early_stopping)
        self.assertEqual(info['fixed_epochs'],40)
        np.testing.assert_allclose(a.predict_proba(X),b.predict_proba(X),atol=1e-12)

    def test_geometry_baseline_uses_distance_and_is_symmetric(self):
        a=range_geometry_probability(100,100*np.exp(-.1),100*np.exp(.1),.02)
        b=range_geometry_probability(100,100*np.exp(-.01),100*np.exp(.01),.02)
        self.assertGreater(a,b)
        self.assertGreater(a,.8)
        self.assertLess(b,.1)


if __name__=='__main__':unittest.main()
