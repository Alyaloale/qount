"""M0: register existing P2 evidence without retraining or historical inference."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .artifacts import (EXTERNAL_ROOT, GUARDS, finish_manifest, new_directory,
                        read_json, sha256, utc_now, verify_files, write_json)


def source_inventory(repo: Path) -> dict:
    """Only declared public code, not private configuration or environment files."""
    paths = [p for p in (repo / "src/qount/research/etf_trader").rglob("*")
             if p.suffix in {".py", ".cpp", ".h", ".json"} and "__pycache__" not in p.parts]
    paths += list((repo / "scripts/research").glob("etf_trader_*.py"))
    paths += [repo / p for p in ("src/qount/__init__.py", "src/qount/research/__init__.py", "pyproject.toml",
                                "scripts/research/3090_auto_continue.sh", "scripts/research/start_3090_optimized.sh",
                                "scripts/research/start_final_training.sh")]
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, text=True,
                          capture_output=True, check=False).stdout.strip() or "unavailable"
    return {"git_commit": head, "files": {str(p.relative_to(repo)): sha256(p)
                                         for p in sorted(paths) if p.is_file()}}


def inspect_checkpoint(path: Path) -> dict:
    # torch is optional on Mac. The authoritative tensor readback runs on WSL CPU.
    import torch
    from qount.research.etf_trader.policy import PolicyConfig, Trader

    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    config = checkpoint["config"]
    state = {k.removeprefix("_orig_mod."): v for k, v in checkpoint["model"].items()}
    if not state or not all(torch.is_tensor(v) and torch.isfinite(v).all().item() for v in state.values()):
        raise ValueError(f"invalid checkpoint tensors: {path.name}")
    model = Trader(PolicyConfig(**config["policy"]))
    model.load_state_dict(state, strict=True)
    model.eval()
    return {"sha256": sha256(path), "config": config, "seed": config["seed"],
            "saved_episode_index": checkpoint.get("episode", config.get("episodes", 0) - 1),
            "finite_tensors": True, "schema_load": "strict",
            "exact_resume_available": all(k in checkpoint for k in ("optimizer", "rng_state"))}


def _differences(expected: dict, actual: dict) -> list[dict]:
    return [{"file": p, "preserved_sha256": digest, "current_sha256": actual.get(p),
             "status": "missing" if p not in actual else "different"}
            for p, digest in expected.items() if actual.get(p) != digest]


def freeze_p2(historical: Path, provenance: Path, recovery: Path, data_root: Path,
              out: Path, repo: Path, mac_inventory: Path | None = None,
              *, external_root: Path = EXTERNAL_ROOT) -> dict:
    """Preserve a partial baseline; originals are verified again after writing."""
    inputs = {}
    for name, root, manifest_name in (
        ("historical", historical, "manifest.json"),
        ("historical_provenance", provenance, "manifest.json"),
        ("cloud_recovery", recovery, "recovery-manifest.json"),
    ):
        manifest = read_json(root / manifest_name)
        inputs[name] = {"root": str(root), "manifest": manifest_name,
                        "manifest_sha256": sha256(root / manifest_name),
                        "files": verify_files(root, manifest["files"])}
    data_manifest = read_json(data_root / "manifest.json")
    data_files = {}
    for entry in data_manifest["files"].values():
        data_files[entry["file"]] = entry["sha256"]
        data_files[entry["raw_file"]] = entry["raw_sha256"]
    inputs["dataset"] = {"root": str(data_root), "manifest": "manifest.json",
                         "manifest_sha256": sha256(data_root / "manifest.json"),
                         "files": verify_files(data_root, data_files)}
    contract = read_json(historical / "contract.json")
    results = read_json(historical / "results.json")
    verify_files(provenance, contract["code_hashes"])
    if results["contract_sha256"] != sha256(historical / "contract.json"):
        raise ValueError("historical result/contract mismatch")
    if contract["data"]["source_manifest_sha256"] != inputs["dataset"]["manifest_sha256"]:
        raise ValueError("historical dataset identity mismatch")
    current = source_inventory(repo)
    mac = read_json(mac_inventory) if mac_inventory else current
    cloud_sources = read_json(recovery / "bundle/evidence/source-manifest.json")
    verify_files(recovery / "bundle", cloud_sources)
    cloud_code = {p.removeprefix("code/"): v["sha256"] for p, v in cloud_sources.items()
                  if p.startswith("code/")}
    historical_code = {f"src/qount/research/etf_trader/{p}": h
                       for p, h in contract["code_hashes"].items()}
    diffs = {"historical_vs_wsl": _differences(historical_code, current["files"]),
             "historical_vs_mac": _differences(historical_code, mac["files"]),
             "cloud_vs_wsl": _differences(cloud_code, current["files"]),
             "cloud_vs_mac": _differences(cloud_code, mac["files"])}
    models = []
    for declared in contract["checkpoints"]:
        path = historical / "checkpoints" / f"{declared['id']}.pt"
        checked = inspect_checkpoint(path)
        if checked["sha256"] != declared["sha256"]:
            raise ValueError("historical checkpoint identity mismatch")
        stored = results["costs"]["2x"]["models"][declared["id"]]
        models.append(declared | checked | {"artifact": str(path), "evidence_role": "historical_main_control",
                      "original_2x": {k: stored[k] for k in
                                      ("cagr", "sharpe", "sharpe_excess_cash", "max_drawdown", "exploratory_gates")}})
    recovered = []
    for original in read_json(recovery / "bundle/evidence/checkpoint-validation.json"):
        path = recovery / "bundle" / original["file"]
        checked = inspect_checkpoint(path)
        if checked["sha256"] != original["sha256"]:
            raise ValueError("cloud checkpoint identity mismatch")
        recovered.append(original | checked | {"artifact": str(path), "evidence_role": "saved_training_evidence"})
    new_directory(out, external_root=external_root)
    write_json(out / "source-differences.json", GUARDS | {"differences": diffs,
               "wsl": current, "mac": mac, "cloud_preserved_files": cloud_code,
               "interpretation": "actual source hashes, not HEAD alone, define each preserved run"})
    write_json(out / "configuration-differences.json", GUARDS | {
        "models": [{k: m[k] for k in ("id", "seed", "saved_episode_index", "config")} for m in models],
        "hardware_attribution": "not_identifiable: architecture, learning rate and budget differ"})
    write_json(out / "exposure-ledger.json", GUARDS | {
        "consumed_through": contract["last"], "history_role": "already_consumed_discovery",
        "prior_model_exposures": [{"model_id": m["id"], "checkpoint_sha256": m["sha256"],
                                  "start": contract["decision_start"], "end": contract["last"],
                                  "source_contract_sha256": results["contract_sha256"]} for m in models],
        "new_alpha_trials": 0, "new_historical_model_inference": False,
        "global_trial_reconciliation": "pending; no global count invented",
        "training_duration_diagnostic": {"status": "skipped", "reason": "optional, not a dependency; M0 registers existing evidence only"}})
    report = GUARDS | {"schema": "etf-p3-p2-preservation-v1", "baseline_id": "p2-frozen-20261002",
             "registered_at": utc_now(), "completion_status": "partial", "m0_status": "completed",
             "inputs": inputs, "main_controls": models, "saved_cloud_checkpoints": recovered,
             "historical_checkpoint_count": len(models), "cloud_checkpoint_count": len(recovered),
             "original_baselines": results["costs"]["2x"]["baselines"],
             "missing_evidence": ["completed Stage B and formal final model selection",
                                  "formal P0 source/cost certification and complete two-family acceptance",
                                  "independent fresh confirmation and reconciled global trial ledger"],
             "stage_b": {"status": "stopped_partial", "latest_saved_episode_index": 60,
                         "log_progress_is_not_saved_weights": True},
             "historical_result_status": "exploratory_weak_holdout_G5_failed",
             "promotion_authorized": False}
    write_json(out / "baseline-manifest.json", report)
    for source in inputs.values():
        verify_files(Path(source["root"]), source["files"])
        if sha256(Path(source["root"]) / source["manifest"]) != source["manifest_sha256"]:
            raise ValueError("preserved manifest changed during M0")
    write_json(out / "readback.json", GUARDS | {"status": "pass", "original_inputs_unchanged": True,
               "counts": {k: len(v["files"]) for k, v in inputs.items()}})
    finish_manifest(out, milestone="M0", baseline_id=report["baseline_id"])
    return report
