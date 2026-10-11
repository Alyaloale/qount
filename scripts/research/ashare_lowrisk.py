"""Run frozen A-share low-risk uptrend research backtest on WSL/E."""
import argparse
import json
from pathlib import Path
from qount.research.ashare_lowrisk import run

def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--contract',required=True,type=Path);p.add_argument('--out',required=True,type=Path)
 a=p.parse_args(argv);print(json.dumps(run(a.contract,a.out),ensure_ascii=False,indent=2,allow_nan=False));return 0

if __name__=='__main__':raise SystemExit(main())
