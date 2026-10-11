"""Thin WSL/E-only independent public-source audit adapter."""
import argparse
import json
from pathlib import Path
from qount.research.q_div_data_audit import audit


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--phases',nargs='+');p.add_argument('--index-name',default='responses.json')
    p.add_argument('--jobs-name',default='jobs.json')
    p.add_argument('--job-ids-name',help='immutable JSON list of exact planned IDs for an independent audit partition')
    a=p.parse_args();result=audit(root=a.root,out=a.out,selected_phases=a.phases,index_name=a.index_name,jobs_name=a.jobs_name,job_ids_name=a.job_ids_name)
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return 0 if not result['errors'] else 1


if __name__=='__main__':raise SystemExit(main())
