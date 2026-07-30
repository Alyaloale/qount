from __future__ import annotations

from datetime import datetime
from datetime import timezone
import unittest

from qount.contracts import StrategyIntent
from qount.governance import StrategyRegistry
from qount.governance import validate_registered_intents
from qount.l1_personal_carrier_recertification import L1_PERSONAL_CARRIER_STRATEGY_ID
from qount.l1_personal_carrier_recertification import L1_PERSONAL_CARRIER_STRATEGY_VERSION
from qount.l1_personal_carrier_recertification import L1_PERSONAL_CARRIER_IMMEDIATE_STRATEGY_VERSION
from qount.l1_personal_carrier_recertification import build_personal_carrier_immediate_recertification_preregistration
from qount.l1_personal_carrier_recertification import build_personal_carrier_preregistration
from qount.persistence import dump_artifact
from qount.persistence import load_artifact
from qount.strategies import personal_carrier_strategy_registration


class PersonalCarrierStrategyRegistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.preregistration = build_personal_carrier_preregistration(
            l1_source_sha256="a" * 64
        )
        self.registered_at = "2026-07-30T12:00:00+00:00"
        self.registration = personal_carrier_strategy_registration(
            preregistration=self.preregistration,
            code_hash="b" * 64,
            config_hash="c" * 64,
            registered_at=self.registered_at,
        )

    def test_standard_registration_is_research_only_and_round_trips(self) -> None:
        self.assertEqual(self.registration.strategy_id, L1_PERSONAL_CARRIER_STRATEGY_ID)
        self.assertEqual(self.registration.strategy_version, L1_PERSONAL_CARRIER_STRATEGY_VERSION)
        self.assertEqual(self.registration.promotion_status, "research")
        self.assertIsNone(self.registration.promotion_artifact_hash)
        self.assertIsNone(self.registration.owner_authorization_hash)
        self.assertEqual(self.registration.maximum_stress_loss_fraction, 1.0)
        self.assertEqual(load_artifact(dump_artifact(self.registration)), self.registration)

    def test_registered_intent_is_accepted_only_in_research_environment(self) -> None:
        registry = StrategyRegistry.create(
            (self.registration,),
            created_at=self.registered_at,
        )
        intent = StrategyIntent.create(
            strategy_id=L1_PERSONAL_CARRIER_STRATEGY_ID,
            strategy_version=L1_PERSONAL_CARRIER_STRATEGY_VERSION,
            snapshot_id="d" * 64,
            decision_time="2026-08-01T00:00:00+00:00",
            data_cutoff="2026-07-31T00:00:00+00:00",
            target_weights={"SPY": 1.0},
            expected_holding_bars=1,
            target_stress_loss_fraction=1.0,
            reason_codes=("L1_ORDERS_UNAUTHORIZED",),
            evidence_hash="e" * 64,
            state_hash="f" * 64,
        )

        self.assertEqual(validate_registered_intents(registry, (intent,), environment="research"), ())
        self.assertIn(
            "intent:0:strategy_status_not_allowed:research",
            validate_registered_intents(registry, (intent,), environment="shadow"),
        )
        self.assertIn(
            "intent:0:strategy_status_not_allowed:research",
            validate_registered_intents(registry, (intent,), environment="production"),
        )

    def test_immediate_successor_uses_a_new_research_only_strategy_version(self) -> None:
        successor = build_personal_carrier_immediate_recertification_preregistration(
            superseded_preregistration=self.preregistration,
            l1_source_sha256="a" * 64,
            authorized_at=datetime(2026, 7, 30, 12, tzinfo=timezone.utc),
        )
        registration = personal_carrier_strategy_registration(
            preregistration=successor,
            code_hash="b" * 64,
            config_hash="c" * 64,
            registered_at=self.registered_at,
        )
        self.assertEqual(
            registration.strategy_version,
            L1_PERSONAL_CARRIER_IMMEDIATE_STRATEGY_VERSION,
        )
        self.assertEqual(registration.promotion_status, "research")


if __name__ == "__main__":
    unittest.main()
