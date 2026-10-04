"""Cloud preparation and fixed-task orchestration, independent of WSL topology."""
from __future__ import annotations

from dataclasses import asdict
import datetime as dt
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

from .artifacts import GUARDS, new_directory, read_json, sha256, utc_now, write_json
from .compute import gpu_preflight, profile, runtime_environment, storage_preflight
from .expanded_data import BootstrapSpec


def require_compute_authorization(config):
    if config.get("training_start_authorized") is not True or any(config.get(k) != v for k, v in GUARDS.items()):
        raise ValueError("owner has stopped compute; a newly authorized research contract is required")


def _interrupted(*_):
    raise InterruptedError("owner stopped GPU calibration")


def inputs(config):
    from .training_data import load_folds, load_training_data
    root = Path(config["data_root"])
    storage = Path(profile(config)["storage_root"])
    root.resolve().relative_to(storage / "datasets/etf_alpha_p3")
    fold_path = Path(config["fold_contract"])
    fold_path.resolve().relative_to(storage / "artifacts/etf_alpha_p3")
    data = load_training_data(root, config["dataset_manifest_sha256"])
    folds = load_folds(fold_path, read_json(root / "dataset-contract.json"))
    if [f.fold_id for f in folds] != [f"WF{y}" for y in range(2020, 2027)]:
        raise ValueError("the seven frozen folds are required")
    for fold in folds:
        data.validate_fold(fold)
    return data, folds


def inspect(config, *, check_gpu=True):
    capacity = storage_preflight(config, BootstrapSpec(**config["bootstrap"]))
    result = GUARDS | {"capacity": capacity, "torch_imported_for_cpu_generation": False,
                      "inputs_ready": False, "checked_at": utc_now()}
    if (Path(config["data_root"]) / "manifest.json").is_file():
        data, folds = inputs(config)
        result.update(inputs_ready=True, real_dates=len(data.dates), folds=[f.fold_id for f in folds])
    if check_gpu:
        gpu = gpu_preflight(config)
        import numpy as np
        if gpu["torch"].split("+")[0] != "2.13.0" or gpu["cuda"] != "13.0" or np.__version__ != "2.5.1":
            raise ValueError("isolated pinned Torch2.13/cu130/NumPy2.5.1 environment required")
        result["gpu"] = gpu
    return result


def prepare(config, out):
    """A reusable CPU-only command; no CUDA/Torch dependency in the worker path."""
    from .augmentation import prepare_bootstrap
    require_compute_authorization(config)
    spec = BootstrapSpec(**config["bootstrap"])
    capacity = storage_preflight(config, spec)
    data, folds = inputs(config)
    if spec != BootstrapSpec():
        raise ValueError("registered full bootstrap specification required")
    out = Path(out)
    new_directory(out, kind="datasets", external_root=Path(profile(config)["storage_root"]))
    stopped = threading.Event()
    handlers = {s: signal.signal(s, lambda *_: stopped.set()) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        with (out / "generation-events.jsonl").open("x", buffering=1) as stream:
            def emit(event, **values):
                record = json.dumps({"time": utc_now(), "event": event, **values}, allow_nan=False)
                stream.write(record + "\n")
                print(record, flush=True)
            started = time.monotonic()
            workers = min(config["cpu_generation_workers"], capacity["effective_cpus"])
            emit("cpu_generation_started", workers=workers, spec=asdict(spec))
            # Line-buffered generation events end before immutable manifest publication.
            manifest = prepare_bootstrap(spec, Path(config["data_root"]), folds, data.dates, out, workers,
                                         expired=stopped.is_set, emit=emit)
            print(json.dumps({"status": "complete", "seconds": time.monotonic() - started,
                              "usable_dates": manifest["usable_augmented_dates"]}), flush=True)
        return manifest
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


def calibrate(config, out, repository):
    """One GPU candidate at a time; compiler hangs/errors have bounded duration."""
    from .cloud_benchmark import amortized_choice
    require_compute_authorization(config)
    runtime_environment(config)
    gpu = gpu_preflight(config)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    calibration_contract = out / "calibration-contract.json"
    write_json(calibration_contract, config)
    records = {"real": [], "bootstrap": []}
    for stage in records:
        for compiled in (False, True):
            name = f"{stage}_{'compiled' if compiled else 'eager'}"
            result_path = out / f"{name}.json"
            command = [sys.executable, str(Path(repository) / "scripts/research/etf_alpha_cloud.py"),
                       "benchmark-candidate", "--out", str(result_path)]
            command.extend(["--contract", str(calibration_contract)])
            if compiled:
                command.append("--compiled")
            if stage == "bootstrap":
                command.append("--bootstrap")
            with (out / f"{name}.log").open("x") as stream:
                child = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                handlers = {s: signal.signal(s, _interrupted)
                            for s in (signal.SIGINT, signal.SIGTERM)}
                try:
                    returncode = child.wait(timeout=180)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
                    returncode = -signal.SIGKILL
                except BaseException:
                    if child.poll() is None:
                        os.killpg(child.pid, signal.SIGTERM)
                        try:
                            child.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            os.killpg(child.pid, signal.SIGKILL)
                            child.wait()
                    raise
                finally:
                    for sig, handler in handlers.items():
                        signal.signal(sig, handler)
            record = read_json(result_path) if returncode == 0 else {
                "status": "failed", "compiled": compiled, "parity_passed": False, "returncode": returncode}
            records[stage].append(record)
            print(json.dumps({"event": "calibration_candidate", "stage": stage, **record}), flush=True)
    value = profile(config)
    real = amortized_choice(records["real"], 400)
    bootstrap = amortized_choice(records["bootstrap"], 256 * 315)
    receipt = GUARDS | {"schema": "etf-alpha-runtime-calibration-v1", "gpu": gpu, "records": records,
        "compile_real": real, "compile_bootstrap": bootstrap, "registered_batch_sizes_unchanged": True,
        "config_sha256": sha256(calibration_contract), "model_source_sha256": sha256(Path(repository) / "src/qount/research/etf_alpha/expanded_models.py"),
        "training_source_sha256": sha256(Path(repository) / "src/qount/research/etf_alpha/expanded_training.py"),
        "profile_kind": value["kind"], "checked_at": utc_now(), "market_data_used_for_calibration": False}
    write_json(out / "calibration.json", receipt)
    return receipt


def execute(config_path, *, repository, calibration, bootstrap_root=None):
    """Run exactly the registered schedule and finalize a lightweight result delivery."""
    config = read_json(Path(config_path))
    require_compute_authorization(config)
    from .cloud_bundle import collect_results
    from .expanded_run import run, validate_contract
    validate_contract(config)
    runtime_environment(config)
    inputs(config)  # Fail before creating a job or expensive model work if frozen input is missing.
    receipt = read_json(Path(calibration))
    calibration_contract = Path(calibration).parent / "calibration-contract.json"
    if sha256(calibration_contract) != receipt["config_sha256"] or read_json(calibration_contract) != config:
        raise ValueError("calibration belongs to a different fixed contract")
    source = Path(repository) / "src/qount/research/etf_alpha"
    if (any(receipt.get(k) != v for k, v in GUARDS.items()) or
        receipt.get("profile_kind") != profile(config)["kind"] or
        receipt.get("model_source_sha256") != sha256(source / "expanded_models.py") or
        receipt.get("training_source_sha256") != sha256(source / "expanded_training.py")):
        raise ValueError("runtime calibration does not match the delivered engine")
    from .cloud_benchmark import amortized_choice
    if (receipt.get("compile_real") != amortized_choice(receipt["records"]["real"], 400) or
        receipt.get("compile_bootstrap") != amortized_choice(receipt["records"]["bootstrap"], 256 * 315)):
        raise ValueError("calibration choice differs from qualified measured candidates")
    config["compute_profile"].update(compile_real=receipt["compile_real"], compile_bootstrap=receipt["compile_bootstrap"])
    value = profile(config)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    storage = Path(value["storage_root"])
    job = storage / "jobs" / f"alpha_3080ti_{stamp}"
    job.mkdir(parents=True, exist_ok=False)
    contract = job / "run-contract.json"
    config["runtime_calibration_sha256"] = sha256(Path(calibration))
    write_json(contract, config)
    write_json(job / "launch.json", GUARDS | {"pid": os.getpid(), "started_at": utc_now(),
        "automatic_restart": False, "instance_shutdown_requested": False, "max_hours": config["max_hours"]})
    out = storage / "artifacts/etf_alpha_p3" / f"cloud_3080ti_{stamp}"
    dataset = Path(bootstrap_root) if bootstrap_root is not None else storage / "datasets/etf_alpha_p3" / f"cloud_bootstrap_{stamp}"
    started = time.monotonic()
    summary = run(contract, out, dataset, repository=Path(repository), reuse_bootstrap=bootstrap_root is not None)
    delivery = storage / "deliveries" / f"{out.name}-results.tar.gz"
    delivered = collect_results(config, out, delivery)
    write_json(job / "exit.json", GUARDS | {"status": summary["status"], "finished_at": utc_now(),
        "run_root": str(out), "bootstrap_root": str(dataset), "delivery": delivered,
        "estimated_compute_cost_cny": (time.monotonic() - started) / 3600 * value["price_per_hour_cny"],
        "instance_shutdown_performed": False, "billing_continues_until_provider_shutdown": True})
    return summary
