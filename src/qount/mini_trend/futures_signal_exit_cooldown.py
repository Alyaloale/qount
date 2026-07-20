"""Reuse the frozen three-bar cooldown after a per-symbol trend exit."""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.grid.data import Bar, Funding
from qount.mini_trend.forward import TOP3, frozen_top3_config
from qount.mini_trend.futures_base_episode_attribution import BASE_EPISODE_REPORT_VERSION
from qount.mini_trend.futures_base_episode_attribution import extract_base_episodes
from qount.mini_trend.futures_base_episode_attribution import _summary as _episode_summary
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


SIGNAL_EXIT_COOLDOWN_PREREG_VERSION = "mini_trend_um_signal_exit_cooldown_preregistration_v0.1"
SIGNAL_EXIT_COOLDOWN_REPORT_VERSION = "mini_trend_um_signal_exit_cooldown_ablation_v0.1"
SIGNAL_EXIT_REASON = "signal_or_allocation_exit"


@dataclass(frozen=True)
class SignalExitCooldownConfig:
    prior_family_trial_count: int = 142
    cooldown_completed_bars: int = (
        FUTURES_BASE_FORWARD_PROTOCOL.stop_cooldown_completed_bars
    )
    maximum_drawdown_worsening_percentage_points: float = 0.5
    minimum_nonnegative_annual_delta_count: int = 3
    bootstrap_block_days: int = 20
    bootstrap_samples: int = 5_000
    bootstrap_seed: int = 20260718
    minimum_bootstrap_terminal_return_win_probability: float = 0.75
    minimum_bootstrap_sharpe_win_probability: float = 0.90
    minimum_bootstrap_drawdown_win_probability: float = 0.75

    @property
    def trial_count(self) -> int:
        return 1

    @property
    def cumulative_trial_count(self) -> int:
        return self.prior_family_trial_count + self.trial_count

    @property
    def contract_hash(self) -> str:
        return canonical_hash(
            {
                "config": asdict(self),
                "strategy": FUTURES_BASE_FORWARD_PROTOCOL.strategy,
                "trigger": (
                    "previous target positive, current Base desired target zero, and Base master "
                    "gate remains risk-on"
                ),
                "action": (
                    "block only that symbol's new entry for the same three completed bars already "
                    "used by the frozen chandelier stop cooldown"
                ),
                "master_gate_exit_unchanged": True,
                "chandelier_stop_unchanged": True,
                "base_risk_target_unchanged": True,
                "new_numeric_parameters": 0,
                "parameter_search_allowed": False,
                "carry_allowed": False,
                "shorting_allowed": False,
                "maximum_effective_gross": 1.0,
                "paper_or_live_allowed": False,
            }
        )


class SignalExitCooldownTransform:
    def __init__(self, cooldown_completed_bars: int) -> None:
        if cooldown_completed_bars < 1:
            raise ValueError("signal-exit cooldown must be positive")
        self._cooldown_bars = cooldown_completed_bars
        self._step = -1
        self._cooldown_until: dict[str, int] = {}
        self._trigger_count = 0
        self._blocked_symbol_bar_count = 0
        self._events: list[dict[str, Any]] = []
        self._last: dict[str, Any] = {}

    def __call__(
        self,
        bars: Mapping[str, Sequence[Bar]],
        config,
        desired: Mapping[str, float],
        previous: Mapping[str, float],
    ) -> Mapping[str, float]:
        self._step += 1
        date = bars["BTCUSDT"][-1].date
        signal = target_weights(bars, config)
        result = {symbol: float(desired[symbol]) for symbol in TOP3}
        triggered = []
        if signal.gate.risk_on:
            for symbol in TOP3:
                if float(previous[symbol]) > 0 and result[symbol] <= 0:
                    self._cooldown_until[symbol] = self._step + self._cooldown_bars
                    self._trigger_count += 1
                    triggered.append(symbol)
                    self._events.append(
                        {
                            "decision_date": date,
                            "symbol": symbol,
                            "event": "signal_exit_cooldown_started",
                        }
                    )
        blocked = []
        for symbol in TOP3:
            if result[symbol] > 0 and self._step <= self._cooldown_until.get(symbol, -1):
                result[symbol] = 0.0
                blocked.append(symbol)
                self._blocked_symbol_bar_count += 1
                self._events.append(
                    {
                        "decision_date": date,
                        "symbol": symbol,
                        "event": "signal_exit_reentry_blocked",
                    }
                )
        self._cooldown_until = {
            symbol: release
            for symbol, release in self._cooldown_until.items()
            if self._step <= release
        }
        self._last = {
            "decision_date": date,
            "base_master_gate_risk_on": signal.gate.risk_on,
            "triggered_symbols": sorted(triggered),
            "blocked_symbols": sorted(blocked),
            "cooldown_remaining": {
                symbol: max(release - self._step, 0)
                for symbol, release in sorted(self._cooldown_until.items())
            },
        }
        return result

    def state_snapshot(self) -> dict[str, Any]:
        return dict(self._last)

    def summary(self) -> dict[str, Any]:
        return {
            "cooldown_completed_bars": self._cooldown_bars,
            "signal_exit_trigger_count": self._trigger_count,
            "blocked_entry_symbol_bar_count": self._blocked_symbol_bar_count,
            "events": list(self._events),
        }


def rapid_reentry_audit(
    episode_artifact: Mapping[str, Any], cooldown_completed_bars: int
) -> dict[str, Any]:
    if episode_artifact.get("schema_version") != BASE_EPISODE_REPORT_VERSION:
        raise ValueError("unexpected Base episode attribution schema")
    if episode_artifact.get("diagnostics", {}).get("verdict") != "base_episode_attribution_complete":
        raise ValueError("Base episode attribution is incomplete")
    if SIGNAL_EXIT_REASON not in episode_artifact.get("diagnostics", {}).get(
        "qualified_exit_reasons", []
    ):
        raise ValueError("Base episode attribution did not qualify signal exits")
    by_symbol = {
        symbol: sorted(
            [row for row in episode_artifact.get("episodes", []) if row["symbol"] == symbol],
            key=lambda row: row["entry_date"],
        )
        for symbol in TOP3
    }
    all_pairs = []
    rapid = []
    for symbol, rows in by_symbol.items():
        for current, following in zip(rows, rows[1:]):
            if current.get("exit_reason") != SIGNAL_EXIT_REASON:
                continue
            gap = (
                dt.date.fromisoformat(str(following["entry_date"]))
                - dt.date.fromisoformat(str(current["exit_date"]))
            ).days
            item = {
                "symbol": symbol,
                "exit_episode_id": current["episode_id"],
                "exit_date": current["exit_date"],
                "next_episode_id": following["episode_id"],
                "next_entry_date": following["entry_date"],
                "gap_days": gap,
                "next_episode_net_pnl_usdt": following["net_pnl_usdt"],
                "next_episode_holding_bars": following["holding_bars"],
                "next_episode_exit_reason": following["exit_reason"],
            }
            all_pairs.append(item)
            if gap <= cooldown_completed_bars:
                rapid.append(item)
    net = [float(row["next_episode_net_pnl_usdt"]) for row in rapid]
    return {
        "signal_exit_with_following_episode_count": len(all_pairs),
        "rapid_reentry_count": len(rapid),
        "rapid_reentry_positive_count": sum(value > 0 for value in net),
        "rapid_reentry_net_pnl_usdt": round(sum(net), 8),
        "cooldown_completed_bars": cooldown_completed_bars,
        "rows": rapid,
    }


def build_signal_exit_cooldown_preregistration(
    episode_artifact: Mapping[str, Any],
    rules_artifact: Mapping[str, Any],
    config: SignalExitCooldownConfig | None = None,
) -> dict[str, Any]:
    config = config or SignalExitCooldownConfig()
    audit = rapid_reentry_audit(episode_artifact, config.cooldown_completed_bars)
    if audit["rapid_reentry_count"] < 1 or audit["rapid_reentry_net_pnl_usdt"] >= 0:
        raise ValueError("rapid re-entry evidence does not support a cooldown ablation")
    _, rules_hash = selected_um_rules(rules_artifact)
    return {
        "schema_version": SIGNAL_EXIT_COOLDOWN_PREREG_VERSION,
        "artifact_type": "mini_trend_um_signal_exit_cooldown_preregistration",
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
            "contract_hash": config.contract_hash,
        },
        "source": {
            "episode_artifact_hash": canonical_hash(episode_artifact),
            "episode_contract_hash": episode_artifact["contract"]["contract_hash"],
            "exchange_rules_hash": rules_hash,
            "rapid_reentry_audit": audit,
        },
    }


def validate_signal_exit_cooldown_preregistration(
    preregistration: Mapping[str, Any],
    episode_artifact: Mapping[str, Any],
    rules_artifact: Mapping[str, Any],
    config: SignalExitCooldownConfig,
) -> None:
    if preregistration.get("schema_version") != SIGNAL_EXIT_COOLDOWN_PREREG_VERSION:
        raise ValueError("unexpected signal-exit cooldown preregistration schema")
    if preregistration.get("contract", {}).get("contract_hash") != config.contract_hash:
        raise ValueError("signal-exit cooldown contract hash mismatch")
    _, rules_hash = selected_um_rules(rules_artifact)
    source = preregistration.get("source", {})
    if source.get("episode_artifact_hash") != canonical_hash(episode_artifact):
        raise ValueError("signal-exit cooldown episode artifact hash mismatch")
    if source.get("exchange_rules_hash") != rules_hash:
        raise ValueError("signal-exit cooldown exchange-rules hash mismatch")


def build_signal_exit_cooldown_report(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    rules_artifact: Mapping[str, Any],
    episode_artifact: Mapping[str, Any],
    preregistration: Mapping[str, Any],
    config: SignalExitCooldownConfig | None = None,
) -> dict[str, Any]:
    config = config or SignalExitCooldownConfig()
    validate_signal_exit_cooldown_preregistration(
        preregistration, episode_artifact, rules_artifact, config
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
    reference_result = run_variant(
        bars_by_symbol, funding_by_symbol, rules, **common
    )
    transform = SignalExitCooldownTransform(config.cooldown_completed_bars)
    candidate_result = run_variant(
        bars_by_symbol,
        funding_by_symbol,
        rules,
        desired_weights_transform=transform,
        **common,
    )
    reference = _summarize(reference_result)
    candidate = _summarize(candidate_result)
    benchmark = _benchmark_returns(
        reference_result.equity, bars_by_symbol, funding_by_symbol
    )
    reference_returns = [float(row["net_return"]) for row in reference_result.equity]
    candidate_returns = [float(row["net_return"]) for row in candidate_result.equity]
    reference["beta_residual"] = {
        name: _beta_residual(reference_returns, values) for name, values in benchmark.items()
    }
    candidate["beta_residual"] = {
        name: _beta_residual(candidate_returns, values) for name, values in benchmark.items()
    }
    comparison = _comparison(candidate, reference)
    bootstrap = paired_moving_block_bootstrap(
        reference_returns,
        candidate_returns,
        block_length=config.bootstrap_block_days,
        samples=config.bootstrap_samples,
        seed=config.bootstrap_seed,
        periods_per_year=365.0,
    )
    probabilities = bootstrap["win_probabilities"]
    activity = transform.summary()
    candidate_episodes, candidate_reconciliation = extract_base_episodes(
        candidate_result, bars_by_symbol, funding_by_symbol
    )
    gates = {
        "episode_evidence_qualified": SIGNAL_EXIT_REASON
        in episode_artifact["diagnostics"]["qualified_exit_reasons"],
        "cooldown_exactly_reuses_stop_contract": config.cooldown_completed_bars
        == FUTURES_BASE_FORWARD_PROTOCOL.stop_cooldown_completed_bars,
        "signal_exit_trigger_exercised": activity["signal_exit_trigger_count"] > 0,
        "rapid_reentry_block_exercised": activity["blocked_entry_symbol_bar_count"] > 0,
        "order_count_lower": candidate["order_count"] < reference["order_count"],
        "decision_batch_count_not_higher": candidate["decision_batch_count"]
        <= reference["decision_batch_count"],
        "average_effective_gross_not_higher": candidate["average_effective_gross"]
        <= reference["average_effective_gross"],
        "maximum_effective_gross_at_most_one": candidate["maximum_effective_gross"] <= 1.0,
        "return_not_lower": candidate["return_pct"] >= reference["return_pct"],
        "sharpe_not_lower": candidate["sharpe"] >= reference["sharpe"],
        "maximum_drawdown_not_materially_worse": candidate["max_drawdown_pct"]
        <= reference["max_drawdown_pct"]
        + config.maximum_drawdown_worsening_percentage_points,
        "minimum_nonnegative_annual_delta_count": comparison["nonnegative_annual_delta_count"]
        >= config.minimum_nonnegative_annual_delta_count,
        "bootstrap_terminal_return_win_probability": probabilities[
            "candidate_terminal_return_above_reference"
        ]
        >= config.minimum_bootstrap_terminal_return_win_probability,
        "bootstrap_sharpe_win_probability": probabilities[
            "candidate_sharpe_above_reference"
        ]
        >= config.minimum_bootstrap_sharpe_win_probability,
        "bootstrap_drawdown_win_probability": probabilities[
            "candidate_max_drawdown_below_reference"
        ]
        >= config.minimum_bootstrap_drawdown_win_probability,
        "execution_contract_clean": (
            candidate["runtime_filter_coverage"] == 1.0
            and candidate["duplicate_decision_count"] == 0
            and candidate["same_bar_stop_reentry_count"] == 0
            and abs(candidate_reconciliation["net_pnl_difference_usdt"]) <= 1e-5
        ),
    }
    retained = all(gates.values())
    return {
        "schema_version": SIGNAL_EXIT_COOLDOWN_REPORT_VERSION,
        "artifact_type": "mini_trend_um_signal_exit_cooldown_ablation",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "consumed_historical_discovery_pool",
            "existing_cache_only": True,
            "network_download_used": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "contract": preregistration["contract"],
        "lineage": {
            "preregistration_hash": canonical_hash(preregistration),
            "episode_artifact_hash": canonical_hash(episode_artifact),
            "data_hash": _data_hash(bars_by_symbol, funding_by_symbol),
            "exchange_rules_hash": rules_hash,
        },
        "source_rapid_reentry_audit": preregistration["source"]["rapid_reentry_audit"],
        "reference": reference,
        "candidate": candidate,
        "candidate_activity": activity,
        "candidate_episode_summary": _episode_summary(candidate_episodes),
        "candidate_episode_reconciliation": candidate_reconciliation,
        "comparison": comparison,
        "paired_block_bootstrap": bootstrap,
        "gates": gates,
        "passed_gate_count": sum(gates.values()),
        "gate_count": len(gates),
        "diagnostics": {
            "trial_count": config.trial_count,
            "cumulative_trial_count": config.cumulative_trial_count,
            "verdict": (
                "retain_signal_exit_cooldown_for_future_only_research"
                if retained
                else "reject_signal_exit_cooldown_ablation"
            ),
            "paper_or_live_allowed": False,
        },
    }


def write_signal_exit_cooldown_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-signal-exit-cooldown",
        path_key="artifact_path",
        default_filename="mini_trend_um_signal_exit_cooldown.json",
        explicit_path=explicit_path,
    )
