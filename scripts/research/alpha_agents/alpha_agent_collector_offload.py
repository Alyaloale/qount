#!/usr/bin/env python3
"""Pull verified closed collector segments to the Mac or acknowledge remote deletion."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.alpha_agents.live_collector_offload import pull_offloaded_segments  # noqa: E402
from qount.alpha_agents.live_collector_offload import remote_ack_segment  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    pull = subparsers.add_parser("pull")
    pull.add_argument("--remote-host", default="qount-vps")
    pull.add_argument("--remote-session-dir", default="/root/qount-alpha/state/alpha-collector-current")
    pull.add_argument("--local-archive-root", default=str(REPO / "state" / "research_runs"))
    pull.add_argument("--delete-remote", action="store_true")
    pull.add_argument("--min-local-free-gb", type=float, default=20.0)
    pull.add_argument("--connect-timeout-seconds", type=int, default=15)
    pull.add_argument("--remote-python", default="/root/qount-alpha/.venv/bin/python")
    pull.add_argument(
        "--remote-cli",
        default="/root/qount-alpha/scripts/research/alpha_agents/alpha_agent_collector_offload.py",
    )

    remote_ack = subparsers.add_parser("remote-ack")
    remote_ack.add_argument("--session-dir", required=True)
    remote_ack.add_argument("--segment-index", type=int, required=True)
    remote_ack.add_argument("--raw-sha256", required=True)
    remote_ack.add_argument("--receipt-id", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "pull":
        result = pull_offloaded_segments(
            remote_host=args.remote_host,
            remote_session_dir=args.remote_session_dir,
            local_archive_root=args.local_archive_root,
            delete_remote=args.delete_remote,
            min_local_free_bytes=int(args.min_local_free_gb * 1024**3),
            connect_timeout_seconds=args.connect_timeout_seconds,
            remote_python=args.remote_python,
            remote_cli=args.remote_cli,
        )
    else:
        result = remote_ack_segment(
            args.session_dir,
            args.segment_index,
            args.raw_sha256,
            args.receipt_id,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
