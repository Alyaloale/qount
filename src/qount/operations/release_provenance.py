"""Build and verify the file-level provenance manifest for a VPS release."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import tomllib
from pathlib import Path
from typing import Any, Iterable, Mapping

from qount.models import utc_now


RELEASE_PROVENANCE_SCHEMA_VERSION = "qount_release_provenance_v0.1"
RELEASE_PROVENANCE_ARTIFACT_TYPE = "qount_release_provenance"
RELEASE_PROVENANCE_VERIFICATION_TYPE = "qount_release_provenance_verification"
DEFAULT_RELEASE_PATHS = (
    "README.md",
    "pyproject.toml",
    "deploy",
    "docs",
    "prompts",
    "scripts",
    "src/qount",
    "tests",
    "web",
)
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class ReleaseProvenanceError(ValueError):
    """Raised when a release manifest cannot prove the deployed source tree."""


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _release_version(repo_root: Path) -> str:
    with (repo_root / "pyproject.toml").open("rb") as handle:
        parsed = tomllib.load(handle)
    version = (parsed.get("project") or {}).get("version")
    if not isinstance(version, str) or not version:
        raise ReleaseProvenanceError("release_version_missing")
    return version


def _release_files(
    repo_root: Path, include_paths: Iterable[str] = DEFAULT_RELEASE_PATHS
) -> dict[str, str]:
    files: dict[str, str] = {}
    for relative in include_paths:
        target = repo_root / relative
        if not target.exists():
            raise ReleaseProvenanceError(f"release_path_missing:{relative}")
        candidates = (target,) if target.is_file() else sorted(target.rglob("*"))
        for candidate in candidates:
            if not candidate.is_file():
                continue
            if "__pycache__" in candidate.parts or candidate.suffix == ".pyc":
                continue
            if candidate.name == ".DS_Store":
                continue
            files[candidate.relative_to(repo_root).as_posix()] = _sha256(candidate)
    if not files:
        raise ReleaseProvenanceError("release_file_set_empty")
    return dict(sorted(files.items()))


def build_release_provenance(
    repo_root: str | os.PathLike[str],
    *,
    git_commit: str,
    include_paths: Iterable[str] = DEFAULT_RELEASE_PATHS,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    commit = git_commit.lower()
    if not _COMMIT_RE.fullmatch(commit):
        raise ReleaseProvenanceError("release_commit_invalid")
    files = _release_files(root, include_paths)
    core = {
        "schema_version": RELEASE_PROVENANCE_SCHEMA_VERSION,
        "artifact_type": RELEASE_PROVENANCE_ARTIFACT_TYPE,
        "created_at": utc_now().isoformat(),
        "git_commit": commit,
        "version": _release_version(root),
        "files": files,
        "source_tree_hash": _canonical_hash({"files": files}),
    }
    return core | {"provenance_hash": _canonical_hash(core)}


def write_release_provenance(
    path: str | os.PathLike[str], payload: Mapping[str, Any]
) -> Path:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"))
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="ascii", dir=target.parent, delete=False
    ) as handle:
        handle.write(encoded + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
    return target


def verify_release_provenance(
    repo_root: str | os.PathLike[str], payload: Mapping[str, Any]
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    provenance = dict(payload)
    required = {
        "schema_version",
        "artifact_type",
        "created_at",
        "git_commit",
        "version",
        "files",
        "source_tree_hash",
        "provenance_hash",
    }
    if set(provenance) != required:
        raise ReleaseProvenanceError("release_provenance_schema_invalid")
    core = {key: value for key, value in provenance.items() if key != "provenance_hash"}
    if provenance["schema_version"] != RELEASE_PROVENANCE_SCHEMA_VERSION:
        raise ReleaseProvenanceError("release_provenance_version_invalid")
    if provenance["artifact_type"] != RELEASE_PROVENANCE_ARTIFACT_TYPE:
        raise ReleaseProvenanceError("release_provenance_type_invalid")
    if not _COMMIT_RE.fullmatch(str(provenance["git_commit"])):
        raise ReleaseProvenanceError("release_provenance_commit_invalid")
    if provenance["provenance_hash"] != _canonical_hash(core):
        raise ReleaseProvenanceError("release_provenance_hash_invalid")
    expected_files = provenance["files"]
    if not isinstance(expected_files, dict) or not all(
        isinstance(path, str) and isinstance(value, str) and _SHA256_RE.fullmatch(value)
        for path, value in expected_files.items()
    ):
        raise ReleaseProvenanceError("release_provenance_file_hashes_invalid")
    actual_files = _release_files(root, tuple(DEFAULT_RELEASE_PATHS))
    if actual_files != expected_files:
        raise ReleaseProvenanceError("release_source_tree_mismatch")
    expected_tree_hash = _canonical_hash({"files": actual_files})
    if provenance["source_tree_hash"] != expected_tree_hash:
        raise ReleaseProvenanceError("release_source_tree_hash_invalid")
    if provenance["version"] != _release_version(root):
        raise ReleaseProvenanceError("release_version_mismatch")
    return {
        "git_commit": provenance["git_commit"],
        "version": provenance["version"],
        "source_tree_hash": provenance["source_tree_hash"],
        "provenance_hash": provenance["provenance_hash"],
    }


def build_release_provenance_verification(
    repo_root: str | os.PathLike[str], payload: Mapping[str, Any]
) -> dict[str, Any]:
    verified = verify_release_provenance(repo_root, payload)
    core = {
        "schema_version": RELEASE_PROVENANCE_SCHEMA_VERSION,
        "artifact_type": RELEASE_PROVENANCE_VERIFICATION_TYPE,
        "created_at": utc_now().isoformat(),
        "meta": {"read_only": True, "orders_allowed": False},
        "provenance": verified,
        "evidence": {"verified": True},
    }
    return core | {"verification_hash": _canonical_hash(core)}
