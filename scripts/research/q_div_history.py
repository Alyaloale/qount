"""Thin adapter for dated Q-DIV financial evidence audits (no returns)."""
import argparse
import json
from qount.research.q_div_history import audit


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--financial-root', required=True)
    p.add_argument('--review-days', required=True)
    p.add_argument('--out', required=True)
    a = p.parse_args()
    print(json.dumps(audit(a.financial_root, a.out, a.review_days), ensure_ascii=False))


if __name__ == '__main__':
    main()
