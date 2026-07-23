#!/usr/bin/env python3
"""Generate and verify the deterministic local multi-sleeve runtime artifact."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from qount.contracts import MarketSnapshot
from qount.contracts import StrategyIntent
from qount.portfolio import SleeveRiskBudget
from qount.portfolio import VirtualExecutionCostModel
from qount.portfolio import MultiSleeveVirtualArtifactError
from qount.portfolio import read_multi_sleeve_virtual_artifact
from qount.portfolio import run_multi_sleeve_virtual_runtime


DECISION_TIME = "2026-07-23T00:05:00+00:00"
DATA_CUTOFF = "2026-07-23T00:00:00+00:00"


def run_fixture(output_directory: Path):
    snapshot = MarketSnapshot.create(
        decision_time=DECISION_TIME,
        data_cutoff=DATA_CUTOFF,
        prices={"BTCUSDT": 100.0, "ETHUSDT": 50.0, "SOLUSDT": 25.0},
        funding={"BTCUSDT": 0.0001, "ETHUSDT": -0.0002, "SOLUSDT": 0.0},
        features={
            "fixture": "multi_sleeve_virtual_runtime_v1",
            "candidate_performance_evidence": False,
        },
        exchange_rules_hash="a" * 64,
        account_snapshot_hash=None,
        data_quality={
            "complete": True,
            "blockers": (),
            "account_snapshot_linked": False,
        },
        source_hashes={"deterministic_fixture": "b" * 64},
    )
    intents = (
        StrategyIntent.create(
            strategy_id="fixture-trend-sleeve",
            strategy_version="1.0",
            snapshot_id=snapshot.snapshot_id,
            decision_time=DECISION_TIME,
            data_cutoff=DATA_CUTOFF,
            target_weights={"BTCUSDT": 0.3, "ETHUSDT": 0.1},
            expected_holding_bars=5,
            target_stress_loss_fraction=0.1,
            reason_codes=("RESEARCH_VIRTUAL_TARGET",),
            evidence_hash="c" * 64,
            state_hash="e" * 64,
        ),
        StrategyIntent.create(
            strategy_id="fixture-defensive-sleeve",
            strategy_version="1.0",
            snapshot_id=snapshot.snapshot_id,
            decision_time=DECISION_TIME,
            data_cutoff=DATA_CUTOFF,
            target_weights={"SOLUSDT": 0.2},
            expected_holding_bars=5,
            target_stress_loss_fraction=0.1,
            reason_codes=("RESEARCH_VIRTUAL_TARGET",),
            evidence_hash="d" * 64,
            state_hash="f" * 64,
        ),
    )
    budgets = tuple(
        SleeveRiskBudget(intent.strategy_id, 0.1, 0.1) for intent in intents
    )
    rules = {
        symbol: {
            "step_size": 0.1,
            "minimum_quantity": 0.1,
            "minimum_notional": 5.0,
        }
        for symbol in snapshot.prices
    }
    expected_strategy_ids = sorted(intent.strategy_id for intent in intents)
    def execute(target: Path):
        return run_multi_sleeve_virtual_runtime(
            target,
            snapshot=snapshot,
            intents=intents,
            budgets=budgets,
            opening_cash_usdt=800.0,
            current_positions={"ETHUSDT": 4.0},
            symbol_rules=rules,
            cost_model=VirtualExecutionCostModel.create(
                model_version="local-r0-contract-fixture-v1",
                taker_fee_rate=0.0004,
                slippage_bps=2.0,
            ),
            allowed_strategy_ids=expected_strategy_ids,
        )

    try:
        return execute(output_directory)
    except MultiSleeveVirtualArtifactError as exc:
        if str(exc) != "virtual_artifact_directory_already_exists":
            raise
    with tempfile.TemporaryDirectory(prefix="qount-r0-runtime-id-") as temporary:
        expected = execute(Path(temporary))
        expected_directory = output_directory / expected.batch.manifest.batch_id
    existing = read_multi_sleeve_virtual_artifact(expected_directory)
    if existing.result.get("result_hash") != expected.result.get("result_hash"):
        raise MultiSleeveVirtualArtifactError(
            "virtual_fixture_existing_artifact_mismatch"
        )
    return existing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "state" / "research_governance" / "runtime"),
    )
    args = parser.parse_args()
    artifact = run_fixture(Path(args.output_dir))
    print(f"artifact_directory={artifact.directory}")
    print(f"batch_id={artifact.batch.manifest.batch_id}")
    print(f"result_hash={artifact.result['result_hash']}")
    print(f"runtime_snapshot_hash={artifact.ledger_snapshot.snapshot_hash}")
    print("orders_authorized=false")
    print("promotion_evidence=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
