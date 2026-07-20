from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import urllib.parse
import urllib.request
import time
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Callable

from qount.artifacts import write_research_json_artifact
from qount.models import utc_now
from qount.settings import Settings


DERIVATIVES_STATE_VERSION = "alpha_agent_derivatives_state_v0.1"

BASE_URL = "https://fapi.binance.com"

PERIOD_MS = {
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1h": 60 * 60_000,
    "2h": 2 * 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "6h": 6 * 60 * 60_000,
    "12h": 12 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}


@dataclass(frozen=True)
class DerivativesStateConfig:
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
    period: str = "5m"
    days: int = 1
    limit: int = 500
    include_current_open_interest: bool = True
    cache_dir: str = "state/alpha_agents/binance_derivatives_state"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OpenInterestHistRow:
    symbol: str
    ts_ms: int
    sum_open_interest: float
    sum_open_interest_value: float
    cmc_circulating_supply: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TakerLongShortRow:
    symbol: str
    ts_ms: int
    buy_sell_ratio: float
    buy_vol: float
    sell_vol: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CurrentOpenInterestRow:
    symbol: str
    ts_ms: int
    open_interest: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _now_ms() -> int:
    return int(utc_now().timestamp() * 1000)


def _url(path: str, params: dict[str, Any]) -> str:
    cleaned = {key: value for key, value in params.items() if value is not None}
    return f"{BASE_URL}{path}?{urllib.parse.urlencode(cleaned)}"


def _default_fetch(url: str) -> bytes:  # pragma: no cover - network
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read()


def _cached_fetch(url: str, *, cache_dir: str, fetch: Callable[[str], bytes] | None) -> bytes:
    os.makedirs(cache_dir, exist_ok=True)
    name = hashlib.sha256(url.encode("utf-8")).hexdigest() + ".json"
    path = Path(cache_dir) / name
    if path.exists() and path.stat().st_size > 0:
        return path.read_bytes()
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            blob = (fetch or _default_fetch)(url)
            break
        except Exception as exc:  # pragma: no cover - retry path is network-dependent
            last_exc = exc
            if attempt == 2:
                raise
            time.sleep(0.5 * (attempt + 1))
    else:  # pragma: no cover
        raise last_exc or RuntimeError("fetch failed")
    path.write_bytes(blob)
    return blob


def _fetch_json(url: str, *, cache_dir: str, fetch: Callable[[str], bytes] | None) -> Any:
    return json.loads(_cached_fetch(url, cache_dir=cache_dir, fetch=fetch).decode("utf-8"))


def _window_chunks(start_ms: int, end_ms: int, *, period_ms: int, limit: int) -> list[tuple[int, int]]:
    max_span = period_ms * max(1, limit - 1)
    out: list[tuple[int, int]] = []
    current = start_ms
    while current <= end_ms:
        chunk_end = min(end_ms, current + max_span)
        out.append((current, chunk_end))
        current = chunk_end + period_ms
    return out


def _parse_open_interest_hist(symbol: str, payload: Any) -> list[OpenInterestHistRow]:
    if not isinstance(payload, list):
        raise ValueError("openInterestHist response must be a list")
    rows: list[OpenInterestHistRow] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        rows.append(
            OpenInterestHistRow(
                symbol=str(item.get("symbol") or symbol).upper(),
                ts_ms=_as_int(item.get("timestamp")),
                sum_open_interest=_as_float(item.get("sumOpenInterest")),
                sum_open_interest_value=_as_float(item.get("sumOpenInterestValue")),
                cmc_circulating_supply=(
                    None if item.get("CMCCirculatingSupply") in {None, ""} else _as_float(item.get("CMCCirculatingSupply"))
                ),
            )
        )
    return rows


def _parse_taker_long_short(symbol: str, payload: Any) -> list[TakerLongShortRow]:
    if not isinstance(payload, list):
        raise ValueError("takerlongshortRatio response must be a list")
    rows: list[TakerLongShortRow] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        rows.append(
            TakerLongShortRow(
                symbol=symbol.upper(),
                ts_ms=_as_int(item.get("timestamp")),
                buy_sell_ratio=_as_float(item.get("buySellRatio")),
                buy_vol=_as_float(item.get("buyVol")),
                sell_vol=_as_float(item.get("sellVol")),
            )
        )
    return rows


def _parse_current_open_interest(symbol: str, payload: Any) -> CurrentOpenInterestRow:
    if not isinstance(payload, dict):
        raise ValueError("openInterest response must be an object")
    return CurrentOpenInterestRow(
        symbol=str(payload.get("symbol") or symbol).upper(),
        ts_ms=_as_int(payload.get("time")),
        open_interest=_as_float(payload.get("openInterest")),
    )


def _dedup_sort(rows):
    seen = {}
    for row in rows:
        seen[(row.symbol, row.ts_ms)] = row
    return [seen[key] for key in sorted(seen)]


def fetch_open_interest_hist(
    symbol: str,
    *,
    period: str,
    start_ms: int,
    end_ms: int,
    limit: int,
    cache_dir: str,
    fetch: Callable[[str], bytes] | None = None,
) -> list[OpenInterestHistRow]:
    rows: list[OpenInterestHistRow] = []
    for start, end in _window_chunks(start_ms, end_ms, period_ms=PERIOD_MS[period], limit=limit):
        url = _url(
            "/futures/data/openInterestHist",
            {"symbol": symbol.upper(), "period": period, "startTime": start, "endTime": end, "limit": limit},
        )
        rows.extend(_parse_open_interest_hist(symbol, _fetch_json(url, cache_dir=cache_dir, fetch=fetch)))
    return _dedup_sort(rows)


def fetch_taker_long_short_ratio(
    symbol: str,
    *,
    period: str,
    start_ms: int,
    end_ms: int,
    limit: int,
    cache_dir: str,
    fetch: Callable[[str], bytes] | None = None,
) -> list[TakerLongShortRow]:
    rows: list[TakerLongShortRow] = []
    for start, end in _window_chunks(start_ms, end_ms, period_ms=PERIOD_MS[period], limit=limit):
        url = _url(
            "/futures/data/takerlongshortRatio",
            {"symbol": symbol.upper(), "period": period, "startTime": start, "endTime": end, "limit": limit},
        )
        rows.extend(_parse_taker_long_short(symbol, _fetch_json(url, cache_dir=cache_dir, fetch=fetch)))
    return _dedup_sort(rows)


def fetch_current_open_interest(
    symbol: str,
    *,
    cache_dir: str,
    fetch: Callable[[str], bytes] | None = None,
) -> CurrentOpenInterestRow:
    url = _url("/fapi/v1/openInterest", {"symbol": symbol.upper()})
    return _parse_current_open_interest(symbol, _fetch_json(url, cache_dir=cache_dir, fetch=fetch))


def _coverage(rows: list[Any], *, period_ms: int, start_ms: int, end_ms: int) -> dict[str, Any]:
    ts = sorted({row.ts_ms for row in rows if row.ts_ms > 0})
    if not ts:
        return {
            "row_count": 0,
            "first_ts": None,
            "last_ts": None,
            "expected_step_ms": period_ms,
            "gap_count": 0,
            "max_gap_ms": None,
            "coverage_ratio": 0.0,
        }
    expected = max(1, int((end_ms - start_ms) / period_ms) + 1)
    gaps = [right - left for left, right in zip(ts, ts[1:]) if right - left > period_ms * 1.5]
    return {
        "row_count": len(ts),
        "first_ts": ts[0],
        "last_ts": ts[-1],
        "expected_step_ms": period_ms,
        "gap_count": len(gaps),
        "max_gap_ms": max(gaps) if gaps else 0,
        "coverage_ratio": min(1.0, len(ts) / expected),
    }


def build_derivatives_state_dataset(
    config: DerivativesStateConfig,
    *,
    fetch: Callable[[str], bytes] | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    if config.period not in PERIOD_MS:
        raise ValueError(f"unsupported period: {config.period}")
    if config.days <= 0 or config.days > 30:
        raise ValueError("days must be in 1..30; Binance derivatives data endpoints expose only recent history")
    if config.limit <= 0 or config.limit > 500:
        raise ValueError("limit must be in 1..500")
    now = now_ms if now_ms is not None else _now_ms()
    start_ms = now - config.days * 24 * 60 * 60_000
    period_ms = PERIOD_MS[config.period]

    open_interest_rows: list[OpenInterestHistRow] = []
    taker_rows: list[TakerLongShortRow] = []
    current_rows: list[CurrentOpenInterestRow] = []
    errors: list[dict[str, str]] = []
    for symbol in config.symbols:
        normalized = symbol.upper()
        try:
            open_interest_rows.extend(
                fetch_open_interest_hist(
                    normalized,
                    period=config.period,
                    start_ms=start_ms,
                    end_ms=now,
                    limit=config.limit,
                    cache_dir=config.cache_dir,
                    fetch=fetch,
                )
            )
        except Exception as exc:
            errors.append(
                {
                    "symbol": normalized,
                    "endpoint": "openInterestHist",
                    "error": type(exc).__name__,
                    "message": str(exc)[:200],
                }
            )
        try:
            taker_rows.extend(
                fetch_taker_long_short_ratio(
                    normalized,
                    period=config.period,
                    start_ms=start_ms,
                    end_ms=now,
                    limit=config.limit,
                    cache_dir=config.cache_dir,
                    fetch=fetch,
                )
            )
        except Exception as exc:
            errors.append(
                {
                    "symbol": normalized,
                    "endpoint": "takerlongshortRatio",
                    "error": type(exc).__name__,
                    "message": str(exc)[:200],
                }
            )
        if config.include_current_open_interest:
            try:
                current_rows.append(fetch_current_open_interest(normalized, cache_dir=config.cache_dir, fetch=fetch))
            except Exception as exc:
                errors.append(
                    {
                        "symbol": normalized,
                        "endpoint": "openInterest",
                        "error": type(exc).__name__,
                        "message": str(exc)[:200],
                    }
                )

    open_interest_rows = _dedup_sort(open_interest_rows)
    taker_rows = _dedup_sort(taker_rows)
    current_rows = _dedup_sort(current_rows)
    by_symbol: dict[str, dict[str, Any]] = {}
    for symbol in config.symbols:
        normalized = symbol.upper()
        oi = [row for row in open_interest_rows if row.symbol == normalized]
        taker = [row for row in taker_rows if row.symbol == normalized]
        by_symbol[normalized] = {
            "open_interest_hist": _coverage(oi, period_ms=period_ms, start_ms=start_ms, end_ms=now),
            "taker_long_short": _coverage(taker, period_ms=period_ms, start_ms=start_ms, end_ms=now),
        }

    basis = {
        "config": config.to_dict(),
        "start_ms": start_ms,
        "end_ms": now,
        "open_interest_count": len(open_interest_rows),
        "taker_count": len(taker_rows),
        "current_open_interest_count": len(current_rows),
    }
    data_hash = hashlib.sha256(json.dumps(basis, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "schema_version": DERIVATIVES_STATE_VERSION,
        "created_at": utc_now().isoformat(),
        "meta": {
            "point_in_time": True,
            "as_of_join_required": True,
            "replayable": True,
            "official_source": "binance_usdm_futures_rest",
            "history_limit": "latest_30_days_official_limit",
            "data_hash": data_hash,
            "source_urls": {
                "open_interest_hist": "https://fapi.binance.com/futures/data/openInterestHist",
                "taker_long_short_ratio": "https://fapi.binance.com/futures/data/takerlongshortRatio",
                "current_open_interest": "https://fapi.binance.com/fapi/v1/openInterest",
            },
        },
        "config": config.to_dict(),
        "window": {
            "start_ms": start_ms,
            "end_ms": now,
            "start_utc": dt.datetime.fromtimestamp(start_ms / 1000, dt.UTC).isoformat(),
            "end_utc": dt.datetime.fromtimestamp(now / 1000, dt.UTC).isoformat(),
            "period_ms": period_ms,
        },
        "diagnostics": {
            "symbols": list(config.symbols),
            "open_interest_hist_count": len(open_interest_rows),
            "taker_long_short_count": len(taker_rows),
            "current_open_interest_count": len(current_rows),
            "errors": errors,
            "by_symbol": by_symbol,
            "promotion_note": "These endpoints are recent-history research inputs only; do not treat as multi-year backtest data.",
        },
        "open_interest_hist": [row.to_dict() for row in open_interest_rows],
        "taker_long_short": [row.to_dict() for row in taker_rows],
        "current_open_interest": [row.to_dict() for row in current_rows],
    }


def write_derivatives_state_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="alpha-agent-derivatives-state",
        path_key="artifact_path",
        default_filename="alpha_agent_derivatives_state.json",
        explicit_path=explicit_path,
    )
