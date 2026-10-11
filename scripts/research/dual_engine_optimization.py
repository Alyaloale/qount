"""Acquire public G20 inputs or run the frozen offline G20/C60 discovery study."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from qount.research.dual_engine_optimization import acquire_equity, read_contract, run_study


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    acquire = sub.add_parser("acquire-g20")
    acquire.add_argument("--out", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--equity-root", type=Path, required=True)
    run.add_argument("--pit-cache", type=Path, required=True)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "acquire-g20":
        manifest = acquire_equity(args.out, read_contract(args.contract))
        print(json.dumps({"input_root": str(args.out), "files": len(manifest["files"])}))
    else:
        result = run_study(equity_root=args.equity_root, pit_cache=args.pit_cache,
                           contract_path=args.contract, out=args.out, repo=args.repo)
        print(json.dumps({"out": str(args.out), "decisions": result["decisions"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
