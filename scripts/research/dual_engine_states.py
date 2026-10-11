"""Run one frozen research-only state/transition study."""
import argparse
import json
from pathlib import Path
from qount.research.dual_engine_states import run_study


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('contract','pit-cache','open-root','prior-results','out','repo'):
        p.add_argument('--'+name,type=Path,required=True)
    args = vars(p.parse_args(argv));args['contract_path'] = args.pop('contract')
    result = run_study(**args)
    print(json.dumps({'curves':len(result['curve_exposures']),'out':str(args['out'])}))
    return 0


if __name__=='__main__':raise SystemExit(main())
