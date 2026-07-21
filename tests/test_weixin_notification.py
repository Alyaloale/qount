from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path

from qount.contracts import canonical_hash
from qount.notifications import OPENCLAW_WEIXIN_PROVIDER_NAME
from qount.notifications import OpenClawWeixinProvider
from qount.notifications import OpenClawWeixinProviderError
from qount.notifications import parse_openclaw_weixin_credential


def _credential(**overrides) -> str:
    value = {
        "account_id": "fixture-im-bot",
        "base_url": "https://ilinkai.weixin.qq.com/",
        "context_token": "fixture-context-token",
        "recipient": "fixture_user@im.wechat",
        "token": "fixture-secret-token",
    }
    value.update(overrides)
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class _Response:
    def __init__(self, status=200, body=b'{"message_id":123456789}'):
        self.status = status
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def read(self, limit):
        return self.body[:limit]


class _Opener:
    def __init__(self, response=None):
        self.response = response or _Response()
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        return self.response


class OpenClawWeixinNotificationTest(unittest.TestCase):
    def test_credential_route_is_strict(self) -> None:
        parsed = parse_openclaw_weixin_credential(_credential())
        self.assertEqual(parsed.account_id, "fixture-im-bot")
        self.assertEqual(parsed.recipient, "fixture_user@im.wechat")
        without_context = json.loads(_credential())
        del without_context["context_token"]
        self.assertIsNone(
            parse_openclaw_weixin_credential(
                json.dumps(without_context, sort_keys=True, separators=(",", ":"))
            ).context_token
        )
        for invalid in (
            _credential(base_url="https://example.com/"),
            _credential(recipient="not-a-weixin-id"),
            json.dumps({"token": "incomplete"}),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(
                OpenClawWeixinProviderError
            ):
                parse_openclaw_weixin_credential(invalid)

    def test_send_uses_official_ilink_contract_and_stable_client_id(self) -> None:
        opener = _Opener()
        provider = OpenClawWeixinProvider(
            opener=opener,
            clock=lambda: dt.datetime.fromisoformat("2026-07-21T14:00:00+00:00"),
        )
        delivery_key = canonical_hash({"delivery": "weixin"})
        response = provider.send(
            {
                "severity": "WARNING",
                "title": "Qount 每日情报复盘",
                "summary": "中文研究报告已完成。",
                "occurred_at": "2026-07-21T13:59:00+00:00",
            },
            delivery_key,
            _credential(),
        )

        self.assertEqual(response["provider"], OPENCLAW_WEIXIN_PROVIDER_NAME)
        self.assertEqual(response["provider_message_id"], "123456789")
        request, timeout = opener.calls[0]
        self.assertEqual(timeout, 15)
        self.assertEqual(
            request.full_url,
            "https://ilinkai.weixin.qq.com/ilink/bot/sendmessage",
        )
        self.assertEqual(request.headers["Authorizationtype"], "ilink_bot_token")
        self.assertEqual(request.headers["Ilink-app-id"], "bot")
        body = json.loads(request.data)
        self.assertEqual(body["msg"]["to_user_id"], "fixture_user@im.wechat")
        self.assertEqual(body["msg"]["client_id"], f"qount:{delivery_key[:32]}")
        self.assertEqual(body["msg"]["message_type"], 2)
        self.assertEqual(body["msg"]["message_state"], 2)
        self.assertIn("中文研究报告已完成", body["msg"]["item_list"][0]["text_item"]["text"])
        self.assertNotIn("fixture-secret-token", request.data.decode("utf-8"))

    def test_send_reads_latest_context_token_from_openclaw_account(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve() / "accounts"
            directory.mkdir(mode=0o700)
            context_path = directory / "fixture-im-bot.context-tokens.json"
            context_path.write_text(
                json.dumps(
                    {"fixture_user@im.wechat": "fresh-context-token"},
                    indent=2,
                )
                + "\n"
            )
            os.chmod(context_path, 0o600)
            opener = _Opener()
            provider = OpenClawWeixinProvider(
                opener=opener,
                context_token_directory=directory,
            )
            provider.send(
                {},
                canonical_hash({"delivery": "fresh-context"}),
                json.dumps(
                    {
                        key: value
                        for key, value in json.loads(_credential()).items()
                        if key != "context_token"
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )

        body = json.loads(opener.calls[0][0].data)
        self.assertEqual(body["msg"]["context_token"], "fresh-context-token")

    def test_static_credential_without_context_token_fails_closed(self) -> None:
        credential = json.loads(_credential())
        del credential["context_token"]
        provider = OpenClawWeixinProvider(opener=_Opener())
        with self.assertRaisesRegex(
            OpenClawWeixinProviderError, "context_token_required"
        ):
            provider.send(
                {},
                canonical_hash({"delivery": "context-required"}),
                json.dumps(credential, sort_keys=True, separators=(",", ":")),
            )

    def test_dynamic_context_token_source_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve() / "accounts"
            directory.mkdir(mode=0o700)
            context_path = directory / "fixture-im-bot.context-tokens.json"
            context_path.write_text(
                json.dumps({"other_user@im.wechat": "other-context-token"})
            )
            os.chmod(context_path, 0o600)
            provider = OpenClawWeixinProvider(
                opener=_Opener(),
                context_token_directory=directory,
            )
            with self.assertRaisesRegex(
                OpenClawWeixinProviderError, "context_recipient_missing"
            ):
                provider.send(
                    {},
                    canonical_hash({"delivery": "missing-context"}),
                    _credential(),
                )
            os.chmod(context_path, 0o644)
            with self.assertRaisesRegex(
                OpenClawWeixinProviderError, "context_file_insecure"
            ):
                provider.send(
                    {},
                    canonical_hash({"delivery": "insecure-context"}),
                    _credential(),
                )

    def test_non_success_response_is_rejected(self) -> None:
        provider = OpenClawWeixinProvider(opener=_Opener(_Response(status=401)))
        with self.assertRaisesRegex(
            OpenClawWeixinProviderError, "http_status:401"
        ):
            provider.send({}, canonical_hash({"delivery": "rejected"}), _credential())

    def test_http_success_with_business_rejection_is_rejected(self) -> None:
        provider = OpenClawWeixinProvider(
            opener=_Opener(_Response(body=b'{"ret":-2,"errmsg":"prepare failed"}'))
        )
        with self.assertRaisesRegex(
            OpenClawWeixinProviderError, "response_rejected:-2"
        ):
            provider.send(
                {}, canonical_hash({"delivery": "business-rejected"}), _credential()
            )

    def test_http_success_with_invalid_body_is_rejected(self) -> None:
        for body in (
            b"",
            b"not-json",
            b"[]",
            b'{"ret":0}',
            b'{"message_id":0}',
            b'{"message_id":true}',
        ):
            with self.subTest(body=body):
                provider = OpenClawWeixinProvider(opener=_Opener(_Response(body=body)))
                with self.assertRaises(OpenClawWeixinProviderError):
                    provider.send(
                        {}, canonical_hash({"delivery": body.hex()}), _credential()
                    )


if __name__ == "__main__":
    unittest.main()
