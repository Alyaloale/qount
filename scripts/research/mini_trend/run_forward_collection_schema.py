#!/usr/bin/env python3
"""Write the forward append-only collection schema artifact for Wave 3 families."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from qount.mini_trend.forward_collection_schema import build_forward_schema_report  # noqa: E402


DEFAULT_OUTPUT_ROOT = ROOT / "state" / "research_runs"


def main() -> int:
    observed_at = datetime.now(timezone.utc).isoformat()
    report = build_forward_schema_report(observed_at)
    ts = observed_at.replace(":", "").replace("-", "").split(".")[0]
    out_dir = Path(DEFAULT_OUTPUT_ROOT) / f"{ts}-forward-collection-schema"
    out_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    artifact_path = out_dir / "forward_collection_schema.json"
    payload = json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    artifact_path.write_bytes(payload.encode("ascii"))
    print(json.dumps({
        "artifact_path": str(artifact_path),
        "families": [c["family"] for c in report["contracts"]],
        "all_verdicts": "continue_collection",
        "read_results_before_window": False,
        "candidate_pnl_ready": False,
        "orders_authorized": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
