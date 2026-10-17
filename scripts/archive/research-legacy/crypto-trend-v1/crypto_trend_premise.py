"""Run the descriptive crypto trend-premise diagnostic (not a trial) on the frozen cost-study bundle.

research_only=true / orders_authorized=false. Offline; no network, no paper state.
Preregistration: docs/crypto-trend-premise-diagnostic-2026-09.md
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from qount.contracts import canonical_hash
from qount.research.c60_cost_study import build_panel
from qount.research.crypto_trend_premise import run

DEFAULT_CLOSES = Path("state/research_runs/c60_cost_expectancy_v1/7495a6fbc649fd2d/closes.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--closes", type=Path, default=DEFAULT_CLOSES)
    parser.add_argument("--out-root", type=Path, default=Path("state/research_runs/crypto_trend_premise_v1"))
    args = parser.parse_args(argv)

    panel, audit = build_panel(json.loads(args.closes.read_text()))
    result = run(panel) | {"data_hash": audit["data_hash"], "closes_path": str(args.closes)}
    args.out_root.mkdir(parents=True, exist_ok=True)
    os.chmod(args.out_root, 0o700)
    out = args.out_root / f"{canonical_hash(result)[:16]}.json"
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    os.chmod(out, 0o600)
    print(json.dumps({"out": str(out)} | result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
