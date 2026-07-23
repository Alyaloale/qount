from __future__ import annotations

import json
import os
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

from qount.contracts import MarketSnapshot
from qount.contracts import StrategyIntent
from qount.contracts import canonical_hash
from qount.execution import build_portfolio_order_plan
from qount.portfolio import MultiSleeveVirtualArtifactError
from qount.portfolio import MultiSleeveVirtualArtifactIncompleteError
from qount.portfolio import SleeveRiskBudget
from qount.portfolio import VirtualExecutionCostModel
from qount.portfolio import allocate_strategy_intents
from qount.portfolio import portfolio_target_from_allocation
from qount.portfolio import read_multi_sleeve_virtual_artifact
from qount.portfolio import run_multi_sleeve_virtual_runtime
from qount.risk import build_portfolio_risk_decision


DECISION_TIME = "2026-07-23T00:05:00+00:00"
DATA_CUTOFF = "2026-07-23T00:00:00+00:00"


def _snapshot() -> MarketSnapshot:
    return MarketSnapshot.create(
        decision_time=DECISION_TIME,
        data_cutoff=DATA_CUTOFF,
        prices={"BTCUSDT": 100.0, "ETHUSDT": 50.0, "SOLUSDT": 25.0},
        funding={"BTCUSDT": 0.0001, "ETHUSDT": -0.0002, "SOLUSDT": 0.0},
        features={"fixture": "multi_sleeve_virtual_runtime"},
        exchange_rules_hash="a" * 64,
        account_snapshot_hash=None,
        data_quality={
            "complete": True,
            "blockers": (),
            "account_snapshot_linked": False,
        },
        source_hashes={"fixture": "b" * 64},
    )


def _intent(
    snapshot: MarketSnapshot,
    *,
    strategy_id: str,
    strategy_version: str,
    weights: dict[str, float],
    hash_character: str,
) -> StrategyIntent:
    return StrategyIntent.create(
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        snapshot_id=snapshot.snapshot_id,
        decision_time=DECISION_TIME,
        data_cutoff=DATA_CUTOFF,
        target_weights=weights,
        expected_holding_bars=5,
        target_stress_loss_fraction=0.1,
        reason_codes=("RESEARCH_VIRTUAL_TARGET",),
        evidence_hash=hash_character * 64,
        state_hash=("e" if hash_character == "c" else "f") * 64,
    )


def _rules(minimum_notional: float = 5.0) -> dict[str, dict[str, float]]:
    return {
        symbol: {
            "step_size": 0.1,
            "minimum_quantity": 0.1,
            "minimum_notional": minimum_notional,
        }
        for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    }


def _inputs():
    snapshot = _snapshot()
    intents = (
        _intent(
            snapshot,
            strategy_id="fixture-trend",
            strategy_version="1.0",
            weights={"BTCUSDT": 0.3, "ETHUSDT": 0.1},
            hash_character="c",
        ),
        _intent(
            snapshot,
            strategy_id="fixture-defensive",
            strategy_version="1.0",
            weights={"SOLUSDT": 0.2},
            hash_character="d",
        ),
    )
    budgets = tuple(
        SleeveRiskBudget(intent.strategy_id, 0.1, 0.1) for intent in intents
    )
    return snapshot, intents, budgets


class MultiSleeveVirtualRuntimeTest(unittest.TestCase):
    @staticmethod
    def _rewrite_envelope(path: Path, envelope: dict[str, object]) -> None:
        payload_hash = canonical_hash({"payload": envelope["payload"]})
        envelope["payload_hash"] = payload_hash
        envelope["object_id"] = canonical_hash(
            {
                "artifact_type": envelope["artifact_type"],
                "payload_hash": payload_hash,
            }
        )
        envelope["artifact_hash"] = canonical_hash(
            {key: value for key, value in envelope.items() if key != "artifact_hash"}
        )
        raw = (
            json.dumps(
                envelope,
                ensure_ascii=True,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("ascii")
        path.write_bytes(raw)
        os.chmod(path, 0o600)

    @staticmethod
    def _refresh_manifest_member(directory: Path, relative_path: str) -> None:
        manifest_path = directory / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="ascii"))
        raw = (directory / relative_path).read_bytes()
        for member in manifest["member_files"]:
            if member["path"] == relative_path:
                member["size_bytes"] = len(raw)
                member["sha256"] = sha256(raw).hexdigest()
                break
        manifest["manifest_hash"] = canonical_hash(
            {key: value for key, value in manifest.items() if key != "manifest_hash"}
        )
        manifest_path.write_text(
            json.dumps(
                manifest,
                ensure_ascii=True,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="ascii",
        )
        os.chmod(manifest_path, 0o600)

    def test_two_sleeve_chain_persists_full_virtual_evidence(self) -> None:
        snapshot, intents, budgets = _inputs()
        cost_model = VirtualExecutionCostModel.create(
            model_version="fixture-v1",
            taker_fee_rate=0.0004,
            slippage_bps=2.0,
        )
        with tempfile.TemporaryDirectory() as tmp:
            artifact = run_multi_sleeve_virtual_runtime(
                Path(tmp),
                snapshot=snapshot,
                intents=intents,
                budgets=budgets,
                opening_cash_usdt=800.0,
                current_positions={"ETHUSDT": 4.0},
                symbol_rules=_rules(),
                cost_model=cost_model,
                allowed_strategy_ids=tuple(intent.strategy_id for intent in intents),
            )
            phases = [order.phase for order in artifact.batch.plan.orders]
            self.assertEqual(phases[0], "reduce")
            self.assertEqual(phases[1:], ["increase", "increase"])
            self.assertEqual(len(artifact.ledger_snapshot.fills), 3)
            self.assertEqual(len(artifact.ledger_snapshot.order_events), 9)
            self.assertTrue(artifact.result["accounting_passed"])
            self.assertTrue(artifact.result["reconciliation_passed"])
            self.assertFalse(artifact.result["orders_authorized"])
            self.assertFalse(artifact.result["orders_routed"])
            self.assertEqual(len(artifact.sleeve_nav["sleeves"]), 2)
            self.assertTrue(
                all(
                    row["standalone_executable_nav"] > 0.0
                    for row in artifact.sleeve_nav["sleeves"]
                )
            )
            self.assertEqual(artifact.directory.stat().st_mode & 0o777, 0o700)
            for path in artifact.directory.rglob("*"):
                self.assertEqual(
                    path.stat().st_mode & 0o777,
                    0o700 if path.is_dir() else 0o600,
                )
            reread = read_multi_sleeve_virtual_artifact(artifact.directory)
            self.assertEqual(reread.result["result_hash"], artifact.result["result_hash"])

    def test_replay_is_economically_idempotent(self) -> None:
        snapshot, intents, budgets = _inputs()
        model = VirtualExecutionCostModel.create(
            model_version="fixture-v1",
            taker_fee_rate=0.0004,
            slippage_bps=2.0,
        )
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            one = run_multi_sleeve_virtual_runtime(
                Path(first),
                snapshot=snapshot,
                intents=intents,
                budgets=budgets,
                opening_cash_usdt=800.0,
                current_positions={"ETHUSDT": 4.0},
                symbol_rules=_rules(),
                cost_model=model,
                allowed_strategy_ids=tuple(intent.strategy_id for intent in intents),
            )
            two = run_multi_sleeve_virtual_runtime(
                Path(second),
                snapshot=snapshot,
                intents=intents,
                budgets=budgets,
                opening_cash_usdt=800.0,
                current_positions={"ETHUSDT": 4.0},
                symbol_rules=_rules(),
                cost_model=model,
                allowed_strategy_ids=tuple(intent.strategy_id for intent in intents),
            )
            self.assertEqual(one.result["result_hash"], two.result["result_hash"])
            self.assertEqual(
                one.ledger_snapshot.snapshot_hash,
                two.ledger_snapshot.snapshot_hash,
            )
            self.assertEqual(one.virtual_execution, two.virtual_execution)

    def test_existing_directory_is_never_overwritten(self) -> None:
        snapshot, intents, budgets = _inputs()
        model = VirtualExecutionCostModel.create(
            model_version="fixture-v1",
            taker_fee_rate=0.0004,
            slippage_bps=2.0,
        )
        with tempfile.TemporaryDirectory() as tmp:
            first = run_multi_sleeve_virtual_runtime(
                Path(tmp),
                snapshot=snapshot,
                intents=intents,
                budgets=budgets,
                opening_cash_usdt=800.0,
                current_positions={"ETHUSDT": 4.0},
                symbol_rules=_rules(),
                cost_model=model,
                allowed_strategy_ids=tuple(intent.strategy_id for intent in intents),
            )
            manifest_before = (first.directory / "manifest.json").read_bytes()
            with self.assertRaises(MultiSleeveVirtualArtifactError):
                run_multi_sleeve_virtual_runtime(
                    Path(tmp),
                    snapshot=snapshot,
                    intents=intents,
                    budgets=budgets,
                    opening_cash_usdt=800.0,
                    current_positions={"ETHUSDT": 4.0},
                    symbol_rules=_rules(),
                    cost_model=model,
                    allowed_strategy_ids=tuple(
                        intent.strategy_id for intent in intents
                    ),
                )
            self.assertEqual(
                (first.directory / "manifest.json").read_bytes(), manifest_before
            )

    def test_tamper_and_manifest_missing_are_detected(self) -> None:
        snapshot, intents, budgets = _inputs()
        model = VirtualExecutionCostModel.create(
            model_version="fixture-v1",
            taker_fee_rate=0.0004,
            slippage_bps=2.0,
        )
        with tempfile.TemporaryDirectory() as tmp:
            artifact = run_multi_sleeve_virtual_runtime(
                Path(tmp),
                snapshot=snapshot,
                intents=intents,
                budgets=budgets,
                opening_cash_usdt=800.0,
                current_positions={"ETHUSDT": 4.0},
                symbol_rules=_rules(),
                cost_model=model,
                allowed_strategy_ids=tuple(intent.strategy_id for intent in intents),
            )
            target = artifact.directory / "result.json"
            envelope = json.loads(target.read_text(encoding="ascii"))
            envelope["payload"]["orders_routed"] = True
            target.write_text(json.dumps(envelope), encoding="ascii")
            os.chmod(target, 0o600)
            with self.assertRaises(MultiSleeveVirtualArtifactError):
                read_multi_sleeve_virtual_artifact(artifact.directory)

        with tempfile.TemporaryDirectory() as tmp:
            artifact = run_multi_sleeve_virtual_runtime(
                Path(tmp),
                snapshot=snapshot,
                intents=intents,
                budgets=budgets,
                opening_cash_usdt=800.0,
                current_positions={"ETHUSDT": 4.0},
                symbol_rules=_rules(),
                cost_model=model,
                allowed_strategy_ids=tuple(intent.strategy_id for intent in intents),
            )
            target = artifact.directory / "runtime_audit.json"
            envelope = json.loads(target.read_text(encoding="ascii"))
            envelope["payload"][0]["previous_hash"] = "f" * 64
            self._rewrite_envelope(target, envelope)
            self._refresh_manifest_member(artifact.directory, "runtime_audit.json")
            with self.assertRaisesRegex(
                MultiSleeveVirtualArtifactError,
                "virtual_artifact_audit_chain_invalid",
            ):
                read_multi_sleeve_virtual_artifact(artifact.directory)

        with tempfile.TemporaryDirectory() as tmp:
            incomplete = Path(tmp) / ("a" * 64)
            incomplete.mkdir(mode=0o700)
            with self.assertRaises(MultiSleeveVirtualArtifactIncompleteError):
                read_multi_sleeve_virtual_artifact(incomplete)

    def test_single_sleeve_passthrough_and_min_notional_fail_closed(self) -> None:
        snapshot, intents, _ = _inputs()
        intent = intents[0]
        budget = SleeveRiskBudget(intent.strategy_id, 0.1, 0.1)
        allocation = allocate_strategy_intents(
            (intent,),
            (budget,),
            account_equity_usdt=1_000.0,
            allowed_strategy_ids=(intent.strategy_id,),
        )
        target = portfolio_target_from_allocation((intent,), allocation)
        risk = build_portfolio_risk_decision(
            snapshot,
            target,
            current_positions={},
            account_equity_usdt=1_000.0,
        )
        plan = build_portfolio_order_plan(
            snapshot,
            target,
            risk,
            current_positions={},
            account_equity_usdt=1_000.0,
            symbol_rules=_rules(minimum_notional=500.0),
        )
        self.assertEqual(
            target.sleeve_contributions[intent.strategy_id],
            target.target_weights,
        )
        self.assertFalse(plan.executable)
        self.assertTrue(
            any("order_notional_below_minimum" in value for value in plan.blockers)
        )
        self.assertEqual(plan.orders, ())

    def test_zero_sleeve_allocator_fails_closed(self) -> None:
        allocation = allocate_strategy_intents(
            (),
            (),
            account_equity_usdt=1_000.0,
            allowed_strategy_ids=(),
        )
        self.assertFalse(allocation["allocatable"])
        self.assertIn("strategy_intents_empty", allocation["blockers"])

    def test_invalid_risk_limits_fail_closed_without_type_errors(self) -> None:
        snapshot, intents, budgets = _inputs()
        allocation = allocate_strategy_intents(
            intents,
            budgets,
            account_equity_usdt=1_000.0,
            allowed_strategy_ids=tuple(intent.strategy_id for intent in intents),
        )
        target = portfolio_target_from_allocation(intents, allocation)
        risk = build_portfolio_risk_decision(
            snapshot,
            target,
            current_positions={},
            account_equity_usdt=1_000.0,
            maximum_portfolio_gross="invalid",  # type: ignore[arg-type]
            maximum_weight_by_symbol={"BTCUSDT": "invalid"},  # type: ignore[dict-item]
        )
        self.assertFalse(risk.approved)
        self.assertIn("maximum_portfolio_gross_invalid", risk.violations)
        self.assertIn(
            "portfolio_risk_symbol_cap_invalid:BTCUSDT",
            risk.violations,
        )

    def test_risk_hash_binds_unused_symbol_caps(self) -> None:
        snapshot, intents, budgets = _inputs()
        allocation = allocate_strategy_intents(
            intents,
            budgets,
            account_equity_usdt=1_000.0,
            allowed_strategy_ids=tuple(intent.strategy_id for intent in intents),
        )
        target = portfolio_target_from_allocation(intents, allocation)
        first = build_portfolio_risk_decision(
            snapshot,
            target,
            current_positions={},
            account_equity_usdt=1_000.0,
            maximum_weight_by_symbol={"UNUSEDUSDT": 0.2},
        )
        second = build_portfolio_risk_decision(
            snapshot,
            target,
            current_positions={},
            account_equity_usdt=1_000.0,
            maximum_weight_by_symbol={"UNUSEDUSDT": 0.3},
        )
        self.assertTrue(first.approved)
        self.assertTrue(second.approved)
        self.assertNotEqual(first.risk_state_hash, second.risk_state_hash)


if __name__ == "__main__":
    unittest.main()
