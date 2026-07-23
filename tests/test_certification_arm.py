from __future__ import annotations

import unittest
from datetime import datetime, timezone

from qount.certification.arm import ARM_STATUSES
from qount.certification.arm import CertificationArm

_HASH_A = "a" * 64
_HASH_B = "b" * 64
_PLAN_ID = "c" * 64
_AUTHORIZED = "2026-07-23T10:00:00+00:00"
_EXPIRES = "2026-07-23T11:00:00+00:00"
_NOW_VALID = "2026-07-23T10:30:00+00:00"
_NOW_EXPIRED = "2026-07-23T11:30:00+00:00"


def _make_arm(**overrides) -> CertificationArm:
    params: dict = dict(
        plan_id=_PLAN_ID,
        authorized_at=_AUTHORIZED,
        expires_at=_EXPIRES,
        owner_authorization_hash=_HASH_A,
        arm_token_hash=_HASH_B,
    )
    params.update(overrides)
    return CertificationArm.create(**params)


class CertificationArmCreateTest(unittest.TestCase):
    """Section 3.1: independent, single-use, time-limited certification arm."""

    def test_create_real_authorized(self):
        arm = _make_arm()
        self.assertEqual(arm.status, "real_authorized")
        self.assertEqual(arm.schema_version, 1)
        self.assertTrue(arm.arm_id)
        self.assertEqual(len(arm.arm_hash), 64)
        self.assertFalse(arm.orders_authorized is None)

    def test_orders_authorized_true_when_real_authorized(self):
        arm = _make_arm()
        self.assertTrue(arm.orders_authorized)

    def test_plan_id_must_be_sha256(self):
        with self.assertRaises(ValueError) as cm:
            _make_arm(plan_id="not-a-hash")
        self.assertIn("certification_arm_plan_id_invalid", str(cm.exception))

    def test_expires_must_be_after_authorized(self):
        with self.assertRaises(ValueError) as cm:
            _make_arm(
                authorized_at=_EXPIRES,
                expires_at=_AUTHORIZED,
            )
        self.assertIn(
            "certification_arm_expires_before_authorized", str(cm.exception)
        )

    def test_hashes_must_be_sha256(self):
        with self.assertRaises(ValueError):
            _make_arm(owner_authorization_hash="short")
        with self.assertRaises(ValueError):
            _make_arm(arm_token_hash="short")

    def test_arm_hash_deterministic(self):
        arm1 = _make_arm()
        arm2 = _make_arm()
        self.assertEqual(arm1.arm_hash, arm2.arm_hash)
        self.assertEqual(arm1.arm_id, arm2.arm_id)

    def test_arm_hash_changes_with_status(self):
        arm = _make_arm()
        used = arm.mark_used()
        self.assertNotEqual(arm.arm_hash, used.arm_hash)
        self.assertNotEqual(arm.arm_id, used.arm_id)


class CertificationArmValidityTest(unittest.TestCase):
    """is_valid_at: real_authorized + not expired."""

    def test_valid_when_real_authorized_and_not_expired(self):
        arm = _make_arm()
        self.assertTrue(arm.is_valid_at(_NOW_VALID))

    def test_invalid_when_expired(self):
        arm = _make_arm()
        self.assertFalse(arm.is_valid_at(_NOW_EXPIRED))

    def test_invalid_when_used(self):
        arm = _make_arm()
        used = arm.mark_used()
        self.assertFalse(used.is_valid_at(_NOW_VALID))

    def test_invalid_when_expired_and_used(self):
        arm = _make_arm()
        used = arm.mark_used()
        self.assertFalse(used.is_valid_at(_NOW_EXPIRED))

    def test_invalid_status_returns_false(self):
        arm = _make_arm()
        used = arm.mark_used()
        self.assertEqual(used.status, "used")
        self.assertFalse(used.orders_authorized)


class CertificationArmMarkUsedTest(unittest.TestCase):
    """mark_used: single-use, permanently disables the arm."""

    def test_mark_used_returns_new_arm_with_used_status(self):
        arm = _make_arm()
        used = arm.mark_used()
        self.assertEqual(used.status, "used")
        self.assertEqual(arm.status, "real_authorized")

    def test_mark_used_preserves_plan_and_owner(self):
        arm = _make_arm()
        used = arm.mark_used()
        self.assertEqual(used.plan_id, arm.plan_id)
        self.assertEqual(
            used.owner_authorization_hash, arm.owner_authorization_hash
        )
        self.assertEqual(used.expires_at, arm.expires_at)

    def test_mark_used_validates(self):
        arm = _make_arm()
        used = arm.mark_used()
        self.assertEqual(used.validate(), ())

    def test_marked_arm_cannot_authorize_orders(self):
        arm = _make_arm()
        used = arm.mark_used()
        self.assertFalse(used.orders_authorized)
        self.assertFalse(used.is_valid_at(_NOW_VALID))

    def test_used_arm_status_in_arm_statuses(self):
        self.assertIn("used", ARM_STATUSES)
        self.assertIn("real_authorized", ARM_STATUSES)
        self.assertIn("expired", ARM_STATUSES)


class CertificationArmTamperTest(unittest.TestCase):
    """Tamper detection: hash, id, status integrity."""

    def test_arm_hash_tamper_detected(self):
        arm = _make_arm()
        errors = arm.validate()
        self.assertEqual(errors, ())
        import dataclasses

        tampered = dataclasses.replace(arm, status="used")
        errors = tampered.validate()
        self.assertIn("certification_arm_hash_invalid", errors)

    def test_arm_id_tamper_detected(self):
        arm = _make_arm()
        import dataclasses

        tampered = dataclasses.replace(arm, arm_id="0" * 64)
        errors = tampered.validate()
        self.assertIn("certification_arm_id_invalid", errors)

    def test_unknown_status_detected(self):
        arm = _make_arm()
        import dataclasses

        tampered = dataclasses.replace(
            arm, status="bogus", arm_hash="0" * 64, arm_id="0" * 64
        )
        errors = tampered.validate()
        self.assertIn("certification_arm_status_invalid", errors)


if __name__ == "__main__":
    unittest.main()
