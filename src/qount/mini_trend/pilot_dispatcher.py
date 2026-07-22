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
from qount.execution import compare_legacy_dispatch_plan
from qount.exchange_utils import (
    build_exchange,
    call_with_time_sync_retry,
    extract_quote_balance,
    resolve_market_symbols,
)
from qount.ledger import RuntimeLedger
from qount.ledger import RuntimeLedgerSnapshot
from qount.ledger import build_runtime_ledger_snapshot
from qount.ledger import reconcile_three_way
from qount.governance import StrategyRegistry
from qount.mini_trend.forward import TOP3
from qount.mini_trend.futures_recovery import canonical_hash, selected_um_rules
from qount.mini_trend.live_pilot import LIVE_PILOT_CONTRACT
from qount.mini_trend.live_pilot import manual_arm_owner_authorization_hash
from qount.models import utc_now
from qount.persistence import VerifiedDecisionBatch
from qount.settings import Settings


PILOT_DISPATCH_VERSION = "mini_trend_um_pilot_dispatch_v0.1"
PILOT_DISPATCH_SNAPSHOT_VERSION = "mini_trend_um_dispatch_snapshot_v0.1"
PILOT_DISPATCH_JOURNAL_VERSION = "mini_trend_um_dispatch_journal_v0.1"
PILOT_MANUAL_ARM_VERSION = "mini_trend_um_manual_arm_v0.1"
_ZERO_HASH = "0" * 64
_CLIENT_PREFIX = "qmt-"
_STANDARD_PROTECTIVE_PREFIX = "q-p-"
_CONFIGURED_SYMBOLS = tuple(f"{symbol[:-4]}/USDT" for symbol in TOP3)


def _managed_protective_client_id(value: object) -> bool:
    client_order_id = str(value or "")
    return client_order_id.startswith(("qmt-s-", _STANDARD_PROTECTIVE_PREFIX))


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _utc_timestamp(value: object) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(dt.timezone.utc)


def _source_age_seconds(
    payload: Mapping[str, Any], *, observed_at: dt.datetime
) -> float | None:
    created_at = _utc_timestamp(payload.get("created_at"))
    if created_at is None:
        return None
    age = (observed_at - created_at).total_seconds()
    if age < -60.0:
        return None
    return max(age, 0.0)


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
        if isinstance(secret, str) and secret:
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


def _position_average_cost(position: Mapping[str, Any]) -> float:
    info = position.get("info") or {}
    return _float(
        position.get("entryPrice")
        or position.get("average")
        or info.get("entryPrice")
        or info.get("breakEvenPrice")
    )


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
                    "average_cost": _position_average_cost(position),
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
            "observations": readiness.get("observations") or {},
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
    initial_dispatch: bool,
) -> bool:
    if not arm or not arm_token or not live_switch_enabled:
        return False
    token_hash = hashlib.sha256(arm_token.encode("utf-8")).hexdigest()
    common_valid = all(
        (
            arm.get("schema_version") == PILOT_MANUAL_ARM_VERSION,
            arm.get("status") == "armed",
            arm.get("contract_hash") == LIVE_PILOT_CONTRACT.contract_hash,
            arm.get("arm_token_sha256") == token_hash,
            arm.get("owner_authorization_hash")
            == manual_arm_owner_authorization_hash(arm),
            live_confirmation == arm.get("arm_id"),
        )
    )
    initial_binding_valid = all(
        (
            arm.get("readiness_hash") == readiness.get("readiness_hash"),
            arm.get("readiness_artifact_sha256") == source_hashes.get("readiness"),
            arm.get("authority_batch_id")
            == (readiness.get("evidence") or {}).get("authority_batch_id"),
            arm.get("runtime_ledger_snapshot_hash")
            == (readiness.get("evidence") or {}).get(
                "runtime_ledger_snapshot_hash"
            ),
            arm.get("pre_dispatch_reconciliation_hash")
            == (readiness.get("evidence") or {}).get(
                "pre_dispatch_reconciliation_hash"
            ),
            arm.get("release_git_commit")
            == (readiness.get("evidence") or {}).get("release_git_commit"),
            arm.get("release_version")
            == (readiness.get("evidence") or {}).get("release_version"),
            arm.get("release_source_tree_hash")
            == (readiness.get("evidence") or {}).get(
                "release_source_tree_hash"
            ),
            arm.get("release_provenance_hash")
            == (readiness.get("evidence") or {}).get(
                "release_provenance_hash"
            ),
        )
    )
    return common_valid and (not initial_dispatch or initial_binding_valid)


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
    evidence = readiness.get("evidence") or {}
    created_at = utc_now().isoformat()
    token_hash = hashlib.sha256(arm_token.encode("utf-8")).hexdigest()
    arm_id = "qmt-arm-" + canonical_hash(
        {
            "readiness_hash": readiness_hash,
            "readiness_artifact_sha256": readiness_artifact_sha256,
            "created_at": created_at,
        }
    )[:20]
    arm = {
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
        "authority_batch_id": evidence.get("authority_batch_id"),
        "runtime_ledger_snapshot_hash": evidence.get(
            "runtime_ledger_snapshot_hash"
        ),
        "pre_dispatch_reconciliation_hash": evidence.get(
            "pre_dispatch_reconciliation_hash"
        ),
        "release_git_commit": evidence.get("release_git_commit"),
        "release_version": evidence.get("release_version"),
        "release_source_tree_hash": evidence.get("release_source_tree_hash"),
        "release_provenance_hash": evidence.get("release_provenance_hash"),
        "initial_margin_balance_usdt": _float(
            evidence.get("available_balance_usdt")
        ),
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
        "governance_override": {
            "scope": "owner_authorized_100_usdt_canary",
            "elapsed_observation_targets_block_orders": False,
            "account_execution_and_reconciliation_gates_block_orders": True,
        },
    }
    return arm | {"owner_authorization_hash": manual_arm_owner_authorization_hash(arm)}


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


def _standard_order_key(order: Any) -> tuple[Any, ...]:
    return (
        str(order.symbol),
        str(order.side),
        str(order.phase),
        str(order.order_type),
        None if order.quantity is None else float(order.quantity),
        bool(order.reduce_only),
        bool(order.close_position),
        None if order.stop_price is None else float(order.stop_price),
    )


def _legacy_order_key(order: Mapping[str, Any]) -> tuple[Any, ...]:
    side = str(order.get("side") or "").lower()
    order_type = str(order.get("type") or "market").lower()
    protective = order_type == "stop_market"
    return (
        str(order.get("symbol") or ""),
        side,
        "protective" if protective else ("reduce" if side == "sell" else "increase"),
        order_type,
        None if protective else float(order.get("quantity")),
        bool(order.get("reduce_only")),
        bool(order.get("close_position")),
        float(order.get("stop_price")) if protective else None,
    )


def _bind_standard_authority(
    report: dict[str, Any],
    readiness: Mapping[str, Any],
    batch: VerifiedDecisionBatch | None,
    ledger_snapshot: RuntimeLedgerSnapshot | None,
    registry: StrategyRegistry | None,
    arm: Mapping[str, Any] | None,
) -> None:
    blockers: list[str] = report["diagnostics"]["blockers"]
    if batch is None or ledger_snapshot is None or registry is None:
        blockers.append("standard_live_execution_authority_missing")
        return
    if arm is None:
        blockers.append("standard_live_execution_manual_arm_missing")
        return
    evidence = readiness.get("evidence") or {}
    source = report.get("standard_authority") or {}
    reconciliation = ledger_snapshot.reconciliation
    checks = {
        "standard_authority_batch_mismatch": (
            batch.manifest.batch_id == evidence.get("authority_batch_id")
            == source.get("batch_id")
            == ledger_snapshot.batch_id
        ),
        "standard_authority_ledger_snapshot_mismatch": (
            ledger_snapshot.snapshot_hash
            == evidence.get("runtime_ledger_snapshot_hash")
            == source.get("ledger_snapshot_hash")
        ),
        "standard_authority_reconciliation_mismatch": (
            reconciliation.get("report_hash")
            == evidence.get("pre_dispatch_reconciliation_hash")
            == source.get("reconciliation_hash")
        ),
        "standard_authority_plan_mismatch": (
            ledger_snapshot.order_plan_id == batch.plan.order_plan_id
            and ledger_snapshot.plan_hash == batch.plan.plan_hash
        ),
        "standard_authority_pre_dispatch_not_ready": (
            reconciliation.get("phase") == "pre_dispatch"
            and reconciliation.get("passed") is True
            and reconciliation.get("halt_required") is False
            and not ledger_snapshot.unresolved_order_ids
            and ledger_snapshot.nav.get("passed") is True
        ),
    }
    blockers.extend(name for name, passed in checks.items() if not passed)
    matching_entries = tuple(
        entry
        for entry in registry.entries
        if entry.strategy_id == LIVE_PILOT_CONTRACT.strategy
    )
    registry_entry = matching_entries[0] if len(matching_entries) == 1 else None
    expected_owner_hash = manual_arm_owner_authorization_hash(arm)
    registry_checks = {
        "standard_live_execution_registry_entry_missing": registry_entry is not None,
        "standard_live_execution_registry_not_minimal_live": bool(
            registry_entry is not None
            and registry_entry.promotion_status == "minimal_live"
        ),
        "standard_live_execution_registry_owner_authorization_mismatch": bool(
            registry_entry is not None
            and expected_owner_hash is not None
            and registry_entry.owner_authorization_hash == expected_owner_hash
        ),
    }
    blockers.extend(
        name for name, passed in registry_checks.items() if not passed
    )
    parity = compare_legacy_dispatch_plan(report, batch.plan)
    report["standard_execution"] = {
        "batch_id": batch.manifest.batch_id,
        "manifest_hash": batch.manifest.manifest_hash,
        "order_plan_id": batch.plan.order_plan_id,
        "plan_hash": batch.plan.plan_hash,
        "pre_dispatch_ledger_snapshot_hash": ledger_snapshot.snapshot_hash,
        "pre_dispatch_reconciliation_hash": reconciliation.get("report_hash"),
        "registry_hash": registry.registry_hash,
        "registry_entry_id": (
            registry_entry.registry_entry_id if registry_entry is not None else None
        ),
        "registry_promotion_status": (
            registry_entry.promotion_status if registry_entry is not None else None
        ),
        "registry_owner_authorization_hash": (
            registry_entry.owner_authorization_hash if registry_entry is not None else None
        ),
        "parity_matches": parity["matches"],
        "parity_differences": list(parity["differences"]),
    }
    if not parity["matches"]:
        blockers.extend(
            f"standard_live_execution_parity_mismatch:{name}"
            for name in parity["differences"]
        )
        return

    standard_by_key: dict[tuple[Any, ...], list[Any]] = {}
    for order in sorted(batch.plan.orders, key=lambda value: value.sequence):
        standard_by_key.setdefault(_standard_order_key(order), []).append(order)
    for legacy in [
        *list(report.get("market_orders") or ()),
        *list(report.get("stop_orders") or ()),
    ]:
        matches = standard_by_key.get(_legacy_order_key(legacy)) or []
        if not matches:
            blockers.append("standard_live_execution_order_identity_missing")
            continue
        standard = matches.pop(0)
        legacy["legacy_client_order_id"] = legacy.get("client_order_id")
        legacy["client_order_id"] = standard.client_order_id
        legacy["standard_sequence"] = standard.sequence


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
    standard_batch: VerifiedDecisionBatch | None = None,
    standard_ledger_snapshot: RuntimeLedgerSnapshot | None = None,
    standard_registry: StrategyRegistry | None = None,
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
        "standard_authority": dict(
            (readiness.get("runtime_sources") or {}).get("standard_authority") or {}
        ),
        "snapshot_hash": snapshot.get("snapshot_hash"),
        "decision": None,
        "capital_usdt": None,
        "desired_weights": {symbol: 0.0 for symbol in TOP3},
        "actual_weights": {symbol: 0.0 for symbol in TOP3},
        "execution_reference_prices": {},
        "market_orders": [],
        "stop_cancels": [],
        "stop_orders": [],
        "retained_stops": [],
        "risk_flags": [],
        "source_freshness": {},
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
    if mode == "live":
        freshness_observed_at = utc_now().astimezone(dt.timezone.utc)
        source_artifacts = {
            "preflight": preflight,
            "projection": projection,
            "readiness": readiness,
            "exchange_rules": rules_artifact,
            "account_snapshot": snapshot,
        }
        source_ages = {
            name: _source_age_seconds(payload, observed_at=freshness_observed_at)
            for name, payload in source_artifacts.items()
        }
        report["source_freshness"] = {
            "observed_at": freshness_observed_at.isoformat(),
            "maximum_age_seconds": (
                LIVE_PILOT_CONTRACT.maximum_live_source_age_seconds
            ),
            "ages_seconds": source_ages,
        }
        for name, age in source_ages.items():
            if age is None:
                blockers.append(f"live_source_timestamp_invalid:{name}")
            elif age > LIVE_PILOT_CONTRACT.maximum_live_source_age_seconds:
                blockers.append(f"live_source_stale:{name}")
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
    if abs(capital - LIVE_PILOT_CONTRACT.canary_capital_usdt) > 1e-12:
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
            and _managed_protective_client_id(order.get("client_order_id"))
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
    report["execution_reference_prices"] = {
        symbol: _float(prices[symbol]) for symbol in TOP3
    }
    margin_balance = _float((snapshot.get("balance") or {}).get("margin_balance"))
    arm_baseline = _float((arm or {}).get("initial_margin_balance_usdt"))
    if mode == "live" and arm_baseline <= 0.0:
        blockers.append("pilot_equity_baseline_missing")
    current_date = utc_now().astimezone(dt.timezone.utc).date().isoformat()
    daily_opening = summary.get("daily_opening_margin_balance_usdt") or {}
    daily_start = _float(daily_opening.get(current_date))
    if daily_start <= 0.0:
        daily_start = _float(summary.get("latest_margin_balance_usdt"))
    if daily_start <= 0.0:
        daily_start = arm_baseline if mode == "live" else margin_balance
    peak = max(
        _float(summary.get("peak_margin_balance_usdt")),
        arm_baseline,
        margin_balance,
    )
    drawdown_loss_usdt = max(0.0, peak - margin_balance)
    drawdown = drawdown_loss_usdt / max(capital, 1e-12)
    daily_loss_usdt = max(0.0, daily_start - margin_balance)
    daily_loss = daily_loss_usdt / max(capital, 1e-12)
    report["account_equity"] = {
        "margin_balance_usdt": margin_balance,
        "pilot_capital_usdt": capital,
        "peak_margin_balance_usdt": peak,
        "drawdown_loss_usdt": drawdown_loss_usdt,
        "drawdown_pct": drawdown * 100.0,
        "daily_start_margin_balance_usdt": daily_start,
        "daily_loss_usdt": daily_loss_usdt,
        "daily_loss_pct": daily_loss * 100.0,
    }
    peak_drawdown_halt = drawdown >= (
        LIVE_PILOT_CONTRACT.maximum_pilot_drawdown_pct / 100.0
    )
    daily_loss_halt = daily_loss >= (
        LIVE_PILOT_CONTRACT.maximum_daily_loss_pct / 100.0
    )
    halt_after_dispatch = peak_drawdown_halt or daily_loss_halt
    report["halt_reason"] = (
        "pilot_drawdown_halt"
        if peak_drawdown_halt
        else ("pilot_daily_loss_halt" if daily_loss_halt else None)
    )
    if peak_drawdown_halt:
        desired = {symbol: 0.0 for symbol in TOP3}
        report["risk_flags"].append("pilot_drawdown_flatten_then_halt")
    if daily_loss_halt:
        desired = {symbol: 0.0 for symbol in TOP3}
        report["risk_flags"].append("pilot_daily_loss_flatten_then_halt")
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
        _bind_standard_authority(
            report,
            readiness,
            standard_batch,
            standard_ledger_snapshot,
            standard_registry,
            arm,
        )
        if readiness.get("diagnostics", {}).get("verdict") != "ready_for_manual_final_arm":
            blockers.append("readiness_not_ready_for_manual_arm")
        live_authorized = _manual_arm_valid(
            arm,
            readiness,
            sources,
            arm_token=arm_token,
            live_switch_enabled=live_switch_enabled,
            live_confirmation=live_confirmation,
            initial_dispatch=not bool(summary.get("executed_decision_ids")),
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
        "standard_authority": report.get("standard_authority"),
        "standard_execution": report.get("standard_execution"),
        "snapshot_hash": report.get("snapshot_hash"),
        "decision": report.get("decision"),
        "capital_usdt": report.get("capital_usdt"),
        "desired_weights": report.get("desired_weights"),
        "execution_reference_prices": report.get("execution_reference_prices"),
        "market_orders": report.get("market_orders"),
        "stop_cancels": report.get("stop_cancels"),
        "stop_orders": report.get("stop_orders"),
        "risk_flags": report.get("risk_flags"),
        "source_freshness": report.get("source_freshness"),
        "halt_after_dispatch": report.get("halt_after_dispatch"),
        "halt_reason": report.get("halt_reason"),
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
            "latest_margin_balance_usdt": 0.0,
            "daily_opening_margin_balance_usdt": {},
        }
    previous = _ZERO_HASH
    event_ids: list[str] = []
    dry_dates: set[str] = set()
    executed: set[str] = set()
    locked: set[str] = set()
    peak = 0.0
    latest_margin_balance = 0.0
    daily_opening: dict[str, float] = {}
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
            if core.get("mode") == "live":
                balance = _float(
                    (core.get("reconciliation") or {}).get("margin_balance_usdt")
                )
                if balance > 0.0:
                    recorded_at = _utc_timestamp(core.get("recorded_at"))
                    if recorded_at is None:
                        raise ValueError(
                            f"dispatch journal recorded_at invalid at row {line_number}"
                        )
                    day = recorded_at.date().isoformat()
                    daily_opening.setdefault(day, balance)
                    latest_margin_balance = balance
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
        "latest_margin_balance_usdt": latest_margin_balance,
        "daily_opening_margin_balance_usdt": daily_opening,
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


def _market_response_observation(
    response: Mapping[str, Any],
    order: Mapping[str, Any],
) -> dict[str, Any]:
    view = _exchange_response_view(response)
    view["client_order_id"] = str(order["client_order_id"])
    planned = _float(order.get("quantity"))
    filled = _float(view.get("filled"))
    average = _float(view.get("average"))
    exchange_order_id = str(view.get("id") or "")
    status = str(view.get("status") or "").lower()
    complete = (
        exchange_order_id
        and planned > 0.0
        and abs(filled - planned) <= 1e-12
        and average > 0.0
        and status in {"closed", "filled"}
    )
    view["ledger_status"] = "FILLED" if complete else "UNKNOWN"
    view["ledger_reason"] = (
        "exchange_market_fill_complete"
        if complete
        else "exchange_market_result_not_definitive"
    )
    return view


def _trade_value(trade: Mapping[str, Any], *names: str) -> Any:
    info = trade.get("info") or {}
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
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
                dt.timezone.utc
            ).isoformat()
        except ValueError:
            pass
    timestamp = _trade_value(trade, "timestamp", "time")
    try:
        milliseconds = float(timestamp)
    except (TypeError, ValueError) as exc:
        raise ValueError("market_trade_time_missing") from exc
    if not math.isfinite(milliseconds) or milliseconds <= 0.0:
        raise ValueError("market_trade_time_missing")
    return dt.datetime.fromtimestamp(
        milliseconds / 1_000.0, tz=dt.timezone.utc
    ).isoformat()


def _trade_fee(trade: Mapping[str, Any]) -> tuple[float, str]:
    fee = trade.get("fee")
    if not isinstance(fee, Mapping):
        info = trade.get("info") or {}
        commission = info.get("commission")
        asset = info.get("commissionAsset")
        if commission in (None, "") or asset in (None, ""):
            raise ValueError("market_trade_fee_evidence_missing")
        fee = {"cost": commission, "currency": asset}
    currency = str(fee.get("currency") or "")
    cost = _float(fee.get("cost"))
    if not currency or cost < 0.0:
        raise ValueError("market_trade_fee_evidence_invalid")
    return cost, currency


def _trade_fill_evidence(
    trade: Mapping[str, Any],
    *,
    exchange_order_id: str,
    client_order_id: str,
) -> dict[str, Any]:
    info = trade.get("info") or {}
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
        or (observed_client_id and observed_client_id != client_order_id)
        or not trade_id
        or quantity <= 0.0
        or price <= 0.0
    ):
        raise ValueError("market_trade_identity_or_value_invalid")
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
    order: Mapping[str, Any],
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    """Confirm a market fill from exchange order and trade records before ledgering it."""

    initial = _exchange_response_view(response)
    exchange_order_id = str(initial.get("id") or "")
    client_order_id = str(order["client_order_id"])
    symbol = str(order["ccxt_symbol"])
    fetch_order = getattr(exchange, "fetch_order", None)
    if not exchange_order_id or not callable(fetch_order):
        raise RuntimeError("market_order_confirmation_query_unavailable")
    confirmed_order = call_with_time_sync_retry(
        exchange,
        fetch_order,
        exchange_order_id,
        symbol,
        retry_attempts=2,
    )
    if not isinstance(confirmed_order, Mapping):
        raise ValueError("market_order_confirmation_invalid")
    confirmed_view = _exchange_response_view(confirmed_order)
    if str(confirmed_view.get("id") or "") != exchange_order_id:
        raise ValueError("market_order_confirmation_identity_invalid")
    confirmed_client_id = str(confirmed_view.get("client_order_id") or "")
    if confirmed_client_id and confirmed_client_id != client_order_id:
        raise ValueError("market_order_confirmation_client_id_invalid")

    fetch_order_trades = getattr(exchange, "fetch_order_trades", None)
    if callable(fetch_order_trades):
        trade_rows = call_with_time_sync_retry(
            exchange,
            fetch_order_trades,
            exchange_order_id,
            symbol,
            retry_attempts=2,
        )
    else:
        fetch_my_trades = getattr(exchange, "fetch_my_trades", None)
        if not callable(fetch_my_trades):
            raise RuntimeError("market_trade_evidence_query_unavailable")
        trade_rows = call_with_time_sync_retry(
            exchange,
            fetch_my_trades,
            symbol,
            None,
            1_000,
            {"orderId": exchange_order_id},
            retry_attempts=2,
        )
    if not isinstance(trade_rows, (list, tuple)):
        raise ValueError("market_trade_evidence_invalid")
    fills = tuple(
        _trade_fill_evidence(
            trade,
            exchange_order_id=exchange_order_id,
            client_order_id=client_order_id,
        )
        for trade in trade_rows
        if isinstance(trade, Mapping)
    )
    if not fills or len(fills) != len(trade_rows):
        raise ValueError("market_trade_evidence_incomplete")
    if len({str(row["exchange_trade_id"]) for row in fills}) != len(fills):
        raise ValueError("market_trade_identity_duplicate")
    planned = _float(order.get("quantity"))
    filled = sum(_float(row["quantity"]) for row in fills)
    average = sum(
        _float(row["quantity"]) * _float(row["price"]) for row in fills
    ) / max(filled, 1e-12)
    currencies = {str(row["fee_asset"]) for row in fills}
    if currencies != {"USDT"}:
        raise ValueError("market_trade_fee_asset_not_usdt")
    confirmed_view["filled"] = filled
    confirmed_view["average"] = average
    observed = _market_response_observation(confirmed_view, order)
    if observed["ledger_status"] != "FILLED" or abs(filled - planned) > 1e-12:
        raise ValueError("market_trade_evidence_not_complete")
    observed["fill_count"] = len(fills)
    observed["fee_usdt"] = sum(_float(row["fee"]) for row in fills)
    return observed, fills


def _adverse_slippage_bps(
    *, side: str, reference_price: float, average_fill_price: float
) -> float:
    if reference_price <= 0.0 or average_fill_price <= 0.0:
        raise ValueError("market_slippage_reference_invalid")
    if side == "buy":
        return (average_fill_price / reference_price - 1.0) * 10_000.0
    if side == "sell":
        return (1.0 - average_fill_price / reference_price) * 10_000.0
    raise ValueError("market_slippage_side_invalid")


def _snapshot_positions(snapshot: Mapping[str, Any]) -> dict[str, float]:
    result = {symbol: 0.0 for symbol in TOP3}
    for row in snapshot.get("positions") or ():
        symbol = row.get("data_symbol")
        if symbol in result and str(row.get("side") or "").lower() == "long":
            result[str(symbol)] += _float(row.get("contracts"))
    return result


def _snapshot_managed_open_order_ids(snapshot: Mapping[str, Any]) -> tuple[str, ...]:
    result: list[str] = []
    for row in snapshot.get("conditional_open_orders") or ():
        if not _managed_protective_client_id(row.get("client_order_id")):
            continue
        client_order_id = str(row.get("client_order_id") or "")
        if client_order_id:
            result.append(client_order_id)
    return tuple(sorted(result))


def _halt(path: str | os.PathLike[str] | None, reason: str) -> None:
    if path is None:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(reason + "\n", encoding="ascii")
    os.chmod(target, 0o600)


def _utc_now_not_before(value: str) -> str:
    floor = dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        dt.timezone.utc
    )
    now = utc_now().astimezone(dt.timezone.utc)
    return max(now, floor).isoformat()


def _record_execution_halt_reconciliation(
    runtime_ledger: RuntimeLedger,
    batch: VerifiedDecisionBatch,
    *,
    reason: str,
) -> RuntimeLedgerSnapshot:
    """Publish an explicit failed post-dispatch state when exchange certainty is lost."""

    latest_nav = runtime_ledger.latest_nav_mark()
    if latest_nav is None:
        raise ValueError("standard_execution_pre_dispatch_nav_missing")
    reconciled_at = _utc_now_not_before(latest_nav.marked_at)
    reconciliation = reconcile_three_way(
        batch_id=batch.manifest.batch_id,
        reconciled_at=reconciled_at,
        phase="post_dispatch",
        target_positions=dict(batch.plan.expected_positions),
        ledger_positions=runtime_ledger.position_quantities(),
        exchange_positions={symbol: 0.0 for symbol in TOP3},
        position_tolerances=dict(batch.plan.reconciliation_tolerance),
        ledger_open_order_ids=runtime_ledger.open_order_ids(),
        exchange_open_order_ids=(),
        equity_residual=latest_nav.residual,
        equity_residual_tolerance=latest_nav.residual_tolerance,
    )
    if reconciliation.passed or not reconciliation.halt_required:
        raise ValueError(f"execution_halt_reconciliation_not_failed:{reason}")
    runtime_ledger.record_reconciliation(reconciliation)
    return build_runtime_ledger_snapshot(
        runtime_ledger,
        batch,
        captured_at=reconciled_at,
    )


def _cash_event_amount(row: Mapping[str, Any]) -> float:
    info = row.get("info") or {}
    # CCXT normalizes ledger amounts to absolute values and moves the sign to
    # ``direction``. Binance's raw ``income`` remains the authoritative signed
    # value for USD-M accounting and prevents an outflow becoming an inflow.
    raw = info.get("income")
    if raw in (None, ""):
        raw = info.get("amount")
    if raw in (None, ""):
        normalized = row.get("amount")
        direction = str(row.get("direction") or "").lower()
        if normalized in (None, "") or direction not in {"in", "out"}:
            raise ValueError("account_ledger_signed_amount_missing")
        try:
            absolute = abs(float(normalized))
        except (TypeError, ValueError) as exc:
            raise ValueError("account_ledger_amount_missing") from exc
        raw = absolute if direction == "in" else -absolute
    try:
        amount = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("account_ledger_amount_missing") from exc
    if not math.isfinite(amount):
        raise ValueError("account_ledger_amount_invalid")
    return amount


def _record_dispatch_cash_events(
    exchange: Any,
    runtime_ledger: RuntimeLedger,
    *,
    after: str,
    through: str,
    fill_fees_usdt: float,
) -> dict[str, Any]:
    """Persist the short execution-window cash evidence without relabeling it as PnL."""

    fetch_ledger = getattr(exchange, "fetch_ledger", None)
    if not callable(fetch_ledger):
        raise RuntimeError("account_ledger_query_unavailable")
    after_time = dt.datetime.fromisoformat(after.replace("Z", "+00:00")).astimezone(
        dt.timezone.utc
    )
    through_time = dt.datetime.fromisoformat(
        through.replace("Z", "+00:00")
    ).astimezone(dt.timezone.utc)
    rows = call_with_time_sync_retry(
        exchange,
        fetch_ledger,
        "USDT",
        int(after_time.timestamp() * 1_000),
        1_000,
        retry_attempts=2,
    )
    if not isinstance(rows, (list, tuple)):
        raise ValueError("account_ledger_response_invalid")
    source_rows = [row for row in rows if isinstance(row, Mapping)]
    if len(source_rows) != len(rows):
        raise ValueError("account_ledger_response_invalid")
    source_hash = canonical_hash(
        {
            "event": "post_dispatch_account_ledger",
            "after": after_time.isoformat(),
            "through": through_time.isoformat(),
            "rows": source_rows,
        }
    )
    funding = 0.0
    transfers = 0.0
    commissions = 0.0
    recorded_ids: set[str] = set()
    for row in source_rows:
        occurred_at = _trade_time(row)
        occurred_time = dt.datetime.fromisoformat(
            occurred_at.replace("Z", "+00:00")
        ).astimezone(dt.timezone.utc)
        if occurred_time <= after_time or occurred_time > through_time:
            continue
        info = row.get("info") or {}
        asset = str(row.get("currency") or info.get("asset") or "")
        if asset != "USDT":
            raise ValueError("account_ledger_asset_invalid")
        ledger_id = str(
            row.get("id")
            or info.get("tranId")
            or info.get("incomeId")
            or info.get("id")
            or ""
        )
        if not ledger_id or ledger_id in recorded_ids:
            raise ValueError("account_ledger_identity_invalid")
        recorded_ids.add(ledger_id)
        kind = str(info.get("incomeType") or info.get("type") or "").upper()
        amount = _cash_event_amount(row)
        if kind in {"COMMISSION", "FEE"}:
            if amount > 1e-12:
                raise ValueError("account_ledger_commission_sign_invalid")
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
            raise ValueError(f"account_ledger_event_unclassified:{kind or 'missing'}")
        runtime_ledger.record_cash_event(
            event_key=f"binance-ledger:{ledger_id}",
            event_type=event_type,
            amount=amount,
            asset=asset,
            occurred_at=occurred_at,
            source_hash=source_hash,
            symbol=(str(row.get("symbol") or info.get("symbol")) or None),
        )
    if commissions > 1e-12 and abs(commissions - fill_fees_usdt) > 1e-8:
        raise ValueError("account_ledger_commission_mismatch")
    return {
        "funding_usdt": funding,
        "transfer_usdt": transfers,
        "commission_usdt": commissions,
        "source_hash": source_hash,
        "row_count": len(source_rows),
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
            and _managed_protective_client_id(order.get("client_order_id"))
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
    standard_batch: VerifiedDecisionBatch | None = None,
    runtime_ledger: RuntimeLedger | None = None,
    pre_dispatch_ledger_snapshot: RuntimeLedgerSnapshot | None = None,
    standard_registry: StrategyRegistry | None = None,
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
    if (
        standard_batch is None
        or runtime_ledger is None
        or pre_dispatch_ledger_snapshot is None
        or standard_registry is None
    ):
        result["status"] = "blocked_standard_execution_ledger_missing"
        return result
    standard = plan.get("standard_execution") or {}
    if (
        standard.get("batch_id") != standard_batch.manifest.batch_id
        or standard.get("plan_hash") != standard_batch.plan.plan_hash
        or standard.get("pre_dispatch_ledger_snapshot_hash")
        != pre_dispatch_ledger_snapshot.snapshot_hash
        or pre_dispatch_ledger_snapshot.reconciliation.get("phase") != "pre_dispatch"
        or pre_dispatch_ledger_snapshot.reconciliation.get("passed") is not True
        or pre_dispatch_ledger_snapshot.unresolved_order_ids
        or standard.get("registry_hash") != standard_registry.registry_hash
        or standard.get("registry_promotion_status") != "minimal_live"
        or not standard.get("registry_owner_authorization_hash")
    ):
        result["status"] = "blocked_standard_execution_authority_mismatch"
        return result
    replayed = build_runtime_ledger_snapshot(
        runtime_ledger,
        standard_batch,
        captured_at=pre_dispatch_ledger_snapshot.captured_at,
    )
    if replayed.snapshot_hash != pre_dispatch_ledger_snapshot.snapshot_hash:
        result["status"] = "blocked_standard_execution_ledger_drift"
        return result
    client = exchange or build_exchange(settings, private=True)
    append_dispatch_journal(
        journal_path,
        _event_row(
            plan,
            event_type="live_intent_locked",
            status="locked",
            reconciliation={
                "margin_balance_usdt": _float(
                    (plan.get("account_equity") or {}).get(
                        "margin_balance_usdt"
                    )
                ),
                "snapshot_hash": plan.get("snapshot_hash"),
            },
        ),
    )
    result["event_recorded"] = True
    responses: list[dict[str, Any]] = []
    result["exchange_mutation_attempted"] = bool(
        plan.get("market_orders")
        or plan.get("stop_cancels")
        or plan.get("stop_orders")
    )
    fill_fees = 0.0
    slippage_breaches: list[dict[str, Any]] = []
    try:
        for order in sorted(
            plan.get("market_orders") or [],
            key=lambda row: 0 if row["side"] == "sell" else 1,
        ):
            client_order_id = str(order["client_order_id"])
            submitted_at = utc_now().isoformat()
            runtime_ledger.transition_order(
                client_order_id,
                "SUBMITTING",
                event_at=submitted_at,
                source_hash=canonical_hash(
                    {
                        "event": "exchange_submission_started",
                        "plan_hash": plan.get("plan_hash"),
                        "client_order_id": client_order_id,
                    }
                ),
            )
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
            observed, fills = _fetch_market_fill_evidence(client, response, order)
            reference_price = _float(
                (plan.get("execution_reference_prices") or {}).get(order["symbol"])
            )
            slippage_bps = _adverse_slippage_bps(
                side=str(order["side"]),
                reference_price=reference_price,
                average_fill_price=_float(observed.get("average")),
            )
            observed["reference_price"] = reference_price
            observed["adverse_slippage_bps"] = slippage_bps
            observed["maximum_adverse_slippage_bps"] = (
                LIVE_PILOT_CONTRACT.maximum_adverse_slippage_bps
            )
            if slippage_bps > LIVE_PILOT_CONTRACT.maximum_adverse_slippage_bps:
                slippage_breaches.append(
                    {
                        "symbol": order["symbol"],
                        "client_order_id": order["client_order_id"],
                        "adverse_slippage_bps": slippage_bps,
                    }
                )
            responses.append(observed)
            observation_hash = canonical_hash(
                {
                    "event": "exchange_market_fill_evidence",
                    "plan_hash": plan.get("plan_hash"),
                    "response": observed,
                    "fills": fills,
                }
            )
            runtime_ledger.transition_order(
                client_order_id,
                str(observed["ledger_status"]),
                event_at=utc_now().isoformat(),
                source_hash=observation_hash,
                exchange_order_id=str(observed.get("id") or "") or None,
                executed_quantity=_float(observed.get("filled")),
                average_price=(
                    _float(observed.get("average"))
                    if _float(observed.get("average")) > 0.0
                    else None
                ),
                reason=str(observed["ledger_reason"]),
            )
            for fill in fills:
                fill_fees += _float(fill["fee"])
                runtime_ledger.record_fill(
                    client_order_id=client_order_id,
                    exchange_trade_id=str(fill["exchange_trade_id"]),
                    quantity=_float(fill["quantity"]),
                    price=_float(fill["price"]),
                    fee=_float(fill["fee"]),
                    fee_asset=str(fill["fee_asset"]),
                    occurred_at=str(fill["occurred_at"]),
                    source_hash=observation_hash,
                )
            if observed["ledger_status"] != "FILLED":
                raise RuntimeError("market_order_result_uncertain")
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
            client_order_id = str(order.get("client_order_id") or "")
            if client_order_id.startswith(_STANDARD_PROTECTIVE_PREFIX):
                runtime_ledger.transition_order(
                    client_order_id,
                    "CANCELED",
                    event_at=utc_now().isoformat(),
                    source_hash=canonical_hash(
                        {
                            "event": "protective_stop_canceled",
                            "plan_hash": plan.get("plan_hash"),
                            "client_order_id": client_order_id,
                            "exchange_order_id": order.get("id"),
                        }
                    ),
                    exchange_order_id=str(order.get("id") or "") or None,
                    reason="confirmed_protective_stop_cancel",
                )
        for order in plan.get("stop_orders") or []:
            client_order_id = str(order["client_order_id"])
            runtime_ledger.transition_order(
                client_order_id,
                "SUBMITTING",
                event_at=utc_now().isoformat(),
                source_hash=canonical_hash(
                    {
                        "event": "protective_stop_submission_started",
                        "plan_hash": plan.get("plan_hash"),
                        "client_order_id": client_order_id,
                    }
                ),
            )
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
            observed = _exchange_response_view(response)
            observed["client_order_id"] = client_order_id
            responses.append(observed)
            exchange_order_id = str(observed.get("id") or "")
            if not exchange_order_id:
                raise RuntimeError("protective_stop_acknowledgement_missing")
            runtime_ledger.transition_order(
                client_order_id,
                "ACKNOWLEDGED",
                event_at=utc_now().isoformat(),
                source_hash=canonical_hash(
                    {
                        "event": "protective_stop_acknowledged",
                        "plan_hash": plan.get("plan_hash"),
                        "response": observed,
                    }
                ),
                exchange_order_id=exchange_order_id,
                reason="exchange_protective_stop_accepted",
            )
    except Exception as exc:
        safe = _safe_error(exc, settings)
        for order in standard_batch.plan.orders:
            current = runtime_ledger.get_order(order.client_order_id)
            if current["status"] in {"SUBMITTING", "PARTIALLY_FILLED"}:
                runtime_ledger.transition_order(
                    order.client_order_id,
                    "UNKNOWN",
                    event_at=utc_now().isoformat(),
                    source_hash=canonical_hash(
                        {
                            "event": "exchange_execution_uncertain",
                            "plan_hash": plan.get("plan_hash"),
                            "client_order_id": order.client_order_id,
                            "error_type": type(exc).__name__,
                        }
                    ),
                    reason=f"execution_error:{type(exc).__name__}",
                )
        responses.append({"error": safe})
        halt_snapshot_hash = None
        try:
            halt_snapshot = _record_execution_halt_reconciliation(
                runtime_ledger,
                standard_batch,
                reason=f"execution_error:{type(exc).__name__}",
            )
            halt_snapshot_hash = halt_snapshot.snapshot_hash
        except Exception as reconciliation_exc:
            responses.append(
                {
                    "halt_reconciliation_error": _safe_error(
                        reconciliation_exc, settings
                    )
                }
            )
        append_dispatch_journal(
            journal_path,
            _event_row(
                plan,
                event_type="live_execution_error",
                status="halted_uncertain",
                exchange_responses=responses,
            ),
        )
        result.update(
            {
                "responses": responses,
                "status": "halted_uncertain",
                "runtime_ledger_snapshot_hash": halt_snapshot_hash,
            }
        )
        _halt(halt_path, "live_execution_error")
        return result

    try:
        post = fetch_pilot_dispatch_snapshot(settings, exchange=client)
        reconciliation = _post_dispatch_reconciliation(plan, post)
        post_hash = canonical_hash(
            {"event": "post_dispatch_account_snapshot", "snapshot": post}
        )
        balance = post.get("balance") or {}
        post_time = str(post.get("created_at") or utc_now().isoformat())
        previous_nav = runtime_ledger.latest_nav_mark()
        if previous_nav is None:
            raise ValueError("standard_execution_pre_dispatch_nav_missing")
        cash_evidence = _record_dispatch_cash_events(
            client,
            runtime_ledger,
            after=previous_nav.marked_at,
            through=post_time,
            fill_fees_usdt=fill_fees,
        )
        runtime_ledger.record_account_observation(
            batch_id=standard_batch.manifest.batch_id,
            observed_at=post_time,
            quote_asset="USDT",
            wallet_balance=_float(balance.get("wallet_balance")),
            available_balance=_float(balance.get("quote_free")),
            actual_gross_notional=sum(
                _float(row.get("notional_usdt"))
                for row in post.get("positions") or ()
            ),
            margin_used=_float(balance.get("quote_used")),
            source_id=canonical_hash({"account_snapshot": post.get("snapshot_hash")}),
            source_hash=post_hash,
        )
        equity = _float(balance.get("margin_balance"))
        nav = runtime_ledger.record_nav_mark(
            marked_at=post_time,
            equity=equity,
            trading_pnl=(
                equity
                - previous_nav.equity
                - _float(cash_evidence["funding_usdt"])
                + fill_fees
                - _float(cash_evidence["transfer_usdt"])
            ),
            residual_tolerance=0.001,
            source_hash=post_hash,
        )
        standard_reconciliation = reconcile_three_way(
            batch_id=standard_batch.manifest.batch_id,
            reconciled_at=post_time,
            phase="post_dispatch",
            target_positions=dict(standard_batch.plan.expected_positions),
            ledger_positions=runtime_ledger.position_quantities(),
            exchange_positions=_snapshot_positions(post),
            position_tolerances=dict(standard_batch.plan.reconciliation_tolerance),
            ledger_open_order_ids=runtime_ledger.open_order_ids(),
            exchange_open_order_ids=_snapshot_managed_open_order_ids(post),
            equity_residual=nav.residual,
            equity_residual_tolerance=nav.residual_tolerance,
        )
        runtime_ledger.record_reconciliation(standard_reconciliation)
        standard_snapshot = build_runtime_ledger_snapshot(
            runtime_ledger,
            standard_batch,
            captured_at=_utc_now_not_before(post_time),
        )
        reconciliation["standard_reconciliation"] = standard_reconciliation.as_dict()
        reconciliation["runtime_ledger_snapshot_hash"] = standard_snapshot.snapshot_hash
        reconciliation["cash_evidence"] = cash_evidence
        completed = bool(reconciliation["passed"] and standard_reconciliation.passed)
        slippage_halt = completed and bool(slippage_breaches)
        completed_status = "halted_slippage" if slippage_halt else "completed"
        reconciliation["slippage"] = {
            "maximum_adverse_slippage_bps": (
                LIVE_PILOT_CONTRACT.maximum_adverse_slippage_bps
            ),
            "breaches": slippage_breaches,
            "passed": not slippage_breaches,
        }
        append_dispatch_journal(
            journal_path,
            _event_row(
                plan,
                event_type="live_completed" if completed else "live_reconciliation_error",
                status=(completed_status if completed else "halted_reconciliation"),
                exchange_responses=responses,
                reconciliation=reconciliation,
            ),
        )
        result.update(
            {
                "responses": responses,
                "status": (
                    completed_status if completed else "halted_reconciliation"
                ),
                "reconciliation": reconciliation,
                "runtime_ledger_snapshot_hash": standard_snapshot.snapshot_hash,
            }
        )
        if not completed or plan.get("halt_after_dispatch") or slippage_halt:
            reason = (
                str(plan.get("halt_reason") or "pilot_risk_halt")
                if plan.get("halt_after_dispatch")
                else (
                    "pilot_slippage_halt"
                    if slippage_halt
                    else "reconciliation_error"
                )
            )
            _halt(halt_path, reason)
        return result
    except Exception as exc:
        responses.append({"post_dispatch_error": _safe_error(exc, settings)})
        halt_snapshot_hash = None
        try:
            halt_snapshot = _record_execution_halt_reconciliation(
                runtime_ledger,
                standard_batch,
                reason=f"post_dispatch_error:{type(exc).__name__}",
            )
            halt_snapshot_hash = halt_snapshot.snapshot_hash
        except Exception as reconciliation_exc:
            responses.append(
                {
                    "halt_reconciliation_error": _safe_error(
                        reconciliation_exc, settings
                    )
                }
            )
        append_dispatch_journal(
            journal_path,
            _event_row(
                plan,
                event_type="live_reconciliation_error",
                status="halted_reconciliation",
                exchange_responses=responses,
            ),
        )
        result.update(
            {
                "responses": responses,
                "status": "halted_reconciliation",
                "runtime_ledger_snapshot_hash": halt_snapshot_hash,
            }
        )
        _halt(halt_path, "post_dispatch_accounting_error")
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
