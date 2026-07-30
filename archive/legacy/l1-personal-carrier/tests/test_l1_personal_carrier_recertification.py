from __future__ import annotations

import hashlib
import json
import math
import tempfile
import unittest
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path

from qount.contracts import canonical_hash
from qount.l1_personal_carrier_recertification import assert_personal_carrier_cache_collection_window
from qount.l1_personal_carrier_recertification import audit_personal_carrier_tiingo_cache
from qount.l1_personal_carrier_recertification import build_personal_carrier_immediate_recertification_preregistration
from qount.l1_personal_carrier_recertification import build_personal_carrier_research_intent
from qount.l1_personal_carrier_recertification import build_personal_carrier_preregistration
from qount.l1_personal_carrier_recertification import claim_personal_carrier_recertification
from qount.l1_personal_carrier_recertification import complete_personal_carrier_recertification
from qount.l1_personal_carrier_recertification import evaluate_personal_carrier_recertification
from qount.l1_personal_carrier_recertification import frozen_l1_s2_signal
from qount.l1_personal_carrier_recertification import L1_PERSONAL_CARRIER_TIINGO_PREPARATION_VERSION
from qount.l1_personal_carrier_recertification import L1_PERSONAL_CARRIER_IMMEDIATE_STRATEGY_VERSION
from qount.l1_personal_carrier_recertification import personal_carrier_strategy_version
from qount.l1_personal_carrier_recertification import validate_personal_carrier_evaluation
from qount.l1_personal_carrier_recertification import validate_personal_carrier_preregistration
from qount.l1_personal_carrier_recertification import validate_personal_carrier_tiingo_cache_preparation


class L1PersonalCarrierPreregistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = build_personal_carrier_preregistration(l1_source_sha256="a" * 64)

    def _tiingo_preparation(self, tiingo_dir: Path) -> dict[str, object]:
        audit = audit_personal_carrier_tiingo_cache(tiingo_cache_dir=tiingo_dir)
        core = {
            "schema_version": L1_PERSONAL_CARRIER_TIINGO_PREPARATION_VERSION,
            "artifact_type": "l1_personal_carrier_tiingo_cache_preparation",
            "prepared_at": "2026-07-30T12:00:00+00:00",
            "preregistration_contract_hash": self.payload["contract_hash"],
            "collection": {
                "download_missing_requested": True,
                "network_download_attempted": True,
                "collection_window_checked_at": "2026-07-30T12:00:00+00:00",
                "start_date": "2010-01-01",
                "existing_cache_files_refreshed": False,
            },
            "cache_audit": audit,
            "meta": {
                "research_only": True,
                "strategy_results_evaluated": False,
                "orders_authorized": False,
                "paper_or_live_allowed": False,
            },
        }
        return core | {"artifact_hash": canonical_hash(core)}

    def _failed_evaluation(self, *, tiingo_cache_preparation_hash: str | None = None) -> dict[str, object]:
        evaluation: dict[str, object] = {
            "schema_version": "l1_personal_carrier_recertification_v0.1",
            "artifact_type": "l1_personal_carrier_recertification_evaluation",
            "evaluated_at": "2026-08-01T00:00:00+00:00",
            "meta": {
                "research_only": True,
                "network_download_attempted": False,
                "orders_authorized": False,
                "paper_or_live_allowed": False,
                "promotion_evidence": False,
            },
            "preregistration_contract_hash": self.payload["contract_hash"],
            "frozen_source_sha256": "a" * 64,
            "input_manifest": {},
            "input_manifest_hash": canonical_hash({}),
            "benchmarks": {
                benchmark_id: {
                    "benchmark_id": benchmark_id,
                    "acceptance_gate": {"pass": False},
                }
                for benchmark_id in ("sixty_forty", "btc_full")
            },
            "acceptance_gate": {
                "pass_requires_all_benchmarks": True,
                "all_benchmarks_pass": False,
                "decision": "accept_buy_and_hold_plus_rebalance_as_sleeve_1_terminal_state",
            },
        }
        if tiingo_cache_preparation_hash is not None:
            evaluation["tiingo_cache_preparation_hash"] = tiingo_cache_preparation_hash
        evaluation["evaluation_hash"] = canonical_hash(evaluation)
        return evaluation

    def test_signal_and_evaluation_controls_are_frozen(self) -> None:
        signal = frozen_l1_s2_signal()
        self.assertEqual(len(signal["universe"]), 21)
        self.assertEqual(signal["lookback_weeks_grid"], [13, 26, 39, 52])
        self.assertEqual(signal["cost_per_side_fraction"], 0.0006)
        validate_personal_carrier_preregistration(self.payload)

    def test_all_benchmarks_must_pass_and_results_are_deferred(self) -> None:
        contract = self.payload["contract"]
        self.assertTrue(contract["acceptance_gate"]["pass_requires_all_benchmarks"])
        self.assertEqual(contract["result_controls"]["not_before_utc"], "2026-07-31T00:00:00+00:00")
        self.assertFalse(self.payload["meta"]["strategy_results_evaluated"])
        self.assertFalse(self.payload["meta"]["orders_authorized"])

    def test_owner_immediate_successor_preserves_the_frozen_contract_surface(self) -> None:
        authorized_at = datetime(2026, 7, 30, 12, tzinfo=timezone.utc)
        successor = build_personal_carrier_immediate_recertification_preregistration(
            superseded_preregistration=self.payload,
            l1_source_sha256="a" * 64,
            authorized_at=authorized_at,
        )
        validate_personal_carrier_preregistration(successor)
        self.assertNotEqual(successor["contract_hash"], self.payload["contract_hash"])
        self.assertEqual(
            successor["contract"]["supersession"]["superseded_preregistration_contract_hash"],
            self.payload["contract_hash"],
        )
        self.assertEqual(
            successor["contract"]["result_controls"]["not_before_utc"],
            authorized_at.isoformat(),
        )
        self.assertEqual(
            successor["contract"]["benchmarks"],
            self.payload["contract"]["benchmarks"],
        )
        self.assertEqual(
            personal_carrier_strategy_version(successor),
            L1_PERSONAL_CARRIER_IMMEDIATE_STRATEGY_VERSION,
        )
        with self.assertRaisesRegex(
            ValueError,
            "personal_carrier_supersession_not_needed_after_original_embargo",
        ):
            build_personal_carrier_immediate_recertification_preregistration(
                superseded_preregistration=self.payload,
                l1_source_sha256="a" * 64,
                authorized_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )

    def test_immediate_successor_can_only_reuse_the_original_pre_embargo_cache_admission(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            tiingo_dir = Path(temporary_dir)
            for ticker in frozen_l1_s2_signal()["universe"]:
                (tiingo_dir / f"tiingo_{ticker}.json").write_text(
                    '[{"date":"2020-01-01T00:00:00+00:00","adjClose":100.0}]',
                    encoding="utf-8",
                )
            preparation = self._tiingo_preparation(tiingo_dir)
            successor = build_personal_carrier_immediate_recertification_preregistration(
                superseded_preregistration=self.payload,
                l1_source_sha256="a" * 64,
                authorized_at=datetime(2026, 7, 30, 12, tzinfo=timezone.utc),
            )
            validate_personal_carrier_tiingo_cache_preparation(
                preparation,
                preregistration=successor,
            )

    def test_tampering_fails_validation(self) -> None:
        self.payload["contract"]["signal"]["rebalance"] = "monthly"
        with self.assertRaisesRegex(ValueError, "contract hash mismatch"):
            validate_personal_carrier_preregistration(self.payload)

    def test_evaluation_respects_the_result_embargo_before_reading_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "evaluation_not_allowed_before"):
            evaluate_personal_carrier_recertification(
                preregistration=self.payload,
                tiingo_cache_dir="/missing/tiingo",
                btc_cache_path="/missing/btc.csv",
                btc_source_manifest_path="/missing/btc-manifest.json",
                frozen_source_sha256="a" * 64,
                evaluated_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
            )

    def test_consumption_claim_does_not_create_a_record_before_embargo(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            with self.assertRaisesRegex(ValueError, "evaluation_not_allowed_before"):
                claim_personal_carrier_recertification(
                    state_dir=root / "state",
                    preregistration=self.payload,
                    tiingo_cache_preparation={},
                    frozen_source_sha256="a" * 64,
                    claimed_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
                )
            self.assertFalse((root / "state").exists())

    def test_cache_collection_window_closes_when_results_become_available(self) -> None:
        allowed_at = assert_personal_carrier_cache_collection_window(
            self.payload,
            checked_at=datetime(2026, 7, 30, 23, 59, 59, tzinfo=timezone.utc),
        )
        self.assertEqual(allowed_at.date().isoformat(), "2026-07-30")
        with self.assertRaisesRegex(ValueError, "cache_collection_not_allowed_on_or_after"):
            assert_personal_carrier_cache_collection_window(
                self.payload,
                checked_at=datetime(2026, 7, 31, tzinfo=timezone.utc),
            )

    def test_tiingo_cache_audit_is_result_free_and_reports_missing_universe_members(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            audit = audit_personal_carrier_tiingo_cache(tiingo_cache_dir=temporary_dir)

        self.assertFalse(audit["complete"])
        self.assertEqual(audit["missing_tickers"], frozen_l1_s2_signal()["universe"])
        self.assertEqual(audit["tiingo_adjusted_close_caches"], [])
        self.assertFalse(audit["meta"]["strategy_results_evaluated"])
        self.assertFalse(audit["meta"]["orders_authorized"])
        self.assertEqual(
            audit["cache_audit_hash"],
            canonical_hash({key: value for key, value in audit.items() if key != "cache_audit_hash"}),
        )

    def test_cache_only_evaluation_hashes_every_input_and_compares_both_benchmarks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            tiingo_dir = root / "tiingo"
            tiingo_dir.mkdir()
            start = datetime(2020, 1, 1, tzinfo=timezone.utc)
            for symbol_index, ticker in enumerate(frozen_l1_s2_signal()["universe"]):
                rows = []
                price = 100.0 + symbol_index
                for week in range(90):
                    price *= 1.0 + 0.002 * math.sin(week / 3.0 + symbol_index) + 0.0004 * (symbol_index + 1)
                    rows.append({
                        "date": (start + timedelta(days=7 * week)).isoformat(),
                        "adjClose": price,
                    })
                (tiingo_dir / f"tiingo_{ticker}.json").write_text(json.dumps(rows), encoding="utf-8")

            btc_cache = root / "btc.csv"
            lines = ["date,close"]
            btc_price = 7_000.0
            for week in range(90):
                btc_price *= 1.0 + 0.006 * math.cos(week / 4.0) + 0.001
                lines.append(f"{(start + timedelta(days=7 * week)).date().isoformat()},{btc_price:.8f}")
            btc_cache.write_text("\n".join(lines) + "\n", encoding="utf-8")
            source_manifest_core = {
                "schema_version": "l1_sealed_btc_daily_cache_v0.1",
                "asset": "BTCUSDT",
                "frequency": "1d",
                "daily_cache": {"sha256": hashlib.sha256(btc_cache.read_bytes()).hexdigest()},
                "source_archives": [{"sha256": "b" * 64}],
                "network_download_attempted": False,
            }
            btc_source_manifest = root / "btc-source-manifest.json"
            btc_source_manifest.write_text(json.dumps({
                **source_manifest_core,
                "manifest_hash": canonical_hash(source_manifest_core),
            }), encoding="utf-8")
            preparation = self._tiingo_preparation(tiingo_dir)

            result = evaluate_personal_carrier_recertification(
                preregistration=self.payload,
                tiingo_cache_dir=tiingo_dir,
                btc_cache_path=btc_cache,
                btc_source_manifest_path=btc_source_manifest,
                frozen_source_sha256="a" * 64,
                tiingo_cache_preparation=preparation,
                evaluated_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )
            with (tiingo_dir / "tiingo_SPY.json").open("a", encoding="utf-8") as handle:
                handle.write("\n")
            with self.assertRaisesRegex(ValueError, "prepared_tiingo_cache_does_not_match_evaluation"):
                evaluate_personal_carrier_recertification(
                    preregistration=self.payload,
                    tiingo_cache_dir=tiingo_dir,
                    btc_cache_path=btc_cache,
                    btc_source_manifest_path=btc_source_manifest,
                    frozen_source_sha256="a" * 64,
                    tiingo_cache_preparation=preparation,
                    evaluated_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                )

        self.assertFalse(result["meta"]["network_download_attempted"])
        self.assertEqual(result["tiingo_cache_preparation_hash"], preparation["artifact_hash"])
        self.assertEqual(len(result["input_manifest"]["tiingo_adjusted_close_caches"]), 21)
        self.assertEqual(set(result["benchmarks"]), {"sixty_forty", "btc_full"})
        self.assertIn("pass", result["benchmarks"]["sixty_forty"]["acceptance_gate"])
        self.assertEqual(
            result["input_manifest"]["tiingo_adjusted_close_caches"][0]["raw_row_count"], 90
        )
        for benchmark in result["benchmarks"].values():
            self.assertEqual(
                benchmark["strategy"]["first_period_start_utc"],
                benchmark["benchmark"]["first_period_start_utc"],
            )
            self.assertEqual(
                benchmark["strategy"]["last_period_end_utc"],
                benchmark["benchmark"]["last_period_end_utc"],
            )
        self.assertIn(result["acceptance_gate"]["decision"], {
            "research_pass_not_promotion",
            "accept_buy_and_hold_plus_rebalance_as_sleeve_1_terminal_state",
        })

    def test_evaluation_rejects_a_source_different_from_the_preregistration(self) -> None:
        with self.assertRaisesRegex(ValueError, "frozen_l1_source_hash_mismatch"):
            evaluate_personal_carrier_recertification(
                preregistration=self.payload,
                tiingo_cache_dir="/missing/tiingo",
                btc_cache_path="/missing/btc.csv",
                btc_source_manifest_path="/missing/btc-manifest.json",
                frozen_source_sha256="b" * 64,
                evaluated_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )

    def test_evaluation_hash_detects_post_evaluation_tampering(self) -> None:
        evaluation = self._failed_evaluation()
        validate_personal_carrier_evaluation(
            evaluation,
            preregistration=self.payload,
            frozen_source_sha256="a" * 64,
        )
        evaluation["acceptance_gate"]["decision"] = "research_pass_not_promotion"
        with self.assertRaisesRegex(ValueError, "evaluation_hash_invalid"):
            validate_personal_carrier_evaluation(
                evaluation,
                preregistration=self.payload,
                frozen_source_sha256="a" * 64,
            )

    def test_failed_evaluation_returns_passive_fallback_before_loading_inputs(self) -> None:
        evaluation = self._failed_evaluation()

        result = build_personal_carrier_research_intent(
            preregistration=self.payload,
            evaluation=evaluation,
            frozen_source_sha256="a" * 64,
            built_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )

        self.assertEqual(result["status"], "terminal_passive_fallback")
        self.assertIsNone(result["strategy_intent"])
        self.assertFalse(result["meta"]["orders_authorized"])
        self.assertIn("RECERTIFICATION_NOT_PASSED", result["execution_blockers"])

    def test_recertification_consumption_is_once_only_and_tamper_evident(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            tiingo_dir = root / "tiingo"
            tiingo_dir.mkdir()
            for ticker in frozen_l1_s2_signal()["universe"]:
                (tiingo_dir / f"tiingo_{ticker}.json").write_text(
                    '[{"date":"2020-01-01T00:00:00+00:00","adjClose":100.0}]',
                    encoding="utf-8",
                )
            preparation = self._tiingo_preparation(tiingo_dir)
            claimed = claim_personal_carrier_recertification(
                state_dir=root / "state",
                preregistration=self.payload,
                tiingo_cache_preparation=preparation,
                frozen_source_sha256="a" * 64,
                claimed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )
            self.assertEqual(claimed["status"], "claimed")
            with self.assertRaisesRegex(
                ValueError,
                "personal_carrier_recertification_already_started_without_terminal_artifact",
            ):
                claim_personal_carrier_recertification(
                    state_dir=root / "state",
                    preregistration=self.payload,
                    tiingo_cache_preparation=preparation,
                    frozen_source_sha256="a" * 64,
                    claimed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                )

            completed = complete_personal_carrier_recertification(
                state_dir=root / "state",
                preregistration=self.payload,
                tiingo_cache_preparation=preparation,
                frozen_source_sha256="a" * 64,
                evaluation=self._failed_evaluation(
                    tiingo_cache_preparation_hash=str(preparation["artifact_hash"])
                ),
                completed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )
            self.assertEqual(completed["status"], "completed")
            reread = claim_personal_carrier_recertification(
                state_dir=root / "state",
                preregistration=self.payload,
                tiingo_cache_preparation=preparation,
                frozen_source_sha256="a" * 64,
                claimed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
            )
            self.assertEqual(reread["status"], "completed")
            self.assertEqual(
                reread["evaluation"]["evaluation_hash"],
                self._failed_evaluation(
                    tiingo_cache_preparation_hash=str(preparation["artifact_hash"])
                )["evaluation_hash"],
            )
            evaluation_path = Path(reread["evaluation_path"])
            evaluation_path.write_text(evaluation_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError,
                "personal_carrier_consumption_evaluation_file_hash_mismatch",
            ):
                claim_personal_carrier_recertification(
                    state_dir=root / "state",
                    preregistration=self.payload,
                    tiingo_cache_preparation=preparation,
                    frozen_source_sha256="a" * 64,
                    claimed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
                )

    def test_passing_evaluation_builds_only_a_blocked_research_intent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            tiingo_dir = root / "tiingo"
            tiingo_dir.mkdir()
            start = datetime(2020, 1, 1, tzinfo=timezone.utc)
            for symbol_index, ticker in enumerate(frozen_l1_s2_signal()["universe"]):
                rows = []
                price = 100.0 + symbol_index
                for week in range(90):
                    price *= 1.0 + 0.002 * math.sin(week / 3.0 + symbol_index) + 0.0004 * (symbol_index + 1)
                    rows.append({
                        "date": (start + timedelta(days=7 * week)).isoformat(),
                        "adjClose": price,
                    })
                (tiingo_dir / f"tiingo_{ticker}.json").write_text(json.dumps(rows), encoding="utf-8")

            btc_cache = root / "btc.csv"
            lines = ["date,close"]
            btc_price = 7_000.0
            for week in range(90):
                btc_price *= 1.0 + 0.006 * math.cos(week / 4.0) + 0.001
                lines.append(f"{(start + timedelta(days=7 * week)).date().isoformat()},{btc_price:.8f}")
            btc_cache.write_text("\n".join(lines) + "\n", encoding="utf-8")
            source_manifest_core = {
                "schema_version": "l1_sealed_btc_daily_cache_v0.1",
                "asset": "BTCUSDT",
                "frequency": "1d",
                "daily_cache": {"sha256": hashlib.sha256(btc_cache.read_bytes()).hexdigest()},
                "source_archives": [{"sha256": "b" * 64}],
                "network_download_attempted": False,
            }
            btc_source_manifest = root / "btc-source-manifest.json"
            btc_source_manifest.write_text(json.dumps({
                **source_manifest_core,
                "manifest_hash": canonical_hash(source_manifest_core),
            }), encoding="utf-8")
            evaluation = evaluate_personal_carrier_recertification(
                preregistration=self.payload,
                tiingo_cache_dir=tiingo_dir,
                btc_cache_path=btc_cache,
                btc_source_manifest_path=btc_source_manifest,
                frozen_source_sha256="a" * 64,
                evaluated_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )
            # This is a synthetic contract test for the post-pass path, not an
            # assertion about the generated fixture's investment performance.
            for benchmark in evaluation["benchmarks"].values():
                benchmark["acceptance_gate"]["pass"] = True
            evaluation["acceptance_gate"] = {
                "pass_requires_all_benchmarks": True,
                "all_benchmarks_pass": True,
                "decision": "research_pass_not_promotion",
            }
            evaluation["evaluation_hash"] = canonical_hash({
                key: value for key, value in evaluation.items() if key != "evaluation_hash"
            })

            result = build_personal_carrier_research_intent(
                preregistration=self.payload,
                evaluation=evaluation,
                frozen_source_sha256="a" * 64,
                tiingo_cache_dir=tiingo_dir,
                btc_cache_path=btc_cache,
                btc_source_manifest_path=btc_source_manifest,
                decision_time=datetime(2026, 8, 2, tzinfo=timezone.utc),
                built_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
            )
            venue_ready_result = build_personal_carrier_research_intent(
                preregistration=self.payload,
                evaluation=evaluation,
                frozen_source_sha256="a" * 64,
                tiingo_cache_dir=tiingo_dir,
                btc_cache_path=btc_cache,
                btc_source_manifest_path=btc_source_manifest,
                venue_capability={
                    "venue_id": "fixture-short-venue",
                    "approved_for_research": True,
                    "supports_all_l1_instruments": True,
                    "supports_long_positions": True,
                    "supports_short_positions": True,
                    "capability_evidence_hash": "c" * 64,
                },
                decision_time=datetime(2026, 8, 2, tzinfo=timezone.utc),
                built_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
            )

        self.assertEqual(result["status"], "blocked_venue_short_capability")
        self.assertTrue(result["requires_short_capability"])
        self.assertFalse(result["meta"]["orders_authorized"])
        self.assertIn("VENUE_SHORT_CAPABILITY_UNVERIFIED", result["execution_blockers"])
        intent = result["strategy_intent"]
        self.assertIsNotNone(intent)
        self.assertAlmostEqual(
            sum(abs(float(weight)) for weight in intent["target_weights"].values()),
            1.0,
        )
        self.assertEqual(intent["target_stress_loss_fraction"], 1.0)
        self.assertEqual(
            venue_ready_result["status"],
            "research_target_ready_execution_still_blocked",
        )
        self.assertFalse(venue_ready_result["meta"]["orders_authorized"])

    def test_intent_builder_respects_embargo_before_reading_evaluation(self) -> None:
        with self.assertRaisesRegex(ValueError, "evaluation_not_allowed_before"):
            build_personal_carrier_research_intent(
                preregistration=self.payload,
                evaluation={},
                frozen_source_sha256="a" * 64,
                built_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()
