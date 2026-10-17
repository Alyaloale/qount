"""Small Binance USD-M planner, durable execution state and read-only recovery.

This phase has no owner authorization wired to this boundary. Planning and polling
are usable, but the production submit gate always reports orders_authorized=False.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any, Mapping, TYPE_CHECKING

from qount.binance_assets import asset_by_execution_symbol, asset_by_signal_symbol
from qount.contracts import canonical_hash
from qount.execution.state_machine import TERMINAL_ORDER_STATUSES

if TYPE_CHECKING:
    from qount.ledger.store import RuntimeLedger


class ExecutionContractError(ValueError):
    pass


class ExchangeRuleLookupError(ExecutionContractError):
    pass


class OrdersNotAuthorized(ExecutionContractError):
    pass


@dataclass(frozen=True)
class SymbolRule:
    step_size: float
    minimum_quantity: float
    minimum_notional: float
    tick_size: float
    maximum_quantity: float = math.inf


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _finite(value: Any, name: str, minimum: float | None = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ExecutionContractError(f"{name}_invalid") from exc
    if isinstance(value, bool) or not math.isfinite(result) or (minimum is not None and result < minimum):
        raise ExecutionContractError(f"{name}_invalid")
    return result


def _floor(value: float, step: float) -> float:
    return float((Decimal(str(value)) / Decimal(str(step))).to_integral_value(rounding=ROUND_DOWN) * Decimal(str(step)))


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _time(value: Any) -> str:
    if value is None:
        return _now()
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(_finite(value, "fill_time") / 1000, timezone.utc).isoformat()
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("timezone_missing")
        return stamp.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError) as exc:
        raise ExecutionContractError("fill_time_missing_or_invalid") from exc


def _view(raw: Mapping[str, Any]) -> dict[str, Any]:
    info = raw.get("info")
    return {**(info if isinstance(info, Mapping) else {}), **{k: v for k, v in raw.items() if v is not None}}


def lookup_usdm_rule(exchange: Any, symbol: str) -> SymbolRule:
    """Read current exchangeInfo; an inactive/non-perpetual symbol fails closed."""
    wanted = str(symbol).strip().upper()
    asset = asset_by_execution_symbol(wanted)
    if asset is None or asset.status != "active":
        raise ExchangeRuleLookupError(f"unknown_binance_asset:{wanted}")
    try:
        row = next(item for item in exchange.fapiPublicGetExchangeInfo({})["symbols"] if item.get("symbol") == wanted)
        if (row["status"] != "TRADING"
                or row["contractType"] not in {"PERPETUAL", "TRADIFI_PERPETUAL"}
                or row["quoteAsset"] != "USDT" or row["marginAsset"] != "USDT"):
            raise ValueError("non_trading_usdm_contract")
        filters = {item["filterType"]: item for item in row["filters"]}
        lot = filters["LOT_SIZE"]
        market = filters.get("MARKET_LOT_SIZE", lot)
        # Both filters apply to market orders. Zero market step disables only that filter.
        steps = [_finite(lot["stepSize"], "step_size", 1e-18)]
        market_step = _finite(market["stepSize"], "market_step_size")
        if market_step:
            steps.append(market_step)
        step = max(steps)
        if any(Decimal(str(step)) % Decimal(str(s)) != 0 for s in steps):
            raise ValueError("incompatible_quantity_steps")
        notional = filters.get("MIN_NOTIONAL") or filters["NOTIONAL"]
        return SymbolRule(
            step_size=step,
            minimum_quantity=max(_finite(lot["minQty"], "minimum_quantity"), _finite(market["minQty"], "market_minimum_quantity")),
            minimum_notional=_finite(notional.get("notional", notional.get("minNotional")), "minimum_notional"),
            tick_size=_finite(filters["PRICE_FILTER"]["tickSize"], "tick_size", 1e-18),
            maximum_quantity=min(_finite(lot["maxQty"], "maximum_quantity", 1e-18), _finite(market["maxQty"], "market_maximum_quantity", 1e-18)),
        )
    except Exception as exc:
        raise ExchangeRuleLookupError(f"exchange_rule_lookup_failed:{type(exc).__name__}") from exc


def _normalize_fill(raw: Mapping[str, Any]) -> dict[str, Any]:
    row = _view(raw)
    trade_id = row.get("tradeId", row.get("id"))
    if trade_id is None or not str(trade_id).strip():
        raise ExecutionContractError("trade_id_missing")
    # CCXT fees is the complete list; fee is often a duplicate of its first entry.
    raw_fees = row.get("fees")
    if isinstance(raw_fees, Mapping):
        # A few CCXT adapters collapse the fee list into {currency: cost}.
        fees = [{"currency": asset, "cost": cost} for asset, cost in raw_fees.items()]
    else:
        fees = raw_fees or ([row["fee"]] if isinstance(row.get("fee"), Mapping) else [])
    if not fees and row.get("commission") is not None:
        fees = [{"cost": row["commission"], "currency": row.get("commissionAsset")}]
    by_asset: dict[str, float] = {}
    for fee in fees:
        asset = fee.get("currency")
        if not asset:
            raise ExecutionContractError("fee_asset_missing")
        by_asset[str(asset)] = by_asset.get(str(asset), 0.0) + _finite(fee["cost"], "fee", None)
    return dict(trade_id=str(trade_id), quantity=_finite(row.get("qty", row.get("amount")), "fill_quantity", 1e-18),
                price=_finite(row.get("price"), "fill_price", 1e-18), fees=by_asset,
                occurred_at=_time(row.get("timestamp", row.get("time", row.get("datetime")))) )


def normalize_order_response(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Raw Binance and CCXT statuses, cumulative quantities, averages and trades."""
    row = _view(raw)
    fills = [_normalize_fill(fill) for fill in (row.get("trades") or row.get("fills") or [])]
    executed = row.get("executedQty", row.get("filled"))
    executed = _finite(executed if executed is not None else sum(f["quantity"] for f in fills), "executed_quantity")
    status = str(row.get("status", "")).upper()
    status = {"NEW": "ACKNOWLEDGED", "OPEN": "ACKNOWLEDGED", "CLOSED": "FILLED", "CANCELLED": "CANCELED", "EXPIRED_IN_MATCH": "EXPIRED"}.get(status, status)
    if status == "ACKNOWLEDGED" and executed > 0:
        status = "PARTIALLY_FILLED"
    if status not in {"ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED", "CANCELED", "EXPIRED", "REJECTED"}:
        status = "UNKNOWN"
    average = row.get("average", row.get("avgPrice"))
    average = _finite(average, "average_price") if average not in (None, "") else 0.0
    if not average and executed:
        cost = row.get("cost", row.get("cumQuote"))
        average = _finite(cost, "order_cost") / executed if cost is not None else 0.0
        if not average and fills:
            average = sum(f["price"] * f["quantity"] for f in fills) / sum(f["quantity"] for f in fills)
    exchange_id = row.get("orderId", row.get("id"))
    return dict(status=status, exchange_order_id=str(exchange_id) if exchange_id is not None else None,
                executed_quantity=executed, average_price=average or None, fills=fills)


class BinanceExecutionStore:
    """A local execution ledger. Claim and observations are SQLite transactions."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        if self.path.is_symlink():
            raise ExecutionContractError("execution_store_symlink_forbidden")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS orders (
                  client_order_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, side TEXT NOT NULL,
                  quantity REAL NOT NULL, status TEXT NOT NULL, exchange_order_id TEXT,
                  executed_quantity REAL NOT NULL DEFAULT 0, average_price REAL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fills (
                  client_order_id TEXT NOT NULL, trade_id TEXT NOT NULL, symbol TEXT NOT NULL,
                  quantity REAL NOT NULL, price REAL NOT NULL, fee REAL NOT NULL, fee_asset TEXT NOT NULL,
                  occurred_at TEXT NOT NULL, PRIMARY KEY(client_order_id, trade_id)
                );
                CREATE TABLE IF NOT EXISTS cash_events (
                  event_key TEXT PRIMARY KEY, event_type TEXT NOT NULL, symbol TEXT,
                  amount REAL NOT NULL, asset TEXT NOT NULL, occurred_at TEXT NOT NULL
                );
            """)
            for table in ("orders", "fills", "cash_events"):
                columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                for column in ("strategy_id", "signal_id", "order_intent_id", "account_record_id"):
                    if column not in columns:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
            if "fees_json" not in {row[1] for row in conn.execute("PRAGMA table_info(fills)")}:
                conn.execute("ALTER TABLE fills ADD COLUMN fees_json TEXT")
        os.chmod(self.path, 0o600)

    def get_order(self, client_order_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM orders WHERE client_order_id=?", (client_order_id,)).fetchone()
            return dict(row) if row else None

    def create_order(self, *, client_order_id: str, symbol: str, side: str, quantity: float,
                     payload: Mapping[str, Any]) -> bool:
        """Only the caller that inserts the durable claim may submit to the venue."""
        encoded = _json(payload)
        trace = [payload.get(key) for key in ("strategy_id", "signal_id", "order_intent_id")]
        if not all(isinstance(value, str) and value.strip() for value in trace):
            raise ExecutionContractError("execution_trace_incomplete")
        with sqlite3.connect(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT payload FROM orders WHERE client_order_id=?", (client_order_id,)).fetchone()
            if row:
                if row[0] != encoded:
                    raise ExecutionContractError("client_order_id_payload_conflict")
                return False
            conn.execute("INSERT INTO orders(client_order_id,symbol,side,quantity,status,payload,strategy_id,signal_id,order_intent_id,account_record_id) VALUES(?,?,?,?,'SUBMITTING',?,?,?,?,?)",
                         (client_order_id, symbol, side, quantity, encoded, *trace, f"order:{symbol}:{client_order_id}"))
        return True

    def apply_response(self, client_order_id: str, observation: Mapping[str, Any]) -> dict[str, Any]:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            order = conn.execute("SELECT * FROM orders WHERE client_order_id=?", (client_order_id,)).fetchone()
            if order is None:
                raise ExecutionContractError("client_order_id_missing")
            executed = observation["executed_quantity"]
            if executed < order["executed_quantity"] - 1e-12 or executed > order["quantity"] + 1e-12:
                raise ExecutionContractError("executed_quantity_invalid")
            exchange_id = observation["exchange_order_id"] or order["exchange_order_id"]
            if order["exchange_order_id"] and exchange_id != order["exchange_order_id"]:
                raise ExecutionContractError("exchange_order_id_conflict")
            status = observation["status"]
            if order["status"] in TERMINAL_ORDER_STATUSES and status != order["status"]:
                raise ExecutionContractError("terminal_order_state_conflict")
            for fill in observation["fills"]:
                record_id = f"fill:{order['symbol']}:{fill['trade_id']}"
                fees_json = _json(fill["fees"])
                # Legacy scalar fee remains usable for single-currency fills only.
                fee_asset, fee = next(iter(fill["fees"].items())) if len(fill["fees"]) == 1 else ("MULTI" if fill["fees"] else "UNKNOWN", 0.0)
                values = (client_order_id, fill["trade_id"], order["symbol"], fill["quantity"], fill["price"], fee, fee_asset,
                          fill["occurred_at"], order["strategy_id"], order["signal_id"], order["order_intent_id"], record_id, fees_json)
                old = conn.execute("SELECT quantity,price,fees_json,occurred_at FROM fills WHERE client_order_id=? AND trade_id=?", (client_order_id, fill["trade_id"])).fetchone()
                # Some Binance/CCXT responses omit trade time.  Normalization
                # then uses the observation time, which can differ on a retry;
                # trade identity plus economics remains the immutable receipt.
                if old and tuple(old[:3]) != (fill["quantity"], fill["price"], fees_json):
                    raise ExecutionContractError("immutable_fill_conflict")
                conn.execute("INSERT OR IGNORE INTO fills(client_order_id,trade_id,symbol,quantity,price,fee,fee_asset,occurred_at,strategy_id,signal_id,order_intent_id,account_record_id,fees_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", values)
                for asset, amount in fill["fees"].items():
                    key = f"fee:{order['symbol']}:{fill['trade_id']}:{asset}"
                    self._cash(conn, event_key=key, event_type="fee", symbol=order["symbol"], amount=amount,
                               asset=asset, occurred_at=fill["occurred_at"], strategy_id=order["strategy_id"],
                               signal_id=order["signal_id"], order_intent_id=order["order_intent_id"], account_record_id=record_id)
            filled = conn.execute("SELECT COALESCE(SUM(quantity),0) FROM fills WHERE client_order_id=?", (client_order_id,)).fetchone()[0]
            if filled > executed + 1e-12:
                raise ExecutionContractError("fills_exceed_executed_quantity")
            if status == "FILLED" and abs(executed - order["quantity"]) > 1e-12:
                raise ExecutionContractError("filled_quantity_incomplete")
            conn.execute("UPDATE orders SET status=?,exchange_order_id=?,executed_quantity=?,average_price=COALESCE(?,average_price) WHERE client_order_id=?",
                         (status, exchange_id, executed, observation["average_price"], client_order_id))
        return self.get_order(client_order_id) or {}

    @staticmethod
    def _cash(conn: sqlite3.Connection, **event: Any) -> None:
        fields = ("event_key", "event_type", "symbol", "amount", "asset", "occurred_at", "strategy_id", "signal_id", "order_intent_id", "account_record_id")
        values = tuple(event[key] for key in fields)
        old = conn.execute(f"SELECT {','.join(fields)} FROM cash_events WHERE event_key=?", (event["event_key"],)).fetchone()
        if old:
            # Exchange retries can report the same immutable event without a
            # timestamp. Identity and economics must match; observation time
            # may be refreshed by a later poll.
            old_core = tuple(old[index] for index in range(len(fields)) if fields[index] != "occurred_at")
            new_core = tuple(values[index] for index in range(len(fields)) if fields[index] != "occurred_at")
            if old_core != new_core:
                raise ExecutionContractError("immutable_cash_event_conflict")
            return
        conn.execute(f"INSERT OR IGNORE INTO cash_events({','.join(fields)}) VALUES({','.join('?' for _ in fields)})", values)

    def record_cash_event(self, **event: Any) -> None:
        if event["event_type"] not in {"fee", "funding"}:
            raise ExecutionContractError("cash_event_type_invalid")
        if not all(isinstance(event.get(key), str) and event[key].strip()
                   for key in ("signal_id", "order_intent_id", "account_record_id")):
            raise ExecutionContractError("execution_trace_incomplete")
        event["amount"] = _finite(event["amount"], "cash_amount", None)
        with sqlite3.connect(self.path) as conn:
            self._cash(conn, **event)

    def inflight(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute("""SELECT orders.* FROM orders WHERE
                status NOT IN ('FILLED','REJECTED','CANCELED','EXPIRED') OR executed_quantity >
                (SELECT COALESCE(SUM(quantity),0) FROM fills WHERE fills.client_order_id=orders.client_order_id)+1e-12
                ORDER BY client_order_id""")]


class BinanceUsdMExecution:
    def __init__(self, exchange: Any, store: BinanceExecutionStore, *, ledger: RuntimeLedger | None = None) -> None:
        self.exchange, self.store, self.ledger = exchange, store, ledger

    @property
    def orders_authorized(self) -> bool:
        return os.environ.get("QOUNT_LIVE_ENABLE", "false").lower() == "true"

    @property
    def primary_strategy(self) -> str:
        return os.environ.get("QOUNT_PRIMARY_STRATEGY", "one_atr_macro_v0_1")

    def authorized_for(self, strategy_id: str) -> bool:
        return self.orders_authorized and str(strategy_id) == self.primary_strategy

    def normalize_symbol(self, symbol: str) -> str:
        asset = asset_by_execution_symbol(symbol) or asset_by_signal_symbol(symbol)
        if asset is None or asset.status != "active":
            raise ExecutionContractError(f"unknown_binance_asset:{symbol}")
        return asset.execution_symbol

    def build_order_plan(self, *, client_order_id: str, symbol: str, side: str, quantity: float, price: float,
                         strategy_id: str, signal_id: str, order_intent_id: str, reduce_only: bool = False) -> dict[str, Any]:
        if not re.fullmatch(r"[.A-Z:/a-z0-9_-]{1,36}", client_order_id):
            raise ExecutionContractError("client_order_id_invalid")
        if not all(isinstance(value, str) and value.strip() for value in (strategy_id, signal_id, order_intent_id)):
            raise ExecutionContractError("execution_trace_incomplete")
        symbol, side = self.normalize_symbol(symbol), str(side).lower()
        if side not in {"buy", "sell"}:
            raise ExecutionContractError("order_side_invalid")
        quantity, price = _finite(quantity, "quantity", 1e-18), _finite(price, "price", 1e-18)
        rule = lookup_usdm_rule(self.exchange, symbol)
        rounded = _floor(quantity, rule.step_size)
        if rounded < rule.minimum_quantity or rounded > rule.maximum_quantity or rounded * price < rule.minimum_notional:
            raise ExecutionContractError("exchange_rule_order_rejected")
        return dict(client_order_id=client_order_id, symbol=symbol, side=side, quantity=rounded, price=price,
                    strategy_id=strategy_id, signal_id=signal_id, order_intent_id=order_intent_id,
                    reduce_only=bool(reduce_only), rule=asdict(rule))

    def submit(self, plan: Mapping[str, Any], *, confirmed: bool = False) -> dict[str, Any]:
        if not self.orders_authorized:
            raise OrdersNotAuthorized("orders_authorized_false")
        if not self.authorized_for(str(plan.get("strategy_id", ""))):
            raise OrdersNotAuthorized("strategy_not_primary")
        if not confirmed:
            raise ExecutionContractError("confirmation_required")
        order = self.build_order_plan(**{key: plan[key] for key in ("client_order_id", "symbol", "side", "quantity", "price", "strategy_id", "signal_id", "order_intent_id", "reduce_only")})
        # Rule snapshots may change; the economic intent stays immutable.
        payload = {key: value for key, value in order.items() if key != "rule"}
        self._bind_ledger(order)
        claimed = self.store.create_order(client_order_id=order["client_order_id"], symbol=order["symbol"], side=order["side"], quantity=order["quantity"], payload=payload)
        if not claimed:
            return self.store.get_order(order["client_order_id"]) or {}
        # If the request times out, retain SUBMITTING; never issue a second create.
        response = self.exchange.create_order(order["symbol"], "market", order["side"], order["quantity"], None,
                                              {"newClientOrderId": order["client_order_id"], "reduceOnly": order["reduce_only"]})
        return self._apply_response(order["client_order_id"], response)

    def poll(self, client_order_id: str) -> dict[str, Any]:
        current = self.store.get_order(client_order_id)
        if current is None:
            raise ExecutionContractError("client_order_id_missing")
        symbol = current["symbol"]
        if hasattr(self.exchange, "fapiPrivateGetOrder"):
            response = self.exchange.fapiPrivateGetOrder({"symbol": symbol, "origClientOrderId": client_order_id})
        else:
            response = self.exchange.fetch_order(current["exchange_order_id"], symbol, {"origClientOrderId": client_order_id})
        result = self._apply_response(client_order_id, response)
        # USD-M order responses usually omit fills. Fetch actual trade identities,
        # even for terminal orders, rather than inventing a fill from the average.
        if result["executed_quantity"] > 0:
            if hasattr(self.exchange, "fapiPrivateGetUserTrades"):
                trades = self.exchange.fapiPrivateGetUserTrades({"symbol": symbol, "orderId": result["exchange_order_id"]})
            elif hasattr(self.exchange, "fetch_order_trades"):
                trades = self.exchange.fetch_order_trades(result["exchange_order_id"], symbol)
            else:
                trades = []
            if trades:
                result = self._apply_response(client_order_id, {**response, "trades": trades})
        return result

    def recover(self) -> list[dict[str, Any]]:
        # Re-read exchange positions on every restart; never restore exposure from
        # simulated positions. Failures propagate before recovery can be called safe.
        if hasattr(self.exchange, "fapiPrivateV3GetPositionRisk"):
            self.positions = self.exchange.fapiPrivateV3GetPositionRisk({})
        elif hasattr(self.exchange, "fetch_positions"):
            self.positions = self.exchange.fetch_positions()
        else:
            self.positions = []
        result = [self.poll(row["client_order_id"]) for row in self.store.inflight()]
        if self.ledger:
            # Replay all stored receipts as well: a crash may have committed this
            # ledger and stopped before the optional RuntimeLedger projection.
            with sqlite3.connect(self.store.path) as conn:
                ids = [row[0] for row in conn.execute("SELECT client_order_id FROM orders")]
            for client_id in ids:
                self._sync_ledger(client_id)
        return result

    def record_funding(self, *, event_key: str, symbol: str, amount: float, occurred_at: str,
                       asset: str = "USDT", client_order_id: str | None = None,
                       strategy_id: str | None = None, signal_id: str | None = None,
                       order_intent_id: str | None = None,
                       account_record_id: str | None = None) -> None:
        symbol = self.normalize_symbol(symbol)
        order = self.store.get_order(client_order_id) if client_order_id else None
        if client_order_id and (order is None or order["symbol"] != symbol):
            raise ExecutionContractError("funding_order_link_invalid")
        if order and signal_id is not None and signal_id != order["signal_id"]:
            raise ExecutionContractError("funding_signal_conflict")
        if order and order_intent_id is not None and order_intent_id != order["order_intent_id"]:
            raise ExecutionContractError("funding_order_intent_conflict")
        if order is None and not all(isinstance(value, str) and value.strip() for value in
                                     (signal_id, order_intent_id, account_record_id)):
            raise ExecutionContractError("execution_trace_incomplete")
        signal_id = order["signal_id"] if order else signal_id
        order_intent_id = order["order_intent_id"] if order else order_intent_id
        account_record_id = account_record_id or (f"income:FUNDING_FEE:{event_key}")
        self.store.record_cash_event(event_key=event_key, event_type="funding", symbol=symbol,
                                     amount=amount, asset=asset, occurred_at=_time(occurred_at),
                                     strategy_id=order["strategy_id"] if order else None,
                                     signal_id=signal_id, order_intent_id=order_intent_id,
                                     account_record_id=account_record_id)
        if self.ledger and order:
            self._sync_ledger(client_order_id)
        elif self.ledger:
            self.ledger.record_cash_event(
                event_key=event_key, event_type="funding", symbol=symbol, amount=amount,
                asset=asset, occurred_at=_time(occurred_at),
                source_hash=canonical_hash({"event_key": event_key, "symbol": symbol,
                                            "amount": amount, "asset": asset}),
                signal_id=signal_id, order_intent_id=order_intent_id,
                account_record_id=account_record_id)

    def _apply_response(self, client_order_id: str, response: Mapping[str, Any]) -> dict[str, Any]:
        row = self.store.apply_response(client_order_id, normalize_order_response(response))
        if self.ledger:
            self._sync_ledger(client_order_id)
        return row

    def _bind_ledger(self, order: Mapping[str, Any]) -> None:
        if not self.ledger:
            return
        try:
            current = self.ledger.get_order(order["client_order_id"])
        except KeyError as exc:
            raise ExecutionContractError("runtime_ledger_order_missing") from exc
        if current["symbol"] != order["symbol"] or current["side"] != order["side"] or current["planned_quantity"] != order["quantity"] or bool(current["reduce_only"]) != order["reduce_only"]:
            raise ExecutionContractError("runtime_ledger_order_mismatch")
        self.ledger.bind_execution_trace(order["client_order_id"], signal_id=order["signal_id"],
                                         order_intent_id=order["order_intent_id"],
                                         account_record_id=f"order:{order['symbol']}:{order['client_order_id']}")

    def _sync_ledger(self, client_order_id: str) -> None:
        if not self.ledger:
            return
        order = self.store.get_order(client_order_id)
        self._bind_ledger({**order, "reduce_only": json.loads(order["payload"])["reduce_only"]})
        current = self.ledger.get_order(client_order_id)
        if current["status"] == "PLANNED":
            self.ledger.transition_order(client_order_id, "SUBMITTING", event_at=_now(), source_hash=canonical_hash({"submit": client_order_id}))
        if order["status"] != "SUBMITTING" and (current["status"] != order["status"] or current["executed_quantity"] != order["executed_quantity"]):
            self.ledger.transition_order(client_order_id, order["status"], event_at=_now(), source_hash=canonical_hash({"order": order}),
                                         exchange_order_id=order["exchange_order_id"], executed_quantity=order["executed_quantity"], average_price=order["average_price"])
        with sqlite3.connect(self.store.path) as conn:
            conn.row_factory = sqlite3.Row
            for fill in conn.execute("SELECT * FROM fills WHERE client_order_id=? ORDER BY occurred_at,trade_id", (client_order_id,)):
                if fill["fee"] < 0:
                    raise ExecutionContractError("runtime_ledger_fee_representation_unsupported")
                fees = json.loads(fill["fees_json"] or "{}")
                primary_asset = fill["fee_asset"]
                primary_fee = fill["fee"]
                if primary_asset == "MULTI" and fees:
                    primary_asset, primary_fee = next(iter(fees.items()))
                self.ledger.record_fill(client_order_id=client_order_id, exchange_trade_id=fill["trade_id"], quantity=fill["quantity"], price=fill["price"],
                                        fee=primary_fee, fee_asset=primary_asset,
                                        occurred_at=fill["occurred_at"], source_hash=canonical_hash(dict(fill)))
                # RuntimeLedger stores one fee on the fill. Preserve any
                # additional CCXT fee currencies as idempotent cash events.
                if len(fees) > 1:
                    primary = next(iter(fees))
                    for fee_asset, fee_amount in fees.items():
                        if fee_asset == primary:
                            continue
                        fee_key = f"fee:{fill['symbol']}:{fill['trade_id']}:{fee_asset}"
                        self.ledger.record_cash_event(
                            event_key=fee_key, event_type="fee", symbol=fill["symbol"],
                            amount=fee_amount, asset=fee_asset, occurred_at=fill["occurred_at"],
                            source_hash=canonical_hash({"event_key": fee_key, "amount": fee_amount,
                                                        "asset": fee_asset, "fill": fill["trade_id"]}),
                            signal_id=fill["signal_id"], order_intent_id=fill["order_intent_id"],
                            account_record_id=f"{fill['account_record_id']}:fee:{fee_asset}")
            # Fill fees are counted by RuntimeLedger.record_fill; funding is
            # represented separately as a signed cash event.
            for event in conn.execute("SELECT * FROM cash_events WHERE event_type='funding' AND signal_id=? AND order_intent_id=?", (order["signal_id"], order["order_intent_id"])):
                self.ledger.record_cash_event(event_key=event["event_key"], event_type="funding", symbol=event["symbol"], amount=event["amount"], asset=event["asset"],
                                              occurred_at=event["occurred_at"], source_hash=canonical_hash(dict(event)), signal_id=event["signal_id"],
                                              order_intent_id=event["order_intent_id"], account_record_id=event["account_record_id"])
