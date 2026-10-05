"""Run fixed G20/C60 major redesigns and preserve immutable strategy versions."""
import argparse
import json
from pathlib import Path
from qount.research.dual_engine_nextgen import read_contract, prepare_opens, run_study
from qount.research.dual_engine_nextgen_data import acquire_supply
from qount.research.dual_engine_registry import build_registry
from qount.research.dual_engine_confirmation import acquire_crypto_later, acquire_crypto_rest_later, run_later


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--contract", type=Path, required=True)
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("acquire-supply")
    for s in ("pit-cache", "out"):
        a.add_argument("--" + s, type=Path, required=True)
    a = sub.add_parser("acquire-opens")
    for s in ("pit-cache", "supply-root", "out"):
        a.add_argument("--" + s, type=Path, required=True)
    a.add_argument("--prior-open-roots", type=Path, nargs="+", required=True)
    a = sub.add_parser("run")
    for s in ("prior-contract", "equity-root", "pit-cache", "expansion-root", "rates-root", "supply-root", "tail-root", "open-root", "prior-results", "out", "repo"):
        a.add_argument("--" + s, type=Path, required=True)
    a = sub.add_parser("register")
    a.add_argument("--studies", type=Path, required=True, help="JSON root/manifest_sha256 pairs and optional selection_exclusions")
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--parent-registry-root", type=Path)
    a = sub.add_parser("acquire-later-crypto")
    for s in ("registry-root", "pit-cache", "out"):
        a.add_argument("--" + s, type=Path, required=True)
    a.add_argument("--archive-period", choices=("monthly", "daily"), default="monthly")
    a = sub.add_parser("acquire-later-rest")
    for s in ("registry-root", "discovery-results", "out"):
        a.add_argument("--" + s, type=Path, required=True)
    a = sub.add_parser("confirm-later")
    for s in ("registry-root", "discovery-results", "equity-later-root", "crypto-later-root", "rates-later-root", "out", "repo"):
        a.add_argument("--" + s, type=Path, required=True)
    args = p.parse_args(argv)
    read_contract(args.contract)
    kwargs = {k: v for k, v in vars(args).items() if k not in ("command", "contract")}
    if args.command == "acquire-supply":
        result = acquire_supply(**kwargs)
        receipt = {"files": len(result["files"])}
    elif args.command == "acquire-opens":
        result = prepare_opens(contract_path=args.contract, **kwargs)
        receipt = {"archives": result["archive_count"]}
    elif args.command == "acquire-later-crypto":
        result = acquire_crypto_later(**kwargs)
        receipt = {"files": len(result["files"])}
    elif args.command == "acquire-later-rest":
        result = acquire_crypto_rest_later(**kwargs)
        receipt = {"files": len(result["files"])}
    elif args.command == "confirm-later":
        result = run_later(**kwargs)
        receipt = {"curves": len(result["summaries"]), "confirmation_status": result["confirmation_status"]}
    elif args.command == "register":
        spec = json.loads(args.studies.read_text())
        result = build_registry([(Path(r["root"]), r["manifest_sha256"]) for r in spec["studies"]],
            args.out, selection_exclusions=spec.get("selection_exclusions", []), parent_registry_root=args.parent_registry_root)
        receipt = {"versions": len(result["versions"]), "curves": len(result["curve_exposures"]), "leaders": result["leaders"]}
    else:
        result = run_study(contract_path=args.contract, **kwargs)
        receipt = {"curves": len(result["curve_exposures"])}
    print(json.dumps({**receipt, "out": str(args.out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
