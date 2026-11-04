#!/usr/bin/env python3
"""Observe one G20-LP v3 cycle receipt and enqueue alerts; --deliver sends now.

Two callers: ExecStopPost of qount-g20-v3-live.service (exception alerts and
the daily receipt summary reach the owner within seconds) and the hourly
qount-v3-watchdog timer (missed-cycle detection: receipt older than 30h, or
still non-live after the first cycle was due).  Failed deliveries stay PENDING
in the notification store and are retried by the qount-serverchan-retry timer.
Enqueue never depends on delivery.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.notifications import NotificationStore  # noqa: E402
from qount.notifications import ProviderTransport  # noqa: E402
from qount.notifications import RateLimitPolicy  # noqa: E402
from qount.notifications import SERVERCHAN_PROVIDER_NAME  # noqa: E402
from qount.notifications import ServerChanProvider  # noqa: E402
from qount.operations.v3_notifications import collect_v3_runtime  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--halt", type=Path, required=True)
    parser.add_argument("--notification-store", type=Path, required=True)
    parser.add_argument("--credential-path", type=Path, required=True)
    parser.add_argument("--deliver", action="store_true")
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--retry-base-seconds", type=int, default=300)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    attempted_at = dt.datetime.now(dt.timezone.utc).isoformat()
    runtime = collect_v3_runtime(args.result, args.halt,
                                 notification_store=args.notification_store.absolute())
    result = {"runtime": runtime, "delivered": None}
    if args.deliver:
        try:
            store = NotificationStore(args.notification_store.absolute())
            transport = ProviderTransport(
                ServerChanProvider(timeout_seconds=args.timeout_seconds),
                provider_name=SERVERCHAN_PROVIDER_NAME,
                credential_path=args.credential_path.absolute(),
                require_credential=True,
                timeout_seconds=args.timeout_seconds + 5,
                rate_limit=RateLimitPolicy(max_calls=args.limit, window_seconds=1.0),
            )
            deliveries = store.deliver_due(
                attempted_at=attempted_at,
                transport=transport,
                channel=SERVERCHAN_PROVIDER_NAME,
                limit=args.limit,
                retry_base_seconds=args.retry_base_seconds,
            )
            result["delivered"] = dict(
                Counter(str(item["status"]) for item in deliveries))
        except Exception as exc:
            # Credentials and provider errors never leak into the receipt path.
            result["delivered"] = f"ERROR:{type(exc).__name__}"
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
