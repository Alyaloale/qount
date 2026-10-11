import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from qount.research.dual_engine_acquisition import replay_acquisition,topup_scope,recovery_scope
from qount.research.dual_engine_family_clock import replay_family_clock
from qount.research.dual_engine_ownership import replay_ownership,ownership_plan
from qount.research.dual_engine_execution_ownership import read_contract
from test_dual_engine_zorder import fixture

class AcquisitionTests(unittest.TestCase):
 def run_fixture(self,band=0.,local=False,targets=None,closes=None,lag=2):
  days,prices,aims=fixture()
  return replay_acquisition(days,closes or prices,prices,targets or aims,start=days[2],lag=lag,cost_bps=50,core_assets=('X','Z'),band=band,local=local,risk_scale=lambda t,w:1.)
 def test_no_band_or_local_reproduces_frozen_clock(self):
  days,p,a=fixture();old=replay_family_clock(days,p,p,a,start=days[2],lag=2,cost_bps=50,clock_mode='sat_week',core_assets=('X','Z'),risk_scale=lambda t,w:1.)
  new=self.run_fixture()
  for x,y in zip(old['records'],new['records'],strict=True):
   for k in ('units','cash','nav','return','turnover','cost_fraction','vintages'):self.assertEqual(x[k],y[k])
 def test_local_core_only_and_sunday_preserved(self):
  names={'X','Y','Z'};cores={'X','Z'}
  self.assertEqual(recovery_scope('2021-01-04',{'X'},cores,names,True)[0],cores)
  self.assertEqual(recovery_scope('2021-01-03',{'X'},cores,names,True)[0],names)
  self.assertEqual(recovery_scope('2021-01-06',set(),cores,names,True)[0],set())
 def test_filter_suppresses_owned_small_buys_only(self):
  p={'decision_weights':{},'recovered_assets':[],'continuing_assets':[]}
  scope,skipped=topup_scope(None,{'X':.21,'Y':.1,'Z':.19,'A':0},{'X':.002,'Y':.001,'Z':.002,'A':.001},{'X':100,'Y':100,'Z':100,'A':100},1,p,.1)
  self.assertEqual(skipped,['X']);self.assertEqual(scope,{'Y','Z','A'})
 def test_recovery_continuation_and_warmup_protected(self):
  args=(None,{'X':.21},{'X':.002},{'X':100},1)
  for p in ({},{'decision_weights':{},'recovered_assets':['X'],'continuing_assets':[]},{'decision_weights':{},'recovered_assets':[],'continuing_assets':['X']}):self.assertEqual(topup_scope(*args,p,.25)[1],[])
 def test_suppressed_units_frozen_and_no_cash_substitution(self):
  days,p,a=fixture();a={t:{'X':.4,'Y':.2 if t<6 else .21} for t in a}
  run=self.run_fixture(.25,targets=a);old={};seen=0
  for row in run['records']:
   for k in row['suppressed_topups']:self.assertEqual(row['units'][k],row['acquisition_before_units'][k]);seen+=1
   self.assertGreaterEqual(row['cash'],-1e-12);old=row['units']
  self.assertGreater(seen,0)
 def test_zero_exit_and_latest_cancellation_unchanged(self):
  days,p,a=fixture();a={t:{'X':.4,**({'Y':.2} if 5<=t<6 else {})} for t in a}
  for local in (False,True):
   row=next(r for r in self.run_fixture(.25,local,targets=a)['records'] if r['date']==days[7]);self.assertNotIn('Y',row['units']);self.assertIn('Y',row['cancelled_stale'])
 def test_future_perturbation_preserves_prefix(self):
  d,p,a=fixture();future=copy.deepcopy(a);q=copy.deepcopy(p)
  for t in range(18,len(d)):future[t]={'Z':.8};q['X'][d[t]]=300
  for local in (False,True):self.assertEqual(self.run_fixture(.1,local)['records'][:16],self.run_fixture(.1,local,targets=future,closes=q)['records'][:16])

class OwnershipTests(unittest.TestCase):
 def run_fixture(self,lag=2,targets=None,closes=None):
  d,p,_=fixture();p['X']={day:100*1.08**i for i,day in enumerate(d)}
  a={1:{'X':.2,'GLD':.2,'BIL':.6},8:{'Y':.2,'GLD':.2,'BIL':.6},12:{'Y':.2,'GLD':.2,'BIL':.6},24:{'Y':.2,'GLD':.2,'BIL':.6}}
  return d,p,replay_ownership(d,closes or p,p,targets or a,start=d[3],lag=lag,cost_bps=40,full_refresh={1,12,24},limit=.2)
 def test_pending_exit_excluded_from_binding_shape(self):
  b={'equity_crisis':{'cash':0,'units':{'X':.9,'Y':.05,'BIL':.05}},'gold':{'cash':20,'units':{}},'reserve':{'cash':60,'units':{}}}
  p=ownership_plan('2021-01-04',b,{'X':100,'Y':100,'BIL':100},{'equity_crisis':{'Y':1},'gold':{},'reserve':{}},{'equity_crisis':(),'gold':(),'reserve':()},.2)['books']['equity_crisis']
  self.assertNotIn('X',p['feasible_shape']);self.assertIn('X',p['source_zero_held_assets'])
 def test_sparse_sources_carried_and_zero_buys_absent(self):
  d,p,run=self.run_fixture();self.assertEqual(run['joint_decisions'][9]['books']['equity_crisis']['source_target']['Y'],1)
  old={b:{} for b in run['initial_capital_shares']}
  for row in run['records']:
   t=d.index(row['date'])
   for b,book in row['books'].items():
    for k,q in book['units'].items():
     if k!='BIL' and q>old[b].get(k,0)+1e-12:self.assertGreater(row['joint_plan']['books'][b]['source_target'].get(k,0),0);self.assertGreater(row['latest_source'][b].get(k,0),0)
    old[b]=book['units']
 def test_veto_does_not_read_future_reentry(self):
  d,p,_=self.run_fixture();a={1:{'X':.2,'GLD':.2,'BIL':.6},4:{'X':.2,'GLD':.2,'BIL':.6},5:{'GLD':.2,'BIL':.8},8:{'X':.2,'GLD':.2,'BIL':.6}}
  _,_,run=self.run_fixture(targets=a)
  row=next(r for r in run['records'] if r['date']==d[6]);self.assertIn('X',row['source_zero_vetoes']['equity_crisis']);self.assertNotIn('X',row['units'])
 def test_gross_book_cash_and_zero_sum_transfers(self):
  d,p,run=self.run_fixture();old={b:{'cash':w,'units':{}} for b,w in run['initial_capital_shares'].items()}
  for row in run['records']:
   self.assertAlmostEqual(sum(b['capital_transfer'] for b in row['books'].values()),0,places=12)
   for b,book in row['books'].items():
    x=old[b];delta={k:book['units'].get(k,0)-x['units'].get(k,0) for k in set(book['units'])|set(x['units'])};fee=sum(abs(q)*p[k][row['date']] for k,q in delta.items())*.004
    self.assertAlmostEqual(book['fee'],fee,places=12);self.assertAlmostEqual(book['cash'],x['cash']+book['capital_transfer']-sum(q*p[k][row['date']] for k,q in delta.items())-fee,places=12)
   old=row['books']
 def test_second_warm_instruction_does_not_reset(self):
  d,p,run=self.run_fixture();self.assertTrue(run['records'][0]['capital_reset']);self.assertFalse(run['records'][1]['capital_reset'])
 def test_future_source_and_price_prefix(self):
  d,p,run=self.run_fixture();a={1:{'X':.2,'GLD':.2,'BIL':.6},8:{'Y':.2,'GLD':.2,'BIL':.6},12:{'Y':.2,'GLD':.2,'BIL':.6},24:{'X':.2,'BIL':.8}}
  self.assertEqual(run['records'][:18],self.run_fixture(targets=a)[2]['records'][:18])
 def test_contract_rejects_changed_band_or_policy(self):
  path=Path(__file__).resolve().parents[1]/'config/dual-engine-execution-ownership-20261005.json';c=read_contract(path)
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'c.json';c['c60_rules']['topup10'][0]=.11;p.write_text(json.dumps(c))
   with self.assertRaises(ValueError):read_contract(p)
