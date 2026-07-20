"""Preregistered lagged-funding cost veto for the UM strong-bull risk boost."""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.grid.data import Bar, Funding
from qount.mini_trend.config import MiniTrendConfig
from qount.mini_trend.futures_base_forward import BASE_FORWARD_PREREG_VERSION
from qount.mini_trend.futures_base_forward import FUTURES_BASE_FORWARD_PROTOCOL
from qount.mini_trend.futures_recovery import canonical_hash
from qount.mini_trend.futures_recovery import load_live_lessons_evidence, selected_um_rules
from qount.mini_trend.futures_regime_overlay import FUTURES_REGIME_OVERLAY_PROTOCOL
from qount.mini_trend.futures_regime_overlay import regime_overlay_config
from qount.mini_trend.futures_regime_stop_latch import FUTURES_REGIME_STOP_LATCH_PROTOCOL
from qount.mini_trend.futures_regime_stop_latch import STRONG_BULL_BOOSTED
from qount.mini_trend.futures_regime_stop_latch import StopLatchedRegimeSelector
from qount.mini_trend.futures_risk_tier import file_sha256
from qount.mini_trend.forward import TOP3
from qount.models import utc_now
from qount.settings import Settings


FUNDING_VETO_PREREG_VERSION = "mini_trend_um_funding_veto_preregistration_v0.1"
STRONG_BULL_FUNDING_VETO = "strong_bull_funding_veto_base"
STRONG_BULL_FUNDING_MISSING = "strong_bull_funding_missing_base"
_DAY_MS = 86_400_000


def _daily_funding_by_bar_open(
    funding: Mapping[str, Sequence[Funding]],
) -> dict[str, dict[int, float]]:
    daily: dict[str, dict[int, float]] = {symbol: {} for symbol in TOP3}
    for symbol in TOP3:
        for row in funding.get(symbol, []):
            bar_open = ((row.ts_ms - 1) // _DAY_MS) * _DAY_MS
            daily[symbol][bar_open] = daily[symbol].get(bar_open, 0.0) + row.rate
    return daily


class FundingVetoRegimeSelector:
    """Apply a causal funding-cost veto before the strong-bull risk boost."""

    def __init__(self, funding: Mapping[str, Sequence[Funding]]) -> None:
        self._base = StopLatchedRegimeSelector()
        self._daily_funding = _daily_funding_by_bar_open(funding)
        self._covered = 0
        self._missing = 0
        self._vetoed = 0
        self._annualized_medians: list[float] = []
        self._events: list[dict[str, Any]] = []

    def __call__(
        self, bars: Mapping[str, Sequence[Bar]]
    ) -> tuple[MiniTrendConfig, str]:
        config, stage = self._base(bars)
        if stage != STRONG_BULL_BOOSTED:
            return config, stage
        bar_open = bars["BTCUSDT"][-1].ts_ms
        values = [self._daily_funding[symbol].get(bar_open) for symbol in TOP3]
        if any(value is None for value in values):
            self._missing += 1
            return (
                regime_overlay_config(FUTURES_FUNDING_VETO_PROTOCOL.base_vol_target),
                STRONG_BULL_FUNDING_MISSING,
            )
        self._covered += 1
        annualized_median = statistics.median(float(value) for value in values) * 365.0
        self._annualized_medians.append(annualized_median)
        if annualized_median > FUTURES_FUNDING_VETO_PROTOCOL.annualized_funding_veto:
            self._vetoed += 1
            self._events.append(
                {
                    "decision_date": bars["BTCUSDT"][-1].date,
                    "annualized_median_funding": annualized_median,
                }
            )
            return (
                regime_overlay_config(FUTURES_FUNDING_VETO_PROTOCOL.base_vol_target),
                STRONG_BULL_FUNDING_VETO,
            )
        return config, stage

    def observe_stops(self, risk_stage: str, stopped: set[str]) -> None:
        inherited_stage = (
            STRONG_BULL_BOOSTED
            if risk_stage in {STRONG_BULL_FUNDING_VETO, STRONG_BULL_FUNDING_MISSING}
            else risk_stage
        )
        self._base.observe_stops(inherited_stage, stopped)

    def state_snapshot(self) -> dict[str, bool]:
        return self._base.state_snapshot()

    def summary(self) -> dict[str, Any]:
        total = self._covered + self._missing
        return {
            "covered_strong_bull_bar_count": self._covered,
            "missing_strong_bull_bar_count": self._missing,
            "funding_coverage": self._covered / total if total else 1.0,
            "vetoed_bar_count": self._vetoed,
            "maximum_annualized_median_funding": (
                max(self._annualized_medians) if self._annualized_medians else None
            ),
            "veto_threshold": FUTURES_FUNDING_VETO_PROTOCOL.annualized_funding_veto,
            "events": list(self._events),
        }


@dataclass(frozen=True)
class FuturesFundingVetoProtocol:
    strategy: str = "MiniTrend-UM-FundingVeto-v0.1"
    capital_usdt: float = 400.0
    market: str = "um"
    interval: str = "1d"
    base_vol_target: float = 0.015
    strong_bull_vol_target: float = 0.020
    annualized_funding_veto: float = 0.50
    maximum_effective_gross: float = 1.0
    daily_chandelier_atr_multiple: float = 3.0
    stop_cooldown_completed_bars: int = 3
    taker_fee_bps: float = 10.0
    slippage_bps: float = 2.0
    gross_cap_policy: str = "renormalize_active_targets_with_filter_floors"

    @property
    def historical_windows(self) -> tuple[dict[str, str], ...]:
        return FUTURES_REGIME_STOP_LATCH_PROTOCOL.historical_windows

    @property
    def full_window(self) -> dict[str, str]:
        return FUTURES_REGIME_STOP_LATCH_PROTOCOL.full_window

    @property
    def contract_basis(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "capital": {
                "capital_usdt": self.capital_usdt,
                "capital_location": "Binance USD-M futures wallet",
                "carry_allowed": False,
            },
            "data": {
                "source": "existing Binance public UM daily kline and funding cache",
                "market": self.market,
                "interval": self.interval,
                "completed_daily_bars_only": True,
                "network_download_allowed": False,
                "funding_alignment": "decision bar open < settlement <= decision bar close",
                "future_funding_used": False,
            },
            "inherited_regime_contract_hash": FUTURES_REGIME_OVERLAY_PROTOCOL.contract_hash,
            "inherited_stop_latch_contract_hash": FUTURES_REGIME_STOP_LATCH_PROTOCOL.contract_hash,
            "candidate_delta": {
                "active_only_before_unlatched_strong_bull_boost": True,
                "aggregation": "median of TOP3 completed-day funding sums",
                "annualization": 365.0,
                "annualized_funding_veto": self.annualized_funding_veto,
                "veto_action": "use base vol_target 0.015 for current completed-bar decision",
                "missing_funding_action": "fail closed to base vol_target 0.015",
                "funding_is_cost_filter_not_carry_alpha": True,
                "parameter_search_allowed": False,
            },
            "execution": {
                "direction": "long_cash",
                "maximum_effective_gross": self.maximum_effective_gross,
                "gross_cap_policy": self.gross_cap_policy,
                "shorting_allowed": False,
                "leverage_boost_allowed": False,
                "taker_fee_bps": self.taker_fee_bps,
                "slippage_bps": self.slippage_bps,
            },
            "stops": FUTURES_REGIME_STOP_LATCH_PROTOCOL.contract_basis["stops"],
        }

    @property
    def contract_hash(self) -> str:
        return canonical_hash(self.contract_basis)

    @property
    def protocol_basis(self) -> dict[str, Any]:
        return {
            "contract_hash": self.contract_hash,
            "holdout_role": "consumed_historical_discovery_only",
            "historical_windows": list(self.historical_windows),
            "full_window": self.full_window,
            "historical_pass_gates": {
                "minimum_full_window_return_uplift_percentage_points": 10.0,
                "minimum_full_window_sharpe_uplift": 0.0,
                "maximum_full_window_drawdown_worsening_percentage_points": 1.0,
                "maximum_segment_drawdown_worsening_percentage_points": 2.0,
                "weak_segment_label": "2025-2026",
                "maximum_weak_segment_return_degradation_percentage_points": 1.0,
                "maximum_average_effective_gross": 0.23,
                "maximum_effective_gross": self.maximum_effective_gross,
                "minimum_funding_vetoed_bar_count": 1,
                "required_funding_coverage": 1.0,
                "minimum_latch_entry_count": 1,
                "required_filter_coverage": 1.0,
                "maximum_duplicate_decision_count": 0,
                "maximum_same_bar_stop_reentry_count": 0,
            },
            "trial_count": 1,
            "mechanism_family_trial_count": 2,
            "threshold_source": "owner-provided external hypothesis; fixed before result",
            "parameter_search_allowed": False,
            "universe_search_allowed": False,
            "paper_or_live_allowed": False,
            "promotion_rule": "Historical evidence may reject or retain for research, never promote.",
        }

    @property
    def protocol_hash(self) -> str:
        return canonical_hash(self.protocol_basis)


FUTURES_FUNDING_VETO_PROTOCOL = FuturesFundingVetoProtocol()


def _load_prior_stop_latch(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("artifact_type") != "mini_trend_um_regime_stop_latch_historical_diagnostic":
        raise ValueError("unexpected prior stop-latch artifact")
    if payload.get("contract_hash") != FUTURES_REGIME_STOP_LATCH_PROTOCOL.contract_hash:
        raise ValueError("prior stop-latch contract hash mismatch")
    if payload.get("diagnostics", {}).get("verdict") != "reject_historical_regime_stop_latch":
        raise ValueError("prior stop-latch result must remain rejected")
    fields = ("return_pct", "sharpe", "max_drawdown_pct", "average_effective_gross")
    return {
        "artifact_path": str(source),
        "artifact_sha256": file_sha256(source),
        "verdict": payload["diagnostics"]["verdict"],
        "full_candidate": {
            field: payload["full_window"]["candidate"][field] for field in fields
        },
        "segments": [
            {
                "label": row["label"],
                "candidate": {field: row["candidate"][field] for field in fields},
            }
            for row in payload["segments"]
        ],
    }


def _validated_base(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != BASE_FORWARD_PREREG_VERSION:
        raise ValueError("funding veto requires current UM base v0.2 preregistration")
    if payload.get("decision_contract", {}).get("contract_hash") != FUTURES_BASE_FORWARD_PROTOCOL.contract_hash:
        raise ValueError("UM base preregistration contract hash mismatch")


def build_funding_veto_preregistration(
    rules_artifact: Mapping[str, Any],
    live_lessons_path: str | Path,
    base_preregistration_path: str | Path,
    prior_stop_latch_path: str | Path,
) -> dict[str, Any]:
    selected, rules_hash = selected_um_rules(rules_artifact)
    lessons = load_live_lessons_evidence(live_lessons_path)
    base_path = Path(base_preregistration_path).expanduser()
    base = json.loads(base_path.read_text(encoding="utf-8"))
    _validated_base(base)
    prior = _load_prior_stop_latch(prior_stop_latch_path)
    protocol = FUTURES_FUNDING_VETO_PROTOCOL
    return {
        "schema_version": FUNDING_VETO_PREREG_VERSION,
        "artifact_type": "mini_trend_um_funding_veto_preregistration",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "strategy_results_evaluated": False,
            "existing_cache_only_at_registration": True,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "decision_contract": protocol.contract_basis | {"contract_hash": protocol.contract_hash},
        "protocol": protocol.protocol_basis | {"protocol_hash": protocol.protocol_hash},
        "exchange_rules": {"selected_rules_hash": rules_hash, "symbols": sorted(selected)},
        "base_preregistration": {"artifact_sha256": file_sha256(base_path)},
        "prior_stop_latch": prior,
        "live_lessons": lessons,
    }


def validate_funding_veto_registration(
    preregistration: Mapping[str, Any],
    rules_artifact: Mapping[str, Any],
    live_lessons_path: str | Path,
    base_preregistration_path: str | Path,
    prior_stop_latch_path: str | Path,
) -> None:
    protocol = FUTURES_FUNDING_VETO_PROTOCOL
    if preregistration.get("schema_version") != FUNDING_VETO_PREREG_VERSION:
        raise ValueError("unexpected funding-veto preregistration schema")
    if preregistration.get("decision_contract", {}).get("contract_hash") != protocol.contract_hash:
        raise ValueError("funding-veto contract hash mismatch")
    if preregistration.get("protocol", {}).get("protocol_hash") != protocol.protocol_hash:
        raise ValueError("funding-veto protocol hash mismatch")
    _, rules_hash = selected_um_rules(rules_artifact)
    if preregistration.get("exchange_rules", {}).get("selected_rules_hash") != rules_hash:
        raise ValueError("funding-veto exchange-rules hash mismatch")
    lessons = load_live_lessons_evidence(live_lessons_path)
    if preregistration.get("live_lessons", {}).get("artifact_sha256") != lessons["artifact_sha256"]:
        raise ValueError("funding-veto live-lessons hash mismatch")
    base_path = Path(base_preregistration_path).expanduser()
    base = json.loads(base_path.read_text(encoding="utf-8"))
    _validated_base(base)
    if preregistration.get("base_preregistration", {}).get("artifact_sha256") != file_sha256(base_path):
        raise ValueError("funding-veto base-preregistration hash mismatch")
    prior = _load_prior_stop_latch(prior_stop_latch_path)
    if preregistration.get("prior_stop_latch", {}).get("artifact_sha256") != prior["artifact_sha256"]:
        raise ValueError("funding-veto prior stop-latch hash mismatch")


def write_funding_veto_preregistration_artifact(
    settings: Settings, payload: dict[str, Any], *, explicit_path: str | None = None
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-funding-veto-preregistration",
        path_key="artifact_path",
        default_filename="mini_trend_um_funding_veto_preregistration.json",
        explicit_path=explicit_path,
    )
