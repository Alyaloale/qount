import copy
import dataclasses
import json
import math
from pathlib import Path
import tempfile
import unittest
from qount.research import dual_engine_regimes as r
from qount.research import dual_engine_nextgen as previous
from qount.research.dual_engine_regimes_data import load_inverse, INVERSE
from qount.research.dual_engine_optimization import EquityPanel, file_hash
from test_dual_engine_expansion import crypto_fixture, macro_fixture

CONTRACT = Path(__file__).resolve().parents[1] / "config/dual-engine-regimes-20261004.json"


def panel_fixture():
    p = macro_fixture()
    maps = [dict(p.closes), dict(p.total_closes), dict(p.total_opens)]
    for m in maps:
        for s in INVERSE:
            m[s] = tuple(100 * math.exp(-.0004 * i + .002 * math.sin(i / 3)) for i in range(len(p.dates)))
    return EquityPanel(p.dates, *maps)


def assets_fixture():
    axis, assets = crypto_fixture()
    reference = next(a for a in assets.values() if a.symbol == "BTCUSDT")
    for s, slope in (("ETHUSDT", .0018), ("PAXGUSDT", .0003)):
        assets[s] = dataclasses.replace(reference, asset_id=s, symbol=s,
            closes=tuple(100 * math.exp(slope * i + .003 * math.sin(i / 7)) for i in range(len(reference.closes))))
    return axis, assets


class RegimesTests(unittest.TestCase):
    def test_contract_inventory(self):
        c = r.read_contract(CONTRACT)
        self.assertEqual(c["new_candidate_trials"], len(r.G20_CANDIDATES + r.C60_CANDIDATES))
        self.assertEqual(c["planned_curves"], 4 * len(r.G20_CONTROLS + r.G20_CANDIDATES + r.C60_CONTROLS + r.C60_CANDIDATES))

    def test_changed_cost_date_or_core_contract_rejected(self):
        original = json.loads(CONTRACT.read_text())
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "contract.json"
            for line, key, value in (("g20", "end", "2026-09-30"), ("g20", "cost_bps", [0, 20]),
                                    ("c60", "annual_volatility_cap", .9)):
                c = copy.deepcopy(original); c[line][key] = value; p.write_text(json.dumps(c))
                with self.assertRaises(ValueError):r.read_contract(p)

    def test_handoff_normal_exit_retains_unabsorbed_probe(self):
        state, probe, core = r.handoff_step("recovery", True, panic=False, slow_recovered=True,
            fast_recovered=True, long_strength=0., fast_strength=.6)
        self.assertEqual(state, "normal")
        self.assertTrue(probe)
        self.assertAlmostEqual(core, .18)
        state, probe, core = r.handoff_step(state, probe, panic=False, slow_recovered=True,
            fast_recovered=True, long_strength=.4, fast_strength=.6)
        self.assertFalse(probe)
        self.assertAlmostEqual(core, .28)

    def test_handoff_invalid_fast_signal_releases_probe(self):
        state, probe, core = r.handoff_step("normal", True, panic=False, slow_recovered=False,
            fast_recovered=False, long_strength=0., fast_strength=.8)
        self.assertFalse(probe)
        self.assertEqual(core, 0.)

    def test_new_panic_clears_probe_and_shrinks_core(self):
        state, probe, core = r.handoff_step("recovery", True, panic=True, slow_recovered=False,
            fast_recovered=False, long_strength=.4, fast_strength=.8)
        self.assertEqual(state, "defensive");self.assertFalse(probe)
        self.assertAlmostEqual(core, .10)

    def test_all_previous_controls_exact(self):
        c = r.read_contract(CONTRACT);p = panel_fixture()
        rates = {s: [0.] * len(p.dates) for s in ("DFII10", "T10YIE")}
        for rule in r.G20_CONTROLS:
            self.assertEqual(r.equity_targets(p, c["g20"], rule, rates), previous.equity_targets(p, c["g20"], rule, rates))
        axis, assets = assets_fixture()
        for rule in r.C60_CONTROLS:
            self.assertEqual(r.crypto_targets(axis, assets, c["c60"], rule), previous.crypto_targets(axis, assets, c["c60"], rule, {}))

    def test_inverse_duration_uses_actual_instrument(self):
        p = panel_fixture();maps=[dict(p.closes),dict(p.total_closes),dict(p.total_opens)]
        for m in maps:
            m["TLT"] = tuple(100 * math.exp(-.01 * i) for i in range(len(p.dates)))
        p = EquityPanel(p.dates, *maps)
        long = r.macro_book(p, 180, directional=False);directional = r.macro_book(p, 180)
        self.assertNotIn("TBF", long)
        self.assertNotIn("TLT", directional)
        self.assertAlmostEqual(directional["TBF"], .1125)
        self.assertEqual({k:v for k,v in directional.items() if k!='TBF'}, long)

    def test_inverse_hedge_budget_does_not_double_count_equity_sources(self):
        p=panel_fixture();maps=[dict(p.closes),dict(p.total_closes),dict(p.total_opens)]
        for m in maps:
            for s in ("SPY","QQQ","TLT"):m[s]=tuple(100*math.exp(-.01*i) for i in range(len(p.dates)))
        hedge=r.crisis_hedge(EquityPanel(p.dates,*maps),180)
        self.assertEqual(len(set(hedge)&{'SH','PSQ'}),1)
        self.assertIn('TBF',hedge);self.assertAlmostEqual(sum(hedge.values()),.15)

    def test_all_equity_budgets_and_monthly_macro_clock(self):
        c=r.read_contract(CONTRACT);p=panel_fixture();rates={s:[0.]*len(p.dates) for s in ('DFII10','T10YIE')}
        monthly=r.old.g20_signals(p)
        for rule in r.G20_CANDIDATES:
            targets,events=r.equity_targets(p,c['g20'],rule,rates)
            for w in targets.values():
                self.assertAlmostEqual(sum(w.values()),1.)
                self.assertTrue(all(v>=0 for v in w.values()))
            for a,b in zip(events,events[1:]):
                if p.dates.index(b['date']) not in monthly:self.assertEqual(a['macro_monthly_shape'],b['macro_monthly_shape'])

    def test_autonomous_satellite_changes_only_satellite_gate(self):
        c=r.read_contract(CONTRACT);axis,assets=assets_fixture()
        baseline,events=r.crypto_targets(axis,assets,c['c60'],'residual2')
        autonomous,traces=r.crypto_targets(axis,assets,c['c60'],'autonomous_satellites')
        for t,trace in traces.items():
            self.assertLessEqual(sum(autonomous[t].values()),1.)
            self.assertAlmostEqual(trace['core_before_risk_cap'],.7*trace['long_strength'])
            if trace['selection'] is not None:
                self.assertEqual(trace['selection']['universe'],
                    [k for k in events[t] if assets[k].symbol not in ('BTCUSDT','PAXGUSDT')])
        self.assertTrue(any(autonomous[t]!=baseline[t] for t in autonomous))

    def test_dual_core_excludes_eth_from_satellite_pool(self):
        c=r.read_contract(CONTRACT);axis,assets=assets_fixture()
        _,traces=r.crypto_targets(axis,assets,c['c60'],'dual_autonomous')
        self.assertTrue(any('ETHUSDT' in e['pre_risk_target'] for e in traces.values()))
        for e in traces.values():self.assertNotIn('ETHUSDT',e['selected'])

    def test_asset_lookup_is_causal_across_segments(self):
        axis,assets=assets_fixture();eth=assets.pop('ETHUSDT')
        early=dataclasses.replace(eth,asset_id='ETHUSDT@early',closes=eth.closes[:400],quote=eth.quote[:400])
        future=dataclasses.replace(eth,asset_id='ETHUSDT@future',start=410,closes=eth.closes[410:],quote=eth.quote[410:])
        assets[early.asset_id]=early;assets[future.asset_id]=future
        self.assertEqual(r.asset_at(assets,'ETHUSDT',390),early)
        self.assertIsNone(r.asset_at(assets,'ETHUSDT',405))

    def test_future_crypto_prices_and_volumes_do_not_change_prefix(self):
        c=r.read_contract(CONTRACT);axis,assets=assets_fixture();changed=copy.deepcopy(assets)
        for a in changed.values():
            object.__setattr__(a,'closes',tuple(v if i+a.start<400 else v*10 for i,v in enumerate(a.closes)))
            object.__setattr__(a,'quote',tuple(v if i+a.start<400 else v*100 for i,v in enumerate(a.quote)))
        for rule in r.C60_CANDIDATES:
            a,_=r.crypto_targets(axis,assets,c['c60'],rule);b,_=r.crypto_targets(axis,changed,c['c60'],rule)
            self.assertEqual({t:w for t,w in a.items() if t<400},{t:w for t,w in b.items() if t<400})

    def test_future_equity_prices_do_not_change_prefix(self):
        c=r.read_contract(CONTRACT);p=panel_fixture();maps=[]
        for m in (p.closes,p.total_closes,p.total_opens):
            maps.append({s:tuple(v if i<190 else v*20 for i,v in enumerate(prices)) for s,prices in m.items()})
        changed=EquityPanel(p.dates,*maps);rates={s:[0.]*len(p.dates) for s in ('DFII10','T10YIE')}
        for rule in r.G20_CANDIDATES:
            a,_=r.equity_targets(p,c['g20'],rule,rates);b,_=r.equity_targets(changed,c['g20'],rule,rates)
            self.assertEqual({t:w for t,w in a.items() if t<190},{t:w for t,w in b.items() if t<190})

    def test_inverse_calendar_gap_is_not_filled(self):
        p=panel_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for s in INVERSE:
                value={'chart':{'result':[{'meta':{'symbol':s},'timestamp':[],
                    'indicators':{'quote':[{'open':[],'close':[]}],'adjclose':[{'adjclose':[]}]}}]}}
                (root/(s+'.source.json')).write_text(json.dumps(value))
            (root/'manifest.json').write_text(json.dumps({'files':{x.name:file_hash(x) for x in root.iterdir()}}))
            with self.assertRaisesRegex(ValueError,'inverse_calendar_gap'):load_inverse(p,root)
