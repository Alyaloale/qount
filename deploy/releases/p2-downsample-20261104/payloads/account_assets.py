"""Read-only Binance wallet totals, futures PnL and persistent asset observations.

Wallet overview is authoritative for cross-wallet totals: never add futures collateral or
PnL to it a second time. Futures equity and PnL are shown as separate diagnostics.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from qount.binance_assets import asset_by_execution_symbol


def _number(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("boolean is not an amount")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite amount")
    return result


def _time(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("account observation needs timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _market(name: str) -> str | None:
    compact = "".join(c for c in name.lower() if c.isalnum())
    if compact in {"umfutures", "usdmfutures", "usdsmfutures", "usdtfutures", "usdtmfutures", "usdtmarginedfutures"}:
        return "usdm"
    if compact in {"coinmfutures", "coinmarginedfutures"}:
        return "coinm"
    return None


def collect_asset_overview(exchange: Any) -> dict[str, Any]:
    """Only four explicit GET endpoints; no order, transfer or account mutations."""
    started = datetime.now(timezone.utc).isoformat()
    result: dict[str, Any] = {
        "schema_version": 1, "started_at": started, "observed_at": started,
        "currency": "USDT", "status": "MISSING", "wallets": [],
        "reported_total_usdt": None, "futures_equity_usdt": None,
        "futures_unrealized_pnl_usdt": None, "futures_positions": [],
        "usdm_wallet_balance_usdt": None, "usdm_available_balance_usdt": None,
        "usdm_margin_balance_usdt": None,
        "futures_positions_complete": False, "errors": {},
        "total_basis": "Binance wallet overview; futures PnL is not added again",
        "pnl_scope": "Binance USD-M USDT collateral and USDT-settled PnL only; other collateral unvalued",
        "unvalued_collateral_assets": [],
        "valuation_basis": "USD-M USDT-settled futures amounts",
        "source_endpoints": [], "read_only": True,
        "safety": {"research_only": True, "orders_authorized": False},
    }
    try:
        raw = exchange.sapiGetAssetWalletBalance({"quoteAsset": "USDT"})
        if not isinstance(raw, list) or not raw:
            raise ValueError("wallet overview must be a nonempty list")
        seen: set[str] = set()
        wallets = []
        for row in raw:
            name = str(row["walletName"]).strip()
            if not name or name.casefold() in seen or not isinstance(row.get("activate"), bool):
                raise ValueError("invalid or duplicated wallet")
            seen.add(name.casefold())
            wallets.append({"name": name, "active": row["activate"],
                            "balance_usdt": _number(row["balance"]),
                            "market": _market(name), "unrealized_pnl_usdt": None,
                            "equity_usdt": None, "pnl_status": "NOT_COLLECTED" if _market(name) == "coinm" else "NOT_APPLICABLE"})
        market_names = [w["market"] for w in wallets if w["market"]]
        if len(market_names) != len(set(market_names)):
            raise ValueError("duplicated futures wallet scope")
        result["wallets"] = wallets
        result["reported_total_usdt"] = sum(row["balance_usdt"] for row in wallets)
        result["source_endpoints"].append("GET /sapi/v1/asset/wallet/balance?quoteAsset=USDT")
    except Exception as exc:
        # Never persist raw exception messages: signed URLs may contain authentication material.
        result["errors"]["wallet_overview"] = type(exc).__name__
        result["observed_at"] = datetime.now(timezone.utc).isoformat()
        return result

    prices = {"USDT": 1.0}
    totals: dict[str, tuple[float, float, list[dict[str, Any]]]] = {}
    futures_wallets = [w for w in wallets if w["market"] == "usdm"]
    markets = {w["market"] for w in futures_wallets if w["active"]}
    for market in sorted(markets):
        try:
            account = exchange.fapiPrivateV3GetAccount({})
            assets, raw_positions = account["assets"], account["positions"]
            if not isinstance(assets, list) or not isinstance(raw_positions, list):
                raise ValueError("incomplete futures account")
            unvalued = [str(a["asset"]) for a in assets if str(a["asset"]) != "USDT" and
                        any(_number(a[k]) != 0 for k in ("walletBalance", "unrealizedProfit", "marginBalance"))]
            if unvalued:
                result["unvalued_collateral_assets"] = sorted(set(unvalued))
                result["errors"]["unvalued_collateral"] = "NON_USDT_NOT_VALUED"
            equity, pnl = 0.0, 0.0
            for asset in assets:
                if str(asset["asset"]) != "USDT":
                    continue  # Never value another stablecoin as USDT at par.
                collateral = _number(asset["walletBalance"])
                unrealized = _number(asset["unrealizedProfit"])
                margin = _number(asset["marginBalance"])
                if not math.isclose(collateral + unrealized, margin, rel_tol=1e-6, abs_tol=1e-7):
                    raise ValueError("futures equity identity mismatch")
                if collateral == 0 and unrealized == 0 and margin == 0:
                    continue
                rate = prices[str(asset["asset"])]
                equity += margin * rate
                pnl += unrealized * rate
            positions = []
            for row in raw_positions:
                amount = _number(row["positionAmt"])
                if amount == 0:
                    continue
                item = {"symbol": str(row["symbol"]), "side": "short" if amount < 0 or row.get("positionSide") == "SHORT" else "long",
                        "quantity": abs(amount), "market": market,
                        "unrealized_pnl": _number(row["unrealizedProfit"]),
                        "pnl_currency": "USDT" if market == "usdm" and str(row["symbol"]).endswith("USDT") else None,
                        "notional_usdt": None}
                asset = asset_by_execution_symbol(item["symbol"])
                item["asset_id"] = asset.asset_id if asset else None
                item["strategy_asset"] = bool(asset and asset.status == "active")
                item["quantity_unit"] = "base_asset"
                symbol = str(row["symbol"])
                settlement = next((a["asset"] for a in sorted(assets, key=lambda a: len(str(a["asset"])), reverse=True) if symbol.endswith(str(a["asset"]))), None)
                if settlement != "USDT":
                    raise ValueError("usd_m_symbol_not_usdt_settled")
                item["pnl_currency"] = "USDT"
                native_pnl = item["unrealized_pnl"]
                item["unrealized_pnl_usdt"] = native_pnl
                if str(row["symbol"]).endswith("USDT") and "notional" in row:
                    item["notional_usdt"] = abs(_number(row["notional"]))
                positions.append(item)
            usdt_values = {}
            if market == "usdm":
                usdt = next((a for a in assets if a["asset"] == "USDT"), None)
                if usdt is not None:
                    usdt_values = {
                        "usdm_wallet_balance_usdt": _number(usdt["walletBalance"]),
                        "usdm_available_balance_usdt": _number(usdt["availableBalance"]),
                        "usdm_margin_balance_usdt": _number(usdt["marginBalance"]),
                    }
            totals[market] = (equity, pnl, positions)
            result.update(usdt_values)
            result["source_endpoints"].append("GET /fapi/v3/account")
        except Exception as exc:
            result["errors"][market] = type(exc).__name__

    for wallet in futures_wallets:
        if wallet["market"] in totals:
            eq, pnl, _ = totals[wallet["market"]]
            wallet.update(equity_usdt=eq, unrealized_pnl_usdt=pnl, pnl_status="AVAILABLE",
                          pnl_scope="USDT collateral and USDT-settled PnL only")
        elif not wallet["active"] and wallet["balance_usdt"] == 0:
            wallet.update(equity_usdt=0.0, unrealized_pnl_usdt=0.0, pnl_status="INACTIVE")
        else:
            wallet["pnl_status"] = "MISSING"
    complete = bool(futures_wallets) and all(w["pnl_status"] in {"AVAILABLE", "INACTIVE"} for w in futures_wallets)
    if complete:
        result["futures_equity_usdt"] = sum(w["equity_usdt"] for w in futures_wallets)
        result["futures_unrealized_pnl_usdt"] = sum(w["unrealized_pnl_usdt"] for w in futures_wallets)
    result["futures_positions"] = [p for _, _, ps in totals.values() for p in ps]
    result["futures_positions_complete"] = complete
    result["status"] = "AVAILABLE" if complete and not result["errors"] else "PARTIAL"
    result["observed_at"] = datetime.now(timezone.utc).isoformat()
    result["collection_span_seconds"] = (datetime.fromisoformat(result["observed_at"]) - datetime.fromisoformat(started)).total_seconds()
    return result


def append_asset_history(path: Path, overview: dict[str, Any]) -> None:
    """Append one real observation; a same-time conflict is never silently overwritten."""
    if path.is_symlink():
        raise ValueError("asset history cannot be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = _time(overview["observed_at"])
    encoded = json.dumps(overview, ensure_ascii=True, sort_keys=True, allow_nan=False)
    with sqlite3.connect(path, timeout=15) as conn:
        os.chmod(path, 0o600)
        conn.execute("CREATE TABLE IF NOT EXISTS asset_observations (observed_at TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        existing = conn.execute("SELECT payload FROM asset_observations WHERE observed_at=?", (stamp,)).fetchone()
        if existing and existing[0] != encoded:
            raise ValueError("asset history timestamp conflict")
        conn.execute("INSERT OR IGNORE INTO asset_observations VALUES (?,?)", (stamp, encoded))


def _downsample_resolution(days: int, resolution: str | None) -> str:
    if resolution in {"raw", "1h", "6h"}:
        return resolution
    return "raw" if days <= 7 else "1h" if days <= 90 else "6h"


def _downsample_bucket(observed: str, resolution: str) -> str:
    parsed = datetime.fromisoformat(observed.replace("Z", "+00:00"))
    if resolution == "1h":
        parsed = parsed.replace(minute=0, second=0, microsecond=0)
    elif resolution == "6h":
        parsed = parsed.replace(hour=parsed.hour - parsed.hour % 6, minute=0, second=0, microsecond=0)
    return parsed.isoformat()


def _downsample_history(points: list[dict[str, Any]], resolution: str) -> list[dict[str, Any]]:
    """Keep the first point of each (time bucket, wallet_scope) run plus the final point.

    Grouping on wallet_scope as well preserves every coverage change the chart
    uses to break the line, so downsampling never bridges a wallet-scope gap.
    """
    if resolution == "raw" or len(points) <= 2:
        return points
    kept: list[dict[str, Any]] = []
    group: object = object()
    for point in points:
        key = (_downsample_bucket(point["observed_at"], resolution), tuple(point.get("wallet_scope") or ()))
        if key != group:
            kept.append(point)
            group = key
    if kept[-1] is not points[-1]:
        kept.append(points[-1])
    return kept


def read_asset_history(path: Path, days: int = 30, resolution: str | None = None) -> dict[str, Any]:
    """Read existing observations only; API requests do not create history."""
    resolution = _downsample_resolution(days, resolution)
    empty = {"currency": "USDT", "points": [], "observation_count": 0,
             "status": "MISSING", "error": None, "resolution": resolution,
             "downsampled": resolution != "raw",
             "basis": "Observed asset values; deposits and withdrawals are not investment returns"}
    if not path.is_file():
        return empty
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=5) as conn:
            rows = conn.execute("SELECT observed_at,payload FROM asset_observations WHERE observed_at>=? ORDER BY observed_at", (cutoff,)).fetchall()
        points = []
        for observed, encoded in rows:
            row = json.loads(encoded)
            points.append({"observed_at": observed, "reported_total_usdt": row.get("reported_total_usdt"),
                           "futures_equity_usdt": row.get("futures_equity_usdt"),
                           "futures_unrealized_pnl_usdt": row.get("futures_unrealized_pnl_usdt"),
                           "status": row["status"],
                           "wallet_scope": sorted(w["name"] for w in row.get("wallets", []))})
        raw_count = len(points)
        return empty | {"status": "AVAILABLE" if points else "EMPTY",
                        "points": _downsample_history(points, resolution),
                        "observation_count": raw_count}
    except (sqlite3.Error, ValueError, KeyError) as exc:
        return empty | {"status": "ERROR", "error": type(exc).__name__}
