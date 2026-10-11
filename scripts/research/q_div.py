"""Thin no-order Q-DIV research snapshot adapter."""
import argparse
import json
from pathlib import Path

from qount.research.q_div_data import fundamental_screen, price_screen


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=['price-screen','fundamental-screen'])
    p.add_argument('--contract', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--technical-root', type=Path)
    p.add_argument('--financial-root', type=Path)
    a = p.parse_args()
    if a.phase == 'price-screen':
        result = price_screen(a.contract,a.out)
    else:
        if not a.technical_root or not a.financial_root:
            p.error('fundamental-screen requires --technical-root and --financial-root')
        result = fundamental_screen(a.contract,a.technical_root,a.financial_root,a.out)
    print(json.dumps({k:v for k,v in result.items() if k != 'source'},ensure_ascii=False))


if __name__ == '__main__':
    main()
