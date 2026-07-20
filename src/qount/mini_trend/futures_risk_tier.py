"""Preregistered single-variable return/risk tier for the no-carry UM base strategy."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from qount.artifacts import write_research_json_artifact
from qount.mini_trend.config import MiniTrendConfig
from qount.mini_trend.forward import TOP3, frozen_top3_config
from qount.mini_trend.futures_base_forward import BASE_FORWARD_PREREG_VERSION
from qount.mini_trend.futures_base_forward import FUTURES_BASE_FORWARD_PROTOCOL
from qount.mini_trend.futures_recovery import canonical_hash
from qount.mini_trend.futures_recovery import load_live_lessons_evidence, selected_um_rules
from qount.models import utc_now
from qount.settings import Settings


RISK_TIER_PREREG_VERSION = "mini_trend_um_risk_tier_preregistration_v0.2"


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def risk_tier_config() -> MiniTrendConfig:
    return replace(
        frozen_top3_config(),
        strategy="MiniTrend-UM-RiskTier-v0.2",
        vol_target=0.020,
    )


@dataclass(frozen=True)
class FuturesRiskTierProtocol:
    strategy: str = "MiniTrend-UM-RiskTier-v0.2"
    capital_usdt: float = 400.0
    market: str = "um"
    interval: str = "1d"
    control_vol_target: float = 0.015
    candidate_vol_target: float = 0.020
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
        control = frozen_top3_config()
        candidate = risk_tier_config()
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
                "config": asdict(control),
            },
            "candidate": {
                "config": asdict(candidate),
                "single_variable_change": {
                    "field": "vol_target",
                    "control": self.control_vol_target,
                    "candidate": self.candidate_vol_target,
                },
                "interpretation": "risk-budget tier only; not a new alpha claim",
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
                "maximum_sharpe_degradation": 0.03,
                "maximum_full_window_drawdown_pct": 25.0,
                "maximum_segment_drawdown_worsening_percentage_points": 5.0,
                "minimum_worst_segment_return_pct": -5.0,
                "maximum_average_effective_gross": 0.30,
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


FUTURES_RISK_TIER_PROTOCOL = FuturesRiskTierProtocol()


def _validated_base_preregistration(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != BASE_FORWARD_PREREG_VERSION:
        raise ValueError("risk tier requires current UM base v0.2 preregistration")
    contract_hash = payload.get("decision_contract", {}).get("contract_hash")
    if contract_hash != FUTURES_BASE_FORWARD_PROTOCOL.contract_hash:
        raise ValueError("UM base preregistration contract hash mismatch")


def build_risk_tier_preregistration(
    rules_artifact: Mapping[str, Any],
    live_lessons_path: str | Path,
    base_preregistration_path: str | Path,
) -> dict[str, Any]:
    selected, rules_hash = selected_um_rules(rules_artifact)
    lessons = load_live_lessons_evidence(live_lessons_path)
    base_path = Path(base_preregistration_path).expanduser()
    base = json.loads(base_path.read_text(encoding="utf-8"))
    _validated_base_preregistration(base)
    protocol = FUTURES_RISK_TIER_PROTOCOL
    return {
        "schema_version": RISK_TIER_PREREG_VERSION,
        "artifact_type": "mini_trend_um_risk_tier_preregistration",
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
        "live_lessons": lessons,
    }


def validate_risk_tier_registration(
    preregistration: Mapping[str, Any],
    rules_artifact: Mapping[str, Any],
    live_lessons_path: str | Path,
    base_preregistration_path: str | Path,
) -> None:
    protocol = FUTURES_RISK_TIER_PROTOCOL
    if preregistration.get("schema_version") != RISK_TIER_PREREG_VERSION:
        raise ValueError("unexpected risk-tier preregistration schema")
    if preregistration.get("decision_contract", {}).get("contract_hash") != protocol.contract_hash:
        raise ValueError("risk-tier contract hash mismatch")
    if preregistration.get("protocol", {}).get("protocol_hash") != protocol.protocol_hash:
        raise ValueError("risk-tier protocol hash mismatch")
    _, rules_hash = selected_um_rules(rules_artifact)
    if preregistration.get("exchange_rules", {}).get("selected_rules_hash") != rules_hash:
        raise ValueError("risk-tier exchange-rules hash mismatch")
    lessons = load_live_lessons_evidence(live_lessons_path)
    if preregistration.get("live_lessons", {}).get("artifact_sha256") != lessons["artifact_sha256"]:
        raise ValueError("risk-tier live-lessons hash mismatch")
    base_path = Path(base_preregistration_path).expanduser()
    base = json.loads(base_path.read_text(encoding="utf-8"))
    _validated_base_preregistration(base)
    if preregistration.get("base_preregistration", {}).get("artifact_sha256") != file_sha256(base_path):
        raise ValueError("risk-tier base-preregistration hash mismatch")


def write_risk_tier_preregistration_artifact(
    settings: Settings, payload: dict[str, Any], *, explicit_path: str | None = None
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-risk-tier-preregistration",
        path_key="artifact_path",
        default_filename="mini_trend_um_risk_tier_preregistration.json",
        explicit_path=explicit_path,
    )
