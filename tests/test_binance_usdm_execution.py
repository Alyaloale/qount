import tempfile
import unittest
import os
import sqlite3
from pathlib import Path
from unittest.mock import patch

from qount.api.db import get_current_paper_position_snapshot, get_paper_trades, init_db, save_paper_line
from qount.api.main import app
from qount.api.paper_filter import is_forward_binance_line
from qount.api.schemas import LineSource, NavPoint, PaperLine, PositionItem
from qount.execution.binance_usdm import BinanceExecutionStore, BinanceUsdMExecution, OrdersNotAuthorized, normalize_order_response
from fastapi.testclient import TestClient


class BinanceUsdMExecutionRegressionTest(unittest.TestCase):
    def _line(self, source):
        return PaperLine(
            line_id="forward", name="forward", as_of="2026-10-16", freshness="FRESH",
            nav_series=[NavPoint(date="2026-10-16", nav=1.0)],
            positions=[PositionItem(symbol="BTCUSDT", quantity=1)], position_status="KNOWN",
            source=source,
        )

    def test_generic_forward_and_spot_provenance_are_hidden(self):
        generic = self._line(LineSource(path="forward.json"))
        self.assertFalse(is_forward_binance_line(generic))
        spot = self._line(LineSource(path="forward.json", venue="binance_usdm", instrument_type="1X_SPOT", price_source="binance_um_klines"))
        self.assertFalse(is_forward_binance_line(spot))
        native = self._line(LineSource(path="forward.json", venue="binance_usdm", instrument_type="USD-M", price_source="binance_um_klines"))
        self.assertTrue(is_forward_binance_line(native))

    def test_hidden_line_history_is_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            db = str(Path(folder) / "paper.db")
            init_db(db)
            save_paper_line(self._line(LineSource(path="forward.json")), db_path=db)
            self.assertEqual(get_paper_trades("forward", db_path=db), [])
            self.assertEqual(get_current_paper_position_snapshot("forward", db_path=db)["status"], "MISSING")

    def test_hidden_unknown_and_archived_lines_are_empty_at_routes(self):
        with tempfile.TemporaryDirectory() as folder:
            db = str(Path(folder) / "paper.db")
            init_db(db)
            legacy = self._line(LineSource(path="legacy.json"))
            save_paper_line(legacy, db_path=db)
            with patch.dict(os.environ, {"QOUNT_DB_PATH": db}):
                with TestClient(app) as client:
                    self.assertEqual(client.get("/paper/lines/forward").status_code, 404)
                    self.assertEqual(client.get("/paper/positions?line_id=forward").json(), [])
                    self.assertEqual(client.get("/paper/trades?line_id=forward").json(), [])
                    self.assertEqual(client.get("/paper/positions/current?line_id=forward").json()["status"], "MISSING")

            native = self._line(LineSource(path="native.json", venue="binance_usdm", instrument_type="USD-M",
                                           price_source="binance_um_klines"))
            save_paper_line(native, db_path=db)
            archived = native.model_copy(update={"status": "ARCHIVED"})
            save_paper_line(archived, db_path=db)
            with patch.dict(os.environ, {"QOUNT_DB_PATH": db}):
                with TestClient(app) as client:
                    self.assertEqual(client.get("/paper/lines/forward").status_code, 404)
                    self.assertEqual(client.get("/paper/positions?line_id=forward").json(), [])
                    self.assertEqual(client.get("/paper/trades?line_id=forward").json(), [])
                    self.assertEqual(client.get("/paper/positions/current?line_id=forward").json()["status"], "MISSING")

    def test_malformed_retained_payload_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            db = str(Path(folder) / "paper.db")
            init_db(db)
            with sqlite3.connect(db) as conn:
                conn.execute("INSERT INTO paper_lines(line_id,payload) VALUES (?,?)", ("broken", "{"))
                conn.commit()
            self.assertIsNone(get_current_paper_position_snapshot("broken", db_path=db).get("positions") or None)
            self.assertEqual(get_current_paper_position_snapshot("broken", db_path=db)["status"], "MISSING")

    def test_ccxt_fees_status_and_signed_funding_shape(self):
        response = normalize_order_response({
            "id": "900", "status": "closed", "filled": 2, "cost": 200,
            "trades": [{"id": "t1", "amount": 1, "price": 99, "fee": {"cost": .1, "currency": "USDT"}},
                        {"id": "t2", "amount": 1, "price": 101, "fees": [{"cost": .2, "currency": "BNB"}]}],
        })
        self.assertEqual(response["status"], "FILLED")
        self.assertEqual(response["executed_quantity"], 2.0)
        self.assertEqual(response["average_price"], 100.0)
        self.assertEqual(response["fills"][1]["fees"]["BNB"], .2)

    def test_fill_idempotency_and_signed_cash_event(self):
        with tempfile.TemporaryDirectory() as folder:
            store = BinanceExecutionStore(Path(folder) / "execution.db")
            payload = {"strategy_id": "s", "signal_id": "sig", "order_intent_id": "intent", "reduce_only": False}
            self.assertTrue(store.create_order(client_order_id="cid", symbol="BTCUSDT", side="buy", quantity=1, payload=payload))
            self.assertFalse(store.create_order(client_order_id="cid", symbol="BTCUSDT", side="buy", quantity=1, payload=payload))
            first = store.apply_response("cid", normalize_order_response({
                "orderId": "o1", "status": "FILLED", "executedQty": "1", "avgPrice": "100",
                "fills": [{"tradeId": "t1", "qty": "1", "price": "100", "commission": "0.1", "commissionAsset": "USDT"}],
            }))
            second = store.apply_response("cid", normalize_order_response({
                "orderId": "o1", "status": "FILLED", "executedQty": "1", "avgPrice": "100",
                "fills": [{"tradeId": "t1", "qty": "1", "price": "100", "commission": "0.1", "commissionAsset": "USDT"}],
            }))
            self.assertEqual(first["executed_quantity"], 1.0)
            self.assertEqual(second["executed_quantity"], 1.0)
            with sqlite3.connect(store.path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM fills").fetchone()[0], 1)
                trace = conn.execute("SELECT signal_id,order_intent_id,account_record_id FROM fills").fetchone()
                self.assertEqual(tuple(trace), ("sig", "intent", "fill:BTCUSDT:t1"))
            store.record_cash_event(event_key="funding:1", event_type="funding", symbol="BTCUSDT", amount=-.25, asset="USDT", occurred_at="2026-10-16T00:00:00Z", strategy_id="s", signal_id="sig", order_intent_id="intent", account_record_id="income:FUNDING_FEE:1")
            row = store.get_order("cid")
            self.assertEqual(row["signal_id"], "sig")
            self.assertEqual(row["status"], "FILLED")
            self.assertEqual(row["account_record_id"], "order:BTCUSDT:cid")
            self.assertEqual(store.inflight(), [])

    def test_cli_confirmation_cannot_authorize_orders(self):
        with tempfile.TemporaryDirectory() as folder:
            store = BinanceExecutionStore(Path(folder) / "execution.db")
            execution = BinanceUsdMExecution(exchange=object(), store=store)
            self.assertFalse(execution.orders_authorized)
            with self.assertRaises(OrdersNotAuthorized):
                execution.submit({}, confirmed=True)


if __name__ == "__main__":
    unittest.main()
