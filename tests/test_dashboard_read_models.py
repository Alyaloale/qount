from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator
from jsonschema import FormatChecker
from referencing import Registry
from referencing import Resource

from qount.alpha_agents.models import AgentReport
from qount.contracts import canonical_hash
from qount.intelligence import DAILY_INTELLIGENCE_ROLES
from qount.intelligence import DailyIntelligenceReport
from qount.intelligence import SearchEvidence
from qount.intelligence import SourceEvidence
from qount.intelligence import build_market_pulse
from qount.intelligence import summarize_trading_history
from qount.notifications import AlertEvent
from qount.notifications import NotificationStore
from qount.notifications import build_notification_snapshot
from qount.persistence import VerifiedDecisionBatch
from qount.reporting import DashboardReadModelError
from qount.reporting import build_dashboard_v1
from qount.reporting import publish_dashboard_v1
from qount.reporting import read_dashboard_v1
from tests.test_immutable_contract_artifacts import _objects


GENERATED_AT = "2026-07-20T00:06:30+00:00"


def _sources() -> tuple[VerifiedDecisionBatch, object]:
    snapshot, intent, target, risk, plan, _, registry, _ = _objects()
    from qount.persistence import build_decision_batch_manifest

    manifest = build_decision_batch_manifest(
        snapshot=snapshot,
        intents=(intent,),
        target=target,
        risk=risk,
        plan=plan,
        created_at="2026-07-20T00:06:00+00:00",
    )
    return (
        VerifiedDecisionBatch(
            manifest=manifest,
            snapshot=snapshot,
            intents=(intent,),
            target=target,
            risk=risk,
            plan=plan,
        ),
        registry,
    )


def _models(*, evaluated_at: str = GENERATED_AT):
    batch, registry = _sources()
    return build_dashboard_v1(
        batch,
        registry,
        generated_at=GENERATED_AT,
        evaluated_at=evaluated_at,
        stale_after_seconds=300,
    )


def _notification_snapshot(root: Path):
    store = NotificationStore(root / "notifications" / "store.sqlite3")
    alert = AlertEvent.create(
        severity="CRITICAL",
        category="runtime_state",
        title="UNKNOWN order requires recovery",
        summary="The deterministic client order ID has no conclusive exchange result.",
        occurred_at="2026-07-20T00:06:10+00:00",
        source_type="runtime_ledger",
        source_id=canonical_hash({"order": "unknown-1"}),
        source_hash=canonical_hash({"ledger": "snapshot-1"}),
        dedupe_key="runtime-order:unknown-1",
        trace_id_value=canonical_hash({"batch": "batch-1"}),
    )
    store.enqueue(
        alert,
        recorded_at="2026-07-20T00:06:15+00:00",
        channels=("webhook",),
    )
    return build_notification_snapshot(
        store, captured_at="2026-07-20T00:06:20+00:00"
    )


def _daily_intelligence() -> DailyIntelligenceReport:
    pulse = build_market_pulse(
        ticker_payload=[
            {
                "symbol": symbol,
                "lastPrice": "100.5",
                "priceChangePercent": "1.25",
                "quoteVolume": "1000000",
            }
            for symbol in ("BTCUSDT", "ETHUSDT", "BNBUSDT")
        ],
        premium_payload=[
            {
                "symbol": symbol,
                "lastFundingRate": "0.0001",
                "nextFundingTime": "1784649600000",
            }
            for symbol in ("BTCUSDT", "ETHUSDT", "BNBUSDT")
        ],
        observed_at="2026-07-20T00:06:25+00:00",
        source_hashes={"ticker_24h": "a" * 64, "premium_index": "b" * 64},
    )
    history = summarize_trading_history(None)
    search = SearchEvidence(
        query="fixture search",
        provider="static_source_plan",
        searched_at="2026-07-20T00:06:25+00:00",
        result_count=1,
        response_hash="c" * 64,
        urls=("https://www.binance.com/en/support/announcement/example",),
    )
    source = SourceEvidence(
        title="Binance notice",
        source_url="https://www.binance.com/en/support/announcement/example",
        final_url="https://www.binance.com/en/support/announcement/example",
        observed_at="2026-07-20T00:06:25+00:00",
        content_type="text/html",
        byte_count=12,
        source_hash="d" * 64,
        body_hash="d" * 64,
        text_excerpt="Official notice",
        published_at="2026-07-20T00:00:00+00:00",
        modified_at=None,
        parser_version="official_source_parser_v0.2",
        content_quality="limited",
        extractor="html_main",
    )
    reports = tuple(
        AgentReport(
            role_id=role_id,
            task_id=f"daily_intelligence_{role_id}_v1",
            status="needs_research",
            summary=f"{role_id} offline review.",
            findings=("Only supplied evidence was reviewed.",),
            risks=("Deterministic validation remains required.",),
        )
        for role_id in DAILY_INTELLIGENCE_ROLES
    )
    return DailyIntelligenceReport.create(
        report_date="2026-07-20",
        created_at="2026-07-20T00:06:25+00:00",
        status="incomplete",
        pipeline_status="complete",
        evidence_status="insufficient",
        evidence_summary={
            "status": "insufficient",
            "verified_source_count": 1,
            "substantive_source_count": 0,
            "source_domain_count": 1,
            "trading_history_status": "unavailable",
            "execution_evidence_status": None,
            "gaps": ["runtime_ledger_history_unavailable"],
        },
        market_pulse=pulse,
        trading_history=history,
        searches=(search,),
        sources=(source,),
        agent_reports=reports,
        executive_summary="Daily intelligence is incomplete without a runtime ledger.",
        observed_impacts=("Market pulse is available.",),
        research_proposals=("Retest the evidence after a complete ledger snapshot.",),
        risk_notes=("No trading authority is granted.",),
        source_hashes={
            "market_pulse": pulse.pulse_hash,
            "trading_history": history["summary_hash"],
            "search_00": search.response_hash,
            "source_00": source.source_hash,
        },
        llm={
            "enabled": False,
            "model": "gpt-5.6-terra",
            "provider_profile": "relay_station_chatgpt",
        },
    )


class DashboardReadModelTest(unittest.TestCase):
    def test_builds_authoritative_overview_strategy_readiness_and_alert_models(self) -> None:
        models = _models()

        self.assertEqual(
            tuple(model.read_model_type for model in models.models()),
            (
                "overview",
                "positions",
                "orders",
                "strategies",
                "decisions",
                "risk",
                "readiness",
                "system",
                "alerts",
                "reports",
                "intelligence",
            ),
        )
        self.assertEqual(models.overview.payload["portfolio"]["approved_target_gross"], 0.6)
        self.assertEqual(
            models.overview.payload["pnl"],
            {
                "status": "unavailable_until_phase_b_ledger",
                "source": "runtime_ledger",
                "values": None,
            },
        )
        self.assertEqual(
            models.overview.payload["portfolio"]["actual_positions"],
            {
                "status": "unavailable_until_phase_b_ledger",
                "source": "runtime_ledger",
                "values": None,
            },
        )
        self.assertFalse(
            models.readiness.payload["strategies"][0]["live_orders_allowed"]
        )
        strategy = models.strategies.payload["strategies"][0]
        self.assertEqual(strategy["registry_status"], "shadow")
        self.assertEqual(strategy["execution_status"], "disarmed")
        self.assertNotIn("promotion_status", strategy)
        self.assertEqual(
            strategy["execution_blockers"],
            ["owner_authorization_missing", "registry_status_not_live"],
        )
        self.assertEqual(
            set(models.overview.source_hashes),
            {"decision_batch_manifest", "strategy_registry"},
        )
        self.assertEqual(
            models.alerts.payload["summary"]["status"],
            "unavailable_until_phase_c_notification_store",
        )
        self.assertEqual(
            models.reports.payload["summary"]["status"],
            "unavailable_until_phase_c_daily_brief",
        )
        self.assertEqual(
            models.intelligence.payload["summary"]["status"],
            "unavailable_until_daily_intelligence",
        )
        self.assertEqual(
            models.orders.payload["summary"]["status"],
            "unavailable_until_phase_b_ledger",
        )
        self.assertEqual(
            models.risk.payload["runtime"]["status"],
            "unavailable_until_phase_b_ledger",
        )
        self.assertEqual(
            models.system.payload["summary"]["status"],
            "unavailable_until_phase_b_ledger",
        )

    def test_staleness_uses_source_time_and_cannot_be_reset_by_republication(self) -> None:
        fresh = _models(evaluated_at="2026-07-20T00:10:59+00:00")
        stale = _models(evaluated_at="2026-07-20T00:11:00+00:00")

        self.assertEqual(fresh.overview.freshness["status"], "fresh")
        self.assertEqual(stale.overview.freshness["status"], "stale")
        self.assertEqual(stale.readiness.payload["status"], "stale")
        self.assertEqual(
            stale.overview.freshness["stale_at"],
            "2026-07-20T00:11:00+00:00",
        )

    def test_readonly_exchange_positions_are_not_promoted_to_ledger_facts(self) -> None:
        batch, registry = _sources()
        core = {
            "status": "blocked",
            "live_orders_allowed": False,
            "runtime_ledger_created": False,
            "strategy_id": "test_strategy",
            "blockers": ["preflight:no_unmanaged_positions"],
            "observed_at": "2026-07-20T00:06:20+00:00",
            "account_observation": {
                "source": "private_account_preflight",
                "observed_at": "2026-07-20T00:06:20+00:00",
                "quote_asset": "USDT",
                "wallet_balance": 200.0,
                "available_balance": 150.0,
                "margin_balance": 200.0,
                "margin_used": 50.0,
                "actual_gross_notional": 100.0,
                "actual_gross_fraction": 0.5,
                "margin_fraction": 0.25,
                "open_order_count": 0,
                "positions": [
                    {
                        "symbol": "BTC/USDT:USDT",
                        "side": "long",
                        "quantity": 0.001,
                        "notional": 100.0,
                    }
                ],
            },
        }
        observation = core | {"observation_hash": canonical_hash(core)}
        models = build_dashboard_v1(
            batch,
            registry,
            generated_at=GENERATED_AT,
            stale_after_seconds=300,
            blocked_runtime_observation=observation,
        )

        summary = models.positions.payload["summary"]
        row = models.positions.payload["positions"][0]
        self.assertEqual(summary["status"], "available_readonly")
        self.assertEqual(summary["fact_scope"], "exchange_account_observation")
        self.assertIsNone(summary["reconciled"])
        self.assertEqual(summary["reconciliation_status"], "unavailable")
        self.assertEqual(row["management_scope"], "outside_qount_ledger")
        self.assertIsNone(row["average_cost"])
        self.assertIsNone(row["realized_trading_pnl"])
        self.assertNotIn("trace", row)
        self.assertEqual(
            models.strategies.payload["strategies"][0]["execution_status"],
            "blocked",
        )

        schema_root = Path(__file__).resolve().parents[1] / "web" / "schemas"
        schemas = {
            path.name: json.loads(path.read_text(encoding="ascii"))
            for path in schema_root.glob("*.schema.json")
        }
        schema_registry = Registry().with_resources(
            [
                (schema["$id"], Resource.from_contents(schema))
                for schema in schemas.values()
            ]
        )
        for model in (models.positions, models.strategies, models.readiness):
            Draft202012Validator(
                schemas[f"dashboard-v1-{model.read_model_type}.schema.json"],
                registry=schema_registry,
                format_checker=FormatChecker(),
            ).validate(model.as_dict())

    def test_tampered_batch_and_registry_fail_before_model_generation(self) -> None:
        batch, registry = _sources()
        tampered_batch = replace(
            batch,
            snapshot=replace(batch.snapshot, prices={"BTCUSDT": 99_000.0}),
        )
        with self.assertRaisesRegex(
            DashboardReadModelError,
            "dashboard_sources_invalid",
        ):
            build_dashboard_v1(
                tampered_batch,
                registry,
                generated_at=GENERATED_AT,
            )

        tampered_registry = replace(registry, registry_hash="f" * 64)
        with self.assertRaisesRegex(DashboardReadModelError, "registry_hash_invalid"):
            build_dashboard_v1(
                batch,
                tampered_registry,
                generated_at=GENERATED_AT,
            )

    def test_atomic_publication_round_trips_and_uses_one_current_release(self) -> None:
        models = _models()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            publication = publish_dashboard_v1(root, models)
            loaded, loaded_publication = read_dashboard_v1(root)

            self.assertEqual(loaded, models)
            self.assertEqual(loaded_publication, publication)
            self.assertTrue((root / "v1").is_symlink())
            self.assertEqual(
                os.readlink(root / "v1"),
                f"releases/{publication.publication_id}",
            )
            release = root / "releases" / publication.publication_id
            for read_model_type, reference in publication.read_models.items():
                self.assertEqual(
                    reference["file_sha256"],
                    hashlib.sha256(
                        (release / reference["file_name"]).read_bytes()
                    ).hexdigest(),
                    read_model_type,
                )
            self.assertEqual(
                {path.name for path in release.iterdir()},
                {
                    "overview.json",
                    "positions.json",
                    "orders.json",
                    "strategies.json",
                    "decisions.json",
                    "risk.json",
                    "readiness.json",
                    "system.json",
                    "alerts.json",
                    "reports.json",
                    "intelligence.json",
                    "publication.json",
                },
            )

    def test_alert_model_has_independent_source_and_freshness(self) -> None:
        batch, registry = _sources()
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = _notification_snapshot(Path(temporary))
            models = build_dashboard_v1(
                batch,
                registry,
                generated_at=GENERATED_AT,
                evaluated_at="2026-07-20T00:08:00+00:00",
                stale_after_seconds=300,
                alert_stale_after_seconds=60,
                notification_snapshot=snapshot,
            )

            self.assertEqual(models.overview.freshness["status"], "fresh")
            self.assertEqual(models.alerts.freshness["status"], "stale")
            self.assertEqual(
                models.alerts.source_hashes,
                {"notification_store": snapshot.snapshot_hash},
            )
            self.assertEqual(models.alerts.payload["summary"]["open_alert_count"], 1)
            self.assertEqual(
                models.alerts.payload["alerts"][0]["deliveries"][0]["status"],
                "PENDING",
            )
            root = Path(temporary) / "dashboard"
            publication = publish_dashboard_v1(root, models)
            loaded, loaded_publication = read_dashboard_v1(root)
            self.assertEqual(loaded, models)
            self.assertEqual(loaded_publication, publication)

            release = root / "releases" / publication.publication_id
            alert_path = release / "alerts.json"
            value = json.loads(alert_path.read_text(encoding="ascii"))
            value["payload"]["summary"]["open_alert_count"] = 0
            alert_path.write_text(
                json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="ascii",
            )
            with self.assertRaisesRegex(DashboardReadModelError, "mismatch"):
                read_dashboard_v1(root)

    def test_intelligence_model_has_independent_source_and_freshness(self) -> None:
        batch, registry = _sources()
        report = _daily_intelligence()
        models = build_dashboard_v1(
            batch,
            registry,
            generated_at=GENERATED_AT,
            evaluated_at=GENERATED_AT,
            stale_after_seconds=300,
            intelligence_stale_after_seconds=2,
            daily_intelligence=report,
        )

        self.assertEqual(models.overview.freshness["status"], "fresh")
        self.assertEqual(models.intelligence.freshness["status"], "stale")
        self.assertEqual(
            models.intelligence.source_hashes,
            {"daily_intelligence": report.report_hash},
        )
        self.assertEqual(models.intelligence.payload["report"], report.as_dict())

    def test_failed_release_write_keeps_previous_atomic_pointer(self) -> None:
        first = _models()
        second_batch, second_registry = _sources()
        second = build_dashboard_v1(
            second_batch,
            second_registry,
            generated_at="2026-07-20T00:07:00+00:00",
            evaluated_at="2026-07-20T00:07:00+00:00",
            stale_after_seconds=300,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_publication = publish_dashboard_v1(root, first)
            real_write = __import__(
                "qount.reporting.read_models", fromlist=["_write_release_file"]
            )._write_release_file
            calls = 0

            def fail_second(path, value):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected write failure")
                return real_write(path, value)

            with patch(
                "qount.reporting.read_models._write_release_file",
                side_effect=fail_second,
            ), self.assertRaisesRegex(OSError, "injected"):
                publish_dashboard_v1(root, second)

            loaded, publication = read_dashboard_v1(root)
            self.assertEqual(loaded, first)
            self.assertEqual(publication, first_publication)
            self.assertEqual(list((root / "releases").glob("*.tmp")), [])

    def test_readback_rejects_content_tamper_extra_file_and_pointer_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            publication = publish_dashboard_v1(root, _models())
            release = root / "releases" / publication.publication_id
            overview_path = release / "overview.json"
            raw = overview_path.read_bytes()
            overview = json.loads(raw)
            overview["payload"]["portfolio"]["approved_target_gross"] = 0.9
            overview_path.write_text(
                json.dumps(overview, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="ascii",
            )
            with self.assertRaisesRegex(DashboardReadModelError, "mismatch"):
                read_dashboard_v1(root)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            publication = publish_dashboard_v1(root, _models())
            release = root / "releases" / publication.publication_id
            (release / "extra.json").write_text("{}\n", encoding="ascii")
            with self.assertRaisesRegex(DashboardReadModelError, "files_mismatch"):
                read_dashboard_v1(root)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            publish_dashboard_v1(root, _models())
            (root / "v1").unlink()
            os.symlink("../escape", root / "v1")
            with self.assertRaisesRegex(DashboardReadModelError, "target_invalid"):
                read_dashboard_v1(root)

    def test_static_schemas_are_strict_v1_contracts(self) -> None:
        schema_root = Path(__file__).resolve().parents[1] / "web" / "schemas"
        names = (
            "dashboard-v1-envelope.schema.json",
            "dashboard-v1-overview.schema.json",
            "dashboard-v1-positions.schema.json",
            "dashboard-v1-orders.schema.json",
            "dashboard-v1-strategies.schema.json",
            "dashboard-v1-decisions.schema.json",
            "dashboard-v1-risk.schema.json",
            "dashboard-v1-readiness.schema.json",
            "dashboard-v1-system.schema.json",
            "dashboard-v1-alerts.schema.json",
            "daily-brief-v1.schema.json",
            "dashboard-v1-reports.schema.json",
            "daily-intelligence-v1.schema.json",
            "daily-intelligence-v2.schema.json",
            "dashboard-v1-intelligence.schema.json",
            "dashboard-v1-publication.schema.json",
        )
        for name in names:
            with self.subTest(name=name):
                schema = json.loads((schema_root / name).read_text(encoding="ascii"))
                self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
                self.assertIn("$id", schema)
                self.assertTrue(
                    schema.get("additionalProperties") is False
                    or schema.get("unevaluatedProperties") is False
                )
        envelope = json.loads(
            (schema_root / "dashboard-v1-envelope.schema.json").read_text(
                encoding="ascii"
            )
        )
        source_variants = envelope["$defs"]["source_hashes"]["oneOf"]
        self.assertEqual(
            envelope["properties"]["read_model_type"]["enum"],
            [
                "overview",
                "positions",
                "orders",
                "strategies",
                "decisions",
                "risk",
                "readiness",
                "system",
                "alerts",
                "reports",
                "intelligence",
            ],
        )
        self.assertEqual(len(source_variants), 9)
        self.assertIn("runtime_ledger", source_variants[1]["required"])
        self.assertIn("blocked_runtime_observation", source_variants[2]["required"])
        self.assertEqual(source_variants[3]["required"], ["notification_store"])
        self.assertEqual(source_variants[4]["required"], ["daily_brief"])
        self.assertEqual(source_variants[5]["required"], ["daily_intelligence"])
        self.assertIn("system_health", source_variants[6]["required"])
        self.assertIn("runtime_ledger", source_variants[7]["required"])
        self.assertIn("blocked_runtime_observation", source_variants[8]["required"])
        self.assertEqual(
            set(
                envelope["$defs"]["authority"]["properties"][
                    "account_and_pnl"
                ]["enum"]
            ),
            {"unavailable_until_phase_b_ledger", "runtime_ledger", "private_account_preflight"},
        )
        overview = json.loads(
            (schema_root / "dashboard-v1-overview.schema.json").read_text(
                encoding="ascii"
            )
        )["allOf"][1]["properties"]["payload"]["properties"]
        self.assertEqual(len(overview["portfolio"]["properties"]["actual_positions"]["oneOf"]), 3)
        self.assertEqual(len(overview["pnl"]["oneOf"]), 2)
        self.assertEqual(len(overview["account"]["oneOf"]), 3)
        strategies = json.loads(
            (schema_root / "dashboard-v1-strategies.schema.json").read_text(
                encoding="ascii"
            )
        )
        nav_schema = strategies["allOf"][1]["properties"]["payload"]["properties"][
            "strategies"
        ]["items"]["properties"]["nav"]
        self.assertEqual(len(nav_schema["oneOf"]), 2)
        strategy_properties = strategies["allOf"][1]["properties"]["payload"][
            "properties"
        ]["strategies"]["items"]["properties"]
        self.assertIn("registry_status", strategy_properties)
        self.assertIn("execution_status", strategy_properties)
        self.assertIn("live_orders_allowed", strategy_properties)
        self.assertNotIn("promotion_status", strategy_properties)
        publication = json.loads(
            (schema_root / "dashboard-v1-publication.schema.json").read_text(
                encoding="ascii"
            )
        )
        self.assertEqual(
            set(publication["properties"]["read_models"]["required"]),
            {
                "overview",
                "positions",
                "orders",
                "strategies",
                "decisions",
                "risk",
                "readiness",
                "system",
                "alerts",
                "reports",
                "intelligence",
            },
        )

    def test_jsonschema_validates_all_models_publication_and_intelligence(self) -> None:
        schema_root = Path(__file__).resolve().parents[1] / "web" / "schemas"
        schemas = {
            path.name: json.loads(path.read_text(encoding="ascii"))
            for path in schema_root.glob("*.schema.json")
        }
        registry = Registry().with_resources(
            [
                (schema["$id"], Resource.from_contents(schema))
                for schema in schemas.values()
            ]
        )
        batch, strategy_registry = _sources()
        report = _daily_intelligence()
        models = build_dashboard_v1(
            batch,
            strategy_registry,
            generated_at=GENERATED_AT,
            evaluated_at=GENERATED_AT,
            daily_intelligence=report,
        )
        with tempfile.TemporaryDirectory() as temporary:
            publication = publish_dashboard_v1(Path(temporary), models)

        for model in models.models():
            schema = schemas[f"dashboard-v1-{model.read_model_type}.schema.json"]
            Draft202012Validator(
                schema,
                registry=registry,
                format_checker=FormatChecker(),
            ).validate(model.as_dict())
        Draft202012Validator(
            schemas["dashboard-v1-publication.schema.json"],
            registry=registry,
            format_checker=FormatChecker(),
        ).validate(publication.as_dict())
        Draft202012Validator(
            schemas["daily-intelligence-v2.schema.json"],
            registry=registry,
            format_checker=FormatChecker(),
        ).validate(report.as_dict())

    def test_browser_uses_only_v1_models_and_contains_no_authoritative_pnl_math(self) -> None:
        app = (
            Path(__file__).resolve().parents[1] / "web" / "site" / "app.js"
        ).read_text(encoding="utf-8")
        self.assertIn("data/v1/publication.json", app)
        self.assertIn("data/v1/overview.json", app)
        self.assertIn("data/v1/positions.json", app)
        self.assertIn("data/v1/orders.json", app)
        self.assertIn("data/v1/decisions.json", app)
        self.assertIn("data/v1/risk.json", app)
        self.assertIn("data/v1/system.json", app)
        self.assertIn("data/v1/alerts.json", app)
        self.assertIn("data/v1/reports.json", app)
        self.assertIn("data/v1/intelligence.json", app)
        self.assertNotIn("api.binance.com", app)
        self.assertNotIn("fapi.binance.com", app)
        self.assertNotIn("unrealized_pnl", app)
        self.assertNotIn("patchLive", app)
        self.assertIn("portfolio.actual_positions", app)
        self.assertIn("payload.pnl", app)
        self.assertIn("交易所只读仓位事实", app)
        self.assertNotIn("手工/外部仓位", app)
        self.assertIn("live_orders_allowed=", app)
        self.assertIn("row.registry_status", app)
        self.assertIn("row.execution_status", app)
        self.assertNotIn("row.promotion_status", app)
        self.assertIn("currentHistoryAuthoritative", app)
        self.assertIn("旧报告缺少当前权威边界", app)
        self.assertIn('history.replaceState(null, "", "#/live")', app)
        self.assertIn("Object.entries(model.source_hashes).filter", app)
        self.assertIn("Object.hasOwn(publication.source_hashes, name)", app)
        self.assertIn("sharedSources.length > 0", app)
        self.assertIn("publication.source_hashes[name] === hash", app)
        self.assertIn("async function sha256Hex", app)
        self.assertIn("reference.file_sha256 !== fileSha256", app)
        self.assertIn("data/releases/${publicationId}/", app)
        self.assertIn("releaseModelPath(path, publication.publication_id)", app)
        for legacy_source in (
            "x4_live.json",
            "x4_paper.json",
            "cxd_live.json",
            "cta.json",
        ):
            self.assertNotIn(legacy_source, app)

        repo_root = Path(__file__).resolve().parents[1]
        for relative_path in (
            "scripts/desktop/cxd_live_cron.sh",
            "scripts/desktop/x4_live_cron.sh",
            "scripts/desktop/x4_paper_cron.sh",
        ):
            with self.subTest(legacy_writer=relative_path):
                self.assertNotIn(
                    "/var/www/qount",
                    (repo_root / relative_path).read_text(encoding="utf-8"),
                )
        production_cron = (repo_root / "deploy/cron/qount-production.crontab").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("cxd_publish_cron.sh", production_cron)


if __name__ == "__main__":
    unittest.main()
