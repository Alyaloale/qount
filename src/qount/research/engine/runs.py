"""Isolated, atomic offline results and content-based reuse; no job service."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import sys
from pathlib import Path


def _encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":"), allow_nan=False) + "\n").encode()


def _logical_path(path):
    parts = Path(path).parts
    for marker in ("src", "scripts", "config", "state"):
        if marker in parts:
            return Path(*parts[parts.index(marker):]).as_posix()
    return Path(path).name


def run_identity(line_id, parameters, inputs, code_files):
    if not re.fullmatch(r"[a-z0-9_]+", line_id):
        raise ValueError("invalid_research_line_id")
    code = sorted([dict(path=_logical_path(p), sha256=hashlib.sha256(Path(p).read_bytes()).hexdigest())
                   for p in set(map(Path, code_files))], key=lambda r:r["path"])
    content = sorted({(r.get("logical_name", Path(r["path"]).name), r["sha256"])
                      for r in inputs})
    runtime = {"python": f"{sys.version_info.major}.{sys.version_info.minor}"}
    identity = dict(line_id=line_id, parameters=parameters, inputs=inputs, code=code, runtime=runtime)
    digest = hashlib.sha256(_encoded(dict(line_id=line_id, parameters=parameters,
                                         inputs=content, code=code, runtime=runtime))).hexdigest()
    return digest, identity


def cached_run(path, digest):
    path = Path(path)
    if not path.exists():
        return None
    summary = json.loads((path/"summary.json").read_text())
    if summary["run_id"] != digest:
        raise ValueError("existing_run_has_different_inputs")
    if set(summary["output_hashes"]) != {"nav.json", "trades.json"}:
        raise ValueError("cached_result_changed_or_incomplete")
    for name, expected in summary["output_hashes"].items():
        if name not in {"nav.json", "trades.json"} or hashlib.sha256((path/name).read_bytes()).hexdigest() != expected:
            raise ValueError("cached_result_changed_or_incomplete")
    return summary


def save_run(path, digest, identity, result):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".writing-", dir=path.parent) as folder:
        staging = Path(folder)
        hashes = {}
        for name, key in (("nav.json", "nav"), ("trades.json", "trades")):
            raw = _encoded(result[key])
            (staging / name).write_bytes(raw)
            hashes[name] = hashlib.sha256(raw).hexdigest()
        summary = {**result["summary"], **identity, "run_id": digest, "output_hashes": hashes,
                   "research_only": True, "orders_authorized": False}
        (staging / "summary.json").write_bytes(_encoded(summary))
        if path.exists():
            return cached_run(path, digest)
        try:
            os.rename(staging, path)
        except OSError:
            if path.exists():
                return cached_run(path, digest)
            raise
    return summary


def cached_features(name, parameters, inputs, code_files, build, root):
    """Reuse JSON-compatible features independently of trading parameters."""
    digest, identity = run_identity(name, parameters, inputs, code_files)
    path = Path(root) / name / (digest + ".json")
    if not path.exists():
        value = build()
        payload = dict(identity=identity, run_id=digest, value=value,
                       value_sha256=hashlib.sha256(_encoded(value)).hexdigest())
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(_encoded(payload))
        try:
            os.link(temporary, path)
        except FileExistsError:
            pass
        finally:
            temporary.unlink()
    payload = json.loads(path.read_text())
    if payload["run_id"] != digest or hashlib.sha256(_encoded(payload["value"])).hexdigest() != payload["value_sha256"]:
        raise ValueError("cached_features_changed")
    return payload["value"]
