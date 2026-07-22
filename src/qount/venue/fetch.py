"""Venue data fetcher for capability snapshot generation.

Fetches exchange_info, server time, and changelog body from public
Binance endpoints via an injected fetcher.  Does NOT import ccxt or
qount.exchange_utils; the caller provides a client implementing
VenueDataFetcher.

Import boundary: this module must NOT import qount.execution,
qount.executor, qount.mini_trend.pilot_dispatcher, or ccxt.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import time
from dataclasses import dataclass
from typing import Any, Mapping, Protocol


class VenueDataFetcher(Protocol):
    """Interface for fetching public venue data.

    The orchestration script constructs a concrete fetcher (e.g. using
    urllib or requests) and injects it.  This keeps the venue package
    free of HTTP library dependencies.
    """

    def fetch_exchange_info(self) -> dict[str, Any]: ...

    def fetch_server_time_ms(self) -> int: ...

    def fetch_changelog_body(self) -> tuple[str, str]:
        """Return (body_text, observed_at_iso)."""
        ...


@dataclass(frozen=True)
class VenueData:
    """Raw venue data fetched from public endpoints."""

    exchange_info: dict[str, Any]
    server_time_ms: int
    local_time_ms: int
    changelog_body: str
    changelog_observed_at: str
    changelog_source_hash: str

    @property
    def server_time_offset_ms(self) -> int:
        return self.server_time_ms - self.local_time_ms


def fetch_venue_data(
    fetcher: VenueDataFetcher,
) -> VenueData:
    """Fetch all venue data via the injected fetcher.

    Returns a VenueData container with exchange_info, server time,
    local time, changelog body, and changelog source hash.
    """
    exchange_info = fetcher.fetch_exchange_info()
    server_time_ms = fetcher.fetch_server_time_ms()
    local_time_ms = int(time.time() * 1000)
    changelog_body, changelog_observed_at = fetcher.fetch_changelog_body()
    changelog_source_hash = hashlib.sha256(
        changelog_body.encode("utf-8")
    ).hexdigest()
    return VenueData(
        exchange_info=exchange_info,
        server_time_ms=server_time_ms,
        local_time_ms=local_time_ms,
        changelog_body=changelog_body,
        changelog_observed_at=changelog_observed_at,
        changelog_source_hash=changelog_source_hash,
    )


def extract_symbol_rules(
    exchange_info: Mapping[str, Any],
    symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Extract symbol rules from exchange_info.

    If *symbols* is provided, only extracts rules for those symbols.
    Otherwise extracts all symbols.
    """
    all_symbols = exchange_info.get("symbols", [])
    symbol_set = set(symbols) if symbols else None
    rules: dict[str, Any] = {}
    for sym_info in all_symbols:
        sym = str(sym_info.get("symbol", ""))
        if not sym:
            continue
        if symbol_set is not None and sym not in symbol_set:
            continue
        rules[sym] = {
            "status": sym_info.get("status"),
            "filters": sym_info.get("filters", []),
            "pricePrecision": sym_info.get("pricePrecision"),
            "quantityPrecision": sym_info.get("quantityPrecision"),
        }
    return rules
