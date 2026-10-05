"""Run public-data G20/C60 breadth, fundamentals and crisis research."""
import argparse
import json
from pathlib import Path
from qount.research.dual_engine_expansion import read_contract, prepare_opens, run_study
from qount.research.dual_engine_expansion_data import acquire


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--contract", type=Path, required=True)
    commands = p.add_subparsers(dest="command", required=True)
    a = commands.add_parser("acquire-public")
    a.add_argument("--out", type=Path, required=True)
    a = commands.add_parser("acquire-opens")
    for s in ("pit-cache", "expansion-root", "prior-open-root", "out"):
        a.add_argument("--" + s, type=Path, required=True)
    a = commands.add_parser("run")
    for s in ("prior-contract", "equity-root", "pit-cache", "expansion-root", "rates-root", "open-root", "prior-results", "out", "repo"):
        a.add_argument("--" + s, type=Path, required=True)
    args = p.parse_args(argv)
    read_contract(args.contract)
    if args.command == "acquire-public":
        result = acquire(args.out)
        print(json.dumps({"files": len(result["files"])}))
    elif args.command == "acquire-opens":
        result = prepare_opens(contract_path=args.contract, pit_cache=args.pit_cache,
            expansion_root=args.expansion_root, prior_open_root=args.prior_open_root, out=args.out)
        print(json.dumps({"archives": result["archive_count"]}))
    else:
        kwargs = {k: v for k, v in vars(args).items() if k not in ("command", "contract")}
        result = run_study(contract_path=args.contract, **kwargs)
        print(json.dumps({"curves": len(result["curve_exposures"]), "out": str(args.out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
