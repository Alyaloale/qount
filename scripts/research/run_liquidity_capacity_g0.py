#!/usr/bin/env python3
"""Run the liquidity_capacity_meta_v1 no-PnL G0 on existing TOP3 UM daily cache."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from qount.grid.data import load_klines  # noqa: E402
from qount.mini_trend.liquidity_capacity_g0 import (  # noqa: E402
    LIQUIDITY_CAPACITY_G0_PROTOCOL,
    build_liquidity_capacity_g0_report,
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
    parser.add_argument("--exchange-rules-path", type=Path)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    protocol = LIQUIDITY_CAPACITY_G0_PROTOCOL
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
        raise RuntimeError("no kline data available for liquidity G0")
    exchange_rules = None
    if args.exchange_rules_path and args.exchange_rules_path.is_file():
        exchange_rules = json.loads(args.exchange_rules_path.read_text(encoding="utf-8"))
    observed_at = datetime.now(timezone.utc).isoformat()
    report = build_liquidity_capacity_g0_report(
        bars, available_symbols=available, exchange_rules=exchange_rules, observed_at=observed_at,
    )
    ts = observed_at.replace(":", "").replace("-", "").split(".")[0]
    out_dir = args.output_root.expanduser().resolve() / f"{ts}-liquidity-capacity-meta-g0"
    out_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    artifact_path = out_dir / "liquidity_capacity_g0.json"
    payload = json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    artifact_path.write_bytes(payload.encode("ascii"))
    print(json.dumps({
        "artifact_path": str(artifact_path),
        "verdict": report["verdict"],
        "kill_tests": report["kill_tests"],
        "rules_coverage": report["rules"]["coverage"],
        "available_symbols": available,
        "missing_symbols": report["universe"]["missing"],
        "candidate_pnl_ready": False,
        "orders_authorized": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
