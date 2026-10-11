"""Mac-only historical P1 public-source collector; private credential file input."""
import argparse
from pathlib import Path
from qount.research.q_div_acquisition import collect_history,collect_repairs


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract',type=Path,required=True)
    parser.add_argument('--credential-file',type=Path,default=Path.home()/'.config/qount/tushare.env')
    parser.add_argument('--receipt-root',type=Path,required=True)
    parser.add_argument('--windows-root',required=True)
    parser.add_argument('--sink-script',required=True)
    parser.add_argument('--repair-inventory',type=Path)
    parser.add_argument('--repair-inventory-sha256')
    parser.add_argument('--repair-seed',type=Path)
    args=parser.parse_args()
    repair=(args.repair_inventory,args.repair_inventory_sha256,args.repair_seed)
    if any(repair) and not all(repair):parser.error('all three --repair-* options are required together')
    kwargs=dict(contract_path=args.contract,credential_path=args.credential_file,
        local=args.receipt_root,root=args.windows_root,sink_script=args.sink_script)
    result=(collect_repairs(**kwargs,inventory_path=args.repair_inventory,
        inventory_sha256=args.repair_inventory_sha256,seed_path=args.repair_seed)
        if all(repair) else collect_history(**kwargs))
    return 1 if result['fatal'] or result['jobs'].get('failed_or_withheld',0) else 0


if __name__=='__main__':
    raise SystemExit(main())
