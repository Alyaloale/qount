#!/usr/bin/env python3
"""Explain the retired X4 headline return using existing local BTC/TOP3 caches only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.research_data.market_data import load_funding, load_klines  # noqa: E402
from qount.mini_trend.forward import TOP3  # noqa: E402
from qount.mini_trend.high_return_attribution import build_high_return_attribution  # noqa: E402
from qount.mini_trend.high_return_attribution import write_high_return_attribution_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


def _offline_only(url: str) -> bytes:
    raise RuntimeError(f"offline cache miss; network disabled for {url.rsplit('/', 1)[-1]}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exchange-rules-path", required=True)
    parser.add_argument("--live-lessons-path", required=True)
    parser.add_argument("--cache-dir", default="state/grid_b/klines")
    parser.add_argument("--output-path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    bars_1d = {
        symbol: load_klines(
            symbol,
            "1d",
            start=(2021, 1),
            end=(2026, 5),
            market="um",
            cache_dir=args.cache_dir,
            fetch=_offline_only,
            skip_missing=True,
        )
        for symbol in TOP3
    }
    btc_1h = load_klines(
        "BTCUSDT",
        "1h",
        start=(2021, 1),
        end=(2026, 5),
        market="um",
        cache_dir=args.cache_dir,
        fetch=_offline_only,
        skip_missing=True,
    )
    funding = {
        symbol: load_funding(
            symbol,
            start=(2021, 1),
            end=(2026, 5),
            cache_dir=args.cache_dir,
            fetch=_offline_only,
            skip_missing=True,
        )
        for symbol in TOP3
    }
    payload = build_high_return_attribution(
        bars_1d,
        btc_1h,
        funding,
        json.loads(Path(args.exchange_rules_path).read_text(encoding="utf-8")),
        json.loads(Path(args.live_lessons_path).read_text(encoding="utf-8")),
    )
    artifact = write_high_return_attribution_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    print(f"artifact={artifact['artifact_path']}")
    print(f"verdict={artifact['diagnostics']['verdict']}")
    for strategy in ("s3_cta", "s4_mom"):
        row = artifact["funding_and_friction_correction"][strategy]
        print(
            f"{strategy}_corrected_return_pct="
            f"{row['all_daily_settlements']['total_return_pct']:.8f}"
        )
        print(
            f"{strategy}_funding_undercount_inflation_pp="
            f"{row['headline_inflation_from_funding_undercount_pp']:.8f}"
        )
    print(
        "current_um_base_return_pct="
        f"{artifact['current_um_base']['metrics']['return_pct']:.8f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
