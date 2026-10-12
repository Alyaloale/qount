"""Market data routes for local Binance klines cache."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional, Tuple
from fastapi import APIRouter, HTTPException, Query

from qount.api.schemas import (
    MarketCoverage,
    MarketKlinesBar,
    MarketKlinesResponse,
)
from qount.research_data.market_data import load_klines

router = APIRouter(prefix="/market", tags=["market"])

POSSIBLE_CACHE_DIRS = [
    "state/r0_runtime/klines",
    "state/grid_b/klines",
]


def _find_cache_dir() -> str:
    for d in POSSIBLE_CACHE_DIRS:
        if os.path.exists(d) and os.path.isdir(d):
            return d
    return POSSIBLE_CACHE_DIRS[0]


def _parse_year_month(val: Optional[str], default: Tuple[int, int]) -> Tuple[int, int]:
    if not val:
        return default
    val = val.strip()
    parts = val.split("-")
    try:
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 1
        return (year, month)
    except Exception:
        return default


@router.get("/klines", response_model=MarketKlinesResponse)
def get_klines(
    symbol: str = Query("BTCUSDT", description="Trading pair symbol"),
    interval: str = Query("1d", description="Kline interval"),
    start: Optional[str] = Query(None, description="Start date (YYYY-MM or YYYY-MM-DD)"),
    end: Optional[str] = Query(None, description="End date (YYYY-MM or YYYY-MM-DD)"),
    live: int = Query(0, description="Set to 1 to enable live fetch if authorized"),
) -> MarketKlinesResponse:
    cache_dir = _find_cache_dir()
    start_tuple = _parse_year_month(start, (2021, 1))
    end_tuple = _parse_year_month(end, (2026, 6))

    source_type = "cache"
    allow_live = os.environ.get("QOUNT_ALLOW_LIVE_FETCH") == "1"

    if live == 1 and allow_live:
        source_type = "live"
        fetch_func = None  # Uses default urllib fetch inside load_klines
    else:
        # Strict local cache only: pass dummy fetch that always raises
        def _no_remote_fetch(url: str) -> bytes:
            raise FileNotFoundError(f"Remote fetch disabled: {url}")
        fetch_func = _no_remote_fetch

    try:
        raw_bars = load_klines(
            symbol=symbol,
            interval=interval,
            start=start_tuple,
            end=end_tuple,
            cache_dir=cache_dir,
            fetch=fetch_func,
            skip_missing=True,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load klines: {str(e)}")

    market_bars = []
    months_seen = set()
    for bar in raw_bars:
        dt = datetime.fromtimestamp(bar.ts_ms / 1000, tz=timezone.utc)
        d_str = dt.strftime("%Y-%m-%d")
        months_seen.add(dt.strftime("%Y-%m"))
        market_bars.append(
            MarketKlinesBar(
                date=d_str,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
            )
        )

    # Detect gaps in expected month range
    expected_months = []
    curr_y, curr_m = start_tuple
    end_y, end_m = end_tuple
    while (curr_y < end_y) or (curr_y == end_y and curr_m <= end_m):
        expected_months.append(f"{curr_y:04d}-{curr_m:02d}")
        curr_m += 1
        if curr_m > 12:
            curr_y += 1
            curr_m = 1

    gaps = [m for m in expected_months if m not in months_seen]

    start_date = market_bars[0].date if market_bars else None
    end_date = market_bars[-1].date if market_bars else None

    return MarketKlinesResponse(
        symbol=symbol,
        interval=interval,
        source=source_type,
        bars=market_bars,
        coverage=MarketCoverage(
            start=start_date,
            end=end_date,
            gaps=gaps,
        ),
    )
