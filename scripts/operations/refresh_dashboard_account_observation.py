#!/usr/bin/env python3
"""Refresh the Dashboard's private account observation without order authority."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Sequence

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.contracts import canonical_hash  # noqa: E402
from qount.mini_trend.pilot_preflight import build_pilot_account_preflight  # noqa: E402
from qount.operations.authority_writer import _readonly_account_observation  # noqa: E402
from qount.settings import Settings  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-path", type=Path, required=True)
    return parser


def _write(path: Path, payload: dict[str, object]) -> None:
    if path.exists() and path.is_symlink():
        raise ValueError("dashboard_account_observation_output_symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    encoded = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii") + b"\n"
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    preflight = build_pilot_account_preflight(Settings.from_env())
    observed_at = str(preflight["created_at"])
    observation = _readonly_account_observation(preflight, observed_at)
    if observation is None:
        raise ValueError("dashboard_account_observation_unavailable")
    preflight_hash = canonical_hash(preflight)
    core: dict[str, object] = {
        "schema_version": 1,
        "artifact_type": "qount_blocked_runtime_observation",
        "created_at": observed_at,
        "observed_at": observed_at,
        "status": "blocked",
        "live_orders_allowed": False,
        "runtime_ledger_created": False,
        "strategy_id": "dashboard_readonly_account_observer",
        "blockers": ["private_account_observation_only"],
        "run_id": f"dashboard-account-observer-{preflight_hash[:16]}",
        "source_hashes": {"account_preflight": preflight_hash},
        "account_observation": observation,
    }
    payload = core | {"observation_hash": canonical_hash(core)}
    _write(args.output_path, payload)
    print(f"observation_hash={payload['observation_hash']}")
    print("private_api_order_attempted=false")
    print("live_orders_allowed=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
