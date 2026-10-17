"""Single-account macro execution with durable intents and an explicit legacy handover.

Strategy rules live in strategies/. This module only reconciles actual venue state,
applies those rules and records real order/funding receipts. Unknown submissions
are queried by the same client ID and are never blindly recreated.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import math
import os
import sqlite3
import time

import ccxt

from qount.contracts import canonical_hash
from qount.execution.binance_usdm import BinanceExecutionStore, BinanceUsdMExecution, normalize_order_response
from qount.execution.protection import position_amount
from qount.research_data.macro_live import write_json
from qount.strategies.macro_1atr import (
    FEE, GAP, RISK_FRACTION, SLIP, STRATEGY_ID, entry_candidates, is_decision, known_atr, trailing_update,
)
from qount.strategies.macro_funding import feature_at, funding_reserve
from qount.strategies.macro_lease import review_lease
from qount.strategies.perpetual import grid

TERMINAL = {"FILLED", "CANCELED", "EXPIRED", "REJECTED"}
ACTIVE_ALGO = {"NEW", "WORKING"}


class MacroBlocked(RuntimeError):
    pass


def require(condition, reason):
    if not condition:
        raise MacroBlocked(reason)


def client_id(kind, value):
    return f"qm1-{kind}-{canonical_hash(value)[:22]}"


class MacroLive:
    def __init__(self, exchange, inputs, *, store_path, state_path, handover, execute=False):
        self.exchange, self.inputs = exchange, inputs
        self.store = BinanceExecutionStore(store_path)
        self.execution = BinanceUsdMExecution(exchange, self.store)
        self.state_path, self.handover, self.execute = state_path, handover, execute
        with sqlite3.connect(self.store.path) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS macro_stops (
                client_id TEXT PRIMARY KEY, parent_client_id TEXT NOT NULL, symbol TEXT NOT NULL,
                quantity REAL NOT NULL, stop_price REAL NOT NULL, status TEXT NOT NULL,
                algo_id TEXT, actual_order_id TEXT, payload TEXT NOT NULL)""")
        self.state = (json.loads(state_path.read_text()) if state_path.exists() else
                      dict(strategy_id=STRATEGY_ID, phase="legacy", position=None, pending_entry=None,
                           last_entry_decision=None, last_closed_hour=None))
        require(self.state.get("strategy_id") == STRATEGY_ID, "state_strategy_mismatch")

    def save(self):
        require(self.execute, "read_only_cycle_cannot_mutate")
        write_json(self.state_path, self.state)

    def authorized(self):
        require(self.execute and self.execution.authorized_for(STRATEGY_ID), "macro_orders_not_authorized")

    def positions(self):
        rows = self.exchange.fapiPrivateV3GetPositionRisk({})
        require(isinstance(rows, list), "positions_response_invalid")
        return [r for r in rows if abs(position_amount(r)) > 1e-12]

    def balance(self):
        account = self.exchange.fapiPrivateV3GetAccount({})
        multi = self.exchange.fapiPrivateGetMultiAssetsMargin({})
        require(str(multi["multiAssetsMargin"]).lower() == "false", "multi_asset_margin_unsupported")
        usdt = next(a for a in account["assets"] if a["asset"] == "USDT")
        values = {k: float(usdt[k]) for k in ("walletBalance", "marginBalance", "availableBalance")}
        require(all(math.isfinite(v) for v in values.values()) and values["marginBalance"] > 0,
                "usdt_balance_invalid")
        return values

    def algo(self, identity):
        try:
            return self.exchange.fapiPrivateGetAlgoOrder({"clientAlgoId": identity})
        except ccxt.OrderNotFound:
            return {"algoStatus": "NOT_FOUND", "clientAlgoId": identity}

    @staticmethod
    def check_stop(row, symbol, quantity, stop, *, working="CONTRACT_PRICE", tick=1e-9):
        require(row.get("symbol") == symbol and row.get("side") == "SELL"
                and row.get("orderType", row.get("type")) == "STOP_MARKET"
                and str(row.get("reduceOnly")).lower() == "true"
                and row.get("workingType") == working
                and row.get("algoStatus") in ACTIVE_ALGO
                and abs(float(row["quantity"])-quantity) <= 1e-10
                and abs(float(row["triggerPrice"])-stop) <= tick+1e-9,
                "native_stop_unconfirmed")

    def legacy(self, positions, normal, algos):
        h = self.handover
        require(h.get("policy") == "preserve_until_flat", "legacy_handover_policy_invalid")
        entry = self.exchange.fapiPrivateGetOrder(dict(symbol=h["symbol"], origClientOrderId=h["entry_client_id"]))
        require(entry["status"] == "FILLED" and abs(float(entry["executedQty"])-h["quantity"]) <= 1e-10,
                "legacy_entry_not_reconciled")
        require(not normal, "foreign_normal_orders_present")
        require(all(r.get("clientAlgoId") == h["stop_client_id"] for r in algos), "foreign_algo_orders_present")
        if positions:
            require(len(positions) == 1 and positions[0]["symbol"] == h["symbol"]
                    and abs(position_amount(positions[0])-h["quantity"]) <= 1e-10,
                    "legacy_position_changed")
            raw = self.algo(h["stop_client_id"])
            # The legacy stop was rounded down by its original executor.
            rule = next(r for r in self.exchange.fapiPublicGetExchangeInfo({})["symbols"] if r["symbol"] == h["symbol"])
            tick = float(next(f["tickSize"] for f in rule["filters"] if f["filterType"] == "PRICE_FILTER"))
            self.check_stop(raw, h["symbol"], h["quantity"], grid(h["original_stop"], tick), working="MARK_PRICE", tick=tick/100)
            return dict(auto_action="HOLD_LEGACY_POSITION", handover="waiting_for_legacy_flat",
                        protection_check={"status": "PROTECTED", "client_id": h["stop_client_id"],
                                          "stop_price": float(raw["triggerPrice"]), "working_type": "MARK_PRICE"})
        # Owner authorized handover after flat; only our exact orphan stop may be removed.
        if algos:
            if not self.execute:
                return dict(auto_action="HANDOVER_ORPHAN_STOP", handover="flat_stop_cleanup_pending")
            self.authorized()
            self.exchange.fapiPrivateDeleteAlgoOrder({"clientAlgoId": h["stop_client_id"]})
            require(not self.exchange.fapiPrivateGetOpenAlgoOrders({}), "legacy_stop_cleanup_unconfirmed")
        if self.execute:
            self.state["phase"] = "macro"
            self.save()
        return None

    def submit(self, payload, *, price_limit=None):
        self.authorized()
        identity = payload["client_order_id"]
        old = self.store.get_order(identity)
        if old is None:
            require(self.store.create_order(client_order_id=identity, symbol=payload["symbol"], side=payload["side"],
                    quantity=payload["quantity"], payload=payload), "order_claim_failed")
            params = dict(symbol=payload["symbol"], side=payload["side"].upper(), quantity=str(payload["quantity"]),
                          newClientOrderId=identity, reduceOnly=str(payload["reduce_only"]).lower(), newOrderRespType="RESULT")
            if price_limit is None:
                params.update(type="MARKET")
            else:
                params.update(type="LIMIT", timeInForce="IOC", price=str(price_limit))
            try:
                response = self.exchange.fapiPrivatePostOrder(params)
                self.store.apply_response(identity, normalize_order_response(response))
            except Exception:
                # An uncertain POST is immediately reconciled, never resubmitted.
                return self.execution.poll(identity)
        # Poll actual fills even after terminal receipts; order responses omit trade IDs.
        return self.execution.poll(identity)

    def order_payload(self, position, kind, quantity):
        identity = client_id(kind, [position["entry_id"], position.get("exit_attempt", 0)])
        return dict(client_order_id=identity, symbol=position["symbol"], side="sell", quantity=quantity,
                    strategy_id=STRATEGY_ID, signal_id=position["signal_id"],
                    order_intent_id=f"intent:{identity}", reduce_only=True)

    def protective(self, pos, stop):
        """Create and query the replacement before removing the old protective stop."""
        self.authorized()
        identity = client_id("stop", [pos["entry_id"], pos["quantity"], stop])
        self.state["pending_stop"] = dict(client_id=identity, stop=stop, quantity=pos["quantity"])
        self.save()
        with sqlite3.connect(self.store.path) as conn:
            row = conn.execute("SELECT client_id FROM macro_stops WHERE client_id=?", (identity,)).fetchone()
            if row is None:
                params = dict(algoType="CONDITIONAL", symbol=pos["symbol"], side="SELL", type="STOP_MARKET",
                              quantity=str(pos["quantity"]), triggerPrice=str(stop), reduceOnly="true",
                              workingType="CONTRACT_PRICE", clientAlgoId=identity)
                conn.execute("INSERT INTO macro_stops VALUES(?,?,?,?,?,'SUBMITTING',NULL,NULL,?)",
                    (identity, pos["entry_id"], pos["symbol"], pos["quantity"], stop, json.dumps(params)))
        if row is None:
            self.exchange.fapiPrivatePostAlgoOrder(params)
        observed = self.algo(identity)
        self.check_stop(observed, pos["symbol"], pos["quantity"], stop)
        with sqlite3.connect(self.store.path) as conn:
            conn.execute("UPDATE macro_stops SET status=?,algo_id=?,actual_order_id=? WHERE client_id=?",
                         (observed["algoStatus"], str(observed["algoId"]), observed.get("actualOrderId"), identity))
        previous = pos.get("stop_id")
        # Save the verified new identity first. On cancellation timeout, next cycle
        # still knows both and cannot lose track of the old conditional order.
        pos.update(stop_id=identity, stop=stop)
        if previous and previous != identity:
            pos["retiring_stop_id"] = previous
        self.state["position"] = pos
        self.save()
        self.retire_stop(pos)
        self.state["pending_stop"] = None
        self.save()
        return observed

    def retire_stop(self, pos):
        old = pos.get("retiring_stop_id")
        if old:
            raw = self.algo(old)
            if raw["algoStatus"] in ACTIVE_ALGO:
                self.authorized()
                self.exchange.fapiPrivateDeleteAlgoOrder({"clientAlgoId": old})
                raw = self.algo(old)
            require(raw["algoStatus"] in {"CANCELED", "FINISHED", "EXPIRED", "REJECTED"}, "old_stop_retirement_unknown")
            pos.pop("retiring_stop_id")
            self.save()

    def recover_entry(self):
        pending = self.state.get("pending_entry")
        if not pending:
            return None
        pos, payload = pending["position"], pending["payload"]
        if self.store.get_order(payload["client_order_id"]) is None and not 0 <= time.time()-pos["entry_time"] <= 90:
            self.state["pending_entry"] = None
            self.save()
            return dict(auto_action="HOLD_MISSED_DECISION", execution_blocker="unsubmitted_intent_expired")
        try:
            receipt = self.submit(payload, price_limit=pending["limit_price"])
            if receipt["status"] not in TERMINAL:
                self.authorized()
                self.exchange.fapiPrivateDeleteOrder({"symbol": pos["symbol"], "origClientOrderId": payload["client_order_id"]})
                receipt = self.execution.poll(payload["client_order_id"])
            require(receipt["status"] in TERMINAL, "entry_still_pending")
        except Exception:
            # A fill can exist even if both POST and the order query timed out.
            # Protect the newly observed exposure while leaving its intent pending.
            observed = self.positions()
            if (len(observed) == 1 and observed[0]["symbol"] == pos["symbol"]
                    and 0 < position_amount(observed[0]) <= pos["quantity"]+1e-10):
                emergency = copy.deepcopy(pos)
                emergency["quantity"] = position_amount(observed[0])
                self.state["position"] = emergency
                self.save()
                try:
                    self.protective(emergency, pos["initial_stop"])
                except Exception:
                    self.exit(emergency, "unknown_entry_unprotected")
            raise MacroBlocked("entry_submission_unknown_reconciliation_pending") from None
        q = receipt["executed_quantity"]
        if q > 0:
            price = receipt["average_price"]
            if price is None or price <= pos["initial_stop"]:
                pos["quantity"] = q
                self.state["position"] = pos
                self.save()
                self.exit(pos, "entry_fill_below_stop_or_unknown")
                raise MacroBlocked("entry_fill_price_invalid_emergency_exit")
            previous = self.state.get("position")
            if previous and previous.get("entry_id") == pos["entry_id"]:
                for key in ("stop_id", "retiring_stop_id"):
                    if previous.get(key):
                        pos[key] = previous[key]
            # Preserve the pretrade budget; scale all quantity-dependent amounts to real fills.
            ratio = q/pos["quantity"]
            for key in ("margin_usdt", "stress_risk_usdt", "structural_risk_usdt", "funding_cost_cap_usdt"):
                if key in pos:
                    pos[key] *= ratio
            pos.update(quantity=q, entry_price=price, notional_usdt=q*price,
                       margin_usdt=q*price/pos["leverage"], structural_r=price-pos["initial_stop"], highest_close=price)
            self.state["position"] = pos
            self.save()
            try:
                stop = self.protective(pos, pos["initial_stop"])
            except Exception:
                # No confirmed initial protection: reduce the actual new exposure.
                # Legacy positions never reach this path.
                self.exit(pos, "initial_protection_failed")
                raise MacroBlocked("initial_protection_failed_emergency_exit") from None
            with sqlite3.connect(self.store.path) as conn:
                filled = conn.execute("SELECT COALESCE(SUM(quantity),0) FROM fills WHERE client_order_id=?", (payload["client_order_id"],)).fetchone()[0]
            require(abs(filled-q) <= 1e-10, "entry_trade_receipts_incomplete")
        else:
            stop = None
        self.state["pending_entry"] = None
        self.save()
        return dict(auto_action="ENTRY_FILLED_PROTECTED" if q else "ENTRY_IOC_UNFILLED",
                    execution={"entry": receipt, "protective": stop})

    def exit(self, pos, reason):
        self.authorized()
        if pos.get("pending_exit") and self.store.get_order(pos["pending_exit"]["client_order_id"]):
            existing = self.execution.poll(pos["pending_exit"]["client_order_id"])
            require(existing["status"] in TERMINAL, "exit_still_pending")
        positions = self.positions()
        require(not positions or (len(positions) == 1 and positions[0]["symbol"] == pos["symbol"]
                and 0 < position_amount(positions[0]) <= pos["quantity"]+1e-10), "exit_position_mismatch")
        if positions:
            q = position_amount(positions[0])
            payload = self.order_payload(pos, "exit", q)
            if pos.get("pending_exit"):
                payload = pos["pending_exit"]
            else:
                pos.update(pending_exit=payload, exit_reason=reason)
                self.save()
            receipt = self.submit(payload)
            require(receipt["status"] in TERMINAL, "exit_still_pending")
            remaining = self.positions()
            if remaining:
                pos["exit_attempt"] = pos.get("exit_attempt", 0)+1
                pos.pop("pending_exit", None)
                self.save()
                raise MacroBlocked("exit_partial_native_stop_retained")
        # Actual flat confirmed before any stop cancellation or optional fill collection.
        self.sync_triggered_stops(pos)
        with sqlite3.connect(self.store.path) as conn:
            owned = {r[0] for r in conn.execute("SELECT client_id FROM macro_stops WHERE parent_client_id=?", (pos["entry_id"],))}
        for raw in self.exchange.fapiPrivateGetOpenAlgoOrders({}):
            if raw.get("clientAlgoId") in owned:
                self.exchange.fapiPrivateDeleteAlgoOrder({"clientAlgoId": raw["clientAlgoId"]})
        require(not any(r.get("clientAlgoId") in owned for r in self.exchange.fapiPrivateGetOpenAlgoOrders({})),
                "flat_native_stop_cleanup_unknown")
        require(not self.positions(), "exit_flat_reconciliation_failed")
        self.state.update(position=None, pending_entry=None, pending_stop=None, last_closed_hour=int(time.time())//3600*3600,
                          last_exit={"entry_id": pos["entry_id"], "reason": reason})
        self.save()
        return dict(auto_action="POSITION_CLOSED", exit_reason=reason)

    def sync_triggered_stops(self, pos):
        """Link a triggered algo to its real market order and immutable fills."""
        with sqlite3.connect(self.store.path) as conn:
            identities = [r[0] for r in conn.execute("SELECT client_id FROM macro_stops WHERE parent_client_id=?", (pos["entry_id"],))]
        for identity in identities:
            raw = self.algo(identity)
            actual = raw.get("actualOrderId")
            if not actual or str(actual) == "0":
                continue
            order = self.exchange.fapiPrivateGetOrder({"symbol": pos["symbol"], "orderId": actual})
            require(order["side"] == "SELL" and order["symbol"] == pos["symbol"], "triggered_stop_order_mismatch")
            payload = dict(client_order_id=order["clientOrderId"], symbol=pos["symbol"], side="sell",
                           quantity=float(order["origQty"]), strategy_id=STRATEGY_ID,
                           signal_id=pos["signal_id"], order_intent_id=f"stop:{identity}", reduce_only=True)
            self.store.create_order(client_order_id=payload["client_order_id"], symbol=pos["symbol"], side="sell",
                                    quantity=payload["quantity"], payload=payload)
            self.execution.poll(payload["client_order_id"])
            with sqlite3.connect(self.store.path) as conn:
                conn.execute("UPDATE macro_stops SET status=?,actual_order_id=? WHERE client_id=?",
                             (raw["algoStatus"], str(actual), identity))

    def prepare_entry(self, pos, now, data):
        self.authorized()
        require(0 <= time.time()-now <= 90, "entry_decision_window_expired")
        # Real venue constraints can reject an otherwise valid research candidate.
        require(not self.positions() and not self.exchange.fapiPrivateGetOpenOrders({})
                and not self.exchange.fapiPrivateGetOpenAlgoOrders({}), "entry_account_not_clean_flat")
        mode = self.exchange.fapiPrivateGetPositionSideDual({})
        require(str(mode["dualSidePosition"]).lower() == "false", "hedge_mode_unsupported")
        s = pos["symbol"]
        commission = self.exchange.fapiPrivateGetCommissionRate({"symbol": s})
        require(float(commission["takerCommissionRate"]) <= FEE, "live_fee_exceeds_selected_cost_model")
        bracket = self.exchange.fapiPrivateGetLeverageBracket({"symbol": s})
        brackets = bracket[0]["brackets"]
        required = next((b for b in brackets if float(b["notionalFloor"]) <= pos["notional_usdt"] < float(b["notionalCap"])), None)
        require(required is not None and float(required["maintMarginRatio"]) <= .01
                and int(required["initialLeverage"]) >= pos["leverage"], "live_bracket_outside_research_assumptions")
        bal = self.balance()
        require(pos["margin_usdt"]+pos["notional_usdt"]*FEE <= bal["availableBalance"], "insufficient_available_margin")
        tick = float(next(f["tickSize"] for f in data[s]["rule"]["filters"] if f["filterType"] == "PRICE_FILTER"))
        limit = grid(pos["entry_price"], tick)
        book = self.exchange.fapiPublicGetDepth({"symbol": s, "limit": 100})
        require(abs(int(book.get("T", book.get("E", 0)))-int(time.time()*1000)) <= 5000, "order_book_stale")
        capacity = sum(float(q) for p, q in book["asks"] if float(p) <= limit)
        require(capacity >= pos["quantity"], "entry_price_or_depth_outside_budget")
        # Configuration changes only apply to this flat symbol, never the legacy holding.
        risk = self.exchange.fapiPrivateV2GetPositionRisk({"symbol": s})
        require(len(risk) == 1 and position_amount(risk[0]) == 0, "entry_symbol_not_flat")
        isolated = str(risk[0].get("marginType", "")).lower() == "isolated" or str(risk[0].get("isolated", False)).lower() == "true"
        if not isolated:
            self.exchange.fapiPrivatePostMarginType({"symbol": s, "marginType": "ISOLATED"})
        lev = self.exchange.fapiPrivatePostLeverage({"symbol": s, "leverage": pos["leverage"]})
        require(int(lev["leverage"]) == pos["leverage"] and float(lev["maxNotionalValue"]) >= pos["notional_usdt"], "leverage_not_confirmed")
        refreshed = self.exchange.fapiPrivateV2GetPositionRisk({"symbol": s})[0]
        require(str(refreshed.get("isolated", False)).lower() == "true" or refreshed.get("marginType") == "isolated", "isolated_margin_not_confirmed")
        server = int(self.exchange.fapiPublicGetTime({})["serverTime"])//1000
        require(abs(server-int(time.time())) <= 3 and 0 <= server-now <= 90, "entry_decision_window_expired")
        require(not self.positions() and not self.exchange.fapiPrivateGetOpenOrders({})
                and not self.exchange.fapiPrivateGetOpenAlgoOrders({}), "account_changed_during_entry_preparation")
        identity = client_id("entry", [STRATEGY_ID, s, now])
        pos = copy.deepcopy(pos)
        pos.update(entry_id=identity, signal_id=f"signal:{s}:{now}", managed_through=now)
        payload = dict(client_order_id=identity, symbol=s, side="buy", quantity=pos["quantity"],
                       strategy_id=STRATEGY_ID, signal_id=pos["signal_id"], order_intent_id=f"intent:{identity}", reduce_only=False)
        self.state.update(pending_entry=dict(position=pos, payload=payload, limit_price=limit), last_entry_decision=now)
        self.save()
        return self.recover_entry()

    def funding_paid(self, pos, now):
        cursor = pos["entry_time"]*1000
        rows = []
        while cursor < now*1000:
            page = self.exchange.fapiPrivateGetIncome(dict(symbol=pos["symbol"], incomeType="FUNDING_FEE",
                          startTime=cursor, endTime=now*1000-1, limit=1000))
            rows.extend(page)
            if len(page) < 1000:
                break
            next_cursor = max(int(r["time"]) for r in page)+1
            require(next_cursor > cursor, "funding_income_pagination_invalid")
            cursor = next_cursor
        unique = {str(r["tranId"]): r for r in rows}
        require(all(r["asset"] == "USDT" and math.isfinite(float(r["income"])) for r in unique.values()), "funding_income_currency_unknown")
        for key, row in unique.items():
            self.execution.record_funding(event_key=f"funding:{pos['symbol']}:{key}", symbol=pos["symbol"],
                  amount=float(row["income"]), occurred_at=dt.datetime.fromtimestamp(int(row["time"])/1000, dt.timezone.utc).isoformat(),
                  client_order_id=pos["entry_id"], account_record_id=f"income:{key}")
        pos["funding"] = sum(float(r["income"]) for r in unique.values())
        if "funding_adverse_paid" in pos:
            pos["funding_adverse_paid"] = sum(max(0, -float(r["income"])) for r in unique.values())
            if pos["funding_adverse_paid"] > pos["funding_cost_cap_usdt"]+1e-9:
                # Never offset adverse spending with favorable payments.
                cumulative = 0.0
                for r in sorted(unique.values(), key=lambda r: int(r["time"])):
                    cumulative += max(0, -float(r["income"]))
                    if cumulative > pos["funding_cost_cap_usdt"]+1e-9:
                        pos.setdefault("funding_exit_due", int(r["time"])//3600000*3600+3600)
                        break

    def manage(self, pos, positions, now):
        if not positions:
            return self.exit(pos, "venue_position_closed") if self.execute else dict(auto_action="POSITION_FLAT_RECONCILE")
        if pos.get("exit_reason") and self.execute:
            return self.exit(pos, pos["exit_reason"])
        if self.execute:
            self.sync_triggered_stops(pos)
            pending_stop = self.state.get("pending_stop")
            if pending_stop:
                self.protective(pos, pending_stop["stop"])
        require(len(positions) == 1 and positions[0]["symbol"] == pos["symbol"]
                and abs(position_amount(positions[0])-pos["quantity"]) <= 1e-10,
                "managed_position_quantity_mismatch")
        require(pos.get("stop_id"), "managed_stop_identity_missing")
        stop = self.algo(pos["stop_id"])
        try:
            self.check_stop(stop, pos["symbol"], pos["quantity"], pos["stop"])
        except MacroBlocked:
            if self.execute:
                return self.exit(pos, "managed_native_stop_not_active")
            raise
        if not self.execute:
            return dict(auto_action="CHECK_MANAGED_POSITION", protection_check={"status": "PROTECTED"})
        self.retire_stop(pos)
        self.funding_paid(pos, now)
        self.save()
        if now >= pos.get("funding_exit_due", math.inf):
            return self.exit(pos, "funding_cost_exit")
        if now >= pos["entry_time"]+pos["max_hold_hours"]*3600:
            return self.exit(pos, "time_exit")
        # Native stop stays active when public inputs are unavailable.
        try:
            data, _ = self.inputs.snapshot(now, held=pos["symbol"])
        except Exception:
            if now >= pos.get("funding_lease_deadline", math.inf):
                return self.exit(pos, "lease_market_or_funding_unknown")
            raise
        bars = data[pos["symbol"]]["trade"]
        complete = [b for b in bars if pos["managed_through"] <= b.t and b.t+3600 <= now]
        tick = next(f["tickSize"] for f in data[pos["symbol"]]["rule"]["filters"] if f["filterType"] == "PRICE_FILTER")
        for b in complete:
            proposed, reason = trailing_update(pos, b.c, known_atr(bars, b.t+3600), tick)
            if reason:
                return self.exit(pos, reason)
            # Calculate missed updates causally, but never claim a historical fill.
            if proposed["stop"] > pos["stop"]:
                current = float(self.exchange.fapiPublicGetTickerPrice({"symbol": pos["symbol"]})["price"])
                if proposed["stop"] >= current:
                    return self.exit(pos, "missed_trailing_crossed_current_price")
                self.protective(pos, proposed["stop"])
            pos.update(highest_close=proposed["highest_close"], managed_through=b.t+3600)
            self.save()
        if is_decision(now) or now >= pos.get("funding_lease_deadline", math.inf):
            try:
                features = self.inputs.features(now)
            except Exception:
                return self.exit(pos, "lease_regime_unknown" if now >= pos.get("funding_lease_deadline", math.inf)
                                 else "trend_inputs_unknown")
            current = feature_at(features[pos["symbol"]], now)
            eligible = current is not None and 0 < now-current["available"] <= 4*86400 and current[pos["hold_feature"]]
            if now >= pos.get("funding_lease_deadline", math.inf):
                balance = self.balance()
                hours = min(168, (pos["entry_time"]+pos["max_hold_hours"]*3600-now)//3600)
                reserve = funding_reserve(data[pos["symbol"]]["funding"], now, hours, "debit_stress")
                price = float(self.exchange.fapiPublicGetTickerPrice({"symbol": pos["symbol"]})["price"])
                review = review_lease(pos, now=now, price=price, equity=balance["marginBalance"],
                            cash=balance["walletBalance"], reserve=reserve, hours=hours, eligible=eligible,
                            fee=FEE, slip=SLIP, risk_fraction=RISK_FRACTION, gap=GAP)
                pos["funding_lease_reviews"].append(review)
                self.save()
                if not review["allowed"]:
                    return self.exit(pos, review["reason"])
                pos["funding_lease_deadline"] = now+hours*3600
                self.save()
            if is_decision(now) and not eligible:
                return self.exit(pos, "trend_off")
        return dict(auto_action="HOLD_MACRO_POSITION", position=pos, protection_check={"status": "PROTECTED"})

    def cycle(self, now):
        if self.execute:
            self.authorized()
        positions = self.positions()
        normal = self.exchange.fapiPrivateGetOpenOrders({})
        algos = self.exchange.fapiPrivateGetOpenAlgoOrders({})
        if self.state["phase"] == "legacy":
            result = self.legacy(positions, normal, algos)
            if result:
                return result
            positions = self.positions()
            normal = self.exchange.fapiPrivateGetOpenOrders({})
            algos = self.exchange.fapiPrivateGetOpenAlgoOrders({})
        if self.state.get("position", {}) and self.state["position"].get("exit_reason") and self.execute:
            return self.exit(self.state["position"], self.state["position"]["exit_reason"])
        if self.state.get("pending_entry"):
            require(self.execute, "pending_entry_requires_reconciliation")
            return self.recover_entry()
        pos = self.state.get("position")
        if pos:
            owned = {pos.get("stop_id"), pos.get("retiring_stop_id")}
            if self.state.get("pending_stop"):
                owned.add(self.state["pending_stop"]["client_id"])
            require(all(r.get("clientAlgoId") in owned for r in algos), "foreign_algo_orders_present")
            require(not normal or (pos.get("pending_exit") and all(r.get("clientOrderId") == pos["pending_exit"]["client_order_id"] for r in normal)), "foreign_normal_orders_present")
            return self.manage(pos, positions, now)
        require(not positions and not normal and not algos, "account_has_unmanaged_exposure_or_orders")
        if not is_decision(now):
            return dict(auto_action="WAIT_NY_1000", protection_check={"status": "FLAT"})
        if self.execute and not 0 <= time.time()-now <= 90:
            return dict(auto_action="HOLD_MISSED_DECISION", execution_blocker="entry_decision_window_expired")
        if self.state.get("last_entry_decision") == now or self.state.get("last_closed_hour") == now:
            return dict(auto_action="HOLD_ALREADY_PROCESSED")
        features = self.inputs.features(now)
        data, caps = self.inputs.snapshot(now, entry=True)
        balance = self.balance()
        # All available USD-M USDT is the capital pool, subject to selected risk/margin caps.
        capital = min(balance["marginBalance"], balance["availableBalance"])
        candidates, rejected = entry_candidates(data, features, caps, now, capital)
        result = dict(auto_action="HOLD_NO_SIGNAL", rejections=rejected, selected=None,
                      capital_usdt=capital, candidate_count=len(candidates))
        if candidates:
            selected = candidates[0]
            result["selected"] = dict(selected, eligible=True, stop_price=selected["stop"])
            if self.execute:
                result.update(self.prepare_entry(selected, now, data))
            else:
                result["auto_action"] = "PLAN_MACRO_ENTRY"
        elif self.execute:
            self.state["last_entry_decision"] = now
            self.save()
        return result
