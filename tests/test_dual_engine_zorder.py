import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from qount.research import dual_engine_zorder as r
from qount.research.dual_engine_family_clock import family_scope, replay_family_clock
from qount.research.dual_engine_coordinator import joint_plan, replay_coordinator
from qount.research.dual_engine_capital import capital_contributions

CONTRACT=Path(__file__).resolve().parents[1]/'config/dual-engine-zorder-20261005.json'


def fixture():
    days=[(dt.date(2021,1,1)+dt.timedelta(days=i)).isoformat() for i in range(30)]
    prices={k:{d:100. for d in days} for k in ('X','Y','Z','GLD','BIL')}
    aims={t:{'X':.4,'Y':.2} for t in range(len(days))}
    return days,prices,aims


class FamilyClockTests(unittest.TestCase):
    def run_fixture(self,mode,lag=2,aims=None,closes=None,risk_scale=None):
        days,prices,target=fixture()
        return replay_family_clock(days,closes or prices,prices,aims or target,start=days[2],lag=lag,cost_bps=50,clock_mode=mode,core_assets=('X','Z'),risk_scale=risk_scale)

    def test_scheduled_family_ownership(self):
        names={'X','Y','Z'};core={'X','Z'}
        self.assertEqual(family_scope('2021-01-03','core_week',set(),core,names), (core,core))
        self.assertEqual(family_scope('2021-01-03','sat_week',set(),core,names), ({'Y'},{'Y'}))
        self.assertEqual(family_scope('2021-01-06','split_week',set(),core,names), ({'Y'},{'Y'}))
        self.assertEqual(family_scope('2021-01-04','split_week',set(),core,names), (set(),set()))
        with self.assertRaises(ValueError):family_scope('2021-01-03','unknown',set(),core,names)

    def test_core_recovery_coupling_is_separate_ablation(self):
        names={'X','Y','Z'};cores={'X','Z'}
        for mode in ('core_week','sat_week','split_week'):
            self.assertIsNone(family_scope('2021-01-04',mode,{'Z'},cores,names)[0])
        self.assertEqual(family_scope('2021-01-04','split_local',{'Z'},cores,names)[0],cores)
        self.assertEqual(family_scope('2021-01-04','split_local',{'Z','Y'},cores,names)[0],names)

    def test_sunday_and_wednesday_have_different_acquisition_scopes(self):
        run=self.run_fixture('split_week');p={x['decision']:x for x in run['decisions']}
        self.assertEqual(p['2021-01-03']['scope_assets'],['X'])
        self.assertEqual(p['2021-01-06']['scope_assets'],['Y'])
        self.assertEqual(p['2021-01-04']['kind'],'reduce')
        self.assertEqual(p['2021-01-03']['refresh_assets'],['X'])

    def test_original_staging_and_continuation_survive_new_clocks(self):
        days,_,aims=fixture();aims={t:{'X':.4,**({'Y':.2} if t>=5 else {})} for t in aims}
        for mode in r.C60_CANDIDATES:
            p={x['decision']:x for x in self.run_fixture(mode,aims=aims)['decisions']}
            self.assertEqual(p[days[5]]['target']['Y'],.1)
            self.assertEqual(p[days[6]]['target']['Y'],.2)
            self.assertEqual(p[days[6]]['continuing_assets'],['Y'])

    def test_latest_closed_zero_cancels_delayed_acquisition(self):
        days,_,aims=fixture();aims={t:{'X':.4,**({'Y':.2} if t>=5 else {})} for t in aims};aims[6]={'X':.4}
        for mode in r.C60_CANDIDATES:
            row=next(x for x in self.run_fixture(mode,aims=aims)['records'] if x['date']==days[7])
            self.assertIn('Y',row['cancelled_stale']);self.assertNotIn('Y',row['units'])

    def test_shared_cash_vintages_and_complement_reductions_conserve(self):
        days,prices,_=fixture()
        for mode in r.C60_CANDIDATES:
            units={};cash=nav=1.
            for row in self.run_fixture(mode)['records']:
                new=row['units'];day=row['date'];names=set(units)|set(new)
                traded=sum(abs(new.get(k,0.)-units.get(k,0.))*prices[k][day] for k in names)
                cash-=sum((new.get(k,0.)-units.get(k,0.))*prices[k][day] for k in names)+traded*.005
                self.assertAlmostEqual(cash,row['cash'],places=12)
                self.assertAlmostEqual(cash+sum(q*prices[k][day] for k,q in new.items()),row['nav'],places=12)
                self.assertAlmostEqual(nav*(1+row['return']),row['nav'],places=12)
                self.assertGreaterEqual(cash,-1e-12)
                for k,v in row['vintages'].items():self.assertAlmostEqual(sum(v.values()),new[k],places=12)
                if row['trade_clock']=='reduce':self.assertEqual(row['risk_buy_notional'],0.)
                if row['trade_clock']=='recover':
                    for k in names-set(row['requested_scope']):self.assertLessEqual(new.get(k,0.),units.get(k,0.)+1e-12)
                nav=row['nav'];units=new

    def test_scope_risk_gate_covers_combined_plan(self):
        p=next(x for x in self.run_fixture('split_week',lag=1,risk_scale=lambda t,w:.5)['decisions'] if x['decision']=='2021-01-06')
        self.assertEqual(p['risk_scale'],.5);self.assertLessEqual(p['target']['X'],.2);self.assertEqual(p['target']['Y'],.1)
        self.assertNotIn('Y',p['sells'])

    def test_future_prices_and_nominal_targets_preserve_prefix(self):
        days,prices,aims=fixture();future=copy.deepcopy(aims);changed=copy.deepcopy(prices)
        for t in range(18,len(days)):future[t]={'Z':.8};changed['X'][days[t]]=500.
        for mode in r.C60_CANDIDATES:
            self.assertEqual(self.run_fixture(mode)['records'][:16],self.run_fixture(mode,aims=future,closes=changed)['records'][:16])


class CoordinatorTests(unittest.TestCase):
    def books(self):return {'equity_crisis':{'cash':0.,'units':{'X':.9,'BIL':.1}},'gold':{'cash':0.,'units':{'GLD':.2}},'reserve':{'cash':80.,'units':{}}}

    def test_joint_budget_accounts_for_new_source_not_only_held_risk(self):
        books=self.books();marks={'X':100.,'GLD':100.,'BIL':100.}
        source={'equity_crisis':{'Y':1.,'BIL':0.},'gold':{'GLD':1.},'reserve':{'BIL':1.}}
        p=joint_plan('2021-01-04',books,marks,source,{'equity_crisis':('X','Y'),'gold':(),'reserve':()},.4)['books']['equity_crisis']
        self.assertTrue(p['binding']);self.assertIsNone(p['scope']);self.assertNotIn('X',p['target'])
        self.assertAlmostEqual(p['planned_risk_weight'],.4);self.assertAlmostEqual(p['target']['Y'],.8)
        self.assertAlmostEqual(p['target']['BIL'],.2)

    def test_mixed_frozen_complement_is_cash_feasible_before_budget(self):
        books=self.books();books['equity_crisis']['units']={'X':.8,'Y':.1,'BIL':.1}
        p=joint_plan('2021-01-04',books,{'X':100.,'Y':100.,'GLD':100.,'BIL':100.},{'equity_crisis':{'Y':.8},'gold':{},'reserve':{}},{'equity_crisis':('Y',),'gold':(),'reserve':()},.4)['books']['equity_crisis']
        self.assertAlmostEqual(p['feasible_shape']['X'],.8);self.assertAlmostEqual(p['feasible_shape']['Y'],.2)
        self.assertAlmostEqual(sum(p['target'].values()),1.)
        self.assertLessEqual(p['planned_risk_weight'],.4+1e-12)

    def test_nonbinding_preserves_source_scope(self):
        books=self.books()
        p=joint_plan('2021-01-04',books,{'X':100.,'GLD':100.,'BIL':100.},{'equity_crisis':{'BIL':1.},'gold':{},'reserve':{}},{'equity_crisis':('X',),'gold':(),'reserve':()},.4)
        self.assertFalse(p['books']['equity_crisis']['binding']);self.assertEqual(p['books']['equity_crisis']['scope'],('X',));self.assertEqual(p['books']['gold']['scope'],())

    def run_fixture(self,lag=2,changed=None,aims=None):
        days,prices,_=fixture();prices['X']={d:100.*1.08**i for i,d in enumerate(days)}
        targets={t:{'X':.2,'GLD':.2,'BIL':.6} for t in range(len(days))}
        targets[8]={'Y':.2,'GLD':.2,'BIL':.6}
        return days,prices,targets,replay_coordinator(days,changed or prices,prices,aims or targets,start=days[3],lag=lag,cost_bps=40,full_refresh={1,12,24},limit=.2)

    def test_joint_source_and_budget_fill_once_without_epoch_cancellation(self):
        days,prices,targets,run=self.run_fixture();changed=fills=0
        for row in run['records']:
            p=row['joint_plan'];self.assertEqual(days.index(row['date'])-days.index(p['decision']),2)
            self.assertEqual(p,run['joint_decisions'][days.index(p['decision'])])
            self.assertNotIn('cap_actions',row);self.assertNotIn('source_epochs',row)
            fills+=sum(x['binding'] for x in p['books'].values())
            changed+=sum(x['binding'] and bool(x['source_scope']) for x in p['books'].values())
        self.assertGreater(fills,0);self.assertGreater(changed,0)

    def test_gross_book_fees_cash_transfers_and_wealth(self):
        days,prices,_,run=self.run_fixture();old={b:{'cash':w,'units':{}} for b,w in run['initial_capital_shares'].items()}
        for row in run['records']:
            self.assertAlmostEqual(sum(b['capital_transfer'] for b in row['books'].values()),0.,places=12)
            for b,book in row['books'].items():
                previous=old[b];names=set(previous['units'])|set(book['units']);day=row['date']
                delta={k:book['units'].get(k,0.)-previous['units'].get(k,0.) for k in names}
                flow=sum(abs(q)*prices[k][day] for k,q in delta.items())
                self.assertAlmostEqual(book['fee'],flow*.004,places=12)
                self.assertAlmostEqual(book['cash'],previous['cash']+book['capital_transfer']-sum(q*prices[k][day] for k,q in delta.items())-book['fee'],places=12)
                if not row['capital_reset']:self.assertEqual(book['capital_transfer'],0.)
            old=row['books']
        self.assertLess(capital_contributions(run,days,prices,prices)['max_error'],1e-10)

    def test_warmup_and_delayed_actual_exposure_can_overshoot(self):
        _,_,_,run=self.run_fixture()
        self.assertTrue(run['records'][0]['capital_allocation']['initial'])
        self.assertFalse(run['records'][1]['capital_reset'])
        self.assertIsNone(run['records'][1]['capital_allocation'])
        self.assertGreater(max(x['book_risk_weights']['equity_crisis'] for x in run['records']),.2)
        for p in run['joint_decisions'].values():
            for book in p['books'].values():self.assertLessEqual(book['planned_risk_weight'],.2+1e-12)

    def test_binding_is_a_full_rebalance_and_can_buy_units_at_fill(self):
        days,prices,_,run=self.run_fixture();buys=0
        previous={}
        for row in run['records']:
            p=row['joint_plan']['books']['equity_crisis']
            if p['binding']:buys+=sum(row['books']['equity_crisis']['units'].get(k,0.)>previous.get(k,0.)+1e-12 for k in ('X','Y'))
            previous=row['books']['equity_crisis']['units']
        self.assertGreater(buys,0)
        self.assertTrue(any(p['books']['equity_crisis']['binding'] for p in run['joint_decisions'].values()))

    def test_future_source_and_prices_preserve_prefix(self):
        days,prices,aims,run=self.run_fixture();changed=copy.deepcopy(prices);future=copy.deepcopy(aims)
        for t in range(18,len(days)):changed['X'][days[t]]=10000.;future[t]={'Z':.2,'BIL':.8}
        b=self.run_fixture(changed=changed,aims=future)[-1]
        self.assertEqual(run['records'][:15],b['records'][:15])


class ProtocolTests(unittest.TestCase):
    def test_contract_inventory_and_identity_changes_rejected(self):
        c=r.read_contract(CONTRACT);self.assertEqual(c['planned_curves'],76)
        self.assertEqual(len(r.G20_CONTROLS+r.C60_CONTROLS),11)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'contract.json'
            for key in ('mechanisms','target_sources','selection_policy'):
                changed=copy.deepcopy(c);changed[key]={};p.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):r.read_contract(p)

    def test_all_nominal_sources_and_fixture_candidates_funded(self):
        from test_dual_engine_regimes import panel_fixture,assets_fixture
        c=r.read_contract(CONTRACT);panel=panel_fixture();rates={k:[0.]*len(panel.dates) for k in ('DFII10','T10YIE')}
        eq_close={k:dict(zip(panel.dates,v)) for k,v in panel.total_closes.items()};eq_open={k:dict(zip(panel.dates,v)) for k,v in panel.total_opens.items()};settings={**c['g20'],'start':panel.dates[160]}
        for rule in r.G20_CONTROLS:self.assertEqual(r.equity_targets(panel,settings,rule,rates),r.twelfth.equity_targets(panel,settings,rule,rates))
        for rule,source in r.G20_SOURCES.items():
            aims,members=r.equity_targets(panel,settings,rule,rates);self.assertEqual((aims,members),r.ninth.equity_targets(panel,settings,source,rates))
            run=r.candidate_replay('g20',rule,panel.dates,eq_close,eq_open,aims,settings=settings,delay=2,cost=40,panel=panel)
            self.assertLess(capital_contributions(run,panel.dates,eq_close,eq_open)['max_error'],1e-10)
        axis,assets=assets_fixture();settings={**c['c60'],'start':axis.dates[365]}
        closes,opens=r.base.crypto_prices(axis,assets,{a.symbol:dict(zip(axis.dates[a.start:a.start+len(a.closes)],a.closes)) for a in assets.values()})
        for rule in r.C60_CONTROLS:self.assertEqual(r.crypto_targets(axis,assets,settings,rule),r.twelfth.crypto_targets(axis,assets,settings,rule))
        for rule in r.C60_CANDIDATES:
            aims,members=r.crypto_targets(axis,assets,settings,rule);self.assertEqual((aims,members),r.tenth.crypto_targets(axis,assets,settings,'staged_risk4'))
            run=r.candidate_replay('c60',rule,axis.dates,closes,opens,aims,settings=settings,delay=1,cost=50,assets=assets)
            self.assertTrue(all(x['cash']>=-1e-10 for x in run['records']))
