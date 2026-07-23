from __future__ import annotations

import unittest

from qount.governance import CandidateRevalidationRecord
from qount.governance import GlobalExperimentRecord
from qount.governance import HistoricalFamilyMapping
from qount.governance import PointInTimeSymbolLifecycle
from qount.governance import ResearchEvidenceReadinessRecord
from qount.governance import UnifiedNavScorecard
from qount.governance import build_point_in_time_universe
from qount.governance import build_r0_candidate_records


_HASH = "a" * 64


def _r0_evidence() -> dict[str, ResearchEvidenceReadinessRecord]:
    def record(
        evidence_type: str,
        scope: str,
        *,
        status: str = "partial",
        missing: dict[str, str] | None = None,
    ) -> ResearchEvidenceReadinessRecord:
        return ResearchEvidenceReadinessRecord.create(
            evidence_type=evidence_type,
            scope=scope,
            status=status,
            available_evidence={"contract": "verified"},
            missing_evidence=missing or {},
            source_hashes={"fixture": _HASH},
            supports_research=True,
            supports_candidate_pnl=False,
        )

    return {
        "cxd_family": record(
            "historical_family_mapping",
            "cxd",
            status="available",
        ),
        "cxd_lifecycle": record(
            "point_in_time_lifecycle",
            "cxd",
            missing={"historical_intervals": "not_collected"},
        ),
        "cxd_cost": record(
            "cost_model",
            "cxd",
            missing={"funding_history": "not_collected"},
        ),
        "cxd_nav": record(
            "standalone_nav_readiness",
            "cxd",
            missing={"candidate_nav": "not_computed"},
        ),
        "cta_r_family": record(
            "historical_family_mapping",
            "cta-r",
            status="available",
        ),
        "cta_r_lifecycle": record(
            "point_in_time_lifecycle",
            "cta-r",
            missing={"historical_intervals": "not_collected"},
        ),
        "cta_r_cost": record(
            "cost_model",
            "cta-r",
            missing={"broker_costs": "not_collected"},
        ),
        "cta_r_nav": record(
            "standalone_nav_readiness",
            "cta-r",
            missing={"candidate_nav": "not_computed"},
        ),
    }


class ResearchRecordsTest(unittest.TestCase):
    def test_global_experiment_record_is_hashed_and_validated(self) -> None:
        record = GlobalExperimentRecord.create(
            hypothesis_family="cta_r_cross_asset",
            trial_number_within_family=1,
            research_question="Does selection-free trend survive current costs?",
            economic_mechanism="cross-asset time-series trend",
            baseline_ids=("base_v0.2",),
            preregistered_primary_metric="cost_adjusted_standalone_executable_nav",
            preregistered_failure_conditions=("negative_residual",),
            allowed_sensitivity_range={"cost_bps": [12, 24]},
            dataset_ids=("cta_current_panel",),
            code_hash=_HASH,
            config_hash=_HASH,
        )
        self.assertEqual(record.validate(), ())
        tampered = record.__class__(**{**record.__dict__, "decision": "retain"})
        self.assertIn("global_experiment_record_hash_invalid", tampered.validate())

    def test_point_in_time_universe_does_not_use_future_or_delisted_symbols(self) -> None:
        lifecycles = (
            PointInTimeSymbolLifecycle.create(
                symbol="BTCUSDT",
                venue="binance_um",
                valid_from="2026-01-01T00:00:00+00:00",
                valid_to=None,
                state="active",
                rules_hash=_HASH,
                source_hash=_HASH,
            ),
            PointInTimeSymbolLifecycle.create(
                symbol="OLDUSDT",
                venue="binance_um",
                valid_from="2025-01-01T00:00:00+00:00",
                valid_to="2026-06-01T00:00:00+00:00",
                state="delisted",
                rules_hash=_HASH,
                source_hash=_HASH,
            ),
            PointInTimeSymbolLifecycle.create(
                symbol="FUTUREUSDT",
                venue="binance_um",
                valid_from="2027-01-01T00:00:00+00:00",
                valid_to=None,
                state="active",
                rules_hash=_HASH,
                source_hash=_HASH,
            ),
        )
        revision = build_point_in_time_universe(
            lifecycles,
            as_of="2026-07-23T00:00:00+00:00",
            venue="binance_um",
            source_hashes={"exchange_info": _HASH},
        )
        self.assertEqual(revision.validate(), ())
        self.assertEqual(revision.included_symbols, ("BTCUSDT",))

    def test_scorecard_contains_three_navs_cost_and_trial_count(self) -> None:
        scorecard = UnifiedNavScorecard.create(
            candidate_id="cta-r",
            signal_nav=1.2,
            standalone_executable_nav=1.1,
            portfolio_realized_nav=1.08,
            beta_residual_return=0.07,
            total_cost=0.02,
            cost_model_hash=_HASH,
            trial_count=1,
            fold_metrics=({"fold": 1, "passed": False},),
            data_hash=_HASH,
        )
        self.assertEqual(scorecard.validate(), ())
        self.assertIn("standalone_executable_nav", scorecard.__dict__)

    def test_default_candidates_are_research_active_without_order_authority(self) -> None:
        cxd, cta_r = build_r0_candidate_records(_r0_evidence())
        self.assertIsInstance(cxd, CandidateRevalidationRecord)
        self.assertEqual(cxd.decision, "active_research")
        self.assertEqual(
            cxd.owner_authorization_state,
            "owner_authorized_research",
        )
        self.assertFalse(cxd.execution_contract["orders_allowed"])
        self.assertTrue(cxd.execution_contract["research_execution_allowed"])
        self.assertFalse(cxd.execution_contract["blocks_local_progress"])
        self.assertFalse(cxd.execution_contract["trial_budget_blocks_research"])
        self.assertFalse(cxd.execution_contract["candidate_pnl_ready"])
        self.assertTrue(cxd.historical_evidence_ids[0])
        self.assertTrue(cxd.current_data_ids[0])
        self.assertTrue(cxd.standalone_nav_artifacts[0])
        self.assertEqual(cta_r.decision, "active_research")
        self.assertEqual(
            cta_r.owner_authorization_state,
            "owner_authorized_research",
        )
        self.assertTrue(cta_r.execution_contract["research_execution_allowed"])
        self.assertEqual(cxd.validate(), ())
        self.assertEqual(cta_r.validate(), ())

    def test_carry_order_authority_remains_separate_from_research(self) -> None:
        cxd, _ = build_r0_candidate_records(_r0_evidence())
        unsafe = cxd.__class__(
            **{
                **cxd.__dict__,
                "execution_contract": {
                    **cxd.execution_contract,
                    "orders_allowed": True,
                },
            }
        )
        self.assertIn(
            "candidate_revalidation_carry_order_authorization_required",
            unsafe.validate(),
        )

    def test_family_mapping_is_not_an_automatic_promotion(self) -> None:
        mapping = HistoricalFamilyMapping.create(
            current_family="cta_r_cross_asset",
            historical_family_ids=("cta_old_v1",),
            mapping_reason="same selection-free mechanism; current data contract differs",
        )
        self.assertEqual(mapping.validate(), ())
        self.assertEqual(mapping.mapping_status, "review_required")

    def test_readiness_record_preserves_missing_evidence_without_authority(self) -> None:
        record = _r0_evidence()["cxd_lifecycle"]
        self.assertEqual(record.validate(), ())
        self.assertEqual(record.status, "partial")
        self.assertFalse(record.supports_candidate_pnl)
        self.assertFalse(record.orders_allowed)

        unsafe = record.__class__(
            **{**record.__dict__, "orders_allowed": True}
        )
        self.assertIn(
            "research_evidence_order_authority_forbidden",
            unsafe.validate(),
        )


if __name__ == "__main__":
    unittest.main()
