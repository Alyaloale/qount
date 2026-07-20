"""Content manifests for qount data migration and external storage."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_tree_manifest(root: Path, *, source_node: str) -> dict[str, Any]:
    target = root.expanduser().resolve()
    if not target.is_dir():
        raise ValueError(f"manifest root is not a directory: {target}")

    records = []
    total_bytes = 0
    for current_root, directory_names, file_names in os.walk(target, followlinks=False):
        directory_names.sort()
        file_names.sort()
        current = Path(current_root)
        for filename in file_names:
            path = current / filename
            relative = path.relative_to(target).as_posix()
            if path.is_symlink():
                records.append(
                    {
                        "path": relative,
                        "kind": "symlink",
                        "target": os.readlink(path),
                    }
                )
                continue
            size = path.stat().st_size
            total_bytes += size
            records.append(
                {
                    "path": relative,
                    "kind": "file",
                    "size": size,
                    "sha256": _sha256_file(path),
                }
            )

    content_hash = _canonical_hash(records)
    return {
        "schema_version": "qount_storage_tree_manifest_v1",
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "source_node": source_node,
        "root": str(target),
        "file_count": sum(record["kind"] == "file" for record in records),
        "symlink_count": sum(record["kind"] == "symlink" for record in records),
        "total_bytes": total_bytes,
        "content_hash": content_hash,
        "records": records,
    }


def write_tree_manifest(payload: dict[str, Any], output_path: Path) -> Path:
    target = output_path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return target
