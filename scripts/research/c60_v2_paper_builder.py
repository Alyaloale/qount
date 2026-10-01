"""Build the C60 v2 research-paper sidecar from public Binance closes.

research_only=true / orders_authorized=false. Writes only the sidecar JSON and its own
hash-chained forward ledger; never reads credentials or touches Dual-Engine paper state.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from qount.research.c60_v2_paper import (
    append_ledger, build_snapshot, fetch_series, read_ledger, write_snapshot,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=None, help="offline closes JSON (testing only)")
    parser.add_argument("--mode", choices=("600", "644"), default="644")
    args = parser.parse_args(argv)

    observed = dt.datetime.now(dt.timezone.utc)
    series = json.loads(args.cache.read_text()) if args.cache else fetch_series(observed)
    ledger = read_ledger(args.ledger)
    snapshot = build_snapshot(series, observed_at=observed, ledger=ledger)
    write_snapshot(snapshot, args.out, mode=int(args.mode, 8))
    appended = append_ledger(args.ledger, snapshot, ledger)
    print(json.dumps({"status": snapshot["status"], "reason_codes": snapshot["reason_codes"],
                      "data_cutoff": snapshot["data_cutoff"], "final_equity": snapshot["final_equity"],
                      "forward": snapshot["forward"], "ledger_appended": appended}))
    return 0 if snapshot["status"] == "valid" else 2


if __name__ == "__main__":
    raise SystemExit(main())
