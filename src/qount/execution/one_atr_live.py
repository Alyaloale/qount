"""Arm-gated 1ATR entry plus protective stop execution.

This adapter is deliberately separate from the historical research runner and
the MiniTrend pilot. It records the entry and protective order in the small
Binance execution SQLite store before consuming a one-shot arm. Without a
valid arm, it cannot call a mutating exchange method.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN
from pathlib import Path
from typing import Any, Mapping

from qount.contracts import canonical_hash
from qount.execution.binance_usdm import (
    BinanceExecutionStore,
    BinanceUsdMExecution,
    ExecutionContractError,
    OrdersNotAuthorized,
    normalize_order_response,
    lookup_usdm_rule,
)


class OneAtrArmError(ExecutionContractError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise OneAtrArmError("arm_expiry_invalid") from exc
    if parsed.tzinfo is None:
        raise OneAtrArmError("arm_expiry_timezone_missing")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class OneAtrArm:
    arm_id: str
    strategy_id: str
    plan_hash: str
    expires_at: str
    confirmation_hash: str
    status: str
    arm_hash: str

    @classmethod
    def load(cls, path: str | os.PathLike[str], *, confirmation: str, plan: Mapping[str, Any]) -> OneAtrArm:
        target = Path(path)
        if target.is_symlink() or not target.is_file():
            raise OneAtrArmError("arm_file_missing_or_symlink")
        if target.stat().st_mode & 0o077:
            raise OneAtrArmError("arm_file_permissions_invalid")
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OneAtrArmError("arm_file_invalid") from exc
        if not isinstance(payload, dict):
            raise OneAtrArmError("arm_payload_invalid")
        expected_plan_hash = canonical_hash(dict(plan))
        expected_confirmation = canonical_hash({"confirmation": confirmation})
        core = {key: payload.get(key) for key in (
            "arm_id", "strategy_id", "plan_hash", "expires_at", "confirmation_hash", "status"
        )}
        if core["status"] != "armed":
            raise OneAtrArmError("arm_not_armed")
        if core["plan_hash"] != expected_plan_hash:
            raise OneAtrArmError("arm_plan_hash_mismatch")
        if core["confirmation_hash"] != expected_confirmation:
            raise OneAtrArmError("arm_confirmation_mismatch")
        if _parse_time(str(core["expires_at"])) <= _now():
            raise OneAtrArmError("arm_expired")
        if payload.get("arm_hash") != canonical_hash(core):
            raise OneAtrArmError("arm_hash_invalid")
        return cls(**core, arm_hash=str(payload["arm_hash"]))

    def consume(self, path: str | os.PathLike[str]) -> None:
        target = Path(path)
        payload = json.loads(target.read_text(encoding="utf-8"))
        core = {key: payload.get(key) for key in (
            "arm_id", "strategy_id", "plan_hash", "expires_at", "confirmation_hash"
        )}
        core["status"] = "used"
        payload.update(core, arm_hash=canonical_hash(core))
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)


def create_arm(path: str | os.PathLike[str], *, arm_id: str, strategy_id: str,
               plan: Mapping[str, Any], expires_at: str, confirmation: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.parent.chmod(0o700)
    core = {
        "arm_id": arm_id,
        "strategy_id": strategy_id,
        "plan_hash": canonical_hash(dict(plan)),
        "expires_at": expires_at,
        "confirmation_hash": canonical_hash({"confirmation": confirmation}),
        "status": "armed",
    }
    payload = core | {"arm_hash": canonical_hash(core)}
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(target, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")


class OneAtrLiveExecutor:
    def __init__(self, exchange: Any, store: BinanceExecutionStore) -> None:
        self.exchange = exchange
        self.store = store
        self.execution = BinanceUsdMExecution(exchange, store)
        with sqlite3.connect(self.store.path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS protective_orders (
                  parent_client_order_id TEXT PRIMARY KEY,
                  protective_client_order_id TEXT UNIQUE NOT NULL,
                  symbol TEXT NOT NULL,
                  side TEXT NOT NULL,
                  quantity REAL NOT NULL,
                  stop_price REAL NOT NULL,
                  status TEXT NOT NULL,
                  payload TEXT NOT NULL
                )
            """)

    def _protective(self, parent_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.store.path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM protective_orders WHERE parent_client_order_id=?", (parent_id,)).fetchone()
            return dict(row) if row else None

    def _save_protective(self, *, parent_id: str, client_id: str, symbol: str, side: str,
                         quantity: float, stop_price: float, status: str, payload: Mapping[str, Any]) -> None:
        encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"))
        with sqlite3.connect(self.store.path) as conn:
            conn.execute("""
                INSERT INTO protective_orders(parent_client_order_id, protective_client_order_id, symbol, side,
                                              quantity, stop_price, status, payload)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(parent_client_order_id) DO UPDATE SET status=excluded.status, payload=excluded.payload
            """, (parent_id, client_id, symbol, side, quantity, stop_price, status, encoded))

    def _rounded_stop(self, *, symbol: str, side: str, stop_price: float) -> float:
        rule = lookup_usdm_rule(self.exchange, symbol)
        value = Decimal(str(stop_price)) / Decimal(str(rule.tick_size))
        rounding = ROUND_DOWN if side == "buy" else ROUND_CEILING
        rounded = value.to_integral_value(rounding=rounding) * Decimal(str(rule.tick_size))
        result = float(rounded)
        if result <= 0:
            raise OneAtrArmError("protective_stop_invalid")
        return result

    def _ensure_protective(self, *, plan: Mapping[str, Any], entry_id: str,
                           filled_quantity: float, stop_price: float) -> dict[str, Any]:
        protective_side = "sell" if str(plan["side"]).lower() == "buy" else "buy"
        stop_price = self._rounded_stop(symbol=str(plan["symbol"]), side=str(plan["side"]).lower(), stop_price=stop_price)
        entry_price = float(plan["price"])
        if (protective_side == "sell" and not stop_price < entry_price) or (protective_side == "buy" and not stop_price > entry_price):
            raise OneAtrArmError("protective_stop_on_wrong_side")
        protective_id = f"q1atr-stop-{canonical_hash({'entry': entry_id, 'stop': stop_price})[:16]}"
        protective_payload = dict(
            strategy_id=plan["strategy_id"], signal_id=plan["signal_id"],
            order_intent_id=f"{plan['order_intent_id']}:protective",
            parent_client_order_id=entry_id, order_type="STOP_MARKET",
            stop_price=stop_price, reduce_only=True,
        )
        claimed = self.store.create_order(client_order_id=protective_id, symbol=str(plan["symbol"]),
                                          side=protective_side, quantity=filled_quantity,
                                          payload=protective_payload)
        protective = self.store.get_order(protective_id)
        if claimed:
            try:
                response = self.exchange.create_order(
                    str(plan["symbol"]), "STOP_MARKET", protective_side, filled_quantity, None,
                    {"stopPrice": stop_price, "reduceOnly": True, "workingType": "MARK_PRICE",
                     "newClientOrderId": protective_id},
                )
                protective = self.store.apply_response(protective_id, normalize_order_response(response))
            except Exception as exc:
                raise OneAtrArmError("protective_submit_unknown") from exc
        elif protective and protective["status"] == "SUBMITTING":
            try:
                protective = self.execution.poll(protective_id)
            except Exception as exc:
                raise OneAtrArmError("protective_recovery_failed") from exc
        if not protective or protective["status"] not in {"ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED"}:
            raise OneAtrArmError("protective_order_not_active")
        self._save_protective(parent_id=entry_id, client_id=protective_id, symbol=str(plan["symbol"]),
                              side=protective_side, quantity=filled_quantity, stop_price=stop_price,
                              status=protective["status"], payload=protective_payload)
        return self._protective(entry_id) or {}

    def execute(self, *, plan: Mapping[str, Any], stop_price: float, arm_path: str,
                confirmation: str) -> dict[str, Any]:
        if not self.execution.authorized_for(str(plan.get("strategy_id", ""))):
            raise OneAtrArmError("strategy_not_authorized")
        arm = OneAtrArm.load(arm_path, confirmation=confirmation, plan=plan)
        if arm.strategy_id != plan.get("strategy_id"):
            raise OneAtrArmError("arm_strategy_mismatch")
        try:
            checked = self.execution.build_order_plan(
                client_order_id=str(plan["client_order_id"]), symbol=str(plan["symbol"]),
                side=str(plan["side"]), quantity=float(plan["quantity"]), price=float(plan["price"]),
                strategy_id=str(plan["strategy_id"]), signal_id=str(plan["signal_id"]),
                order_intent_id=str(plan["order_intent_id"]), reduce_only=False,
            )
        except ExecutionContractError as exc:
            raise OneAtrArmError(f"entry_exchange_rule_rejected:{exc}") from exc
        if str(plan["side"]).lower() == "buy" and not 0 < float(stop_price) < float(checked["price"]):
            raise OneAtrArmError("protective_stop_not_below_long_entry")
        if str(plan["side"]).lower() == "sell" and not float(stop_price) > float(checked["price"]):
            raise OneAtrArmError("protective_stop_not_above_short_entry")
        plan = dict(plan) | {"quantity": checked["quantity"], "symbol": checked["symbol"], "price": checked["price"]}
        entry_id = str(plan["client_order_id"])
        existing = self.store.get_order(entry_id)
        if existing is None:
            payload = dict(plan)
            payload["order_type"] = "MARKET"
            payload["protective_stop_price"] = float(stop_price)
            if not self.store.create_order(client_order_id=entry_id, symbol=str(plan["symbol"]),
                                           side=str(plan["side"]), quantity=float(plan["quantity"]), payload=payload):
                raise OneAtrArmError("entry_claim_failed")
            response = self.exchange.create_order(
                str(plan["symbol"]), "market", str(plan["side"]), float(plan["quantity"]), None,
                {"newClientOrderId": entry_id, "reduceOnly": False},
            )
            existing = self.store.apply_response(entry_id, normalize_order_response(response))
        elif existing["status"] == "SUBMITTING":
            try:
                existing = self.execution.poll(entry_id)
            except Exception as exc:
                raise OneAtrArmError("entry_recovery_failed") from exc
        if existing["status"] not in {"FILLED", "PARTIALLY_FILLED"}:
            raise OneAtrArmError(f"entry_not_filled:{existing['status']}")
        filled_quantity = float(existing["executed_quantity"])
        if filled_quantity <= 0:
            raise OneAtrArmError("entry_has_no_filled_quantity")
        protection = self._protective(entry_id)
        if protection is None:
            protection = self._ensure_protective(plan=plan, entry_id=entry_id,
                                                 filled_quantity=filled_quantity, stop_price=stop_price)
        elif protection["status"] not in {"ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED"}:
            raise OneAtrArmError("protective_order_not_active")
        arm.consume(arm_path)
        return {"entry": existing, "protective": protection, "arm_status": "used"}

    def recover_unprotected(self) -> list[str]:
        repaired: list[str] = []
        with sqlite3.connect(self.store.path) as conn:
            conn.row_factory = sqlite3.Row
            orders = [dict(row) for row in conn.execute(
                "SELECT * FROM orders WHERE status IN ('FILLED','PARTIALLY_FILLED') AND executed_quantity > 0"
            )]
        for order in orders:
            entry_id = order["client_order_id"]
            if self._protective(entry_id):
                continue
            payload = json.loads(order["payload"])
            stop_price = payload.get("protective_stop_price")
            if stop_price is None:
                raise OneAtrArmError(f"unprotected_stop_missing:{entry_id}")
            plan = {
                "client_order_id": entry_id, "symbol": order["symbol"], "side": order["side"],
                "quantity": order["quantity"], "price": order["average_price"] or payload.get("price"),
                "strategy_id": order["strategy_id"], "signal_id": order["signal_id"],
                "order_intent_id": order["order_intent_id"], "reduce_only": False,
            }
            self._ensure_protective(plan=plan, entry_id=entry_id,
                                    filled_quantity=float(order["executed_quantity"]),
                                    stop_price=float(stop_price))
            repaired.append(entry_id)
        return repaired
