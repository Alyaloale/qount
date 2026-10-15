"""Smoke tests for FastAPI endpoints and database storage."""

from __future__ import annotations

import os
import json
import tempfile
import unittest
from fastapi.testclient import TestClient

from qount.api.db import (
    get_last_ingest_time,
    get_paper_line,
    get_paper_lines_count,
    get_paper_lines_summary,
    get_paper_positions,
    get_paper_trades,
    init_db,
    log_ingest,
    save_paper_line,
)
from qount.api.ingest import run_ingest
from qount.api.main import app
from qount.api.schemas import LineMetrics, LineSource, NavPoint, PaperLine, PositionItem


class TestApiSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from unittest.mock import patch
        cls.temp_db = tempfile.TemporaryDirectory()
        cls.environment = patch.dict(os.environ, {"QOUNT_DB_PATH": os.path.join(cls.temp_db.name, "api.db")})
        cls.environment.start()
        init_db()
        run_ingest()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()
        cls.environment.stop()
        cls.temp_db.cleanup()

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

    def test_account_missing_baseline_reports_no_figures(self) -> None:
        """An existing package without the requested model must not look like 1m NAV."""
        import json
        import qount.api.routes.account as account_module

        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = os.path.join(tmpdir, "summary.json")
            with open(package_path, "w", encoding="utf-8") as handle:
                json.dump({"generated_at": "2026-10-12T12:00:00Z", "assets": {}}, handle)
            original_source = os.environ.get("QOUNT_ACCOUNT_SOURCE_PATH")
            os.environ["QOUNT_ACCOUNT_SOURCE_PATH"] = package_path
            try:
                snapshot = account_module.load_account_snapshot()
            finally:
                if original_source is None:
                    os.environ.pop("QOUNT_ACCOUNT_SOURCE_PATH", None)
                else:
                    os.environ["QOUNT_ACCOUNT_SOURCE_PATH"] = original_source

        self.assertIsNotNone(snapshot.error)
        self.assertIn("BASELINE_ABSENT", snapshot.error)
        self.assertEqual(snapshot.nav, 0.0)
        self.assertEqual(snapshot.cash, 0.0)
        self.assertEqual(snapshot.positions, [])

    def test_account_missing_trade_file_has_no_fabricated_entry_date(self) -> None:
        """A known baseline without a trades artifact has no sourced entry date."""
        import json
        import qount.api.routes.account as account_module

        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = os.path.join(tmpdir, "summary.json")
            with open(package_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "generated_at": "2026-10-12T12:00:00Z",
                        "assets": {
                            "513100.SH": {
                                "baselines": [
                                    {
                                        "model_name": "MA120_Band1.5pct",
                                        "terminal_equity": 123456.0,
                                        "end_date": "20261009",
                                    }
                                ]
                            }
                        },
                    },
                    handle,
                )
            original_source = os.environ.get("QOUNT_ACCOUNT_SOURCE_PATH")
            original_trades = os.environ.get("QOUNT_ACCOUNT_TRADES_PATH")
            os.environ["QOUNT_ACCOUNT_SOURCE_PATH"] = package_path
            os.environ["QOUNT_ACCOUNT_TRADES_PATH"] = os.path.join(tmpdir, "missing-trades.json")
            try:
                snapshot = account_module.load_account_snapshot()
            finally:
                if original_source is None:
                    os.environ.pop("QOUNT_ACCOUNT_SOURCE_PATH", None)
                else:
                    os.environ["QOUNT_ACCOUNT_SOURCE_PATH"] = original_source
                if original_trades is None:
                    os.environ.pop("QOUNT_ACCOUNT_TRADES_PATH", None)
                else:
                    os.environ["QOUNT_ACCOUNT_TRADES_PATH"] = original_trades

        self.assertEqual(snapshot.positions, [])
        self.assertEqual(snapshot.positions_status, "UNKNOWN")

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
                nav_series=[
                    NavPoint(date="2026-10-10T00:00:00Z", nav=1.1),
                    NavPoint(date="2026-10-09T15:00:30Z", nav=1.05),
                    NavPoint(date="2026-10-09", nav=1.0),
                ],
                metrics=LineMetrics(cagr_pct=10.0),
                source=LineSource(path="dummy"),
            )
            save_paper_line(line, db_path=test_db)
            self.assertEqual(get_paper_lines_count(test_db), 1)

            retrieved = get_paper_line("iso_test", db_path=test_db)
            self.assertIsNotNone(retrieved)
            self.assertEqual(retrieved.line_id, "iso_test")
            self.assertEqual(
                [point.date for point in retrieved.nav_series],
                ["2026-10-09", "2026-10-09T15:00:30Z", "2026-10-10T00:00:00Z"],
            )
            self.assertIsNone(retrieved.nav_series[0].benchmark_nav)

            log_ingest("iso_test", ok=True, message="Test message", db_path=test_db)
            self.assertIsNotNone(get_last_ingest_time(test_db))

            retired = line.model_copy(update={"line_id": "retired_line"})
            save_paper_line(retired, db_path=test_db)
            disabled = line.model_copy(update={"line_id": "disabled_line"})
            save_paper_line(disabled, db_path=test_db)
            registry_path = os.path.join(tmpdir, "registry.json")
            with open(registry_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "lines": [
                            {
                                "id": "dual_g20",
                                "adapter": "dual_engine",
                                "name": "G20",
                                "enabled": True,
                                "config": {"account": "g20", "root": os.path.join(tmpdir, "missing")},
                            },
                            {"id": "disabled_line", "enabled": False},
                        ]
                    },
                    handle,
                )

            # Ingestion prunes rows no longer represented in the active registry.
            ingest_res = run_ingest(registry_path=registry_path, db_path=test_db)
            self.assertFalse(ingest_res["ok"])
            self.assertEqual(ingest_res["status"], "failed")
            self.assertEqual(ingest_res["processed"], 0)
            self.assertEqual(ingest_res["results"]["dual_g20"]["status"], "MISSING")
            self.assertIsNone(get_paper_line("iso_test", db_path=test_db))
            self.assertIsNone(get_paper_line("retired_line", db_path=test_db))
            self.assertIsNone(get_paper_line("disabled_line", db_path=test_db))
            missing_line = get_paper_line("dual_g20", db_path=test_db)
            self.assertEqual(missing_line.status, "ACTIVE_PAPER")
            self.assertEqual(missing_line.data_status, "MISSING")

    def test_position_snapshot_diff_creates_timestamped_simulated_trades(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = os.path.join(tmpdir, "positions.db")
            api_config = os.path.join(tmpdir, "api.json")
            with open(api_config, "w", encoding="utf-8") as handle:
                json.dump({"paper_trade_cost_bps": {"rotation": 25}}, handle)
            original_config = os.environ.get("QOUNT_API_CONFIG")
            os.environ["QOUNT_API_CONFIG"] = api_config
            try:
                source = LineSource(path="synthetic-two-snapshot-test")
                first = PaperLine(
                    line_id="rotation", name="Rotation", as_of="2026-10-10",
                    nav_series=[NavPoint(date="2026-10-10T15:00:00Z", nav=1.0)],
                    positions=[PositionItem(symbol="AAA", weight=1.0, quantity=2, price=10, market_value=20)],
                    position_status="KNOWN",
                    source=source,
                )
                second = first.model_copy(update={
                    "nav_series": [NavPoint(date="2026-10-10T15:15:00Z", nav=1.01)],
                    "positions": [PositionItem(symbol="BBB", weight=1.0, quantity=4, price=5, market_value=20)],
                })
                save_paper_line(first, db_path=test_db)
                save_paper_line(second, db_path=test_db)
            finally:
                if original_config is None:
                    os.environ.pop("QOUNT_API_CONFIG", None)
                else:
                    os.environ["QOUNT_API_CONFIG"] = original_config

            position_rows = get_paper_positions("rotation", start="2026-10-10", end="2026-10-10", db_path=test_db)
            trades = get_paper_trades("rotation", db_path=test_db)
            self.assertEqual(len(position_rows), 3)
            self.assertEqual({row.date for row in position_rows}, {
                "2026-10-10T15:00:00.000000Z", "2026-10-10T15:15:00.000000Z"
            })
            self.assertTrue(all(row.record_kind == "simulated_not_realized" for row in position_rows))
            self.assertEqual({(trade.symbol, trade.side) for trade in trades}, {("AAA", "SELL"), ("BBB", "BUY")})
            self.assertEqual(len(trades), 2)
            self.assertTrue(all(trade.record_kind == "simulated_not_realized" for trade in trades))
            self.assertTrue(all(trade.cost is not None for trade in trades))

    def test_weight_only_positions_remain_unknown_quantity_and_signal_nav_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = os.path.join(tmpdir, "weight-only.db")
            source = LineSource(path="weight-only-source")
            first = PaperLine(
                line_id="weight_only", name="Weight only", as_of="2026-10-10",
                nav_series=[NavPoint(date="2026-10-10T15:00:00Z", nav=1.0, signal_nav=1.01)],
                positions=[PositionItem(symbol="ETF", weight=0.7, quantity=None)],
                position_status="KNOWN", source=source,
            )
            second = first.model_copy(update={
                "nav_series": [NavPoint(date="2026-10-11T15:00:00Z", nav=1.02, signal_nav=1.04)],
                "positions": [PositionItem(symbol="ETF", weight=0.65, quantity=None)],
            })
            save_paper_line(first, db_path=test_db)
            save_paper_line(second, db_path=test_db)
            detail = get_paper_line("weight_only", db_path=test_db)
            positions = get_paper_positions("weight_only", db_path=test_db)
            trades = get_paper_trades("weight_only", db_path=test_db)
        self.assertEqual(detail.nav_series[-1].signal_nav, 1.04)
        self.assertEqual(positions[-1].action, "ADJUST")
        self.assertIsNone(positions[-1].quantity)
        self.assertEqual(trades, [])

    def test_position_and_trade_readonly_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = os.path.join(tmpdir, "api-ledger.db")
            original_db = os.environ.get("QOUNT_DB_PATH")
            os.environ["QOUNT_DB_PATH"] = test_db
            try:
                line = PaperLine(
                    line_id="api_line", name="API line", as_of="2026-10-10",
                    nav_series=[NavPoint(date="2026-10-10T15:00:00Z", nav=1.0)],
                    positions=[PositionItem(symbol="AAA", weight=1.0, quantity=1, price=20, market_value=20)],
                    position_status="KNOWN",
                    source=LineSource(path="api-test"),
                )
                save_paper_line(line)
                client = TestClient(app)
                position_response = client.get("/paper/positions?line_id=api_line")
                trade_response = client.get("/paper/trades?line_id=api_line")
            finally:
                if original_db is None:
                    os.environ.pop("QOUNT_DB_PATH", None)
                else:
                    os.environ["QOUNT_DB_PATH"] = original_db
        self.assertEqual(position_response.status_code, 200)
        self.assertEqual(len(position_response.json()), 1)
        self.assertEqual(position_response.json()[0]["record_kind"], "simulated_not_realized")
        self.assertEqual(trade_response.status_code, 200)
        self.assertEqual(trade_response.json(), [])


if __name__ == "__main__":
    unittest.main()
