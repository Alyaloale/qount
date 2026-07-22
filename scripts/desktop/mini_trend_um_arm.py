#!/usr/bin/env python3
"""Create the one-time MiniTrend final-arm file after every readiness gate passes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.mini_trend.pilot_dispatcher import build_manual_arm  # noqa: E402
from qount.models import utc_now  # noqa: E402
from qount.operations import AuthorityWriterConfig  # noqa: E402
from qount.operations import authorize_minimal_live_authority_bundle  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readiness-path", required=True)
    parser.add_argument("--confirm-readiness-hash", required=True)
    parser.add_argument("--arm-token-env", default="QOUNT_MINI_TREND_ARM_TOKEN")
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--authority-root", required=True)
    parser.add_argument("--authority-source-root", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--backup-root", required=True)
    parser.add_argument("--dashboard-root", required=True)
    parser.add_argument("--authority-lock-path", required=True)
    parser.add_argument("--notification-store", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    source = Path(args.readiness_path).expanduser()
    raw = source.read_bytes()
    readiness = json.loads(raw)
    if not isinstance(readiness, dict):
        raise ValueError("readiness artifact must be a JSON object")
    token = os.getenv(args.arm_token_env)
    if token is None:
        raise ValueError(f"missing arm token environment variable: {args.arm_token_env}")
    output = Path(args.output_path).expanduser()
    if output.exists():
        raise FileExistsError(f"manual arm file already exists: {output}")
    payload = build_manual_arm(
        readiness,
        readiness_artifact_sha256=hashlib.sha256(raw).hexdigest(),
        confirmed_readiness_hash=args.confirm_readiness_hash,
        arm_token=token,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    raw_arm = output.read_bytes()
    try:
        promotion = authorize_minimal_live_authority_bundle(
            AuthorityWriterConfig(
                repo_root=REPO.resolve(),
                # The authority writer validates that this selector itself is a
                # symlink into forward/runs.  Keep the leaf symlink intact.
                source_root=Path(args.authority_source_root).expanduser().absolute(),
                authority_root=Path(args.authority_root).expanduser().resolve(),
                runtime_root=Path(args.runtime_root).expanduser().resolve(),
                backup_root=Path(args.backup_root).expanduser().resolve(),
                dashboard_root=Path(args.dashboard_root).expanduser().resolve(),
                lock_path=Path(args.authority_lock_path).expanduser().resolve(),
                notification_store_path=Path(args.notification_store)
                .expanduser()
                .resolve(),
            ),
            arm=payload,
            arm_artifact_hash=hashlib.sha256(raw_arm).hexdigest(),
            captured_at=utc_now().isoformat(),
        )
    except Exception:
        output.unlink()
        raise
    print(f"arm_path={output.resolve()}")
    print(f"arm_id={payload['arm_id']}")
    print(f"readiness_hash={payload['readiness_hash']}")
    print(f"authority_hash={promotion.authority_hash}")
    print("promotion_status=minimal_live")
    print("exchange_mutation_attempted=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
