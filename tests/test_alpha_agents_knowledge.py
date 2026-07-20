from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qount.alpha_agents.knowledge import assess_source
from qount.alpha_agents.knowledge import build_knowledge_report
from qount.alpha_agents.knowledge import write_knowledge_report_artifact
from qount.alpha_agents.models import SourceRef
from qount.settings import Settings


class AlphaAgentsKnowledgeTest(unittest.TestCase):
    def test_assess_source_distinguishes_primary_and_tutorial(self) -> None:
        official = assess_source(
            SourceRef(
                title="Binance Futures ExchangeInfo",
                url="https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information",
                source_type="official_exchange_doc",
            )
        )
        tutorial = assess_source(
            SourceRef(
                title="Some quant tutorial",
                url="https://example.com/tutorial",
                source_type="tutorial",
            )
        )
        self.assertEqual(official.verdict, "accept")
        self.assertIn("exchange_rule", official.allowed_use)
        self.assertEqual(tutorial.verdict, "review")
        self.assertIn("secondary_source_needs_primary_confirmation", tutorial.reasons)

    def test_build_report_and_artifact(self) -> None:
        report = build_knowledge_report(("binance_market_data", "validation"))
        self.assertGreater(report["source_count"], 0)
        self.assertGreater(report["verdict_counts"]["accept"], 0)
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"QOUNT_PROJECT_ROOT": tmp}, clear=False):
                artifact = write_knowledge_report_artifact(Settings.from_env(), report)
            path = Path(artifact["artifact_path"])
            self.assertTrue(path.exists())
            path.relative_to(Path(tmp) / "state" / "research_runs")


if __name__ == "__main__":
    unittest.main()
