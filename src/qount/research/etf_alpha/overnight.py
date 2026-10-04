"""Bounded E3/E4/E5 walk-forward scheduler on WSL and the external E disk.

CPU preparation is frozen before GPU fitting. No market-data acquisition,
credentials, service operations, P2 resumption or order interfaces are used.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import datetime as dt
import json
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

from .artifacts import EXTERNAL_ROOT, GUARDS, finish_manifest, new_directory, read_json, sha256, utc_now, write_json
from .data import Panel
from .diagnostics import bridge_report, lagged_beta, prediction_report, retention as _retention, select_candidate, block_interval
from .models import HEADS, ModelSpec, SharedPredictor
from .ridge import block_permutation, fit_ridge
from .training import TensorPartition, _prediction, fit, inverse_predictions
from .training_data import Partition, fit_target_scales, load_folds, load_training_data, prepare_partition


def retention(candidate, parent):
    """Preserve the immutable v1 proposal when replaying this older entry."""
    return _retention(candidate, parent, turnover_rule="parent_nonincrease_v1")


def validate_run(config, proposal):
    if config.get("training_start_authorized") is not True or config.get("research_only") is not True or config.get("orders_authorized") is not False:
        raise ValueError("explicit research training authorization contract required")
    if not 0 < config["max_hours"] <= 8 or config["max_fits"] != 224 or config["concurrent_cuda_jobs"] != 1:
        raise ValueError("bounded eight-hour, 224-fit, single-GPU contract required")
    if config["seeds"] != list(range(1000, 1005)) or config["final_seeds"] != list(range(1005, 1010)):
        raise ValueError("seed search outside the frozen proposal")
    if config["amp"] or config["matmul_precision"] != "highest" or config["retry_failed_jobs"]:
        raise ValueError("precision changes and automatic retries are not declared")
    if config["restore_cloud_3090"] or config["change_services"] or not config["outer_test_after_selection_freeze"]:
        raise ValueError("run exceeds the declared research boundary")
    if config["data_root"] != proposal["data"]["root"] or config["dataset_manifest_sha256"] != proposal["data"]["manifest_sha256"]:
        raise ValueError("inputs differ from the declared frozen proposal")
    schedule = ["E3-mlp-mtr", "E3-mlp-raw", "E4-mlp-multitask", "E5-market-mlp", "E5-market-gru"]
    if config["model_schedule"] != schedule or proposal["training"]["amp"]:
        raise ValueError("configuration sweep is not authorized")


class RunLog:
    def __init__(self, out, deadline):
        self.out, self.deadline = out, deadline
        self.lock = threading.Lock()
        self.stream = (out / "events.jsonl").open("x", buffering=1)
        self.state = GUARDS | {"status": "preparing", "fits_started": 0, "fits_completed": 0,
                               "fits_failed": 0, "outer_test_status": "withheld"}

    def emit(self, event, **data):
        with self.lock:
            record = {"time": utc_now(), "event": event,
                      "remaining_seconds": None if self.deadline is None else max(0, self.deadline - time.monotonic()), **data}
            line = json.dumps(record, ensure_ascii=False, allow_nan=False)
            self.stream.write(line + "\n")
            print(line, flush=True)

    def update(self, **data):
        with self.lock:
            self.state.update(data, updated_at=utc_now())
            tmp = self.out / "status.json.tmp"
            tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2, allow_nan=False))
            tmp.replace(self.out / "status.json")

    def close(self):
        with self.lock:
            self.stream.close()


def monitor(log, stopped):
    smi = Path("/usr/lib/wsl/lib/nvidia-smi")
    while not stopped.wait(15):
        try:
            gpu = subprocess.run([str(smi), "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
                                  "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5)
            log.emit("resources", gpu_csv=gpu.stdout.strip(), gpu_probe_returncode=gpu.returncode,
                     load_average=list(os.getloadavg()), e_disk_free_bytes=shutil.disk_usage(EXTERNAL_ROOT).free)
        except Exception as exc:
            log.emit("resource_probe_failed", error=str(exc))


def save_partition(root, part):
    root.mkdir()
    arrays = {"rows": part.rows, "assets": part.assets, **({"market": part.market} if part.market is not None else {}),
              **{f"target_{k}": v for k, v in part.targets.items()}, **{f"mask_{k}": v for k, v in part.masks.items()}}
    for name, value in arrays.items():
        np.save(root / f"{name}.npy", value, allow_pickle=False)
    return {p.name: sha256(p) for p in sorted(root.iterdir())}


def predict_partition(data, rows):
    indices = data.windows(rows)
    if not data.available[rows].all():
        raise ValueError("prediction features are incomplete")
    return Partition(rows.copy(), data.assets[rows].astype(np.float32), data.market[indices].astype(np.float32), {}, {})


def prepare_fold(data, fold, root, options, log):
    directory = root / fold.fold_id
    directory.mkdir()
    counts = data.validate_fold(fold)
    scales = fit_target_scales(data, fold.train_rows, HEADS)
    train = prepare_partition(data, fold.train_rows, scales, HEADS, tuple(range(38)), market=True)
    validation = prepare_partition(data, fold.validation_rows, scales, HEADS, tuple(range(38)), market=True)
    va, te = np.searchsorted(data.dates, [fold.validation_start, fold.test_start])
    full_validation = predict_partition(data, np.arange(va, te))
    hashes = {name: save_partition(directory / name, part) for name, part in
              (("train", train), ("validation", validation), ("validation_bridge", full_validation))}
    ridge = fit_ridge(train.assets, train.targets["mu20"], train.masks["mu20"], options["ridge_l2_mean_mse"])
    perm = block_permutation(len(train.rows))
    negative = fit_ridge(train.assets, train.targets["mu20"][perm], train.masks["mu20"][perm], options["ridge_l2_mean_mse"])
    for name, model in (("E3-ridge-raw", ridge), ("negative-ridge-shuffle", negative)):
        out = directory / name
        out.mkdir()
        np.savez(out / "model.npz", coefficients=model.coefficients, intercept=model.intercept)
        for label, part in (("validation", validation), ("validation_bridge", full_validation)):
            mu = scales.inverse("mu20", model.predict(part.assets))
            np.savez_compressed(out / f"{label}.npz", rows=part.rows, mu20=mu)
    np.save(directory / "negative-control-permutation.npy", perm, allow_pickle=False)
    write_json(directory / "preparation.json", GUARDS | {"fold": fold.fold_id, "counts": counts,
        "target_scales": asdict(scales), "files": hashes, "mtr_columns": list(range(35, 38)),
        "test_prepared": False, "ridge_penalty": options["ridge_l2_mean_mse"], "negative_control_seed": 1000})
    log.emit("fold_prepared", fold=fold.fold_id, **counts)
    return scales, train, validation, full_validation


def report_job(data, panel, beta, scales, job, seed, parameters):
    with np.load(job / "validation.npz", allow_pickle=False) as saved:
        rows = saved["rows"].copy()
        pred = {k: saved[k].copy() for k in HEADS if k in saved}
    metrics, series = prediction_report(data, rows, pred, scales, panel, beta)
    with np.load(job / "validation_bridge.npz", allow_pickle=False) as saved:
        bridge, curves, _ = bridge_report(panel, saved["rows"], saved["mu20"])
    report = GUARDS | {"seed": seed, "parameters": parameters, "prediction": metrics, "bridge": bridge}
    np.savez_compressed(job / "validation_ic.npz", **series)
    np.savez_compressed(job / "validation_curve.npz", **curves)
    write_json(job / "diagnostics.json", report)
    return report


def spec_for(name, parent_heads=HEADS):
    market = {"E5-market-mlp": "mlp", "E5-market-gru": "gru"}.get(name, "none")
    heads = HEADS if name == "E4-mlp-multitask" else (parent_heads if market != "none" else ("mu20",))
    return ModelSpec(3 if name == "E3-mlp-mtr" else 38, tuple(heads), market)


def adapt(base, spec):
    return TensorPartition(base.rows, base.assets[..., 35:38].contiguous() if spec.asset_dim == 3 else base.assets,
                           base.market if spec.market != "none" else None,
                           {k: v for k, v in base.targets.items() if k in spec.heads},
                           {k: v for k, v in base.masks.items() if k in spec.heads})


def run(config_path: Path, out: Path, *, repository: Path) -> dict:
    config = read_json(config_path)
    proposal_path = repository / config["proposal"]
    proposal = read_json(proposal_path)
    validate_run(config, proposal)
    # Resolve/check the actual mounted E device, rather than creating a fallback /mnt/e tree.
    mounts = Path("/proc/mounts").read_text().splitlines()
    if not any(len(line.split()) > 1 and line.split()[1] == "/mnt/e" for line in mounts):
        raise ValueError("E drive is not mounted")
    data_root = Path(config["data_root"])
    data_root.resolve().relative_to(EXTERNAL_ROOT / "datasets" / "etf_alpha_p3")
    if shutil.disk_usage(EXTERNAL_ROOT).free < 5 * 1024 ** 3:
        raise ValueError("at least 5 GiB free on E required")
    if not torch.cuda.is_available():
        raise RuntimeError("RTX4060 CUDA compute is unavailable")
    if "4060" not in torch.cuda.get_device_name(0):
        raise RuntimeError("the declared RTX4060 was not found")
    new_directory(out)
    begun = time.monotonic()
    deadline = begun + config["max_hours"] * 3600
    stop, monitor_stop = threading.Event(), threading.Event()
    log = RunLog(out, deadline)
    signal_handlers = {}
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal_handlers[sig] = signal.signal(sig, lambda *_: stop.set())
    expired = lambda: stop.is_set() or time.monotonic() >= deadline - 60
    thread = threading.Thread(target=monitor, args=(log, monitor_stop), daemon=True)
    thread.start()
    summary = GUARDS | {"status": "starting", "started_at": utc_now(), "max_hours": config["max_hours"],
                        "outer_test_status": "withheld", "selections": {}, "failures": []}
    diagnostics = ThreadPoolExecutor(max_workers=config["diagnostic_workers"])
    futures = []
    fits_started = fits_completed = 0
    try:
        write_json(out / "run-contract.json", config)
        write_json(out / "training-proposal.json", proposal)
        finish_time = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=config["max_hours"])
        source_root = out / "run-code"
        source_root.mkdir()
        for relative in ("src/qount/research/etf_alpha", "src/qount/research/etf_trader"):
            shutil.copytree(repository / relative, source_root / relative, ignore=shutil.ignore_patterns("__pycache__", "*.so", "*.pyc"))
        for relative in ("src/qount/__init__.py", "src/qount/research/__init__.py"):
            shutil.copy2(repository / relative, source_root / relative)
        (source_root / "config").mkdir()
        shutil.copy2(proposal_path, source_root / config["proposal"])
        shutil.copy2(config_path, source_root / "config" / config_path.name)
        entry = source_root / "scripts/research"
        entry.mkdir(parents=True)
        shutil.copy2(repository / "scripts/research/etf_alpha_train.py", entry)
        write_json(out / "environment.json", {"python": os.sys.version, "python_executable": os.sys.executable,
            "torch": torch.__version__, "cuda": torch.version.cuda, "numpy": np.__version__,
            "gpu": torch.cuda.get_device_name(0), "logical_cpus": len(os.sched_getaffinity(0)),
            "cpu_training_threads": config["cpu_threads"], "cpu_preparation_workers": min(7, len(os.sched_getaffinity(0))),
            "deadline_utc": finish_time.isoformat(), "dataset_manifest_sha256": config["dataset_manifest_sha256"],
            "proposal_sha256": sha256(proposal_path), "run_contract_sha256": sha256(config_path)})
        packages = subprocess.run([os.sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True, timeout=30, check=True)
        (out / "requirements-lock.txt").write_text(packages.stdout)
        torch.set_num_threads(config["cpu_threads"])
        torch.set_num_interop_threads(2)
        torch.set_float32_matmul_precision(config["matmul_precision"])
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch._dynamo.config.cache_size_limit = 32
        log.update(deadline_utc=finish_time.isoformat(), started_at=summary["started_at"], run_root=str(out))
        log.emit("preflight", gpu=torch.cuda.get_device_name(0), torch=torch.__version__, deadline_utc=finish_time.isoformat())
        data = load_training_data(data_root, config["dataset_manifest_sha256"])
        folds = load_folds(Path(config["fold_contract"]), read_json(data_root / "dataset-contract.json"))
        if [f.fold_id for f in folds] != proposal["walk_forward"]["fold_ids"] or tuple(data.names[-3:]) != ("M", "Trend_orth_M", "Risk"):
            raise ValueError("fold or MTR feature contract mismatch")
        with np.load(data_root / "panel.npz", allow_pickle=False) as panel_file:
            panel = Panel(data.dates, data.symbols, **{k: panel_file[k].copy() for k in
                ("open", "high", "low", "close", "volume", "dividends", "splits", "cash_open", "cash_close")}, audit={})
        beta = lagged_beta(panel)
        ready = out / "prepared"
        ready.mkdir()
        from threadpoolctl import threadpool_limits
        with threadpool_limits(limits=1), ThreadPoolExecutor(max_workers=min(7, len(folds), len(os.sched_getaffinity(0)))) as pool:
            prepared = list(pool.map(lambda fold: prepare_fold(data, fold, ready, proposal["training"], log), folds))
        finish_manifest(ready, phase="cpu_preparation_complete", dataset_manifest_sha256=config["dataset_manifest_sha256"])
        fits_started = fits_completed = 14  # Seven declared deterministic Ridge plus seven shuffle controls.
        log.emit("cpu_phase_complete", folds=len(folds), fits=fits_completed,
                 seconds=time.monotonic() - begun, prepared_manifest_sha256=sha256(ready / "manifest.json"))
        log.update(status="training", fits_started=fits_started, fits_completed=fits_completed)
        selected_jobs = {}
        all_records = {}
        for fold, prepared_fold in zip(folds, prepared):
            if expired():
                break
            scales, train, validation, full_validation = prepared_fold
            base_train, base_validation, base_full = (TensorPartition.from_partition(p, "cuda")
                                                      for p in (train, validation, full_validation))
            records, specs = {}, {}
            fold_out = out / fold.fold_id
            fold_out.mkdir()
            for name in ("E3-ridge-raw", "negative-ridge-shuffle"):
                job = ready / fold.fold_id / name
                records[name] = [report_job(data, panel, beta, scales, job, 1000, 39)]
            parent_heads = ("mu20",)
            for name in config["model_schedule"]:
                if expired():
                    break
                if name.startswith("E5"):
                    parent_heads = HEADS if retention(records.get("E4-mlp-multitask", []), records.get("E3-mlp-raw", []))["retained"] else ("mu20",)
                spec = spec_for(name, parent_heads)
                specs[name] = spec
                pending = []
                for seed in config["seeds"]:
                    if expired():
                        break
                    job = fold_out / name / f"seed_{seed}"
                    fits_started += 1
                    if fits_started > config["max_fits"]:
                        raise RuntimeError("declared fit limit exceeded")
                    log.update(current_fold=fold.fold_id, current_model=name, current_seed=seed, fits_started=fits_started)
                    log.emit("fit_started", fold=fold.fold_id, model=name, seed=seed, parameters=spec.parameters)
                    try:
                        receipt = fit(spec, adapt(base_train, spec), adapt(base_validation, spec), scales,
                            seed, job, proposal["training"], expired=expired,
                            emit=lambda event, **kw: log.emit(event, fold=fold.fold_id, model=name, seed=seed, **kw),
                            compile_mode=config["compile_mode"], inference={"validation_bridge": adapt(base_full, spec)})
                        if receipt["status"] == "complete":
                            fits_completed += 1
                            future = diagnostics.submit(report_job, data, panel, beta, scales, job, seed, spec.parameters)
                            pending.append(future)
                            futures.append(future)
                        else:
                            stop.set()
                        log.emit("fit_finished", fold=fold.fold_id, model=name, seed=seed, **receipt)
                        log.update(fits_completed=fits_completed)
                    except Exception as exc:
                        failed = {"fold": fold.fold_id, "model": name, "seed": seed, "error": f"{type(exc).__name__}: {exc}"}
                        summary["failures"].append(failed)
                        job.mkdir(parents=True, exist_ok=True)
                        (job / "failure-traceback.txt").write_text(traceback.format_exc())
                        write_json(job / "failure.json", GUARDS | failed)
                        log.emit("fit_failed", **failed)
                        log.update(fits_failed=len(summary["failures"]))
                        if isinstance(exc, torch.cuda.OutOfMemoryError) or "CUDA" in str(exc) or "nonfinite" in str(exc):
                            raise
                records[name] = sorted([future.result() for future in pending], key=lambda r: r["seed"])
                log.emit("configuration_diagnostics", fold=fold.fold_id, model=name, completed_seeds=len(records[name]))
            if expired():
                break
            if any(len(records.get(name, [])) != 5 for name in config["model_schedule"]):
                summary["status"] = "incomplete_failed_fits"
                break
            e4 = retention(records["E4-mlp-multitask"], records["E3-mlp-raw"])
            parent = "E4-mlp-multitask" if e4["retained"] else "E3-mlp-raw"
            static = retention(records["E5-market-mlp"], records[parent])
            gru_parent = retention(records["E5-market-gru"], records[parent])
            gru_static = retention(records["E5-market-gru"], records["E5-market-mlp"])
            eligible = {name: records[name] for name in ("E3-ridge-raw", "E3-mlp-mtr", "E3-mlp-raw")}
            for name, retained in (("E4-mlp-multitask", e4["retained"]), ("E5-market-mlp", static["retained"]),
                                   ("E5-market-gru", gru_parent["retained"] and gru_static["retained"])):
                if retained:
                    eligible[name] = records[name]
            chosen = select_candidate(eligible)
            selection = GUARDS | {"fold": fold.fold_id, "selected": chosen, "eligible": list(eligible),
                "E4": e4, "E5_parent": parent, "E5_static": static, "E5_gru_parent": gru_parent,
                "E5_gru_static": gru_static, "test_used_for_selection": False,
                "extension_seeds": config["final_seeds"] if chosen != "E3-ridge-raw" else [],
                "ensemble_seeds": config["seeds"]}
            write_json(fold_out / "selection.json", selection)
            summary["selections"][fold.fold_id] = selection
            log.emit("selection_frozen", **selection)
            # Additional seeds were declared before test; no retry or new architecture.
            if chosen != "E3-ridge-raw":
                for seed in config["final_seeds"]:
                    if expired():
                        break
                    spec = specs[chosen]
                    job = fold_out / chosen / f"seed_{seed}"
                    fits_started += 1
                    if fits_started > config["max_fits"]:
                        raise RuntimeError("declared fit limit exceeded")
                    log.update(current_fold=fold.fold_id, current_model=chosen, current_seed=seed, fits_started=fits_started)
                    receipt = fit(spec, adapt(base_train, spec), adapt(base_validation, spec), scales, seed, job,
                        proposal["training"], expired=expired,
                        emit=lambda event, **kw: log.emit(event, fold=fold.fold_id, model=chosen, seed=seed, **kw),
                        compile_mode=config["compile_mode"], inference={"validation_bridge": adapt(base_full, spec)})
                    log.emit("fit_finished", fold=fold.fold_id, model=chosen, seed=seed, **receipt)
                    if receipt["status"] != "complete":
                        stop.set()
                        break
                    fits_completed += 1
                    future = diagnostics.submit(report_job, data, panel, beta, scales, job, seed, spec.parameters)
                    futures.append(future)
                    log.update(fits_completed=fits_completed)
            selected_jobs[fold.fold_id] = (chosen, specs.get(chosen), scales)
            all_records[fold.fold_id] = records
            write_json(fold_out / "screening-diagnostics.json", records)
            del base_train, base_validation, base_full
        # Do not open outer test predictions/metrics unless the entire declared selection stage finished.
        if len(selected_jobs) == len(folds) and not expired() and not summary["failures"]:
            for future in futures:
                future.result()
            write_json(out / "selection-freeze.json", GUARDS | {"selections": summary["selections"],
                "fits_completed": fits_completed, "fit_limit": config["max_fits"], "test_not_used": True, "frozen_at": utc_now()})
            log.emit("outer_test_unsealed", selection_sha256=sha256(out / "selection-freeze.json"))
            summary["outer_test_status"] = "evaluating"
            log.update(status="outer_test", outer_test_status="evaluating")
            summary["outer_test"] = evaluate_test(data, panel, beta, folds, selected_jobs, out, config, expired, log)
            summary["outer_test_status"] = summary["outer_test"]["status"]
            summary["status"] = "complete" if not expired() and summary["outer_test_status"] == "complete" else "budget_stopped"
            write_json(out / "family-review.json", GUARDS | {"families": ["E3", "E4", "E5"],
                "validation_selections": summary["selections"], "outer_test_status": summary["outer_test_status"],
                "next_stage_authorized": False, "A_P_R_F_gates": "require_separate_review_of_reports",
                "no_automatic_new_trials": True, "DSR_PBO": "not_identifiable_from_seven_overlapping_annual_folds"})
        elif expired():
            summary["status"] = "budget_stopped"
        else:
            summary["status"] = "incomplete_failed_fits"
    except Exception as exc:
        summary["status"] = "failed"
        summary["error"] = f"{type(exc).__name__}: {exc}"
        (out / "failure-traceback.txt").write_text(traceback.format_exc())
        log.emit("run_failed", error=summary["error"])
    finally:
        diagnostics.shutdown(wait=True, cancel_futures=True)
        monitor_stop.set()
        thread.join(timeout=6)
        for sig, handler in signal_handlers.items():
            signal.signal(sig, handler)
        summary.update(fits_started=fits_started, fits_completed=fits_completed,
                       seconds=time.monotonic() - begun, finished_at=utc_now())
        log.update(status=summary["status"], outer_test_status=summary["outer_test_status"],
                   fits_started=fits_started, fits_completed=fits_completed, error=summary.get("error"))
        write_json(out / "summary.json", summary)
        log.emit("run_finished", status=summary["status"], fits_completed=fits_completed,
                 seconds=summary["seconds"], outer_test_status=summary["outer_test_status"])
        log.close()
        finish_manifest(out, schema="etf-alpha-overnight-results-v1", status=summary["status"],
                        training_start_authorized=True, result_status="research_diagnostics", started_at=summary["started_at"])
    return summary


def evaluate_test(data, panel, beta, folds, chosen_jobs, out, config, expired, log):
    states, curves, reports = {}, [], {}
    first = int(folds[0].test_rows[0])
    for fold in folds:
        if expired():
            return {"status": "budget_stopped", "folds": reports}
        chosen, spec, scales = chosen_jobs[fold.fold_id]
        part = predict_partition(data, fold.test_rows)
        if chosen == "E3-ridge-raw":
            with np.load(out / "prepared" / fold.fold_id / chosen / "model.npz") as saved:
                mu = scales.inverse("mu20", part.assets @ saved["coefficients"] + saved["intercept"])
            predictions = {"mu20": mu}
        else:
            tp = adapt(TensorPartition.from_partition(part, "cuda"), spec)
            seed_preds = []
            for seed in config["seeds"] + config["final_seeds"]:
                model = SharedPredictor(spec).cuda()
                checkpoint = torch.load(out / fold.fold_id / chosen / f"seed_{seed}" / "best.pt", map_location="cuda", weights_only=True)
                model.load_state_dict(checkpoint["model"], strict=True)
                seed_preds.append(inverse_predictions(_prediction(model, model.forward, tp), scales))
            # The registered ensemble uses the original five screening seeds.
            predictions = {k: np.mean([p[k] for p in seed_preds[:5]], axis=0) for k in spec.heads}
            for seed, pred in zip(config["seeds"] + config["final_seeds"], seed_preds):
                np.savez_compressed(out / fold.fold_id / chosen / f"seed_{seed}" / "test.npz", rows=part.rows, **pred)
        fold_out = out / fold.fold_id
        np.savez_compressed(fold_out / "test-ensemble.npz", rows=part.rows, **predictions)
        report, series = prediction_report(data, part.rows, predictions, scales, panel, beta)
        bridge, curve, states = bridge_report(panel, part.rows, predictions["mu20"], state_by_cost=states, anchor=first)
        np.savez_compressed(fold_out / "test-ic.npz", **series)
        np.savez_compressed(fold_out / "test-curve.npz", **curve)
        record = GUARDS | {"fold": fold.fold_id, "model": chosen, "prediction": report, "bridge": bridge,
                           "continuous_state": True, "partial_year": fold.fold_id == "WF2026"}
        write_json(fold_out / "test-report.json", record)
        reports[fold.fold_id] = record
        curves.append(curve)
        log.emit("test_fold_complete", fold=fold.fold_id, model=chosen, bridge=bridge,
                 rank_ic=report["rank_ic"], huber=report["mu20_huber"])
    combined = {key: np.concatenate([c[key] if i == 0 else c[key][1:] for i, c in enumerate(curves)]) for key in curves[0]}
    np.savez_compressed(out / "continuous-test-curve.npz", **combined)
    totals = {}
    for multiplier in (1, 2, 3):
        r = combined[f"returns_{multiplier}x"][1:]
        equity = combined[f"equity_{multiplier}x"]
        cash_r = panel.cash_close[combined["rows"][1:]] / panel.cash_close[combined["rows"][1:] - 1] - 1
        excess = r - cash_r
        annual = {}
        dates = np.asarray(data.dates)[combined["rows"]][1:]
        for year in sorted({d[:4] for d in dates}):
            yr = r[np.char.startswith(dates, year)]
            annual[year] = {"return": float(np.prod(1 + yr) - 1), "days": len(yr), "partial": year == "2026"}
        full_years = {y: v for y, v in annual.items() if not v["partial"]}
        best_year = max(full_years, key=lambda y: full_years[y]["return"])
        dropped = r[~np.char.startswith(dates, best_year)]
        from qount.research.etf_trader.env import max_drawdown
        totals[f"{multiplier}x"] = {"cagr": float((equity[-1] / equity[0]) ** (252 / len(r)) - 1),
            "sharpe_excess_cash": float(excess.mean() / excess.std(ddof=1) * np.sqrt(252)),
            "max_drawdown": max_drawdown(equity), "annual": annual,
            "drop_best_complete_year": {"year": best_year, "cagr": float(np.prod(1 + dropped) ** (252 / len(dropped)) - 1)},
            "excess_daily_mean_intervals": {str(b): block_interval(excess, block=b) for b in (40, 60, 120)}}
    return {"status": "complete", "folds": reports, "continuous": totals,
            "holdout_role": "discovery", "production_effect": False, "fresh_confirmation": "insufficient"}
