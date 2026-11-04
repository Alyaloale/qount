"""Read-only G20-LP v3 status route test (receipt + store + state, no exchange)."""
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


class G20V3StatusRouteTest(unittest.TestCase):
    def _client_paths(self, root: Path):
        result = root / "live-result.json"
        store = root / "execution.sqlite3"
        state = root / "g20-v3-state.json"
        result.write_text(json.dumps({
            "strategy_id": "g20_leveraged_pool_v3", "execution_mode": "auto_live",
            "orders_authorized": True, "auto_action": "RESIZE", "signal_date": "2026-11-03",
            "capital_usdt": 43.8711, "scheduled_resize": True, "drift_breach": False,
            "created_at": "2026-11-04T00:00:20Z",
            "plan": [{"symbol": "SOLUSDT", "action": "BUY", "target_notional": 7.98}],
            "orders": [{"client_order_id": "v3-20261103-SOLUSDT-b", "status": "FILLED"}],
            "order_counts": {"submitted": 1, "skipped_rule": 0, "planned_only": 0},
        }))
        state.write_text(json.dumps({"cycle_count": 1, "last_signal_date": "2026-11-03"}))
        with sqlite3.connect(store) as db:
            db.executescript("""
              create table orders (client_order_id text, symbol text, side text, quantity real,
                status text, executed_quantity real, average_price real,
                strategy_id text, signal_id text, order_intent_id text, account_record_id text);
              create table fills (client_order_id text, trade_id text, symbol text, quantity real,
                price real, fee real, fee_asset text, occurred_at text,
                strategy_id text, signal_id text, order_intent_id text, account_record_id text, fees_json text);
              insert into orders values ('v3-20261103-SOLUSDT-b','SOLUSDT','buy',0.012,'FILLED',0.012,640.0,
                'g20_leveraged_pool_v3','g20v3-20261103','g20v3-20261103-SOLUSDT','order:SOLUSDT:v3-20261103-SOLUSDT-b');
              insert into fills values ('v3-20261103-SOLUSDT-b','1','SOLUSDT',0.012,640.0,0.0008,'USDT',
                '2026-11-04T00:00:20Z','g20_leveraged_pool_v3','g20v3-20261103','g20v3-20261103-SOLUSDT',
                'fill:SOLUSDT:1','{"USDT": 0.0008}');
            """)
        return result, store, state

    def test_reads_receipt_store_and_state_without_exchange_calls(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            result, store, state = self._client_paths(root)
            app = FastAPI()
            app.include_router(router)
            with patch.dict(os.environ, {
                "QOUNT_G20V3_RESULT_PATH": str(result),
                "QOUNT_G20V3_EXECUTION_STORE": str(store),
                "QOUNT_G20V3_STATE_PATH": str(state),
                "QOUNT_G20V3_HALT_PATH": str(root / "HALT"),
            }):
                data = TestClient(app).get("/account/g20-v3").json()
            self.assertEqual(data["status"], "AVAILABLE")
            self.assertEqual(data["strategy_id"], "g20_leveraged_pool_v3")
            self.assertTrue(data["orders_authorized"])
            self.assertFalse(data["research_only"])
            self.assertFalse(data["halted"])
            self.assertEqual(data["signal_date"], "2026-11-03")
            self.assertEqual(data["auto_action"], "RESIZE")
            self.assertEqual(data["cycle"]["cycle_count"], 1)
            self.assertEqual(len(data["plan"]), 1)
            self.assertEqual(data["orders"][0]["client_order_id"], "v3-20261103-SOLUSDT-b")
            self.assertEqual(len(data["executed_fills"]), 1)
            self.assertTrue(data["next_cycle_at"].endswith("+00:00"))

    def test_halt_and_missing_receipt_stay_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = FastAPI()
            app.include_router(router)
            with patch.dict(os.environ, {
                "QOUNT_G20V3_RESULT_PATH": str(root / "absent.json"),
                "QOUNT_G20V3_EXECUTION_STORE": str(root / "absent.sqlite3"),
                "QOUNT_G20V3_STATE_PATH": str(root / "absent-state.json"),
                "QOUNT_G20V3_HALT_PATH": str(root / "HALT"),
            }):
                (root / "HALT").write_text("")
                data = TestClient(app).get("/account/g20-v3").json()
            self.assertEqual(data["status"], "MISSING")
            self.assertTrue(data["halted"])
            self.assertTrue(data["error"].startswith("result_unavailable:"))
            self.assertIsNone(data["cycle"])
            self.assertEqual(data["orders"], [])


if __name__ == "__main__":
    unittest.main()
