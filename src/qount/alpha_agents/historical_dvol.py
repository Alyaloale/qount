from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Callable

from qount.artifacts import write_research_json_artifact
from qount.settings import Settings

from .source_capacity import DERIBIT_DVOL_URL


HISTORICAL_DVOL_VERSION = "alpha_agent_historical_dvol_v0.1"
HOUR_MS = 3_600_000
FetchBytes = Callable[[str], bytes]


@dataclass(frozen=True)
class HistoricalDvolConfig:
    currencies: tuple[str, ...] = ("BTC", "ETH")
    start_date: str = "2021-04-01"
    end_date: str = "2024-12-31"
    resolution_seconds: int = 3_600
    cache_dir: str = "state/alpha_agents/deribit_historical_dvol"
    request_retries: int = 3
    request_timeout_seconds: float = 30.0
    min_coverage_ratio: float = 0.999

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _date_ms(raw: str) -> int:
    value = dt.datetime.combine(dt.date.fromisoformat(raw), dt.time(), tzinfo=dt.UTC)
    return int(value.timestamp() * 1000)


def _month_ranges(start: dt.date, end: dt.date) -> list[tuple[str, int, int]]:
    cursor = start.replace(day=1)
    end_exclusive = end + dt.timedelta(days=1)
    ranges: list[tuple[str, int, int]] = []
    while cursor < end_exclusive:
        if cursor.month == 12:
            next_month = cursor.replace(year=cursor.year + 1, month=1)
        else:
            next_month = cursor.replace(month=cursor.month + 1)
        chunk_start = max(cursor, start)
        chunk_end_exclusive = min(next_month, end_exclusive)
        ranges.append(
            (
                f"{cursor.year:04d}-{cursor.month:02d}",
                _date_ms(chunk_start.isoformat()),
                _date_ms(chunk_end_exclusive.isoformat()),
            )
        )
        cursor = next_month
    return ranges


def dvol_url(*, currency: str, start_ms: int, end_exclusive_ms: int) -> str:
    if end_exclusive_ms <= start_ms:
        raise ValueError("DVOL request end must follow start")
    return (
        f"{DERIBIT_DVOL_URL}?currency={currency}&start_timestamp={start_ms}"
        f"&end_timestamp={end_exclusive_ms - HOUR_MS}&resolution=3600"
    )


def _default_fetch(url: str, *, timeout_seconds: float, retries: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "qount-historical-dvol/0.1"})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return response.read()
        except urllib.error.HTTPError:
            raise
        except (OSError, TimeoutError, urllib.error.URLError):
            if attempt >= retries:
                raise
            time.sleep(0.25 * (2**attempt))
    raise AssertionError("unreachable")


def _atomic_cache(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(f"{path.name}.part")
    part.write_bytes(raw)
    os.replace(part, path)


def parse_dvol_response(
    raw: bytes,
    *,
    currency: str,
    start_ms: int,
    end_exclusive_ms: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = json.loads(raw)
    if payload.get("error") is not None:
        raise ValueError(f"Deribit DVOL API error: {payload['error']}")
    result = payload.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("data"), list):
        raise ValueError("Deribit DVOL response is missing result.data")
    if result.get("continuation") is not None:
        raise ValueError("monthly DVOL request unexpectedly requires continuation")
    rows: list[dict[str, Any]] = []
    previous_ts: int | None = None
    for line_number, source in enumerate(result["data"], start=1):
        if not isinstance(source, list) or len(source) != 5:
            raise ValueError(f"invalid DVOL OHLC schema at row {line_number}")
        try:
            ts_ms = int(source[0])
            open_value, high, low, close = (float(value) for value in source[1:])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid DVOL value at row {line_number}") from exc
        if not all(math.isfinite(value) and value >= 0 for value in (open_value, high, low, close)):
            raise ValueError(f"non-finite or negative DVOL value at row {line_number}")
        if high < max(open_value, close, low) or low > min(open_value, close, high):
            raise ValueError(f"invalid DVOL OHLC range at row {line_number}")
        if not start_ms <= ts_ms < end_exclusive_ms:
            raise ValueError(f"DVOL timestamp outside request range at row {line_number}")
        if previous_ts is not None and ts_ms <= previous_ts:
            raise ValueError(f"DVOL timestamps are not strictly increasing at row {line_number}")
        rows.append(
            {
                "currency": currency,
                "ts_ms": ts_ms,
                "open": open_value,
                "high": high,
                "low": low,
                "close": close,
            }
        )
        previous_ts = ts_ms
    return rows, {
        "currency": currency,
        "row_count": len(rows),
        "first_ts_ms": rows[0]["ts_ms"] if rows else None,
        "last_ts_ms": rows[-1]["ts_ms"] if rows else None,
        "response_bytes": len(raw),
        "response_sha256": hashlib.sha256(raw).hexdigest(),
        "continuation": None,
        "schema_valid": True,
    }


def _load_month(
    *,
    currency: str,
    month: str,
    start_ms: int,
    end_exclusive_ms: int,
    config: HistoricalDvolConfig,
    fetch: FetchBytes | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    url = dvol_url(currency=currency, start_ms=start_ms, end_exclusive_ms=end_exclusive_ms)
    cache_path = (
        Path(config.cache_dir).expanduser()
        / f"{currency}-{month}-{start_ms}-{end_exclusive_ms}.json"
    )
    cache_hit = cache_path.exists()
    if cache_hit:
        raw = cache_path.read_bytes()
    else:
        actual_fetch = fetch or (
            lambda target: _default_fetch(
                target,
                timeout_seconds=config.request_timeout_seconds,
                retries=config.request_retries,
            )
        )
        raw = actual_fetch(url)
        _atomic_cache(cache_path, raw)
    rows, provenance = parse_dvol_response(
        raw,
        currency=currency,
        start_ms=start_ms,
        end_exclusive_ms=end_exclusive_ms,
    )
    provenance.update(
        {
            "month": month,
            "request_url": url,
            "request_start_ms": start_ms,
            "request_end_exclusive_ms": end_exclusive_ms,
            "cache_path": str(cache_path),
            "cache_hit": cache_hit,
        }
    )
    return rows, provenance


def _validate_config(config: HistoricalDvolConfig) -> tuple[dt.date, dt.date]:
    if set(config.currencies) != {"BTC", "ETH"} or len(config.currencies) != 2:
        raise ValueError("historical DVOL v0 requires frozen BTC and ETH currencies")
    start = dt.date.fromisoformat(config.start_date)
    end = dt.date.fromisoformat(config.end_date)
    if end < start:
        raise ValueError("end_date must not precede start_date")
    if config.resolution_seconds != 3_600:
        raise ValueError("historical DVOL v0 supports hourly resolution only")
    if config.request_retries < 0:
        raise ValueError("request_retries must be non-negative")
    if config.request_timeout_seconds <= 0:
        raise ValueError("request_timeout_seconds must be positive")
    if not 0 < config.min_coverage_ratio <= 1:
        raise ValueError("min_coverage_ratio must be in (0, 1]")
    return start, end


def build_historical_dvol_dataset(
    config: HistoricalDvolConfig = HistoricalDvolConfig(),
    *,
    fetch: FetchBytes | None = None,
) -> dict[str, Any]:
    start, end = _validate_config(config)
    chunks = _month_ranges(start, end)
    rows_by_currency: dict[str, dict[int, dict[str, Any]]] = {}
    provenance: list[dict[str, Any]] = []
    duplicate_count = 0
    for currency in config.currencies:
        indexed: dict[int, dict[str, Any]] = {}
        for month, start_ms, end_exclusive_ms in chunks:
            rows, source = _load_month(
                currency=currency,
                month=month,
                start_ms=start_ms,
                end_exclusive_ms=end_exclusive_ms,
                config=config,
                fetch=fetch,
            )
            provenance.append(source)
            for row in rows:
                ts_ms = int(row["ts_ms"])
                if ts_ms in indexed:
                    duplicate_count += 1
                    continue
                indexed[ts_ms] = row
        rows_by_currency[currency] = indexed

    start_ms = _date_ms(start.isoformat())
    end_exclusive_ms = _date_ms((end + dt.timedelta(days=1)).isoformat())
    expected_timestamps = list(range(start_ms, end_exclusive_ms, HOUR_MS))
    by_currency: dict[str, dict[str, Any]] = {}
    for currency in config.currencies:
        indexed = rows_by_currency[currency]
        missing = [ts_ms for ts_ms in expected_timestamps if ts_ms not in indexed]
        coverage = len(indexed) / len(expected_timestamps) if expected_timestamps else 0.0
        by_currency[currency] = {
            "expected_row_count": len(expected_timestamps),
            "actual_row_count": len(indexed),
            "coverage_ratio": min(1.0, coverage),
            "missing_count": len(missing),
            "first_missing_ts_ms": missing[0] if missing else None,
            "first_ts_ms": min(indexed) if indexed else None,
            "last_ts_ms": max(indexed) if indexed else None,
        }

    common_timestamps = sorted(set.intersection(*(set(rows) for rows in rows_by_currency.values())))
    features = []
    for ts_ms in common_timestamps:
        btc = rows_by_currency["BTC"][ts_ms]
        eth = rows_by_currency["ETH"][ts_ms]
        features.append(
            {
                "ts_ms": ts_ms,
                "decision_ts_ms": ts_ms + HOUR_MS,
                "btc_dvol_open": btc["open"],
                "btc_dvol_high": btc["high"],
                "btc_dvol_low": btc["low"],
                "btc_dvol_close": btc["close"],
                "eth_dvol_open": eth["open"],
                "eth_dvol_high": eth["high"],
                "eth_dvol_low": eth["low"],
                "eth_dvol_close": eth["close"],
                "eth_minus_btc_dvol_close": eth["close"] - btc["close"],
                "complete": True,
            }
        )
    common_coverage = len(features) / len(expected_timestamps) if expected_timestamps else 0.0
    blockers: list[str] = []
    if duplicate_count:
        blockers.append("duplicate_hour_rows")
    if any(row["coverage_ratio"] < config.min_coverage_ratio for row in by_currency.values()):
        blockers.append("currency_coverage_below_gate")
    if common_coverage < config.min_coverage_ratio:
        blockers.append("aligned_coverage_below_gate")
    hash_provenance = [
        {key: value for key, value in row.items() if key not in {"cache_hit", "cache_path"}}
        for row in provenance
    ]
    basis = {
        "config": config.to_dict(),
        "provenance": hash_provenance,
        "hourly_features": features,
    }
    return {
        "schema_version": HISTORICAL_DVOL_VERSION,
        "artifact_type": "historical_dvol_dataset",
        "meta": {
            "research_only": True,
            "public_data_only": True,
            "private_exchange_data": False,
            "orders_allowed": False,
            "source": "Deribit public DVOL API",
            "source_checksum_sidecar": False,
            "raw_response_sha256_persisted": True,
            "point_in_time_rule": "decision_ts_ms equals source candle timestamp plus one hour",
            "strategy_results_evaluated": False,
            "data_hash": hashlib.sha256(
                json.dumps(basis, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        },
        "config": config.to_dict(),
        "diagnostics": {
            "verdict": "pass_dataset" if not blockers else "block_data",
            "blockers": blockers,
            "expected_hour_count": len(expected_timestamps),
            "aligned_complete_hour_count": len(features),
            "aligned_coverage_ratio": min(1.0, common_coverage),
            "duplicate_count": duplicate_count,
            "request_count": len(provenance),
            "response_bytes": sum(int(row["response_bytes"]) for row in provenance),
            "by_currency": by_currency,
            "strategy_results_evaluated": False,
            "promotion_evidence": False,
        },
        "source_requests": provenance,
        "hourly_features": features,
    }


def write_historical_dvol_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="alpha-agent-historical-dvol",
        path_key="artifact_path",
        default_filename="alpha_agent_historical_dvol.json",
        explicit_path=explicit_path,
    )
