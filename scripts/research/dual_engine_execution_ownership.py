"""One frozen research-only ownership/acquisition study."""
import argparse
import json
from pathlib import Path
from qount.research.dual_engine_execution_ownership import run_study

def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__)
 for name in ('contract','out','repo'):p.add_argument('--'+name,type=Path,required=True)
 a=vars(p.parse_args(argv));a['contract_path']=a.pop('contract');r=run_study(**a)
 print(json.dumps({'curves':len(r['curve_exposures']),'out':str(a['out'])}));return 0
if __name__=='__main__':raise SystemExit(main())
