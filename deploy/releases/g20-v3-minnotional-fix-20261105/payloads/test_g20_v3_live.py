"""Unit tests for the G20-LP v3 live executor (planning semantics + cycle)."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from qount.execution.binance_usdm import BinanceExecutionStore, BinanceUsdMExecution
from qount.execution.g20_v3_live import (
    POOL, STRATEGY_ID, LegRule, V3PoolLive, breaches, plan_legs, signal_from_klines,
)

RULE = LegRule(step_size=0.001, minimum_quantity=0.001, minimum_notional=5.0)
RULES = {s: RULE for s in POOL}


def _prices(value=100.0):
    return {s: value for s in POOL}


class PlanLegsTests(unittest.TestCase):
    def test_equal_weight_entries_at_design_point(self):
        plan = plan_legs(equity=43.87, prices=_prices(4.0), held={}, rules=RULES)
        self.assertEqual(len(plan), len(POOL))
        for leg in plan:
            self.assertEqual(leg["action"], "BUY")
            # 43.87 * 2 / 11 = 7.98U target per leg
            self.assertAlmostEqual(leg["quantity"] * 4.0, 7.976, places=2)

    def test_target_below_minimum_notional_closes_or_skips(self):
        # equity 25U -> 25*2/11 = 4.55U per leg < 5U minimum
        held = {s: 0.06 for s in POOL}          # 6U position each (>5U min -> close)
        plan = plan_legs(equity=25.0, prices=_prices(100.0), held=held, rules=RULES)
        self.assertEqual({leg["action"] for leg in plan}, {"CLOSE"})

    def test_xau_rounding_dust_rounds_up_not_closes(self):
        # 2026-11-05 incident: target 8.0444U at price 4071.67, step 0.001.
        # The floor (0.001 = 4.07U) is below the 5U minimum notional; the
        # executable size is 0.002 = 8.14U.  The old code zeroed the target
        # and CLOSED a healthy 0.002 position.
        rule = LegRule(step_size=0.001, minimum_quantity=0.001, minimum_notional=5.0)
        rules = {"XAUUSDT": rule}
        prices = {"XAUUSDT": 4071.67}
        plan = plan_legs(equity=4.0222, prices=prices, held={"XAUUSDT": 0.002},
                         rules=rules, pool=("XAUUSDT",))
        self.assertEqual(plan[0]["action"], "HOLD")
        self.assertEqual(plan[0]["desired_quantity"], 0.002)
        plan = plan_legs(equity=4.0222, prices=prices, held={},
                         rules=rules, pool=("XAUUSDT",))
        self.assertEqual(plan[0]["action"], "BUY")
        self.assertEqual(plan[0]["quantity"], 0.002)

    def test_target_above_minimum_never_rounds_to_unexecutable(self):
        rule = LegRule(step_size=0.001, minimum_quantity=0.001, minimum_notional=5.0)
        rules = {"XAUUSDT": rule}
        prices = {"XAUUSDT": 4071.67}
        for equity in (2.6, 4.0222, 6.0, 100.0):   # targets 5.2 .. 200U
            plan = plan_legs(equity=equity, prices=prices, held={},
                             rules=rules, pool=("XAUUSDT",))
            self.assertGreaterEqual(plan[0]["quantity"] * 4071.67, 5.0)

    def test_dust_close_is_skipped_not_ordered(self):
        held = {"SPYUSDT": 0.02}                 # 2U position < 5U minimum
        plan = plan_legs(equity=2.0, prices=_prices(100.0), held=held,
                         rules={"SPYUSDT": RULE}, pool=("SPYUSDT",))
        self.assertEqual(plan[0]["action"], "SKIP")
        self.assertEqual(plan[0]["reason"], "close_below_minimum_notional")

    def test_small_resize_delta_is_rejected_live_semantics(self):
        held = {s: 0.075 for s in POOL}          # 7.5U vs 7.9U desired: delta 0.4U < 5U
        plan = plan_legs(equity=43.87, prices=_prices(100.0), held=held, rules=RULES)
        self.assertEqual({leg["action"] for leg in plan}, {"SKIP"})
        self.assertEqual({leg["reason"] for leg in plan}, {"delta_below_minimum_notional"})

    def test_adequate_delta_trades(self):
        held = {s: 0.020 for s in POOL}          # 2U held vs 7.9U desired: delta 5.9U > 5U
        plan = plan_legs(equity=43.87, prices=_prices(100.0), held=held, rules=RULES)
        self.assertEqual({leg["action"] for leg in plan}, {"BUY"})

    def test_at_target_holds(self):
        held = {s: 0.079 for s in POOL}
        plan = plan_legs(equity=43.87, prices=_prices(100.0), held=held, rules=RULES)
        self.assertEqual({leg["action"] for leg in plan}, {"HOLD"})

    def test_invalid_equity_blocks(self):
        with self.assertRaises(Exception):
            plan_legs(equity=0.0, prices=_prices(), held={}, rules=RULES)


class BreachAndSignalTests(unittest.TestCase):
    def test_breach_covers_missing_and_held_legs(self):
        full = {s: 0.079 for s in POOL}             # 7.9U vs 7.976U target
        self.assertFalse(breaches(equity=43.87, prices=_prices(100.0),
                                  held=full, rules=RULES))
        missing_one = dict(full)
        missing_one.pop("SPYUSDT")
        self.assertTrue(breaches(equity=43.87, prices=_prices(100.0),
                                 held=missing_one, rules=RULES))
        # An empty book is the worst missing-leg case, not a clean state.
        self.assertTrue(breaches(equity=43.87, prices=_prices(100.0),
                                 held={}, rules=RULES))
        over = dict(full)
        over["SPYUSDT"] = 0.079 * 1.3
        self.assertTrue(breaches(equity=43.87, prices=_prices(100.0),
                                 held=over, rules=RULES))

    def test_breach_ignores_positions_outside_pool(self):
        # A foreign position must not crash the drift check; the cycle layer
        # blocks on it explicitly instead.
        full = {s: 0.079 for s in POOL}
        full["BTCUSDT"] = 1.0
        self.assertFalse(breaches(equity=43.87, prices=_prices(100.0),
                                  held=full, rules=RULES))

    def test_breach_cash_leg_only_when_tradeable_position_left(self):
        # equity 25U -> 4.55U target per leg < 5U minimum: cash semantics.
        # Empty/dust book must not breach (no daily resize churn at the floor).
        self.assertFalse(breaches(equity=25.0, prices=_prices(100.0),
                                  held={}, rules=RULES))
        self.assertFalse(breaches(equity=25.0, prices=_prices(100.0),
                                  held={"SPYUSDT": 0.02}, rules=RULES))
        self.assertTrue(breaches(equity=25.0, prices=_prices(100.0),
                                 held={"SPYUSDT": 0.06}, rules=RULES))

    def test_signal_bar_selection_skips_forming_bar(self):
        day = 1_700_000_000_000
        rows = [[day, 1, 2, 0.5, 1.5, 10], [day + 86_400_000, 1, 2, 0.5, 2.5, 10]]
        now = day + 86_400_000 + 5_000      # 5s into the forming bar
        got_day, close = signal_from_klines(rows, now_ms=now)
        self.assertEqual(got_day, day)      # rows[-1] is forming -> signal rows[-2]
        self.assertEqual(close, 1.5)

    def test_signal_bar_without_forming_bar(self):
        day = 1_700_000_000_000
        rows = [[day, 1, 2, 0.5, 1.5, 10], [day + 86_400_000, 1, 2, 0.5, 2.5, 10]]
        now = day + 2 * 86_400_000 + 5_000  # last row already fully closed
        got_day, close = signal_from_klines(rows, now_ms=now)
        self.assertEqual(got_day, day + 86_400_000)
        self.assertEqual(close, 2.5)


class FakeExchange:
    def __init__(self, equity=43.87, positions=None, prices=None):
        self.equity = equity
        self.positions = positions or {}
        self.prices = prices or {}
        self.orders = []
        self.config_calls = []
        self.leverage_error = None
        self.margin_error = None
        self.v2_positions = None

    def fapiPrivatePostLeverage(self, params):
        if self.leverage_error is not None:
            raise self.leverage_error
        self.config_calls.append(("leverage", params["symbol"], params["leverage"]))
        return {"symbol": params["symbol"], "leverage": params["leverage"]}

    def fapiPrivatePostMarginType(self, params):
        if self.margin_error is not None:
            raise self.margin_error
        self.config_calls.append(("marginType", params["symbol"], params["marginType"]))
        return {"code": 200, "msg": "success"}

    def fapiPrivateV2GetPositionRisk(self, params):
        if self.v2_positions is not None:
            return self.v2_positions
        return [{"symbol": s, "positionAmt": str(q), "entryPrice": "1", "markPrice": "1",
                 "leverage": "3", "marginType": "cross", "isolatedMargin": "0",
                 "liquidationPrice": "0"}
                for s, q in self.positions.items()]

    def fapiPrivateV3GetAccount(self, params):
        return {"assets": [{"asset": "USDT", "walletBalance": self.equity,
                            "marginBalance": self.equity, "availableBalance": self.equity}]}

    def fapiPrivateV3GetPositionRisk(self, params):
        return [{"symbol": s, "positionAmt": str(q), "entryPrice": "1", "markPrice": "1"}
                for s, q in self.positions.items()]

    def fapiPublicGetExchangeInfo(self, params):
        return {"symbols": [{"symbol": s, "status": "TRADING", "contractType": "PERPETUAL",
                             "quoteAsset": "USDT", "marginAsset": "USDT",
                             "filters": [{"filterType": "LOT_SIZE", "stepSize": "0.001",
                                          "minQty": "0.001", "maxQty": "100000"},
                                         {"filterType": "MARKET_LOT_SIZE", "stepSize": "0.001",
                                          "minQty": "0.001", "maxQty": "100000"},
                                         {"filterType": "MIN_NOTIONAL", "notional": "5"},
                                         {"filterType": "PRICE_FILTER", "tickSize": "0.01"}]}
                for s in POOL]}

    def fetch_ohlcv(self, symbol, timeframe, limit=3):
        day = (int(time.time() * 1000) // 86_400_000 - 2) * 86_400_000
        px = self.prices.get(symbol, 100.0)
        return [[day, px, px, px, px, 1], [day + 86_400_000, px, px, px, px, 1],
                [day + 2 * 86_400_000, px, px, px, px, 1]]

    def create_order(self, symbol, type, side, quantity, price, params):
        self.orders.append((symbol, side, quantity, params.get("newClientOrderId")))
        return {"orderId": len(self.orders), "clientOrderId": params.get("newClientOrderId"),
                "symbol": symbol, "side": side.upper(), "type": "MARKET",
                "avgPrice": str(self.prices.get(symbol, 100.0)),
                "executedQty": str(quantity), "origQty": str(quantity),
                "status": "FILLED", "time": int(time.time() * 1000),
                "updateTime": int(time.time() * 1000), "reduceOnly": params.get("reduceOnly")}

    def fapiPrivateGetOrder(self, params):
        for i, (symbol, side, quantity, cid) in enumerate(self.orders):
            if cid == params.get("origClientOrderId"):
                return {"orderId": i + 1, "clientOrderId": cid, "symbol": symbol,
                        "side": side.upper(), "type": "MARKET",
                        "avgPrice": str(self.prices.get(symbol, 100.0)),
                        "executedQty": str(quantity), "origQty": str(quantity),
                        "status": "FILLED", "time": int(time.time() * 1000),
                        "updateTime": int(time.time() * 1000), "reduceOnly": False}
        raise RuntimeError("order_not_found")

    def fapiPrivateGetUserTrades(self, params):
        oid = params.get("orderId")
        trades = []
        for i, (symbol, side, quantity, cid) in enumerate(self.orders):
            if oid in (None, i + 1, str(i + 1)):
                trades.append({"id": i + 1, "orderId": i + 1, "symbol": symbol,
                               "side": side.upper(), "price": str(self.prices.get(symbol, 100.0)),
                               "qty": str(quantity), "commission": "0",
                               "commissionAsset": "USDT", "time": int(time.time() * 1000)})
        return trades


class CycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = BinanceExecutionStore(Path(self.tmp.name) / "exec.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def _live(self, exchange, state=None):
        execution = BinanceUsdMExecution(exchange, self.store)
        return V3PoolLive(exchange, execution, state=state or {})

    def test_plan_only_cycle_sizes_whole_book(self):
        exchange = FakeExchange()
        live = self._live(exchange)
        receipt = live.cycle(execute=False)
        self.assertEqual(receipt["auto_action"], "RESIZE")
        self.assertEqual(len(receipt["orders"]), len(POOL))
        self.assertEqual({o["status"] for o in receipt["orders"]}, {"PLANNED"})
        self.assertEqual(exchange.orders, [])
        self.assertEqual(live.state["cycle_count"], 1)

    def test_execute_cycle_places_orders_when_authorized(self):
        exchange = FakeExchange()
        live = self._live(exchange)
        with mock.patch.dict(os.environ, {"QOUNT_LIVE_ENABLE": "true",
                                          "QOUNT_PRIMARY_STRATEGY": STRATEGY_ID}):
            receipt = live.cycle(execute=True)
        self.assertEqual(receipt["auto_action"], "RESIZE")
        self.assertTrue(receipt["orders_authorized"])
        self.assertEqual(len(exchange.orders), len(POOL))
        self.assertEqual({o[3].split("-")[2] for o in exchange.orders}, set(POOL))

    def test_execute_without_env_gates_is_blocked(self):
        exchange = FakeExchange()
        live = self._live(exchange)
        with mock.patch.dict(os.environ, {"QOUNT_LIVE_ENABLE": "false"}, clear=False):
            receipt = live.cycle(execute=True)
        self.assertEqual(receipt["auto_action"], "BLOCKED")
        self.assertEqual(exchange.orders, [])
        self.assertEqual(exchange.config_calls, [])

    def test_execute_cycle_normalizes_account_config(self):
        exchange = FakeExchange()
        live = self._live(exchange)
        with mock.patch.dict(os.environ, {"QOUNT_LIVE_ENABLE": "true",
                                          "QOUNT_PRIMARY_STRATEGY": STRATEGY_ID}):
            receipt = live.cycle(execute=True)
        self.assertEqual(receipt["auto_action"], "RESIZE")
        self.assertEqual({(s, v) for kind, s, v in exchange.config_calls if kind == "leverage"},
                         {(s, 3) for s in POOL})
        self.assertEqual({(s, v) for kind, s, v in exchange.config_calls if kind == "marginType"},
                         {(s, "CROSSED") for s in POOL})

    def test_plan_only_never_touches_account_config(self):
        exchange = FakeExchange()
        live = self._live(exchange)
        receipt = live.cycle(execute=False)
        self.assertEqual(receipt["auto_action"], "RESIZE")
        self.assertEqual(exchange.config_calls, [])

    def test_margin_type_in_position_error_is_tolerated(self):
        exchange = FakeExchange()
        exchange.margin_error = RuntimeError(
            'binance {"code":-4048,"msg":"Margin type cannot be changed in position"}')
        live = self._live(exchange)
        with mock.patch.dict(os.environ, {"QOUNT_LIVE_ENABLE": "true",
                                          "QOUNT_PRIMARY_STRATEGY": STRATEGY_ID}):
            receipt = live.cycle(execute=True)
        self.assertEqual(receipt["auto_action"], "RESIZE")

    def test_unexpected_account_config_error_blocks(self):
        exchange = FakeExchange()
        exchange.margin_error = RuntimeError('binance {"code":-2015,"msg":"Invalid API-key"}')
        live = self._live(exchange)
        with mock.patch.dict(os.environ, {"QOUNT_LIVE_ENABLE": "true",
                                          "QOUNT_PRIMARY_STRATEGY": STRATEGY_ID}):
            receipt = live.cycle(execute=True)
        self.assertEqual(receipt["auto_action"], "BLOCKED")
        self.assertTrue(receipt["execution_blocker"].startswith("account_config_margin_type:"))
        self.assertEqual(exchange.orders, [])

    def test_isolated_liq_too_close_blocks(self):
        exchange = FakeExchange()
        exchange.v2_positions = [{"symbol": "SOLUSDT", "positionAmt": "0.08",
                                  "markPrice": "91.0", "liquidationPrice": "88.0",
                                  "marginType": "isolated"}]
        live = self._live(exchange)
        receipt = live.cycle(execute=False)
        self.assertEqual(receipt["auto_action"], "BLOCKED")
        self.assertEqual(receipt["execution_blocker"], "isolated_liq_too_close")

    def test_duplicate_signal_date_is_no_action(self):
        exchange = FakeExchange()
        yesterday = time.strftime("%Y-%m-%d", time.gmtime(
            (int(time.time() * 1000) // 86_400_000 - 1) * 86_400_000 / 1000))
        live = self._live(exchange, state={"last_signal_date": yesterday,
                                          "cycle_count": 1})
        receipt = live.cycle(execute=False)
        self.assertEqual(receipt["auto_action"], "NO_ACTION")
        self.assertEqual(receipt["reason"], "signal_date_already_processed")

    def test_within_band_cycle_does_not_resize(self):
        target = 43.87 * 2 / 11
        positions = {s: round(target * 1.02 / 100.0, 3) for s in POOL}
        exchange = FakeExchange(positions=positions)
        live = self._live(exchange, state={"cycle_count": 1})
        receipt = live.cycle(execute=False)
        self.assertEqual(receipt["auto_action"], "NO_ACTION")
        self.assertEqual(receipt["reason"], "within_drift_band")

    def test_breach_triggers_resize_off_schedule(self):
        target = 43.87 * 2 / 11
        positions = {s: round(target * 1.40 / 100.0, 3) for s in POOL}
        exchange = FakeExchange(positions=positions)
        live = self._live(exchange, state={"cycle_count": 1})
        receipt = live.cycle(execute=False)
        self.assertEqual(receipt["auto_action"], "RESIZE")
        self.assertTrue(receipt["drift_breach"])

    def test_missing_leg_triggers_off_schedule_resize(self):
        positions = {s: 0.079 for s in POOL}
        positions.pop("XAUUSDT")                    # wrongly closed leg
        exchange = FakeExchange(positions=positions)
        live = self._live(exchange, state={"cycle_count": 1})
        receipt = live.cycle(execute=False)
        self.assertEqual(receipt["auto_action"], "RESIZE")
        self.assertTrue(receipt["drift_breach"])

    def test_cycle_keeps_granular_leg_near_target(self):
        # 2026-11-05 incident end to end: XAU at 4071.67, held 0.002 (8.14U)
        # against a 7.98U target must plan HOLD, never CLOSE.
        prices = {s: 100.0 for s in POOL}
        prices["XAUUSDT"] = 4071.67
        positions = {s: 0.079 for s in POOL}
        positions["XAUUSDT"] = 0.002
        exchange = FakeExchange(positions=positions, prices=prices)
        live = self._live(exchange)                 # cycle_count 0 -> scheduled
        receipt = live.cycle(execute=False)
        self.assertEqual(receipt["auto_action"], "RESIZE")
        xau = next(leg for leg in receipt["plan"] if leg["symbol"] == "XAUUSDT")
        self.assertEqual(xau["action"], "HOLD")
        self.assertEqual(xau["desired_quantity"], 0.002)

    def test_order_identity_is_idempotent_across_reruns(self):
        exchange = FakeExchange()
        live = self._live(exchange)
        with mock.patch.dict(os.environ, {"QOUNT_LIVE_ENABLE": "true",
                                          "QOUNT_PRIMARY_STRATEGY": STRATEGY_ID}):
            first = live.cycle(execute=True)
            live2 = self._live(exchange, state={"cycle_count": 1})
            # Rerun with lost dedup state re-plans the same signal date, but
            # every identity is already claimed in the store: RECONCILED, and
            # the venue never sees a second order.
            second = live2.cycle(execute=True)
        self.assertEqual(first["auto_action"], "RESIZE")
        self.assertEqual(second["auto_action"], "RESIZE")
        self.assertEqual({o["status"] for o in second["orders"]}, {"RECONCILED"})
        self.assertEqual(len(exchange.orders), len(POOL))

    def test_cycle_blocks_on_positions_outside_pool(self):
        exchange = FakeExchange(positions={"BTCUSDT": 0.1})
        live = self._live(exchange)
        receipt = live.cycle(execute=False)
        self.assertEqual(receipt["auto_action"], "BLOCKED")
        self.assertEqual(receipt["execution_blocker"], "positions_outside_pool")
        self.assertEqual(exchange.orders, [])


if __name__ == "__main__":
    unittest.main()
