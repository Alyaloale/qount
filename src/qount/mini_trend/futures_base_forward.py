"""Future-only preregistration for the no-carry UM base trend control."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from qount.artifacts import write_research_json_artifact
from qount.mini_trend.forward import TOP3, frozen_top3_config
from qount.mini_trend.futures_recovery import load_live_lessons_evidence, selected_um_rules
from qount.models import utc_now
from qount.settings import Settings


BASE_FORWARD_PREREG_VERSION = "mini_trend_um_base_forward_preregistration_v0.2"


def _hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class FuturesBaseForwardProtocol:
    strategy: str = "MiniTrend-UM-Base-v0.2"
    capital_usdt: float = 400.0
    market: str = "um"
    interval: str = "1d"
    forward_start_date: str = "2026-07-17"
    minimum_forward_bars: int = 60
    minimum_active_bars: int = 10
    maximum_forward_drawdown_pct: float = 15.0
    maximum_fee_to_notional_pct: float = 0.12
    taker_fee_bps: float = 10.0
    slippage_bps: float = 2.0
    filter_buffer: float = 1.05
    daily_chandelier_atr_multiple: float = 3.0
    stop_cooldown_completed_bars: int = 3

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
                "source": "Binance public UM daily klines + funding",
                "market": self.market,
                "interval": self.interval,
                "forward_start_date": self.forward_start_date,
                "completed_daily_bars_only": True,
                "funding_included": True,
                "private_exchange_data": False,
            },
            "signal": {
                "universe": list(TOP3),
                "config": asdict(frozen_top3_config()),
                "recovery_overlay": False,
            },
            "execution": {
                "direction": "long_cash",
                "maximum_effective_gross": 1.0,
                "shorting_allowed": False,
                "leverage_boost_allowed": False,
                "one_decision_per_completed_bar": True,
                "runtime_filter_coverage_required": 1.0,
                "filter_buffer": self.filter_buffer,
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
        return _hash(self.contract_basis)

    @property
    def protocol_basis(self) -> dict[str, Any]:
        return {
            "contract_hash": self.contract_hash,
            "holdout_role": "future_only_forward_monitoring",
            "minimum_forward_bars": self.minimum_forward_bars,
            "minimum_active_bars": self.minimum_active_bars,
            "maximum_forward_drawdown_pct": self.maximum_forward_drawdown_pct,
            "maximum_fee_to_notional_pct": self.maximum_fee_to_notional_pct,
            "required_filter_coverage": 1.0,
            "trial_count": 1,
            "parameter_search_allowed": False,
            "universe_search_allowed": False,
            "high_frequency_data_allowed": False,
            "paper_or_live_allowed": False,
            "interpretation": "A forward control readout, not an alpha promotion claim.",
        }

    @property
    def protocol_hash(self) -> str:
        return _hash(self.protocol_basis)


FUTURES_BASE_FORWARD_PROTOCOL = FuturesBaseForwardProtocol()


def build_futures_base_forward_preregistration(
    rules_artifact: Mapping[str, Any], live_lessons_path: str | Path
) -> dict[str, Any]:
    selected, rules_hash = selected_um_rules(rules_artifact)
    lessons = load_live_lessons_evidence(live_lessons_path)
    protocol = FUTURES_BASE_FORWARD_PROTOCOL
    return {
        "schema_version": BASE_FORWARD_PREREG_VERSION,
        "artifact_type": "mini_trend_um_base_forward_preregistration",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "strategy_results_evaluated": False,
            "future_only": True,
            "existing_cache_only_at_registration": True,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "decision_contract": {**protocol.contract_basis, "contract_hash": protocol.contract_hash},
        "protocol": {**protocol.protocol_basis, "protocol_hash": protocol.protocol_hash},
        "exchange_rules": {
            "selected_rules_hash": rules_hash,
            "raw_exchange_info_hash": rules_artifact.get("raw_exchange_info_hash"),
            "rules": [selected[symbol] for symbol in TOP3],
        },
        "live_lessons": lessons,
    }


def write_futures_base_forward_preregistration_artifact(
    settings: Settings, payload: dict[str, Any], *, explicit_path: str | None = None
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-base-forward-preregistration",
        path_key="artifact_path",
        default_filename="mini_trend_um_base_forward_preregistration.json",
        explicit_path=explicit_path,
    )
