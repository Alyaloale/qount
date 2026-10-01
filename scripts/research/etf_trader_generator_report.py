"""Structural-generator acceptance report (ETF expert trader §7.2/§7.3).

research_only=true / orders_authorized=false / trial=false. Synthetic worlds only: no market
data, credentials, accounts or paper state. Design: docs/etf-imitation-policy-design-2026-09.md
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from qount.research.etf_trader.generator.calibration import calibration_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", choices=("us", "cn"), required=True)
    parser.add_argument("--worlds", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260930)
    parser.add_argument("--plausibility-years", type=float, default=100.0)
    parser.add_argument("--stylized-years", type=float, default=40.0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    report = calibration_report(
        args.account, args.worlds, args.seed, args.plausibility_years, args.stylized_years, args.workers
    )
    text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
        os.chmod(args.out, 0o600)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
