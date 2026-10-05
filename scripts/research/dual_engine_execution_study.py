"""Acquire matched public opens or execute the frozen G20/C60 mechanism study."""

import argparse
import json
from pathlib import Path

from qount.research.dual_engine_execution_study import acquire, read_contract, run_study


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    acq = commands.add_parser("acquire-opens")
    acq.add_argument("--pit-cache", type=Path, required=True)
    acq.add_argument("--out", type=Path, required=True)
    run = commands.add_parser("run")
    for name in ("original-root", "equity-root", "pit-cache", "open-root", "original-contract", "out", "repo"):
        run.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args(argv)
    read_contract(args.contract)
    if args.command == "acquire-opens":
        result = acquire(pit_cache=args.pit_cache, out=args.out)
        print(json.dumps({"output": str(args.out), "files": len(result["files"])}))
    else:
        result = run_study(original_root=args.original_root, equity_root=args.equity_root, pit_cache=args.pit_cache,
                           open_root=args.open_root, contract_path=args.contract, original_contract_path=args.original_contract,
                           out=args.out, repo=args.repo)
        print(json.dumps({"out": str(args.out), "decisions": result["decisions"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
