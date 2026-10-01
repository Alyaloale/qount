"""Refresh the CTA-R public qfq seed, extend the forward ledger and publish the CTA-R sidecar.

research_only=true / orders_authorized=false. Public Tencent quotes only; no credentials.
Writes only its own state directory and the static sidecar JSON. Does not touch the CTA-R input
collector, its seed, or any Dual-Engine paper state. Contract: docs/cta-r-forward-ledger-2026-09.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import time
import urllib.request
from pathlib import Path

from qount.research.cta_r_forward import (
    CONTRACT, CtaRForwardError, advance, append_ledger, fetch_tencent_series, forward_summary,
    load_panel, read_ledger, replay_drift, write_seed,
)
from qount.research.cta_r_paper import build_cta_r_paper_snapshot, write_cta_r_paper_snapshot


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 qount-research"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed public host
                body = response.read()
            time.sleep(0.15)
            return body
        except OSError:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def _refresh_seed(seed: Path, observed: dt.datetime, ledger_last: str | None) -> list[str]:
    """Replace the seed only if the fresh fetch is complete and not behind the ledger."""

    tmp = seed.with_name(seed.name + ".candidate")
    try:
        write_seed(tmp, fetch_tencent_series(_get, observed_at=observed), fetched_at=observed)
        candidate = load_panel(tmp)
        if ledger_last and candidate.dates[-1] < ledger_last:
            raise CtaRForwardError("seed_behind_ledger")
    except (OSError, ValueError) as error:
        tmp.unlink(missing_ok=True)
        return [f"seed_refresh_failed:{type(error).__name__}:{str(error)[:80]}"]
    if seed.exists():
        shutil.copy2(seed, seed.with_name(seed.name + ".previous"))
    tmp.replace(seed)
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--no-fetch", action="store_true", help="reuse the existing seed (testing/offline)")
    parser.add_argument("--mode", choices=("600", "644"), default="644")
    args = parser.parse_args(argv)

    observed = dt.datetime.now(dt.timezone.utc)
    seed = args.state_dir / "seed" / "etf_data.zip"
    ledger_path = args.state_dir / "forward-ledger.jsonl"
    ledger = read_ledger(ledger_path)
    reasons = [] if args.no_fetch else _refresh_seed(seed, observed, ledger[-1]["date"] if ledger else None)
    if not seed.exists():
        print(json.dumps({"status": "insufficient", "reason_codes": reasons + ["seed_missing"]}))
        return 2

    panel = load_panel(seed)
    new, advance_reasons = advance(panel, ledger)
    appended = append_ledger(ledger_path, new)
    ledger = ledger + new
    reasons += advance_reasons

    snapshot = build_cta_r_paper_snapshot(seed, observed_at=observed)
    snapshot["source"] = CONTRACT["source"]
    snapshot["forward"] = forward_summary(ledger, drift=replay_drift(panel, ledger))
    snapshot["reason_codes"] = list(snapshot["reason_codes"]) + reasons
    if any(r.startswith(("seed_refresh_failed", "forward_head_missing")) for r in reasons):
        snapshot["status"] = "insufficient"
    write_cta_r_paper_snapshot(snapshot, args.out, mode=int(args.mode, 8))
    print(json.dumps({"status": snapshot["status"], "reason_codes": snapshot["reason_codes"],
                      "data_cutoff": snapshot["data_cutoff"], "ledger_appended": appended,
                      "forward": {k: snapshot["forward"][k] for k in
                                  ("bars", "last_date", "return", "stress_return", "rebalances",
                                   "replay_max_return_diff", "ledger_head_hash")},
                      "research_only": True, "orders_authorized": False}))
    return 0 if snapshot["status"] == "valid" else 2


if __name__ == "__main__":
    raise SystemExit(main())
