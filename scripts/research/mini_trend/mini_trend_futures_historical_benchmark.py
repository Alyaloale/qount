#!/usr/bin/env python3
"""Compare the existing UM trend control with BTC and TOP3 buy-and-hold benchmarks."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.research_data.market_data import load_funding, load_klines  # noqa: E402
from qount.mini_trend.futures_historical_benchmark import build_benchmark_report  # noqa: E402
from qount.mini_trend.futures_historical_benchmark import write_benchmark_artifact  # noqa: E402
from qount.mini_trend.futures_recovery import FUTURES_RECOVERY_PROTOCOL  # noqa: E402
from qount.settings import Settings  # noqa: E402


def _month(value: str) -> tuple[int, int]:
    year, month = value[:7].split("-", 1)
    return int(year), int(month)


def _offline_only(url: str) -> bytes:
    raise RuntimeError(f"offline cache miss; network disabled for {url.rsplit('/', 1)[-1]}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-historical-path", required=True)
    parser.add_argument("--base-preregistration-path", required=True)
    parser.add_argument("--exchange-rules-path", required=True)
    parser.add_argument("--cache-dir", default="state/grid_b/klines")
    parser.add_argument("--output-path")
    return parser.parse_args(argv)


def _load_inputs(cache_dir: str) -> dict[str, dict]:
    inputs = {}
    for spec in FUTURES_RECOVERY_PROTOCOL.historical_diagnostic_windows:
        start = _month(spec["warmup_start"])
        end = _month(spec["end"])
        inputs[spec["label"]] = {
            "bars": {
                symbol: load_klines(
                    symbol, "1d", start=start, end=end, market="um", cache_dir=cache_dir,
                    fetch=_offline_only, skip_missing=True,
                )
                for symbol in ("BTCUSDT", "ETHUSDT", "BNBUSDT")
            },
            "funding": {
                symbol: load_funding(
                    symbol, start=start, end=end, cache_dir=cache_dir,
                    fetch=_offline_only, skip_missing=True,
                )
                for symbol in ("BTCUSDT", "ETHUSDT", "BNBUSDT")
            },
        }
    return inputs


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    rules = json.loads(Path(args.exchange_rules_path).read_text(encoding="utf-8"))
    payload = build_benchmark_report(
        _load_inputs(args.cache_dir),
        args.source_historical_path,
        args.base_preregistration_path,
        rules,
    )
    artifact = write_benchmark_artifact(Settings.from_env(), payload, explicit_path=args.output_path)
    print(f"artifact={artifact['artifact_path']}")
    print(f"verdict={artifact['diagnostics']['verdict']}")
    print(f"control_positive_segments={artifact['diagnostics']['control_positive_segments']}")
    print(f"control_outperformed_btc_segments={artifact['diagnostics']['control_outperformed_btc_segments']}")
    print(f"control_outperformed_top3_segments={artifact['diagnostics']['control_outperformed_top3_segments']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
