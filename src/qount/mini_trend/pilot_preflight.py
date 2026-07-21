"""Read-only Binance account preflight for the MiniTrend UM pilot."""

from __future__ import annotations

from typing import Any, Mapping

from qount.artifacts import write_research_json_artifact
from qount.exchange_utils import build_exchange
from qount.exchange_utils import call_with_time_sync_retry
from qount.exchange_utils import extract_quote_balance
from qount.exchange_utils import resolve_market_symbols
from qount.mini_trend.forward import TOP3
from qount.mini_trend.live_pilot import LIVE_PILOT_CONTRACT
from qount.models import utc_now
from qount.settings import Settings


PILOT_PREFLIGHT_VERSION = "mini_trend_um_pilot_preflight_v0.4"
_CONFIGURED_SYMBOLS = tuple(
    f"{symbol[:-4]}/USDT" for symbol in TOP3
)


def _safe_error(exc: Exception, settings: Settings) -> str:
    value = f"{type(exc).__name__}: {exc}"
    for secret in (settings.binance_api_key, settings.binance_api_secret):
        if secret:
            value = value.replace(secret, "[REDACTED]")
    return value[:1000]


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _position_symbol(position: Mapping[str, Any]) -> str:
    return str(position.get("symbol") or (position.get("info") or {}).get("symbol") or "")


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


def _position_leverage(position: Mapping[str, Any]) -> float:
    return _float(position.get("leverage") or (position.get("info") or {}).get("leverage"))


def _position_margin_mode(position: Mapping[str, Any]) -> str | None:
    info = position.get("info") or {}
    value = position.get("marginMode") or info.get("marginType")
    if value:
        return str(value).lower()
    isolated = info.get("isolated")
    if isolated is None:
        return None
    return "isolated" if str(isolated).lower() in {"1", "true", "yes"} else "cross"


def _position_notional(position: Mapping[str, Any]) -> float:
    info = position.get("info") or {}
    return abs(_float(position.get("notional") or info.get("notional")))


def _configured_leverage(configuration: Mapping[str, Any]) -> float:
    info = configuration.get("info") or {}
    return _float(
        configuration.get("leverage")
        or configuration.get("longLeverage")
        or configuration.get("shortLeverage")
        or info.get("leverage")
    )


def _fetch_all_open_orders(exchange: Any) -> list[dict[str, Any]]:
    options = getattr(exchange, "options", None)
    if not isinstance(options, dict):
        return call_with_time_sync_retry(
            exchange, exchange.fetch_open_orders, retry_attempts=2
        )

    warning_key = "warnOnFetchOpenOrdersWithoutSymbol"
    sentinel = object()
    previous = options.get(warning_key, sentinel)
    # This is an intentional once-per-preflight, all-symbol USD-M account audit.
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


def build_pilot_account_preflight(
    settings: Settings,
    *,
    exchange: Any | None = None,
) -> dict[str, Any]:
    if not settings.contract_market:
        raise ValueError("MiniTrend pilot preflight requires the USD-M futures market")
    result: dict[str, Any] = {
        "schema_version": PILOT_PREFLIGHT_VERSION,
        "artifact_type": "mini_trend_um_pilot_account_preflight",
        "created_at": utc_now().isoformat(),
        "meta": {
            "read_only": True,
            "private_api_order_attempted": False,
            "mutating_account_method_attempted": False,
            "live_orders_allowed": False,
        },
        "contract_hash": LIVE_PILOT_CONTRACT.contract_hash,
        "account": {
            "credentials_present": bool(
                settings.binance_api_key and settings.binance_api_secret
            ),
            "permissions": {},
            "balance": {},
            "position_mode": {},
            "nonzero_positions": [],
            "top3_configuration": {},
            "open_order_count": None,
        },
        "evidence": {},
        "diagnostics": {
            "errors": {},
            "gates": {},
            "blockers": [],
            "verdict": "blocked_account_preflight",
            "live_orders_allowed": False,
        },
    }
    evidence = {
        "configured_exchange_route_ok": False,
        "public_api_ok": False,
        "credentials_ok": False,
        "api_key_reading_enabled": False,
        "api_key_spot_margin_disabled": False,
        "api_key_withdrawal_disabled": False,
        "api_key_futures_enabled": False,
        "api_key_ip_restricted": False,
        "account_balance_audit_complete": False,
        "available_balance_usdt": None,
        "position_mode_oneway": False,
        "position_audit_complete": False,
        "unmanaged_position_count": None,
        "account_flat": False,
        "open_order_audit_complete": False,
        "open_order_count": None,
        "isolated_one_x_verified": False,
    }
    result["evidence"] = evidence
    if not result["account"]["credentials_present"]:
        result["diagnostics"]["errors"]["credentials"] = "missing_api_credentials"
        return _finalize(result)

    client = exchange or build_exchange(settings, private=True)
    try:
        markets = call_with_time_sync_retry(
            client,
            client.load_markets,
            sync_before=True,
            retry_attempts=2,
        )
        resolved = resolve_market_symbols(markets, _CONFIGURED_SYMBOLS, settings)
        result["account"]["resolved_symbols"] = list(resolved)
        evidence["configured_exchange_route_ok"] = True
        evidence["public_api_ok"] = len(resolved) == len(TOP3)
    except Exception as exc:
        result["diagnostics"]["errors"]["public_api"] = _safe_error(exc, settings)
        return _finalize(result)

    try:
        balance = call_with_time_sync_retry(client, client.fetch_balance, retry_attempts=2)
        quote = extract_quote_balance(balance, settings)
        result["account"]["balance"] = quote
        evidence["credentials_ok"] = True
        evidence["account_balance_audit_complete"] = True
        evidence["available_balance_usdt"] = quote["quote_free"]
    except Exception as exc:
        result["diagnostics"]["errors"]["balance"] = _safe_error(exc, settings)
        return _finalize(result)

    try:
        permissions = _api_restrictions(client)
        result["account"]["permissions"] = permissions or {}
        if permissions is None:
            result["diagnostics"]["errors"]["permissions"] = "api_restrictions_unavailable"
        else:
            evidence["api_key_reading_enabled"] = permissions["enableReading"]
            evidence["api_key_spot_margin_disabled"] = not permissions[
                "enableSpotAndMarginTrading"
            ]
            evidence["api_key_withdrawal_disabled"] = not permissions[
                "enableWithdrawals"
            ]
            evidence["api_key_futures_enabled"] = permissions["enableFutures"]
            evidence["api_key_ip_restricted"] = permissions["ipRestrict"]
    except Exception as exc:
        result["diagnostics"]["errors"]["permissions"] = _safe_error(exc, settings)

    try:
        mode = call_with_time_sync_retry(
            client,
            client.fetch_position_mode,
            params={"subType": "linear"},
            retry_attempts=2,
        )
        hedged = bool(mode.get("hedged"))
        result["account"]["position_mode"] = {"hedged": hedged}
        evidence["position_mode_oneway"] = not hedged
    except Exception as exc:
        result["diagnostics"]["errors"]["position_mode"] = _safe_error(exc, settings)

    try:
        all_positions = call_with_time_sync_retry(
            client, client.fetch_positions, retry_attempts=2
        )
        nonzero = []
        resolved_set = set(result["account"]["resolved_symbols"])
        unmanaged = 0
        for position in all_positions:
            contracts = _position_contracts(position)
            if contracts <= 0.0:
                continue
            symbol = _position_symbol(position)
            side = _position_side(position)
            nonzero.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "contracts": contracts,
                    "notional_usdt": _position_notional(position),
                    "leverage": _position_leverage(position),
                    "margin_mode": _position_margin_mode(position),
                }
            )
            unmanaged += int(symbol not in resolved_set or side != "long")
        result["account"]["nonzero_positions"] = nonzero
        evidence["position_audit_complete"] = True
        evidence["unmanaged_position_count"] = unmanaged
        evidence["account_flat"] = len(nonzero) == 0
    except Exception as exc:
        result["diagnostics"]["errors"]["positions"] = _safe_error(exc, settings)

    try:
        symbols = list(result["account"]["resolved_symbols"])
        leverages = call_with_time_sync_retry(
            client,
            client.fetch_leverages,
            symbols,
            params={"subType": "linear"},
            retry_attempts=2,
        )
        margin_modes = call_with_time_sync_retry(
            client,
            client.fetch_margin_modes,
            symbols,
            params={"subType": "linear"},
            retry_attempts=2,
        )
        configuration = {}
        for symbol in symbols:
            leverage = leverages.get(symbol) if isinstance(leverages, Mapping) else None
            margin_mode = (
                margin_modes.get(symbol) if isinstance(margin_modes, Mapping) else None
            )
            configuration[symbol] = {
                "present": isinstance(leverage, Mapping)
                and isinstance(margin_mode, Mapping),
                "leverage": _configured_leverage(leverage or {}),
                "margin_mode": _position_margin_mode(margin_mode or {}),
            }
        result["account"]["top3_configuration"] = configuration
        evidence["isolated_one_x_verified"] = all(
            row["present"]
            and row["leverage"] == float(LIVE_PILOT_CONTRACT.exchange_leverage)
            and row["margin_mode"] == LIVE_PILOT_CONTRACT.margin_mode
            for row in configuration.values()
        )
    except Exception as exc:
        result["diagnostics"]["errors"]["top3_configuration"] = _safe_error(
            exc, settings
        )

    try:
        orders = _fetch_all_open_orders(client)
        result["account"]["open_order_count"] = len(orders)
        evidence["open_order_audit_complete"] = True
        evidence["open_order_count"] = len(orders)
    except Exception as exc:
        result["diagnostics"]["errors"]["open_orders"] = _safe_error(exc, settings)
    return _finalize(result)


def _finalize(result: dict[str, Any]) -> dict[str, Any]:
    evidence = result["evidence"]
    available = evidence["available_balance_usdt"]
    gates = {
        "configured_exchange_route": evidence["configured_exchange_route_ok"],
        "public_api": evidence["public_api_ok"],
        "private_credentials": evidence["credentials_ok"],
        "reading_enabled": evidence["api_key_reading_enabled"],
        "withdrawal_disabled": evidence["api_key_withdrawal_disabled"],
        "futures_enabled": evidence["api_key_futures_enabled"],
        "ip_restricted": evidence["api_key_ip_restricted"],
        "balance_audited": evidence["account_balance_audit_complete"],
        "pilot_capital_available": (
            available is not None
            and float(available) + 1e-12 >= LIVE_PILOT_CONTRACT.minimum_capital_usdt
        ),
        "position_mode_oneway": evidence["position_mode_oneway"],
        "position_audited": evidence["position_audit_complete"],
        "no_unmanaged_positions": evidence["unmanaged_position_count"] == 0,
        "open_orders_audited": evidence["open_order_audit_complete"],
        "isolated_one_x_verified": evidence["isolated_one_x_verified"],
    }
    passed = all(gates.values())
    result["diagnostics"]["gates"] = gates
    result["diagnostics"]["blockers"] = [
        name for name, value in gates.items() if not value
    ]
    result["diagnostics"]["verdict"] = (
        "account_preflight_pass" if passed else "blocked_account_preflight"
    )
    return result


def write_pilot_account_preflight_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-pilot-preflight",
        path_key="artifact_path",
        default_filename="mini_trend_um_pilot_preflight.json",
        explicit_path=explicit_path,
    )
