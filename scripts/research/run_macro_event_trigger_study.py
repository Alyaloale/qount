#!/usr/bin/env python3
"""Run the frozen CPI or NFP anchor-trigger study on public OKX BTC-USDT candles."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.artifacts import persistent_research_dir  # noqa: E402
from qount.settings import Settings  # noqa: E402
from qount.small_account.macro_event_trigger_study import HourlyCandle  # noqa: E402
from qount.small_account.macro_event_trigger_study import all_scheduled_events  # noqa: E402
from qount.small_account.macro_event_trigger_study import build_study_report  # noqa: E402
from qount.small_account.macro_event_trigger_study import scheduled_events  # noqa: E402


OKX_ENDPOINT = "https://www.okx.com/api/v5/market/history-candles"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-type", choices=("cpi", "nfp", "all"), default="all")
    parser.add_argument("--cache-path", type=Path, default=Path("state/research_cache/okx_btcusdt_1h_2024-2026.json"))
    parser.add_argument("--refresh", action="store_true", help="discard the normalized public-candle cache")
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args(argv)


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "qount-macro-event-study/0.1"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed public endpoint
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == 4:
                raise
            time.sleep(1.0 * (attempt + 1))
    raise AssertionError("unreachable")


def _as_epoch_ms(value: dt.datetime) -> int:
    return int(value.timestamp() * 1_000)


def _required_range() -> tuple[dt.datetime, dt.datetime]:
    events = all_scheduled_events()
    start = min(event.released_at for event in events) - dt.timedelta(hours=73)
    end = max(event.released_at for event in events) + dt.timedelta(hours=72)
    return start, end


def download_okx_candles(start: dt.datetime, end: dt.datetime) -> tuple[list[HourlyCandle], list[str]]:
    """Fetch bounded, contiguous pages; OKX's ``after`` cursor returns older rows."""
    # Releases occur at :30. Include the whole hourly candle that completed at
    # the release (for the causal freeze), rather than dropping it at :30.
    requested_start = start.replace(minute=0, second=0, microsecond=0)
    requested_end = end.replace(minute=0, second=0, microsecond=0)
    end_cursor = _as_epoch_ms(requested_end + dt.timedelta(hours=1))
    start_ms = _as_epoch_ms(requested_start)
    rows: dict[int, HourlyCandle] = {}
    response_hashes: list[str] = []
    cursors = list(range(end_cursor, start_ms, -(100 * 60 * 60 * 1_000)))

    def fetch_page(cursor: int) -> tuple[int, bytes]:
        query = urllib.parse.urlencode({"instId": "BTC-USDT", "bar": "1H", "after": cursor, "limit": 100})
        raw = _fetch(f"{OKX_ENDPOINT}?{query}")
        return cursor, raw

    # The public endpoint is rate-limited. Four bounded in-flight requests
    # preserve its historical source while avoiding a multi-minute serial pull.
    with ThreadPoolExecutor(max_workers=4) as executor:
        pages = list(executor.map(fetch_page, cursors))
    for cursor, raw in pages:
        response_hashes.append(hashlib.sha256(raw).hexdigest())
        payload = json.loads(raw)
        if payload.get("code") != "0" or not payload.get("data"):
            raise RuntimeError(f"OKX public candle response failed: {payload.get('code')} {payload.get('msg')}")
        page = payload["data"]
        for item in page:
            opened_ms = int(item[0])
            opened_at = dt.datetime.fromtimestamp(opened_ms / 1_000, tz=dt.timezone.utc)
            rows[opened_ms] = HourlyCandle(opened_at, float(item[1]), float(item[2]), float(item[3]), float(item[4]))
    candles = [row for opened_ms, row in sorted(rows.items()) if start_ms <= opened_ms <= _as_epoch_ms(requested_end)]
    if not candles or candles[0].opened_at > requested_start or candles[-1].opened_at < requested_end:
        raise RuntimeError("OKX public candle history does not cover the requested study range")
    return candles, response_hashes


def _load_or_download(args: argparse.Namespace) -> tuple[list[HourlyCandle], dict]:
    cache_path = args.cache_path if args.cache_path.is_absolute() else REPO / args.cache_path
    if cache_path.exists() and not args.refresh:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
        return [
            HourlyCandle(dt.datetime.fromisoformat(row["opened_at_utc"]), row["open"], row["high"], row["low"], row["close"])
            for row in raw["candles"]
        ], raw["provenance"]
    start, end = _required_range()
    candles, response_hashes = download_okx_candles(start, end)
    provenance = {
        "endpoint": OKX_ENDPOINT,
        "instrument": "BTC-USDT",
        "bar": "1H",
        "requested_start_utc": start.isoformat(),
        "requested_end_utc": end.isoformat(),
        "response_count": len(response_hashes),
        "response_sha256": response_hashes,
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"provenance": provenance, "candles": [row.as_dict() for row in candles]}, ensure_ascii=False), encoding="utf-8")
    return candles, provenance


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    candles, provenance = _load_or_download(args)
    settings = Settings.from_env()
    output_dir = args.output_dir or persistent_research_dir(settings, "macro-event-anchor-trigger-study", args.event_type)
    if not output_dir.is_absolute():
        output_dir = REPO / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    market_path = output_dir / "okx_btcusdt_1h_market_data.json"
    market_payload = {"provenance": provenance, "candles": [row.as_dict() for row in candles]}
    market_bytes = json.dumps(market_payload, ensure_ascii=False, indent=2).encode("utf-8")
    market_path.write_bytes(market_bytes)
    artifact_provenance = {
        **provenance,
        "artifact_path": str(market_path),
        "artifact_sha256": hashlib.sha256(market_bytes).hexdigest(),
    }
    types = ("cpi", "nfp") if args.event_type == "all" else (args.event_type,)
    for event_type in types:
        report = build_study_report(
            scheduled_events(event_type), candles, market_data_provenance=artifact_provenance
        )
        path = output_dir / f"{event_type}_anchor_trigger_study.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        summary = report["summary"]
        print(f"{event_type}: verdict={report['verdict']} anchors={summary['anchor_trigger_count']}/{summary['event_count']} strong={summary['strong_d0_count']}/{summary['anchor_trigger_count']} artifact={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
