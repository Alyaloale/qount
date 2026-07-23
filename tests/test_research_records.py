from __future__ import annotations

import unittest

from qount.governance import CandidateRevalidationRecord
from qount.governance import GlobalExperimentRecord
from qount.governance import HistoricalFamilyMapping
from qount.governance import PointInTimeSymbolLifecycle
from qount.governance import UnifiedNavScorecard
from qount.governance import build_point_in_time_universe
from qount.governance import build_r0_candidate_records


_HASH = "a" * 64


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

    def test_default_candidates_keep_cxd_blocked_and_cta_research_only(self) -> None:
        cxd, cta_r = build_r0_candidate_records()
        self.assertIsInstance(cxd, CandidateRevalidationRecord)
        self.assertEqual(cxd.decision, "blocked")
        self.assertEqual(
            cxd.owner_authorization_state,
            "blocked_pending_owner_authorization",
        )
        self.assertFalse(cxd.execution_contract["orders_allowed"])
        self.assertEqual(cta_r.decision, "planned")
        self.assertEqual(cta_r.owner_authorization_state, "research_only")
        self.assertEqual(cxd.validate(), ())
        self.assertEqual(cta_r.validate(), ())

    def test_family_mapping_is_not_an_automatic_promotion(self) -> None:
        mapping = HistoricalFamilyMapping.create(
            current_family="cta_r_cross_asset",
            historical_family_ids=("cta_old_v1",),
            mapping_reason="same selection-free mechanism; current data contract differs",
        )
        self.assertEqual(mapping.validate(), ())
        self.assertEqual(mapping.mapping_status, "review_required")


if __name__ == "__main__":
    unittest.main()
