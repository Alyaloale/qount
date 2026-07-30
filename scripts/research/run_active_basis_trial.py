#!/usr/bin/env python3
"""Run the frozen research-only active positive-basis trial."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.contracts import canonical_hash  # noqa: E402
from qount.research.active_basis import (  # noqa: E402
    build_daily_basis_series,
    evaluate_active_basis,
    protocol,
)
from qount.grid.data import load_funding, load_klines  # noqa: E402


DEFAULT_CACHE_ROOT = REPO / "state" / "r0_runtime"
DEFAULT_OUTPUT_ROOT = REPO / "state" / "research_runs"


def _month(value: str) -> tuple[int, int]:
    year, month = value[:7].split("-", 1)
    return int(year), int(month)


def _offline(_url: str) -> bytes:
    raise RuntimeError("active_basis_trial_offline_cache_miss")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _archive_inventory(cache_root: Path, symbol: str, start: str, end: str) -> list[dict[str, Any]]:
    start_year, start_month = _month(start)
    end_year, end_month = _month(end)
    inventory: list[dict[str, Any]] = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        for path in (
            cache_root / "klines" / f"{symbol}-1d-{year:04d}-{month:02d}.zip",
            cache_root / "klines" / f"um-{symbol}-1d-{year:04d}-{month:02d}.zip",
            cache_root / "funding" / f"{symbol}-fundingRate-{year:04d}-{month:02d}.zip",
        ):
            if path.is_file():
                inventory.append(
                    {
                        "path": str(path.relative_to(REPO)),
                        "size_bytes": path.stat().st_size,
                        "sha256": _sha256(path),
                    }
                )
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return inventory


def _write_once(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=True, allow_nan=False, sort_keys=True, indent=2).encode("ascii") + b"\n"
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-06-30")
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    start_month = _month(args.start)
    end_month = _month(args.end)
    symbol = str(args.symbol).upper()
    if args.output_dir is None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output_dir = DEFAULT_OUTPUT_ROOT / f"{stamp}-{symbol.lower()}-active-basis-trial-1"
    else:
        output_dir = args.output_dir

    protocol_payload = protocol()
    preregistration = {
        **protocol_payload,
        "contract_hash": canonical_hash(protocol_payload),
        "registered_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "data_role": "consumed_historical_discovery_pool",
    }
    _write_once(output_dir / "preregistration.json", preregistration)

    spot = load_klines(
        symbol,
        "1d",
        start=start_month,
        end=end_month,
        market="spot",
        cache_dir=str(args.cache_root / "klines"),
        fetch=_offline,
    )
    perp = load_klines(
        symbol,
        "1d",
        start=start_month,
        end=end_month,
        market="um",
        cache_dir=str(args.cache_root / "klines"),
        fetch=_offline,
    )
    funding = load_funding(
        symbol,
        start=start_month,
        end=end_month,
        cache_dir=str(args.cache_root / "funding"),
        fetch=_offline,
    )
    series = build_daily_basis_series(spot, perp, funding)
    report = evaluate_active_basis(series, symbol=symbol)
    report["preregistration_contract_hash"] = preregistration["contract_hash"]
    report["source_inventory"] = _archive_inventory(args.cache_root, symbol, args.start, args.end)
    report["source_inventory_hash"] = canonical_hash({"files": report["source_inventory"]})
    report["code_hash"] = canonical_hash(
        {
            "active_basis_py": _sha256(REPO / "src" / "qount" / "research" / "active_basis.py"),
            "runner_py": _sha256(Path(__file__).resolve()),
        }
    )
    report["result_hash"] = canonical_hash({key: value for key, value in report.items() if key != "result_hash"})
    _write_once(output_dir / "result.json", report)
    print(json.dumps({
        "output_dir": str(output_dir),
        "contract_hash": report["contract_hash"],
        "result_hash": report["result_hash"],
        "verdict": report["verdict"],
        "bar_count": report["series"]["bar_count"],
        "active": report["active"],
        "funding_only_baseline": report["funding_only_baseline"],
        "static_positive_carry_baseline": report["static_positive_carry_baseline"],
        "kill_gates": report["kill_gates"],
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
