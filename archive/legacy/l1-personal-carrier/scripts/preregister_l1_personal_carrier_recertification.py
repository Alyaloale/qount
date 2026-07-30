#!/usr/bin/env python3
"""Write the result-free L1-S2 personal-carrier re-certification contract."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from qount.artifacts import persistent_research_dir  # noqa: E402
from qount.l1_personal_carrier_recertification import L1_S2_SOURCE_COMMIT  # noqa: E402
from qount.l1_personal_carrier_recertification import build_personal_carrier_preregistration  # noqa: E402
from qount.l1_personal_carrier_recertification import validate_personal_carrier_preregistration  # noqa: E402
from qount.settings import Settings  # noqa: E402


def _frozen_source_sha256() -> str:
    result = subprocess.run(
        ["git", "show", f"{L1_S2_SOURCE_COMMIT}:src/qount/l1_cross_asset.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return hashlib.sha256(result.stdout).hexdigest()


def main() -> int:
    payload = build_personal_carrier_preregistration(l1_source_sha256=_frozen_source_sha256())
    validate_personal_carrier_preregistration(payload)
    directory = persistent_research_dir(Settings.from_env(), "l1-personal-carrier-recertification", "preregistration")
    path = directory / "l1_personal_carrier_recertification_preregistration.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"artifact={path}")
    print(f"contract_hash={payload['contract_hash']}")
    print("strategy_results_evaluated=false")
    print("not_before_utc=2026-07-31T00:00:00+00:00")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
