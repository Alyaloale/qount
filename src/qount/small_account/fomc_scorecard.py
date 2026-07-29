"""Immutable, order-free outcome accounting for the FOMC v0.2 shadow run.

The scorecard intentionally models only the frozen entry, original protective
stop, and event force-exit.  It is not a live fill reconstruction, a complete
post-entry management simulation, or promotion evidence.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any, Mapping, Sequence

from qount.contracts import canonical_hash
from qount.contracts import is_sha256
from qount.contracts.trace import aware_datetime
from qount.small_account.event_signal import CompletedCandle
from qount.small_account.fomc_runtime import FomcEventDefinition
from qount.small_account.fomc_runtime import FomcRuntimeError
from qount.small_account.fomc_runtime import FomcSignalScan


FOMC_SHADOW_SCORECARD_SCHEMA_VERSION = 1
FOMC_SHADOW_SCORECARD_ARTIFACT_TYPE = "fomc_v02_shadow_scorecard"
FOMC_SHADOW_OUTCOME_MODEL = "original_stop_or_event_force_exit_v1"
_EPSILON = 1e-12


class FomcShadowScorecardError(ValueError):
    """Raised when immutable shadow evidence cannot support a scorecard."""


def _finite(value: object) -> bool:
    try:
        return not isinstance(value, bool) and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _utc(value: object, *, name: str) -> dt.datetime:
    try:
        return aware_datetime(str(value)).astimezone(dt.timezone.utc)
    except (AttributeError, TypeError, ValueError) as exc:
        raise FomcShadowScorecardError(f"fomc_scorecard_{name}_invalid") from exc


def _mapping(value: object, *, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FomcShadowScorecardError(f"fomc_scorecard_{name}_invalid")
    return value


def _number(value: object, *, name: str, positive: bool = False) -> float:
    if not _finite(value):
        raise FomcShadowScorecardError(f"fomc_scorecard_{name}_invalid")
    number = float(value)
    if positive and number <= 0.0:
        raise FomcShadowScorecardError(f"fomc_scorecard_{name}_invalid")
    return number


def _valid_result(result: Mapping[str, Any], event: FomcEventDefinition) -> None:
    result_hash = result.get("result_hash")
    expected_hash = canonical_hash(
        {key: value for key, value in result.items() if key != "result_hash"}
    )
    if not is_sha256(result_hash) or result_hash != expected_hash:
        raise FomcShadowScorecardError("fomc_scorecard_run_result_hash_invalid")
    result_event = _mapping(result.get("event"), name="run_event")
    if (
        result_event.get("event_id") != event.event_id
        or result_event.get("definition_hash") != event.definition_hash
    ):
        raise FomcShadowScorecardError("fomc_scorecard_run_event_mismatch")
    _utc(result.get("observed_at"), name="run_observed_at")


def _candle_core(candle: CompletedCandle) -> dict[str, object]:
    return {
        "closed_at": candle.closed_at.astimezone(dt.timezone.utc).isoformat(),
        "open": float(candle.open),
        "high": float(candle.high),
        "low": float(candle.low),
        "close": float(candle.close),
        "volume": float(candle.volume),
    }


def _validated_fifteen_minute_candles(
    candles: Sequence[CompletedCandle],
) -> tuple[CompletedCandle, ...]:
    if not isinstance(candles, Sequence) or isinstance(candles, (str, bytes)):
        raise FomcShadowScorecardError("fomc_scorecard_outcome_candles_invalid")
    validated: list[CompletedCandle] = []
    previous: dt.datetime | None = None
    for index, candle in enumerate(candles):
        if not isinstance(candle, CompletedCandle):
            raise FomcShadowScorecardError(
                f"fomc_scorecard_outcome_candle_{index}_invalid"
            )
        if candle.validate() or candle.interval_minutes != 15:
            raise FomcShadowScorecardError(
                f"fomc_scorecard_outcome_candle_{index}_invalid"
            )
        closed_at = candle.closed_at.astimezone(dt.timezone.utc)
        if previous is not None and closed_at <= previous:
            raise FomcShadowScorecardError("fomc_scorecard_outcome_candles_unordered")
        previous = closed_at
        validated.append(candle)
    return tuple(validated)


def _outcome_candles(
    candles: Sequence[CompletedCandle],
    *,
    entry_observed_at: dt.datetime,
    event: FomcEventDefinition,
) -> tuple[CompletedCandle, ...]:
    selected: list[CompletedCandle] = []
    for candle in _validated_fifteen_minute_candles(candles):
        closed_at = candle.closed_at.astimezone(dt.timezone.utc)
        if entry_observed_at < closed_at <= event.force_exit_time:
            selected.append(candle)
    if not selected:
        raise FomcShadowScorecardError("fomc_scorecard_outcome_candles_missing")
    if selected[0].closed_at.astimezone(dt.timezone.utc) > entry_observed_at + dt.timedelta(
        minutes=15
    ):
        raise FomcShadowScorecardError("fomc_scorecard_outcome_opening_gap")
    return tuple(selected)


def _cost_rates(value: Mapping[str, Any]) -> dict[str, float]:
    fields = (
        "entry_fee_rate",
        "exit_fee_rate",
        "entry_slippage_rate",
        "exit_slippage_rate",
        "adverse_funding_rate",
    )
    rates = {
        name: _number(value.get(name), name=f"cost_{name}") for name in fields
    }
    if any(rate < 0.0 or rate >= 1.0 for rate in rates.values()):
        raise FomcShadowScorecardError("fomc_scorecard_cost_rates_invalid")
    return rates


def _net_pnl_per_unit(
    *,
    side: str,
    entry_price: float,
    exit_price: float,
    costs: Mapping[str, float],
) -> float:
    price_pnl = (
        exit_price - entry_price if side == "long" else entry_price - exit_price
    )
    entry_cost = entry_price * (
        costs["entry_fee_rate"] + costs["entry_slippage_rate"]
    )
    exit_cost = exit_price * (
        costs["exit_fee_rate"] + costs["exit_slippage_rate"]
    )
    funding_cost = entry_price * costs["adverse_funding_rate"]
    return price_pnl - entry_cost - exit_cost - funding_cost


def _candidate_from_result(result: Mapping[str, Any]) -> dict[str, Any] | None:
    if result.get("stage") != "ARMED":
        return None
    signal = _mapping(result.get("signal"), name="candidate_signal")
    if signal.get("state") != "ARMED" or signal.get("side") not in {"long", "short"}:
        raise FomcShadowScorecardError("fomc_scorecard_armed_signal_invalid")
    chain = _mapping(result.get("standard_chain"), name="candidate_standard_chain")
    sizing = _mapping(chain.get("sizing"), name="candidate_sizing")
    if sizing.get("allowed") is not True:
        return None
    market = _mapping(result.get("market"), name="candidate_market")
    side = str(signal["side"])
    entry_price = _number(chain.get("entry_price"), name="candidate_entry_price", positive=True)
    stop_price = _number(
        chain.get("effective_stop_price"), name="candidate_stop_price", positive=True
    )
    target_price = _number(
        chain.get("structure_target_price"), name="candidate_target_price", positive=True
    )
    worst_stop_fill_price = _number(
        sizing.get("worst_stop_fill_price"),
        name="candidate_worst_stop_fill_price",
        positive=True,
    )
    risk_per_unit = _number(
        sizing.get("risk_per_unit_usdt"),
        name="candidate_risk_per_unit",
        positive=True,
    )
    quantity = _number(sizing.get("quantity"), name="candidate_quantity", positive=True)
    if side == "long":
        geometry_valid = (
            worst_stop_fill_price < stop_price < entry_price < target_price
        )
    else:
        geometry_valid = (
            target_price < entry_price < stop_price < worst_stop_fill_price
        )
    if not geometry_valid:
        raise FomcShadowScorecardError("fomc_scorecard_candidate_geometry_invalid")
    costs = _cost_rates(_mapping(chain.get("costs"), name="candidate_costs"))
    costs_hash = chain.get("costs_hash")
    if not is_sha256(costs_hash) or costs_hash != canonical_hash(costs):
        raise FomcShadowScorecardError("fomc_scorecard_candidate_costs_hash_invalid")
    stop_gap_rate = _number(chain.get("stop_gap_rate"), name="candidate_stop_gap")
    if stop_gap_rate < 0.0 or stop_gap_rate >= 1.0:
        raise FomcShadowScorecardError("fomc_scorecard_candidate_stop_gap_invalid")
    signal_available_at = _utc(
        signal.get("signal_available_at"), name="candidate_signal_available_at"
    )
    observed_at = _utc(result.get("observed_at"), name="candidate_observed_at")
    if signal_available_at > observed_at:
        raise FomcShadowScorecardError("fomc_scorecard_candidate_time_invalid")
    return {
        "result_hash": str(result["result_hash"]),
        "scan_hash": str(signal.get("scan_hash")),
        "side": side,
        "signal_available_at": signal_available_at,
        "entry_observed_at": observed_at,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "worst_stop_fill_price": worst_stop_fill_price,
        "target_price": target_price,
        "risk_per_unit_usdt": risk_per_unit,
        "quantity": quantity,
        "costs": costs,
        "costs_hash": str(costs_hash),
        "stop_gap_rate": stop_gap_rate,
        "market_observation_hash": str(market.get("observation_hash")),
    }


def _select_candidate(
    results: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any] | None, int]:
    candidates = [
        candidate
        for result in results
        if (candidate := _candidate_from_result(result)) is not None
    ]
    if not candidates:
        return None, 0
    candidates.sort(
        key=lambda value: (
            value["signal_available_at"],
            value["entry_observed_at"],
            value["result_hash"],
        )
    )
    return candidates[0], len(candidates)


def _entry_cutoff_coverage(
    event: FomcEventDefinition,
    results: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, str], int] | None:
    """Return evidence that the saved shadow scan reached the entry cutoff."""

    coverage: list[dict[str, str]] = []
    for result in results:
        observed_at = _utc(result.get("observed_at"), name="run_observed_at")
        if not event.entry_cutoff_time <= observed_at < event.force_exit_time:
            continue
        if result.get("stage") not in {"OBSERVE", "ARMED", "NO_TRADE"}:
            continue
        signal_value = _mapping(
            result.get("signal"), name="entry_cutoff_signal"
        )
        try:
            signal = FomcSignalScan.from_mapping(signal_value)
        except FomcRuntimeError as exc:
            raise FomcShadowScorecardError(
                "fomc_scorecard_entry_cutoff_signal_invalid"
            ) from exc
        signal_evaluated_at = _utc(
            signal.evaluated_at, name="entry_cutoff_signal_evaluated_at"
        )
        if signal.event_id != event.event_id or signal_evaluated_at != observed_at:
            raise FomcShadowScorecardError(
                "fomc_scorecard_entry_cutoff_signal_mismatch"
            )
        coverage.append(
            {
                "result_hash": str(result["result_hash"]),
                "observed_at": observed_at.isoformat(),
                "stage": str(result["stage"]),
                "scan_hash": signal.scan_hash,
            }
        )
    if not coverage:
        return None
    return coverage[-1], len(coverage)


def _score_candidate(
    event: FomcEventDefinition,
    candidate: Mapping[str, Any],
    candles: Sequence[CompletedCandle],
) -> dict[str, Any]:
    side = str(candidate["side"])
    entry_price = float(candidate["entry_price"])
    stop_price = float(candidate["stop_price"])
    worst_stop_fill_price = float(candidate["worst_stop_fill_price"])
    target_price = float(candidate["target_price"])
    risk_per_unit = float(candidate["risk_per_unit_usdt"])
    costs = _cost_rates(_mapping(candidate["costs"], name="candidate_costs"))
    entry_observed_at = candidate["entry_observed_at"]
    if not isinstance(entry_observed_at, dt.datetime):
        raise FomcShadowScorecardError("fomc_scorecard_candidate_time_invalid")
    path = _outcome_candles(
        candles,
        entry_observed_at=entry_observed_at,
        event=event,
    )
    expected_previous = path[0].closed_at.astimezone(dt.timezone.utc)
    if expected_previous > entry_observed_at + dt.timedelta(minutes=15):
        raise FomcShadowScorecardError("fomc_scorecard_outcome_opening_gap")

    favorable_prices = [entry_price]
    adverse_prices = [entry_price]
    target_touched_at: str | None = None
    exit_candle: CompletedCandle | None = None
    evaluated_candle_count = 0
    exit_reason = ""
    exit_price: float | None = None
    for index, candle in enumerate(path):
        evaluated_candle_count = index + 1
        closed_at = candle.closed_at.astimezone(dt.timezone.utc)
        if index:
            expected = expected_previous + dt.timedelta(minutes=15)
            if closed_at != expected:
                raise FomcShadowScorecardError("fomc_scorecard_outcome_candle_gap")
        expected_previous = closed_at
        stop_touched = (
            candle.low <= stop_price + _EPSILON
            if side == "long"
            else candle.high >= stop_price - _EPSILON
        )
        if stop_touched:
            adverse_prices.append(worst_stop_fill_price)
            exit_candle = candle
            exit_reason = "protective_stop_stress_fill"
            exit_price = worst_stop_fill_price
            break
        if side == "long":
            favorable_prices.append(candle.high)
            adverse_prices.append(candle.low)
            target_touched = candle.high >= target_price - _EPSILON
        else:
            favorable_prices.append(candle.low)
            adverse_prices.append(candle.high)
            target_touched = candle.low <= target_price + _EPSILON
        if target_touched and target_touched_at is None:
            target_touched_at = closed_at.isoformat()
        if closed_at == event.force_exit_time:
            exit_candle = candle
            exit_reason = "event_force_exit_mark"
            exit_price = candle.close
            break
    if exit_candle is None or exit_price is None:
        raise FomcShadowScorecardError("fomc_scorecard_force_exit_candle_missing")

    if side == "long":
        mfe_price = max(favorable_prices)
        mae_price = min(adverse_prices)
    else:
        mfe_price = min(favorable_prices)
        mae_price = max(adverse_prices)
    final_net_pnl = _net_pnl_per_unit(
        side=side,
        entry_price=entry_price,
        exit_price=exit_price,
        costs=costs,
    )
    mfe_net_pnl = _net_pnl_per_unit(
        side=side,
        entry_price=entry_price,
        exit_price=mfe_price,
        costs=costs,
    )
    mae_net_pnl = _net_pnl_per_unit(
        side=side,
        entry_price=entry_price,
        exit_price=mae_price,
        costs=costs,
    )
    return {
        "status": "scored_frozen_v02_plan",
        "outcome_model": FOMC_SHADOW_OUTCOME_MODEL,
        "entry_observed_at": entry_observed_at.isoformat(),
        "entry_price": entry_price,
        "stop_price": stop_price,
        "worst_stop_fill_price": worst_stop_fill_price,
        "target_price": target_price,
        "target_touched_at": target_touched_at,
        "exit_reason": exit_reason,
        "exit_observed_at": exit_candle.closed_at.astimezone(dt.timezone.utc).isoformat(),
        "exit_price": exit_price,
        "risk_per_unit_usdt": risk_per_unit,
        "final_net_pnl_per_unit_usdt": final_net_pnl,
        "final_net_r": final_net_pnl / risk_per_unit,
        "mfe_price": mfe_price,
        "mae_price": mae_price,
        "mfe_net_pnl_per_unit_usdt": mfe_net_pnl,
        "mae_net_pnl_per_unit_usdt": mae_net_pnl,
        "mfe_net_r": mfe_net_pnl / risk_per_unit,
        "mae_net_r": mae_net_pnl / risk_per_unit,
        "outcome_candle_count": evaluated_candle_count,
        "available_outcome_candle_count": len(path),
    }


def build_fomc_v02_shadow_scorecard(
    event: FomcEventDefinition,
    *,
    run_results: Sequence[Mapping[str, Any]],
    fifteen_minute_candles: Sequence[CompletedCandle],
    generated_at: str | dt.datetime,
) -> dict[str, Any]:
    """Build one final, no-order scorecard after the event has expired."""

    if not isinstance(event, FomcEventDefinition) or event.validate():
        raise FomcShadowScorecardError("fomc_scorecard_event_invalid")
    created_at = _utc(generated_at, name="generated_at")
    if created_at < event.force_exit_time:
        raise FomcShadowScorecardError("fomc_scorecard_event_not_expired")
    if not isinstance(run_results, Sequence) or isinstance(run_results, (str, bytes)):
        raise FomcShadowScorecardError("fomc_scorecard_run_results_invalid")
    if not run_results:
        raise FomcShadowScorecardError("fomc_scorecard_run_history_missing")

    results = [dict(result) for result in run_results]
    for result in results:
        _valid_result(result, event)
    results.sort(
        key=lambda value: (
            _utc(value["observed_at"], name="run_observed_at"),
            str(value["result_hash"]),
        )
    )
    candidate, candidate_observation_count = _select_candidate(results)
    validated_candles = _validated_fifteen_minute_candles(fifteen_minute_candles)
    outcome_candle_hash = canonical_hash(
        {
            "interval": "15m",
            "candles": [_candle_core(candle) for candle in validated_candles],
        }
    )
    if candidate is None:
        cutoff_coverage = _entry_cutoff_coverage(event, results)
        if cutoff_coverage is None:
            raise FomcShadowScorecardError(
                "fomc_scorecard_entry_cutoff_coverage_missing"
            )
        entry_cutoff_coverage, entry_cutoff_coverage_run_count = cutoff_coverage
        outcome: dict[str, Any] = {
            "status": "no_eligible_v02_shadow_setup",
            "outcome_model": FOMC_SHADOW_OUTCOME_MODEL,
            "final_net_r": None,
            "mfe_net_r": None,
            "mae_net_r": None,
        }
        candidate_evidence = None
    else:
        entry_cutoff_coverage = None
        entry_cutoff_coverage_run_count = 0
        outcome = _score_candidate(event, candidate, validated_candles)
        candidate_evidence = {
            "result_hash": candidate["result_hash"],
            "scan_hash": candidate["scan_hash"],
            "market_observation_hash": candidate["market_observation_hash"],
            "side": candidate["side"],
            "signal_available_at": candidate["signal_available_at"].isoformat(),
            "entry_observed_at": candidate["entry_observed_at"].isoformat(),
            "planned_entry_price": candidate["entry_price"],
            "effective_stop_price": candidate["stop_price"],
            "worst_stop_fill_price": candidate["worst_stop_fill_price"],
            "structure_target_price": candidate["target_price"],
            "risk_per_unit_usdt": candidate["risk_per_unit_usdt"],
            "quantity": candidate["quantity"],
            "costs": candidate["costs"],
            "costs_hash": candidate["costs_hash"],
            "stop_gap_rate": candidate["stop_gap_rate"],
        }
    run_hashes = [str(result["result_hash"]) for result in results]
    core = {
        "schema_version": FOMC_SHADOW_SCORECARD_SCHEMA_VERSION,
        "artifact_type": FOMC_SHADOW_SCORECARD_ARTIFACT_TYPE,
        "event_id": event.event_id,
        "event_definition_hash": event.definition_hash,
        "generated_at": created_at.isoformat(),
        "source": {
            "run_count": len(results),
            "run_result_hashes": run_hashes,
            "run_history_hash": canonical_hash(run_hashes),
            "outcome_candle_hash": outcome_candle_hash,
            "entry_cutoff_coverage": entry_cutoff_coverage,
            "entry_cutoff_coverage_run_count": entry_cutoff_coverage_run_count,
        },
        "strategy": {
            "strategy_id": event.strategy_id,
            "strategy_version": event.strategy_version,
            "candidate_observation_count": candidate_observation_count,
            "candidate": candidate_evidence,
        },
        "outcome": outcome,
        "permissions": {
            "orders_authorized": False,
            "paper_or_live_allowed": False,
            "private_api_used": False,
            "private_api_order_attempted": False,
            "exchange_mutation_attempted": False,
        },
        "promotion": {
            "promotion_evidence": False,
            "paper_or_live_allowed": False,
            "reason": "single_event_shadow_outcome_is_process_evidence_only",
        },
    }
    return core | {"scorecard_hash": canonical_hash(core)}


def validate_fomc_v02_shadow_scorecard(value: Mapping[str, Any]) -> None:
    """Validate an immutable scorecard before the state store accepts it."""

    if not isinstance(value, Mapping):
        raise FomcShadowScorecardError("fomc_scorecard_mapping_invalid")
    core = {key: item for key, item in value.items() if key != "scorecard_hash"}
    if value.get("schema_version") != FOMC_SHADOW_SCORECARD_SCHEMA_VERSION:
        raise FomcShadowScorecardError("fomc_scorecard_schema_invalid")
    if value.get("artifact_type") != FOMC_SHADOW_SCORECARD_ARTIFACT_TYPE:
        raise FomcShadowScorecardError("fomc_scorecard_artifact_type_invalid")
    if not is_sha256(value.get("event_id")) or not is_sha256(
        value.get("event_definition_hash")
    ):
        raise FomcShadowScorecardError("fomc_scorecard_event_invalid")
    if value.get("scorecard_hash") != canonical_hash(core):
        raise FomcShadowScorecardError("fomc_scorecard_hash_invalid")
    permissions = _mapping(value.get("permissions"), name="permissions")
    if any(permissions.get(name) is not False for name in permissions):
        raise FomcShadowScorecardError("fomc_scorecard_permissions_invalid")
    promotion = _mapping(value.get("promotion"), name="promotion")
    if (
        promotion.get("promotion_evidence") is not False
        or promotion.get("paper_or_live_allowed") is not False
    ):
        raise FomcShadowScorecardError("fomc_scorecard_promotion_boundary_invalid")


__all__ = (
    "FOMC_SHADOW_OUTCOME_MODEL",
    "FOMC_SHADOW_SCORECARD_ARTIFACT_TYPE",
    "FOMC_SHADOW_SCORECARD_SCHEMA_VERSION",
    "FomcShadowScorecardError",
    "build_fomc_v02_shadow_scorecard",
    "validate_fomc_v02_shadow_scorecard",
)
