from __future__ import annotations

import json
from pathlib import Path

from .models import ResearchTask


def seed_research_tasks() -> tuple[ResearchTask, ...]:
    return (
        ResearchTask(
            task_id="source_map_v0",
            title="Build alpha data source map",
            objective="Collect official market, derivatives, and project evidence sources for the alpha engine.",
            role_ids=("market_data_scout", "exchange_rules_scout", "quant_librarian"),
            required_outputs=("source_summary", "data_gap", "validation_gate"),
            source_tags=("binance_market_data", "binance_derivatives_state", "validation", "project_evidence"),
            priority=10,
        ),
        ResearchTask(
            task_id="beta_residual_target_v0",
            title="Define beta-residual target",
            objective="Prevent another MiniTrend-style beta wrapper by defining labels and benchmarks that remove BTC/TOP3 beta.",
            role_ids=("feature_designer", "experiment_designer", "red_team"),
            required_outputs=("label_spec", "baseline_spec", "missing_test"),
            source_tags=("project_evidence", "validation"),
            priority=20,
        ),
        ResearchTask(
            task_id="intraday_microstructure_v0",
            title="Design intraday crypto feature experiment",
            objective="Propose first 1m/5m order-flow, spread, funding, and OI feature set with strict as-of joins.",
            role_ids=("feature_designer", "experiment_designer", "backtest_auditor"),
            required_outputs=("feature_spec", "experiment_spec", "audit_report"),
            source_tags=("binance_market_data", "binance_derivatives_state", "validation"),
            priority=30,
        ),
        ResearchTask(
            task_id="a10_training_lane_v0",
            title="Define A10 model-training lane",
            objective="Split deterministic feature store, tabular baseline, sequence-model experiments, and promotion gates.",
            role_ids=("model_trainer", "experiment_designer", "red_team"),
            required_outputs=("model_artifact_contract", "oos_scorecard", "falsification_path"),
            source_tags=("validation", "project_evidence"),
            priority=40,
        ),
        ResearchTask(
            task_id="small_account_risk_v0",
            title="Design 400 USDT aggressive risk boundary",
            objective="Allow futures and shorts in research while preserving deterministic small-account safety gates.",
            role_ids=("risk_architect", "exchange_rules_scout", "ops_auditor"),
            required_outputs=("risk_rule", "implementation_constraint", "ops_report"),
            source_tags=("binance_market_data", "project_evidence"),
            priority=50,
        ),
    )


def load_research_tasks(path: str | Path) -> tuple[ResearchTask, ...]:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    rows = payload.get("tasks", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("task JSON must be a list or an object with tasks=[]")
    tasks: list[ResearchTask] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("each task must be an object")
        tasks.append(
            ResearchTask(
                task_id=str(row["task_id"]),
                title=str(row["title"]),
                objective=str(row["objective"]),
                role_ids=tuple(str(item) for item in row.get("role_ids", ())),
                required_outputs=tuple(str(item) for item in row.get("required_outputs", ())),
                source_tags=tuple(str(item) for item in row.get("source_tags", ())),
                holdout_role=str(row.get("holdout_role", "discovery")),
                priority=int(row.get("priority", 100)),
            )
        )
    return tuple(tasks)
