"""Preregistered stop-latched strong-bull risk overlay for UM MiniTrend."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.grid.data import Bar
from qount.mini_trend.config import MiniTrendConfig
from qount.mini_trend.forward import TOP3, frozen_top3_config
from qount.mini_trend.futures_base_forward import BASE_FORWARD_PREREG_VERSION
from qount.mini_trend.futures_base_forward import FUTURES_BASE_FORWARD_PROTOCOL
from qount.mini_trend.futures_recovery import canonical_hash
from qount.mini_trend.futures_recovery import load_live_lessons_evidence, selected_um_rules
from qount.mini_trend.futures_regime_overlay import BEAR_CASH
from qount.mini_trend.futures_regime_overlay import FUTURES_REGIME_OVERLAY_PROTOCOL
from qount.mini_trend.futures_regime_overlay import STRONG_BULL, TRANSITION_RANGE
from qount.mini_trend.futures_regime_overlay import classify_regime, regime_overlay_config
from qount.mini_trend.futures_risk_tier import file_sha256
from qount.models import utc_now
from qount.settings import Settings


REGIME_STOP_LATCH_PREREG_VERSION = "mini_trend_um_regime_stop_latch_preregistration_v0.1"
STRONG_BULL_BOOSTED = "strong_bull_boosted"
STRONG_BULL_LATCHED_BASE = "strong_bull_latched_base"
STOP_LATCH_RISK_STAGES = (
    STRONG_BULL_BOOSTED,
    STRONG_BULL_LATCHED_BASE,
    TRANSITION_RANGE,
    BEAR_CASH,
)


class StopLatchedRegimeSelector:
    """Disable only the risk boost after a stop within a continuous strong-bull regime."""

    def __init__(self) -> None:
        self._boost_latched = False

    def __call__(
        self, bars: Mapping[str, Sequence[Bar]]
    ) -> tuple[MiniTrendConfig, str]:
        decision = classify_regime(bars)
        protocol = FUTURES_REGIME_STOP_LATCH_PROTOCOL
        if decision.stage != STRONG_BULL:
            self._boost_latched = False
            return decision.config, decision.stage
        if self._boost_latched:
            return (
                regime_overlay_config(protocol.base_vol_target),
                STRONG_BULL_LATCHED_BASE,
            )
        return (
            regime_overlay_config(protocol.strong_bull_vol_target),
            STRONG_BULL_BOOSTED,
        )

    def observe_stops(self, risk_stage: str, stopped: set[str]) -> None:
        if stopped and risk_stage in {STRONG_BULL_BOOSTED, STRONG_BULL_LATCHED_BASE}:
            self._boost_latched = True

    def state_snapshot(self) -> dict[str, bool]:
        return {"boost_latched": self._boost_latched}


@dataclass(frozen=True)
class FuturesRegimeStopLatchProtocol:
    strategy: str = "MiniTrend-UM-RegimeStopLatch-v0.1"
    capital_usdt: float = 400.0
    market: str = "um"
    interval: str = "1d"
    base_vol_target: float = 0.015
    strong_bull_vol_target: float = 0.020
    maximum_effective_gross: float = 1.0
    daily_chandelier_atr_multiple: float = 3.0
    stop_cooldown_completed_bars: int = 3
    taker_fee_bps: float = 10.0
    slippage_bps: float = 2.0
    filter_buffer: float = 1.05
    gross_cap_policy: str = "renormalize_active_targets_with_filter_floors"

    @property
    def historical_windows(self) -> tuple[dict[str, str], ...]:
        return FUTURES_REGIME_OVERLAY_PROTOCOL.historical_windows

    @property
    def full_window(self) -> dict[str, str]:
        return FUTURES_REGIME_OVERLAY_PROTOCOL.full_window

    @property
    def contract_basis(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "capital": {
                "capital_usdt": self.capital_usdt,
                "capital_location": "Binance USD-M futures wallet",
                "carry_allowed": False,
                "external_cash_flow_adjustment_required": True,
            },
            "data": {
                "source": "existing Binance public UM daily kline and funding cache",
                "market": self.market,
                "interval": self.interval,
                "completed_daily_bars_only": True,
                "all_funding_settlements_included": True,
                "network_download_allowed": False,
            },
            "control": {
                "strategy": FUTURES_BASE_FORWARD_PROTOCOL.strategy,
                "config": asdict(frozen_top3_config()),
            },
            "inherited_regime_contract_hash": FUTURES_REGIME_OVERLAY_PROTOCOL.contract_hash,
            "candidate_delta": {
                "regime_classification_unchanged": True,
                "strong_bull_initial_vol_target": self.strong_bull_vol_target,
                "stop_trigger": "any existing 3xATR symbol stop in continuous strong_bull",
                "action_from_next_completed_bar": "revert risk boost to base vol_target 0.015",
                "base_signal_and_position_cooldown_unchanged": True,
                "reset": "only after at least one non-strong-bull completed bar and later re-entry",
                "new_numeric_thresholds": 0,
            },
            "execution": {
                "direction": "long_cash",
                "maximum_effective_gross": self.maximum_effective_gross,
                "gross_cap_policy": self.gross_cap_policy,
                "shorting_allowed": False,
                "leverage_boost_allowed": False,
                "one_decision_per_completed_bar": True,
                "filter_buffer": self.filter_buffer,
                "runtime_filter_coverage_required": 1.0,
                "unknown_capital_action": "fail_closed",
                "taker_fee_bps": self.taker_fee_bps,
                "slippage_bps": self.slippage_bps,
            },
            "stops": {
                "daily_chandelier_atr_multiple": self.daily_chandelier_atr_multiple,
                "latch_required": True,
                "cooldown_completed_bars": self.stop_cooldown_completed_bars,
                "same_bar_reentry_allowed": False,
            },
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
                "minimum_latch_activation_count": 1,
                "minimum_latched_bar_count": 1,
                "required_filter_coverage": 1.0,
                "maximum_duplicate_decision_count": 0,
                "maximum_same_bar_stop_reentry_count": 0,
            },
            "trial_count": 1,
            "parameter_search_allowed": False,
            "universe_search_allowed": False,
            "shorting_allowed": False,
            "leverage_search_allowed": False,
            "high_frequency_data_allowed": False,
            "paper_or_live_allowed": False,
            "promotion_rule": "Historical evidence may reject or retain for research, never promote to paper/live.",
        }

    @property
    def protocol_hash(self) -> str:
        return canonical_hash(self.protocol_basis)


FUTURES_REGIME_STOP_LATCH_PROTOCOL = FuturesRegimeStopLatchProtocol()


def _validated_base_preregistration(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != BASE_FORWARD_PREREG_VERSION:
        raise ValueError("stop-latch overlay requires current UM base v0.2 preregistration")
    if payload.get("decision_contract", {}).get("contract_hash") != FUTURES_BASE_FORWARD_PROTOCOL.contract_hash:
        raise ValueError("UM base preregistration contract hash mismatch")


def _load_prior_regime_overlay(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("artifact_type") != "mini_trend_um_regime_overlay_historical_diagnostic":
        raise ValueError("unexpected prior regime-overlay artifact")
    if payload.get("contract_hash") != FUTURES_REGIME_OVERLAY_PROTOCOL.contract_hash:
        raise ValueError("prior regime-overlay contract hash mismatch")
    if payload.get("diagnostics", {}).get("verdict") != "reject_historical_regime_overlay":
        raise ValueError("prior regime overlay must remain historically rejected")
    weak = next(row for row in payload["segments"] if row["label"] == "2025-2026")
    return {
        "artifact_path": str(source),
        "artifact_sha256": file_sha256(source),
        "verdict": payload["diagnostics"]["verdict"],
        "full_candidate_return_pct": payload["full_window"]["candidate"]["return_pct"],
        "full_candidate_max_drawdown_pct": payload["full_window"]["candidate"]["max_drawdown_pct"],
        "weak_candidate_return_pct": weak["candidate"]["return_pct"],
        "weak_candidate_max_drawdown_pct": weak["candidate"]["max_drawdown_pct"],
    }


def build_regime_stop_latch_preregistration(
    rules_artifact: Mapping[str, Any],
    live_lessons_path: str | Path,
    base_preregistration_path: str | Path,
    prior_regime_overlay_path: str | Path,
) -> dict[str, Any]:
    selected, rules_hash = selected_um_rules(rules_artifact)
    lessons = load_live_lessons_evidence(live_lessons_path)
    base_path = Path(base_preregistration_path).expanduser()
    base = json.loads(base_path.read_text(encoding="utf-8"))
    _validated_base_preregistration(base)
    prior = _load_prior_regime_overlay(prior_regime_overlay_path)
    protocol = FUTURES_REGIME_STOP_LATCH_PROTOCOL
    return {
        "schema_version": REGIME_STOP_LATCH_PREREG_VERSION,
        "artifact_type": "mini_trend_um_regime_stop_latch_preregistration",
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
        "exchange_rules": {
            "selected_rules_hash": rules_hash,
            "symbols": sorted(selected),
        },
        "base_preregistration": {
            "artifact_sha256": file_sha256(base_path),
            "contract_hash": base["decision_contract"]["contract_hash"],
        },
        "prior_regime_overlay": prior,
        "live_lessons": lessons,
    }


def validate_regime_stop_latch_registration(
    preregistration: Mapping[str, Any],
    rules_artifact: Mapping[str, Any],
    live_lessons_path: str | Path,
    base_preregistration_path: str | Path,
    prior_regime_overlay_path: str | Path,
) -> None:
    protocol = FUTURES_REGIME_STOP_LATCH_PROTOCOL
    if preregistration.get("schema_version") != REGIME_STOP_LATCH_PREREG_VERSION:
        raise ValueError("unexpected regime-stop-latch preregistration schema")
    if preregistration.get("decision_contract", {}).get("contract_hash") != protocol.contract_hash:
        raise ValueError("regime-stop-latch contract hash mismatch")
    if preregistration.get("protocol", {}).get("protocol_hash") != protocol.protocol_hash:
        raise ValueError("regime-stop-latch protocol hash mismatch")
    _, rules_hash = selected_um_rules(rules_artifact)
    if preregistration.get("exchange_rules", {}).get("selected_rules_hash") != rules_hash:
        raise ValueError("regime-stop-latch exchange-rules hash mismatch")
    lessons = load_live_lessons_evidence(live_lessons_path)
    if preregistration.get("live_lessons", {}).get("artifact_sha256") != lessons["artifact_sha256"]:
        raise ValueError("regime-stop-latch live-lessons hash mismatch")
    base_path = Path(base_preregistration_path).expanduser()
    base = json.loads(base_path.read_text(encoding="utf-8"))
    _validated_base_preregistration(base)
    if preregistration.get("base_preregistration", {}).get("artifact_sha256") != file_sha256(base_path):
        raise ValueError("regime-stop-latch base-preregistration hash mismatch")
    prior = _load_prior_regime_overlay(prior_regime_overlay_path)
    if preregistration.get("prior_regime_overlay", {}).get("artifact_sha256") != prior["artifact_sha256"]:
        raise ValueError("regime-stop-latch prior-overlay hash mismatch")


def write_regime_stop_latch_preregistration_artifact(
    settings: Settings, payload: dict[str, Any], *, explicit_path: str | None = None
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-regime-stop-latch-preregistration",
        path_key="artifact_path",
        default_filename="mini_trend_um_regime_stop_latch_preregistration.json",
        explicit_path=explicit_path,
    )
