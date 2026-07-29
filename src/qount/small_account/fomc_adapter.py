"""Order-free adapter from a frozen FOMC signal to the standard authority chain."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, replace
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Any, Mapping, Sequence

from qount.contracts import InstrumentId
from qount.contracts import MarketSnapshot
from qount.contracts import OrderPlan
from qount.contracts import PlannedOrder
from qount.contracts import ProductCapability
from qount.contracts import RiskDecision
from qount.contracts import StrategyIntent
from qount.contracts import canonical_hash
from qount.contracts import is_sha256
from qount.contracts import trace_id
from qount.contracts import validate_decision_batch
from qount.contracts.trace import aware_datetime
from qount.persistence import VerifiedDecisionBatch
from qount.persistence import build_decision_batch_manifest
from qount.portfolio import SleeveRiskBudget
from qount.portfolio import allocate_strategy_intents
from qount.portfolio import portfolio_target_from_allocation
from qount.risk import build_portfolio_risk_decision
from qount.small_account.fomc_runtime import FomcEventDefinition
from qount.small_account.fomc_runtime import FomcFreezeSnapshot
from qount.small_account.fomc_runtime import FomcRuntimeError
from qount.small_account.fomc_runtime import FomcSignalScan
from qount.small_account.fomc_runtime import frozen_structure_target
from qount.small_account.risk import AccountGuardDecision
from qount.small_account.risk import AccountRiskSnapshot
from qount.small_account.risk import DEFAULT_SMALL_ACCOUNT_POLICY
from qount.small_account.risk import ExecutionCostRates
from qount.small_account.risk import PositionSizeDecision
from qount.small_account.risk import evaluate_account_guard
from qount.small_account.risk import size_linear_usdt_futures


FOMC_MARKET_OBSERVATION_SCHEMA_VERSION = 2
FOMC_STANDARD_CHAIN_VERSION = 1
DEFAULT_FOMC_COSTS = ExecutionCostRates(
    entry_fee_rate=0.0005,
    exit_fee_rate=0.0005,
    entry_slippage_rate=0.0005,
    exit_slippage_rate=0.0005,
    # Covers two potentially adverse eight-hour funding settlements.
    adverse_funding_rate=0.0006,
)
DEFAULT_FOMC_STOP_GAP_RATE = 0.005

_REASON_SANITIZER = re.compile(r"[^A-Z0-9_.:-]+")


def btc_usdt_perpetual_instrument() -> InstrumentId:
    return InstrumentId.create(
        venue="binance",
        symbol="BTCUSDT",
        asset_class="crypto",
        product_kind="perpetual",
        underlying="BTC",
        price_currency="USD",
        settlement_asset="USDT",
        multiplier=1.0,
        session_calendar="continuous",
    )


def _reason(value: object, *, prefix: str = "FOMC") -> str:
    normalized = _REASON_SANITIZER.sub("_", str(value).upper()).strip("_")
    result = f"{prefix}_{normalized}" if normalized else f"{prefix}_UNKNOWN"
    return result[:96]


def _account_hash(snapshot: AccountRiskSnapshot | None) -> str | None:
    return canonical_hash(asdict(snapshot)) if snapshot is not None else None


@dataclass(frozen=True)
class FomcMarketObservation:
    schema_version: int
    observation_id: str
    symbol: str
    observed_at: str
    data_cutoff: str
    last_price: float
    bid_price: float
    ask_price: float
    mark_price: float
    index_price: float
    funding_rate: float
    price_tick: float
    quantity_step: float
    minimum_quantity: float
    minimum_notional_usdt: float
    exchange_rules_hash: str
    source_hashes: Mapping[str, str]
    observation_hash: str

    @classmethod
    def create(
        cls,
        *,
        symbol: str,
        observed_at: str,
        data_cutoff: str,
        last_price: float,
        bid_price: float,
        ask_price: float,
        mark_price: float,
        index_price: float,
        funding_rate: float,
        price_tick: float,
        quantity_step: float,
        minimum_quantity: float,
        minimum_notional_usdt: float,
        exchange_rules_hash: str,
        source_hashes: Mapping[str, str],
    ) -> "FomcMarketObservation":
        core = {
            "schema_version": FOMC_MARKET_OBSERVATION_SCHEMA_VERSION,
            "symbol": str(symbol).upper(),
            "observed_at": aware_datetime(observed_at).isoformat(),
            "data_cutoff": aware_datetime(data_cutoff).isoformat(),
            "last_price": float(last_price),
            "bid_price": float(bid_price),
            "ask_price": float(ask_price),
            "mark_price": float(mark_price),
            "index_price": float(index_price),
            "funding_rate": float(funding_rate),
            "price_tick": float(price_tick),
            "quantity_step": float(quantity_step),
            "minimum_quantity": float(minimum_quantity),
            "minimum_notional_usdt": float(minimum_notional_usdt),
            "exchange_rules_hash": str(exchange_rules_hash),
            "source_hashes": dict(sorted((str(k), str(v)) for k, v in source_hashes.items())),
        }
        observation_hash = canonical_hash(core)
        observation = cls(
            **core,
            observation_id=trace_id(
                "fomc_market_observation",
                {
                    "symbol": core["symbol"],
                    "observed_at": core["observed_at"],
                    "observation_hash": observation_hash,
                },
            ),
            observation_hash=observation_hash,
        )
        errors = observation.validate()
        if errors:
            raise FomcRuntimeError(
                "fomc_market_observation_invalid:" + ",".join(errors)
            )
        return observation

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "FomcMarketObservation":
        try:
            observation = cls(
                schema_version=int(value["schema_version"]),
                observation_id=str(value["observation_id"]),
                symbol=str(value["symbol"]),
                observed_at=str(value["observed_at"]),
                data_cutoff=str(value["data_cutoff"]),
                last_price=float(value["last_price"]),
                bid_price=float(value["bid_price"]),
                ask_price=float(value["ask_price"]),
                mark_price=float(value["mark_price"]),
                index_price=float(value["index_price"]),
                funding_rate=float(value["funding_rate"]),
                price_tick=float(value["price_tick"]),
                quantity_step=float(value["quantity_step"]),
                minimum_quantity=float(value["minimum_quantity"]),
                minimum_notional_usdt=float(value["minimum_notional_usdt"]),
                exchange_rules_hash=str(value["exchange_rules_hash"]),
                source_hashes=dict(value["source_hashes"]),
                observation_hash=str(value["observation_hash"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise FomcRuntimeError("fomc_market_observation_mapping_invalid") from exc
        errors = observation.validate()
        if errors:
            raise FomcRuntimeError(
                "fomc_market_observation_invalid:" + ",".join(errors)
            )
        return observation

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "symbol": self.symbol,
            "observed_at": self.observed_at,
            "data_cutoff": self.data_cutoff,
            "last_price": self.last_price,
            "bid_price": self.bid_price,
            "ask_price": self.ask_price,
            "mark_price": self.mark_price,
            "index_price": self.index_price,
            "funding_rate": self.funding_rate,
            "price_tick": self.price_tick,
            "quantity_step": self.quantity_step,
            "minimum_quantity": self.minimum_quantity,
            "minimum_notional_usdt": self.minimum_notional_usdt,
            "exchange_rules_hash": self.exchange_rules_hash,
            "source_hashes": dict(self.source_hashes),
        }

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.schema_version != FOMC_MARKET_OBSERVATION_SCHEMA_VERSION:
            errors.append("market_observation_schema_invalid")
        try:
            observed = aware_datetime(self.observed_at)
            cutoff = aware_datetime(self.data_cutoff)
            if cutoff > observed:
                errors.append("market_observation_cutoff_after_observation")
        except (AttributeError, TypeError, ValueError):
            errors.append("market_observation_time_invalid")
        for name in (
            "last_price",
            "bid_price",
            "ask_price",
            "mark_price",
            "index_price",
            "price_tick",
            "quantity_step",
            "minimum_quantity",
        ):
            try:
                value = float(getattr(self, name))
            except (TypeError, ValueError):
                value = math.nan
            if not math.isfinite(value) or value <= 0.0:
                errors.append(f"market_observation_{name}_invalid")
        try:
            funding = float(self.funding_rate)
            minimum_notional = float(self.minimum_notional_usdt)
        except (TypeError, ValueError):
            funding = minimum_notional = math.nan
        if not math.isfinite(funding):
            errors.append("market_observation_funding_rate_invalid")
        if not math.isfinite(minimum_notional) or minimum_notional < 0.0:
            errors.append("market_observation_minimum_notional_invalid")
        if (
            math.isfinite(self.bid_price)
            and math.isfinite(self.ask_price)
            and self.bid_price > self.ask_price
        ):
            errors.append("market_observation_crossed_quote")
        for name in ("observation_id", "exchange_rules_hash", "observation_hash"):
            if not is_sha256(getattr(self, name)):
                errors.append(f"market_observation_{name}_invalid")
        if not self.source_hashes or any(
            not key or not is_sha256(value)
            for key, value in self.source_hashes.items()
        ):
            errors.append("market_observation_source_hashes_invalid")
        expected_hash = canonical_hash(self._core())
        if self.observation_hash != expected_hash:
            errors.append("market_observation_hash_invalid")
        expected_id = trace_id(
            "fomc_market_observation",
            {
                "symbol": self.symbol,
                "observed_at": self.observed_at,
                "observation_hash": expected_hash,
            },
        )
        if self.observation_id != expected_id:
            errors.append("market_observation_id_invalid")
        return tuple(dict.fromkeys(errors))

    def entry_price(self, side: str) -> float:
        if side == "long":
            return self.ask_price
        if side == "short":
            return self.bid_price
        return self.last_price

    def as_dict(self) -> dict[str, Any]:
        return self._core() | {
            "observation_id": self.observation_id,
            "observation_hash": self.observation_hash,
        }


@dataclass(frozen=True)
class FomcStandardChain:
    schema_version: int
    event: FomcEventDefinition
    freeze: FomcFreezeSnapshot
    signal: FomcSignalScan
    market: FomcMarketObservation
    instrument: InstrumentId
    capability: ProductCapability
    entry_price: float | None
    effective_stop_price: float | None
    costs: ExecutionCostRates
    stop_gap_rate: float
    sizing: PositionSizeDecision | None
    structure_target_price: float | None
    account_guard: AccountGuardDecision | None
    account_snapshot_linked: bool
    orders_authorized: bool
    blockers: tuple[str, ...]
    batch: VerifiedDecisionBatch
    chain_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event.event_id,
            "freeze_id": self.freeze.freeze_id,
            "signal_scan_hash": self.signal.scan_hash,
            "market_observation_id": self.market.observation_id,
            "instrument_id": self.instrument.instrument_id,
            "capability_id": self.capability.capability_id,
            "entry_price": self.entry_price,
            "effective_stop_price": self.effective_stop_price,
            "costs": asdict(self.costs),
            "costs_hash": canonical_hash(asdict(self.costs)),
            "stop_gap_rate": self.stop_gap_rate,
            "structure_target_price": self.structure_target_price,
            "sizing": asdict(self.sizing) if self.sizing is not None else None,
            "account_guard": (
                asdict(self.account_guard) if self.account_guard is not None else None
            ),
            "account_snapshot_linked": self.account_snapshot_linked,
            "orders_authorized": self.orders_authorized,
            "blockers": list(self.blockers),
            "standard_chain": {
                "snapshot_id": self.batch.snapshot.snapshot_id,
                "decision_id": self.batch.intents[0].decision_id,
                "portfolio_target_id": self.batch.target.portfolio_target_id,
                "risk_decision_id": self.batch.risk.risk_decision_id,
                "order_plan_id": self.batch.plan.order_plan_id,
                "batch_id": self.batch.manifest.batch_id,
                "manifest_hash": self.batch.manifest.manifest_hash,
                "plan_executable": self.batch.plan.executable,
                "planned_order_count": len(self.batch.plan.orders),
                "orders_authorized": self.batch.manifest.orders_authorized,
            },
            "chain_hash": self.chain_hash,
        }


def _logical_shadow_account() -> AccountRiskSnapshot:
    equity = DEFAULT_SMALL_ACCOUNT_POLICY.initial_equity_usdt
    return AccountRiskSnapshot(
        net_liquidation_equity_usdt=equity,
        high_water_equity_usdt=equity,
        day_start_equity_usdt=equity,
        rolling_24h_start_equity_usdt=equity,
        protective_cycle_verified=False,
    )


def _capability(
    event: FomcEventDefinition,
    market: FomcMarketObservation,
) -> ProductCapability:
    return ProductCapability.create(
        instrument_key=event.instrument_key,
        observed_at=market.observed_at,
        source_hash=market.exchange_rules_hash,
        long_allowed=True,
        short_allowed=True,
        buy_allowed=True,
        sell_allowed=True,
        sell_close_only=False,
        reduce_only_supported=True,
        fractional_supported=True,
        funding_applicable=True,
        order_types=("MARKET", "STOP_MARKET"),
        trading_sessions=("CONTINUOUS",),
    )


def _intent_reason_codes(
    signal: FomcSignalScan,
    *,
    target_available: bool,
    sizing_allowed: bool,
) -> tuple[str, ...]:
    reasons = [
        _reason(f"SIGNAL_{signal.state}"),
        _reason(f"SIDE_{signal.side}"),
    ]
    reasons.extend(_reason(value) for value in signal.reasons)
    reasons.append(
        "FOMC_FROZEN_TARGET_AVAILABLE"
        if target_available
        else "FOMC_FROZEN_TARGET_MISSING"
    )
    reasons.append("FOMC_SIZE_ALLOWED" if sizing_allowed else "FOMC_SIZE_BLOCKED")
    return tuple(dict.fromkeys(reasons))


def _stop_on_tick(value: float, *, side: str, tick: float) -> float:
    if not math.isfinite(value) or value <= 0.0 or not math.isfinite(tick) or tick <= 0.0:
        raise FomcRuntimeError("fomc_stop_tick_input_invalid")
    rounding = ROUND_FLOOR if side == "long" else ROUND_CEILING
    units = (Decimal(str(value)) / Decimal(str(tick))).to_integral_value(
        rounding=rounding
    )
    return float(units * Decimal(str(tick)))


def _blocked_order_plan(
    *,
    risk: RiskDecision,
    snapshot: MarketSnapshot,
    decision_ids: Sequence[str],
    created_at: str,
    current_position_hash: str,
    blockers: Sequence[str],
) -> OrderPlan:
    return OrderPlan.create(
        batch_id=risk.batch_id,
        risk_decision_id=risk.risk_decision_id,
        portfolio_target_id=risk.portfolio_target_id,
        snapshot_id=snapshot.snapshot_id,
        decision_ids=decision_ids,
        created_at=created_at,
        current_position_hash=current_position_hash,
        approved_target=risk.approved_target,
        orders=(),
        expected_positions={symbol: 0.0 for symbol in risk.approved_target},
        reconciliation_tolerance={},
        blockers=tuple(blockers),
        executable=not blockers,
    )


def build_fomc_standard_chain(
    event: FomcEventDefinition,
    freeze: FomcFreezeSnapshot,
    signal: FomcSignalScan,
    market: FomcMarketObservation,
    *,
    account_snapshot: AccountRiskSnapshot | None = None,
    current_position_quantity: float = 0.0,
    orders_authorized: bool = False,
    costs: ExecutionCostRates = DEFAULT_FOMC_COSTS,
    stop_gap_rate: float = DEFAULT_FOMC_STOP_GAP_RATE,
    leverage: float | None = None,
) -> FomcStandardChain:
    """Build a complete signed decision batch without routing any order."""

    if event.validate() or freeze.validate() or market.validate():
        raise FomcRuntimeError("fomc_standard_chain_input_invalid")
    if freeze.event_id != event.event_id or signal.event_id != event.event_id:
        raise FomcRuntimeError("fomc_standard_chain_event_mismatch")
    instrument = btc_usdt_perpetual_instrument()
    if (
        event.instrument_key != instrument.instrument_key
        or event.symbol != instrument.symbol
        or market.symbol != event.symbol
    ):
        raise FomcRuntimeError("fomc_standard_chain_instrument_mismatch")
    capability = _capability(event, market)
    side = signal.side
    entry_price = market.entry_price(side)
    target_price = (
        frozen_structure_target(freeze, side=side, entry_price=entry_price)
        if signal.armed and side in {"long", "short"}
        else None
    )
    effective_stop_price = (
        _stop_on_tick(
            signal.structural_stop_price,
            side=side,
            tick=market.price_tick,
        )
        if signal.armed
        and side in {"long", "short"}
        and signal.structural_stop_price is not None
        else None
    )
    sizing: PositionSizeDecision | None = None
    blockers: list[str] = []
    if signal.armed:
        if effective_stop_price is None:
            blockers.append("FOMC_STRUCTURAL_STOP_MISSING")
        elif target_price is None:
            blockers.append("FOMC_FROZEN_TARGET_MISSING")
        else:
            sizing = size_linear_usdt_futures(
                side=side,
                entry_price=entry_price,
                stop_price=effective_stop_price,
                target_price=target_price,
                stop_gap_rate=stop_gap_rate,
                quantity_step=market.quantity_step,
                minimum_notional_usdt=market.minimum_notional_usdt,
                costs=costs,
                # This event path is always bounded by the first-entry budget.
                # A previously verified protective cycle must not widen a shadow
                # candidate before its separately authorized FOMC entry.
                risk_budget_usdt=DEFAULT_SMALL_ACCOUNT_POLICY.first_live_risk_cap_usdt,
                leverage=leverage,
                protective_cycle_verified=False,
            )
            if (
                sizing.allowed
                and sizing.quantity + 1e-12 < market.minimum_quantity
            ):
                sizing = replace(
                    sizing,
                    allowed=False,
                    reasons=("quantity_below_exchange_minimum",),
                )
            blockers.extend(_reason(value) for value in sizing.reasons)
    sizing_allowed = bool(sizing is not None and sizing.allowed)
    logical_account = account_snapshot or _logical_shadow_account()
    requested_risk = sizing.estimated_stress_loss_usdt if sizing_allowed else 0.0
    account_guard = evaluate_account_guard(
        logical_account,
        requested_new_risk_usdt=requested_risk,
        requested_crypto_beta_direction=side if requested_risk > 0.0 else None,
    )
    if signal.armed and not account_guard.allow_new_risk:
        blockers.extend(_reason(value, prefix="FOMC_ACCOUNT") for value in account_guard.reasons)
    target_weight = 0.0
    if signal.armed and sizing_allowed and account_guard.allow_new_risk:
        target_weight = sizing.notional_usdt / DEFAULT_SMALL_ACCOUNT_POLICY.initial_equity_usdt
        if side == "short":
            target_weight = -target_weight
    account_snapshot_hash = _account_hash(account_snapshot)
    feature_core = {
        "event_id": event.event_id,
        "event_definition_hash": event.definition_hash,
        "freeze_id": freeze.freeze_id,
        "freeze_hash": freeze.freeze_hash,
        "signal_scan_hash": signal.scan_hash,
        "signal_state": signal.state,
        "signal_side": signal.side,
        "structure_target_price": target_price,
        "sizing": asdict(sizing) if sizing is not None else None,
        "account_guard": asdict(account_guard),
        "account_mode": "linked" if account_snapshot is not None else "shadow_assumption",
        "orders_authorized": bool(orders_authorized),
    }
    snapshot = MarketSnapshot.create(
        decision_time=market.observed_at,
        data_cutoff=market.data_cutoff,
        prices={event.instrument_key: entry_price},
        funding={event.instrument_key: market.funding_rate},
        features={"fomc": feature_core},
        exchange_rules_hash=market.exchange_rules_hash,
        account_snapshot_hash=account_snapshot_hash,
        data_quality={
            "complete": True,
            "blockers": (),
            "account_snapshot_linked": account_snapshot is not None,
        },
        source_hashes={
            "event": event.definition_hash,
            "freeze": freeze.freeze_hash,
            "market": market.observation_hash,
            **dict(market.source_hashes),
        },
    )
    evidence_hash = canonical_hash(
        {
            "event": event.definition_hash,
            "freeze": freeze.freeze_hash,
            "signal": signal.scan_hash,
            "market": market.observation_hash,
            "costs": asdict(costs),
        }
    )
    state_hash = canonical_hash(feature_core)
    stress_fraction = (
        sizing.estimated_stress_loss_usdt
        / DEFAULT_SMALL_ACCOUNT_POLICY.initial_equity_usdt
        if sizing_allowed
        else 0.0
    )
    intent = StrategyIntent.create(
        strategy_id=event.strategy_id,
        strategy_version=event.strategy_version,
        snapshot_id=snapshot.snapshot_id,
        decision_time=snapshot.decision_time,
        data_cutoff=snapshot.data_cutoff,
        target_weights={event.instrument_key: target_weight},
        expected_holding_bars=8,
        target_stress_loss_fraction=stress_fraction,
        reason_codes=_intent_reason_codes(
            signal,
            target_available=target_price is not None,
            sizing_allowed=sizing_allowed,
        ),
        evidence_hash=evidence_hash,
        state_hash=state_hash,
    )
    budget = SleeveRiskBudget(
        strategy_id=intent.strategy_id,
        target_stress_loss_fraction=stress_fraction,
        estimated_standalone_stress_loss_fraction=(
            stress_fraction if stress_fraction > 0.0 else 1.0
        ),
    )
    allocation = allocate_strategy_intents(
        (intent,),
        (budget,),
        account_equity_usdt=DEFAULT_SMALL_ACCOUNT_POLICY.initial_equity_usdt,
        allowed_strategy_ids=(intent.strategy_id,),
        minimum_notional_by_symbol={
            event.instrument_key: market.minimum_notional_usdt
        },
        maximum_weight_by_symbol={event.instrument_key: 1.0},
        maximum_portfolio_gross=1.0,
        maximum_positions_per_cluster=1,
        correlation_cluster_by_symbol={event.instrument_key: "crypto_beta"},
    )
    target = portfolio_target_from_allocation((intent,), allocation)
    risk = build_portfolio_risk_decision(
        snapshot,
        target,
        current_positions={event.instrument_key: current_position_quantity},
        account_equity_usdt=DEFAULT_SMALL_ACCOUNT_POLICY.initial_equity_usdt,
        maximum_portfolio_gross=1.0,
        maximum_weight_by_symbol={event.instrument_key: 1.0},
        risk_source_hashes={
            "freeze": freeze.freeze_hash,
            "account_guard": canonical_hash(asdict(account_guard)),
        },
        instruments={event.instrument_key: instrument},
        product_capabilities={event.instrument_key: capability},
    )
    current_position_hash = canonical_hash(
        {event.instrument_key: float(current_position_quantity)}
    )
    plan_blockers = list(dict.fromkeys(blockers))
    can_plan_entry = (
        signal.armed
        and sizing_allowed
        and account_guard.allow_new_risk
        and risk.approved
        and not risk.violations
        and abs(current_position_quantity) <= 1e-12
    )
    if signal.armed and abs(current_position_quantity) > 1e-12:
        plan_blockers.append("FOMC_EXISTING_POSITION_NOT_FLAT")
    if can_plan_entry:
        if account_snapshot is None:
            plan_blockers.append("FOMC_ACCOUNT_SNAPSHOT_NOT_LINKED")
        if not orders_authorized:
            plan_blockers.append("FOMC_MANUAL_ARM_REQUIRED")
        assert sizing is not None
        assert effective_stop_price is not None
        entry_side = "buy" if side == "long" else "sell"
        protective_side = "sell" if side == "long" else "buy"
        orders = (
            PlannedOrder.create(
                batch_id=risk.batch_id,
                decision_ids=target.decision_ids,
                symbol=event.instrument_key,
                side=entry_side,
                quantity=sizing.quantity,
                reduce_only=False,
                phase="increase",
                sequence=1,
                order_type="MARKET",
            ),
            PlannedOrder.create(
                batch_id=risk.batch_id,
                decision_ids=target.decision_ids,
                symbol=event.instrument_key,
                side=protective_side,
                quantity=None,
                reduce_only=True,
                phase="protective",
                sequence=2,
                order_type="STOP_MARKET",
                close_position=True,
                stop_price=effective_stop_price,
            ),
        )
        signed_quantity = sizing.quantity if side == "long" else -sizing.quantity
        plan = OrderPlan.create(
            batch_id=risk.batch_id,
            risk_decision_id=risk.risk_decision_id,
            portfolio_target_id=target.portfolio_target_id,
            snapshot_id=snapshot.snapshot_id,
            decision_ids=target.decision_ids,
            created_at=market.observed_at,
            current_position_hash=current_position_hash,
            approved_target=risk.approved_target,
            orders=orders,
            expected_positions={event.instrument_key: signed_quantity},
            reconciliation_tolerance={event.instrument_key: market.quantity_step},
            blockers=tuple(dict.fromkeys(plan_blockers)),
            executable=not plan_blockers,
        )
    else:
        if signal.armed and not plan_blockers:
            plan_blockers.append("FOMC_ENTRY_PLAN_BLOCKED")
        plan = _blocked_order_plan(
            risk=risk,
            snapshot=snapshot,
            decision_ids=target.decision_ids,
            created_at=market.observed_at,
            current_position_hash=current_position_hash,
            blockers=tuple(dict.fromkeys(plan_blockers)),
        )
    manifest = build_decision_batch_manifest(
        snapshot=snapshot,
        intents=(intent,),
        target=target,
        risk=risk,
        plan=plan,
        created_at=market.observed_at,
    )
    batch = VerifiedDecisionBatch(
        manifest=manifest,
        snapshot=snapshot,
        intents=(intent,),
        target=target,
        risk=risk,
        plan=plan,
    )
    contract_errors = validate_decision_batch(
        snapshot, batch.intents, target, risk, plan
    )
    if contract_errors:
        raise FomcRuntimeError(
            "fomc_standard_chain_invalid:" + ",".join(contract_errors)
        )
    chain_core = {
        "schema_version": FOMC_STANDARD_CHAIN_VERSION,
        "event_id": event.event_id,
        "freeze_id": freeze.freeze_id,
        "signal_scan_hash": signal.scan_hash,
        "market_observation_id": market.observation_id,
        "instrument_id": instrument.instrument_id,
        "capability_id": capability.capability_id,
        "entry_price": entry_price if signal.armed else None,
        "effective_stop_price": effective_stop_price,
        "costs": asdict(costs),
        "costs_hash": canonical_hash(asdict(costs)),
        "stop_gap_rate": stop_gap_rate,
        "structure_target_price": target_price,
        "sizing": asdict(sizing) if sizing is not None else None,
        "account_guard": asdict(account_guard),
        "account_snapshot_linked": account_snapshot is not None,
        "orders_authorized": bool(orders_authorized),
        "blockers": tuple(dict.fromkeys(plan_blockers)),
        "manifest_hash": manifest.manifest_hash,
    }
    return FomcStandardChain(
        schema_version=FOMC_STANDARD_CHAIN_VERSION,
        event=event,
        freeze=freeze,
        signal=signal,
        market=market,
        instrument=instrument,
        capability=capability,
        entry_price=entry_price if signal.armed else None,
        effective_stop_price=effective_stop_price,
        costs=costs,
        stop_gap_rate=stop_gap_rate,
        sizing=sizing,
        structure_target_price=target_price,
        account_guard=account_guard,
        account_snapshot_linked=account_snapshot is not None,
        orders_authorized=bool(orders_authorized),
        blockers=tuple(dict.fromkeys(plan_blockers)),
        batch=batch,
        chain_hash=canonical_hash(chain_core),
    )


__all__ = (
    "DEFAULT_FOMC_COSTS",
    "DEFAULT_FOMC_STOP_GAP_RATE",
    "FOMC_MARKET_OBSERVATION_SCHEMA_VERSION",
    "FOMC_STANDARD_CHAIN_VERSION",
    "FomcMarketObservation",
    "FomcStandardChain",
    "btc_usdt_perpetual_instrument",
    "build_fomc_standard_chain",
)
