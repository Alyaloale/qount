from __future__ import annotations

import unittest
from dataclasses import replace

from qount.governance import DeploymentManifest
from qount.governance import StrategyRegistration
from qount.governance import StrategyRegistry
from qount.governance import validate_registry_transition
from qount.governance import validate_registered_intents
from qount.governance import validate_strategy_transition
from qount.mini_trend.live_pilot import LIVE_PILOT_CONTRACT
from qount.strategies import BASE_STRATEGY_VERSION
from qount.strategies import base_strategy_registration
from qount.contracts import StrategyIntent


T0 = "2026-07-19T12:00:00+00:00"
T1 = "2026-07-19T12:01:00+00:00"
T2 = "2026-07-19T12:02:00+00:00"


def _registration(
    status: str,
    *,
    strategy_id: str = "test_strategy",
    registered_at: str = T0,
    code_hash: str = "b" * 64,
    config_hash: str = "c" * 64,
    promotion_hash: str | None = None,
    owner_hash: str | None = None,
    maximum_stress: float = 0.01,
    maximum_gross: float = 0.50,
    supersedes: str | None = None,
    halted_from: str | None = None,
    recovery_hash: str | None = None,
    strategy_kind: str = "continuous",
) -> StrategyRegistration:
    return StrategyRegistration.create(
        strategy_id=strategy_id,
        strategy_version="1.2.3",
        strategy_kind=strategy_kind,
        promotion_status=status,
        strategy_contract_hash="a" * 64,
        code_hash=code_hash,
        config_hash=config_hash,
        promotion_artifact_hash=promotion_hash,
        owner_authorization_hash=owner_hash,
        maximum_stress_loss_fraction=maximum_stress,
        maximum_gross=maximum_gross,
        registered_at=registered_at,
        supersedes_entry_id=supersedes,
        halted_from_status=halted_from,
        recovery_evidence_hash=recovery_hash,
    )


def _registry(entry: StrategyRegistration) -> StrategyRegistry:
    return StrategyRegistry.create((entry,), created_at=T1)


def _intent(
    *,
    strategy_version: str = "1.2.3",
    target_weight: float = 0.20,
    stress_loss: float = 0.005,
) -> StrategyIntent:
    return StrategyIntent.create(
        strategy_id="test_strategy",
        strategy_version=strategy_version,
        snapshot_id="5" * 64,
        decision_time="2026-07-20T00:05:00+00:00",
        data_cutoff="2026-07-20T00:00:00+00:00",
        target_weights={"BTCUSDT": target_weight},
        expected_holding_bars=1,
        target_stress_loss_fraction=stress_loss,
        reason_codes=("TEST_TARGET",),
        evidence_hash="6" * 64,
        state_hash="7" * 64,
    )


def _manifest(
    registry: StrategyRegistry,
    entry: StrategyRegistration,
    *,
    environment: str,
    dirty: bool,
    rollback_target: str | None,
) -> DeploymentManifest:
    return DeploymentManifest.create(
        registry,
        strategy_entry_ids=(entry.registry_entry_id,),
        environment=environment,
        git_commit="1" * 40,
        dirty=dirty,
        code_tree_hash="2" * 64,
        dependency_lock_hash="3" * 64,
        config_hash="4" * 64,
        deployed_at=T2,
        deployed_by="local-governance-test",
        rollback_target=rollback_target,
    )


class GovernanceRegistryTest(unittest.TestCase):
    def test_registration_and_registry_are_deterministic(self) -> None:
        first = _registration("research")
        second = _registration("research")
        first_registry = _registry(first)
        second_registry = _registry(second)

        self.assertEqual(first, second)
        self.assertEqual(first.validate(), ())
        self.assertEqual(first_registry, second_registry)
        self.assertEqual(first_registry.validate(), ())

    def test_registration_hash_detects_tampering(self) -> None:
        registration = _registration("research")
        tampered = replace(registration, config_hash="d" * 64)

        self.assertIn("strategy_registration_hash_invalid", tampered.validate())
        self.assertIn("strategy_registration_id_invalid", tampered.validate())

    def test_live_registration_requires_promotion_owner_and_risk_budget(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "promotion_evidence_missing",
        ):
            _registration(
                "minimal_live",
                promotion_hash=None,
                owner_hash=None,
                maximum_stress=0.0,
                maximum_gross=0.0,
            )
        with self.assertRaisesRegex(ValueError, "filter_cannot_be_live"):
            _registration(
                "minimal_live",
                promotion_hash="d" * 64,
                owner_hash="e" * 64,
                strategy_kind="filter",
            )

    def test_transition_rejects_skip_and_same_version_code_change(self) -> None:
        research = _registration("research")
        skipped = _registration(
            "paper",
            registered_at=T1,
            promotion_hash="d" * 64,
            supersedes=research.registry_entry_id,
        )
        changed_code = _registration(
            "frozen_candidate",
            registered_at=T1,
            code_hash="e" * 64,
            promotion_hash="d" * 64,
            supersedes=research.registry_entry_id,
        )

        self.assertIn(
            "strategy_transition_skip_or_reverse_forbidden",
            validate_strategy_transition(research, skipped),
        )
        self.assertIn(
            "strategy_transition_immutable_field_changed:code_hash",
            validate_strategy_transition(research, changed_code),
        )

    def test_transition_requires_owner_authorization_for_risk_increase(self) -> None:
        research = _registration(
            "research",
            maximum_stress=0.01,
            maximum_gross=0.25,
        )
        unapproved = _registration(
            "frozen_candidate",
            registered_at=T1,
            promotion_hash="d" * 64,
            maximum_stress=0.02,
            maximum_gross=0.50,
            supersedes=research.registry_entry_id,
        )
        approved = _registration(
            "frozen_candidate",
            registered_at=T1,
            promotion_hash="d" * 64,
            owner_hash="e" * 64,
            maximum_stress=0.02,
            maximum_gross=0.50,
            supersedes=research.registry_entry_id,
        )

        self.assertIn(
            "strategy_transition_risk_increase_authorization_missing",
            validate_strategy_transition(research, unapproved),
        )
        self.assertEqual(validate_strategy_transition(research, approved), ())

    def test_halt_and_recovery_require_reconciliation_and_cannot_escalate(self) -> None:
        shadow = _registration("shadow", promotion_hash="d" * 64)
        halted = _registration(
            "halted",
            registered_at=T1,
            promotion_hash="d" * 64,
            maximum_stress=0.0,
            maximum_gross=0.0,
            supersedes=shadow.registry_entry_id,
            halted_from="shadow",
        )
        recovered = _registration(
            "shadow",
            registered_at=T2,
            promotion_hash="d" * 64,
            owner_hash="e" * 64,
            supersedes=halted.registry_entry_id,
            recovery_hash="f" * 64,
        )
        escalated = _registration(
            "paper",
            registered_at=T2,
            promotion_hash="d" * 64,
            owner_hash="e" * 64,
            supersedes=halted.registry_entry_id,
            recovery_hash="f" * 64,
        )

        self.assertEqual(validate_strategy_transition(shadow, halted), ())
        self.assertEqual(validate_strategy_transition(halted, recovered), ())
        self.assertIn(
            "strategy_transition_halted_recovery_above_origin",
            validate_strategy_transition(halted, escalated),
        )

    def test_registry_rejects_duplicate_strategy_version(self) -> None:
        research = _registration("research")
        with self.assertRaisesRegex(ValueError, "strategy_id_duplicate"):
            StrategyRegistry.create((research, research), created_at=T1)

    def test_new_version_restarts_research_and_registry_removal_requires_halt(self) -> None:
        shadow = _registration("shadow", promotion_hash="d" * 64)
        upgraded = StrategyRegistration.create(
            strategy_id=shadow.strategy_id,
            strategy_version="2.0.0",
            strategy_kind=shadow.strategy_kind,
            promotion_status="research",
            strategy_contract_hash="e" * 64,
            code_hash="f" * 64,
            config_hash="1" * 64,
            promotion_artifact_hash=None,
            owner_authorization_hash=None,
            maximum_stress_loss_fraction=shadow.maximum_stress_loss_fraction,
            maximum_gross=shadow.maximum_gross,
            registered_at=T1,
            supersedes_entry_id=shadow.registry_entry_id,
        )
        previous = StrategyRegistry.create((shadow,), created_at=T1)
        current = StrategyRegistry.create((upgraded,), created_at=T2)
        removed = StrategyRegistry.create(
            (
                _registration(
                    "research",
                    strategy_id="other_strategy",
                    registered_at=T1,
                ),
            ),
            created_at=T2,
        )

        self.assertEqual(validate_strategy_transition(shadow, upgraded), ())
        self.assertEqual(validate_registry_transition(previous, current), ())
        self.assertIn(
            f"strategy_registry_removed_without_halt:{shadow.strategy_id}",
            validate_registry_transition(previous, removed),
        )

    def test_shadow_manifest_is_bound_but_never_authorizes_orders(self) -> None:
        shadow = _registration("shadow", promotion_hash="d" * 64)
        registry = _registry(shadow)
        manifest = _manifest(
            registry,
            shadow,
            environment="shadow",
            dirty=True,
            rollback_target=None,
        )

        self.assertFalse(manifest.orders_authorized)
        self.assertEqual(manifest.validate(), ())
        self.assertEqual(manifest.validate_against_registry(registry), ())
        self.assertEqual(manifest.as_dict()["manifest_hash"], manifest.manifest_hash)

    def test_registered_intent_requires_exact_version_status_and_risk_budget(self) -> None:
        shadow = _registration("shadow", promotion_hash="d" * 64)
        registry = _registry(shadow)

        self.assertEqual(
            validate_registered_intents(
                registry,
                (_intent(),),
                environment="shadow",
            ),
            (),
        )
        production_errors = validate_registered_intents(
            registry,
            (_intent(),),
            environment="production",
        )
        oversized_errors = validate_registered_intents(
            registry,
            (_intent(target_weight=0.60, stress_loss=0.02),),
            environment="shadow",
        )
        version_errors = validate_registered_intents(
            registry,
            (_intent(strategy_version="1.2.4"),),
            environment="shadow",
        )

        self.assertIn(
            "intent:0:strategy_status_not_allowed:shadow",
            production_errors,
        )
        self.assertIn(
            "intent:0:registered_maximum_gross_exceeded",
            oversized_errors,
        )
        self.assertIn(
            "intent:0:registered_stress_loss_budget_exceeded",
            oversized_errors,
        )
        self.assertIn(
            "intent:0:strategy_version_registry_mismatch",
            version_errors,
        )

    def test_production_manifest_rejects_dirty_or_unpromoted_strategy(self) -> None:
        shadow = _registration("shadow", promotion_hash="d" * 64)
        shadow_registry = _registry(shadow)
        with self.assertRaisesRegex(ValueError, "status_not_allowed"):
            _manifest(
                shadow_registry,
                shadow,
                environment="production",
                dirty=False,
                rollback_target="9" * 64,
            )

        live = _registration(
            "minimal_live",
            promotion_hash="d" * 64,
            owner_hash="e" * 64,
        )
        live_registry = _registry(live)
        with self.assertRaisesRegex(ValueError, "production_dirty"):
            _manifest(
                live_registry,
                live,
                environment="production",
                dirty=True,
                rollback_target="9" * 64,
            )

    def test_clean_production_manifest_binds_rollback_and_detects_tampering(self) -> None:
        live = _registration(
            "minimal_live",
            promotion_hash="d" * 64,
            owner_hash="e" * 64,
        )
        registry = _registry(live)
        manifest = _manifest(
            registry,
            live,
            environment="production",
            dirty=False,
            rollback_target="9" * 64,
        )
        tampered = replace(manifest, orders_authorized=True)

        self.assertEqual(manifest.validate(), ())
        self.assertIn("deployment_manifest_cannot_authorize_orders", tampered.validate())
        self.assertIn("deployment_manifest_hash_invalid", tampered.validate())

    def test_base_adapter_binds_authoritative_identity_and_contract(self) -> None:
        registration = base_strategy_registration(
            promotion_status="shadow",
            code_hash="a" * 64,
            config_hash="b" * 64,
            promotion_artifact_hash="c" * 64,
            owner_authorization_hash=None,
            maximum_stress_loss_fraction=0.10,
            maximum_gross=1.0,
            registered_at=T0,
        )

        self.assertEqual(registration.strategy_id, LIVE_PILOT_CONTRACT.strategy)
        self.assertEqual(registration.strategy_version, BASE_STRATEGY_VERSION)
        self.assertEqual(
            registration.strategy_contract_hash,
            LIVE_PILOT_CONTRACT.contract_hash,
        )


if __name__ == "__main__":
    unittest.main()
