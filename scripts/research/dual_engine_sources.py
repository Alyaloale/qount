"""Acquire qualified public information, replay and register the eleventh study."""
import argparse
import json
from pathlib import Path

from qount.research.dual_engine_information_data import acquire
from qount.research.dual_engine_sources import read_contract, run_study
from qount.research.dual_engine_registry import build_registry


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract', type=Path, required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    acquire_parser = sub.add_parser('acquire')
    for name in ('out', 'prior-open-root', 'pit-cache', 'curve-csv', 'curve-receipt'):
        acquire_parser.add_argument('--' + name, type=Path, required=True)
    run = sub.add_parser('run')
    for name in ('prior-contract', 'equity-root', 'pit-cache', 'expansion-root', 'rates-root',
                 'inverse-root', 'tail-root', 'open-root', 'prior-results', 'information-root', 'out', 'repo'):
        run.add_argument('--' + name, type=Path, required=True)
    register = sub.add_parser('register')
    register.add_argument('--studies', type=Path, required=True)
    register.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    contract = read_contract(args.contract)
    kwargs = {k: v for k, v in vars(args).items() if k not in ('command', 'contract')}
    if args.command == 'acquire':
        result = acquire(**kwargs)
    elif args.command == 'run':
        result = run_study(contract_path=args.contract, **kwargs)
        result = {'curves': len(result['curve_exposures'])}
    else:
        spec = json.loads(args.studies.read_text())
        # Snapshot qualification must be preserved regardless of caller input.
        exclusions = sorted(set(spec.get('selection_exclusions', [])) | set(contract['selection_exclusions']))
        result = build_registry([(Path(r['root']), r['manifest_sha256']) for r in spec['studies']],
                                args.out, selection_exclusions=exclusions)
        result = {'versions': len(result['versions']), 'curves': len(result['curve_exposures']), 'leaders': result['leaders']}
    print(json.dumps({**result, 'out': str(args.out)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
