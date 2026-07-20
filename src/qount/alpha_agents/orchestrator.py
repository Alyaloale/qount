from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
from typing import Any

from qount.artifacts import write_research_json_artifact
from qount.models import utc_now
from qount.settings import Settings

from .llm import AlphaLLMConfig
from .llm import request_agent_report
from .models import ALPHA_AGENT_VERSION
from .models import AgentReport
from .models import ResearchTask
from .roles import AgentRegistry
from .roles import default_registry
from .sources import sources_for_tags
from .tasks import seed_research_tasks


class AlphaAgentOrchestrator:
    def __init__(
        self,
        *,
        registry: AgentRegistry | None = None,
        llm_config: AlphaLLMConfig | None = None,
    ) -> None:
        self.registry = registry or default_registry()
        self.llm_config = llm_config or AlphaLLMConfig.from_env()

    def run_task(self, task: ResearchTask, *, objective: str) -> list[AgentReport]:
        context: dict[str, Any] = {
            "objective": objective,
            "guardrails": (
                "research_only",
                "no_live_orders",
                "no_risk_override",
                "beta_attribution_required",
                "costs_and_min_notional_required",
            ),
        }
        sources = sources_for_tags(task.source_tags)
        reports: list[AgentReport] = []
        for role_id in task.role_ids:
            role = self.registry.get(role_id)
            reports.append(
                request_agent_report(
                    config=self.llm_config,
                    role=role,
                    task=task,
                    sources=sources,
                    context=context,
                )
            )
        return reports

    def run_seed_plan(
        self,
        *,
        objective: str,
        task_id: str | None = None,
        tasks: tuple[ResearchTask, ...] | None = None,
    ) -> dict[str, Any]:
        tasks = tuple(sorted(tasks or seed_research_tasks(), key=lambda task: task.priority))
        if task_id is not None:
            tasks = tuple(task for task in tasks if task.task_id == task_id)
            if not tasks:
                raise ValueError(f"unknown seed task: {task_id}")
        jobs: list[tuple[int, ResearchTask, str]] = []
        order = 0
        for task in tasks:
            for role_id in task.role_ids:
                jobs.append((order, task, role_id))
                order += 1
        report_by_order: dict[int, AgentReport] = {}
        max_workers = max(1, min(self.llm_config.max_concurrency, len(jobs) or 1))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._run_role_task, task=task, role_id=role_id, objective=objective): order
                for order, task, role_id in jobs
            }
            for future in as_completed(futures):
                report_by_order[futures[future]] = future.result()
        reports = [report_by_order[index] for index in sorted(report_by_order)]
        return {
            "schema_version": ALPHA_AGENT_VERSION,
            "created_at": utc_now().isoformat(),
            "objective": objective,
            "mode": "research_only",
            "llm": {
                "enabled": self.llm_config.enabled,
                "base_url": self.llm_config.base_url,
                "model": self.llm_config.model,
                "api_key_present": bool(self.llm_config.api_key),
                "max_concurrency": self.llm_config.max_concurrency,
            },
            "agent_manifest": self.registry.manifest(),
            "tasks": [task.to_dict() for task in tasks],
            "reports": [report.to_dict() for report in reports],
            "hard_boundaries": [
                "Agents do not produce orders, target weights, live config changes, or risk overrides.",
                "Promotion requires deterministic quant artifacts, not LLM agreement.",
                "VPS production state is read-only unless owner explicitly authorizes deployment.",
            ],
        }

    def _run_role_task(self, *, task: ResearchTask, role_id: str, objective: str) -> AgentReport:
        context: dict[str, Any] = {
            "objective": objective,
            "guardrails": (
                "research_only",
                "no_live_orders",
                "no_risk_override",
                "beta_attribution_required",
                "costs_and_min_notional_required",
            ),
        }
        sources = sources_for_tags(task.source_tags)
        role = self.registry.get(role_id)
        return request_agent_report(
            config=self.llm_config,
            role=role,
            task=task,
            sources=sources,
            context=context,
        )


def write_alpha_agent_plan_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="alpha-agent-plan",
        path_key="artifact_path",
        default_filename="alpha_agent_plan.json",
        explicit_path=explicit_path,
    )
