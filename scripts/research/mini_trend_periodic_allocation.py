#!/usr/bin/env python3
"""Compare periodic allocation and causal action labels on cached crypto/SPY history."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.grid.data import Funding, load_funding, load_klines  # noqa: E402
from qount.l1_cross_asset import normalize_tiingo_eod  # noqa: E402
from qount.mini_trend.backtest import align_bars  # noqa: E402
from qount.mini_trend.forward import TOP3  # noqa: E402
from qount.mini_trend.periodic_allocation import AssetSeries  # noqa: E402
from qount.mini_trend.periodic_allocation import (  # noqa: E402
    build_periodic_allocation_report,
    write_periodic_allocation_artifact,
)
from qount.settings import Settings  # noqa: E402


_DAY_MS = 86_400_000


def _offline_only(url: str) -> bytes:
    raise RuntimeError(f"offline cache miss; network disabled for {url.rsplit('/', 1)[-1]}")


def _month(value: str) -> tuple[int, int]:
    year, month = value[:7].split("-", 1)
    return int(year), int(month)


def _funding_sum(rows: list[Funding], start_ms: int, end_ms: int) -> float:
    return sum(row.rate for row in rows if start_ms < row.ts_ms <= end_ms)


def _crypto_series(cache_dir: str, start: str, end: str) -> dict[str, AssetSeries]:
    bars = align_bars(
        {
            symbol: load_klines(
                symbol,
                "1d",
                start=_month(start),
                end=_month(end),
                market="um",
                cache_dir=cache_dir,
                fetch=_offline_only,
            )
            for symbol in TOP3
        },
        TOP3,
    )
    funding = {
        symbol: load_funding(
            symbol,
            start=_month(start),
            end=_month(end),
            cache_dir=cache_dir,
            fetch=_offline_only,
        )
        for symbol in TOP3
    }
    dates = tuple(row.date for row in bars["BTCUSDT"])
    top3_closes = [1.0]
    for index in range(1, len(dates)):
        daily = [
            bars[symbol][index].close / bars[symbol][index - 1].close - 1.0
            for symbol in TOP3
        ]
        top3_closes.append(top3_closes[-1] * (1.0 + sum(daily) / len(daily)))
    top3_funding = []
    btc_funding = []
    for index in range(len(dates) - 1):
        start_ms = bars["BTCUSDT"][index].ts_ms + _DAY_MS
        end_ms = bars["BTCUSDT"][index + 1].ts_ms + _DAY_MS
        values = [
            _funding_sum(funding[symbol], start_ms, end_ms) for symbol in TOP3
        ]
        top3_funding.append(sum(values) / len(values))
        btc_funding.append(values[0])
    return {
        "btc_um": AssetSeries(
            asset_id="btc_um",
            dates=dates,
            closes=tuple(float(row.close) for row in bars["BTCUSDT"]),
            funding_returns=tuple(btc_funding),
            periods_per_year=365.0,
            decision_stride=7,
            allocation_step=0.25,
            turnover_cost_bps=12.0,
        ),
        "crypto_top3_um_equal_weight": AssetSeries(
            asset_id="crypto_top3_um_equal_weight",
            dates=dates,
            closes=tuple(top3_closes),
            funding_returns=tuple(top3_funding),
            periods_per_year=365.0,
            decision_stride=7,
            allocation_step=0.50,
            turnover_cost_bps=12.0,
        ),
    }


def _spy_series(path: str | Path) -> AssetSeries:
    raw = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    points = normalize_tiingo_eod(raw)
    dates = tuple(
        dt.datetime.fromtimestamp(point.timestamp_ms / 1000, dt.UTC).date().isoformat()
        for point in points
    )
    closes = tuple(float(point.value) for point in points)
    return AssetSeries(
        asset_id="spy_adjusted",
        dates=dates,
        closes=closes,
        funding_returns=tuple(0.0 for _ in range(len(closes) - 1)),
        periods_per_year=252.0,
        decision_stride=5,
        allocation_step=0.25,
        turnover_cost_bps=10.0,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--crypto-cache-dir", required=True)
    parser.add_argument("--spy-path", required=True)
    parser.add_argument("--start-month", default="2021-01")
    parser.add_argument("--end-month", default="2026-05")
    parser.add_argument("--output-path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    series = _crypto_series(
        args.crypto_cache_dir,
        args.start_month,
        args.end_month,
    )
    series["spy_adjusted"] = _spy_series(args.spy_path)
    payload = build_periodic_allocation_report(series)
    artifact = write_periodic_allocation_artifact(
        Settings.from_env(),
        payload,
        explicit_path=args.output_path,
    )
    print(f"artifact={artifact['artifact_path']}")
    for asset_id, asset in artifact["assets"].items():
        line = asset["full_history_policies"]["line_dca_dcr"]["metrics"]
        buy_hold = asset["full_history_policies"]["buy_hold"]["metrics"]
        print(
            f"asset={asset_id} line_return={line['return_pct']}% "
            f"line_sharpe={line['sharpe']} line_maxdd={line['max_drawdown_pct']}% "
            f"buy_hold_return={buy_hold['return_pct']}%"
        )
        for model_name, model in asset["models"].items():
            pooled = model["pooled"]
            policy = asset["walk_forward_policies"][f"ml_{model_name}_dca_dcr"]["metrics"]
            print(
                f"asset={asset_id} model={model_name} "
                f"brier_uplift={pooled['mean_brier_uplift_vs_constant']} "
                f"policy_return={policy['return_pct']}% policy_sharpe={policy['sharpe']}"
            )
    print("paper_or_live_allowed=False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
