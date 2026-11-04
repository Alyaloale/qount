from __future__ import annotations

import datetime
import json
import unittest

from qount.contracts import canonical_hash
from qount.notifications import ProviderResponseError
from qount.notifications import SERVERCHAN_PROVIDER_NAME
from qount.notifications import ServerChanProvider
from qount.notifications import ServerChanProviderError
from qount.notifications import validate_serverchan_sendkey


SENDKEY = "SCTfixturekey1234567890abcd"
DELIVERY_KEY = canonical_hash("delivery-key-fixture")


class URLErrorWithUrl(Exception):
    """Stand-in for a urllib error whose message carries the request URL."""


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
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if self.error is not None:
            raise self.error
        return _Response(self.payload)


def _provider(opener):
    return ServerChanProvider(
        opener=opener,
        clock=lambda: datetime.datetime.fromisoformat(
            "2026-11-03T12:00:02+00:00"
        ),
    )


PAYLOAD = dict(severity="CRITICAL", title="QOUNT 测试", summary="摘要",
               occurred_at="2026-11-03T12:00:00+00:00")


class ServerChanNotificationTest(unittest.TestCase):
    def test_sendkey_is_strict(self):
        self.assertEqual(validate_serverchan_sendkey(SENDKEY), SENDKEY)
        for invalid in ("sct-lower", "SCT", "SCT short", "SCT" + "x" * 200,
                        "SCT\ninjected", "", None):
            with self.subTest(invalid=invalid), self.assertRaises(ServerChanProviderError):
                validate_serverchan_sendkey(invalid)

    def test_success_posts_markdown_and_returns_provider_contract(self):
        opener = _Opener({"code": 0, "message": "", "data": {"pushid": "1", "error": "SUCCESS"}})
        result = _provider(opener).send(PAYLOAD, DELIVERY_KEY, SENDKEY)
        self.assertEqual(result["provider"], SERVERCHAN_PROVIDER_NAME)
        self.assertTrue(result["accepted"])
        self.assertEqual(result["status"], "ACCEPTED")
        request, timeout = opener.calls[0]
        self.assertEqual(request.full_url, f"https://sctapi.ftqq.com/{SENDKEY}.send")
        self.assertEqual(request.get_method(), "POST")
        body = request.data.decode("utf-8")
        self.assertIn("title=%5B", body)  # URL-encoded "[信息]/[严重] …" label
        self.assertIn("desp=", body)
        self.assertEqual(timeout, 5)

    def test_rejection_is_typed_and_contains_no_key_material(self):
        opener = _Opener({"code": 40001, "message": "bad key"})
        with self.assertRaises(ProviderResponseError) as caught:
            _provider(opener).send(PAYLOAD, DELIVERY_KEY, SENDKEY)
        self.assertIn("serverchan_rejected:40001", str(caught.exception))
        self.assertNotIn(SENDKEY, str(caught.exception))

    def test_malformed_response_is_an_error(self):
        opener = _Opener({"message": "no code"})
        with self.assertRaises(ServerChanProviderError) as caught:
            _provider(opener).send(PAYLOAD, DELIVERY_KEY, SENDKEY)
        self.assertEqual(str(caught.exception), "serverchan_response_fields_invalid")

    def test_transport_failure_never_propagates_url_with_sendkey(self):
        error = URLErrorWithUrl(f"https://sctapi.ftqq.com/{SENDKEY}.send timed out")
        opener = _Opener(error=error)
        with self.assertRaises(ServerChanProviderError) as caught:
            _provider(opener).send(PAYLOAD, DELIVERY_KEY, SENDKEY)
        message = str(caught.exception)
        self.assertIn("serverchan_transport_error:URLErrorWithUrl", message)
        self.assertNotIn(SENDKEY, message)

    def test_missing_credential_is_typed(self):
        with self.assertRaises(ServerChanProviderError) as caught:
            _provider(_Opener({"code": 0})).send(PAYLOAD, DELIVERY_KEY, None)
        self.assertEqual(str(caught.exception), "serverchan_sendkey_required")


if __name__ == "__main__":
    unittest.main()
