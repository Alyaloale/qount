"""Point-in-time G0 contract for long-only mapped-equity convergence research."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from qount.artifacts import write_research_json_artifact
from qount.mini_trend.futures_recovery import canonical_hash
from qount.models import utc_now
from qount.governance.event_capacity import equity_mapping_event_capacity
from qount.governance.research import equity_mapping_independence
from qount.settings import Settings


EQUITY_MAPPING_G0_VERSION = "equity_mapping_g0_v0.4"
EQUITY_MAPPING_G0_INPUT_VERSION = "equity_mapping_g0_input_v0.2"
NEW_YORK = ZoneInfo("America/New_York")
_HASH_LENGTH = 64


@dataclass(frozen=True)
class MappedEquityInstrument:
    venue: str
    venue_symbol: str
    venue_base_currency: str
    cash_quote_venue: str
    stablecoin_quote_venue: str
    cash_symbol: str
    product_kind: str
    claim_kind: str
    quote_currency: str
    price_multiplier: float
    price_multiplier_scope: str
    mapping_available_at: str
    mapping_source_hash: str

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not all(
            (
                self.venue,
                self.venue_symbol,
                self.venue_base_currency,
                self.cash_quote_venue,
                self.stablecoin_quote_venue,
                self.cash_symbol,
            )
        ):
            errors.append("instrument_identity_missing")
        if self.product_kind not in {"tokenized_spot", "equity_perpetual"}:
            errors.append("instrument_product_kind_invalid")
        expected_claim = {
            "tokenized_spot": "custodied_claim",
            "equity_perpetual": "synthetic_derivative",
        }.get(self.product_kind)
        if expected_claim is not None and self.claim_kind != expected_claim:
            errors.append("instrument_claim_kind_mismatch")
        if self.quote_currency != "USDT":
            errors.append("instrument_quote_currency_not_usdt")
        if not math.isfinite(self.price_multiplier) or self.price_multiplier <= 0.0:
            errors.append("instrument_price_multiplier_invalid")
        if self.price_multiplier_scope != "mapped_quote_to_one_cash_share":
            errors.append("instrument_price_multiplier_scope_invalid")
        if _timestamp(self.mapping_available_at) is None:
            errors.append("instrument_mapping_available_at_invalid")
        if not _valid_hash(self.mapping_source_hash):
            errors.append("instrument_mapping_source_hash_invalid")
        return tuple(errors)


@dataclass(frozen=True)
class ExecutableQuote:
    venue: str
    symbol: str
    product_kind: str
    base_currency: str
    bid: float
    ask: float
    quote_currency: str
    quote_at: str
    available_at: str
    source_hash: str
    session: str

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_fraction(self) -> float:
        return (self.ask - self.bid) / self.mid if self.mid > 0.0 else math.inf

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not all(
            (
                self.venue,
                self.symbol,
                self.product_kind,
                self.base_currency,
                self.quote_currency,
            )
        ):
            errors.append("quote_identity_missing")
        if not all(math.isfinite(value) for value in (self.bid, self.ask)):
            errors.append("quote_price_non_finite")
        elif self.bid <= 0.0 or self.ask < self.bid:
            errors.append("quote_bid_ask_invalid")
        quote_at = _timestamp(self.quote_at)
        available_at = _timestamp(self.available_at)
        if quote_at is None:
            errors.append("quote_at_invalid")
        if available_at is None:
            errors.append("quote_available_at_invalid")
        if quote_at is not None and available_at is not None and available_at < quote_at:
            errors.append("quote_available_before_quote")
        if not _valid_hash(self.source_hash):
            errors.append("quote_source_hash_invalid")
        return tuple(errors)


@dataclass(frozen=True)
class CorporateActionState:
    cash_symbol: str
    cash_trading_date: str
    status: str
    action_kind: str
    adjustment_factor: float | None
    adjustment_scope: str
    effective_at: str | None
    available_at: str
    source_hash: str

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.status not in {"none", "point_in_time_adjusted", "unknown"}:
            errors.append("corporate_action_status_invalid")
        if self.status == "point_in_time_adjusted":
            if self.action_kind not in {"split", "reverse_split"}:
                errors.append("corporate_action_kind_not_multiplicative")
            if self.adjustment_factor is None or not math.isfinite(self.adjustment_factor):
                errors.append("corporate_action_adjustment_factor_invalid")
            elif self.adjustment_factor <= 0.0:
                errors.append("corporate_action_adjustment_factor_invalid")
            if self.adjustment_scope != "multiply_cash_quote_to_instrument_basis":
                errors.append("corporate_action_adjustment_scope_invalid")
        elif self.adjustment_factor not in {None, 1.0}:
            errors.append("corporate_action_unexpected_adjustment_factor")
        elif self.status == "none" and self.adjustment_scope != "none":
            errors.append("corporate_action_adjustment_scope_invalid")
        elif self.status == "unknown" and self.adjustment_scope != "unknown":
            errors.append("corporate_action_adjustment_scope_invalid")
        if self.status == "none":
            if self.action_kind != "none" or self.effective_at is not None:
                errors.append("corporate_action_none_metadata_invalid")
        elif self.status == "unknown":
            if self.action_kind != "unknown":
                errors.append("corporate_action_unknown_kind_invalid")
        elif _timestamp(self.effective_at or "") is None:
            errors.append("corporate_action_effective_at_invalid")
        if _timestamp(self.available_at) is None:
            errors.append("corporate_action_available_at_invalid")
        if not _valid_hash(self.source_hash):
            errors.append("corporate_action_source_hash_invalid")
        try:
            dt.date.fromisoformat(self.cash_trading_date)
        except ValueError:
            errors.append("corporate_action_cash_date_invalid")
        return tuple(errors)

    @property
    def cash_quote_multiplier(self) -> float | None:
        if self.status == "none":
            return 1.0
        if self.status == "point_in_time_adjusted":
            return self.adjustment_factor
        return None


@dataclass(frozen=True)
class CashSessionState:
    cash_trading_date: str
    is_trading_day: bool
    session_type: str
    suspended: bool
    regular_open_time_local: str
    regular_close_time_local: str | None
    calendar_available_at: str
    calendar_source_hash: str

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        try:
            dt.date.fromisoformat(self.cash_trading_date)
        except ValueError:
            errors.append("cash_session_date_invalid")
        if self.session_type not in {"regular", "half_day", "closed"}:
            errors.append("cash_session_type_invalid")
        if self.is_trading_day == (self.session_type == "closed"):
            errors.append("cash_session_open_state_inconsistent")
        try:
            regular_open = dt.time.fromisoformat(self.regular_open_time_local)
        except (TypeError, ValueError):
            regular_open = None
            errors.append("cash_session_regular_open_invalid")
        if self.session_type == "closed":
            if self.regular_close_time_local is not None:
                errors.append("cash_session_closed_has_close_time")
        else:
            try:
                regular_close = dt.time.fromisoformat(
                    str(self.regular_close_time_local)
                )
            except (TypeError, ValueError):
                regular_close = None
                errors.append("cash_session_regular_close_invalid")
            if (
                regular_open is not None
                and regular_close is not None
                and regular_close <= regular_open
            ):
                errors.append("cash_session_hours_invalid")
            expected_close = dt.time(13, 0) if self.session_type == "half_day" else dt.time(16, 0)
            if regular_close is not None and regular_close != expected_close:
                errors.append("cash_session_close_time_mismatch")
        if regular_open is not None and regular_open != dt.time(9, 30):
            errors.append("cash_session_open_time_mismatch")
        if _timestamp(self.calendar_available_at) is None:
            errors.append("cash_calendar_available_at_invalid")
        if not _valid_hash(self.calendar_source_hash):
            errors.append("cash_calendar_source_hash_invalid")
        return tuple(errors)


@dataclass(frozen=True)
class EquityMappingEventContext:
    closure_kind: str
    is_earnings: bool
    available_at: str
    source_hash: str

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.closure_kind not in {
            "ordinary_overnight",
            "ordinary_weekend",
            "holiday",
        }:
            errors.append("event_context_closure_kind_invalid")
        if _timestamp(self.available_at) is None:
            errors.append("event_context_available_at_invalid")
        if not _valid_hash(self.source_hash):
            errors.append("event_context_source_hash_invalid")
        return tuple(errors)


@dataclass(frozen=True)
class EquityMappingStressScenario:
    scenario_id: str
    stress_loss_fraction: float
    method: str
    included_components: tuple[str, ...]
    observation_end_at: str
    available_at: str
    source_hash: str

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.scenario_id:
            errors.append("stress_scenario_id_missing")
        if (
            not math.isfinite(self.stress_loss_fraction)
            or not 0.0 < self.stress_loss_fraction <= 1.0
        ):
            errors.append("stress_scenario_loss_fraction_invalid")
        if self.method not in {
            "historical_gap_spread_haircut",
            "documented_venue_stress_floor",
        }:
            errors.append("stress_scenario_method_invalid")
        required_components = {
            "mapped_spread",
            "stablecoin_conversion_spread",
            "fees",
            "slippage",
            "gap_tail",
            "market_impact",
        }
        if not required_components.issubset(set(self.included_components)):
            errors.append("stress_scenario_components_incomplete")
        observation_end = _timestamp(self.observation_end_at)
        available_at = _timestamp(self.available_at)
        if observation_end is None:
            errors.append("stress_scenario_observation_end_invalid")
        if available_at is None:
            errors.append("stress_scenario_available_at_invalid")
        if (
            observation_end is not None
            and available_at is not None
            and available_at < observation_end
        ):
            errors.append("stress_scenario_available_before_observations")
        if not _valid_hash(self.source_hash):
            errors.append("stress_scenario_source_hash_invalid")
        return tuple(errors)


@dataclass(frozen=True)
class EquityMappingG0Config:
    decision_time_local: str = "09:25:00"
    reference_window_start_local: str = "09:24:30"
    reference_window_end_local: str = "09:25:00"
    maximum_quote_skew_seconds: float = 5.0
    minimum_independent_cash_dates: int = 30
    maximum_event_stress_loss_fraction: float = 0.0025

    def __post_init__(self) -> None:
        if self.decision_time_local != "09:25:00":
            raise ValueError("Equity Mapping decision time changed")
        if self.reference_window_start_local != "09:24:30":
            raise ValueError("Equity Mapping reference window start changed")
        if self.reference_window_end_local != self.decision_time_local:
            raise ValueError("Equity Mapping reference cannot extend beyond decision")
        if self.maximum_quote_skew_seconds <= 0.0:
            raise ValueError("Equity Mapping quote skew must be positive")
        if self.minimum_independent_cash_dates < 1:
            raise ValueError("Equity Mapping independent-date gate must be positive")
        if self.maximum_event_stress_loss_fraction != 0.0025:
            raise ValueError("Equity Mapping event stress budget changed")

    @property
    def contract_hash(self) -> str:
        return canonical_hash(asdict(self))


def _timestamp(value: str) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(dt.UTC)


def _valid_hash(value: str) -> bool:
    return len(value) == _HASH_LENGTH and all(char in "0123456789abcdef" for char in value)


def _quote_prices_valid(quote: ExecutableQuote) -> bool:
    return (
        math.isfinite(quote.bid)
        and math.isfinite(quote.ask)
        and quote.bid > 0.0
        and quote.ask >= quote.bid
    )


def _decision_bounds(
    cash_date: str, config: EquityMappingG0Config
) -> tuple[dt.datetime, dt.datetime]:
    date_value = dt.date.fromisoformat(cash_date)
    start = dt.datetime.combine(
        date_value,
        dt.time.fromisoformat(config.reference_window_start_local),
        NEW_YORK,
    ).astimezone(dt.UTC)
    decision = dt.datetime.combine(
        date_value,
        dt.time.fromisoformat(config.decision_time_local),
        NEW_YORK,
    ).astimezone(dt.UTC)
    return start, decision


def _event_id(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _economic_event_identity(event: Mapping[str, Any]) -> dict[str, str] | None:
    fields = (
        "venue",
        "venue_symbol",
        "cash_symbol",
        "cash_trading_date",
        "decision_time",
        "closure_kind",
        "contract_hash",
    )
    identity = {name: str(event.get(name, "")) for name in fields}
    if any(not value for value in identity.values()):
        return None
    return identity


def build_equity_mapping_g0_event(
    *,
    instrument: MappedEquityInstrument,
    mapped_quote: ExecutableQuote,
    cash_premarket_quote: ExecutableQuote,
    usdt_usd_quote: ExecutableQuote,
    cash_session: CashSessionState,
    corporate_action: CorporateActionState,
    event_context: EquityMappingEventContext,
    stress_scenario: EquityMappingStressScenario,
    account_equity_usdt: float,
    minimum_notional_usdt: float,
    config: EquityMappingG0Config | None = None,
) -> dict[str, Any]:
    """Build one point-in-time event without computing a future return or PnL."""

    config = config or EquityMappingG0Config()
    reasons = list(instrument.validate())
    quote_rows = (mapped_quote, cash_premarket_quote, usdt_usd_quote)
    for label, quote in zip(("mapped", "cash", "usdt_usd"), quote_rows):
        reasons.extend(f"{label}:{error}" for error in quote.validate())
    reasons.extend(cash_session.validate())
    reasons.extend(corporate_action.validate())
    reasons.extend(event_context.validate())
    reasons.extend(stress_scenario.validate())

    if mapped_quote.venue != instrument.venue:
        reasons.append("mapped_quote_venue_mismatch")
    if mapped_quote.symbol != instrument.venue_symbol:
        reasons.append("mapped_quote_symbol_mismatch")
    if mapped_quote.product_kind != instrument.product_kind:
        reasons.append("mapped_quote_product_kind_mismatch")
    if mapped_quote.base_currency != instrument.venue_base_currency:
        reasons.append("mapped_quote_base_currency_invalid")
    if mapped_quote.quote_currency != "USDT":
        reasons.append("mapped_quote_currency_invalid")
    if mapped_quote.session != "continuous":
        reasons.append("mapped_quote_session_invalid")
    if cash_premarket_quote.symbol != instrument.cash_symbol:
        reasons.append("cash_quote_symbol_mismatch")
    if cash_premarket_quote.venue != instrument.cash_quote_venue:
        reasons.append("cash_quote_venue_mismatch")
    if cash_premarket_quote.product_kind != "cash_equity":
        reasons.append("cash_quote_product_kind_invalid")
    if cash_premarket_quote.base_currency != instrument.cash_symbol:
        reasons.append("cash_quote_base_currency_invalid")
    if cash_premarket_quote.quote_currency != "USD":
        reasons.append("cash_quote_currency_invalid")
    if cash_premarket_quote.session != "premarket":
        reasons.append("cash_quote_not_premarket")
    if (
        usdt_usd_quote.symbol != "USDTUSD"
        or usdt_usd_quote.venue != instrument.stablecoin_quote_venue
        or usdt_usd_quote.base_currency != "USDT"
        or usdt_usd_quote.quote_currency != "USD"
        or usdt_usd_quote.product_kind != "fx_spot"
        or usdt_usd_quote.session != "continuous"
    ):
        reasons.append("stablecoin_quote_identity_invalid")
    if corporate_action.cash_symbol != instrument.cash_symbol:
        reasons.append("corporate_action_symbol_mismatch")
    if corporate_action.cash_trading_date != cash_session.cash_trading_date:
        reasons.append("corporate_action_cash_date_mismatch")
    if corporate_action.status == "unknown":
        reasons.append("corporate_action_not_point_in_time_reconstructable")
    if not cash_session.is_trading_day or cash_session.session_type == "closed":
        reasons.append("cash_session_not_open")
    if cash_session.suspended:
        reasons.append("cash_symbol_suspended")

    start, decision = _decision_bounds(cash_session.cash_trading_date, config)
    mapping_available = _timestamp(instrument.mapping_available_at)
    calendar_available = _timestamp(cash_session.calendar_available_at)
    action_available = _timestamp(corporate_action.available_at)
    action_effective = _timestamp(corporate_action.effective_at or "")
    context_available = _timestamp(event_context.available_at)
    stress_observation_end = _timestamp(stress_scenario.observation_end_at)
    stress_available = _timestamp(stress_scenario.available_at)
    if mapping_available is not None and mapping_available > decision:
        reasons.append("instrument_mapping_not_available_at_decision")
    if calendar_available is not None and calendar_available > decision:
        reasons.append("cash_calendar_not_available_at_decision")
    if action_available is not None and action_available > decision:
        reasons.append("corporate_action_not_available_at_decision")
    if action_effective is not None and action_effective > decision:
        reasons.append("corporate_action_not_effective_at_decision")
    if context_available is not None and context_available > decision:
        reasons.append("event_context_not_available_at_decision")
    if stress_observation_end is not None and stress_observation_end > decision:
        reasons.append("stress_scenario_uses_future_observations")
    if stress_available is not None and stress_available > decision:
        reasons.append("stress_scenario_not_available_at_decision")
    try:
        regular_open = dt.datetime.combine(
            dt.date.fromisoformat(cash_session.cash_trading_date),
            dt.time.fromisoformat(cash_session.regular_open_time_local),
            NEW_YORK,
        ).astimezone(dt.UTC)
    except (TypeError, ValueError):
        regular_open = None
    if regular_open is not None and decision >= regular_open:
        reasons.append("decision_not_before_cash_open")

    quote_times: list[dt.datetime] = []
    for label, quote in zip(("mapped", "cash", "usdt_usd"), quote_rows):
        quote_at = _timestamp(quote.quote_at)
        available_at = _timestamp(quote.available_at)
        if quote_at is None or available_at is None:
            continue
        quote_times.append(quote_at)
        if not start <= quote_at <= decision:
            reasons.append(f"{label}:quote_outside_reference_window")
        if available_at > decision:
            reasons.append(f"{label}:quote_not_available_at_decision")
    if quote_times:
        skew = (max(quote_times) - min(quote_times)).total_seconds()
        if skew > config.maximum_quote_skew_seconds:
            reasons.append("cross_market_quote_skew_exceeded")
    else:
        skew = None

    price_inputs_valid = all(_quote_prices_valid(quote) for quote in quote_rows)
    cash_quote_multiplier = corporate_action.cash_quote_multiplier
    comparable_inputs_valid = (
        price_inputs_valid
        and cash_quote_multiplier is not None
        and math.isfinite(cash_quote_multiplier)
        and cash_quote_multiplier > 0.0
        and math.isfinite(instrument.price_multiplier)
        and instrument.price_multiplier > 0.0
    )
    if comparable_inputs_valid:
        mapped_mid_usd = (
            mapped_quote.mid * usdt_usd_quote.mid * instrument.price_multiplier
        )
        cash_reference_mid_usd = cash_premarket_quote.mid * cash_quote_multiplier
        true_gap = mapped_mid_usd / cash_reference_mid_usd - 1.0
        gap_lower_bound = (
            mapped_quote.bid
            * usdt_usd_quote.bid
            * instrument.price_multiplier
            / (cash_premarket_quote.ask * cash_quote_multiplier)
            - 1.0
        )
        gap_upper_bound = (
            mapped_quote.ask
            * usdt_usd_quote.ask
            * instrument.price_multiplier
            / (cash_premarket_quote.bid * cash_quote_multiplier)
            - 1.0
        )
        if not gap_lower_bound <= true_gap <= gap_upper_bound:
            reasons.append("gap_quote_interval_inconsistent")
        capacity = equity_mapping_event_capacity(
            account_equity_usdt=account_equity_usdt,
            true_gap=gap_upper_bound,
            stress_loss_fraction=stress_scenario.stress_loss_fraction,
            minimum_notional_usdt=minimum_notional_usdt,
            corporate_action_status=corporate_action.status,
        )
        reasons.extend(capacity["reasons"])
    else:
        mapped_mid_usd = None
        cash_reference_mid_usd = None
        true_gap = None
        gap_lower_bound = None
        gap_upper_bound = None
        capacity = {
            "notional_usdt": None,
            "live_trial_eligible": False,
            "reasons": ("capacity_not_evaluated_invalid_comparable_prices",),
        }
        reasons.extend(capacity["reasons"])
    reasons = list(dict.fromkeys(reasons))
    event_evidence = {
        "contract_hash": config.contract_hash,
        "instrument": asdict(instrument),
        "mapped_quote": asdict(mapped_quote),
        "cash_premarket_quote": asdict(cash_premarket_quote),
        "usdt_usd_quote": asdict(usdt_usd_quote),
        "cash_session": asdict(cash_session),
        "corporate_action": asdict(corporate_action),
        "event_context": asdict(event_context),
        "stress_scenario": asdict(stress_scenario),
    }
    economic_identity = {
        "venue": instrument.venue,
        "venue_symbol": instrument.venue_symbol,
        "cash_symbol": instrument.cash_symbol,
        "cash_trading_date": cash_session.cash_trading_date,
        "decision_time": decision.isoformat(),
        "closure_kind": event_context.closure_kind,
        "contract_hash": config.contract_hash,
    }
    identity = {
        **economic_identity,
        "event_id": _event_id(economic_identity),
        "evidence_revision_id": _event_id(event_evidence),
        "instrument_mapping_source_hash": instrument.mapping_source_hash,
        "mapped_source_hash": mapped_quote.source_hash,
        "cash_source_hash": cash_premarket_quote.source_hash,
        "stablecoin_source_hash": usdt_usd_quote.source_hash,
        "calendar_source_hash": cash_session.calendar_source_hash,
        "corporate_action_source_hash": corporate_action.source_hash,
        "event_context_source_hash": event_context.source_hash,
        "stress_scenario_source_hash": stress_scenario.source_hash,
    }
    data_reasons = [
        reason
        for reason in reasons
        if reason
        not in {
            "not_a_negative_gap_long_event",
            "stress_sized_notional_below_exchange_minimum",
        }
    ]
    return {
        "schema_version": EQUITY_MAPPING_G0_VERSION,
        **identity,
        "product_kind": instrument.product_kind,
        "claim_kind": instrument.claim_kind,
        "session_type": cash_session.session_type,
        "closure_kind": event_context.closure_kind,
        "is_earnings": event_context.is_earnings,
        "is_ordinary_weekend": event_context.closure_kind == "ordinary_weekend",
        "is_holiday": event_context.closure_kind == "holiday",
        "mapped_mid_usdt": (
            mapped_quote.mid if _quote_prices_valid(mapped_quote) else None
        ),
        "usdt_usd_mid": (
            usdt_usd_quote.mid if _quote_prices_valid(usdt_usd_quote) else None
        ),
        "mapped_mid_usd": mapped_mid_usd,
        "cash_premarket_mid_usd": (
            cash_premarket_quote.mid
            if _quote_prices_valid(cash_premarket_quote)
            else None
        ),
        "cash_quote_adjustment_factor": cash_quote_multiplier,
        "cash_reference_mid_usd": cash_reference_mid_usd,
        "true_gap": true_gap,
        "gap_lower_bound": gap_lower_bound,
        "gap_upper_bound": gap_upper_bound,
        "mapped_spread_fraction": (
            mapped_quote.spread_fraction
            if _quote_prices_valid(mapped_quote)
            else None
        ),
        "cash_spread_fraction": (
            cash_premarket_quote.spread_fraction
            if _quote_prices_valid(cash_premarket_quote)
            else None
        ),
        "quote_skew_seconds": skew,
        "stress_sized_notional_usdt": capacity["notional_usdt"],
        "stress_scenario_id": stress_scenario.scenario_id,
        "stress_loss_fraction": stress_scenario.stress_loss_fraction,
        "data_contract_valid": not data_reasons,
        "mid_negative_gap_observation": true_gap is not None and true_gap < 0.0,
        "long_negative_gap_candidate": (
            gap_upper_bound is not None and gap_upper_bound < 0.0
        ),
        "research_candidate_eligible": not reasons,
        "stress_capacity_computed": capacity["notional_usdt"] is not None,
        "stress_capacity_eligible": not reasons,
        "minimal_live_trial_eligible": False,
        "shadow_only": bool(reasons),
        "reasons": reasons,
        "future_return_evaluated": False,
        "pnl_evaluated": False,
        "orders_allowed": False,
        "paper_or_live_allowed": False,
        "execution_evidence_present": False,
        "next_required_stage": "post_decision_shadow_execution_quote",
    }


def build_equity_mapping_g0_report(
    events: Sequence[Mapping[str, Any]],
    *,
    config: EquityMappingG0Config | None = None,
) -> dict[str, Any]:
    config = config or EquityMappingG0Config()
    unique_by_id: dict[str, Mapping[str, Any]] = {}
    duplicate_event_ids: list[str] = []
    invalid_event_ids: list[str] = []
    contract_mismatch_event_ids: list[str] = []
    for event in events:
        event_id = str(event.get("event_id", ""))
        economic_identity = _economic_event_identity(event)
        expected_event_id = (
            _event_id(economic_identity) if economic_identity is not None else None
        )
        if not _valid_hash(event_id) or event_id != expected_event_id:
            invalid_event_ids.append(event_id)
            continue
        if str(event.get("contract_hash", "")) != config.contract_hash:
            contract_mismatch_event_ids.append(event_id)
            continue
        if event_id in unique_by_id:
            duplicate_event_ids.append(event_id)
            continue
        unique_by_id[event_id] = event
    unique_events = list(unique_by_id.values())
    valid = [
        event for event in unique_events if bool(event.get("data_contract_valid"))
    ]
    evidence = equity_mapping_independence(valid)
    gates = {
        "events_present": bool(events),
        "all_event_ids_valid": not invalid_event_ids,
        "all_event_contract_hashes_match": not contract_mismatch_event_ids,
        "duplicate_event_ids_absent": not duplicate_event_ids,
        "all_events_data_contract_valid": (
            bool(events) and len(valid) == len(unique_events) == len(events)
        ),
        "independent_cash_dates_at_least_30": (
            evidence["independent_cash_trading_dates"]
            >= config.minimum_independent_cash_dates
        ),
    }
    if (
        not gates["events_present"]
        or not gates["all_event_ids_valid"]
        or not gates["all_event_contract_hashes_match"]
        or not gates["duplicate_event_ids_absent"]
        or not gates["all_events_data_contract_valid"]
    ):
        verdict = "block_equity_mapping_g0_data_contract"
    elif not gates["independent_cash_dates_at_least_30"]:
        verdict = "collect_equity_mapping_independent_dates"
    else:
        verdict = "pass_equity_mapping_g0_contract_only"
    return {
        "schema_version": EQUITY_MAPPING_G0_VERSION,
        "artifact_type": "equity_mapping_g0_contract_audit",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "discovery_or_forward_collection",
            "future_return_evaluated": False,
            "pnl_evaluated": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "contract": {**asdict(config), "contract_hash": config.contract_hash},
        "event_count": len(events),
        "unique_event_count": len(unique_events),
        "duplicate_event_count": len(duplicate_event_ids),
        "duplicate_event_ids": sorted(set(duplicate_event_ids)),
        "invalid_event_id_count": len(invalid_event_ids),
        "invalid_event_ids": sorted(set(invalid_event_ids)),
        "contract_mismatch_event_count": len(contract_mismatch_event_ids),
        "contract_mismatch_event_ids": sorted(set(contract_mismatch_event_ids)),
        "valid_event_count": len(valid),
        "long_negative_gap_candidate_count": sum(
            bool(event.get("long_negative_gap_candidate")) for event in valid
        ),
        "research_candidate_eligible_count": sum(
            bool(event.get("research_candidate_eligible")) for event in valid
        ),
        "independence": evidence,
        "gates": gates,
        "verdict": verdict,
        "events": list(events),
    }


def build_equity_mapping_g0_dataset(
    payload: Mapping[str, Any],
    *,
    verified_raw_collection_manifests: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Parse a structured offline input into a G0 contract audit."""

    if payload.get("schema_version") != EQUITY_MAPPING_G0_INPUT_VERSION:
        raise ValueError("equity_mapping_g0_input_schema_invalid")
    dataset_role = str(payload.get("dataset_role", ""))
    if dataset_role not in {"synthetic_fixture", "point_in_time_collection"}:
        raise ValueError("equity_mapping_g0_dataset_role_invalid")
    raw_config = payload.get("config", {})
    if not isinstance(raw_config, Mapping):
        raise ValueError("equity_mapping_g0_config_not_object")
    config = EquityMappingG0Config(**dict(raw_config))
    raw_events = payload.get("events")
    if not isinstance(raw_events, list):
        raise ValueError("equity_mapping_g0_events_not_list")

    events: list[dict[str, Any]] = []
    for index, raw_event in enumerate(raw_events):
        if not isinstance(raw_event, Mapping):
            raise ValueError(f"equity_mapping_g0_event_not_object:{index}")
        try:
            event = build_equity_mapping_g0_event(
                instrument=MappedEquityInstrument(**dict(raw_event["instrument"])),
                mapped_quote=ExecutableQuote(**dict(raw_event["mapped_quote"])),
                cash_premarket_quote=ExecutableQuote(
                    **dict(raw_event["cash_premarket_quote"])
                ),
                usdt_usd_quote=ExecutableQuote(**dict(raw_event["usdt_usd_quote"])),
                cash_session=CashSessionState(**dict(raw_event["cash_session"])),
                corporate_action=CorporateActionState(
                    **dict(raw_event["corporate_action"])
                ),
                event_context=EquityMappingEventContext(
                    **dict(raw_event["event_context"])
                ),
                stress_scenario=EquityMappingStressScenario(
                    **dict(raw_event["stress_scenario"])
                ),
                account_equity_usdt=float(raw_event["account_equity_usdt"]),
                minimum_notional_usdt=float(raw_event["minimum_notional_usdt"]),
                config=config,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"equity_mapping_g0_event_parse_failed:{index}:{type(exc).__name__}"
            ) from exc
        events.append(event)

    report = build_equity_mapping_g0_report(events, config=config)
    if "raw_collection_manifests" in payload:
        raise ValueError("equity_mapping_g0_embedded_raw_manifests_forbidden")
    raw_manifests = list(verified_raw_collection_manifests)
    raw_lineage_required = dataset_role == "point_in_time_collection"
    manifest_hashes_by_date: dict[str, set[str]] = {}
    invalid_manifest_count = 0
    if raw_lineage_required:
        from qount.mini_trend.equity_mapping_collection import (
            collection_source_hashes,
        )

        for manifest in raw_manifests:
            if not isinstance(manifest, Mapping):
                invalid_manifest_count += 1
                continue
            batch = manifest.get("batch")
            verification = manifest.get("verification")
            if (
                manifest.get("verdict") != "sealed_raw_collection"
                or not isinstance(batch, Mapping)
                or batch.get("dataset_role") != "point_in_time_forward_collection"
                or batch.get("synthetic_fixture") is not False
                or not isinstance(verification, Mapping)
                or verification.get("raw_readback_verified") is not True
            ):
                invalid_manifest_count += 1
                continue
            try:
                hashes = collection_source_hashes((manifest,))
            except ValueError:
                invalid_manifest_count += 1
                continue
            cash_date = str(batch.get("cash_trading_date", ""))
            manifest_hashes_by_date.setdefault(cash_date, set()).update(hashes)

    missing_source_hashes_by_event: dict[str, list[str]] = {}
    source_hash_fields = (
        "instrument_mapping_source_hash",
        "mapped_source_hash",
        "cash_source_hash",
        "stablecoin_source_hash",
        "calendar_source_hash",
        "corporate_action_source_hash",
        "event_context_source_hash",
        "stress_scenario_source_hash",
    )
    if raw_lineage_required:
        for event in events:
            available_hashes = manifest_hashes_by_date.get(
                str(event["cash_trading_date"]), set()
            )
            missing = sorted(
                {
                    str(event[field])
                    for field in source_hash_fields
                    if str(event[field]) not in available_hashes
                }
            )
            if missing:
                missing_source_hashes_by_event[str(event["event_id"])] = missing
    raw_lineage_complete = (
        not raw_lineage_required
        or (
            bool(raw_manifests)
            and invalid_manifest_count == 0
            and not missing_source_hashes_by_event
        )
    )
    report["gates"]["raw_collection_lineage_complete"] = raw_lineage_complete
    report["raw_collection_lineage"] = {
        "required": raw_lineage_required,
        "manifest_count": len(raw_manifests),
        "invalid_manifest_count": invalid_manifest_count,
        "cash_trading_dates": sorted(manifest_hashes_by_date),
        "missing_source_hashes_by_event": missing_source_hashes_by_event,
        "complete": raw_lineage_complete,
    }
    if not raw_lineage_complete:
        report["verdict"] = "block_equity_mapping_g0_raw_lineage"
    report["input"] = {
        "schema_version": EQUITY_MAPPING_G0_INPUT_VERSION,
        "dataset_role": dataset_role,
        "synthetic_fixture": dataset_role == "synthetic_fixture",
        "market_evidence_claimed": raw_lineage_required and raw_lineage_complete,
    }
    return report


def write_equity_mapping_g0_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="equity-mapping-g0",
        path_key="artifact_path",
        default_filename="equity_mapping_g0.json",
        explicit_path=explicit_path,
    )
