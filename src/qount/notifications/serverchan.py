"""ServerChan (Server酱) WeChat service-account notification provider.

Delivery uses the ServerChan Turbo SendKey API: one HTTPS POST to
``https://sctapi.ftqq.com/<sendkey>.send`` pushes a template message through
the ServerChan service account.  Unlike the OpenClaw personal-bot channel,
service-account pushes are not gated on a user conversation window: the
program can push anytime.  The SendKey is the credential and travels in the
URL path, so no exception message or response body is ever propagated with
URL content attached.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import urllib.parse
import urllib.request
from typing import Any, Mapping

from qount.contracts import canonical_hash
from qount.contracts import trace_id

from .transport import ProviderResponse
from .transport import ProviderResponseError


SERVERCHAN_PROVIDER_NAME = "serverchan"
SERVERCHAN_API_HOST = "sctapi.ftqq.com"

_SENDKEY_RE = re.compile(r"^SCT[0-9A-Za-z]{8,128}$")


class ServerChanProviderError(ValueError):
    """Raised when the SendKey is invalid or the response is malformed."""


def validate_serverchan_sendkey(value: str) -> str:
    if not isinstance(value, str) or not _SENDKEY_RE.fullmatch(value):
        raise ServerChanProviderError("serverchan_sendkey_invalid")
    return value


class ServerChanProvider:
    """Send a compact markdown push through the ServerChan SendKey API.

    ServerChan does not expose a client idempotency key.  The qount delivery
    key is embedded in the message body and retained by NotificationStore, but
    a crash after HTTP acceptance and before the local success marker may
    result in a visible duplicate on retry.
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
            raise ServerChanProviderError("serverchan_provider_config_invalid")
        self.timeout_seconds = timeout_seconds
        self.maximum_response_bytes = maximum_response_bytes
        self.opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({})
        )
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))

    @staticmethod
    def _content(payload: Mapping[str, Any], delivery_key: str) -> tuple[str, str]:
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
        api_title = f"[{severity_label}] {title}"
        if len(api_title) > 32:
            api_title = api_title[:31] + "…"
        desp = (
            f"### [{severity_label}] {title}\n\n"
            f"{summary}\n\n"
            f"> 时间：`{occurred_at}`\n"
            f"> 证据：`{delivery_key[:12]}`"
        )
        return api_title, desp

    def send(
        self,
        payload: Mapping[str, Any],
        delivery_key: str,
        credential: str | None,
    ) -> Mapping[str, Any]:
        if credential is None:
            raise ServerChanProviderError("serverchan_sendkey_required")
        sendkey = validate_serverchan_sendkey(credential)
        api_title, desp = self._content(payload, delivery_key)
        body = urllib.parse.urlencode(
            {"title": api_title, "desp": desp}
        ).encode("utf-8")
        request = urllib.request.Request(
            f"https://{SERVERCHAN_API_HOST}/{sendkey}.send",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                "User-Agent": "qount-serverchan-notifier/1",
            },
        )
        try:
            with self.opener.open(request, timeout=self.timeout_seconds) as response:
                raw = response.read(self.maximum_response_bytes + 1)
                status = int(response.status)
        except Exception as exc:
            # The request URL carries the SendKey: never propagate messages.
            raise ServerChanProviderError(
                f"serverchan_transport_error:{type(exc).__name__}"
            ) from None
        if len(raw) > self.maximum_response_bytes:
            raise ServerChanProviderError("serverchan_response_too_large")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ServerChanProviderError("serverchan_response_invalid") from exc
        if status != 200 or not isinstance(value, Mapping):
            raise ServerChanProviderError(f"serverchan_http_status:{status}")
        if "code" not in value:
            raise ServerChanProviderError("serverchan_response_fields_invalid")
        code = value["code"]
        if code != 0:
            # Only the numeric code is echoed; response text may carry content.
            raise ProviderResponseError(f"serverchan_rejected:{code}")
        response_hash = canonical_hash(dict(value))
        return ProviderResponse.create(
            provider=SERVERCHAN_PROVIDER_NAME,
            delivery_key=delivery_key,
            status="ACCEPTED",
            accepted=True,
            provider_message_id=trace_id(
                "serverchan_delivery",
                {"delivery_key": delivery_key, "response_hash": response_hash},
            ),
            received_at=self.clock().isoformat(),
        ).as_dict()


__all__ = [
    "SERVERCHAN_API_HOST",
    "SERVERCHAN_PROVIDER_NAME",
    "ServerChanProvider",
    "ServerChanProviderError",
    "validate_serverchan_sendkey",
]
