from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qount.alpha_agents.llm import AlphaLLMConfig
from qount.alpha_agents.llm import find_forbidden_output
from qount.alpha_agents.models import AgentReport
from qount.alpha_agents.orchestrator import AlphaAgentOrchestrator
from qount.alpha_agents.orchestrator import write_alpha_agent_plan_artifact
from qount.alpha_agents.roles import default_registry
from qount.alpha_agents.roles import load_registry
from qount.alpha_agents.tasks import load_research_tasks
from qount.alpha_agents.validators import validate_agent_report
from qount.settings import Settings


class AlphaAgentsTest(unittest.TestCase):
    def test_registry_keeps_llm_out_of_deterministic_roles(self) -> None:
        registry = default_registry()
        self.assertFalse(registry.get("model_trainer").llm_allowed)
        self.assertFalse(registry.get("backtest_auditor").llm_allowed)
        self.assertIn("risk_override", registry.get("red_team").forbidden_outputs)

    def test_orchestrator_runs_without_llm_or_network(self) -> None:
        llm_config = AlphaLLMConfig(
            enabled=False,
            base_url="https://llm.alyaloale.com/v1",
            api_key="",
            model="glm-5.2",
        )
        payload = AlphaAgentOrchestrator(llm_config=llm_config).run_seed_plan(
            objective="test objective",
            task_id="beta_residual_target_v0",
        )
        self.assertEqual(payload["mode"], "research_only")
        self.assertEqual(len(payload["tasks"]), 1)
        self.assertEqual({report["status"] for report in payload["reports"]}, {"needs_research"})
        self.assertIn("research-only", " ".join(payload["reports"][0]["findings"]))

    def test_artifact_writer_uses_research_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"QOUNT_PROJECT_ROOT": tmp}, clear=False):
                settings = Settings.from_env()
                artifact = write_alpha_agent_plan_artifact(
                    settings,
                    {"schema_version": "test", "reports": []},
                    explicit_path=None,
                )
            path = Path(artifact["artifact_path"])
            self.assertTrue(path.exists())
            path.relative_to(Path(tmp) / "state" / "research_runs")
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["persistent_artifact_path"], str(path))

    def test_custom_roles_and_tasks_are_loadable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            roles_path = root / "roles.json"
            tasks_path = root / "tasks.json"
            roles_path.write_text(
                json.dumps(
                    {
                        "roles": [
                            {
                                "role_id": "quant_researcher",
                                "name": "QuantResearcher",
                                "kind": "quant_worker",
                                "mission": "Run deterministic experiments.",
                                "allowed_outputs": ["scorecard"],
                                "forbidden_outputs": ["order"],
                                "llm_allowed": False,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            tasks_path.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "task_id": "quant_task",
                                "title": "Quant task",
                                "objective": "Run a deterministic test.",
                                "role_ids": ["quant_researcher"],
                                "required_outputs": ["scorecard"],
                                "priority": 1,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            registry = load_registry(roles_path)
            tasks = load_research_tasks(tasks_path)
            payload = AlphaAgentOrchestrator(
                registry=registry,
                llm_config=AlphaLLMConfig(enabled=True, base_url="x", api_key="secret", model="m"),
            ).run_seed_plan(objective="swap role test", tasks=tasks)
        self.assertEqual(payload["tasks"][0]["task_id"], "quant_task")
        self.assertEqual(payload["reports"][0]["status"], "needs_research")
        self.assertFalse(payload["agent_manifest"]["roles"][0]["llm_allowed"])

    def test_forbidden_output_scanner_blocks_trade_language(self) -> None:
        hits = find_forbidden_output("Set leverage to 5x and arm live after market buy.")
        self.assertIn("set leverage", hits)
        self.assertIn("arm live", hits)
        self.assertIn("market buy", hits)

    def test_report_validator_checks_status_and_boundaries(self) -> None:
        errors = validate_agent_report(
            AgentReport(
                role_id="red_team",
                task_id="task",
                status="approved",
                summary="Enable live and set leverage.",
            )
        )
        self.assertIn("invalid_status:approved", errors)
        self.assertIn("forbidden_output:enable live", errors)
        self.assertIn("forbidden_output:set leverage", errors)


if __name__ == "__main__":
    unittest.main()
