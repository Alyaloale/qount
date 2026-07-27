"""Public-data-only FOMC shadow watcher and secure runtime storage."""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
import stat
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from qount.contracts import canonical_hash
from qount.contracts import is_sha256
from qount.contracts.trace import aware_datetime
from qount.exchange_utils import build_exchange
from qount.notifications import AlertEvent
from qount.notifications import NotificationStore
from qount.notifications import synchronize_producer_incidents
from qount.persistence import publish_decision_batch
from qount.persistence import read_decision_batch
from qount.settings import Settings
from qount.small_account.event_signal import CompletedCandle
from qount.small_account.fomc_adapter import FomcMarketObservation
from qount.small_account.fomc_adapter import FomcStandardChain
from qount.small_account.fomc_adapter import build_fomc_standard_chain
from qount.small_account.fomc_runtime import FomcEventDefinition
from qount.small_account.fomc_runtime import FomcFreezeSnapshot
from qount.small_account.fomc_runtime import build_fomc_freeze_snapshot
from qount.small_account.fomc_runtime import fomc_stage
from qount.small_account.fomc_runtime import scan_fomc_hybrid_signal


FOMC_WATCHER_SCHEMA_VERSION = 1
FOMC_WATCHER_ARTIFACT_TYPE = "fomc_shadow_runtime"
FOMC_ALERT_CATEGORIES = (
    "fomc_event_cash_only",
    "fomc_event_freeze",
    "fomc_event_readiness",
    "fomc_event_signal",
)

_ERROR_CODE = re.compile(r"[^A-Z0-9_.:-]+")


class FomcWatcherError(ValueError):
    """Raised when watcher state or public market data is invalid."""


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            dict(value),
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        + b"\n"
    )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _secure_directory(path: Path) -> None:
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise FomcWatcherError("fomc_state_directory_invalid")
    os.chmod(path, 0o700)
    if stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode) != 0o700:
        raise FomcWatcherError("fomc_state_directory_mode_invalid")


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    raw = _canonical_bytes(value)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = -1
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if path.read_bytes() != raw:
        raise FomcWatcherError("fomc_state_readback_mismatch")
    _fsync_directory(path.parent)


def _write_latest(path: Path, value: Mapping[str, Any]) -> None:
    raw = _canonical_bytes(value)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = -1
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise FomcWatcherError("fomc_state_file_invalid")
    if stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode) != 0o600:
        raise FomcWatcherError("fomc_state_file_mode_invalid")
    try:
        value = json.loads(path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FomcWatcherError("fomc_state_json_invalid") from exc
    if not isinstance(value, dict):
        raise FomcWatcherError("fomc_state_object_required")
    return value


def load_fomc_event_definition(path: str | os.PathLike[str]) -> FomcEventDefinition:
    requested = Path(path).expanduser()
    if requested.is_symlink():
        raise FomcWatcherError("fomc_event_config_invalid")
    source = requested.resolve()
    if not source.is_file():
        raise FomcWatcherError("fomc_event_config_invalid")
    try:
        value = json.loads(source.read_text(encoding="ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FomcWatcherError("fomc_event_config_json_invalid") from exc
    if not isinstance(value, Mapping):
        raise FomcWatcherError("fomc_event_config_object_required")
    event_value = value.get("event", value)
    if not isinstance(event_value, Mapping):
        raise FomcWatcherError("fomc_event_config_event_invalid")
    return FomcEventDefinition.from_mapping(event_value)


class FomcStateStore:
    def __init__(self, root: str | os.PathLike[str], event_id: str) -> None:
        if not is_sha256(event_id):
            raise FomcWatcherError("fomc_event_id_invalid")
        requested = Path(root).expanduser()
        if requested.is_symlink():
            raise FomcWatcherError("fomc_state_root_symlink_forbidden")
        self.root = requested.resolve()
        self.event_root = self.root / "events" / event_id
        self.runs_root = self.event_root / "runs"
        self.batches_root = self.event_root / "decision_batches"
        for path in (
            self.root,
            self.root / "events",
            self.event_root,
            self.runs_root,
            self.batches_root,
        ):
            _secure_directory(path)

    @property
    def freeze_path(self) -> Path:
        return self.event_root / "freeze.json"

    @property
    def latest_path(self) -> Path:
        return self.event_root / "latest.json"

    def read_freeze(self) -> FomcFreezeSnapshot | None:
        if not self.freeze_path.exists():
            return None
        return FomcFreezeSnapshot.from_mapping(_read_json(self.freeze_path))

    def write_freeze(self, freeze: FomcFreezeSnapshot) -> FomcFreezeSnapshot:
        existing = self.read_freeze()
        if existing is not None:
            if existing != freeze:
                raise FomcWatcherError("fomc_freeze_immutable_conflict")
            return existing
        _write_exclusive(self.freeze_path, freeze.as_dict())
        return FomcFreezeSnapshot.from_mapping(_read_json(self.freeze_path))

    def publish_batch(self, chain: FomcStandardChain) -> None:
        batch = chain.batch
        target = self.batches_root / batch.manifest.batch_id
        if target.exists():
            existing = read_decision_batch(target)
            if existing.manifest.manifest_hash != batch.manifest.manifest_hash:
                raise FomcWatcherError("fomc_decision_batch_conflict")
            return
        publish_decision_batch(
            target,
            snapshot=batch.snapshot,
            intents=batch.intents,
            target=batch.target,
            risk=batch.risk,
            plan=batch.plan,
            created_at=batch.manifest.created_at,
        )

    def write_result(self, result: Mapping[str, Any]) -> Path:
        expected = canonical_hash(
            {key: value for key, value in result.items() if key != "result_hash"}
        )
        if result.get("result_hash") != expected:
            raise FomcWatcherError("fomc_result_hash_invalid")
        observed = dt.datetime.fromisoformat(
            str(result["observed_at"]).replace("Z", "+00:00")
        )
        name = f"{observed:%Y%m%dT%H%M%SZ}-{expected[:12]}.json"
        path = self.runs_root / name
        if path.exists():
            if _read_json(path) != dict(result):
                raise FomcWatcherError("fomc_result_immutable_conflict")
        else:
            _write_exclusive(path, result)
        _write_latest(self.latest_path, result)
        return path


def _number(value: object, *fallbacks: object) -> float:
    for candidate in (value, *fallbacks):
        try:
            number = float(candidate)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return math.nan


def _completed_candles(
    rows: Sequence[Sequence[Any]],
    *,
    interval_minutes: int,
    observed_at: dt.datetime,
) -> tuple[CompletedCandle, ...]:
    candles: list[CompletedCandle] = []
    interval = dt.timedelta(minutes=interval_minutes)
    for index, row in enumerate(rows):
        if not isinstance(row, Sequence) or len(row) < 6:
            raise FomcWatcherError(f"fomc_public_ohlcv_row_invalid:{index}")
        try:
            opened = dt.datetime.fromtimestamp(
                float(row[0]) / 1_000.0, tz=dt.timezone.utc
            )
            candle = CompletedCandle(
                interval_minutes=interval_minutes,
                closed_at=opened + interval,
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
        except (TypeError, ValueError, OSError) as exc:
            raise FomcWatcherError(
                f"fomc_public_ohlcv_row_invalid:{index}"
            ) from exc
        errors = candle.validate()
        if errors:
            raise FomcWatcherError(
                f"fomc_public_ohlcv_candle_invalid:{index}:" + ",".join(errors)
            )
        # A bar stamped exactly at ``observed_at`` can still be the exchange's
        # in-progress boundary bar. Require a positive close-time margin.
        if candle.closed_at < observed_at:
            candles.append(candle)
    candles.sort(key=lambda candle: candle.closed_at)
    if len({candle.closed_at for candle in candles}) != len(candles):
        raise FomcWatcherError("fomc_public_ohlcv_duplicate_close")
    return tuple(candles)


def _market_record(
    markets: Mapping[str, Any], event: FomcEventDefinition
) -> Mapping[str, Any]:
    candidates = []
    for key, raw in markets.items():
        if not isinstance(raw, Mapping):
            continue
        market_id = str(raw.get("id") or "").upper()
        if market_id != event.symbol:
            continue
        if raw.get("linear") is not True or raw.get("swap") is not True:
            continue
        if str(raw.get("settle") or "").upper() != "USDT":
            continue
        if raw.get("active") is False:
            continue
        candidates.append((str(key), raw))
    if len(candidates) != 1:
        raise FomcWatcherError("fomc_public_market_identity_ambiguous")
    return candidates[0][1]


def _symbol_rules(market: Mapping[str, Any]) -> tuple[float, float, float, str]:
    info = market.get("info") if isinstance(market.get("info"), Mapping) else {}
    filters = info.get("filters") if isinstance(info, Mapping) else ()
    by_type = {
        str(row.get("filterType")): row
        for row in filters or ()
        if isinstance(row, Mapping)
    }
    lot = by_type.get("LOT_SIZE", {})
    notional = by_type.get("MIN_NOTIONAL", by_type.get("NOTIONAL", {}))
    limits = market.get("limits") if isinstance(market.get("limits"), Mapping) else {}
    amount_limits = limits.get("amount") if isinstance(limits.get("amount"), Mapping) else {}
    cost_limits = limits.get("cost") if isinstance(limits.get("cost"), Mapping) else {}
    precision = market.get("precision") if isinstance(market.get("precision"), Mapping) else {}
    step = _number(lot.get("stepSize"), precision.get("amount"))
    minimum_quantity = _number(lot.get("minQty"), amount_limits.get("min"))
    minimum_notional = _number(
        notional.get("notional"),
        notional.get("minNotional"),
        cost_limits.get("min"),
        0.0,
    )
    contract_size = _number(market.get("contractSize"), 1.0)
    rule_core = {
        "symbol": str(market.get("id") or ""),
        "step_size": step,
        "minimum_quantity": minimum_quantity,
        "minimum_notional": minimum_notional,
        "contract_size": contract_size,
        "linear": bool(market.get("linear")),
        "swap": bool(market.get("swap")),
        "active": market.get("active"),
    }
    if not all(
        math.isfinite(value) and value > 0.0
        for value in (step, minimum_quantity)
    ):
        raise FomcWatcherError("fomc_public_symbol_rules_invalid")
    if not math.isfinite(minimum_notional) or minimum_notional < 0.0:
        raise FomcWatcherError("fomc_public_minimum_notional_invalid")
    if not math.isclose(contract_size, 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise FomcWatcherError("fomc_public_contract_size_invalid")
    return step, minimum_quantity, minimum_notional, canonical_hash(rule_core)


def collect_fomc_public_market(
    exchange: Any,
    event: FomcEventDefinition,
    *,
    observed_at: str | dt.datetime,
) -> tuple[
    tuple[CompletedCandle, ...],
    tuple[CompletedCandle, ...],
    FomcMarketObservation,
]:
    """Collect only public market endpoints; no private method is reachable here."""

    now = (
        observed_at
        if isinstance(observed_at, dt.datetime)
        else dt.datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
    ).astimezone(dt.timezone.utc)
    markets = exchange.load_markets()
    if not isinstance(markets, Mapping):
        raise FomcWatcherError("fomc_public_markets_invalid")
    market = _market_record(markets, event)
    ccxt_symbol = str(market.get("symbol") or "")
    if not ccxt_symbol:
        raise FomcWatcherError("fomc_public_ccxt_symbol_missing")
    hourly_rows = exchange.fetch_ohlcv(ccxt_symbol, timeframe="1h", limit=900)
    fifteen_rows = exchange.fetch_ohlcv(ccxt_symbol, timeframe="15m", limit=300)
    hourly = _completed_candles(
        hourly_rows, interval_minutes=60, observed_at=now
    )
    fifteen = _completed_candles(
        fifteen_rows, interval_minutes=15, observed_at=now
    )
    if not hourly or not fifteen:
        raise FomcWatcherError("fomc_public_completed_candles_missing")
    ticker = exchange.fetch_ticker(ccxt_symbol)
    funding = exchange.fetch_funding_rate(ccxt_symbol)
    if not isinstance(ticker, Mapping) or not isinstance(funding, Mapping):
        raise FomcWatcherError("fomc_public_quote_payload_invalid")
    ticker_info = ticker.get("info") if isinstance(ticker.get("info"), Mapping) else {}
    funding_info = funding.get("info") if isinstance(funding.get("info"), Mapping) else {}
    last = _number(
        ticker.get("last"), ticker_info.get("lastPrice"), hourly[-1].close
    )
    bid = _number(ticker.get("bid"), ticker_info.get("bidPrice"), last)
    ask = _number(ticker.get("ask"), ticker_info.get("askPrice"), last)
    mark = _number(funding.get("markPrice"), funding_info.get("markPrice"), last)
    index = _number(
        funding.get("indexPrice"), funding_info.get("indexPrice"), mark
    )
    funding_rate = _number(
        funding.get("fundingRate"), funding_info.get("lastFundingRate"), 0.0
    )
    step, minimum_quantity, minimum_notional, rules_hash = _symbol_rules(market)
    hourly_hash = canonical_hash(
        {
            "interval": "1h",
            "rows": [
                [
                    candle.closed_at.isoformat(),
                    candle.open,
                    candle.high,
                    candle.low,
                    candle.close,
                    candle.volume,
                ]
                for candle in hourly
            ],
        }
    )
    fifteen_hash = canonical_hash(
        {
            "interval": "15m",
            "rows": [
                [
                    candle.closed_at.isoformat(),
                    candle.open,
                    candle.high,
                    candle.low,
                    candle.close,
                    candle.volume,
                ]
                for candle in fifteen
            ],
        }
    )
    ticker_hash = canonical_hash(
        {"last": last, "bid": bid, "ask": ask, "observed_at": now.isoformat()}
    )
    funding_hash = canonical_hash(
        {
            "mark": mark,
            "index": index,
            "funding_rate": funding_rate,
            "observed_at": now.isoformat(),
        }
    )
    data_cutoff = max(hourly[-1].closed_at, fifteen[-1].closed_at)
    observation = FomcMarketObservation.create(
        symbol=event.symbol,
        observed_at=now.isoformat(),
        data_cutoff=data_cutoff.isoformat(),
        last_price=last,
        bid_price=bid,
        ask_price=ask,
        mark_price=mark,
        index_price=index,
        funding_rate=funding_rate,
        quantity_step=step,
        minimum_quantity=minimum_quantity,
        minimum_notional_usdt=minimum_notional,
        exchange_rules_hash=rules_hash,
        source_hashes={
            "hourly_candles": hourly_hash,
            "fifteen_minute_candles": fifteen_hash,
            "ticker": ticker_hash,
            "funding": funding_hash,
            "exchange_rules": rules_hash,
        },
    )
    return hourly, fifteen, observation


def _result(
    event: FomcEventDefinition,
    *,
    observed_at: dt.datetime,
    stage: str,
    freeze: FomcFreezeSnapshot | None,
    market: FomcMarketObservation | None,
    signal: Mapping[str, Any] | None,
    chain: FomcStandardChain | None,
    blockers: Sequence[str],
) -> dict[str, Any]:
    core = {
        "schema_version": FOMC_WATCHER_SCHEMA_VERSION,
        "artifact_type": FOMC_WATCHER_ARTIFACT_TYPE,
        "event": event.as_dict(),
        "observed_at": observed_at.isoformat(),
        "stage": stage,
        "freeze": freeze.as_dict() if freeze is not None else None,
        "market": market.as_dict() if market is not None else None,
        "signal": dict(signal) if signal is not None else None,
        "standard_chain": chain.as_dict() if chain is not None else None,
        "blockers": list(dict.fromkeys(str(value) for value in blockers)),
        "permissions": {
            "orders_authorized": False,
            "paper_or_live_allowed": False,
            "private_api_used": False,
            "private_api_order_attempted": False,
            "exchange_mutation_attempted": False,
        },
    }
    return core | {"result_hash": canonical_hash(core)}


def _error_code(exc: Exception) -> str:
    raw = f"{type(exc).__name__}:{exc}".upper()
    return _ERROR_CODE.sub("_", raw).strip("_")[:160] or "FOMC_WATCHER_ERROR"


def build_fomc_alerts(
    event: FomcEventDefinition,
    result: Mapping[str, Any],
) -> tuple[AlertEvent, ...]:
    stage = str(result.get("stage") or "")
    observed_at = str(result["observed_at"])
    observed_time = aware_datetime(observed_at).astimezone(dt.timezone.utc)
    alerts: list[AlertEvent] = []

    def create(
        *,
        severity: str,
        category: str,
        title: str,
        summary: str,
        occurred_at: str,
        identity: Mapping[str, Any],
        source_hash: str,
        trace_id_value: str | None = None,
    ) -> AlertEvent:
        source_id = canonical_hash(dict(identity))
        return AlertEvent.create(
            severity=severity,
            category=category,
            title=title,
            summary=summary,
            occurred_at=occurred_at,
            source_type="event_strategy",
            source_id=source_id,
            source_hash=source_hash,
            dedupe_key=f"fomc:{event.event_id}:{category}:{source_id}",
            trace_id_value=trace_id_value,
        )

    if event.cash_only_time <= observed_time < event.freeze_time:
        identity = {
            "event_id": event.event_id,
            "cash_only_from": event.cash_only_from,
            "freeze_at": event.freeze_at,
        }
        source_hash = canonical_hash(identity)
        alerts.append(
            create(
                severity="WARNING",
                category="fomc_event_cash_only",
                title="FOMC cash-only window is active",
                summary=(
                    f"{event.symbol} new event risk must remain disabled until "
                    f"the frozen event policy permits observation; "
                    f"freeze_at={event.freeze_at}."
                ),
                occurred_at=event.cash_only_from,
                identity=identity,
                source_hash=source_hash,
            )
        )
    if stage in {"FREEZE_REQUIRED", "HALTED"}:
        blockers = tuple(str(value) for value in result.get("blockers") or ())
        source_hash = canonical_hash(
            {"event_id": event.event_id, "stage": stage, "blockers": blockers}
        )
        alerts.append(
            create(
                severity="CRITICAL" if stage == "HALTED" else "WARNING",
                category="fomc_event_readiness",
                title="FOMC watcher is not ready",
                summary=(
                    f"Stage={stage}; blockers={', '.join(blockers) or 'UNKNOWN'}; "
                    "new risk remains disabled."
                ),
                occurred_at=max(event.freeze_at, observed_at),
                identity={
                    "event_id": event.event_id,
                    "stage": stage,
                    "blockers": blockers,
                },
                source_hash=source_hash,
            )
        )
    freeze = result.get("freeze")
    if stage in {"EVENT_FROZEN", "BLACKOUT"} and isinstance(freeze, Mapping):
        source_hash = str(freeze["freeze_hash"])
        alerts.append(
            create(
                severity="INFO",
                category="fomc_event_freeze",
                title="FOMC event range is frozen",
                summary=(
                    f"{event.symbol} H0={float(freeze['h0']):.8g}, "
                    f"L0={float(freeze['l0']):.8g}, "
                    f"ATR0={float(freeze['atr0']):.8g}; "
                    "watcher remains order-free during blackout."
                ),
                occurred_at=str(freeze["frozen_at"]),
                identity={
                    "event_id": event.event_id,
                    "freeze_id": freeze["freeze_id"],
                },
                source_hash=source_hash,
                trace_id_value=str(freeze["freeze_id"]),
            )
        )
    signal = result.get("signal")
    if stage == "ARMED" and isinstance(signal, Mapping):
        chain = result.get("standard_chain")
        chain_value = chain if isinstance(chain, Mapping) else {}
        sizing = chain_value.get("sizing")
        sizing_value = sizing if isinstance(sizing, Mapping) else {}
        identity = {
            "event_id": event.event_id,
            "state": signal.get("state"),
            "side": signal.get("side"),
            "anchor": signal.get("anchor_candle_id"),
            "breakout": signal.get("breakout_candle_id"),
            "retest": signal.get("retest_candle_ids"),
        }
        source_hash = canonical_hash(identity)
        standard = chain_value.get("standard_chain")
        trace_id_value = (
            str(standard.get("batch_id")) if isinstance(standard, Mapping) else None
        )
        alerts.append(
            create(
                severity="WARNING",
                category="fomc_event_signal",
                title="FOMC signal is armed but cannot trade",
                summary=(
                    f"Side={signal.get('side')}; planned notional="
                    f"{float(sizing_value.get('notional_usdt') or 0.0):.2f} USDT; "
                    f"stress risk="
                    f"{float(sizing_value.get('estimated_stress_loss_usdt') or 0.0):.2f} USDT; "
                    f"blockers={', '.join(chain_value.get('blockers') or ()) or 'UNKNOWN'}."
                ),
                occurred_at=str(signal.get("signal_available_at") or observed_at),
                identity=identity,
                source_hash=source_hash,
                trace_id_value=trace_id_value,
            )
        )
    return tuple(alerts)


def _sync_alerts(
    notification_store: NotificationStore | None,
    event: FomcEventDefinition,
    result: Mapping[str, Any],
) -> None:
    if notification_store is None:
        return
    synchronize_producer_incidents(
        notification_store,
        build_fomc_alerts(event, result),
        source_type="event_strategy",
        categories=FOMC_ALERT_CATEGORIES,
        observed_at=str(result["observed_at"]),
        channels=("dashboard",),
        max_attempts=1,
    )


def run_fomc_shadow_cycle(
    event: FomcEventDefinition,
    store: FomcStateStore,
    *,
    observed_at: str | dt.datetime | None = None,
    exchange: Any | None = None,
    notification_store: NotificationStore | None = None,
) -> dict[str, Any]:
    """Run one order-free cycle and persist every decision before returning."""

    now = (
        dt.datetime.now(dt.timezone.utc)
        if observed_at is None
        else observed_at
        if isinstance(observed_at, dt.datetime)
        else dt.datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
    ).astimezone(dt.timezone.utc)
    freeze = store.read_freeze()
    if now < event.freeze_time:
        result = _result(
            event,
            observed_at=now,
            stage="SCHEDULED",
            freeze=freeze,
            market=None,
            signal=None,
            chain=None,
            blockers=(),
        )
        store.write_result(result)
        _sync_alerts(notification_store, event, result)
        return result
    if now >= event.force_exit_time:
        result = _result(
            event,
            observed_at=now,
            stage="EXPIRED",
            freeze=freeze,
            market=None,
            signal=None,
            chain=None,
            blockers=("FOMC_FREEZE_MISSING",) if freeze is None else (),
        )
        store.write_result(result)
        _sync_alerts(notification_store, event, result)
        return result

    owned_exchange = exchange is None
    client = exchange
    try:
        if client is None:
            settings = replace(Settings.from_env(), market_type="future")
            client = build_exchange(settings, private=False)
        hourly, fifteen, market = collect_fomc_public_market(
            client, event, observed_at=now
        )
        if freeze is None:
            freeze = store.write_freeze(
                build_fomc_freeze_snapshot(
                    event,
                    hourly_candles=hourly,
                    fifteen_minute_candles=fifteen,
                    exchange_rules_hash=market.exchange_rules_hash,
                    source_hashes=market.source_hashes,
                )
            )
        stage = fomc_stage(
            event,
            evaluated_at=now,
            freeze_available=True,
        )
        signal = None
        chain = None
        blockers: tuple[str, ...] = ()
        if stage in {"OBSERVE", "NO_TRADE"}:
            scanned = scan_fomc_hybrid_signal(
                event,
                freeze,
                hourly_candles=hourly,
                fifteen_minute_candles=fifteen,
                planned_entry_price=market.last_price,
                evaluated_at=now,
            )
            if scanned.side in {"long", "short"}:
                scanned = scan_fomc_hybrid_signal(
                    event,
                    freeze,
                    hourly_candles=hourly,
                    fifteen_minute_candles=fifteen,
                    planned_entry_price=market.entry_price(scanned.side),
                    evaluated_at=now,
                )
            signal = scanned.as_dict()
            stage = fomc_stage(
                event,
                evaluated_at=now,
                freeze_available=True,
                scan=scanned,
            )
            chain = build_fomc_standard_chain(
                event,
                freeze,
                scanned,
                market,
                account_snapshot=None,
                orders_authorized=False,
            )
            store.publish_batch(chain)
            blockers = chain.blockers
        result = _result(
            event,
            observed_at=now,
            stage=stage,
            freeze=freeze,
            market=market,
            signal=signal,
            chain=chain,
            blockers=blockers,
        )
    except Exception as exc:
        result = _result(
            event,
            observed_at=now,
            stage="HALTED",
            freeze=freeze,
            market=None,
            signal=None,
            chain=None,
            blockers=(_error_code(exc),),
        )
    finally:
        if owned_exchange and client is not None:
            close = getattr(client, "close", None)
            if callable(close):
                close()
    store.write_result(result)
    _sync_alerts(notification_store, event, result)
    return result


__all__ = (
    "FOMC_ALERT_CATEGORIES",
    "FOMC_WATCHER_ARTIFACT_TYPE",
    "FOMC_WATCHER_SCHEMA_VERSION",
    "FomcStateStore",
    "FomcWatcherError",
    "build_fomc_alerts",
    "collect_fomc_public_market",
    "load_fomc_event_definition",
    "run_fomc_shadow_cycle",
)
