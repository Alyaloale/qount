from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from qount.alpha_agents.llm import AlphaLLMConfig
from qount.alpha_agents.models import AgentReport
from qount.alpha_agents.official_sources import build_official_source_document
from qount.intelligence import IntelligenceContractError
from qount.intelligence import StaticSearchProvider
from qount.intelligence import alert_from_daily_intelligence
from qount.intelligence import build_market_pulse
from qount.intelligence import fetch_binance_market_pulse
from qount.intelligence import read_latest_daily_intelligence
from qount.intelligence import run_daily_intelligence
from qount.intelligence import summarize_trading_history
from qount.ledger import build_runtime_ledger_snapshot
from scripts.operations.run_daily_intelligence import (
    DAILY_INTELLIGENCE_DEFAULT_LLM_MODEL,
)
from scripts.operations.run_daily_intelligence import _parser as daily_intelligence_parser
from tests.test_ledger_dashboard_bridge import CAPTURED_AT
from tests.test_ledger_dashboard_bridge import _ledger_with_accounting


CREATED_AT = "2026-07-21T10:00:00+00:00"
SOURCE_URL = "https://www.binance.com/en/support/announcement/example"


def _market():
    symbols = ("BTCUSDT", "ETHUSDT", "BNBUSDT")
    ticker = [
            {
                "symbol": symbol,
                "lastPrice": "100.5",
                "priceChangePercent": "1.25",
                "quoteVolume": "1000000",
            }
            for symbol in symbols
        ]
    premium = [
            {
                "symbol": symbol,
                "lastFundingRate": "0.0001",
                "nextFundingTime": "1784649600000",
            }
            for symbol in symbols
        ]
    raw_bodies = {
        "ticker_24h": json.dumps(ticker, separators=(",", ":")).encode("utf-8"),
        "premium_index": json.dumps(premium, separators=(",", ":")).encode("utf-8"),
    }
    pulse = build_market_pulse(
        ticker_payload=ticker,
        premium_payload=premium,
        observed_at=CREATED_AT,
        source_hashes={
            name: hashlib.sha256(raw).hexdigest()
            for name, raw in raw_bodies.items()
        },
    )
    return pulse, raw_bodies


def _config():
    return AlphaLLMConfig(
        enabled=False,
        base_url="https://llm.alyaloale.com/v1",
        api_key="",
        model="gpt-5.6-terra",
    )


class DailyIntelligenceTest(unittest.TestCase):
    def test_daily_cli_defaults_to_sol_without_changing_research_default(self) -> None:
        args = daily_intelligence_parser().parse_args(
            [
                "--authority-root",
                "/authority",
                "--archive-root",
                "/archive",
                "--notification-store",
                "/notifications.sqlite3",
                "--search-provider",
                "official-feeds",
            ]
        )

        self.assertEqual(DAILY_INTELLIGENCE_DEFAULT_LLM_MODEL, "gpt-5.6-sol")
        self.assertEqual(args.llm_model, "gpt-5.6-sol")

    def test_offline_multi_agent_report_archives_source_bytes_and_is_read_only(self) -> None:
        body = b"<html><body>Binance official market notice.</body></html>"

        def fetcher(url, *, observed_at):
            self.assertEqual(url, SOURCE_URL)
            return build_official_source_document(
                source_url=url,
                final_url=url,
                body=body,
                content_type_header="text/html; charset=utf-8",
                observed_at=observed_at,
            )

        with tempfile.TemporaryDirectory() as temporary:
            pulse, market_bodies = _market()
            run = run_daily_intelligence(
                created_at=CREATED_AT,
                market_pulse=pulse,
                market_bodies=market_bodies,
                runtime_ledger_snapshot=None,
                search_provider=StaticSearchProvider(
                    {"fixture search": (("Binance notice", SOURCE_URL),)}
                ),
                archive_root=temporary,
                llm_config=_config(),
                search_queries=("fixture search",),
                source_fetcher=fetcher,
            )
            loaded = read_latest_daily_intelligence(temporary)
            report_dir = Path(run.archive.report_path).parent

            self.assertEqual(loaded, run.report)
            self.assertEqual(run.report.status, "incomplete")
            self.assertFalse(run.report.orders_allowed)
            self.assertFalse(run.report.live_changes_allowed)
            self.assertIn("任务骨架", run.report.executive_summary)
            self.assertIn("每日情报复盘", alert_from_daily_intelligence(run.report).title)
            self.assertEqual(
                tuple(row["role_id"] for row in run.report.agent_reports),
                (
                    "market_analyst",
                    "event_analyst",
                    "execution_reviewer",
                    "strategy_reviewer",
                    "red_team",
                    "editor",
                ),
            )
            source_path = report_dir / "sources" / f"{hashlib.sha256(body).hexdigest()}.bin"
            self.assertEqual(source_path.read_bytes(), body)
            self.assertEqual(oct(os.stat(source_path).st_mode & 0o777), "0o600")
            for name, raw in market_bodies.items():
                market_path = report_dir / "market" / f"{hashlib.sha256(raw).hexdigest()}.json"
                self.assertEqual(market_path.read_bytes(), raw, name)
            search_path = next(report_dir.glob("searches/*.json"))
            self.assertEqual(
                hashlib.sha256(search_path.read_bytes()).hexdigest(),
                run.report.searches[0]["response_hash"],
            )
            alert = alert_from_daily_intelligence(run.report)
            self.assertEqual(alert.source_type, "intelligence")
            self.assertEqual(alert.source_hash, run.report.report_hash)
            self.assertIn("已验证来源", alert.summary)

    def test_report_and_archived_source_tamper_fail_closed(self) -> None:
        body = b"<html><body>Official notice.</body></html>"

        def fetcher(url, *, observed_at):
            return build_official_source_document(
                source_url=url,
                final_url=url,
                body=body,
                content_type_header="text/html",
                observed_at=observed_at,
            )

        with tempfile.TemporaryDirectory() as temporary:
            pulse, market_bodies = _market()
            run = run_daily_intelligence(
                created_at=CREATED_AT,
                market_pulse=pulse,
                market_bodies=market_bodies,
                runtime_ledger_snapshot=None,
                search_provider=StaticSearchProvider(
                    {"fixture": (("Notice", SOURCE_URL),)}
                ),
                archive_root=temporary,
                llm_config=_config(),
                search_queries=("fixture",),
                source_fetcher=fetcher,
            )
            with self.assertRaisesRegex(
                IntelligenceContractError, "report_hash_invalid"
            ):
                replace(run.report, executive_summary="tampered").validate()

            source_path = next(Path(run.archive.report_path).parent.glob("sources/*.bin"))
            source_path.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "evidence_hash_mismatch"):
                read_latest_daily_intelligence(temporary)

    def test_llm_infrastructure_failure_opens_batch_circuit(self) -> None:
        body = b"<html><body>Official notice.</body></html>"

        def fetcher(url, *, observed_at):
            return build_official_source_document(
                source_url=url,
                final_url=url,
                body=body,
                content_type_header="text/html",
                observed_at=observed_at,
            )

        first_failure = AgentReport(
            role_id="market_analyst",
            task_id="daily_intelligence_market_analyst_v1",
            status="blocked",
            summary="LLM 请求失败，已阻断本批后续网络调用。",
            risks=("llm_request_error:InternalServerError:http_502:attempts_2",),
        )
        with tempfile.TemporaryDirectory() as temporary, patch(
            "qount.intelligence.daily.request_agent_report",
            return_value=first_failure,
        ) as requester:
            pulse, market_bodies = _market()
            run = run_daily_intelligence(
                created_at=CREATED_AT,
                market_pulse=pulse,
                market_bodies=market_bodies,
                runtime_ledger_snapshot=None,
                search_provider=StaticSearchProvider(
                    {"fixture": (("Notice", SOURCE_URL),)}
                ),
                archive_root=temporary,
                llm_config=AlphaLLMConfig(
                    enabled=True,
                    base_url="https://llm.alyaloale.com/v1",
                    api_key="fixture-secret",
                    model="gpt-5.6-terra",
                ),
                search_queries=("fixture",),
                source_fetcher=fetcher,
            )

        self.assertEqual(requester.call_count, 1)
        self.assertEqual(run.report.agent_reports[0]["role_id"], "market_analyst")
        self.assertEqual(
            run.report.agent_reports[0]["risks"],
            ["llm_request_error:InternalServerError:http_502:attempts_2"],
        )
        self.assertTrue(
            all(
                report["risks"] == ["llm_batch_circuit_open"]
                for report in run.report.agent_reports[1:]
            )
        )

    def test_real_source_context_is_bounded_per_role(self) -> None:
        body = b"<html><title>Official notice</title><body>" + (b"source " * 4_000) + b"</body></html>"
        urls = tuple(
            f"https://www.binance.com/en/support/announcement/{index}"
            for index in range(8)
        )

        def fetcher(url, *, observed_at):
            return build_official_source_document(
                source_url=url,
                final_url=url,
                body=body,
                content_type_header="text/html",
                observed_at=observed_at,
            )

        calls: list[dict] = []

        def request(**kwargs):
            calls.append(kwargs)
            return AgentReport(
                role_id=kwargs["role"].role_id,
                task_id=kwargs["task"].task_id,
                status="ok",
                summary="本角色已完成有界复核。",
                findings=("来源和账本均按给定上下文复核。",),
                proposals=("保持研究模式并运行基线否决测试。",),
                risks=("仍需独立样本验证。",),
                sources=kwargs["sources"],
            )

        with tempfile.TemporaryDirectory() as temporary, patch(
            "qount.intelligence.daily.request_agent_report", side_effect=request
        ):
            pulse, market_bodies = _market()
            run = run_daily_intelligence(
                created_at=CREATED_AT,
                market_pulse=pulse,
                market_bodies=market_bodies,
                runtime_ledger_snapshot=None,
                search_provider=StaticSearchProvider(
                    {"fixture": tuple((f"Notice {i}", url) for i, url in enumerate(urls))}
                ),
                archive_root=temporary,
                llm_config=AlphaLLMConfig(
                    enabled=True,
                    base_url="https://llm.alyaloale.com/v1",
                    api_key="fixture-secret",
                    model="gpt-5.6-sol",
                ),
                search_queries=("fixture",),
                source_fetcher=fetcher,
            )

        self.assertEqual(run.report.status, "incomplete")
        self.assertEqual(len(calls), 6)
        payload_sizes = [len(json.dumps(call["context"], ensure_ascii=False)) for call in calls]
        self.assertLess(max(payload_sizes), 35_000)
        self.assertIn("prior_agent_reports", calls[-1]["context"])
        self.assertNotIn("raw_response", calls[-1]["context"]["prior_agent_reports"][0])
        self.assertEqual(run.report.executive_summary, "本角色已完成有界复核。")
        self.assertTrue(
            all(report["status"] == "ok" for report in run.report.agent_reports)
        )

    def test_public_market_fetch_hashes_exact_http_bytes(self) -> None:
        pulse, raw_bodies = _market()

        class Response:
            status = 200

            def __init__(self, url, raw):
                self.url = url
                self.raw = raw

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return None

            def geturl(self):
                return self.url

            def read(self, limit):
                return self.raw[:limit]

        class Opener:
            def open(self, request, timeout):
                name = "ticker_24h" if "ticker/24hr" in request.full_url else "premium_index"
                return Response(request.full_url, raw_bodies[name])

        fetched = fetch_binance_market_pulse(
            observed_at=CREATED_AT,
            opener=Opener(),
        )
        self.assertEqual(fetched.pulse, pulse)
        self.assertEqual(fetched.raw_bodies, raw_bodies)

    def test_runtime_ledger_v3_history_uses_real_order_fill_and_nav_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger, batch, _ = _ledger_with_accounting(Path(temporary))
            snapshot = build_runtime_ledger_snapshot(
                ledger,
                batch,
                captured_at=CAPTURED_AT,
            )
            summary = summarize_trading_history(snapshot)

        self.assertEqual(summary["status"], "available")
        self.assertEqual(summary["current_equity"], snapshot.nav["equity"])
        self.assertEqual(summary["funding"], snapshot.nav["funding"])
        self.assertEqual(summary["fees"], snapshot.nav["fees"])
        filled = next(
            row for row in summary["recent_orders"] if row["status"] == "FILLED"
        )
        self.assertEqual(filled["executed_quantity"], 0.001)
        self.assertEqual(summary["recent_fills"][0]["fee"], 0.1)
        self.assertNotIn("fee_amount", summary["recent_fills"][0])
        self.assertEqual(summary["execution_evidence_status"], "fills_verified")
        self.assertTrue(summary["execution_evidence_sufficient"])

    def test_flat_zero_order_cycle_is_no_order_expected_evidence(self) -> None:
        snapshot = SimpleNamespace(
            validate=lambda: None,
            batch_id="a" * 64,
            source_updated_at="2026-07-21T10:00:00+00:00",
            position_details=(),
            orders=(),
            fills=(),
            cash_events=(),
            recoveries=(),
            unresolved_order_ids=(),
            nav={
                "equity": 100.0,
                "trading_pnl": 0.0,
                "trading_pnl_cumulative": 0.0,
                "funding": 0.0,
                "funding_cumulative": 0.0,
                "fees": 0.0,
                "fees_cumulative": 0.0,
                "transfers": 0.0,
                "transfers_cumulative": 0.0,
                "residual": 0.0,
            },
            account={
                "wallet_balance": 100.0,
                "available_balance": 100.0,
                "current_drawdown_fraction": 0.0,
                "peak_drawdown_fraction": 0.0,
            },
            reconciliation={"passed": True, "halt_required": False},
        )

        summary = summarize_trading_history(snapshot)

        self.assertEqual(summary["execution_evidence_status"], "no_order_expected")
        self.assertTrue(summary["execution_evidence_sufficient"])

    def test_history_position_count_excludes_zero_quantity_symbol_rows(self) -> None:
        snapshot = SimpleNamespace(
            validate=lambda: None,
            batch_id="b" * 64,
            source_updated_at="2026-07-21T10:00:00+00:00",
            position_details=(
                {"quantity": 0.0},
                {"quantity": 0.25},
                {"quantity": -0.5},
                {"quantity": 0.0},
            ),
            orders=(),
            fills=(),
            cash_events=(),
            recoveries=(),
            unresolved_order_ids=(),
            nav={
                "equity": 100.0,
                "trading_pnl": 0.0,
                "trading_pnl_cumulative": 0.0,
                "funding": 0.0,
                "funding_cumulative": 0.0,
                "fees": 0.0,
                "fees_cumulative": 0.0,
                "transfers": 0.0,
                "transfers_cumulative": 0.0,
                "residual": 0.0,
            },
            account={
                "wallet_balance": 100.0,
                "available_balance": 100.0,
                "current_drawdown_fraction": 0.0,
                "peak_drawdown_fraction": 0.0,
            },
            reconciliation={"passed": True, "halt_required": False},
        )

        summary = summarize_trading_history(snapshot)

        self.assertEqual(summary["position_count"], 2)

    def test_daily_systemd_template_has_network_but_no_exchange_credentials(self) -> None:
        root = Path(__file__).resolve().parents[1]
        service = (root / "deploy/systemd/qount-daily-intelligence.service").read_text()
        timer = (root / "deploy/systemd/qount-daily-intelligence.timer").read_text()

        self.assertIn("Type=oneshot", service)
        self.assertIn("PrivateNetwork=false", service)
        self.assertIn("RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6", service)
        self.assertIn("ProtectSystem=strict", service)
        self.assertIn("ProtectHome=read-only", service)
        self.assertIn("UMask=0077", service)
        self.assertNotIn("EnvironmentFile=", service)
        self.assertIn("QOUNT_ALPHA_AGENT_MODEL", service)
        self.assertIn("QOUNT_ALPHA_AGENT_API_KEY", service)
        self.assertIn("QOUNT_BINANCE_API_KEY", service)
        self.assertIn("--search-provider official-feeds", service)
        self.assertNotIn("brave-search.key", service)
        self.assertNotIn("--search-credential-path", service)
        self.assertIn("--llm-credential-path /etc/qount/intelligence/relay-station.key", service)
        self.assertIn("--llm-model gpt-5.6-sol", service)
        self.assertNotIn("--send-wecom", service)
        self.assertIn("--enqueue-personal-weixin", service)
        self.assertIn("--send-personal-weixin", service)
        self.assertIn(
            "--personal-weixin-credential-path /etc/qount/intelligence/openclaw-weixin.json",
            service,
        )
        self.assertIn(
            "--personal-weixin-context-token-directory /root/.openclaw/openclaw-weixin/accounts",
            service,
        )
        self.assertIn("After=network-online.target openclaw-gateway.service", service)
        self.assertIn("Wants=network-online.target openclaw-gateway.service", service)
        self.assertIn(
            "ConditionPathIsDirectory=/root/.openclaw/openclaw-weixin/accounts",
            service,
        )
        self.assertIn(
            "ReadOnlyPaths=/root/.openclaw/openclaw-weixin/accounts",
            service,
        )
        self.assertIn(
            "ConditionPathExists=/etc/qount/intelligence/openclaw-weixin.json",
            service,
        )
        self.assertIn("Unit=qount-daily-intelligence.service", timer)
        self.assertIn("OnCalendar=*-*-* 04:30:00 UTC", timer)


if __name__ == "__main__":
    unittest.main()
