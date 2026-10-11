"""Thin adapter for the frozen C60 gradient discovery comparison."""
import argparse
import json
from qount.research.c60_gradient_study import run


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--contract', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--repo', required=True)
    args = p.parse_args()
    result = run(args.contract, args.out, args.repo)
    print(json.dumps({k: v for k, v in result.items() if k != 'results'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
