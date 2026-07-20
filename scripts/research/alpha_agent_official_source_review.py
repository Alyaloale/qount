#!/usr/bin/env python3
"""Fetch one allowlisted official document and request a research-only LLM review."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.alpha_agents.llm import AlphaLLMConfig  # noqa: E402
from qount.alpha_agents.llm import request_agent_report  # noqa: E402
from qount.alpha_agents.models import ResearchTask  # noqa: E402
from qount.alpha_agents.models import SourceRef  # noqa: E402
from qount.alpha_agents.official_sources import fetch_official_source_document  # noqa: E402
from qount.alpha_agents.official_sources import official_source_llm_context  # noqa: E402
from qount.alpha_agents.roles import default_registry  # noqa: E402
from qount.artifacts import write_research_json_artifact  # noqa: E402
from qount.models import utc_now  # noqa: E402
from qount.settings import Settings  # noqa: E402


def _canonical_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--objective", required=True)
    parser.add_argument("--role-id", default="market_data_scout")
    parser.add_argument("--with-llm", action="store_true")
    parser.add_argument("--output-path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    document = fetch_official_source_document(args.url)
    context = dict(official_source_llm_context(document))
    task = ResearchTask(
        task_id="official_source_review_v0",
        title=args.title,
        objective=args.objective,
        role_ids=(args.role_id,),
        required_outputs=("source_summary", "data_gap", "validation_gate"),
        source_tags=("official_source",),
        holdout_role="discovery",
        priority=10,
    )
    source = SourceRef(
        title=args.title,
        url=document.final_url,
        source_type="official_source_document",
        notes=f"sha256={document.source_hash}; observed_at={document.observed_at}",
    )
    config = AlphaLLMConfig.from_env(enabled_override=args.with_llm)
    report = request_agent_report(
        config=config,
        role=default_registry().get(args.role_id),
        task=task,
        sources=(source,),
        context=context,
    )
    payload = {
        "schema_version": "alpha_official_source_review_v0.1",
        "artifact_type": "alpha_official_source_review",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "discovery",
            "network_fetch_used": True,
            "environment_proxy_used": False,
            "llm_enabled": config.enabled,
            "llm_model": config.model,
            "llm_provider_profile": config.provider_profile,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "task": task.to_dict(),
        "source": document.to_metadata(),
        "source_context_hash": _canonical_hash(context),
        "source_text_excerpt": document.text_excerpt,
        "report": report.to_dict(),
    }
    artifact = write_research_json_artifact(
        Settings.from_env(),
        payload,
        kind="alpha-official-source-review",
        path_key="artifact_path",
        default_filename="alpha_official_source_review.json",
        explicit_path=args.output_path,
    )
    print(f"artifact={artifact['artifact_path']}")
    print(f"status={report.status}")
    print(f"model={config.model}")
    print(f"source_hash={document.source_hash}")
    print("orders_allowed=False")
    print("paper_or_live_allowed=False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
