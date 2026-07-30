#!/usr/bin/env python3
"""Research-only multi-agent plan runner.

This writes an alpha-agent task/report artifact. It does not fetch private
exchange data, write paper/live state, change VPS config, or place orders.
LLM calls are opt-in via --with-llm plus QOUNT_ALPHA_AGENT_API_KEY.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.alpha_agents.llm import AlphaLLMConfig  # noqa: E402
from qount.alpha_agents.orchestrator import AlphaAgentOrchestrator  # noqa: E402
from qount.alpha_agents.orchestrator import write_alpha_agent_plan_artifact  # noqa: E402
from qount.alpha_agents.roles import load_registry  # noqa: E402
from qount.alpha_agents.tasks import load_research_tasks  # noqa: E402
from qount.settings import Settings  # noqa: E402


DEFAULT_OBJECTIVE = (
    "Design research evidence for a 1000 USDT crypto portfolio while preserving "
    "standalone attribution, small-account execution, and beta controls."
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--objective", default=DEFAULT_OBJECTIVE)
    parser.add_argument("--task-id", default=None, help="Optional seed task id to run.")
    parser.add_argument("--output-path", default=None, help="Optional artifact JSON path.")
    parser.add_argument("--roles-path", default=None, help="Optional JSON role registry.")
    parser.add_argument("--tasks-path", default=None, help="Optional JSON task list.")
    parser.add_argument(
        "--with-llm",
        action="store_true",
        help="Opt in to the configured research LLM client.",
    )
    parser.add_argument("--print-json", action="store_true", help="Print the final artifact payload.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    settings = Settings.from_env()
    llm_config = AlphaLLMConfig.from_env(enabled_override=args.with_llm)
    registry = load_registry(args.roles_path) if args.roles_path else None
    tasks = load_research_tasks(args.tasks_path) if args.tasks_path else None
    orchestrator = AlphaAgentOrchestrator(registry=registry, llm_config=llm_config)
    payload = orchestrator.run_seed_plan(objective=args.objective, task_id=args.task_id, tasks=tasks)
    artifact = write_alpha_agent_plan_artifact(settings, payload, explicit_path=args.output_path)
    if args.print_json:
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
    else:
        print(f"artifact={artifact['artifact_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
