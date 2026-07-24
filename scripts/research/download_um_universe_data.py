#!/usr/bin/env python3
"""Download UM 1d klines + fundingRate for the 7 missing LiquidTrend10 alts.

Copies SOL/XRP/ADA/LINK klines from the grid_b cache (already verified) and
downloads DOGE/AVAX/LTC klines plus all 7 alts' fundingRate from
data.binance.vision. Funding missing = fail closed (never zero-filled).

Run on WSL/Windows (direct or Liangxin Cloud proxy; never Sophie home proxy).
Mac only tests the script logic without actual downloads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from qount.grid.data import (  # noqa: E402
    download_funding_month,
    download_month,
    funding_url,
    month_url,
)

ALTS_TO_COPY = ("SOLUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT")
ALTS_TO_DOWNLOAD = ("DOGEUSDT", "AVAXUSDT", "LTCUSDT")
ALL_ALTS = ALTS_TO_COPY + ALTS_TO_DOWNLOAD
DEFAULT_KLINE_CACHE = ROOT / "state" / "r0_runtime" / "klines"
DEFAULT_FUNDING_CACHE = ROOT / "state" / "r0_runtime" / "funding"
DEFAULT_GRID_B_CACHE = ROOT / "state" / "grid_b" / "klines"


def _month(value: str) -> tuple[int, int]:
    year, month = value.split("-", 1)
    return int(year), int(month)


def _months(start: tuple[int, int], end: tuple[int, int]) -> Iterator[tuple[int, int]]:
    year, month = start
    while (year, month) <= end:
        yield year, month
        month += 1
        if month == 13:
            year += 1
            month = 1


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_existing_klines(symbols: tuple[str, ...], grid_b_cache: Path, kline_cache: Path) -> list[dict]:
    copied: list[dict] = []
    for symbol in symbols:
        for src in sorted(grid_b_cache.glob(f"um-{symbol}-1d-*.zip")):
            dst = kline_cache / src.name
            if not dst.exists():
                shutil.copy2(src, dst)
            copied.append({
                "symbol": symbol,
                "action": "copy_from_grid_b",
                "file": src.name,
                "sha256": _file_sha256(dst),
            })
    return copied


def _download_klines(symbols: tuple[str, ...], start: str, end: str, kline_cache: Path) -> list[dict]:
    downloaded: list[dict] = []
    start_m, end_m = _month(start), _month(end)
    for symbol in symbols:
        for year, month in _months(start_m, end_m):
            try:
                blob = download_month(
                    symbol, "1d", year, month, market="um",
                    cache_dir=str(kline_cache), fetch=None,
                )
                downloaded.append({
                    "symbol": symbol,
                    "action": "download_kline",
                    "year": year,
                    "month": month,
                    "bytes": len(blob),
                    "url": month_url(symbol, "1d", year, month, market="um"),
                })
            except Exception as exc:
                downloaded.append({
                    "symbol": symbol,
                    "action": "download_kline_failed",
                    "year": year,
                    "month": month,
                    "error": str(exc),
                })
    return downloaded


def _download_funding(symbols: tuple[str, ...], start: str, end: str, funding_cache: Path) -> list[dict]:
    downloaded: list[dict] = []
    start_m, end_m = _month(start), _month(end)
    for symbol in symbols:
        for year, month in _months(start_m, end_m):
            try:
                blob = download_funding_month(
                    symbol, year, month,
                    cache_dir=str(funding_cache), fetch=None,
                )
                downloaded.append({
                    "symbol": symbol,
                    "action": "download_funding",
                    "year": year,
                    "month": month,
                    "bytes": len(blob),
                    "url": funding_url(symbol, year, month),
                })
            except Exception as exc:
                downloaded.append({
                    "symbol": symbol,
                    "action": "download_funding_failed",
                    "year": year,
                    "month": month,
                    "error": str(exc),
                })
    return downloaded


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kline-cache", type=Path, default=DEFAULT_KLINE_CACHE)
    parser.add_argument("--funding-cache", type=Path, default=DEFAULT_FUNDING_CACHE)
    parser.add_argument("--grid-b-cache", type=Path, default=DEFAULT_GRID_B_CACHE)
    parser.add_argument("--start-month", default="2021-01")
    parser.add_argument("--end-month", default="2026-07")
    parser.add_argument("--skip-copy", action="store_true", help="skip copying from grid_b")
    parser.add_argument("--skip-download", action="store_true", help="skip downloading (test mode)")
    parser.add_argument("--output-root", type=Path, default=ROOT / "state" / "research_runs")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    kline_cache = args.kline_cache.expanduser().resolve()
    funding_cache = args.funding_cache.expanduser().resolve()
    kline_cache.mkdir(parents=True, exist_ok=True)
    funding_cache.mkdir(parents=True, exist_ok=True)
    observed_at = datetime.now(timezone.utc).isoformat()

    log: dict = {
        "observed_at": observed_at,
        "start_month": args.start_month,
        "end_month": args.end_month,
        "orders_authorized": False,
    }

    if not args.skip_copy:
        log["copied_klines"] = _copy_existing_klines(ALTS_TO_COPY, args.grid_b_cache, kline_cache)
    if not args.skip_download:
        log["downloaded_klines"] = _download_klines(
            ALTS_TO_DOWNLOAD, args.start_month, args.end_month, kline_cache,
        )
        log["downloaded_funding"] = _download_funding(
            ALL_ALTS, args.start_month, args.end_month, funding_cache,
        )

    summary: dict[str, int] = {}
    for key in ("copied_klines", "downloaded_klines", "downloaded_funding"):
        if key in log:
            ok = sum(1 for r in log[key] if "error" not in r)
            fail = sum(1 for r in log[key] if "error" in r)
            summary[key] = {"ok": ok, "failed": fail}
    log["summary"] = summary

    ts = observed_at.replace(":", "").replace("-", "").split(".")[0]
    out_dir = args.output_root.expanduser().resolve() / f"{ts}-um-universe-download"
    out_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    artifact_path = out_dir / "um_universe_download.json"
    artifact_path.write_text(
        json.dumps(log, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps({"artifact_path": str(artifact_path), "summary": summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
