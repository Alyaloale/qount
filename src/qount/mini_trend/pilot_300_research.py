"""Historical capital/risk review for the owner-selected 300 USDT pilot."""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.research_data.market_data import Bar, Funding
from qount.mini_trend.backtest import align_bars
from qount.mini_trend.forward import TOP3, frozen_top3_config
from qount.mini_trend.futures_funding_veto import FundingVetoRegimeSelector
from qount.mini_trend.futures_recovery import canonical_hash, selected_um_rules
from qount.mini_trend.futures_recovery_backtest import VariantResult, run_variant
from qount.mini_trend.futures_regime_overlay import control_regime_config_selector
from qount.mini_trend.futures_regime_stop_latch import StopLatchedRegimeSelector
from qount.mini_trend.futures_risk_tier import risk_tier_config
from qount.mini_trend.live_pilot import LIVE_PILOT_CONTRACT
from qount.mini_trend.scorecard import max_drawdown_pct
from qount.models import utc_now
from qount.research_data.metrics import returns_from_curve, sharpe
from qount.settings import Settings


PILOT_300_RESEARCH_VERSION = "mini_trend_um_pilot_300_research_v0.1"


@dataclass(frozen=True)
class Pilot300ResearchProtocol:
    capital_usdt: float = 300.0
    pilot_days: int = 30
    pilot_drawdown_halt_pct: float = 10.0
    daily_account_loss_halt_pct: float | None = None
    trial_count: int = 4

    @property
    def contract_basis(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "live_pilot_contract_hash": LIVE_PILOT_CONTRACT.contract_hash,
            "universe": list(TOP3),
            "market": "um",
            "interval": "1d",
            "direction": "long_cash",
            "maximum_effective_gross": 1.0,
            "carry_allowed": False,
            "shorting_allowed": False,
            "leverage_boost_allowed": False,
            "candidate_set": [
                "base_v0.2",
                "global_risk_2pct",
                "stop_latch",
                "funding_veto",
            ],
            "parameter_search_allowed": False,
            "holdout_role": "consumed_historical_discovery_pool",
        }

    @property
    def contract_hash(self) -> str:
        return canonical_hash(self.contract_basis)


PILOT_300_PROTOCOL = Pilot300ResearchProtocol()


def _run_candidates(
    bars: Mapping[str, Sequence[Bar]],
    funding: Mapping[str, Sequence[Funding]],
    rules: Mapping[str, Mapping[str, Any]],
    *,
    protocol: Pilot300ResearchProtocol,
) -> dict[str, VariantResult]:
    common = {
        "recovery_enabled": False,
        "daily_chandelier_atr_multiple": (
            LIVE_PILOT_CONTRACT.daily_chandelier_atr_multiple
        ),
        "stop_cooldown_completed_bars": (
            LIVE_PILOT_CONTRACT.stop_cooldown_completed_bars
        ),
        "gross_cap_policy": "renormalize_active_targets_with_filter_floors",
        "capital_usdt": protocol.capital_usdt,
    }
    base = run_variant(
        bars,
        funding,
        rules,
        base_config=frozen_top3_config(),
        base_config_selector=control_regime_config_selector,
        **common,
    )
    risk_2pct = run_variant(
        bars,
        funding,
        rules,
        base_config=risk_tier_config(),
        **common,
    )
    stop_selector = StopLatchedRegimeSelector()
    stop_latch = run_variant(
        bars,
        funding,
        rules,
        base_config=frozen_top3_config(),
        base_config_selector=stop_selector,
        base_config_feedback=stop_selector.observe_stops,
        **common,
    )
    funding_selector = FundingVetoRegimeSelector(funding)
    funding_veto = run_variant(
        bars,
        funding,
        rules,
        base_config=frozen_top3_config(),
        base_config_selector=funding_selector,
        base_config_feedback=funding_selector.observe_stops,
        **common,
    )
    return {
        "base_v0.2": base,
        "global_risk_2pct": risk_2pct,
        "stop_latch": stop_latch,
        "funding_veto": funding_veto,
    }


def _metrics(result: VariantResult, capital_usdt: float) -> dict[str, Any]:
    curve = [capital_usdt] + [float(row["equity"]) for row in result.equity]
    gross = [float(row["gross"]) for row in result.equity]
    returns = returns_from_curve(curve)
    return {
        **result.metrics,
        "sharpe": round(
            sharpe(returns, periods_per_year=365.0) if len(returns) >= 2 else 0.0,
            8,
        ),
        "average_effective_gross": round(statistics.mean(gross), 8),
        "maximum_effective_gross": round(max(gross), 8),
    }


def _quantile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _episode_summary(rows: Sequence[dict[str, Any]], drawdown_halt: float) -> dict[str, Any]:
    returns = [float(row["return_pct"]) for row in rows]
    drawdowns = [float(row["max_drawdown_pct"]) for row in rows]
    return {
        "episode_count": len(rows),
        "positive_episode_count": sum(value > 0.0 for value in returns),
        "positive_episode_rate": round(
            sum(value > 0.0 for value in returns) / len(returns) if returns else 0.0,
            8,
        ),
        "mean_return_pct": round(statistics.mean(returns) if returns else 0.0, 8),
        "median_return_pct": round(statistics.median(returns) if returns else 0.0, 8),
        "p10_return_pct": round(_quantile(returns, 0.10), 8),
        "p90_return_pct": round(_quantile(returns, 0.90), 8),
        "worst_return_pct": round(min(returns) if returns else 0.0, 8),
        "best_return_pct": round(max(returns) if returns else 0.0, 8),
        "median_max_drawdown_pct": round(
            statistics.median(drawdowns) if drawdowns else 0.0,
            8,
        ),
        "worst_max_drawdown_pct": round(max(drawdowns) if drawdowns else 0.0, 8),
        "drawdown_halt_count": sum(value >= drawdown_halt for value in drawdowns),
        "drawdown_halt_rate": round(
            sum(value >= drawdown_halt for value in drawdowns) / len(drawdowns)
            if drawdowns
            else 0.0,
            8,
        ),
    }


def _rolling_pilot_episodes(
    bars: Mapping[str, Sequence[Bar]],
    funding: Mapping[str, Sequence[Funding]],
    rules: Mapping[str, Mapping[str, Any]],
    *,
    protocol: Pilot300ResearchProtocol,
) -> dict[str, Any]:
    aligned = align_bars(bars, TOP3)
    warmup = 200
    episode_rows: dict[str, list[dict[str, Any]]] = {
        name: [] for name in protocol.contract_basis["candidate_set"]
    }
    for start_index in range(warmup, len(aligned["BTCUSDT"]) - protocol.pilot_days, protocol.pilot_days):
        slice_start = start_index - warmup
        slice_end = start_index + protocol.pilot_days + 1
        sliced = {
            symbol: rows[slice_start:slice_end] for symbol, rows in aligned.items()
        }
        candidates = _run_candidates(sliced, funding, rules, protocol=protocol)
        for name, result in candidates.items():
            if len(result.equity) != protocol.pilot_days:
                raise ValueError("rolling pilot episode length mismatch")
            curve = [protocol.capital_usdt] + [
                float(row["equity"]) for row in result.equity
            ]
            episode_rows[name].append(
                {
                    "decision_start": result.equity[0]["decision_date"],
                    "outcome_end": result.equity[-1]["outcome_date"],
                    "return_pct": (curve[-1] / curve[0] - 1.0) * 100.0,
                    "max_drawdown_pct": max_drawdown_pct(curve),
                }
            )
    return {
        "episode_step_days": protocol.pilot_days,
        "overlapping": False,
        "summaries": {
            name: _episode_summary(rows, protocol.pilot_drawdown_halt_pct)
            for name, rows in episode_rows.items()
        },
        "episodes": episode_rows,
    }


def build_pilot_300_research_report(
    inputs: Mapping[str, Mapping[str, Any]],
    rules_artifact: Mapping[str, Any],
    *,
    protocol: Pilot300ResearchProtocol | None = None,
) -> dict[str, Any]:
    protocol = protocol or PILOT_300_PROTOCOL
    if protocol.capital_usdt != PILOT_300_PROTOCOL.capital_usdt:
        raise ValueError("historical research capital must remain frozen at 300 USDT")
    if not (
        LIVE_PILOT_CONTRACT.minimum_capital_usdt
        <= protocol.capital_usdt
        <= LIVE_PILOT_CONTRACT.maximum_capital_usdt
    ):
        raise ValueError("historical research capital is outside the current pilot range")
    if protocol.daily_account_loss_halt_pct is not None:
        raise ValueError("current owner contract has no account-level daily loss halt")
    if protocol.pilot_drawdown_halt_pct != LIVE_PILOT_CONTRACT.maximum_pilot_drawdown_pct:
        raise ValueError("research drawdown halt does not match the live-pilot contract")
    rules, rules_hash = selected_um_rules(rules_artifact)
    window_reports = {}
    full_results: dict[str, VariantResult] | None = None
    for label, source in inputs.items():
        bars = align_bars(source["bars"], TOP3)
        candidates = _run_candidates(bars, source["funding"], rules, protocol=protocol)
        window_reports[label] = {
            "data_hash": canonical_hash(
                {
                    "dates": [row.date for row in bars["BTCUSDT"]],
                    "funding_counts": {
                        symbol: len(source["funding"].get(symbol, [])) for symbol in TOP3
                    },
                }
            ),
            "candidates": {
                name: _metrics(result, protocol.capital_usdt)
                for name, result in candidates.items()
            },
        }
        if label == "2021-2026-full":
            full_results = candidates
    if full_results is None:
        raise ValueError("300 USDT research requires the full historical window")
    full_source = inputs["2021-2026-full"]
    episodes = _rolling_pilot_episodes(
        full_source["bars"],
        full_source["funding"],
        rules,
        protocol=protocol,
    )
    full_candidates = window_reports["2021-2026-full"]["candidates"]
    profit_leader = max(
        full_candidates,
        key=lambda name: float(full_candidates[name]["return_pct"]),
    )
    return {
        "schema_version": PILOT_300_RESEARCH_VERSION,
        "artifact_type": "mini_trend_um_pilot_300_historical_research",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "consumed_historical_discovery_pool",
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "contract": protocol.contract_basis | {"contract_hash": protocol.contract_hash},
        "exchange_rules_hash": rules_hash,
        "windows": window_reports,
        "rolling_30_day_pilots": episodes,
        "diagnostics": {
            "historical_profit_leader": profit_leader,
            "selected_live_control": "base_v0.2",
            "candidate_promotion_allowed": False,
            "interpretation": (
                "The profit leader is a consumed-history research priority only; "
                "independent forward evidence is still required before it can control orders."
            ),
        },
    }


def write_pilot_300_research_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-pilot-300-research",
        path_key="artifact_path",
        default_filename="mini_trend_um_pilot_300_research.json",
        explicit_path=explicit_path,
    )
