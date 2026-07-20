#!/usr/bin/env python3
"""Collect and audit public Binance USD-M microstructure streams.

This is research-only. It records public websocket events and public depth
snapshots, writes a replayable artifact, and never reads account credentials or
places orders. A passing result is only a data-quality smoke verdict.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.alpha_agents.live_collector import LiveCollectorConfig  # noqa: E402
from qount.alpha_agents.live_collector import run_live_collector  # noqa: E402
from qount.alpha_agents.live_collector_session import LiveCollectorSessionConfig  # noqa: E402
from qount.alpha_agents.live_collector_session import mark_live_collector_session_superseded  # noqa: E402
from qount.alpha_agents.live_collector_session import resume_live_collector_session  # noqa: E402
from qount.alpha_agents.live_collector_session import run_live_collector_session  # noqa: E402
from qount.alpha_agents.live_collector_session import verify_live_collector_session  # noqa: E402
from qount.settings import Settings  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT")
    parser.add_argument("--streams", default="bookTicker,aggTrade,depth,forceOrder")
    parser.add_argument("--duration-seconds", type=int, default=60)
    parser.add_argument("--snapshot-interval-seconds", type=int, default=30)
    parser.add_argument("--depth-speed-ms", type=int, default=100, choices=(100, 250, 500))
    parser.add_argument("--depth-limit", type=int, default=1000, choices=(5, 10, 20, 50, 100, 500, 1000))
    parser.add_argument("--max-events", type=int, default=0)
    parser.add_argument("--max-snapshot-error-rate", type=float, default=0.01)
    parser.add_argument("--snapshot-max-retries", type=int, default=2)
    parser.add_argument("--snapshot-retry-delay-seconds", type=float, default=0.5)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--session-duration-seconds", type=int, default=0)
    parser.add_argument("--segment-duration-seconds", type=int, default=24 * 60 * 60)
    parser.add_argument("--max-segments", type=int, default=0)
    parser.add_argument("--resume-session-dir", default=None)
    parser.add_argument("--verify-session-dir", default=None)
    parser.add_argument("--supersede-session-dir", default=None)
    parser.add_argument("--replacement-session-id", default=None)
    parser.add_argument("--minimum-session-duration-seconds", type=int, default=7 * 24 * 60 * 60)
    parser.add_argument("--ws-base-url", default="wss://fstream.binance.com")
    parser.add_argument("--ws-api-url", default="wss://ws-fapi.binance.com/ws-fapi/v1")
    parser.add_argument("--depth-url", default="https://fapi.binance.com/fapi/v1/depth")
    parser.add_argument("--snapshot-transport", default="websocket_api", choices=("websocket_api", "rest"))
    parser.add_argument("--no-proxy-env", action="store_true")
    parser.add_argument("--min-free-disk-gb", type=float, default=0.0)
    parser.add_argument("--disk-check-interval-seconds", type=float, default=30.0)
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.supersede_session_dir:
        if not args.replacement_session_id:
            raise ValueError("--supersede-session-dir requires --replacement-session-id")
        artifact = mark_live_collector_session_superseded(
            args.supersede_session_dir,
            args.replacement_session_id,
        )
        print(f"artifact={Path(args.supersede_session_dir).expanduser() / 'alpha_agent_live_collector_session.json'}")
        print(f"status={artifact['session']['status']}")
        print(f"replacement_session_id={args.replacement_session_id}")
        return 0
    if args.verify_session_dir:
        if args.resume_session_dir or args.output_dir or args.session_duration_seconds or args.max_segments:
            raise ValueError(
                "--verify-session-dir cannot be combined with resume/output/session-duration/max-segments"
            )
        verification = verify_live_collector_session(
            args.verify_session_dir,
            minimum_duration_seconds=args.minimum_session_duration_seconds,
        )
        if args.print_json:
            print(json.dumps(verification, ensure_ascii=False, indent=2))
        else:
            print(f"session={verification['session_artifact_path']}")
            print(f"segments={len(verification['segments'])}")
            print(f"deep_replay={str(verification['deep_replay']).lower()}")
            print(f"verdict={verification['verdict']}")
            print(f"blockers={','.join(verification['blockers']) or 'none'}")
        if verification["verdict"] == "pass_data_gate":
            return 0
        if verification["verdict"] == "incomplete":
            return 2
        return 1
    config = LiveCollectorConfig(
        symbols=tuple(item.strip().upper() for item in args.symbols.split(",") if item.strip()),
        streams=tuple(item.strip() for item in args.streams.split(",") if item.strip()),
        duration_seconds=args.duration_seconds,
        snapshot_interval_seconds=args.snapshot_interval_seconds,
        depth_speed_ms=args.depth_speed_ms,
        depth_limit=args.depth_limit,
        max_events=args.max_events,
        max_snapshot_error_rate=args.max_snapshot_error_rate,
        snapshot_max_retries=args.snapshot_max_retries,
        snapshot_retry_delay_seconds=args.snapshot_retry_delay_seconds,
        ws_base_url=args.ws_base_url,
        ws_api_url=args.ws_api_url,
        depth_url=args.depth_url,
        snapshot_transport=args.snapshot_transport,
        use_proxy_env=not args.no_proxy_env,
        min_free_disk_bytes=int(args.min_free_disk_gb * 1024**3),
        disk_check_interval_seconds=args.disk_check_interval_seconds,
    )
    settings = Settings.from_env()
    if args.resume_session_dir:
        if args.output_dir or args.session_duration_seconds:
            raise ValueError("--resume-session-dir cannot be combined with --output-dir or --session-duration-seconds")
        artifact = resume_live_collector_session(
            settings,
            args.resume_session_dir,
            max_segments=args.max_segments,
        )
    elif args.session_duration_seconds:
        artifact = run_live_collector_session(
            settings,
            config,
            LiveCollectorSessionConfig(
                total_duration_seconds=args.session_duration_seconds,
                segment_duration_seconds=args.segment_duration_seconds,
            ),
            explicit_output_dir=args.output_dir,
            max_segments=args.max_segments,
        )
    else:
        artifact = run_live_collector(settings, config, explicit_output_dir=args.output_dir)
    if args.print_json:
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
    elif artifact.get("schema_version", "").startswith("alpha_agent_live_collector_session_"):
        session = artifact["session"]
        aggregate = artifact["aggregate"]
        print(f"artifact={artifact['artifact_path']}")
        print(f"status={session['status']}")
        print(f"segments={aggregate['segment_count']}")
        print(f"market_events={aggregate['market_events']}")
        print(f"verdict={session['verdict']}")
        print(f"remaining_seconds={session['remaining_duration_seconds']}")
    else:
        audit = artifact["audit"]
        print(f"artifact={artifact['artifact_path']}")
        print(f"raw={artifact['raw_event_path']}")
        print(f"market_events={artifact['capture']['market_events']}")
        print(f"verdict={audit['verdict']}")
        print(f"blockers={','.join(audit['blockers']) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
