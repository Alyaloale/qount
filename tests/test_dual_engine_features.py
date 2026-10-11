import copy
import datetime as dt
import json
import math
import tempfile
import unittest
from pathlib import Path

from qount.research import dual_engine_features as f
from qount.research.c60_pit_universe import Asset
from qount.research.dual_engine_family_clock import replay_family_clock

CONTRACT = Path(__file__).resolve().parents[1]/'config/dual-engine-features-20261005.json'


class PathQualityTests(unittest.TestCase):
    def test_monotonic_and_flat_paths_have_defined_features(self):
        up = f.path_features([100*1.01**t for t in range(100)])
        down = f.path_features([100*.99**t for t in range(100)])
        self.assertEqual(up['agreement'], 1)
        self.assertAlmostEqual(up['efficiency'], 1)
        self.assertEqual(up['downside_quality'], 1)
        self.assertEqual(down['agreement'], 0)
        self.assertAlmostEqual(down['efficiency'], 1)
        self.assertEqual(down['downside_quality'], 0)
        self.assertEqual(f.path_features([100]*91), {'agreement':0., 'efficiency':0., 'downside_quality':.5})

    def test_directionless_chop_is_not_high_efficiency(self):
        values = [100*math.exp(.1*(t%2)) for t in range(91)]
        result = f.path_features(values)
        self.assertAlmostEqual(result['efficiency'], 0., places=12)
        self.assertAlmostEqual(result['downside_quality'], .5, places=12)

    def test_missing_or_invalid_history_fails_closed(self):
        for prices in (None, [100]*90, [100]*90+[0], [100]*90+[float('nan')]):
            with self.assertRaises(ValueError): f.path_features(prices)

    def fixture(self):
        days = [(dt.date(2020,9,1)+dt.timedelta(days=i)).isoformat() for i in range(150)]
        prices = tuple(100*math.exp(.004*t+.025*math.sin(t)) for t in range(150))
        assets = {'X':Asset('X','BTCUSDT',0,prices,(100.,)*150),
                  'G':Asset('G','PAXGUSDT',0,prices,(100.,)*150)}
        targets = {t:{'X':.6, 'G':.1} for t in range(90,150)}
        return days, assets, targets

    def test_sizing_preserves_zeros_and_gold_and_never_redistributes(self):
        days, assets, targets = self.fixture()
        targets[100]['X']=0
        features=f.feature_panel(targets,assets)
        for rule in f.CANDIDATES+('uniform75',):
            result=f.sized_targets(targets,features,rule)
            self.assertEqual(result[100]['X'],0)
            for t,weights in result.items():
                self.assertEqual(weights['G'],.1)
                self.assertGreaterEqual(weights['X'],.5*targets[t]['X'])
                self.assertLessEqual(weights['X'],targets[t]['X'])
                self.assertLessEqual(sum(weights.values()),sum(targets[t].values()))

    def test_future_changes_do_not_change_features_targets_or_execution_prefix(self):
        days,assets,targets=self.fixture()
        changed=dict(assets)
        a=assets['X']; changed['X']=Asset('X','BTCUSDT',0,a.closes[:125]+(1.,)*25,a.quote)
        features=f.feature_panel(targets,assets); newer=f.feature_panel(targets,changed)
        self.assertEqual({t:v for t,v in features.items() if t<125}, {t:v for t,v in newer.items() if t<125})
        opens={k:{d:100. for d in days} for k in assets}
        closes={k:dict(zip(days,a.closes)) for k,a in assets.items()}
        changed_closes={k:dict(zip(days,a.closes)) for k,a in changed.items()}
        for rule in f.CANDIDATES:
            target=f.sized_targets(targets,features,rule); other=f.sized_targets(targets,newer,rule)
            kwargs=dict(start=days[92],lag=2,cost_bps=50,clock_mode='sat_week',core_assets=('X',))
            run=replay_family_clock(days,closes,opens,target,**kwargs)
            later=replay_family_clock(days,changed_closes,opens,other,**kwargs)
            self.assertEqual(run['records'][:32],later['records'][:32])

    def test_label_starts_at_tplus2_and_censors_incomplete_tail(self):
        days,assets,targets=self.fixture();features=f.feature_panel(targets,assets)
        closes={k:dict(zip(days,a.closes)) for k,a in assets.items()}
        opens={k:{d:200. for d in days} for k in assets}
        result=f.forward_diagnostics(features,targets,days,closes,opens,start=days[90],end=days[-1])
        first=result['rows'][0]
        self.assertEqual(first['fill'],days[92]);self.assertEqual(first['end'],days[111])
        self.assertAlmostEqual(first['forward_net_return'],assets['X'].closes[111]*.995/(200*1.005)-1)
        self.assertEqual(result['censored'],21)
        self.assertEqual(len(result['rows']),39)

    def test_labels_do_not_fill_missing_price_path(self):
        days,assets,targets=self.fixture();features=f.feature_panel(targets,assets)
        closes={k:dict(zip(days,a.closes)) for k,a in assets.items()}
        opens={k:{d:200. for d in days} for k in assets};del closes['X'][days[100]]
        result=f.forward_diagnostics(features,targets,days,closes,opens,start=days[90],end=days[-1])
        self.assertGreater(result['censored'],21)
        self.assertNotIn(days[90],[r['decision'] for r in result['rows']])

    def test_win_denominator_includes_flat_and_excludes_open(self):
        episodes=[{'status':s,'net_pnl':p,'fees_flip_gross_profit':False} for s,p in [('closed',2),('closed',-1),('closed',0),('open_censored',100)]]
        holding={'episodes':episodes,'assets':{'X':{'allocated_fees':.1,'gross_pnl':1.1}}}
        run={'records':[{'date':'2021-01-01','return':.1},{'date':'2021-01-31','return':-.05},{'date':'2021-02-01','return':-.8}]}
        result=f.win_statistics(holding,run)
        self.assertEqual(result['closed_net_win_rate'],1/3)
        self.assertEqual(result['open_censored_episodes'],1)
        self.assertEqual(result['profit_factor'],2)
        self.assertEqual(result['payoff_ratio'],2)
        self.assertEqual(result['complete_months'],1)

    def test_joint_goal_requires_all_three_metrics_in_every_cell(self):
        base={k:{'cagr':.2,'max_drawdown':-.2,'wins':{'closed_net_win_rate':.4}} for k in ('a','b','c','d')}
        candidate={k:{'cagr':.21,'max_drawdown':-.19,'wins':{'closed_net_win_rate':.41}} for k in base}
        self.assertTrue(f.objective_gate(candidate,base)['passed'])
        candidate['d']['cagr']=.19
        self.assertFalse(f.objective_gate(candidate,base)['passed'])

    def test_contract_rejects_post_freeze_economic_changes(self):
        c=f.read_contract(CONTRACT)
        for key,value in (('planned_curves',40),('orders_authorized',True),('mechanisms',{})):
            other=copy.deepcopy(c);other[key]=value
            with tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'contract.json';path.write_text(json.dumps(other))
                with self.assertRaises(ValueError):f.read_contract(path)


if __name__=='__main__':unittest.main()
