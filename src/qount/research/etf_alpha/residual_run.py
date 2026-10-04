"""Explicitly activated R3 pilot, causal inner selection and fixed final fits."""
from __future__ import annotations

import json
from pathlib import Path
import signal
import threading
import time

import numpy as np

from qount.research.etf_trader.costs import cost_params_for
from qount.research.etf_trader.universe import US_ACCOUNT

from .artifacts import GUARDS, finish_manifest, read_json, sha256, utc_now, write_json
from .diagnostics import block_interval, ic_series, mean_finite
from .execution import execution_inputs
from .expanded_data import load_panel
from .residual_data import BASELINES, FAMILIES, NEURALS, RIDGES, ResidualTransform, epoch_schedule, shuffled_labels, target_context
from .residual_runtime import authorize, check_ready, cuda_check, cuda_lock
from .residual_selection import execute_path, prediction_stats, select_from_past, total_forecast


def execute_schedule(seeds,fit_slot,select_year,freeze,evaluate_outer):
    """The pilot can stop all subsequent fits; no outer callback precedes freeze."""
    receipts = {}
    for year in (2017,2018,2019):
        receipts[f"inner_{year}"] = fit_slot(f"inner_{year}",None)
    pilot = select_year(2020)
    if pilot["selected"]==BASELINES[0]:
        return {"status":"pilot_no_increment","outer_test_status":"withheld","pilot":pilot,
                "selections":{"WF2020":pilot},"inner_fits":receipts}
    for year in range(2020,2026):
        receipts[f"inner_{year}"] = fit_slot(f"inner_{year}",None)
    selections = {"WF2020":pilot}|{f"WF{y}":select_year(y) for y in range(2021,2027)}
    epochs = {f"WF{y}":epoch_schedule(y,receipts,seeds) for y in range(2020,2027)}
    freeze(selections,epochs)
    for year in range(2020,2027):
        fit_slot(f"final_{year}",epochs[f"WF{year}"])
    outer = evaluate_outer(selections)
    return {"status":"complete","outer_test_status":"complete","pilot":pilot,"selections":selections,
            "final_epoch_schedule":epochs,"inner_fits":receipts,"outer_test":outer}


class FitBudget:
    def __init__(self,maximum=272):
        self.maximum,self.started,self.completed = maximum,0,0

    def claim(self):
        if self.started>=self.maximum:
            raise RuntimeError("registered residual fit budget exhausted")
        self.started += 1

    def finish(self,receipt):
        if receipt["status"]!="complete":
            raise InterruptedError("residual fit incomplete; no automatic retry or continuation")
        self.completed += 1


class RunLog:
    def __init__(self,out):
        self.out,self.stream = out,(out/"events.jsonl").open("x")
        self.state = GUARDS|{"status":"starting","fits_started":0,"fits_completed":0,"outer_test_status":"withheld"}

    def emit(self,event,**values):
        record = {"time":utc_now(),"event":event}|values
        line = json.dumps(record,ensure_ascii=False,allow_nan=False)
        self.stream.write(line+"\n");self.stream.flush()
        print(line,flush=True)

    def update(self,**values):
        self.state.update(values)
        self.state["updated_at"] = utc_now()
        temporary = self.out/"status.json.tmp"
        temporary.write_text(json.dumps(self.state,indent=2,allow_nan=False)+"\n")
        temporary.replace(self.out/"status.json")


def load_slot(ready,name):
    with np.load(Path(ready)/f"{name}.npz",allow_pickle=False) as values:
        return {k:values[k].copy() for k in values.files}


def outer_summary(metrics,curve,panel,cash_returns):
    result = metrics.copy()
    rows,r = curve["rows"][1:],curve["returns"][1:]
    dates = np.asarray(panel.dates)[rows]
    annual = {str(year):{"return":float(np.prod(1+r[np.char.startswith(dates,str(year))])-1),
                        "partial":year==2026,"days":int(np.char.startswith(dates,str(year)).sum())}
              for year in range(2020,2027)}
    best = max((y for y,v in annual.items() if not v["partial"]),key=lambda y:annual[y]["return"])
    dropped = r[~np.char.startswith(dates,best)]
    result.update(annual=annual,drop_best_complete_year={"year":best,"cagr":float(np.prod(1+dropped)**(252/len(dropped))-1)},
                  excess_daily_mean_intervals={str(b):block_interval(r-cash_returns[rows],block=b) for b in (40,60,120)})
    return result


def run_engine(ready,authorization,out,repository):
    # This guard precedes Torch import, run directory creation and any fitting.
    if authorization is None:
        raise PermissionError("engine is ready but waiting for the owner training instruction")
    ready,out,repository = map(Path,(ready,out,repository))
    info = check_ready(ready,repository,gpu=False)
    permit = authorize(authorization,info,out)
    config = read_json(ready/"runtime-contract.json")
    with cuda_lock(config["engine"]["cuda_lock"]):
        environment = cuda_check()
        out.mkdir(parents=True,exist_ok=False)
        return _run_locked(ready,out,config,permit,environment)


def _run_locked(ready,out,config,permit,environment):
    import torch
    from .compute import monitor_compute
    from .residual_training import fit
    from .ridge import fit_ridge
    budget = FitBudget(config["budget"]["full_max_fits"])
    log = RunLog(out)
    stopped,monitor_stop = threading.Event(),threading.Event()
    previous = {s:signal.signal(s,lambda *_:stopped.set()) for s in (signal.SIGINT,signal.SIGTERM)}
    compute = {"storage_root":str(Path(config["data"]["root"]).parents[2]),"price_per_hour_cny":0.}
    monitor = threading.Thread(target=monitor_compute,args=(log,monitor_stop,compute),daemon=True)
    monitor.start()
    started = time.monotonic()
    summary = GUARDS|{"status":"starting","outer_test_status":"withheld","started_at":utc_now()}
    try:
        write_json(out/"run-contract.json",config)
        write_json(out/"owner-activation.json",permit)
        write_json(out/"environment.json",environment)
        write_json(out/"prepared-reference.json",info_binding(ready))
        panel = load_panel(Path(config["data"]["root"]))
        inputs = execution_inputs(panel,cost_params_for(US_ACCOUNT))
        anchor = read_json(ready/"derived-fold-contract.json")["anchor_row"]
        arrays,predictions = {},{}

        def alive():
            if stopped.is_set():
                raise InterruptedError("owner or signal stopped this run")

        def train_slot(name,fixed):
            alive()
            values = load_slot(ready,name)
            arrays[name],predictions[name] = values,{}
            slot_out = out/name
            slot_out.mkdir()
            receipts = {}
            train_x = torch.as_tensor(values["train_x"],device="cuda")
            checkpoint_x = torch.as_tensor(values["checkpoint_x"],device="cuda")
            checkpoint_y = torch.as_tensor(values["checkpoint_y"],device="cuda")
            checkpoint_mask = torch.as_tensor(values["checkpoint_mask"],device="cuda")
            evaluation_x = torch.as_tensor(values["evaluation_x"],device="cuda")
            for family in (*RIDGES,*NEURALS):
                receipts[family],predictions[name][family] = {},{}
                for seed in config["training"]["seeds"] if family in NEURALS else [1000]:
                    alive();budget.claim()
                    log.update(status="pilot_fitting" if name in {"inner_2017","inner_2018","inner_2019"} else "fitting",
                               current_slot=name,current_model=family,current_seed=seed,fits_started=budget.started,
                               fits_completed=budget.completed)
                    log.emit("fit_started",slot=name,model=family,seed=seed)
                    job = slot_out/family/f"seed_{seed}"
                    y,mask = values["train_y"],values["train_mask"]
                    null = None
                    if "shuffle" in family:
                        y,mask,null = shuffled_labels(y,mask,seed,asset_shuffle="asset" in family,
                            minimum_shift=config["engine"].get("null_minimum_shift_sessions",1))
                    if family in RIDGES:
                        job.mkdir(parents=True)
                        model = fit_ridge(values["train_x"],y,mask,.01)
                        prediction = model.predict(values["evaluation_x"])
                        np.savez_compressed(job/"model.npz",coefficients=model.coefficients,intercept=model.intercept)
                        np.savez_compressed(job/"evaluation-prediction.npz",standardized_residual=prediction)
                        receipt = {"status":"complete","parameters":9,"deterministic":True,"outer_labels_used":False}
                        write_json(job/"fit.json",receipt)
                    else:
                        emit = lambda event,**kw:log.emit(event,slot=name,model=family,seed=seed,**kw)
                        receipt = fit(train_x,torch.as_tensor(y,device="cuda"),torch.as_tensor(mask,device="cuda"),
                            checkpoint_x,checkpoint_y,checkpoint_mask,evaluation_x,seed=seed,out=job,options=config["training"],
                            expired=stopped.is_set,emit=emit,permit=permit,
                            fixed_epochs=None if fixed is None else fixed[family][str(seed)])
                        budget.finish(receipt)
                        with np.load(job/"evaluation-prediction.npz",allow_pickle=False) as saved:
                            prediction = saved["standardized_residual"].copy()
                    if family in RIDGES:
                        budget.finish(receipt)
                    if prediction.shape!=(len(values["evaluation_rows"]),8) or not np.isfinite(prediction).all():
                        raise FloatingPointError("finite aligned eight-asset residual forecasts required")
                    if null is not None:
                        write_json(job/"null-permutation.json",null)
                    write_json(job/"input-reference.json",GUARDS|{"prepared_root":str(ready),"slot":name,
                        "slot_arrays_sha256":sha256(ready/f"{name}.npz"),"slot_transform_sha256":sha256(ready/f"{name}.json")})
                    receipts[family][str(seed)],predictions[name][family][str(seed)] = receipt,prediction
                    log.emit("fit_finished",slot=name,model=family,seed=seed,**receipt)
                    log.update(fits_started=budget.started,fits_completed=budget.completed)
            del train_x,checkpoint_x,checkpoint_y,checkpoint_mask,evaluation_x
            torch.cuda.empty_cache()
            return receipts

        def select_year(year):
            alive()
            log.update(status="past_inner_selection",current_outer_year=year)
            selection,curves = select_from_past(year,arrays,predictions,panel,inputs,anchor=anchor,
                interval_samples=config["engine"]["interval_samples"],stability_samples=config["engine"]["stability_samples"])
            alive()
            folder = out/"validation"/f"WF{year}"
            folder.mkdir(parents=True)
            write_json(folder/"selection.json",GUARDS|selection)
            for name,curve in curves.items():
                np.savez_compressed(folder/f"{name}.npz",**curve)
            log.emit("past_only_selection_frozen",outer_year=year,selected=selection["selected"])
            return selection

        def freeze(selections,epochs):
            alive()
            write_json(out/"selection-freeze.json",GUARDS|{"created_at":utc_now(),"selections":selections,"epochs":epochs,
                "fits_completed":budget.completed,"outer_labels_used":False})
            log.emit("all_selections_and_epochs_frozen",fits_completed=budget.completed,outer_test_status="withheld")

        def outer(selections):
            alive()
            if not (out/"selection-freeze.json").is_file() or budget.completed!=272:
                raise RuntimeError("outer diagnostics require frozen choices and all registered fits")
            log.update(status="outer_diagnostics",outer_test_status="released_after_freeze")
            sequence = {n:[] for n in (*FAMILIES,"selected")}
            outer_out = out/"outer_test";outer_out.mkdir()
            from .training_data import load_training_data
            data = load_training_data(Path(config["data"]["root"]),config["data"]["manifest_sha256"])
            beta,realised,_ = target_context(data,panel)
            predictive = {n:[] for n in sequence}
            seed_predictive = {n:{str(s):[] for s in config["training"]["seeds"]} for n in NEURALS}
            for year in range(2020,2027):
                name = f"final_{year}";values=arrays[name];rows=values["evaluation_rows"]
                forecasts = {f:total_forecast(values,np.mean(list(predictions[name][f].values()),axis=0)) for f in (*RIDGES,*NEURALS)}
                forecasts.update({n:values[c] for n,c in zip(BASELINES,("evaluation_base","evaluation_asset_train_mean","evaluation_momentum120","evaluation_cash"))})
                forecasts["selected"] = forecasts[selections[f"WF{year}"]["selected"]]
                transform = read_json(ready/f"{name}.json")["transform"]
                context = ResidualTransform(np.asarray(transform["means"]),np.asarray(transform["kappa"]),transform["scale"],transform["spy"])
                truth = context.residual(data,rows,realised,beta)[:,values["learned_columns"]]/context.scale
                mask = data.masks["mu20"][rows][:,values["learned_columns"]]&np.isfinite(truth)
                labels = {"evaluation_y":np.where(mask,truth,0),"evaluation_mask":mask}
                for neural in NEURALS:
                    for seed,pred in predictions[name][neural].items():
                        seed_predictive[neural][seed].append(prediction_stats(labels,pred)["rank"])
                for family,mu in forecasts.items():
                    sequence[family].append((rows,mu))
                    folder=outer_out/family;folder.mkdir(exist_ok=True)
                    np.savez_compressed(folder/f"WF{year}-predictions.npz",rows=rows,mu20=mu)
                    residual = (mu-values["evaluation_base"])[:,values["learned_columns"]]/context.scale
                    stats = prediction_stats(labels,residual)
                    total_mask = data.masks["mu20"][rows]&np.isfinite(data.targets["mu20"][rows])
                    total_ic,total_rank = ic_series(mu,data.targets["mu20"][rows],total_mask)
                    stats.update(total_ic=total_ic,total_rank=total_rank)
                    predictive[family].append(stats)
                    np.savez_compressed(folder/f"WF{year}-IC.npz",rows=rows,**stats)
            reports = {}
            for family,parts in sequence.items():
                reports[family] = {}
                for multiplier in (1.,2.,3.):
                    alive()
                    metrics,curve = execute_path(panel,parts,inputs,anchor=anchor,multiplier=multiplier)
                    np.savez_compressed(outer_out/family/f"continuous-{multiplier:g}x.npz",**curve)
                    reports[family][f"{multiplier:g}x"] = outer_summary(metrics,curve,panel,inputs.cash_returns)
                log.emit("outer_family_complete",model=family)
            diagnostic = {family:{"residual_rank_ic":mean_finite(np.concatenate([s["rank"] for s in stats])),
                "standardized_residual_huber":mean_finite(np.concatenate([s["huber"] for s in stats])),
                "total_return_rank_ic":mean_finite(np.concatenate([s["total_rank"] for s in stats]))}
                for family,stats in predictive.items()}
            for real,controls in ((RIDGES[0],RIDGES[1:]),(NEURALS[0],NEURALS[1:])):
                own = np.concatenate([s["rank"] for s in predictive[real]])
                diagnostic[real]["paired_null_rank_intervals"] = {control:{str(b):block_interval(
                    own-np.concatenate([s["rank"] for s in predictive[control]]),block=b) for b in (40,60,120)} for control in controls}
            for family,seeds in seed_predictive.items():
                diagnostic[family]["seed_residual_rank_ic"] = {s:mean_finite(np.concatenate(v)) for s,v in seeds.items()}
            write_json(outer_out/"predictive-diagnostics.json",GUARDS|{"selection_already_frozen":True,"families":diagnostic})
            return reports

        result = execute_schedule(config["training"]["seeds"],train_slot,select_year,freeze,outer)
        expected = 51 if result["status"]=="pilot_no_increment" else 272
        if budget.started!=expected or budget.completed!=expected:
            raise RuntimeError("registered schedule and actual fit counts differ")
        summary.update(result)
    except InterruptedError as error:
        summary.update(status="owner_or_signal_stopped",error=str(error))
    except Exception as error:
        summary.update(status="failed",error=f"{type(error).__name__}: {error}")
        log.emit("run_failed",error=summary["error"])
    finally:
        monitor_stop.set();monitor.join(timeout=5)
        for sig,handler in previous.items():
            signal.signal(sig,handler)
        summary.update(fits_started=budget.started,fits_completed=budget.completed,finished_at=utc_now(),
                       seconds=time.monotonic()-started,automatic_restart_authorized=False)
        log.update(status=summary["status"],outer_test_status=summary["outer_test_status"],
                   fits_started=budget.started,fits_completed=budget.completed)
        write_json(out/"summary.json",summary)
        report = "# R3 residual run\n\nresearch_only=true / orders_authorized=false / holdout_role=discovery\n\n"
        report += f"Status: {summary['status']}; fits {budget.completed}/{budget.started}; outer {summary['outer_test_status']}.\n\n"
        if summary.get("outer_test"):
            report += "| Family (2x cost) | CAGR | Cash-excess Sharpe | MDD |\n| --- | ---: | ---: | ---: |\n"
            for name,metrics in summary["outer_test"].items():
                b=metrics["2x"];report+=f"| {name} | {b['cagr']:.2%} | {b['sharpe_excess_cash']:.3f} | {b['max_drawdown']:.2%} |\n"
        (out/"REPORT.md").write_text(report)
        log.stream.close()
        finish_manifest(out,phase=summary["status"],ready_manifest_sha256=sha256(ready/"manifest.json"))
    return summary


def info_binding(ready):
    info = read_json(ready/"READY.json")
    return GUARDS|{"ready_root":str(ready),"prepared_manifest_sha256":sha256(ready/"manifest.json"),
                  "dataset_manifest_sha256":info["dataset_manifest_sha256"],
                  "deployment_manifest_sha256":info["deployment_manifest_sha256"]}
