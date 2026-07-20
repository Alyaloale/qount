#!/usr/bin/env python3
"""Download immutable Binance TradFi archives directly and run weekend convergence."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.grid.data import load_funding, load_klines  # noqa: E402
from qount.l1_cross_asset import normalize_tiingo_eod  # noqa: E402
from qount.mini_trend.tradifi_weekend import TRADIFI_LISTING_MONTHS  # noqa: E402
from qount.mini_trend.tradifi_weekend import (  # noqa: E402
    TradifiWeekendConfig,
    build_tradifi_weekend_report,
    write_tradifi_weekend_artifact,
)
from qount.settings import Settings  # noqa: E402


def _direct_fetch(url: str) -> bytes:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, headers={"User-Agent": "qount-tradifi-research/1.0"})
    with opener.open(request, timeout=30) as response:
        return response.read()


def _offline_fetch(url: str) -> bytes:
    raise RuntimeError(f"offline cache miss: {url.rsplit('/', 1)[-1]}")


def _cash_dates(path: str | Path) -> list[str]:
    raw = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    points = normalize_tiingo_eod(raw)
    import datetime as dt

    return [
        dt.datetime.fromtimestamp(point.timestamp_ms / 1000, dt.UTC).date().isoformat()
        for point in points
    ]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--spy-path", required=True)
    parser.add_argument("--end-month", default="2026-06")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--output-path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    end = tuple(int(value) for value in args.end_month.split("-", 1))
    fetch = _offline_fetch if args.offline else _direct_fetch
    bars = {
        symbol: load_klines(
            symbol,
            "1h",
            start=start,
            end=end,
            market="um",
            cache_dir=args.cache_dir,
            fetch=fetch,
            skip_missing=True,
        )
        for symbol, start in TRADIFI_LISTING_MONTHS.items()
    }
    funding = {
        symbol: load_funding(
            symbol,
            start=start,
            end=end,
            cache_dir=args.cache_dir,
            fetch=fetch,
            skip_missing=True,
        )
        for symbol, start in TRADIFI_LISTING_MONTHS.items()
    }
    payload = build_tradifi_weekend_report(
        bars,
        funding,
        _cash_dates(args.spy_path),
        TradifiWeekendConfig(end_month=end),
    )
    artifact = write_tradifi_weekend_artifact(
        Settings.from_env(),
        payload,
        explicit_path=args.output_path,
    )
    pooled = artifact["pooled"]
    print(f"artifact={artifact['artifact_path']}")
    print(f"pooled_symbol_events={pooled['symbol_event_count']}")
    print(f"pooled_event_dates={pooled['event_date_count']}")
    print(f"weekend_cash_correlation={pooled['weekend_cash_return_correlation']}")
    print(f"opposite_sign_rate={pooled['opposite_sign_reversion_rate']}")
    print(f"long_discount_trades={pooled['long_discount_symbol_trade_count']}")
    print(f"long_discount_return={pooled['portfolio_compound_return_pct']}%")
    print(f"long_discount_bootstrap={pooled['portfolio_date_clustered_bootstrap']}")
    print("paper_or_live_allowed=False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
