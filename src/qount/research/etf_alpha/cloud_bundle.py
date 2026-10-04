"""Allowlisted, deterministic P3 deliveries; never traverse private repo state."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

from .artifacts import GUARDS, read_json, safe_member, sha256, verify_files, write_json

DATASET_ID = "m0_m1_20261002T112648Z"
DATASET_SHA256 = "bfb139712e50be05e78df4b0eb305378d37e3c8ce0cd37c15bfd8545651235bb"
INPUT_NAMES = {"panel.npz", "features.npz", "labels.npz", "dataset-contract.json", "source-manifest.json", "calendar.csv"}
TRADER_NAMES = ("__init__", "constraints", "costs", "env", "scorer", "universe", "features", "policy")
TEST_NAMES = ("test_etf_alpha_m1", "test_etf_alpha_training", "test_etf_alpha_expanded", "test_etf_alpha_cloud")


def _archive(out, members, metadata):
    """Fixed metadata makes the same public bytes produce the same gzip/tar hash."""
    out = Path(out)
    records = {}
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("xb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w|") as archive:
            for name, path in sorted(members.items()):
                safe_member(Path("/bundle"), name)
                if path.is_symlink() or not path.is_file():
                    raise ValueError(f"only regular allowlisted files may be sent: {name}")
                content = path.read_bytes()
                records[name] = hashlib.sha256(content).hexdigest()
                entry = tarfile.TarInfo(name)
                entry.size, entry.mtime, entry.mode = len(content), 0, 0o755 if path.suffix == ".sh" else 0o644
                archive.addfile(entry, io.BytesIO(content))
            content = json.dumps(GUARDS | metadata | {"files": records}, sort_keys=True, indent=2,
                                 ensure_ascii=False, allow_nan=False).encode() + b"\n"
            entry = tarfile.TarInfo("delivery-manifest.json")
            entry.size, entry.mode = len(content), 0o644
            archive.addfile(entry, io.BytesIO(content))
    verify_archive(out)
    receipt = GUARDS | metadata | {"archive": out.name, "sha256": sha256(out), "bytes": out.stat().st_size,
                                   "file_count": len(records)}
    write_json(out.with_suffix(out.suffix + ".receipt.json"), receipt)
    return receipt


def verify_archive(path):
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        names = [m.name for m in members]
        if len(names) != len(set(names)) or any(not m.isfile() for m in members):
            raise ValueError("archive requires unique regular files")
        for name in names:
            safe_member(Path("/bundle"), name)
        if "delivery-manifest.json" not in names:
            raise ValueError("delivery manifest missing")
        manifest = json.load(archive.extractfile("delivery-manifest.json"))
        if set(names) != set(manifest["files"]) | {"delivery-manifest.json"}:
            raise ValueError("archive contains undeclared or missing files")
        for name, expected in manifest["files"].items():
            digest = hashlib.sha256()
            with archive.extractfile(name) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                raise ValueError(f"delivery hash mismatch: {name}")
        for key, value in GUARDS.items():
            if manifest.get(key) != value:
                raise ValueError("delivery research guards differ")
    return manifest


def pack(repository, out):
    repository = Path(repository)
    relative = ["src/qount/__init__.py", "src/qount/research/__init__.py",
                "scripts/research/etf_alpha_expand.py", "scripts/research/etf_alpha_cloud.py",
                "config/etf-alpha-stage1-proposal-20261002.json", "config/etf-alpha-expanded-20261003.json",
                "config/etf-alpha-cloud-3080ti-20261003.json",
                "deploy/cloud/alpha-3080ti/setup.sh", "deploy/cloud/alpha-3080ti/README.md",
                "deploy/cloud/alpha-3080ti/requirements.txt"]
    relative += [str(p.relative_to(repository)) for p in sorted((repository / "src/qount/research/etf_alpha").glob("*.py"))]
    relative += [f"src/qount/research/etf_trader/{name}.py" for name in TRADER_NAMES]
    relative += [f"tests/{name}.py" for name in TEST_NAMES]
    return _archive(out, {name: repository / name for name in relative},
                    {"schema": "etf-alpha-cloud-code-delivery-v1", "dataset_included": False,
                     "dataset_manifest_sha256": DATASET_SHA256, "machine_id": "jn1f8a7n6z"})


def export_inputs(data_root, fold_contract, out):
    data_root, fold_contract = Path(data_root), Path(fold_contract)
    if sha256(data_root / "manifest.json") != DATASET_SHA256:
        raise ValueError("only the registered immutable M0/M1 dataset may be exported")
    manifest = read_json(data_root / "manifest.json")
    if set(manifest["files"]) != INPUT_NAMES:
        raise ValueError("unexpected frozen dataset members; explicit input inventory required")
    verify_files(data_root, manifest["files"])
    expected = read_json(data_root / "dataset-contract.json")["contracts"]["fold-contract.json"]
    if sha256(fold_contract) != expected:
        raise ValueError("registered frozen fold hash differs")
    members = {f"datasets/etf_alpha_p3/{DATASET_ID}/{name}": data_root / name
               for name in sorted(INPUT_NAMES | {"manifest.json"})}
    members[f"artifacts/etf_alpha_p3/{DATASET_ID}/m1/fold-contract.json"] = fold_contract
    return _archive(out, members, {"schema": "etf-alpha-cloud-input-delivery-v1",
                                   "dataset_manifest_sha256": DATASET_SHA256})


def collect_results(config, run_root, out):
    from .compute import profile
    run_root = Path(run_root)
    run_root.resolve().relative_to(Path(profile(config)["storage_root"]) / "artifacts/etf_alpha_p3")
    manifest = read_json(run_root / "manifest.json")
    verify_files(run_root, manifest["files"])
    members = {f"{run_root.name}/{name}": safe_member(run_root, name) for name in manifest["files"]}
    members[f"{run_root.name}/manifest.json"] = run_root / "manifest.json"
    for name in ("selection-freeze.json", "summary.json", "REPORT.md"):
        if manifest.get("status") == "complete" and not (run_root / name).is_file():
            raise ValueError("completed result is missing a required artifact")
    return _archive(out, members, {"schema": "etf-alpha-cloud-result-delivery-v1",
        "run_manifest_sha256": sha256(run_root / "manifest.json"), "bootstrap_included": False,
        "status": manifest.get("status"), "dataset_manifest_sha256": config["dataset_manifest_sha256"]})
