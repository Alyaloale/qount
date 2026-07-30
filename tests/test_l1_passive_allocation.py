from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path

from qount.contracts import StrategyIntent
from qount.governance import StrategyRegistry
from qount.governance import validate_registered_intents
from qount.l1_passive_allocation import L1_PASSIVE_ALLOCATION_STRATEGY_ID
from qount.l1_passive_allocation import L1_PASSIVE_ALLOCATION_STRATEGY_VERSION
from qount.l1_passive_allocation import build_l1_passive_allocation_preregistration
from qount.l1_passive_allocation import validate_l1_passive_allocation_preregistration
from qount.persistence import write_immutable_json_document
from qount.strategies import passive_allocation_strategy_registration


class L1PassiveAllocationPreregistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = build_l1_passive_allocation_preregistration()

    def test_policy_freezes_assets_weights_cash_and_calendar(self) -> None:
        validate_l1_passive_allocation_preregistration(self.payload)
        contract = self.payload["contract"]
        self.assertEqual(
            contract["strategic_allocation"]["assets"],
            [
                {
                    "ticker": "SPY",
                    "asset_class": "US_large_cap_equity_ETF",
                    "target_weight": 0.60,
                },
                {
                    "ticker": "TLT",
                    "asset_class": "US_long_duration_treasury_ETF",
                    "target_weight": 0.40,
                },
            ],
        )
        self.assertEqual(contract["cash_rule"]["strategic_target_weight"], 0.0)
        self.assertEqual(contract["rebalance_calendar"]["frequency"], "annual")
        self.assertFalse(contract["rebalance_calendar"]["intra_year_drift_band_rebalance_allowed"])

    def test_tampered_weight_or_authority_fails_closed(self) -> None:
        tampered = json.loads(json.dumps(self.payload))
        tampered["contract"]["strategic_allocation"]["assets"][0]["target_weight"] = 0.70
        with self.assertRaisesRegex(ValueError, "contract_invalid"):
            validate_l1_passive_allocation_preregistration(tampered)

        tampered = json.loads(json.dumps(self.payload))
        tampered["meta"]["orders_authorized"] = True
        with self.assertRaisesRegex(ValueError, "authority_invalid"):
            validate_l1_passive_allocation_preregistration(tampered)

    def test_json_contract_is_published_once_with_restricted_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "passive-preregistration.json"
            receipt = write_immutable_json_document(path, self.payload)
            self.assertEqual(receipt["object"], self.payload)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                write_immutable_json_document(path, self.payload)

    def test_registry_entry_is_research_only(self) -> None:
        registration = passive_allocation_strategy_registration(
            preregistration=self.payload,
            code_hash="a" * 64,
            config_hash="b" * 64,
            registered_at="2026-07-30T12:00:00+00:00",
        )
        self.assertEqual(registration.strategy_id, L1_PASSIVE_ALLOCATION_STRATEGY_ID)
        self.assertEqual(registration.strategy_version, L1_PASSIVE_ALLOCATION_STRATEGY_VERSION)
        self.assertEqual(registration.promotion_status, "research")
        registry = StrategyRegistry.create((registration,), created_at=registration.registered_at)
        intent = StrategyIntent.create(
            strategy_id=registration.strategy_id,
            strategy_version=registration.strategy_version,
            snapshot_id="c" * 64,
            decision_time="2026-08-01T00:00:00+00:00",
            data_cutoff="2026-07-31T00:00:00+00:00",
            target_weights={"SPY": 0.60, "TLT": 0.40},
            expected_holding_bars=252,
            target_stress_loss_fraction=1.0,
            reason_codes=("PASSIVE_ALLOCATION_NOT_AUTHORIZED",),
            evidence_hash="d" * 64,
            state_hash="e" * 64,
        )
        self.assertEqual(validate_registered_intents(registry, (intent,), environment="research"), ())
        self.assertIn(
            "intent:0:strategy_status_not_allowed:research",
            validate_registered_intents(registry, (intent,), environment="paper"),
        )


if __name__ == "__main__":
    unittest.main()
