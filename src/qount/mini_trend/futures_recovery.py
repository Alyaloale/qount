"""Preregistered low-frequency USD-M futures recovery candidate."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from qount.artifacts import write_research_json_artifact
from qount.mini_trend.forward import TOP3, frozen_top3_config
from qount.mini_trend.live_lessons import LIVE_LESSONS_VERSION
from qount.models import utc_now
from qount.settings import Settings


FUTURES_RECOVERY_PREREG_VERSION = "mini_trend_um_recovery_preregistration_v0.1"


def canonical_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class FuturesRecoveryProtocol:
    strategy: str = "MiniTrend-UM-Recovery-v0.1"
    capital_usdt: float = 400.0
    market: str = "um"
    interval: str = "1d"
    direction: str = "long_cash"
    maximum_effective_gross: float = 1.0
    recovery_sma: int = 20
    recovery_confirmation_bars: int = 3
    recovery_breadth: float = 2.0 / 3.0
    recovery_maximum_gross: float = 0.25
    filter_buffer: float = 1.05
    daily_chandelier_atr_multiple: float = 3.0
    stop_cooldown_completed_bars: int = 3
    taker_fee_bps: float = 10.0
    slippage_bps: float = 2.0
    forward_start_date: str = "2026-07-17"

    @property
    def historical_diagnostic_windows(self) -> tuple[dict[str, str], ...]:
        return (
            {"label": "2021-2022", "warmup_start": "2021-01-01", "start": "2021-07-20", "end": "2022-12-31"},
            {"label": "2023-2024", "warmup_start": "2023-01-01", "start": "2023-07-20", "end": "2024-12-31"},
            {"label": "2025-2026", "warmup_start": "2025-01-01", "start": "2025-07-20", "end": "2026-05-31"},
        )

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
                "source": "Binance public monthly dumps from existing local cache",
                "market": self.market,
                "interval": self.interval,
                "completed_daily_bars_only": True,
                "funding_included": True,
                "private_exchange_data": False,
                "direct_home_proxy_bulk_download_allowed": False,
                "bulk_download_route": "owner-approved Liangxin Cloud proxy with repo-external credentials",
            },
            "base_signal_config": asdict(frozen_top3_config()),
            "recovery_overlay": {
                "active_only_when_base_master_gate_closed": True,
                "sma": self.recovery_sma,
                "confirmation_bars": self.recovery_confirmation_bars,
                "btc_confirmation_required": True,
                "breadth_required": self.recovery_breadth,
                "maximum_gross": self.recovery_maximum_gross,
            },
            "execution": {
                "direction": self.direction,
                "maximum_effective_gross": self.maximum_effective_gross,
                "leverage_boost_allowed": False,
                "shorting_allowed": False,
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
            "control": "same UM TOP3 base signal, costs, funding, filters and stop state without recovery overlay",
        }

    @property
    def contract_hash(self) -> str:
        return canonical_hash(self.contract_basis)

    @property
    def protocol_basis(self) -> dict[str, Any]:
        return {
            "contract_hash": self.contract_hash,
            "holdout_role": "consumed_historical_diagnostic_then_new_forward",
            "historical_diagnostic_windows": list(self.historical_diagnostic_windows),
            "forward_start_date": self.forward_start_date,
            "historical_pass_gates": {
                "positive_incremental_net_return_segments": 2,
                "maximum_drawdown_worsening_percentage_points": 2.0,
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
            "promotion_rule": (
                "Historical diagnostic can reject the candidate but cannot promote it. "
                "Only bars on or after forward_start_date may support a later paper-readiness review."
            ),
        }

    @property
    def protocol_hash(self) -> str:
        return canonical_hash(self.protocol_basis)


FUTURES_RECOVERY_PROTOCOL = FuturesRecoveryProtocol()


def selected_um_rules(rules_artifact: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], str]:
    if rules_artifact.get("market") != "um":
        raise ValueError("futures recovery requires UM exchange rules")
    if rules_artifact.get("source_type") != "runtime_exchange_info":
        raise ValueError("futures recovery requires runtime exchangeInfo rules")
    indexed = {
        str(row.get("symbol", "")).upper(): dict(row)
        for row in rules_artifact.get("rules", [])
        if isinstance(row, Mapping) and row.get("symbol")
    }
    missing = sorted(set(TOP3) - set(indexed))
    if missing:
        raise ValueError(f"UM exchange rules missing TOP3 symbols: {','.join(missing)}")
    selected = {symbol: indexed[symbol] for symbol in TOP3}
    non_trading = [symbol for symbol, row in selected.items() if row.get("status") != "TRADING"]
    if non_trading:
        raise ValueError(f"UM symbols not trading: {','.join(non_trading)}")
    return selected, canonical_hash(selected)


def load_live_lessons_evidence(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("schema_version") != LIVE_LESSONS_VERSION:
        raise ValueError("unexpected live-lessons schema")
    if payload.get("verdict") != "audit_complete_research_only":
        raise ValueError("live-lessons audit is not complete")
    constraints = payload.get("candidate_constraints", {})
    if constraints.get("carry_allowed") is not False or constraints.get("market") != "um_futures":
        raise ValueError("live-lessons constraints do not bind no-carry UM futures")
    return {
        "artifact_path": str(source),
        "artifact_sha256": file_sha256(source),
        "strategy_return_pre_withdrawal_pct": payload["equity"][
            "inception_to_pre_withdrawal_return_pct"
        ],
        "july_rebound_giveback_usdt": payload["equity"]["july_rebound_giveback_usdt"],
        "post_inception_placed_order_count": payload["orders"]["post_inception_placed_order_count"],
        "exact_duplicate_order_count": payload["orders"]["exact_duplicate_order_count"],
        "same_bar_direction_flip_group_count": payload["orders"][
            "same_bar_direction_flip_group_count"
        ],
        "fail_closed_unknown_capital_count": payload["operations"][
            "fail_closed_unknown_capital_count"
        ],
    }


def build_futures_recovery_preregistration(
    rules_artifact: Mapping[str, Any],
    live_lessons_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    protocol = FUTURES_RECOVERY_PROTOCOL
    selected, rules_hash = selected_um_rules(rules_artifact)
    return {
        "schema_version": FUTURES_RECOVERY_PREREG_VERSION,
        "artifact_type": "mini_trend_um_recovery_preregistration",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "strategy_results_evaluated": False,
            "existing_cache_only": True,
            "private_exchange_data": False,
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
        "live_lessons": dict(live_lessons_evidence),
    }


def validate_futures_recovery_registration(
    preregistration: Mapping[str, Any],
    rules_artifact: Mapping[str, Any],
    live_lessons_evidence: Mapping[str, Any],
) -> None:
    protocol = FUTURES_RECOVERY_PROTOCOL
    _, rules_hash = selected_um_rules(rules_artifact)
    if preregistration.get("schema_version") != FUTURES_RECOVERY_PREREG_VERSION:
        raise ValueError("unexpected futures-recovery preregistration schema")
    if preregistration.get("decision_contract", {}).get("contract_hash") != protocol.contract_hash:
        raise ValueError("futures-recovery contract hash mismatch")
    if preregistration.get("protocol", {}).get("protocol_hash") != protocol.protocol_hash:
        raise ValueError("futures-recovery protocol hash mismatch")
    if preregistration.get("exchange_rules", {}).get("selected_rules_hash") != rules_hash:
        raise ValueError("futures-recovery exchange-rules hash mismatch")
    if preregistration.get("live_lessons", {}).get("artifact_sha256") != live_lessons_evidence.get(
        "artifact_sha256"
    ):
        raise ValueError("futures-recovery live-lessons hash mismatch")


def write_futures_recovery_preregistration_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-recovery-preregistration",
        path_key="artifact_path",
        default_filename="mini_trend_um_recovery_preregistration.json",
        explicit_path=explicit_path,
    )
