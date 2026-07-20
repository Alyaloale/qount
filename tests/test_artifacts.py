from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from qount.artifacts import write_research_json_artifact


class ResearchArtifactTest(unittest.TestCase):
    def test_same_second_writes_use_distinct_directories(self) -> None:
        fixed_now = dt.datetime(2026, 7, 10, 13, 10, 19, tzinfo=dt.UTC)
        with tempfile.TemporaryDirectory() as tmp, patch("qount.artifacts.utc_now", return_value=fixed_now):
            settings = SimpleNamespace(project_root=Path(tmp))
            first = write_research_json_artifact(
                settings,
                {"run": "first"},
                kind="alpha-agent-beta-metrics",
                path_key="artifact_path",
                default_filename="alpha_agent_beta_metrics.json",
                explicit_path=None,
            )
            second = write_research_json_artifact(
                settings,
                {"run": "second"},
                kind="alpha-agent-beta-metrics",
                path_key="artifact_path",
                default_filename="alpha_agent_beta_metrics.json",
                explicit_path=None,
            )

            first_path = Path(first["artifact_path"])
            second_path = Path(second["artifact_path"])
            self.assertNotEqual(first_path.parent, second_path.parent)
            self.assertTrue(second_path.parent.name.endswith("-01"))
            self.assertEqual(json.loads(first_path.read_text(encoding="utf-8"))["run"], "first")
            self.assertEqual(json.loads(second_path.read_text(encoding="utf-8"))["run"], "second")


if __name__ == "__main__":
    unittest.main()
