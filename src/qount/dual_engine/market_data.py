"""Tiingo + Binance public-data collector for Dual-Engine paper cycles."""

from __future__ import annotations

import datetime as dt
import json
import math
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.parse import urlencode
from urllib.request import build_opener
from urllib.request import HTTPRedirectHandler
from urllib.request import Request
from zoneinfo import ZoneInfo

from qount.contracts import canonical_hash
from qount.contracts.trace import aware_datetime
from qount.dual_engine.contracts import C60_SYMBOLS
from qount.dual_engine.contracts import DualEngineContractError
from qount.dual_engine.contracts import DualEnginePaperContract
from qount.dual_engine.contracts import G20_EXECUTION_SYMBOLS
from qount.dual_engine.contracts import G20_PROXY_SYMBOLS
from qount.dual_engine.contracts import PaperCycleInput


TIINGO_BASE_URL = "https://api.tiingo.com"
BINANCE_BASE_URL = "https://api.binance.com"
PAPER_EVENTS = {"daily-close", "g20-open"}
_NEW_YORK = ZoneInfo("America/New_York")


class DualEngineMarketDataError(DualEngineContractError):
    """A public market response is unavailable or violates the frozen input contract."""


class NoScheduledPaperEvent(DualEngineMarketDataError):
    """The requested event is intentionally inactive for this session."""


@dataclass(frozen=True)
class DualEngineMarketConfig:
    schema_version: int
    tiingo_token_env: str
    timeout_seconds: int
    history_calendar_days: int
    g20_signal_dates: tuple[str, ...]
    g20_rebalance_dates: tuple[str, ...]
    orders_authorized: bool
    private_exchange_api_used: bool

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DualEngineMarketConfig":
        expected = {
            "schema_version", "tiingo_token_env", "timeout_seconds",
            "history_calendar_days", "g20_signal_dates",
            "g20_rebalance_dates", "orders_authorized",
            "private_exchange_api_used",
        }
        if set(value) != expected:
            raise DualEngineMarketDataError("paper_market_config_fields_invalid")
        config = cls(
            schema_version=int(value["schema_version"]),
            tiingo_token_env=str(value["tiingo_token_env"]),
            timeout_seconds=int(value["timeout_seconds"]),
            history_calendar_days=int(value["history_calendar_days"]),
            g20_signal_dates=tuple(str(item) for item in value["g20_signal_dates"]),
            g20_rebalance_dates=tuple(str(item) for item in value["g20_rebalance_dates"]),
            orders_authorized=value["orders_authorized"],
            private_exchange_api_used=value["private_exchange_api_used"],
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.schema_version != 1:
            raise DualEngineMarketDataError("paper_market_config_schema_invalid")
        if (
            not self.tiingo_token_env
            or not self.tiingo_token_env.replace("_", "").isalnum()
            or self.timeout_seconds < 1
            or self.timeout_seconds > 60
            or self.history_calendar_days < 180
            or self.history_calendar_days > 800
            or self.orders_authorized is not False
            or self.private_exchange_api_used is not False
        ):
            raise DualEngineMarketDataError("paper_market_config_invalid")
        for collection in (self.g20_signal_dates, self.g20_rebalance_dates):
            if len(collection) != len(set(collection)) or tuple(sorted(collection)) != collection:
                raise DualEngineMarketDataError("paper_market_calendar_invalid")
            for value in collection:
                try:
                    dt.date.fromisoformat(value)
                except ValueError as exc:
                    raise DualEngineMarketDataError("paper_market_calendar_invalid") from exc


JsonGetter = Callable[[str, Mapping[str, str], int], tuple[Any, str]]


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise DualEngineMarketDataError("paper_market_redirect_forbidden")


def _public_json_get(
    url: str,
    headers: Mapping[str, str],
    timeout_seconds: int,
) -> tuple[Any, str]:
    if not (
        url.startswith(f"{TIINGO_BASE_URL}/")
        or url.startswith(f"{BINANCE_BASE_URL}/")
    ):
        raise DualEngineMarketDataError("paper_market_url_forbidden")
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "qount-dual-engine-paper/1.0", **headers},
        method="GET",
    )
    try:
        with build_opener(_RejectRedirects()).open(
            request,
            timeout=timeout_seconds,
        ) as response:
            raw = response.read(20_000_001)
            if len(raw) > 20_000_000:
                raise DualEngineMarketDataError("paper_market_response_too_large")
    except OSError as exc:
        raise DualEngineMarketDataError("paper_market_request_failed") from exc
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DualEngineMarketDataError("paper_market_json_invalid") from exc
    return payload, canonical_hash({"url_path": url.split("?", 1)[0], "payload": payload})


def _url(base: str, path: str, parameters: Mapping[str, object]) -> str:
    return f"{base}{path}?{urlencode({key: value for key, value in parameters.items()})}"


def _number(value: object, *, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DualEngineMarketDataError(f"{name}_invalid") from exc
    if not math.isfinite(number) or number <= 0.0:
        raise DualEngineMarketDataError(f"{name}_invalid")
    return number


def _tiingo_daily(
    symbol: str,
    *,
    start: dt.date,
    end: dt.date,
    token: str,
    config: DualEngineMarketConfig,
    getter: JsonGetter,
) -> tuple[list[Mapping[str, Any]], str]:
    payload, payload_hash = getter(
        _url(
            TIINGO_BASE_URL,
            f"/tiingo/daily/{symbol}/prices",
            {"startDate": start.isoformat(), "endDate": end.isoformat(), "resampleFreq": "daily"},
        ),
        {"Authorization": f"Token {token}"},
        config.timeout_seconds,
    )
    if not isinstance(payload, list) or not payload or any(not isinstance(row, Mapping) for row in payload):
        raise DualEngineMarketDataError(f"paper_tiingo_daily_invalid:{symbol}")
    rows = sorted(payload, key=lambda row: str(row.get("date", "")))
    return rows, payload_hash


def _tiingo_first_intraday_price(
    symbol: str,
    *,
    session: dt.date,
    observed: dt.datetime,
    token: str,
    config: DualEngineMarketConfig,
    getter: JsonGetter,
) -> tuple[float, str]:
    payload, payload_hash = getter(
        _url(
            TIINGO_BASE_URL,
            f"/iex/{symbol}/prices",
            {
                "startDate": session.isoformat(),
                "endDate": session.isoformat(),
                "resampleFreq": "1min",
                "columns": "date,open,high,low,close",
            },
        ),
        {"Authorization": f"Token {token}"},
        config.timeout_seconds,
    )
    if not isinstance(payload, list) or not payload:
        raise DualEngineMarketDataError(f"paper_tiingo_intraday_missing:{symbol}")
    rows: list[Mapping[str, Any]] = []
    for row in payload:
        if not isinstance(row, Mapping):
            continue
        try:
            timestamp = aware_datetime(str(row["date"]))
        except (KeyError, TypeError, ValueError):
            continue
        local = timestamp.astimezone(_NEW_YORK)
        if (
            local.date() == session
            and local.time() >= dt.time(hour=9, minute=30)
            and timestamp <= observed
        ):
            rows.append(row)
    rows.sort(key=lambda row: str(row.get("date", "")))
    if not rows:
        raise DualEngineMarketDataError(f"paper_tiingo_intraday_invalid:{symbol}")
    first = rows[0]
    return _number(first.get("open") or first.get("close"), name=f"paper_tiingo_open:{symbol}"), payload_hash


def _binance_history_and_fill(
    symbol: str,
    *,
    observed: dt.datetime,
    config: DualEngineMarketConfig,
    getter: JsonGetter,
) -> tuple[tuple[float, ...], float, int, tuple[str, str]]:
    observed_ms = int(observed.timestamp() * 1000)
    payload, history_hash = getter(
        _url(
            BINANCE_BASE_URL,
            "/api/v3/klines",
            {"symbol": symbol, "interval": "1d", "limit": 120, "endTime": observed_ms},
        ),
        {},
        config.timeout_seconds,
    )
    if not isinstance(payload, list):
        raise DualEngineMarketDataError(f"paper_binance_klines_invalid:{symbol}")
    closed = [row for row in payload if isinstance(row, list) and len(row) >= 7 and int(row[6]) < observed_ms]
    if len(closed) < 91:
        raise DualEngineMarketDataError(f"paper_binance_history_short:{symbol}")
    closed = closed[-100:]
    closes = tuple(_number(row[4], name=f"paper_binance_close:{symbol}") for row in closed)
    cutoff_ms = int(closed[-1][6])
    trades, fill_hash = getter(
        _url(
            BINANCE_BASE_URL,
            "/api/v3/aggTrades",
            {
                "symbol": symbol,
                "startTime": cutoff_ms + 1,
                "endTime": observed_ms,
                "limit": 1,
            },
        ),
        {},
        config.timeout_seconds,
    )
    if not isinstance(trades, list) or not trades or not isinstance(trades[0], Mapping):
        raise DualEngineMarketDataError(f"paper_binance_later_quote_missing:{symbol}")
    fill = _number(trades[0].get("p"), name=f"paper_binance_fill:{symbol}")
    if int(trades[0].get("T", 0)) <= cutoff_ms:
        raise DualEngineMarketDataError(f"paper_binance_later_quote_invalid:{symbol}")
    return closes, fill, cutoff_ms, (history_hash, fill_hash)


def _binance_rules(
    *,
    config: DualEngineMarketConfig,
    getter: JsonGetter,
) -> tuple[dict[str, dict[str, float]], str]:
    payload, payload_hash = getter(
        _url(BINANCE_BASE_URL, "/api/v3/exchangeInfo", {"symbols": json.dumps(list(C60_SYMBOLS), separators=(",", ":"))}),
        {},
        config.timeout_seconds,
    )
    if not isinstance(payload, Mapping) or not isinstance(payload.get("symbols"), list):
        raise DualEngineMarketDataError("paper_binance_rules_invalid")
    result: dict[str, dict[str, float]] = {}
    for row in payload["symbols"]:
        if not isinstance(row, Mapping) or row.get("symbol") not in C60_SYMBOLS:
            continue
        filters = {
            item.get("filterType"): item
            for item in row.get("filters", [])
            if isinstance(item, Mapping)
        }
        lot = filters.get("LOT_SIZE", {})
        notional = filters.get("NOTIONAL", filters.get("MIN_NOTIONAL", {}))
        result[str(row["symbol"])] = {
            "step_size": _number(lot.get("stepSize"), name="paper_binance_step"),
            "minimum_notional": _number(notional.get("minNotional"), name="paper_binance_min_notional"),
        }
    if set(result) != set(C60_SYMBOLS):
        raise DualEngineMarketDataError("paper_binance_rules_incomplete")
    return result, payload_hash


def collect_market_cycle(
    config: DualEngineMarketConfig,
    *,
    observed_at: str,
    event: str,
    getter: JsonGetter = _public_json_get,
    environment: Mapping[str, str] | None = None,
) -> PaperCycleInput:
    """Collect one no-order cycle; scheduled dates are explicit and fail closed."""

    config.validate()
    if event not in PAPER_EVENTS:
        raise DualEngineMarketDataError("paper_market_event_invalid")
    observed = aware_datetime(observed_at)
    if observed < aware_datetime(DualEnginePaperContract.frozen_v1().forward_not_before):
        raise NoScheduledPaperEvent("paper_forward_not_started")
    session = observed.astimezone(_NEW_YORK).date()
    session_text = session.isoformat()
    if event == "g20-open" and session_text not in config.g20_rebalance_dates:
        raise NoScheduledPaperEvent("paper_g20_open_not_scheduled")
    g20_signal_day = event == "daily-close" and session_text in config.g20_signal_dates
    g20_rebalance_day = event == "g20-open"
    token = (environment or os.environ).get(config.tiingo_token_env, "")
    if not token:
        raise DualEngineMarketDataError("paper_tiingo_token_missing")
    start = session - dt.timedelta(days=config.history_calendar_days)

    proxy_closes: dict[str, tuple[float, ...]] = {}
    mark_prices: dict[str, float] = {}
    fill_prices: dict[str, float] = {}
    tiingo_hashes: dict[str, str] = {}
    tiingo_cutoffs: list[dt.datetime] = []
    tiingo_sessions: list[dt.date] = []
    for symbol in (*G20_PROXY_SYMBOLS, *G20_EXECUTION_SYMBOLS, "BIL"):
        rows, payload_hash = _tiingo_daily(
            symbol,
            start=start,
            end=session,
            token=token,
            config=config,
            getter=getter,
        )
        tiingo_hashes[symbol] = payload_hash
        usable_rows = [
            row
            for row in rows
            if str(row.get("date", ""))[:10]
            < (session_text if g20_rebalance_day else "9999-12-31")
        ] if g20_rebalance_day else rows
        if not usable_rows:
            raise DualEngineMarketDataError(f"paper_tiingo_history_short:{symbol}")
        latest = usable_rows[-1]
        try:
            session_date = dt.date.fromisoformat(str(latest["date"])[:10])
            tiingo_sessions.append(session_date)
            tiingo_cutoffs.append(
                dt.datetime.combine(
                    session_date,
                    dt.time(hour=16),
                    tzinfo=_NEW_YORK,
                ).astimezone(dt.timezone.utc)
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise DualEngineMarketDataError(f"paper_tiingo_date_invalid:{symbol}") from exc
        if symbol in G20_PROXY_SYMBOLS:
            proxy_closes[symbol] = tuple(
                _number(row.get("adjClose") or row.get("close"), name=f"paper_tiingo_close:{symbol}")
                for row in usable_rows[-100:]
            )
        else:
            close = _number(latest.get("close"), name=f"paper_tiingo_mark:{symbol}")
            mark_prices[symbol] = close
            fill_prices[symbol] = close
    if any(len(values) < 64 for values in proxy_closes.values()):
        raise DualEngineMarketDataError("paper_tiingo_history_short")
    if g20_signal_day and (
        set(tiingo_sessions) != {session}
        or observed < dt.datetime.combine(
            session,
            dt.time(hour=16),
            tzinfo=_NEW_YORK,
        ).astimezone(dt.timezone.utc)
    ):
        raise DualEngineMarketDataError("paper_g20_signal_close_unavailable")
    if g20_rebalance_day:
        for symbol in (*G20_EXECUTION_SYMBOLS, "BIL"):
            fill, payload_hash = _tiingo_first_intraday_price(
                symbol,
                session=session,
                observed=observed,
                token=token,
                config=config,
                getter=getter,
            )
            fill_prices[symbol] = fill
            mark_prices[symbol] = fill
            tiingo_hashes[f"{symbol}:first_intraday"] = payload_hash

    crypto_closes: dict[str, tuple[float, ...]] = {}
    binance_hashes: dict[str, tuple[str, str]] = {}
    crypto_cutoffs: list[dt.datetime] = []
    for symbol in C60_SYMBOLS:
        closes, fill, cutoff_ms, hashes = _binance_history_and_fill(
            symbol,
            observed=observed,
            config=config,
            getter=getter,
        )
        crypto_closes[symbol] = closes
        mark_prices[symbol] = fill
        fill_prices[symbol] = fill
        crypto_cutoffs.append(dt.datetime.fromtimestamp(cutoff_ms / 1000, tz=dt.timezone.utc))
        binance_hashes[symbol] = hashes
    rules, rules_hash = _binance_rules(config=config, getter=getter)
    for symbol in (*G20_EXECUTION_SYMBOLS, "BIL"):
        rules[symbol] = {"step_size": 1.0, "minimum_notional": 0.0}
    data_cutoff = max(*tiingo_cutoffs, *crypto_cutoffs).isoformat()
    return PaperCycleInput.create(
        observed_at=observed.isoformat(),
        decision_time=observed.isoformat(),
        data_cutoff=data_cutoff,
        proxy_closes=proxy_closes,
        crypto_closes=crypto_closes,
        mark_prices=mark_prices,
        fill_prices=fill_prices,
        symbol_rules=rules,
        source_hashes={
            "tiingo_public": canonical_hash(tiingo_hashes),
            "binance_public": canonical_hash(binance_hashes),
            "binance_exchange_rules": rules_hash,
        },
        g20_signal_day=g20_signal_day,
        g20_rebalance_day=g20_rebalance_day,
    )


__all__ = [
    "BINANCE_BASE_URL",
    "PAPER_EVENTS",
    "TIINGO_BASE_URL",
    "DualEngineMarketConfig",
    "DualEngineMarketDataError",
    "NoScheduledPaperEvent",
    "collect_market_cycle",
]
