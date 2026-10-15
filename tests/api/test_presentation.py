"""Read-only presentation boundaries: provenance, clocks, and ledger date filters."""

import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from qount.api.main import app
from qount.api.routes.assistant import get_assistant_daily
from qount.api.routes.account import load_live_account_snapshot
from qount.api.db import get_paper_trades, save_paper_line
from qount.api.schemas import LineSource, PaperLine


class TestPresentation(unittest.TestCase):
    def daily_package(self, root, as_of=None):
        as_of = as_of or datetime.now(timezone.utc).date().isoformat()
        boundary = {"research_only": True, "orders_authorized": False}
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "input_status": {
                "as_of_date": as_of or datetime.now(timezone.utc).date().isoformat(),
                "expected_as_of_date": as_of
                or datetime.now(timezone.utc).date().isoformat(),
                "source_data_hash": "a" * 64,
                "freshness_status": "FRESH",
                "assets_qualification": {
                    "ETF#0": {
                        "symbol": "ETF",
                        "as_of_date": as_of,
                        "is_actionable": True,
                    }
                },
            },
            "rule_status": {
                "assets": {
                    "ETF#0": {
                        "symbol": "ETF",
                        "as_of_date": as_of,
                        "is_actionable": True,
                    }
                }
            },
            "risk_and_evidence": {"safety_boundary": boundary},
            "tool_status": {
                "report_generation_status": "SUCCESS",
                "evidence_qualification_status": "QUALIFIED",
            },
        }
        content = json.dumps(report).encode()
        (root / "daily-report.json").write_bytes(content)
        manifest = {
            "boundary": boundary,
            "input_files": {"data_sha256": "a" * 64},
            "output_artifacts": {
                "daily_report_json": {
                    "file": "daily-report.json",
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            },
        }
        (root / "manifest.json").write_text(json.dumps(manifest))
        (root / "_COMPLETE").write_text("complete")
        return report

    def reseal_report(self, root, report):
        content = json.dumps(report).encode()
        (root / "daily-report.json").write_bytes(content)
        manifest = json.loads((root / "manifest.json").read_text())
        manifest["output_artifacts"]["daily_report_json"]["sha256"] = hashlib.sha256(
            content
        ).hexdigest()
        (root / "manifest.json").write_text(json.dumps(manifest))

    def test_report_flags_do_not_override_missing_or_disqualified_asset_evidence(self):
        for case, expected in [
            ("no_expected_date", "DISQUALIFIED"),
            ("not_actionable", "DISQUALIFIED"),
            ("wrong_symbol", "ERROR"),
            ("wrong_input_hash", "ERROR"),
        ]:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                report = self.daily_package(root)
                if case == "no_expected_date":
                    report["input_status"]["expected_as_of_date"] = None
                elif case == "not_actionable":
                    report["input_status"]["assets_qualification"]["ETF#0"][
                        "is_actionable"
                    ] = False
                elif case == "wrong_symbol":
                    report["rule_status"]["assets"]["ETF#0"]["symbol"] = "OTHER"
                else:
                    report["input_status"]["source_data_hash"] = "b" * 64
                self.reseal_report(root, report)
                with patch.dict(os.environ, {"QOUNT_ASSISTANT_DAILY_RUN": folder}):
                    self.assertEqual(get_assistant_daily()["status"], expected)

    def test_daily_unconfigured_never_discovers_replay_samples(self):
        with patch.dict(os.environ, {}, clear=True):
            result = get_assistant_daily()
        self.assertEqual(result["status"], "MISSING")
        self.assertIsNone(result["report"])

    def test_daily_hash_and_completion_are_required(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.daily_package(root)
            with patch.dict(os.environ, {"QOUNT_ASSISTANT_DAILY_RUN": folder}):
                self.assertEqual(get_assistant_daily()["status"], "QUALIFIED")
                (root / "_COMPLETE").unlink()
                self.assertEqual(get_assistant_daily()["status"], "ERROR")
                (root / "_COMPLETE").write_text("complete")
                with (root / "daily-report.json").open("ab") as stream:
                    stream.write(b" ")
                self.assertEqual(get_assistant_daily()["status"], "ERROR")

    def test_old_qualified_daily_remains_explicitly_historical(self):
        with tempfile.TemporaryDirectory() as folder:
            self.daily_package(Path(folder), "2020-01-01")
            with patch.dict(os.environ, {"QOUNT_ASSISTANT_DAILY_RUN": folder}):
                self.assertEqual(get_assistant_daily()["status"], "HISTORICAL")

    def test_daily_refuses_unqualified_boundaries(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.daily_package(root)
            manifest = json.loads((root / "manifest.json").read_text())
            manifest["boundary"]["orders_authorized"] = True
            (root / "manifest.json").write_text(json.dumps(manifest))
            with patch.dict(os.environ, {"QOUNT_ASSISTANT_DAILY_RUN": folder}):
                self.assertEqual(get_assistant_daily()["status"], "ERROR")

    def test_observation_without_a_clock_never_gets_request_time(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "observation.json"
            path.write_text(
                json.dumps(
                    {
                        "account_observation": {
                            "wallet_balance": 100,
                            "available_balance": 100,
                        }
                    }
                )
            )
            with patch.dict(os.environ, {"QOUNT_ACCOUNT_OBSERVATION_PATH": str(path)}):
                snapshot = load_live_account_snapshot()
            self.assertIn("OBSERVATION_INCOMPLETE", snapshot.error)
            self.assertEqual(snapshot.nav, 0)

    def test_trade_date_filter_includes_intraday_records_on_end_date(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "test.db")
            line = PaperLine(
                line_id="test",
                name="Test",
                as_of="2026-10-12",
                source=LineSource(path="test"),
                position_status="KNOWN",
            )
            events = [
                {
                    "date": day,
                    "symbol": "ETF",
                    "side": "BUY",
                    "quantity": 1,
                    "price": 10,
                }
                for day in [
                    "2026-10-09T23:59:00Z",
                    "2026-10-10T12:00:00Z",
                    "2026-10-12T00:00:00Z",
                ]
            ]
            save_paper_line(line, db_path=path, trade_events=events)
            rows = get_paper_trades(
                "test", db_path=path, start="2026-10-09", end="2026-10-09"
            )
            self.assertEqual(len(rows), 1)
            with patch.dict(os.environ, {"QOUNT_DB_PATH": path}):
                response = TestClient(app).get(
                    "/paper/trades?line_id=test&start=2026-10-09&end=2026-10-09"
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.json()), 1)

    def test_source_rule_reason_and_explicit_zero_cost_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "test.db")
            line = PaperLine(
                line_id="test",
                name="Test",
                as_of="2026-10-12",
                source=LineSource(path="test"),
                position_status="KNOWN",
            )
            save_paper_line(
                line,
                db_path=path,
                trade_events=[
                    {
                        "date": "2026-10-09",
                        "symbol": "ETF",
                        "side": "BUY",
                        "quantity": 1,
                        "price": 10,
                        "cost": 0,
                        "note": "MA120 confirmed crossover",
                    }
                ],
            )
            row = get_paper_trades("test", db_path=path)[0]
            self.assertEqual(row.cost, 0)
            self.assertEqual(row.note, "MA120 confirmed crossover")

    def test_deployed_retention_keeps_provenance_and_invalidates_current_positions(self):
        from qount.api.db import get_paper_line, get_current_paper_position_snapshot
        from qount.api.schemas import NavPoint, LineMetrics, PositionItem
        with tempfile.TemporaryDirectory() as folder:
            db=str(Path(folder)/'retention.db')
            original=PaperLine(line_id='retained',name='Retained',as_of='2026-10-09',source=LineSource(path='original',sha256='a'*64),position_status='KNOWN',positions=[PositionItem(symbol='ETF',quantity=10)],nav_series=[NavPoint(date='2026-10-09',nav=1.2)],metrics=LineMetrics(cagr_pct=5))
            save_paper_line(original,db_path=db)
            missing=original.model_copy(update={'as_of':'unknown','source':LineSource(path='missing'),'data_status':'MISSING','error':'source_missing','position_status':'UNKNOWN','nav_series':[],'metrics':None})
            save_paper_line(missing,db_path=db)
            retained=get_paper_line('retained',db_path=db)
            self.assertEqual(retained.as_of,'2026-10-09')
            self.assertEqual(retained.source.path,'original')
            self.assertEqual(retained.metrics.cagr_pct,5)
            self.assertEqual(retained.nav_series[0].nav,1.2)
            snapshot=get_current_paper_position_snapshot('retained',db_path=db)
            self.assertEqual(snapshot['status'],'UNKNOWN')
            self.assertIsNone(snapshot['as_of'])

    def test_deployed_unknown_quantities_cannot_create_a_trade(self):
        from qount.api.schemas import PositionItem
        with tempfile.TemporaryDirectory() as folder:
            db=str(Path(folder)/'unknown.db')
            line=PaperLine(line_id='unknown',name='Unknown quantity',as_of='2026-10-09',source=LineSource(path='test'),position_status='KNOWN',positions=[PositionItem(symbol='ETF',quantity=None,weight=.5)])
            save_paper_line(line,db_path=db)
            save_paper_line(line.model_copy(update={'as_of':'2026-10-12','positions':[PositionItem(symbol='ETF',quantity=10,weight=.5)]}),db_path=db)
            self.assertEqual(get_paper_trades('unknown',db_path=db),[])

    def test_deployed_split_parser_reconciles_shares_and_rejects_oversells(self):
        from qount.api.ledger import parse_personal_assistant_position_ledger
        events=[{'date':'20260101','action':'BUY','shares':10},{'date':'20260102','action':'CORPORATE_ACTION_SPLIT','shares_before':10,'shares_after':50,'split_ratio':5}]
        self.assertEqual(parse_personal_assistant_position_ledger(events,as_of='2026-10-12'),(50,'2026-01-01'))
        with self.assertRaises(ValueError):
            parse_personal_assistant_position_ledger(events+[{'date':'20260103','action':'SELL','shares':51}],as_of='2026-10-12')
