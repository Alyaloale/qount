"""Independent certification arm for Phase D real minimum certification.

A certification arm is a single-use, time-limited authorization that
allows exactly one real certification run (section 3.1).  It is
intentionally separate from the Base mini-trend arm/token: it must not
be reused, must expire, and must bind to a specific CertificationPlan.

``orders_authorized`` on the arm reflects the ``real_authorized`` status;
expiry is checked at use time via ``is_valid_at(now)``.  Consuming the
arm (``mark_used``) permanently disables it -- a used arm can never
authorize orders again.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qount.contracts.hashing import canonical_hash
from qount.contracts.trace import aware_datetime
from qount.contracts.trace import is_sha256
from qount.contracts.trace import trace_id

ARM_SCHEMA_VERSION = 1

ARM_STATUSES = ("real_authorized", "used", "expired")


@dataclass(frozen=True)
class CertificationArm:
    """A single-use, time-limited certification authorization (section 3.1).

    The arm binds to one CertificationPlan, carries an independent token
    hash (never the Base arm token), and expires.  ``mark_used`` returns
    a new arm with ``status='used'`` that can no longer authorize orders.
    """

    schema_version: int
    arm_id: str
    plan_id: str
    authorized_at: str
    expires_at: str
    owner_authorization_hash: str
    arm_token_hash: str
    status: str
    arm_hash: str

    @staticmethod
    def _build_core(
        *,
        plan_id: str,
        authorized_at: str,
        expires_at: str,
        owner_authorization_hash: str,
        arm_token_hash: str,
        status: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": ARM_SCHEMA_VERSION,
            "plan_id": plan_id,
            "authorized_at": authorized_at,
            "expires_at": expires_at,
            "owner_authorization_hash": owner_authorization_hash,
            "arm_token_hash": arm_token_hash,
            "status": status,
        }

    @classmethod
    def create(
        cls,
        *,
        plan_id: str,
        authorized_at: str,
        expires_at: str,
        owner_authorization_hash: str,
        arm_token_hash: str,
    ) -> CertificationArm:
        core = cls._build_core(
            plan_id=plan_id,
            authorized_at=authorized_at,
            expires_at=expires_at,
            owner_authorization_hash=owner_authorization_hash,
            arm_token_hash=arm_token_hash,
            status="real_authorized",
        )
        arm_hash = canonical_hash(core)
        arm = cls(
            schema_version=ARM_SCHEMA_VERSION,
            arm_id=trace_id("certification_arm", {"arm_hash": arm_hash}),
            plan_id=plan_id,
            authorized_at=authorized_at,
            expires_at=expires_at,
            owner_authorization_hash=owner_authorization_hash,
            arm_token_hash=arm_token_hash,
            status="real_authorized",
            arm_hash=arm_hash,
        )
        errors = arm.validate()
        if errors:
            raise ValueError(f"certification_arm_invalid:{','.join(errors)}")
        return arm

    def _core(self) -> dict[str, Any]:
        return self._build_core(
            plan_id=self.plan_id,
            authorized_at=self.authorized_at,
            expires_at=self.expires_at,
            owner_authorization_hash=self.owner_authorization_hash,
            arm_token_hash=self.arm_token_hash,
            status=self.status,
        )

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.schema_version != ARM_SCHEMA_VERSION:
            errors.append("certification_arm_schema_version_invalid")
        if not is_sha256(self.plan_id):
            errors.append("certification_arm_plan_id_invalid")
        try:
            aware_datetime(self.authorized_at)
        except (AttributeError, TypeError, ValueError):
            errors.append("certification_arm_authorized_at_invalid")
        try:
            expires_dt = aware_datetime(self.expires_at)
            authorized_dt = aware_datetime(self.authorized_at)
            if expires_dt <= authorized_dt:
                errors.append("certification_arm_expires_before_authorized")
        except (AttributeError, TypeError, ValueError):
            errors.append("certification_arm_expires_at_invalid")
        for name in (
            "owner_authorization_hash",
            "arm_token_hash",
        ):
            if not is_sha256(getattr(self, name)):
                errors.append(f"certification_arm_{name}_invalid")
        if self.status not in ARM_STATUSES:
            errors.append("certification_arm_status_invalid")
        expected_hash = canonical_hash(self._core())
        if self.arm_hash != expected_hash:
            errors.append("certification_arm_hash_invalid")
        expected_id = trace_id(
            "certification_arm", {"arm_hash": expected_hash}
        )
        if self.arm_id != expected_id:
            errors.append("certification_arm_id_invalid")
        return tuple(errors)

    @property
    def orders_authorized(self) -> bool:
        return self.status == "real_authorized"

    def is_valid_at(self, now: str) -> bool:
        if self.status != "real_authorized":
            return False
        try:
            now_dt = aware_datetime(now)
            expires_dt = aware_datetime(self.expires_at)
        except (AttributeError, TypeError, ValueError):
            return False
        return now_dt < expires_dt

    def mark_used(self) -> CertificationArm:
        core = self._build_core(
            plan_id=self.plan_id,
            authorized_at=self.authorized_at,
            expires_at=self.expires_at,
            owner_authorization_hash=self.owner_authorization_hash,
            arm_token_hash=self.arm_token_hash,
            status="used",
        )
        arm_hash = canonical_hash(core)
        used = CertificationArm(
            schema_version=ARM_SCHEMA_VERSION,
            arm_id=trace_id("certification_arm", {"arm_hash": arm_hash}),
            plan_id=self.plan_id,
            authorized_at=self.authorized_at,
            expires_at=self.expires_at,
            owner_authorization_hash=self.owner_authorization_hash,
            arm_token_hash=self.arm_token_hash,
            status="used",
            arm_hash=arm_hash,
        )
        errors = used.validate()
        if errors:
            raise ValueError(f"certification_arm_invalid:{','.join(errors)}")
        return used
