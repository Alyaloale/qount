"""Enterprise WeChat group-robot notification provider."""

from __future__ import annotations

import datetime as dt
import json
import urllib.parse
import urllib.request
from typing import Any, Mapping

from qount.contracts import canonical_hash
from qount.contracts import trace_id

from .transport import ProviderResponse
from .transport import ProviderResponseError


WECOM_PROVIDER_NAME = "wecom_group_robot"
WECOM_WEBHOOK_HOST = "qyapi.weixin.qq.com"
WECOM_WEBHOOK_PATH = "/cgi-bin/webhook/send"


class WeComProviderError(ValueError):
    """Raised when WeCom rejects a message or returns malformed evidence."""


def validate_wecom_webhook(value: str) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise WeComProviderError("wecom_webhook_invalid")
    parsed = urllib.parse.urlparse(value)
    query = urllib.parse.parse_qs(parsed.query, strict_parsing=True)
    if (
        parsed.scheme != "https"
        or parsed.hostname != WECOM_WEBHOOK_HOST
        or parsed.path != WECOM_WEBHOOK_PATH
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or set(query) != {"key"}
        or len(query["key"]) != 1
        or not query["key"][0]
        or len(query["key"][0]) > 128
    ):
        raise WeComProviderError("wecom_webhook_invalid")
    return value


class WeComGroupRobotProvider:
    """Send compact markdown through a WeCom group robot webhook.

    WeCom does not expose a client idempotency key. The qount delivery key is
    embedded in the message and retained by NotificationStore, but a process
    crash after HTTP acceptance and before the local success marker may result
    in a visible duplicate on retry.
    """

    def __init__(
        self,
        *,
        timeout_seconds: int = 5,
        maximum_response_bytes: int = 64_000,
        opener: Any | None = None,
        clock: Any | None = None,
    ) -> None:
        if timeout_seconds < 1 or maximum_response_bytes < 1:
            raise WeComProviderError("wecom_provider_config_invalid")
        self.timeout_seconds = timeout_seconds
        self.maximum_response_bytes = maximum_response_bytes
        self.opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({})
        )
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))

    @staticmethod
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
            f"### [{severity_label}] {title}\n"
            f"> {summary}\n"
            f"> 时间：`{occurred_at}`\n"
            f"> 证据：`{delivery_key[:12]}`"
        )
        if len(content.encode("utf-8")) > 4_096:
            content = content[:3_600] + f"\n> 证据：`{delivery_key[:12]}`"
        return content

    def send(
        self,
        payload: Mapping[str, Any],
        delivery_key: str,
        credential: str | None,
    ) -> Mapping[str, Any]:
        if credential is None:
            raise WeComProviderError("wecom_webhook_required")
        webhook = validate_wecom_webhook(credential)
        body = json.dumps(
            {
                "msgtype": "markdown",
                "markdown": {"content": self._content(payload, delivery_key)},
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            webhook,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "qount-wecom-notifier/1",
            },
        )
        with self.opener.open(request, timeout=self.timeout_seconds) as response:
            raw = response.read(self.maximum_response_bytes + 1)
            status = int(response.status)
        if len(raw) > self.maximum_response_bytes:
            raise WeComProviderError("wecom_response_too_large")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise WeComProviderError("wecom_response_invalid") from exc
        if status != 200 or not isinstance(value, Mapping):
            raise WeComProviderError(f"wecom_http_status:{status}")
        if set(value) != {"errcode", "errmsg"}:
            raise WeComProviderError("wecom_response_fields_invalid")
        if value["errcode"] != 0 or value["errmsg"] != "ok":
            raise ProviderResponseError(
                f"wecom_rejected:{value['errcode']}:{str(value['errmsg'])[:120]}"
            )
        response_hash = canonical_hash(dict(value))
        return ProviderResponse.create(
            provider=WECOM_PROVIDER_NAME,
            delivery_key=delivery_key,
            status="ACCEPTED",
            accepted=True,
            provider_message_id=trace_id(
                "wecom_delivery",
                {"delivery_key": delivery_key, "response_hash": response_hash},
            ),
            received_at=self.clock().isoformat(),
        ).as_dict()


__all__ = [
    "WECOM_PROVIDER_NAME",
    "WECOM_WEBHOOK_HOST",
    "WECOM_WEBHOOK_PATH",
    "WeComGroupRobotProvider",
    "WeComProviderError",
    "validate_wecom_webhook",
]
