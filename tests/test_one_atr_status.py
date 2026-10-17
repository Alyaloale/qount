import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from qount.api.routes.account import router


class OneAtrStatusRouteTest(unittest.TestCase):
    def test_reads_result_store_and_arm_without_exchange_calls(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            result = root / "result.json"
            store = root / "execution.sqlite3"
            arm = root / "arm.json"
            result.write_text(json.dumps({
                "strategy_id": "one_atr_macro_v0_1", "execution_mode": "live",
                "orders_authorized": True, "selected": {"symbol": "CLUSDT", "stop_price": 90},
                "created_at": "2026-10-16T10:00:00Z",
                "execution": {"entry": {"status": "FILLED"}, "protective": {"status": "ACKNOWLEDGED"}, "arm_status": "used"},
            }))
            arm.write_text(json.dumps({"status": "used"}))
            with sqlite3.connect(store) as db:
                db.executescript("""
                  create table orders (client_order_id text, symbol text, side text, status text, executed_quantity real,
                    average_price real, strategy_id text, signal_id text, order_intent_id text, account_record_id text);
                  create table protective_orders (parent_client_order_id text, protective_client_order_id text,
                    symbol text, side text, quantity real, stop_price real, status text);
                  insert into orders values ('entry','CLUSDT','buy','FILLED',0.15,96.1,'s','sig','intent','record');
                  insert into protective_orders values ('entry','stop','CLUSDT','sell',0.15,90.06,'ACKNOWLEDGED');
                """)
            app = FastAPI(); app.include_router(router)
            with patch.dict(os.environ, {
                "QOUNT_1ATR_RESULT_PATH": str(result), "QOUNT_1ATR_EXECUTION_STORE": str(store),
                "QOUNT_1ATR_ARM_PATH": str(arm), "QOUNT_1ATR_HALT_PATH": str(root / "HALT"),
            }):
                data = TestClient(app).get("/account/one-atr").json()
            self.assertEqual(data["status"], "AVAILABLE")
            self.assertTrue(data["strategy_live"])
            self.assertTrue(data["execution_authorized"])
            self.assertFalse(data["global_orders_authorized"])
            self.assertFalse(data["research_only"])
            self.assertEqual(data["selected"]["symbol"], "CLUSDT")
            self.assertEqual(data["protective_orders"][0]["status"], "ACKNOWLEDGED")
            self.assertEqual(data["arm_status"], "used")

    def test_macro_handover_exposes_actual_protection_and_does_not_inherit_legacy_orders(self):
        from datetime import datetime, timezone
        from qount.execution.binance_usdm import BinanceExecutionStore
        from qount.strategies.macro_1atr import STRATEGY_ID
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);result=root/'result.json';store=BinanceExecutionStore(root/'execution.db')
            store.create_order(client_order_id='old',symbol='CLUSDT',side='buy',quantity=.15,
                payload=dict(strategy_id='one_atr_macro_v0_1',signal_id='old-signal',order_intent_id='old-intent'))
            result.write_text(json.dumps(dict(strategy_id=STRATEGY_ID,execution_mode='auto_live',orders_authorized=True,
                created_at=datetime.now(timezone.utc).isoformat(),auto_action='HOLD_LEGACY_POSITION',
                handover='waiting_for_legacy_flat',risk_fraction=.5,
                protection_check=dict(status='PROTECTED',stop_price=90.06))))
            app=FastAPI();app.include_router(router)
            with patch.dict(os.environ,{'QOUNT_1ATR_RESULT_PATH':str(result),'QOUNT_1ATR_EXECUTION_STORE':str(store.path),
                                       'QOUNT_1ATR_ARM_PATH':str(root/'arm.json'),'QOUNT_1ATR_HALT_PATH':str(root/'HALT')}):
                data=TestClient(app).get('/account/one-atr').json()
            self.assertEqual(data['strategy_id'],STRATEGY_ID)
            self.assertEqual(data['handover'],'waiting_for_legacy_flat')
            self.assertEqual(data['protection_check']['stop_price'],90.06)
            self.assertEqual(data['orders'],[]);self.assertEqual(len(data['legacy_orders']),1)
            self.assertEqual(data['protective_orders'],[])
            self.assertFalse(data['orders_authorized']);self.assertTrue(data['execution_authorized'])
            self.assertIsNone(data['error'])


if __name__ == "__main__":
    unittest.main()
