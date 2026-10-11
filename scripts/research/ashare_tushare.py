"""Thin Mac-only adapter: secret on the terminal; only public bytes cross SSH."""
import argparse
import getpass
import hashlib
import subprocess
from pathlib import Path

from qount.research.ashare_tushare import acquire


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--contract',type=Path,required=True)
    p.add_argument('--receipt',type=Path,required=True)
    p.add_argument('--public-sink',required=True)
    p.add_argument('--e-root',required=True)
    a=p.parse_args()
    def put(name, public):
        digest=hashlib.sha256(public).hexdigest()
        subprocess.run(['ssh','-o','BatchMode=yes','qount-wsl','python3',a.public_sink,a.e_root,name,digest],
                       input=public,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True)
    result=acquire(contract_path=a.contract,token=getpass.getpass('Tushare credential (hidden, memory only): '),
                   put_public=put,receipt_path=a.receipt)
    print({k:v for k,v in result.items() if k not in ('error',)},flush=True)
    return 0 if result['status']=='completed' else 1


if __name__=='__main__':raise SystemExit(main())
