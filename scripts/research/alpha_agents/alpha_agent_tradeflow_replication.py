#!/usr/bin/env python3
"""Preregister or evaluate frozen trade-flow cross-symbol replication."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.alpha_agents.tradeflow_replication import build_tradeflow_replication_preregistration  # noqa: E402
from qount.alpha_agents.tradeflow_replication import build_tradeflow_replication_report  # noqa: E402
from qount.alpha_agents.tradeflow_replication import write_tradeflow_replication_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


def _mapping(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        symbol, separator, path = value.partition("=")
        if not separator or not symbol or not path:
            raise ValueError("replica paths must use SYMBOL=PATH")
        result[symbol.upper()] = path
    return result


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preregister-only", action="store_true")
    parser.add_argument("--preregistration-path", default=None)
    parser.add_argument("--anchor-discovery-path", default=None)
    parser.add_argument("--anchor-oos-path", default=None)
    parser.add_argument("--replica-discovery", action="append", default=[])
    parser.add_argument("--replica-oos", action="append", default=[])
    parser.add_argument("--output-path", default=None)
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.preregister_only:
        payload = build_tradeflow_replication_preregistration()
    else:
        required = {
            "preregistration_path": args.preregistration_path,
            "anchor_discovery_path": args.anchor_discovery_path,
            "anchor_oos_path": args.anchor_oos_path,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"replication report missing arguments: {','.join(missing)}")
        payload = build_tradeflow_replication_report(
            preregistration_path=args.preregistration_path,
            anchor_discovery_path=args.anchor_discovery_path,
            anchor_oos_path=args.anchor_oos_path,
            replica_discovery_paths=_mapping(args.replica_discovery),
            replica_oos_paths=_mapping(args.replica_oos),
        )
    artifact = write_tradeflow_replication_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    diagnostics = artifact["diagnostics"]
    if args.print_json:
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
    else:
        print(f"artifact={artifact['artifact_path']}")
        print(f"artifact_type={artifact['artifact_type']}")
        print(f"protocol_hash={artifact['protocol']['protocol_hash']}")
        print(f"verdict={diagnostics['verdict']}")
        if artifact["artifact_type"] == "replication_report":
            print(f"replica_oos_count={diagnostics['replica_oos_count']}")
            print(f"positive_replica_rank_ic_count={diagnostics['positive_replica_rank_ic_count']}")
            print(f"positive_replica_residual_count={diagnostics['positive_replica_residual_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
