"""Immutable manifest-last storage for certification evidence bundles.

CertificationResult references are only useful when every referenced payload
is retained.  This module persists the complete evidence set before writing
the result manifest, so an interrupted run is never mistaken for a complete
certification.
"""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from qount.certification.contracts import CertificationResult
from qount.certification.contracts import CertificationRun
from qount.certification.contracts import REQUIRED_RESULT_MEMBERS
from qount.contracts.batch import ArtifactReference
from qount.contracts.hashing import canonical_hash
from qount.persistence import read_immutable_artifact
from qount.persistence import write_immutable_artifact


_ARTIFACT_SCHEMA_VERSION = 1
_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|secret|password|passphrase|private[_-]?key|"
    r"access[_-]?token|bearer[_-]?token|listen[_-]?key|"
    r"authorization|credential|signature)$",
    re.IGNORECASE,
)
_ALLOWED_HASH_KEYS = {
    "arm_token_hash",
    "owner_authorization_hash",
    "authorization_hash",
}


class CertificationArtifactStoreError(ValueError):
    """Raised when a certification evidence bundle is incomplete or unsafe."""


class CertificationArtifactIncompleteError(CertificationArtifactStoreError):
    """Raised when the manifest-last completion marker is absent."""


@dataclass(frozen=True)
class VerifiedCertificationBundle:
    """A complete, hash-verified certification evidence bundle."""

    directory: Path
    result: CertificationResult
    run: CertificationRun
    member_count: int
    member_payloads: Mapping[str, Mapping[str, Any]]


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii") + b"\n"


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _require_directory_mode(path: Path) -> None:
    if stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode) != 0o700:
        raise CertificationArtifactStoreError(
            "certification_artifact_directory_mode_invalid"
        )


def _require_file_mode(path: Path) -> None:
    if stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode) != 0o600:
        raise CertificationArtifactStoreError(
            "certification_artifact_file_mode_invalid:"
            f"{path.name}"
        )


def _require_completed_directory(path: Path) -> Path:
    if path.name.endswith((".tmp", ".partial")):
        raise CertificationArtifactStoreError(
            "certification_artifact_directory_temporary"
        )
    if path.is_symlink():
        raise CertificationArtifactStoreError(
            "certification_artifact_directory_symlink_forbidden"
        )
    return path


def _scan_sensitive(value: Any, *, path: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CertificationArtifactStoreError(
                    "certification_artifact_key_invalid"
                )
            if key not in _ALLOWED_HASH_KEYS and _SENSITIVE_KEY.search(key):
                raise CertificationArtifactStoreError(
                    "certification_artifact_sensitive_field:"
                    f"{path}.{key}"
                )
            _scan_sensitive(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _scan_sensitive(item, path=f"{path}[{index}]")


def _member_envelope(
    reference: ArtifactReference,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    payload_dict = dict(payload)
    _scan_sensitive(payload_dict)
    payload_hash = canonical_hash(payload_dict)
    core = {
        "artifact_schema_version": _ARTIFACT_SCHEMA_VERSION,
        "artifact_type": reference.artifact_type,
        "object_id": reference.object_id,
        "payload": payload_dict,
        "payload_hash": payload_hash,
    }
    artifact_hash = canonical_hash(core)
    if payload_hash != reference.payload_hash:
        raise CertificationArtifactStoreError(
            "certification_artifact_payload_hash_mismatch:"
            f"{reference.file_name}"
        )
    if artifact_hash != reference.artifact_hash:
        raise CertificationArtifactStoreError(
            "certification_artifact_hash_mismatch:"
            f"{reference.file_name}"
        )
    return core | {"artifact_hash": artifact_hash}


def _write_member(path: Path, envelope: Mapping[str, Any]) -> None:
    if path.name.endswith((".tmp", ".partial")):
        raise CertificationArtifactStoreError(
            "certification_artifact_path_temporary"
        )
    if path.exists():
        raise CertificationArtifactStoreError(
            "certification_artifact_member_already_exists:"
            f"{path.name}"
        )
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    raw = _canonical_bytes(envelope)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = -1
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if path.read_bytes() != raw:
        raise CertificationArtifactStoreError(
            "certification_artifact_member_readback_mismatch:"
            f"{path.name}"
        )
    _require_file_mode(path)


def _run_payload(run: CertificationRun) -> dict[str, Any]:
    return {
        "schema_version": run.schema_version,
        "run_id": run.run_id,
        "plan_id": run.plan_id,
        "certification_type": run.certification_type,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "status": run.status,
        "orders_authorized": run.orders_authorized,
        "run_hash": run.run_hash,
    }


def _metadata_payload(
    run: CertificationRun,
    result: CertificationResult,
) -> dict[str, Any]:
    core = {
        "schema_version": 1,
        "result_source_run_id": result.run_id,
        "run": _run_payload(run),
        "member_count": len(result.artifact_members),
        "member_hashes": {
            reference.file_name: reference.artifact_hash
            for reference in result.artifact_members
        },
    }
    return core | {"metadata_hash": canonical_hash(core)}


def publish_certification_bundle(
    directory: str | os.PathLike[str],
    *,
    run: CertificationRun,
    result: CertificationResult,
    member_payloads: Mapping[str, Mapping[str, Any]],
) -> VerifiedCertificationBundle:
    """Persist all referenced members, then the result manifest last."""

    target = _require_completed_directory(Path(directory))
    if target.name != result.run_id:
        raise CertificationArtifactStoreError(
            "certification_artifact_directory_run_id_mismatch"
        )
    if target.exists():
        raise CertificationArtifactStoreError(
            "certification_artifact_directory_already_exists"
        )
    references = tuple(result.artifact_members)
    expected_types = set(REQUIRED_RESULT_MEMBERS)
    reference_types = {reference.artifact_type for reference in references}
    if reference_types != expected_types or len(references) != len(expected_types):
        raise CertificationArtifactStoreError(
            "certification_artifact_result_members_not_exact"
        )
    actual_types = set(member_payloads)
    if actual_types != expected_types:
        missing = ",".join(sorted(expected_types - actual_types)) or "none"
        unexpected = ",".join(sorted(actual_types - expected_types)) or "none"
        raise CertificationArtifactStoreError(
            "certification_artifact_members_mismatch:"
            f"missing={missing}:unexpected={unexpected}"
        )
    if len({reference.file_name for reference in references}) != len(references):
        raise CertificationArtifactStoreError(
            "certification_artifact_member_file_duplicate"
        )

    envelopes = [
        (reference, _member_envelope(
            reference,
            member_payloads[reference.artifact_type],
        ))
        for reference in references
    ]
    metadata = _metadata_payload(run, result)
    _scan_sensitive(metadata)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir(mode=0o700)
    os.chmod(target, 0o700)
    _require_directory_mode(target)
    _fsync_directory(target.parent)

    try:
        for reference, envelope in envelopes:
            _write_member(target / reference.file_name, envelope)

        _write_member(target / "bundle_metadata.json", metadata)

        # The CertificationResult is the completion marker and must be last.
        write_immutable_artifact(target / "manifest.json", result)
        _fsync_directory(target)
    except Exception:
        _fsync_directory(target)
        raise
    return read_certification_bundle(target)


def read_certification_bundle(
    directory: str | os.PathLike[str],
) -> VerifiedCertificationBundle:
    """Read a complete bundle and verify every member against its manifest."""

    source = _require_completed_directory(Path(directory))
    if not source.is_dir():
        raise CertificationArtifactStoreError(
            "certification_artifact_directory_missing"
        )
    _require_directory_mode(source)
    manifest_path = source / "manifest.json"
    if manifest_path.is_symlink():
        raise CertificationArtifactStoreError(
            "certification_artifact_manifest_symlink_forbidden"
        )
    if not manifest_path.is_file():
        raise CertificationArtifactIncompleteError(
            "certification_artifact_manifest_missing"
        )
    _require_file_mode(manifest_path)
    result = read_immutable_artifact(
        manifest_path,
        expected_artifact_type="certification_result",
    )
    if not isinstance(result, CertificationResult):
        raise CertificationArtifactStoreError(
            "certification_artifact_manifest_type_invalid"
        )
    if source.name != result.run_id:
        raise CertificationArtifactStoreError(
            "certification_artifact_directory_run_id_mismatch"
        )
    expected_files = {
        "manifest.json",
        "bundle_metadata.json",
        *(reference.file_name for reference in result.artifact_members),
    }
    actual_files = {path.name for path in source.iterdir()}
    if actual_files != expected_files:
        missing = ",".join(sorted(expected_files - actual_files)) or "none"
        unexpected = ",".join(sorted(actual_files - expected_files)) or "none"
        raise CertificationArtifactIncompleteError(
            "certification_artifact_files_mismatch:"
            f"missing={missing}:unexpected={unexpected}"
        )

    run: CertificationRun | None = None
    metadata_path = source / "bundle_metadata.json"
    if metadata_path.is_symlink():
        raise CertificationArtifactStoreError(
            "certification_artifact_metadata_symlink_forbidden"
        )
    _require_file_mode(metadata_path)
    metadata = json.loads(metadata_path.read_text(encoding="ascii"))
    _scan_sensitive(metadata)
    if not isinstance(metadata, dict) or set(metadata) != {
        "schema_version",
        "result_source_run_id",
        "run",
        "member_count",
        "member_hashes",
        "metadata_hash",
    }:
        raise CertificationArtifactStoreError(
            "certification_artifact_metadata_fields_invalid"
        )
    metadata_core = {
        key: value for key, value in metadata.items() if key != "metadata_hash"
    }
    if metadata.get("metadata_hash") != canonical_hash(metadata_core):
        raise CertificationArtifactStoreError(
            "certification_artifact_metadata_hash_invalid"
        )
    run_data = metadata.get("run") if isinstance(metadata, dict) else None
    if not isinstance(run_data, dict):
        raise CertificationArtifactStoreError("certification_artifact_run_missing")
    run = CertificationRun(**run_data)
    errors = run.validate()
    if errors:
        raise CertificationArtifactStoreError(
            "certification_artifact_run_invalid:" + ",".join(errors)
        )
    if metadata.get("result_source_run_id") != result.run_id:
        raise CertificationArtifactStoreError(
            "certification_artifact_result_source_run_id_mismatch"
        )
    expected_member_hashes = {
        reference.file_name: reference.artifact_hash
        for reference in result.artifact_members
    }
    if metadata.get("member_count") != len(result.artifact_members):
        raise CertificationArtifactStoreError(
            "certification_artifact_metadata_member_count_invalid"
        )
    if metadata.get("member_hashes") != expected_member_hashes:
        raise CertificationArtifactStoreError(
            "certification_artifact_metadata_member_hashes_invalid"
        )
    expected_status = "completed" if result.completed else "halted"
    if run.status != expected_status or run.completed_at is None:
        raise CertificationArtifactStoreError(
            "certification_artifact_final_run_status_invalid"
        )

    member_payloads: dict[str, Mapping[str, Any]] = {}
    for reference in result.artifact_members:
        path = source / reference.file_name
        if path.is_symlink() or not path.is_file():
            raise CertificationArtifactStoreError(
                "certification_artifact_member_missing_or_symlink:"
                f"{reference.file_name}"
            )
        _require_file_mode(path)
        envelope = json.loads(path.read_text(encoding="ascii"))
        if not isinstance(envelope, dict):
            raise CertificationArtifactStoreError(
                "certification_artifact_member_envelope_invalid:"
                f"{reference.file_name}"
            )
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            raise CertificationArtifactStoreError(
                "certification_artifact_member_payload_invalid:"
                f"{reference.file_name}"
            )
        _scan_sensitive(payload)
        expected = _member_envelope(reference, payload)
        if envelope != expected:
            raise CertificationArtifactStoreError(
                "certification_artifact_member_tampered:"
                f"{reference.file_name}"
            )
        member_payloads[reference.artifact_type] = payload
    plan_payload = member_payloads.get("certification_plan", {})
    if (
        run.plan_id != plan_payload.get("plan_id")
        or run.certification_type != plan_payload.get("certification_type")
    ):
        raise CertificationArtifactStoreError(
            "certification_artifact_final_run_plan_mismatch"
        )
    return VerifiedCertificationBundle(
        directory=source,
        result=result,
        run=run,
        member_count=len(result.artifact_members),
        member_payloads=member_payloads,
    )
