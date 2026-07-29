#!/usr/bin/env python3
"""Run one public-data-only FOMC shadow watcher cycle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.notifications import NotificationStore  # noqa: E402
from qount.small_account.fomc_watcher import FomcStateStore  # noqa: E402
from qount.small_account.fomc_watcher import load_fomc_event_definition  # noqa: E402
from qount.small_account.fomc_watcher import run_fomc_shadow_cycle  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-config", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--notification-store", type=Path, required=True)
    parser.add_argument(
        "--observed-at",
        help="UTC observation override for deterministic order-free verification.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    event = load_fomc_event_definition(args.event_config)
    state_store = FomcStateStore(args.state_root, event.event_id)
    notification_store = NotificationStore(args.notification_store)
    result = run_fomc_shadow_cycle(
        event,
        state_store,
        observed_at=args.observed_at,
        notification_store=notification_store,
    )
    signal = result.get("signal") or {}
    chain = result.get("standard_chain") or {}
    standard_chain = chain.get("standard_chain") or {}
    sizing = chain.get("sizing") or {}
    summary = {
        "event_id": event.event_id,
        "observed_at": result["observed_at"],
        "stage": result["stage"],
        "side": signal.get("side"),
        "notional_usdt": sizing.get("notional_usdt"),
        "stress_loss_usdt": sizing.get("estimated_stress_loss_usdt"),
        "blockers": result["blockers"],
        "batch_id": standard_chain.get("batch_id"),
        "result_hash": result["result_hash"],
        "scorecard": result.get("scorecard"),
        "permissions": result["permissions"],
    }
    print(json.dumps(summary, ensure_ascii=True, allow_nan=False, sort_keys=True))
    return 2 if result["stage"] == "HALTED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
