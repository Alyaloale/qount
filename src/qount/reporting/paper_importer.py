"""Strict read-only importer for the separately published paper program."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from typing import Any

from qount.dual_engine import PaperProgramSnapshot
from qount.dual_engine.reference_data import read_public_reference, with_public_benchmark


class PaperProgramImportError(ValueError):
    """The optional paper source is unsafe, malformed, or unverifiable."""


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        + b"\n"
    )


def read_paper_program_snapshot(root: str | Path, *, observed_at: str | None = None) -> PaperProgramSnapshot:
    """Read only ``current/paper_program_snapshot.json`` with fail-closed checks."""

    source_root = Path(root).expanduser()
    if not source_root.is_absolute() or source_root == Path("/"):
        raise PaperProgramImportError("paper_import_root_invalid")
    current = source_root / "current"
    path = current / "paper_program_snapshot.json"
    for candidate, name in (
        (source_root, "root"),
        (current, "current"),
    ):
        if candidate.is_symlink() or not candidate.is_dir():
            raise PaperProgramImportError(f"paper_import_{name}_invalid")
        if stat.S_IMODE(os.stat(candidate, follow_symlinks=False).st_mode) != 0o700:
            raise PaperProgramImportError(f"paper_import_{name}_mode_invalid")
    if path.is_symlink() or not path.is_file():
        raise PaperProgramImportError("paper_import_snapshot_invalid")
    if stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode) not in {0o600, 0o640}:
        raise PaperProgramImportError("paper_import_snapshot_mode_invalid")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PaperProgramImportError(f"paper_import_duplicate_key:{key}")
            result[key] = value
        return result

    raw = path.read_bytes()
    try:
        value = json.loads(raw, object_pairs_hook=reject_duplicates)
    except PaperProgramImportError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PaperProgramImportError("paper_import_json_invalid") from exc
    if not isinstance(value, dict) or _canonical_bytes(value) != raw:
        raise PaperProgramImportError("paper_import_not_canonical")
    try:
        snapshot = PaperProgramSnapshot.from_dict(value)
    except ValueError as exc:
        raise PaperProgramImportError(f"paper_import_contract_invalid:{exc}") from exc
    if observed_at is not None:
        try:
            reference = read_public_reference(source_root, observed_at=observed_at)
            return with_public_benchmark(snapshot, reference)
        except (OSError, ValueError, TypeError, KeyError):
            # Keep the valid accounting view; absence is visible as no benchmark.
            # Research source health independently reports missing/stale references.
            pass
    return snapshot


__all__ = ["PaperProgramImportError", "read_paper_program_snapshot"]
