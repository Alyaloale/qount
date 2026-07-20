from __future__ import annotations

import datetime as dt
import os
import stat
import tempfile
import time
import unittest
from pathlib import Path

from qount.contracts import canonical_hash
from qount.notifications import AlertEvent
from qount.notifications import FakeNotificationProvider
from qount.notifications import NotificationStore
from qount.notifications import ProviderCredentialError
from qount.notifications import ProviderRateLimitError
from qount.notifications import ProviderResponse
from qount.notifications import ProviderResponseError
from qount.notifications import ProviderTimeoutError
from qount.notifications import ProviderTransport
from qount.notifications import RateLimitPolicy


OCCURRED_AT = "2026-07-20T00:10:00+00:00"
RECORDED_AT = "2026-07-20T00:10:01+00:00"
RECEIVED_AT = "2026-07-20T00:10:02+00:00"


def _hash(name: str) -> str:
    return canonical_hash({"notification_transport_fixture": name})


def _payload() -> dict[str, str]:
    return {
        "alert_id": _hash("alert"),
        "event_hash": _hash("event"),
    }


def _alert() -> AlertEvent:
    return AlertEvent.create(
        severity="HALT",
        category="reconciliation",
        title="Runtime reconciliation blocked",
        summary="Ledger and exchange positions do not match.",
        occurred_at=OCCURRED_AT,
        source_type="reconciliation",
        source_id=_hash("source"),
        source_hash=_hash("source-payload"),
        dedupe_key="reconciliation:transport-fixture",
        trace_id_value=_hash("trace"),
    )


class ProviderResponseContractTest(unittest.TestCase):
    def test_response_hash_delivery_key_and_acceptance_are_strict(self) -> None:
        response = ProviderResponse.create(
            provider="fake",
            delivery_key=_hash("delivery"),
            status="ACCEPTED",
            accepted=True,
            provider_message_id=_hash("message"),
            received_at=RECEIVED_AT,
        )
        self.assertEqual(ProviderResponse.from_mapping(response.as_dict()), response)

        wrong_key = dict(response.as_dict())
        wrong_key["delivery_key"] = _hash("other-delivery")
        with self.assertRaisesRegex(ProviderResponseError, "response_hash_invalid"):
            ProviderResponse.from_mapping(wrong_key)

        with self.assertRaisesRegex(
            ProviderResponseError, "status_acceptance_mismatch"
        ):
            ProviderResponse.create(
                provider="fake",
                delivery_key=_hash("delivery"),
                status="REJECTED",
                accepted=True,
                provider_message_id=_hash("message"),
                received_at=RECEIVED_AT,
            )

    def test_transport_rejects_wrong_delivery_key_and_provider_rejection(self) -> None:
        requested_key = _hash("delivery")
        wrong_key = ProviderResponse.create(
            provider="fake",
            delivery_key=_hash("wrong"),
            status="ACCEPTED",
            accepted=True,
            provider_message_id=_hash("message"),
            received_at=RECEIVED_AT,
        ).as_dict()
        transport = ProviderTransport(
            FakeNotificationProvider(responses=[wrong_key]),
            provider_name="fake",
            rate_limit=RateLimitPolicy(max_calls=2, window_seconds=1.0),
        )
        with self.assertRaisesRegex(ProviderResponseError, "delivery_key_mismatch"):
            transport(_payload(), requested_key)

        rejected = ProviderResponse.create(
            provider="fake",
            delivery_key=requested_key,
            status="REJECTED",
            accepted=False,
            provider_message_id=None,
            received_at=RECEIVED_AT,
        ).as_dict()
        transport = ProviderTransport(
            FakeNotificationProvider(responses=[rejected]),
            provider_name="fake",
        )
        with self.assertRaisesRegex(ProviderResponseError, "provider_rejected"):
            transport(_payload(), requested_key)

        wrong_provider = ProviderResponse.create(
            provider="other",
            delivery_key=requested_key,
            status="ACCEPTED",
            accepted=True,
            provider_message_id=_hash("message"),
            received_at=RECEIVED_AT,
        ).as_dict()
        transport = ProviderTransport(
            FakeNotificationProvider(responses=[wrong_provider]),
            provider_name="fake",
        )
        with self.assertRaisesRegex(ProviderResponseError, "identity_mismatch"):
            transport(_payload(), requested_key)


class ProviderTransportPolicyTest(unittest.TestCase):
    def test_fake_provider_is_idempotent_for_one_delivery_key(self) -> None:
        now = dt.datetime.fromisoformat(RECEIVED_AT)
        provider = FakeNotificationProvider(clock=lambda: now)
        transport = ProviderTransport(
            provider,
            provider_name="fake",
            rate_limit=RateLimitPolicy(max_calls=2, window_seconds=1.0),
        )
        key = _hash("delivery")
        first = transport(_payload(), key)
        second = transport(_payload(), key)

        self.assertEqual(first["status"], "ACCEPTED")
        self.assertEqual(second["status"], "DUPLICATE")
        self.assertEqual(first["provider_message_id"], second["provider_message_id"])
        self.assertEqual({call["delivery_key"] for call in provider.calls}, {key})

    def test_rate_limit_fails_before_a_second_provider_call(self) -> None:
        current = [10.0]
        provider = FakeNotificationProvider()
        transport = ProviderTransport(
            provider,
            provider_name="fake",
            rate_limit=RateLimitPolicy(max_calls=1, window_seconds=5.0),
            monotonic_clock=lambda: current[0],
        )
        transport(_payload(), _hash("delivery-1"))
        with self.assertRaisesRegex(ProviderRateLimitError, "rate_limit_exceeded"):
            transport(_payload(), _hash("delivery-2"))
        self.assertEqual(len(provider.calls), 1)

        current[0] = 15.0
        transport(_payload(), _hash("delivery-2"))
        self.assertEqual(len(provider.calls), 2)

    def test_timeout_is_local_and_audited(self) -> None:
        def slow_provider(payload, delivery_key, credential):
            time.sleep(0.05)
            return ProviderResponse.create(
                provider="fake",
                delivery_key=delivery_key,
                status="ACCEPTED",
                accepted=True,
                provider_message_id=_hash("slow-message"),
                received_at=RECEIVED_AT,
            ).as_dict()

        transport = ProviderTransport(
            slow_provider,
            provider_name="fake",
            timeout_seconds=0.005,
        )
        with self.assertRaisesRegex(ProviderTimeoutError, "provider_timeout"):
            transport(_payload(), _hash("delivery"))
        self.assertEqual(
            transport.audit_events[-1]["event_type"],
            "notification_transport_timeout",
        )

    def test_credentials_require_0600_and_no_key_mode_is_audited(self) -> None:
        events: list[dict[str, object]] = []
        no_key = ProviderTransport(
            FakeNotificationProvider(),
            provider_name="fake",
            audit_sink=lambda event: events.append(dict(event)),
        )
        self.assertIsNone(no_key.credential)
        self.assertEqual(events[0]["credential_present"], False)
        self.assertEqual(events[0]["credential_source"], "none")
        self.assertNotIn("credential", events[0])
        self.assertNotIn("credential_fingerprint", events[0])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "private"
            root.mkdir(mode=0o700)
            os.chmod(root, 0o700)
            credential = root / "provider.key"
            credential.write_text("fixture-provider-key", encoding="utf-8")
            os.chmod(credential, 0o644)
            with self.assertRaisesRegex(
                ProviderCredentialError, "credential_mode_invalid"
            ):
                ProviderTransport(
                    FakeNotificationProvider(),
                    provider_name="fake",
                    credential_path=credential,
                )

            os.chmod(credential, 0o600)
            configured = ProviderTransport(
                FakeNotificationProvider(),
                provider_name="fake",
                credential_path=credential,
            )
            self.assertEqual(configured.credential, "fixture-provider-key")
            self.assertEqual(stat.S_IMODE(credential.stat().st_mode), 0o600)
            self.assertNotIn(
                "fixture-provider-key",
                repr(configured.audit_events),
            )
            self.assertNotIn("credential_fingerprint", configured.audit_events[0])

    def test_store_retries_fake_failure_with_the_same_delivery_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = NotificationStore(
                Path(temporary) / "private" / "notifications.sqlite3"
            )
            store.enqueue(_alert(), recorded_at=RECORDED_AT, max_attempts=2)
            provider = FakeNotificationProvider(
                failures=[ConnectionError("fake provider offline")],
                clock=lambda: dt.datetime.fromisoformat(RECEIVED_AT),
            )
            transport = ProviderTransport(
                provider,
                provider_name="fake",
                rate_limit=RateLimitPolicy(max_calls=2, window_seconds=1.0),
            )

            first = store.deliver_due(
                attempted_at=RECORDED_AT,
                transport=transport,
                retry_base_seconds=1,
            )
            second = store.deliver_due(
                attempted_at="2026-07-20T00:10:02+00:00",
                transport=transport,
                retry_base_seconds=1,
            )
            rows = store.verified_rows()

        self.assertEqual(first[0]["status"], "RETRY_WAIT")
        self.assertEqual(second[0]["status"], "DELIVERED")
        self.assertEqual(len({call["delivery_key"] for call in provider.calls}), 1)
        self.assertEqual([row["status"] for row in rows["attempts"]], ["FAILED", "SUCCEEDED"])


if __name__ == "__main__":
    unittest.main()
