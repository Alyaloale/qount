"""Bounded public-data replay for the owner-authorized 2026 YTD paper curve."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
import json
import os
from typing import Any, Mapping

from qount.contracts import canonical_hash
from qount.contracts.trace import aware_datetime
from qount.dual_engine.contracts import C60_SYMBOLS
from qount.dual_engine.contracts import G20_EXECUTION_SYMBOLS
from qount.dual_engine.contracts import G20_PROXY_SYMBOLS
from qount.dual_engine.contracts import PaperCycleInput
from qount.dual_engine.market_data import BINANCE_BASE_URL
from qount.dual_engine.market_data import DualEngineMarketConfig
from qount.dual_engine.market_data import DualEngineMarketDataError
from qount.dual_engine.market_data import JsonGetter
from qount.dual_engine.market_data import TIINGO_BASE_URL
from qount.dual_engine.market_data import _binance_rules
from qount.dual_engine.market_data import _number
from qount.dual_engine.market_data import _public_json_get
from qount.dual_engine.market_data import _tiingo_daily
from qount.dual_engine.market_data import _url


YTD_REPLAY_START = dt.date(2026, 1, 1)
_UTC = dt.timezone.utc


@dataclass(frozen=True)
class YtdReplay:
    start_date: str
    end_date: str
    first_observed_at: str
    last_observed_at: str
    cycles: tuple[PaperCycleInput, ...]
    archive_hashes: Mapping[str, str]

    def validate(self) -> None:
        if dt.date.fromisoformat(self.start_date) != YTD_REPLAY_START:
            raise DualEngineMarketDataError("paper_ytd_start_invalid")
        if not self.cycles:
            raise DualEngineMarketDataError("paper_ytd_cycles_empty")
        if self.first_observed_at != self.cycles[0].observed_at:
            raise DualEngineMarketDataError("paper_ytd_first_time_invalid")
        if self.last_observed_at != self.cycles[-1].observed_at:
            raise DualEngineMarketDataError("paper_ytd_last_time_invalid")
        previous: dt.datetime | None = None
        for cycle in self.cycles:
            cycle.validate()
            observed = aware_datetime(cycle.observed_at)
            if previous is not None and observed <= previous:
                raise DualEngineMarketDataError("paper_ytd_cycle_order_invalid")
            previous = observed
        if not self.cycles[0].g20_rebalance_day:
            raise DualEngineMarketDataError("paper_ytd_bootstrap_event_invalid")
        if set(self.archive_hashes) != {
            "tiingo_public_archive",
            "binance_public_archive",
            "binance_exchange_rules",
        }:
            raise DualEngineMarketDataError("paper_ytd_archive_hashes_invalid")


def _date(value: object, *, name: str) -> dt.date:
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError) as exc:
        raise DualEngineMarketDataError(f"{name}_invalid") from exc


def _utc_ms(value: dt.datetime) -> int:
    return int(value.timestamp() * 1000)


def _load_tiingo_archive(
    config: DualEngineMarketConfig,
    *,
    start: dt.date,
    end: dt.date,
    token: str,
    getter: JsonGetter,
) -> tuple[dict[str, list[Mapping[str, Any]]], str]:
    archive: dict[str, list[Mapping[str, Any]]] = {}
    hashes: dict[str, str] = {}
    for symbol in (*G20_PROXY_SYMBOLS, *G20_EXECUTION_SYMBOLS, "BIL"):
        rows, payload_hash = _tiingo_daily(
            symbol,
            start=start,
            end=end,
            token=token,
            config=config,
            getter=getter,
        )
        normalized: list[Mapping[str, Any]] = []
        seen: set[dt.date] = set()
        for row in rows:
            session = _date(row.get("date"), name=f"paper_ytd_tiingo_date:{symbol}")
            if session in seen:
                raise DualEngineMarketDataError(
                    f"paper_ytd_tiingo_duplicate:{symbol}:{session}"
                )
            seen.add(session)
            normalized.append(row)
        archive[symbol] = normalized
        hashes[symbol] = payload_hash
    return archive, canonical_hash(hashes)


def _load_binance_archive(
    config: DualEngineMarketConfig,
    *,
    start: dt.date,
    end: dt.date,
    getter: JsonGetter,
) -> tuple[dict[str, dict[dt.date, list[Any]]], str]:
    archive: dict[str, dict[dt.date, list[Any]]] = {}
    hashes: dict[str, str] = {}
    start_at = dt.datetime.combine(start, dt.time(), tzinfo=_UTC)
    end_at = dt.datetime.combine(end + dt.timedelta(days=2), dt.time(), tzinfo=_UTC)
    for symbol in C60_SYMBOLS:
        payload, payload_hash = getter(
            _url(
                BINANCE_BASE_URL,
                "/api/v3/klines",
                {
                    "symbol": symbol,
                    "interval": "1d",
                    "startTime": _utc_ms(start_at),
                    "endTime": _utc_ms(end_at) - 1,
                    "limit": 1000,
                },
            ),
            {},
            config.timeout_seconds,
        )
        if not isinstance(payload, list):
            raise DualEngineMarketDataError(
                f"paper_ytd_binance_klines_invalid:{symbol}"
            )
        rows: dict[dt.date, list[Any]] = {}
        for row in payload:
            if not isinstance(row, list) or len(row) < 7:
                continue
            session = dt.datetime.fromtimestamp(int(row[0]) / 1000, tz=_UTC).date()
            if session in rows:
                raise DualEngineMarketDataError(
                    f"paper_ytd_binance_duplicate:{symbol}:{session}"
                )
            rows[session] = row
        if len(rows) < 92:
            raise DualEngineMarketDataError(
                f"paper_ytd_binance_history_short:{symbol}"
            )
        archive[symbol] = rows
        hashes[symbol] = payload_hash
    return archive, canonical_hash(hashes)


def _tiingo_rows(
    archive: Mapping[str, list[Mapping[str, Any]]],
    symbol: str,
    *,
    before: dt.date,
    inclusive: bool,
) -> list[Mapping[str, Any]]:
    rows = []
    for row in archive[symbol]:
        session = _date(
            row.get("date"), name=f"paper_ytd_tiingo_date:{symbol}"
        )
        matches = session <= before if inclusive else session < before
        if matches:
            rows.append(row)
    if not rows:
        raise DualEngineMarketDataError(f"paper_ytd_tiingo_missing:{symbol}:{before}")
    return rows


def _proxy_closes(
    archive: Mapping[str, list[Mapping[str, Any]]],
    *,
    before: dt.date,
    inclusive: bool,
) -> dict[str, tuple[float, ...]]:
    result: dict[str, tuple[float, ...]] = {}
    for symbol in G20_PROXY_SYMBOLS:
        rows = _tiingo_rows(archive, symbol, before=before, inclusive=inclusive)[-100:]
        if len(rows) < 64:
            raise DualEngineMarketDataError(
                f"paper_ytd_tiingo_history_short:{symbol}:{before}"
            )
        result[symbol] = tuple(
            _number(
                row.get("adjClose") or row.get("close"),
                name=f"paper_ytd_tiingo_close:{symbol}",
            )
            for row in rows
        )
    return result


def _crypto_closes(
    archive: Mapping[str, Mapping[dt.date, list[Any]]],
    *,
    through: dt.date,
) -> dict[str, tuple[float, ...]]:
    result: dict[str, tuple[float, ...]] = {}
    for symbol in C60_SYMBOLS:
        rows = [
            row
            for session, row in sorted(archive[symbol].items())
            if session <= through
        ][-100:]
        if len(rows) < 91:
            raise DualEngineMarketDataError(
                f"paper_ytd_binance_history_short:{symbol}:{through}"
            )
        result[symbol] = tuple(
            _number(row[4], name=f"paper_ytd_binance_close:{symbol}")
            for row in rows
        )
    return result


def _daily_cycle(
    config: DualEngineMarketConfig,
    *,
    session: dt.date,
    tiingo: Mapping[str, list[Mapping[str, Any]]],
    binance: Mapping[str, Mapping[dt.date, list[Any]]],
    symbol_rules: Mapping[str, Mapping[str, float]],
    archive_hashes: Mapping[str, str],
) -> PaperCycleInput:
    next_session = session + dt.timedelta(days=1)
    cutoff = dt.datetime.combine(next_session, dt.time(), tzinfo=_UTC)
    observed = cutoff + dt.timedelta(seconds=5)
    signal_day = session.isoformat() in config.g20_signal_dates
    marks: dict[str, float] = {}
    fills: dict[str, float] = {}
    for symbol in (*G20_EXECUTION_SYMBOLS, "BIL"):
        rows = _tiingo_rows(tiingo, symbol, before=session, inclusive=True)
        if signal_day and _date(
            rows[-1].get("date"), name=f"paper_ytd_signal_date:{symbol}"
        ) != session:
            raise DualEngineMarketDataError(
                f"paper_ytd_signal_close_missing:{symbol}:{session}"
            )
        close = _number(
            rows[-1].get("close"), name=f"paper_ytd_tiingo_mark:{symbol}"
        )
        marks[symbol] = close
        fills[symbol] = close
    for symbol in C60_SYMBOLS:
        try:
            next_row = binance[symbol][next_session]
        except KeyError as exc:
            raise DualEngineMarketDataError(
                f"paper_ytd_binance_fill_missing:{symbol}:{next_session}"
            ) from exc
        fill = _number(next_row[1], name=f"paper_ytd_binance_open:{symbol}")
        marks[symbol] = fill
        fills[symbol] = fill
    source_hashes = {
        "tiingo_public": canonical_hash(
            {"archive": archive_hashes["tiingo_public_archive"], "session": session.isoformat()}
        ),
        "binance_public": canonical_hash(
            {"archive": archive_hashes["binance_public_archive"], "session": session.isoformat()}
        ),
        "binance_exchange_rules": archive_hashes["binance_exchange_rules"],
    }
    return PaperCycleInput.create(
        observed_at=observed.isoformat(),
        decision_time=observed.isoformat(),
        data_cutoff=cutoff.isoformat(),
        proxy_closes=_proxy_closes(tiingo, before=session, inclusive=True),
        crypto_closes=_crypto_closes(binance, through=session),
        mark_prices=marks,
        fill_prices=fills,
        symbol_rules=symbol_rules,
        source_hashes=source_hashes,
        g20_signal_day=signal_day,
        g20_rebalance_day=False,
    )


def _binance_minute_open(
    symbol: str,
    *,
    observed: dt.datetime,
    config: DualEngineMarketConfig,
    getter: JsonGetter,
) -> tuple[float, str]:
    start = observed - dt.timedelta(minutes=2)
    payload, payload_hash = getter(
        _url(
            BINANCE_BASE_URL,
            "/api/v3/klines",
            {
                "symbol": symbol,
                "interval": "1m",
                "startTime": _utc_ms(start),
                "endTime": _utc_ms(observed),
                "limit": 3,
            },
        ),
        {},
        config.timeout_seconds,
    )
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], list):
        raise DualEngineMarketDataError(
            f"paper_ytd_binance_minute_missing:{symbol}"
        )
    return (
        _number(payload[0][1], name=f"paper_ytd_binance_minute_open:{symbol}"),
        payload_hash,
    )


def _g20_cycle(
    config: DualEngineMarketConfig,
    *,
    session: dt.date,
    tiingo: Mapping[str, list[Mapping[str, Any]]],
    binance: Mapping[str, Mapping[dt.date, list[Any]]],
    symbol_rules: Mapping[str, Mapping[str, float]],
    archive_hashes: Mapping[str, str],
    getter: JsonGetter,
) -> PaperCycleInput:
    observed = dt.datetime.combine(
        session,
        dt.time(hour=15, second=30),
        tzinfo=_UTC,
    )
    cutoff = observed
    previous_crypto = (observed - dt.timedelta(days=1)).date()
    marks: dict[str, float] = {}
    fills: dict[str, float] = {}
    tiingo_open_hashes: dict[str, str] = {}
    binance_intraday_hashes: dict[str, str] = {}
    for symbol in (*G20_EXECUTION_SYMBOLS, "BIL"):
        rows = _tiingo_rows(
            tiingo,
            symbol,
            before=session,
            inclusive=True,
        )
        row = rows[-1]
        if _date(
            row.get("date"), name=f"paper_ytd_g20_open_date:{symbol}"
        ) != session:
            raise DualEngineMarketDataError(
                f"paper_ytd_g20_open_missing:{symbol}:{session}"
            )
        fill = _number(row.get("open"), name=f"paper_ytd_g20_open:{symbol}")
        marks[symbol] = fill
        fills[symbol] = fill
        tiingo_open_hashes[symbol] = canonical_hash(
            {"session": session.isoformat(), "symbol": symbol, "row": row}
        )
    for symbol in C60_SYMBOLS:
        fill, payload_hash = _binance_minute_open(
            symbol,
            observed=observed,
            config=config,
            getter=getter,
        )
        marks[symbol] = fill
        fills[symbol] = fill
        binance_intraday_hashes[symbol] = payload_hash
    source_hashes = {
        "tiingo_public": canonical_hash({
            "archive": archive_hashes["tiingo_public_archive"],
            "daily_open": tiingo_open_hashes,
            "session": session.isoformat(),
        }),
        "binance_public": canonical_hash({
            "archive": archive_hashes["binance_public_archive"],
            "intraday": binance_intraday_hashes,
            "session": session.isoformat(),
        }),
        "binance_exchange_rules": archive_hashes["binance_exchange_rules"],
    }
    return PaperCycleInput.create(
        observed_at=observed.isoformat(),
        decision_time=observed.isoformat(),
        data_cutoff=cutoff.isoformat(),
        proxy_closes=_proxy_closes(tiingo, before=session, inclusive=False),
        crypto_closes=_crypto_closes(binance, through=previous_crypto),
        mark_prices=marks,
        fill_prices=fills,
        symbol_rules=symbol_rules,
        source_hashes=source_hashes,
        g20_signal_day=False,
        g20_rebalance_day=True,
    )


def collect_ytd_replay(
    config: DualEngineMarketConfig,
    *,
    start_date: dt.date = YTD_REPLAY_START,
    end_date: dt.date,
    getter: JsonGetter = _public_json_get,
    environment: Mapping[str, str] | None = None,
) -> YtdReplay:
    """Collect a bounded 2026 replay with no account, broker, or order access."""

    config.validate()
    if start_date != YTD_REPLAY_START or end_date < start_date:
        raise DualEngineMarketDataError("paper_ytd_range_invalid")
    token = (environment or os.environ).get(config.tiingo_token_env, "")
    if not token:
        raise DualEngineMarketDataError("paper_tiingo_token_missing")
    history_start = start_date - dt.timedelta(days=config.history_calendar_days)
    tiingo, tiingo_hash = _load_tiingo_archive(
        config,
        start=history_start,
        end=end_date,
        token=token,
        getter=getter,
    )
    binance, binance_hash = _load_binance_archive(
        config,
        start=history_start,
        end=end_date,
        getter=getter,
    )
    symbol_rules, rules_hash = _binance_rules(config=config, getter=getter)
    for symbol in (*G20_EXECUTION_SYMBOLS, "BIL"):
        symbol_rules[symbol] = {"step_size": 1.0, "minimum_notional": 0.0}
    archive_hashes = {
        "tiingo_public_archive": tiingo_hash,
        "binance_public_archive": binance_hash,
        "binance_exchange_rules": rules_hash,
    }
    rebalance_dates = [
        dt.date.fromisoformat(value)
        for value in config.g20_rebalance_dates
        if start_date <= dt.date.fromisoformat(value) <= end_date
    ]
    if not rebalance_dates:
        raise DualEngineMarketDataError("paper_ytd_rebalance_dates_missing")
    events: list[PaperCycleInput] = [
        _g20_cycle(
            config,
            session=session,
            tiingo=tiingo,
            binance=binance,
            symbol_rules=symbol_rules,
            archive_hashes=archive_hashes,
            getter=getter,
        )
        for session in rebalance_dates
    ]
    first_event_date = rebalance_dates[0]
    session = max(start_date, first_event_date)
    while session <= end_date:
        events.append(
            _daily_cycle(
                config,
                session=session,
                tiingo=tiingo,
                binance=binance,
                symbol_rules=symbol_rules,
                archive_hashes=archive_hashes,
            )
        )
        session += dt.timedelta(days=1)
    events.sort(key=lambda cycle: aware_datetime(cycle.observed_at))
    replay = YtdReplay(
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        first_observed_at=events[0].observed_at,
        last_observed_at=events[-1].observed_at,
        cycles=tuple(events),
        archive_hashes=archive_hashes,
    )
    replay.validate()
    return replay


__all__ = ["YTD_REPLAY_START", "YtdReplay", "collect_ytd_replay"]
