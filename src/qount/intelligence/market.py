"""Public Binance market pulse for daily intelligence."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .contracts import MarketPulse


BINANCE_UM_TICKER_URL = "https://fapi.binance.com/fapi/v1/ticker/24hr"
BINANCE_UM_PREMIUM_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
DEFAULT_MARKET_SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT")


class MarketPulseError(ValueError):
    """Raised when the public market snapshot is incomplete or malformed."""


@dataclass(frozen=True)
class MarketPulseFetch:
    pulse: MarketPulse
    raw_bodies: Mapping[str, bytes] = field(repr=False)

    def validate(self) -> None:
        self.pulse.validate()
        if set(self.raw_bodies) != set(self.pulse.source_hashes):
            raise MarketPulseError("market_raw_source_names_invalid")
        for name, raw in self.raw_bodies.items():
            if (
                not isinstance(raw, bytes)
                or not raw
                or hashlib.sha256(raw).hexdigest()
                != self.pulse.source_hashes[name]
            ):
                raise MarketPulseError("market_raw_source_hash_invalid")


def _fetch_json(
    url: str,
    *,
    timeout_seconds: int,
    maximum_bytes: int,
    opener: Any,
) -> tuple[Any, bytes, str]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "qount-market-pulse/1"},
    )
    with opener.open(request, timeout=timeout_seconds) as response:
        if int(response.status) != 200 or response.geturl() != url:
            raise MarketPulseError("market_source_response_invalid")
        raw = response.read(maximum_bytes + 1)
    if len(raw) > maximum_bytes:
        raise MarketPulseError("market_source_response_too_large")
    try:
        return json.loads(raw), raw, hashlib.sha256(raw).hexdigest()
    except json.JSONDecodeError as exc:
        raise MarketPulseError("market_source_json_invalid") from exc


def build_market_pulse(
    *,
    ticker_payload: Sequence[Mapping[str, Any]],
    premium_payload: Sequence[Mapping[str, Any]],
    observed_at: str,
    source_hashes: Mapping[str, str],
    symbols: Sequence[str] = DEFAULT_MARKET_SYMBOLS,
) -> MarketPulse:
    ticker = {str(row.get("symbol")): row for row in ticker_payload}
    premium = {str(row.get("symbol")): row for row in premium_payload}
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        if symbol not in ticker or symbol not in premium:
            raise MarketPulseError(f"market_symbol_missing:{symbol}")
        ticker_row = ticker[symbol]
        premium_row = premium[symbol]
        try:
            funding_millis = int(premium_row["nextFundingTime"])
            next_funding_time = dt.datetime.fromtimestamp(
                funding_millis / 1000.0, tz=dt.timezone.utc
            ).isoformat()
            rows.append(
                {
                    "symbol": symbol,
                    "last_price": float(ticker_row["lastPrice"]),
                    "change_24h_pct": float(ticker_row["priceChangePercent"]),
                    "quote_volume_24h": float(ticker_row["quoteVolume"]),
                    "funding_rate": float(premium_row["lastFundingRate"]),
                    "next_funding_time": next_funding_time,
                }
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MarketPulseError(f"market_symbol_payload_invalid:{symbol}") from exc
    return MarketPulse.create(
        observed_at=observed_at,
        venue="binance_usd_m",
        symbols=rows,
        source_hashes=source_hashes,
    )


def fetch_binance_market_pulse(
    *,
    observed_at: str,
    symbols: Sequence[str] = DEFAULT_MARKET_SYMBOLS,
    timeout_seconds: int = 20,
    maximum_bytes: int = 2_000_000,
    opener: Any | None = None,
) -> MarketPulseFetch:
    if timeout_seconds < 1 or maximum_bytes < 1:
        raise MarketPulseError("market_fetch_config_invalid")
    client = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))
    ticker, ticker_raw, ticker_hash = _fetch_json(
        BINANCE_UM_TICKER_URL,
        timeout_seconds=timeout_seconds,
        maximum_bytes=maximum_bytes,
        opener=client,
    )
    premium, premium_raw, premium_hash = _fetch_json(
        BINANCE_UM_PREMIUM_URL,
        timeout_seconds=timeout_seconds,
        maximum_bytes=maximum_bytes,
        opener=client,
    )
    if not isinstance(ticker, list) or not isinstance(premium, list):
        raise MarketPulseError("market_source_shape_invalid")
    result = MarketPulseFetch(
        pulse=build_market_pulse(
            ticker_payload=ticker,
            premium_payload=premium,
            observed_at=observed_at,
            source_hashes={
                "ticker_24h": ticker_hash,
                "premium_index": premium_hash,
            },
            symbols=symbols,
        ),
        raw_bodies={
            "ticker_24h": ticker_raw,
            "premium_index": premium_raw,
        },
    )
    result.validate()
    return result


__all__ = [
    "BINANCE_UM_PREMIUM_URL",
    "BINANCE_UM_TICKER_URL",
    "DEFAULT_MARKET_SYMBOLS",
    "MarketPulseFetch",
    "MarketPulseError",
    "build_market_pulse",
    "fetch_binance_market_pulse",
]
