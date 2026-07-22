from __future__ import annotations

import json
import unittest

from qount.contracts import canonical_hash
from qount.persistence import ArtifactCodecError
from qount.persistence import dump_artifact
from qount.persistence import load_artifact
from qount.venue import COMPATIBILITY_LEVELS
from qount.venue import VENUE_SCHEMA_VERSION
from qount.venue import ChangelogDiff
from qount.venue import VenueCapabilitySnapshot
from qount.venue import build_venue_capability_snapshot
from qount.venue import diff_changelog

_HASH_A = "a" * 64
_HASH_B = "b" * 64
_OBSERVED = "2026-07-23T10:00:00+00:00"
_REVIEWED = "2026-07-22T00:00:00+00:00"

_EXCHANGE_INFO = {
    "symbols": [
        {"symbol": "BTCUSDT", "pricePrecision": 2, "quantityPrecision": 3},
    ],
    "rateLimits": [{"rateLimitType": "ORDERS", "limit": 300}],
}
_SYMBOL_RULES = {
    "BTCUSDT": {"minQty": 0.001, "minNotional": 5.0, "pricePrecision": 2},
}


def _make_snapshot(**overrides) -> VenueCapabilitySnapshot:
    params: dict = dict(
        venue="binance_usdm",
        observed_at=_OBSERVED,
        server_time_offset_ms=0,
        exchange_info_schema_hash=_HASH_A,
        symbol_rules_hash=_HASH_B,
        position_mode="one_way",
        margin_mode="isolated",
        leverage=1,
        order_endpoint_contract_hashes={},
        algo_endpoint_contract_hashes={},
        order_capabilities={},
        conditional_algo_capabilities={},
        query_retention_assumptions={},
        websocket_assumptions={},
        rest_recovery_assumptions={},
        changelog_last_reviewed_at=_REVIEWED,
        changelog_source_hash=_HASH_A,
        compatibility="pass",
        blockers=(),
    )
    params.update(overrides)
    return VenueCapabilitySnapshot.create(**params)


class VenueCapabilitySnapshotTest(unittest.TestCase):
    def test_create_produces_valid_snapshot(self):
        snap = _make_snapshot()
        self.assertEqual(snap.schema_version, VENUE_SCHEMA_VERSION)
        self.assertEqual(snap.venue, "binance_usdm")
        self.assertEqual(snap.compatibility, "pass")
        self.assertFalse(snap.validate())

    def test_invalid_venue_rejected(self):
        with self.assertRaises(ValueError):
            _make_snapshot(venue="Invalid Venue")

    def test_invalid_hash_fields_rejected(self):
        with self.assertRaises(ValueError):
            _make_snapshot(exchange_info_schema_hash="not-a-hash")

    def test_invalid_leverage_rejected(self):
        with self.assertRaises(ValueError):
            _make_snapshot(leverage=0)

    def test_blocked_requires_blockers(self):
        with self.assertRaises(ValueError):
            _make_snapshot(compatibility="blocked", blockers=())

    def test_pass_disallows_blockers(self):
        with self.assertRaises(ValueError):
            _make_snapshot(compatibility="pass", blockers=("some_blocker",))

    def test_review_required_allows_blockers(self):
        snap = _make_snapshot(
            compatibility="review_required",
            blockers=("exchange_info_schema_changed",),
        )
        self.assertFalse(snap.validate())

    def test_invalid_compatibility_rejected(self):
        with self.assertRaises(ValueError):
            _make_snapshot(compatibility="invalid")

    def test_deterministic_hash(self):
        s1 = _make_snapshot()
        s2 = _make_snapshot()
        self.assertEqual(s1.snapshot_hash, s2.snapshot_hash)
        self.assertEqual(s1.snapshot_id, s2.snapshot_id)

    def test_round_trip(self):
        snap = _make_snapshot()
        raw = dump_artifact(snap)
        restored = load_artifact(
            raw, expected_artifact_type="venue_capability_snapshot"
        )
        self.assertEqual(restored.snapshot_id, snap.snapshot_id)
        self.assertEqual(restored.compatibility, "pass")

    def test_tampered_payload_detected(self):
        snap = _make_snapshot()
        raw = json.loads(dump_artifact(snap))
        raw["payload"]["venue"] = "other_venue"
        with self.assertRaises(ArtifactCodecError) as cm:
            load_artifact(
                json.dumps(raw, sort_keys=True).encode("ascii") + b"\n"
            )
        self.assertIn("payload_hash_mismatch", str(cm.exception))


class BuildSnapshotTest(unittest.TestCase):
    def test_build_hashes_exchange_info_and_rules(self):
        snap = build_venue_capability_snapshot(
            venue="binance_usdm",
            observed_at=_OBSERVED,
            exchange_info=_EXCHANGE_INFO,
            symbol_rules=_SYMBOL_RULES,
            position_mode="one_way",
            margin_mode="isolated",
            leverage=1,
            changelog_last_reviewed_at=_REVIEWED,
            changelog_source_hash=_HASH_A,
        )
        self.assertEqual(snap.compatibility, "pass")
        self.assertEqual(snap.blockers, ())
        self.assertNotEqual(snap.exchange_info_schema_hash, _HASH_A)

    def test_build_with_wrong_position_mode_blocked(self):
        snap = build_venue_capability_snapshot(
            venue="binance_usdm",
            observed_at=_OBSERVED,
            exchange_info=_EXCHANGE_INFO,
            symbol_rules=_SYMBOL_RULES,
            position_mode="hedge",
            margin_mode="isolated",
            leverage=1,
            changelog_last_reviewed_at=_REVIEWED,
            changelog_source_hash=_HASH_A,
        )
        self.assertEqual(snap.compatibility, "blocked")
        self.assertIn("position_mode_not_one_way", snap.blockers)

    def test_build_detects_exchange_info_change(self):
        prev = build_venue_capability_snapshot(
            venue="binance_usdm",
            observed_at=_OBSERVED,
            exchange_info=_EXCHANGE_INFO,
            symbol_rules=_SYMBOL_RULES,
            position_mode="one_way",
            margin_mode="isolated",
            leverage=1,
            changelog_last_reviewed_at=_REVIEWED,
            changelog_source_hash=_HASH_A,
        )
        changed_info = dict(_EXCHANGE_INFO)
        changed_info["new_field"] = "value"
        snap = build_venue_capability_snapshot(
            venue="binance_usdm",
            observed_at=_OBSERVED,
            exchange_info=changed_info,
            symbol_rules=_SYMBOL_RULES,
            position_mode="one_way",
            margin_mode="isolated",
            leverage=1,
            changelog_last_reviewed_at=_REVIEWED,
            changelog_source_hash=_HASH_A,
            previous_snapshot=prev,
        )
        self.assertEqual(snap.compatibility, "review_required")
        self.assertIn("exchange_info_schema_changed", snap.blockers)

    def test_build_detects_symbol_rules_change(self):
        prev = build_venue_capability_snapshot(
            venue="binance_usdm",
            observed_at=_OBSERVED,
            exchange_info=_EXCHANGE_INFO,
            symbol_rules=_SYMBOL_RULES,
            position_mode="one_way",
            margin_mode="isolated",
            leverage=1,
            changelog_last_reviewed_at=_REVIEWED,
            changelog_source_hash=_HASH_A,
        )
        changed_rules = dict(_SYMBOL_RULES)
        changed_rules["BTCUSDT"] = dict(_SYMBOL_RULES["BTCUSDT"])
        changed_rules["BTCUSDT"]["minQty"] = 0.002
        snap = build_venue_capability_snapshot(
            venue="binance_usdm",
            observed_at=_OBSERVED,
            exchange_info=_EXCHANGE_INFO,
            symbol_rules=changed_rules,
            position_mode="one_way",
            margin_mode="isolated",
            leverage=1,
            changelog_last_reviewed_at=_REVIEWED,
            changelog_source_hash=_HASH_A,
            previous_snapshot=prev,
        )
        self.assertEqual(snap.compatibility, "review_required")
        self.assertIn("symbol_rules_changed", snap.blockers)

    def test_build_detects_changelog_change(self):
        prev = build_venue_capability_snapshot(
            venue="binance_usdm",
            observed_at=_OBSERVED,
            exchange_info=_EXCHANGE_INFO,
            symbol_rules=_SYMBOL_RULES,
            position_mode="one_way",
            margin_mode="isolated",
            leverage=1,
            changelog_last_reviewed_at=_REVIEWED,
            changelog_source_hash=_HASH_A,
        )
        snap = build_venue_capability_snapshot(
            venue="binance_usdm",
            observed_at=_OBSERVED,
            exchange_info=_EXCHANGE_INFO,
            symbol_rules=_SYMBOL_RULES,
            position_mode="one_way",
            margin_mode="isolated",
            leverage=1,
            changelog_last_reviewed_at=_REVIEWED,
            changelog_source_hash=_HASH_B,
            previous_snapshot=prev,
        )
        self.assertEqual(snap.compatibility, "review_required")
        self.assertIn("changelog_text_changed", snap.blockers)

    def test_build_no_change_remains_pass(self):
        prev = build_venue_capability_snapshot(
            venue="binance_usdm",
            observed_at=_OBSERVED,
            exchange_info=_EXCHANGE_INFO,
            symbol_rules=_SYMBOL_RULES,
            position_mode="one_way",
            margin_mode="isolated",
            leverage=1,
            changelog_last_reviewed_at=_REVIEWED,
            changelog_source_hash=_HASH_A,
        )
        snap = build_venue_capability_snapshot(
            venue="binance_usdm",
            observed_at="2026-07-23T11:00:00+00:00",
            exchange_info=_EXCHANGE_INFO,
            symbol_rules=_SYMBOL_RULES,
            position_mode="one_way",
            margin_mode="isolated",
            leverage=1,
            changelog_last_reviewed_at=_REVIEWED,
            changelog_source_hash=_HASH_A,
            previous_snapshot=prev,
        )
        self.assertEqual(snap.compatibility, "pass")


class ChangelogDiffTest(unittest.TestCase):
    def test_no_change_diff(self):
        diff = diff_changelog(
            venue="binance_usdm",
            previous_source_hash=_HASH_A,
            current_source_hash=_HASH_A,
            previous_observed_at=_REVIEWED,
            current_observed_at=_OBSERVED,
        )
        self.assertFalse(diff.text_changed)
        self.assertFalse(diff.review_required)

    def test_changed_diff(self):
        diff = diff_changelog(
            venue="binance_usdm",
            previous_source_hash=_HASH_A,
            current_source_hash=_HASH_B,
            previous_observed_at=_REVIEWED,
            current_observed_at=_OBSERVED,
        )
        self.assertTrue(diff.text_changed)
        self.assertTrue(diff.review_required)

    def test_round_trip(self):
        diff = diff_changelog(
            venue="binance_usdm",
            previous_source_hash=_HASH_A,
            current_source_hash=_HASH_B,
            previous_observed_at=_REVIEWED,
            current_observed_at=_OBSERVED,
        )
        raw = dump_artifact(diff)
        restored = load_artifact(
            raw, expected_artifact_type="venue_changelog_diff"
        )
        self.assertEqual(restored.diff_id, diff.diff_id)
        self.assertTrue(restored.text_changed)

    def test_deterministic_hash(self):
        d1 = diff_changelog(
            venue="binance_usdm",
            previous_source_hash=_HASH_A,
            current_source_hash=_HASH_B,
            previous_observed_at=_REVIEWED,
            current_observed_at=_OBSERVED,
        )
        d2 = diff_changelog(
            venue="binance_usdm",
            previous_source_hash=_HASH_A,
            current_source_hash=_HASH_B,
            previous_observed_at=_REVIEWED,
            current_observed_at=_OBSERVED,
        )
        self.assertEqual(d1.diff_hash, d2.diff_hash)


if __name__ == "__main__":
    unittest.main()
