"""Raw exchange response archiver for the shadow accountant.

Archives raw Binance USD-M responses (trades, income history, open orders)
to an immutable directory with per-file SHA-256 verification and a manifest.
Both shadow and primary ledger can read the same archived responses, each
verifying hash, pagination completeness, and parse version (section 4.3).

Import boundary: this module must NOT import qount.execution,
qount.mini_trend.pilot_dispatcher, qount.ledger, or ccxt.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from qount.shadow_accounting.contracts import FetchResult
from qount.shadow_accounting.contracts import ShadowRun


def _sha256_file(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_jsonl(
    path: Path, records: Sequence[Mapping[str, Any]]
) -> str:
    """Write records as canonical JSONL and return the file's SHA-256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="ascii") as f:
        for record in records:
            canonical = json.dumps(
                dict(record),
                ensure_ascii=True,
                sort_keys=True,
                allow_nan=False,
                separators=(",", ":"),
            )
            f.write(canonical + "\n")
    return _sha256_file(path)


def _write_canonical_json(
    path: Path, data: Mapping[str, Any]
) -> str:
    """Write canonical JSON and return the file's SHA-256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    canonical = json.dumps(
        data,
        ensure_ascii=True,
        sort_keys=True,
        allow_nan=False,
        separators=(",", ":"),
    )
    with open(path, "w", encoding="ascii") as f:
        f.write(canonical)
    return _sha256_file(path)


def archive_raw_responses(
    fetch_results: Sequence[FetchResult],
    *,
    run_dir: str | os.PathLike[str],
) -> dict[str, Any]:
    """Archive raw fetch results to ``<run_dir>/raw/`` as JSONL files.

    Returns a manifest dict mapping file names to SHA-256 hashes and
    metadata.  Raises FileExistsError if the raw directory already exists.
    """
    run_path = Path(run_dir)
    raw_dir = run_path / "raw"
    if raw_dir.exists():
        raise FileExistsError(f"shadow_archive_raw_dir_exists:{raw_dir}")
    raw_dir.mkdir(parents=True, exist_ok=False)

    manifest: dict[str, Any] = {"files": {}, "fetch_hashes": []}
    for fetch_result in fetch_results:
        file_name = f"{fetch_result.data_type}.jsonl"
        file_path = raw_dir / file_name
        file_hash = _write_jsonl(file_path, fetch_result.records)
        manifest["files"][file_name] = {
            "data_type": fetch_result.data_type,
            "record_count": len(fetch_result.records),
            "sha256": file_hash,
            "fetch_hash": fetch_result.fetch_hash,
        }
        manifest["fetch_hashes"].append(fetch_result.fetch_hash)

    manifest_path = run_path / "archive_manifest.json"
    _write_canonical_json(manifest_path, manifest)
    return manifest


def archive_shadow_run(
    shadow_run: ShadowRun,
    *,
    run_dir: str | os.PathLike[str],
) -> str:
    """Archive a ShadowRun summary as ``shadow_run.json``.

    Returns the SHA-256 of the written file.
    """
    run_path = Path(run_dir)
    run_json = {
        "run_id": shadow_run.run_id,
        "observed_at": shadow_run.observed_at,
        "venue": shadow_run.venue,
        "symbols": list(shadow_run.symbols),
        "fetch_hashes": list(shadow_run.fetch_hashes),
        "position_hashes": list(shadow_run.position_hashes),
        "nav_hash": shadow_run.nav_hash,
        "coverage_window_hash": shadow_run.coverage_window_hash,
        "unknown_income_count": shadow_run.unknown_income_count,
        "diff_hashes": list(shadow_run.diff_hashes),
        "has_blocking_diff": shadow_run.has_blocking_diff,
        "watermark_hash": shadow_run.watermark_hash,
        "run_hash": shadow_run.run_hash,
    }
    return _write_canonical_json(run_path / "shadow_run.json", run_json)


def archive_json(
    data: Mapping[str, Any],
    *,
    file_name: str,
    run_dir: str | os.PathLike[str],
) -> str:
    """Archive an arbitrary JSON artifact in the run directory.

    Returns the SHA-256 of the written file.
    """
    run_path = Path(run_dir)
    return _write_canonical_json(run_path / file_name, data)


def verify_archive(
    run_dir: str | os.PathLike[str],
) -> dict[str, Any]:
    """Verify an archived run directory.

    Re-reads all raw files, recomputes SHA-256, and checks against
    the manifest.  Raises ValueError on any mismatch or missing file.
    """
    run_path = Path(run_dir)
    manifest_path = run_path / "archive_manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"shadow_archive_manifest_missing:{manifest_path}")

    with open(manifest_path, "r", encoding="ascii") as f:
        manifest = json.load(f)

    raw_dir = run_path / "raw"
    for file_name, expected in manifest["files"].items():
        file_path = raw_dir / file_name
        if not file_path.is_file():
            raise ValueError(f"shadow_archive_file_missing:{file_name}")
        actual_hash = _sha256_file(file_path)
        if actual_hash != expected["sha256"]:
            raise ValueError(
                f"shadow_archive_hash_mismatch:{file_name}"
            )

    return manifest
