"""Immutable event clock, freeze snapshot, and signal scan for FOMC v0.2."""

from __future__ import annotations

import datetime as dt
import math
import re
import statistics
from dataclasses import dataclass
from numbers import Real
from typing import Any, Mapping, Sequence

from qount.contracts import canonical_hash
from qount.contracts import is_sha256
from qount.contracts import trace_id
from qount.contracts.trace import aware_datetime
from qount.small_account.event_signal import CompletedCandle
from qount.small_account.event_signal import DEFAULT_FOMC_SIGNAL_POLICY
from qount.small_account.event_signal import FomcSignalDecision
from qount.small_account.event_signal import FomcSignalPolicy
from qount.small_account.event_signal import SIGNAL_CONTRACT_VERSION
from qount.small_account.event_signal import evaluate_fomc_hybrid_signal


FOMC_EVENT_SCHEMA_VERSION = 1
FOMC_FREEZE_SCHEMA_VERSION = 1
FOMC_SCAN_SCHEMA_VERSION = 1
FOMC_STRATEGY_ID = "SmallAccount-FOMC-RightSide"
FOMC_STRATEGY_VERSION = "0.2"
FOMC_STAGES = (
    "SCHEDULED",
    "FREEZE_REQUIRED",
    "EVENT_FROZEN",
    "BLACKOUT",
    "OBSERVE",
    "ARMED",
    "NO_TRADE",
    "EXPIRED",
    "HALTED",
)

_EVENT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,95}$")
_EPSILON = 1e-12


class FomcRuntimeError(ValueError):
    """Raised when event data cannot satisfy the frozen FOMC contract."""


def _finite(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, Real)
        and math.isfinite(float(value))
    )


def _utc(value: str | dt.datetime, *, name: str) -> dt.datetime:
    try:
        parsed = value if isinstance(value, dt.datetime) else aware_datetime(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise FomcRuntimeError(f"{name}_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FomcRuntimeError(f"{name}_invalid")
    return parsed.astimezone(dt.timezone.utc)


def _iso(value: str | dt.datetime, *, name: str) -> str:
    return _utc(value, name=name).isoformat()


def _candle_core(candle: CompletedCandle) -> dict[str, Any]:
    return {
        "interval_minutes": candle.interval_minutes,
        "closed_at": candle.closed_at.astimezone(dt.timezone.utc).isoformat(),
        "open": float(candle.open),
        "high": float(candle.high),
        "low": float(candle.low),
        "close": float(candle.close),
        "volume": float(candle.volume),
    }


def candle_id(candle: CompletedCandle) -> str:
    errors = candle.validate() if isinstance(candle, CompletedCandle) else ("invalid",)
    if errors:
        raise FomcRuntimeError("fomc_candle_invalid:" + ",".join(errors))
    return trace_id("fomc_completed_candle", _candle_core(candle))


@dataclass(frozen=True)
class FomcEventDefinition:
    schema_version: int
    event_id: str
    event_name: str
    strategy_id: str
    strategy_version: str
    instrument_key: str
    symbol: str
    source_url: str
    source_hash: str
    cash_only_from: str
    freeze_at: str
    statement_at: str
    press_conference_at: str
    observation_starts_at: str
    entry_cutoff_at: str
    force_exit_at: str
    definition_hash: str

    @classmethod
    def create(
        cls,
        *,
        event_name: str,
        instrument_key: str,
        symbol: str,
        source_url: str,
        source_hash: str,
        cash_only_from: str,
        freeze_at: str,
        statement_at: str,
        press_conference_at: str,
        observation_starts_at: str,
        entry_cutoff_at: str,
        force_exit_at: str,
        strategy_id: str = FOMC_STRATEGY_ID,
        strategy_version: str = FOMC_STRATEGY_VERSION,
    ) -> "FomcEventDefinition":
        core = {
            "schema_version": FOMC_EVENT_SCHEMA_VERSION,
            "event_name": str(event_name),
            "strategy_id": str(strategy_id),
            "strategy_version": str(strategy_version),
            "instrument_key": str(instrument_key),
            "symbol": str(symbol).upper(),
            "source_url": str(source_url),
            "source_hash": str(source_hash),
            "cash_only_from": _iso(cash_only_from, name="cash_only_from"),
            "freeze_at": _iso(freeze_at, name="freeze_at"),
            "statement_at": _iso(statement_at, name="statement_at"),
            "press_conference_at": _iso(
                press_conference_at, name="press_conference_at"
            ),
            "observation_starts_at": _iso(
                observation_starts_at, name="observation_starts_at"
            ),
            "entry_cutoff_at": _iso(entry_cutoff_at, name="entry_cutoff_at"),
            "force_exit_at": _iso(force_exit_at, name="force_exit_at"),
        }
        definition_hash = canonical_hash(core)
        event = cls(
            **core,
            event_id=trace_id(
                "fomc_event",
                {
                    "event_name": core["event_name"],
                    "statement_at": core["statement_at"],
                    "definition_hash": definition_hash,
                },
            ),
            definition_hash=definition_hash,
        )
        errors = event.validate()
        if errors:
            raise FomcRuntimeError("fomc_event_invalid:" + ",".join(errors))
        return event

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "FomcEventDefinition":
        required = {
            "event_name",
            "strategy_id",
            "strategy_version",
            "instrument_key",
            "symbol",
            "source_url",
            "source_hash",
            "cash_only_from",
            "freeze_at",
            "statement_at",
            "press_conference_at",
            "observation_starts_at",
            "entry_cutoff_at",
            "force_exit_at",
        }
        missing = sorted(required - set(value))
        if missing:
            raise FomcRuntimeError("fomc_event_fields_missing:" + ",".join(missing))
        return cls.create(
            event_name=str(value["event_name"]),
            instrument_key=str(value["instrument_key"]),
            symbol=str(value["symbol"]),
            source_url=str(value["source_url"]),
            source_hash=str(value["source_hash"]),
            cash_only_from=str(value["cash_only_from"]),
            freeze_at=str(value["freeze_at"]),
            statement_at=str(value["statement_at"]),
            press_conference_at=str(value["press_conference_at"]),
            observation_starts_at=str(value["observation_starts_at"]),
            entry_cutoff_at=str(value["entry_cutoff_at"]),
            force_exit_at=str(value["force_exit_at"]),
            strategy_id=str(value["strategy_id"]),
            strategy_version=str(value["strategy_version"]),
        )

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_name": self.event_name,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "instrument_key": self.instrument_key,
            "symbol": self.symbol,
            "source_url": self.source_url,
            "source_hash": self.source_hash,
            "cash_only_from": self.cash_only_from,
            "freeze_at": self.freeze_at,
            "statement_at": self.statement_at,
            "press_conference_at": self.press_conference_at,
            "observation_starts_at": self.observation_starts_at,
            "entry_cutoff_at": self.entry_cutoff_at,
            "force_exit_at": self.force_exit_at,
        }

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.schema_version != FOMC_EVENT_SCHEMA_VERSION:
            errors.append("event_schema_version_invalid")
        for name in ("event_name", "strategy_id", "strategy_version"):
            if not _EVENT_NAME_RE.fullmatch(str(getattr(self, name))):
                errors.append(f"event_{name}_invalid")
        if (
            self.strategy_id != FOMC_STRATEGY_ID
            or self.strategy_version != FOMC_STRATEGY_VERSION
        ):
            errors.append("event_strategy_identity_invalid")
        if not self.instrument_key or not self.symbol:
            errors.append("event_instrument_invalid")
        if not self.source_url.startswith("https://"):
            errors.append("event_source_url_invalid")
        if not is_sha256(self.source_hash):
            errors.append("event_source_hash_invalid")
        time_names = (
            "cash_only_from",
            "freeze_at",
            "statement_at",
            "press_conference_at",
            "observation_starts_at",
            "entry_cutoff_at",
            "force_exit_at",
        )
        parsed: list[dt.datetime] = []
        for name in time_names:
            try:
                parsed.append(_utc(getattr(self, name), name=name))
            except FomcRuntimeError:
                errors.append(f"event_{name}_invalid")
        if len(parsed) == len(time_names):
            if any(later <= earlier for earlier, later in zip(parsed, parsed[1:])):
                errors.append("event_clock_order_invalid")
            if self.freeze_time - self.cash_only_time > dt.timedelta(hours=1):
                errors.append("event_freeze_window_invalid")
            if self.observation_time - self.statement_time < dt.timedelta(hours=4):
                errors.append("event_blackout_too_short")
        expected_hash = canonical_hash(self._core())
        if self.definition_hash != expected_hash:
            errors.append("event_definition_hash_invalid")
        expected_id = trace_id(
            "fomc_event",
            {
                "event_name": self.event_name,
                "statement_at": self.statement_at,
                "definition_hash": expected_hash,
            },
        )
        if self.event_id != expected_id:
            errors.append("event_id_invalid")
        return tuple(dict.fromkeys(errors))

    @property
    def cash_only_time(self) -> dt.datetime:
        return _utc(self.cash_only_from, name="cash_only_from")

    @property
    def freeze_time(self) -> dt.datetime:
        return _utc(self.freeze_at, name="freeze_at")

    @property
    def statement_time(self) -> dt.datetime:
        return _utc(self.statement_at, name="statement_at")

    @property
    def observation_time(self) -> dt.datetime:
        return _utc(self.observation_starts_at, name="observation_starts_at")

    @property
    def entry_cutoff_time(self) -> dt.datetime:
        return _utc(self.entry_cutoff_at, name="entry_cutoff_at")

    @property
    def force_exit_time(self) -> dt.datetime:
        return _utc(self.force_exit_at, name="force_exit_at")

    def as_dict(self) -> dict[str, Any]:
        return self._core() | {
            "event_id": self.event_id,
            "definition_hash": self.definition_hash,
        }


@dataclass(frozen=True)
class FomcFreezeSnapshot:
    schema_version: int
    freeze_id: str
    event_id: str
    symbol: str
    frozen_at: str
    data_cutoff: str
    h0: float
    l0: float
    atr0: float
    v20_1h: float
    v20_15m: float
    pivot_highs: tuple[float, ...]
    pivot_lows: tuple[float, ...]
    hourly_candle_count: int
    fifteen_minute_candle_count: int
    hourly_candle_hash: str
    fifteen_minute_candle_hash: str
    exchange_rules_hash: str
    source_hashes: Mapping[str, str]
    freeze_hash: str

    @classmethod
    def create(
        cls,
        *,
        event_id: str,
        symbol: str,
        frozen_at: str,
        data_cutoff: str,
        h0: float,
        l0: float,
        atr0: float,
        v20_1h: float,
        v20_15m: float,
        pivot_highs: Sequence[float],
        pivot_lows: Sequence[float],
        hourly_candle_count: int,
        fifteen_minute_candle_count: int,
        hourly_candle_hash: str,
        fifteen_minute_candle_hash: str,
        exchange_rules_hash: str,
        source_hashes: Mapping[str, str],
    ) -> "FomcFreezeSnapshot":
        core = {
            "schema_version": FOMC_FREEZE_SCHEMA_VERSION,
            "event_id": str(event_id),
            "symbol": str(symbol).upper(),
            "frozen_at": _iso(frozen_at, name="frozen_at"),
            "data_cutoff": _iso(data_cutoff, name="data_cutoff"),
            "h0": float(h0),
            "l0": float(l0),
            "atr0": float(atr0),
            "v20_1h": float(v20_1h),
            "v20_15m": float(v20_15m),
            "pivot_highs": tuple(sorted({float(value) for value in pivot_highs})),
            "pivot_lows": tuple(sorted({float(value) for value in pivot_lows})),
            "hourly_candle_count": int(hourly_candle_count),
            "fifteen_minute_candle_count": int(fifteen_minute_candle_count),
            "hourly_candle_hash": str(hourly_candle_hash),
            "fifteen_minute_candle_hash": str(fifteen_minute_candle_hash),
            "exchange_rules_hash": str(exchange_rules_hash),
            "source_hashes": dict(sorted((str(k), str(v)) for k, v in source_hashes.items())),
        }
        freeze_hash = canonical_hash(core)
        snapshot = cls(
            **core,
            freeze_id=trace_id(
                "fomc_freeze",
                {"event_id": event_id, "freeze_hash": freeze_hash},
            ),
            freeze_hash=freeze_hash,
        )
        errors = snapshot.validate()
        if errors:
            raise FomcRuntimeError("fomc_freeze_invalid:" + ",".join(errors))
        return snapshot

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "FomcFreezeSnapshot":
        rebuilt = cls.create(
            event_id=str(value["event_id"]),
            symbol=str(value["symbol"]),
            frozen_at=str(value["frozen_at"]),
            data_cutoff=str(value["data_cutoff"]),
            h0=float(value["h0"]),
            l0=float(value["l0"]),
            atr0=float(value["atr0"]),
            v20_1h=float(value["v20_1h"]),
            v20_15m=float(value["v20_15m"]),
            pivot_highs=tuple(value["pivot_highs"]),
            pivot_lows=tuple(value["pivot_lows"]),
            hourly_candle_count=int(value["hourly_candle_count"]),
            fifteen_minute_candle_count=int(value["fifteen_minute_candle_count"]),
            hourly_candle_hash=str(value["hourly_candle_hash"]),
            fifteen_minute_candle_hash=str(value["fifteen_minute_candle_hash"]),
            exchange_rules_hash=str(value["exchange_rules_hash"]),
            source_hashes=dict(value["source_hashes"]),
        )
        if (
            value.get("freeze_id") != rebuilt.freeze_id
            or value.get("freeze_hash") != rebuilt.freeze_hash
            or value.get("schema_version") != rebuilt.schema_version
        ):
            raise FomcRuntimeError("fomc_freeze_hash_mismatch")
        return rebuilt

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "symbol": self.symbol,
            "frozen_at": self.frozen_at,
            "data_cutoff": self.data_cutoff,
            "h0": self.h0,
            "l0": self.l0,
            "atr0": self.atr0,
            "v20_1h": self.v20_1h,
            "v20_15m": self.v20_15m,
            "pivot_highs": tuple(self.pivot_highs),
            "pivot_lows": tuple(self.pivot_lows),
            "hourly_candle_count": self.hourly_candle_count,
            "fifteen_minute_candle_count": self.fifteen_minute_candle_count,
            "hourly_candle_hash": self.hourly_candle_hash,
            "fifteen_minute_candle_hash": self.fifteen_minute_candle_hash,
            "exchange_rules_hash": self.exchange_rules_hash,
            "source_hashes": dict(self.source_hashes),
        }

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.schema_version != FOMC_FREEZE_SCHEMA_VERSION:
            errors.append("freeze_schema_version_invalid")
        for name in (
            "freeze_id",
            "event_id",
            "hourly_candle_hash",
            "fifteen_minute_candle_hash",
            "exchange_rules_hash",
            "freeze_hash",
        ):
            if not is_sha256(getattr(self, name)):
                errors.append(f"freeze_{name}_invalid")
        try:
            frozen = _utc(self.frozen_at, name="frozen_at")
            cutoff = _utc(self.data_cutoff, name="data_cutoff")
            if cutoff > frozen:
                errors.append("freeze_data_cutoff_after_freeze")
        except FomcRuntimeError:
            errors.append("freeze_time_invalid")
        for name in ("h0", "l0", "atr0", "v20_1h", "v20_15m"):
            if not _finite(getattr(self, name)) or float(getattr(self, name)) <= 0.0:
                errors.append(f"freeze_{name}_invalid")
        if _finite(self.h0) and _finite(self.l0) and self.h0 <= self.l0:
            errors.append("freeze_range_invalid")
        for name, values in (
            ("pivot_highs", self.pivot_highs),
            ("pivot_lows", self.pivot_lows),
        ):
            if tuple(sorted(set(values))) != values or any(
                not _finite(value) or value <= 0.0 for value in values
            ):
                errors.append(f"freeze_{name}_invalid")
        if self.hourly_candle_count < 720:
            errors.append("freeze_hourly_history_insufficient")
        if self.fifteen_minute_candle_count < 20:
            errors.append("freeze_fifteen_minute_history_insufficient")
        if not self.source_hashes or any(
            not key or not is_sha256(value)
            for key, value in self.source_hashes.items()
        ):
            errors.append("freeze_source_hashes_invalid")
        expected_hash = canonical_hash(self._core())
        if self.freeze_hash != expected_hash:
            errors.append("freeze_hash_invalid")
        expected_id = trace_id(
            "fomc_freeze",
            {"event_id": self.event_id, "freeze_hash": expected_hash},
        )
        if self.freeze_id != expected_id:
            errors.append("freeze_id_invalid")
        return tuple(dict.fromkeys(errors))

    def as_dict(self) -> dict[str, Any]:
        return self._core() | {
            "freeze_id": self.freeze_id,
            "freeze_hash": self.freeze_hash,
        }


def _validated_completed_candles(
    candles: Sequence[CompletedCandle],
    *,
    interval_minutes: int,
    cutoff: dt.datetime,
    name: str,
) -> tuple[CompletedCandle, ...]:
    if not isinstance(candles, Sequence) or isinstance(candles, (str, bytes)):
        raise FomcRuntimeError(f"{name}_sequence_invalid")
    completed: list[CompletedCandle] = []
    for index, candle in enumerate(candles):
        if not isinstance(candle, CompletedCandle):
            raise FomcRuntimeError(f"{name}_{index}_invalid")
        errors = candle.validate()
        if errors:
            raise FomcRuntimeError(
                f"{name}_{index}_invalid:" + ",".join(errors)
            )
        if candle.interval_minutes != interval_minutes:
            raise FomcRuntimeError(f"{name}_{index}_interval_invalid")
        if candle.closed_at.astimezone(dt.timezone.utc) <= cutoff:
            completed.append(candle)
    if any(
        later.closed_at <= earlier.closed_at
        for earlier, later in zip(completed, completed[1:])
    ):
        raise FomcRuntimeError(f"{name}_not_strictly_ordered")
    if len({candle.closed_at for candle in completed}) != len(completed):
        raise FomcRuntimeError(f"{name}_duplicate_close")
    return tuple(completed)


def _confirmed_pivots(
    candles: Sequence[CompletedCandle],
    *,
    field: str,
    wing: int = 3,
) -> tuple[float, ...]:
    values = [float(getattr(candle, field)) for candle in candles]
    pivots: list[float] = []
    for index in range(wing, len(values) - wing):
        center = values[index]
        left = values[index - wing : index]
        right = values[index + 1 : index + wing + 1]
        if field == "high" and all(center > value for value in (*left, *right)):
            pivots.append(center)
        if field == "low" and all(center < value for value in (*left, *right)):
            pivots.append(center)
    return tuple(sorted(set(pivots)))


def build_fomc_freeze_snapshot(
    event: FomcEventDefinition,
    *,
    hourly_candles: Sequence[CompletedCandle],
    fifteen_minute_candles: Sequence[CompletedCandle],
    exchange_rules_hash: str,
    source_hashes: Mapping[str, str],
) -> FomcFreezeSnapshot:
    """Freeze the last known pre-event range without using future candles."""

    event_errors = event.validate() if isinstance(event, FomcEventDefinition) else ("invalid",)
    if event_errors:
        raise FomcRuntimeError("fomc_event_invalid:" + ",".join(event_errors))
    hourly = _validated_completed_candles(
        hourly_candles,
        interval_minutes=60,
        cutoff=event.freeze_time,
        name="freeze_hourly",
    )
    fifteen = _validated_completed_candles(
        fifteen_minute_candles,
        interval_minutes=15,
        cutoff=event.freeze_time,
        name="freeze_fifteen_minute",
    )
    if len(hourly) < 720:
        raise FomcRuntimeError("freeze_hourly_history_insufficient")
    if len(fifteen) < 20:
        raise FomcRuntimeError("freeze_fifteen_minute_history_insufficient")
    if event.freeze_time - hourly[-1].closed_at > dt.timedelta(hours=1):
        raise FomcRuntimeError("freeze_hourly_data_stale")
    if event.freeze_time - fifteen[-1].closed_at > dt.timedelta(minutes=15):
        raise FomcRuntimeError("freeze_fifteen_minute_data_stale")

    range_bars = hourly[-72:]
    atr_bars = hourly[-15:]
    true_ranges = []
    for previous, current in zip(atr_bars, atr_bars[1:]):
        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    pivot_bars = hourly[-720:]
    data_cutoff = max(hourly[-1].closed_at, fifteen[-1].closed_at)
    hourly_hash = canonical_hash(
        {"interval": "1h", "candles": [_candle_core(candle) for candle in pivot_bars]}
    )
    fifteen_hash = canonical_hash(
        {
            "interval": "15m",
            "candles": [_candle_core(candle) for candle in fifteen],
        }
    )
    normalized_sources = dict(source_hashes)
    normalized_sources.setdefault("event_definition", event.definition_hash)
    normalized_sources.setdefault("hourly_candles", hourly_hash)
    normalized_sources.setdefault("fifteen_minute_candles", fifteen_hash)
    return FomcFreezeSnapshot.create(
        event_id=event.event_id,
        symbol=event.symbol,
        frozen_at=event.freeze_at,
        data_cutoff=data_cutoff.isoformat(),
        h0=max(candle.high for candle in range_bars),
        l0=min(candle.low for candle in range_bars),
        atr0=sum(true_ranges) / len(true_ranges),
        v20_1h=statistics.median(candle.volume for candle in hourly[-20:]),
        v20_15m=statistics.median(candle.volume for candle in fifteen[-20:]),
        pivot_highs=_confirmed_pivots(pivot_bars, field="high"),
        pivot_lows=_confirmed_pivots(pivot_bars, field="low"),
        hourly_candle_count=len(hourly),
        fifteen_minute_candle_count=len(fifteen),
        hourly_candle_hash=hourly_hash,
        fifteen_minute_candle_hash=fifteen_hash,
        exchange_rules_hash=exchange_rules_hash,
        source_hashes=normalized_sources,
    )


def frozen_structure_target(
    freeze: FomcFreezeSnapshot,
    *,
    side: str,
    entry_price: float,
) -> float | None:
    if freeze.validate():
        raise FomcRuntimeError("fomc_freeze_invalid")
    if not _finite(entry_price) or entry_price <= 0.0:
        raise FomcRuntimeError("entry_price_invalid")
    if side == "long":
        candidates = [value for value in freeze.pivot_highs if value > entry_price]
        return min(candidates) if candidates else None
    if side == "short":
        candidates = [value for value in freeze.pivot_lows if value < entry_price]
        return max(candidates) if candidates else None
    raise FomcRuntimeError("side_invalid")


@dataclass(frozen=True)
class FomcSignalScan:
    schema_version: int
    event_id: str
    evaluated_at: str
    state: str
    side: str
    reasons: tuple[str, ...]
    breakout_line: float | None
    retest_extreme: float | None
    structural_stop_price: float | None
    anchor_candle_id: str | None
    breakout_candle_id: str | None
    retest_candle_ids: tuple[str, ...]
    signal_available_at: str | None
    scan_hash: str

    @classmethod
    def create(
        cls,
        *,
        event_id: str,
        evaluated_at: str,
        decision: FomcSignalDecision,
        anchor: CompletedCandle | None,
        breakout: CompletedCandle | None,
        retest: Sequence[CompletedCandle],
    ) -> "FomcSignalScan":
        signal_available_at = (
            retest[-1].closed_at.isoformat()
            if retest
            else breakout.closed_at.isoformat()
            if breakout is not None
            else anchor.closed_at.isoformat()
            if anchor is not None
            else None
        )
        core = {
            "schema_version": FOMC_SCAN_SCHEMA_VERSION,
            "event_id": event_id,
            "evaluated_at": _iso(evaluated_at, name="evaluated_at"),
            "state": decision.state,
            "side": decision.side,
            "reasons": tuple(decision.reasons),
            "breakout_line": decision.breakout_line,
            "retest_extreme": decision.retest_extreme,
            "structural_stop_price": decision.structural_stop_price,
            "anchor_candle_id": candle_id(anchor) if anchor is not None else None,
            "breakout_candle_id": candle_id(breakout) if breakout is not None else None,
            "retest_candle_ids": tuple(candle_id(candle) for candle in retest),
            "signal_available_at": signal_available_at,
        }
        scan_hash = canonical_hash(core)
        return cls(**core, scan_hash=scan_hash)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "FomcSignalScan":
        try:
            core = {
                "schema_version": int(value["schema_version"]),
                "event_id": str(value["event_id"]),
                "evaluated_at": _iso(str(value["evaluated_at"]), name="evaluated_at"),
                "state": str(value["state"]),
                "side": str(value["side"]),
                "reasons": tuple(str(item) for item in value["reasons"]),
                "breakout_line": (
                    float(value["breakout_line"])
                    if value.get("breakout_line") is not None
                    else None
                ),
                "retest_extreme": (
                    float(value["retest_extreme"])
                    if value.get("retest_extreme") is not None
                    else None
                ),
                "structural_stop_price": (
                    float(value["structural_stop_price"])
                    if value.get("structural_stop_price") is not None
                    else None
                ),
                "anchor_candle_id": (
                    str(value["anchor_candle_id"])
                    if value.get("anchor_candle_id") is not None
                    else None
                ),
                "breakout_candle_id": (
                    str(value["breakout_candle_id"])
                    if value.get("breakout_candle_id") is not None
                    else None
                ),
                "retest_candle_ids": tuple(
                    str(item) for item in value["retest_candle_ids"]
                ),
                "signal_available_at": (
                    _iso(str(value["signal_available_at"]), name="signal_available_at")
                    if value.get("signal_available_at") is not None
                    else None
                ),
            }
            scan_hash = str(value["scan_hash"])
        except (KeyError, TypeError, ValueError, FomcRuntimeError) as exc:
            raise FomcRuntimeError("fomc_signal_scan_mapping_invalid") from exc
        if core["schema_version"] != FOMC_SCAN_SCHEMA_VERSION:
            raise FomcRuntimeError("fomc_signal_scan_schema_invalid")
        if not is_sha256(core["event_id"]):
            raise FomcRuntimeError("fomc_signal_scan_event_id_invalid")
        if core["state"] not in {"OBSERVE", "ARMED", "NO_TRADE", "EXPIRED"}:
            raise FomcRuntimeError("fomc_signal_scan_state_invalid")
        if core["side"] not in {"long", "short", "none"}:
            raise FomcRuntimeError("fomc_signal_scan_side_invalid")
        identity_values = (
            core["anchor_candle_id"],
            core["breakout_candle_id"],
            *core["retest_candle_ids"],
        )
        if any(item is not None and not is_sha256(item) for item in identity_values):
            raise FomcRuntimeError("fomc_signal_scan_candle_id_invalid")
        if canonical_hash(core) != scan_hash:
            raise FomcRuntimeError("fomc_signal_scan_hash_invalid")
        return cls(**core, scan_hash=scan_hash)

    @property
    def armed(self) -> bool:
        return self.state == "ARMED"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "evaluated_at": self.evaluated_at,
            "state": self.state,
            "side": self.side,
            "reasons": list(self.reasons),
            "breakout_line": self.breakout_line,
            "retest_extreme": self.retest_extreme,
            "structural_stop_price": self.structural_stop_price,
            "anchor_candle_id": self.anchor_candle_id,
            "breakout_candle_id": self.breakout_candle_id,
            "retest_candle_ids": list(self.retest_candle_ids),
            "signal_available_at": self.signal_available_at,
            "scan_hash": self.scan_hash,
        }


def _scan_decision(
    *,
    state: str,
    side: str,
    reasons: Sequence[str],
    breakout_line: float | None,
) -> FomcSignalDecision:
    return FomcSignalDecision(
        contract_version=SIGNAL_CONTRACT_VERSION,
        state=state,  # type: ignore[arg-type]
        side=side,
        reasons=tuple(reasons),
        breakout_line=breakout_line,
        retest_extreme=None,
        structural_stop_price=None,
    )


def scan_fomc_hybrid_signal(
    event: FomcEventDefinition,
    freeze: FomcFreezeSnapshot,
    *,
    hourly_candles: Sequence[CompletedCandle],
    fifteen_minute_candles: Sequence[CompletedCandle],
    planned_entry_price: float,
    evaluated_at: str | dt.datetime,
    policy: FomcSignalPolicy = DEFAULT_FOMC_SIGNAL_POLICY,
) -> FomcSignalScan:
    """Lock the first completed 1h direction anchor and scan one 15m setup."""

    now = _utc(evaluated_at, name="evaluated_at")
    if event.validate() or freeze.validate() or freeze.event_id != event.event_id:
        raise FomcRuntimeError("fomc_event_freeze_mismatch")
    if now < event.observation_time:
        decision = _scan_decision(
            state="OBSERVE",
            side="none",
            reasons=("observation_window_not_open",),
            breakout_line=None,
        )
        return FomcSignalScan.create(
            event_id=event.event_id,
            evaluated_at=now.isoformat(),
            decision=decision,
            anchor=None,
            breakout=None,
            retest=(),
        )
    hourly = _validated_completed_candles(
        hourly_candles,
        interval_minutes=60,
        cutoff=now,
        name="signal_hourly",
    )
    fifteen = _validated_completed_candles(
        fifteen_minute_candles,
        interval_minutes=15,
        cutoff=now,
        name="signal_fifteen_minute",
    )
    long_line = freeze.h0 + policy.breakout_atr_offset * freeze.atr0
    short_line = freeze.l0 - policy.breakout_atr_offset * freeze.atr0
    anchors: list[tuple[dt.datetime, str, CompletedCandle]] = []
    for candle in hourly:
        if candle.closed_at < event.observation_time:
            continue
        if candle.close > long_line:
            anchors.append((candle.closed_at, "long", candle))
        if candle.close < short_line:
            anchors.append((candle.closed_at, "short", candle))
    if not anchors:
        decision = _scan_decision(
            state="OBSERVE",
            side="none",
            reasons=("direction_anchor_missing",),
            breakout_line=None,
        )
        return FomcSignalScan.create(
            event_id=event.event_id,
            evaluated_at=now.isoformat(),
            decision=decision,
            anchor=None,
            breakout=None,
            retest=(),
        )
    anchors.sort(key=lambda row: (row[0], row[1]))
    first_time = anchors[0][0]
    first = [row for row in anchors if row[0] == first_time]
    if len({row[1] for row in first}) != 1:
        decision = _scan_decision(
            state="NO_TRADE",
            side="none",
            reasons=("direction_anchor_ambiguous",),
            breakout_line=None,
        )
        return FomcSignalScan.create(
            event_id=event.event_id,
            evaluated_at=now.isoformat(),
            decision=decision,
            anchor=None,
            breakout=None,
            retest=(),
        )
    _, side, anchor = first[0]
    breakout_line = long_line if side == "long" else short_line
    candidate_bars = tuple(
        candle for candle in fifteen if candle.closed_at >= anchor.closed_at
    )
    for index, breakout in enumerate(candidate_bars):
        preliminary = evaluate_fomc_hybrid_signal(
            side=side,
            h0=freeze.h0,
            l0=freeze.l0,
            atr0=freeze.atr0,
            v20_15m=freeze.v20_15m,
            anchor_1h=anchor,
            breakout_15m=breakout,
            retest_15m=(),
            planned_entry_price=planned_entry_price,
            observation_started_at=event.observation_time,
            entry_cutoff_at=event.entry_cutoff_time,
            evaluated_at=now,
            policy=policy,
        )
        if preliminary.reasons != ("retest_missing",):
            continue
        following = candidate_bars[index + 1 : index + policy.maximum_retest_bars + 2]
        if not following:
            return FomcSignalScan.create(
                event_id=event.event_id,
                evaluated_at=now.isoformat(),
                decision=preliminary,
                anchor=anchor,
                breakout=breakout,
                retest=(),
            )
        latest = preliminary
        maximum = min(len(following), policy.maximum_retest_bars)
        for count in range(1, maximum + 1):
            retest = following[:count]
            latest = evaluate_fomc_hybrid_signal(
                side=side,
                h0=freeze.h0,
                l0=freeze.l0,
                atr0=freeze.atr0,
                v20_15m=freeze.v20_15m,
                anchor_1h=anchor,
                breakout_15m=breakout,
                retest_15m=retest,
                planned_entry_price=planned_entry_price,
                observation_started_at=event.observation_time,
                entry_cutoff_at=event.entry_cutoff_time,
                evaluated_at=now,
                policy=policy,
            )
            if latest.armed or latest.state == "NO_TRADE":
                return FomcSignalScan.create(
                    event_id=event.event_id,
                    evaluated_at=now.isoformat(),
                    decision=latest,
                    anchor=anchor,
                    breakout=breakout,
                    retest=retest,
                )
        if len(following) > policy.maximum_retest_bars:
            expired_retest = following[: policy.maximum_retest_bars + 1]
            expired = evaluate_fomc_hybrid_signal(
                side=side,
                h0=freeze.h0,
                l0=freeze.l0,
                atr0=freeze.atr0,
                v20_15m=freeze.v20_15m,
                anchor_1h=anchor,
                breakout_15m=breakout,
                retest_15m=expired_retest,
                planned_entry_price=planned_entry_price,
                observation_started_at=event.observation_time,
                entry_cutoff_at=event.entry_cutoff_time,
                evaluated_at=now,
                policy=policy,
            )
            return FomcSignalScan.create(
                event_id=event.event_id,
                evaluated_at=now.isoformat(),
                decision=expired,
                anchor=anchor,
                breakout=breakout,
                retest=expired_retest,
            )
        return FomcSignalScan.create(
            event_id=event.event_id,
            evaluated_at=now.isoformat(),
            decision=latest,
            anchor=anchor,
            breakout=breakout,
            retest=following,
        )

    decision = _scan_decision(
        state="OBSERVE",
        side=side,
        reasons=("qualified_breakout_missing",),
        breakout_line=breakout_line,
    )
    return FomcSignalScan.create(
        event_id=event.event_id,
        evaluated_at=now.isoformat(),
        decision=decision,
        anchor=anchor,
        breakout=None,
        retest=(),
    )


def fomc_stage(
    event: FomcEventDefinition,
    *,
    evaluated_at: str | dt.datetime,
    freeze_available: bool,
    scan: FomcSignalScan | None = None,
    halted: bool = False,
) -> str:
    now = _utc(evaluated_at, name="evaluated_at")
    if halted:
        return "HALTED"
    if now < event.freeze_time:
        return "SCHEDULED"
    if not freeze_available:
        return "FREEZE_REQUIRED"
    if now < event.statement_time:
        return "EVENT_FROZEN"
    if now < event.observation_time:
        return "BLACKOUT"
    if now >= event.force_exit_time:
        return "EXPIRED"
    if now > event.entry_cutoff_time:
        return "NO_TRADE"
    if scan is not None and scan.state in {"ARMED", "NO_TRADE"}:
        return scan.state
    return "OBSERVE"


__all__ = (
    "FOMC_EVENT_SCHEMA_VERSION",
    "FOMC_FREEZE_SCHEMA_VERSION",
    "FOMC_SCAN_SCHEMA_VERSION",
    "FOMC_STAGES",
    "FOMC_STRATEGY_ID",
    "FOMC_STRATEGY_VERSION",
    "FomcEventDefinition",
    "FomcFreezeSnapshot",
    "FomcRuntimeError",
    "FomcSignalScan",
    "build_fomc_freeze_snapshot",
    "candle_id",
    "fomc_stage",
    "frozen_structure_target",
    "scan_fomc_hybrid_signal",
)
