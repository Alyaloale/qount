from __future__ import annotations

import json
import unittest

from qount.contracts import canonical_hash
from qount.notifications import ProviderResponseError
from qount.notifications import ProviderTransport
from qount.notifications import WECOM_PROVIDER_NAME
from qount.notifications import WeComGroupRobotProvider
from qount.notifications import WeComProviderError
from qount.notifications import validate_wecom_webhook


WEBHOOK = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=fixture-key"


class _Response:
    status = 200

    def __init__(self, payload):
        self.raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def read(self, limit):
        return self.raw[:limit]


class _Opener:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        return _Response(self.payload)


class WeComNotificationTest(unittest.TestCase):
    def test_webhook_is_strict_and_success_returns_provider_contract(self) -> None:
        self.assertEqual(validate_wecom_webhook(WEBHOOK), WEBHOOK)
        for invalid in (
            "http://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x",
            "https://example.com/cgi-bin/webhook/send?key=x",
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?other=x",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(WeComProviderError):
                validate_wecom_webhook(invalid)

        opener = _Opener({"errcode": 0, "errmsg": "ok"})
        provider = WeComGroupRobotProvider(
            opener=opener,
            clock=lambda: __import__("datetime").datetime.fromisoformat(
                "2026-07-21T10:00:02+00:00"
            ),
        )
        delivery_key = canonical_hash({"delivery": 1})
        response = provider.send(
            {
                "severity": "INFO",
                "title": "Daily intelligence",
                "summary": "Review completed.",
                "occurred_at": "2026-07-21T10:00:00+00:00",
            },
            delivery_key,
            WEBHOOK,
        )
        self.assertEqual(response["provider"], WECOM_PROVIDER_NAME)
        self.assertEqual(response["delivery_key"], delivery_key)
        sent = json.loads(opener.calls[0][0].data)
        self.assertIn(delivery_key[:12], sent["markdown"]["content"])
        self.assertIn("时间：", sent["markdown"]["content"])
        self.assertIn("证据：", sent["markdown"]["content"])
        self.assertNotIn("fixture-key", sent["markdown"]["content"])

    def test_provider_rejection_propagates_through_transport(self) -> None:
        opener = _Opener({"errcode": 93000, "errmsg": "invalid webhook"})
        provider = WeComGroupRobotProvider(opener=opener)
        transport = ProviderTransport(
            provider,
            provider_name=WECOM_PROVIDER_NAME,
        )
        transport.credential = WEBHOOK
        with self.assertRaisesRegex(ProviderResponseError, "wecom_rejected"):
            transport(
                {"alert_id": "a" * 64, "title": "x", "summary": "y"},
                canonical_hash({"delivery": 1}),
            )


if __name__ == "__main__":
    unittest.main()
