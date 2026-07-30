#!/usr/bin/env python3
"""Seal pre-existing BTCUSDT 1d archives into a cache-only L1 benchmark input."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime
from datetime import timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from qount.contracts import canonical_hash  # noqa: E402
from qount.grid.data import parse_zip_bytes  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iso_date(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).date().isoformat()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    archives = sorted(args.archive_dir.glob("BTCUSDT-1d-*.zip"))
    if not archives:
        raise SystemExit(f"no_btc_daily_archives:{args.archive_dir}")
    output_dir = args.output_dir
    csv_path = output_dir / "BTCUSDT-1d-sealed.csv"
    manifest_path = output_dir / "BTCUSDT-1d-sealed-manifest.json"
    if csv_path.exists() or manifest_path.exists():
        raise SystemExit(f"sealed_output_already_exists:{output_dir}")

    bars_by_timestamp: dict[int, float] = {}
    archive_manifest: list[dict[str, object]] = []
    for archive in archives:
        bars = parse_zip_bytes(archive.read_bytes())
        if not bars:
            raise SystemExit(f"archive_has_no_bars:{archive}")
        for bar in bars:
            existing = bars_by_timestamp.get(bar.ts_ms)
            if existing is not None and existing != bar.close:
                raise SystemExit(f"duplicate_bar_close_conflict:{archive}:{bar.ts_ms}")
            bars_by_timestamp[bar.ts_ms] = bar.close
        archive_manifest.append({
            "path": str(archive.resolve()),
            "sha256": _sha256(archive),
            "bar_count": len(bars),
            "first_date": _iso_date(min(bar.ts_ms for bar in bars)),
            "last_date": _iso_date(max(bar.ts_ms for bar in bars)),
        })

    timestamps = sorted(bars_by_timestamp)
    if any(current - previous != 86_400_000 for previous, current in zip(timestamps, timestamps[1:])):
        raise SystemExit("btc_daily_archive_gap_detected")
    output_dir.mkdir(parents=True, exist_ok=False)
    with csv_path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("date", "close"))
        for timestamp in timestamps:
            writer.writerow((_iso_date(timestamp), f"{bars_by_timestamp[timestamp]:.8f}"))

    manifest_core = {
        "schema_version": "l1_sealed_btc_daily_cache_v0.1",
        "asset": "BTCUSDT",
        "frequency": "1d",
        "network_download_attempted": False,
        "daily_cache": {
            "path": str(csv_path.resolve()),
            "sha256": _sha256(csv_path),
            "bar_count": len(timestamps),
            "first_date": _iso_date(timestamps[0]),
            "last_date": _iso_date(timestamps[-1]),
        },
        "source_archives": archive_manifest,
    }
    manifest = {**manifest_core, "manifest_hash": canonical_hash(manifest_core)}
    with manifest_path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=True, indent=2)
        handle.write("\n")
    print(f"btc_cache={csv_path}")
    print(f"source_manifest={manifest_path}")
    print(f"manifest_hash={manifest['manifest_hash']}")
    print(f"bar_count={len(timestamps)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
