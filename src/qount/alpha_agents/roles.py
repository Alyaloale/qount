from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .models import AgentRole


DEFAULT_ROLES: tuple[AgentRole, ...] = (
    AgentRole(
        role_id="market_data_scout",
        name="MarketDataScout",
        kind="llm_research",
        mission="Find usable crypto market data feeds and identify their latency, depth, and retention limits.",
        allowed_outputs=("source_summary", "data_gap", "collection_task"),
        forbidden_outputs=("trade_signal", "target_weight", "risk_override"),
        required_checks=("official_or_primary_source", "retention_window", "rate_limit"),
    ),
    AgentRole(
        role_id="exchange_rules_scout",
        name="ExchangeRulesScout",
        kind="llm_research",
        mission="Track exchange filters, fees, leverage brackets, funding fields, and minimum notional constraints.",
        allowed_outputs=("rule_summary", "implementation_constraint", "test_case"),
        forbidden_outputs=("trade_signal", "position_size", "risk_override"),
        required_checks=("official_exchange_doc", "runtime_exchange_info_required"),
    ),
    AgentRole(
        role_id="quant_librarian",
        name="QuantLibrarian",
        kind="llm_research",
        mission="Collect validation methods and translate them into testable research gates.",
        allowed_outputs=("paper_summary", "validation_gate", "metric_definition"),
        forbidden_outputs=("strategy_promotion", "trade_signal"),
        required_checks=("primary_reference", "multiple_testing_penalty", "leakage_control"),
    ),
    AgentRole(
        role_id="feature_designer",
        name="FeatureDesigner",
        kind="llm_research",
        mission="Propose features from approved data sources, with explicit leakage and cost assumptions.",
        allowed_outputs=("feature_spec", "label_spec", "data_dependency"),
        forbidden_outputs=("live_order", "risk_override"),
        required_checks=("as_of_join", "cost_hurdle", "beta_residual_target"),
    ),
    AgentRole(
        role_id="experiment_designer",
        name="ExperimentDesigner",
        kind="llm_research",
        mission="Turn research hypotheses into small experiments with windows, baselines, and kill criteria.",
        allowed_outputs=("experiment_spec", "baseline_spec", "kill_test"),
        forbidden_outputs=("promotion_claim", "live_config_change"),
        required_checks=("holdout_role", "trial_count", "benchmark_vs_beta"),
    ),
    AgentRole(
        role_id="model_trainer",
        name="ModelTrainer",
        kind="quant_worker",
        mission="Train and score models on A10 or research hosts using deterministic scripts and frozen datasets.",
        allowed_outputs=("model_artifact", "oos_scorecard", "feature_importance"),
        forbidden_outputs=("direct_order", "risk_override", "paper_promotion"),
        required_checks=("purged_cv", "embargo", "train_test_split_recorded"),
        llm_allowed=False,
    ),
    AgentRole(
        role_id="backtest_auditor",
        name="BacktestAuditor",
        kind="deterministic_audit",
        mission="Verify cost model, min-notional coverage, beta attribution, and leakage boundaries.",
        allowed_outputs=("audit_report", "blocker", "scorecard"),
        forbidden_outputs=("trade_signal", "risk_override"),
        required_checks=("cost_sensitivity", "beta_benchmark", "effective_breadth"),
        llm_allowed=False,
    ),
    AgentRole(
        role_id="risk_architect",
        name="RiskArchitect",
        kind="deterministic_gate",
        mission="Define hard gates for capital, drawdown, leverage, stale data, and unmanaged positions.",
        allowed_outputs=("risk_rule", "kill_switch", "position_limit"),
        forbidden_outputs=("alpha_claim", "llm_override"),
        required_checks=("fail_closed", "small_account_min_notional", "unmanaged_position_halt"),
        llm_allowed=False,
    ),
    AgentRole(
        role_id="red_team",
        name="RedTeamAgent",
        kind="llm_review",
        mission="Attack assumptions, search for beta leakage, hindsight, data snooping, and cost undercounting.",
        allowed_outputs=("critique", "missing_test", "falsification_path"),
        forbidden_outputs=("trade_signal", "target_weight", "risk_override"),
        required_checks=("beta_attribution", "counterexample", "simpler_baseline"),
    ),
    AgentRole(
        role_id="ops_auditor",
        name="OpsAuditAgent",
        kind="llm_review",
        mission="Read paper/live artifacts and explain operational anomalies without changing runtime state.",
        allowed_outputs=("ops_report", "halt_recommendation", "state_diff"),
        forbidden_outputs=("order", "cron_change", "live_arm"),
        required_checks=("read_only", "state_replay", "human_action_required"),
    ),
)


@dataclass(frozen=True)
class AgentRegistry:
    roles: tuple[AgentRole, ...]

    def get(self, role_id: str) -> AgentRole:
        for role in self.roles:
            if role.role_id == role_id:
                return role
        raise KeyError(f"unknown alpha agent role: {role_id}")

    def llm_roles(self) -> tuple[AgentRole, ...]:
        return tuple(role for role in self.roles if role.llm_allowed)

    def manifest(self) -> dict[str, object]:
        return {"roles": [role.to_dict() for role in self.roles]}


def default_registry() -> AgentRegistry:
    return AgentRegistry(DEFAULT_ROLES)


def load_registry(path: str | Path) -> AgentRegistry:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    rows = payload.get("roles", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("role registry JSON must be a list or an object with roles=[]")
    roles: list[AgentRole] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("each role must be an object")
        roles.append(
            AgentRole(
                role_id=str(row["role_id"]),
                name=str(row["name"]),
                kind=str(row["kind"]),
                mission=str(row["mission"]),
                allowed_outputs=tuple(str(item) for item in row.get("allowed_outputs", ())),
                forbidden_outputs=tuple(str(item) for item in row.get("forbidden_outputs", ())),
                required_checks=tuple(str(item) for item in row.get("required_checks", ())),
                llm_allowed=bool(row.get("llm_allowed", True)),
            )
        )
    return AgentRegistry(tuple(roles))
