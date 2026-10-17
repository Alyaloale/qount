import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qount.execution.binance_usdm import BinanceExecutionStore
from qount.execution.one_atr_live import OneAtrArmError, OneAtrLiveExecutor, create_arm


class FakeExchange:
    def __init__(self):
        self.calls = []

    def fapiPublicGetExchangeInfo(self, _params):
        return {"symbols": [{"symbol": "CLUSDT", "status": "TRADING", "contractType": "PERPETUAL",
                              "quoteAsset": "USDT", "marginAsset": "USDT", "filters": [
                                  {"filterType": "LOT_SIZE", "minQty": "0.01", "maxQty": "1000", "stepSize": "0.01"},
                                  {"filterType": "MARKET_LOT_SIZE", "minQty": "0.01", "maxQty": "1000", "stepSize": "0.01"},
                                  {"filterType": "MIN_NOTIONAL", "notional": "5"},
                                  {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                              ]}]}

    def create_order(self, symbol, order_type, side, quantity, _price, params):
        self.calls.append((symbol, order_type, side, quantity, params))
        client_id = params["newClientOrderId"]
        if order_type == "market":
            return {"id": client_id, "orderId": "entry-1", "status": "FILLED", "executedQty": quantity,
                    "avgPrice": "100", "fills": [{"tradeId": "trade-1", "qty": quantity,
                    "price": "100", "commission": "0.01", "commissionAsset": "USDT"}]}
        return {"id": client_id, "orderId": "stop-1", "status": "NEW", "executedQty": 0}


class PartialExchange(FakeExchange):
    def create_order(self, symbol, order_type, side, quantity, _price, params):
        self.calls.append((symbol, order_type, side, quantity, params))
        client_id = params["newClientOrderId"]
        if order_type == "market":
            filled = quantity / 2
            return {"id": client_id, "orderId": "entry-partial", "status": "PARTIALLY_FILLED",
                    "executedQty": filled, "avgPrice": "100",
                    "fills": [{"tradeId": "trade-partial", "qty": filled,
                                "price": "100", "commission": "0.01", "commissionAsset": "USDT"}]}
        return {"id": client_id, "orderId": "stop-partial", "status": "NEW", "executedQty": 0}


class OneAtrLiveTest(unittest.TestCase):
    def test_entry_and_protective_stop_are_idempotent_and_consume_arm(self):
        with tempfile.TemporaryDirectory() as folder:
            store = BinanceExecutionStore(Path(folder) / "execution.db")
            plan = {"client_order_id": "q1atr-entry-1", "symbol": "CLUSDT", "side": "buy", "quantity": 0.1,
                    "price": 100, "strategy_id": "one_atr_macro_v0_1", "signal_id": "sig-1",
                    "order_intent_id": "intent-1", "reduce_only": False}
            arm = Path(folder) / "arm.json"
            create_arm(arm, arm_id="arm-1", strategy_id=plan["strategy_id"], plan=plan,
                       expires_at="2999-01-01T00:00:00Z", confirmation="owner-confirm")
            exchange = FakeExchange()
            executor = OneAtrLiveExecutor(exchange, store)
            with patch.dict(os.environ, {"QOUNT_LIVE_ENABLE": "true", "QOUNT_PRIMARY_STRATEGY": plan["strategy_id"]}):
                result = executor.execute(plan=plan, stop_price=90, arm_path=arm, confirmation="owner-confirm")
            self.assertEqual(result["entry"]["status"], "FILLED")
            self.assertEqual(result["protective"]["status"], "ACKNOWLEDGED")
            self.assertEqual(len(exchange.calls), 2)
            self.assertEqual(json.loads(arm.read_text())["status"], "used")
            with patch.dict(os.environ, {"QOUNT_LIVE_ENABLE": "true", "QOUNT_PRIMARY_STRATEGY": plan["strategy_id"]}):
                with self.assertRaises(OneAtrArmError):
                    executor.execute(plan=plan, stop_price=90, arm_path=arm, confirmation="owner-confirm")

    def test_partial_entry_is_protected_for_filled_quantity(self):
        with tempfile.TemporaryDirectory() as folder:
            store = BinanceExecutionStore(Path(folder) / "execution.db")
            plan = {"client_order_id": "q1atr-entry-partial", "symbol": "CLUSDT", "side": "buy", "quantity": 0.1,
                    "price": 100, "strategy_id": "one_atr_macro_v0_1", "signal_id": "sig-partial",
                    "order_intent_id": "intent-partial", "reduce_only": False}
            arm = Path(folder) / "arm.json"
            create_arm(arm, arm_id="arm-partial", strategy_id=plan["strategy_id"], plan=plan,
                       expires_at="2999-01-01T00:00:00Z", confirmation="owner-confirm")
            exchange = PartialExchange()
            with patch.dict(os.environ, {"QOUNT_LIVE_ENABLE": "true", "QOUNT_PRIMARY_STRATEGY": plan["strategy_id"]}):
                result = OneAtrLiveExecutor(exchange, store).execute(
                    plan=plan, stop_price=90, arm_path=arm, confirmation="owner-confirm")
            self.assertEqual(result["entry"]["status"], "PARTIALLY_FILLED")
            self.assertEqual(result["protective"]["quantity"], 0.05)
            self.assertEqual(json.loads(arm.read_text())["status"], "used")

    def test_invalid_arm_makes_no_exchange_call(self):
        with tempfile.TemporaryDirectory() as folder:
            store = BinanceExecutionStore(Path(folder) / "execution.db")
            exchange = FakeExchange()
            executor = OneAtrLiveExecutor(exchange, store)
            plan = {"client_order_id": "q1atr-entry-1", "symbol": "CLUSDT", "side": "buy", "quantity": 0.1,
                    "price": 100, "strategy_id": "one_atr_macro_v0_1", "signal_id": "sig-1",
                    "order_intent_id": "intent-1", "reduce_only": False}
            with self.assertRaises(OneAtrArmError):
                executor.execute(plan=plan, stop_price=90, arm_path=Path(folder) / "missing", confirmation="x")
            self.assertEqual(exchange.calls, [])


if __name__ == "__main__":
    unittest.main()
