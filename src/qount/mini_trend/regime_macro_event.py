"""Event-driven H.4.1 confirmation of MiniTrend trend-gate transitions."""

from __future__ import annotations

import datetime as dt
from bisect import bisect_right
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.research_data.market_data import Bar, Funding
from qount.mini_trend.forward import TOP3, frozen_top3_config
from qount.mini_trend.futures_base_forward import FUTURES_BASE_FORWARD_PROTOCOL
from qount.mini_trend.futures_funding_veto_robustness import paired_moving_block_bootstrap
from qount.mini_trend.futures_recovery import canonical_hash, selected_um_rules
from qount.mini_trend.futures_recovery_backtest import run_variant
from qount.mini_trend.regime_adaptation_ablation import _benchmark_returns
from qount.mini_trend.regime_adaptation_ablation import _beta_residual
from qount.mini_trend.regime_adaptation_ablation import _comparison
from qount.mini_trend.regime_adaptation_ablation import _data_hash
from qount.mini_trend.regime_adaptation_ablation import _summarize
from qount.mini_trend.signals import target_weights
from qount.models import utc_now
from qount.settings import Settings


MACRO_EVENT_PREREG_VERSION = "mini_trend_h41_event_gate_preregistration_v0.1"
MACRO_EVENT_REPORT_VERSION = "mini_trend_h41_event_gate_ablation_v0.1"
MACRO_FEATURE = "fed_assets_4w_change_pct"


@dataclass(frozen=True)
class MacroEventSpec:
    trial_id: str
    block_new_entries_during_contraction: bool
    delay_master_gate_exit_during_expansion: bool


MACRO_EVENT_SPECS = (
    MacroEventSpec("macro_contraction_blocks_new_entries", True, False),
    MacroEventSpec("macro_expansion_delays_master_gate_exit", False, True),
    MacroEventSpec("macro_dual_trend_confirmation", True, True),
)


@dataclass(frozen=True)
class MacroEventConfig:
    prior_family_trial_count: int = 138
    maximum_return_degradation_percentage_points: float = 3.0
    minimum_drawdown_improvement_percentage_points: float = 0.5
    minimum_nonnegative_annual_delta_count: int = 4
    bootstrap_block_days: int = 20
    bootstrap_samples: int = 5_000
    bootstrap_seed: int = 20260718
    minimum_bootstrap_sharpe_win_probability: float = 0.90
    minimum_bootstrap_drawdown_win_probability: float = 0.75

    @property
    def trial_count(self) -> int:
        return len(MACRO_EVENT_SPECS)

    @property
    def cumulative_trial_count(self) -> int:
        return self.prior_family_trial_count + self.trial_count

    @property
    def contract_hash(self) -> str:
        return canonical_hash(
            {
                "config": asdict(self),
                "specs": [asdict(spec) for spec in MACRO_EVENT_SPECS],
                "macro_feature": MACRO_FEATURE,
                "macro_state": "expansion if 4-week change >= 0, contraction otherwise",
                "timing": "latest H.4.1 release decision_date as-of each completed market day",
                "mechanism": (
                    "confirm only Base entry/master-gate exit events; never continuously scale risk"
                ),
                "base_vol_target_unchanged": frozen_top3_config().vol_target,
                "parameter_search_allowed": False,
                "carry_allowed": False,
                "shorting_allowed": False,
                "maximum_effective_gross": 1.0,
                "paper_or_live_allowed": False,
            }
        )


class MacroEventTransform:
    def __init__(self, features: Sequence[Mapping[str, Any]], spec: MacroEventSpec):
        rows = sorted(features, key=lambda row: str(row["decision_date"]))
        self._dates = [dt.date.fromisoformat(str(row["decision_date"])) for row in rows]
        if not rows or self._dates != sorted(self._dates) or len(self._dates) != len(set(self._dates)):
            raise ValueError("H.4.1 feature dates must be nonempty, unique, and increasing")
        self._rows = [dict(row) for row in rows]
        self._spec = spec
        self._last_macro_decision_date: str | None = None
        self.source_update_count = 0
        self.entry_block_symbol_count = 0
        self.exit_delay_symbol_count = 0
        self.intervention_bar_count = 0
        self._last: dict[str, Any] = {}

    def __call__(
        self,
        bars: Mapping[str, Sequence[Bar]],
        config,
        desired: Mapping[str, float],
        previous: Mapping[str, float],
    ) -> Mapping[str, float]:
        decision_date = dt.date.fromisoformat(bars["BTCUSDT"][-1].date)
        index = bisect_right(self._dates, decision_date) - 1
        if index < 0:
            raise ValueError(f"missing causal H.4.1 state for {decision_date}")
        macro = self._rows[index]
        macro_decision_date = str(macro["decision_date"])
        source_updated = macro_decision_date != self._last_macro_decision_date
        if source_updated:
            self.source_update_count += 1
            self._last_macro_decision_date = macro_decision_date
        value = float(macro[MACRO_FEATURE])
        contraction = value < 0.0
        result = {symbol: float(desired[symbol]) for symbol in TOP3}
        base = target_weights(bars, config)
        entry_blocks = 0
        exit_delays = 0
        if self._spec.block_new_entries_during_contraction and contraction:
            for symbol in TOP3:
                if previous[symbol] <= 0.0 and result[symbol] > 0.0:
                    result[symbol] = 0.0
                    entry_blocks += 1
        if (
            self._spec.delay_master_gate_exit_during_expansion
            and not contraction
            and not base.gate.risk_on
        ):
            for symbol in TOP3:
                if previous[symbol] > 0.0 and result[symbol] <= 0.0:
                    result[symbol] = float(previous[symbol])
                    exit_delays += 1
        intervened = entry_blocks > 0 or exit_delays > 0
        self.entry_block_symbol_count += entry_blocks
        self.exit_delay_symbol_count += exit_delays
        self.intervention_bar_count += int(intervened)
        self._last = {
            "decision_date": decision_date.isoformat(),
            "macro_decision_date": macro_decision_date,
            "macro_release_date": macro["release_date"],
            "macro_observation_date": macro["observation_date"],
            "macro_value": value,
            "macro_state": "contraction" if contraction else "expansion",
            "source_updated": source_updated,
            "base_master_gate_risk_on": base.gate.risk_on,
            "entry_block_symbol_count": entry_blocks,
            "exit_delay_symbol_count": exit_delays,
            "intervened": intervened,
        }
        return result

    def state_snapshot(self) -> dict[str, Any]:
        return dict(self._last)


def _validate_h41_dataset(h41_dataset: Mapping[str, Any]) -> None:
    if h41_dataset.get("diagnostics", {}).get("verdict") != "pass_point_in_time_macro_dataset":
        raise ValueError("H.4.1 dataset did not pass its point-in-time gate")
    if h41_dataset.get("meta", {}).get("point_in_time") is not True:
        raise ValueError("H.4.1 dataset is not marked point-in-time")
    if not h41_dataset.get("weekly_features"):
        raise ValueError("H.4.1 dataset has no weekly features")


def build_macro_event_preregistration(
    h41_dataset: Mapping[str, Any],
    rules_artifact: Mapping[str, Any],
    config: MacroEventConfig | None = None,
) -> dict[str, Any]:
    config = config or MacroEventConfig()
    _validate_h41_dataset(h41_dataset)
    _, rules_hash = selected_um_rules(rules_artifact)
    return {
        "schema_version": MACRO_EVENT_PREREG_VERSION,
        "artifact_type": "mini_trend_h41_event_gate_preregistration",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "consumed_historical_discovery_pool",
            "strategy_results_evaluated": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "contract": {
            **asdict(config),
            "trial_count": config.trial_count,
            "cumulative_trial_count": config.cumulative_trial_count,
            "specs": [asdict(spec) for spec in MACRO_EVENT_SPECS],
            "contract_hash": config.contract_hash,
        },
        "source": {
            "h41_contract_hash": h41_dataset["contract"]["contract_hash"],
            "h41_data_hash": h41_dataset["data_hash"],
            "exchange_rules_hash": rules_hash,
        },
    }


def validate_macro_event_preregistration(
    preregistration: Mapping[str, Any],
    h41_dataset: Mapping[str, Any],
    rules_artifact: Mapping[str, Any],
    config: MacroEventConfig,
) -> None:
    if preregistration.get("schema_version") != MACRO_EVENT_PREREG_VERSION:
        raise ValueError("unexpected macro-event preregistration schema")
    if preregistration.get("contract", {}).get("contract_hash") != config.contract_hash:
        raise ValueError("macro-event contract hash mismatch")
    _validate_h41_dataset(h41_dataset)
    _, rules_hash = selected_um_rules(rules_artifact)
    source = preregistration.get("source", {})
    if source.get("h41_data_hash") != h41_dataset.get("data_hash"):
        raise ValueError("macro-event H.4.1 data hash mismatch")
    if source.get("exchange_rules_hash") != rules_hash:
        raise ValueError("macro-event exchange rules hash mismatch")


def build_macro_event_report(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    rules_artifact: Mapping[str, Any],
    h41_dataset: Mapping[str, Any],
    preregistration: Mapping[str, Any],
    config: MacroEventConfig | None = None,
) -> dict[str, Any]:
    config = config or MacroEventConfig()
    validate_macro_event_preregistration(
        preregistration, h41_dataset, rules_artifact, config
    )
    rules, rules_hash = selected_um_rules(rules_artifact)
    common = {
        "recovery_enabled": False,
        "base_config": frozen_top3_config(),
        "daily_chandelier_atr_multiple": (
            FUTURES_BASE_FORWARD_PROTOCOL.daily_chandelier_atr_multiple
        ),
        "stop_cooldown_completed_bars": (
            FUTURES_BASE_FORWARD_PROTOCOL.stop_cooldown_completed_bars
        ),
        "gross_cap_policy": "renormalize_active_targets_with_filter_floors",
    }
    control_result = run_variant(bars_by_symbol, funding_by_symbol, rules, **common)
    control = _summarize(control_result)
    benchmark = _benchmark_returns(
        control_result.equity, bars_by_symbol, funding_by_symbol
    )
    control_returns = [float(row["net_return"]) for row in control_result.equity]
    control["beta_residual"] = {
        name: _beta_residual(control_returns, values)
        for name, values in benchmark.items()
    }
    trials = []
    for spec in MACRO_EVENT_SPECS:
        transform = MacroEventTransform(h41_dataset["weekly_features"], spec)
        result = run_variant(
            bars_by_symbol,
            funding_by_symbol,
            rules,
            desired_weights_transform=transform,
            **common,
        )
        candidate = _summarize(result)
        candidate_returns = [float(row["net_return"]) for row in result.equity]
        candidate["beta_residual"] = {
            name: _beta_residual(candidate_returns, values)
            for name, values in benchmark.items()
        }
        comparison = _comparison(candidate, control)
        bootstrap = paired_moving_block_bootstrap(
            control_returns,
            candidate_returns,
            block_length=config.bootstrap_block_days,
            samples=config.bootstrap_samples,
            seed=config.bootstrap_seed,
            periods_per_year=365.0,
        )
        probabilities = bootstrap["win_probabilities"]
        gates = {
            "base_vol_target_unchanged": all(
                float(row["execution_state"]["active_vol_target"])
                == frozen_top3_config().vol_target
                for row in result.equity
            ),
            "maximum_effective_gross_at_most_one": (
                candidate["maximum_effective_gross"] <= 1.0
            ),
            "turnover_batches_not_higher": (
                candidate["decision_batch_count"] <= control["decision_batch_count"]
            ),
            "trading_cost_not_higher": (
                candidate["trading_cost_usdt"] <= control["trading_cost_usdt"]
            ),
            "minimum_drawdown_improvement": (
                comparison["drawdown_improvement_percentage_points"]
                >= config.minimum_drawdown_improvement_percentage_points
            ),
            "sharpe_not_lower": candidate["sharpe"] >= control["sharpe"],
            "maximum_return_degradation": (
                comparison["return_delta_percentage_points"]
                >= -config.maximum_return_degradation_percentage_points
            ),
            "minimum_nonnegative_annual_delta_count": (
                comparison["nonnegative_annual_delta_count"]
                >= config.minimum_nonnegative_annual_delta_count
            ),
            "bootstrap_sharpe_win_probability": (
                probabilities["candidate_sharpe_above_reference"]
                >= config.minimum_bootstrap_sharpe_win_probability
            ),
            "bootstrap_drawdown_win_probability": (
                probabilities["candidate_max_drawdown_below_reference"]
                >= config.minimum_bootstrap_drawdown_win_probability
            ),
            "execution_contract_clean": (
                candidate["runtime_filter_coverage"] == 1.0
                and candidate["duplicate_decision_count"] == 0
                and candidate["same_bar_stop_reentry_count"] == 0
            ),
        }
        trials.append(
            {
                "trial_id": spec.trial_id,
                "spec": asdict(spec),
                "event_audit": {
                    "macro_source_update_count": transform.source_update_count,
                    "intervention_bar_count": transform.intervention_bar_count,
                    "entry_block_symbol_count": transform.entry_block_symbol_count,
                    "exit_delay_symbol_count": transform.exit_delay_symbol_count,
                },
                "candidate": candidate,
                "comparison": comparison,
                "paired_block_bootstrap": bootstrap,
                "gates": gates,
                "passed_gate_count": sum(gates.values()),
                "gate_count": len(gates),
                "verdict": (
                    "retain_macro_event_gate_candidate"
                    if all(gates.values())
                    else "reject_macro_event_gate_candidate"
                ),
            }
        )
    ranked = sorted(
        trials,
        key=lambda row: (
            row["passed_gate_count"],
            row["comparison"]["sharpe_delta"],
            row["comparison"]["drawdown_improvement_percentage_points"],
            row["comparison"]["return_delta_percentage_points"],
        ),
        reverse=True,
    )
    retained = [row for row in ranked if row["verdict"].startswith("retain_")]
    return {
        "schema_version": MACRO_EVENT_REPORT_VERSION,
        "artifact_type": "mini_trend_h41_event_gate_ablation",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "consumed_historical_discovery_pool",
            "network_download_used": False,
            "private_exchange_data": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "contract": preregistration["contract"],
        "lineage": {
            "preregistration_hash": canonical_hash(preregistration),
            "h41_contract_hash": h41_dataset["contract"]["contract_hash"],
            "h41_data_hash": h41_dataset["data_hash"],
            "market_data_hash": _data_hash(bars_by_symbol, funding_by_symbol),
            "exchange_rules_hash": rules_hash,
        },
        "control": control,
        "trials": trials,
        "ranking": [row["trial_id"] for row in ranked],
        "retained_trial_ids": [row["trial_id"] for row in retained],
        "diagnostics": {
            "trial_count": len(trials),
            "cumulative_trial_count": config.cumulative_trial_count,
            "retained_trial_count": len(retained),
            "verdict": (
                "retain_h41_event_gate_for_future_only_research"
                if retained
                else "reject_h41_event_gate_ablation"
            ),
            "paper_or_live_allowed": False,
        },
    }


def write_macro_event_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-h41-event-gate",
        path_key="artifact_path",
        default_filename="mini_trend_h41_event_gate.json",
        explicit_path=explicit_path,
    )
