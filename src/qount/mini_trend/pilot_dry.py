"""Pure dry-run order planning for the MiniTrend UM pilot."""

from __future__ import annotations

from decimal import Decimal, ROUND_DOWN
from typing import Any, Mapping

from qount.artifacts import write_research_json_artifact
from qount.mini_trend.forward import TOP3
from qount.mini_trend.futures_recovery import selected_um_rules
from qount.mini_trend.live_pilot import LIVE_PILOT_CONTRACT
from qount.models import utc_now
from qount.settings import Settings


PILOT_DRY_PLAN_VERSION = "mini_trend_um_pilot_dry_plan_v0.2"


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _round_down(value: float, step: float) -> float:
    if step <= 0.0:
        return value
    value_dec = Decimal(str(value))
    step_dec = Decimal(str(step))
    units = (value_dec / step_dec).to_integral_value(rounding=ROUND_DOWN)
    return float(units * step_dec)


def build_pilot_dry_plan(
    preflight: Mapping[str, Any],
    desired_weights: Mapping[str, float],
    prices: Mapping[str, float],
    rules_artifact: Mapping[str, Any],
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": PILOT_DRY_PLAN_VERSION,
        "artifact_type": "mini_trend_um_pilot_dry_plan",
        "created_at": utc_now().isoformat(),
        "meta": {
            "dry_run_only": True,
            "private_api_order_attempted": False,
            "orders_allowed": False,
            "live_orders_allowed": False,
        },
        "contract_hash": LIVE_PILOT_CONTRACT.contract_hash,
        "desired_weights": dict(desired_weights),
        "actual_weights": {symbol: 0.0 for symbol in TOP3},
        "would_place_orders": [],
        "blocked_orders": [],
        "diagnostics": {
            "blockers": [],
            "verdict": "blocked_dry_plan",
            "live_orders_allowed": False,
        },
    }
    if preflight.get("contract_hash") != LIVE_PILOT_CONTRACT.contract_hash:
        report["diagnostics"]["blockers"].append("preflight_contract_mismatch")
        return report
    if preflight.get("diagnostics", {}).get("verdict") != "account_preflight_pass":
        report["diagnostics"]["blockers"].append("account_preflight_blocked")
        return report
    if set(desired_weights) != set(TOP3):
        raise ValueError("dry plan desired weights must contain exactly TOP3")
    normalized = {symbol: float(desired_weights[symbol]) for symbol in TOP3}
    if any(value < 0.0 for value in normalized.values()):
        raise ValueError("dry plan cannot create short exposure")
    if sum(normalized.values()) > LIVE_PILOT_CONTRACT.maximum_effective_gross + 1e-12:
        raise ValueError("dry plan desired weights exceed gross one")
    if set(prices) != set(TOP3) or any(float(prices[symbol]) <= 0.0 for symbol in TOP3):
        raise ValueError("dry plan requires positive TOP3 prices")

    rules, rules_hash = selected_um_rules(rules_artifact)
    report["exchange_rules_hash"] = rules_hash
    current_notional = {symbol: 0.0 for symbol in TOP3}
    symbol_aliases = {
        symbol: {symbol, f"{symbol[:-4]}/USDT:USDT"} for symbol in TOP3
    }
    for position in preflight.get("account", {}).get("nonzero_positions", []):
        raw_symbol = str(position.get("symbol") or "")
        matched = next(
            (
                symbol
                for symbol, aliases in symbol_aliases.items()
                if raw_symbol in aliases
            ),
            None,
        )
        if matched is None or str(position.get("side")).lower() != "long":
            report["diagnostics"]["blockers"].append("unexpected_live_position")
            return report
        current_notional[matched] += abs(_float(position.get("notional_usdt")))

    capital = _float(
        preflight.get("evidence", {}).get("available_balance_usdt")
    )
    if not 0.0 < capital <= LIVE_PILOT_CONTRACT.maximum_capital_usdt:
        report["diagnostics"]["blockers"].append("invalid_audited_capital")
        return report
    report["capital_usdt"] = capital
    report["actual_weights"] = {
        symbol: current_notional[symbol] / capital for symbol in TOP3
    }
    for symbol in TOP3:
        target_notional = normalized[symbol] * capital
        delta_notional = target_notional - current_notional[symbol]
        if target_notional > 0.0 and current_notional[symbol] > 0.0:
            denominator = max(target_notional, current_notional[symbol])
            if abs(delta_notional) < LIVE_PILOT_CONTRACT.rebalance_deadband * denominator:
                continue
        if abs(delta_notional) <= 1e-9:
            continue
        rule = rules[symbol]
        price = float(prices[symbol])
        step = _float(rule.get("market_step_size") or rule.get("step_size"))
        quantity = _round_down(abs(delta_notional) / price, step)
        notional = quantity * price
        minimum = max(
            _float(rule.get("min_notional")),
            _float(rule.get("min_qty")) * price,
        ) * 1.05
        intent = {
            "symbol": symbol,
            "side": "buy" if delta_notional > 0.0 else "sell",
            "quantity": quantity,
            "notional_usdt": notional,
            "target_weight": normalized[symbol],
            "reduce_only": delta_notional < 0.0,
            "order_type": "market",
        }
        if quantity <= 0.0 or notional + 1e-12 < minimum:
            report["blocked_orders"].append(
                intent | {"reason": "below_buffered_exchange_minimum"}
            )
            continue
        report["would_place_orders"].append(intent)

    if report["blocked_orders"]:
        report["diagnostics"]["blockers"].append("blocked_order_intents")
    report["diagnostics"]["verdict"] = (
        "dry_plan_ready"
        if not report["diagnostics"]["blockers"]
        else "blocked_dry_plan"
    )
    return report


def write_pilot_dry_plan_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-pilot-dry-plan",
        path_key="artifact_path",
        default_filename="mini_trend_um_pilot_dry_plan.json",
        explicit_path=explicit_path,
    )
