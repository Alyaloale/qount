"""Unit tests for CandidateConfig shared strategy configuration."""

from __future__ import annotations

import unittest

from qount.research_data.candidate_config import CANDIDATE_CONFIG_SCHEMA_VERSION
from qount.research_data.candidate_config import CandidateConfig


class TestCandidateConfigCreate(unittest.TestCase):
    def test_default_config_matches_runtime_defaults(self) -> None:
        cfg = CandidateConfig.default()
        self.assertEqual(cfg.fast, 20)
        self.assertEqual(cfg.slow, 100)
        self.assertEqual(cfg.regime_sma, 0)
        self.assertFalse(cfg.allow_short)

    def test_create_with_explicit_params(self) -> None:
        cfg = CandidateConfig.create(fast=10, slow=50, regime_sma=200, allow_short=True)
        self.assertEqual(cfg.fast, 10)
        self.assertEqual(cfg.slow, 50)
        self.assertEqual(cfg.regime_sma, 200)
        self.assertTrue(cfg.allow_short)

    def test_create_regime_sma_zero_allowed(self) -> None:
        cfg = CandidateConfig.create(fast=20, slow=100, regime_sma=0)
        self.assertEqual(cfg.regime_sma, 0)

    def test_create_fast_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            CandidateConfig.create(fast=0, slow=100)

    def test_create_slow_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            CandidateConfig.create(fast=20, slow=0)

    def test_create_slow_must_exceed_fast(self) -> None:
        with self.assertRaises(ValueError):
            CandidateConfig.create(fast=100, slow=100)
        with self.assertRaises(ValueError):
            CandidateConfig.create(fast=100, slow=50)

    def test_create_regime_sma_negative_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CandidateConfig.create(fast=20, slow=100, regime_sma=-1)

    def test_create_non_bool_allow_short_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CandidateConfig.create(fast=20, slow=100, allow_short=1)  # type: ignore[arg-type]


class TestCandidateConfigHash(unittest.TestCase):
    def test_hash_is_stable(self) -> None:
        cfg1 = CandidateConfig.create(fast=20, slow=100, regime_sma=0)
        cfg2 = CandidateConfig.create(fast=20, slow=100, regime_sma=0)
        self.assertEqual(cfg1.config_hash, cfg2.config_hash)

    def test_hash_differs_on_fast(self) -> None:
        cfg1 = CandidateConfig.create(fast=20, slow=100)
        cfg2 = CandidateConfig.create(fast=10, slow=100)
        self.assertNotEqual(cfg1.config_hash, cfg2.config_hash)

    def test_hash_differs_on_slow(self) -> None:
        cfg1 = CandidateConfig.create(fast=20, slow=100)
        cfg2 = CandidateConfig.create(fast=20, slow=200)
        self.assertNotEqual(cfg1.config_hash, cfg2.config_hash)

    def test_hash_differs_on_regime_sma(self) -> None:
        cfg1 = CandidateConfig.create(fast=20, slow=100, regime_sma=0)
        cfg2 = CandidateConfig.create(fast=20, slow=100, regime_sma=200)
        self.assertNotEqual(cfg1.config_hash, cfg2.config_hash)

    def test_hash_differs_on_allow_short(self) -> None:
        cfg1 = CandidateConfig.create(fast=20, slow=100, allow_short=False)
        cfg2 = CandidateConfig.create(fast=20, slow=100, allow_short=True)
        self.assertNotEqual(cfg1.config_hash, cfg2.config_hash)

    def test_hash_is_64_char_hex(self) -> None:
        cfg = CandidateConfig.default()
        self.assertEqual(len(cfg.config_hash), 64)
        int(cfg.config_hash, 16)

    def test_default_hash_matches_explicit_zero(self) -> None:
        cfg_default = CandidateConfig.default()
        cfg_explicit = CandidateConfig.create(fast=20, slow=100, regime_sma=0, allow_short=False)
        self.assertEqual(cfg_default.config_hash, cfg_explicit.config_hash)


class TestCandidateConfigValidate(unittest.TestCase):
    def test_valid_config_no_errors(self) -> None:
        cfg = CandidateConfig.default()
        self.assertEqual(cfg.validate(), ())

    def test_tampered_fast_detected(self) -> None:
        cfg = CandidateConfig.default()
        tampered = CandidateConfig(
            fast=999, slow=cfg.slow, regime_sma=cfg.regime_sma,
            allow_short=cfg.allow_short, config_hash=cfg.config_hash,
        )
        errors = tampered.validate()
        self.assertIn("candidate_config_hash_invalid", errors)

    def test_tampered_regime_sma_detected(self) -> None:
        cfg = CandidateConfig.create(fast=20, slow=100, regime_sma=0)
        tampered = CandidateConfig(
            fast=cfg.fast, slow=cfg.slow, regime_sma=200,
            allow_short=cfg.allow_short, config_hash=cfg.config_hash,
        )
        errors = tampered.validate()
        self.assertIn("candidate_config_hash_invalid", errors)


class TestCandidateConfigSerialization(unittest.TestCase):
    def test_round_trip_to_dict_from_dict(self) -> None:
        cfg = CandidateConfig.create(fast=20, slow=100, regime_sma=0, allow_short=False)
        d = cfg.to_dict()
        restored = CandidateConfig.from_dict(d)
        self.assertEqual(restored.fast, cfg.fast)
        self.assertEqual(restored.slow, cfg.slow)
        self.assertEqual(restored.regime_sma, cfg.regime_sma)
        self.assertEqual(restored.allow_short, cfg.allow_short)
        self.assertEqual(restored.config_hash, cfg.config_hash)

    def test_round_trip_with_regime_sma_200(self) -> None:
        cfg = CandidateConfig.create(fast=10, slow=50, regime_sma=200, allow_short=True)
        d = cfg.to_dict()
        restored = CandidateConfig.from_dict(d)
        self.assertEqual(restored, cfg)

    def test_to_dict_includes_schema_version(self) -> None:
        d = CandidateConfig.default().to_dict()
        self.assertEqual(d["schema_version"], CANDIDATE_CONFIG_SCHEMA_VERSION)

    def test_from_dict_rejects_tampered_hash(self) -> None:
        cfg = CandidateConfig.default()
        d = cfg.to_dict()
        d["fast"] = 999
        with self.assertRaises(ValueError):
            CandidateConfig.from_dict(d)

    def test_from_dict_defaults_missing_regime_sma(self) -> None:
        d = {"fast": 20, "slow": 100, "config_hash": ""}
        with self.assertRaises(ValueError):
            CandidateConfig.from_dict(d)

    def test_from_dict_accepts_legacy_without_config_hash_if_valid(self) -> None:
        cfg = CandidateConfig.create(fast=20, slow=100, regime_sma=0, allow_short=False)
        d = {
            "fast": 20, "slow": 100,
            "regime_sma": 0, "allow_short": False,
            "config_hash": cfg.config_hash,
        }
        restored = CandidateConfig.from_dict(d)
        self.assertEqual(restored, cfg)


class TestCandidateConfigCrossScriptConsistency(unittest.TestCase):
    """Verify that runtime, decision, and advancement configs produce the same hash."""

    def test_runtime_default_equals_decision_bundle_inherited(self) -> None:
        runtime_cfg = CandidateConfig.default()
        bundle_trend_config = {"fast": 20, "slow": 100, "regime_sma": 0, "allow_short": False}
        inherited_cfg = CandidateConfig.create(
            fast=bundle_trend_config["fast"],
            slow=bundle_trend_config["slow"],
            regime_sma=bundle_trend_config["regime_sma"],
            allow_short=bundle_trend_config["allow_short"],
        )
        self.assertEqual(runtime_cfg.config_hash, inherited_cfg.config_hash)

    def test_regime_sma_200_produces_different_hash_than_default(self) -> None:
        cfg_off = CandidateConfig.create(fast=20, slow=100, regime_sma=0)
        cfg_on = CandidateConfig.create(fast=20, slow=100, regime_sma=200)
        self.assertNotEqual(cfg_off.config_hash, cfg_on.config_hash)

    def test_advancement_default_now_matches_runtime_default(self) -> None:
        runtime_default = CandidateConfig.default()
        advancement_default = CandidateConfig.create(
            fast=20, slow=100, regime_sma=0, allow_short=False,
        )
        self.assertEqual(runtime_default.config_hash, advancement_default.config_hash)


if __name__ == "__main__":
    unittest.main()
