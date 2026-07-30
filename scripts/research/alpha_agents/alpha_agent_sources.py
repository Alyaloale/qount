#!/usr/bin/env python3
"""Build a research-only source-quality report for Alpha Agents."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.alpha_agents.knowledge import build_knowledge_report  # noqa: E402
from qount.alpha_agents.knowledge import write_knowledge_report_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tags", default="", help="Comma-separated SOURCE_BOOK tags; empty means all.")
    parser.add_argument("--output-path", default=None)
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    tags = tuple(item.strip() for item in args.tags.split(",") if item.strip()) or None
    payload = build_knowledge_report(tags)
    artifact = write_knowledge_report_artifact(Settings.from_env(), payload, explicit_path=args.output_path)
    if args.print_json:
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
    else:
        print(f"artifact={artifact['artifact_path']}")
        print(f"source_count={artifact['source_count']}")
        print(f"verdict_counts={artifact['verdict_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
