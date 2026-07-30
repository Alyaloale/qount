"""No-PnL effective-breadth G0 for the eleven SPDR sector ETFs."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from qount.contracts import canonical_hash
from qount.l3_information_edge import SupplyPoint, _panel_effective_breadth
from qount.models import utc_now


SPDR_SECTOR_ETFS = ("XLK", "XLF", "XLV", "XLE", "XLI", "XLP", "XLY", "XLU", "XLB", "XLRE", "XLC")
MINIMUM_EFFECTIVE_BREADTH = 2.0


def _aligned_daily_returns(series_by_ticker: Mapping[str, Sequence[SupplyPoint]]) -> tuple[list[int], dict[str, list[float]]]:
    by_ticker = {ticker: {row.timestamp_ms: row.value for row in rows} for ticker, rows in series_by_ticker.items()}
    if set(by_ticker) != set(SPDR_SECTOR_ETFS):
        raise ValueError("SPDR sector universe must be exact")
    common = sorted(set.intersection(*(set(values) for values in by_ticker.values())))
    if len(common) < 2:
        raise ValueError("SPDR sector panel has insufficient common adjusted-close history")
    returns: dict[str, list[float]] = {}
    for ticker, values in by_ticker.items():
        closes = [values[stamp] for stamp in common]
        if any(value <= 0.0 for value in closes):
            raise ValueError(f"SPDR sector panel has invalid adjusted close for {ticker}")
        returns[ticker] = [closes[index] / closes[index - 1] - 1.0 for index in range(1, len(closes))]
    return common, returns


def build_spdr_sector_breadth_report(
    series_by_ticker: Mapping[str, Sequence[SupplyPoint]], *, cache_manifest: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    common_dates, return_panel = _aligned_daily_returns(series_by_ticker)
    breadth = _panel_effective_breadth(return_panel)
    value = float(breadth["effective_breadth"])
    verdict = "pass_to_simple_momentum_preregistration" if value >= MINIMUM_EFFECTIVE_BREADTH else "downgrade_to_sector_vs_broad_binary_timing"
    contract = {
        "universe": list(SPDR_SECTOR_ETFS),
        "price_field": "Tiingo adjusted close",
        "frequency": "daily",
        "minimum_effective_breadth": MINIMUM_EFFECTIVE_BREADTH,
        "effective_breadth_formula": "N / (1 + (N - 1) * mean_abs_pairwise_daily_return_correlation)",
        "result_actions": {
            "below_threshold": "downgrade_to_sector_vs_broad_binary_timing",
            "at_or_above_threshold": "allow_simple_non_ml_momentum_preregistration_only",
        },
    }
    return {
        "schema_version": "spdr_sector_effective_breadth_g0_v0.1",
        "artifact_type": "spdr_sector_effective_breadth_g0",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "pnl_evaluated": False,
            "ml_allowed": False,
            "orders_authorized": False,
            "paper_or_live_allowed": False,
        },
        "contract": contract,
        "contract_hash": canonical_hash(contract),
        "data": {
            "common_adjusted_close_count": len(common_dates),
            "common_first_timestamp_ms": common_dates[0],
            "common_last_timestamp_ms": common_dates[-1],
            "cache_manifest": [dict(row) for row in cache_manifest],
        },
        "breadth": breadth,
        "verdict": verdict,
    }
