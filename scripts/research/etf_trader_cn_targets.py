"""Build the CN autocorrelation calibration targets from 2005–2014 public index closes (§7.3).

research_only=true / orders_authorized=false / trial=false. Public Tencent index data only:
no credentials, accounts or paper state. The 2005–2014 window is outside the §9 CN test
window (2015–2026). Design: docs/etf-imitation-policy-design-2026-09.md
"""

from __future__ import annotations

import argparse
import csv
import os
import urllib.request
from pathlib import Path

from qount.research.etf_trader.generator import targets as TG

DEFAULT_OUT = Path("src/qount/research/etf_trader/generator/data/cn_targets.json")


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--raw-dir", type=Path, default=None, help="optionally keep the fetched closes as CSV")
    parser.add_argument("--draws", type=int, default=TG.BOOTSTRAP_DRAWS)
    args = parser.parse_args(argv)

    series = {code: TG.fetch_tencent_index(_get, code, TG.CALIBRATION_START, TG.CALIBRATION_END)
              for _, code in TG.CN_INDEX_FOR_COLUMN.values()}
    if args.raw_dir:
        args.raw_dir.mkdir(parents=True, exist_ok=True)
        for code, rows in series.items():
            with open(args.raw_dir / f"{code}_2005_2014.csv", "w", newline="") as fh:
                csv.writer(fh).writerows([("date", "close"), *rows])
    targets = TG.build_cn_targets(series, draws=args.draws)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(targets.to_json() + "\n")
    os.chmod(args.out, 0o644)
    print(targets.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
