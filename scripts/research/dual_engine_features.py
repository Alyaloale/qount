"""Run a frozen C60 path-quality study with no order or fitting capability."""
import argparse
import json
from pathlib import Path
from qount.research.dual_engine_features import run_study


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('contract', 'pit-cache', 'open-root', 'prior-results', 'out', 'repo'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = vars(parser.parse_args(argv))
    args['contract_path'] = args.pop('contract')
    result = run_study(**args)
    print(json.dumps({'curves': len(result['curve_exposures']), 'out': str(args['out'])}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
