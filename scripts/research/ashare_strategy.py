"""Run frozen A-share research selection/holding proxy backtest on WSL/E."""
import argparse
import json
from pathlib import Path
from qount.research.ashare_strategy import run

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(argv)
    result=run(args.contract,args.out)
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    return 0

if __name__=='__main__':raise SystemExit(main())
