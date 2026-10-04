"""Immutable public research artifacts; never load an environment or credentials."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

EXTERNAL_ROOT = Path("/mnt/e/qount_data/qount")
GUARDS = {"research_only": True, "orders_authorized": False, "holdout_role": "discovery"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def safe_member(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe manifest member: {relative}")
    resolved = (root / path).resolve()
    resolved.relative_to(root.resolve())
    return resolved


def verify_files(root: Path, files: dict) -> dict:
    """Read every declared byte; missing files or mismatches fail closed."""
    checked = {}
    for relative, entry in files.items():
        expected = entry["sha256"] if isinstance(entry, dict) else entry
        actual = sha256(safe_member(root, relative))
        if actual != expected:
            raise ValueError(f"hash mismatch: {relative}")
        checked[relative] = actual
    return checked


def new_directory(path: Path, *, kind: str = "artifacts", external_root: Path = EXTERNAL_ROOT) -> None:
    if not external_root.is_dir():
        raise ValueError("external disk missing; refusing a fallback data location")
    if kind not in {"artifacts", "datasets"}:
        raise ValueError("unsupported artifact kind")
    parent = external_root.resolve() / kind / "etf_alpha_p3"
    relative = path.resolve().relative_to(parent)
    if not relative.parts:
        raise ValueError("a new run/dataset directory is required")
    path.mkdir(parents=True, exist_ok=False)


def finish_manifest(root: Path, **metadata) -> dict:
    manifest = GUARDS | metadata | {
        "created_at": utc_now(),
        "files": {str(p.relative_to(root)): sha256(p) for p in sorted(root.rglob("*"))
                  if p.is_file() and p.name != "manifest.json"},
    }
    write_json(root / "manifest.json", manifest)
    verify_files(root, manifest["files"])
    return manifest
