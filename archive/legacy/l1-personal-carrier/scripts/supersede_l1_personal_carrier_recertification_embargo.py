#!/usr/bin/env python3
"""Create an owner-directed immediate successor to the frozen L1 re-certification."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from qount.artifacts import persistent_research_dir  # noqa: E402
from qount.l1_personal_carrier_recertification import L1_S2_SOURCE_COMMIT  # noqa: E402
from qount.l1_personal_carrier_recertification import build_personal_carrier_immediate_recertification_preregistration  # noqa: E402
from qount.l1_personal_carrier_recertification import personal_carrier_strategy_version  # noqa: E402
from qount.l1_personal_carrier_recertification import validate_personal_carrier_preregistration  # noqa: E402
from qount.models import utc_now  # noqa: E402
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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--superseded-preregistration", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        superseded = json.loads(args.superseded_preregistration.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"invalid_superseded_preregistration:{args.superseded_preregistration}") from error
    if not isinstance(superseded, dict):
        raise SystemExit(f"invalid_superseded_preregistration:{args.superseded_preregistration}")
    try:
        payload = build_personal_carrier_immediate_recertification_preregistration(
            superseded_preregistration=superseded,
            l1_source_sha256=_frozen_source_sha256(superseded),
            authorized_at=utc_now(),
        )
        validate_personal_carrier_preregistration(payload)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    directory = persistent_research_dir(
        Settings.from_env(),
        "l1-personal-carrier-recertification",
        "immediate-preregistration",
    )
    path = directory / "l1_personal_carrier_immediate_recertification_preregistration.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"artifact={path}")
    print(f"contract_hash={payload['contract_hash']}")
    print(f"supersedes_contract_hash={superseded['contract_hash']}")
    print(f"not_before_utc={payload['contract']['result_controls']['not_before_utc']}")
    print(f"strategy_version={personal_carrier_strategy_version(payload)}")
    print("strategy_results_evaluated=false")
    print("paper_or_live_allowed=false")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
