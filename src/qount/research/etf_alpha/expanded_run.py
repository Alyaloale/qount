"""Authorized P3 v2 large augmentation/ablation run; CPU then one CUDA trainer."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import datetime as dt
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
import time
import traceback

import numpy as np
import torch

from .artifacts import GUARDS, finish_manifest, new_directory, read_json, sha256, utc_now, write_json
from .augmentation import prepare_bootstrap, verify_bootstrap
from .compute import gpu_preflight, profile, storage_preflight, monitor_compute
from .diagnostics import block_interval, bridge_report, lagged_beta, prediction_report
from .expanded_data import BootstrapSpec, load_panel, representation
from .expanded_models import ExpandedPredictor, ExpandedSpec
from .expanded_reporting import render_report
from .expanded_selection import BASELINES, select_v2
from .expanded_training import fit_expanded, load_bootstrap
from .models import ModelSpec, SharedPredictor
from .overnight import RunLog, adapt, prepare_fold, report_job, save_partition
from .ridge import block_permutation
from .training import TensorPartition, _prediction, fit, inverse_predictions
from .training_data import Partition, load_folds, load_training_data

SCHEDULE = ("E3-mlp-mtr", "E3-mlp-raw", "v2-levels", "v2-levels-id", "v2-rank-id",
            "v2-rank-shuffle", "v2-bootstrap-rank-id")


def validate_contract(config):
    for key, expected in (GUARDS | {"training_start_authorized": True, "schema": "etf-alpha-expanded-v2",
        "concurrent_cuda_jobs": 1, "retry_failed_jobs": False, "change_services": False,
        "restore_cloud_3090": False, "outer_test_after_selection_freeze": True,
        "amp": False, "matmul_precision": "highest"}).items():
        if config.get(key) != expected:
            raise ValueError(f"undeclared research contract: {key}")
    hours = config["max_hours"]
    if hours is not None and (isinstance(hours, bool) or not isinstance(hours, (int, float))
                              or not np.isfinite(hours) or hours <= 0):
        raise ValueError("max_hours must be null or a finite positive duration")
    if config["max_fits"] != 259:
        raise ValueError("the registered 259-fit bound is required")
    if config["model_schedule"] != list(SCHEDULE) or config["seeds"] != list(range(1000, 1005)):
        raise ValueError("unregistered architecture/seed sweep")
    if config["dataset_manifest_sha256"] != "bfb139712e50be05e78df4b0eb305378d37e3c8ce0cd37c15bfd8545651235bb":
        raise ValueError("the registered frozen M0/M1 input is required")
    spec = BootstrapSpec(**config["bootstrap"])
    if spec != BootstrapSpec():
        raise ValueError("fixed 1024-world-per-fold bootstrap protocol required")
    if not 1 <= config["cpu_generation_workers"] <= 24:
        raise ValueError("bounded CPU generation workers required")
    compute = profile(config)
    if config["cpu_generation_workers"] > compute["cpu_limit"]:
        raise ValueError("generation workers exceed the declared allocation")
    options = config["training"]
    expected_options = {"learning_rate": .0003, "matrix_weight_decay": .001, "batch_dates": 64,
        "max_epochs": 200, "early_stopping_patience": 15, "early_stopping_min_delta": .0001,
        "pretrain_batch_dates": 4096, "pretrain_max_epochs": 256, "pretrain_max_seconds_per_fit": 600}
    if options != expected_options:
        raise ValueError("fixed optimization and per-fit compute limits required")
    if config["selector"] != "validation_rank_controls_huber_1.05_hard_budget_risk_utility_v2":
        raise ValueError("undeclared validation selector")
    return spec


def expiry_checks(max_hours, begun, stop):
    """An unlimited run still honors manual stop; bounded runs reserve cleanup time."""
    deadline = None if max_hours is None else begun + max_hours * 3600
    expired = lambda: stop.is_set() or (deadline is not None and time.monotonic() >= deadline - 600)
    final_expired = lambda: stop.is_set() or (deadline is not None and time.monotonic() >= deadline - 60)
    return deadline, expired, final_expired


def expanded_partition(part, all_assets, market):
    return Partition(part.rows, all_assets[part.rows].copy(), market[part.rows].astype(np.float32),
                     {"mu20": part.targets["mu20"]} if "mu20" in part.targets else {},
                     {"mu20": part.masks["mu20"]} if "mu20" in part.masks else {})


def baseline_prediction(name, panel, raw, names, data, train_rows, rows):
    if name == "train-asset-mean":
        y, m = data.targets["mu20"][train_rows], data.masks["mu20"][train_rows]
        means = np.where(m, y, 0).sum(0) / m.sum(0)
        return np.broadcast_to(means, (len(rows), len(panel.symbols))).copy()
    if name == "momentum120":
        return raw[rows, :, names.index("return120")] / 6
    if name == "cash":
        forecast = panel.cash_close[rows] / panel.cash_close[rows - 20] - 1
        return np.broadcast_to(forecast[:, None], (len(rows), len(panel.symbols))).copy()
    raise ValueError("unknown fixed baseline")


def continuous_metrics(combined, data, panel):
    from qount.research.etf_trader.env import max_drawdown
    totals = {}
    for multiplier in (1, 2, 3):
        r = combined[f"returns_{multiplier}x"][1:]
        equity = combined[f"equity_{multiplier}x"]
        cash = panel.cash_close[combined["rows"][1:]] / panel.cash_close[combined["rows"][1:] - 1] - 1
        excess = r - cash
        dates = np.asarray(data.dates)[combined["rows"]][1:]
        annual = {year: {"return": float(np.prod(1 + r[np.char.startswith(dates, year)]) - 1),
                         "days": int(np.char.startswith(dates, year).sum()), "partial": year == "2026"}
                  for year in sorted({d[:4] for d in dates})}
        best = max((y for y in annual if not annual[y]["partial"]), key=lambda y: annual[y]["return"])
        dropped = r[~np.char.startswith(dates, best)]
        sd = excess.std(ddof=1)
        totals[f"{multiplier}x"] = {"cagr": float((equity[-1] / equity[0]) ** (252 / len(r)) - 1),
            "sharpe_excess_cash": float(excess.mean() / sd * np.sqrt(252)) if sd > 1e-12 else None,
            "max_drawdown": max_drawdown(equity), "annual": annual,
            "drop_best_complete_year": {"year": best, "cagr": float(np.prod(1 + dropped) ** (252 / len(dropped)) - 1)},
            "excess_daily_mean_intervals": {str(b): block_interval(excess, block=b) for b in (40, 60, 120)}}
    return totals


def evaluate_all(data, panel, raw, all_assets, folds, prepared, selections, out, config, beta, *, expired, log):
    families = (*BASELINES, "negative-ridge-shuffle", *SCHEDULE, "selected")
    states, curves, reports = {k: {} for k in families}, {k: [] for k in families}, {k: {} for k in families}
    anchor = int(folds[0].test_rows[0])
    for fold, items in zip(folds, prepared):
        scales, train, validation, full = items
        rows = fold.test_rows
        base = Partition(rows, data.assets[rows].astype(np.float32), None, {}, {})
        expanded = Partition(rows, all_assets[rows], data.market[rows].astype(np.float32), {}, {})
        old_gpu, expanded_gpu = TensorPartition.from_partition(base, "cuda"), TensorPartition.from_partition(expanded, "cuda")
        predictions = {}
        for name in families:
            if expired():
                return {"status": "budget_stopped", "folds": reports}
            if name == "selected":
                mu = predictions[selections[fold.fold_id]["selected"]]
            elif name in ("E3-ridge-raw", "negative-ridge-shuffle"):
                with np.load(out / "prepared" / fold.fold_id / name / "model.npz") as saved:
                    mu = scales.inverse("mu20", base.assets @ saved["coefficients"] + saved["intercept"])
            elif name in BASELINES:
                mu = baseline_prediction(name, panel, raw, data.names, data, fold.train_rows, rows)
            else:
                values = []
                for seed in config["seeds"]:
                    path = out / fold.fold_id / name / f"seed_{seed}"
                    checkpoint = torch.load(path / "best.pt", map_location="cuda", weights_only=True)
                    if name.startswith("E3"):
                        spec = ModelSpec(3 if name.endswith("mtr") else 38)
                        model, part = SharedPredictor(spec).cuda(), adapt(old_gpu, spec)
                    else:
                        spec = ExpandedSpec(identity=name != "v2-levels", rank_weight=.3 if "rank" in name else 0.)
                        model, part = ExpandedPredictor(spec).cuda(), expanded_gpu
                    model.load_state_dict(checkpoint["model"], strict=True)
                    mu = inverse_predictions(_prediction(model, model.forward, part), scales)["mu20"]
                    np.savez_compressed(path / "test.npz", rows=rows, mu20=mu)
                    values.append(mu)
                    del model
                mu = np.mean(values, axis=0)
            predictions[name] = mu
            root = out / "outer_test" / name / fold.fold_id
            root.mkdir(parents=True)
            np.savez_compressed(root / "predictions.npz", rows=rows, mu20=mu)
            prediction, ic = prediction_report(data, rows, {"mu20": mu}, scales, panel, beta)
            bridge, curve, states[name] = bridge_report(panel, rows, mu, state_by_cost=states[name], anchor=anchor)
            np.savez_compressed(root / "ic.npz", **ic)
            np.savez_compressed(root / "curve.npz", **curve)
            report = GUARDS | {"fold": fold.fold_id, "family": name, "prediction": prediction,
                               "bridge": bridge, "seeds": config["seeds"] if name in SCHEDULE else [],
                               "used_for_selection": False}
            write_json(root / "report.json", report)
            reports[name][fold.fold_id] = report
            curves[name].append(curve)
            log.emit("outer_fold_complete", fold=fold.fold_id, family=name, rank_ic=prediction["rank_ic"], bridge=bridge)
        del old_gpu, expanded_gpu
    totals = {}
    for name in families:
        combined = {key: np.concatenate([c[key] if i == 0 else c[key][1:] for i, c in enumerate(curves[name])])
                    for key in curves[name][0]}
        np.savez_compressed(out / "outer_test" / name / "continuous-curve.npz", **combined)
        totals[name] = continuous_metrics(combined, data, panel)
    return {"status": "complete", "continuous": totals, "folds": reports,
            "holdout_role": "discovery", "fresh_confirmation": "insufficient", "production_effect": False}


def run(config_path: Path, out: Path, dataset_out: Path, *, repository: Path, reuse_bootstrap=False):
    config = read_json(config_path)
    spec = validate_contract(config)
    capacity = storage_preflight(config, spec, reuse_bootstrap=reuse_bootstrap)
    compute = capacity["profile"]
    storage = Path(compute["storage_root"])
    gpu_preflight(config)
    new_directory(out, external_root=storage)
    if reuse_bootstrap:
        dataset_out.resolve().relative_to(storage / "datasets" / "etf_alpha_p3")
    else:
        new_directory(dataset_out, kind="datasets", external_root=storage)
    begun, stop, monitor_stop = time.monotonic(), threading.Event(), threading.Event()
    deadline, expired, final_expired = expiry_checks(config["max_hours"], begun, stop)
    log = RunLog(out, deadline)
    handlers = {sig: signal.signal(sig, lambda *_: stop.set()) for sig in (signal.SIGINT, signal.SIGTERM)}
    monitor_thread = threading.Thread(target=monitor_compute, args=(log, monitor_stop, compute), daemon=True)
    monitor_thread.start()
    summary = GUARDS | {"status": "starting", "started_at": utc_now(), "outer_test_status": "withheld",
                        "selections": {}, "bootstrap_root": str(dataset_out), "failures": [],
                        "max_hours": config["max_hours"], "wall_clock_limit_enabled": deadline is not None}
    completed, started = 0, 0
    diagnostics = ThreadPoolExecutor(max_workers=compute["diagnostic_workers"])
    try:
        write_json(out / "run-contract.json", config)
        code = out / "run-code"
        for relative in ("src/qount/research/etf_alpha", "src/qount/research/etf_trader"):
            shutil.copytree(repository / relative, code / relative, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.so"))
        for relative in ("src/qount/__init__.py", "src/qount/research/__init__.py", "scripts/research/etf_alpha_expand.py"):
            (code / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(repository / relative, code / relative)
        (code / "config").mkdir()
        shutil.copy2(config_path, code / "config" / config_path.name)
        proposal = read_json(repository / config["control_proposal"])
        shutil.copy2(repository / config["control_proposal"], code / config["control_proposal"])
        packages = subprocess.run([os.sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True, check=True, timeout=30)
        (out / "requirements-lock.txt").write_text(packages.stdout)
        deadline_utc = None if deadline is None else (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=config["max_hours"])).isoformat()
        workers = min(config["cpu_generation_workers"], capacity["effective_cpus"])
        write_json(out / "environment.json", {"python": os.sys.version, "executable": os.sys.executable,
            "torch": torch.__version__, "numpy": np.__version__, "cuda": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0), "logical_cpus": len(os.sched_getaffinity(0)),
            "cpu_generation_workers": workers, "deadline_utc": deadline_utc,
            "source_manifest_sha256": config["dataset_manifest_sha256"], "run_contract_sha256": sha256(config_path),
            "compute_profile": compute, "capacity": {k: v for k, v in capacity.items() if k != "profile"}})
        torch.set_num_threads(2)
        torch.set_num_interop_threads(2)
        torch.set_float32_matmul_precision("highest")
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch._dynamo.config.cache_size_limit = 64
        log.update(status="cpu_preparation", deadline_utc=deadline_utc, run_root=str(out),
                   bootstrap_root=str(dataset_out), cpu_generation_workers=workers,
                   wall_clock_limit_enabled=deadline is not None, max_hours=config["max_hours"])
        data_root = Path(config["data_root"])
        data_root.resolve().relative_to(storage / "datasets" / "etf_alpha_p3")
        data = load_training_data(data_root, config["dataset_manifest_sha256"])
        folds = load_folds(Path(config["fold_contract"]), read_json(data_root / "dataset-contract.json"))
        if [f.fold_id for f in folds] != [f"WF{y}" for y in range(2020, 2027)]:
            raise ValueError("seven frozen folds required")
        panel, beta = load_panel(data_root), None
        beta = lagged_beta(panel)
        with np.load(data_root / "features.npz", allow_pickle=False) as saved:
            raw = saved["raw"].copy()
        all_assets = representation(raw, data.assets, data.names)
        ready = out / "prepared"
        ready.mkdir()
        from threadpoolctl import threadpool_limits
        with threadpool_limits(limits=1), ThreadPoolExecutor(max_workers=7) as pool:
            prepared = list(pool.map(lambda f: prepare_fold(data, f, ready, proposal["training"], log), folds))
        for fold, (_, train, validation, full) in zip(folds, prepared):
            for name, part in (("train", train), ("validation", validation), ("validation_bridge", full)):
                save_partition(ready / fold.fold_id / f"expanded_{name}", expanded_partition(part, all_assets, data.market))
        finish_manifest(ready, phase="real_cpu_preparation_complete", test_prepared=False)
        started = completed = 14
        log.update(status="cpu_bootstrap_generation", fits_started=started, fits_completed=completed)
        log.emit("bootstrap_generation_started", worlds=spec.worlds_per_fold * 7, workers=workers,
                 expected_bytes=spec.estimated_bytes_per_fold * 7)
        if reuse_bootstrap:
            bootstrap_manifest = verify_bootstrap(spec, data_root, folds, data.dates, dataset_out)
            log.emit("bootstrap_reused", root=str(dataset_out), verified=True)
        else:
            bootstrap_manifest = prepare_bootstrap(spec, data_root, folds, data.dates, dataset_out, workers,
                                                   expired=expired, emit=log.emit)
        summary["bootstrap_manifest_sha256"] = sha256(dataset_out / "manifest.json")
        summary["usable_augmented_dates"] = bootstrap_manifest["usable_augmented_dates"]
        log.emit("cpu_phase_complete", seconds=time.monotonic() - begun,
                 usable_augmented_dates=summary["usable_augmented_dates"], manifest_sha256=summary["bootstrap_manifest_sha256"])
        log.update(status="gpu_training")
        for fold, items in zip(folds, prepared):
            if expired():
                break
            scales, train, validation, full = items
            fold_out = out / fold.fold_id
            fold_out.mkdir()
            old = [TensorPartition.from_partition(p, "cuda") for p in (train, validation, full)]
            expanded = [TensorPartition.from_partition(expanded_partition(p, all_assets, data.market), "cuda")
                        for p in (train, validation, full)]
            records = {}
            for name in ("E3-ridge-raw", "negative-ridge-shuffle"):
                records[name] = [report_job(data, panel, beta, scales, ready / fold.fold_id / name, 1000, 39)]
            for name in BASELINES[1:]:
                job = fold_out / name
                job.mkdir()
                for key, part in (("validation", validation), ("validation_bridge", full)):
                    mu = baseline_prediction(name, panel, raw, data.names, data, fold.train_rows, part.rows)
                    np.savez_compressed(job / f"{key}.npz", rows=part.rows, mu20=mu)
                records[name] = [report_job(data, panel, beta, scales, job, 1000, 9 if name == "train-asset-mean" else 0)]
            for name in SCHEDULE:
                if expired():
                    break
                boot = None
                if name == "v2-bootstrap-rank-id":
                    boot = load_bootstrap(dataset_out / fold.fold_id, scales)
                    log.emit("bootstrap_resident", fold=fold.fold_id, dates=len(boot.rows),
                             allocated_bytes=torch.cuda.memory_allocated())
                pending = []
                for seed in config["seeds"]:
                    if expired():
                        break
                    started += 1
                    if started > config["max_fits"]:
                        raise RuntimeError("registered fit budget exceeded")
                    job = fold_out / name / f"seed_{seed}"
                    log.update(current_fold=fold.fold_id, current_model=name, current_seed=seed, fits_started=started)
                    emit = lambda event, **kw: log.emit(event, fold=fold.fold_id, model=name, seed=seed, **kw)
                    emit("fit_started")
                    if name.startswith("E3"):
                        ms = ModelSpec(3 if name.endswith("mtr") else 38)
                        receipt = fit(ms, adapt(old[0], ms), adapt(old[1], ms), scales, seed, job,
                            proposal["training"], expired=expired, emit=emit,
                            inference={"validation_bridge": adapt(old[2], ms)},
                            compile_mode=("reduce-overhead" if compute["kind"] == "wsl_4060" else "default")
                            if compute["compile_real"] else None)
                    else:
                        ms = ExpandedSpec(identity=name != "v2-levels", rank_weight=.3 if "rank" in name else 0.)
                        tp = expanded[0]
                        if name == "v2-rank-shuffle":
                            perm = torch.as_tensor(block_permutation(len(tp.rows), seed=seed), device="cuda")
                            tp = TensorPartition(tp.rows, tp.assets, tp.market,
                                {"mu20": tp.targets["mu20"][perm]}, {"mu20": tp.masks["mu20"][perm]})
                        receipt = fit_expanded(ms, tp, expanded[1], scales, seed, job, config["training"],
                            expired=expired, emit=emit, bootstrap=boot, inference={"validation_bridge": expanded[2]},
                            compile_enabled=compute["compile_bootstrap"] if boot is not None else compute["compile_real"])
                    emit("fit_finished", **receipt)
                    if receipt["status"] != "complete":
                        stop.set()
                        break
                    completed += 1
                    log.update(fits_completed=completed)
                    pending.append(diagnostics.submit(report_job, data, panel, beta, scales, job, seed, ms.parameters))
                records[name] = sorted([future.result() for future in pending], key=lambda r: r["seed"])
                del boot
                if name == "v2-bootstrap-rank-id":
                    torch.cuda.empty_cache()
            if expired() or any(len(records.get(k, [])) != 5 for k in SCHEDULE):
                break
            selected = GUARDS | {"fold": fold.fold_id, **select_v2(records)}
            write_json(fold_out / "screening-diagnostics.json", records)
            write_json(fold_out / "selection.json", selected)
            summary["selections"][fold.fold_id] = selected
            log.emit("selection_frozen", **selected)
            del old, expanded
        if len(summary["selections"]) == 7 and not expired():
            write_json(out / "selection-freeze.json", GUARDS | {"selections": summary["selections"],
                "fits_completed": completed, "frozen_families": list(SCHEDULE), "outer_not_used": True,
                "frozen_at": utc_now()})
            log.update(status="outer_test", outer_test_status="evaluating")
            log.emit("outer_test_unsealed", selection_sha256=sha256(out / "selection-freeze.json"))
            summary["outer_test"] = evaluate_all(data, panel, raw, all_assets, folds, prepared,
                summary["selections"], out, config, beta, expired=final_expired, log=log)
            summary["outer_test_status"] = summary["outer_test"]["status"]
            summary["status"] = "complete" if summary["outer_test_status"] == "complete" else "budget_stopped"
        else:
            summary["status"] = "budget_stopped"
        write_json(out / "family-review.json", GUARDS | {"outer_status": summary["outer_test_status"],
            "new_independent_training_information": False, "next_stage_authorized": False,
            "fresh_confirmation": "insufficient", "DSR_PBO": "not_identifiable_from_seven_overlapping_annual_folds",
            "production_effect": False, "no_automatic_new_trials": True})
    except Exception as exc:
        summary["status"] = "budget_stopped" if isinstance(exc, TimeoutError) and expired() else "failed"
        summary["error"] = f"{type(exc).__name__}: {exc}"
        summary["failures"].append(summary["error"])
        (out / "failure-traceback.txt").write_text(traceback.format_exc())
        log.emit("run_failed", error=summary["error"])
    finally:
        diagnostics.shutdown(wait=True, cancel_futures=True)
        monitor_stop.set()
        monitor_thread.join(timeout=6)
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
        summary.update(fits_started=started, fits_completed=completed, seconds=time.monotonic() - begun, finished_at=utc_now())
        summary["estimated_compute_cost_cny"] = summary["seconds"] / 3600 * compute["price_per_hour_cny"]
        summary["cost_is_provider_bill"] = False
        log.update(status=summary["status"], fits_started=started, fits_completed=completed,
                   outer_test_status=summary["outer_test_status"], error=summary.get("error"))
        write_json(out / "summary.json", summary)
        (out / "REPORT.md").write_text(render_report(summary, config), encoding="utf-8")
        log.emit("run_finished", status=summary["status"], fits_completed=completed, seconds=summary["seconds"])
        log.close()
        finish_manifest(out, schema="etf-alpha-expanded-results-v2", status=summary["status"],
                        result_status="research_diagnostics", bootstrap_root=str(dataset_out))
    return summary
