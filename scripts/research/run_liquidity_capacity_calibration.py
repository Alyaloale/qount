#!/usr/bin/env python3
"""Calibrate liquidity_capacity_meta_v1 execution cost/capacity from a frozen G0.

Consumes a passing ``liquidity_capacity_g0.json`` artifact (verdict
``pass_to_capacity_calibration``), binds its SHA-256, and writes an immutable
capacity/cost scorecard. Produces no direction, alpha or PnL; orders_authorized
stays false.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from qount.mini_trend.liquidity_capacity_calibration import (  # noqa: E402
    build_calibration_scorecard,
)


DEFAULT_OUTPUT_ROOT = ROOT / "state" / "research_runs"


def _latest_g0(output_root: Path) -> Path | None:
    candidates = sorted(output_root.glob("*-liquidity-capacity-meta-g0"))
    for path in reversed(candidates):
        artifact = path / "liquidity_capacity_g0.json"
        if artifact.is_file():
            return artifact
    return None


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--g0-artifact",
        type=Path,
        help="Path to liquidity_capacity_g0.json; defaults to newest passing G0.",
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    output_root = args.output_root.expanduser().resolve()
    g0_path = args.g0_artifact
    if g0_path is None:
        g0_path = _latest_g0(output_root)
        if g0_path is None:
            raise RuntimeError(f"no liquidity G0 artifact found under {output_root}")
    g0_path = g0_path.expanduser().resolve()

    raw = g0_path.read_bytes()
    g0_artifact_hash = hashlib.sha256(raw).hexdigest()
    g0 = json.loads(raw.decode("ascii"))
    verdict = g0.get("verdict")
    liquidity = g0.get("liquidity", {})
    available = list(g0.get("universe", {}).get("available", []))

    observed_at = datetime.now(timezone.utc).isoformat()
    scorecard = build_calibration_scorecard(
        liquidity,
        available_symbols=available,
        g0_artifact_hash=g0_artifact_hash,
        g0_verdict=verdict,
        observed_at=observed_at,
    )
    scorecard["g0_input"]["g0_artifact_path"] = str(g0_path)

    ts = observed_at.replace(":", "").replace("-", "").split(".")[0]
    out_dir = output_root / f"{ts}-liquidity-capacity-meta-calibration"
    out_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    artifact_path = out_dir / "liquidity_capacity_calibration.json"
    payload = json.dumps(scorecard, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    artifact_path.write_bytes(payload.encode("ascii"))
    artifact_path.chmod(0o600)

    part = scorecard["universe_capacity_participation_only"]
    print(json.dumps({
        "artifact_path": str(artifact_path),
        "g0_artifact_hash": g0_artifact_hash,
        "g0_verdict": verdict,
        "symbols_calibrated": scorecard["g0_input"]["symbols_calibrated"],
        "universe_participation_capacity_usdt": part["equal_weight_universe_capacity_usdt"],
        "participation_binding_symbol": part["min_participation_symbol"],
        "cs_spread_overstated_symbols": scorecard["cost_error"]["cs_spread_overstated_symbols"],
        "candidate_pnl_ready": False,
        "orders_authorized": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
