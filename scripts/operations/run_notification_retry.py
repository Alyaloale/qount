#!/usr/bin/env python3
"""Retry a bounded batch of due OpenClaw Weixin notification jobs."""

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
from qount.notifications import OPENCLAW_WEIXIN_PROVIDER_NAME  # noqa: E402
from qount.notifications import OpenClawWeixinProvider  # noqa: E402
from qount.notifications import ProviderTransport  # noqa: E402
from qount.notifications import RateLimitPolicy  # noqa: E402


MAXIMUM_RETRY_BATCH = 2


def _bounded_batch(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("retry_limit_invalid") from exc
    if not 1 <= parsed <= MAXIMUM_RETRY_BATCH:
        raise argparse.ArgumentTypeError("retry_limit_invalid")
    return parsed


def _positive_seconds(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("retry_seconds_invalid") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("retry_seconds_invalid")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notification-store", type=Path, required=True)
    parser.add_argument("--credential-path", type=Path, required=True)
    parser.add_argument("--context-token-directory", type=Path, required=True)
    parser.add_argument("--limit", type=_bounded_batch, default=MAXIMUM_RETRY_BATCH)
    parser.add_argument(
        "--retry-base-seconds",
        type=_positive_seconds,
        default=300,
    )
    parser.add_argument("--timeout-seconds", type=_positive_seconds, default=20)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    attempted_at = dt.datetime.now(dt.timezone.utc).isoformat()
    store = NotificationStore(args.notification_store.absolute())
    transport = ProviderTransport(
        OpenClawWeixinProvider(
            timeout_seconds=args.timeout_seconds,
            context_token_directory=args.context_token_directory.absolute(),
        ),
        provider_name=OPENCLAW_WEIXIN_PROVIDER_NAME,
        credential_path=args.credential_path.absolute(),
        require_credential=True,
        timeout_seconds=args.timeout_seconds + 5,
        rate_limit=RateLimitPolicy(
            max_calls=MAXIMUM_RETRY_BATCH,
            window_seconds=1.0,
        ),
    )
    deliveries = store.deliver_due(
        attempted_at=attempted_at,
        transport=transport,
        channel=OPENCLAW_WEIXIN_PROVIDER_NAME,
        limit=args.limit,
        retry_base_seconds=args.retry_base_seconds,
    )
    status_counts = Counter(str(item["status"]) for item in deliveries)
    print(
        json.dumps(
            {
                "attempted_at": attempted_at,
                "channel": OPENCLAW_WEIXIN_PROVIDER_NAME,
                "processed": len(deliveries),
                "status_counts": dict(sorted(status_counts.items())),
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
