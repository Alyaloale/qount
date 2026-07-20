from __future__ import annotations

import unittest

from qount.mini_trend.macro_h41_model import H41FeatureAuditConfig
from qount.mini_trend.macro_h41_model import augment_dataset_with_h41_feature


class MiniTrendMacroH41ModelTest(unittest.TestCase):
    def test_model_seed_matches_retained_rolling_control(self) -> None:
        config = H41FeatureAuditConfig()
        self.assertEqual(config.model_seed, config.seed + 60 * 100 + 365)

    def test_asof_join_never_uses_future_release(self) -> None:
        base = {
            "schema_version": "base",
            "artifact_type": "base",
            "created_at": "x",
            "features": ["price"],
            "contract": {"contract_hash": "base", "test_years": [2023]},
            "summary": {"row_count": 2},
            "data_hash": "base-data",
            "rows": [
                {"decision_date": "2023-01-06", "features": {"price": 1.0}},
                {"decision_date": "2023-01-12", "features": {"price": 2.0}},
            ],
        }
        h41 = {
            "contract": {"contract_hash": "h41"},
            "data_hash": "h41-data",
            "diagnostics": {"verdict": "pass_point_in_time_macro_dataset"},
            "weekly_features": [
                {
                    "observation_date": "2023-01-04",
                    "release_date": "2023-01-05",
                    "decision_date": "2023-01-06",
                    "fed_assets_4w_change_pct": 0.1,
                    "fed_assets_13w_change_pct": 0.2,
                    "fed_assets_4w_acceleration": 0.3,
                },
                {
                    "observation_date": "2023-01-11",
                    "release_date": "2023-01-12",
                    "decision_date": "2023-01-13",
                    "fed_assets_4w_change_pct": 9.9,
                    "fed_assets_13w_change_pct": 9.9,
                    "fed_assets_4w_acceleration": 9.9,
                },
            ],
        }
        result = augment_dataset_with_h41_feature(
            base, h41, "fed_assets_4w_change_pct"
        )
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(result["rows"][0]["features"]["fed_assets_4w_change_pct"], 0.1)
        self.assertEqual(result["rows"][1]["features"]["fed_assets_4w_change_pct"], 0.1)
        self.assertEqual(
            result["rows"][1]["h41_lineage"]["macro_decision_date"], "2023-01-06"
        )

    def test_rejects_dataset_that_failed_point_in_time_gate(self) -> None:
        with self.assertRaisesRegex(ValueError, "point-in-time"):
            augment_dataset_with_h41_feature(
                {"rows": []},
                {"diagnostics": {"verdict": "block_data"}},
                "fed_assets_4w_change_pct",
            )

    def test_augmentation_preserves_existing_extended_feature_list(self) -> None:
        base = {
            "contract": {
                "contract_hash": "base",
                "test_years": [2023],
                "feature_names": ["price", "hashrate_z90"],
            },
            "summary": {"row_count": 1},
            "data_hash": "base-data",
            "rows": [
                {
                    "decision_date": "2023-01-06",
                    "features": {"price": 1.0, "hashrate_z90": 2.0},
                }
            ],
        }
        h41 = {
            "contract": {"contract_hash": "h41"},
            "data_hash": "h41-data",
            "diagnostics": {"verdict": "pass_point_in_time_macro_dataset"},
            "weekly_features": [
                {
                    "observation_date": "2023-01-04",
                    "release_date": "2023-01-05",
                    "decision_date": "2023-01-06",
                    "fed_assets_4w_change_pct": 0.1,
                    "fed_assets_13w_change_pct": 0.2,
                    "fed_assets_4w_acceleration": 0.3,
                }
            ],
        }
        result = augment_dataset_with_h41_feature(
            base, h41, "fed_assets_4w_change_pct"
        )
        self.assertEqual(
            result["features"],
            ["price", "hashrate_z90", "fed_assets_4w_change_pct"],
        )


if __name__ == "__main__":
    unittest.main()
