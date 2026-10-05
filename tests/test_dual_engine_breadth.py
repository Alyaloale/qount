import copy
import dataclasses
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from qount.research import dual_engine_breadth as r
from qount.research import dual_engine_regimes as prior
from qount.research.dual_engine_optimization import EquityPanel
from test_dual_engine_regimes import panel_fixture, assets_fixture

CONTRACT = Path(__file__).resolve().parents[1] / 'config/dual-engine-breadth-20261005.json'


class BreadthTests(unittest.TestCase):
    def test_contract_inventory_and_reject_changed_protocol(self):
        c = r.read_contract(CONTRACT)
        self.assertEqual(c['planned_curves'], 4 * len(r.G20_CONTROLS + r.G20_CANDIDATES + r.C60_CONTROLS + r.C60_CANDIDATES))
        self.assertEqual(c['new_candidate_trials'], 14)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'contract.json'
            for line, key, value in [('g20','cost_bps',[0,20]), ('c60','end','2026-09-30'), ('c60','annual_volatility_cap',.8)]:
                changed = copy.deepcopy(c);changed[line][key] = value;p.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):r.read_contract(p)

    def test_previous_controls_exact(self):
        c=r.read_contract(CONTRACT);p=panel_fixture();rates={s:[0.]*len(p.dates) for s in ('DFII10','T10YIE')}
        for rule in r.G20_CONTROLS:
            self.assertEqual(r.equity_targets(p,c['g20'],rule,rates),prior.equity_targets(p,c['g20'],rule,rates))
        axis,assets=assets_fixture()
        for rule in r.C60_CONTROLS:
            self.assertEqual(r.crypto_targets(axis,assets,c['c60'],rule),prior.crypto_targets(axis,assets,c['c60'],rule))

    def test_inverse_exit_follows_source_rebound(self):
        p=panel_fixture();maps=[dict(m) for m in (p.closes,p.total_closes,p.total_opens)]
        for m in maps:
            for s in ('SPY','QQQ','TLT'):
                m[s]=tuple(100*math.exp(-.003*i) for i in range(len(p.dates)))
        down=EquityPanel(p.dates,*maps)
        self.assertAlmostEqual(sum(r.protection_book(down,180,.15,'inverse').values()),.15)
        for m in maps:
            for s in ('SPY','QQQ','TLT'):
                a=list(m[s])
                for i in range(176,181):a[i]=a[175]*math.exp(.007*(i-175))
                m[s]=tuple(a)
        rebound=EquityPanel(p.dates,*maps)
        self.assertTrue(all(prior.signed_signal(rebound,s,180)<0 for s in ('SPY','QQQ','TLT')))
        self.assertEqual(r.protection_book(rebound,180,.15,'inverse'),{})

    def test_sector_budgets_and_freed_budget_conservation(self):
        c=r.read_contract(CONTRACT);p=panel_fixture();rates={s:[0.]*len(p.dates) for s in ('DFII10','T10YIE')}
        for rule in r.G20_CANDIDATES:
            targets,events=r.equity_targets(p,c['g20'],rule,rates)
            for e in events:
                w=e['target'];self.assertAlmostEqual(sum(w.values()),1.)
                self.assertTrue(all(x>=0 for x in w.values()))
                self.assertLessEqual(sum(e['protection'].values()),e['released_equity_budget']+1e-12)
                self.assertLessEqual(sum(w[s] for s in e['selected']),.2+1e-12)
                self.assertEqual(len(e['selected']),3 if rule.startswith('sector3') else 1)

    def test_four_corner_monthly_universe_is_matched(self):
        c=r.read_contract(CONTRACT);axis,assets=assets_fixture()
        btc=next(a for a in assets.values() if a.symbol=='BTCUSDT')
        _,b=r.crypto_targets(axis,assets,c['c60'],'dual_pool_all')
        _,d=r.crypto_targets(axis,assets,c['c60'],'dual_core')
        _,e=r.crypto_targets(axis,assets,c['c60'],'btc_pool_ex_eth')
        for t,trace in b.items():
            if trace['selection'] is not None:
                expected,_=r.previous.select_satellites(assets,t,btc.window(t),axis.dates[t],'residual2',{})
                self.assertEqual(expected,trace['selected'])
                self.assertEqual(d[t]['selected'],e[t]['selected'])
        for t,trace in e.items():
            self.assertAlmostEqual(trace['core_before_risk_cap'],.7*trace['long_strength'])
            self.assertNotIn('ETHUSDT',trace['selected'])

    def test_dual_pool_adds_eth_core_and_satellite(self):
        c=r.read_contract(CONTRACT);axis,assets=assets_fixture();eth=assets['ETHUSDT']
        with patch.object(r,'satellite_selection',return_value=((eth.asset_id,),{'selected':(eth.asset_id,)})):
            _,events=r.crypto_targets(axis,assets,c['c60'],'dual_pool_all')
        event=next(e for e in events.values() if e['selected'] and e['long_strength']>0 and e['eth_strength']>0)
        expected=.2*event['eth_strength']+.15*event['long_strength']*event['eth_strength']
        self.assertAlmostEqual(event['pre_risk_target'][eth.asset_id],expected)

    def test_crypto_public_gate_and_total_budgets(self):
        c=r.read_contract(CONTRACT);axis,assets=assets_fixture()
        for rule in r.C60_CANDIDATES:
            targets,events=r.crypto_targets(axis,assets,c['c60'],rule)
            for t,e in events.items():
                self.assertLessEqual(sum(e['pre_risk_target'].values()),1.+1e-12)
                self.assertLessEqual(sum(targets[t].values()),1.+1e-12)
                if rule.endswith('publicgate'):
                    self.assertEqual(e['satellite_gate'],max(e['long_strength'],e['eth_strength']))
                else:self.assertEqual(e['satellite_gate'],e['long_strength'])
                if e['satellite_gate']==0:
                    self.assertTrue(all(assets[k].symbol in ('BTCUSDT','ETHUSDT','PAXGUSDT') for k in targets[t]))

    def test_gold_transfer_spends_only_inactive_satellite_budget(self):
        c=r.read_contract(CONTRACT);axis,assets=assets_fixture()
        _,events=r.crypto_targets(axis,assets,c['c60'],'crisis_gold_transfer')
        for e in events.values():
            self.assertAlmostEqual(e['gold_budget']+.3*e['long_strength'],.3)
            self.assertLessEqual(e['pre_risk_target'].get('PAXGUSDT',0),e['gold_budget']+1e-12)

    def test_risk_satellite_shares_preserve_vacant_slots_and_monthly_clock(self):
        c=r.read_contract(CONTRACT);axis,assets=assets_fixture()
        _,equal=r.crypto_targets(axis,assets,c['c60'],'dual_sat4')
        _,risk=r.crypto_targets(axis,assets,c['c60'],'dual_sat4_risk')
        last=None
        for t,e in risk.items():
            self.assertEqual(e['selected'],equal[t]['selected'])
            self.assertAlmostEqual(sum(e['satellite_shares'].values()),.3*len(e['selected'])/4)
            if last is not None and e['selection'] is None:self.assertEqual(e['satellite_shares'],last)
            last=e['satellite_shares']

    def test_future_crypto_prices_and_volumes_leave_prefix_unchanged(self):
        c=r.read_contract(CONTRACT);axis,assets=assets_fixture();changed=copy.deepcopy(assets)
        for a in changed.values():
            object.__setattr__(a,'closes',tuple(v if i+a.start<400 else v*10 for i,v in enumerate(a.closes)))
            object.__setattr__(a,'quote',tuple(v if i+a.start<400 else v*100 for i,v in enumerate(a.quote)))
        for rule in r.C60_CANDIDATES:
            a,_=r.crypto_targets(axis,assets,c['c60'],rule);b,_=r.crypto_targets(axis,changed,c['c60'],rule)
            self.assertEqual({t:w for t,w in a.items() if t<400},{t:w for t,w in b.items() if t<400})

    def test_future_equity_prices_leave_prefix_unchanged(self):
        c=r.read_contract(CONTRACT);p=panel_fixture();maps=[]
        for m in (p.closes,p.total_closes,p.total_opens):
            maps.append({s:tuple(v if i<190 else v*20 for i,v in enumerate(a)) for s,a in m.items()})
        changed=EquityPanel(p.dates,*maps);rates={s:[0.]*len(p.dates) for s in ('DFII10','T10YIE')}
        for rule in r.G20_CANDIDATES:
            a,_=r.equity_targets(p,c['g20'],rule,rates);b,_=r.equity_targets(changed,c['g20'],rule,rates)
            self.assertEqual({t:w for t,w in a.items() if t<190},{t:w for t,w in b.items() if t<190})

    def test_future_gold_segment_does_not_fill_past_gap(self):
        c=r.read_contract(CONTRACT);axis,assets=assets_fixture();gold=assets.pop('PAXGUSDT')
        future=dataclasses.replace(gold,asset_id='PAXGUSDT@future',start=410,closes=gold.closes[410:],quote=gold.quote[410:])
        assets[future.asset_id]=future
        targets,_=r.crypto_targets(axis,assets,c['c60'],'family_gold')
        self.assertTrue(all(future.asset_id not in w for t,w in targets.items() if t<410))
