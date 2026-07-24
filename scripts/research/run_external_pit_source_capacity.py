#!/usr/bin/env python3
"""Write the external PIT source-capacity audit artifact for Wave 4 families."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from qount.mini_trend.external_pit_source_capacity import build_external_pit_source_capacity_report  # noqa: E402


DEFAULT_OUTPUT_ROOT = ROOT / "state" / "research_runs"


def main() -> int:
    observed_at = datetime.now(timezone.utc).isoformat()
    report = build_external_pit_source_capacity_report(observed_at)
    ts = observed_at.replace(":", "").replace("-", "").split(".")[0]
    out_dir = Path(DEFAULT_OUTPUT_ROOT) / f"{ts}-external-pit-source-capacity"
    out_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    artifact_path = out_dir / "external_pit_source_capacity.json"
    payload = json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    artifact_path.write_bytes(payload.encode("ascii"))
    print(json.dumps({
        "artifact_path": str(artifact_path),
        "families": [f["family"] for f in report["families"]],
        "selected_for_g0": report["selected_for_g0"],
        "candidate_pnl_ready": False,
        "orders_authorized": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
