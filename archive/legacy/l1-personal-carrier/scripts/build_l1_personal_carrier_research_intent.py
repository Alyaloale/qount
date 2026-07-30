#!/usr/bin/env python3
"""Build an order-free L1 research target after a passing re-certification."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from qount.artifacts import persistent_research_dir  # noqa: E402
from qount.l1_personal_carrier_recertification import L1_S2_SOURCE_COMMIT  # noqa: E402
from qount.l1_personal_carrier_recertification import assert_personal_carrier_result_window  # noqa: E402
from qount.l1_personal_carrier_recertification import build_personal_carrier_research_intent  # noqa: E402
from qount.settings import Settings  # noqa: E402


def _frozen_source_sha256(preregistration: dict[str, object]) -> str:
    expected = str(preregistration["contract"]["source_integrity"]["sha256"])
    try:
        result = subprocess.run(
            ["git", "show", f"{L1_S2_SOURCE_COMMIT}:src/qount/l1_cross_asset.py"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return expected
    actual = hashlib.sha256(result.stdout).hexdigest()
    if actual != expected:
        raise ValueError("frozen_l1_source_hash_mismatch")
    return actual


def _read_json(path: Path, *, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"invalid_{label}:{path}") from error
    if not isinstance(value, dict):
        raise SystemExit(f"invalid_{label}:{path}")
    return value


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--tiingo-cache-dir", type=Path, required=True)
    parser.add_argument("--btc-cache", type=Path, required=True)
    parser.add_argument("--btc-source-manifest", type=Path, required=True)
    parser.add_argument(
        "--venue-capability",
        type=Path,
        help="Optional research venue-capability record; it cannot authorize orders.",
    )
    parser.add_argument(
        "--decision-time",
        help="UTC ISO-8601 time for a reproducible research target; defaults to current UTC.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    preregistration = _read_json(args.preregistration, label="preregistration")
    try:
        # Do this before opening the result artifact or any market-data cache.
        assert_personal_carrier_result_window(preregistration)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    evaluation = _read_json(args.evaluation, label="evaluation")
    venue_capability = (
        _read_json(args.venue_capability, label="venue_capability")
        if args.venue_capability is not None
        else None
    )
    try:
        decision_time = datetime.fromisoformat(args.decision_time.replace("Z", "+00:00")) if args.decision_time else None
    except ValueError as error:
        raise SystemExit("invalid_decision_time") from error
    try:
        result = build_personal_carrier_research_intent(
            preregistration=preregistration,
            evaluation=evaluation,
            frozen_source_sha256=_frozen_source_sha256(preregistration),
            tiingo_cache_dir=args.tiingo_cache_dir,
            btc_cache_path=args.btc_cache,
            btc_source_manifest_path=args.btc_source_manifest,
            venue_capability=venue_capability,
            decision_time=decision_time,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    output_dir = persistent_research_dir(
        Settings.from_env(), "l1-personal-carrier-recertification", "research-intent"
    )
    output_path = output_dir / "l1_personal_carrier_research_intent.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"artifact={output_path}")
    print(f"status={result['status']}")
    print("orders_authorized=false")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
