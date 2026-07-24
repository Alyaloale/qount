"""No-PnL G0 for ``market_breadth_dispersion_v1``.

Outputs trend-health state only: advance ratio, residual dispersion, first
principal component share, correlation clusters, BTC down-day conditional
correlation and segment stability. It does NOT produce direction, PnL or a
strategy signal. Kill tests fire before any PnL read: breadth below the
pre-registered floor, equivalence to BTC beta, single-year concentration, or
non-reconstructable PIT universe.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from qount.contracts import canonical_hash
from qount.grid.data import Bar
from qount.mini_trend.liquid_trend import (
    LIQUID_TREND_UNIVERSE,
    _correlation_clusters,
    _edge_jaccard,
    _return_panel,
    _segment_breadth,
    effective_breadth,
)


MARKET_BREADTH_G0_VERSION = "market_breadth_dispersion_g0_v0.1"
MARKET_BREADTH_FAMILY = "market_breadth_dispersion_v1"


@dataclass(frozen=True)
class MarketBreadthG0Protocol:
    hypothesis_family: str = MARKET_BREADTH_FAMILY
    candidate_id: str = "market_breadth_dispersion_state_v0"
    trial_number_within_family: int = 0
    family_trial_budget: int = 3
    target_universe: tuple[str, ...] = LIQUID_TREND_UNIVERSE
    benchmark: str = "BTCUSDT"
    interval: str = "1d"
    market: str = "um"
    start_month: str = "2020-02"
    end_month: str = "2026-06"
    trend_lookback: int = 60
    cluster_abs_correlation: float = 0.6
    minimum_effective_breadth: float = 2.0
    maximum_pc1_share_for_independence: float = 0.85
    minimum_segment_count_for_stability: int = 2
    output_role: str = "state_only_no_direction_no_pnl"

    @property
    def contract_basis(self) -> dict[str, Any]:
        return {
            "hypothesis_family": self.hypothesis_family,
            "candidate_id": self.candidate_id,
            "trial_number_within_family": self.trial_number_within_family,
            "family_trial_budget": self.family_trial_budget,
            "data": {
                "market": self.market,
                "interval": self.interval,
                "target_universe": list(self.target_universe),
                "benchmark": self.benchmark,
                "start_month": self.start_month,
                "end_month": self.end_month,
                "data_role": "consumed_historical_discovery_pool",
                "existing_cache_only": True,
            },
            "features": {
                "advance_ratio": "fraction of universe with positive daily return",
                "trend_distance": "abs(close - sma60) / close cross-sectional distribution",
                "residual_dispersion": "cross-sectional stdev of BTC-beta-residual returns",
                "first_principal_component_share": "PC1 / sum(eigenvalues)",
                "effective_breadth": "N / (1 + (N-1)*mean_abs_corr)",
                "correlation_clusters": "union-find at abs_corr >= 0.6",
                "downside_conditional_correlation": "breadth on BTC down days only",
                "segment_stability": "high-corr edge Jaccard vs full window",
            },
            "output_role": self.output_role,
            "kill_tests": {
                "effective_breadth_below_floor": f"effective_breadth < {self.minimum_effective_breadth}",
                "equivalent_to_btc_beta": f"PC1 share > {self.maximum_pc1_share_for_independence:.2f}",
                "single_year_concentration": "fewer than 2 segments with finite breadth",
                "pit_universe_not_reconstructable": "target universe symbols missing from cache",
            },
            "candidate_pnl_ready": False,
            "promotion_evidence": False,
            "orders_authorized": False,
        }

    @property
    def contract_hash(self) -> str:
        return canonical_hash(self.contract_basis)


MARKET_BREADTH_G0_PROTOCOL = MarketBreadthG0Protocol()


def _bars_by_date(bars: Mapping[str, Sequence[Bar]]) -> tuple[dict[str, dict[str, Bar]], list[str]]:
    dates_by_symbol = {
        symbol: {bar.date: bar for bar in rows} for symbol, rows in bars.items()
    }
    common = sorted(
        set.intersection(*(set(d.keys()) for d in dates_by_symbol.values()))
        if dates_by_symbol
        else set()
    )
    return dates_by_symbol, common


def _advance_ratio(panel: Mapping[str, Sequence[float]]) -> list[float]:
    if not panel:
        return []
    length = min(len(v) for v in panel.values())
    ratios: list[float] = []
    for index in range(length):
        positive = sum(1.0 for values in panel.values() if values[index] > 0.0)
        ratios.append(positive / len(panel))
    return ratios


def _trend_distance(
    bars_by_date: Mapping[str, Mapping[str, Bar]],
    dates: Sequence[str],
    lookback: int,
) -> dict[str, Any]:
    distances: list[float] = []
    for symbol in bars_by_date:
        indexed = bars_by_date[symbol]
        for index in range(lookback, len(dates)):
            bar = indexed[dates[index]]
            window = [indexed[dates[index - offset]].close for offset in range(1, lookback + 1)]
            sma = statistics.mean(window)
            if bar.close > 0.0:
                distances.append(abs(bar.close - sma) / bar.close)
    if not distances:
        return {"count": 0, "median": None, "p90": None, "mean": None}
    distances.sort()
    return {
        "count": len(distances),
        "median": statistics.median(distances),
        "p90": distances[int(0.9 * len(distances))] if distances else None,
        "mean": statistics.mean(distances),
    }


def _residual_dispersion(
    panel: Mapping[str, Sequence[float]], benchmark: Sequence[float]
) -> dict[str, Any]:
    bench_mean = statistics.mean(benchmark) if benchmark else 0.0
    bench_var = sum((v - bench_mean) ** 2 for v in benchmark) if benchmark else 0.0
    dispersions: list[float] = []
    for symbol, returns in panel.items():
        if symbol == "BTCUSDT" or bench_var <= 0.0 or len(returns) != len(benchmark):
            continue
        sym_mean = statistics.mean(returns)
        beta = sum((r - sym_mean) * (b - bench_mean) for r, b in zip(returns, benchmark)) / bench_var
        residuals = [r - beta * b for r, b in zip(returns, benchmark)]
        if len(residuals) > 1:
            dispersions.append(statistics.stdev(residuals))
    if not dispersions:
        return {"count": 0, "median": None, "mean": None}
    return {
        "count": len(dispersions),
        "median": statistics.median(dispersions),
        "mean": statistics.mean(dispersions),
    }


def build_market_breadth_g0_report(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    *,
    available_symbols: Sequence[str],
    observed_at: str,
) -> dict[str, Any]:
    protocol = MARKET_BREADTH_G0_PROTOCOL
    bars_by_date, common_dates = _bars_by_date(bars_by_symbol)
    universe_gap = sorted(set(protocol.target_universe) - set(available_symbols))
    universe_coverage = len(available_symbols) / len(protocol.target_universe)
    panel = _return_panel(bars_by_date, common_dates) if common_dates else {}

    if panel and "BTCUSDT" in panel:
        full_breadth = effective_breadth(panel)
    else:
        full_breadth = None

    advance_ratios = _advance_ratio(panel)
    advance_ratio_summary = {
        "mean": statistics.mean(advance_ratios) if advance_ratios else None,
        "median": statistics.median(advance_ratios) if advance_ratios else None,
        "count": len(advance_ratios),
    }
    trend_distance = _trend_distance(bars_by_date, common_dates, protocol.trend_lookback)
    residual_dispersion = (
        _residual_dispersion(panel, panel["BTCUSDT"])
        if panel and "BTCUSDT" in panel
        else {"count": 0, "median": None, "mean": None}
    )

    if full_breadth:
        clusters = _correlation_clusters(
            tuple(available_symbols), full_breadth["pairs"], protocol.cluster_abs_correlation
        )
        downside_indices = [
            i for i, v in enumerate(panel.get("BTCUSDT", [])) if v < 0.0
        ]
        downside_panel = {
            symbol: [values[i] for i in downside_indices]
            for symbol, values in panel.items()
        }
        downside_breadth = (
            effective_breadth(downside_panel) if len(downside_indices) >= 2 else None
        )
        full_high_corr_edges = sorted(
            [str(row["left"]), str(row["right"])]
            for row in full_breadth["pairs"]
            if float(row["absolute_correlation"]) >= protocol.cluster_abs_correlation
        )
        segments = [
            {
                "label": label,
                **_segment_breadth(
                    bars_by_date, common_dates, start, end, protocol.cluster_abs_correlation,
                ),
            }
            for label, start, end in (
                ("2020-2021", "2020-02-10", "2021-12-31"),
                ("2022-2023", "2022-01-01", "2023-12-31"),
                ("2024-2026", "2024-01-01", "2026-06-30"),
            )
        ]
        segment_stability = [
            {
                "label": seg["label"],
                "high_correlation_edge_jaccard_vs_full": _edge_jaccard(
                    full_high_corr_edges, seg.get("high_correlation_edges", [])
                ),
            }
            for seg in segments
        ]
        finite_breadth_segments = sum(
            1 for seg in segments if seg.get("effective_breadth") is not None
        )
    else:
        clusters = []
        downside_breadth = None
        segments = []
        segment_stability = []
        finite_breadth_segments = 0

    pc1_share = full_breadth["first_principal_component_share"] if full_breadth else 1.0
    effective_breadth_value = full_breadth["effective_breadth"] if full_breadth else 0.0

    kill_tests = {
        "effective_breadth_below_floor": (
            effective_breadth_value < protocol.minimum_effective_breadth
        ),
        "equivalent_to_btc_beta": pc1_share > protocol.maximum_pc1_share_for_independence,
        "single_year_concentration": (
            finite_breadth_segments < protocol.minimum_segment_count_for_stability
        ),
        "pit_universe_not_reconstructable": len(universe_gap) > 0,
    }
    blocked = any(kill_tests.values())

    return {
        "schema_version": MARKET_BREADTH_G0_VERSION,
        "artifact_type": "market_breadth_dispersion_g0",
        "observed_at": observed_at,
        "contract_hash": protocol.contract_hash,
        "meta": {
            "research_only": True,
            "output_role": protocol.output_role,
            "direction_produced": False,
            "pnl_evaluated": False,
            "candidate_pnl_ready": False,
            "promotion_evidence": False,
            "orders_authorized": False,
        },
        "universe": {
            "target": list(protocol.target_universe),
            "available": list(available_symbols),
            "missing": universe_gap,
            "coverage_ratio": universe_coverage,
        },
        "common_bar_count": len(common_dates),
        "first_common_date": common_dates[0] if common_dates else None,
        "last_common_date": common_dates[-1] if common_dates else None,
        "breadth": full_breadth,
        "downside_breadth": downside_breadth,
        "advance_ratio": advance_ratio_summary,
        "trend_distance": trend_distance,
        "residual_dispersion": residual_dispersion,
        "correlation_clusters": clusters,
        "segments": segments,
        "segment_stability": segment_stability,
        "kill_tests": kill_tests,
        "verdict": "block_capacity" if blocked else "pass_to_state_increment",
        "remaining_blockers": (
            [
                f"effective_breadth_{effective_breadth_value:.4f}_below_{protocol.minimum_effective_breadth}",
                f"pc1_share_{pc1_share:.4f}_exceeds_{protocol.maximum_pc1_share_for_independence}",
                f"only_{finite_breadth_segments}_segments_with_finite_breadth",
                f"{len(universe_gap)}_of_{len(protocol.target_universe)}_universe_symbols_missing",
            ]
            if blocked
            else []
        ),
    }
