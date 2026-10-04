#!/usr/bin/env python3
"""Register immutable P2 evidence; no training, inference, env or service access."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from qount.research.etf_alpha.preservation import freeze_p2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("historical", "provenance", "recovery", "data-root", "out", "repo"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--mac-inventory", type=Path)
    args = parser.parse_args()
    report = freeze_p2(args.historical, args.provenance, args.recovery, args.data_root,
                       args.out, args.repo, args.mac_inventory)
    print(json.dumps({k: report[k] for k in ("baseline_id", "m0_status", "completion_status",
          "historical_checkpoint_count", "cloud_checkpoint_count", "research_only", "orders_authorized")}))


if __name__ == "__main__":
    main()
