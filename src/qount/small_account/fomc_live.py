"""Fail-closed live execution boundary for the FOMC event strategy.

The public watcher remains order-free.  This module adds a separate private
account preflight, exact-plan readiness artifact, short-lived one-use arm, and
an idempotent Binance USD-M dispatcher.  No function routes an order unless a
manual switch or a one-event owner authorization produces a matching arm,
token, confirmation, and current account state for the same frozen plan.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import json
import math
import os
import secrets
import stat
import tempfile
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from qount.contracts import MarketSnapshot
from qount.contracts import OrderPlan
from qount.contracts import PlannedOrder
from qount.contracts import ProductCapability
from qount.contracts import RiskDecision
from qount.contracts import StrategyIntent
from qount.contracts import canonical_hash
from qount.contracts import is_sha256
from qount.contracts.trace import aware_datetime
from qount.exchange_utils import build_exchange
from qount.exchange_utils import call_with_time_sync_retry
from qount.exchange_utils import extract_quote_balance
from qount.exchange_utils import resolve_market_symbol
from qount.ledger import RuntimeLedger
from qount.ledger import build_runtime_ledger_snapshot
from qount.ledger import reconcile_three_way
from qount.models import utc_now
from qount.persistence import VerifiedDecisionBatch
from qount.persistence import build_decision_batch_manifest
from qount.persistence import read_decision_batch
from qount.portfolio import SleeveRiskBudget
from qount.portfolio import allocate_strategy_intents
from qount.portfolio import portfolio_target_from_allocation
from qount.risk import build_portfolio_risk_decision
from qount.settings import Settings
from qount.small_account.fomc_adapter import DEFAULT_FOMC_COSTS
from qount.small_account.fomc_adapter import DEFAULT_FOMC_STOP_GAP_RATE
from qount.small_account.fomc_adapter import FomcMarketObservation
from qount.small_account.fomc_adapter import FomcStandardChain
from qount.small_account.fomc_adapter import btc_usdt_perpetual_instrument
from qount.small_account.fomc_adapter import build_fomc_standard_chain
from qount.small_account.fomc_runtime import FomcEventDefinition
from qount.small_account.fomc_runtime import FomcFreezeSnapshot
from qount.small_account.fomc_runtime import FomcRuntimeError
from qount.small_account.fomc_runtime import FomcSignalScan
from qount.small_account.fomc_runtime import FOMC_STRATEGY_ID
from qount.small_account.fomc_runtime import FOMC_STRATEGY_VERSION
from qount.small_account.risk import AccountRiskSnapshot
from qount.small_account.risk import DEFAULT_SMALL_ACCOUNT_POLICY
from qount.small_account.risk import size_linear_usdt_futures
from qount.small_account.fomc_watcher import FomcStateStore
from qount.small_account.fomc_watcher import collect_fomc_public_market
from qount.small_account.fomc_watcher import run_fomc_shadow_cycle
from qount.small_account.management import calculate_one_third_exit_quantity
from qount.small_account.management import calculate_post_2r_tail_stop
from qount.small_account.management import calculate_profit_thresholds


FOMC_LIVE_PREFLIGHT_VERSION = 1
FOMC_LIVE_READINESS_VERSION = 1
FOMC_LIVE_ARM_VERSION = 1
FOMC_LIVE_AUTO_AUTHORIZATION_VERSION = 1
FOMC_LIVE_EXECUTION_VERSION = 1
FOMC_LIVE_REDUCTION_ATTEMPT_VERSION = 1
FOMC_LIVE_MANAGEMENT_VERSION = 1
FOMC_LIVE_ARM_TTL_SECONDS = 10 * 60
FOMC_LIVE_MAX_QUOTE_AGE_SECONDS = 90
FOMC_LIVE_MAX_ADVERSE_SLIPPAGE_BPS = 20.0
FOMC_LIVE_MAX_TAKER_FEE_RATE = DEFAULT_FOMC_COSTS.entry_fee_rate
FOMC_LIVE_MINIMUM_FREE_BALANCE_USDT = (
    DEFAULT_SMALL_ACCOUNT_POLICY.maximum_isolated_margin_usdt
    + DEFAULT_SMALL_ACCOUNT_POLICY.first_live_risk_cap_usdt
)

_TRUE_VALUES = frozenset({"1", "true", "yes", "on", "live"})


class FomcLiveError(ValueError):
    """Raised when the FOMC live boundary cannot prove a safe state."""


def _enabled(value: object) -> bool:
    return str(value or "").strip().lower() in _TRUE_VALUES


def _float(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _utc(value: str | dt.datetime | None = None) -> dt.datetime:
    if value is None:
        return utc_now().astimezone(dt.timezone.utc)
    parsed = value if isinstance(value, dt.datetime) else aware_datetime(str(value))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FomcLiveError("fomc_live_time_invalid")
    return parsed.astimezone(dt.timezone.utc)


def _time_after(*values: str, minimum_step_microseconds: int = 1) -> str:
    floor = max(_utc(value) for value in values)
    now = _utc()
    if now <= floor:
        now = floor + dt.timedelta(microseconds=minimum_step_microseconds)
    return now.isoformat()


def _safe_error(exc: Exception, settings: Settings) -> str:
    value = f"{type(exc).__name__}: {exc}"
    for secret in (settings.binance_api_key, settings.binance_api_secret):
        if secret:
            value = value.replace(secret, "[REDACTED]")
    return value[:1000]


def _api_key_fingerprint(settings: Settings) -> str:
    """Return a non-secret credential binding for an armed live account."""

    raw_key = settings.binance_api_key
    if not isinstance(raw_key, str) or not raw_key or raw_key != raw_key.strip():
        raise FomcLiveError("fomc_live_api_key_identity_invalid")
    try:
        encoded = raw_key.encode("ascii")
    except UnicodeEncodeError as exc:
        raise FomcLiveError("fomc_live_api_key_identity_invalid") from exc
    return hashlib.sha256(b"qount-binance-api-key-v1:\x00" + encoded).hexdigest()


def _number(value: object, *fallbacks: object) -> float:
    for candidate in (value, *fallbacks):
        try:
            number = float(candidate)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return math.nan


def _market_rules(market: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize the exact Binance contract fields used by the public watcher."""

    info = market.get("info") if isinstance(market.get("info"), Mapping) else {}
    filters = info.get("filters") if isinstance(info, Mapping) else ()
    by_type = {
        str(row.get("filterType")): row
        for row in filters or ()
        if isinstance(row, Mapping)
    }
    lot = by_type.get("LOT_SIZE", {})
    price_filter = by_type.get("PRICE_FILTER", {})
    notional = by_type.get("MIN_NOTIONAL", by_type.get("NOTIONAL", {}))
    limits = market.get("limits") if isinstance(market.get("limits"), Mapping) else {}
    amount_limits = (
        limits.get("amount") if isinstance(limits.get("amount"), Mapping) else {}
    )
    cost_limits = (
        limits.get("cost") if isinstance(limits.get("cost"), Mapping) else {}
    )
    precision = (
        market.get("precision") if isinstance(market.get("precision"), Mapping) else {}
    )
    price_tick = _number(price_filter.get("tickSize"), precision.get("price"))
    quantity_step = _number(lot.get("stepSize"), precision.get("amount"))
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
        "step_size": quantity_step,
        "price_tick": price_tick,
        "minimum_quantity": minimum_quantity,
        "minimum_notional": minimum_notional,
        "contract_size": contract_size,
        "linear": bool(market.get("linear")),
        "swap": bool(market.get("swap")),
        "active": market.get("active"),
    }
    if not all(
        math.isfinite(value) and value > 0.0
        for value in (price_tick, quantity_step, minimum_quantity)
    ):
        raise FomcLiveError("fomc_live_market_rules_invalid")
    if not math.isfinite(minimum_notional) or minimum_notional < 0.0:
        raise FomcLiveError("fomc_live_market_rules_invalid")
    if not math.isclose(contract_size, 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise FomcLiveError("fomc_live_market_contract_size_invalid")
    return {
        "symbol": str(market.get("id") or "").upper(),
        "settle": str(market.get("settle") or "").upper(),
        "linear": bool(market.get("linear")),
        "swap": bool(market.get("swap")),
        "active": market.get("active"),
        "price_tick": price_tick,
        "quantity_step": quantity_step,
        "minimum_quantity": minimum_quantity,
        "minimum_notional_usdt": minimum_notional,
        "contract_size": contract_size,
        "exchange_rules_hash": canonical_hash(rule_core),
    }


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
        raise FomcLiveError("fomc_live_directory_invalid")
    os.chmod(path, 0o700)
    if stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode) != 0o700:
        raise FomcLiveError("fomc_live_directory_mode_invalid")


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
        raise FomcLiveError("fomc_live_write_readback_mismatch")
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
        raise FomcLiveError("fomc_live_file_invalid")
    if stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode) != 0o600:
        raise FomcLiveError("fomc_live_file_mode_invalid")
    try:
        value = json.loads(path.read_text(encoding="ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FomcLiveError("fomc_live_json_invalid") from exc
    if not isinstance(value, dict):
        raise FomcLiveError("fomc_live_json_object_required")
    return value


def _hashed_artifact_valid(payload: Mapping[str, Any], hash_field: str) -> bool:
    expected = canonical_hash(
        {key: value for key, value in payload.items() if key != hash_field}
    )
    return payload.get(hash_field) == expected


class FomcLiveStore:
    """Secure event-local storage for readiness, arms, attempts, and ledger."""

    def __init__(self, state_root: str | os.PathLike[str], event_id: str) -> None:
        if not is_sha256(event_id):
            raise FomcLiveError("fomc_live_event_id_invalid")
        requested = Path(state_root).expanduser()
        if requested.is_symlink():
            raise FomcLiveError("fomc_live_state_root_symlink_forbidden")
        self.state_root = requested.resolve()
        self.root = self.state_root / "events" / event_id / "live"
        self.readiness_root = self.root / "readiness"
        self.arms_root = self.root / "arms"
        self.consumptions_root = self.root / "consumptions"
        self.executions_root = self.root / "executions"
        self.reduction_attempts_root = self.root / "reduction-attempts"
        self.management_root = self.root / "management"
        for path in (
            self.state_root,
            self.state_root / "events",
            self.state_root / "events" / event_id,
            self.root,
            self.readiness_root,
            self.arms_root,
            self.consumptions_root,
            self.executions_root,
            self.reduction_attempts_root,
            self.management_root,
        ):
            _secure_directory(path)

    @property
    def readiness_latest_path(self) -> Path:
        return self.root / "readiness-latest.json"

    @property
    def arm_latest_path(self) -> Path:
        return self.root / "arm-latest.json"

    @property
    def auto_authorization_path(self) -> Path:
        return self.root / "auto-authorization.json"

    @property
    def auto_authorization_consumption_path(self) -> Path:
        return self.root / "auto-authorization-consumption.json"

    @property
    def auto_arm_secret_path(self) -> Path:
        return self.root / "auto-arm-secret.json"

    @property
    def execution_latest_path(self) -> Path:
        return self.root / "execution-latest.json"

    @property
    def management_latest_path(self) -> Path:
        return self.root / "management-latest.json"

    @property
    def attempt_path(self) -> Path:
        return self.root / "attempt.json"

    @property
    def halt_path(self) -> Path:
        return self.root / "HALT"

    @property
    def lock_path(self) -> Path:
        return self.root / "cycle.lock"

    @property
    def ledger_path(self) -> Path:
        return self.root / "runtime.sqlite3"

    def ledger(self) -> RuntimeLedger:
        return RuntimeLedger(self.ledger_path)

    def cycle_lock(self):
        descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        return os.fdopen(descriptor, "r+")

    def write_readiness(self, payload: Mapping[str, Any]) -> Path:
        if not _hashed_artifact_valid(payload, "readiness_hash"):
            raise FomcLiveError("fomc_live_readiness_hash_invalid")
        readiness_hash = str(payload["readiness_hash"])
        path = self.readiness_root / f"{readiness_hash}.json"
        if path.exists():
            if _read_json(path) != dict(payload):
                raise FomcLiveError("fomc_live_readiness_conflict")
        else:
            _write_exclusive(path, payload)
        _write_latest(self.readiness_latest_path, payload)
        return path

    def read_readiness(self, readiness_hash: str | None = None) -> dict[str, Any] | None:
        path = (
            self.readiness_root / f"{readiness_hash}.json"
            if readiness_hash
            else self.readiness_latest_path
        )
        if not path.exists():
            return None
        payload = _read_json(path)
        if not _hashed_artifact_valid(payload, "readiness_hash"):
            raise FomcLiveError("fomc_live_readiness_hash_invalid")
        return payload

    def write_arm(self, payload: Mapping[str, Any]) -> Path:
        validate_fomc_live_arm(payload)
        arm_id = str(payload["arm_id"])
        path = self.arms_root / f"{arm_id}.json"
        if path.exists():
            if _read_json(path) != dict(payload):
                raise FomcLiveError("fomc_live_arm_conflict")
        else:
            _write_exclusive(path, payload)
        _write_latest(self.arm_latest_path, payload)
        return path

    def read_arm(self, arm_id: str | None = None) -> dict[str, Any] | None:
        path = self.arms_root / f"{arm_id}.json" if arm_id else self.arm_latest_path
        if not path.exists():
            return None
        payload = _read_json(path)
        validate_fomc_live_arm(payload)
        return payload

    def write_auto_authorization(self, payload: Mapping[str, Any]) -> Path:
        validate_fomc_live_auto_authorization(payload)
        if self.auto_authorization_path.exists():
            if _read_json(self.auto_authorization_path) != dict(payload):
                raise FomcLiveError("fomc_live_auto_authorization_conflict")
            return self.auto_authorization_path
        _write_exclusive(self.auto_authorization_path, payload)
        return self.auto_authorization_path

    def read_auto_authorization(self) -> dict[str, Any] | None:
        if not self.auto_authorization_path.exists():
            return None
        payload = _read_json(self.auto_authorization_path)
        validate_fomc_live_auto_authorization(payload)
        return payload

    def read_auto_authorization_consumption(self) -> dict[str, Any] | None:
        if not self.auto_authorization_consumption_path.exists():
            return None
        payload = _read_json(self.auto_authorization_consumption_path)
        validate_fomc_live_auto_authorization_consumption(payload)
        return payload

    def consume_auto_authorization(
        self,
        authorization: Mapping[str, Any],
        arm: Mapping[str, Any],
        *,
        consumed_at: str | dt.datetime,
    ) -> dict[str, Any]:
        validate_fomc_live_auto_authorization(authorization)
        validate_fomc_live_arm(arm)
        consumed = _utc(consumed_at)
        core = {
            "schema_version": FOMC_LIVE_AUTO_AUTHORIZATION_VERSION,
            "artifact_type": "fomc_live_auto_authorization_consumption",
            "authorization_id": authorization["authorization_id"],
            "event_id": authorization["event_id"],
            "account_scope_hash": authorization["account_scope_hash"],
            "arm_id": arm["arm_id"],
            "readiness_hash": arm["readiness_hash"],
            "consumed_at": consumed.isoformat(),
            "single_use": True,
        }
        payload = core | {"consumption_hash": canonical_hash(core)}
        validate_fomc_live_auto_authorization_consumption(payload)
        if self.auto_authorization_consumption_path.exists():
            raise FomcLiveError("fomc_live_auto_authorization_already_consumed")
        _write_exclusive(self.auto_authorization_consumption_path, payload)
        return payload

    def write_auto_arm_secret(
        self, arm: Mapping[str, Any], *, arm_token: str
    ) -> Path:
        validate_fomc_live_arm(arm)
        if hashlib.sha256(arm_token.encode("utf-8")).hexdigest() != arm.get(
            "arm_token_sha256"
        ):
            raise FomcLiveError("fomc_live_auto_arm_token_mismatch")
        core = {
            "schema_version": FOMC_LIVE_AUTO_AUTHORIZATION_VERSION,
            "artifact_type": "fomc_live_auto_arm_secret",
            "arm_id": arm["arm_id"],
            "arm_token": arm_token,
            "arm_token_sha256": arm["arm_token_sha256"],
        }
        payload = core | {"secret_hash": canonical_hash(core)}
        if self.auto_arm_secret_path.exists():
            if _read_json(self.auto_arm_secret_path) != payload:
                raise FomcLiveError("fomc_live_auto_arm_secret_conflict")
            return self.auto_arm_secret_path
        _write_exclusive(self.auto_arm_secret_path, payload)
        return self.auto_arm_secret_path

    def read_auto_arm_secret(self) -> dict[str, Any] | None:
        if not self.auto_arm_secret_path.exists():
            return None
        payload = _read_json(self.auto_arm_secret_path)
        validate_fomc_live_auto_arm_secret(payload)
        return payload

    def consumption_path(self, arm_id: str) -> Path:
        return self.consumptions_root / f"{arm_id}.json"

    def arm_consumed(self, arm_id: str) -> bool:
        return self.consumption_path(arm_id).exists()

    def consume_arm(self, arm: Mapping[str, Any], *, consumed_at: str) -> dict[str, Any]:
        validate_fomc_live_arm(arm)
        arm_id = str(arm["arm_id"])
        core = {
            "schema_version": FOMC_LIVE_ARM_VERSION,
            "artifact_type": "fomc_live_arm_consumption",
            "arm_id": arm_id,
            "event_id": arm["event_id"],
            "readiness_hash": arm["readiness_hash"],
            "batch_id": arm["batch_id"],
            "consumed_at": _utc(consumed_at).isoformat(),
            "single_use": True,
        }
        payload = core | {"consumption_hash": canonical_hash(core)}
        path = self.consumption_path(arm_id)
        if path.exists():
            raise FomcLiveError("fomc_live_arm_already_consumed")
        _write_exclusive(path, payload)
        return payload

    def write_attempt(self, payload: Mapping[str, Any]) -> Path:
        if not _hashed_artifact_valid(payload, "attempt_hash"):
            raise FomcLiveError("fomc_live_attempt_hash_invalid")
        if self.attempt_path.exists():
            existing = _read_json(self.attempt_path)
            if existing != dict(payload):
                raise FomcLiveError("fomc_live_attempt_already_exists")
            return self.attempt_path
        _write_exclusive(self.attempt_path, payload)
        return self.attempt_path

    def read_attempt(self) -> dict[str, Any] | None:
        if not self.attempt_path.exists():
            return None
        payload = _read_json(self.attempt_path)
        if not _hashed_artifact_valid(payload, "attempt_hash"):
            raise FomcLiveError("fomc_live_attempt_hash_invalid")
        return payload

    def reduction_attempt_path(self, reduction_key: str) -> Path:
        if not is_sha256(reduction_key):
            raise FomcLiveError("fomc_live_reduction_key_invalid")
        return self.reduction_attempts_root / f"{reduction_key}.json"

    def write_reduction_attempt(self, payload: Mapping[str, Any]) -> Path:
        if not _hashed_artifact_valid(payload, "attempt_hash"):
            raise FomcLiveError("fomc_live_reduction_attempt_hash_invalid")
        reduction_key = str(payload.get("reduction_key") or "")
        path = self.reduction_attempt_path(reduction_key)
        if path.exists():
            if _read_json(path) != dict(payload):
                raise FomcLiveError("fomc_live_reduction_attempt_conflict")
            return path
        _write_exclusive(path, payload)
        return path

    def read_reduction_attempt(self, reduction_key: str) -> dict[str, Any] | None:
        path = self.reduction_attempt_path(reduction_key)
        if not path.exists():
            return None
        payload = _read_json(path)
        if not _hashed_artifact_valid(payload, "attempt_hash"):
            raise FomcLiveError("fomc_live_reduction_attempt_hash_invalid")
        if payload.get("reduction_key") != reduction_key:
            raise FomcLiveError("fomc_live_reduction_attempt_identity_invalid")
        return payload

    def list_reduction_attempts(self) -> tuple[dict[str, Any], ...]:
        attempts = []
        for path in sorted(self.reduction_attempts_root.glob("*.json")):
            payload = _read_json(path)
            if not _hashed_artifact_valid(payload, "attempt_hash"):
                raise FomcLiveError("fomc_live_reduction_attempt_hash_invalid")
            if path.stem != payload.get("reduction_key"):
                raise FomcLiveError("fomc_live_reduction_attempt_identity_invalid")
            attempts.append(payload)
        return tuple(attempts)

    def write_management_state(self, payload: Mapping[str, Any]) -> Path:
        if not _hashed_artifact_valid(payload, "management_hash"):
            raise FomcLiveError("fomc_live_management_hash_invalid")
        management_hash = str(payload.get("management_hash") or "")
        if not is_sha256(management_hash):
            raise FomcLiveError("fomc_live_management_identity_invalid")
        path = self.management_root / f"{management_hash}.json"
        if path.exists():
            if _read_json(path) != dict(payload):
                raise FomcLiveError("fomc_live_management_conflict")
        else:
            _write_exclusive(path, payload)
        _write_latest(self.management_latest_path, payload)
        return path

    def read_management_state(self) -> dict[str, Any] | None:
        if not self.management_latest_path.exists():
            return None
        payload = _read_json(self.management_latest_path)
        if not _hashed_artifact_valid(payload, "management_hash"):
            raise FomcLiveError("fomc_live_management_hash_invalid")
        if payload.get("artifact_type") != "fomc_live_position_management":
            raise FomcLiveError("fomc_live_management_type_invalid")
        return payload

    def write_execution(self, payload: Mapping[str, Any]) -> Path:
        if not _hashed_artifact_valid(payload, "execution_hash"):
            raise FomcLiveError("fomc_live_execution_hash_invalid")
        execution_hash = str(payload["execution_hash"])
        path = self.executions_root / f"{execution_hash}.json"
        if path.exists():
            if _read_json(path) != dict(payload):
                raise FomcLiveError("fomc_live_execution_conflict")
        else:
            _write_exclusive(path, payload)
        _write_latest(self.execution_latest_path, payload)
        return path

    def read_execution(self) -> dict[str, Any] | None:
        if not self.execution_latest_path.exists():
            return None
        payload = _read_json(self.execution_latest_path)
        if not _hashed_artifact_valid(payload, "execution_hash"):
            raise FomcLiveError("fomc_live_execution_hash_invalid")
        return payload

    def halt(self, reason: str, *, occurred_at: str) -> None:
        core = {
            "event_id": self.root.parent.name,
            "occurred_at": _utc(occurred_at).isoformat(),
            "reason": str(reason),
        }
        payload = core | {"halt_hash": canonical_hash(core)}
        if self.halt_path.exists():
            return
        _write_exclusive(self.halt_path, payload)


def _position_symbol(position: Mapping[str, Any]) -> str:
    info = position.get("info") if isinstance(position.get("info"), Mapping) else {}
    return str(position.get("symbol") or info.get("symbol") or "")


def _position_quantity(position: Mapping[str, Any]) -> float:
    info = position.get("info") if isinstance(position.get("info"), Mapping) else {}
    raw_signed = info.get("positionAmt")
    if raw_signed not in (None, ""):
        return _float(raw_signed)
    quantity = abs(_float(position.get("contracts")))
    side = str(position.get("side") or "").lower()
    return -quantity if side == "short" else quantity


def _position_average(position: Mapping[str, Any]) -> float:
    info = position.get("info") if isinstance(position.get("info"), Mapping) else {}
    return _float(
        position.get("entryPrice")
        or position.get("average")
        or info.get("entryPrice")
        or info.get("breakEvenPrice")
    )


def _position_margin_mode(value: Mapping[str, Any]) -> str | None:
    info = value.get("info") if isinstance(value.get("info"), Mapping) else {}
    mode = value.get("marginMode") or info.get("marginType")
    if mode:
        return str(mode).lower()
    isolated = info.get("isolated")
    if isolated is None:
        return None
    return "isolated" if str(isolated).lower() in _TRUE_VALUES else "cross"


def _configured_leverage(value: Mapping[str, Any]) -> float:
    info = value.get("info") if isinstance(value.get("info"), Mapping) else {}
    return _float(
        value.get("leverage")
        or value.get("longLeverage")
        or value.get("shortLeverage")
        or info.get("leverage")
    )


def _exchange_status(value: object) -> str:
    status = str(value or "").strip().lower()
    return {
        "new": "open",
        "untriggered": "open",
        "triggered": "closed",
        "filled": "closed",
        "cancelled": "canceled",
    }.get(status, status)


def _order_view(order: Mapping[str, Any], *, fallback_symbol: str = "") -> dict[str, Any]:
    info = order.get("info") if isinstance(order.get("info"), Mapping) else {}
    trigger = (
        order.get("stopPrice")
        or order.get("triggerPrice")
        or info.get("stopPrice")
        or info.get("triggerPrice")
    )
    return {
        "id": str(
            order.get("id")
            or order.get("orderId")
            or order.get("algoId")
            or info.get("orderId")
            or info.get("algoId")
            or ""
        ),
        "client_order_id": str(
            order.get("clientOrderId")
            or order.get("clientAlgoId")
            or info.get("clientOrderId")
            or info.get("clientAlgoId")
            or ""
        ),
        "symbol": str(order.get("symbol") or fallback_symbol),
        "type": str(
            order.get("type")
            or order.get("orderType")
            or info.get("origType")
            or info.get("orderType")
            or info.get("type")
            or ""
        ),
        "working_type": str(
            order.get("workingType")
            or order.get("triggerType")
            or info.get("workingType")
            or info.get("triggerType")
            or ""
        ),
        "side": str(order.get("side") or info.get("side") or "").lower(),
        "trigger_price": _float(trigger) if trigger not in (None, "") else None,
        "reduce_only": bool(
            order.get("reduceOnly")
            or str(info.get("reduceOnly") or "").lower() == "true"
        ),
        "close_position": bool(
            order.get("closePosition")
            or str(info.get("closePosition") or "").lower() == "true"
        ),
        "status": _exchange_status(
            order.get("status")
            or order.get("algoStatus")
            or info.get("status")
            or info.get("algoStatus")
        ),
        "actual_order_id": str(
            order.get("actualOrderId") or info.get("actualOrderId") or ""
        ),
    }


def _protective_stop_shape_matches(
    stop: Mapping[str, Any],
    *,
    signed_quantity: float,
    stop_price: float,
    price_tick: float,
) -> bool:
    """Bind an owned stop to the exact close direction and trigger semantics."""

    expected_side = "sell" if signed_quantity > 0.0 else "buy"
    observed_price = _float(stop.get("trigger_price"), math.nan)
    return (
        signed_quantity != 0.0
        and stop.get("close_position") is True
        and str(stop.get("side") or "").lower() == expected_side
        and str(stop.get("type") or "").upper() == "STOP_MARKET"
        and str(stop.get("working_type") or "").upper() == "MARK_PRICE"
        and math.isfinite(stop_price)
        and math.isfinite(observed_price)
        and abs(observed_price - stop_price) <= max(price_tick, 1e-12)
    )


def _fetch_all_open_orders(exchange: Any) -> list[Mapping[str, Any]]:
    options = getattr(exchange, "options", None)
    if not isinstance(options, dict):
        return list(
            call_with_time_sync_retry(
                exchange, exchange.fetch_open_orders, retry_attempts=2
            )
        )
    warning_key = "warnOnFetchOpenOrdersWithoutSymbol"
    sentinel = object()
    previous = options.get(warning_key, sentinel)
    options[warning_key] = False
    try:
        return list(
            call_with_time_sync_retry(
                exchange, exchange.fetch_open_orders, retry_attempts=2
            )
        )
    finally:
        if previous is sentinel:
            options.pop(warning_key, None)
        else:
            options[warning_key] = previous


def _fetch_order_by_client_id(
    exchange: Any,
    event: FomcEventDefinition,
    *,
    ccxt_symbol: str,
    client_order_id: str,
    conditional: bool | None = None,
) -> Mapping[str, Any]:
    """Read one exact Binance order without guessing from an account-wide list."""

    endpoint_groups: list[tuple[tuple[str, ...], dict[str, Any]]] = []
    if conditional is not True:
        endpoint_groups.append(
            (
                ("fapiPrivateGetOrder", "fapi_private_get_order"),
                {"symbol": event.symbol, "origClientOrderId": client_order_id},
            )
        )
    if conditional is not False:
        endpoint_groups.append(
            (
                ("fapiPrivateGetAlgoOrder", "fapi_private_get_algo_order"),
                {"symbol": event.symbol, "clientAlgoId": client_order_id},
            )
        )
    failures: list[Exception] = []
    for names, request in endpoint_groups:
        for name in names:
            operation = getattr(exchange, name, None)
            if not callable(operation):
                continue
            try:
                payload = call_with_time_sync_retry(
                    exchange,
                    operation,
                    request,
                    retry_attempts=2,
                )
            except Exception as exc:
                failures.append(exc)
                continue
            if isinstance(payload, Mapping):
                view = _exchange_response_view(payload)
                if view["client_order_id"] != client_order_id:
                    raise FomcLiveError("fomc_live_order_client_identity_mismatch")
                return payload

    fetch_order = getattr(exchange, "fetch_order", None)
    if callable(fetch_order):
        parameter_sets = []
        if conditional is not True:
            parameter_sets.append({"origClientOrderId": client_order_id})
        if conditional is not False:
            parameter_sets.append({"stop": True, "clientAlgoId": client_order_id})
        for params in parameter_sets:
            try:
                payload = call_with_time_sync_retry(
                    exchange,
                    fetch_order,
                    "",
                    ccxt_symbol,
                    params,
                    retry_attempts=2,
                )
            except Exception as exc:
                failures.append(exc)
                continue
            if isinstance(payload, Mapping):
                view = _exchange_response_view(payload)
                if view["client_order_id"] != client_order_id:
                    raise FomcLiveError("fomc_live_order_client_identity_mismatch")
                return payload

    operation = getattr(exchange, "fetch_orders", None)
    if callable(operation):
        parameter_sets: list[dict[str, Any]] = []
        if conditional is not True:
            parameter_sets.append({})
        if conditional is not False:
            parameter_sets.append({"stop": True})
        matches: list[Mapping[str, Any]] = []
        for params in parameter_sets:
            try:
                rows = call_with_time_sync_retry(
                    exchange,
                    operation,
                    ccxt_symbol,
                    None,
                    None,
                    params,
                    retry_attempts=2,
                )
            except TypeError:
                if params:
                    continue
                try:
                    rows = call_with_time_sync_retry(
                        exchange,
                        operation,
                        ccxt_symbol,
                        retry_attempts=2,
                    )
                except Exception as exc:
                    failures.append(exc)
                    continue
            except Exception as exc:
                failures.append(exc)
                continue
            matches.extend(
                row
                for row in rows or ()
                if isinstance(row, Mapping)
                and _order_view(row, fallback_symbol=ccxt_symbol)["client_order_id"]
                == client_order_id
            )
        unique = {
            (_order_view(row, fallback_symbol=ccxt_symbol)["id"], canonical_hash(row)): row
            for row in matches
        }
        if len(unique) == 1:
            return next(iter(unique.values()))
        if len(unique) > 1:
            raise FomcLiveError("fomc_live_order_client_identity_ambiguous")
    detail = f":{type(failures[-1]).__name__}" if failures else ""
    raise FomcLiveError(f"fomc_live_order_client_identity_unavailable{detail}")


def _api_restrictions(exchange: Any) -> dict[str, bool] | None:
    for name in ("sapiGetAccountApiRestrictions", "sapi_get_account_apirestrictions"):
        operation = getattr(exchange, name, None)
        if not callable(operation):
            continue
        payload = call_with_time_sync_retry(exchange, operation, retry_attempts=2)
        if isinstance(payload, Mapping):
            return {
                key: bool(payload.get(key))
                for key in (
                    "enableReading",
                    "enableSpotAndMarginTrading",
                    "enableFutures",
                    "enableWithdrawals",
                    "ipRestrict",
                )
            }
    return None


def _trading_fee(exchange: Any, symbol: str) -> dict[str, float]:
    operation = getattr(exchange, "fetch_trading_fee", None)
    if callable(operation):
        payload = call_with_time_sync_retry(
            exchange, operation, symbol, retry_attempts=2
        )
    else:
        operation = getattr(exchange, "fetch_trading_fees", None)
        if not callable(operation):
            raise RuntimeError("fomc_live_trading_fee_query_unavailable")
        rows = call_with_time_sync_retry(exchange, operation, retry_attempts=2)
        payload = rows.get(symbol) if isinstance(rows, Mapping) else None
    if not isinstance(payload, Mapping):
        raise ValueError("fomc_live_trading_fee_invalid")
    maker = _float(payload.get("maker"), math.nan)
    taker = _float(payload.get("taker"), math.nan)
    if not all(math.isfinite(value) and 0.0 <= value < 1.0 for value in (maker, taker)):
        raise ValueError("fomc_live_trading_fee_invalid")
    return {"maker": maker, "taker": taker}


def _configuration_row(
    payload: object,
    symbol: str,
) -> Mapping[str, Any] | None:
    if isinstance(payload, Mapping):
        direct = payload.get(symbol)
        if isinstance(direct, Mapping):
            return direct
        if "leverage" in payload or "marginMode" in payload or "marginType" in payload:
            return payload
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        for row in payload:
            if isinstance(row, Mapping) and _position_symbol(row) == symbol:
                return row
    return None


def build_fomc_live_account_preflight(
    settings: Settings,
    event: FomcEventDefinition,
    *,
    observed_at: str | dt.datetime,
    exchange: Any | None = None,
    halt_present: bool = False,
    expected_position_quantity: float = 0.0,
    expected_stop_client_id: str | None = None,
    expected_stop_price: float | None = None,
    price_tick: float | None = None,
) -> dict[str, Any]:
    """Read current private account state without calling a mutating endpoint."""

    if not settings.contract_market or settings.exchange_id != "binance":
        raise FomcLiveError("fomc_live_binance_usdm_required")
    now = _utc(observed_at)
    result: dict[str, Any] = {
        "schema_version": FOMC_LIVE_PREFLIGHT_VERSION,
        "artifact_type": "fomc_live_account_preflight",
        "event_id": event.event_id,
        "created_at": now.isoformat(),
        "meta": {
            "read_only": True,
            "private_api_used": True,
            "private_api_order_attempted": False,
            "exchange_mutation_attempted": False,
            "live_orders_allowed": False,
        },
        "account": {
            "credentials_present": bool(
                settings.binance_api_key and settings.binance_api_secret
            ),
            "permissions": {},
            "balance": {},
            "position_mode": {},
            "positions": [],
            "regular_open_orders": [],
            "conditional_open_orders": [],
            "configuration": {},
            "trading_fee": {},
            "resolved_symbol": None,
            "market_rules": {},
            "account_scope_hash": None,
        },
        "expected": {
            "position_quantity": float(expected_position_quantity),
            "stop_client_order_id": expected_stop_client_id,
            "stop_price": expected_stop_price,
            "stop_side": (
                "sell"
                if expected_position_quantity > 0.0
                else "buy" if expected_position_quantity < 0.0 else None
            ),
            "stop_order_type": "STOP_MARKET" if expected_stop_client_id else None,
            "stop_working_type": "MARK_PRICE" if expected_stop_client_id else None,
        },
        "diagnostics": {
            "errors": {},
            "gates": {},
            "blockers": [],
            "verdict": "blocked_fomc_live_account_preflight",
        },
    }
    if not result["account"]["credentials_present"]:
        result["diagnostics"]["errors"]["credentials"] = "missing_api_credentials"
        return _finalize_fomc_live_preflight(result, halt_present=halt_present)

    owned_exchange = exchange is None
    client = exchange or build_exchange(settings, private=True)
    ccxt_symbol: str | None = None
    raw_balance: Mapping[str, Any] = {}
    try:
        try:
            markets = call_with_time_sync_retry(
                client,
                client.load_markets,
                sync_before=True,
                retry_attempts=2,
            )
            configured = f"{event.symbol[:-4]}/USDT"
            ccxt_symbol = resolve_market_symbol(markets, configured, settings)
            market = markets[ccxt_symbol]
            if (
                str(market.get("id") or "").upper() != event.symbol
                or market.get("linear") is not True
                or market.get("swap") is not True
                or str(market.get("settle") or "").upper() != "USDT"
                or market.get("active") is False
            ):
                raise ValueError("fomc_live_market_identity_invalid")
            result["account"]["resolved_symbol"] = ccxt_symbol
            result["account"]["market_rules"] = _market_rules(market)
        except Exception as exc:
            result["diagnostics"]["errors"]["market"] = _safe_error(exc, settings)
            return _finalize_fomc_live_preflight(result, halt_present=halt_present)

        try:
            raw = call_with_time_sync_retry(client, client.fetch_balance, retry_attempts=2)
            if not isinstance(raw, Mapping):
                raise ValueError("fomc_live_balance_invalid")
            raw_balance = raw
            result["account"]["balance"] = extract_quote_balance(dict(raw), settings)
        except Exception as exc:
            result["diagnostics"]["errors"]["balance"] = _safe_error(exc, settings)

        try:
            permissions = _api_restrictions(client)
            if permissions is None:
                raise RuntimeError("fomc_live_api_restrictions_unavailable")
            result["account"]["permissions"] = permissions
        except Exception as exc:
            result["diagnostics"]["errors"]["permissions"] = _safe_error(exc, settings)

        try:
            mode = call_with_time_sync_retry(
                client,
                client.fetch_position_mode,
                params={"subType": "linear"},
                retry_attempts=2,
            )
            result["account"]["position_mode"] = {"hedged": bool(mode.get("hedged"))}
        except Exception as exc:
            result["diagnostics"]["errors"]["position_mode"] = _safe_error(exc, settings)

        try:
            rows = call_with_time_sync_retry(
                client, client.fetch_positions, retry_attempts=2
            )
            positions = []
            for row in rows:
                if not isinstance(row, Mapping):
                    raise ValueError("fomc_live_position_row_invalid")
                quantity = _position_quantity(row)
                if abs(quantity) <= 1e-15:
                    continue
                positions.append(
                    {
                        "symbol": _position_symbol(row),
                        "quantity": quantity,
                        "average_price": _position_average(row),
                        "notional_usdt": abs(
                            _float(
                                row.get("notional")
                                or (row.get("info") or {}).get("notional")
                            )
                        ),
                    }
                )
            result["account"]["positions"] = positions
        except Exception as exc:
            result["diagnostics"]["errors"]["positions"] = _safe_error(exc, settings)

        try:
            regular = [
                _order_view(row)
                for row in _fetch_all_open_orders(client)
                if isinstance(row, Mapping)
            ]
            result["account"]["regular_open_orders"] = regular
        except Exception as exc:
            result["diagnostics"]["errors"]["regular_orders"] = _safe_error(
                exc, settings
            )

        try:
            assert ccxt_symbol is not None
            rows = call_with_time_sync_retry(
                client,
                client.fetch_open_orders,
                ccxt_symbol,
                params={"stop": True},
                retry_attempts=2,
            )
            conditional = []
            seen: set[tuple[str, str]] = set()
            for row in rows:
                if not isinstance(row, Mapping):
                    raise ValueError("fomc_live_conditional_order_row_invalid")
                view = _order_view(row, fallback_symbol=ccxt_symbol)
                identity = (view["id"], view["client_order_id"])
                if identity in seen:
                    continue
                seen.add(identity)
                conditional.append(view)
            result["account"]["conditional_open_orders"] = conditional
        except Exception as exc:
            result["diagnostics"]["errors"]["conditional_orders"] = _safe_error(
                exc, settings
            )

        try:
            assert ccxt_symbol is not None
            leverages = call_with_time_sync_retry(
                client,
                client.fetch_leverages,
                [ccxt_symbol],
                params={"subType": "linear"},
                retry_attempts=2,
            )
            margins = call_with_time_sync_retry(
                client,
                client.fetch_margin_modes,
                [ccxt_symbol],
                params={"subType": "linear"},
                retry_attempts=2,
            )
            leverage_row = _configuration_row(leverages, ccxt_symbol)
            margin_row = _configuration_row(margins, ccxt_symbol)
            result["account"]["configuration"] = {
                "leverage": _configured_leverage(leverage_row or {}),
                "margin_mode": _position_margin_mode(margin_row or {}),
                "present": leverage_row is not None and margin_row is not None,
            }
        except Exception as exc:
            result["diagnostics"]["errors"]["configuration"] = _safe_error(
                exc, settings
            )

        try:
            assert ccxt_symbol is not None
            result["account"]["trading_fee"] = _trading_fee(client, ccxt_symbol)
        except Exception as exc:
            result["diagnostics"]["errors"]["trading_fee"] = _safe_error(
                exc, settings
            )

        balance_info = (
            raw_balance.get("info")
            if isinstance(raw_balance.get("info"), Mapping)
            else {}
        )
        account_identity = {
            "exchange_id": settings.exchange_id,
            "market_type": settings.market_type,
            "quote_asset": settings.quote_currency,
            "api_key_fingerprint": _api_key_fingerprint(settings),
            "account_alias": str(
                balance_info.get("accountAlias")
                or balance_info.get("accountType")
                or "binance-usdm"
            ),
            "permissions": result["account"]["permissions"],
        }
        result["account"]["account_scope_hash"] = canonical_hash(account_identity)
        return _finalize_fomc_live_preflight(
            result,
            halt_present=halt_present,
            price_tick=price_tick,
        )
    finally:
        if owned_exchange:
            close = getattr(client, "close", None)
            if callable(close):
                close()


def _finalize_fomc_live_preflight(
    result: dict[str, Any],
    *,
    halt_present: bool,
    price_tick: float | None = None,
) -> dict[str, Any]:
    account = result["account"]
    errors = result["diagnostics"]["errors"]
    permissions = account.get("permissions") or {}
    balance = account.get("balance") or {}
    positions = account.get("positions") or []
    regular = account.get("regular_open_orders") or []
    conditional = account.get("conditional_open_orders") or []
    configuration = account.get("configuration") or {}
    trading_fee = account.get("trading_fee") or {}
    market_rules = account.get("market_rules") or {}
    expected_quantity = _float(result["expected"]["position_quantity"])
    resolved_symbol = str(account.get("resolved_symbol") or "")
    matching_positions = [
        row
        for row in positions
        if row.get("symbol") == resolved_symbol
        and abs(_float(row.get("quantity")) - expected_quantity) <= 1e-12
    ]
    expected_position_state = (
        not positions
        if abs(expected_quantity) <= 1e-15
        else len(positions) == 1 and len(matching_positions) == 1
    )
    expected_stop_id = result["expected"].get("stop_client_order_id")
    matching_stops = [
        row for row in conditional if row.get("client_order_id") == expected_stop_id
    ]
    stop_shape_matches = True
    if expected_stop_id and matching_stops:
        stop_shape_matches = _protective_stop_shape_matches(
            matching_stops[0],
            signed_quantity=expected_quantity,
            stop_price=_float(result["expected"].get("stop_price"), math.nan),
            price_tick=_float(price_tick),
        )
    expected_stop_state = (
        not conditional
        if expected_stop_id is None
        else len(conditional) == 1
        and len(matching_stops) == 1
        and stop_shape_matches
    )
    leverage = _float(configuration.get("leverage"))
    gates = {
        "no_collection_errors": not errors,
        "credentials_present": bool(account.get("credentials_present")),
        "account_scope_bound": is_sha256(account.get("account_scope_hash")),
        "market_rules_bound": (
            is_sha256(market_rules.get("exchange_rules_hash"))
            and market_rules.get("symbol")
            and market_rules.get("settle") == "USDT"
            and market_rules.get("linear") is True
            and market_rules.get("swap") is True
            and market_rules.get("active") is not False
        ),
        "reading_enabled": permissions.get("enableReading") is True,
        "futures_enabled": permissions.get("enableFutures") is True,
        "withdrawals_disabled": permissions.get("enableWithdrawals") is False,
        "ip_restricted": permissions.get("ipRestrict") is True,
        "position_mode_oneway": (account.get("position_mode") or {}).get("hedged")
        is False,
        "position_state_exact": expected_position_state,
        "regular_orders_absent": not regular,
        "conditional_stop_state_exact": expected_stop_state,
        "isolated_margin": configuration.get("margin_mode") == "isolated",
        "leverage_within_contract": 0.0 < leverage
        <= DEFAULT_SMALL_ACCOUNT_POLICY.maximum_futures_leverage,
        "fee_within_contract": 0.0
        <= _float(trading_fee.get("taker"), math.inf)
        <= FOMC_LIVE_MAX_TAKER_FEE_RATE,
        "capital_available": _float(balance.get("quote_free"))
        >= FOMC_LIVE_MINIMUM_FREE_BALANCE_USDT,
        "halt_absent": not halt_present,
    }
    blockers = [name for name, passed in gates.items() if not passed]
    result["diagnostics"]["gates"] = gates
    result["diagnostics"]["blockers"] = blockers
    result["diagnostics"]["verdict"] = (
        "fomc_live_account_preflight_pass"
        if not blockers
        else "blocked_fomc_live_account_preflight"
    )
    core = {key: value for key, value in result.items() if key != "preflight_hash"}
    result["preflight_hash"] = canonical_hash(core)
    return result


def account_risk_snapshot_from_preflight(
    preflight: Mapping[str, Any],
) -> AccountRiskSnapshot:
    if not _hashed_artifact_valid(preflight, "preflight_hash"):
        raise FomcLiveError("fomc_live_preflight_hash_invalid")
    if (preflight.get("diagnostics") or {}).get("verdict") != (
        "fomc_live_account_preflight_pass"
    ):
        raise FomcLiveError("fomc_live_preflight_not_passed")
    equity = _float((preflight.get("account") or {}).get("balance", {}).get("margin_balance"))
    if equity <= 0.0:
        raise FomcLiveError("fomc_live_equity_invalid")
    baseline = max(equity, DEFAULT_SMALL_ACCOUNT_POLICY.initial_equity_usdt)
    return AccountRiskSnapshot(
        net_liquidation_equity_usdt=equity,
        high_water_equity_usdt=baseline,
        day_start_equity_usdt=equity,
        rolling_24h_start_equity_usdt=equity,
        protective_cycle_verified=False,
    )


def build_fomc_live_readiness(
    event: FomcEventDefinition,
    shadow_result: Mapping[str, Any],
    preflight: Mapping[str, Any],
) -> tuple[dict[str, Any], FomcStandardChain | None]:
    """Bind an exact order-free candidate plan that only a matching arm may route."""

    if not _hashed_artifact_valid(shadow_result, "result_hash"):
        raise FomcLiveError("fomc_live_shadow_result_hash_invalid")
    if not _hashed_artifact_valid(preflight, "preflight_hash"):
        raise FomcLiveError("fomc_live_preflight_hash_invalid")
    observed_at = _utc(str(shadow_result["observed_at"]))
    blockers: list[str] = []
    if shadow_result.get("stage") != "ARMED":
        blockers.append("shadow_signal_not_armed")
    if (preflight.get("diagnostics") or {}).get("verdict") != (
        "fomc_live_account_preflight_pass"
    ):
        blockers.append("private_account_preflight_not_passed")
    if observed_at >= event.entry_cutoff_time:
        blockers.append("entry_cutoff_reached")
    shadow_permissions = shadow_result.get("permissions") or {}
    if any(
        shadow_permissions.get(name) is not False
        for name in (
            "orders_authorized",
            "paper_or_live_allowed",
            "private_api_used",
            "exchange_mutation_attempted",
        )
    ):
        blockers.append("shadow_permission_boundary_invalid")

    chain: FomcStandardChain | None = None
    signal: FomcSignalScan | None = None
    market: FomcMarketObservation | None = None
    freeze: FomcFreezeSnapshot | None = None
    if not blockers:
        try:
            freeze = FomcFreezeSnapshot.from_mapping(shadow_result["freeze"])
            signal = FomcSignalScan.from_mapping(shadow_result["signal"])
            market = FomcMarketObservation.from_mapping(shadow_result["market"])
            private_rules = (preflight.get("account") or {}).get("market_rules") or {}
            if (
                private_rules.get("exchange_rules_hash")
                != market.exchange_rules_hash
                or private_rules.get("symbol") != event.symbol
                or private_rules.get("settle") != "USDT"
                or private_rules.get("linear") is not True
                or private_rules.get("swap") is not True
                or private_rules.get("active") is False
                or private_rules.get("price_tick") != market.price_tick
                or private_rules.get("quantity_step") != market.quantity_step
                or private_rules.get("minimum_quantity") != market.minimum_quantity
                or private_rules.get("minimum_notional_usdt")
                != market.minimum_notional_usdt
                or private_rules.get("contract_size") != 1.0
            ):
                blockers.append("public_private_exchange_rules_mismatch")
            leverage = _float(
                (preflight.get("account") or {}).get("configuration", {}).get("leverage")
            )
            chain = build_fomc_standard_chain(
                event,
                freeze,
                signal,
                market,
                account_snapshot=account_risk_snapshot_from_preflight(preflight),
                orders_authorized=False,
                leverage=leverage,
            )
        except Exception as exc:
            blockers.append(f"candidate_chain_invalid:{type(exc).__name__}")
    if chain is not None:
        if chain.blockers != ("FOMC_MANUAL_ARM_REQUIRED",):
            blockers.append("candidate_plan_has_non_arm_blockers")
        if len(chain.batch.plan.orders) != 2:
            blockers.append("candidate_plan_order_count_invalid")
        elif (
            chain.batch.plan.orders[0].order_type.upper() != "MARKET"
            or chain.batch.plan.orders[1].order_type.upper() != "STOP_MARKET"
            or not chain.batch.plan.orders[1].close_position
        ):
            blockers.append("candidate_plan_shape_invalid")
        if chain.sizing is None or not chain.sizing.allowed:
            blockers.append("candidate_sizing_not_allowed")
        elif (
            chain.sizing.estimated_stress_loss_usdt
            > DEFAULT_SMALL_ACCOUNT_POLICY.first_live_risk_cap_usdt + 1e-12
        ):
            blockers.append("first_live_risk_cap_exceeded")

    expires_at = min(
        observed_at + dt.timedelta(seconds=FOMC_LIVE_ARM_TTL_SECONDS),
        event.entry_cutoff_time,
    )
    plan_scope: dict[str, Any] | None = None
    management_partial_reduction = None
    if chain is not None and chain.sizing is not None and signal is not None and market is not None:
        entry_order, stop_order = chain.batch.plan.orders
        management_partial_reduction = calculate_one_third_exit_quantity(
            initial_quantity=_float(entry_order.quantity, math.nan),
            quantity_step=market.quantity_step,
            minimum_quantity=market.minimum_quantity,
        )
        if not management_partial_reduction.allowed:
            blockers.extend(management_partial_reduction.reasons)
        if not management_partial_reduction.allowed:
            entry_order = stop_order = None
        if entry_order is not None and stop_order is not None:
            plan_scope = {
                "event_id": event.event_id,
                "account_scope_hash": (preflight.get("account") or {}).get(
                    "account_scope_hash"
                ),
                "strategy_id": event.strategy_id,
                "strategy_version": event.strategy_version,
                "symbol": event.symbol,
                "instrument_key": event.instrument_key,
                "side": signal.side,
                "quantity": entry_order.quantity,
                "reference_entry_price": market.entry_price(signal.side),
                "maximum_notional_usdt": chain.sizing.notional_usdt,
                "maximum_stress_loss_usdt": chain.sizing.estimated_stress_loss_usdt,
                "risk_per_unit_usdt": chain.sizing.risk_per_unit_usdt,
                "target_price": chain.structure_target_price,
                "stop_price": stop_order.stop_price,
                "exchange_rules_hash": market.exchange_rules_hash,
                "price_tick": market.price_tick,
                "quantity_step": market.quantity_step,
                "minimum_quantity": market.minimum_quantity,
                "minimum_notional_usdt": market.minimum_notional_usdt,
                "contract_size": 1.0,
                "leverage": chain.sizing.leverage,
                "margin_mode": "isolated",
                "entry_client_order_id": entry_order.client_order_id,
                "stop_client_order_id": stop_order.client_order_id,
                "force_exit_at": event.force_exit_at,
                "emergency_flatten_allowed": True,
                "maximum_adverse_slippage_bps": FOMC_LIVE_MAX_ADVERSE_SLIPPAGE_BPS,
                "management_contract_version": FOMC_LIVE_MANAGEMENT_VERSION,
                "freeze_h0": chain.freeze.h0,
                "freeze_l0": chain.freeze.l0,
                "costs": asdict(chain.costs),
                "one_third_partial_quantity": management_partial_reduction.partial_quantity,
                "one_third_remaining_quantity": management_partial_reduction.remaining_quantity,
            }
    gates = {
        "shadow_signal_armed": shadow_result.get("stage") == "ARMED",
        "private_account_preflight_passed": (
            (preflight.get("diagnostics") or {}).get("verdict")
            == "fomc_live_account_preflight_pass"
        ),
        "candidate_plan_bound": plan_scope is not None,
        "manual_arm_is_only_remaining_authority": (
            chain is not None and chain.blockers == ("FOMC_MANUAL_ARM_REQUIRED",)
        ),
        "entry_window_open": observed_at < event.entry_cutoff_time,
        "orders_not_yet_authorized": True,
        "exchange_mutation_not_attempted": True,
    }
    blockers.extend(name for name, passed in gates.items() if not passed)
    blockers = list(dict.fromkeys(blockers))
    core = {
        "schema_version": FOMC_LIVE_READINESS_VERSION,
        "artifact_type": "fomc_live_readiness",
        "event_id": event.event_id,
        "created_at": observed_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "shadow_result_hash": shadow_result["result_hash"],
        "preflight_hash": preflight["preflight_hash"],
        "batch_id": chain.batch.manifest.batch_id if chain is not None else None,
        "manifest_hash": (
            chain.batch.manifest.manifest_hash if chain is not None else None
        ),
        "plan_hash": chain.batch.plan.plan_hash if chain is not None else None,
        "signal_identity": (
            {
                "side": signal.side,
                "anchor_candle_id": signal.anchor_candle_id,
                "breakout_candle_id": signal.breakout_candle_id,
                "retest_candle_ids": list(signal.retest_candle_ids),
                "structural_stop_price": signal.structural_stop_price,
                "signal_available_at": signal.signal_available_at,
            }
            if signal is not None
            else None
        ),
        "scope": plan_scope,
        "gates": gates,
        "blockers": blockers,
        "verdict": "ready_for_fomc_live_arm" if not blockers else "blocked_fomc_live_readiness",
        "permissions": {
            "orders_authorized": False,
            "private_api_used": True,
            "private_api_order_attempted": False,
            "exchange_mutation_attempted": False,
            "manual_arm_required": True,
        },
    }
    return core | {"readiness_hash": canonical_hash(core)}, chain


def build_fomc_live_arm(
    readiness: Mapping[str, Any],
    *,
    arm_token: str,
    armed_at: str | dt.datetime,
    confirmed_readiness_hash: str,
) -> dict[str, Any]:
    if not _hashed_artifact_valid(readiness, "readiness_hash"):
        raise FomcLiveError("fomc_live_readiness_hash_invalid")
    if readiness.get("verdict") != "ready_for_fomc_live_arm":
        raise FomcLiveError("fomc_live_readiness_not_passed")
    if confirmed_readiness_hash != readiness.get("readiness_hash"):
        raise FomcLiveError("fomc_live_readiness_manual_confirmation_mismatch")
    if not arm_token or len(arm_token) < 32:
        raise FomcLiveError("fomc_live_arm_token_too_short")
    now = _utc(armed_at)
    expires = _utc(str(readiness["expires_at"]))
    if now >= expires:
        raise FomcLiveError("fomc_live_readiness_expired")
    scope = readiness.get("scope")
    if not isinstance(scope, Mapping):
        raise FomcLiveError("fomc_live_readiness_scope_missing")
    core = {
        "schema_version": FOMC_LIVE_ARM_VERSION,
        "artifact_type": "fomc_live_manual_arm",
        "status": "armed",
        "event_id": readiness["event_id"],
        "readiness_hash": readiness["readiness_hash"],
        "batch_id": readiness["batch_id"],
        "manifest_hash": readiness["manifest_hash"],
        "plan_hash": readiness["plan_hash"],
        "account_scope_hash": scope["account_scope_hash"],
        "arm_token_sha256": hashlib.sha256(arm_token.encode("utf-8")).hexdigest(),
        "armed_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "single_use": True,
        "scope": dict(scope),
    }
    arm_id = canonical_hash(core)
    owner_core = {
        "arm_id": arm_id,
        "event_id": core["event_id"],
        "readiness_hash": core["readiness_hash"],
        "batch_id": core["batch_id"],
        "plan_hash": core["plan_hash"],
        "account_scope_hash": core["account_scope_hash"],
        "expires_at": core["expires_at"],
        "scope": core["scope"],
    }
    payload = core | {
        "arm_id": arm_id,
        "owner_authorization_hash": canonical_hash(owner_core),
    }
    validate_fomc_live_arm(payload)
    return payload


def validate_fomc_live_arm(arm: Mapping[str, Any]) -> None:
    required_hashes = (
        "arm_id",
        "event_id",
        "readiness_hash",
        "batch_id",
        "manifest_hash",
        "plan_hash",
        "account_scope_hash",
        "arm_token_sha256",
        "owner_authorization_hash",
    )
    if arm.get("schema_version") != FOMC_LIVE_ARM_VERSION:
        raise FomcLiveError("fomc_live_arm_schema_invalid")
    if arm.get("artifact_type") != "fomc_live_manual_arm" or arm.get("status") != "armed":
        raise FomcLiveError("fomc_live_arm_type_or_status_invalid")
    if any(not is_sha256(arm.get(name)) for name in required_hashes):
        raise FomcLiveError("fomc_live_arm_hash_field_invalid")
    if arm.get("single_use") is not True or not isinstance(arm.get("scope"), Mapping):
        raise FomcLiveError("fomc_live_arm_scope_invalid")
    try:
        armed_at = _utc(str(arm["armed_at"]))
        expires_at = _utc(str(arm["expires_at"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise FomcLiveError("fomc_live_arm_time_invalid") from exc
    if expires_at <= armed_at:
        raise FomcLiveError("fomc_live_arm_time_order_invalid")
    core = {
        key: arm[key]
        for key in (
            "schema_version",
            "artifact_type",
            "status",
            "event_id",
            "readiness_hash",
            "batch_id",
            "manifest_hash",
            "plan_hash",
            "account_scope_hash",
            "arm_token_sha256",
            "armed_at",
            "expires_at",
            "single_use",
            "scope",
        )
    }
    expected_arm_id = canonical_hash(core)
    if arm.get("arm_id") != expected_arm_id:
        raise FomcLiveError("fomc_live_arm_id_invalid")
    owner_core = {
        "arm_id": expected_arm_id,
        "event_id": arm["event_id"],
        "readiness_hash": arm["readiness_hash"],
        "batch_id": arm["batch_id"],
        "plan_hash": arm["plan_hash"],
        "account_scope_hash": arm["account_scope_hash"],
        "expires_at": arm["expires_at"],
        "scope": arm["scope"],
    }
    if arm.get("owner_authorization_hash") != canonical_hash(owner_core):
        raise FomcLiveError("fomc_live_arm_owner_authorization_invalid")


def _auto_execution_policy_scope() -> dict[str, Any]:
    policy = DEFAULT_SMALL_ACCOUNT_POLICY
    if policy.validate():
        raise FomcLiveError("fomc_live_auto_policy_invalid")
    core = {
        "initial_equity_usdt": policy.initial_equity_usdt,
        "first_live_risk_cap_usdt": policy.first_live_risk_cap_usdt,
        "per_trade_risk_cap_usdt": policy.per_trade_risk_cap_usdt,
        "concurrent_stress_risk_cap_usdt": policy.concurrent_stress_risk_cap_usdt,
        "rolling_24h_loss_limit_usdt": policy.rolling_24h_loss_limit_usdt,
        "strategy_drawdown_limit_usdt": policy.strategy_drawdown_limit_usdt,
        "maximum_crypto_beta_exposures": policy.maximum_crypto_beta_exposures,
        "maximum_futures_leverage": policy.maximum_futures_leverage,
        "maximum_isolated_margin_usdt": policy.maximum_isolated_margin_usdt,
        "maximum_futures_notional_usdt": policy.maximum_futures_notional_usdt,
    }
    return core | {"policy_hash": canonical_hash(core)}


def build_fomc_live_auto_authorization(
    event: FomcEventDefinition,
    preflight: Mapping[str, Any],
    *,
    authorized_at: str | dt.datetime,
) -> dict[str, Any]:
    """Create the owner-authorized, one-event automatic execution boundary."""

    if not _hashed_artifact_valid(preflight, "preflight_hash"):
        raise FomcLiveError("fomc_live_preflight_hash_invalid")
    if (preflight.get("diagnostics") or {}).get("verdict") != (
        "fomc_live_account_preflight_pass"
    ):
        raise FomcLiveError("fomc_live_auto_authorization_preflight_not_passed")
    account_scope_hash = (preflight.get("account") or {}).get("account_scope_hash")
    if not is_sha256(account_scope_hash):
        raise FomcLiveError("fomc_live_auto_authorization_account_scope_invalid")
    now = _utc(authorized_at)
    if now >= event.entry_cutoff_time:
        raise FomcLiveError("fomc_live_auto_authorization_entry_cutoff_reached")
    policy = _auto_execution_policy_scope()
    core = {
        "schema_version": FOMC_LIVE_AUTO_AUTHORIZATION_VERSION,
        "artifact_type": "fomc_live_auto_authorization",
        "status": "authorized",
        "authorization_source": "owner_explicit_auto_execution",
        "event_id": event.event_id,
        "event_definition_hash": event.definition_hash,
        "strategy_id": event.strategy_id,
        "strategy_version": event.strategy_version,
        "symbol": event.symbol,
        "instrument_key": event.instrument_key,
        "account_scope_hash": account_scope_hash,
        "policy": policy,
        "authorized_at": now.isoformat(),
        "expires_at": event.entry_cutoff_time.isoformat(),
        "single_use": True,
    }
    authorization_id = canonical_hash(core)
    owner_core = {
        "authorization_id": authorization_id,
        "event_id": event.event_id,
        "event_definition_hash": event.definition_hash,
        "account_scope_hash": account_scope_hash,
        "policy_hash": policy["policy_hash"],
        "expires_at": core["expires_at"],
    }
    payload = core | {
        "authorization_id": authorization_id,
        "owner_authorization_hash": canonical_hash(owner_core),
    }
    validate_fomc_live_auto_authorization(payload)
    return payload


def validate_fomc_live_auto_authorization(
    authorization: Mapping[str, Any],
) -> None:
    core_fields = (
        "schema_version",
        "artifact_type",
        "status",
        "authorization_source",
        "event_id",
        "event_definition_hash",
        "strategy_id",
        "strategy_version",
        "symbol",
        "instrument_key",
        "account_scope_hash",
        "policy",
        "authorized_at",
        "expires_at",
        "single_use",
    )
    required_hashes = (
        "authorization_id",
        "event_id",
        "event_definition_hash",
        "account_scope_hash",
        "owner_authorization_hash",
    )
    if (
        any(name not in authorization for name in core_fields)
        or authorization.get("schema_version") != FOMC_LIVE_AUTO_AUTHORIZATION_VERSION
        or authorization.get("artifact_type") != "fomc_live_auto_authorization"
        or authorization.get("status") != "authorized"
        or authorization.get("authorization_source")
        != "owner_explicit_auto_execution"
        or authorization.get("single_use") is not True
        or any(not is_sha256(authorization.get(name)) for name in required_hashes)
        or any(
            not isinstance(authorization.get(name), str)
            or not str(authorization.get(name)).strip()
            for name in ("strategy_id", "strategy_version", "symbol", "instrument_key")
        )
    ):
        raise FomcLiveError("fomc_live_auto_authorization_invalid")
    if (
        authorization["strategy_id"] != FOMC_STRATEGY_ID
        or authorization["strategy_version"] != FOMC_STRATEGY_VERSION
    ):
        raise FomcLiveError("fomc_live_auto_authorization_strategy_identity_invalid")
    try:
        authorized_at = _utc(str(authorization["authorized_at"]))
        expires_at = _utc(str(authorization["expires_at"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise FomcLiveError("fomc_live_auto_authorization_time_invalid") from exc
    if expires_at <= authorized_at:
        raise FomcLiveError("fomc_live_auto_authorization_time_order_invalid")
    policy = authorization.get("policy")
    if not isinstance(policy, Mapping) or dict(policy) != _auto_execution_policy_scope():
        raise FomcLiveError("fomc_live_auto_authorization_policy_invalid")
    core = {key: authorization[key] for key in core_fields}
    authorization_id = canonical_hash(core)
    if authorization.get("authorization_id") != authorization_id:
        raise FomcLiveError("fomc_live_auto_authorization_id_invalid")
    owner_core = {
        "authorization_id": authorization_id,
        "event_id": authorization["event_id"],
        "event_definition_hash": authorization["event_definition_hash"],
        "account_scope_hash": authorization["account_scope_hash"],
        "policy_hash": policy["policy_hash"],
        "expires_at": authorization["expires_at"],
    }
    if authorization.get("owner_authorization_hash") != canonical_hash(owner_core):
        raise FomcLiveError("fomc_live_auto_owner_authorization_invalid")


def validate_fomc_live_auto_authorization_consumption(
    consumption: Mapping[str, Any],
) -> None:
    core_fields = (
        "schema_version",
        "artifact_type",
        "authorization_id",
        "event_id",
        "account_scope_hash",
        "arm_id",
        "readiness_hash",
        "consumed_at",
        "single_use",
    )
    hash_fields = (
        "authorization_id",
        "event_id",
        "account_scope_hash",
        "arm_id",
        "readiness_hash",
        "consumption_hash",
    )
    if (
        any(name not in consumption for name in core_fields)
        or consumption.get("schema_version") != FOMC_LIVE_AUTO_AUTHORIZATION_VERSION
        or consumption.get("artifact_type")
        != "fomc_live_auto_authorization_consumption"
        or consumption.get("single_use") is not True
        or any(not is_sha256(consumption.get(name)) for name in hash_fields)
    ):
        raise FomcLiveError("fomc_live_auto_consumption_invalid")
    try:
        _utc(str(consumption["consumed_at"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise FomcLiveError("fomc_live_auto_consumption_time_invalid") from exc
    core = {key: consumption[key] for key in core_fields}
    if consumption.get("consumption_hash") != canonical_hash(core):
        raise FomcLiveError("fomc_live_auto_consumption_hash_invalid")


def validate_fomc_live_auto_arm_secret(secret: Mapping[str, Any]) -> None:
    core_fields = (
        "schema_version",
        "artifact_type",
        "arm_id",
        "arm_token",
        "arm_token_sha256",
    )
    if (
        any(name not in secret for name in core_fields)
        or secret.get("schema_version") != FOMC_LIVE_AUTO_AUTHORIZATION_VERSION
        or secret.get("artifact_type") != "fomc_live_auto_arm_secret"
        or not is_sha256(secret.get("arm_id"))
        or not is_sha256(secret.get("arm_token_sha256"))
        or not is_sha256(secret.get("secret_hash"))
        or not isinstance(secret.get("arm_token"), str)
        or len(str(secret.get("arm_token"))) < 32
    ):
        raise FomcLiveError("fomc_live_auto_arm_secret_invalid")
    token = str(secret["arm_token"])
    if hashlib.sha256(token.encode("utf-8")).hexdigest() != secret.get(
        "arm_token_sha256"
    ):
        raise FomcLiveError("fomc_live_auto_arm_secret_token_invalid")
    core = {key: secret[key] for key in core_fields}
    if secret.get("secret_hash") != canonical_hash(core):
        raise FomcLiveError("fomc_live_auto_arm_secret_hash_invalid")


def _auto_execution_authorization_blockers(
    event: FomcEventDefinition,
    authorization: Mapping[str, Any],
    readiness: Mapping[str, Any],
    *,
    observed_at: str | dt.datetime,
    consumed: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    blockers: list[str] = []
    try:
        validate_fomc_live_auto_authorization(authorization)
    except FomcLiveError as exc:
        return (str(exc),)
    if not _hashed_artifact_valid(readiness, "readiness_hash"):
        blockers.append("fomc_live_auto_readiness_hash_invalid")
    if readiness.get("verdict") != "ready_for_fomc_live_arm":
        blockers.append("fomc_live_auto_readiness_not_passed")
    if authorization.get("event_id") != event.event_id:
        blockers.append("fomc_live_auto_event_id_changed")
    if authorization.get("event_definition_hash") != event.definition_hash:
        blockers.append("fomc_live_auto_event_definition_changed")
    for name in ("strategy_id", "strategy_version", "symbol", "instrument_key"):
        if authorization.get(name) != getattr(event, name):
            blockers.append(f"fomc_live_auto_event_scope_changed:{name}")
    scope = readiness.get("scope")
    if not isinstance(scope, Mapping):
        blockers.append("fomc_live_auto_readiness_scope_missing")
        scope = {}
    if scope.get("event_id") != event.event_id:
        blockers.append("fomc_live_auto_readiness_event_changed")
    if scope.get("account_scope_hash") != authorization.get("account_scope_hash"):
        blockers.append("fomc_live_auto_account_scope_changed")
    policy = authorization.get("policy") or {}
    if _float(scope.get("maximum_notional_usdt"), math.inf) > _float(
        policy.get("maximum_futures_notional_usdt"), 0.0
    ) + 1e-12:
        blockers.append("fomc_live_auto_notional_limit_exceeded")
    if _float(scope.get("maximum_stress_loss_usdt"), math.inf) > _float(
        policy.get("first_live_risk_cap_usdt"), 0.0
    ) + 1e-12:
        blockers.append("fomc_live_auto_first_risk_limit_exceeded")
    if scope.get("margin_mode") != "isolated":
        blockers.append("fomc_live_auto_margin_mode_invalid")
    if not 0.0 < _float(scope.get("leverage"), math.nan) <= _float(
        policy.get("maximum_futures_leverage"), 0.0
    ):
        blockers.append("fomc_live_auto_leverage_limit_exceeded")
    if scope.get("side") not in {"long", "short"}:
        blockers.append("fomc_live_auto_side_invalid")
    now = _utc(observed_at)
    if now >= _utc(str(authorization["expires_at"])):
        blockers.append("fomc_live_auto_authorization_expired")
    if now >= event.entry_cutoff_time:
        blockers.append("fomc_live_auto_entry_cutoff_reached")
    if consumed is not None:
        try:
            validate_fomc_live_auto_authorization_consumption(consumed)
        except FomcLiveError as exc:
            blockers.append(str(exc))
        if consumed.get("authorization_id") != authorization.get("authorization_id"):
            blockers.append("fomc_live_auto_consumption_authorization_mismatch")
        else:
            blockers.append("fomc_live_auto_authorization_consumed")
    return tuple(dict.fromkeys(blockers))


def _auto_execution_arm_state_blockers(
    event: FomcEventDefinition,
    authorization: Mapping[str, Any] | None,
    consumption: Mapping[str, Any] | None,
    readiness: Mapping[str, Any] | None,
    arm: Mapping[str, Any],
    secret: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    """Prove that a persisted arm came from this automatic authorization."""

    blockers: list[str] = []
    if authorization is None:
        blockers.append("fomc_live_auto_authorization_missing")
    else:
        try:
            validate_fomc_live_auto_authorization(authorization)
        except FomcLiveError as exc:
            blockers.append(str(exc))
    if consumption is None:
        blockers.append("fomc_live_auto_consumption_missing")
    else:
        try:
            validate_fomc_live_auto_authorization_consumption(consumption)
        except FomcLiveError as exc:
            blockers.append(str(exc))
    if secret is None:
        blockers.append("fomc_live_auto_arm_secret_missing")
    else:
        try:
            validate_fomc_live_auto_arm_secret(secret)
        except FomcLiveError as exc:
            blockers.append(str(exc))
    if not _hashed_artifact_valid(readiness or {}, "readiness_hash"):
        blockers.append("fomc_live_auto_readiness_hash_invalid")
    if readiness is None:
        blockers.append("fomc_live_auto_readiness_missing")
    if authorization is not None:
        if authorization.get("event_id") != event.event_id:
            blockers.append("fomc_live_auto_event_id_changed")
        if authorization.get("event_definition_hash") != event.definition_hash:
            blockers.append("fomc_live_auto_event_definition_changed")
        for name in ("strategy_id", "strategy_version", "symbol", "instrument_key"):
            if authorization.get(name) != getattr(event, name):
                blockers.append(f"fomc_live_auto_event_scope_changed:{name}")
    if readiness is not None:
        scope = readiness.get("scope")
        if readiness.get("event_id") != event.event_id:
            blockers.append("fomc_live_auto_readiness_event_changed")
        if not isinstance(scope, Mapping):
            blockers.append("fomc_live_auto_readiness_scope_missing")
        elif authorization is not None and scope.get("account_scope_hash") != authorization.get(
            "account_scope_hash"
        ):
            blockers.append("fomc_live_auto_account_scope_changed")
        if readiness.get("readiness_hash") != arm.get("readiness_hash"):
            blockers.append("fomc_live_auto_arm_readiness_mismatch")
    if arm.get("event_id") != event.event_id:
        blockers.append("fomc_live_auto_arm_event_changed")
    if authorization is not None and arm.get("account_scope_hash") != authorization.get(
        "account_scope_hash"
    ):
        blockers.append("fomc_live_auto_arm_account_scope_changed")
    arm_scope = arm.get("scope")
    if not isinstance(arm_scope, Mapping):
        blockers.append("fomc_live_auto_arm_scope_missing")
    elif arm_scope.get("account_scope_hash") != arm.get("account_scope_hash"):
        blockers.append("fomc_live_auto_arm_scope_account_mismatch")
    if consumption is not None:
        if authorization is not None and consumption.get("authorization_id") != authorization.get(
            "authorization_id"
        ):
            blockers.append("fomc_live_auto_consumption_authorization_mismatch")
        if consumption.get("event_id") != arm.get("event_id"):
            blockers.append("fomc_live_auto_consumption_event_mismatch")
        if consumption.get("account_scope_hash") != arm.get("account_scope_hash"):
            blockers.append("fomc_live_auto_consumption_account_scope_mismatch")
        if consumption.get("arm_id") != arm.get("arm_id"):
            blockers.append("fomc_live_auto_consumption_arm_mismatch")
        if consumption.get("readiness_hash") != arm.get("readiness_hash"):
            blockers.append("fomc_live_auto_consumption_readiness_mismatch")
    if secret is not None:
        if secret.get("arm_id") != arm.get("arm_id"):
            blockers.append("fomc_live_auto_secret_arm_mismatch")
        if secret.get("arm_token_sha256") != arm.get("arm_token_sha256"):
            blockers.append("fomc_live_auto_secret_token_mismatch")
    return tuple(dict.fromkeys(blockers))


def fomc_live_arm_valid(
    arm: Mapping[str, Any] | None,
    readiness: Mapping[str, Any],
    *,
    arm_token: str | None,
    live_switch_enabled: bool,
    live_confirmation: str | None,
    observed_at: str | dt.datetime,
    consumed: bool,
) -> bool:
    if not arm or not arm_token or not live_switch_enabled or consumed:
        return False
    try:
        validate_fomc_live_arm(arm)
    except FomcLiveError:
        return False
    return all(
        (
            _hashed_artifact_valid(readiness, "readiness_hash"),
            readiness.get("verdict") == "ready_for_fomc_live_arm",
            arm.get("readiness_hash") == readiness.get("readiness_hash"),
            arm.get("batch_id") == readiness.get("batch_id"),
            arm.get("plan_hash") == readiness.get("plan_hash"),
            arm.get("account_scope_hash")
            == (readiness.get("scope") or {}).get("account_scope_hash"),
            arm.get("arm_token_sha256")
            == hashlib.sha256(arm_token.encode("utf-8")).hexdigest(),
            live_confirmation == arm.get("arm_id"),
            _utc(observed_at) < _utc(str(arm.get("expires_at"))),
        )
    )


def write_fomc_live_environment(
    path: str | os.PathLike[str],
    *,
    arm: Mapping[str, Any],
    arm_token: str,
    enabled: bool = False,
) -> Path:
    validate_fomc_live_arm(arm)
    if hashlib.sha256(arm_token.encode("utf-8")).hexdigest() != arm.get(
        "arm_token_sha256"
    ):
        raise FomcLiveError("fomc_live_environment_token_mismatch")
    target = Path(path).expanduser().resolve()
    lines = (
        f"QOUNT_FOMC_LIVE_ENABLE={'true' if enabled else 'false'}\n"
        f"QOUNT_FOMC_LIVE_CONFIRMATION={arm['arm_id']}\n"
        f"QOUNT_FOMC_ARM_TOKEN={arm_token}\n"
    ).encode("ascii")
    return _write_fomc_live_environment_bytes(target, lines)


def _write_fomc_live_environment_bytes(target: Path, lines: bytes) -> Path:
    _secure_directory(target.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(lines)
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = -1
        os.replace(temporary, target)
        _fsync_directory(target.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()
    if target.read_bytes() != lines or stat.S_IMODE(target.stat().st_mode) != 0o600:
        raise FomcLiveError("fomc_live_environment_write_failed")
    return target


def set_fomc_live_environment_switch(
    path: str | os.PathLike[str],
    *,
    arm_id: str,
    enabled: bool,
) -> Path:
    target = Path(path).expanduser().resolve()
    if target.is_symlink() or not target.is_file():
        raise FomcLiveError("fomc_live_environment_invalid")
    if stat.S_IMODE(target.stat().st_mode) != 0o600:
        raise FomcLiveError("fomc_live_environment_mode_invalid")
    values: dict[str, str] = {}
    for line in target.read_text(encoding="ascii").splitlines():
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    if values.get("QOUNT_FOMC_LIVE_CONFIRMATION") != arm_id:
        raise FomcLiveError("fomc_live_environment_arm_mismatch")
    token = values.get("QOUNT_FOMC_ARM_TOKEN")
    if not token:
        raise FomcLiveError("fomc_live_environment_token_missing")
    lines = (
        f"QOUNT_FOMC_LIVE_ENABLE={'true' if enabled else 'false'}\n"
        f"QOUNT_FOMC_LIVE_CONFIRMATION={arm_id}\n"
        f"QOUNT_FOMC_ARM_TOKEN={token}\n"
    ).encode("ascii")
    return _write_fomc_live_environment_bytes(target, lines)


def _exchange_response_view(response: Mapping[str, Any]) -> dict[str, Any]:
    info = response.get("info") if isinstance(response.get("info"), Mapping) else {}
    return {
        "id": str(
            response.get("id")
            or response.get("orderId")
            or response.get("algoId")
            or info.get("orderId")
            or info.get("algoId")
            or ""
        ),
        "client_order_id": str(
            response.get("clientOrderId")
            or response.get("clientAlgoId")
            or response.get("client_order_id")
            or info.get("clientOrderId")
            or info.get("clientAlgoId")
            or ""
        ),
        "status": _exchange_status(
            response.get("status")
            or response.get("algoStatus")
            or info.get("status")
            or info.get("algoStatus")
        ),
        "symbol": str(response.get("symbol") or info.get("symbol") or ""),
        "type": str(
            response.get("type")
            or response.get("orderType")
            or info.get("origType")
            or info.get("orderType")
            or info.get("type")
            or ""
        ),
        "working_type": str(
            response.get("workingType")
            or response.get("triggerType")
            or response.get("working_type")
            or info.get("workingType")
            or info.get("triggerType")
            or ""
        ),
        "side": str(response.get("side") or info.get("side") or "").lower(),
        "filled": _float(
            response.get("filled")
            or response.get("executedQty")
            or info.get("executedQty")
        ),
        "average": _float(
            response.get("average")
            or response.get("avgPrice")
            or info.get("avgPrice")
        ),
        "trigger_price": _float(
            response.get("stopPrice")
            or response.get("triggerPrice")
            or response.get("trigger_price")
            or info.get("stopPrice")
        ),
        "close_position": bool(
            response.get("closePosition")
            or response.get("close_position")
            or str(info.get("closePosition") or "").lower() == "true"
        ),
        "actual_order_id": str(
            response.get("actualOrderId")
            or response.get("actual_order_id")
            or info.get("actualOrderId")
            or ""
        ),
    }


def _trade_value(trade: Mapping[str, Any], *names: str) -> Any:
    info = trade.get("info") if isinstance(trade.get("info"), Mapping) else {}
    for name in names:
        value = trade.get(name)
        if value not in (None, ""):
            return value
        value = info.get(name)
        if value not in (None, ""):
            return value
    return None


def _trade_time(trade: Mapping[str, Any]) -> str:
    value = _trade_value(trade, "datetime")
    if isinstance(value, str) and value:
        return _utc(value).isoformat()
    timestamp = _float(_trade_value(trade, "timestamp", "time"), math.nan)
    if not math.isfinite(timestamp) or timestamp <= 0.0:
        raise FomcLiveError("fomc_live_trade_time_missing")
    return dt.datetime.fromtimestamp(
        timestamp / 1_000.0, tz=dt.timezone.utc
    ).isoformat()


def _trade_fee(trade: Mapping[str, Any]) -> tuple[float, str]:
    fee = trade.get("fee")
    if not isinstance(fee, Mapping):
        info = trade.get("info") if isinstance(trade.get("info"), Mapping) else {}
        fee = {
            "cost": info.get("commission"),
            "currency": info.get("commissionAsset"),
        }
    cost = _float(fee.get("cost"), math.nan)
    asset = str(fee.get("currency") or "")
    if not math.isfinite(cost) or cost < 0.0 or not asset:
        raise FomcLiveError("fomc_live_trade_fee_invalid")
    return cost, asset


def _normalized_trade(
    trade: Mapping[str, Any],
    *,
    exchange_order_id: str,
    client_order_id: str | None,
) -> dict[str, Any]:
    info = trade.get("info") if isinstance(trade.get("info"), Mapping) else {}
    observed_order_id = str(
        _trade_value(trade, "order", "orderId") or info.get("orderId") or ""
    )
    observed_client_id = str(
        _trade_value(trade, "clientOrderId", "client_order_id")
        or info.get("clientOrderId")
        or ""
    )
    trade_id = str(_trade_value(trade, "id", "tradeId") or info.get("id") or "")
    quantity = _float(_trade_value(trade, "amount", "qty", "quantity"))
    price = _float(_trade_value(trade, "price"))
    fee, fee_asset = _trade_fee(trade)
    if (
        observed_order_id != exchange_order_id
        or (
            client_order_id is not None
            and observed_client_id
            and observed_client_id != client_order_id
        )
        or not trade_id
        or quantity <= 0.0
        or price <= 0.0
    ):
        raise FomcLiveError("fomc_live_trade_identity_or_value_invalid")
    return {
        "exchange_trade_id": trade_id,
        "quantity": quantity,
        "price": price,
        "fee": fee,
        "fee_asset": fee_asset,
        "occurred_at": _trade_time(trade),
    }


def _fetch_market_fill_evidence(
    exchange: Any,
    response: Mapping[str, Any],
    *,
    ccxt_symbol: str,
    client_order_id: str,
    planned_quantity: float | None,
    confirmed_response: Mapping[str, Any] | None = None,
    conditional: bool = False,
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...], str]:
    initial = _exchange_response_view(response)
    exchange_order_id = str(initial.get("id") or "")
    if not exchange_order_id:
        raise FomcLiveError("fomc_live_market_confirmation_unavailable")
    confirmed: Mapping[str, Any] | None = confirmed_response
    if confirmed is None:
        fetch_order = getattr(exchange, "fetch_order", None)
        if not callable(fetch_order):
            raise FomcLiveError("fomc_live_market_confirmation_unavailable")
        if conditional:
            confirmed = call_with_time_sync_retry(
                exchange,
                fetch_order,
                exchange_order_id,
                ccxt_symbol,
                {"stop": True, "clientAlgoId": client_order_id},
                retry_attempts=2,
            )
        else:
            confirmed = call_with_time_sync_retry(
                exchange,
                fetch_order,
                exchange_order_id,
                ccxt_symbol,
                retry_attempts=2,
            )
    if not isinstance(confirmed, Mapping):
        raise FomcLiveError("fomc_live_market_confirmation_invalid")
    view = _exchange_response_view(confirmed)
    if view["id"] != exchange_order_id:
        raise FomcLiveError("fomc_live_market_confirmation_identity_invalid")
    if view["client_order_id"] and view["client_order_id"] != client_order_id:
        raise FomcLiveError("fomc_live_market_confirmation_client_id_invalid")

    trade_order_id = str(view.get("actual_order_id") or exchange_order_id)
    fetch_order_trades = getattr(exchange, "fetch_order_trades", None)
    if callable(fetch_order_trades):
        rows = call_with_time_sync_retry(
            exchange,
            fetch_order_trades,
            trade_order_id,
            ccxt_symbol,
            retry_attempts=2,
        )
    else:
        fetch_my_trades = getattr(exchange, "fetch_my_trades", None)
        if not callable(fetch_my_trades):
            raise FomcLiveError("fomc_live_trade_evidence_unavailable")
        rows = call_with_time_sync_retry(
            exchange,
            fetch_my_trades,
            ccxt_symbol,
            None,
            1_000,
            {"orderId": trade_order_id},
            retry_attempts=2,
        )
    if not isinstance(rows, (list, tuple)):
        raise FomcLiveError("fomc_live_trade_evidence_invalid")
    raw_trades = tuple(row for row in rows if isinstance(row, Mapping))
    if len(raw_trades) != len(rows) or not raw_trades:
        raise FomcLiveError("fomc_live_trade_evidence_incomplete")
    fills = tuple(
        _normalized_trade(
            row,
            exchange_order_id=trade_order_id,
            client_order_id=(
                None
                if conditional and trade_order_id != exchange_order_id
                else client_order_id
            ),
        )
        for row in raw_trades
    )
    if len({row["exchange_trade_id"] for row in fills}) != len(fills):
        raise FomcLiveError("fomc_live_trade_identity_duplicate")
    total = sum(_float(row["quantity"]) for row in fills)
    if total <= 0.0 or abs(_float(view.get("filled")) - total) > 1e-12:
        raise FomcLiveError("fomc_live_market_fill_quantity_readback_mismatch")
    if planned_quantity is not None and total > planned_quantity + 1e-12:
        raise FomcLiveError("fomc_live_market_fill_quantity_exceeds_plan")
    average = sum(
        _float(row["quantity"]) * _float(row["price"]) for row in fills
    ) / total
    status = str(view.get("status") or "").lower()
    full_fill = planned_quantity is None or abs(total - planned_quantity) <= 1e-12
    permitted_statuses = (
        {"closed", "filled"} if full_fill else {"canceled", "expired"}
    )
    if status not in permitted_statuses:
        raise FomcLiveError("fomc_live_market_order_not_closed")
    fee_totals: dict[str, float] = {}
    for row in fills:
        asset = str(row["fee_asset"])
        fee_totals[asset] = fee_totals.get(asset, 0.0) + _float(row["fee"])
    normalized = view | {
        "client_order_id": client_order_id,
        "filled": total,
        "average": average,
        "fill_count": len(fills),
        "fee_usdt": fee_totals.get("USDT", 0.0),
        "fee_totals": fee_totals,
        "fee_conversion_complete": set(fee_totals) <= {"USDT"},
        "terminal_partial_fill": not full_fill,
    }
    evidence_hash = canonical_hash(
        {
            "submit_response": response,
            "confirmed_order": confirmed,
            "trade_order_id": trade_order_id,
            "trades": raw_trades,
            "normalized": normalized,
            "fills": fills,
        }
    )
    return normalized, fills, evidence_hash


def _record_recovered_entry_fill(
    ledger: RuntimeLedger,
    parent_batch: VerifiedDecisionBatch,
    event: FomcEventDefinition,
    *,
    exchange: Any,
    ccxt_symbol: str,
    response: Mapping[str, Any],
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...], str]:
    """Idempotently restore a full or terminal partial entry before any exit."""

    entry_order = parent_batch.plan.orders[0]
    view, fills, evidence_hash = _fetch_market_fill_evidence(
        exchange,
        response,
        ccxt_symbol=ccxt_symbol,
        client_order_id=entry_order.client_order_id,
        planned_quantity=_float(entry_order.quantity),
        confirmed_response=response,
    )
    if (
        view["client_order_id"] != entry_order.client_order_id
        or view["side"] != entry_order.side
        or view["symbol"] not in {event.symbol, ccxt_symbol}
    ):
        raise FomcLiveError("fomc_live_recovered_entry_identity_invalid")
    planned_quantity = _float(entry_order.quantity)
    filled_quantity = _float(view["filled"])
    if filled_quantity <= 0.0 or filled_quantity > planned_quantity + 1e-12:
        raise FomcLiveError("fomc_live_recovered_entry_quantity_invalid")
    full_fill = abs(filled_quantity - planned_quantity) <= 1e-12
    next_status = "FILLED" if full_fill else {
        "canceled": "CANCELED",
        "expired": "EXPIRED",
    }.get(str(view["status"]), "")
    if not next_status:
        raise FomcLiveError("fomc_live_recovered_entry_terminal_state_invalid")
    current = ledger.get_order(entry_order.client_order_id)
    if current["status"] != next_status:
        if current["status"] not in {
            "SUBMITTING",
            "ACKNOWLEDGED",
            "PARTIALLY_FILLED",
            "UNKNOWN",
        }:
            raise FomcLiveError("fomc_live_recovered_entry_state_invalid")
        ledger.transition_order(
            entry_order.client_order_id,
            next_status,
            event_at=_time_after(
                str(current["last_transition_at"]),
                *(str(row["occurred_at"]) for row in fills),
            ),
            source_hash=evidence_hash,
            exchange_order_id=str(view["id"]),
            executed_quantity=_float(view["filled"]),
            average_price=_float(view["average"]),
            reason=(
                "fomc_live_recovered_entry_fill_confirmed"
                if full_fill
                else "fomc_live_recovered_terminal_partial_entry_confirmed"
            ),
        )
    for fill in fills:
        if ledger.has_fill(
            client_order_id=entry_order.client_order_id,
            exchange_trade_id=str(fill["exchange_trade_id"]),
        ):
            continue
        ledger.record_fill(
            client_order_id=entry_order.client_order_id,
            exchange_trade_id=str(fill["exchange_trade_id"]),
            quantity=_float(fill["quantity"]),
            price=_float(fill["price"]),
            fee=_float(fill["fee"]),
            fee_asset=str(fill["fee_asset"]),
            occurred_at=str(fill["occurred_at"]),
            source_hash=evidence_hash,
        )
    return view, fills, evidence_hash


def _adverse_slippage_bps(
    *, side: str, reference_price: float, average_fill_price: float
) -> float:
    if reference_price <= 0.0 or average_fill_price <= 0.0:
        raise FomcLiveError("fomc_live_slippage_reference_invalid")
    if side == "buy":
        return (average_fill_price / reference_price - 1.0) * 10_000.0
    if side == "sell":
        return (1.0 - average_fill_price / reference_price) * 10_000.0
    raise FomcLiveError("fomc_live_slippage_side_invalid")


def _cash_event_amount(row: Mapping[str, Any]) -> float:
    info = row.get("info") if isinstance(row.get("info"), Mapping) else {}
    raw = info.get("income")
    if raw in (None, ""):
        raw = info.get("amount")
    if raw in (None, ""):
        normalized = row.get("amount")
        direction = str(row.get("direction") or "").lower()
        if normalized in (None, "") or direction not in {"in", "out"}:
            raise FomcLiveError("fomc_live_cash_signed_amount_missing")
        absolute = abs(_float(normalized, math.nan))
        raw = absolute if direction == "in" else -absolute
    amount = _float(raw, math.nan)
    if not math.isfinite(amount):
        raise FomcLiveError("fomc_live_cash_amount_invalid")
    return amount


def _record_cash_events(
    exchange: Any,
    ledger: RuntimeLedger,
    *,
    after: str,
    through: str,
    fill_fees_usdt: float,
) -> dict[str, Any]:
    operation = getattr(exchange, "fetch_ledger", None)
    if not callable(operation):
        raise FomcLiveError("fomc_live_account_ledger_unavailable")
    after_time = _utc(after)
    through_time = _utc(through)
    rows = call_with_time_sync_retry(
        exchange,
        operation,
        "USDT",
        int(after_time.timestamp() * 1_000),
        1_000,
        retry_attempts=2,
    )
    if not isinstance(rows, (list, tuple)) or any(
        not isinstance(row, Mapping) for row in rows
    ):
        raise FomcLiveError("fomc_live_account_ledger_invalid")
    source_hash = canonical_hash(
        {
            "event": "fomc_live_account_ledger",
            "after": after_time.isoformat(),
            "through": through_time.isoformat(),
            "rows": rows,
        }
    )
    funding = transfers = commissions = 0.0
    seen: set[str] = set()
    for row in rows:
        occurred_at = _trade_time(row)
        occurred = _utc(occurred_at)
        if occurred <= after_time or occurred > through_time:
            continue
        info = row.get("info") if isinstance(row.get("info"), Mapping) else {}
        asset = str(row.get("currency") or info.get("asset") or "")
        identity = str(
            row.get("id")
            or info.get("tranId")
            or info.get("incomeId")
            or info.get("id")
            or ""
        )
        if asset != "USDT" or not identity or identity in seen:
            raise FomcLiveError("fomc_live_account_ledger_identity_invalid")
        seen.add(identity)
        kind = str(info.get("incomeType") or info.get("type") or "").upper()
        amount = _cash_event_amount(row)
        if kind in {"COMMISSION", "FEE"}:
            if amount > 1e-12:
                raise FomcLiveError("fomc_live_commission_sign_invalid")
            commissions += abs(amount)
            continue
        if kind == "REALIZED_PNL":
            continue
        if kind == "FUNDING_FEE":
            event_type = "funding"
            funding += amount
        elif kind in {"TRANSFER", "INTERNAL_TRANSFER"}:
            event_type = "transfer"
            transfers += amount
        elif abs(amount) <= 1e-12:
            continue
        else:
            raise FomcLiveError(
                f"fomc_live_account_ledger_event_unclassified:{kind or 'missing'}"
            )
        ledger.record_cash_event(
            event_key=f"binance-ledger:{identity}",
            event_type=event_type,
            amount=amount,
            asset=asset,
            occurred_at=occurred_at,
            source_hash=source_hash,
            symbol=(str(row.get("symbol") or info.get("symbol")) or None),
        )
    if abs(commissions - fill_fees_usdt) > 1e-8:
        raise FomcLiveError("fomc_live_commission_mismatch")
    return {
        "funding_usdt": funding,
        "transfer_usdt": transfers,
        "commission_usdt": commissions,
        "source_hash": source_hash,
        "row_count": len(rows),
    }


def _preflight_exchange_positions(
    event: FomcEventDefinition, preflight: Mapping[str, Any]
) -> dict[str, float]:
    positions = (preflight.get("account") or {}).get("positions") or []
    quantity = sum(_float(row.get("quantity")) for row in positions)
    return {event.instrument_key: quantity}


def _preflight_exchange_open_ids(preflight: Mapping[str, Any]) -> tuple[str, ...]:
    account = preflight.get("account") or {}
    values = []
    for row in (
        *(account.get("regular_open_orders") or []),
        *(account.get("conditional_open_orders") or []),
    ):
        client_id = str(row.get("client_order_id") or "")
        if client_id:
            values.append(client_id)
    return tuple(sorted(set(values)))


def _record_account_observation(
    ledger: RuntimeLedger,
    batch: VerifiedDecisionBatch,
    preflight: Mapping[str, Any],
    *,
    observed_at: str,
) -> Any:
    account = preflight.get("account") or {}
    balance = account.get("balance") or {}
    positions = account.get("positions") or []
    source_hash = str(preflight["preflight_hash"])
    return ledger.record_account_observation(
        batch_id=batch.manifest.batch_id,
        observed_at=observed_at,
        quote_asset="USDT",
        wallet_balance=_float(balance.get("wallet_balance")),
        available_balance=_float(balance.get("quote_free")),
        actual_gross_notional=sum(
            abs(_float(row.get("notional_usdt"))) for row in positions
        ),
        margin_used=_float(balance.get("quote_used")),
        source_id=canonical_hash(
            {
                "account_scope_hash": account.get("account_scope_hash"),
                "preflight_hash": source_hash,
            }
        ),
        source_hash=source_hash,
    )


def _record_pre_dispatch_state(
    ledger: RuntimeLedger,
    batch: VerifiedDecisionBatch,
    event: FomcEventDefinition,
    preflight: Mapping[str, Any],
) -> str:
    recorded_at = str(preflight["created_at"])
    ledger.record_verified_batch(batch, recorded_at=recorded_at)
    ledger.record_position_snapshot(
        symbol=event.instrument_key,
        quantity=0.0,
        average_cost=0.0,
        realized_trading_pnl=0.0,
        occurred_at=recorded_at,
        source_hash=str(preflight["preflight_hash"]),
    )
    mark_time = _time_after(recorded_at)
    balance = (preflight.get("account") or {}).get("balance") or {}
    equity = _float(balance.get("margin_balance"))
    if ledger.latest_nav_mark() is not None:
        raise FomcLiveError("fomc_live_pre_dispatch_nav_already_exists")
    nav = ledger.record_nav_mark(
        marked_at=mark_time,
        opening_equity=equity,
        equity=equity,
        trading_pnl=0.0,
        residual_tolerance=0.001,
        source_hash=str(preflight["preflight_hash"]),
    )
    _record_account_observation(
        ledger, batch, preflight, observed_at=mark_time
    )
    reconciliation = reconcile_three_way(
        batch_id=batch.manifest.batch_id,
        reconciled_at=mark_time,
        phase="pre_dispatch",
        target_positions=ledger.position_quantities(),
        ledger_positions=ledger.position_quantities(),
        exchange_positions=_preflight_exchange_positions(event, preflight),
        position_tolerances=dict(batch.plan.reconciliation_tolerance),
        ledger_open_order_ids=ledger.open_order_ids(),
        exchange_open_order_ids=_preflight_exchange_open_ids(preflight),
        equity_residual=nav.residual,
        equity_residual_tolerance=nav.residual_tolerance,
    )
    ledger.record_reconciliation(reconciliation)
    if not reconciliation.passed or not ledger.risk_increase_allowed():
        raise FomcLiveError("fomc_live_pre_dispatch_reconciliation_failed")
    return mark_time


def _current_scope_blockers(
    event: FomcEventDefinition,
    readiness: Mapping[str, Any],
    shadow_result: Mapping[str, Any],
    preflight: Mapping[str, Any],
) -> tuple[str, ...]:
    blockers: list[str] = []
    if shadow_result.get("stage") != "ARMED":
        blockers.append("current_signal_not_armed")
    if (preflight.get("diagnostics") or {}).get("verdict") != (
        "fomc_live_account_preflight_pass"
    ):
        blockers.append("current_account_preflight_not_passed")
    scope = readiness.get("scope") or {}
    if (preflight.get("account") or {}).get("account_scope_hash") != scope.get(
        "account_scope_hash"
    ):
        blockers.append("account_scope_changed")
    account = preflight.get("account") or {}
    private_rules = account.get("market_rules") or {}
    if private_rules.get("exchange_rules_hash") != scope.get("exchange_rules_hash"):
        blockers.append("private_exchange_rules_changed")
    for name in (
        "price_tick",
        "quantity_step",
        "minimum_quantity",
        "minimum_notional_usdt",
        "contract_size",
    ):
        if private_rules.get(name) != scope.get(name):
            blockers.append(f"private_exchange_rule_changed:{name}")
    if (
        private_rules.get("symbol") != event.symbol
        or private_rules.get("settle") != "USDT"
        or private_rules.get("linear") is not True
        or private_rules.get("swap") is not True
        or private_rules.get("active") is False
    ):
        blockers.append("private_market_identity_changed")
    configuration = account.get("configuration") or {}
    if configuration.get("margin_mode") != scope.get("margin_mode"):
        blockers.append("margin_mode_changed")
    if _float(configuration.get("leverage"), math.nan) != _float(
        scope.get("leverage"), math.nan
    ):
        blockers.append("leverage_changed")
    current_signal = shadow_result.get("signal") or {}
    frozen_signal = readiness.get("signal_identity") or {}
    for name in (
        "side",
        "anchor_candle_id",
        "breakout_candle_id",
        "retest_candle_ids",
        "structural_stop_price",
        "signal_available_at",
    ):
        if current_signal.get(name) != frozen_signal.get(name):
            blockers.append(f"signal_identity_changed:{name}")
    try:
        market = FomcMarketObservation.from_mapping(shadow_result["market"])
        if market.exchange_rules_hash != scope.get("exchange_rules_hash"):
            blockers.append("public_exchange_rules_changed")
        for name in (
            "price_tick",
            "quantity_step",
            "minimum_quantity",
            "minimum_notional_usdt",
        ):
            if getattr(market, name) != scope.get(name):
                blockers.append(f"public_exchange_rule_changed:{name}")
        side = str(scope["side"])
        current_entry = market.entry_price(side)
        reference = _float(scope["reference_entry_price"])
        adverse = (
            (current_entry / reference - 1.0) * 10_000.0
            if side == "long"
            else (1.0 - current_entry / reference) * 10_000.0
        )
        if adverse > _float(scope["maximum_adverse_slippage_bps"]):
            blockers.append("pre_submit_adverse_slippage_exceeded")
        age = (_utc(str(shadow_result["observed_at"])) - _utc(market.observed_at)).total_seconds()
        if age < -1.0 or age > FOMC_LIVE_MAX_QUOTE_AGE_SECONDS:
            blockers.append("current_quote_stale")
        fresh_sizing = size_linear_usdt_futures(
            side=side,
            entry_price=current_entry,
            stop_price=_float(scope["stop_price"]),
            target_price=_float(scope["target_price"]),
            stop_gap_rate=DEFAULT_FOMC_STOP_GAP_RATE,
            quantity_step=market.quantity_step,
            minimum_notional_usdt=market.minimum_notional_usdt,
            costs=DEFAULT_FOMC_COSTS,
            risk_budget_usdt=DEFAULT_SMALL_ACCOUNT_POLICY.first_live_risk_cap_usdt,
            leverage=_float(configuration.get("leverage")),
            protective_cycle_verified=False,
        )
        if not fresh_sizing.allowed or fresh_sizing.quantity + 1e-12 < _float(
            scope["quantity"]
        ):
            blockers.append("armed_quantity_exceeds_fresh_risk_capacity")
    except Exception as exc:
        blockers.append(f"current_market_scope_invalid:{type(exc).__name__}")
    if _utc(str(shadow_result["observed_at"])) >= event.entry_cutoff_time:
        blockers.append("entry_cutoff_reached")
    return tuple(dict.fromkeys(blockers))


def _entry_submission_time_evidence(
    event: FomcEventDefinition,
    arm: Mapping[str, Any],
    current_shadow: Mapping[str, Any],
    current_preflight: Mapping[str, Any],
) -> dict[str, Any]:
    """Use trusted wall time immediately before the only risk-increasing call."""

    checked_at = _utc()
    blockers: list[str] = []
    if checked_at >= _utc(str(arm["expires_at"])):
        blockers.append("manual_arm_expired_before_submit")
    if checked_at >= event.entry_cutoff_time:
        blockers.append("entry_cutoff_reached_before_submit")
    market = FomcMarketObservation.from_mapping(current_shadow["market"])
    for name, timestamp in (
        ("quote", market.observed_at),
        ("shadow", str(current_shadow["observed_at"])),
        ("preflight", str(current_preflight["created_at"])),
    ):
        age = (checked_at - _utc(timestamp)).total_seconds()
        if age < -1.0 or age > FOMC_LIVE_MAX_QUOTE_AGE_SECONDS:
            blockers.append(f"{name}_stale_before_submit")
    if blockers:
        raise FomcLiveError(
            "fomc_live_pre_submit_time_invalid:" + ",".join(blockers)
        )
    return {
        "checked_at": checked_at.isoformat(),
        "arm_expires_at": _utc(str(arm["expires_at"])).isoformat(),
        "entry_cutoff_at": event.entry_cutoff_time.isoformat(),
        "quote_observed_at": market.observed_at,
        "preflight_created_at": str(current_preflight["created_at"]),
    }


def _create_fomc_entry_order(
    exchange: Any,
    event: FomcEventDefinition,
    arm: Mapping[str, Any],
    current_shadow: Mapping[str, Any],
    current_preflight: Mapping[str, Any],
    *,
    ccxt_symbol: str,
    side: str,
    quantity: float,
    client_order_id: str,
    mutation_marker: dict[str, bool] | None = None,
) -> tuple[Mapping[str, Any], dict[str, Any]]:
    timing = _entry_submission_time_evidence(
        event, arm, current_shadow, current_preflight
    )
    if mutation_marker is not None:
        mutation_marker["attempted"] = True
    response = call_with_time_sync_retry(
        exchange,
        exchange.create_order,
        ccxt_symbol,
        "market",
        side,
        quantity,
        None,
        {
            "newClientOrderId": client_order_id,
            "reduceOnly": False,
        },
        retry_attempts=1,
    )
    if not isinstance(response, Mapping):
        raise FomcLiveError("fomc_live_entry_response_invalid")
    return response, timing


def _execution_artifact(
    event: FomcEventDefinition,
    readiness: Mapping[str, Any],
    arm: Mapping[str, Any],
    *,
    observed_at: str,
    status: str,
    entry: Mapping[str, Any] | None = None,
    protection: Mapping[str, Any] | None = None,
    reconciliation: Mapping[str, Any] | None = None,
    blockers: Sequence[str] = (),
    exchange_mutation_attempted: bool,
) -> dict[str, Any]:
    core = {
        "schema_version": FOMC_LIVE_EXECUTION_VERSION,
        "artifact_type": "fomc_live_execution",
        "event_id": event.event_id,
        "readiness_hash": readiness["readiness_hash"],
        "arm_id": arm["arm_id"],
        "batch_id": readiness["batch_id"],
        "observed_at": _utc(observed_at).isoformat(),
        "status": status,
        "scope": dict(readiness.get("scope") or {}),
        "entry": dict(entry) if entry is not None else None,
        "protection": dict(protection) if protection is not None else None,
        "reconciliation": (
            dict(reconciliation) if reconciliation is not None else None
        ),
        "blockers": list(dict.fromkeys(str(value) for value in blockers)),
        "permissions": {
            "orders_authorized": True,
            "private_api_used": True,
            "private_api_order_attempted": exchange_mutation_attempted,
            "exchange_mutation_attempted": exchange_mutation_attempted,
            "authority_source": "single_use_fomc_manual_arm",
        },
    }
    return core | {"execution_hash": canonical_hash(core)}


def _mark_inflight_unknown(
    ledger: RuntimeLedger,
    batch: VerifiedDecisionBatch,
    *,
    reason: str,
) -> None:
    for order in batch.plan.orders:
        current = ledger.get_order(order.client_order_id)
        if current["status"] not in {"SUBMITTING", "PARTIALLY_FILLED"}:
            continue
        ledger.transition_order(
            order.client_order_id,
            "UNKNOWN",
            event_at=_time_after(str(current["last_transition_at"])),
            source_hash=canonical_hash(
                {
                    "event": "fomc_live_execution_uncertain",
                    "client_order_id": order.client_order_id,
                    "reason": reason,
                }
            ),
            exchange_order_id=(
                str(current["exchange_order_id"])
                if current["exchange_order_id"] is not None
                else None
            ),
            executed_quantity=_float(current["executed_quantity"]),
            average_price=(
                _float(current["average_price"])
                if current["average_price"] is not None
                else None
            ),
            reason=reason,
        )


def _exit_client_order_id(event_id: str, purpose: str) -> str:
    digest = canonical_hash({"event_id": event_id, "purpose": purpose})
    return f"qf-{digest[:32]}"


def _management_enabled(scope: Mapping[str, Any]) -> bool:
    return _float(scope.get("management_contract_version"), math.nan) == float(
        FOMC_LIVE_MANAGEMENT_VERSION
    )


def _management_entry_time(execution: Mapping[str, Any]) -> str:
    entry = execution.get("entry") or {}
    fills = entry.get("fills") if isinstance(entry, Mapping) else None
    occurred = [
        str(row.get("occurred_at"))
        for row in fills or ()
        if isinstance(row, Mapping) and row.get("occurred_at")
    ]
    if occurred:
        return max(_utc(value).isoformat() for value in occurred)
    observed_at = execution.get("observed_at")
    if not observed_at:
        raise FomcLiveError("fomc_live_management_entry_time_missing")
    return _utc(str(observed_at)).isoformat()


def _management_entry_fee_usdt(execution: Mapping[str, Any]) -> float:
    entry = execution.get("entry") or {}
    direct = _float(entry.get("fee_usdt"), math.nan)
    if math.isfinite(direct) and direct >= 0.0:
        return direct
    total = 0.0
    for row in entry.get("fills") or ():
        if not isinstance(row, Mapping):
            continue
        if str(row.get("fee_asset") or "").upper() != "USDT":
            raise FomcLiveError("fomc_live_management_entry_fee_asset_invalid")
        fee = _float(row.get("fee"), math.nan)
        if not math.isfinite(fee) or fee < 0.0:
            raise FomcLiveError("fomc_live_management_entry_fee_invalid")
        total += fee
    return total


def _management_state_payload(
    *,
    event: FomcEventDefinition,
    parent_batch: VerifiedDecisionBatch,
    scope: Mapping[str, Any],
    execution: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    """Freeze post-entry thresholds before the first management venue mutation."""

    entry = execution.get("entry") or {}
    side = str(scope.get("side") or "")
    entry_price = _float(entry.get("average"), math.nan)
    initial_quantity = _float(entry.get("filled"), math.nan)
    if not math.isfinite(initial_quantity) or initial_quantity <= 0.0:
        initial_quantity = _float(scope.get("quantity"), math.nan)
    if side not in {"long", "short"} or not math.isfinite(entry_price) or entry_price <= 0.0:
        raise FomcLiveError("fomc_live_management_entry_invalid")
    if not math.isfinite(initial_quantity) or initial_quantity <= 0.0:
        raise FomcLiveError("fomc_live_management_quantity_invalid")
    costs = scope.get("costs")
    if not isinstance(costs, Mapping):
        raise FomcLiveError("fomc_live_management_costs_missing")
    exit_fee_rate = _float(costs.get("exit_fee_rate"), math.nan)
    exit_slippage_rate = _float(costs.get("exit_slippage_rate"), math.nan)
    adverse_funding_rate = _float(costs.get("adverse_funding_rate"), math.nan)
    entry_fee_usdt = _management_entry_fee_usdt(execution)
    adverse_funding_usdt = entry_price * initial_quantity * adverse_funding_rate
    initial_stop_price = _float(scope.get("stop_price"), math.nan)
    active_stop_id = str(scope.get("stop_client_order_id") or "")
    if (
        not active_stop_id
        or not math.isfinite(initial_stop_price)
        or initial_stop_price <= 0.0
    ):
        raise FomcLiveError("fomc_live_management_initial_stop_invalid")
    full_risk_usdt = _float(scope.get("maximum_stress_loss_usdt"), math.nan)
    if not math.isfinite(full_risk_usdt) or full_risk_usdt <= 0.0:
        full_risk_usdt = _float(scope.get("risk_per_unit_usdt"), math.nan) * initial_quantity
    worst_stop_fill = (
        initial_stop_price * (1.0 - DEFAULT_FOMC_STOP_GAP_RATE)
        if side == "long"
        else initial_stop_price * (1.0 + DEFAULT_FOMC_STOP_GAP_RATE)
    )
    structural_loss_per_unit = (
        entry_price - worst_stop_fill
        if side == "long"
        else worst_stop_fill - entry_price
    )
    actual_stress_risk = (
        structural_loss_per_unit * initial_quantity
        + entry_fee_usdt
        + worst_stop_fill
        * initial_quantity
        * (exit_fee_rate + exit_slippage_rate)
        + adverse_funding_usdt
    )
    if (
        not math.isfinite(structural_loss_per_unit)
        or structural_loss_per_unit <= 0.0
        or not math.isfinite(actual_stress_risk)
        or actual_stress_risk <= 0.0
    ):
        raise FomcLiveError("fomc_live_management_actual_stress_invalid")
    full_risk_usdt = (
        max(full_risk_usdt, actual_stress_risk)
        if math.isfinite(full_risk_usdt) and full_risk_usdt > 0.0
        else actual_stress_risk
    )
    thresholds = calculate_profit_thresholds(
        side=side,
        entry_price=entry_price,
        initial_quantity=initial_quantity,
        full_risk_usdt=full_risk_usdt,
        entry_fee_usdt=entry_fee_usdt,
        adverse_funding_usdt=adverse_funding_usdt,
        exit_fee_rate=exit_fee_rate,
        exit_slippage_rate=exit_slippage_rate,
    )
    partial = calculate_one_third_exit_quantity(
        initial_quantity=initial_quantity,
        quantity_step=_float(scope.get("quantity_step"), math.nan),
        minimum_quantity=_float(scope.get("minimum_quantity"), math.nan),
    )
    if not thresholds.allowed:
        raise FomcLiveError(
            "fomc_live_management_thresholds_invalid:" + ",".join(thresholds.reasons)
        )
    if not partial.allowed:
        raise FomcLiveError(
            "fomc_live_management_partial_invalid:" + ",".join(partial.reasons)
        )
    freeze_h0 = _float(scope.get("freeze_h0"), math.nan)
    freeze_l0 = _float(scope.get("freeze_l0"), math.nan)
    if (
        not active_stop_id
        or not math.isfinite(initial_stop_price)
        or initial_stop_price <= 0.0
        or not math.isfinite(freeze_h0)
        or not math.isfinite(freeze_l0)
        or freeze_l0 >= freeze_h0
    ):
        raise FomcLiveError("fomc_live_management_scope_invalid")
    created = _utc(created_at).isoformat()
    core = {
        "schema_version": FOMC_LIVE_MANAGEMENT_VERSION,
        "artifact_type": "fomc_live_position_management",
        "event_id": event.event_id,
        "parent_batch_id": parent_batch.manifest.batch_id,
        "entry_client_order_id": str(scope.get("entry_client_order_id") or ""),
        "side": side,
        "entry_at": _management_entry_time(execution),
        "entry_price": entry_price,
        "initial_quantity": initial_quantity,
        "remaining_quantity": initial_quantity,
        "full_risk_usdt": full_risk_usdt,
        "entry_fee_usdt": entry_fee_usdt,
        "adverse_funding_usdt": adverse_funding_usdt,
        "net_break_even_price": thresholds.net_break_even_price,
        "net_one_r_price": thresholds.net_one_r_price,
        "net_two_r_price": thresholds.net_two_r_price,
        "initial_stop_client_order_id": active_stop_id,
        "initial_stop_price": initial_stop_price,
        "active_stop_client_order_id": active_stop_id,
        "active_stop_price": initial_stop_price,
        "freeze_h0": freeze_h0,
        "freeze_l0": freeze_l0,
        "partial_quantity": partial.partial_quantity,
        "price_tick": _float(scope.get("price_tick"), math.nan),
        "partial_exit_confirmed": False,
        "one_r_confirmed": False,
        "pending_action": None,
        "actions": [],
        "previous_management_hash": None,
        "created_at": created,
        "updated_at": created,
    }
    if not math.isfinite(_float(core["price_tick"], math.nan)) or _float(
        core["price_tick"], math.nan
    ) <= 0.0:
        raise FomcLiveError("fomc_live_management_price_tick_missing")
    return core | {"management_hash": canonical_hash(core)}


def _advance_management_state(
    state: Mapping[str, Any],
    *,
    updated_at: str,
    **changes: Any,
) -> dict[str, Any]:
    core = {key: value for key, value in state.items() if key != "management_hash"}
    core.update(changes)
    core["previous_management_hash"] = state.get("management_hash")
    core["updated_at"] = _utc(updated_at).isoformat()
    return core | {"management_hash": canonical_hash(core)}


def _round_protective_stop_price(*, side: str, price: float, price_tick: float) -> float:
    if side not in {"long", "short"} or not math.isfinite(price) or price <= 0.0:
        raise FomcLiveError("fomc_live_management_stop_price_invalid")
    if not math.isfinite(price_tick) or price_tick <= 0.0:
        raise FomcLiveError("fomc_live_management_price_tick_invalid")
    units = price / price_tick
    rounded_units = (
        math.ceil(units - 1e-12) if side == "long" else math.floor(units + 1e-12)
    )
    rounded = rounded_units * price_tick
    if rounded <= 0.0 or not math.isfinite(rounded):
        raise FomcLiveError("fomc_live_management_stop_price_invalid")
    decimals = max(0, int(-math.floor(math.log10(price_tick))) + 3)
    return round(rounded, decimals)


def _management_action_key(
    state: Mapping[str, Any],
    *,
    purpose: str,
    replacement_stop_price: float,
    partial_quantity: float | None,
) -> str:
    return canonical_hash(
        {
            "management_hash": state.get("management_hash"),
            "purpose": purpose,
            "active_stop_client_order_id": state.get("active_stop_client_order_id"),
            "replacement_stop_price": replacement_stop_price,
            "partial_quantity": partial_quantity,
        }
    )


def _build_fomc_management_batch(
    parent_batch: VerifiedDecisionBatch,
    event: FomcEventDefinition,
    *,
    action_key: str,
    purpose: str,
    signed_quantity_before: float,
    signed_quantity_after: float,
    partial_quantity: float | None,
    replacement_stop_price: float,
    created_at: str,
) -> tuple[VerifiedDecisionBatch, PlannedOrder | None, PlannedOrder]:
    """Create an immutable partial/replacement-stop batch before venue mutation."""

    if (
        not is_sha256(action_key)
        or signed_quantity_before == 0.0
        or signed_quantity_after == 0.0
        or signed_quantity_before * signed_quantity_after <= 0.0
        or not math.isfinite(replacement_stop_price)
        or replacement_stop_price <= 0.0
    ):
        raise FomcLiveError("fomc_live_management_batch_inputs_invalid")
    if partial_quantity is not None and (
        not math.isfinite(partial_quantity)
        or partial_quantity <= 0.0
        or partial_quantity >= abs(signed_quantity_before)
    ):
        raise FomcLiveError("fomc_live_management_partial_quantity_invalid")
    created = _utc(created_at).isoformat()
    batch_id = canonical_hash(
        {
            "parent_batch_id": parent_batch.manifest.batch_id,
            "event_id": event.event_id,
            "action_key": action_key,
            "purpose": purpose,
            "signed_quantity_before": signed_quantity_before,
            "signed_quantity_after": signed_quantity_after,
            "partial_quantity": partial_quantity,
            "replacement_stop_price": replacement_stop_price,
            "created_at": created,
            "kind": "fomc_live_management_v1",
        }
    )
    risk = RiskDecision.create(
        batch_id=batch_id,
        portfolio_target_id=parent_batch.target.portfolio_target_id,
        decision_time=parent_batch.target.decision_time,
        approved=True,
        input_target=parent_batch.target.target_weights,
        approved_target=parent_batch.target.target_weights,
        adjustments=("FOMC_LIVE_POST_ENTRY_MANAGEMENT",),
        violations=(),
        risk_state_hash=canonical_hash(
            {
                "parent_batch_id": parent_batch.manifest.batch_id,
                "action_key": action_key,
                "purpose": purpose,
            }
        ),
        increase_risk_allowed=False,
        reduce_risk_allowed=True,
    )
    side = "sell" if signed_quantity_before > 0.0 else "buy"
    partial_order: PlannedOrder | None = None
    orders: list[PlannedOrder] = []
    if partial_quantity is not None:
        partial_order = PlannedOrder.create(
            batch_id=batch_id,
            decision_ids=parent_batch.target.decision_ids,
            symbol=event.instrument_key,
            side=side,
            quantity=partial_quantity,
            reduce_only=True,
            phase="reduce",
            sequence=1,
            order_type="MARKET",
        )
        orders.append(partial_order)
    stop_order = PlannedOrder.create(
        batch_id=batch_id,
        decision_ids=parent_batch.target.decision_ids,
        symbol=event.instrument_key,
        side=side,
        quantity=None,
        reduce_only=True,
        phase="protective",
        sequence=len(orders) + 1,
        order_type="STOP_MARKET",
        close_position=True,
        stop_price=replacement_stop_price,
    )
    orders.append(stop_order)
    plan = OrderPlan.create(
        batch_id=batch_id,
        risk_decision_id=risk.risk_decision_id,
        portfolio_target_id=parent_batch.target.portfolio_target_id,
        snapshot_id=parent_batch.snapshot.snapshot_id,
        decision_ids=parent_batch.target.decision_ids,
        created_at=created,
        current_position_hash=canonical_hash(
            {event.instrument_key: float(signed_quantity_before)}
        ),
        approved_target=risk.approved_target,
        orders=tuple(orders),
        expected_positions={event.instrument_key: float(signed_quantity_after)},
        reconciliation_tolerance=parent_batch.plan.reconciliation_tolerance,
        blockers=(),
        executable=True,
    )
    manifest = build_decision_batch_manifest(
        snapshot=parent_batch.snapshot,
        intents=parent_batch.intents,
        target=parent_batch.target,
        risk=risk,
        plan=plan,
        created_at=created,
    )
    return (
        VerifiedDecisionBatch(
            manifest=manifest,
            snapshot=parent_batch.snapshot,
            intents=parent_batch.intents,
            target=parent_batch.target,
            risk=risk,
            plan=plan,
        ),
        partial_order,
        stop_order,
    )


def _plan_management_action(
    live_store: FomcLiveStore,
    ledger: RuntimeLedger,
    parent_batch: VerifiedDecisionBatch,
    event: FomcEventDefinition,
    state: Mapping[str, Any],
    *,
    purpose: str,
    replacement_stop_price: float,
    partial_quantity: float | None,
    started_at: str,
) -> tuple[dict[str, Any], VerifiedDecisionBatch, PlannedOrder | None, PlannedOrder]:
    pending = state.get("pending_action")
    if isinstance(pending, Mapping):
        return _pending_management_action_batch(parent_batch, event, state)
    side = str(state.get("side") or "")
    remaining = _float(state.get("remaining_quantity"), math.nan)
    if side not in {"long", "short"} or not math.isfinite(remaining) or remaining <= 0.0:
        raise FomcLiveError("fomc_live_management_position_invalid")
    signed_before = remaining if side == "long" else -remaining
    signed_after = (
        signed_before
        if partial_quantity is None
        else signed_before - partial_quantity if side == "long" else signed_before + partial_quantity
    )
    action_key = _management_action_key(
        state,
        purpose=purpose,
        replacement_stop_price=replacement_stop_price,
        partial_quantity=partial_quantity,
    )
    created_at = _utc(started_at).isoformat()
    batch, partial_order, stop_order = _build_fomc_management_batch(
        parent_batch,
        event,
        action_key=action_key,
        purpose=purpose,
        signed_quantity_before=signed_before,
        signed_quantity_after=signed_after,
        partial_quantity=partial_quantity,
        replacement_stop_price=replacement_stop_price,
        created_at=created_at,
    )
    action = {
        "action_key": action_key,
        "purpose": purpose,
        "phase": "planned",
        "created_at": created_at,
        "management_batch_id": batch.manifest.batch_id,
        "signed_quantity_before": signed_before,
        "signed_quantity_after": signed_after,
        "partial_quantity": partial_quantity,
        "partial_client_order_id": (
            partial_order.client_order_id if partial_order is not None else None
        ),
        "replacement_stop_price": replacement_stop_price,
        "replacement_stop_client_order_id": stop_order.client_order_id,
        "replaced_stop_client_order_id": state.get("active_stop_client_order_id"),
        "replaced_stop_price": state.get("active_stop_price"),
    }
    next_state = _advance_management_state(
        state,
        updated_at=created_at,
        pending_action=action,
    )
    live_store.write_management_state(next_state)
    ledger.record_verified_batch(batch, recorded_at=created_at)
    return next_state, batch, partial_order, stop_order


def _pending_management_action_batch(
    parent_batch: VerifiedDecisionBatch,
    event: FomcEventDefinition,
    state: Mapping[str, Any],
) -> tuple[dict[str, Any], VerifiedDecisionBatch, PlannedOrder | None, PlannedOrder]:
    action = state.get("pending_action")
    if not isinstance(action, Mapping):
        raise FomcLiveError("fomc_live_management_pending_action_missing")
    batch, partial_order, stop_order = _build_fomc_management_batch(
        parent_batch,
        event,
        action_key=str(action.get("action_key") or ""),
        purpose=str(action.get("purpose") or ""),
        signed_quantity_before=_float(action.get("signed_quantity_before"), math.nan),
        signed_quantity_after=_float(action.get("signed_quantity_after"), math.nan),
        partial_quantity=(
            _float(action.get("partial_quantity"), math.nan)
            if action.get("partial_quantity") is not None
            else None
        ),
        replacement_stop_price=_float(action.get("replacement_stop_price"), math.nan),
        created_at=str(action.get("created_at") or ""),
    )
    if (
        action.get("management_batch_id") != batch.manifest.batch_id
        or action.get("partial_client_order_id")
        != (partial_order.client_order_id if partial_order is not None else None)
        or action.get("replacement_stop_client_order_id") != stop_order.client_order_id
    ):
        raise FomcLiveError("fomc_live_management_pending_action_identity_invalid")
    return dict(action), batch, partial_order, stop_order


def _record_management_market_fill(
    ledger: RuntimeLedger,
    order: PlannedOrder,
    *,
    view: Mapping[str, Any],
    fills: Sequence[Mapping[str, Any]],
    evidence_hash: str,
    reason: str,
) -> None:
    current = ledger.get_order(order.client_order_id)
    filled_at = _time_after(
        str(current["last_transition_at"]),
        *(str(row["occurred_at"]) for row in fills),
    )
    if current["status"] != "FILLED":
        ledger.transition_order(
            order.client_order_id,
            "FILLED",
            event_at=filled_at,
            source_hash=evidence_hash,
            exchange_order_id=str(view["id"]),
            executed_quantity=_float(view["filled"]),
            average_price=_float(view["average"]),
            reason=reason,
        )
    for fill in fills:
        if ledger.has_fill(
            client_order_id=order.client_order_id,
            exchange_trade_id=str(fill["exchange_trade_id"]),
        ):
            continue
        ledger.record_fill(
            client_order_id=order.client_order_id,
            exchange_trade_id=str(fill["exchange_trade_id"]),
            quantity=_float(fill["quantity"]),
            price=_float(fill["price"]),
            fee=_float(fill["fee"]),
            fee_asset=str(fill["fee_asset"]),
            occurred_at=str(fill["occurred_at"]),
            source_hash=evidence_hash,
        )


def _management_partial_reconciliation(
    ledger: RuntimeLedger,
    event: FomcEventDefinition,
    *,
    preflight: Mapping[str, Any],
    signed_remaining_quantity: float,
    active_stop_client_order_id: str,
    active_stop_price: float,
    price_tick: float,
    account_observation_hash: str,
) -> dict[str, Any]:
    """Persist the target/ledger/exchange evidence before replacing protection."""

    account = preflight.get("account") or {}
    exchange_quantity = _preflight_exchange_positions(event, preflight).get(
        event.instrument_key, 0.0
    )
    ledger_quantity = ledger.position_quantities().get(event.instrument_key, 0.0)
    matching_stops = [
        row
        for row in account.get("conditional_open_orders", [])
        if row.get("client_order_id") == active_stop_client_order_id
    ]
    stop_exact = len(matching_stops) == 1 and _protective_stop_shape_matches(
        matching_stops[0],
        signed_quantity=signed_remaining_quantity,
        stop_price=active_stop_price,
        price_tick=price_tick,
    )
    tolerance = 1e-12
    core = {
        "artifact_type": "fomc_live_management_partial_reconciliation",
        "event_id": event.event_id,
        "preflight_hash": preflight["preflight_hash"],
        "account_observation_hash": account_observation_hash,
        "target_remaining_quantity": signed_remaining_quantity,
        "ledger_remaining_quantity": ledger_quantity,
        "exchange_remaining_quantity": exchange_quantity,
        "position_tolerance": tolerance,
        "target_ledger_difference": ledger_quantity - signed_remaining_quantity,
        "ledger_exchange_difference": exchange_quantity - ledger_quantity,
        "active_stop_client_order_id": active_stop_client_order_id,
        "active_stop_exact": stop_exact,
    }
    passed = (
        abs(_float(core["target_ledger_difference"])) <= tolerance
        and abs(_float(core["ledger_exchange_difference"])) <= tolerance
        and stop_exact
    )
    return core | {
        "passed": passed,
        "reconciliation_hash": canonical_hash(core | {"passed": passed}),
    }


def _confirm_management_partial_fill(
    settings: Settings,
    event: FomcEventDefinition,
    ledger: RuntimeLedger,
    *,
    management_batch: VerifiedDecisionBatch,
    exchange: Any,
    ccxt_symbol: str,
    partial_order: PlannedOrder,
    active_stop_client_order_id: str,
    active_stop_price: float,
    signed_remaining_quantity: float,
    price_tick: float,
    started_at: str,
) -> tuple[dict[str, Any], Mapping[str, Any]]:
    """Fill the planned partial first; the active native stop remains live here."""

    current = ledger.get_order(partial_order.client_order_id)
    if current["status"] == "PLANNED":
        ledger.transition_order(
            partial_order.client_order_id,
            "SUBMITTING",
            event_at=_time_after(str(current["last_transition_at"]), started_at),
            source_hash=canonical_hash(
                {
                    "event": "fomc_live_management_partial_submission_started",
                    "client_order_id": partial_order.client_order_id,
                }
            ),
        )
        response = call_with_time_sync_retry(
            exchange,
            exchange.create_order,
            ccxt_symbol,
            "market",
            partial_order.side,
            _float(partial_order.quantity),
            None,
            {"newClientOrderId": partial_order.client_order_id, "reduceOnly": True},
            retry_attempts=1,
        )
        if not isinstance(response, Mapping):
            raise FomcLiveError("fomc_live_management_partial_response_invalid")
    elif current["status"] in {"SUBMITTING", "ACKNOWLEDGED", "UNKNOWN"}:
        response = _fetch_order_by_client_id(
            exchange,
            event,
            ccxt_symbol=ccxt_symbol,
            client_order_id=partial_order.client_order_id,
            conditional=False,
        )
    elif current["status"] == "FILLED":
        response = _fetch_order_by_client_id(
            exchange,
            event,
            ccxt_symbol=ccxt_symbol,
            client_order_id=partial_order.client_order_id,
            conditional=False,
        )
    else:
        raise FomcLiveError("fomc_live_management_partial_terminal_unfilled")
    view, fills, evidence_hash = _fetch_market_fill_evidence(
        exchange,
        response,
        ccxt_symbol=ccxt_symbol,
        client_order_id=partial_order.client_order_id,
        planned_quantity=_float(partial_order.quantity),
        confirmed_response=response,
    )
    if view["side"] != partial_order.side:
        raise FomcLiveError("fomc_live_management_partial_side_invalid")
    _record_management_market_fill(
        ledger,
        partial_order,
        view=view,
        fills=fills,
        evidence_hash=evidence_hash,
        reason="fomc_live_management_partial_fill_confirmed",
    )
    post = build_fomc_live_account_preflight(
        settings,
        event,
        observed_at=_time_after(*(str(row["occurred_at"]) for row in fills)),
        exchange=exchange,
        halt_present=False,
        expected_position_quantity=signed_remaining_quantity,
        expected_stop_client_id=active_stop_client_order_id,
        expected_stop_price=active_stop_price,
        price_tick=price_tick,
    )
    if (post.get("diagnostics") or {}).get("verdict") != (
        "fomc_live_account_preflight_pass"
    ):
        raise FomcLiveError("fomc_live_management_partial_readback_failed")
    observed_at = _time_after(
        str(post["created_at"]),
        *(str(row["occurred_at"]) for row in fills),
    )
    observation = _record_account_observation(
        ledger,
        management_batch,
        post,
        observed_at=observed_at,
    )
    reconciliation = _management_partial_reconciliation(
        ledger,
        event,
        preflight=post,
        signed_remaining_quantity=signed_remaining_quantity,
        active_stop_client_order_id=active_stop_client_order_id,
        active_stop_price=active_stop_price,
        price_tick=price_tick,
        account_observation_hash=str(observation.observation_hash),
    )
    if not reconciliation["passed"]:
        raise FomcLiveError("fomc_live_management_partial_reconciliation_failed")
    return (
        view
        | {
            "fills": list(fills),
            "evidence_hash": evidence_hash,
            "post_preflight_hash": post["preflight_hash"],
            "partial_reconciliation": reconciliation,
        },
        post,
    )


def _submit_management_replacement_stop(
    settings: Settings,
    event: FomcEventDefinition,
    ledger: RuntimeLedger,
    parent_batch: VerifiedDecisionBatch,
    *,
    exchange: Any,
    ccxt_symbol: str,
    stop_order: PlannedOrder,
    signed_remaining_quantity: float,
    price_tick: float,
    started_at: str,
) -> tuple[dict[str, Any], Mapping[str, Any]]:
    current = ledger.get_order(stop_order.client_order_id)
    if current["status"] == "PLANNED":
        ledger.transition_order(
            stop_order.client_order_id,
            "SUBMITTING",
            event_at=_time_after(str(current["last_transition_at"]), started_at),
            source_hash=canonical_hash(
                {
                    "event": "fomc_live_management_stop_submission_started",
                    "client_order_id": stop_order.client_order_id,
                }
            ),
        )
        response = call_with_time_sync_retry(
            exchange,
            exchange.create_order,
            ccxt_symbol,
            "STOP_MARKET",
            stop_order.side,
            None,
            None,
            {
                "stopPrice": stop_order.stop_price,
                "closePosition": True,
                "newClientOrderId": stop_order.client_order_id,
                "workingType": "MARK_PRICE",
            },
            retry_attempts=1,
        )
        if not isinstance(response, Mapping):
            raise FomcLiveError("fomc_live_management_stop_response_invalid")
    elif current["status"] in {"SUBMITTING", "UNKNOWN", "ACKNOWLEDGED"}:
        response = _fetch_order_by_client_id(
            exchange,
            event,
            ccxt_symbol=ccxt_symbol,
            client_order_id=stop_order.client_order_id,
            conditional=True,
        )
    else:
        raise FomcLiveError("fomc_live_management_stop_terminal_invalid")
    view = _exchange_response_view(response)
    if (
        view["client_order_id"] not in {"", stop_order.client_order_id}
        or view["id"] == ""
    ):
        raise FomcLiveError("fomc_live_management_stop_identity_invalid")
    post = build_fomc_live_account_preflight(
        settings,
        event,
        observed_at=_time_after(started_at),
        exchange=exchange,
        halt_present=False,
        expected_position_quantity=signed_remaining_quantity,
        expected_stop_client_id=stop_order.client_order_id,
        expected_stop_price=_float(stop_order.stop_price),
        price_tick=price_tick,
    )
    if (post.get("diagnostics") or {}).get("verdict") != (
        "fomc_live_account_preflight_pass"
    ):
        raise FomcLiveError("fomc_live_management_stop_readback_failed")
    readback = next(
        row
        for row in (post.get("account") or {}).get("conditional_open_orders", [])
        if row.get("client_order_id") == stop_order.client_order_id
    )
    evidence_hash = canonical_hash(
        {
            "event": "fomc_live_management_stop_acknowledged_and_read_back",
            "response": view,
            "readback": readback,
            "post_preflight_hash": post["preflight_hash"],
        }
    )
    current = ledger.get_order(stop_order.client_order_id)
    if current["status"] != "ACKNOWLEDGED":
        ledger.transition_order(
            stop_order.client_order_id,
            "ACKNOWLEDGED",
            event_at=_time_after(str(current["last_transition_at"]), started_at),
            source_hash=evidence_hash,
            exchange_order_id=str(view["id"]),
            reason="fomc_live_management_replacement_stop_confirmed",
        )
    return (
        view
        | {
            "client_order_id": stop_order.client_order_id,
            "readback": readback,
            "evidence_hash": evidence_hash,
        },
        post,
    )


def _cancel_uncertain_management_replacement_stop(
    ledger: RuntimeLedger,
    parent_batch: VerifiedDecisionBatch,
    event: FomcEventDefinition,
    *,
    exchange: Any,
    ccxt_symbol: str,
    replacement_stop_client_order_id: str,
    signed_remaining_quantity: float,
    replacement_stop_price: float,
    price_tick: float,
    at: str,
) -> dict[str, Any]:
    """Resolve and remove a replacement stop whose submit outcome is uncertain."""

    response = _fetch_order_by_client_id(
        exchange,
        event,
        ccxt_symbol=ccxt_symbol,
        client_order_id=replacement_stop_client_order_id,
        conditional=True,
    )
    view = _exchange_response_view(response)
    if (
        view["client_order_id"] != replacement_stop_client_order_id
        or not view["id"]
        or not _protective_stop_shape_matches(
            view,
            signed_quantity=signed_remaining_quantity,
            stop_price=replacement_stop_price,
            price_tick=price_tick,
        )
    ):
        raise FomcLiveError("fomc_live_management_replacement_stop_identity_invalid")
    if view["status"] == "open":
        terminal = _cancel_protective_stop(
            exchange,
            event,
            ccxt_symbol=ccxt_symbol,
            stop=view,
        )
    elif view["status"] in {"canceled", "expired", "rejected"}:
        terminal = _owned_stop_terminal_evidence(
            exchange,
            event,
            ccxt_symbol=ccxt_symbol,
            client_order_id=replacement_stop_client_order_id,
            exchange_order_id=str(view["id"]),
        )
    else:
        raise FomcLiveError("fomc_live_management_replacement_stop_terminal_ambiguous")
    _transition_owned_stop_terminal(
        ledger,
        parent_batch,
        stop_client_order_id=replacement_stop_client_order_id,
        at=at,
        source_hash=canonical_hash(
            {
                "event": "fomc_live_management_uncertain_replacement_stop_canceled",
                "replacement_stop_client_order_id": replacement_stop_client_order_id,
                "terminal": terminal,
            }
        ),
        terminal_evidence=terminal,
    )
    return {
        "replacement_stop": view,
        "terminal": terminal,
    }


def _continue_management_action(
    settings: Settings,
    event: FomcEventDefinition,
    live_store: FomcLiveStore,
    ledger: RuntimeLedger,
    parent_batch: VerifiedDecisionBatch,
    state: Mapping[str, Any],
    *,
    exchange: Any,
    ccxt_symbol: str,
    active_stop: Mapping[str, Any] | None,
    started_at: str,
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Resume the sole pending management action without resubmitting UNKNOWNs."""

    action, batch, partial_order, stop_order = _pending_management_action_batch(
        parent_batch, event, state
    )
    ledger.record_verified_batch(batch, recorded_at=str(action["created_at"]))
    phase = str(action.get("phase") or "")
    signed_after = _float(action.get("signed_quantity_after"), math.nan)
    price_tick = _float((state.get("price_tick") or 0.0), math.nan)
    if not math.isfinite(price_tick) or price_tick <= 0.0:
        price_tick = _float((state.get("market_rules") or {}).get("price_tick"), math.nan)
    if not math.isfinite(price_tick) or price_tick <= 0.0:
        raise FomcLiveError("fomc_live_management_price_tick_missing")
    if not math.isfinite(signed_after) or signed_after == 0.0:
        raise FomcLiveError("fomc_live_management_remaining_quantity_invalid")
    evidence: dict[str, Any] = {}

    if partial_order is not None and phase == "planned":
        partial_fill, _ = _confirm_management_partial_fill(
            settings,
            event,
            ledger,
            management_batch=batch,
            exchange=exchange,
            ccxt_symbol=ccxt_symbol,
            partial_order=partial_order,
            active_stop_client_order_id=str(action["replaced_stop_client_order_id"]),
            active_stop_price=_float(action["replaced_stop_price"]),
            signed_remaining_quantity=signed_after,
            price_tick=price_tick,
            started_at=started_at,
        )
        evidence["partial_fill"] = partial_fill
        action = dict(action) | {
            "phase": "partial_confirmed",
            "partial_fill": partial_fill,
        }
        state = _advance_management_state(
            state,
            updated_at=started_at,
            remaining_quantity=abs(signed_after),
            partial_exit_confirmed=True,
            pending_action=action,
        )
        live_store.write_management_state(state)
        phase = "partial_confirmed"
    elif partial_order is None and phase == "planned":
        phase = "ready_to_cancel"

    if phase in {"partial_confirmed", "ready_to_cancel", "cancelling_active_stop"}:
        if phase != "cancelling_active_stop":
            action = dict(action) | {"phase": "cancelling_active_stop"}
            state = _advance_management_state(
                state,
                updated_at=started_at,
                pending_action=action,
            )
            live_store.write_management_state(state)
        replaced_stop_id = str(action.get("replaced_stop_client_order_id") or "")
        if not replaced_stop_id:
            raise FomcLiveError("fomc_live_management_replaced_stop_missing")
        if active_stop is not None:
            if active_stop.get("client_order_id") != replaced_stop_id:
                raise FomcLiveError("fomc_live_management_replaced_stop_identity_invalid")
            terminal = _cancel_protective_stop(
                exchange,
                event,
                ccxt_symbol=ccxt_symbol,
                stop=active_stop,
            )
        else:
            current = ledger.get_order(replaced_stop_id)
            terminal = _owned_stop_terminal_evidence(
                exchange,
                event,
                ccxt_symbol=ccxt_symbol,
                client_order_id=replaced_stop_id,
                exchange_order_id=(
                    str(current["exchange_order_id"])
                    if current["exchange_order_id"] is not None
                    else None
                ),
            )
        _transition_owned_stop_terminal(
            ledger,
            parent_batch,
            stop_client_order_id=replaced_stop_id,
            at=started_at,
            source_hash=canonical_hash(
                {
                    "event": "fomc_live_management_active_stop_canceled",
                    "action_key": action["action_key"],
                    "terminal": terminal,
                }
            ),
            terminal_evidence=terminal,
        )
        evidence["canceled_stop"] = terminal
        action = dict(action) | {
            "phase": "active_stop_canceled",
            "canceled_stop": terminal,
        }
        state = _advance_management_state(
            state,
            updated_at=started_at,
            pending_action=action,
        )
        live_store.write_management_state(state)
        phase = "active_stop_canceled"

    if phase in {"active_stop_canceled", "submitting_replacement_stop"}:
        if phase != "submitting_replacement_stop":
            action = dict(action) | {"phase": "submitting_replacement_stop"}
            state = _advance_management_state(
                state,
                updated_at=started_at,
                pending_action=action,
            )
            live_store.write_management_state(state)
        replacement_stop, _ = _submit_management_replacement_stop(
            settings,
            event,
            ledger,
            parent_batch,
            exchange=exchange,
            ccxt_symbol=ccxt_symbol,
            stop_order=stop_order,
            signed_remaining_quantity=signed_after,
            price_tick=price_tick,
            started_at=started_at,
        )
        evidence["replacement_stop"] = replacement_stop
        completed_action = dict(action) | {
            "phase": "completed",
            "replacement_stop": replacement_stop,
            "completed_at": _time_after(started_at),
        }
        actions = list(state.get("actions") or ())
        actions.append(completed_action)
        next_state = _advance_management_state(
            state,
            updated_at=str(completed_action["completed_at"]),
            remaining_quantity=abs(signed_after),
            active_stop_client_order_id=stop_order.client_order_id,
            active_stop_price=_float(stop_order.stop_price),
            partial_exit_confirmed=(
                bool(state.get("partial_exit_confirmed")) or partial_order is not None
            ),
            pending_action=None,
            actions=actions,
        )
        live_store.write_management_state(next_state)
        return next_state, evidence, True
    raise FomcLiveError("fomc_live_management_action_phase_invalid")


def _management_completed_after(
    candles: Sequence[Any], *, entry_at: str, interval_minutes: int
) -> tuple[Any, ...]:
    entry_time = _utc(entry_at)
    completed = tuple(
        candle
        for candle in candles
        if getattr(candle, "interval_minutes", None) == interval_minutes
        and getattr(candle, "closed_at", entry_time) > entry_time
    )
    if any(
        later.closed_at <= earlier.closed_at
        for earlier, later in zip(completed, completed[1:])
    ):
        raise FomcLiveError("fomc_live_management_candles_not_ordered")
    return completed


def _management_atr14(hourly: Sequence[Any]) -> float | None:
    if len(hourly) < 15:
        return None
    bars = hourly[-15:]
    if any(
        later.closed_at - earlier.closed_at != dt.timedelta(hours=1)
        for earlier, later in zip(bars, bars[1:])
    ):
        raise FomcLiveError("fomc_live_management_hourly_gap")
    true_ranges = [
        max(
            float(current.high) - float(current.low),
            abs(float(current.high) - float(previous.close)),
            abs(float(current.low) - float(previous.close)),
        )
        for previous, current in zip(bars, bars[1:])
    ]
    atr = sum(true_ranges) / len(true_ranges)
    if not math.isfinite(atr) or atr <= 0.0:
        raise FomcLiveError("fomc_live_management_atr_invalid")
    return atr


def _evaluate_fomc_management_policy(
    state: Mapping[str, Any],
    *,
    hourly: Sequence[Any],
    fifteen_minute: Sequence[Any],
    mark_price: float,
    funding_rate: float,
) -> dict[str, Any]:
    """Return a no-mutation management decision from completed public candles."""

    side = str(state.get("side") or "")
    entry_at = str(state.get("entry_at") or "")
    if side not in {"long", "short"} or not entry_at:
        raise FomcLiveError("fomc_live_management_state_invalid")
    if not math.isfinite(mark_price) or mark_price <= 0.0:
        raise FomcLiveError("fomc_live_management_mark_price_invalid")
    completed_hourly = tuple(
        candle
        for candle in hourly
        if getattr(candle, "interval_minutes", None) == 60
    )
    hourly_after = _management_completed_after(
        hourly, entry_at=entry_at, interval_minutes=60
    )
    fifteen_after = _management_completed_after(
        fifteen_minute, entry_at=entry_at, interval_minutes=15
    )
    net_one_r = _float(state.get("net_one_r_price"), math.nan)
    net_two_r = _float(state.get("net_two_r_price"), math.nan)
    net_break_even = _float(state.get("net_break_even_price"), math.nan)
    active_stop = _float(state.get("active_stop_price"), math.nan)
    if any(
        not math.isfinite(value) or value <= 0.0
        for value in (net_one_r, net_two_r, net_break_even, active_stop)
    ):
        raise FomcLiveError("fomc_live_management_threshold_state_invalid")
    reached_one_r = bool(state.get("one_r_confirmed")) or any(
        (float(candle.close) >= net_one_r if side == "long" else float(candle.close) <= net_one_r)
        for candle in fifteen_after
    )
    reached_two_r = any(
        (float(candle.close) >= net_two_r if side == "long" else float(candle.close) <= net_two_r)
        for candle in fifteen_after
    )
    latest_hour = hourly_after[-1] if hourly_after else None
    if latest_hour is not None:
        returned_to_range = (
            float(latest_hour.close) <= _float(state.get("freeze_h0"), math.nan)
            if side == "long"
            else float(latest_hour.close) >= _float(state.get("freeze_l0"), math.nan)
        )
        if returned_to_range:
            return {
                "kind": "flatten",
                "purpose": "returned-to-frozen-range",
                "reached_one_r": reached_one_r,
                "hourly_count": len(hourly_after),
            }
    full_risk = _float(state.get("full_risk_usdt"), math.nan)
    notional = _float(state.get("entry_price"), math.nan) * _float(
        state.get("remaining_quantity"), math.nan
    )
    adverse_funding = (
        side == "long" and funding_rate > 0.0
    ) or (side == "short" and funding_rate < 0.0)
    if (
        not reached_one_r
        and adverse_funding
        and math.isfinite(full_risk)
        and math.isfinite(notional)
        and abs(funding_rate) * notional > 0.1 * full_risk
    ):
        return {
            "kind": "flatten",
            "purpose": "adverse-funding-before-one-r",
            "reached_one_r": reached_one_r,
            "hourly_count": len(hourly_after),
        }
    if len(hourly_after) >= 8 and not reached_one_r:
        return {
            "kind": "flatten",
            "purpose": "eight-hour-no-one-r",
            "reached_one_r": reached_one_r,
            "hourly_count": len(hourly_after),
        }

    price_tick = _float(state.get("price_tick"), math.nan)
    if not bool(state.get("partial_exit_confirmed")) and reached_two_r:
        next_stop = _round_protective_stop_price(
            side=side, price=net_one_r, price_tick=price_tick
        )
        return {
            "kind": "action",
            "purpose": "two-r-partial-and-profit-floor",
            "replacement_stop_price": next_stop,
            "partial_quantity": _float(state.get("partial_quantity"), math.nan),
            "reached_one_r": reached_one_r,
            "hourly_count": len(hourly_after),
        }
    if not bool(state.get("partial_exit_confirmed")) and reached_one_r:
        next_stop = _round_protective_stop_price(
            side=side, price=net_break_even, price_tick=price_tick
        )
        tighter = next_stop > active_stop if side == "long" else next_stop < active_stop
        return {
            "kind": "action" if tighter else "noop",
            "purpose": "one-r-net-break-even-stop",
            "replacement_stop_price": next_stop if tighter else None,
            "partial_quantity": None,
            "reached_one_r": reached_one_r,
            "hourly_count": len(hourly_after),
        }
    if bool(state.get("partial_exit_confirmed")) and hourly_after:
        atr14 = _management_atr14(completed_hourly)
        if atr14 is not None:
            favorable_close = (
                max(float(candle.close) for candle in hourly_after)
                if side == "long"
                else min(float(candle.close) for candle in hourly_after)
            )
            tail = calculate_post_2r_tail_stop(
                side=side,
                previous_stop_price=active_stop,
                net_one_r_floor_price=net_one_r,
                favorable_completed_1h_close_price=favorable_close,
                atr14_1h=atr14,
                partial_exit_confirmed=True,
            )
            if tail.allowed and tail.next_stop_price is not None:
                next_stop = _round_protective_stop_price(
                    side=side,
                    price=tail.next_stop_price,
                    price_tick=price_tick,
                )
                tighter = (
                    next_stop > active_stop if side == "long" else next_stop < active_stop
                )
                if tighter:
                    return {
                        "kind": "action",
                        "purpose": "post-two-r-atr-trailing-stop",
                        "replacement_stop_price": next_stop,
                        "partial_quantity": None,
                        "reached_one_r": reached_one_r,
                        "hourly_count": len(hourly_after),
                        "atr14_1h": atr14,
                        "favorable_completed_1h_close_price": favorable_close,
                    }
    return {
        "kind": "noop",
        "reached_one_r": reached_one_r,
        "hourly_count": len(hourly_after),
    }


def _build_fomc_reduction_batch(
    parent_batch: VerifiedDecisionBatch,
    event: FomcEventDefinition,
    *,
    purpose: str,
    signed_quantity: float,
    created_at: str,
    include_order: bool,
) -> tuple[VerifiedDecisionBatch, PlannedOrder | None]:
    """Create a signed, reduce-only ledger batch for a verified live exit."""

    quantity = abs(_float(signed_quantity))
    if include_order and quantity <= 0.0:
        raise FomcLiveError("fomc_live_reduction_quantity_invalid")
    batch_id = canonical_hash(
        {
            "parent_batch_id": parent_batch.manifest.batch_id,
            "event_id": event.event_id,
            "purpose": purpose,
            "signed_quantity": signed_quantity,
            "created_at": _utc(created_at).isoformat(),
            "kind": "fomc_live_reduce_only_v1",
        }
    )
    risk = RiskDecision.create(
        batch_id=batch_id,
        portfolio_target_id=parent_batch.target.portfolio_target_id,
        decision_time=parent_batch.target.decision_time,
        approved=True,
        input_target=parent_batch.target.target_weights,
        approved_target=parent_batch.target.target_weights,
        adjustments=("FOMC_LIVE_VERIFIED_RISK_REDUCTION",),
        violations=(),
        risk_state_hash=canonical_hash(
            {
                "parent_batch_id": parent_batch.manifest.batch_id,
                "purpose": purpose,
                "signed_quantity": signed_quantity,
            }
        ),
        increase_risk_allowed=False,
        reduce_risk_allowed=True,
    )
    order: PlannedOrder | None = None
    blockers: tuple[str, ...] = ()
    if include_order:
        order = PlannedOrder.create(
            batch_id=batch_id,
            decision_ids=parent_batch.target.decision_ids,
            symbol=event.instrument_key,
            side="sell" if signed_quantity > 0.0 else "buy",
            quantity=quantity,
            reduce_only=True,
            phase="reduce",
            sequence=1,
            order_type="MARKET",
        )
        orders = (order,)
        executable = True
    else:
        orders = ()
        blockers = ("FOMC_LIVE_EXIT_RECONCILIATION_ONLY",)
        executable = False
    plan = OrderPlan.create(
        batch_id=batch_id,
        risk_decision_id=risk.risk_decision_id,
        portfolio_target_id=parent_batch.target.portfolio_target_id,
        snapshot_id=parent_batch.snapshot.snapshot_id,
        decision_ids=parent_batch.target.decision_ids,
        created_at=_utc(created_at).isoformat(),
        current_position_hash=canonical_hash(
            {event.instrument_key: float(signed_quantity)}
        ),
        approved_target=risk.approved_target,
        orders=orders,
        expected_positions={event.instrument_key: 0.0},
        reconciliation_tolerance=parent_batch.plan.reconciliation_tolerance,
        blockers=blockers,
        executable=executable,
    )
    manifest = build_decision_batch_manifest(
        snapshot=parent_batch.snapshot,
        intents=parent_batch.intents,
        target=parent_batch.target,
        risk=risk,
        plan=plan,
        created_at=_utc(created_at).isoformat(),
    )
    return (
        VerifiedDecisionBatch(
            manifest=manifest,
            snapshot=parent_batch.snapshot,
            intents=parent_batch.intents,
            target=parent_batch.target,
            risk=risk,
            plan=plan,
        ),
        order,
    )


def _reduction_attempt_key(
    parent_batch: VerifiedDecisionBatch,
    event: FomcEventDefinition,
    *,
    purpose: str,
    signed_quantity: float,
) -> str:
    return canonical_hash(
        {
            "parent_batch_id": parent_batch.manifest.batch_id,
            "event_id": event.event_id,
            "purpose": purpose,
            "signed_quantity": float(signed_quantity),
            "kind": "fomc_live_reduction_attempt_v1",
        }
    )


def _existing_reduction_attempt(
    live_store: FomcLiveStore,
    parent_batch: VerifiedDecisionBatch,
    event: FomcEventDefinition,
) -> dict[str, Any] | None:
    matches = [
        row
        for row in live_store.list_reduction_attempts()
        if row.get("parent_batch_id") == parent_batch.manifest.batch_id
        and row.get("event_id") == event.event_id
    ]
    if len(matches) > 1:
        raise FomcLiveError("fomc_live_reduction_attempt_ambiguous")
    return matches[0] if matches else None


def _load_or_create_reduction_attempt(
    live_store: FomcLiveStore,
    parent_batch: VerifiedDecisionBatch,
    event: FomcEventDefinition,
    *,
    purpose: str,
    signed_quantity: float,
    started_at: str,
) -> tuple[dict[str, Any], VerifiedDecisionBatch, PlannedOrder]:
    """Persist the only reduce-only submission identity before any venue call."""

    existing = _existing_reduction_attempt(live_store, parent_batch, event)
    if existing is not None:
        if abs(_float(existing.get("signed_quantity")) - signed_quantity) > 1e-12:
            raise FomcLiveError("fomc_live_reduction_attempt_quantity_changed")
        attempt = existing
    else:
        reduction_key = _reduction_attempt_key(
            parent_batch,
            event,
            purpose=purpose,
            signed_quantity=signed_quantity,
        )
        created_at = _utc(started_at).isoformat()
        reduction_batch, reduction_order = _build_fomc_reduction_batch(
            parent_batch,
            event,
            purpose=purpose,
            signed_quantity=signed_quantity,
            created_at=created_at,
            include_order=True,
        )
        assert reduction_order is not None
        core = {
            "schema_version": FOMC_LIVE_REDUCTION_ATTEMPT_VERSION,
            "artifact_type": "fomc_live_reduction_attempt",
            "reduction_key": reduction_key,
            "event_id": event.event_id,
            "parent_batch_id": parent_batch.manifest.batch_id,
            "purpose": purpose,
            "signed_quantity": float(signed_quantity),
            "created_at": created_at,
            "reduction_batch_id": reduction_batch.manifest.batch_id,
            "client_order_id": reduction_order.client_order_id,
        }
        attempt = core | {"attempt_hash": canonical_hash(core)}
        live_store.write_reduction_attempt(attempt)

    reduction_batch, reduction_order = _build_fomc_reduction_batch(
        parent_batch,
        event,
        purpose=str(attempt["purpose"]),
        signed_quantity=_float(attempt["signed_quantity"]),
        created_at=str(attempt["created_at"]),
        include_order=True,
    )
    assert reduction_order is not None
    if (
        attempt.get("reduction_batch_id") != reduction_batch.manifest.batch_id
        or attempt.get("client_order_id") != reduction_order.client_order_id
        or attempt.get("reduction_key")
        != _reduction_attempt_key(
            parent_batch,
            event,
            purpose=str(attempt["purpose"]),
            signed_quantity=_float(attempt["signed_quantity"]),
        )
    ):
        raise FomcLiveError("fomc_live_reduction_attempt_identity_invalid")
    return attempt, reduction_batch, reduction_order


def _record_flat_ledger_state(
    settings: Settings,
    event: FomcEventDefinition,
    ledger: RuntimeLedger,
    reconciliation_batch: VerifiedDecisionBatch,
    *,
    preflight: Mapping[str, Any],
    exchange: Any,
    after: str,
    through: str,
    fill_fees_usdt: float | None = None,
) -> dict[str, Any]:
    """Write the account-verified flat state before a terminal execution artifact."""

    if (preflight.get("diagnostics") or {}).get("verdict") != (
        "fomc_live_account_preflight_pass"
    ):
        raise FomcLiveError("fomc_live_flat_ledger_preflight_not_passed")
    fee_totals = ledger.fill_fee_totals(after=after, through=through)
    recorded_fill_fees = fee_totals.get("USDT", 0.0)
    if fill_fees_usdt is not None and fill_fees_usdt - recorded_fill_fees > 1e-8:
        raise FomcLiveError("fomc_live_fill_fee_evidence_exceeds_ledger")
    unconverted_fees = {
        asset: amount
        for asset, amount in fee_totals.items()
        if asset != "USDT" and amount > 0.0
    }
    if unconverted_fees:
        _record_account_observation(
            ledger, reconciliation_batch, preflight, observed_at=through
        )
        return {
            "reduction_batch_id": reconciliation_batch.manifest.batch_id,
            "preflight_hash": preflight["preflight_hash"],
            "recorded_fill_fees_usdt": recorded_fill_fees,
            "unconverted_fill_fees": unconverted_fees,
            "accounting_complete": False,
            "accounting_blockers": [
                "fomc_live_non_usdt_fee_conversion_unavailable"
            ],
            "reconciliation": {
                "passed": False,
                "recorded": False,
                "blockers": [
                    "fomc_live_non_usdt_fee_conversion_unavailable"
                ],
            },
        }
    cash = _record_cash_events(
        exchange,
        ledger,
        after=after,
        through=through,
        fill_fees_usdt=recorded_fill_fees,
    )
    _record_account_observation(
        ledger, reconciliation_batch, preflight, observed_at=through
    )
    previous_nav = ledger.latest_nav_mark()
    if previous_nav is None:
        raise FomcLiveError("fomc_live_flat_ledger_nav_missing")
    balance = (preflight.get("account") or {}).get("balance") or {}
    equity = _float(balance.get("margin_balance"))
    nav = ledger.record_nav_mark(
        marked_at=through,
        equity=equity,
        trading_pnl=(
            equity
            - previous_nav.equity
            - _float(cash["funding_usdt"])
            + recorded_fill_fees
            - _float(cash["transfer_usdt"])
        ),
        residual_tolerance=0.001,
        source_hash=str(preflight["preflight_hash"]),
    )
    reconciliation = reconcile_three_way(
        batch_id=reconciliation_batch.manifest.batch_id,
        reconciled_at=through,
        phase="post_dispatch",
        target_positions=dict(reconciliation_batch.plan.expected_positions),
        ledger_positions=ledger.position_quantities(),
        exchange_positions=_preflight_exchange_positions(event, preflight),
        position_tolerances=dict(reconciliation_batch.plan.reconciliation_tolerance),
        ledger_open_order_ids=ledger.open_order_ids(),
        exchange_open_order_ids=_preflight_exchange_open_ids(preflight),
        equity_residual=nav.residual,
        equity_residual_tolerance=nav.residual_tolerance,
    )
    ledger.record_reconciliation(reconciliation)
    snapshot = build_runtime_ledger_snapshot(
        ledger, reconciliation_batch, captured_at=_time_after(through)
    )
    if not reconciliation.passed:
        raise FomcLiveError("fomc_live_flat_ledger_reconciliation_failed")
    return {
        "reduction_batch_id": reconciliation_batch.manifest.batch_id,
        "preflight_hash": preflight["preflight_hash"],
        "cash_evidence": cash,
        "recorded_fill_fees_usdt": recorded_fill_fees,
        "unconverted_fill_fees": {},
        "accounting_complete": True,
        "runtime_ledger_snapshot_hash": snapshot.snapshot_hash,
        "reconciliation": reconciliation.as_dict(),
    }


def _owned_stop_terminal_evidence(
    exchange: Any,
    event: FomcEventDefinition,
    *,
    ccxt_symbol: str,
    client_order_id: str,
    exchange_order_id: str | None = None,
) -> dict[str, Any]:
    response = _fetch_order_by_client_id(
        exchange,
        event,
        ccxt_symbol=ccxt_symbol,
        client_order_id=client_order_id,
        conditional=True,
    )
    view = _exchange_response_view(response)
    if view["client_order_id"] != client_order_id:
        raise FomcLiveError("fomc_live_stop_terminal_client_identity_invalid")
    if exchange_order_id and view["id"] != exchange_order_id:
        raise FomcLiveError("fomc_live_stop_terminal_exchange_identity_invalid")
    if view["status"] not in {"canceled", "expired", "rejected"}:
        raise FomcLiveError("fomc_live_stop_terminal_state_unverified")
    evidence_hash = canonical_hash(
        {
            "event": "fomc_live_owned_stop_terminal_query",
            "client_order_id": client_order_id,
            "response": response,
            "view": view,
        }
    )
    return view | {"evidence_hash": evidence_hash}


def _transition_owned_stop_terminal(
    ledger: RuntimeLedger,
    parent_batch: VerifiedDecisionBatch,
    *,
    stop_client_order_id: str | None = None,
    at: str,
    source_hash: str,
    terminal_evidence: Mapping[str, Any] | None,
    allow_unsubmitted: bool = False,
) -> None:
    default_stop_order = parent_batch.plan.orders[1]
    client_order_id = stop_client_order_id or default_stop_order.client_order_id
    current = ledger.get_order(client_order_id)
    if current["status"] in {"CANCELED", "REJECTED", "EXPIRED"}:
        return
    if current["status"] == "FILLED":
        raise FomcLiveError("fomc_live_stop_already_filled")
    if current["status"] == "PLANNED" and allow_unsubmitted and terminal_evidence is None:
        next_status = "CANCELED"
        exchange_order_id = None
        reason = "fomc_live_protection_never_submitted"
    else:
        if terminal_evidence is None:
            raise FomcLiveError("fomc_live_stop_terminal_evidence_missing")
        if terminal_evidence.get("client_order_id") != client_order_id:
            raise FomcLiveError("fomc_live_stop_terminal_client_identity_invalid")
        observed_status = _exchange_status(terminal_evidence.get("status"))
        next_status = {
            "canceled": "CANCELED",
            "expired": "EXPIRED",
            "rejected": "REJECTED",
        }.get(observed_status, "")
        if not next_status:
            raise FomcLiveError("fomc_live_stop_terminal_state_unverified")
        exchange_order_id = str(terminal_evidence.get("id") or "") or None
        reason = "fomc_live_owned_protection_terminal_after_flatten"
    ledger.transition_order(
        client_order_id,
        next_status,
        event_at=_time_after(str(current["last_transition_at"]), at),
        source_hash=source_hash,
        exchange_order_id=exchange_order_id,
        executed_quantity=_float(current["executed_quantity"]),
        average_price=(
            _float(current["average_price"])
            if current["average_price"] is not None
            else None
        ),
        reason=reason,
    )


def _ledgered_flatten_position(
    settings: Settings,
    event: FomcEventDefinition,
    live_store: FomcLiveStore,
    parent_batch: VerifiedDecisionBatch,
    *,
    exchange: Any,
    ccxt_symbol: str,
    quantity: float,
    position_side: str,
    purpose: str,
    protective_stop: Mapping[str, Any] | None,
    started_at: str,
    protective_stop_client_order_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Submit a registered reduce-only order and close its ledger evidence loop."""

    if position_side not in {"long", "short"} or abs(_float(quantity)) <= 0.0:
        raise FomcLiveError("fomc_live_reduction_position_invalid")
    ledger = live_store.ledger()
    signed_quantity = abs(_float(quantity)) * (1.0 if position_side == "long" else -1.0)
    attempt, reduction_batch, reduction_order = _load_or_create_reduction_attempt(
        live_store,
        parent_batch,
        event,
        purpose=purpose,
        signed_quantity=signed_quantity,
        started_at=started_at,
    )
    purpose = str(attempt["purpose"])
    ledger.record_verified_batch(
        reduction_batch, recorded_at=str(attempt["created_at"])
    )
    current = ledger.get_order(reduction_order.client_order_id)
    submitting_at = _time_after(
        str(attempt["created_at"]), str(current["last_transition_at"]), started_at
    )
    if current["status"] == "PLANNED":
        ledger.transition_order(
            reduction_order.client_order_id,
            "SUBMITTING",
            event_at=submitting_at,
            source_hash=canonical_hash(
                {
                    "event": "fomc_live_reduce_only_submission_started",
                    "purpose": purpose,
                    "client_order_id": reduction_order.client_order_id,
                    "reduction_attempt_hash": attempt["attempt_hash"],
                }
            ),
        )
        try:
            flattened = _flatten_position(
                settings,
                event,
                exchange=exchange,
                ccxt_symbol=ccxt_symbol,
                quantity=quantity,
                position_side=position_side,
                purpose=purpose,
                protective_stop=protective_stop,
                client_order_id=reduction_order.client_order_id,
            )
        except Exception:
            _mark_inflight_unknown(
                ledger,
                reduction_batch,
                reason="fomc_live_reduce_only_submission_uncertain",
            )
            raise
    elif current["status"] in {
        "SUBMITTING",
        "ACKNOWLEDGED",
        "PARTIALLY_FILLED",
        "UNKNOWN",
        "FILLED",
    }:
        response = _fetch_order_by_client_id(
            exchange,
            event,
            ccxt_symbol=ccxt_symbol,
            client_order_id=reduction_order.client_order_id,
            conditional=False,
        )
        response_view = _exchange_response_view(response)
        if response_view["status"] != "closed":
            terminal_status = {
                "canceled": "CANCELED",
                "expired": "EXPIRED",
                "rejected": "REJECTED",
            }.get(str(response_view["status"]))
            executed = _float(response_view.get("filled"))
            if terminal_status and 0.0 < executed < abs(_float(quantity)):
                partial_order, partial_fills, partial_hash = _fetch_market_fill_evidence(
                    exchange,
                    response,
                    ccxt_symbol=ccxt_symbol,
                    client_order_id=reduction_order.client_order_id,
                    planned_quantity=abs(_float(quantity)),
                    confirmed_response=response,
                )
                if partial_order.get("side") not in {
                    "",
                    "sell" if position_side == "long" else "buy",
                }:
                    raise FomcLiveError("fomc_live_reduction_partial_side_invalid")
                if current["status"] != terminal_status:
                    ledger.transition_order(
                        reduction_order.client_order_id,
                        terminal_status,
                        event_at=_time_after(
                            str(current["last_transition_at"]),
                            *(str(row["occurred_at"]) for row in partial_fills),
                        ),
                        source_hash=partial_hash,
                        exchange_order_id=str(partial_order["id"]),
                        executed_quantity=executed,
                        average_price=_float(partial_order["average"]),
                        reason="fomc_live_reduce_only_terminal_partial_fill",
                    )
                for fill in partial_fills:
                    ledger.record_fill(
                        client_order_id=reduction_order.client_order_id,
                        exchange_trade_id=str(fill["exchange_trade_id"]),
                        quantity=_float(fill["quantity"]),
                        price=_float(fill["price"]),
                        fee=_float(fill["fee"]),
                        fee_asset=str(fill["fee_asset"]),
                        occurred_at=str(fill["occurred_at"]),
                        source_hash=partial_hash,
                    )
                residual_quantity = abs(_float(quantity)) - executed
                residual_preflight = build_fomc_live_account_preflight(
                    settings,
                    event,
                    observed_at=_time_after(
                        *(str(row["occurred_at"]) for row in partial_fills)
                    ),
                    exchange=exchange,
                    halt_present=False,
                    expected_position_quantity=(
                        residual_quantity
                        if position_side == "long"
                        else -residual_quantity
                    ),
                )
                residual_positions = (
                    residual_preflight.get("account") or {}
                ).get("positions") or []
                if (
                    (residual_preflight.get("diagnostics") or {}).get("errors")
                    or len(residual_positions) != 1
                    or abs(
                        _float(residual_positions[0].get("quantity"))
                        - (
                            residual_quantity
                            if position_side == "long"
                            else -residual_quantity
                        )
                    )
                    > 1e-12
                ):
                    raise FomcLiveError(
                        "fomc_live_reduction_terminal_partial_residual_unverified"
                    )
                raise FomcLiveError(
                    "fomc_live_reduction_terminal_partial_residual_present"
                )
            if terminal_status and current["status"] != terminal_status:
                ledger.transition_order(
                    reduction_order.client_order_id,
                    terminal_status,
                    event_at=_time_after(str(current["last_transition_at"])),
                    source_hash=canonical_hash(
                        {
                            "event": "fomc_live_reduce_only_terminal_unfilled",
                            "response": response,
                            "view": response_view,
                        }
                    ),
                    exchange_order_id=str(response_view.get("id") or "") or None,
                    executed_quantity=executed,
                    average_price=(
                        _float(response_view.get("average"))
                        if executed > 0.0
                        else None
                    ),
                    reason="fomc_live_reduce_only_terminal_without_full_fill",
                )
            raise FomcLiveError("fomc_live_reduction_retry_not_filled")
        flattened = _confirm_flatten_response(
            settings,
            event,
            exchange=exchange,
            ccxt_symbol=ccxt_symbol,
            quantity=quantity,
            position_side=position_side,
            purpose=purpose,
            protective_stop=protective_stop,
            client_order_id=reduction_order.client_order_id,
            response=response,
            confirmed_response=response,
        )
    else:
        raise FomcLiveError("fomc_live_reduction_attempt_terminal_unfilled")

    exit_order = flattened["order"]
    fills = tuple(flattened["fills"])
    filled_at = _time_after(
        submitting_at,
        str(current["last_transition_at"]),
        *(str(row["occurred_at"]) for row in fills),
    )
    evidence_hash = str(flattened["evidence_hash"])
    current = ledger.get_order(reduction_order.client_order_id)
    if current["status"] != "FILLED":
        ledger.transition_order(
            reduction_order.client_order_id,
            "FILLED",
            event_at=filled_at,
            source_hash=evidence_hash,
            exchange_order_id=str(exit_order["id"]),
            executed_quantity=_float(exit_order["filled"]),
            average_price=_float(exit_order["average"]),
            reason="fomc_live_reduce_only_fill_confirmed",
        )
    for fill in fills:
        ledger.record_fill(
            client_order_id=reduction_order.client_order_id,
            exchange_trade_id=str(fill["exchange_trade_id"]),
            quantity=_float(fill["quantity"]),
            price=_float(fill["price"]),
            fee=_float(fill["fee"]),
            fee_asset=str(fill["fee_asset"]),
            occurred_at=str(fill["occurred_at"]),
            source_hash=evidence_hash,
        )

    active_stop_client_order_id = (
        protective_stop_client_order_id
        or parent_batch.plan.orders[1].client_order_id
    )
    stop_current = ledger.get_order(active_stop_client_order_id)
    stop_terminal = flattened.get("canceled_stop")
    if (
        stop_terminal is None
        and stop_current["status"] not in {"PLANNED", "CANCELED", "REJECTED", "EXPIRED"}
    ):
        stop_terminal = _owned_stop_terminal_evidence(
            exchange,
            event,
            ccxt_symbol=ccxt_symbol,
            client_order_id=active_stop_client_order_id,
            exchange_order_id=(
                str(stop_current["exchange_order_id"])
                if stop_current["exchange_order_id"] is not None
                else None
            ),
        )
    _transition_owned_stop_terminal(
        ledger,
        parent_batch,
        stop_client_order_id=active_stop_client_order_id,
        at=filled_at,
        source_hash=canonical_hash(
            {
                "event": "fomc_live_protection_removed_after_reduce_only_exit",
                "canceled_stop": flattened.get("canceled_stop"),
                "flat_readback_hash": flattened["post_preflight_hash"],
            }
        ),
        terminal_evidence=stop_terminal,
        allow_unsubmitted=True,
    )
    post = flattened.pop("_post_preflight", None)
    if not isinstance(post, Mapping):
        post = build_fomc_live_account_preflight(
            settings,
            event,
            observed_at=_time_after(filled_at),
            exchange=exchange,
            halt_present=False,
            expected_position_quantity=0.0,
        )
    through = _time_after(filled_at, str(post["created_at"]))
    previous_nav = ledger.latest_nav_mark()
    if previous_nav is None:
        raise FomcLiveError("fomc_live_flat_ledger_nav_missing")
    ledger_state = _record_flat_ledger_state(
        settings,
        event,
        ledger,
        reduction_batch,
        preflight=post,
        exchange=exchange,
        after=str(previous_nav.marked_at),
        through=through,
        fill_fees_usdt=sum(
            _float(row["fee"])
            for row in fills
            if str(row["fee_asset"]) == "USDT"
        ),
    )
    return flattened, ledger_state


def _ledger_native_stop_flatten(
    settings: Settings,
    event: FomcEventDefinition,
    ledger: RuntimeLedger,
    parent_batch: VerifiedDecisionBatch,
    *,
    exchange: Any,
    ccxt_symbol: str,
    stop_client_order_id: str,
    signed_quantity: float,
    observed_at: str,
) -> dict[str, Any]:
    """Reconstruct a native close-position stop before declaring the account flat."""

    response = _fetch_order_by_client_id(
        exchange,
        event,
        ccxt_symbol=ccxt_symbol,
        client_order_id=stop_client_order_id,
        conditional=True,
    )
    view, fills, evidence_hash = _fetch_market_fill_evidence(
        exchange,
        response,
        ccxt_symbol=ccxt_symbol,
        client_order_id=stop_client_order_id,
        planned_quantity=None,
        confirmed_response=response,
        conditional=True,
    )
    info = response.get("info") if isinstance(response.get("info"), Mapping) else {}
    is_algo = any(
        value not in (None, "")
        for value in (
            response.get("algoId"),
            response.get("clientAlgoId"),
            info.get("algoId"),
            info.get("clientAlgoId"),
        )
    )
    raw_type = str(
        response.get("orderType")
        or info.get("orderType")
        or info.get("origType")
        or response.get("type")
        or ""
    ).upper()
    expected_side = "sell" if signed_quantity > 0.0 else "buy"
    filled_quantity = sum(_float(row["quantity"]) for row in fills)
    if (
        view["client_order_id"] != stop_client_order_id
        or view["symbol"] not in {event.symbol, ccxt_symbol}
        or view["side"] != expected_side
        or "STOP" not in raw_type
        or not view["close_position"]
        or (is_algo and not view["actual_order_id"])
        or abs(filled_quantity - abs(signed_quantity)) > 1e-12
    ):
        raise FomcLiveError("fomc_live_native_stop_identity_invalid")
    filled_at = _time_after(observed_at, *(str(row["occurred_at"]) for row in fills))
    current = ledger.get_order(stop_client_order_id)
    if current["status"] != "FILLED":
        ledger.transition_order(
            stop_client_order_id,
            "FILLED",
            event_at=_time_after(str(current["last_transition_at"]), filled_at),
            source_hash=evidence_hash,
            exchange_order_id=str(view["id"]),
            executed_quantity=filled_quantity,
            average_price=_float(view["average"]),
            reason="fomc_live_native_stop_fill_confirmed",
        )
    ledger_filled_at = str(ledger.get_order(stop_client_order_id)["last_transition_at"])
    for fill in fills:
        ledger.record_fill(
            client_order_id=stop_client_order_id,
            exchange_trade_id=str(fill["exchange_trade_id"]),
            quantity=_float(fill["quantity"]),
            price=_float(fill["price"]),
            fee=_float(fill["fee"]),
            fee_asset=str(fill["fee_asset"]),
            occurred_at=str(fill["occurred_at"]),
            source_hash=evidence_hash,
        )
    reduction_batch, _ = _build_fomc_reduction_batch(
        parent_batch,
        event,
        purpose="native-stop-reconciliation",
        signed_quantity=signed_quantity,
        created_at=ledger_filled_at,
        include_order=False,
    )
    ledger.record_verified_batch(reduction_batch, recorded_at=ledger_filled_at)
    post = build_fomc_live_account_preflight(
        settings,
        event,
        observed_at=_time_after(filled_at),
        exchange=exchange,
        halt_present=False,
        expected_position_quantity=0.0,
    )
    through = _time_after(filled_at, str(post["created_at"]))
    previous_nav = ledger.latest_nav_mark()
    if previous_nav is None:
        raise FomcLiveError("fomc_live_flat_ledger_nav_missing")
    ledger_state = _record_flat_ledger_state(
        settings,
        event,
        ledger,
        reduction_batch,
        preflight=post,
        exchange=exchange,
        after=str(previous_nav.marked_at),
        through=through,
        fill_fees_usdt=sum(
            _float(row["fee"])
            for row in fills
            if str(row["fee_asset"]) == "USDT"
        ),
    )
    return {
        "order": view,
        "fills": list(fills),
        "evidence_hash": evidence_hash,
        "ledger_state": ledger_state,
    }


def _ledger_flat_without_entry_fill(
    settings: Settings,
    event: FomcEventDefinition,
    ledger: RuntimeLedger,
    parent_batch: VerifiedDecisionBatch,
    *,
    preflight: Mapping[str, Any],
    exchange: Any,
    entry_view: Mapping[str, Any],
    observed_at: str,
) -> dict[str, Any]:
    """Close a crash-recovered attempt that exchange proves never filled."""

    status = str(entry_view.get("status") or "").lower()
    terminal_status = {
        "rejected": "REJECTED",
        "reject": "REJECTED",
        "expired": "EXPIRED",
    }.get(status, "CANCELED")
    entry_order = parent_batch.plan.orders[0]
    current = ledger.get_order(entry_order.client_order_id)
    source_hash = canonical_hash(
        {
            "event": "fomc_live_interrupted_unfilled_entry_confirmed",
            "entry": dict(entry_view),
            "preflight_hash": preflight["preflight_hash"],
        }
    )
    if current["status"] == "FILLED":
        raise FomcLiveError("fomc_live_interrupted_entry_ledger_conflict")
    if current["status"] not in {"CANCELED", "REJECTED", "EXPIRED"}:
        if current["status"] == "PLANNED" and terminal_status != "CANCELED":
            raise FomcLiveError("fomc_live_interrupted_entry_transition_invalid")
        ledger.transition_order(
            entry_order.client_order_id,
            terminal_status,
            event_at=_time_after(str(current["last_transition_at"]), observed_at),
            source_hash=source_hash,
            exchange_order_id=str(entry_view.get("id") or "") or None,
            executed_quantity=0.0,
            reason="fomc_live_interrupted_entry_unfilled",
        )
    stop_order = parent_batch.plan.orders[1]
    stop_current = ledger.get_order(stop_order.client_order_id)
    stop_terminal: Mapping[str, Any] | None = None
    if stop_current["status"] not in {"PLANNED", "CANCELED", "REJECTED", "EXPIRED"}:
        stop_terminal = _owned_stop_terminal_evidence(
            exchange,
            event,
            ccxt_symbol=str((preflight.get("account") or {})["resolved_symbol"]),
            client_order_id=stop_order.client_order_id,
            exchange_order_id=(
                str(stop_current["exchange_order_id"])
                if stop_current["exchange_order_id"] is not None
                else None
            ),
        )
    _transition_owned_stop_terminal(
        ledger,
        parent_batch,
        at=observed_at,
        source_hash=source_hash,
        terminal_evidence=stop_terminal,
        allow_unsubmitted=True,
    )
    reconciliation_created_at = str(
        ledger.get_order(entry_order.client_order_id)["last_transition_at"]
    )
    reconciliation_batch, _ = _build_fomc_reduction_batch(
        parent_batch,
        event,
        purpose="interrupted-unfilled-entry-reconciliation",
        signed_quantity=0.0,
        created_at=reconciliation_created_at,
        include_order=False,
    )
    ledger.record_verified_batch(
        reconciliation_batch, recorded_at=reconciliation_created_at
    )
    through = _time_after(observed_at, str(preflight["created_at"]))
    return _record_flat_ledger_state(
        settings,
        event,
        ledger,
        reconciliation_batch,
        preflight=preflight,
        exchange=exchange,
        after=str(ledger.latest_nav_mark().marked_at),
        through=through,
        fill_fees_usdt=0.0,
    )


def _cancel_protective_stop(
    exchange: Any,
    event: FomcEventDefinition,
    *,
    ccxt_symbol: str,
    stop: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not stop:
        return None
    exchange_order_id = str(stop.get("id") or "")
    client_order_id = str(stop.get("client_order_id") or "")
    if not exchange_order_id or not client_order_id:
        raise FomcLiveError("fomc_live_stop_cancel_identity_missing")
    cancel_response: Mapping[str, Any] | None = None
    cancel_error_type: str | None = None
    try:
        response = call_with_time_sync_retry(
            exchange,
            exchange.cancel_order,
            exchange_order_id,
            ccxt_symbol,
            {"stop": True, "clientAlgoId": client_order_id},
            retry_attempts=1,
        )
        if not isinstance(response, Mapping):
            raise FomcLiveError("fomc_live_stop_cancel_response_invalid")
        cancel_response = response
        cancel_view = _exchange_response_view(response)
        if cancel_view["id"] and cancel_view["id"] != exchange_order_id:
            raise FomcLiveError("fomc_live_stop_cancel_exchange_identity_invalid")
        if (
            cancel_view["client_order_id"]
            and cancel_view["client_order_id"] != client_order_id
        ):
            raise FomcLiveError("fomc_live_stop_cancel_client_identity_invalid")
    except Exception as exc:
        cancel_error_type = type(exc).__name__
    terminal = _owned_stop_terminal_evidence(
        exchange,
        event,
        ccxt_symbol=ccxt_symbol,
        client_order_id=client_order_id,
        exchange_order_id=exchange_order_id,
    )
    return terminal | {
        "cancel_response": dict(cancel_response) if cancel_response is not None else None,
        "cancel_error_type": cancel_error_type,
    }


def _confirm_flatten_response(
    settings: Settings,
    event: FomcEventDefinition,
    *,
    exchange: Any,
    ccxt_symbol: str,
    quantity: float,
    position_side: str,
    purpose: str,
    protective_stop: Mapping[str, Any] | None,
    client_order_id: str,
    response: Mapping[str, Any],
    confirmed_response: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    absolute_quantity = abs(_float(quantity))
    if absolute_quantity <= 0.0 or position_side not in {"long", "short"}:
        raise FomcLiveError("fomc_live_flatten_position_invalid")
    expected_side = "sell" if position_side == "long" else "buy"
    submitted = _exchange_response_view(response)
    if (
        (submitted["client_order_id"] and submitted["client_order_id"] != client_order_id)
        or (submitted["side"] and submitted["side"] != expected_side)
        or submitted["symbol"] not in {"", event.symbol, ccxt_symbol}
    ):
        raise FomcLiveError("fomc_live_flatten_order_identity_invalid")
    order, fills, evidence_hash = _fetch_market_fill_evidence(
        exchange,
        response,
        ccxt_symbol=ccxt_symbol,
        client_order_id=client_order_id,
        planned_quantity=absolute_quantity,
        confirmed_response=confirmed_response,
    )
    if order["side"] and order["side"] != expected_side:
        raise FomcLiveError("fomc_live_flatten_order_side_invalid")
    canceled_stop = _cancel_protective_stop(
        exchange,
        event,
        ccxt_symbol=ccxt_symbol,
        stop=protective_stop,
    )
    post = build_fomc_live_account_preflight(
        settings,
        event,
        observed_at=_time_after(*(str(row["occurred_at"]) for row in fills)),
        exchange=exchange,
        halt_present=False,
        expected_position_quantity=0.0,
    )
    if (post.get("diagnostics") or {}).get("verdict") != (
        "fomc_live_account_preflight_pass"
    ):
        raise FomcLiveError("fomc_live_flatten_readback_failed")
    return {
        "purpose": purpose,
        "client_order_id": client_order_id,
        "canceled_stop": canceled_stop,
        "order": order,
        "fills": list(fills),
        "evidence_hash": evidence_hash,
        "post_preflight_hash": post["preflight_hash"],
        "flat_readback_verified": True,
        "_post_preflight": post,
    }


def _flatten_position(
    settings: Settings,
    event: FomcEventDefinition,
    *,
    exchange: Any,
    ccxt_symbol: str,
    quantity: float,
    position_side: str,
    purpose: str,
    protective_stop: Mapping[str, Any] | None = None,
    client_order_id: str | None = None,
) -> dict[str, Any]:
    """Flatten exactly once, resolve owned protection, and prove the account is flat."""

    absolute_quantity = abs(_float(quantity))
    if absolute_quantity <= 0.0 or position_side not in {"long", "short"}:
        raise FomcLiveError("fomc_live_flatten_position_invalid")
    client_order_id = client_order_id or _exit_client_order_id(event.event_id, purpose)
    response = call_with_time_sync_retry(
        exchange,
        exchange.create_order,
        ccxt_symbol,
        "market",
        "sell" if position_side == "long" else "buy",
        absolute_quantity,
        None,
        {
            "newClientOrderId": client_order_id,
            "reduceOnly": True,
        },
        retry_attempts=1,
    )
    if not isinstance(response, Mapping):
        raise FomcLiveError("fomc_live_flatten_response_invalid")
    return _confirm_flatten_response(
        settings,
        event,
        exchange=exchange,
        ccxt_symbol=ccxt_symbol,
        quantity=quantity,
        position_side=position_side,
        purpose=purpose,
        protective_stop=protective_stop,
        client_order_id=client_order_id,
        response=response,
    )


def dispatch_fomc_live_entry(
    settings: Settings,
    event: FomcEventDefinition,
    state_store: FomcStateStore,
    live_store: FomcLiveStore,
    readiness: Mapping[str, Any],
    arm: Mapping[str, Any],
    current_shadow: Mapping[str, Any],
    current_preflight: Mapping[str, Any],
    *,
    exchange: Any,
) -> dict[str, Any]:
    """Consume the exact arm, confirm the entry fill, then read back protection."""

    blockers = _current_scope_blockers(
        event, readiness, current_shadow, current_preflight
    )
    if blockers:
        return _execution_artifact(
            event,
            readiness,
            arm,
            observed_at=str(current_shadow["observed_at"]),
            status="blocked_current_scope",
            blockers=blockers,
            exchange_mutation_attempted=False,
        )
    batch_path = state_store.batches_root / str(readiness["batch_id"])
    batch = read_decision_batch(batch_path)
    if (
        batch.manifest.manifest_hash != readiness.get("manifest_hash")
        or batch.plan.plan_hash != readiness.get("plan_hash")
        or batch.plan.blockers != ("FOMC_MANUAL_ARM_REQUIRED",)
    ):
        raise FomcLiveError("fomc_live_bound_batch_invalid")
    scope = readiness.get("scope") or {}
    entry_order, stop_order = batch.plan.orders
    if (
        entry_order.client_order_id != scope.get("entry_client_order_id")
        or stop_order.client_order_id != scope.get("stop_client_order_id")
    ):
        raise FomcLiveError("fomc_live_bound_order_identity_invalid")
    ledger = live_store.ledger()
    pre_nav_time = _record_pre_dispatch_state(
        ledger, batch, event, current_preflight
    )
    attempt_core = {
        "schema_version": FOMC_LIVE_EXECUTION_VERSION,
        "artifact_type": "fomc_live_single_entry_attempt",
        "event_id": event.event_id,
        "arm_id": arm["arm_id"],
        "readiness_hash": readiness["readiness_hash"],
        "batch_id": batch.manifest.batch_id,
        "plan_hash": batch.plan.plan_hash,
        "started_at": _time_after(pre_nav_time),
        "entry_client_order_id": entry_order.client_order_id,
        "stop_client_order_id": stop_order.client_order_id,
    }
    attempt = attempt_core | {"attempt_hash": canonical_hash(attempt_core)}
    live_store.write_attempt(attempt)
    live_store.consume_arm(arm, consumed_at=attempt["started_at"])
    ccxt_symbol = str((current_preflight.get("account") or {})["resolved_symbol"])
    responses: list[dict[str, Any]] = []
    exchange_mutation_attempted = False
    entry_mutation = {"attempted": False}
    try:
        entry_started = _time_after(attempt["started_at"])
        entry_started_hash = canonical_hash(
            {
                "event": "fomc_live_entry_submission_started",
                "arm_id": arm["arm_id"],
                "client_order_id": entry_order.client_order_id,
            }
        )
        ledger.transition_order(
            entry_order.client_order_id,
            "SUBMITTING",
            event_at=entry_started,
            source_hash=entry_started_hash,
        )
        response, submission_timing = _create_fomc_entry_order(
            exchange,
            event,
            arm,
            current_shadow,
            current_preflight,
            ccxt_symbol=ccxt_symbol,
            side=entry_order.side,
            quantity=entry_order.quantity,
            client_order_id=entry_order.client_order_id,
            mutation_marker=entry_mutation,
        )
        exchange_mutation_attempted = entry_mutation["attempted"]
        entry_view, fills, entry_evidence_hash = _fetch_market_fill_evidence(
            exchange,
            response,
            ccxt_symbol=ccxt_symbol,
            client_order_id=entry_order.client_order_id,
            planned_quantity=_float(entry_order.quantity),
        )
        entry_observed_at = _time_after(
            entry_started, *(str(row["occurred_at"]) for row in fills)
        )
        terminal_partial = bool(entry_view.get("terminal_partial_fill"))
        observed_entry_status = (
            {
                "canceled": "CANCELED",
                "expired": "EXPIRED",
            }.get(str(entry_view.get("status")), "")
            if terminal_partial
            else "FILLED"
        )
        if not observed_entry_status:
            raise FomcLiveError("fomc_live_terminal_partial_entry_state_invalid")
        ledger.transition_order(
            entry_order.client_order_id,
            observed_entry_status,
            event_at=entry_observed_at,
            source_hash=entry_evidence_hash,
            exchange_order_id=str(entry_view["id"]),
            executed_quantity=_float(entry_view["filled"]),
            average_price=_float(entry_view["average"]),
            reason=(
                "fomc_live_terminal_partial_entry_confirmed"
                if terminal_partial
                else "fomc_live_market_fill_confirmed"
            ),
        )
        for fill in fills:
            ledger.record_fill(
                client_order_id=entry_order.client_order_id,
                exchange_trade_id=str(fill["exchange_trade_id"]),
                quantity=_float(fill["quantity"]),
                price=_float(fill["price"]),
                fee=_float(fill["fee"]),
                fee_asset=str(fill["fee_asset"]),
                occurred_at=str(fill["occurred_at"]),
                source_hash=entry_evidence_hash,
            )
        slippage = _adverse_slippage_bps(
            side=entry_order.side,
            reference_price=_float(scope["reference_entry_price"]),
            average_fill_price=_float(entry_view["average"]),
        )
        entry_record = entry_view | {
            "evidence_hash": entry_evidence_hash,
            "fills": list(fills),
            "adverse_slippage_bps": slippage,
            "submission_timing": submission_timing,
        }
        responses.append(entry_record)
        if terminal_partial:
            raise FomcLiveError("fomc_live_terminal_partial_entry_requires_flatten")

        stop_started = _time_after(entry_observed_at)
        ledger.transition_order(
            stop_order.client_order_id,
            "SUBMITTING",
            event_at=stop_started,
            source_hash=canonical_hash(
                {
                    "event": "fomc_live_stop_submission_started",
                    "arm_id": arm["arm_id"],
                    "client_order_id": stop_order.client_order_id,
                }
            ),
        )
        stop_response = call_with_time_sync_retry(
            exchange,
            exchange.create_order,
            ccxt_symbol,
            "STOP_MARKET",
            stop_order.side,
            None,
            None,
            {
                "stopPrice": stop_order.stop_price,
                "closePosition": True,
                "newClientOrderId": stop_order.client_order_id,
                "workingType": "MARK_PRICE",
            },
            retry_attempts=1,
        )
        if not isinstance(stop_response, Mapping):
            raise FomcLiveError("fomc_live_stop_response_invalid")
        stop_view = _exchange_response_view(stop_response)
        stop_view["client_order_id"] = stop_order.client_order_id
        if not stop_view["id"]:
            raise FomcLiveError("fomc_live_stop_acknowledgement_missing")
        post_preflight = build_fomc_live_account_preflight(
            settings,
            event,
            observed_at=_time_after(stop_started),
            exchange=exchange,
            halt_present=live_store.halt_path.exists(),
            expected_position_quantity=_float(
                batch.plan.expected_positions[event.instrument_key]
            ),
            expected_stop_client_id=stop_order.client_order_id,
            expected_stop_price=_float(stop_order.stop_price),
            price_tick=_float(scope["price_tick"]),
        )
        if (post_preflight.get("diagnostics") or {}).get("verdict") != (
            "fomc_live_account_preflight_pass"
        ):
            raise FomcLiveError("fomc_live_stop_readback_failed")
        readback = next(
            row
            for row in (post_preflight.get("account") or {}).get(
                "conditional_open_orders", []
            )
            if row.get("client_order_id") == stop_order.client_order_id
        )
        stop_ack_time = _time_after(stop_started)
        stop_evidence_hash = canonical_hash(
            {
                "event": "fomc_live_stop_acknowledged_and_read_back",
                "response": stop_view,
                "readback": readback,
                "post_preflight_hash": post_preflight["preflight_hash"],
            }
        )
        ledger.transition_order(
            stop_order.client_order_id,
            "ACKNOWLEDGED",
            event_at=stop_ack_time,
            source_hash=stop_evidence_hash,
            exchange_order_id=str(stop_view["id"]),
            reason="fomc_live_native_stop_confirmed",
        )
        protection_record = stop_view | {
            "readback": readback,
            "evidence_hash": stop_evidence_hash,
            "acknowledged_at": stop_ack_time,
        }
        responses.append(protection_record)

        if entry_view.get("fee_conversion_complete") is not True:
            raise FomcLiveError("fomc_live_entry_fee_conversion_unavailable")

        post_time = _time_after(stop_ack_time)
        fill_fees = _float(entry_view.get("fee_usdt"))
        cash = _record_cash_events(
            exchange,
            ledger,
            after=pre_nav_time,
            through=post_time,
            fill_fees_usdt=fill_fees,
        )
        _record_account_observation(
            ledger, batch, post_preflight, observed_at=post_time
        )
        previous_nav = ledger.latest_nav_mark()
        if previous_nav is None:
            raise FomcLiveError("fomc_live_pre_dispatch_nav_missing")
        balance = (post_preflight.get("account") or {}).get("balance") or {}
        equity = _float(balance.get("margin_balance"))
        nav = ledger.record_nav_mark(
            marked_at=post_time,
            equity=equity,
            trading_pnl=(
                equity
                - previous_nav.equity
                - _float(cash["funding_usdt"])
                + fill_fees
                - _float(cash["transfer_usdt"])
            ),
            residual_tolerance=0.001,
            source_hash=str(post_preflight["preflight_hash"]),
        )
        reconciliation = reconcile_three_way(
            batch_id=batch.manifest.batch_id,
            reconciled_at=post_time,
            phase="post_dispatch",
            target_positions=dict(batch.plan.expected_positions),
            ledger_positions=ledger.position_quantities(),
            exchange_positions=_preflight_exchange_positions(event, post_preflight),
            position_tolerances=dict(batch.plan.reconciliation_tolerance),
            ledger_open_order_ids=ledger.open_order_ids(),
            exchange_open_order_ids=_preflight_exchange_open_ids(post_preflight),
            equity_residual=nav.residual,
            equity_residual_tolerance=nav.residual_tolerance,
        )
        ledger.record_reconciliation(reconciliation)
        snapshot = build_runtime_ledger_snapshot(
            ledger, batch, captured_at=_time_after(post_time)
        )
        if not reconciliation.passed:
            raise FomcLiveError("fomc_live_post_dispatch_reconciliation_failed")
        status = (
            "protected_slippage_halt"
            if slippage > FOMC_LIVE_MAX_ADVERSE_SLIPPAGE_BPS
            else "protected"
        )
        execution = _execution_artifact(
            event,
            readiness,
            arm,
            observed_at=post_time,
            status=status,
            entry=entry_record,
            protection=protection_record,
            reconciliation={
                "report": reconciliation.as_dict(),
                "runtime_ledger_snapshot_hash": snapshot.snapshot_hash,
                "cash_evidence": cash,
            },
            exchange_mutation_attempted=True,
        )
        if status != "protected":
            live_store.halt("fomc_live_adverse_slippage", occurred_at=post_time)
        live_store.write_execution(execution)
        return execution
    except Exception as exc:
        exchange_mutation_attempted = (
            exchange_mutation_attempted or entry_mutation["attempted"]
        )
        reason = f"execution_error:{type(exc).__name__}"
        occurred_at = _time_after(attempt["started_at"])
        if not exchange_mutation_attempted:
            no_submit_hash = canonical_hash(
                {
                    "event": "fomc_live_pre_submit_aborted",
                    "reason": reason,
                    "client_order_id": entry_order.client_order_id,
                }
            )
            current_entry = ledger.get_order(entry_order.client_order_id)
            if current_entry["status"] == "SUBMITTING":
                ledger.transition_order(
                    entry_order.client_order_id,
                    "CANCELED",
                    event_at=_time_after(
                        str(current_entry["last_transition_at"]), occurred_at
                    ),
                    source_hash=no_submit_hash,
                    reason="fomc_live_pre_submit_time_or_scope_abort",
                )
            _transition_owned_stop_terminal(
                ledger,
                batch,
                at=occurred_at,
                source_hash=no_submit_hash,
                terminal_evidence=None,
                allow_unsubmitted=True,
            )
            live_store.halt(reason, occurred_at=occurred_at)
            execution = _execution_artifact(
                event,
                readiness,
                arm,
                observed_at=occurred_at,
                status="halted_pre_submit",
                blockers=(reason, _safe_error(exc, settings)),
                reconciliation={"ledger_integrity": ledger.integrity_check()},
                exchange_mutation_attempted=False,
            )
            live_store.write_execution(execution)
            return execution
        _mark_inflight_unknown(ledger, batch, reason=reason)
        live_store.halt(reason, occurred_at=occurred_at)
        emergency: dict[str, Any] | None = None
        emergency_quantity = 0.0
        emergency_side = "long" if str(scope["side"]) == "long" else "short"
        emergency_stop = responses[1] if len(responses) > 1 else None
        if exchange_mutation_attempted:
            try:
                observed = build_fomc_live_account_preflight(
                    settings,
                    event,
                    observed_at=_time_after(attempt["started_at"]),
                    exchange=exchange,
                    halt_present=False,
                )
                observed_account = observed.get("account") or {}
                observed_diagnostics = observed.get("diagnostics") or {}
                if observed_diagnostics.get("errors"):
                    raise FomcLiveError("fomc_live_emergency_account_read_incomplete")
                if observed_account.get("account_scope_hash") != scope.get(
                    "account_scope_hash"
                ):
                    raise FomcLiveError("fomc_live_emergency_account_scope_changed")
                regular_orders = observed_account.get("regular_open_orders") or []
                owned_regular = [
                    row
                    for row in regular_orders
                    if row.get("client_order_id") == entry_order.client_order_id
                ]
                if len(owned_regular) != len(regular_orders) or len(owned_regular) > 1:
                    raise FomcLiveError(
                        "fomc_live_emergency_regular_order_ownership_ambiguous"
                    )
                if owned_regular:
                    owned_entry = owned_regular[0]
                    if not owned_entry.get("id"):
                        raise FomcLiveError(
                            "fomc_live_emergency_entry_identity_missing"
                        )
                    canceled = call_with_time_sync_retry(
                        exchange,
                        exchange.cancel_order,
                        str(owned_entry["id"]),
                        str(observed_account["resolved_symbol"]),
                        retry_attempts=1,
                    )
                    if not isinstance(canceled, Mapping):
                        raise FomcLiveError(
                            "fomc_live_emergency_entry_cancel_invalid"
                        )
                    observed = build_fomc_live_account_preflight(
                        settings,
                        event,
                        observed_at=_time_after(str(observed["created_at"])),
                        exchange=exchange,
                        halt_present=False,
                    )
                    observed_account = observed.get("account") or {}
                    observed_diagnostics = observed.get("diagnostics") or {}
                    if (
                        observed_diagnostics.get("errors")
                        or observed_account.get("account_scope_hash")
                        != scope.get("account_scope_hash")
                        or observed_account.get("regular_open_orders")
                    ):
                        raise FomcLiveError(
                            "fomc_live_emergency_entry_cancel_unverified"
                        )
                matching_positions = [
                    row
                    for row in observed_account.get("positions", [])
                    if row.get("symbol")
                    == observed_account.get("resolved_symbol")
                ]
                if (
                    len(matching_positions) != 1
                    or len(observed_account.get("positions", [])) != 1
                ):
                    raise FomcLiveError("fomc_live_emergency_position_ambiguous")
                signed_quantity = _float(matching_positions[0].get("quantity"))
                expected_quantity = abs(_float(scope.get("quantity")))
                entry_evidence = (
                    responses[0]
                    if responses
                    else _fetch_order_by_client_id(
                        exchange,
                        event,
                        ccxt_symbol=ccxt_symbol,
                        client_order_id=entry_order.client_order_id,
                        conditional=False,
                    )
                )
                entry_view = _exchange_response_view(entry_evidence)
                expected_entry_side = "buy" if scope.get("side") == "long" else "sell"
                observed_quantity = _float(entry_view.get("filled"))
                if (
                    entry_view["client_order_id"] != entry_order.client_order_id
                    or entry_view["side"] != expected_entry_side
                    or entry_view["symbol"] not in {event.symbol, ccxt_symbol}
                    or entry_view["status"] not in {"closed", "filled", "canceled", "expired"}
                    or observed_quantity <= 0.0
                    or observed_quantity > expected_quantity + 1e-12
                    or abs(abs(signed_quantity) - observed_quantity) > 1e-12
                    or signed_quantity * (1.0 if expected_entry_side == "buy" else -1.0) <= 0.0
                ):
                    raise FomcLiveError("fomc_live_emergency_position_not_owned")
                _record_recovered_entry_fill(
                    ledger,
                    batch,
                    event,
                    exchange=exchange,
                    ccxt_symbol=ccxt_symbol,
                    response=entry_evidence,
                )
                emergency_quantity = abs(signed_quantity)
                emergency_side = "long" if signed_quantity > 0.0 else "short"
                stops = observed_account.get("conditional_open_orders", [])
                matching_stops = [
                    row
                    for row in stops
                    if row.get("client_order_id") == stop_order.client_order_id
                ]
                if len(matching_stops) > 1:
                    raise FomcLiveError("fomc_live_emergency_stop_ambiguous")
                if matching_stops:
                    emergency_stop = matching_stops[0]
                    if not _protective_stop_shape_matches(
                        emergency_stop,
                        signed_quantity=signed_quantity,
                        stop_price=_float(scope.get("stop_price"), math.nan),
                        price_tick=_float(scope.get("price_tick")),
                    ):
                        raise FomcLiveError("fomc_live_emergency_stop_not_owned")
                elif stops:
                    raise FomcLiveError("fomc_live_emergency_stop_unowned")
                if emergency_quantity <= 0.0:
                    raise FomcLiveError("fomc_live_emergency_position_unknown")
                flattened, ledger_state = _ledgered_flatten_position(
                    settings,
                    event,
                    live_store,
                    batch,
                    exchange=exchange,
                    ccxt_symbol=ccxt_symbol,
                    quantity=emergency_quantity,
                    position_side=emergency_side,
                    purpose="protection-failure",
                    protective_stop=emergency_stop,
                    started_at=_time_after(attempt["started_at"]),
                )
                emergency = flattened | {"ledger_state": ledger_state}
            except Exception as flatten_exc:
                emergency = {
                    "purpose": "protection-failure",
                    "flat_readback_verified": False,
                    "error": _safe_error(flatten_exc, settings),
                }
        status = (
            "halted_emergency_flattened"
            if emergency and emergency.get("flat_readback_verified") is True
            else "halted_uncertain"
        )
        execution = _execution_artifact(
            event,
            readiness,
            arm,
            observed_at=occurred_at,
            status=status,
            blockers=(reason, _safe_error(exc, settings)),
            reconciliation={
                "ledger_integrity": ledger.integrity_check(),
                "exchange_responses": responses,
                "emergency_flatten": emergency,
            },
            exchange_mutation_attempted=exchange_mutation_attempted,
        )
        live_store.write_execution(execution)
        return execution


def manage_fomc_live_position(
    settings: Settings,
    event: FomcEventDefinition,
    live_store: FomcLiveStore,
    *,
    state_store: FomcStateStore,
    observed_at: str | dt.datetime,
    exchange: Any,
) -> dict[str, Any]:
    """Monitor protection until a ledger-reconciled flat terminal state exists."""

    requested_time = _utc(observed_at)
    deadline_time = max(requested_time, _utc())

    execution = live_store.read_execution()
    if execution is None:
        raise FomcLiveError("fomc_live_execution_missing")
    if execution.get("status") in {
        "force_exit_flattened",
        "halted_emergency_flattened",
        "protection_failure_flattened",
        "native_stop_flattened",
        "management_early_exit_flattened",
    }:
        return execution
    if execution.get("status") not in {
        "protected",
        "protected_slippage_halt",
        "halted_position_state_changed",
        "management_state_uncertain",
        "halted_uncertain",
    }:
        raise FomcLiveError("fomc_live_execution_not_manageable")
    scope = execution.get("scope") or {}
    parent_batch = read_decision_batch(
        state_store.batches_root / str(execution["batch_id"])
    )
    ledger = live_store.ledger()
    management_state: dict[str, Any] | None = None
    if _management_enabled(scope):
        management_state = live_store.read_management_state()
        if management_state is None:
            management_state = _management_state_payload(
                event=event,
                parent_batch=parent_batch,
                scope=scope,
                execution=execution,
                created_at=deadline_time.isoformat(),
            )
            live_store.write_management_state(management_state)
        if (
            management_state.get("event_id") != event.event_id
            or management_state.get("parent_batch_id")
            != parent_batch.manifest.batch_id
        ):
            raise FomcLiveError("fomc_live_management_state_identity_invalid")
    side = str(scope.get("side") or "")
    signed_quantity = _float(scope.get("quantity")) * (
        1.0 if side == "long" else -1.0
    )
    stop_client_id = str(scope.get("stop_client_order_id") or "")
    active_stop_price = _float(scope.get("stop_price"), math.nan)
    if management_state is not None:
        side = str(management_state["side"])
        signed_quantity = _float(management_state["remaining_quantity"]) * (
            1.0 if side == "long" else -1.0
        )
        stop_client_id = str(management_state["active_stop_client_order_id"])
        active_stop_price = _float(management_state["active_stop_price"], math.nan)
    current_protection: Mapping[str, Any] | None = execution.get("protection")

    def artifact(
        status: str,
        *,
        blockers: Sequence[str] = (),
        reconciliation: Mapping[str, Any] | None = None,
        exchange_mutation_attempted: bool = False,
    ) -> dict[str, Any]:
        return _execution_artifact(
            event,
            {
                "readiness_hash": execution["readiness_hash"],
                "batch_id": execution["batch_id"],
                "scope": scope,
            },
            {"arm_id": execution["arm_id"]},
            observed_at=deadline_time.isoformat(),
            status=status,
            entry=execution.get("entry"),
            protection=current_protection,
            blockers=blockers,
            reconciliation=reconciliation,
            exchange_mutation_attempted=exchange_mutation_attempted,
        )

    preflight = build_fomc_live_account_preflight(
        settings,
        event,
        observed_at=observed_at,
        exchange=exchange,
        halt_present=False,
        expected_position_quantity=signed_quantity,
        expected_stop_client_id=stop_client_id,
        expected_stop_price=active_stop_price,
        price_tick=_float(scope.get("price_tick")),
    )
    account = preflight.get("account") or {}
    diagnostics = preflight.get("diagnostics") or {}
    positions = account.get("positions") or []
    regular = account.get("regular_open_orders") or []
    conditional = account.get("conditional_open_orders") or []
    matching_positions = [
        row
        for row in positions
        if row.get("symbol") == account.get("resolved_symbol")
    ]
    matching_stops = [
        row
        for row in conditional
        if row.get("client_order_id") == stop_client_id
    ]
    account_scope_matches = account.get("account_scope_hash") == scope.get(
        "account_scope_hash"
    )
    complete_read = not diagnostics.get("errors")
    exact_position = (
        len(positions) == 1
        and len(matching_positions) == 1
        and abs(_float(matching_positions[0].get("quantity")) - signed_quantity)
        <= 1e-12
    )
    stop_shape_exact = not matching_stops or (
        len(matching_stops) == 1
        and _protective_stop_shape_matches(
            matching_stops[0],
            signed_quantity=signed_quantity,
            stop_price=active_stop_price,
            price_tick=_float(scope.get("price_tick")),
        )
    )
    only_owned_stop = len(conditional) == len(matching_stops) <= 1
    reduction_attempt = _existing_reduction_attempt(live_store, parent_batch, event)
    entry_order = parent_batch.plan.orders[0]
    entry_state = ledger.get_order(entry_order.client_order_id)
    execution_entry = execution.get("entry") or {}
    ledger_position_exact = abs(
        ledger.position_quantities().get(event.instrument_key, 0.0) - signed_quantity
    ) <= 1e-12
    expected_entry_quantity = (
        _float(management_state.get("initial_quantity"), math.nan)
        if management_state is not None
        else abs(signed_quantity)
    )
    strategy_position_evidence_exact = (
        entry_state["status"] == "FILLED"
        and abs(_float(entry_state["executed_quantity"]) - expected_entry_quantity)
        <= 1e-12
        and execution_entry.get("client_order_id") == entry_order.client_order_id
        and execution_entry.get("side") == entry_order.side
        and execution_entry.get("symbol")
        in {event.symbol, str(account.get("resolved_symbol"))}
        and _exchange_status(execution_entry.get("status")) == "closed"
        and abs(_float(execution_entry.get("filled")) - expected_entry_quantity)
        <= 1e-12
        and ledger_position_exact
    )

    if not complete_read or not account_scope_matches:
        live_store.halt(
            "fomc_live_position_state_unreadable",
            occurred_at=deadline_time.isoformat(),
        )
        result = artifact(
            "management_state_uncertain",
            blockers=tuple(diagnostics.get("blockers") or ())
            + (("account_scope_changed",) if not account_scope_matches else ()),
            reconciliation={"preflight_hash": preflight["preflight_hash"]},
        )
        live_store.write_execution(result)
        return result

    if not positions and not regular and not conditional and reduction_attempt is not None:
        try:
            reduction_order_state = ledger.get_order(
                str(reduction_attempt["client_order_id"])
            )
        except KeyError:
            reduction_order_state = None
        if reduction_order_state is not None and reduction_order_state["status"] != "PLANNED":
            purpose = str(reduction_attempt["purpose"])
            try:
                flattened, ledger_state = _ledgered_flatten_position(
                    settings,
                    event,
                    live_store,
                    parent_batch,
                    exchange=exchange,
                    ccxt_symbol=str(account["resolved_symbol"]),
                    quantity=abs(signed_quantity),
                    position_side=side,
                    purpose=purpose,
                    protective_stop=None,
                    started_at=_time_after(str(preflight["created_at"])),
                )
                terminal_status = {
                    "force-exit": "force_exit_flattened",
                    "protection-missing": "protection_failure_flattened",
                    "protection-failure": "halted_emergency_flattened",
                }.get(purpose, "force_exit_flattened")
                result = artifact(
                    terminal_status,
                    reconciliation={purpose: flattened, "ledger_state": ledger_state},
                )
            except Exception as exc:
                result = artifact(
                    "management_state_uncertain",
                    blockers=(
                        "fomc_live_reduce_only_recovery_uncertain",
                        _safe_error(exc, settings),
                    ),
                    reconciliation={"preflight_hash": preflight["preflight_hash"]},
                )
            live_store.write_execution(result)
            return result

    if not positions and not regular and not conditional:
        try:
            native_stop = _ledger_native_stop_flatten(
                settings,
                event,
                ledger,
                parent_batch,
                exchange=exchange,
                ccxt_symbol=str(account["resolved_symbol"]),
                stop_client_order_id=stop_client_id,
                signed_quantity=signed_quantity,
                observed_at=deadline_time.isoformat(),
            )
            result = artifact(
                "native_stop_flattened",
                reconciliation={"native_stop": native_stop},
            )
        except Exception as exc:
            result = artifact(
                "management_state_uncertain",
                blockers=("fomc_live_flat_account_ledger_unresolved", _safe_error(exc, settings)),
                reconciliation={"preflight_hash": preflight["preflight_hash"]},
            )
        live_store.write_execution(result)
        return result

    preflight_passed = diagnostics.get("verdict") == "fomc_live_account_preflight_pass"
    protection_missing = (
        exact_position
        and not regular
        and only_owned_stop
        and (not matching_stops or not stop_shape_exact)
    )
    pending_action = (
        management_state.get("pending_action")
        if management_state is not None
        else None
    )
    if (
        management_state is not None
        and isinstance(pending_action, Mapping)
        and deadline_time < event.force_exit_time
        and exact_position
        and strategy_position_evidence_exact
        and not regular
        and only_owned_stop
    ):
        action_phase = str(pending_action.get("phase") or "")
        active_stop = matching_stops[0] if matching_stops else None
        can_continue = preflight_passed or (
            action_phase in {"active_stop_canceled", "submitting_replacement_stop"}
            and not conditional
        )
        if can_continue:
            try:
                management_state, management_evidence, _ = _continue_management_action(
                    settings,
                    event,
                    live_store,
                    ledger,
                    parent_batch,
                    management_state,
                    exchange=exchange,
                    ccxt_symbol=str(account["resolved_symbol"]),
                    active_stop=active_stop,
                    started_at=_time_after(str(preflight["created_at"])),
                )
                current_protection = management_evidence.get(
                    "replacement_stop", current_protection
                )
                result = artifact(
                    "protected",
                    reconciliation={
                        "preflight_hash": preflight["preflight_hash"],
                        "management": management_evidence,
                        "management_hash": management_state["management_hash"],
                    },
                    exchange_mutation_attempted=True,
                )
                live_store.write_execution(result)
                return result
            except Exception as exc:
                latest_management = live_store.read_management_state() or management_state
                latest_pending = latest_management.get("pending_action") or {}
                phase_after_error = str(latest_pending.get("phase") or "")
                if phase_after_error in {
                    "active_stop_canceled",
                    "submitting_replacement_stop",
                }:
                    try:
                        replacement_cleanup = _cancel_uncertain_management_replacement_stop(
                            ledger,
                            parent_batch,
                            event,
                            exchange=exchange,
                            ccxt_symbol=str(account["resolved_symbol"]),
                            replacement_stop_client_order_id=str(
                                latest_pending["replacement_stop_client_order_id"]
                            ),
                            signed_remaining_quantity=signed_quantity,
                            replacement_stop_price=_float(
                                latest_pending["replacement_stop_price"]
                            ),
                            price_tick=_float(latest_management["price_tick"]),
                            at=_time_after(str(preflight["created_at"])),
                        )
                        flattened, ledger_state = _ledgered_flatten_position(
                            settings,
                            event,
                            live_store,
                            parent_batch,
                            exchange=exchange,
                            ccxt_symbol=str(account["resolved_symbol"]),
                            quantity=abs(signed_quantity),
                            position_side=side,
                            purpose="management-protection-replacement-failure",
                            protective_stop=None,
                            protective_stop_client_order_id=str(
                                latest_pending["replacement_stop_client_order_id"]
                            ),
                            started_at=_time_after(str(preflight["created_at"])),
                        )
                        live_store.halt(
                            "fomc_live_management_replacement_stop_failed",
                            occurred_at=deadline_time.isoformat(),
                        )
                        result = artifact(
                            "halted_emergency_flattened",
                            blockers=(
                                "fomc_live_management_replacement_stop_failed",
                                _safe_error(exc, settings),
                            ),
                            reconciliation={
                                "replacement_stop_cleanup": replacement_cleanup,
                                "management_emergency_flatten": flattened,
                                "ledger_state": ledger_state,
                            },
                            exchange_mutation_attempted=True,
                        )
                    except Exception as flatten_exc:
                        live_store.halt(
                            "fomc_live_management_replacement_stop_uncertain",
                            occurred_at=deadline_time.isoformat(),
                        )
                        result = artifact(
                            "management_state_uncertain",
                            blockers=(
                                "fomc_live_management_replacement_stop_uncertain",
                                _safe_error(exc, settings),
                                _safe_error(flatten_exc, settings),
                            ),
                            exchange_mutation_attempted=True,
                        )
                else:
                    live_store.halt(
                        "fomc_live_management_action_uncertain",
                        occurred_at=deadline_time.isoformat(),
                    )
                    result = artifact(
                        "management_state_uncertain",
                        blockers=(
                            "fomc_live_management_action_uncertain",
                            _safe_error(exc, settings),
                        ),
                        reconciliation={"preflight_hash": preflight["preflight_hash"]},
                        exchange_mutation_attempted=True,
                    )
                live_store.write_execution(result)
                return result
    if preflight_passed and deadline_time < event.force_exit_time:
        if management_state is not None:
            try:
                hourly, fifteen_minute, market = collect_fomc_public_market(
                    exchange,
                    event,
                    observed_at=deadline_time,
                )
                if (
                    market.exchange_rules_hash != scope.get("exchange_rules_hash")
                    or abs(market.price_tick - _float(scope.get("price_tick"))) > 1e-12
                    or abs(market.quantity_step - _float(scope.get("quantity_step")))
                    > 1e-12
                ):
                    raise FomcLiveError("fomc_live_management_public_rules_changed")
                policy_decision = _evaluate_fomc_management_policy(
                    management_state,
                    hourly=hourly,
                    fifteen_minute=fifteen_minute,
                    mark_price=market.mark_price,
                    funding_rate=market.funding_rate,
                )
            except Exception as exc:
                result = artifact(
                    "protected",
                    blockers=("fomc_live_management_market_unavailable", _safe_error(exc, settings)),
                    reconciliation={
                        "preflight_hash": preflight["preflight_hash"],
                        "management_hash": management_state["management_hash"],
                    },
                )
                live_store.write_execution(result)
                return result
            if policy_decision.get("reached_one_r") and not management_state.get(
                "one_r_confirmed"
            ):
                management_state = _advance_management_state(
                    management_state,
                    updated_at=deadline_time.isoformat(),
                    one_r_confirmed=True,
                )
                live_store.write_management_state(management_state)
            if policy_decision.get("kind") == "flatten":
                purpose = str(policy_decision["purpose"])
                try:
                    flattened, ledger_state = _ledgered_flatten_position(
                        settings,
                        event,
                        live_store,
                        parent_batch,
                        exchange=exchange,
                        ccxt_symbol=str(account["resolved_symbol"]),
                        quantity=abs(signed_quantity),
                        position_side=side,
                        purpose=purpose,
                        protective_stop=(matching_stops[0] if matching_stops else None),
                        protective_stop_client_order_id=stop_client_id,
                        started_at=_time_after(str(preflight["created_at"])),
                    )
                    result = artifact(
                        "management_early_exit_flattened",
                        reconciliation={
                            purpose: flattened,
                            "ledger_state": ledger_state,
                            "management": policy_decision,
                        },
                        exchange_mutation_attempted=True,
                    )
                except Exception as exc:
                    live_store.halt(
                        "fomc_live_management_exit_uncertain",
                        occurred_at=deadline_time.isoformat(),
                    )
                    result = artifact(
                        "management_state_uncertain",
                        blockers=("fomc_live_management_exit_uncertain", _safe_error(exc, settings)),
                        exchange_mutation_attempted=True,
                    )
                live_store.write_execution(result)
                return result
            if policy_decision.get("kind") == "action":
                replacement_stop_price = _float(
                    policy_decision.get("replacement_stop_price"), math.nan
                )
                stop_already_crossed = (
                    side == "long" and market.mark_price <= replacement_stop_price
                ) or (
                    side == "short" and market.mark_price >= replacement_stop_price
                )
                if stop_already_crossed:
                    policy_decision = dict(policy_decision) | {
                        "kind": "flatten",
                        "purpose": "management-stop-already-crossed",
                    }
                    try:
                        flattened, ledger_state = _ledgered_flatten_position(
                            settings,
                            event,
                            live_store,
                            parent_batch,
                            exchange=exchange,
                            ccxt_symbol=str(account["resolved_symbol"]),
                            quantity=abs(signed_quantity),
                            position_side=side,
                            purpose=str(policy_decision["purpose"]),
                            protective_stop=(matching_stops[0] if matching_stops else None),
                            protective_stop_client_order_id=stop_client_id,
                            started_at=_time_after(str(preflight["created_at"])),
                        )
                        result = artifact(
                            "management_early_exit_flattened",
                            reconciliation={
                                "management": policy_decision,
                                "ledger_state": ledger_state,
                                "flattened": flattened,
                            },
                            exchange_mutation_attempted=True,
                        )
                    except Exception as exc:
                        live_store.halt(
                            "fomc_live_management_exit_uncertain",
                            occurred_at=deadline_time.isoformat(),
                        )
                        result = artifact(
                            "management_state_uncertain",
                            blockers=(
                                "fomc_live_management_exit_uncertain",
                                _safe_error(exc, settings),
                            ),
                            exchange_mutation_attempted=True,
                        )
                    live_store.write_execution(result)
                    return result
                try:
                    management_state, _, _, _ = _plan_management_action(
                        live_store,
                        ledger,
                        parent_batch,
                        event,
                        management_state,
                        purpose=str(policy_decision["purpose"]),
                        replacement_stop_price=replacement_stop_price,
                        partial_quantity=(
                            _float(policy_decision["partial_quantity"])
                            if policy_decision.get("partial_quantity") is not None
                            else None
                        ),
                        started_at=_time_after(str(preflight["created_at"])),
                    )
                    management_state, management_evidence, _ = _continue_management_action(
                        settings,
                        event,
                        live_store,
                        ledger,
                        parent_batch,
                        management_state,
                        exchange=exchange,
                        ccxt_symbol=str(account["resolved_symbol"]),
                        active_stop=matching_stops[0],
                        started_at=_time_after(str(preflight["created_at"])),
                    )
                    current_protection = management_evidence.get(
                        "replacement_stop", current_protection
                    )
                    result = artifact(
                        "protected",
                        reconciliation={
                            "preflight_hash": preflight["preflight_hash"],
                            "management": policy_decision | management_evidence,
                            "management_hash": management_state["management_hash"],
                        },
                        exchange_mutation_attempted=True,
                    )
                except Exception as exc:
                    latest_management = live_store.read_management_state() or management_state
                    latest_pending = latest_management.get("pending_action") or {}
                    if str(latest_pending.get("phase") or "") in {
                        "active_stop_canceled",
                        "submitting_replacement_stop",
                    }:
                        try:
                            replacement_cleanup = _cancel_uncertain_management_replacement_stop(
                                ledger,
                                parent_batch,
                                event,
                                exchange=exchange,
                                ccxt_symbol=str(account["resolved_symbol"]),
                                replacement_stop_client_order_id=str(
                                    latest_pending["replacement_stop_client_order_id"]
                                ),
                                signed_remaining_quantity=signed_quantity,
                                replacement_stop_price=_float(
                                    latest_pending["replacement_stop_price"]
                                ),
                                price_tick=_float(latest_management["price_tick"]),
                                at=_time_after(str(preflight["created_at"])),
                            )
                            flattened, ledger_state = _ledgered_flatten_position(
                                settings,
                                event,
                                live_store,
                                parent_batch,
                                exchange=exchange,
                                ccxt_symbol=str(account["resolved_symbol"]),
                                quantity=abs(signed_quantity),
                                position_side=side,
                                purpose="management-protection-replacement-failure",
                                protective_stop=None,
                                protective_stop_client_order_id=str(
                                    latest_pending["replacement_stop_client_order_id"]
                                ),
                                started_at=_time_after(str(preflight["created_at"])),
                            )
                            live_store.halt(
                                "fomc_live_management_replacement_stop_failed",
                                occurred_at=deadline_time.isoformat(),
                            )
                            result = artifact(
                                "halted_emergency_flattened",
                                blockers=(
                                    "fomc_live_management_replacement_stop_failed",
                                    _safe_error(exc, settings),
                                ),
                                reconciliation={
                                    "replacement_stop_cleanup": replacement_cleanup,
                                    "ledger_state": ledger_state,
                                    "flattened": flattened,
                                },
                                exchange_mutation_attempted=True,
                            )
                        except Exception as flatten_exc:
                            live_store.halt(
                                "fomc_live_management_replacement_stop_uncertain",
                                occurred_at=deadline_time.isoformat(),
                            )
                            result = artifact(
                                "management_state_uncertain",
                                blockers=(
                                    "fomc_live_management_replacement_stop_uncertain",
                                    _safe_error(exc, settings),
                                    _safe_error(flatten_exc, settings),
                                ),
                                exchange_mutation_attempted=True,
                            )
                    else:
                        live_store.halt(
                            "fomc_live_management_action_uncertain",
                            occurred_at=deadline_time.isoformat(),
                        )
                        result = artifact(
                            "management_state_uncertain",
                            blockers=(
                                "fomc_live_management_action_uncertain",
                                _safe_error(exc, settings),
                            ),
                            exchange_mutation_attempted=True,
                        )
                live_store.write_execution(result)
                return result
        if (
            management_state is None
            and execution.get("status") in {"protected", "protected_slippage_halt"}
        ):
            return execution
        result = artifact(
            "protected",
            reconciliation={"preflight_hash": preflight["preflight_hash"]},
        )
        live_store.write_execution(result)
        return result

    should_reduce = (
        exact_position
        and strategy_position_evidence_exact
        and not regular
        and only_owned_stop
        and (deadline_time >= event.force_exit_time or protection_missing)
    )
    if not should_reduce:
        live_store.halt(
            "fomc_live_position_or_protection_changed",
            occurred_at=deadline_time.isoformat(),
        )
        result = artifact(
            "halted_position_state_changed",
            blockers=tuple(diagnostics.get("blockers") or ()),
            reconciliation={"preflight_hash": preflight["preflight_hash"]},
        )
        live_store.write_execution(result)
        return result

    stop = matching_stops[0] if matching_stops else None
    purpose = "force-exit" if deadline_time >= event.force_exit_time else "protection-missing"
    try:
        flattened, ledger_state = _ledgered_flatten_position(
            settings,
            event,
            live_store,
            parent_batch,
            exchange=exchange,
            ccxt_symbol=str(account["resolved_symbol"]),
            quantity=abs(signed_quantity),
            position_side=side,
            purpose=purpose,
            protective_stop=stop,
            started_at=_time_after(str(preflight["created_at"])),
            protective_stop_client_order_id=stop_client_id,
        )
        result = artifact(
            "force_exit_flattened"
            if purpose == "force-exit"
            else "protection_failure_flattened",
            reconciliation={purpose: flattened, "ledger_state": ledger_state},
            exchange_mutation_attempted=True,
        )
    except Exception as exc:
        live_store.halt(
            "fomc_live_reduce_only_exit_uncertain",
            occurred_at=deadline_time.isoformat(),
        )
        result = artifact(
            "management_state_uncertain",
            blockers=("fomc_live_reduce_only_exit_uncertain", _safe_error(exc, settings)),
            exchange_mutation_attempted=True,
        )
    live_store.write_execution(result)
    return result


def _recover_interrupted_fomc_attempt(
    settings: Settings,
    event: FomcEventDefinition,
    live_store: FomcLiveStore,
    readiness: Mapping[str, Any],
    arm: Mapping[str, Any],
    *,
    observed_at: str | dt.datetime,
    exchange: Any,
    state_store: FomcStateStore | None = None,
) -> dict[str, Any]:
    """Never resubmit an interrupted attempt; inspect, flatten if safe, and halt."""

    attempt = live_store.read_attempt()
    scope = readiness.get("scope") or {}
    expected_entry_id = str(scope.get("entry_client_order_id") or "")
    expected_stop_id = str(scope.get("stop_client_order_id") or "")
    if (
        attempt is None
        or not expected_entry_id
        or not expected_stop_id
        or attempt.get("entry_client_order_id") != expected_entry_id
        or attempt.get("stop_client_order_id") != expected_stop_id
        or attempt.get("event_id") != event.event_id
        or attempt.get("arm_id") != arm.get("arm_id")
        or attempt.get("readiness_hash") != readiness.get("readiness_hash")
        or attempt.get("batch_id") != readiness.get("batch_id")
        or attempt.get("plan_hash") != readiness.get("plan_hash")
    ):
        raise FomcLiveError("fomc_live_interrupted_attempt_identity_invalid")
    preflight = build_fomc_live_account_preflight(
        settings,
        event,
        observed_at=observed_at,
        exchange=exchange,
        halt_present=False,
    )
    account = preflight.get("account") or {}
    diagnostics = preflight.get("diagnostics") or {}
    positions = [
        row
        for row in account.get("positions", [])
        if row.get("symbol") == account.get("resolved_symbol")
        and abs(_float(row.get("quantity"))) > 0.0
    ]
    regular = account.get("regular_open_orders") or []
    conditional = account.get("conditional_open_orders") or []
    recovery: dict[str, Any] = {
        "preflight_hash": preflight["preflight_hash"],
        "flat_readback_verified": False,
    }
    status = "halted_uncertain"
    blockers: list[str] = ["fomc_live_interrupted_attempt"]
    mutation_attempted = False

    def prove_flat_entry(post: Mapping[str, Any]) -> dict[str, Any]:
        if state_store is None:
            raise FomcLiveError("fomc_live_interrupted_ledger_context_missing")
        parent_batch = read_decision_batch(
            state_store.batches_root / str(readiness["batch_id"])
        )
        entry_response = _fetch_order_by_client_id(
            exchange,
            event,
            ccxt_symbol=str((post.get("account") or {})["resolved_symbol"]),
            client_order_id=expected_entry_id,
            conditional=False,
        )
        entry_view = _exchange_response_view(entry_response)
        expected_side = "buy" if scope.get("side") == "long" else "sell"
        expected_quantity = abs(_float(scope.get("quantity")))
        if (
            entry_view.get("client_order_id") != expected_entry_id
            or entry_view.get("side") != expected_side
            or entry_view.get("symbol")
            not in {event.symbol, str((post.get("account") or {})["resolved_symbol"])}
        ):
            raise FomcLiveError("fomc_live_interrupted_entry_identity_invalid")
        observed_status = str(entry_view.get("status") or "").lower()
        filled = _float(entry_view.get("filled"))
        ledger = live_store.ledger()
        if observed_status in {"canceled", "cancelled", "rejected", "expired"} and abs(
            filled
        ) <= 1e-12:
            ledger_state = _ledger_flat_without_entry_fill(
                settings,
                event,
                ledger,
                parent_batch,
                preflight=post,
                exchange=exchange,
                entry_view=entry_view,
                observed_at=_time_after(str(post["created_at"])),
            )
            return {
                "entry": entry_view,
                "ledger_state": ledger_state,
                "flat_readback_verified": True,
            }
        if observed_status in {"closed", "filled"} and abs(
            filled - expected_quantity
        ) <= 1e-12:
            entry_view, entry_fills, entry_evidence_hash = _record_recovered_entry_fill(
                ledger,
                parent_batch,
                event,
                exchange=exchange,
                ccxt_symbol=str((post.get("account") or {})["resolved_symbol"]),
                response=entry_response,
            )
            entry_record = entry_view | {
                "fills": list(entry_fills),
                "evidence_hash": entry_evidence_hash,
            }
            reduction_attempt = _existing_reduction_attempt(
                live_store, parent_batch, event
            )
            if reduction_attempt is not None:
                try:
                    reduction_state = ledger.get_order(
                        str(reduction_attempt["client_order_id"])
                    )
                except KeyError:
                    reduction_state = None
                if reduction_state is not None and reduction_state["status"] != "PLANNED":
                    flattened, ledger_state = _ledgered_flatten_position(
                        settings,
                        event,
                        live_store,
                        parent_batch,
                        exchange=exchange,
                        ccxt_symbol=str((post.get("account") or {})["resolved_symbol"]),
                        quantity=expected_quantity,
                        position_side=(
                            "long" if scope.get("side") == "long" else "short"
                        ),
                        purpose=str(reduction_attempt["purpose"]),
                        protective_stop=None,
                        started_at=_time_after(str(post["created_at"])),
                    )
                    return {
                        "entry": entry_record,
                        "reduction": flattened,
                        "ledger_state": ledger_state,
                        "flat_readback_verified": True,
                    }
            native_stop = _ledger_native_stop_flatten(
                settings,
                event,
                ledger,
                parent_batch,
                exchange=exchange,
                ccxt_symbol=str((post.get("account") or {})["resolved_symbol"]),
                stop_client_order_id=expected_stop_id,
                signed_quantity=(
                    expected_quantity if scope.get("side") == "long" else -expected_quantity
                ),
                observed_at=_time_after(str(post["created_at"])),
            )
            return {
                "entry": entry_record,
                "native_stop": native_stop,
                "flat_readback_verified": True,
            }
        raise FomcLiveError("fomc_live_interrupted_flat_entry_not_reconstructed")

    try:
        if diagnostics.get("errors"):
            raise FomcLiveError("fomc_live_interrupted_account_read_incomplete")
        if account.get("account_scope_hash") != scope.get("account_scope_hash"):
            raise FomcLiveError("fomc_live_interrupted_account_scope_changed")
        known_regular = [
            row
            for row in regular
            if row.get("client_order_id") == expected_entry_id
        ]
        unknown_regular = [
            row
            for row in regular
            if row.get("client_order_id") != expected_entry_id
        ]
        known_conditional = [
            row
            for row in conditional
            if row.get("client_order_id") == expected_stop_id
        ]
        unknown_conditional = [
            row
            for row in conditional
            if row.get("client_order_id") != expected_stop_id
        ]
        if unknown_regular or unknown_conditional:
            raise FomcLiveError("fomc_live_interrupted_order_ownership_ambiguous")
        if len(known_regular) > 1 or len(known_conditional) > 1:
            raise FomcLiveError("fomc_live_interrupted_order_identity_ambiguous")
        if known_regular:
            known_entry = known_regular[0]
            if not known_entry.get("id"):
                raise FomcLiveError("fomc_live_interrupted_entry_identity_missing")
            mutation_attempted = True
            response = call_with_time_sync_retry(
                exchange,
                exchange.cancel_order,
                str(known_entry["id"]),
                str(account["resolved_symbol"]),
                retry_attempts=1,
            )
            if not isinstance(response, Mapping):
                raise FomcLiveError("fomc_live_interrupted_entry_cancel_invalid")
            preflight = build_fomc_live_account_preflight(
                settings,
                event,
                observed_at=_time_after(str(preflight["created_at"])),
                exchange=exchange,
                halt_present=False,
            )
            account = preflight.get("account") or {}
            positions = [
                row
                for row in account.get("positions", [])
                if row.get("symbol") == account.get("resolved_symbol")
                and abs(_float(row.get("quantity"))) > 0.0
            ]
            conditional = account.get("conditional_open_orders") or []
            if (preflight.get("diagnostics") or {}).get("errors"):
                raise FomcLiveError("fomc_live_interrupted_account_read_incomplete")
            if account.get("account_scope_hash") != scope.get("account_scope_hash"):
                raise FomcLiveError("fomc_live_interrupted_account_scope_changed")
            if account.get("regular_open_orders"):
                raise FomcLiveError("fomc_live_interrupted_entry_cancel_unverified")
            if any(
                row.get("client_order_id") != expected_stop_id
                for row in conditional
            ):
                raise FomcLiveError("fomc_live_interrupted_order_ownership_ambiguous")
        if len(positions) > 1:
            raise FomcLiveError("fomc_live_interrupted_position_ambiguous")
        if len(account.get("positions", [])) != len(positions):
            raise FomcLiveError("fomc_live_interrupted_account_position_ambiguous")
        if positions:
            quantity = _float(positions[0]["quantity"])
            if quantity == 0.0:
                raise FomcLiveError("fomc_live_interrupted_position_invalid")
            entry_evidence = _fetch_order_by_client_id(
                exchange,
                event,
                ccxt_symbol=str(account["resolved_symbol"]),
                client_order_id=expected_entry_id,
                conditional=False,
            )
            entry_view = _exchange_response_view(entry_evidence)
            expected_side = "buy" if scope.get("side") == "long" else "sell"
            expected_quantity = abs(_float(scope.get("quantity")))
            filled_quantity = _float(entry_view.get("filled"))
            if (
                entry_view.get("client_order_id") != expected_entry_id
                or entry_view.get("side") != expected_side
                or entry_view.get("symbol") not in {event.symbol, str(account["resolved_symbol"])}
                or entry_view.get("status") not in {"closed", "filled", "canceled", "expired"}
                or filled_quantity <= 0.0
                or filled_quantity > expected_quantity + 1e-12
                or abs(abs(quantity) - filled_quantity) > 1e-12
                or quantity * (1.0 if expected_side == "buy" else -1.0) <= 0.0
            ):
                raise FomcLiveError("fomc_live_interrupted_position_not_owned")
            if state_store is None:
                raise FomcLiveError("fomc_live_interrupted_ledger_context_missing")
            parent_batch = read_decision_batch(
                state_store.batches_root / str(readiness["batch_id"])
            )
            _record_recovered_entry_fill(
                live_store.ledger(),
                parent_batch,
                event,
                exchange=exchange,
                ccxt_symbol=str(account["resolved_symbol"]),
                response=entry_evidence,
            )
            stops = [
                row
                for row in conditional
                if row.get("client_order_id") == expected_stop_id
            ]
            if len(stops) > 1 or len(stops) != len(conditional):
                raise FomcLiveError("fomc_live_interrupted_stop_ownership_ambiguous")
            stop = stops[0] if stops else None
            if stop is not None and (
                not _protective_stop_shape_matches(
                    stop,
                    signed_quantity=quantity,
                    stop_price=_float(scope.get("stop_price"), math.nan),
                    price_tick=_float(scope.get("price_tick")),
                )
            ):
                raise FomcLiveError("fomc_live_interrupted_stop_not_owned")
            mutation_attempted = True
            flattened, ledger_state = _ledgered_flatten_position(
                settings,
                event,
                live_store,
                parent_batch,
                exchange=exchange,
                ccxt_symbol=str(account["resolved_symbol"]),
                quantity=abs(quantity),
                position_side="long" if quantity > 0.0 else "short",
                purpose="interrupted-attempt",
                protective_stop=stop,
                started_at=_time_after(str(preflight["created_at"])),
            )
            recovery = flattened | {"ledger_state": ledger_state}
        elif conditional:
            if (
                len(conditional) != 1
                or conditional[0].get("client_order_id") != expected_stop_id
                or not _protective_stop_shape_matches(
                    conditional[0],
                    signed_quantity=(
                        abs(_float(scope.get("quantity")))
                        if scope.get("side") == "long"
                        else -abs(_float(scope.get("quantity")))
                    ),
                    stop_price=_float(scope.get("stop_price"), math.nan),
                    price_tick=_float(scope.get("price_tick")),
                )
            ):
                raise FomcLiveError("fomc_live_interrupted_stop_ownership_ambiguous")
            mutation_attempted = True
            canceled = _cancel_protective_stop(
                exchange,
                event,
                ccxt_symbol=str(account["resolved_symbol"]),
                stop=conditional[0],
            )
            post = build_fomc_live_account_preflight(
                settings,
                event,
                observed_at=_time_after(str(preflight["created_at"])),
                exchange=exchange,
                halt_present=False,
            )
            if (post.get("diagnostics") or {}).get("verdict") != (
                "fomc_live_account_preflight_pass"
            ):
                raise FomcLiveError("fomc_live_interrupted_flat_readback_failed")
            recovery = {
                "canceled_stop": canceled,
                "post_preflight_hash": post["preflight_hash"],
            } | prove_flat_entry(post)
        else:
            verdict = (preflight.get("diagnostics") or {}).get("verdict")
            if verdict != "fomc_live_account_preflight_pass":
                raise FomcLiveError("fomc_live_interrupted_flat_readback_failed")
            recovery |= prove_flat_entry(preflight)
        status = "halted_interrupted_attempt_flat"
    except Exception as exc:
        blockers.append(_safe_error(exc, settings))
    occurred_at = _utc(observed_at).isoformat()
    live_store.halt("fomc_live_interrupted_attempt", occurred_at=occurred_at)
    result = _execution_artifact(
        event,
        readiness,
        arm,
        observed_at=occurred_at,
        status=status,
        blockers=blockers,
        reconciliation={"interrupted_attempt_recovery": recovery},
        exchange_mutation_attempted=mutation_attempted,
    )
    live_store.write_execution(result)
    return result


def prepare_fomc_live_readiness(
    settings: Settings,
    event: FomcEventDefinition,
    state_store: FomcStateStore,
    live_store: FomcLiveStore,
    *,
    observed_at: str | dt.datetime | None = None,
    public_exchange: Any | None = None,
    private_exchange: Any | None = None,
) -> dict[str, Any]:
    """Run the explicit private preflight and freeze a currently armed plan."""

    shadow = run_fomc_shadow_cycle(
        event,
        state_store,
        observed_at=observed_at,
        exchange=public_exchange,
    )
    readiness, _ = _prepare_fomc_live_readiness_from_shadow(
        settings,
        event,
        live_store,
        shadow,
        private_exchange=private_exchange,
    )
    return readiness


def _prepare_fomc_live_readiness_from_shadow(
    settings: Settings,
    event: FomcEventDefinition,
    live_store: FomcLiveStore,
    shadow: Mapping[str, Any],
    *,
    private_exchange: Any | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind a read-only account preflight to one already-collected shadow scan."""

    preflight = build_fomc_live_account_preflight(
        settings,
        event,
        observed_at=str(shadow["observed_at"]),
        exchange=private_exchange,
        halt_present=live_store.halt_path.exists(),
    )
    readiness, _ = build_fomc_live_readiness(event, shadow, preflight)
    live_store.write_readiness(readiness)
    return readiness, preflight


def _auto_cycle_result(
    event: FomcEventDefinition,
    *,
    observed_at: dt.datetime,
    status: str,
    blockers: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "observed_at": observed_at.isoformat(),
        "status": status,
        "blockers": list(dict.fromkeys(str(value) for value in blockers)),
        "exchange_mutation_attempted": False,
    }


def run_fomc_auto_execution_cycle(
    settings: Settings,
    event: FomcEventDefinition,
    state_store: FomcStateStore,
    live_store: FomcLiveStore,
    *,
    observed_at: str | dt.datetime | None = None,
    public_exchange: Any | None = None,
    private_exchange: Any | None = None,
) -> dict[str, Any]:
    """Route one owner-authorized event entry only after all live gates agree.

    The authorization is event/account/policy-bound and consumed before the
    arm is persisted. Incomplete automatic state cannot mint a fresh arm; a
    persisted arm must prove its binding again before it reaches the dispatcher.
    """

    now = max(_utc(observed_at), _utc())
    execution = live_store.read_execution()
    attempt = live_store.read_attempt()
    arm = live_store.read_arm()

    if execution is not None or attempt is not None:
        return run_fomc_live_cycle(
            settings,
            event,
            state_store,
            live_store,
            observed_at=now,
            arm_token=None,
            live_switch_enabled=False,
            live_confirmation=None,
            public_exchange=public_exchange,
            private_exchange=private_exchange,
        )

    try:
        authorization = live_store.read_auto_authorization()
        consumed = live_store.read_auto_authorization_consumption()
        secret = live_store.read_auto_arm_secret()
        readiness = live_store.read_readiness() if arm is not None else None
    except FomcLiveError as exc:
        return _auto_cycle_result(
            event,
            observed_at=now,
            status="auto_state_invalid",
            blockers=(str(exc),),
        )
    if arm is not None:
        blockers = _auto_execution_arm_state_blockers(
            event,
            authorization,
            consumed,
            readiness,
            arm,
            secret,
        )
        if blockers:
            return _auto_cycle_result(
                event,
                observed_at=now,
                status="auto_arm_state_invalid",
                blockers=blockers,
            )
        assert secret is not None
        return run_fomc_live_cycle(
            settings,
            event,
            state_store,
            live_store,
            observed_at=now,
            arm_token=str(secret["arm_token"]),
            live_switch_enabled=True,
            live_confirmation=str(arm["arm_id"]),
            public_exchange=public_exchange,
            private_exchange=private_exchange,
        )

    if authorization is None:
        return _auto_cycle_result(
            event,
            observed_at=now,
            status="auto_disarmed",
            blockers=("fomc_live_auto_authorization_missing",),
        )
    if consumed is not None:
        return _auto_cycle_result(
            event,
            observed_at=now,
            status="auto_authorization_consumed",
            blockers=("fomc_live_auto_authorization_consumed",),
        )
    try:
        validate_fomc_live_auto_authorization(authorization)
    except FomcLiveError as exc:
        return _auto_cycle_result(
            event,
            observed_at=now,
            status="auto_authorization_invalid",
            blockers=(str(exc),),
        )
    if now < event.observation_time:
        return _auto_cycle_result(
            event,
            observed_at=now,
            status="auto_waiting_for_observation",
        )
    if now >= event.entry_cutoff_time:
        return _auto_cycle_result(
            event,
            observed_at=now,
            status="auto_entry_window_closed",
            blockers=("fomc_live_auto_entry_cutoff_reached",),
        )

    shadow = run_fomc_shadow_cycle(
        event,
        state_store,
        observed_at=now,
        exchange=public_exchange,
    )
    if shadow.get("stage") != "ARMED":
        return _auto_cycle_result(
            event,
            observed_at=now,
            status="auto_waiting_for_signal",
            blockers=tuple(str(value) for value in shadow.get("blockers") or ()),
        )
    readiness, _ = _prepare_fomc_live_readiness_from_shadow(
        settings,
        event,
        live_store,
        shadow,
        private_exchange=private_exchange,
    )
    blockers = _auto_execution_authorization_blockers(
        event,
        authorization,
        readiness,
        observed_at=now,
        consumed=None,
    )
    if blockers:
        return _auto_cycle_result(
            event,
            observed_at=now,
            status="auto_authorization_blocked",
            blockers=blockers,
        )
    try:
        token = secrets.token_urlsafe(48)
        arm = build_fomc_live_arm(
            readiness,
            arm_token=token,
            armed_at=now,
            confirmed_readiness_hash=str(readiness["readiness_hash"]),
        )
        live_store.consume_auto_authorization(authorization, arm, consumed_at=now)
        live_store.write_arm(arm)
        live_store.write_auto_arm_secret(arm, arm_token=token)
    except FomcLiveError as exc:
        return _auto_cycle_result(
            event,
            observed_at=now,
            status="auto_authorization_blocked",
            blockers=(str(exc),),
        )
    return run_fomc_live_cycle(
        settings,
        event,
        state_store,
        live_store,
        observed_at=now,
        arm_token=token,
        live_switch_enabled=True,
        live_confirmation=str(arm["arm_id"]),
        public_exchange=public_exchange,
        private_exchange=private_exchange,
    )


def run_fomc_live_cycle(
    settings: Settings,
    event: FomcEventDefinition,
    state_store: FomcStateStore,
    live_store: FomcLiveStore,
    *,
    observed_at: str | dt.datetime | None = None,
    arm_token: str | None,
    live_switch_enabled: bool,
    live_confirmation: str | None,
    public_exchange: Any | None = None,
    private_exchange: Any | None = None,
) -> dict[str, Any]:
    """Run one serialized live cycle without creating authority implicitly."""

    now = max(_utc(observed_at), _utc())
    with live_store.cycle_lock():
        existing = live_store.read_execution()
        if existing and existing.get("status") == "halted_uncertain":
            readiness = live_store.read_readiness()
            arm = live_store.read_arm()
            if readiness is not None and arm is not None and live_store.read_attempt() is not None:
                owned_exchange = private_exchange is None
                client = private_exchange or build_exchange(settings, private=True)
                try:
                    return _recover_interrupted_fomc_attempt(
                        settings,
                        event,
                        live_store,
                        readiness,
                        arm,
                        observed_at=now,
                        exchange=client,
                        state_store=state_store,
                    )
                finally:
                    if owned_exchange:
                        close = getattr(client, "close", None)
                        if callable(close):
                            close()
        if existing and existing.get("status") in {
            "protected",
            "protected_slippage_halt",
            "halted_position_state_changed",
            "management_state_uncertain",
        }:
            owned_exchange = private_exchange is None
            client = private_exchange or build_exchange(settings, private=True)
            try:
                return manage_fomc_live_position(
                    settings,
                    event,
                    live_store,
                    state_store=state_store,
                    observed_at=now,
                    exchange=client,
                )
            finally:
                if owned_exchange:
                    close = getattr(client, "close", None)
                    if callable(close):
                        close()
        if existing is not None:
            return existing

        readiness = live_store.read_readiness()
        arm = live_store.read_arm()
        if readiness is None or arm is None:
            return {
                "event_id": event.event_id,
                "observed_at": now.isoformat(),
                "status": "disarmed",
                "blockers": ["fomc_live_readiness_or_arm_missing"],
                "exchange_mutation_attempted": False,
            }
        attempt = live_store.read_attempt()
        if attempt is not None:
            owned_exchange = private_exchange is None
            client = private_exchange or build_exchange(settings, private=True)
            try:
                return _recover_interrupted_fomc_attempt(
                    settings,
                    event,
                    live_store,
                    readiness,
                    arm,
                    observed_at=now,
                    exchange=client,
                    state_store=state_store,
                )
            finally:
                if owned_exchange:
                    close = getattr(client, "close", None)
                    if callable(close):
                        close()
        shadow = run_fomc_shadow_cycle(
            event,
            state_store,
            observed_at=now,
            exchange=public_exchange,
        )
        consumed = live_store.arm_consumed(str(arm["arm_id"]))
        if not fomc_live_arm_valid(
            arm,
            readiness,
            arm_token=arm_token,
            live_switch_enabled=live_switch_enabled,
            live_confirmation=live_confirmation,
            observed_at=now,
            consumed=consumed,
        ):
            return {
                "event_id": event.event_id,
                "observed_at": now.isoformat(),
                "status": "disarmed",
                "blockers": ["fomc_live_arm_or_switch_invalid"],
                "exchange_mutation_attempted": False,
            }
        owned_exchange = private_exchange is None
        client = private_exchange or build_exchange(settings, private=True)
        try:
            preflight = build_fomc_live_account_preflight(
                settings,
                event,
                observed_at=now,
                exchange=client,
                halt_present=live_store.halt_path.exists(),
            )
            try:
                execution = dispatch_fomc_live_entry(
                    settings,
                    event,
                    state_store,
                    live_store,
                    readiness,
                    arm,
                    shadow,
                    preflight,
                    exchange=client,
                )
            except Exception as exc:
                occurred_at = now.isoformat()
                live_store.halt(
                    "fomc_live_pre_dispatch_interrupted", occurred_at=occurred_at
                )
                execution = _execution_artifact(
                    event,
                    readiness,
                    arm,
                    observed_at=occurred_at,
                    status="halted_pre_dispatch_interrupted",
                    blockers=(_safe_error(exc, settings),),
                    exchange_mutation_attempted=False,
                )
            live_store.write_execution(execution)
            return execution
        finally:
            if owned_exchange:
                close = getattr(client, "close", None)
                if callable(close):
                    close()


__all__ = (
    "FomcLiveError",
    "FomcLiveStore",
    "account_risk_snapshot_from_preflight",
    "build_fomc_live_account_preflight",
    "build_fomc_live_auto_authorization",
    "build_fomc_live_arm",
    "build_fomc_live_readiness",
    "dispatch_fomc_live_entry",
    "fomc_live_arm_valid",
    "manage_fomc_live_position",
    "prepare_fomc_live_readiness",
    "run_fomc_auto_execution_cycle",
    "run_fomc_live_cycle",
    "set_fomc_live_environment_switch",
    "validate_fomc_live_auto_authorization",
    "validate_fomc_live_arm",
    "write_fomc_live_environment",
)
