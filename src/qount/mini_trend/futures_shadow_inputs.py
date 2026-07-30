"""Append-only public Binance UM inputs for future shadow monitoring."""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import math
import os
import shutil
import urllib.parse
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.research_data.market_data import Funding
from qount.research_data.market_data import day_url, funding_url, month_url
from qount.research_data.market_data import parse_funding_zip_bytes, parse_zip_bytes
from qount.mini_trend.forward import TOP3
from qount.mini_trend.futures_recovery import canonical_hash
from qount.models import utc_now
from qount.settings import Settings


SHADOW_INPUT_REFRESH_VERSION = "mini_trend_um_shadow_input_refresh_v0.2"
PUBLIC_UM_API_BASE_URL = "https://fapi.binance.com"
_DAY_MS = 86_400_000
_FUNDING_SETTLEMENT_ROUND_MS = 60_000
_FUNDING_SETTLEMENT_MAX_JITTER_MS = 1_000
_FUNDING_QUERY_END_GRACE_MS = 60_000
FetchBytes = Callable[[str], bytes]


@dataclass(frozen=True)
class ShadowInputRefreshConfig:
    symbols: tuple[str, ...] = TOP3
    interval: str = "1d"
    market: str = "um"
    request_timeout_seconds: float = 30.0
    funding_api_limit: int = 1000

    @property
    def contract_hash(self) -> str:
        return canonical_hash(
            {
                "config": asdict(self),
                "sources": {
                    "klines_and_closed_funding_months": "data.binance.vision",
                    "latest_completed_kline_fallback": (
                        "Binance public USD-M klines REST"
                    ),
                    "open_month_funding": "Binance public USD-M fundingRate REST",
                },
                "storage": "immutable cache files plus append-only funding snapshots",
                "private_exchange_data": False,
                "orders_allowed": False,
            }
        )


def _direct_fetch(url: str, *, timeout_seconds: float) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "qount-um-shadow-inputs/0.1"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout_seconds) as response:
        return response.read()


def proxy_fetch(proxy_url: str, *, timeout_seconds: float) -> FetchBytes:
    """Build a standard HTTP(S) proxy fetcher without persisting the proxy URL."""

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    )

    def fetch(url: str) -> bytes:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "qount-um-shadow-inputs/0.1"},
        )
        with opener.open(request, timeout=timeout_seconds) as response:
            return response.read()

    return fetch


def _month(value: str) -> tuple[int, int]:
    parsed = dt.date.fromisoformat(f"{value}-01")
    return parsed.year, parsed.month


def _iter_months(start: tuple[int, int], end: tuple[int, int]):
    year, month = start
    while (year, month) <= end:
        yield year, month
        month += 1
        if month == 13:
            year += 1
            month = 1


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_funding_settlement_timestamp(timestamp: int) -> int:
    rounded = (
        (timestamp + _FUNDING_SETTLEMENT_ROUND_MS // 2)
        // _FUNDING_SETTLEMENT_ROUND_MS
    ) * _FUNDING_SETTLEMENT_ROUND_MS
    if abs(timestamp - rounded) < _FUNDING_SETTLEMENT_MAX_JITTER_MS:
        return rounded
    return timestamp


def _write_immutable(path: Path, raw: bytes) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError(f"refusing to overwrite mismatched public input: {path}")
        return True
    partial = path.with_name(f"{path.name}.part")
    partial.write_bytes(raw)
    os.replace(partial, path)
    return False


def _copy_seed(path: Path, source: Path) -> bool:
    if path.exists() or not source.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f"{path.name}.part")
    shutil.copyfile(source, partial)
    os.replace(partial, path)
    return True


def funding_api_url(
    symbol: str,
    *,
    start_ms: int,
    end_ms: int,
    limit: int,
    base_url: str = PUBLIC_UM_API_BASE_URL,
) -> str:
    query = urllib.parse.urlencode(
        {
            "symbol": symbol,
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": limit,
        }
    )
    return f"{base_url.rstrip('/')}/fapi/v1/fundingRate?{query}"


def kline_api_url(
    symbol: str,
    *,
    interval: str,
    open_time_ms: int,
    base_url: str = PUBLIC_UM_API_BASE_URL,
) -> str:
    query = urllib.parse.urlencode(
        {
            "symbol": symbol,
            "interval": interval,
            "startTime": open_time_ms,
            "endTime": open_time_ms + _DAY_MS - 1,
            "limit": 1,
        }
    )
    return f"{base_url.rstrip('/')}/fapi/v1/klines?{query}"


def parse_completed_daily_kline_api_response(
    raw: bytes,
    *,
    symbol: str,
    day: dt.date,
    retrieved_at: dt.datetime,
) -> bytes:
    payload = json.loads(raw)
    if not isinstance(payload, list) or len(payload) != 1:
        raise ValueError("Binance kline response must contain exactly one row")
    row = payload[0]
    if not isinstance(row, list) or len(row) < 12:
        raise ValueError("invalid Binance kline response row")
    expected_open_ms = int(
        dt.datetime.combine(day, dt.time(), dt.UTC).timestamp() * 1000
    )
    expected_close_ms = expected_open_ms + _DAY_MS - 1
    try:
        open_ms = int(row[0])
        close_ms = int(row[6])
        numeric = [float(row[index]) for index in (1, 2, 3, 4, 5, 7, 9, 10)]
        trade_count = int(row[8])
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid Binance kline response value") from exc
    retrieved_ms = int(retrieved_at.timestamp() * 1000)
    if open_ms != expected_open_ms or close_ms != expected_close_ms:
        raise ValueError("Binance kline response is outside the requested day")
    if close_ms >= retrieved_ms:
        raise ValueError("Binance kline response is not yet completed")
    if not all(math.isfinite(value) for value in numeric) or trade_count < 0:
        raise ValueError("Binance kline response contains invalid numeric data")

    csv = ",".join(str(value) for value in row[:12]) + "\n"
    buffer = io.BytesIO()
    info = zipfile.ZipInfo(f"{symbol}-1d-{day.isoformat()}.csv")
    info.date_time = (1980, 1, 1, 0, 0, 0)
    info.compress_type = zipfile.ZIP_STORED
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(info, csv.encode("utf-8"))
    result = buffer.getvalue()
    parsed = parse_zip_bytes(result)
    if len(parsed) != 1 or parsed[0].ts_ms != expected_open_ms:
        raise ValueError("converted Binance kline response failed validation")
    return result


def parse_funding_api_response(
    raw: bytes,
    *,
    symbol: str,
    start_ms: int,
    end_ms: int,
) -> list[Funding]:
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise ValueError("Binance funding response must be a list")
    seen: dict[int, Funding] = {}
    for item in payload:
        if not isinstance(item, Mapping) or item.get("symbol") != symbol:
            raise ValueError("Binance funding response contains an unexpected symbol")
        try:
            timestamp = int(item["fundingTime"])
            rate = float(item["fundingRate"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid Binance funding response row") from exc
        if timestamp < start_ms or timestamp > end_ms or not math.isfinite(rate):
            raise ValueError("Binance funding response row is outside the requested range")
        canonical_timestamp = canonical_funding_settlement_timestamp(timestamp)
        if (
            canonical_timestamp in seen
            and seen[canonical_timestamp].rate != rate
        ):
            raise ValueError("conflicting duplicate funding settlement")
        seen[canonical_timestamp] = Funding(canonical_timestamp, rate)
    return [seen[timestamp] for timestamp in sorted(seen)]


def _funding_days_missing(
    rows: Sequence[Funding],
    *,
    first_day: dt.date,
    last_day: dt.date,
    minimum_settlements: int = 3,
) -> list[str]:
    counts: dict[dt.date, int] = {}
    for row in rows:
        timestamp = canonical_funding_settlement_timestamp(row.ts_ms)
        settlement_day_ms = ((timestamp - 1) // _DAY_MS) * _DAY_MS
        settlement_day = dt.datetime.fromtimestamp(
            settlement_day_ms / 1000, dt.UTC
        ).date()
        counts[settlement_day] = counts.get(settlement_day, 0) + 1
    missing = []
    day = first_day
    while day <= last_day:
        if counts.get(day, 0) < minimum_settlements:
            missing.append(day.isoformat())
        day += dt.timedelta(days=1)
    return missing


def _load_funding_snapshot(path: Path) -> tuple[str, list[Funding]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != (
        "mini_trend_um_funding_snapshot_v0.1"
    ):
        raise ValueError(f"unexpected funding snapshot schema at {path}")
    symbol = str(payload["symbol"])
    rows = [
        Funding(
            canonical_funding_settlement_timestamp(int(row["ts_ms"])),
            float(row["rate"]),
        )
        for row in payload["rows"]
    ]
    return symbol, rows


def load_funding_snapshots(
    snapshot_root: str | Path,
    *,
    symbols: Sequence[str] = TOP3,
) -> dict[str, list[Funding]]:
    root = Path(snapshot_root).expanduser()
    merged: dict[str, dict[int, Funding]] = {symbol: {} for symbol in symbols}
    if not root.exists():
        return {symbol: [] for symbol in symbols}
    for path in sorted(root.rglob("*.json")):
        symbol, rows = _load_funding_snapshot(path)
        if symbol not in merged:
            continue
        for row in rows:
            existing = merged[symbol].get(row.ts_ms)
            if existing is not None and existing.rate != row.rate:
                raise ValueError(f"conflicting funding snapshots for {symbol} at {row.ts_ms}")
            merged[symbol][row.ts_ms] = row
    return {
        symbol: [by_time[timestamp] for timestamp in sorted(by_time)]
        for symbol, by_time in merged.items()
    }


def merge_funding(
    archived: Mapping[str, Sequence[Funding]],
    snapshots: Mapping[str, Sequence[Funding]],
    *,
    symbols: Sequence[str] = TOP3,
) -> dict[str, list[Funding]]:
    result: dict[str, list[Funding]] = {}
    for symbol in symbols:
        by_time: dict[int, Funding] = {}
        for row in [*archived.get(symbol, []), *snapshots.get(symbol, [])]:
            timestamp = canonical_funding_settlement_timestamp(row.ts_ms)
            normalized = Funding(timestamp, row.rate)
            existing = by_time.get(timestamp)
            if existing is not None and existing.rate != row.rate:
                raise ValueError(f"archive/snapshot funding conflict for {symbol} at {timestamp}")
            by_time[timestamp] = normalized
        result[symbol] = [by_time[timestamp] for timestamp in sorted(by_time)]
    return result


def _cache_record(path: Path, *, kind: str, symbol: str, cache_hit: bool) -> dict[str, Any]:
    raw = path.read_bytes()
    return {
        "kind": kind,
        "symbol": symbol,
        "path": str(path),
        "bytes": len(raw),
        "sha256": _sha256(raw),
        "cache_hit": cache_hit,
    }


def refresh_shadow_inputs(
    *,
    cache_dir: str | Path,
    funding_snapshot_root: str | Path,
    start_month: str,
    end_date: str,
    retrieved_at: dt.datetime | None = None,
    seed_cache_dir: str | Path | None = None,
    config: ShadowInputRefreshConfig | None = None,
    vision_fetch: FetchBytes | None = None,
    kline_fetch: FetchBytes | None = None,
    funding_fetch: FetchBytes | None = None,
    funding_transport: str = "direct_wsl",
) -> dict[str, Any]:
    config = config or ShadowInputRefreshConfig()
    retrieved_at = (retrieved_at or utc_now()).astimezone(dt.UTC)
    end = dt.date.fromisoformat(end_date)
    if end >= retrieved_at.date():
        raise ValueError("end_date must be a completed UTC day before retrieval")
    start = _month(start_month)
    if start > (end.year, end.month):
        raise ValueError("start_month must not be after end_date")
    cache_root = Path(cache_dir).expanduser()
    snapshot_root = Path(funding_snapshot_root).expanduser()
    seed_root = Path(seed_cache_dir).expanduser() if seed_cache_dir else None
    actual_vision_fetch = vision_fetch or (
        lambda url: _direct_fetch(url, timeout_seconds=config.request_timeout_seconds)
    )
    actual_funding_fetch = funding_fetch or (
        lambda url: _direct_fetch(url, timeout_seconds=config.request_timeout_seconds)
    )
    actual_kline_fetch = kline_fetch or actual_funding_fetch
    files: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []

    def obtain(
        name: str,
        url: str,
        *,
        kind: str,
        symbol: str,
        parser,
        fallback_day: dt.date | None = None,
    ) -> None:
        target = cache_root / name
        seeded = _copy_seed(target, seed_root / name) if seed_root else False
        source = "data.binance.vision"
        try:
            if target.exists():
                raw = target.read_bytes()
                source = "immutable_cache"
            else:
                try:
                    raw = actual_vision_fetch(url)
                except Exception:
                    if fallback_day != end:
                        raise
                    open_time_ms = int(
                        dt.datetime.combine(fallback_day, dt.time(), dt.UTC).timestamp()
                        * 1000
                    )
                    raw = parse_completed_daily_kline_api_response(
                        actual_kline_fetch(
                            kline_api_url(
                                symbol,
                                interval=config.interval,
                                open_time_ms=open_time_ms,
                            )
                        ),
                        symbol=symbol,
                        day=fallback_day,
                        retrieved_at=retrieved_at,
                    )
                    source = "binance_public_um_rest"
            parsed = parser(raw)
            if not parsed:
                raise ValueError("public archive parsed to zero rows")
            cache_hit = target.exists()
            _write_immutable(target, raw)
            record = _cache_record(
                target,
                kind=kind,
                symbol=symbol,
                cache_hit=cache_hit or seeded,
            )
            record["source"] = source
            files.append(record)
        except Exception as exc:
            unavailable.append(
                {
                    "kind": kind,
                    "symbol": symbol,
                    "name": name,
                    "error_type": type(exc).__name__,
                }
            )

    end_month = (end.year, end.month)
    for year, month in _iter_months(start, end_month):
        final_month = (year, month) == end_month
        for symbol in config.symbols:
            if final_month:
                for day in range(1, end.day + 1):
                    name = f"um-{symbol}-{config.interval}-{year:04d}-{month:02d}-{day:02d}.zip"
                    obtain(
                        name,
                        day_url(
                            symbol,
                            config.interval,
                            year,
                            month,
                            day,
                            market=config.market,
                        ),
                        kind="daily_kline",
                        symbol=symbol,
                        parser=parse_zip_bytes,
                        fallback_day=dt.date(year, month, day),
                    )
                continue
            kline_name = f"um-{symbol}-{config.interval}-{year:04d}-{month:02d}.zip"
            obtain(
                kline_name,
                month_url(
                    symbol,
                    config.interval,
                    year,
                    month,
                    market=config.market,
                ),
                kind="monthly_kline",
                symbol=symbol,
                parser=parse_zip_bytes,
            )
            funding_name = f"{symbol}-fundingRate-{year:04d}-{month:02d}.zip"
            obtain(
                funding_name,
                funding_url(symbol, year, month),
                kind="monthly_funding",
                symbol=symbol,
                parser=parse_funding_zip_bytes,
            )

    start_ms = int(dt.datetime(end.year, end.month, 1, tzinfo=dt.UTC).timestamp() * 1000)
    end_ms = int(
        dt.datetime.combine(end + dt.timedelta(days=1), dt.time(), tzinfo=dt.UTC).timestamp()
        * 1000
    ) + _FUNDING_QUERY_END_GRACE_MS
    retrieval_id = retrieved_at.strftime("%Y%m%dT%H%M%SZ")
    funding_api: dict[str, Any] = {
        "transport": funding_transport,
        "requested_symbols": list(config.symbols),
        "complete_symbols": [],
        "failed_symbols": [],
        "settlement_count_by_symbol": {},
    }
    for symbol in config.symbols:
        url = funding_api_url(
            symbol,
            start_ms=start_ms,
            end_ms=end_ms,
            limit=config.funding_api_limit,
        )
        try:
            raw = actual_funding_fetch(url)
            rows = parse_funding_api_response(
                raw,
                symbol=symbol,
                start_ms=start_ms,
                end_ms=end_ms,
            )
            missing_days = _funding_days_missing(
                rows,
                first_day=dt.date(end.year, end.month, 1),
                last_day=end,
            )
            if missing_days:
                raise ValueError(
                    f"incomplete daily funding settlements: {len(missing_days)} day(s)"
                )
            snapshot = {
                "schema_version": "mini_trend_um_funding_snapshot_v0.1",
                "artifact_type": "mini_trend_um_public_funding_snapshot",
                "retrieved_at": retrieved_at.isoformat(),
                "symbol": symbol,
                "query": {"start_ms": start_ms, "end_ms": end_ms},
                "raw_response_sha256": _sha256(raw),
                "rows": [{"ts_ms": row.ts_ms, "rate": row.rate} for row in rows],
            }
            snapshot_raw = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
            path = (
                snapshot_root
                / f"{end.year:04d}"
                / f"{end.month:02d}"
                / f"{retrieval_id}-{symbol}.json"
            )
            cache_hit = _write_immutable(path, snapshot_raw)
            files.append(
                _cache_record(
                    path,
                    kind="funding_api_snapshot",
                    symbol=symbol,
                    cache_hit=cache_hit,
                )
            )
            funding_api["complete_symbols"].append(symbol)
            funding_api["settlement_count_by_symbol"][symbol] = len(rows)
        except Exception as exc:
            funding_api["failed_symbols"].append(
                {"symbol": symbol, "error_type": type(exc).__name__}
            )

    required_monthly = sum(
        2 * len(config.symbols)
        for month in _iter_months(start, end_month)
        if month != end_month
    )
    monthly_complete = sum(
        row["kind"] in {"monthly_kline", "monthly_funding"} for row in files
    ) == required_monthly
    daily_complete = not any(row["kind"] == "daily_kline" for row in unavailable)
    funding_complete = len(funding_api["complete_symbols"]) == len(config.symbols)
    verdict = (
        "shadow_inputs_refreshed"
        if monthly_complete and daily_complete and funding_complete
        else "await_complete_shadow_input_transport"
    )
    data_hash = canonical_hash(
        [
            {
                "kind": row["kind"],
                "symbol": row["symbol"],
                "bytes": row["bytes"],
                "sha256": row["sha256"],
            }
            for row in sorted(
                files,
                key=lambda value: (
                    value["kind"],
                    value["symbol"],
                    value["sha256"],
                ),
            )
        ]
    )
    return {
        "schema_version": SHADOW_INPUT_REFRESH_VERSION,
        "artifact_type": "mini_trend_um_shadow_input_refresh",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "public_data_only": True,
            "private_exchange_data": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "contract": asdict(config) | {"contract_hash": config.contract_hash},
        "data_hash": data_hash,
        "request": {
            "start_month": start_month,
            "end_date": end.isoformat(),
            "retrieved_at": retrieved_at.isoformat(),
            "cache_dir": str(cache_root),
            "funding_snapshot_root": str(snapshot_root),
            "seed_cache_used": seed_root is not None,
        },
        "files": files,
        "unavailable": unavailable,
        "funding_api": funding_api,
        "diagnostics": {
            "monthly_archive_complete": monthly_complete,
            "daily_archive_complete_through_end_date": daily_complete,
            "current_month_funding_complete": funding_complete,
            "unavailable_count": len(unavailable),
            "verdict": verdict,
            "strategy_results_evaluated": False,
            "paper_or_live_allowed": False,
        },
    }


def write_shadow_input_refresh_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-shadow-input-refresh",
        path_key="artifact_path",
        default_filename="mini_trend_um_shadow_input_refresh.json",
        explicit_path=explicit_path,
    )
