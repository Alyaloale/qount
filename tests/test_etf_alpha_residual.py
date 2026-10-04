"""Causal R3 protocol/readiness tests; no optimizer steps or model fitting."""
from __future__ import annotations

from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from qount.research.etf_alpha.artifacts import read_json, write_json
from qount.research.etf_alpha.cloud_bundle import verify_archive
from qount.research.etf_alpha.execution import simulate
from qount.research.etf_alpha.residual_data import BASELINES, FEATURES, NEURALS, RIDGES, build_slots, epoch_schedule, fit_transform, null_permutation, prepare_slot, shuffled_labels, target_context
from qount.research.etf_alpha.residual_run import FitBudget, execute_schedule, run_engine
from qount.research.etf_alpha.residual_runtime import authorize, launch, pack_delivery, validate_contract
from qount.research.etf_alpha.residual_selection import execute_path, prediction_stats, select_from_past, signal_gate, total_forecast, utility_sensitivity
from qount.research.etf_alpha.training_data import TARGETS, TrainingData
from test_etf_alpha_m1 import fixture, prepared

ROOT = Path(__file__).resolve().parents[1]


def data_fixture():
    panel = fixture(3550,first="2013-01-02")
    size = len(panel.dates)
    names = FEATURES+tuple(f"other_{i}" for i in range(30))
    assets = np.random.default_rng(19).normal(0,.05,(size,9,38))
    raw = assets.copy()
    raw[120:,:,3] = panel.close[120:]/panel.close[:-120]-1
    starts = np.arange(size)+1;starts[starts>=size]=-1
    ends,targets,masks = {},{},{}
    for horizon in (5,20,60):
        end = np.arange(size)+horizon+1;end[end>=size]=-1;ends[horizon]=end
        y = np.full((size,9),np.nan)
        valid = end>=0
        y[valid] = panel.open[end[valid]]/panel.open[starts[valid]]-1
        targets[f"mu{horizon}"],masks[f"mu{horizon}"] = y,np.isfinite(y)
    targets.update(sigma20=np.where(masks["mu20"],.1,np.nan),p_up=(targets["mu20"]>0).astype(float),q10=targets["mu20"].copy())
    masks.update({key:masks["mu20"].copy() for key in ("sigma20","p_up","q10")})
    data = TrainingData(panel.dates,panel.symbols,names,assets,np.ones_like(assets,bool),np.zeros((size,17)),
        np.ones((size,17),bool),targets,masks,starts,ends)
    data.validate()
    return data,panel,raw


class CausalDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data,cls.panel,cls.raw = data_fixture()
        cls.context = target_context(cls.data,cls.panel)
        cls.slots = build_slots(cls.data,cls.context[0])

    def test_sixteen_slots_purge_checkpoint_and_inner_label_tail(self):
        self.assertEqual(len(self.slots),16)
        for slot in self.slots:
            self.assertTrue(np.all(np.diff(slot.evaluation_rows)==1))
            self.assertTrue(np.all(np.char.startswith(np.array(self.data.dates)[slot.evaluation_rows],str(slot.year))))
            boundary = f"{slot.year-1 if slot.kind=='inner' else slot.year}-01-01"
            edge = np.searchsorted(self.data.dates,boundary)
            self.assertTrue(np.all(self.data.end_rows[20][slot.train_rows]<edge-5))
            if slot.kind=="inner":
                start = np.searchsorted(self.data.dates,f"{slot.year}-01-01")
                next_year = np.searchsorted(self.data.dates,f"{slot.year+1}-01-01")
                self.assertTrue(np.all(self.data.end_rows[20][slot.checkpoint_rows]<start-5))
                self.assertTrue(np.all(self.data.end_rows[20][slot.evaluation_label_rows]<next_year-5))
                self.assertLess(len(slot.evaluation_label_rows),len(slot.evaluation_rows))
            else:
                self.assertEqual(len(slot.checkpoint_rows),0)
                self.assertEqual(len(slot.evaluation_label_rows),0)

    def test_centering_and_reconstruction_spy_exactly_causal_market(self):
        slot = self.slots[0]
        beta,cash,forecast = self.context
        transform = fit_transform(self.data,slot.train_rows,cash,beta)
        residual = transform.residual(self.data,slot.train_rows,cash,beta)
        np.testing.assert_allclose(residual.mean(0),0,atol=1e-14)
        np.testing.assert_array_equal(residual[:,transform.spy],0)
        rows=slot.evaluation_rows
        mu=transform.reconstruct(forecast[rows],self.raw[rows,0,3]/6,beta[rows],np.ones((len(rows),9)))
        np.testing.assert_array_equal(mu[:,transform.spy],self.raw[rows,0,3]/6)

    def test_future_labels_do_not_change_training_transform_or_forecasts(self):
        slot=self.slots[0]
        before,transform=prepare_slot(self.data,self.panel,self.raw,slot,self.context)
        changed={k:v.copy() for k,v in self.data.targets.items()}
        changed["mu20"][slot.evaluation_rows]+=2
        other=replace(self.data,targets=changed)
        after,second=prepare_slot(other,self.panel,self.raw,slot,self.context)
        self.assertEqual(transform.contract(),second.contract())
        for key in ("train_y","train_x","evaluation_base","evaluation_momentum120"):
            np.testing.assert_array_equal(before[key],after[key])
        self.assertFalse(np.array_equal(before["evaluation_y"],after["evaluation_y"]))

    def test_outer_preparation_excludes_labels_and_preserves_all_dates(self):
        slot=self.slots[-1]
        values,_=prepare_slot(self.data,self.panel,self.raw,slot,self.context)
        self.assertNotIn("evaluation_y",values)
        self.assertEqual(len(values["evaluation_rows"]),len(slot.evaluation_rows))
        forecast=total_forecast(values,np.zeros((len(slot.evaluation_rows),8)))
        np.testing.assert_array_equal(forecast,values["evaluation_base"])

    def test_beta_and_cash_forecast_are_causal(self):
        row=1200
        future_close=self.panel.close.copy();future_close[row+1:]*=3
        future_cash=self.panel.cash_close.copy();future_cash[row+1:]*=2
        changed=replace(self.panel,close=future_close,cash_close=future_cash)
        beta,_,cash=target_context(self.data,changed)
        np.testing.assert_array_equal(beta[:row+1],self.context[0][:row+1])
        np.testing.assert_array_equal(cash[:row+1],self.context[2][:row+1])


class NullAndPredictionTests(unittest.TestCase):
    def test_zero_same_date_pairs_ragged_blocks_and_determinism(self):
        for length in (120,121,253,941,2601):
            for seed in range(1000,1005):
                p=null_permutation(length,seed)
                np.testing.assert_array_equal(np.sort(p),np.arange(length))
                self.assertTrue(np.all(p!=np.arange(length)))
                np.testing.assert_array_equal(p,null_permutation(length,seed))
                for start in range(0,length,60):
                    block=np.arange(start,min(length,start+60))
                    location=int(np.flatnonzero(p==start)[0])
                    np.testing.assert_array_equal(p[location:location+len(block)],block)

    def test_both_nulls_move_masks_with_targets_and_keep_all_values(self):
        y=np.arange(941*8).reshape(941,8);mask=(y%7)!=0
        for strong in (False,True):
            shuffled,valid,receipt=shuffled_labels(y,mask,1000,asset_shuffle=strong)
            np.testing.assert_array_equal(valid,shuffled%7!=0)
            np.testing.assert_array_equal(np.sort(shuffled.ravel()),y.ravel())
            self.assertEqual(receipt["unchanged_date_pairs"],0)
            self.assertTrue(np.all(shuffled//8!=np.arange(len(y))[:,None]))

    def test_reviewed_nulls_exclude_overlapping_labels_at_all_actual_slot_lengths(self):
        lengths=(226,478,729,980,1232,1485,1737,1988,2238,2490,2740)
        for length in lengths:
            for seed in range(1000,1005):
                with self.subTest(length=length,seed=seed):
                    p=null_permutation(length,seed,minimum_shift=25)
                    np.testing.assert_array_equal(np.sort(p),np.arange(length))
                    self.assertGreaterEqual(int(np.abs(p-np.arange(length)).min()),25)
                    for start in range(0,length,60):
                        block=np.arange(start,min(length,start+60))
                        location=int(np.flatnonzero(p==start)[0])
                        np.testing.assert_array_equal(p[location:location+len(block)],block)

    def test_reviewed_null_receipts_and_masks_bind_the_separation(self):
        y=np.arange(478*8).reshape(478,8);mask=(y%7)!=0
        for strong in (False,True):
            target,valid,receipt=shuffled_labels(y,mask,1003,asset_shuffle=strong,minimum_shift=25)
            self.assertGreaterEqual(receipt["minimum_date_shift"],25)
            self.assertEqual(receipt["minimum_shift_required"],25)
            self.assertEqual(receipt["unchanged_date_pairs"],0)
            np.testing.assert_array_equal(valid,target%7!=0)
            np.testing.assert_array_equal(np.sort(target.ravel()),y.ravel())
            self.assertTrue(np.all(np.abs(target//8-np.arange(len(y))[:,None])>=25))

    def test_rank_and_huber_exclude_spy_and_unavailable_tail(self):
        y=np.tile(np.arange(8),(240,1)).astype(float)
        mask=np.ones_like(y,bool);mask[-26:]=False
        values={"evaluation_y":y,"evaluation_mask":mask}
        stats=prediction_stats(values,y)
        np.testing.assert_allclose(stats["rank"][:-26],1)
        np.testing.assert_array_equal(stats["huber"][:-26],0)
        self.assertTrue(np.isnan(stats["rank"][-26:]).all())
        self.assertTrue(np.isnan(stats["huber"][-26:]).all())


def fake_receipts(year):
    return {family:{str(seed):{"status":"complete","best_epoch":(year-2017)%5+seed-1000}
                    for seed in range(1000,1005)} for family in NEURALS}


class ScheduleTests(unittest.TestCase):
    def test_failed_pilot_stops_at_fifty_one_without_outer_or_freeze(self):
        budget=FitBudget();seen=[]
        def fit(name,epochs):
            seen.append(name)
            for _ in range(17):budget.claim();budget.finish({"status":"complete"})
            return fake_receipts(int(name[-4:]))
        def forbidden(*_):self.fail("pilot must withhold subsequent work")
        result=execute_schedule(range(1000,1005),fit,lambda y:{"selected":BASELINES[0]},forbidden,forbidden)
        self.assertEqual(result["status"],"pilot_no_increment")
        self.assertEqual((budget.started,budget.completed),(51,51))
        self.assertEqual(seen,["inner_2017","inner_2018","inner_2019"])

    def test_passing_schedule_freezes_at_153_before_119_final_fits(self):
        budget=FitBudget();frozen=[];slots=[]
        def fit(name,epochs):
            slots.append(name)
            if name.startswith("final"):
                self.assertTrue(frozen);self.assertIsNotNone(epochs)
            else:self.assertIsNone(epochs)
            for _ in range(17):budget.claim();budget.finish({"status":"complete"})
            return fake_receipts(int(name[-4:]))
        def freeze(choices,epochs):
            self.assertEqual(budget.completed,153)
            self.assertEqual(len(choices),7);self.assertEqual(len(epochs),7);frozen.append(True)
        def outer(choices):self.assertEqual(budget.completed,272);return {"checked":True}
        result=execute_schedule(range(1000,1005),fit,lambda y:{"selected":NEURALS[0]},freeze,outer)
        self.assertEqual(result["status"],"complete")
        self.assertEqual((budget.started,budget.completed,len(set(slots))),(272,272,16))
        with self.assertRaises(RuntimeError):budget.claim()

    def test_epoch_schedule_ignores_future_and_rejects_incomplete_past(self):
        receipts={f"inner_{y}":fake_receipts(y) for y in range(2017,2026)}
        expected=epoch_schedule(2020,receipts,range(1000,1005))
        receipts["inner_2025"]=None
        self.assertEqual(expected,epoch_schedule(2020,receipts,range(1000,1005)))
        self.assertEqual(expected[NEURALS[0]]["1000"],2)
        receipts["inner_2018"][NEURALS[0]]["1000"]["status"]="partial"
        with self.assertRaises(ValueError):epoch_schedule(2020,receipts,range(1000,1005))

    def test_partial_fit_cannot_consume_a_complete_budget_slot(self):
        budget=FitBudget();budget.claim()
        with self.assertRaises(InterruptedError):budget.finish({"status":"partial"})
        self.assertEqual((budget.started,budget.completed),(1,0))


class SelectorTests(unittest.TestCase):
    def test_selector_reads_only_three_past_years_and_trades_mean_forecast(self):
        data,panel,raw=data_fixture();context=target_context(data,panel)
        slots,predictions={},{}
        for slot in build_slots(data,context[0])[:3]:
            values,_=prepare_slot(data,panel,raw,slot,context)
            slots[slot.name]=values
            predictions[slot.name]={family:{str(s):np.full((len(slot.evaluation_rows),8),s-999.)
                for s in (range(1000,1005) if family in NEURALS else [1000])} for family in (*RIDGES,*NEURALS)}
        slots["inner_2025"]=None;predictions["inner_2025"]=None
        seen=[]
        def execute(_panel,sequence,_inputs,**options):
            self.assertEqual([int(panel.dates[int(rows[0])][:4]) for rows,_ in sequence],[2017,2018,2019])
            seen.append(sequence)
            rows=np.concatenate([r for r,_ in sequence]);size=len(rows)
            curve={"rows":rows,"returns":np.r_[0,np.full(size-1,.0001)]}
            return {"hard_constraints":True,"utility":0.,"max_rolling_voluntary":0.},curve
        with patch("qount.research.etf_alpha.residual_selection.execute_path",side_effect=execute),patch(
            "qount.research.etf_alpha.residual_selection.signal_gate",return_value={"qualified":False}):
            selection,_=select_from_past(2020,slots,predictions,panel,prepared(panel),anchor=520,stability_samples=10)
        self.assertEqual(selection["selected"],BASELINES[0]);self.assertEqual(selection["inner_eval_years"],[2017,2018,2019])
        self.assertEqual(len(seen),9)
        for (rows,mu),year in zip(seen[2],range(2017,2020)):
            values=slots[f"inner_{year}"]
            expected=total_forecast(values,np.full((len(rows),8),3.))
            np.testing.assert_array_equal(mu,expected)

    def statistics(self):
        def annual(rank,loss):return [{"rank":np.full(252,rank),"huber":np.full(252,loss)} for _ in range(3)]
        values={f:annual(.01,1) for f in (*RIDGES,*NEURALS,BASELINES[0])}
        values[RIDGES[0]]=annual(.12,.8);values[NEURALS[0]]=annual(.15,.8)
        seeds={f:{str(s):values[f] for s in range(1000,1005)} for f in NEURALS}
        return values,seeds

    def test_paired_controls_and_three_year_signals_required(self):
        values,seeds=self.statistics()
        self.assertTrue(signal_gate(NEURALS[0],values,seeds,samples=30)["qualified"])
        values[NEURALS[0]][0]["rank"]=np.full(252,-.01)
        values[NEURALS[0]][1]["rank"]=np.full(252,-.01)
        self.assertFalse(signal_gate(NEURALS[0],values,seeds,samples=30)["qualified"])

    def test_ridge_uses_annual_evidence_and_mlp_requires_three_seeds(self):
        values,seeds=self.statistics()
        ridge=signal_gate(RIDGES[0],values,{},samples=30)
        self.assertTrue(ridge["qualified"]);self.assertIsNone(ridge["paired_positive_seed_count"])
        for seed in (1000,1001,1002):seeds[NEURALS[0]][str(seed)]=values[NEURALS[1]]
        result=signal_gate(NEURALS[0],values,seeds,samples=30)
        self.assertEqual(result["paired_positive_seed_count"],2);self.assertFalse(result["qualified"])

    def test_ridge_cannot_pass_on_one_paired_winning_year(self):
        values,_=self.statistics()
        for i,rank in enumerate((-.3,.13,.13)):
            values[RIDGES[1]][i]["rank"]=np.full(252,rank)
        with patch("qount.research.etf_alpha.residual_selection.block_interval",return_value={"status":"diagnostic","lower":.1,"upper":.2}):
            result=signal_gate(RIDGES[0],values,{},samples=30)
        self.assertEqual(result["positive_inner_years"],3)
        self.assertEqual(result["paired_positive_inner_years"][RIDGES[1]],1)
        self.assertFalse(result["qualified"])

    def test_ensemble_ledger_carries_state_across_year_boundary(self):
        panel=fixture(530,first="2018-01-02")
        rows=np.arange(100,500)
        mu=np.tile(np.arange(9)*.01,(len(rows),1))
        metrics,curve=execute_path(panel,[(rows,mu)],prepared(panel),anchor=100)
        two,joined=execute_path(panel,[(rows[:150],mu[:150]),(rows[150:],mu[150:])],prepared(panel),anchor=100)
        for key in curve:np.testing.assert_allclose(curve[key],joined[key],atol=1e-10)
        self.assertEqual(metrics,two)

    def test_boundary_rebalance_uses_prior_close_forecast_and_matches_one_account(self):
        panel=fixture(530,first="2018-01-02")
        rows=np.arange(100,500)
        mu=np.zeros((len(rows),9));mu[:,0]=.1;mu[148:,0]=0;mu[148:,5]=.1
        metrics,curve=execute_path(panel,[(rows,mu)],prepared(panel),anchor=100)
        with patch("qount.research.etf_alpha.residual_selection.simulate",wraps=simulate) as simulated:
            two,joined=execute_path(panel,[(rows[:148],mu[:148]),(rows[148:],mu[148:])],prepared(panel),anchor=100)
            _,policy=simulated.call_args.args
            prior=policy(type("Observation",(),{"t":247})())
            self.assertIsNotNone(prior.target)
            self.assertGreater(prior.target[0],0)
            self.assertEqual(prior.target[5],0)
        for key in curve:np.testing.assert_array_equal(curve[key],joined[key])
        self.assertEqual(metrics,two)

    def test_partition_gaps_and_duplicate_decision_dates_are_rejected(self):
        panel=fixture(530,first="2018-01-02");inputs=prepared(panel)
        for rows in (np.r_[100:200,201:300],np.r_[100:200,199:300]):
            with self.assertRaises(ValueError):
                execute_path(panel,[(rows,np.zeros((len(rows),9)))],inputs,anchor=100)

    def test_stability_uses_shared_dates_and_fixed_risk(self):
        size=500;rows=np.arange(size+1)
        curves={BASELINES[0]:{"rows":rows,"returns":np.r_[0,np.full(size,.0001)]},RIDGES[0]:{"rows":rows,"returns":np.r_[0,.0005+np.sin(np.arange(size))*.001]}}
        metrics={n:{"max_rolling_voluntary":0.} for n in curves}
        result=utility_sensitivity(curves,np.zeros(size+1),metrics,list(curves),RIDGES[0],samples=20)
        self.assertTrue(all(v["winner_retained"]==1 for v in result.values()))
        curves[RIDGES[0]]["rows"]=rows+1
        with self.assertRaises(ValueError):utility_sensitivity(curves,np.zeros(size+2),metrics,list(curves),RIDGES[0],samples=2)


class ReadinessAndActivationTests(unittest.TestCase):
    def test_contract_matches_frozen_proposal_and_rejects_policy_drift(self):
        contract=read_json(ROOT/"config/etf-alpha-residual-ready-20261003.json")
        validate_contract(contract,ROOT)
        for section,key,value in (("training","seeds",[1000]),("budget","full_max_fits",273),("engine","compile",True)):
            other=json.loads(json.dumps(contract));other[section][key]=value
            with self.assertRaises(ValueError):validate_contract(other,ROOT)

    def test_reviewed_contract_preserves_research_fields_and_requires_separation(self):
        contract=read_json(ROOT/"config/etf-alpha-residual-reviewed-20261003.json")
        validate_contract(contract,ROOT)
        historical=read_json(ROOT/"config/etf-alpha-residual-ready-20261003.json")
        for key in ("data","target","models","controls","training","walk_forward","selection","budget","execution","fresh_confirmation"):
            self.assertEqual(contract[key],historical[key])
        for key,value in (("null_minimum_shift_sessions",1),("portfolio_boundary_policy","reset_annually")):
            other=json.loads(json.dumps(contract));other["engine"][key]=value
            with self.assertRaises(ValueError):validate_contract(other,ROOT)
        other=json.loads(json.dumps(contract));other["review"]["source_runtime_contract_sha256"]="changed"
        with self.assertRaises(ValueError):validate_contract(other,ROOT)

    def test_missing_activation_blocks_before_storage_cuda_or_fitting(self):
        with patch("qount.research.etf_alpha.residual_runtime.check_ready",side_effect=AssertionError("must not probe")):
            with self.assertRaises(PermissionError):launch("missing",None,"missing","missing")
        with patch("qount.research.etf_alpha.residual_run.check_ready",side_effect=AssertionError("must not probe")):
            with self.assertRaises(PermissionError):run_engine("missing",None,"missing","missing")

    def test_future_owner_activation_bound_to_prepared_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();out=root/"artifacts/etf_alpha_p3/new_run"
            info={"ready_directory":str(root/"ready"),"prepared_manifest_sha256":"prepared", "runtime_contract_sha256":"contract",
                "deployment_manifest_sha256":"code","created_at":"2026-10-03T13:00:00+00:00"}
            receipt={k:info[k] for k in info if k!="created_at"}
            receipt.update(training_start_authorized=True,owner_instruction="训练",decision_reference="docs/current.md",
                output_directory=str(out),issued_at="2026-10-03T13:01:00+00:00",activation_nonce="synthetic-test-only")
            path=root/"synthetic-owner.json"
            def save(value):path.write_text(json.dumps(value,ensure_ascii=False))
            with patch("qount.research.etf_alpha.residual_runtime.EXTERNAL_ROOT",root):
                save(receipt);self.assertTrue(authorize(path,info,out)["verified_explicit_start"])
                for key,value in (("owner_instruction","参照方案部署训练引擎，等我说训练再开始"),("prepared_manifest_sha256","stale"),("issued_at",info["created_at"]),("training_start_authorized",False)):
                    bad=receipt|{key:value};save(bad)
                    with self.assertRaises(PermissionError):authorize(path,info,out)
            self.assertFalse(out.exists())

    def test_cli_missing_authorization_exits_without_creating_run(self):
        script=ROOT/"scripts/research/etf_alpha_residual.py"
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/"never_started"
            for command in ("run","launch"):
                result=subprocess.run([sys.executable,str(script),command,"--ready","missing","--out",str(out)],capture_output=True,text=True)
                self.assertEqual(result.returncode,2,result.stderr)
                self.assertIn("ready_waiting_owner",result.stderr)
                self.assertFalse(out.exists())

    def test_public_delivery_is_deterministic_and_has_no_private_state(self):
        with tempfile.TemporaryDirectory() as directory:
            receipts=[]
            for name in ("a.tar.gz","b.tar.gz"):
                out=Path(directory)/name
                receipt=pack_delivery(ROOT,ROOT/"config/etf-alpha-residual-reviewed-20261003.json",out)
                receipts.append(receipt)
                manifest=verify_archive(out)
                self.assertFalse(manifest["training_start_authorized"])
                self.assertTrue(all(".env" not in name and not name.startswith(("state/","data/","models/")) for name in manifest["files"]))
            self.assertEqual(receipts[0]["sha256"],receipts[1]["sha256"])


@unittest.skipUnless(importlib.util.find_spec("torch"),"isolated Torch environment required")
class NeuralReadinessTests(unittest.TestCase):
    def test_161_parameters_and_no_asset_identity_channel(self):
        import torch
        from qount.research.etf_alpha.residual_models import ResidualPredictor
        model=ResidualPredictor().eval();x=torch.randn(5,8,8);permutation=torch.tensor([3,1,7,0,4,2,6,5])
        self.assertEqual(sum(p.numel() for p in model.parameters()),161)
        torch.testing.assert_close(model(x[:,permutation]),model(x)[:,permutation])

    def test_numerical_probe_never_updates_weights(self):
        from qount.research.etf_alpha.residual_training import numerical_probe
        result=numerical_probe("cpu")
        self.assertTrue(result["weights_unchanged"]);self.assertEqual(result["optimizer_steps"],0)

    def test_fit_guard_precedes_optimizer_and_directory_creation(self):
        from qount.research.etf_alpha.residual_training import fit
        with tempfile.TemporaryDirectory() as directory,patch("torch.optim.AdamW",side_effect=AssertionError("optimizer forbidden")):
            out=Path(directory)/"no_fit"
            with self.assertRaises(PermissionError):fit(None,None,None,None,None,None,None,seed=1000,out=out,options={},expired=lambda:False,emit=lambda *_:None)
            self.assertFalse(out.exists())


if __name__=="__main__":unittest.main()
