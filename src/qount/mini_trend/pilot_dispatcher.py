"""Fail-closed, idempotent dispatcher for the MiniTrend USD-M pilot."""

from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import json
import math
import os
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any, Mapping

from qount.artifacts import write_research_json_artifact
from qount.exchange_utils import (
    build_exchange,
    call_with_time_sync_retry,
    extract_quote_balance,
    resolve_market_symbols,
)
from qount.mini_trend.forward import TOP3
from qount.mini_trend.futures_recovery import canonical_hash, selected_um_rules
from qount.mini_trend.live_pilot import LIVE_PILOT_CONTRACT
from qount.models import utc_now
from qount.settings import Settings


PILOT_DISPATCH_VERSION = "mini_trend_um_pilot_dispatch_v0.1"
PILOT_DISPATCH_SNAPSHOT_VERSION = "mini_trend_um_dispatch_snapshot_v0.1"
PILOT_DISPATCH_JOURNAL_VERSION = "mini_trend_um_dispatch_journal_v0.1"
PILOT_MANUAL_ARM_VERSION = "mini_trend_um_manual_arm_v0.1"
_ZERO_HASH = "0" * 64
_CLIENT_PREFIX = "qmt-"
_CONFIGURED_SYMBOLS = tuple(f"{symbol[:-4]}/USDT" for symbol in TOP3)


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


def _safe_error(exc: Exception, settings: Settings) -> str:
    value = f"{type(exc).__name__}: {exc}"
    for secret in (settings.binance_api_key, settings.binance_api_secret):
        if secret:
            value = value.replace(secret, "[REDACTED]")
    return value[:1000]


def _client_order_id(kind: str, decision_id: str, symbol: str) -> str:
    digest = canonical_hash(
        {"kind": kind, "decision_id": decision_id, "symbol": symbol}
    )[:12]
    return f"qmt-{kind}-{symbol[:-4].lower()}-{digest}"[:36]


def _position_symbol(position: Mapping[str, Any]) -> str:
    info = position.get("info") or {}
    return str(position.get("symbol") or info.get("symbol") or "")


def _position_contracts(position: Mapping[str, Any]) -> float:
    info = position.get("info") or {}
    value = position.get("contracts")
    if value is None:
        value = info.get("positionAmt")
    return abs(_float(value))


def _position_side(position: Mapping[str, Any]) -> str:
    side = str(position.get("side") or "").lower()
    if side in {"long", "short"}:
        return side
    signed = _float((position.get("info") or {}).get("positionAmt"))
    return "short" if signed < 0.0 else "long"


def _order_view(order: Mapping[str, Any], *, ccxt_symbol: str) -> dict[str, Any]:
    info = order.get("info") or {}
    trigger = (
        order.get("stopPrice")
        or order.get("triggerPrice")
        or info.get("stopPrice")
    )
    client_id = (
        order.get("clientOrderId")
        or info.get("clientOrderId")
        or info.get("clientAlgoId")
        or ""
    )
    return {
        "id": str(order.get("id") or info.get("orderId") or info.get("algoId") or ""),
        "client_order_id": str(client_id),
        "symbol": ccxt_symbol,
        "type": str(order.get("type") or info.get("origType") or info.get("type") or ""),
        "side": str(order.get("side") or info.get("side") or "").lower(),
        "trigger_price": _float(trigger) if trigger not in (None, "") else None,
        "reduce_only": bool(
            order.get("reduceOnly")
            or str(info.get("reduceOnly")).lower() == "true"
        ),
        "close_position": bool(
            order.get("closePosition")
            or str(info.get("closePosition")).lower() == "true"
        ),
        "status": str(order.get("status") or info.get("status") or ""),
    }


def _fetch_all_open_orders(exchange: Any) -> list[dict[str, Any]]:
    options = getattr(exchange, "options", None)
    if not isinstance(options, dict):
        return call_with_time_sync_retry(
            exchange, exchange.fetch_open_orders, retry_attempts=2
        )
    warning_key = "warnOnFetchOpenOrdersWithoutSymbol"
    sentinel = object()
    previous = options.get(warning_key, sentinel)
    options[warning_key] = False
    try:
        return call_with_time_sync_retry(
            exchange, exchange.fetch_open_orders, retry_attempts=2
        )
    finally:
        if previous is sentinel:
            options.pop(warning_key, None)
        else:
            options[warning_key] = previous


def fetch_pilot_dispatch_snapshot(
    settings: Settings,
    *,
    exchange: Any | None = None,
) -> dict[str, Any]:
    """Read the current USD-M book, including Binance's separate stop-order book."""

    if not settings.contract_market:
        raise ValueError("MiniTrend dispatcher requires the USD-M futures market")
    client = exchange or build_exchange(settings, private=True)
    report: dict[str, Any] = {
        "schema_version": PILOT_DISPATCH_SNAPSHOT_VERSION,
        "artifact_type": "mini_trend_um_dispatch_account_snapshot",
        "created_at": utc_now().isoformat(),
        "meta": {
            "read_only": True,
            "private_api_order_attempted": False,
            "mutating_account_method_attempted": False,
            "live_orders_allowed": False,
        },
        "contract_hash": LIVE_PILOT_CONTRACT.contract_hash,
        "balance": {},
        "prices": {},
        "positions": [],
        "regular_open_orders": [],
        "conditional_open_orders": [],
        "diagnostics": {
            "errors": {},
            "blockers": [],
            "verdict": "blocked_account_snapshot",
        },
    }
    resolved_by_data: dict[str, str] = {}
    try:
        markets = call_with_time_sync_retry(
            client, client.load_markets, sync_before=True, retry_attempts=2
        )
        resolved = resolve_market_symbols(markets, _CONFIGURED_SYMBOLS, settings)
        resolved_by_data = dict(zip(TOP3, resolved, strict=True))
        report["resolved_symbols"] = resolved_by_data
    except Exception as exc:
        report["diagnostics"]["errors"]["markets"] = _safe_error(exc, settings)
        return _finalize_snapshot(report)

    try:
        balance = call_with_time_sync_retry(client, client.fetch_balance, retry_attempts=2)
        report["balance"] = extract_quote_balance(balance, settings)
    except Exception as exc:
        report["diagnostics"]["errors"]["balance"] = _safe_error(exc, settings)

    try:
        mode = call_with_time_sync_retry(
            client,
            client.fetch_position_mode,
            params={"subType": "linear"},
            retry_attempts=2,
        )
        report["position_mode"] = {"hedged": bool(mode.get("hedged"))}
    except Exception as exc:
        report["diagnostics"]["errors"]["position_mode"] = _safe_error(exc, settings)

    try:
        for data_symbol, ccxt_symbol in resolved_by_data.items():
            ticker = call_with_time_sync_retry(
                client, client.fetch_ticker, ccxt_symbol, retry_attempts=2
            )
            price = _float(
                ticker.get("last")
                or ticker.get("close")
                or ticker.get("bid")
                or ticker.get("ask")
            )
            if price <= 0.0:
                raise ValueError(f"non-positive ticker for {data_symbol}")
            report["prices"][data_symbol] = price
    except Exception as exc:
        report["diagnostics"]["errors"]["prices"] = _safe_error(exc, settings)

    inverse = {value: key for key, value in resolved_by_data.items()}
    try:
        positions = call_with_time_sync_retry(
            client, client.fetch_positions, retry_attempts=2
        )
        for position in positions:
            contracts = _position_contracts(position)
            if contracts <= 0.0:
                continue
            ccxt_symbol = _position_symbol(position)
            data_symbol = inverse.get(ccxt_symbol)
            price = _float(report["prices"].get(data_symbol))
            notional = abs(
                _float(position.get("notional") or (position.get("info") or {}).get("notional"))
            )
            if notional <= 0.0 and price > 0.0:
                notional = contracts * price
            report["positions"].append(
                {
                    "data_symbol": data_symbol,
                    "symbol": ccxt_symbol,
                    "side": _position_side(position),
                    "contracts": contracts,
                    "notional_usdt": notional,
                }
            )
    except Exception as exc:
        report["diagnostics"]["errors"]["positions"] = _safe_error(exc, settings)

    try:
        report["regular_open_orders"] = [
            _order_view(order, ccxt_symbol=str(order.get("symbol") or ""))
            for order in _fetch_all_open_orders(client)
        ]
    except Exception as exc:
        report["diagnostics"]["errors"]["regular_open_orders"] = _safe_error(
            exc, settings
        )

    try:
        seen: set[tuple[str, str]] = set()
        for data_symbol, ccxt_symbol in resolved_by_data.items():
            orders = call_with_time_sync_retry(
                client,
                client.fetch_open_orders,
                ccxt_symbol,
                params={"stop": True},
                retry_attempts=2,
            )
            for order in orders:
                view = _order_view(order, ccxt_symbol=ccxt_symbol)
                key = (view["id"], ccxt_symbol)
                if key in seen:
                    continue
                seen.add(key)
                report["conditional_open_orders"].append(
                    view | {"data_symbol": data_symbol}
                )
    except Exception as exc:
        report["diagnostics"]["errors"]["conditional_open_orders"] = _safe_error(
            exc, settings
        )
    return _finalize_snapshot(report)


def _finalize_snapshot(report: dict[str, Any]) -> dict[str, Any]:
    errors = report["diagnostics"]["errors"]
    blockers = [f"snapshot_{name}_unavailable" for name in sorted(errors)]
    if report.get("position_mode", {}).get("hedged") is not False:
        blockers.append("position_mode_not_oneway")
    if set(report.get("prices", {})) != set(TOP3):
        blockers.append("top3_prices_incomplete")
    balance = report.get("balance") or {}
    if _float(balance.get("margin_balance")) <= 0.0:
        blockers.append("margin_balance_unavailable")
    core = {
        "contract_hash": report["contract_hash"],
        "balance": report.get("balance"),
        "prices": report.get("prices"),
        "positions": report.get("positions"),
        "regular_open_orders": report.get("regular_open_orders"),
        "conditional_open_orders": report.get("conditional_open_orders"),
        "position_mode": report.get("position_mode"),
        "resolved_symbols": report.get("resolved_symbols"),
    }
    report["snapshot_hash"] = canonical_hash(core)
    report["diagnostics"]["blockers"] = list(dict.fromkeys(blockers))
    report["diagnostics"]["verdict"] = (
        "account_snapshot_pass" if not blockers else "blocked_account_snapshot"
    )
    return report


def _readiness_hash_valid(readiness: Mapping[str, Any]) -> bool:
    contract = readiness.get("contract") or {}
    raw_request = readiness.get("request") or {}
    signed_request = {
        name: raw_request.get(name)
        for name in (
            "owner_requested_one_month_live",
            "capital_usdt",
            "start_date",
            "duration_days",
        )
    }
    expected = canonical_hash(
        {
            "contract_hash": contract.get("contract_hash"),
            "request": signed_request,
            "evidence": readiness.get("evidence") or {},
            "gates": readiness.get("gates") or {},
        }
    )
    return readiness.get("readiness_hash") == expected


def _manual_arm_valid(
    arm: Mapping[str, Any] | None,
    readiness: Mapping[str, Any],
    source_hashes: Mapping[str, str],
    *,
    arm_token: str | None,
    live_switch_enabled: bool,
    live_confirmation: str | None,
) -> bool:
    if not arm or not arm_token or not live_switch_enabled:
        return False
    token_hash = hashlib.sha256(arm_token.encode("utf-8")).hexdigest()
    return all(
        (
            arm.get("schema_version") == PILOT_MANUAL_ARM_VERSION,
            arm.get("status") == "armed",
            arm.get("contract_hash") == LIVE_PILOT_CONTRACT.contract_hash,
            arm.get("readiness_hash") == readiness.get("readiness_hash"),
            arm.get("readiness_artifact_sha256") == source_hashes.get("readiness"),
            arm.get("arm_token_sha256") == token_hash,
            live_confirmation == arm.get("arm_id"),
        )
    )


def build_manual_arm(
    readiness: Mapping[str, Any],
    *,
    readiness_artifact_sha256: str,
    confirmed_readiness_hash: str,
    arm_token: str,
) -> dict[str, Any]:
    """Build the separate final-arm artifact after every readiness gate passes."""

    if readiness.get("diagnostics", {}).get("verdict") != "ready_for_manual_final_arm":
        raise ValueError("readiness is not ready for manual final arm")
    if not _readiness_hash_valid(readiness):
        raise ValueError("readiness hash is invalid")
    readiness_hash = str(readiness.get("readiness_hash") or "")
    if confirmed_readiness_hash != readiness_hash:
        raise ValueError("confirmed readiness hash does not match")
    if len(arm_token) < 16:
        raise ValueError("manual arm token must contain at least 16 characters")
    request = readiness.get("request") or {}
    created_at = utc_now().isoformat()
    token_hash = hashlib.sha256(arm_token.encode("utf-8")).hexdigest()
    arm_id = "qmt-arm-" + canonical_hash(
        {
            "readiness_hash": readiness_hash,
            "readiness_artifact_sha256": readiness_artifact_sha256,
            "created_at": created_at,
        }
    )[:20]
    return {
        "schema_version": PILOT_MANUAL_ARM_VERSION,
        "artifact_type": "mini_trend_um_manual_final_arm",
        "created_at": created_at,
        "meta": {
            "manual_final_arm": True,
            "private_api_order_attempted": False,
            "mutating_account_method_attempted": False,
            "live_orders_allowed_without_runtime_switch": False,
        },
        "status": "armed",
        "arm_id": arm_id,
        "contract_hash": LIVE_PILOT_CONTRACT.contract_hash,
        "readiness_hash": readiness_hash,
        "readiness_artifact_sha256": readiness_artifact_sha256,
        "arm_token_sha256": token_hash,
        "capital_usdt": _float(request.get("capital_usdt")),
        "start_date": request.get("start_date"),
        "end_date_exclusive": request.get("end_date_exclusive"),
        "required_runtime": {
            "mode": "live",
            "enable_env": "QOUNT_MINI_TREND_LIVE_ENABLE=true",
            "confirmation_env_value": arm_id,
            "arm_token_required": True,
            "current_reconciliation_required": True,
        },
    }


def _critical_preflight_valid(preflight: Mapping[str, Any]) -> bool:
    meta = preflight.get("meta") or {}
    evidence = preflight.get("evidence") or {}
    required = (
        "configured_exchange_route_ok",
        "public_api_ok",
        "credentials_ok",
        "api_key_reading_enabled",
        "api_key_withdrawal_disabled",
        "api_key_futures_enabled",
        "api_key_ip_restricted",
        "account_balance_audit_complete",
        "position_mode_oneway",
        "position_audit_complete",
        "open_order_audit_complete",
        "isolated_one_x_verified",
    )
    return (
        bool(meta.get("read_only"))
        and not bool(meta.get("private_api_order_attempted"))
        and not bool(meta.get("mutating_account_method_attempted"))
        and not bool(meta.get("live_orders_allowed"))
        and all(bool(evidence.get(name)) for name in required)
        and evidence.get("unmanaged_position_count") == 0
    )


def _snapshot_hash_valid(snapshot: Mapping[str, Any]) -> bool:
    core = {
        "contract_hash": snapshot.get("contract_hash"),
        "balance": snapshot.get("balance"),
        "prices": snapshot.get("prices"),
        "positions": snapshot.get("positions"),
        "regular_open_orders": snapshot.get("regular_open_orders"),
        "conditional_open_orders": snapshot.get("conditional_open_orders"),
        "position_mode": snapshot.get("position_mode"),
        "resolved_symbols": snapshot.get("resolved_symbols"),
    }
    return snapshot.get("snapshot_hash") == canonical_hash(core)


def _artifact_is_order_free(payload: Mapping[str, Any]) -> bool:
    meta = payload.get("meta") or {}
    return not any(
        bool(meta.get(name))
        for name in (
            "orders_allowed",
            "live_orders_allowed",
            "private_api_order_attempted",
            "mutating_account_method_attempted",
        )
    )


def build_pilot_dispatch_plan(
    preflight: Mapping[str, Any],
    projection: Mapping[str, Any],
    readiness: Mapping[str, Any],
    rules_artifact: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    *,
    mode: str = "dry",
    source_hashes: Mapping[str, str] | None = None,
    arm: Mapping[str, Any] | None = None,
    arm_token: str | None = None,
    live_switch_enabled: bool = False,
    live_confirmation: str | None = None,
    journal_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate current sources and build deterministic market/stop intents."""

    if mode not in {"dry", "live"}:
        raise ValueError("dispatcher mode must be dry or live")
    sources = dict(source_hashes or {})
    summary = dict(journal_summary or {})
    report: dict[str, Any] = {
        "schema_version": PILOT_DISPATCH_VERSION,
        "artifact_type": "mini_trend_um_pilot_dispatch",
        "created_at": utc_now().isoformat(),
        "meta": {
            "mode": mode,
            "private_api_order_attempted": False,
            "mutating_account_method_attempted": False,
            "orders_allowed": False,
            "live_orders_allowed": False,
        },
        "contract_hash": LIVE_PILOT_CONTRACT.contract_hash,
        "readiness_hash": readiness.get("readiness_hash"),
        "source_hashes": sources,
        "snapshot_hash": snapshot.get("snapshot_hash"),
        "decision": None,
        "capital_usdt": None,
        "desired_weights": {symbol: 0.0 for symbol in TOP3},
        "actual_weights": {symbol: 0.0 for symbol in TOP3},
        "market_orders": [],
        "stop_cancels": [],
        "stop_orders": [],
        "retained_stops": [],
        "risk_flags": [],
        "diagnostics": {
            "blockers": [],
            "verdict": "blocked_dispatch",
            "dry_evidence_valid": False,
            "live_authorized": False,
        },
    }
    blockers: list[str] = report["diagnostics"]["blockers"]

    required_sources = {"preflight", "projection", "readiness", "exchange_rules"}
    if not required_sources.issubset(
        {name for name, value in sources.items() if str(value)}
    ):
        blockers.append("required_source_hashes_missing")

    if preflight.get("artifact_type") != "mini_trend_um_pilot_account_preflight":
        blockers.append("invalid_preflight_artifact")
    if projection.get("artifact_type") != "mini_trend_um_pilot_latest_projection":
        blockers.append("invalid_projection_artifact")
    if readiness.get("artifact_type") != "mini_trend_um_live_pilot_readiness":
        blockers.append("invalid_readiness_artifact")
    if snapshot.get("artifact_type") != "mini_trend_um_dispatch_account_snapshot":
        blockers.append("invalid_account_snapshot")
    if not all(
        _artifact_is_order_free(payload)
        for payload in (preflight, projection, readiness, snapshot)
    ):
        blockers.append("order_capable_source_artifact")
    contract_hashes = {
        preflight.get("contract_hash"),
        (projection.get("contract") or {}).get("live_pilot_contract_hash"),
        (readiness.get("contract") or {}).get("contract_hash"),
        snapshot.get("contract_hash"),
    }
    if contract_hashes != {LIVE_PILOT_CONTRACT.contract_hash}:
        blockers.append("contract_hash_mismatch")
    if not _readiness_hash_valid(readiness):
        blockers.append("readiness_hash_invalid")
    runtime_preflight = (
        (readiness.get("runtime_sources") or {}).get("preflight") or {}
    )
    if runtime_preflight.get("sha256") != sources.get("preflight"):
        blockers.append("readiness_preflight_source_mismatch")
    if not _critical_preflight_valid(preflight):
        blockers.append("critical_account_preflight_blocked")
    if snapshot.get("diagnostics", {}).get("verdict") != "account_snapshot_pass":
        blockers.append("current_account_snapshot_blocked")
    if not _snapshot_hash_valid(snapshot):
        blockers.append("account_snapshot_hash_invalid")

    decision = projection.get("decision")
    if not isinstance(decision, Mapping):
        blockers.append("latest_completed_decision_unavailable")
        report["diagnostics"]["verdict"] = "await_dispatch_decision"
        return _finalize_plan(report)
    report["decision"] = dict(decision)
    decision_id = str(decision.get("decision_id") or "")
    if not decision_id:
        blockers.append("decision_id_missing")
    else:
        decision_core = {
            key: value for key, value in decision.items() if key != "decision_id"
        }
        expected_decision_id = canonical_hash(
            {
                "live_pilot_contract_hash": LIVE_PILOT_CONTRACT.contract_hash,
                "decision": decision_core,
            }
        )
        if decision_id != expected_decision_id:
            blockers.append("decision_id_invalid")
    execution_state = decision.get("execution_state") or {}
    if decision.get("execution_state_hash") != canonical_hash(execution_state):
        blockers.append("execution_state_hash_invalid")
    rules, rules_hash = selected_um_rules(rules_artifact)
    if decision.get("exchange_rules_hash") != rules_hash:
        blockers.append("projection_exchange_rules_mismatch")

    desired_raw = decision.get("desired_weights") or {}
    if set(desired_raw) != set(TOP3):
        blockers.append("desired_weights_schema_mismatch")
        return _finalize_plan(report)
    desired = {symbol: _float(desired_raw[symbol]) for symbol in TOP3}
    if any(value < 0.0 or not math.isfinite(value) for value in desired.values()):
        blockers.append("invalid_or_short_target")
    if sum(desired.values()) > LIVE_PILOT_CONTRACT.maximum_effective_gross + 1e-12:
        blockers.append("target_gross_above_one")

    request = readiness.get("request") or {}
    capital = _float(request.get("capital_usdt"))
    if mode == "live" and arm:
        capital = _float(arm.get("capital_usdt"))
    if not (
        LIVE_PILOT_CONTRACT.minimum_capital_usdt
        <= capital
        <= LIVE_PILOT_CONTRACT.maximum_capital_usdt
    ):
        blockers.append("invalid_dispatch_capital")
    report["capital_usdt"] = capital
    if abs(_float((projection.get("contract") or {}).get("capital_usdt")) - capital) > 1e-6:
        blockers.append("projection_capital_mismatch")

    regular_orders = snapshot.get("regular_open_orders") or []
    if regular_orders:
        blockers.append("unresolved_regular_open_orders")
    conditional = snapshot.get("conditional_open_orders") or []
    managed_stops: dict[str, dict[str, Any]] = {}
    for order in conditional:
        symbol = order.get("data_symbol")
        managed = (
            symbol in TOP3
            and str(order.get("client_order_id") or "").startswith("qmt-s-")
            and bool(order.get("close_position") or order.get("reduce_only"))
            and str(order.get("side") or "").lower() == "sell"
        )
        if not managed or symbol in managed_stops:
            blockers.append("unmanaged_or_duplicate_conditional_order")
            continue
        managed_stops[str(symbol)] = dict(order)

    positions = {symbol: 0.0 for symbol in TOP3}
    for position in snapshot.get("positions") or []:
        symbol = position.get("data_symbol")
        if symbol not in TOP3 or str(position.get("side")).lower() != "long":
            blockers.append("unmanaged_or_short_position")
            continue
        positions[str(symbol)] += _float(position.get("contracts"))

    prices = snapshot.get("prices") or {}
    if set(prices) != set(TOP3) or any(_float(prices.get(s)) <= 0.0 for s in TOP3):
        blockers.append("current_prices_invalid")
        return _finalize_plan(report)
    margin_balance = _float((snapshot.get("balance") or {}).get("margin_balance"))
    peak = max(_float(summary.get("peak_margin_balance_usdt")), capital)
    drawdown = 0.0 if peak <= 0.0 else max(0.0, 1.0 - margin_balance / peak)
    report["account_equity"] = {
        "margin_balance_usdt": margin_balance,
        "peak_margin_balance_usdt": peak,
        "drawdown_pct": drawdown * 100.0,
    }
    halt_after_dispatch = drawdown >= (
        LIVE_PILOT_CONTRACT.maximum_pilot_drawdown_pct / 100.0
    )
    if halt_after_dispatch:
        desired = {symbol: 0.0 for symbol in TOP3}
        report["risk_flags"].append("pilot_drawdown_flatten_then_halt")
    report["halt_after_dispatch"] = halt_after_dispatch

    protective = decision.get("protective_stop_prices") or {}
    for symbol in TOP3:
        if desired[symbol] <= 0.0:
            continue
        stop = _float(protective.get(symbol))
        if stop <= 0.0:
            blockers.append(f"{symbol}:missing_protective_stop")
        elif _float(prices[symbol]) <= stop:
            desired[symbol] = 0.0
            report["risk_flags"].append(f"{symbol}:price_below_protective_stop")
    report["desired_weights"] = desired
    report["actual_weights"] = {
        symbol: positions[symbol] * _float(prices[symbol]) / max(capital, 1e-12)
        for symbol in TOP3
    }

    predicted = dict(positions)
    reconciliation_tolerance = {}
    for symbol in TOP3:
        rule = rules[symbol]
        price = _float(prices[symbol])
        current_notional = positions[symbol] * price
        target_notional = desired[symbol] * capital
        delta = target_notional - current_notional
        if target_notional > 0.0 and current_notional > 0.0:
            denominator = max(target_notional, current_notional)
            if abs(delta) < LIVE_PILOT_CONTRACT.rebalance_deadband * denominator:
                continue
        step = _float(rule.get("market_step_size") or rule.get("step_size"))
        reconciliation_tolerance[symbol] = max(step * 1.01, 1e-12)
        quantity = _round_down(abs(delta) / price, step)
        if delta < 0.0:
            quantity = min(quantity, _round_down(positions[symbol], step))
        notional = quantity * price
        minimum = max(
            _float(rule.get("min_notional")),
            _float(rule.get("min_qty")) * price,
        ) * 1.05
        if quantity <= 0.0 or notional + 1e-12 < minimum:
            if abs(delta) > 1e-9:
                report["risk_flags"].append(f"{symbol}:below_buffered_minimum")
            continue
        side = "buy" if delta > 0.0 else "sell"
        intent = {
            "symbol": symbol,
            "ccxt_symbol": (snapshot.get("resolved_symbols") or {}).get(symbol),
            "side": side,
            "type": "market",
            "quantity": quantity,
            "notional_usdt": notional,
            "reduce_only": side == "sell",
            "client_order_id": _client_order_id("m", decision_id, symbol),
        }
        report["market_orders"].append(intent)
        predicted[symbol] += quantity if side == "buy" else -quantity

    report["expected_positions_base"] = {
        symbol: max(predicted[symbol], 0.0) for symbol in TOP3
    }
    report["reconciliation_tolerance_base"] = reconciliation_tolerance

    for symbol in TOP3:
        existing = managed_stops.get(symbol)
        wants_stop = predicted[symbol] > 0.0 and desired[symbol] > 0.0
        if not wants_stop:
            if existing:
                report["stop_cancels"].append(existing)
            continue
        tick = _float(rules[symbol].get("tick_size"))
        stop_price = _round_down(_float(protective.get(symbol)), tick)
        if stop_price <= 0.0 or stop_price >= _float(prices[symbol]):
            blockers.append(f"{symbol}:invalid_native_stop_price")
            continue
        old = _float((existing or {}).get("trigger_price"))
        if existing and abs(old - stop_price) <= max(tick, 1e-12):
            report["retained_stops"].append(existing)
            continue
        if existing:
            report["stop_cancels"].append(existing)
        report["stop_orders"].append(
            {
                "symbol": symbol,
                "ccxt_symbol": (snapshot.get("resolved_symbols") or {}).get(symbol),
                "side": "sell",
                "type": "STOP_MARKET",
                "stop_price": stop_price,
                "close_position": True,
                "client_order_id": _client_order_id("s", decision_id, symbol),
            }
        )

    if decision_id in set(summary.get("executed_decision_ids") or []):
        blockers.append("decision_already_executed")
    if decision_id in set(summary.get("locked_live_decision_ids") or []):
        blockers.append("decision_has_unresolved_live_intent")

    live_authorized = False
    if mode == "live":
        if readiness.get("diagnostics", {}).get("verdict") != "ready_for_manual_final_arm":
            blockers.append("readiness_not_ready_for_manual_arm")
        live_authorized = _manual_arm_valid(
            arm,
            readiness,
            sources,
            arm_token=arm_token,
            live_switch_enabled=live_switch_enabled,
            live_confirmation=live_confirmation,
        )
        if not live_authorized:
            blockers.append("manual_arm_or_live_switch_invalid")
        if arm:
            date = str(decision.get("decision_date") or "")
            if not (
                str(arm.get("start_date") or "") <= date
                < str(arm.get("end_date_exclusive") or "")
            ):
                blockers.append("decision_outside_armed_window")

    report["diagnostics"]["live_authorized"] = live_authorized
    if not blockers:
        report["diagnostics"]["dry_evidence_valid"] = mode == "dry"
        report["diagnostics"]["verdict"] = (
            "live_dispatch_ready" if mode == "live" else "dry_dispatch_ready"
        )
        report["meta"]["orders_allowed"] = mode == "live"
        report["meta"]["live_orders_allowed"] = mode == "live"
    return _finalize_plan(report)


def _finalize_plan(report: dict[str, Any]) -> dict[str, Any]:
    report["diagnostics"]["blockers"] = list(
        dict.fromkeys(report["diagnostics"]["blockers"])
    )
    core = {
        "contract_hash": report.get("contract_hash"),
        "readiness_hash": report.get("readiness_hash"),
        "source_hashes": report.get("source_hashes"),
        "snapshot_hash": report.get("snapshot_hash"),
        "decision": report.get("decision"),
        "capital_usdt": report.get("capital_usdt"),
        "desired_weights": report.get("desired_weights"),
        "market_orders": report.get("market_orders"),
        "stop_cancels": report.get("stop_cancels"),
        "stop_orders": report.get("stop_orders"),
        "risk_flags": report.get("risk_flags"),
        "halt_after_dispatch": report.get("halt_after_dispatch"),
        "expected_positions_base": report.get("expected_positions_base"),
        "reconciliation_tolerance_base": report.get(
            "reconciliation_tolerance_base"
        ),
    }
    report["plan_hash"] = canonical_hash(core)
    return report


_JOURNAL_FIELDS = {
    "schema_version",
    "event_id",
    "recorded_at",
    "event_type",
    "mode",
    "decision_date",
    "decision_id",
    "plan_hash",
    "contract_hash",
    "readiness_hash",
    "source_hashes",
    "client_order_ids",
    "planned_orders",
    "exchange_responses",
    "reconciliation",
    "status",
}


def _journal_core(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(row).items()
        if key not in {"row_hash", "chain_hash"}
    }


def _validate_journal_row(row: Mapping[str, Any]) -> None:
    missing = sorted(_JOURNAL_FIELDS - set(row))
    if missing:
        raise ValueError(f"dispatch journal row missing fields: {','.join(missing)}")
    if row.get("schema_version") != PILOT_DISPATCH_JOURNAL_VERSION:
        raise ValueError("dispatch journal schema mismatch")
    dt.datetime.fromisoformat(str(row["recorded_at"]))
    dt.date.fromisoformat(str(row["decision_date"]))
    if row["mode"] not in {"dry", "live"}:
        raise ValueError("dispatch journal mode invalid")
    if row["contract_hash"] != LIVE_PILOT_CONTRACT.contract_hash:
        raise ValueError("dispatch journal contract mismatch")
    for name in (
        "source_hashes",
        "reconciliation",
    ):
        if not isinstance(row[name], dict):
            raise ValueError(f"dispatch journal {name} must be an object")
    for name in (
        "client_order_ids",
        "planned_orders",
        "exchange_responses",
    ):
        if not isinstance(row[name], list):
            raise ValueError(f"dispatch journal {name} must be a list")


def verify_dispatch_journal(path: str | os.PathLike[str]) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return {
            "schema_version": PILOT_DISPATCH_JOURNAL_VERSION,
            "row_count": 0,
            "final_chain_hash": _ZERO_HASH,
            "event_ids": [],
            "dry_decision_dates": [],
            "executed_decision_ids": [],
            "locked_live_decision_ids": [],
            "peak_margin_balance_usdt": 0.0,
        }
    previous = _ZERO_HASH
    event_ids: list[str] = []
    dry_dates: set[str] = set()
    executed: set[str] = set()
    locked: set[str] = set()
    peak = 0.0
    count = 0
    with target.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"dispatch journal row {line_number} is not an object")
            core = _journal_core(row)
            _validate_journal_row(core)
            row_hash = canonical_hash(core)
            chain_hash = canonical_hash(
                {"previous_chain_hash": previous, "row_hash": row_hash}
            )
            if row.get("row_hash") != row_hash or row.get("chain_hash") != chain_hash:
                raise ValueError(f"dispatch journal hash mismatch at row {line_number}")
            event_id = str(core["event_id"])
            if event_id in event_ids:
                raise ValueError(f"duplicate dispatch journal event: {event_id}")
            event_ids.append(event_id)
            decision_id = str(core["decision_id"])
            event_type = str(core["event_type"])
            if event_type == "dry_validated" and core["status"] == "valid":
                dry_dates.add(str(core["decision_date"]))
            if event_type == "live_intent_locked":
                locked.add(decision_id)
            if event_type == "live_completed":
                executed.add(decision_id)
                locked.discard(decision_id)
            balance = _float(
                (core.get("reconciliation") or {}).get("margin_balance_usdt")
            )
            peak = max(peak, balance)
            previous = chain_hash
            count += 1
    return {
        "schema_version": PILOT_DISPATCH_JOURNAL_VERSION,
        "row_count": count,
        "final_chain_hash": previous,
        "event_ids": event_ids,
        "dry_decision_dates": sorted(dry_dates),
        "executed_decision_ids": sorted(executed),
        "locked_live_decision_ids": sorted(locked),
        "peak_margin_balance_usdt": peak,
    }


def append_dispatch_journal(
    path: str | os.PathLike[str], row: Mapping[str, Any]
) -> dict[str, Any]:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    core = _journal_core(row)
    _validate_journal_row(core)
    with target.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.seek(0)
            current = verify_dispatch_journal(target)
            if core["event_id"] in current["event_ids"]:
                raise ValueError(f"duplicate dispatch journal event: {core['event_id']}")
            row_hash = canonical_hash(core)
            chain_hash = canonical_hash(
                {
                    "previous_chain_hash": current["final_chain_hash"],
                    "row_hash": row_hash,
                }
            )
            payload = core | {"row_hash": row_hash, "chain_hash": chain_hash}
            handle.seek(0, os.SEEK_END)
            handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return payload


def dry_dispatch_evidence(path: str | os.PathLike[str]) -> dict[str, Any]:
    try:
        summary = verify_dispatch_journal(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "dry_run_days": 0,
            "dry_run_schema_error_count": 1,
            "error": f"{type(exc).__name__}: {str(exc)[:300]}",
        }
    return {
        "dry_run_days": len(summary["dry_decision_dates"]),
        "dry_run_schema_error_count": 0,
        "decision_dates": summary["dry_decision_dates"],
        "row_count": summary["row_count"],
        "final_chain_hash": summary["final_chain_hash"],
    }


def _event_row(
    plan: Mapping[str, Any],
    *,
    event_type: str,
    status: str,
    exchange_responses: list[dict[str, Any]] | None = None,
    reconciliation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    decision = plan.get("decision") or {}
    planned = [
        *list(plan.get("market_orders") or []),
        *list(plan.get("stop_cancels") or []),
        *list(plan.get("stop_orders") or []),
    ]
    client_ids = sorted(
        {
            str(row.get("client_order_id"))
            for row in planned
            if row.get("client_order_id")
        }
    )
    event_id = canonical_hash(
        {
            "event_type": event_type,
            "mode": plan.get("meta", {}).get("mode"),
            "decision_id": decision.get("decision_id"),
            "plan_hash": plan.get("plan_hash"),
        }
    )
    return {
        "schema_version": PILOT_DISPATCH_JOURNAL_VERSION,
        "event_id": event_id,
        "recorded_at": utc_now().isoformat(),
        "event_type": event_type,
        "mode": plan.get("meta", {}).get("mode"),
        "decision_date": decision.get("decision_date"),
        "decision_id": decision.get("decision_id"),
        "plan_hash": plan.get("plan_hash"),
        "contract_hash": plan.get("contract_hash"),
        "readiness_hash": plan.get("readiness_hash"),
        "source_hashes": dict(plan.get("source_hashes") or {}),
        "client_order_ids": client_ids,
        "planned_orders": planned,
        "exchange_responses": list(exchange_responses or []),
        "reconciliation": dict(reconciliation or {}),
        "status": status,
    }


def _exchange_response_view(response: Mapping[str, Any]) -> dict[str, Any]:
    info = response.get("info") or {}
    return {
        "id": response.get("id") or info.get("orderId") or info.get("algoId"),
        "client_order_id": (
            response.get("clientOrderId")
            or info.get("clientOrderId")
            or info.get("clientAlgoId")
        ),
        "status": response.get("status") or info.get("status"),
        "symbol": response.get("symbol") or info.get("symbol"),
        "type": response.get("type") or info.get("origType") or info.get("type"),
        "side": response.get("side") or info.get("side"),
        "amount": response.get("amount"),
        "filled": response.get("filled") or info.get("executedQty"),
        "average": response.get("average") or info.get("avgPrice"),
        "stop_price": (
            response.get("stopPrice")
            or response.get("triggerPrice")
            or info.get("stopPrice")
        ),
    }


def _post_dispatch_reconciliation(
    plan: Mapping[str, Any], snapshot: Mapping[str, Any]
) -> dict[str, Any]:
    blockers: list[str] = []
    actual = {symbol: 0.0 for symbol in TOP3}
    for position in snapshot.get("positions") or []:
        symbol = position.get("data_symbol")
        if symbol not in TOP3 or str(position.get("side")).lower() != "long":
            blockers.append("unmanaged_or_short_position")
            continue
        actual[str(symbol)] += _float(position.get("contracts"))
    expected = plan.get("expected_positions_base") or {}
    tolerance = plan.get("reconciliation_tolerance_base") or {}
    if set(expected) != set(TOP3):
        blockers.append("expected_position_schema_missing")
    else:
        for symbol in TOP3:
            if abs(actual[symbol] - _float(expected[symbol])) > _float(
                tolerance.get(symbol)
            ):
                blockers.append(f"{symbol}:position_reconciliation_mismatch")

    if snapshot.get("regular_open_orders"):
        blockers.append("regular_open_order_remains")
    if not _snapshot_hash_valid(snapshot):
        blockers.append("post_dispatch_snapshot_hash_invalid")
    stops: dict[str, list[Mapping[str, Any]]] = {symbol: [] for symbol in TOP3}
    for order in snapshot.get("conditional_open_orders") or []:
        symbol = order.get("data_symbol")
        managed = (
            symbol in TOP3
            and str(order.get("client_order_id") or "").startswith("qmt-s-")
            and bool(order.get("close_position") or order.get("reduce_only"))
            and str(order.get("side") or "").lower() == "sell"
        )
        if not managed:
            blockers.append("unmanaged_conditional_order_remains")
            continue
        stops[str(symbol)].append(order)
    for symbol in TOP3:
        should_have_stop = _float(expected.get(symbol)) > _float(tolerance.get(symbol))
        if should_have_stop and len(stops[symbol]) != 1:
            blockers.append(f"{symbol}:protective_stop_reconciliation_mismatch")
        if not should_have_stop and stops[symbol]:
            blockers.append(f"{symbol}:stale_protective_stop_remains")
    blockers = list(dict.fromkeys(blockers))
    return {
        "snapshot_hash": snapshot.get("snapshot_hash"),
        "snapshot_verdict": snapshot.get("diagnostics", {}).get("verdict"),
        "margin_balance_usdt": _float(
            (snapshot.get("balance") or {}).get("margin_balance")
        ),
        "expected_positions_base": dict(expected),
        "actual_positions_base": actual,
        "regular_open_order_count": len(snapshot.get("regular_open_orders") or []),
        "conditional_open_order_count": len(
            snapshot.get("conditional_open_orders") or []
        ),
        "blockers": blockers,
        "passed": (
            snapshot.get("diagnostics", {}).get("verdict")
            == "account_snapshot_pass"
            and not blockers
        ),
    }


def run_pilot_dispatch(
    settings: Settings,
    plan: dict[str, Any],
    journal_path: str | os.PathLike[str],
    *,
    exchange: Any | None = None,
    halt_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Record a dry decision or execute an already-authorized live plan."""

    mode = str(plan.get("meta", {}).get("mode") or "dry")
    result = {
        "mode": mode,
        "event_recorded": False,
        "duplicate_noop": False,
        "exchange_mutation_attempted": False,
        "responses": [],
        "status": "blocked",
    }
    if mode == "dry":
        if plan.get("diagnostics", {}).get("verdict") != "dry_dispatch_ready":
            result["status"] = "not_recorded"
            return result
        current = verify_dispatch_journal(journal_path)
        date = str((plan.get("decision") or {}).get("decision_date"))
        if date in current["dry_decision_dates"]:
            result.update({"duplicate_noop": True, "status": "duplicate_dry_noop"})
            return result
        row = _event_row(
            plan,
            event_type="dry_validated",
            status="valid",
            reconciliation={
                "margin_balance_usdt": _float(
                    (plan.get("account_equity") or {}).get("margin_balance_usdt")
                ),
                "snapshot_hash": plan.get("snapshot_hash"),
            },
        )
        append_dispatch_journal(journal_path, row)
        result.update({"event_recorded": True, "status": "dry_validated"})
        return result

    if plan.get("diagnostics", {}).get("verdict") != "live_dispatch_ready":
        return result
    if not plan.get("meta", {}).get("live_orders_allowed"):
        return result
    client = exchange or build_exchange(settings, private=True)
    append_dispatch_journal(
        journal_path,
        _event_row(plan, event_type="live_intent_locked", status="locked"),
    )
    result["event_recorded"] = True
    responses: list[dict[str, Any]] = []
    result["exchange_mutation_attempted"] = True
    try:
        for order in sorted(
            plan.get("market_orders") or [],
            key=lambda row: 0 if row["side"] == "sell" else 1,
        ):
            params = {"newClientOrderId": order["client_order_id"]}
            if order.get("reduce_only"):
                params["reduceOnly"] = True
            response = client.create_order(
                order["ccxt_symbol"],
                "market",
                order["side"],
                order["quantity"],
                None,
                params,
            )
            responses.append(_exchange_response_view(response))
        for order in plan.get("stop_cancels") or []:
            client.cancel_order(
                order["id"], order["symbol"], params={"stop": True}
            )
            responses.append(
                {
                    "action": "cancel_stop",
                    "id": order["id"],
                    "symbol": order["symbol"],
                }
            )
        for order in plan.get("stop_orders") or []:
            response = client.create_order(
                order["ccxt_symbol"],
                "STOP_MARKET",
                "sell",
                None,
                None,
                {
                    "stopPrice": order["stop_price"],
                    "closePosition": True,
                    "newClientOrderId": order["client_order_id"],
                },
            )
            responses.append(_exchange_response_view(response))
    except Exception as exc:
        safe = _safe_error(exc, settings)
        responses.append({"error": safe})
        append_dispatch_journal(
            journal_path,
            _event_row(
                plan,
                event_type="live_execution_error",
                status="halted_uncertain",
                exchange_responses=responses,
            ),
        )
        result.update({"responses": responses, "status": "halted_uncertain"})
        if halt_path:
            Path(halt_path).write_text("live_execution_error\n", encoding="ascii")
        return result

    post = fetch_pilot_dispatch_snapshot(settings, exchange=client)
    reconciliation = _post_dispatch_reconciliation(plan, post)
    completed = bool(reconciliation["passed"])
    append_dispatch_journal(
        journal_path,
        _event_row(
            plan,
            event_type="live_completed" if completed else "live_reconciliation_error",
            status="completed" if completed else "halted_reconciliation",
            exchange_responses=responses,
            reconciliation=reconciliation,
        ),
    )
    result.update(
        {
            "responses": responses,
            "status": "completed" if completed else "halted_reconciliation",
            "reconciliation": reconciliation,
        }
    )
    if (not completed or plan.get("halt_after_dispatch")) and halt_path:
        reason = "pilot_drawdown_halt" if plan.get("halt_after_dispatch") else "reconciliation_error"
        Path(halt_path).write_text(reason + "\n", encoding="ascii")
    return result


def write_pilot_dispatch_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-pilot-dispatch",
        path_key="artifact_path",
        default_filename="mini_trend_um_pilot_dispatch.json",
        explicit_path=explicit_path,
    )
