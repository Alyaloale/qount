"""Account snapshot route for qount API."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Query

from qount.api.schemas import (
    AccountSnapshot,
    BalanceItem,
    LineSafety,
    LineSource,
    PositionItem,
)
from qount.binance_assets import asset_by_execution_symbol, load_binance_assets
from qount.operations.account_assets import read_asset_history
from qount.operations.account_trades import read_trade_records, strategy_accounting
from qount.operations.account_performance import read_account_performance

router = APIRouter(prefix="/account", tags=["account"])

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compute_sha256(path: str) -> Optional[str]:
    if not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _execution_symbol(value: object) -> str:
    """Normalize CCXT symbols such as ``CL/USDT:USDT`` to ``CLUSDT``."""
    raw = str(value or "").strip().upper()
    if "/" in raw:
        base, quote = raw.split("/", 1)
        return f"{base}{quote.split(':', 1)[0]}"
    return raw


def _annotate_asset_positions(overview: dict) -> dict:
    """Attach the shared identity map to observed USD-M positions when known."""
    positions = overview.get("futures_positions")
    if not isinstance(positions, list):
        return overview
    assets = load_binance_assets()
    annotated = []
    for row in positions:
        if not isinstance(row, dict):
            annotated.append(row)
            continue
        symbol = _execution_symbol(row.get("symbol"))
        asset = asset_by_execution_symbol(symbol, assets=assets)
        item = dict(row)
        item["execution_symbol"] = symbol
        item["asset_id"] = asset.asset_id if asset else None
        item["signal_symbol"] = asset.signal_symbol if asset else None
        item["venue"] = asset.venue if asset else "binance_usdm" if row.get("market") == "usdm" else None
        item["strategy_asset"] = bool(asset and asset.status == "active")
        annotated.append(item)
    result = overview | {"futures_positions": annotated}
    return result


@router.get("", response_model=AccountSnapshot)
def get_account() -> AccountSnapshot:
    """Return the current Binance USD-M account observation.

    Historical paper packages remain available to their research adapters, but the
    main account surface must never present one as the user's current account.
    """
    return load_live_account_snapshot()


# ---------------------------------------------------------------------------
# Live read-only exchange account
# ---------------------------------------------------------------------------

#: Written every ~5 minutes on the VPS by qount-dashboard-account-observer, which reads the
#: exchange through a read-only key. This process never touches the key itself.
DEFAULT_OBSERVATION_SOURCE = "/var/lib/qount/blocked_runtime_observation.json"
DEFAULT_ONE_ATR_RESULT = "/var/lib/qount/1atr/live-result.json"
DEFAULT_ONE_ATR_STORE = "/var/lib/qount/1atr/execution.sqlite3"
DEFAULT_ONE_ATR_ARM = "/var/lib/qount/1atr/arm.json"
DEFAULT_ONE_ATR_HALT = "/var/lib/qount/1atr/HALT"


def load_live_account_snapshot() -> AccountSnapshot:
    """Map the host's read-only account observation onto an AccountSnapshot.

    The observation already exists on the host; nothing here talks to an exchange. When the
    file is absent or unreadable the snapshot reports the failure and carries no balance —
    it must never fall back to the PAPER figures, which would present a simulation number as
    if it were the real account.
    """
    path = os.environ.get("QOUNT_ACCOUNT_OBSERVATION_PATH", DEFAULT_OBSERVATION_SOURCE)

    if not os.path.exists(path):
        return AccountSnapshot(
            as_of=_now_iso(),
            mode="LIVE_READONLY",
            source_kind="binance_api",
            nav=0.0,
            cash=0.0,
            positions=[],
            positions_status="MISSING",
            currency="USDT",
            balances=[],
            read_only=True,
            source=LineSource(path=path, sha256=None, produced_at=None),
            safety=LineSafety(research_only=True, orders_authorized=False),
            error=(
                "OBSERVATION_NOT_FOUND: the read-only account observation is produced on the host "
                "that holds the exchange key and is not present here."
            ),
        )

    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        observation = payload.get("account_observation") or {}
    except Exception as exc:
        return AccountSnapshot(
            as_of=_now_iso(),
            mode="LIVE_READONLY",
            source_kind="binance_api",
            nav=0.0,
            cash=0.0,
            positions=[],
            currency="USDT",
            balances=[],
            read_only=True,
            source=LineSource(path=path, sha256=_compute_sha256(path), produced_at=None),
            safety=LineSafety(research_only=True, orders_authorized=False),
            error=f"OBSERVATION_UNREADABLE: {type(exc).__name__}",
        )

    quote_asset = str(observation.get("quote_asset") or "USDT")
    try:
        wallet_balance = float(observation["wallet_balance"])
        available_balance = float(observation["available_balance"])
        if not math.isfinite(wallet_balance) or not math.isfinite(available_balance) or available_balance < 0:
            raise ValueError("invalid balances")
    except (KeyError, TypeError, ValueError):
        return AccountSnapshot(
            as_of=_now_iso(), mode="LIVE_READONLY", source_kind="binance_api", nav=0.0,
            cash=0.0, positions=[], currency="USDT", balances=[], read_only=True,
            positions_status="MISSING",
            source=LineSource(path=path, sha256=_compute_sha256(path), produced_at=None),
            safety=LineSafety(research_only=True, orders_authorized=False),
            error="OBSERVATION_INCOMPLETE: required wallet and available balances are absent or invalid.",
        )
    observed_at = observation.get("observed_at")
    if not isinstance(observed_at, str) or not observed_at.strip():
        return AccountSnapshot(
            as_of="unknown", mode="LIVE_READONLY", source_kind="binance_api", nav=0.0,
            cash=0.0, positions=[], currency=quote_asset, balances=[], read_only=True,
            positions_status="MISSING",
            source=LineSource(path=path, sha256=_compute_sha256(path), produced_at=None),
            safety=LineSafety(research_only=True, orders_authorized=False),
            error="OBSERVATION_INCOMPLETE: observed_at is absent; freshness cannot be established.",
        )
    try:
        parsed_time = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        if parsed_time.tzinfo is None:
            raise ValueError("observation timestamp needs a timezone")
    except ValueError:
        return AccountSnapshot(
            as_of="unknown", mode="LIVE_READONLY", source_kind="binance_api", nav=0.0,
            cash=0.0, positions=[], currency=quote_asset, balances=[], read_only=True,
            positions_status="MISSING",
            source=LineSource(path=path, sha256=_compute_sha256(path), produced_at=None),
            safety=LineSafety(research_only=True, orders_authorized=False),
            error="OBSERVATION_INCOMPLETE: observed_at is invalid.",
        )
    observed_at = observed_at.strip()
    raw_positions = observation.get("positions")
    if not isinstance(raw_positions, list):
        return AccountSnapshot(
            as_of=observed_at, mode="LIVE_READONLY", source_kind="binance_api", nav=0.0,
            cash=0.0, positions=[], currency=quote_asset, balances=[], read_only=True,
            positions_status="MISSING",
            source=LineSource(path=path, sha256=_compute_sha256(path), produced_at=observed_at),
            safety=LineSafety(research_only=True, orders_authorized=False),
            error="OBSERVATION_INCOMPLETE: positions must be an explicit list.",
        )

    balances = [
        BalanceItem(
            asset=quote_asset,
            free=available_balance,
            locked=max(0.0, wallet_balance - available_balance),
        )
    ]

    positions: list[PositionItem] = []
    for row in raw_positions:
        if not isinstance(row, dict):
            return AccountSnapshot(
                as_of=observed_at, mode="LIVE_READONLY", source_kind="binance_api", nav=0.0,
                cash=0.0, positions=[], currency=quote_asset, balances=[], read_only=True,
                positions_status="MISSING",
                source=LineSource(path=path, sha256=_compute_sha256(path), produced_at=observed_at),
                safety=LineSafety(research_only=True, orders_authorized=False),
                error="OBSERVATION_INCOMPLETE: positions contains an invalid row.",
            )
        symbol = row.get("symbol")
        if not symbol:
            return AccountSnapshot(
                as_of=observed_at, mode="LIVE_READONLY", source_kind="binance_api", nav=0.0,
                cash=0.0, positions=[], currency=quote_asset, balances=[], read_only=True,
                positions_status="MISSING",
                source=LineSource(path=path, sha256=_compute_sha256(path), produced_at=observed_at),
                safety=LineSafety(research_only=True, orders_authorized=False),
                error="OBSERVATION_INCOMPLETE: a position has no symbol.",
            )
        try:
            quantity = float(row["quantity"])
            notional = float(row["notional"])
            if not math.isfinite(quantity) or not math.isfinite(notional) or notional < 0:
                raise ValueError("invalid position values")
        except (KeyError, TypeError, ValueError):
            return AccountSnapshot(
                as_of=observed_at, mode="LIVE_READONLY", source_kind="binance_api", nav=0.0,
                cash=0.0, positions=[], currency=quote_asset, balances=[], read_only=True,
                positions_status="MISSING",
                source=LineSource(path=path, sha256=_compute_sha256(path), produced_at=observed_at),
                safety=LineSafety(research_only=True, orders_authorized=False),
                error="OBSERVATION_INCOMPLETE: a position is missing quantity or notional.",
            )
        execution_symbol = _execution_symbol(symbol)
        mapped_asset = asset_by_execution_symbol(execution_symbol)
        positions.append(PositionItem(
            symbol=execution_symbol, weight=None, quantity=quantity,
            market_value=notional, side=str(row.get("side") or "unknown").lower(),
            asset_id=mapped_asset.asset_id if mapped_asset else None,
            signal_symbol=mapped_asset.signal_symbol if mapped_asset else None,
            execution_symbol=mapped_asset.execution_symbol if mapped_asset else execution_symbol,
            venue="binance_usdm",
        ))

    return AccountSnapshot(
        as_of=observed_at,
        mode="LIVE_READONLY",
        source_kind="binance_api",
        nav=wallet_balance,
        observation_interval_seconds=300,
        cash=available_balance,
        positions=positions,
        positions_status="KNOWN",
        currency=quote_asset,
        balances=balances,
        read_only=True,
        source=LineSource(
            path=path,
            sha256=_compute_sha256(path),
            produced_at=observed_at,
        ),
        safety=LineSafety(research_only=True, orders_authorized=False),
        error=None,
    )


@router.get("/live", response_model=AccountSnapshot)
def get_live_account() -> AccountSnapshot:
    """Return the real read-only exchange account, or an explicit failure."""
    return load_live_account_snapshot()


@router.get("/one-atr")
def get_one_atr_status() -> dict:
    """Return the read-only 1ATR signal, execution receipt and protection state."""
    from qount.operations.account_trades import strategy_accounting
    result_path = Path(os.environ.get("QOUNT_1ATR_RESULT_PATH", DEFAULT_ONE_ATR_RESULT))
    store_path = Path(os.environ.get("QOUNT_1ATR_EXECUTION_STORE", DEFAULT_ONE_ATR_STORE))
    arm_path = Path(os.environ.get("QOUNT_1ATR_ARM_PATH", DEFAULT_ONE_ATR_ARM))
    halt_path = Path(os.environ.get("QOUNT_1ATR_HALT_PATH", DEFAULT_ONE_ATR_HALT))
    response = {
        "status": "MISSING", "read_only": True, "strategy_id": "one_atr_macro_v0_1",
        # This endpoint is read-only even when the strategy has a live receipt.
        # Keep global API order authority separate from the strategy's one-shot arm.
        "execution_mode": "unknown", "orders_authorized": False,
        "strategy_live": False, "execution_authorized": False,
        "global_orders_authorized": False, "research_only": True, "selected": None,
        "orders": [], "protective_orders": [], "arm_status": "missing",
        "halted": halt_path.exists(), "error": None,
    }
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("result_not_object")
        response.update({key: payload.get(key) for key in (
            "strategy_id", "execution_mode", "selected", "auto_action", "execution_blocker", "protection_check",
            "handover", "position", "decision_clock", "risk_fraction", "gross_cap", "maximum_leverage",
            "rejections", "candidate_count", "capital_usdt", "last_decision", "accounting_errors")})
        live = payload.get("execution_mode") in {"live", "auto_live"}
        response["strategy_live"] = live
        response["execution_authorized"] = live and payload.get("orders_authorized") is True
        response["research_only"] = not live
        response["status"] = "AVAILABLE"
        response["last_result_at"] = payload.get("created_at")
        if response["strategy_id"] == "rolling7_risk_no_chase_mr_signal_gap_1atr":
            from qount.research_data.bars import session, NY
            now = datetime.now(timezone.utc)
            next_check = now.replace(minute=0, second=5, microsecond=0)
            if next_check <= now:
                next_check += timedelta(hours=1)
            response["expected_next_check_at"] = next_check.isoformat()
            response["next_entry_at"] = None
            for offset in range(15):
                day = now.astimezone(NY).date()+timedelta(days=offset)
                candidate = datetime(day.year, day.month, day.day, 10, tzinfo=NY)
                if candidate <= now:
                    continue
                try:
                    allowed = session(int(candidate.timestamp()))
                except ValueError:
                    break  # Never extend the production calendar by displaying a date.
                if allowed:
                    response["next_entry_at"] = candidate.astimezone(timezone.utc).isoformat()
                    break
        try:
            created = datetime.fromisoformat(str(payload.get("created_at")).replace("Z", "+00:00"))
            if created.tzinfo is None:
                raise ValueError("result_timezone_missing")
            age = max(0.0, (datetime.now(timezone.utc) - created.astimezone(timezone.utc)).total_seconds())
            if (created.astimezone(timezone.utc)-datetime.now(timezone.utc)).total_seconds() > 60:
                raise ValueError("result_time_in_future")
            response["result_age_seconds"] = age
            hourly = response["strategy_id"] == "rolling7_risk_no_chase_mr_signal_gap_1atr"
            response["result_stale"] = age > (2 * 3600 if hourly else 36 * 3600)
            if response["result_stale"]:
                response["status"] = "STALE"
        except (TypeError, ValueError):
            response["result_stale"] = True
            response["status"] = "STALE"
        execution = payload.get("execution") or {}
        response["last_execution"] = {
            "entry": execution.get("entry"),
            "protective": execution.get("protective"),
            "arm_status": execution.get("arm_status"),
        } if execution else None
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        response["error"] = f"result_unavailable:{type(exc).__name__}"
    try:
        if store_path.is_file():
            with sqlite3.connect(f"file:{store_path.resolve()}?mode=ro", uri=True) as conn:
                conn.row_factory = sqlite3.Row
                all_orders = [dict(row) for row in conn.execute(
                    "SELECT client_order_id,symbol,side,status,executed_quantity,average_price,"
                    "strategy_id,signal_id,order_intent_id,account_record_id FROM orders ORDER BY rowid"
                )]
                response["orders"] = [r for r in all_orders if r["strategy_id"] == response["strategy_id"]]
                response["legacy_orders"] = [r for r in all_orders if r["strategy_id"] != response["strategy_id"]]
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if response["strategy_id"] == "rolling7_risk_no_chase_mr_signal_gap_1atr":
                    if "macro_stops" in tables:
                        response["protective_orders"] = [dict(r) for r in conn.execute(
                            "SELECT parent_client_id AS parent_client_order_id,client_id AS protective_client_order_id,"
                            "symbol,'sell' AS side,quantity,stop_price,status,actual_order_id FROM macro_stops ORDER BY rowid DESC")]
                elif "protective_orders" in tables:
                    response["protective_orders"] = [dict(row) for row in conn.execute(
                        "SELECT parent_client_order_id,protective_client_order_id,symbol,side,quantity,stop_price,status "
                        "FROM protective_orders ORDER BY rowid"
                    )]
    except (OSError, sqlite3.Error) as exc:
        response["error"] = f"execution_store_unavailable:{type(exc).__name__}"
    try:
        if arm_path.is_file():
            arm = json.loads(arm_path.read_text(encoding="utf-8"))
            response["arm_status"] = arm.get("status", "invalid")
    except (OSError, json.JSONDecodeError):
        response["arm_status"] = "invalid"
    trades_path = Path(os.environ.get("QOUNT_ACCOUNT_TRADES_PATH", str(Path(os.environ.get("QOUNT_ACCOUNT_OBSERVATION_PATH", DEFAULT_OBSERVATION_SOURCE)).with_name("account-trades.sqlite3"))))
    response["accounting"] = strategy_accounting(trades_path, store_path, response["strategy_id"])
    response["runtime"] = None
    assets_path = Path(os.environ.get("QOUNT_ACCOUNT_ASSETS_PATH", str(Path(
        os.environ.get("QOUNT_ACCOUNT_OBSERVATION_PATH", DEFAULT_OBSERVATION_SOURCE)).with_name("account-assets.json"))))
    try:
        overview = json.loads(assets_path.read_text())
        runtime = overview["strategy_runtime"]
        stamp = datetime.fromisoformat(runtime["observed_at"].replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc)-stamp).total_seconds()
        if overview.get("read_only") is True and runtime.get("strategy_id") == response["strategy_id"]:
            response["runtime"] = {**runtime, "stale": not -60 <= age <= 900}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass  # An absent runtime observation never invents an active timer.
    return response


@router.get("/assets")
def get_asset_overview() -> dict:
    """All returned Binance wallets and futures PnL, from the host's read-only collector."""
    legacy_path = Path(os.environ.get("QOUNT_ACCOUNT_OBSERVATION_PATH", DEFAULT_OBSERVATION_SOURCE))
    path = Path(os.environ.get("QOUNT_ACCOUNT_ASSETS_PATH", str(legacy_path.with_name("account-assets.json"))))
    missing = {"status": "MISSING", "currency": "USDT", "wallets": [],
               "reported_total_usdt": None, "futures_equity_usdt": None,
               "futures_unrealized_pnl_usdt": None, "read_only": True,
               "futures_positions": [], "futures_positions_complete": False,
               "error": "ASSET_OVERVIEW_NOT_COLLECTED"}
    if not path.is_file():
        return missing
    try:
        overview = json.loads(path.read_text())
        if not isinstance(overview, dict):
            return missing
        if overview.get("currency") != "USDT" or overview.get("read_only") is not True:
            raise ValueError("invalid asset overview identity")
        stamp = datetime.fromisoformat(str(overview["observed_at"]).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("asset observation timezone missing")
        wallets = overview["wallets"]
        if not isinstance(wallets, list):
            raise ValueError("invalid wallets")
        for row in wallets:
            if not isinstance(row.get("name"), str) or not math.isfinite(float(row["balance_usdt"])):
                raise ValueError("invalid wallet amount")
        if len({row["name"].casefold() for row in wallets}) != len(wallets):
            raise ValueError("duplicate wallet names")
        for key in ("reported_total_usdt", "futures_equity_usdt", "futures_unrealized_pnl_usdt"):
            if overview.get(key) is not None and not math.isfinite(float(overview[key])):
                raise ValueError("invalid total")
        total = overview.get("reported_total_usdt")
        if total is not None and not math.isclose(float(total), sum(float(w["balance_usdt"]) for w in wallets), rel_tol=1e-9, abs_tol=1e-7):
            raise ValueError("wallet total mismatch")
        return _annotate_asset_positions(overview)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return missing | {"status": "ERROR", "error": "ASSET_OVERVIEW_UNREADABLE"}


@router.get("/history")
def get_asset_history(days: int = Query(default=30, ge=1, le=365)) -> dict:
    """Historical observations, never a simulated or cash-flow-adjusted return curve."""
    legacy = Path(os.environ.get("QOUNT_ACCOUNT_OBSERVATION_PATH", DEFAULT_OBSERVATION_SOURCE))
    source = Path(os.environ.get("QOUNT_ACCOUNT_ASSETS_PATH", str(legacy.with_name("account-assets.json"))))
    path = Path(os.environ.get("QOUNT_ACCOUNT_HISTORY_PATH", str(source.with_name("account-assets-history.sqlite3"))))
    return read_asset_history(path, days=days)


@router.get("/trades")
def get_account_trade_records(limit: int = Query(default=100, ge=1, le=500)) -> dict:
    """Read existing account records only; never access exchange credentials."""
    legacy=Path(os.environ.get("QOUNT_ACCOUNT_OBSERVATION_PATH",DEFAULT_OBSERVATION_SOURCE))
    path = Path(os.environ.get("QOUNT_ACCOUNT_TRADES_PATH", str(legacy.with_name("account-trades.sqlite3"))))
    store = Path(os.environ.get("QOUNT_1ATR_EXECUTION_STORE", DEFAULT_ONE_ATR_STORE))
    return read_trade_records(path, limit=limit, execution_path=store)


@router.get("/performance")
def get_account_performance(days: int = Query(default=30, ge=1, le=365)) -> dict:
    """Cash-flow-adjusted real USDT futures returns; never contacts the exchange."""
    legacy = Path(os.environ.get("QOUNT_ACCOUNT_OBSERVATION_PATH", DEFAULT_OBSERVATION_SOURCE))
    assets = Path(os.environ.get("QOUNT_ACCOUNT_ASSETS_PATH", str(legacy.with_name("account-assets.json"))))
    history = Path(os.environ.get("QOUNT_ACCOUNT_HISTORY_PATH", str(assets.with_name("account-assets-history.sqlite3"))))
    trades = Path(os.environ.get("QOUNT_ACCOUNT_TRADES_PATH", str(legacy.with_name("account-trades.sqlite3"))))
    return read_account_performance(history, trades, days)
