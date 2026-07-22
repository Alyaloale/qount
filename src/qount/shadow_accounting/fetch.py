"""Private exchange data fetcher for the shadow accountant.

Fetches user trades, income history, and open orders from Binance USD-M
via an injected read-only exchange client.  Does NOT import ccxt or
qount.execution; the caller provides a client implementing ReadOnlyExchange.

Import boundary: this module must NOT import qount.execution,
qount.mini_trend.pilot_dispatcher, qount.ledger, or ccxt.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from typing import Any, Callable, Mapping, Protocol, Sequence

from qount.shadow_accounting.contracts import FetchResult
from qount.shadow_accounting.contracts import QueryMetadata


class ReadOnlyExchange(Protocol):
    """Read-only exchange interface returning raw Binance USD-M responses.

    The orchestration script is responsible for constructing a client
    that implements this interface, typically by wrapping ccxt or
    direct REST calls.  Methods must return raw Binance dict responses
    (not ccxt-standardized objects) so that rebuild functions can
    consume them directly.
    """

    def fetch_my_trades(
        self,
        symbol: str,
        *,
        start_time: int,
        end_time: int,
        limit: int = ...,
    ) -> list[dict[str, Any]]: ...

    def fetch_income_history(
        self,
        *,
        start_time: int,
        end_time: int,
        limit: int = ...,
    ) -> list[dict[str, Any]]: ...

    def fetch_open_orders(
        self,
        symbol: str | None = ...,
    ) -> list[dict[str, Any]]: ...


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _canonical_json_hash(records: Sequence[Mapping[str, Any]]) -> str:
    if not records:
        return hashlib.sha256(b"[]").hexdigest()
    canonical = json.dumps(
        [dict(r) for r in records],
        ensure_ascii=True,
        sort_keys=True,
        allow_nan=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def _retry_call(
    func: Callable[[], list[dict[str, Any]]],
    *,
    max_retries: int,
    retry_delay_seconds: float,
) -> tuple[list[dict[str, Any]], int]:
    """Call *func* with retries.  Returns (result, retry_count)."""
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return func(), attempt
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                time.sleep(retry_delay_seconds)
    assert last_exc is not None
    raise last_exc


def fetch_private_trades(
    exchange: ReadOnlyExchange,
    symbols: Sequence[str],
    *,
    start_ms: int,
    end_ms: int,
    page_size: int = 1000,
    max_retries: int = 3,
    retry_delay_seconds: float = 1.0,
) -> FetchResult:
    """Fetch user trades for multiple symbols with independent pagination.

    For each symbol, paginates through the ``[start_ms, end_ms]`` window
    using the last trade's time as the next page's start_time.
    Stops when a page returns fewer than *page_size* records or when
    the window is exhausted.
    """
    all_records: list[dict[str, Any]] = []
    queries: list[QueryMetadata] = []

    for symbol in symbols:
        page_start = start_ms
        page_count = 0
        total_retries = 0
        symbol_records: list[dict[str, Any]] = []

        while True:
            page_count += 1
            records, retries = _retry_call(
                lambda s=symbol, st=page_start, e=end_ms: exchange.fetch_my_trades(
                    s, start_time=st, end_time=e, limit=page_size,
                ),
                max_retries=max_retries,
                retry_delay_seconds=retry_delay_seconds,
            )
            total_retries += retries
            symbol_records.extend(records)

            if len(records) < page_size:
                break
            last_time = records[-1].get("time")
            if last_time is None:
                break
            next_start = int(last_time) + 1
            if next_start >= end_ms:
                break
            page_start = next_start

        source_hash = _canonical_json_hash(symbol_records)
        queries.append(
            QueryMetadata.create(
                endpoint="fetch_my_trades",
                symbol=symbol,
                query_start_ms=start_ms,
                query_end_ms=end_ms,
                observed_at=_now_iso(),
                page_count=page_count,
                retry_count=total_retries,
                result_count=len(symbol_records),
                source_hash=source_hash,
                coverage_complete=True,
            )
        )
        all_records.extend(symbol_records)

    return FetchResult.create(
        data_type="trades",
        records=all_records,
        queries=queries,
    )


def fetch_income_history(
    exchange: ReadOnlyExchange,
    *,
    start_ms: int,
    end_ms: int,
    page_size: int = 1000,
    max_retries: int = 3,
    retry_delay_seconds: float = 1.0,
) -> FetchResult:
    """Fetch income history for the entire account with pagination.

    Paginates through the ``[start_ms, end_ms]`` window using the last
    income record's time as the next page's start_time.
    """
    page_start = start_ms
    page_count = 0
    total_retries = 0
    all_records: list[dict[str, Any]] = []

    while True:
        page_count += 1
        records, retries = _retry_call(
            lambda st=page_start, e=end_ms: exchange.fetch_income_history(
                start_time=st, end_time=e, limit=page_size,
            ),
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
        )
        total_retries += retries
        all_records.extend(records)

        if len(records) < page_size:
            break
        last_time = records[-1].get("time")
        if last_time is None:
            break
        next_start = int(last_time) + 1
        if next_start >= end_ms:
            break
        page_start = next_start

    source_hash = _canonical_json_hash(all_records)
    queries = (
        QueryMetadata.create(
            endpoint="fetch_income_history",
            symbol="",
            query_start_ms=start_ms,
            query_end_ms=end_ms,
            observed_at=_now_iso(),
            page_count=page_count,
            retry_count=total_retries,
            result_count=len(all_records),
            source_hash=source_hash,
            coverage_complete=True,
        ),
    )
    return FetchResult.create(
        data_type="income_history",
        records=all_records,
        queries=queries,
    )


def fetch_open_orders(
    exchange: ReadOnlyExchange,
    symbols: Sequence[str] | None = None,
    *,
    max_retries: int = 3,
    retry_delay_seconds: float = 1.0,
) -> FetchResult:
    """Fetch current open orders.

    If *symbols* is None, fetches all open orders.  Otherwise fetches
    per-symbol and aggregates.  Open orders are a point-in-time snapshot;
    no pagination is needed.
    """
    all_records: list[dict[str, Any]] = []
    queries: list[QueryMetadata] = []

    if symbols is None:
        records, retries = _retry_call(
            lambda: exchange.fetch_open_orders(None),
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
        )
        all_records.extend(records)
        source_hash = _canonical_json_hash(all_records)
        queries.append(
            QueryMetadata.create(
                endpoint="fetch_open_orders",
                symbol="",
                query_start_ms=0,
                query_end_ms=0,
                observed_at=_now_iso(),
                page_count=1,
                retry_count=retries,
                result_count=len(all_records),
                source_hash=source_hash,
                coverage_complete=True,
            )
        )
    else:
        for symbol in symbols:
            records, retries = _retry_call(
                lambda s=symbol: exchange.fetch_open_orders(s),
                max_retries=max_retries,
                retry_delay_seconds=retry_delay_seconds,
            )
            all_records.extend(records)
            source_hash = _canonical_json_hash(records)
            queries.append(
                QueryMetadata.create(
                    endpoint="fetch_open_orders",
                    symbol=symbol,
                    query_start_ms=0,
                    query_end_ms=0,
                    observed_at=_now_iso(),
                    page_count=1,
                    retry_count=retries,
                    result_count=len(records),
                    source_hash=source_hash,
                    coverage_complete=True,
                )
            )

    return FetchResult.create(
        data_type="open_orders",
        records=all_records,
        queries=queries,
    )
