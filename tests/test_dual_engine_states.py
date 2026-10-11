import copy
import datetime as dt
import json
import math
import tempfile
import unittest
from pathlib import Path

from qount.research import dual_engine_states as r
from qount.research.dual_engine_state_clock import replay_state_clock
from qount.research.dual_engine_family_clock import replay_family_clock
from qount.research.c60_pit_universe import Asset

CONTRACT = Path(__file__).resolve().parents[1]/'config/dual-engine-states-20261005.json'


class StateTests(unittest.TestCase):
    def test_state_priority_and_sign_boundaries(self):
        def state(**kw):
            args=dict(rank=.9,r20=.1,r60=.3,prior20=.2,rebound=False);args.update(kw)
            return r.classify_state(**args)
        self.assertEqual(state(),'mature')
        self.assertEqual(state(rank=None,rebound=True),'unknown')
        self.assertEqual(state(rebound=True,r20=-.1),'rebound')
        self.assertEqual(state(r20=0),'fading')
        self.assertEqual(state(r20=.3),'accelerating')
        self.assertEqual(state(rank=.5),'balanced')
        self.assertEqual(state(rank=.75),'mature')

    def test_market_rebound_requires_all_three_conditions(self):
        falling=[100*math.exp(-.005*i) for i in range(41)]
        rebound=falling+[falling[-1]*math.exp(.003*i+.02*(i%2)) for i in range(1,21)]
        self.assertTrue(r.market_rebound(rebound))
        self.assertFalse(r.market_rebound([100*1.01**i for i in range(61)]))
        self.assertFalse(r.market_rebound([100]*61))
        self.assertFalse(r.market_rebound(None))

    def test_rank_history_excludes_current_and_unknown_does_not_cut(self):
        prices=tuple(100*math.exp(.002*t+.01*math.sin(t)) for t in range(400))
        asset=Asset('X','BTCUSDT',0,prices,(100.,)*400)
        source={t:{'X':.4,'G':.1} for t in range(100,400)}
        gold=Asset('G','PAXGUSDT',0,prices,(100.,)*400)
        states=r.state_panel(source,{'X':asset,'G':gold})
        self.assertEqual(states[119]['X']['history_count'],59)
        self.assertIsNone(states[119]['X']['rank'])
        self.assertEqual(states[120]['X']['history_count'],60)
        self.assertEqual(states[399]['X']['history_count'],252)
        current=r.efficiency(asset.window(120,61));history=[r.efficiency(asset.window(t,61)) for t in range(60,120)]
        expected=(sum(x<current for x in history)+.5*sum(x==current for x in history))/60
        self.assertEqual(states[120]['X']['rank'],expected)
        self.assertNotIn('G',states[120])
        for rule in r.CANDIDATES:
            targets=r.candidate_targets(source,states,rule)
            self.assertEqual(targets[119]['X'],.4);self.assertEqual(targets[200]['G'],.1)

    def test_future_prices_do_not_change_state_or_target_prefix(self):
        prices=tuple(100*math.exp(.002*t+.01*math.sin(t)) for t in range(400))
        source={t:{'X':.4} for t in range(100,400)}
        assets={'X':Asset('X','BTCUSDT',0,prices,(100.,)*400)}
        changed={'X':Asset('X','BTCUSDT',0,prices[:350]+(1.,)*50,(100.,)*400)}
        a=r.state_panel(source,assets);b=r.state_panel(source,changed)
        self.assertEqual({t:f for t,f in a.items() if t<350},{t:f for t,f in b.items() if t<350})
        for rule in r.CANDIDATES:
            x=r.candidate_targets(source,a,rule);y=r.candidate_targets(source,b,rule)
            self.assertEqual({t:f for t,f in x.items() if t<350},{t:f for t,f in y.items() if t<350})

    def test_state_sizing_has_separate_mechanism_ablations(self):
        source={0:{'M':.2,'R':.2,'X':.2,'G':.1,'Z':0}}
        states={0:{'M':{'state':'mature'},'R':{'state':'rebound'},'X':{'state':'accelerating'}}}
        self.assertEqual(r.candidate_targets(source,states,'mature_half')[0]['M'],.1)
        self.assertEqual(r.candidate_targets(source,states,'mature_half')[0]['R'],.2)
        self.assertEqual(r.candidate_targets(source,states,'rebound_half')[0]['M'],.2)
        self.assertEqual(r.candidate_targets(source,states,'rebound_half')[0]['R'],.1)
        self.assertEqual(r.candidate_targets(source,states,'transition_fill'),source)
        for rule in r.CANDIDATES:
            result=r.candidate_targets(source,states,rule)[0]
            self.assertEqual(result['Z'],0);self.assertEqual(result['G'],.1)
            self.assertLessEqual(sum(result.values()),.7+1e-12)

    def test_events_require_continuous_source_and_qualified_transition(self):
        source={t:{'X':.2} for t in range(5)}
        states={t:{'X':{'state':s}} for t,s in enumerate(('unknown','accelerating','mature','accelerating','accelerating'))}
        self.assertEqual(r.transition_events(source,states),{0:[],1:[],2:[],3:['X'],4:[]})
        source[2]={}
        self.assertEqual(r.transition_events(source,states)[3],[])

    def test_contract_rejects_economic_drift(self):
        c=r.read_contract(CONTRACT)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'c.json'
            for key,value in (('planned_curves',44),('mechanisms',{}),('orders_authorized',True),('state_settings',{})):
                d=copy.deepcopy(c);d[key]=value;p.write_text(json.dumps(d))
                with self.assertRaises(ValueError):r.read_contract(p)


class StateClockTests(unittest.TestCase):
    def fixture(self):
        days=[(dt.date(2021,1,1)+dt.timedelta(days=i)).isoformat() for i in range(25)]
        prices={k:{d:100. for d in days} for k in ('X','Y')}
        targets={t:{'X':.4,'Y':.2} for t in range(len(days))}
        states={t:{k:{'state':'accelerating'} for k in ('X','Y')} for t in targets}
        return days,prices,targets,states

    def run_fixture(self,*,events=None,states=None,targets=None,closes=None,risk_scale=None,lag=2):
        days,prices,aims,st=self.fixture()
        return replay_state_clock(days,closes or prices,prices,targets or aims,states=states or st,events=events or {},
            start=days[2],lag=lag,cost_bps=50,core_assets=('X',),risk_scale=risk_scale)

    def test_no_events_preserve_original_financial_path(self):
        days,prices,targets,states=self.fixture()
        original=replay_family_clock(days,prices,prices,targets,start=days[2],lag=2,cost_bps=50,clock_mode='sat_week',core_assets=('X',))
        new=self.run_fixture()
        for a,b in zip(original['records'],new['records'],strict=True):
            for key in ('return','cash','nav','units','weights','turnover','cost_fraction','vintages'):
                self.assertEqual(a[key],b[key])

    def test_acceleration_event_is_asset_scoped_and_risk_scaled(self):
        run=self.run_fixture(events={5:['X']},risk_scale=lambda t,w:.5)
        p=next(d for d in run['decisions'] if d['decision']=='2021-01-06')
        self.assertEqual(p['scope_assets'],['X'])
        self.assertEqual(p['event_only_assets'],['X'])
        self.assertNotIn('X',p['sells']);self.assertLessEqual(p['target']['X'],.2)
        row=run['records'][5]
        self.assertEqual(row['date'],'2021-01-08')
        self.assertLessEqual(row['units'].get('Y',0),run['records'][4]['units'].get('Y',0))

    def test_delayed_state_cancellation_freezes_held_units(self):
        days,prices,targets,states=self.fixture();states[6]['X']['state']='mature'
        run=self.run_fixture(events={5:['X']},states=states)
        row=next(x for x in run['records'] if x['date']==days[7])
        prior=next(x for x in run['records'] if x['date']==days[6])
        self.assertEqual(row['cancelled_state_events'],['X'])
        self.assertEqual(row['units']['X'],prior['units']['X'])
        self.assertEqual(row['state_event_buy_notional'],0)

    def test_latest_nominal_zero_still_exits_cancelled_asset(self):
        days,prices,targets,states=self.fixture();targets[6]={'Y':.2}
        run=self.run_fixture(events={5:['X']},targets=targets)
        row=next(x for x in run['records'] if x['date']==days[7])
        self.assertIn('X',row['cancelled_stale']);self.assertNotIn('X',row['units'])

    def test_regular_scheduled_scope_is_not_cancelled_by_event_state(self):
        days,prices,targets,states=self.fixture();states[10]['Y']['state']='mature'
        run=self.run_fixture(events={9:['Y']},states=states)
        plan=next(p for p in run['decisions'] if p['decision']==days[9])
        self.assertEqual(plan['event_only_assets'],[])
        row=next(x for x in run['records'] if x['date']==days[11])
        self.assertEqual(row['cancelled_state_events'],[])

    def test_cash_units_actual_gross_fees_and_vintages_conserve(self):
        days,prices,targets,states=self.fixture()
        run=self.run_fixture(events={5:['X'],12:['Y']});units={};cash=nav=1.
        for row in run['records']:
            new=row['units'];names=set(units)|set(new)
            traded=sum(abs(new.get(k,0)-units.get(k,0))*100 for k in names)
            cash-=sum((new.get(k,0)-units.get(k,0))*100 for k in names)+traded*.005
            self.assertAlmostEqual(cash,row['cash'],places=12)
            self.assertAlmostEqual(cash+sum(q*100 for q in new.values()),row['nav'],places=12)
            self.assertAlmostEqual(nav*(1+row['return']),row['nav'],places=12)
            for k,v in row['vintages'].items():self.assertAlmostEqual(sum(v.values()),new[k],places=12)
            self.assertGreaterEqual(row['cash'],-1e-12)
            units=new;nav=row['nav']

    def test_future_states_events_prices_and_targets_preserve_prefix(self):
        days,prices,targets,states=self.fixture();changed=copy.deepcopy(prices);st=copy.deepcopy(states);aims=copy.deepcopy(targets)
        for t in range(18,25):
            changed['X'][days[t]]=1000.;st[t]['X']['state']='mature';aims[t]={'Y':.9}
        original=self.run_fixture(events={5:['X']})
        newer=self.run_fixture(events={5:['X'],19:['Y']},states=st,closes=changed,targets=aims)
        self.assertEqual(original['records'][:16],newer['records'][:16])


if __name__=='__main__':unittest.main()
