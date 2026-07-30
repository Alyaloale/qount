"""Preregistered three-stage risk overlay for the no-carry UM base strategy."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.research_data.market_data import Bar
from qount.mini_trend.config import MiniTrendConfig
from qount.mini_trend.forward import TOP3, frozen_top3_config
from qount.mini_trend.futures_base_forward import BASE_FORWARD_PREREG_VERSION
from qount.mini_trend.futures_base_forward import FUTURES_BASE_FORWARD_PROTOCOL
from qount.mini_trend.futures_recovery import canonical_hash
from qount.mini_trend.futures_recovery import load_live_lessons_evidence, selected_um_rules
from qount.mini_trend.futures_risk_tier import FUTURES_RISK_TIER_PROTOCOL, file_sha256
from qount.mini_trend.signals import sma, target_weights
from qount.models import utc_now
from qount.settings import Settings


REGIME_OVERLAY_PREREG_VERSION = "mini_trend_um_regime_overlay_preregistration_v0.1"
STRONG_BULL = "strong_bull"
TRANSITION_RANGE = "transition_range"
BEAR_CASH = "bear_cash"
RISK_STAGES = (STRONG_BULL, TRANSITION_RANGE, BEAR_CASH)


def regime_overlay_config(vol_target: float) -> MiniTrendConfig:
    return replace(
        frozen_top3_config(),
        strategy="MiniTrend-UM-RegimeOverlay-v0.1",
        vol_target=vol_target,
    )


@dataclass(frozen=True)
class RegimeDecision:
    stage: str
    config: MiniTrendConfig
    btc_close: float
    btc_sma200: float
    btc_sma20: float
    btc_sma60: float
    breadth: float


def classify_regime(bars: Mapping[str, Sequence[Bar]]) -> RegimeDecision:
    """Classify one completed daily bar without future data or hidden state."""

    protocol = FUTURES_REGIME_OVERLAY_PROTOCOL
    windows = {symbol: list(bars[symbol]) for symbol in TOP3}
    base = target_weights(windows, frozen_top3_config())
    btc_closes = [bar.close for bar in windows["BTCUSDT"]]
    btc_sma200 = sma(btc_closes, protocol.regime_sma)
    btc_sma20 = sma(btc_closes, protocol.fast_sma)
    btc_sma60 = sma(btc_closes, protocol.slow_sma)
    if btc_sma200 is None or btc_sma20 is None or btc_sma60 is None:
        raise ValueError("insufficient completed bars for regime classification")
    strong_bull = (
        base.gate.btc_gate
        and btc_sma20 > btc_sma60
        and base.gate.breadth >= protocol.strong_bull_breadth
    )
    if strong_bull:
        stage = STRONG_BULL
        vol_target = protocol.strong_bull_vol_target
    elif base.gate.risk_on:
        stage = TRANSITION_RANGE
        vol_target = protocol.transition_range_vol_target
    else:
        stage = BEAR_CASH
        vol_target = protocol.bear_vol_target
    return RegimeDecision(
        stage=stage,
        config=regime_overlay_config(vol_target),
        btc_close=btc_closes[-1],
        btc_sma200=btc_sma200,
        btc_sma20=btc_sma20,
        btc_sma60=btc_sma60,
        breadth=base.gate.breadth,
    )


def regime_config_selector(
    bars: Mapping[str, Sequence[Bar]],
) -> tuple[MiniTrendConfig, str]:
    decision = classify_regime(bars)
    return decision.config, decision.stage


def control_regime_config_selector(
    bars: Mapping[str, Sequence[Bar]],
) -> tuple[MiniTrendConfig, str]:
    decision = classify_regime(bars)
    return frozen_top3_config(), decision.stage


@dataclass(frozen=True)
class FuturesRegimeOverlayProtocol:
    strategy: str = "MiniTrend-UM-RegimeOverlay-v0.1"
    capital_usdt: float = 400.0
    market: str = "um"
    interval: str = "1d"
    regime_sma: int = 200
    fast_sma: int = 20
    slow_sma: int = 60
    strong_bull_breadth: float = 2.0 / 3.0
    strong_bull_vol_target: float = 0.020
    transition_range_vol_target: float = 0.015
    bear_vol_target: float = 0.015
    maximum_effective_gross: float = 1.0
    daily_chandelier_atr_multiple: float = 3.0
    stop_cooldown_completed_bars: int = 3
    taker_fee_bps: float = 10.0
    slippage_bps: float = 2.0
    filter_buffer: float = 1.05
    gross_cap_policy: str = "renormalize_active_targets_with_filter_floors"
    forward_start_date: str = "2026-07-17"
    minimum_forward_bars: int = 60
    minimum_active_bars: int = 10

    @property
    def historical_windows(self) -> tuple[dict[str, str], ...]:
        return (
            {"label": "2021-2022", "warmup_start": "2021-01-01", "start": "2021-07-20", "end": "2022-12-31"},
            {"label": "2023-2024", "warmup_start": "2023-01-01", "start": "2023-07-20", "end": "2024-12-31"},
            {"label": "2025-2026", "warmup_start": "2025-01-01", "start": "2025-07-20", "end": "2026-05-31"},
        )

    @property
    def full_window(self) -> dict[str, str]:
        return {
            "label": "2021-2026-full",
            "warmup_start": "2021-01-01",
            "start": "2021-07-20",
            "end": "2026-05-31",
        }

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
                "private_exchange_data": False,
                "network_download_allowed": False,
            },
            "control": {
                "strategy": FUTURES_BASE_FORWARD_PROTOCOL.strategy,
                "config": asdict(frozen_top3_config()),
            },
            "overlay": {
                "classification_timing": "one completed daily bar; no lookahead",
                "strong_bull": {
                    "conditions": [
                        "BTC close > BTC SMA200",
                        "BTC SMA20 > BTC SMA60",
                        "TOP3 breadth above own SMA200 >= 2/3",
                    ],
                    "vol_target": self.strong_bull_vol_target,
                },
                "transition_range": {
                    "conditions": "base master gate open and strong_bull false",
                    "vol_target": self.transition_range_vol_target,
                },
                "bear_cash": {
                    "conditions": "base master gate closed",
                    "target": "cash",
                },
                "stage_order": list(RISK_STAGES),
                "parameter_search_allowed": False,
            },
            "execution": {
                "direction": "long_cash",
                "maximum_effective_gross": self.maximum_effective_gross,
                "gross_cap_policy": self.gross_cap_policy,
                "shorting_allowed": False,
                "leverage_boost_allowed": False,
                "recovery_overlay_allowed": False,
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
            "holdout_role": "consumed_historical_discovery_then_new_forward_shadow",
            "historical_windows": list(self.historical_windows),
            "full_window": self.full_window,
            "historical_pass_gates": {
                "minimum_full_window_return_uplift_percentage_points": 10.0,
                "minimum_full_window_sharpe_uplift": 0.0,
                "maximum_full_window_drawdown_pct": 20.0,
                "maximum_segment_drawdown_worsening_percentage_points": 2.0,
                "weak_segment_label": "2025-2026",
                "maximum_weak_segment_return_degradation_percentage_points": 1.0,
                "maximum_average_effective_gross": 0.25,
                "maximum_effective_gross": self.maximum_effective_gross,
                "all_risk_stages_required_in_full_window": True,
                "required_filter_coverage": 1.0,
                "maximum_duplicate_decision_count": 0,
                "maximum_same_bar_stop_reentry_count": 0,
            },
            "forward_start_date": self.forward_start_date,
            "minimum_forward_bars": self.minimum_forward_bars,
            "minimum_active_bars": self.minimum_active_bars,
            "trial_count": 1,
            "parameter_search_allowed": False,
            "universe_search_allowed": False,
            "shorting_allowed": False,
            "leverage_search_allowed": False,
            "high_frequency_data_allowed": False,
            "paper_or_live_allowed": False,
        }

    @property
    def protocol_hash(self) -> str:
        return canonical_hash(self.protocol_basis)


FUTURES_REGIME_OVERLAY_PROTOCOL = FuturesRegimeOverlayProtocol()


def _validated_base_preregistration(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != BASE_FORWARD_PREREG_VERSION:
        raise ValueError("regime overlay requires current UM base v0.2 preregistration")
    if payload.get("decision_contract", {}).get("contract_hash") != FUTURES_BASE_FORWARD_PROTOCOL.contract_hash:
        raise ValueError("UM base preregistration contract hash mismatch")


def _load_prior_risk_tier(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("artifact_type") != "mini_trend_um_risk_tier_historical_diagnostic":
        raise ValueError("unexpected prior risk-tier artifact")
    if payload.get("contract_hash") != FUTURES_RISK_TIER_PROTOCOL.contract_hash:
        raise ValueError("prior risk-tier contract hash mismatch")
    if payload.get("diagnostics", {}).get("verdict") != "reject_historical_risk_tier":
        raise ValueError("prior 2.0% risk tier must remain historically rejected")
    return {
        "artifact_path": str(source),
        "artifact_sha256": file_sha256(source),
        "verdict": payload["diagnostics"]["verdict"],
        "control_return_pct": payload["full_window"]["control"]["return_pct"],
        "candidate_return_pct": payload["full_window"]["candidate"]["return_pct"],
        "candidate_max_drawdown_pct": payload["full_window"]["candidate"]["max_drawdown_pct"],
    }


def build_regime_overlay_preregistration(
    rules_artifact: Mapping[str, Any],
    live_lessons_path: str | Path,
    base_preregistration_path: str | Path,
    prior_risk_tier_path: str | Path,
) -> dict[str, Any]:
    selected, rules_hash = selected_um_rules(rules_artifact)
    lessons = load_live_lessons_evidence(live_lessons_path)
    base_path = Path(base_preregistration_path).expanduser()
    base = json.loads(base_path.read_text(encoding="utf-8"))
    _validated_base_preregistration(base)
    prior = _load_prior_risk_tier(prior_risk_tier_path)
    protocol = FUTURES_REGIME_OVERLAY_PROTOCOL
    return {
        "schema_version": REGIME_OVERLAY_PREREG_VERSION,
        "artifact_type": "mini_trend_um_regime_overlay_preregistration",
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
            "market": rules_artifact.get("market"),
            "source_type": rules_artifact.get("source_type"),
            "selected_rules_hash": rules_hash,
            "symbols": sorted(selected),
        },
        "base_preregistration": {
            "schema_version": base["schema_version"],
            "contract_hash": base["decision_contract"]["contract_hash"],
            "protocol_hash": base["protocol"]["protocol_hash"],
            "artifact_sha256": file_sha256(base_path),
        },
        "prior_risk_tier": prior,
        "live_lessons": lessons,
    }


def validate_regime_overlay_registration(
    preregistration: Mapping[str, Any],
    rules_artifact: Mapping[str, Any],
    live_lessons_path: str | Path,
    base_preregistration_path: str | Path,
    prior_risk_tier_path: str | Path,
) -> None:
    protocol = FUTURES_REGIME_OVERLAY_PROTOCOL
    if preregistration.get("schema_version") != REGIME_OVERLAY_PREREG_VERSION:
        raise ValueError("unexpected regime-overlay preregistration schema")
    if preregistration.get("decision_contract", {}).get("contract_hash") != protocol.contract_hash:
        raise ValueError("regime-overlay contract hash mismatch")
    if preregistration.get("protocol", {}).get("protocol_hash") != protocol.protocol_hash:
        raise ValueError("regime-overlay protocol hash mismatch")
    _, rules_hash = selected_um_rules(rules_artifact)
    if preregistration.get("exchange_rules", {}).get("selected_rules_hash") != rules_hash:
        raise ValueError("regime-overlay exchange-rules hash mismatch")
    lessons = load_live_lessons_evidence(live_lessons_path)
    if preregistration.get("live_lessons", {}).get("artifact_sha256") != lessons["artifact_sha256"]:
        raise ValueError("regime-overlay live-lessons hash mismatch")
    base_path = Path(base_preregistration_path).expanduser()
    base = json.loads(base_path.read_text(encoding="utf-8"))
    _validated_base_preregistration(base)
    if preregistration.get("base_preregistration", {}).get("artifact_sha256") != file_sha256(base_path):
        raise ValueError("regime-overlay base-preregistration hash mismatch")
    prior = _load_prior_risk_tier(prior_risk_tier_path)
    if preregistration.get("prior_risk_tier", {}).get("artifact_sha256") != prior["artifact_sha256"]:
        raise ValueError("regime-overlay prior risk-tier hash mismatch")


def write_regime_overlay_preregistration_artifact(
    settings: Settings, payload: dict[str, Any], *, explicit_path: str | None = None
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-regime-overlay-preregistration",
        path_key="artifact_path",
        default_filename="mini_trend_um_regime_overlay_preregistration.json",
        explicit_path=explicit_path,
    )
