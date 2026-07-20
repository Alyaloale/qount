"""No-overwrite, fsync-backed storage for verified JSON artifacts."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from qount.persistence.codec import artifact_type_for
from qount.persistence.codec import dump_artifact
from qount.persistence.codec import load_artifact


def _completed_path(path: Path) -> Path:
    if path.name.endswith((".tmp", ".partial")):
        raise ValueError("immutable_artifact_path_is_temporary")
    return path


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_immutable_artifact(path: str | Path, value: object) -> dict[str, object]:
    """Publish a verified artifact atomically without replacing an existing path."""

    target = _completed_path(Path(path))
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = dump_artifact(value)
    expected_type = artifact_type_for(value)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = -1
        os.link(temporary, target)
        _fsync_directory(target.parent)
        actual = target.read_bytes()
        if actual != raw:
            raise RuntimeError("immutable_artifact_readback_bytes_mismatch")
        loaded = load_artifact(actual, expected_artifact_type=expected_type)
        return {
            "artifact_type": expected_type,
            "object": loaded,
            "path": str(target),
            "size_bytes": len(actual),
        }
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def read_immutable_artifact(
    path: str | Path,
    *,
    expected_artifact_type: str | None = None,
) -> object:
    """Read a completed artifact and verify every envelope and object hash."""

    source = _completed_path(Path(path))
    if not source.is_file():
        raise FileNotFoundError(source)
    return load_artifact(
        source.read_bytes(),
        expected_artifact_type=expected_artifact_type,
    )
