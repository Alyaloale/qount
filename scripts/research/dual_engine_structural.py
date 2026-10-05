"""Explore structural G20/C60 alternatives on immutable public inputs."""

import argparse
import json
from pathlib import Path

from qount.research.dual_engine_structural import prepare_opens, read_contract, run_study


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    acq = commands.add_parser("acquire-opens")
    for name in ("pit-cache", "prior-open-root", "out"):
        acq.add_argument(f"--{name}", type=Path, required=True)
    run = commands.add_parser("run")
    for name in ("prior-contract", "equity-root", "pit-cache", "open-root", "prior-results", "out", "repo"):
        run.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args(argv)
    read_contract(args.contract)
    if args.command == "acquire-opens":
        result = prepare_opens(pit_cache=args.pit_cache, prior_open_root=args.prior_open_root,
                               out=args.out, contract_path=args.contract)
        print(json.dumps({"archives": result["archive_count"], "out": str(args.out)}))
    else:
        result = run_study(contract_path=args.contract, prior_contract=args.prior_contract,
            equity_root=args.equity_root, pit_cache=args.pit_cache, open_root=args.open_root,
            prior_results=args.prior_results, out=args.out, repo=args.repo)
        print(json.dumps({"out": str(args.out), "curves": len(result["curve_exposures"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
