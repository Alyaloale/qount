"""Personal Weixin notifications using an imported OpenClaw account."""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import secrets
import stat
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .transport import ProviderResponse


OPENCLAW_WEIXIN_PROVIDER_NAME = "openclaw_weixin"
OPENCLAW_WEIXIN_HOST = "ilinkai.weixin.qq.com"
OPENCLAW_WEIXIN_CHANNEL_VERSION = "2.4.4"
OPENCLAW_WEIXIN_APP_ID = "bot"
OPENCLAW_WEIXIN_APP_CLIENT_VERSION = str((2 << 16) | (4 << 8) | 4)
_RECIPIENT_RE = re.compile(r"^[A-Za-z0-9_-]{1,96}@im\.wechat$")
_ACCOUNT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MAXIMUM_CONTEXT_FILE_BYTES = 64_000


class OpenClawWeixinProviderError(ValueError):
    """Raised when the imported Weixin credential or response is invalid."""


@dataclass(frozen=True)
class OpenClawWeixinCredential:
    account_id: str
    base_url: str
    context_token: str | None
    recipient: str
    token: str


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise OpenClawWeixinProviderError(
                f"openclaw_weixin_credential_duplicate_key:{key}"
            )
        value[key] = item
    return value


def _credential_text(value: object, *, name: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(char) < 32 for char in value)
    ):
        raise OpenClawWeixinProviderError(
            f"openclaw_weixin_credential_{name}_invalid"
        )
    return value


def parse_openclaw_weixin_credential(raw: str) -> OpenClawWeixinCredential:
    try:
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except OpenClawWeixinProviderError:
        raise
    except (TypeError, json.JSONDecodeError) as exc:
        raise OpenClawWeixinProviderError(
            "openclaw_weixin_credential_invalid"
        ) from exc
    required = {"account_id", "base_url", "recipient", "token"}
    if (
        not isinstance(value, dict)
        or not required.issubset(value)
        or set(value) - (required | {"context_token"})
    ):
        raise OpenClawWeixinProviderError(
            "openclaw_weixin_credential_fields_invalid"
        )
    account_id = _credential_text(value["account_id"], name="account_id", maximum=128)
    base_url = _credential_text(value["base_url"], name="base_url", maximum=512)
    context_token = (
        None
        if "context_token" not in value
        else _credential_text(
            value["context_token"], name="context_token", maximum=2_048
        )
    )
    recipient = _credential_text(value["recipient"], name="recipient", maximum=128)
    token = _credential_text(value["token"], name="token", maximum=512)
    parsed = urllib.parse.urlparse(base_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != OPENCLAW_WEIXIN_HOST
        or parsed.port not in {None, 443}
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
        or not _ACCOUNT_ID_RE.fullmatch(account_id)
        or not _RECIPIENT_RE.fullmatch(recipient)
    ):
        raise OpenClawWeixinProviderError(
            "openclaw_weixin_credential_route_invalid"
        )
    return OpenClawWeixinCredential(
        account_id=account_id,
        base_url=base_url,
        context_token=context_token,
        recipient=recipient,
        token=token,
    )


def _has_symlink_component(path: Path) -> bool:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _load_current_context_token(
    directory: Path,
    *,
    account_id: str,
    recipient: str,
) -> str:
    if (
        not directory.is_absolute()
        or _has_symlink_component(directory)
        or not directory.is_dir()
    ):
        raise OpenClawWeixinProviderError(
            "openclaw_weixin_context_directory_invalid"
        )
    directory_stat = os.stat(directory, follow_symlinks=False)
    if directory_stat.st_uid != os.geteuid() or stat.S_IMODE(
        directory_stat.st_mode
    ) & 0o022:
        raise OpenClawWeixinProviderError(
            "openclaw_weixin_context_directory_insecure"
        )
    path = directory / f"{account_id}.context-tokens.json"
    if path.is_symlink() or not path.is_file():
        raise OpenClawWeixinProviderError("openclaw_weixin_context_file_invalid")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        try:
            file_stat = os.fstat(descriptor)
            if (
                not stat.S_ISREG(file_stat.st_mode)
                or stat.S_IMODE(file_stat.st_mode) != 0o600
                or file_stat.st_uid != os.geteuid()
            ):
                raise OpenClawWeixinProviderError(
                    "openclaw_weixin_context_file_insecure"
                )
            encoded = os.read(descriptor, _MAXIMUM_CONTEXT_FILE_BYTES + 1)
        finally:
            os.close(descriptor)
    except OpenClawWeixinProviderError:
        raise
    except OSError as exc:
        raise OpenClawWeixinProviderError(
            "openclaw_weixin_context_file_read_failed"
        ) from exc
    if len(encoded) > _MAXIMUM_CONTEXT_FILE_BYTES:
        raise OpenClawWeixinProviderError(
            "openclaw_weixin_context_file_too_large"
        )
    try:
        value = json.loads(
            encoded.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except OpenClawWeixinProviderError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpenClawWeixinProviderError(
            "openclaw_weixin_context_file_invalid"
        ) from exc
    if not isinstance(value, dict) or any(
        not isinstance(key, str)
        or not _RECIPIENT_RE.fullmatch(key)
        or not isinstance(item, str)
        for key, item in value.items()
    ):
        raise OpenClawWeixinProviderError("openclaw_weixin_context_file_invalid")
    if recipient not in value:
        raise OpenClawWeixinProviderError(
            "openclaw_weixin_context_recipient_missing"
        )
    return _credential_text(
        value[recipient], name="context_token", maximum=2_048
    )


def _wechat_uin() -> str:
    value = str(secrets.randbits(32)).encode("ascii")
    return base64.b64encode(value).decode("ascii")


def _content(payload: Mapping[str, Any], delivery_key: str) -> str:
    severity = str(payload.get("severity") or "INFO")
    severity_label = {
        "INFO": "信息",
        "WARNING": "注意",
        "CRITICAL": "严重",
        "HALT": "停机",
    }.get(severity, severity)
    title = str(payload.get("title") or "Qount 通知")
    summary = str(payload.get("summary") or "暂无摘要")
    occurred_at = str(payload.get("occurred_at") or "未知")
    content = (
        f"【Qount {severity_label}】{title}\n"
        f"{summary}\n"
        f"时间：{occurred_at}\n"
        f"证据：{delivery_key[:12]}\n"
        "详情：https://qount.alyaloale.com/#/intelligence"
    )
    encoded = content.encode("utf-8")
    if len(encoded) > 4_000:
        summary_bytes = summary.encode("utf-8")[:2_800]
        summary = summary_bytes.decode("utf-8", errors="ignore") + "..."
        content = (
            f"【Qount {severity_label}】{title}\n"
            f"{summary}\n"
            f"时间：{occurred_at}\n"
            f"证据：{delivery_key[:12]}\n"
            "详情：https://qount.alyaloale.com/#/intelligence"
        )
    return content


class OpenClawWeixinProvider:
    """Send one text message through Tencent's OpenClaw Weixin iLink API."""

    def __init__(
        self,
        *,
        timeout_seconds: int = 15,
        maximum_response_bytes: int = 64_000,
        opener: Any | None = None,
        clock: Any | None = None,
        context_token_directory: str | Path | None = None,
    ) -> None:
        if timeout_seconds < 1 or maximum_response_bytes < 1:
            raise OpenClawWeixinProviderError(
                "openclaw_weixin_provider_config_invalid"
            )
        self.timeout_seconds = timeout_seconds
        self.maximum_response_bytes = maximum_response_bytes
        self.opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({})
        )
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
        self.context_token_directory = (
            None
            if context_token_directory is None
            else Path(context_token_directory)
        )
        if (
            self.context_token_directory is not None
            and not self.context_token_directory.is_absolute()
        ):
            raise OpenClawWeixinProviderError(
                "openclaw_weixin_context_directory_invalid"
            )

    def send(
        self,
        payload: Mapping[str, Any],
        delivery_key: str,
        credential: str | None,
    ) -> Mapping[str, Any]:
        if credential is None:
            raise OpenClawWeixinProviderError(
                "openclaw_weixin_credential_required"
            )
        parsed = parse_openclaw_weixin_credential(credential)
        context_token = parsed.context_token
        if self.context_token_directory is not None:
            context_token = _load_current_context_token(
                self.context_token_directory,
                account_id=parsed.account_id,
                recipient=parsed.recipient,
            )
        if context_token is None:
            raise OpenClawWeixinProviderError(
                "openclaw_weixin_context_token_required"
            )
        client_id = f"qount:{delivery_key[:32]}"
        body = json.dumps(
            {
                "msg": {
                    "from_user_id": "",
                    "to_user_id": parsed.recipient,
                    "client_id": client_id,
                    "message_type": 2,
                    "message_state": 2,
                    "item_list": [
                        {"type": 1, "text_item": {"text": _content(payload, delivery_key)}}
                    ],
                    "context_token": context_token,
                },
                "base_info": {
                    "channel_version": OPENCLAW_WEIXIN_CHANNEL_VERSION,
                    "bot_agent": "Qount/0.2.0",
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        endpoint = urllib.parse.urljoin(parsed.base_url, "ilink/bot/sendmessage")
        request = urllib.request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {parsed.token}",
                "AuthorizationType": "ilink_bot_token",
                "Content-Type": "application/json",
                "User-Agent": "qount-openclaw-weixin-notifier/1",
                "X-WECHAT-UIN": _wechat_uin(),
                "iLink-App-Id": OPENCLAW_WEIXIN_APP_ID,
                "iLink-App-ClientVersion": OPENCLAW_WEIXIN_APP_CLIENT_VERSION,
            },
        )
        with self.opener.open(request, timeout=self.timeout_seconds) as response:
            raw = response.read(self.maximum_response_bytes + 1)
            status = int(response.status)
        if len(raw) > self.maximum_response_bytes:
            raise OpenClawWeixinProviderError(
                "openclaw_weixin_response_too_large"
            )
        if status < 200 or status >= 300:
            raise OpenClawWeixinProviderError(
                f"openclaw_weixin_http_status:{status}"
            )
        try:
            response_body = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OpenClawWeixinProviderError(
                "openclaw_weixin_response_invalid"
            ) from exc
        if not isinstance(response_body, dict):
            raise OpenClawWeixinProviderError(
                "openclaw_weixin_response_invalid"
            )
        if "ret" in response_body:
            ret = response_body["ret"]
            if not isinstance(ret, int) or isinstance(ret, bool):
                raise OpenClawWeixinProviderError(
                    "openclaw_weixin_response_ret_invalid"
                )
            if ret != 0:
                raise OpenClawWeixinProviderError(
                    f"openclaw_weixin_response_rejected:{ret}"
                )
        message_id = response_body.get("message_id")
        if (
            not isinstance(message_id, int)
            or isinstance(message_id, bool)
            or message_id <= 0
        ):
            raise OpenClawWeixinProviderError(
                "openclaw_weixin_response_message_id_invalid"
            )
        return ProviderResponse.create(
            provider=OPENCLAW_WEIXIN_PROVIDER_NAME,
            delivery_key=delivery_key,
            status="ACCEPTED",
            accepted=True,
            provider_message_id=str(message_id),
            received_at=self.clock().isoformat(),
        ).as_dict()


__all__ = [
    "OPENCLAW_WEIXIN_PROVIDER_NAME",
    "OpenClawWeixinCredential",
    "OpenClawWeixinProvider",
    "OpenClawWeixinProviderError",
    "parse_openclaw_weixin_credential",
]
