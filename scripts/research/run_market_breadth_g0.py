#!/usr/bin/env python3
"""Run the market_breadth_dispersion_v1 no-PnL G0 on existing TOP3 UM daily cache."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from qount.contracts import canonical_hash  # noqa: E402
from qount.grid.data import load_klines  # noqa: E402
from qount.mini_trend.liquid_trend import LIQUID_TREND_UNIVERSE  # noqa: E402
from qount.mini_trend.market_breadth_g0 import (  # noqa: E402
    MARKET_BREADTH_G0_PROTOCOL,
    build_market_breadth_g0_report,
)


DEFAULT_KLINE_CACHE = ROOT / "state" / "r0_runtime" / "klines"
DEFAULT_OUTPUT_ROOT = ROOT / "state" / "research_runs"


def _offline_only(url: str) -> bytes:
    raise RuntimeError(f"offline cache miss; network disabled for {url.rsplit('/', 1)[-1]}")


def _month(value: str) -> tuple[int, int]:
    year, month = value.split("-", 1)
    return int(year), int(month)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kline-cache", type=Path, default=DEFAULT_KLINE_CACHE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    protocol = MARKET_BREADTH_G0_PROTOCOL
    start = _month(protocol.start_month)
    end = _month(protocol.end_month)
    available: list[str] = []
    bars: dict[str, list] = {}
    for symbol in protocol.target_universe:
        try:
            rows = load_klines(
                symbol, protocol.interval, start=start, end=end, market=protocol.market,
                cache_dir=str(args.kline_cache), fetch=_offline_only, skip_missing=True,
            )
        except (FileNotFoundError, RuntimeError):
            rows = []
        if rows:
            available.append(symbol)
            bars[symbol] = rows
    if not bars:
        raise RuntimeError("no kline data available for breadth G0")
    observed_at = datetime.now(timezone.utc).isoformat()
    report = build_market_breadth_g0_report(
        bars, available_symbols=available, observed_at=observed_at,
    )
    ts = observed_at.replace(":", "").replace("-", "").split(".")[0]
    out_dir = args.output_root.expanduser().resolve() / f"{ts}-market-breadth-dispersion-g0"
    out_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    artifact_path = out_dir / "market_breadth_g0.json"
    payload = json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    artifact_path.write_bytes(payload.encode("ascii"))
    print(json.dumps({
        "artifact_path": str(artifact_path),
        "verdict": report["verdict"],
        "kill_tests": report["kill_tests"],
        "available_symbols": available,
        "missing_symbols": report["universe"]["missing"],
        "effective_breadth": report["breadth"]["effective_breadth"] if report["breadth"] else None,
        "pc1_share": report["breadth"]["first_principal_component_share"] if report["breadth"] else None,
        "candidate_pnl_ready": False,
        "orders_authorized": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
