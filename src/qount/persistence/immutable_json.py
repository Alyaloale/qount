"""No-overwrite, fsync-backed storage for verified JSON artifacts."""

from __future__ import annotations

import errno
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

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


def _publish_without_hard_link(target: Path, raw: bytes) -> None:
    """Publish with ``O_EXCL`` on filesystems without hard-link support.

    DrvFS/ExFAT rejects hard links.  Creating the target itself exclusively keeps
    the important no-overwrite property: a failed or interrupted publication is
    preserved as evidence and cannot be silently replaced by a later run.
    """

    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _write_no_overwrite_bytes(target: Path, raw: bytes) -> None:
    """Publish exact bytes once, with readback verification."""

    target = _completed_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
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
        try:
            os.link(temporary, target)
        except OSError as error:
            if error.errno not in {errno.EPERM, errno.EXDEV, errno.EOPNOTSUPP}:
                raise
            _publish_without_hard_link(target, raw)
        _fsync_directory(target.parent)
        actual = target.read_bytes()
        if actual != raw:
            raise RuntimeError("immutable_artifact_readback_bytes_mismatch")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def write_immutable_artifact(path: str | Path, value: object) -> dict[str, object]:
    """Publish a verified artifact atomically without replacing an existing path."""

    target = _completed_path(Path(path))
    raw = dump_artifact(value)
    expected_type = artifact_type_for(value)
    _write_no_overwrite_bytes(target, raw)
    loaded = load_artifact(target.read_bytes(), expected_artifact_type=expected_type)
    return {
        "artifact_type": expected_type,
        "object": loaded,
        "path": str(target),
        "size_bytes": len(raw),
    }


def write_immutable_json_document(path: str | Path, value: Mapping[str, Any]) -> dict[str, object]:
    """Publish an application-validated JSON document without replacement.

    Some research contracts are JSON documents rather than runtime dataclasses.
    Their callers validate the schema and internal hashes before this function seals
    their canonical bytes with the same no-overwrite and fsync guarantees used for
    runtime artifacts.
    """

    try:
        raw = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii") + b"\n"
    except (TypeError, ValueError) as error:
        raise ValueError("immutable_json_document_not_canonical") from error
    target = _completed_path(Path(path))
    _write_no_overwrite_bytes(target, raw)
    decoded = json.loads(target.read_text(encoding="ascii"))
    if decoded != value:
        raise RuntimeError("immutable_json_document_readback_mismatch")
    return {
        "artifact_type": "json_document",
        "object": decoded,
        "path": str(target),
        "size_bytes": len(raw),
    }


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
