"""Public-data-only, fixed-horizon opportunity research; never orders or services."""
import argparse
import json
from pathlib import Path

from qount.research.opportunity_data import acquire, requalify, run, verify


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name, fields in (('acquire', ('contract', 'out')), ('requalify', ('contract', 'input-root', 'out')),
                         ('run', ('contract', 'input-root', 'out', 'repo')),
                         ('verify', ('out',))):
        p = sub.add_parser(name)
        for field in fields:
            p.add_argument('--' + field, type=Path, required=True)
        if name == 'acquire':
            p.add_argument('--reuse-roots', type=Path, nargs='*', default=[])
    args = vars(parser.parse_args(argv))
    command = args.pop('command')
    if 'contract' in args:
        args['contract_path'] = args.pop('contract')
    result = {'acquire': acquire, 'requalify': requalify, 'run': run, 'verify': verify}[command](**args)
    if command == 'run':
        result = {k: result[k] for k in ('study_id', 'candidate_diagnostic_gate_passed', 'decision', 'manifest_sha256')}
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
