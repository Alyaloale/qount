#!/usr/bin/env python3
"""Request a bounded, research-only red-team review of Equity Mapping G0."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.alpha_agents.llm import AlphaLLMConfig  # noqa: E402
from qount.alpha_agents.llm import request_agent_report  # noqa: E402
from qount.alpha_agents.models import ResearchTask  # noqa: E402
from qount.alpha_agents.models import SourceRef  # noqa: E402
from qount.alpha_agents.roles import default_registry  # noqa: E402
from qount.artifacts import write_research_json_artifact  # noqa: E402
from qount.models import utc_now  # noqa: E402
from qount.settings import Settings  # noqa: E402


SOURCE_SPECS = (
    (Path("src/qount/mini_trend/equity_mapping.py"), None, None),
    (Path("src/qount/governance/event_capacity.py"), None, None),
    (
        Path("tests/test_mini_trend_equity_mapping.py"),
        "__TEST_METHOD_NAMES__",
        None,
    ),
)
MAX_SOURCE_CHARS = 42_000


def _canonical_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _load_sources() -> tuple[list[dict[str, str]], tuple[SourceRef, ...]]:
    context_rows: list[dict[str, str]] = []
    references: list[SourceRef] = []
    total_chars = 0
    for relative_path, start_marker, end_marker in SOURCE_SPECS:
        path = (REPO / relative_path).resolve()
        path.relative_to(REPO.resolve())
        full_text = path.read_text(encoding="utf-8")
        file_hash = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
        if start_marker is None:
            excerpt = full_text
        elif start_marker == "__TEST_METHOD_NAMES__":
            excerpt = "\n".join(
                line.strip()
                for line in full_text.splitlines()
                if line.lstrip().startswith("def test_")
            )
        else:
            start = full_text.find(start_marker)
            end = full_text.find(end_marker or "", start)
            if start < 0 or end < 0:
                raise ValueError("equity_mapping_red_team_source_marker_missing")
            excerpt = full_text[start:end]
        total_chars += len(excerpt)
        if total_chars > MAX_SOURCE_CHARS:
            raise ValueError("equity_mapping_red_team_source_limit_exceeded")
        excerpt_hash = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
        context_rows.append(
            {
                "path": relative_path.as_posix(),
                "file_sha256": file_hash,
                "excerpt_sha256": excerpt_hash,
                "text": excerpt,
            }
        )
        references.append(
            SourceRef(
                title=relative_path.as_posix(),
                url=f"repo://qount/{relative_path.as_posix()}",
                source_type="local_code_or_test",
                notes=f"file_sha256={file_hash}; excerpt_sha256={excerpt_hash}",
            )
        )
    return context_rows, tuple(references)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-llm", action="store_true")
    parser.add_argument("--output-path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    source_rows, references = _load_sources()
    task = ResearchTask(
        task_id="equity_mapping_g0_red_team_v0",
        title="Equity Mapping G0 point-in-time contract red team",
        objective=(
            "Find concrete data-contract or implementation failures in the supplied G0 code. "
            "Check USDT/USD conversion direction, multiplier and corporate-action semantics, "
            "New York DST and half-day handling, quote_at versus available_at, bid/ask "
            "executability, long-only enforcement, independent-date counting, duplicate events, "
            "and stress sizing versus minimum notional. Separate verified code findings from "
            "hypotheses. Do not propose trades, weights, live settings, or risk overrides."
        ),
        role_ids=("red_team",),
        required_outputs=("critique", "missing_test", "falsification_path"),
        source_tags=("local_code", "point_in_time_contract"),
        holdout_role="discovery",
        priority=5,
    )
    context = {
        "mode": "research_sandbox",
        "scope": "G0 data and capacity contract only; no PnL and no execution authorization",
        "frozen_owner_constraints": {
            "direction": "long/cash only",
            "carry": False,
            "short": False,
            "leverage_boost": False,
            "effective_gross_cap": 1.0,
            "event_account_stress_budget_fraction": 0.0025,
            "minimum_independent_cash_dates": 30,
        },
        "review_instruction": (
            "Cite the supplied path and exact field or function for every verified finding. "
            "Mark anything requiring venue documentation or real quote fixtures as a hypothesis."
        ),
        "sources": source_rows,
    }
    config = AlphaLLMConfig.from_env(enabled_override=args.with_llm)
    report = request_agent_report(
        config=config,
        role=default_registry().get("red_team"),
        task=task,
        sources=references,
        context=context,
    )
    payload = {
        "schema_version": "equity_mapping_g0_red_team_v0.1",
        "artifact_type": "equity_mapping_g0_red_team",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "discovery",
            "local_sources_only": True,
            "environment_proxy_used": False,
            "llm_enabled": config.enabled,
            "llm_model": config.model,
            "llm_provider_profile": config.provider_profile,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "task": task.to_dict(),
        "source_manifest": [
            {
                "path": row["path"],
                "file_sha256": row["file_sha256"],
                "excerpt_sha256": row["excerpt_sha256"],
            }
            for row in source_rows
        ],
        "context_hash": _canonical_hash(context),
        "report": report.to_dict(),
    }
    artifact = write_research_json_artifact(
        Settings.from_env(),
        payload,
        kind="equity-mapping-g0-red-team",
        path_key="artifact_path",
        default_filename="equity_mapping_g0_red_team.json",
        explicit_path=args.output_path,
    )
    print(f"artifact={artifact['artifact_path']}")
    print(f"status={report.status}")
    print(f"model={config.model}")
    print(f"context_hash={payload['context_hash']}")
    print("orders_allowed=False")
    print("paper_or_live_allowed=False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
