"""No-overwrite local archive for daily intelligence evidence."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from qount.contracts import canonical_hash
from qount.contracts import is_sha256

from .contracts import DailyIntelligenceReport
from .contracts import daily_intelligence_from_dict


class IntelligenceArchiveError(ValueError):
    """Raised when an intelligence archive cannot be verified."""


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("ascii")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_once(path: Path, raw: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = -1
        os.link(temporary, path)
        _fsync_directory(path.parent)
        if path.read_bytes() != raw:
            raise IntelligenceArchiveError("intelligence_archive_readback_mismatch")
    except FileExistsError as exc:
        raise IntelligenceArchiveError("intelligence_archive_target_exists") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


@dataclass(frozen=True)
class IntelligenceArchiveRecord:
    report_id: str
    report_hash: str
    report_path: str
    manifest_hash: str
    source_file_count: int
    search_file_count: int
    market_file_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "report_hash": self.report_hash,
            "report_path": self.report_path,
            "manifest_hash": self.manifest_hash,
            "source_file_count": self.source_file_count,
            "search_file_count": self.search_file_count,
            "market_file_count": self.market_file_count,
        }


def archive_daily_intelligence(
    root: str | Path,
    report: DailyIntelligenceReport,
    *,
    source_bodies: Mapping[str, bytes],
    search_bodies: Sequence[bytes],
    market_bodies: Mapping[str, bytes],
) -> IntelligenceArchiveRecord:
    report.validate()
    archive_root = Path(root).resolve()
    archive_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(archive_root, 0o700)
    reports_root = archive_root / "reports"
    reports_root.mkdir(exist_ok=True, mode=0o700)
    target = reports_root / report.report_id
    try:
        target.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise IntelligenceArchiveError("intelligence_report_already_archived") from exc

    source_rows: list[dict[str, Any]] = []
    source_dir = target / "sources"
    source_dir.mkdir(mode=0o700)
    expected_source_hashes = {row["source_hash"] for row in report.sources}
    if set(source_bodies) != expected_source_hashes:
        raise IntelligenceArchiveError("intelligence_source_body_set_mismatch")
    for source_hash, raw in sorted(source_bodies.items()):
        import hashlib

        if not is_sha256(source_hash) or hashlib.sha256(raw).hexdigest() != source_hash:
            raise IntelligenceArchiveError("intelligence_source_body_hash_mismatch")
        path = source_dir / f"{source_hash}.bin"
        _write_once(path, raw)
        source_rows.append(
            {"file_name": path.name, "sha256": source_hash, "byte_count": len(raw)}
        )

    search_rows: list[dict[str, Any]] = []
    search_dir = target / "searches"
    search_dir.mkdir(mode=0o700)
    import hashlib

    if len(search_bodies) != len(report.searches):
        raise IntelligenceArchiveError("intelligence_search_body_count_mismatch")
    for evidence, raw in zip(report.searches, search_bodies, strict=True):
        digest = hashlib.sha256(raw).hexdigest()
        if digest != evidence["response_hash"]:
            raise IntelligenceArchiveError("intelligence_search_body_hash_mismatch")
        path = search_dir / f"{digest}.json"
        if not path.exists():
            _write_once(path, raw)
        search_rows.append(
            {"file_name": path.name, "sha256": digest, "byte_count": len(raw)}
        )
    search_rows.sort(key=lambda row: row["file_name"])

    if set(market_bodies) != set(report.market_pulse["source_hashes"]):
        raise IntelligenceArchiveError("intelligence_market_body_names_mismatch")
    market_rows: list[dict[str, Any]] = []
    market_dir = target / "market"
    market_dir.mkdir(mode=0o700)
    for source_name, raw in sorted(market_bodies.items()):
        digest = hashlib.sha256(raw).hexdigest()
        if digest != report.market_pulse["source_hashes"][source_name]:
            raise IntelligenceArchiveError("intelligence_market_body_hash_mismatch")
        path = market_dir / f"{digest}.json"
        if not path.exists():
            _write_once(path, raw)
        market_rows.append(
            {
                "source_name": source_name,
                "file_name": path.name,
                "sha256": digest,
                "byte_count": len(raw),
            }
        )

    report_path = target / "report.json"
    _write_once(report_path, _canonical_bytes(report.as_dict()))
    manifest_core = {
        "schema_version": 1,
        "report_id": report.report_id,
        "report_hash": report.report_hash,
        "report_file": "report.json",
        "sources": source_rows,
        "searches": search_rows,
        "market": market_rows,
    }
    manifest = manifest_core | {"manifest_hash": canonical_hash(manifest_core)}
    _write_once(target / "manifest.json", _canonical_bytes(manifest))
    _fsync_directory(target)

    latest = archive_root / "latest"
    temporary_link = archive_root / f".latest.{report.report_id}.tmp"
    os.symlink(f"reports/{report.report_id}", temporary_link)
    os.replace(temporary_link, latest)
    _fsync_directory(archive_root)

    loaded = read_latest_daily_intelligence(archive_root)
    if loaded.report_hash != report.report_hash:
        raise IntelligenceArchiveError("intelligence_archive_report_mismatch")
    return IntelligenceArchiveRecord(
        report_id=report.report_id,
        report_hash=report.report_hash,
        report_path=str(report_path),
        manifest_hash=manifest["manifest_hash"],
        source_file_count=len(source_rows),
        search_file_count=len(search_rows),
        market_file_count=len(market_rows),
    )


def read_latest_daily_intelligence(root: str | Path) -> DailyIntelligenceReport:
    archive_root = Path(root).resolve()
    latest = archive_root / "latest"
    if not latest.is_symlink():
        raise IntelligenceArchiveError("intelligence_latest_missing")
    link = os.readlink(latest)
    if not link.startswith("reports/") or Path(link).is_absolute() or ".." in Path(link).parts:
        raise IntelligenceArchiveError("intelligence_latest_target_invalid")
    directory = (archive_root / link).resolve()
    if directory.parent != (archive_root / "reports").resolve():
        raise IntelligenceArchiveError("intelligence_latest_escape")
    report_path = directory / "report.json"
    manifest_path = directory / "manifest.json"
    if report_path.is_symlink() or manifest_path.is_symlink():
        raise IntelligenceArchiveError("intelligence_archive_symlink_rejected")
    try:
        report_raw = json.loads(report_path.read_text(encoding="ascii"))
        manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntelligenceArchiveError("intelligence_archive_json_invalid") from exc
    report = daily_intelligence_from_dict(report_raw)
    manifest_core = {key: value for key, value in manifest.items() if key != "manifest_hash"}
    if (
        set(manifest) != {
            "schema_version",
            "report_id",
            "report_hash",
            "report_file",
            "sources",
            "searches",
            "market",
            "manifest_hash",
        }
        or manifest.get("manifest_hash") != canonical_hash(manifest_core)
        or manifest.get("report_id") != report.report_id
        or manifest.get("report_hash") != report.report_hash
    ):
        raise IntelligenceArchiveError("intelligence_manifest_invalid")
    import hashlib

    if (
        {row["sha256"] for row in manifest["sources"]}
        != {row["source_hash"] for row in report.sources}
        or sorted(row["sha256"] for row in manifest["searches"])
        != sorted(row["response_hash"] for row in report.searches)
        or {
            row["source_name"]: row["sha256"] for row in manifest["market"]
        }
        != dict(report.market_pulse["source_hashes"])
    ):
        raise IntelligenceArchiveError("intelligence_manifest_evidence_mismatch")

    for subdir, rows in (
        ("sources", manifest["sources"]),
        ("searches", manifest["searches"]),
        ("market", manifest["market"]),
    ):
        for row in rows:
            path = directory / subdir / row["file_name"]
            if path.is_symlink() or not path.is_file():
                raise IntelligenceArchiveError("intelligence_evidence_missing")
            raw = path.read_bytes()
            if len(raw) != row["byte_count"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
                raise IntelligenceArchiveError("intelligence_evidence_hash_mismatch")
    return report


__all__ = [
    "IntelligenceArchiveError",
    "IntelligenceArchiveRecord",
    "archive_daily_intelligence",
    "read_latest_daily_intelligence",
]
