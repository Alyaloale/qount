"""Attribute every frozen G20/C60 curve; no-order cash/unit holding episodes."""
import argparse
import json
from pathlib import Path
from qount.research.dual_engine_holdings import run_from_paths


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('contract','registry-root','out','repo','equity-root','pit-cache','expansion-root','tail-root','inverse-root'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--open-roots',type=Path,nargs='+',required=True)
    r=run_from_paths(**vars(p.parse_args(argv)))
    print(json.dumps({'counts':r['counts'],'result_status':r['result_status']}))
    return 0


if __name__=='__main__':raise SystemExit(main())
