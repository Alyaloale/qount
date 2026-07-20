from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from qount.contracts import canonical_hash
from qount.ledger import build_runtime_ledger_snapshot
from qount.notifications import AlertEvent
from qount.notifications import NotificationStore
from qount.notifications import build_notification_snapshot
from qount.reporting import DailyBriefError
from qount.reporting import DashboardReadModelError
from qount.reporting import build_dashboard_v1
from qount.reporting import build_daily_brief
from qount.reporting import daily_brief_from_dict
from qount.reporting import publish_dashboard_v1
from qount.reporting import read_dashboard_v1
from qount.reporting import validate_daily_brief_sources
from tests.test_ledger_dashboard_bridge import CAPTURED_AT
from tests.test_ledger_dashboard_bridge import _ledger_with_accounting
from tests.test_system_health import _health_snapshot


def _notification_snapshot(root: Path, *, severity: str = "INFO"):
    store = NotificationStore(root / "notifications" / "store.sqlite3")
    event = AlertEvent.create(
        severity=severity,
        category="runtime_state",
        title=f"{severity} fixture event",
        summary="Deterministic local DailyBrief fixture.",
        occurred_at="2026-07-20T00:06:10+00:00",
        source_type="runtime_ledger",
        source_id=canonical_hash({"daily_brief": "source"}),
        source_hash=canonical_hash({"daily_brief": "snapshot"}),
        dedupe_key=f"daily-brief:{severity.lower()}",
        trace_id_value=canonical_hash({"daily_brief": "trace"}),
    )
    store.enqueue(
        event,
        recorded_at="2026-07-20T00:06:15+00:00",
        channels=("webhook",),
    )
    return build_notification_snapshot(
        store,
        captured_at="2026-07-20T00:06:20+00:00",
    )


def _sources(root: Path, *, unresolved: bool = False, severity: str = "INFO"):
    ledger, batch, registry = _ledger_with_accounting(
        root / "ledger",
        unresolved=unresolved,
    )
    ledger_snapshot = build_runtime_ledger_snapshot(
        ledger,
        batch,
        captured_at=CAPTURED_AT,
    )
    notification_snapshot = _notification_snapshot(root, severity=severity)
    return batch, registry, ledger_snapshot, notification_snapshot


def _canonical_bytes(value: dict[str, object]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        + b"\n"
    )


class DailyBriefTest(unittest.TestCase):
    def test_deterministic_brief_binds_phase_b_and_c_authority(self) -> None:
        briefs = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as temporary:
                sources = _sources(Path(temporary))
                brief = build_daily_brief(*sources, generated_at=CAPTURED_AT)
                brief.validate()
                briefs.append(brief)

        self.assertEqual(briefs[0], briefs[1])
        brief = briefs[0]
        self.assertEqual(brief.status, "clear")
        self.assertEqual(
            set(brief.source_hashes),
            {
                "decision_batch_manifest",
                "strategy_registry",
                "runtime_ledger",
                "notification_store",
            },
        )
        self.assertEqual(brief.account["equity"], 1_015.9)
        self.assertEqual(brief.account["approved_target_gross"], 0.6)
        self.assertEqual(
            [row["symbol"] for row in brief.positions],
            ["BTCUSDT", "ETHUSDT"],
        )
        self.assertEqual(brief.positions[0]["strategy_links"][0]["reason_codes"], [
            "BASE_MASTER_GATE_ACTIVE",
            "BTCUSDT_TARGET_LONG",
        ])
        self.assertEqual(brief.owner_actions, ())
        self.assertFalse(brief.strategies[0]["live_orders_allowed"])
        self.assertEqual(brief.orders["runtime_order_count"], 3)
        self.assertEqual(brief.orders["fill_count"], 1)
        self.assertEqual(brief.orders["fill_notional"], 100.0)
        self.assertEqual(brief.orders["fill_fees_by_asset"], {"USDT": 0.1})
        self.assertEqual(
            brief.orders["protective_order_runtime_statuses"],
            {"CANCELED": 1},
        )
        self.assertEqual(
            brief.orders["unavailable_fields"],
            ["order_latency", "slippage"],
        )

    def test_recoverable_order_or_halt_alert_requires_halt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            sources = _sources(
                Path(temporary),
                unresolved=True,
                severity="HALT",
            )
            brief = build_daily_brief(*sources, generated_at=CAPTURED_AT)

        self.assertEqual(brief.status, "halt_required")
        self.assertEqual(
            brief.owner_actions,
            (
                "resolve_recoverable_order_states",
                "review_open_halt_alerts",
            ),
        )
        gates = {row["gate"]: row["status"] for row in brief.readiness["gates"]}
        self.assertEqual(gates["order_state_recovery"], "block")
        self.assertEqual(gates["unresolved_alerts"], "block")
        self.assertEqual(gates["live_orders_allowed"], "block")

    def test_critical_alert_requires_attention_but_not_order_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            sources = _sources(Path(temporary), severity="CRITICAL")
            brief = build_daily_brief(*sources, generated_at=CAPTURED_AT)

        self.assertEqual(brief.status, "attention_required")
        self.assertEqual(brief.owner_actions, ("review_open_critical_alerts",))
        self.assertEqual(brief.alerts["open_severity_counts"]["CRITICAL"], 1)
        self.assertEqual(
            brief.llm,
            {"status": "not_requested_deterministic_only", "reports": []},
        )

    def test_content_and_source_tamper_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            sources = _sources(Path(temporary), severity="CRITICAL")
            brief = build_daily_brief(*sources, generated_at=CAPTURED_AT)
            tampered = replace(
                brief,
                account=dict(brief.account) | {"equity": 9_999.0},
            )
            with self.assertRaisesRegex(DailyBriefError, "daily_brief_hash_invalid"):
                tampered.validate()

            mismatched_notification = replace(
                sources[3],
                snapshot_hash="f" * 64,
            )
            with self.assertRaisesRegex(
                DailyBriefError,
                "notification_snapshot_invalid",
            ):
                validate_daily_brief_sources(
                    brief,
                    sources[0],
                    sources[1],
                    sources[2],
                    mismatched_notification,
                )

    def test_canonical_round_trip_and_golden_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            sources = _sources(Path(temporary), severity="CRITICAL")
            brief = build_daily_brief(*sources, generated_at=CAPTURED_AT)
            raw = _canonical_bytes(brief.as_dict())
            loaded = daily_brief_from_dict(json.loads(raw))
        self.assertEqual(loaded, brief)

        golden_path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "daily_brief_v1_golden.json"
        )
        expected = golden_path.read_bytes()
        self.assertEqual(raw, expected)
        self.assertEqual(
            hashlib.sha256(raw).hexdigest(),
            "6ea5d7f0ca239382e672fe0b4ad9115d631f1e81548d2bda386d7f533a58e6f9",
        )

    def test_reports_model_has_independent_freshness_and_atomic_tamper_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = _sources(root, severity="CRITICAL")
            brief = build_daily_brief(*sources, generated_at=CAPTURED_AT)
            models = build_dashboard_v1(
                sources[0],
                sources[1],
                generated_at=CAPTURED_AT,
                evaluated_at="2026-07-20T00:08:10+00:00",
                stale_after_seconds=900,
                ledger_snapshot=sources[2],
                notification_snapshot=sources[3],
                daily_brief=brief,
                system_health=_health_snapshot(),
                report_stale_after_seconds=60,
            )
            self.assertEqual(models.overview.freshness["status"], "fresh")
            self.assertEqual(models.reports.freshness["status"], "stale")
            self.assertEqual(models.reports.source_hashes, {"daily_brief": brief.brief_hash})
            self.assertEqual(
                models.reports.payload["summary"]["brief_status"],
                "attention_required",
            )
            dashboard_root = root / "dashboard"
            publication = publish_dashboard_v1(dashboard_root, models)
            loaded, loaded_publication = read_dashboard_v1(dashboard_root)
            self.assertEqual(loaded, models)
            self.assertEqual(loaded_publication, publication)

            reports_path = (
                dashboard_root
                / "releases"
                / publication.publication_id
                / "reports.json"
            )
            value = json.loads(reports_path.read_text(encoding="ascii"))
            value["payload"]["brief"]["account"]["equity"] = 9_999.0
            reports_path.write_text(
                json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="ascii",
            )
            with self.assertRaisesRegex(DashboardReadModelError, "invalid|mismatch"):
                read_dashboard_v1(dashboard_root)


if __name__ == "__main__":
    unittest.main()
