"""Smoke tests for FastAPI endpoints and database storage."""

from __future__ import annotations

import os
import tempfile
import unittest
from fastapi.testclient import TestClient

from qount.api.db import (
    get_last_ingest_time,
    get_paper_line,
    get_paper_lines_count,
    get_paper_lines_summary,
    init_db,
    log_ingest,
    save_paper_line,
)
from qount.api.ingest import run_ingest
from qount.api.main import app
from qount.api.schemas import LineMetrics, LineSource, NavPoint, PaperLine


class TestApiSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_health_endpoint(self) -> None:
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["db_connected"])
        self.assertTrue(data["safety"]["research_only"])
        self.assertFalse(data["safety"]["orders_authorized"])

    def test_account_endpoint(self) -> None:
        resp = self.client.get("/account")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["mode"], "PAPER")
        self.assertEqual(data["source_kind"], "local_snapshot")
        self.assertEqual(data["currency"], "CNY")
        self.assertTrue(data["safety"]["research_only"])
        self.assertFalse(data["safety"]["orders_authorized"])
        # Either the reconciled package is present and yields a NAV, or it is absent and the
        # endpoint reports why. What it must never do is invent a figure.
        if data.get("error"):
            self.assertEqual(data["nav"], 0.0, "an unavailable source must not carry a NAV")
        else:
            self.assertGreater(data["nav"], 0)

    def test_account_missing_source_reports_no_figures(self) -> None:
        """Regression: an absent package must not be replaced by a synthetic balance."""
        import qount.api.routes.account as account_module

        original = os.environ.get("QOUNT_ACCOUNT_SOURCE_PATH")
        os.environ["QOUNT_ACCOUNT_SOURCE_PATH"] = "/nonexistent/package/summary.json"
        try:
            snapshot = account_module.load_account_snapshot()
        finally:
            if original is None:
                os.environ.pop("QOUNT_ACCOUNT_SOURCE_PATH", None)
            else:
                os.environ["QOUNT_ACCOUNT_SOURCE_PATH"] = original
        self.assertIsNotNone(snapshot.error)
        self.assertIn("SOURCE_NOT_FOUND", snapshot.error)
        self.assertEqual(snapshot.nav, 0.0)
        self.assertEqual(snapshot.cash, 0.0)

    def test_account_live_endpoint_reports_readonly(self) -> None:
        """The live endpoint must always be read-only and never borrow PAPER figures."""
        resp = self.client.get("/account/live")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["mode"], "LIVE_READONLY")
        self.assertEqual(data["source_kind"], "binance_api")
        self.assertTrue(data["read_only"])
        self.assertFalse(data["safety"]["orders_authorized"])
        # Local hosts hold no observation file; the endpoint must say so rather than
        # falling back to the paper NAV.
        if data.get("error"):
            self.assertEqual(data["nav"], 0.0)
            self.assertEqual(data["balances"], [])

    def test_paper_lines_list(self) -> None:
        resp = self.client.get("/paper/lines")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 1)
        # Summaries should NOT contain nav_series
        for item in data:
            self.assertNotIn("nav_series", item)
            self.assertIn("line_id", item)
            self.assertIn("status", item)

    def test_paper_line_detail(self) -> None:
        resp = self.client.get("/paper/lines/personal_assistant")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["line_id"], "personal_assistant")
        self.assertIn("nav_series", data)
        self.assertGreater(len(data["nav_series"]), 0)
        self.assertEqual(data["status"], "ACTIVE_PAPER")

    def test_paper_line_not_found(self) -> None:
        resp = self.client.get("/paper/lines/non_existent_12345")
        self.assertEqual(resp.status_code, 404)

    def test_research_registry(self) -> None:
        resp = self.client.get("/research/registry")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("registry", data)
        self.assertIn("available_adapters", data)
        self.assertIn("lines_adapter_status", data)

    def test_market_klines(self) -> None:
        resp = self.client.get("/market/klines?symbol=BTCUSDT&start=2021-01&end=2021-03")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["symbol"], "BTCUSDT")
        self.assertEqual(data["source"], "cache")
        self.assertEqual(len(data["bars"]), 90)
        self.assertIn("coverage", data)

    def test_static_routes(self) -> None:
        resp_root = self.client.get("/")
        self.assertEqual(resp_root.status_code, 200)
        self.assertIn("text/html", resp_root.headers.get("content-type", ""))

        resp_css = self.client.get("/style.css")
        self.assertEqual(resp_css.status_code, 200)

        resp_js = self.client.get("/app.js")
        self.assertEqual(resp_js.status_code, 200)

    def test_database_isolation_and_ingest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = os.path.join(tmpdir, "isolated.db")
            init_db(test_db)
            self.assertEqual(get_paper_lines_count(test_db), 0)

            line = PaperLine(
                line_id="iso_test",
                name="Isolated Line",
                as_of="2026-10-09",
                nav_series=[NavPoint(date="2026-10-09", nav=1.0)],
                metrics=LineMetrics(cagr_pct=10.0),
                source=LineSource(path="dummy"),
            )
            save_paper_line(line, db_path=test_db)
            self.assertEqual(get_paper_lines_count(test_db), 1)

            retrieved = get_paper_line("iso_test", db_path=test_db)
            self.assertIsNotNone(retrieved)
            self.assertEqual(retrieved.line_id, "iso_test")
            self.assertEqual(len(retrieved.nav_series), 1)

            log_ingest("iso_test", ok=True, message="Test message", db_path=test_db)
            self.assertIsNotNone(get_last_ingest_time(test_db))

            # Test run_ingest into isolated DB
            ingest_res = run_ingest(db_path=test_db)
            self.assertTrue(ingest_res["ok"])
            self.assertGreaterEqual(ingest_res["processed"], 1)


if __name__ == "__main__":
    unittest.main()
