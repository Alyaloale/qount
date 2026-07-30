#!/usr/bin/env python3
"""Prepare and audit the frozen L1-S2 Tiingo cache before result disclosure.

With ``--download-missing``, only absent members of the frozen 21-ETF universe are
downloaded. Existing cache files are never refreshed or replaced. The command is
blocked on and after the re-certification embargo, and it never calculates strategy
results or produces an execution artifact.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from qount.artifacts import persistent_research_dir  # noqa: E402
from qount.contracts import canonical_hash  # noqa: E402
from qount.l1_personal_carrier_recertification import L1_S2_UNIVERSE  # noqa: E402
from qount.l1_personal_carrier_recertification import (  # noqa: E402
    assert_personal_carrier_cache_collection_window,
)
from qount.l1_personal_carrier_recertification import assert_personal_carrier_source_parity  # noqa: E402
from qount.l1_personal_carrier_recertification import audit_personal_carrier_tiingo_cache  # noqa: E402
from qount.l1_personal_carrier_recertification import validate_personal_carrier_preregistration  # noqa: E402
from qount.models import utc_now  # noqa: E402
from qount.settings import Settings  # noqa: E402


_TIINGO_EOD_URL_TEMPLATE = "https://api.tiingo.com/tiingo/daily/{ticker}/prices"
_TIINGO_START_DATE = "2010-01-01"


def _read_json(path: Path, *, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"invalid_{label}:{path}") from error
    if not isinstance(value, dict):
        raise SystemExit(f"invalid_{label}:{path}")
    return value


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument(
        "--download-missing",
        action="store_true",
        help="Fetch only missing frozen-universe files before the embargo expires.",
    )
    return parser.parse_args(argv)


def _private_dotenv_has_tiingo_key() -> bool:
    """Detect an unexported local key without returning or logging its value."""

    dotenv_path = ROOT / ".env"
    try:
        lines = dotenv_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        candidate = line.strip()
        if candidate.startswith("export "):
            candidate = candidate[7:].lstrip()
        key, separator, value = candidate.partition("=")
        if key.strip() == "QOUNT_TIINGO_API_KEY" and separator:
            return bool(value.strip().strip("'\""))
    return False


def _download_missing_cache(*, ticker: str, cache_path: Path, api_key: str) -> None:
    """Fetch one absent raw Tiingo file and publish it with no-overwrite semantics."""

    url = (
        _TIINGO_EOD_URL_TEMPLATE.format(ticker=ticker.lower())
        + f"?startDate={_TIINGO_START_DATE}&format=json&token={api_key}"
    )
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "qount-l1-personal-carrier-cache/1.0",
            "Content-Type": "application/json",
        },
    )
    try:
        # Tiingo is intentionally contacted directly.  WSL's legacy proxy
        # variables are not part of this cache-admission contract and have
        # previously made the public EOD endpoint unreachable.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
        rows = json.loads(raw)
    except (urllib.error.URLError, TimeoutError, ConnectionError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"tiingo_download_failed:{ticker}") from error
    if not isinstance(rows, list):
        raise SystemExit(f"tiingo_download_payload_invalid:{ticker}")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=cache_path.parent,
        prefix=f".{cache_path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        handle = os.fdopen(descriptor, "w", encoding="utf-8")
        descriptor = -1
        with handle:
            json.dump(rows, handle, ensure_ascii=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_path, cache_path)
        except OSError as error:
            # Windows ExFAT/DrvFS does not implement hard links.  The temporary
            # file is fully fsynced on the same directory, so a same-directory
            # rename retains atomic publication.  Recheck the target first so
            # a normal concurrent cache builder still fails closed.
            if error.errno not in {errno.EPERM, errno.EOPNOTSUPP, errno.EXDEV}:
                raise
            if cache_path.exists():
                raise FileExistsError(cache_path) from error
            os.rename(temporary_path, cache_path)
        directory_descriptor = os.open(cache_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except FileExistsError as error:
        raise SystemExit(f"tiingo_cache_race_detected:{ticker}:{cache_path}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_path.exists():
            temporary_path.unlink()


def _write_audit_artifact(
    *,
    settings: Settings,
    preregistration: dict[str, object],
    audit: dict[str, object],
    download_missing: bool,
    collection_checked_at: str | None,
) -> Path:
    core = {
        "schema_version": "l1_personal_carrier_tiingo_cache_preparation_v0.1",
        "artifact_type": "l1_personal_carrier_tiingo_cache_preparation",
        "prepared_at": utc_now().isoformat(),
        "preregistration_contract_hash": preregistration["contract_hash"],
        "collection": {
            "download_missing_requested": download_missing,
            "network_download_attempted": download_missing,
            "collection_window_checked_at": collection_checked_at,
            "start_date": _TIINGO_START_DATE,
            "existing_cache_files_refreshed": False,
        },
        "cache_audit": audit,
        "meta": {
            "research_only": True,
            "strategy_results_evaluated": False,
            "orders_authorized": False,
            "paper_or_live_allowed": False,
        },
    }
    artifact = core | {"artifact_hash": canonical_hash(core)}
    directory = persistent_research_dir(
        settings,
        "l1-personal-carrier-recertification",
        "tiingo-cache-preparation",
    )
    path = directory / "l1_personal_carrier_tiingo_cache_preparation.json"
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    preregistration = _read_json(args.preregistration, label="preregistration")
    validate_personal_carrier_preregistration(preregistration)
    try:
        assert_personal_carrier_source_parity(preregistration)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    settings = Settings.from_env()
    collection_checked_at: str | None = None

    audit = audit_personal_carrier_tiingo_cache(tiingo_cache_dir=args.cache_dir)
    if args.download_missing:
        try:
            checked_at = assert_personal_carrier_cache_collection_window(preregistration)
        except ValueError as error:
            raise SystemExit(str(error)) from error
        collection_checked_at = checked_at.isoformat()
        if audit["invalid_caches"]:
            raise SystemExit("tiingo_cache_contains_invalid_existing_file")
        if audit["missing_tickers"] and not settings.tiingo_api_key:
            if _private_dotenv_has_tiingo_key():
                raise SystemExit(
                    "QOUNT_TIINGO_API_KEY is present in .env but not exported; "
                    "run: set -a; source .env; set +a"
                )
            raise SystemExit("QOUNT_TIINGO_API_KEY is required to download missing L1 cache files")
        args.cache_dir.mkdir(parents=True, exist_ok=True)
        for ticker in audit["missing_tickers"]:
            cache_path = args.cache_dir / f"tiingo_{ticker}.json"
            _download_missing_cache(
                ticker=str(ticker),
                cache_path=cache_path,
                api_key=settings.tiingo_api_key,
            )
        audit = audit_personal_carrier_tiingo_cache(tiingo_cache_dir=args.cache_dir)

    path = _write_audit_artifact(
        settings=settings,
        preregistration=preregistration,
        audit=audit,
        download_missing=args.download_missing,
        collection_checked_at=collection_checked_at,
    )
    print(f"artifact={path}")
    print(f"cache_complete={str(audit['complete']).lower()}")
    print(f"cached_tickers={len(audit['tiingo_adjusted_close_caches'])}")
    print(f"missing_tickers={','.join(audit['missing_tickers']) or 'none'}")
    return 0 if audit["complete"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
