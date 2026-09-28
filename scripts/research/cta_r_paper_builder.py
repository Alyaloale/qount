#!/usr/bin/env python3
"""Build the isolated CTA-R research paper sidecar from a public ETF seed."""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.research.cta_r_paper import build_cta_r_paper_snapshot  # noqa: E402
from qount.research.cta_r_paper import write_cta_r_paper_snapshot  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--observed-at", default=None)
    args = parser.parse_args(argv)
    observed = dt.datetime.fromisoformat(args.observed_at) if args.observed_at else None
    snapshot = build_cta_r_paper_snapshot(args.seed, observed_at=observed)
    # The static Dashboard sidecar contains public research data and must be readable by its web server.
    write_cta_r_paper_snapshot(snapshot, args.out, mode=0o644)
    print(f"output={args.out.resolve()}")
    print(f"status={snapshot['status']}")
    print(f"data_cutoff={snapshot['data_cutoff']}")
    print("research_only=true")
    print("orders_authorized=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
