from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from qount.contracts import canonical_hash
from qount.notifications import AlertEvent
from qount.notifications import NotificationStore
from scripts.operations import run_notification_retry


OCCURRED_AT = "2026-07-27T04:30:00+00:00"
RECORDED_AT = "2026-07-27T04:30:01+00:00"


def _alert(index: int) -> AlertEvent:
    return AlertEvent.create(
        severity="INFO",
        category="daily_intelligence",
        title=f"Qount daily review {index}",
        summary="Fixture review completed.",
        occurred_at=OCCURRED_AT,
        source_type="intelligence",
        source_id=canonical_hash({"retry_source": index}),
        source_hash=canonical_hash({"retry_payload": index}),
        dedupe_key=f"daily_intelligence:retry:{index}",
    )


class _AcceptingTransport:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def available_rate_slots(self) -> int:
        return 2 - len(self.calls)

    def __call__(self, payload, delivery_key):
        self.calls.append(delivery_key)
        return {"accepted": True}


class NotificationRetryCliTest(unittest.TestCase):
    def test_cli_processes_only_two_due_openclaw_weixin_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store_path = root / "notifications" / "store.sqlite3"
            store = NotificationStore(store_path)
            for index in range(3):
                store.enqueue(
                    _alert(index),
                    recorded_at=RECORDED_AT,
                    channels=("openclaw_weixin", "wecom"),
                )
            credential = root / "openclaw-weixin.json"
            credential.write_text("fixture", encoding="ascii")
            context_directory = root / "accounts"
            context_directory.mkdir()
            transport = _AcceptingTransport()
            output = io.StringIO()

            with patch.object(
                run_notification_retry,
                "ProviderTransport",
                return_value=transport,
            ) as transport_factory, redirect_stdout(output):
                result = run_notification_retry.main(
                    [
                        "--notification-store",
                        str(store_path),
                        "--credential-path",
                        str(credential),
                        "--context-token-directory",
                        str(context_directory),
                    ]
                )
            rows = store.verified_rows()

        self.assertEqual(result, 0)
        self.assertEqual(len(transport.calls), 2)
        summary = json.loads(output.getvalue())
        self.assertEqual(summary["channel"], "openclaw_weixin")
        self.assertEqual(summary["processed"], 2)
        self.assertEqual(summary["status_counts"], {"DELIVERED": 2})
        openclaw_jobs = [
            row for row in rows["jobs"] if row["channel"] == "openclaw_weixin"
        ]
        wecom_jobs = [row for row in rows["jobs"] if row["channel"] == "wecom"]
        self.assertEqual(
            sorted(row["status"] for row in openclaw_jobs),
            ["DELIVERED", "DELIVERED", "PENDING"],
        )
        self.assertEqual({row["status"] for row in wecom_jobs}, {"PENDING"})
        kwargs = transport_factory.call_args.kwargs
        self.assertTrue(kwargs["require_credential"])
        self.assertEqual(kwargs["rate_limit"].max_calls, 2)

    def test_cli_rejects_batches_larger_than_provider_capacity(self) -> None:
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            run_notification_retry._parser().parse_args(
                [
                    "--notification-store",
                    "/tmp/notifications.sqlite3",
                    "--credential-path",
                    "/tmp/openclaw-weixin.json",
                    "--context-token-directory",
                    "/tmp/accounts",
                    "--limit",
                    "3",
                ]
            )

    def test_systemd_templates_are_bounded_and_have_no_trading_secrets(self) -> None:
        root = Path(__file__).resolve().parents[1]
        service = (
            root / "deploy/systemd/qount-notification-retry.service"
        ).read_text(encoding="utf-8")
        timer = (
            root / "deploy/systemd/qount-notification-retry.timer"
        ).read_text(encoding="utf-8")

        self.assertIn("run_notification_retry.py", service)
        self.assertIn("--limit 2", service)
        self.assertNotIn("run_daily_intelligence.py", service)
        self.assertNotIn("EnvironmentFile=", service)
        self.assertIn("QOUNT_BINANCE_API_KEY", service)
        self.assertIn("QOUNT_ALPHA_AGENT_API_KEY", service)
        self.assertIn("ProtectSystem=strict", service)
        self.assertIn("ProtectHome=read-only", service)
        self.assertIn("ReadWritePaths=/var/lib/qount/notifications", service)
        self.assertIn("OnCalendar=*:0/5", timer)
        self.assertIn("Unit=qount-notification-retry.service", timer)


if __name__ == "__main__":
    unittest.main()
