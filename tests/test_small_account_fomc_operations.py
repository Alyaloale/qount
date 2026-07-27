from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from qount.small_account import load_fomc_event_definition
from scripts.operations.run_fomc_shadow import main


ROOT = Path(__file__).resolve().parents[1]
EVENT_CONFIG = ROOT / "deploy" / "events" / "fomc-2026-07.json"


class FomcOperationsTest(unittest.TestCase):
    def test_release_event_definition_is_frozen_and_order_free(self) -> None:
        raw = json.loads(EVENT_CONFIG.read_text(encoding="ascii"))
        event = load_fomc_event_definition(EVENT_CONFIG)

        self.assertEqual(event.validate(), ())
        self.assertEqual(event.symbol, "BTCUSDT")
        self.assertEqual(event.statement_at, "2026-07-29T18:00:00+00:00")
        self.assertEqual(event.force_exit_at, "2026-07-30T11:00:00+00:00")
        self.assertEqual(
            event.source_hash,
            "7a2aa9a08cd03847bd8befc9aa73f5f7978217fdabc31d253b5659b2c94f16f2",
        )
        self.assertEqual(
            raw["permissions"],
            {
                "orders_authorized": False,
                "paper_or_live_allowed": False,
                "private_api_allowed": False,
            },
        )

    def test_cli_scheduled_smoke_uses_no_market_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = main(
                    (
                        "--event-config",
                        str(EVENT_CONFIG),
                        "--state-root",
                        str(root / "fomc"),
                        "--notification-store",
                        str(root / "notifications" / "store.sqlite3"),
                        "--observed-at",
                        "2026-07-29T17:00:00Z",
                    )
                )
            result = json.loads(output.getvalue())

            self.assertEqual(status, 0)
            self.assertEqual(result["stage"], "SCHEDULED")
            self.assertIsNone(result["batch_id"])
            self.assertIsNone(result["side"])
            self.assertFalse(result["permissions"]["private_api_used"])
            self.assertFalse(result["permissions"]["exchange_mutation_attempted"])

    def test_systemd_runtime_has_no_secret_or_order_authority_path(self) -> None:
        service = (
            ROOT / "deploy" / "systemd" / "qount-fomc-shadow.service"
        ).read_text(encoding="ascii")
        timer = (
            ROOT / "deploy" / "systemd" / "qount-fomc-shadow.timer"
        ).read_text(encoding="ascii")

        self.assertIn("Type=oneshot", service)
        self.assertIn("orders impossible", service)
        self.assertIn("QOUNT_MODE=shadow", service)
        self.assertIn("QOUNT_LIVE_ENABLE=false", service)
        self.assertIn("QOUNT_MINI_TREND_LIVE_ENABLE=false", service)
        self.assertIn("UnsetEnvironment=", service)
        self.assertIn("QOUNT_BINANCE_API_KEY", service)
        self.assertIn("QOUNT_BINANCE_API_SECRET", service)
        self.assertNotIn("EnvironmentFile=", service)
        self.assertIn("run_fomc_shadow.py", service)
        self.assertIn("ProtectSystem=strict", service)
        self.assertIn("ReadWritePaths=/var/lib/qount/fomc", service)
        self.assertIn(
            "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
            service,
        )
        self.assertIn("2026-07-29 17..23:0/5:00 UTC", timer)
        self.assertIn("2026-07-30 11:00:00 UTC", timer)
        self.assertNotIn("OnCalendar=*-*-*", timer)
        self.assertIn("Unit=qount-fomc-shadow.service", timer)

    def test_dashboard_marks_event_strategy_alerts(self) -> None:
        app = (ROOT / "web" / "site" / "app.js").read_text(encoding="utf-8")
        style = (ROOT / "web" / "site" / "style.css").read_text(encoding="utf-8")

        self.assertIn('event_strategy: "事件策略"', app)
        self.assertIn('fomc_event_cash_only: "FOMC 现金窗口"', app)
        self.assertIn('fomc_event_signal: "FOMC 交易信号"', app)
        self.assertIn('row.source_type === "event_strategy"', app)
        self.assertIn("openEventAlertCount", app)
        self.assertIn(".event-incident", style)
        self.assertIn(".source-badge", style)
        self.assertRegex(
            (ROOT / "web" / "site" / "index.html").read_text(),
            r'<script src="app\.js\?v=\d+"></script>',
        )


if __name__ == "__main__":
    unittest.main()
