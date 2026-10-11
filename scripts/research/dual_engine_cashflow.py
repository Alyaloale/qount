"""Frozen, public-data-only BTC cashflow feasibility research."""
import argparse
import json
from pathlib import Path

from qount.research.dual_engine_cashflow import read_contract, run_study
from qount.research.dual_engine_cashflow_data import acquire
from qount.research.dual_engine_cashflow_verify import verify_study
from qount.research.dual_engine_cashflow_inputs import prepare_inputs
from qount.research.dual_engine_cashflow_qualification import run_coverage_audit
from qount.research.dual_engine_cashflow_mark_repair import repair_mark_inputs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for command, names in (('acquire', ('contract', 'out')), ('audit', ('contract', 'prior-partial-root', 'out')),
                           ('repair', ('coverage-root', 'gap-plan', 'out')),
                           ('prepare', ('contract', 'coverage-root', 'out')), ('run', ('contract', 'input-root', 'out', 'repo')), ('verify', ('out', 'repo'))):
        child = sub.add_parser(command)
        for name in names:
            child.add_argument('--' + name, type=Path, required=True)
        if command == 'prepare':
            child.add_argument('--mark-repair-root', type=Path)
    args = vars(parser.parse_args(argv))
    command = args.pop('command')
    if command == 'acquire':
        result = acquire(read_contract(args.pop('contract')), **args)
    elif command == 'repair':
        result = repair_mark_inputs(**args)
    elif command in ('audit', 'prepare'):
        args['contract_path'] = args.pop('contract')
        result = (run_coverage_audit if command == 'audit' else prepare_inputs)(**args)
    elif command == 'run':
        args['contract_path'] = args.pop('contract')
        result = run_study(**args)
        result = {'curves': len(result['curve_exposures']), 'feasibility_passed': result['feasibility_passed']}
    else:
        result = verify_study(**args)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
