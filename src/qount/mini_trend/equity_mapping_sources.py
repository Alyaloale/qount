"""Public source adapters and capacity audit for Equity Mapping research."""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import hashlib
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from qount.artifacts import persistent_research_dir
from qount.mini_trend.equity_mapping import CashSessionState
from qount.mini_trend.equity_mapping import CorporateActionState
from qount.mini_trend.equity_mapping import ExecutableQuote
from qount.mini_trend.equity_mapping import MappedEquityInstrument
from qount.mini_trend.futures_recovery import canonical_hash
from qount.models import utc_now
from qount.settings import Settings


EQUITY_MAPPING_SOURCE_CAPACITY_VERSION = "equity_mapping_source_capacity_v0.1"
DEFAULT_MAPPED_SYMBOLS = (
    "AAPLUSDT",
    "AMZNUSDT",
    "COINUSDT",
    "GOOGLUSDT",
    "METAUSDT",
    "MSFTUSDT",
    "MSTRUSDT",
    "NVDAUSDT",
    "QQQUSDT",
    "SPYUSDT",
    "TSLAUSDT",
)
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MONEY = re.compile(r"^\$?([0-9]+(?:\.[0-9]+)?)$")
_US_DATE_FORMATS = ("%b %d, %Y", "%m/%d/%Y")
FetchSource = Callable[["SourceProbe"], "SourceResponse"]


@dataclass(frozen=True)
class SourceProbe:
    source_id: str
    role: str
    url: str
    allowed_hosts: tuple[str, ...]
    timeout_seconds: float = 10.0


@dataclass(frozen=True)
class SourceResponse:
    source_id: str
    role: str
    source_url: str
    final_url: str | None
    observed_at: str
    available_at: str
    status_code: int | None
    content_type: str | None
    body: bytes = field(repr=False)
    error: str | None = None
    environment_proxy_used: bool = False

    @property
    def source_hash(self) -> str | None:
        return hashlib.sha256(self.body).hexdigest() if self.body else None

    def metadata(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "role": self.role,
            "source_url": self.source_url,
            "final_url": self.final_url,
            "observed_at": self.observed_at,
            "available_at": self.available_at,
            "status_code": self.status_code,
            "content_type": self.content_type,
            "byte_count": len(self.body),
            "source_hash": self.source_hash,
            "error": self.error,
            "environment_proxy_used": self.environment_proxy_used,
        }


def _utc(value: object) -> dt.datetime:
    if not isinstance(value, str):
        raise ValueError("equity_mapping_source_timestamp_invalid")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("equity_mapping_source_timestamp_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("equity_mapping_source_timestamp_naive")
    return parsed.astimezone(dt.UTC)


def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).isoformat()


def _json_object(response: SourceResponse) -> Mapping[str, Any]:
    if response.error is not None or response.status_code != 200:
        raise ValueError("equity_mapping_source_response_unavailable")
    try:
        payload = json.loads(response.body)
    except json.JSONDecodeError as exc:
        raise ValueError("equity_mapping_source_json_invalid") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("equity_mapping_source_json_not_object")
    return payload


def _number(raw: object, *, label: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}_invalid") from exc
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{label}_invalid")
    return value


def _money(raw: object, *, label: str) -> float:
    if not isinstance(raw, str):
        raise ValueError(f"{label}_invalid")
    match = _MONEY.fullmatch(raw.replace(",", "").strip())
    if match is None:
        raise ValueError(f"{label}_invalid")
    return _number(match.group(1), label=label)


def _parse_us_datetime(raw: object) -> dt.datetime:
    if not isinstance(raw, str):
        raise ValueError("equity_mapping_source_us_datetime_invalid")
    normalized = raw.replace(" ET", "").strip()
    for date_format in (
        "%b %d, %Y %I:%M %p",
        "%m/%d/%Y %I:%M %p",
        "%b %d, %Y",
    ):
        try:
            parsed = dt.datetime.strptime(normalized, date_format)
        except ValueError:
            continue
        return parsed.replace(tzinfo=ZoneInfo("America/New_York"))
    raise ValueError("equity_mapping_source_us_datetime_invalid")


def _parse_us_date(raw: object) -> dt.date:
    if not isinstance(raw, str):
        raise ValueError("equity_mapping_source_us_date_invalid")
    for date_format in _US_DATE_FORMATS:
        try:
            return dt.datetime.strptime(raw.strip(), date_format).date()
        except ValueError:
            continue
    raise ValueError("equity_mapping_source_us_date_invalid")


def _validate_probe_url(probe: SourceProbe, final_url: str | None = None) -> None:
    for candidate in (probe.url, final_url):
        if candidate is None:
            continue
        parsed = urllib.parse.urlparse(candidate)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.hostname.lower() not in probe.allowed_hosts
        ):
            raise ValueError("equity_mapping_source_url_invalid")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("equity_mapping_source_url_invalid") from exc
        if port not in {None, 443}:
            raise ValueError("equity_mapping_source_url_invalid")


def fetch_source_no_proxy(probe: SourceProbe) -> SourceResponse:
    """Fetch one bounded public source without inheriting environment proxies."""

    _validate_probe_url(probe)
    if probe.timeout_seconds <= 0.0:
        raise ValueError("equity_mapping_source_timeout_invalid")
    observed = dt.datetime.now(dt.UTC)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(
        probe.url,
        headers={
            "Accept": "application/json,text/html,text/plain,*/*",
            "Origin": "https://www.nasdaq.com",
            "Referer": "https://www.nasdaq.com/",
            "User-Agent": "Mozilla/5.0 qount-equity-mapping-source-audit/0.1",
        },
    )
    try:
        with opener.open(request, timeout=probe.timeout_seconds) as response:
            body = response.read(_MAX_RESPONSE_BYTES + 1)
            available = dt.datetime.now(dt.UTC)
            if len(body) > _MAX_RESPONSE_BYTES:
                raise ValueError("equity_mapping_source_response_too_large")
            final_url = response.geturl()
            _validate_probe_url(probe, final_url)
            return SourceResponse(
                source_id=probe.source_id,
                role=probe.role,
                source_url=probe.url,
                final_url=final_url,
                observed_at=_iso(observed),
                available_at=_iso(available),
                status_code=int(response.status),
                content_type=response.headers.get("Content-Type"),
                body=body,
            )
    except urllib.error.HTTPError as exc:
        final_url = exc.geturl()
        _validate_probe_url(probe, final_url)
        body = exc.read(_MAX_RESPONSE_BYTES + 1)
        return SourceResponse(
            source_id=probe.source_id,
            role=probe.role,
            source_url=probe.url,
            final_url=final_url,
            observed_at=_iso(observed),
            available_at=_iso(dt.datetime.now(dt.UTC)),
            status_code=int(exc.code),
            content_type=exc.headers.get("Content-Type"),
            body=body[:_MAX_RESPONSE_BYTES],
            error="http_error",
        )
    except (OSError, TimeoutError, urllib.error.URLError):
        return SourceResponse(
            source_id=probe.source_id,
            role=probe.role,
            source_url=probe.url,
            final_url=None,
            observed_at=_iso(observed),
            available_at=_iso(dt.datetime.now(dt.UTC)),
            status_code=None,
            content_type=None,
            body=b"",
            error="transport_unavailable",
        )


def parse_binance_instrument_mapping(
    response: SourceResponse,
    *,
    venue_symbol: str,
    cash_quote_venue: str,
    stablecoin_quote_venue: str,
) -> MappedEquityInstrument:
    payload = _json_object(response)
    rows = payload.get("symbols")
    if not isinstance(rows, list):
        raise ValueError("binance_exchange_info_symbols_invalid")
    matches = [
        row
        for row in rows
        if isinstance(row, Mapping) and row.get("symbol") == venue_symbol
    ]
    if len(matches) != 1:
        raise ValueError("binance_instrument_mapping_missing_or_duplicate")
    row = matches[0]
    cash_symbol = venue_symbol.removesuffix("USDT")
    if (
        row.get("status") != "TRADING"
        or row.get("contractType") != "PERPETUAL"
        or row.get("underlyingType") != "TRADIFI"
        or row.get("quoteAsset") != "USDT"
        or row.get("baseAsset") != cash_symbol
    ):
        raise ValueError("binance_instrument_mapping_semantics_invalid")
    source_hash = response.source_hash
    if source_hash is None:
        raise ValueError("binance_instrument_mapping_hash_missing")
    return MappedEquityInstrument(
        venue="binance",
        venue_symbol=venue_symbol,
        venue_base_currency=cash_symbol,
        cash_quote_venue=cash_quote_venue,
        stablecoin_quote_venue=stablecoin_quote_venue,
        cash_symbol=cash_symbol,
        product_kind="equity_perpetual",
        claim_kind="synthetic_derivative",
        quote_currency="USDT",
        price_multiplier=1.0,
        price_multiplier_scope="mapped_quote_to_one_cash_share",
        mapping_available_at=response.available_at,
        mapping_source_hash=source_hash,
    )


def parse_binance_book_ticker(
    response: SourceResponse,
    *,
    venue_symbol: str,
) -> ExecutableQuote:
    payload = _json_object(response)
    if payload.get("symbol") != venue_symbol:
        raise ValueError("binance_book_ticker_symbol_mismatch")
    bid = _number(payload.get("bidPrice"), label="binance_book_ticker_bid")
    ask = _number(payload.get("askPrice"), label="binance_book_ticker_ask")
    if ask < bid:
        raise ValueError("binance_book_ticker_crossed")
    try:
        event_ms = int(payload["time"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("binance_book_ticker_time_missing") from exc
    quote_at = dt.datetime.fromtimestamp(event_ms / 1000, dt.UTC)
    if quote_at > _utc(response.available_at):
        raise ValueError("binance_book_ticker_time_after_availability")
    source_hash = response.source_hash
    if source_hash is None:
        raise ValueError("binance_book_ticker_hash_missing")
    cash_symbol = venue_symbol.removesuffix("USDT")
    return ExecutableQuote(
        venue="binance",
        symbol=venue_symbol,
        product_kind="equity_perpetual",
        base_currency=cash_symbol,
        bid=bid,
        ask=ask,
        quote_currency="USDT",
        quote_at=_iso(quote_at),
        available_at=response.available_at,
        source_hash=source_hash,
        session="continuous",
    )


def parse_bitstamp_usdtusd_book(response: SourceResponse) -> ExecutableQuote:
    payload = _json_object(response)
    bids = payload.get("bids")
    asks = payload.get("asks")
    if not isinstance(bids, list) or not bids or not isinstance(asks, list) or not asks:
        raise ValueError("bitstamp_usdtusd_levels_missing")
    if not isinstance(bids[0], list) or not isinstance(asks[0], list):
        raise ValueError("bitstamp_usdtusd_level_invalid")
    bid = _number(bids[0][0], label="bitstamp_usdtusd_bid")
    ask = _number(asks[0][0], label="bitstamp_usdtusd_ask")
    if ask < bid:
        raise ValueError("bitstamp_usdtusd_crossed")
    try:
        microtimestamp = int(payload["microtimestamp"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("bitstamp_usdtusd_timestamp_missing") from exc
    quote_at = dt.datetime.fromtimestamp(microtimestamp / 1_000_000, dt.UTC)
    if quote_at > _utc(response.available_at):
        raise ValueError("bitstamp_usdtusd_time_after_availability")
    source_hash = response.source_hash
    if source_hash is None:
        raise ValueError("bitstamp_usdtusd_hash_missing")
    return ExecutableQuote(
        venue="bitstamp",
        symbol="USDTUSD",
        product_kind="fx_spot",
        base_currency="USDT",
        bid=bid,
        ask=ask,
        quote_currency="USD",
        quote_at=_iso(quote_at),
        available_at=response.available_at,
        source_hash=source_hash,
        session="continuous",
    )


def parse_nasdaq_market_session(
    response: SourceResponse,
    *,
    cash_trading_date: str,
) -> CashSessionState:
    payload = _json_object(response)
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise ValueError("nasdaq_market_info_data_invalid")
    target_date = dt.date.fromisoformat(cash_trading_date)
    next_trade_date = _parse_us_date(data.get("nextTradeDate"))
    opening = _parse_us_datetime(data.get("marketOpeningTime"))
    closing = _parse_us_datetime(data.get("marketClosingTime"))
    if (
        next_trade_date != target_date
        or opening.date() != target_date
        or closing.date() != target_date
    ):
        raise ValueError("nasdaq_market_info_target_date_mismatch")
    if opening.time() != dt.time(9, 30) or closing.time() != dt.time(16, 0):
        raise ValueError("nasdaq_market_info_session_hours_invalid")
    source_hash = response.source_hash
    if source_hash is None:
        raise ValueError("nasdaq_market_info_hash_missing")
    return CashSessionState(
        cash_trading_date=cash_trading_date,
        is_trading_day=True,
        session_type="regular",
        suspended=False,
        regular_open_time_local="09:30:00",
        regular_close_time_local="16:00:00",
        calendar_available_at=response.available_at,
        calendar_source_hash=source_hash,
    )


def audit_nasdaq_cash_quote(
    response: SourceResponse,
    *,
    cash_symbol: str,
) -> dict[str, Any]:
    reasons: list[str] = []
    diagnostics: dict[str, Any] = {}
    try:
        payload = _json_object(response)
        data = payload.get("data")
        if not isinstance(data, Mapping) or data.get("symbol") != cash_symbol:
            raise ValueError("nasdaq_cash_quote_identity_invalid")
        primary = data.get("primaryData")
        if not isinstance(primary, Mapping):
            raise ValueError("nasdaq_cash_quote_primary_data_invalid")
        diagnostics = {
            "is_real_time": primary.get("isRealTime"),
            "market_status": data.get("marketStatus"),
            "bid_price_present": primary.get("bidPrice") not in {None, "N/A"},
            "ask_price_present": primary.get("askPrice") not in {None, "N/A"},
            "available_time_fields": sorted(
                key for key in primary if "time" in str(key).casefold()
            ),
        }
        if primary.get("isRealTime") is not True:
            reasons.append("cash_quote_not_realtime")
        try:
            bid = _money(primary.get("bidPrice"), label="nasdaq_cash_quote_bid")
            ask = _money(primary.get("askPrice"), label="nasdaq_cash_quote_ask")
            if ask < bid:
                reasons.append("cash_quote_crossed")
        except ValueError:
            reasons.append("cash_quote_bid_ask_missing")
        quote_time_fields = {
            key: value
            for key, value in primary.items()
            if str(key).casefold() in {
                "quotetimestamp",
                "bidasktimestamp",
                "lastquotetimestamp",
            }
        }
        if not quote_time_fields:
            reasons.append("cash_quote_source_event_timestamp_missing")
        else:
            parsed_times: list[dt.datetime] = []
            for raw_timestamp in quote_time_fields.values():
                try:
                    parsed_times.append(_utc(raw_timestamp))
                except ValueError:
                    try:
                        parsed_times.append(_parse_us_datetime(raw_timestamp))
                    except ValueError:
                        continue
            if not parsed_times:
                reasons.append("cash_quote_source_event_timestamp_invalid")
            elif any(
                timestamp.astimezone(dt.UTC) > _utc(response.available_at)
                for timestamp in parsed_times
            ):
                reasons.append("cash_quote_source_event_timestamp_after_availability")
            diagnostics["parsed_quote_timestamps"] = [
                _iso(timestamp) for timestamp in parsed_times
            ]
    except ValueError as exc:
        reasons.append(str(exc))
    return {
        "semantic_ready": not reasons,
        "reasons": list(dict.fromkeys(reasons)),
        "diagnostics": diagnostics,
    }


def parse_nasdaq_explicit_corporate_action(
    response: SourceResponse,
    *,
    cash_symbol: str,
    cash_trading_date: str,
) -> CorporateActionState:
    payload = _json_object(response)
    data = payload.get("data")
    rows = data.get("rows") if isinstance(data, Mapping) else None
    if not isinstance(rows, list):
        raise ValueError("nasdaq_splits_rows_invalid")
    target_date = dt.date.fromisoformat(cash_trading_date)
    matching = []
    off_date_rows = False
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("nasdaq_splits_row_invalid")
        execution_date = _parse_us_date(row.get("executionDate"))
        if execution_date != target_date:
            off_date_rows = True
        if row.get("symbol") == cash_symbol and execution_date == target_date:
            matching.append(row)
    if len(matching) > 1:
        raise ValueError("nasdaq_split_duplicate_symbol_date")
    source_hash = response.source_hash
    if source_hash is None:
        raise ValueError("nasdaq_splits_hash_missing")
    if not matching:
        if off_date_rows:
            raise ValueError("nasdaq_splits_response_not_scoped_to_requested_date")
        raise ValueError("nasdaq_split_absence_not_proven")
    ratio = str(matching[0].get("ratio", ""))
    left, separator, right = ratio.partition(":")
    if not separator:
        raise ValueError("nasdaq_split_ratio_invalid")
    numerator = _number(left.strip(), label="nasdaq_split_ratio_numerator")
    denominator = _number(right.strip(), label="nasdaq_split_ratio_denominator")
    adjustment_factor = denominator / numerator
    return CorporateActionState(
        cash_symbol=cash_symbol,
        cash_trading_date=cash_trading_date,
        status="point_in_time_adjusted",
        action_kind="split" if numerator >= denominator else "reverse_split",
        adjustment_factor=adjustment_factor,
        adjustment_scope="multiply_cash_quote_to_instrument_basis",
        effective_at=dt.datetime.combine(target_date, dt.time(0), dt.UTC).isoformat(),
        available_at=response.available_at,
        source_hash=source_hash,
    )


def audit_nasdaq_earnings_context(
    response: SourceResponse,
    *,
    cash_symbol: str,
    cash_trading_date: str,
) -> dict[str, Any]:
    reasons: list[str] = []
    matches = 0
    try:
        payload = _json_object(response)
        data = payload.get("data")
        rows = data.get("rows") if isinstance(data, Mapping) else None
        if not isinstance(rows, list):
            raise ValueError("nasdaq_earnings_rows_invalid")
        target_date = dt.date.fromisoformat(cash_trading_date)
        if not rows:
            reasons.append("earnings_event_date_not_bound_in_rows")
        for row in rows:
            if not isinstance(row, Mapping):
                reasons.append("earnings_event_date_not_bound_in_rows")
                continue
            date_values = [
                value
                for key, value in row.items()
                if str(key).casefold() in {
                    "date",
                    "eventdate",
                    "earningsdate",
                    "reportdate",
                }
            ]
            try:
                row_dates = {_parse_us_date(value) for value in date_values}
            except ValueError:
                row_dates = set()
            if target_date not in row_dates:
                reasons.append("earnings_event_date_not_bound_in_rows")
            if row.get("symbol") == cash_symbol and target_date in row_dates:
                matches += 1
        if matches > 1:
            reasons.append("earnings_duplicate_symbol")
    except ValueError as exc:
        reasons.append(str(exc))
    return {
        "semantic_ready": not reasons,
        "reasons": list(dict.fromkeys(reasons)),
        "diagnostics": {
            "cash_symbol": cash_symbol,
            "cash_trading_date": cash_trading_date,
            "matching_row_count": matches,
        },
    }


def source_probe_specs(
    *,
    cash_trading_date: str,
    mapped_symbol: str = "NVDAUSDT",
    timeout_seconds: float = 10.0,
) -> tuple[SourceProbe, ...]:
    try:
        dt.date.fromisoformat(cash_trading_date)
    except ValueError as exc:
        raise ValueError("equity_mapping_source_cash_date_invalid") from exc
    if mapped_symbol not in DEFAULT_MAPPED_SYMBOLS:
        raise ValueError("equity_mapping_source_mapped_symbol_invalid")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0.0:
        raise ValueError("equity_mapping_source_timeout_invalid")
    cash_symbol = mapped_symbol.removesuffix("USDT")
    return (
        SourceProbe(
            "binance_exchange_info",
            "instrument_mapping",
            "https://fapi.binance.com/fapi/v1/exchangeInfo",
            ("fapi.binance.com",),
            timeout_seconds,
        ),
        SourceProbe(
            "binance_mapped_book",
            "mapped_quote",
            f"https://fapi.binance.com/fapi/v1/ticker/bookTicker?symbol={mapped_symbol}",
            ("fapi.binance.com",),
            timeout_seconds,
        ),
        SourceProbe(
            "nasdaq_cash_quote",
            "cash_premarket_quote",
            f"https://api.nasdaq.com/api/quote/{cash_symbol}/info?assetclass=stocks",
            ("api.nasdaq.com",),
            timeout_seconds,
        ),
        SourceProbe(
            "coinbase_usdtusd_book",
            "usdt_usd_quote",
            "https://api.exchange.coinbase.com/products/USDT-USD/book?level=1",
            ("api.exchange.coinbase.com",),
            timeout_seconds,
        ),
        SourceProbe(
            "kraken_usdtusd_book",
            "usdt_usd_quote",
            "https://api.kraken.com/0/public/Depth?pair=USDTUSD&count=1",
            ("api.kraken.com",),
            timeout_seconds,
        ),
        SourceProbe(
            "bitstamp_usdtusd_book",
            "usdt_usd_quote",
            "https://www.bitstamp.net/api/v2/order_book/usdtusd/?limit=1",
            ("www.bitstamp.net",),
            timeout_seconds,
        ),
        SourceProbe(
            "gemini_usdtusd_book",
            "usdt_usd_quote",
            "https://api.gemini.com/v1/book/usdtusd?limit_bids=1&limit_asks=1",
            ("api.gemini.com",),
            timeout_seconds,
        ),
        SourceProbe(
            "nasdaq_market_info",
            "cash_calendar",
            "https://api.nasdaq.com/api/market-info",
            ("api.nasdaq.com",),
            timeout_seconds,
        ),
        SourceProbe(
            "nasdaq_splits",
            "corporate_action",
            f"https://api.nasdaq.com/api/calendar/splits?date={cash_trading_date}",
            ("api.nasdaq.com",),
            timeout_seconds,
        ),
        SourceProbe(
            "nasdaq_earnings",
            "event_context",
            f"https://api.nasdaq.com/api/calendar/earnings?date={cash_trading_date}",
            ("api.nasdaq.com",),
            timeout_seconds,
        ),
    )


def _audit_response(
    response: SourceResponse,
    *,
    mapped_symbol: str,
    cash_trading_date: str,
) -> dict[str, Any]:
    cash_symbol = mapped_symbol.removesuffix("USDT")
    if response.error is not None:
        return {"semantic_ready": False, "reasons": [response.error]}
    if response.status_code != 200:
        return {
            "semantic_ready": False,
            "reasons": [f"source_http_status_{response.status_code}"],
        }
    try:
        if response.source_id == "binance_exchange_info":
            value = parse_binance_instrument_mapping(
                response,
                venue_symbol=mapped_symbol,
                cash_quote_venue="nasdaq",
                stablecoin_quote_venue="bitstamp",
            )
            reasons = value.validate()
            return {"semantic_ready": not reasons, "reasons": list(reasons)}
        if response.source_id == "binance_mapped_book":
            value = parse_binance_book_ticker(response, venue_symbol=mapped_symbol)
            reasons = value.validate()
            return {"semantic_ready": not reasons, "reasons": list(reasons)}
        if response.source_id == "bitstamp_usdtusd_book":
            value = parse_bitstamp_usdtusd_book(response)
            reasons = value.validate()
            return {"semantic_ready": not reasons, "reasons": list(reasons)}
        if response.source_id == "nasdaq_market_info":
            value = parse_nasdaq_market_session(
                response, cash_trading_date=cash_trading_date
            )
            reasons = value.validate()
            return {"semantic_ready": not reasons, "reasons": list(reasons)}
        if response.source_id == "nasdaq_cash_quote":
            return audit_nasdaq_cash_quote(response, cash_symbol=cash_symbol)
        if response.source_id == "nasdaq_splits":
            value = parse_nasdaq_explicit_corporate_action(
                response,
                cash_symbol=cash_symbol,
                cash_trading_date=cash_trading_date,
            )
            reasons = value.validate()
            return {"semantic_ready": not reasons, "reasons": list(reasons)}
        if response.source_id == "nasdaq_earnings":
            return audit_nasdaq_earnings_context(
                response,
                cash_symbol=cash_symbol,
                cash_trading_date=cash_trading_date,
            )
        if response.role == "usdt_usd_quote":
            return {
                "semantic_ready": False,
                "reasons": ["usdtusd_adapter_not_implemented_for_source"],
            }
    except (KeyError, TypeError, ValueError) as exc:
        return {"semantic_ready": False, "reasons": [str(exc)]}
    return {"semantic_ready": False, "reasons": ["source_adapter_missing"]}


def build_equity_mapping_source_capacity(
    *,
    cash_trading_date: str,
    mapped_symbol: str = "NVDAUSDT",
    timeout_seconds: float = 10.0,
    fetch: FetchSource = fetch_source_no_proxy,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Probe public sources without creating a market event or strategy trial."""

    specs = source_probe_specs(
        cash_trading_date=cash_trading_date,
        mapped_symbol=mapped_symbol,
        timeout_seconds=timeout_seconds,
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        responses = list(executor.map(fetch, specs))
    by_id = {response.source_id: response for response in responses}
    probes: list[dict[str, Any]] = []
    for spec in specs:
        response = by_id[spec.source_id]
        audit = _audit_response(
            response,
            mapped_symbol=mapped_symbol,
            cash_trading_date=cash_trading_date,
        )
        probes.append({**response.metadata(), "audit": audit})

    role_sources: dict[str, list[dict[str, Any]]] = {}
    for probe in probes:
        role_sources.setdefault(str(probe["role"]), []).append(probe)
    required_roles = (
        "instrument_mapping",
        "mapped_quote",
        "cash_premarket_quote",
        "usdt_usd_quote",
        "cash_calendar",
        "corporate_action",
        "event_context",
        "stress_scenario",
    )
    role_gates = {
        role: any(
            bool(source["audit"]["semantic_ready"])
            for source in role_sources.get(role, [])
        )
        for role in required_roles
    }
    blockers = [role for role, passed in role_gates.items() if not passed]
    report = {
        "schema_version": EQUITY_MAPPING_SOURCE_CAPACITY_VERSION,
        "artifact_type": "equity_mapping_public_source_capacity",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "source_capacity_only",
            "trial_count": 0,
            "market_event_created": False,
            "future_return_evaluated": False,
            "pnl_evaluated": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
            "environment_proxy_used": False,
        },
        "contract": {
            "cash_trading_date": cash_trading_date,
            "mapped_symbol": mapped_symbol,
            "cash_symbol": mapped_symbol.removesuffix("USDT"),
            "decision_time_local": "09:25:00 America/New_York",
            "maximum_cross_leg_skew_seconds": 5.0,
            "timeout_seconds": timeout_seconds,
            "source_ids": [spec.source_id for spec in specs],
        },
        "probes": probes,
        "role_gates": role_gates,
        "blockers": blockers,
        "verdict": (
            "pass_equity_mapping_source_capacity"
            if not blockers
            else "block_equity_mapping_source_capacity"
        ),
    }
    report["contract"]["contract_hash"] = canonical_hash(report["contract"])
    raw_bodies = {
        response.source_id: response.body for response in responses if response.body
    }
    return report, raw_bodies


def write_equity_mapping_source_capacity_artifact(
    settings: Settings,
    payload: Mapping[str, Any],
    raw_bodies: Mapping[str, bytes],
) -> dict[str, Any]:
    """Write the bounded probe bodies and a content manifest to a research run."""

    run_dir = persistent_research_dir(settings, "equity-mapping-source-capacity")
    raw_dir = run_dir / "raw"
    raw_dir.mkdir()
    files = []
    for source_id in sorted(raw_bodies):
        raw = raw_bodies[source_id]
        path = raw_dir / f"{source_id}.bin"
        path.write_bytes(raw)
        readback_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        expected_hash = hashlib.sha256(raw).hexdigest()
        if readback_hash != expected_hash:
            raise OSError("equity_mapping_source_artifact_readback_failed")
        files.append(
            {
                "source_id": source_id,
                "relative_path": str(path.relative_to(run_dir)),
                "byte_count": len(raw),
                "sha256": expected_hash,
            }
        )
    result = dict(payload)
    result["raw_manifest"] = {
        "file_count": len(files),
        "byte_count": sum(int(row["byte_count"]) for row in files),
        "files": files,
        "content_hash": canonical_hash(files),
    }
    artifact_path = run_dir / "equity_mapping_source_capacity.json"
    result["artifact_path"] = str(artifact_path)
    result["persistent_artifact_path"] = str(artifact_path)
    artifact_path.write_text(
        json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8"
    )
    return result
