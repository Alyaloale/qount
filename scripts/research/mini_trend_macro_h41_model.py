#!/usr/bin/env python3
"""Run the fixed three-feature Federal Reserve H.4.1 economic audit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.grid.data import load_funding, load_klines  # noqa: E402
from qount.mini_trend.forward import TOP3  # noqa: E402
from qount.mini_trend.macro_h41_model import H41FeatureAuditConfig  # noqa: E402
from qount.mini_trend.macro_h41_model import build_h41_feature_audit  # noqa: E402
from qount.mini_trend.macro_h41_model import write_h41_feature_audit_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


def _month(value: str) -> tuple[int, int]:
    year, month = value.split("-", 1)
    return int(year), int(month)


def _offline_only(url: str) -> bytes:
    raise RuntimeError(f"offline cache miss; network disabled for {url.rsplit('/', 1)[-1]}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market-cache-dir", required=True)
    parser.add_argument("--h41-dataset", required=True)
    parser.add_argument("--start-month", default="2021-01")
    parser.add_argument("--end-month", default="2026-06")
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    start, end = _month(args.start_month), _month(args.end_month)
    bars = {
        symbol: load_klines(
            symbol,
            "1d",
            start=start,
            end=end,
            market="um",
            cache_dir=args.market_cache_dir,
            fetch=_offline_only,
            skip_missing=True,
        )
        for symbol in TOP3
    }
    funding = {
        symbol: load_funding(
            symbol,
            start=start,
            end=end,
            cache_dir=args.market_cache_dir,
            fetch=_offline_only,
            skip_missing=True,
        )
        for symbol in TOP3
    }
    h41_dataset = json.loads(Path(args.h41_dataset).expanduser().read_text(encoding="utf-8"))
    payload = build_h41_feature_audit(
        bars,
        funding,
        h41_dataset,
        H41FeatureAuditConfig(bootstrap_samples=args.bootstrap_samples),
    )
    artifact = write_h41_feature_audit_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    diagnostics = artifact["diagnostics"]
    print(f"artifact={artifact['artifact_path']}")
    print(f"verdict={diagnostics['verdict']}")
    print(f"trial_count={diagnostics['trial_count']}")
    print(f"cumulative_trial_count={diagnostics['cumulative_trial_count']}")
    control = artifact["control"]
    print(
        f"control_rank_ic={control['pooled_rank_ic']:.8f} "
        f"control_spread={control['pooled_high_minus_low_actual']:.8f} "
        f"control_bootstrap={control['bootstrap']['probability_spread_positive']:.6f}"
    )
    for trial in artifact["trials"]:
        comparison = trial["comparison"]
        print(
            f"trial={trial['trial_id']} rank_ic={trial['pooled_rank_ic']:.8f} "
            f"spread={trial['pooled_high_minus_low_actual']:.8f} "
            f"bootstrap={trial['bootstrap']['probability_spread_positive']:.6f} "
            f"rank_ic_delta={comparison['pooled_rank_ic_delta']:.8f} "
            f"spread_delta={comparison['pooled_spread_delta']:.8f} "
            f"gates={trial['passed_gate_count']}/{trial['gate_count']} "
            f"verdict={trial['verdict']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
