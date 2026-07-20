#!/usr/bin/env python3
"""Audit causal HMM probabilities against future market and MiniTrend base outcomes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.grid.data import load_funding, load_klines  # noqa: E402
from qount.mini_trend.forward import TOP3, frozen_top3_config  # noqa: E402
from qount.mini_trend.futures_recovery import FUTURES_RECOVERY_PROTOCOL  # noqa: E402
from qount.mini_trend.futures_recovery_backtest import run_variant  # noqa: E402
from qount.mini_trend.regime_hmm_audit import HMMAuditConfig  # noqa: E402
from qount.mini_trend.regime_hmm_audit import build_hmm_economic_audit  # noqa: E402
from qount.mini_trend.regime_hmm_audit import (  # noqa: E402
    write_hmm_economic_audit_artifact,
)
from qount.mini_trend.regime_ml import RegimeMLConfig  # noqa: E402
from qount.mini_trend.regime_ml import build_regime_ml_dataset  # noqa: E402
from qount.settings import Settings  # noqa: E402


def _month(value: str) -> tuple[int, int]:
    year, month = value.split("-", 1)
    return int(year), int(month)


def _offline_only(url: str) -> bytes:
    raise RuntimeError(f"offline cache miss; network disabled for {url.rsplit('/', 1)[-1]}")


def _normalize_rules(payload: dict) -> dict[str, dict]:
    rules = payload.get("rules", payload)
    if isinstance(rules, list):
        return {str(row["symbol"]): dict(row) for row in rules}
    if isinstance(rules, dict):
        return {str(symbol): dict(row) for symbol, row in rules.items()}
    raise ValueError("exchange rules must be a list of symbol rows or a symbol mapping")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--exchange-rules-path", required=True)
    parser.add_argument("--start-month", default="2021-01")
    parser.add_argument("--end-month", default="2026-06")
    parser.add_argument("--start-date", default="2021-07-20")
    parser.add_argument("--end-date", default="2026-05-31")
    parser.add_argument("--horizon-days", type=int, default=30)
    parser.add_argument("--barrier-sigma", type=float, default=1.0)
    parser.add_argument("--probability-bins", type=int, default=5)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--bootstrap-block-days", type=int, default=30)
    parser.add_argument("--trial-count", type=int, default=1)
    parser.add_argument("--output-path")
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
            cache_dir=args.cache_dir,
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
            cache_dir=args.cache_dir,
            fetch=_offline_only,
            skip_missing=True,
        )
        for symbol in TOP3
    }
    rules_payload = json.loads(Path(args.exchange_rules_path).read_text(encoding="utf-8"))
    rules = _normalize_rules(rules_payload)
    dataset = build_regime_ml_dataset(
        bars,
        funding,
        RegimeMLConfig(
            start_date=args.start_date,
            end_date=args.end_date,
            horizon_days=args.horizon_days,
            barrier_sigma=args.barrier_sigma,
            trial_count=args.trial_count,
        ),
    )
    base_result = run_variant(
        bars,
        funding,
        rules,
        recovery_enabled=False,
        base_config=frozen_top3_config(),
        daily_chandelier_atr_multiple=FUTURES_RECOVERY_PROTOCOL.daily_chandelier_atr_multiple,
        stop_cooldown_completed_bars=FUTURES_RECOVERY_PROTOCOL.stop_cooldown_completed_bars,
        gross_cap_policy="renormalize_active_targets_with_filter_floors",
    )
    payload = build_hmm_economic_audit(
        dataset,
        base_result,
        HMMAuditConfig(
            probability_bins=args.probability_bins,
            economic_horizon_days=args.horizon_days,
            bootstrap_block_days=args.bootstrap_block_days,
            bootstrap_samples=args.bootstrap_samples,
            trial_count=args.trial_count,
        ),
    )
    artifact = write_hmm_economic_audit_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    diagnostics = artifact["diagnostics"]
    economics = artifact["economic_conditioning"]
    print(f"artifact={artifact['artifact_path']}")
    print(f"verdict={diagnostics['verdict']}")
    print(f"gates={diagnostics['passed_gate_count']}/{diagnostics['gate_count']}")
    print(f"oos_rows={artifact['sample']['economically_aligned_rows']}")
    print(
        "risk_score_top3_spearman="
        f"{economics['risk_score_top3_return_spearman']:.8f}"
    )
    print(
        "high_minus_low_top3_return="
        f"{economics['high_minus_low_top3_return'] * 100.0:.8f}pp"
    )
    print(
        "bootstrap_positive_probability="
        f"{economics['block_bootstrap']['forward_return_horizon']['probability_spread_positive']:.6f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
