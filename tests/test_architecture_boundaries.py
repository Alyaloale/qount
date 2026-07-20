from __future__ import annotations

import ast
import unittest
from pathlib import Path

import qount.portfolio_governance as legacy_governance
from qount.contracts import StrategyIntent
from qount.governance import EquityMappingExecutionContract
from qount.governance import FormalTrial
from qount.governance import ForwardPeriod
from qount.governance import SleeveRuntimeEligibility
from qount.governance import equity_mapping_event_capacity
from qount.governance import register_formal_trial
from qount.governance import validate_runtime_eligibility
from qount.mini_trend.portfolio_intent import (
    base_intent_from_projection as legacy_base_intent_from_projection,
)
from qount.portfolio import NavAttribution
from qount.portfolio import SleeveRiskBudget
from qount.portfolio import allocate_strategy_intents
from qount.portfolio import scale_standalone_weights
from qount.strategies import base_intent_from_projection


ROOT = Path(__file__).resolve().parents[1]
CORE_MODULES = (
    "src/qount/contracts/batch.py",
    "src/qount/contracts/hashing.py",
    "src/qount/contracts/runtime.py",
    "src/qount/contracts/strategy.py",
    "src/qount/contracts/trace.py",
    "src/qount/governance/eligibility.py",
    "src/qount/governance/event_capacity.py",
    "src/qount/governance/registry.py",
    "src/qount/governance/research.py",
    "src/qount/portfolio/models.py",
    "src/qount/portfolio/allocator.py",
    "src/qount/risk/validation.py",
    "src/qount/risk/legacy_dispatch.py",
    "src/qount/execution/legacy_dispatch.py",
    "src/qount/execution/parity.py",
    "src/qount/execution/state_machine.py",
)
FORBIDDEN_CORE_IMPORTS = (
    "ccxt",
    "os",
    "pathlib",
    "qount.exchange_utils",
    "qount.execution",
    "qount.executor",
    "qount.settings",
)
PERSISTENCE_MODULES = (
    "src/qount/persistence/batch_store.py",
    "src/qount/persistence/codec.py",
    "src/qount/persistence/immutable_json.py",
)
REPORTING_MODULES = (
    "src/qount/reporting/artifact_importer.py",
    "src/qount/reporting/daily_brief.py",
    "src/qount/reporting/read_models.py",
)
NOTIFICATION_MODULES = (
    "src/qount/notifications/collector.py",
    "src/qount/notifications/contracts.py",
    "src/qount/notifications/health.py",
    "src/qount/notifications/producers.py",
    "src/qount/notifications/store.py",
)
RUNTIME_LEDGER_MODULES = (
    "src/qount/execution/recovery.py",
    "src/qount/ledger/audit.py",
    "src/qount/ledger/legacy_replay.py",
    "src/qount/ledger/read_model.py",
    "src/qount/ledger/reconciliation.py",
    "src/qount/ledger/store.py",
    "src/qount/notifications/producers.py",
)
OPERATIONS_MODULES = (
    "src/qount/operations/backups.py",
    "src/qount/operations/dashboard_publisher.py",
    "src/qount/operations/health_probes.py",
)
AUTHORITY_WRITER_MODULES = (
    "src/qount/operations/authority_writer.py",
)
FORBIDDEN_PERSISTENCE_IMPORTS = (
    "aiohttp",
    "ccxt",
    "httpx",
    "requests",
    "urllib",
    "qount.exchange_utils",
    "qount.execution",
    "qount.executor",
    "qount.notifier",
    "qount.settings",
)


def _intent(
    strategy_id: str,
    weights: dict[str, float],
    evidence_hash_character: str,
    state_hash_character: str,
) -> StrategyIntent:
    return StrategyIntent(
        strategy_id=strategy_id,
        decision_time="2026-07-19T00:05:00+00:00",
        data_cutoff="2026-07-19T00:00:00+00:00",
        target_weights=weights,
        expected_holding_bars=1,
        target_stress_loss_fraction=0.10,
        evidence_hash=evidence_hash_character * 64,
        state_hash=state_hash_character * 64,
    )


class ArchitectureBoundaryTest(unittest.TestCase):
    def test_legacy_portfolio_governance_exports_authoritative_objects(self) -> None:
        expected = {
            "StrategyIntent": StrategyIntent,
            "SleeveRuntimeEligibility": SleeveRuntimeEligibility,
            "validate_runtime_eligibility": validate_runtime_eligibility,
            "NavAttribution": NavAttribution,
            "SleeveRiskBudget": SleeveRiskBudget,
            "scale_standalone_weights": scale_standalone_weights,
            "allocate_strategy_intents": allocate_strategy_intents,
            "EquityMappingExecutionContract": EquityMappingExecutionContract,
            "equity_mapping_event_capacity": equity_mapping_event_capacity,
            "FormalTrial": FormalTrial,
            "ForwardPeriod": ForwardPeriod,
            "register_formal_trial": register_formal_trial,
        }
        for name, authoritative_object in expected.items():
            with self.subTest(name=name):
                self.assertIs(getattr(legacy_governance, name), authoritative_object)

    def test_legacy_base_adapter_exports_authoritative_function(self) -> None:
        self.assertIs(
            legacy_base_intent_from_projection,
            base_intent_from_projection,
        )

    def test_compatibility_module_contains_no_business_definitions(self) -> None:
        tree = ast.parse(
            (ROOT / "src/qount/portfolio_governance.py").read_text(encoding="utf-8")
        )
        definitions = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        self.assertEqual(definitions, [])

    def test_core_domains_do_not_import_runtime_or_exchange_modules(self) -> None:
        for relative_path in CORE_MODULES:
            tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
            imported_modules: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_modules.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_modules.append(node.module)
            violations = [
                imported
                for imported in imported_modules
                if any(
                    imported == forbidden or imported.startswith(f"{forbidden}.")
                    for forbidden in FORBIDDEN_CORE_IMPORTS
                )
            ]
            with self.subTest(module=relative_path):
                self.assertEqual(violations, [])

    def test_persistence_boundary_does_not_import_exchange_or_settings(self) -> None:
        for relative_path in (
            *PERSISTENCE_MODULES,
            *REPORTING_MODULES,
            *NOTIFICATION_MODULES,
        ):
            tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
            imported_modules: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_modules.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_modules.append(node.module)
            violations = [
                imported
                for imported in imported_modules
                if any(
                    imported == forbidden or imported.startswith(f"{forbidden}.")
                    for forbidden in FORBIDDEN_PERSISTENCE_IMPORTS
                )
            ]
            environment_reads = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "os"
                and node.attr in {"environ", "getenv"}
            ]
            with self.subTest(module=relative_path):
                self.assertEqual(violations, [])
                self.assertEqual(environment_reads, [])

    def test_runtime_ledger_does_not_import_exchange_or_settings(self) -> None:
        forbidden = (
            "ccxt",
            "requests",
            "qount.exchange_utils",
            "qount.executor",
            "qount.mini_trend.pilot_dispatcher",
            "qount.settings",
        )
        for relative_path in RUNTIME_LEDGER_MODULES:
            tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
            imported_modules: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_modules.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_modules.append(node.module)
            violations = [
                imported
                for imported in imported_modules
                if any(
                    imported == value or imported.startswith(f"{value}.")
                    for value in forbidden
                )
            ]
            with self.subTest(module=relative_path):
                self.assertEqual(violations, [])

    def test_dashboard_operations_do_not_import_exchange_or_live_runtime(self) -> None:
        forbidden = (
            "aiohttp",
            "ccxt",
            "httpx",
            "requests",
            "urllib",
            "qount.exchange_utils",
            "qount.execution",
            "qount.executor",
            "qount.ledger.store",
            "qount.notifier",
            "qount.settings",
        )
        for relative_path in OPERATIONS_MODULES:
            tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
            imported_modules: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_modules.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_modules.append(node.module)
            violations = [
                imported
                for imported in imported_modules
                if any(
                    imported == value or imported.startswith(f"{value}.")
                    for value in forbidden
                )
            ]
            environment_reads = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "os"
                and node.attr in {"environ", "getenv"}
            ]
            with self.subTest(module=relative_path):
                self.assertEqual(violations, [])
                self.assertEqual(environment_reads, [])

    def test_authority_writer_bridge_does_not_import_exchange_or_settings(self) -> None:
        forbidden = (
            "aiohttp",
            "ccxt",
            "httpx",
            "requests",
            "urllib",
            "qount.exchange_utils",
            "qount.executor",
            "qount.mini_trend.pilot_dispatcher",
            "qount.notifier",
            "qount.settings",
        )
        for relative_path in AUTHORITY_WRITER_MODULES:
            tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
            imported_modules: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_modules.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_modules.append(node.module)
            violations = [
                imported
                for imported in imported_modules
                if any(
                    imported == value or imported.startswith(f"{value}.")
                    for value in forbidden
                )
            ]
            environment_reads = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "os"
                and node.attr in {"environ", "getenv"}
            ]
            with self.subTest(module=relative_path):
                self.assertEqual(violations, [])
                self.assertEqual(environment_reads, [])

    def test_allocator_keeps_pre_migration_golden_hash(self) -> None:
        result = allocate_strategy_intents(
            (
                _intent("base", {"BTCUSDT": 0.4, "ETHUSDT": 0.2}, "a", "b"),
                _intent("event", {"BTCUSDT": 0.2}, "c", "d"),
            ),
            (
                SleeveRiskBudget("base", 0.10, 0.20, 1.0),
                SleeveRiskBudget("event", 0.0025, 0.05, 0.10),
            ),
            account_equity_usdt=500.0,
            allowed_strategy_ids=("base", "event"),
            minimum_notional_by_symbol={"BTCUSDT": 5.0, "ETHUSDT": 5.0},
            maximum_weight_by_symbol={"BTCUSDT": 0.5, "ETHUSDT": 0.25},
            correlation_cluster_by_symbol={
                "BTCUSDT": "crypto_beta",
                "ETHUSDT": "crypto_beta",
            },
        )
        self.assertEqual(
            result["allocation_hash"],
            "8c2f5dfd30a3142c18b3e968b9a54bd221cae822950d2656be2b19c48a3055d5",
        )


if __name__ == "__main__":
    unittest.main()
