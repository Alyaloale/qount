"""Freeze, prepare and replay ninth-round G20/C60 structural research."""
import argparse
import json
from pathlib import Path
from qount.research.dual_engine_reform import read_contract, run_study
from qount.research.dual_engine_registry import build_registry


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--contract", type=Path, required=True)
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("run")
    for s in ("prior-contract", "equity-root", "pit-cache", "expansion-root", "rates-root", "inverse-root", "tail-root", "open-root", "prior-results", "out", "repo"):
        a.add_argument("--" + s, type=Path, required=True)
    a = sub.add_parser("register")
    a.add_argument("--studies", type=Path, required=True)
    a.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    read_contract(args.contract)
    kwargs = {k: v for k, v in vars(args).items() if k not in ("command", "contract")}
    if args.command == "register":
        spec = json.loads(args.studies.read_text())
        result = build_registry([(Path(r["root"]), r["manifest_sha256"]) for r in spec["studies"]],
            args.out, selection_exclusions=spec.get("selection_exclusions", []))
        receipt = {"versions": len(result["versions"]), "curves": len(result["curve_exposures"]), "leaders": result["leaders"]}
    else:
        result = run_study(contract_path=args.contract, **kwargs)
        receipt = {"curves": len(result["curve_exposures"])}
    print(json.dumps({**receipt, "out": str(args.out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
