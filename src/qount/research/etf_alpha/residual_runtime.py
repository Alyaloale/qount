"""Prepared R3 delivery, readiness checks and explicit owner activation receipts."""
from __future__ import annotations

from contextlib import contextmanager
import datetime as dt
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np

from .artifacts import EXTERNAL_ROOT, GUARDS, finish_manifest, new_directory, read_json, sha256, utc_now, verify_files, write_json
from .cloud_bundle import TRADER_NAMES, _archive
from .expanded_data import load_panel
from .residual_data import BASELINES, FEATURES, NEURALS, RIDGES, build_slots, prepare_slot, target_context
from .training_data import load_folds, load_training_data


def validate_contract(contract,repository):
    schema = contract.get("schema")
    if schema not in {"etf-alpha-residual-engine-v1","etf-alpha-residual-engine-v2"}:
        raise ValueError("registered residual engine schema required")
    expected = GUARDS|{"training_start_authorized":False,
        "automatic_restart_authorized":False,"training_status":"ready_waiting_owner"}
    if any(contract.get(k)!=v for k,v in expected.items()):
        raise ValueError("registered waiting-owner residual engine contract required")
    if contract["proposal_path"]!="config/etf-alpha-residual-pilot-20261003.json":
        raise ValueError("registered public proposal path required")
    proposal_path = Path(repository)/contract["proposal_path"]
    if sha256(proposal_path)!=contract["proposal_sha256"]:
        raise ValueError("residual proposal fingerprint changed")
    proposal = read_json(proposal_path)
    for key in ("data","target","models","controls","training","walk_forward","selection","budget","execution","fresh_confirmation"):
        if contract[key]!=proposal[key]:
            raise ValueError(f"runtime changes the frozen residual proposal: {key}")
    if tuple(contract["data"]["features"])!=FEATURES or contract["training"]["seeds"]!=list(range(1000,1005)):
        raise ValueError("registered features and five seeds required")
    if [m["name"] for m in contract["models"]]!=[*RIDGES,*NEURALS] or contract["budget"]["full_max_fits"]!=272 or contract["budget"]["pilot_max_fits"]!=51:
        raise ValueError("registered five-model/51-pilot/272-fit schedule required")
    engine = contract["engine"]
    if (engine["device"]!="cuda" or engine["compile"] is not False or engine["interval_samples"]!=500
        or engine["stability_samples"]!=400 or engine["decision_anchor"]!="first_2015_execution_date"
        or engine["gradient_clip_norm"]!=1 or engine["optimizer_betas"]!=[.9,.999] or engine["optimizer_epsilon"]!=1e-8
        or engine["cuda_lock"]!="/home/alyaloale/.cache/qount-compute/locks/etf-alpha-cuda.lock"
        or engine["activation_policy"]!="fresh_explicit_owner_instruction_bound_to_ready_manifest"
        or engine["environment_python"]!="/home/alyaloale/.cache/qount-compute/venvs/etf-alpha-20261003/bin/python"):
        raise ValueError("undeclared residual engine implementation options")
    if schema=="etf-alpha-residual-engine-v2" and (
        engine.get("null_minimum_shift_sessions")!=contract["target"]["horizon_sessions"]+contract["walk_forward"]["embargo_sessions"]
        or engine.get("portfolio_boundary_policy")!="continuous_close_decisions_next_open_fills"):
        raise ValueError("reviewed residual engine requires 25-session null separation and continuous boundary decisions")
    if schema=="etf-alpha-residual-engine-v2":
        review = contract.get("review",{})
        original = "config/etf-alpha-residual-ready-20261003.json"
        if (review.get("source_runtime_contract_path")!=original
            or review.get("source_runtime_contract_sha256")!=sha256(Path(repository)/original)):
            raise ValueError("reviewed residual engine must bind the unchanged historical runtime contract")
    if schema=="etf-alpha-residual-engine-v1" and engine.get("null_minimum_shift_sessions",1)!=1:
        raise ValueError("historical v1 null protocol must remain unchanged")
    return proposal


def storage_check():
    if not os.path.ismount("/mnt/e") or not EXTERNAL_ROOT.is_dir():
        raise ValueError("mounted E research storage required; no fallback location")
    free = shutil.disk_usage(EXTERNAL_ROOT).free
    if free<2*1024**3:
        raise ValueError("two GiB free research artifact reserve required")
    return {"mount":"/mnt/e","free_bytes":free}


@contextmanager
def cuda_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("a") as stream:
        try:
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("another ETF Alpha compute job holds the shared CUDA lock") from error
        try:
            yield
        finally:
            fcntl.flock(stream,fcntl.LOCK_UN)


def cuda_check(*,numerics=False):
    import torch
    if (torch.__version__.split("+")[0]!="2.13.0" or torch.version.cuda!="13.0" or np.__version__!="2.5.1"
        or not torch.cuda.is_available() or torch.cuda.device_count()!=1 or "4060" not in torch.cuda.get_device_name(0)):
        raise ValueError("isolated Torch2.13/cu130/NumPy2.5.1 and one RTX4060 required")
    torch.set_num_threads(2)
    torch.set_float32_matmul_precision("highest")
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    info = {"torch":torch.__version__,"numpy":np.__version__,"cuda":torch.version.cuda,
            "gpu":torch.cuda.get_device_name(0),"python":sys.version,"executable":sys.executable}
    if sys.executable!="/home/alyaloale/.cache/qount-compute/venvs/etf-alpha-20261003/bin/python":
        raise ValueError("registered isolated Python executable required")
    if numerics:
        from .residual_training import numerical_probe
        info["probe"] = numerical_probe("cuda")
    return info


def verify_delivery(repository):
    root = Path(repository)
    manifest = read_json(root/"delivery-manifest.json")
    verify_files(root,manifest["files"])
    if any(manifest.get(k)!=v for k,v in GUARDS.items()) or manifest.get("training_start_authorized") is not False:
        raise ValueError("paused public residual code delivery required")
    return sha256(root/"delivery-manifest.json")


def prepare_engine(contract_path,out,repository):
    contract_path,out,repository = map(Path,(contract_path,out,repository))
    config = read_json(contract_path)
    validate_contract(config,repository)
    storage = storage_check()
    deployment_hash = verify_delivery(repository)
    data_root = Path(config["data"]["root"])
    data = load_training_data(data_root,config["data"]["manifest_sha256"])
    panel = load_panel(data_root)
    original = load_folds(Path(config["engine"]["original_fold_contract"]),read_json(data_root/"dataset-contract.json"))
    context = target_context(data,panel)
    slots = build_slots(data,context[0])
    if any(not np.array_equal(s.evaluation_rows,f.test_rows) for s,f in zip([s for s in slots if s.kind=="final"],original)):
        raise ValueError("R3 outer execution dates differ from the original frozen calendar")
    new_directory(out)
    write_json(out/"runtime-contract.json",config)
    source = out/"source_snapshot"
    delivery = read_json(repository/"delivery-manifest.json")
    for relative in [*delivery["files"],"delivery-manifest.json"]:
        destination = source/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(repository/relative,destination)
    anchor = int(np.searchsorted(data.dates,"2015-01-01"))
    slot_contracts,counts,null_checks = {},{},{}
    with np.load(data_root/"features.npz",allow_pickle=False) as values:
        raw = values["raw"].copy()
    for slot in slots:
        values,transform = prepare_slot(data,panel,raw,slot,context)
        np.savez_compressed(out/f"{slot.name}.npz",**values)
        write_json(out/f"{slot.name}.json",GUARDS|slot.contract()|{"transform":transform.contract(),
            "outer_evaluation_labels_prepared":False,"preparation_only":True})
        slot_contracts[slot.name] = slot.contract()
        counts[slot.name] = {"train":len(slot.train_rows),"checkpoint":len(slot.checkpoint_rows),
                            "execution":len(slot.evaluation_rows),"evaluation_labels":len(slot.evaluation_label_rows)}
        from .residual_data import shuffled_labels
        null_checks[slot.name] = {}
        for seed in config["training"]["seeds"]:
            for strong in (False,True):
                _,_,receipt = shuffled_labels(values["train_y"],values["train_mask"],seed,asset_shuffle=strong,
                    minimum_shift=config["engine"].get("null_minimum_shift_sessions",1))
                null_checks[slot.name][f"{seed}_{'time_asset' if strong else 'time'}"] = {
                    "unchanged_date_pairs":receipt["unchanged_date_pairs"],"train_dates":len(slot.train_rows),
                    "minimum_date_shift":receipt["minimum_date_shift"],"minimum_shift_required":receipt["minimum_shift_required"]}
        print(f"prepared {slot.name}: train={len(slot.train_rows)} checkpoint={len(slot.checkpoint_rows)} execution={len(slot.evaluation_rows)}",flush=True)
    write_json(out/"derived-fold-contract.json",GUARDS|{"anchor_row":anchor,"anchor_date":data.dates[anchor],
        "horizon":20,"embargo_sessions":5,"slots":slot_contracts,
        "inner_tail_labels_known_before_next_year":True,"outer_execution_dates_match_original":True})
    write_json(out/"null-control-readiness.json",GUARDS|{"slots":null_checks,"model_fits":0})
    with cuda_lock(config["engine"]["cuda_lock"]):
        environment = cuda_check(numerics=True)
    write_json(out/"environment.json",environment)
    info = GUARDS|{"status":"ready_waiting_owner","created_at":utc_now(),"source_data":str(data_root),
        "dataset_manifest_sha256":config["data"]["manifest_sha256"],"proposal_sha256":config["proposal_sha256"],
        "runtime_contract_sha256":sha256(out/"runtime-contract.json"),"deployment_manifest_sha256":deployment_hash,
        "code_root":str(repository.resolve()),"fits_started":0,"fits_completed":0,"optimizer_steps":0,
        "ridge_fits":0,"neural_fits":0,"training_start_authorized":False,"automatic_restart_authorized":False,
        "cpu_preparation_complete":True,"cuda_numerics_passed":True,"slot_counts":counts,"storage":storage}
    write_json(out/"READY.json",info)
    finish_manifest(out,phase="residual_engine_ready_waiting_owner",no_model_fits=True)
    return info


def check_ready(ready,repository,*,gpu=True):
    ready,repository = Path(ready),Path(repository)
    storage_check()
    manifest = read_json(ready/"manifest.json")
    verify_files(ready,manifest["files"])
    info = read_json(ready/"READY.json")
    config = read_json(ready/"runtime-contract.json")
    validate_contract(config,repository)
    data_root = Path(config["data"]["root"])
    verify_files(data_root,read_json(data_root/"manifest.json")["files"])
    if (info["status"]!="ready_waiting_owner" or info["fits_started"]!=0 or info["optimizer_steps"]!=0
        or info["deployment_manifest_sha256"]!=verify_delivery(repository)
        or info["runtime_contract_sha256"]!=sha256(ready/"runtime-contract.json")
        or sha256(Path(config["data"]["root"])/"manifest.json")!=info["dataset_manifest_sha256"]):
        raise ValueError("prepared runtime, deployment or source binding changed")
    if gpu:
        with cuda_lock(config["engine"]["cuda_lock"]):
            cuda_check()
    return info|{"prepared_manifest_sha256":sha256(ready/"manifest.json"),"ready_directory":str(ready.resolve()),
                 "current_check":"passed","authorization_required":True}


def authorize(authorization,ready_info,out):
    """The deployment request contains '训练' but is not a start instruction."""
    if authorization is None:
        raise PermissionError("waiting for the later explicit owner training instruction")
    receipt = read_json(Path(authorization))
    instruction = receipt.get("owner_instruction","").strip().rstrip("!！。.")
    if receipt.get("training_start_authorized") is not True or instruction not in {"训练","开始训练","启动训练"}:
        raise PermissionError("an explicit later start instruction, not deployment or waiting text, is required")
    expected = {"decision_reference":"docs/current.md","ready_directory":ready_info["ready_directory"],
        "prepared_manifest_sha256":ready_info["prepared_manifest_sha256"],
        "runtime_contract_sha256":ready_info["runtime_contract_sha256"],
        "deployment_manifest_sha256":ready_info["deployment_manifest_sha256"],"output_directory":str(Path(out).resolve())}
    if any(receipt.get(k)!=v for k,v in expected.items()):
        raise PermissionError("owner activation does not bind this prepared code/data/run")
    issued = dt.datetime.fromisoformat(receipt["issued_at"])
    prepared = dt.datetime.fromisoformat(ready_info["created_at"])
    if issued.tzinfo is None or issued<=prepared or not receipt.get("activation_nonce"):
        raise PermissionError("fresh post-deployment activation receipt required")
    Path(out).resolve().relative_to(EXTERNAL_ROOT.resolve()/"artifacts/etf_alpha_p3")
    if Path(out).exists() or Path(out).resolve().is_relative_to(Path(ready_info["ready_directory"])):
        raise ValueError("a new independent training run directory is required")
    return receipt|{"verified_explicit_start":True}


def launch(ready,authorization,out,repository):
    if authorization is None:
        raise PermissionError("training remains stopped until the owner start instruction")
    info = check_ready(ready,repository)
    permit = authorize(authorization,info,out)
    Path(out).parent.mkdir(parents=True,exist_ok=True)
    reservation = Path(str(out)+".launch.json")
    write_json(reservation,GUARDS|{"status":"launch_reserved","created_at":utc_now(),"activation_nonce":permit["activation_nonce"]})
    script = Path(repository)/"scripts/research/etf_alpha_residual.py"
    args = [sys.executable,"-u",str(script),"run","--ready",str(ready),"--authorization",str(authorization),"--out",str(out)]
    logfile = Path(str(out)+".supervisor.log")
    environment = os.environ|{"PYTHONPATH":str(Path(repository)/"src"),"OPENBLAS_NUM_THREADS":"1","OMP_NUM_THREADS":"2"}
    with logfile.open("xb") as log:
        process = subprocess.Popen(args,stdout=log,stderr=subprocess.STDOUT,cwd=repository,env=environment,start_new_session=True)
    result = GUARDS|{"status":"launched","pid":process.pid,"output_root":str(out),"log":str(logfile),
                    "automatic_restart_authorized":False,"activation_nonce":permit["activation_nonce"]}
    write_json(Path(str(out)+".pid.json"),result)
    return result


def pack_delivery(repository,contract_path,out):
    repository,contract_path = Path(repository),Path(contract_path)
    config = read_json(contract_path)
    validate_contract(config,repository)
    relative = ["src/qount/__init__.py","src/qount/research/__init__.py","scripts/research/etf_alpha_residual.py",
        config["proposal_path"],str(contract_path.resolve().relative_to(repository.resolve())),
        "config/etf-alpha-residual-ready-20261003.json","config/etf-alpha-residual-reviewed-20261003.json",
        "tests/test_etf_alpha_residual.py","tests/test_etf_alpha_m1.py","deploy/wsl/alpha-residual/README.md"]
    relative += [str(p.relative_to(repository)) for p in sorted((repository/"src/qount/research/etf_alpha").glob("*.py"))]
    relative += [f"src/qount/research/etf_trader/{n}.py" for n in TRADER_NAMES]
    return _archive(out,{name:repository/name for name in relative},
        {"kind":"residual-engine-code-delivery","training_start_authorized":False,"proposal_sha256":config["proposal_sha256"],
         "runtime_contract_sha256":sha256(contract_path),"contains_private_environment":False})
