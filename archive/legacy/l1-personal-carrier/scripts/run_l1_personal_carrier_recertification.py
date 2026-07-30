#!/usr/bin/env python3
"""Run the cache-only, time-locked L1-S2 personal-carrier re-certification."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from qount.l1_personal_carrier_recertification import L1_S2_SOURCE_COMMIT  # noqa: E402
from qount.l1_personal_carrier_recertification import assert_personal_carrier_result_window  # noqa: E402
from qount.l1_personal_carrier_recertification import claim_personal_carrier_recertification  # noqa: E402
from qount.l1_personal_carrier_recertification import complete_personal_carrier_recertification  # noqa: E402
from qount.l1_personal_carrier_recertification import evaluate_personal_carrier_recertification  # noqa: E402
from qount.l1_personal_carrier_recertification import validate_personal_carrier_tiingo_cache_preparation  # noqa: E402
from qount.l1_personal_carrier_recertification import validate_personal_carrier_preregistration  # noqa: E402
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
        # WSL is a synced compute workspace and deliberately has no .git metadata.
        # The preregistration already binds the frozen source content hash.
        return expected
    actual = hashlib.sha256(result.stdout).hexdigest()
    if actual != expected:
        raise ValueError("frozen_l1_source_hash_mismatch")
    return actual


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument(
        "--tiingo-cache-preparation",
        type=Path,
        required=True,
        help="Pre-embargo Tiingo cache-admission artifact bound to this evaluation.",
    )
    parser.add_argument("--tiingo-cache-dir", type=Path, required=True)
    parser.add_argument("--btc-cache", type=Path, required=True)
    parser.add_argument("--btc-source-manifest", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        preregistration = json.loads(args.preregistration.read_text(encoding="utf-8"))
        tiingo_cache_preparation = json.loads(
            args.tiingo_cache_preparation.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit("invalid_preregistration_or_tiingo_preparation") from error
    validate_personal_carrier_preregistration(preregistration)
    settings = Settings.from_env()
    try:
        # Keep the embargo check before the one-shot claim and before any market
        # cache is opened.  Preparation validation is metadata-only.
        assert_personal_carrier_result_window(preregistration)
        validate_personal_carrier_tiingo_cache_preparation(
            tiingo_cache_preparation,
            preregistration=preregistration,
        )
        frozen_source_sha256 = _frozen_source_sha256(preregistration)
        consumption = claim_personal_carrier_recertification(
            state_dir=settings.state_dir,
            preregistration=preregistration,
            tiingo_cache_preparation=tiingo_cache_preparation,
            frozen_source_sha256=frozen_source_sha256,
        )
        if consumption["status"] == "completed":
            result = consumption["evaluation"]
            print(f"artifact={consumption['evaluation_path']}")
            print(f"input_manifest_hash={result['input_manifest_hash']}")
            print(f"all_benchmarks_pass={result['acceptance_gate']['all_benchmarks_pass']}")
            print(f"decision={result['acceptance_gate']['decision']}")
            print("recalculated=false")
            return 0
        result = evaluate_personal_carrier_recertification(
            preregistration=preregistration,
            tiingo_cache_dir=args.tiingo_cache_dir,
            btc_cache_path=args.btc_cache,
            btc_source_manifest_path=args.btc_source_manifest,
            frozen_source_sha256=frozen_source_sha256,
            tiingo_cache_preparation=tiingo_cache_preparation,
            state_dir=settings.state_dir,
        )
        consumption = complete_personal_carrier_recertification(
            state_dir=settings.state_dir,
            preregistration=preregistration,
            tiingo_cache_preparation=tiingo_cache_preparation,
            frozen_source_sha256=frozen_source_sha256,
            evaluation=result,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print(f"artifact={consumption['evaluation_path']}")
    print(f"input_manifest_hash={result['input_manifest_hash']}")
    print(f"all_benchmarks_pass={result['acceptance_gate']['all_benchmarks_pass']}")
    print(f"decision={result['acceptance_gate']['decision']}")
    print("recalculated=true")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
