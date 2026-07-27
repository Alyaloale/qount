"""Injected notification provider contracts and a local-safe transport.

The transport deliberately knows nothing about HTTP, webhooks, or exchange
credentials.  A provider is injected as a callable (or an object exposing
``send``), while this module owns the response contract, delivery-key check,
rate limit, timeout and credential audit boundary.  Tests can therefore use
``FakeNotificationProvider`` without ever sending a real message.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import re
import stat
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from qount.contracts import canonical_hash
from qount.contracts import is_sha256
from qount.contracts import trace_id
from qount.contracts.trace import aware_datetime


PROVIDER_RESPONSE_SCHEMA_VERSION = 1
PROVIDER_RESPONSE_STATUSES = ("ACCEPTED", "DUPLICATE", "REJECTED")
NOTIFICATION_FAILURE_REASON_MAXIMUM = 120
_FAILURE_REASON_RE = re.compile(
    rf"^[A-Za-z][A-Za-z0-9_]{{0,{NOTIFICATION_FAILURE_REASON_MAXIMUM - 1}}}"
    rf"(?::[-]?[A-Za-z0-9_]{{1,{NOTIFICATION_FAILURE_REASON_MAXIMUM - 2}}})?$"
)
_SAFE_FAILURE_TYPE_NAMES = frozenset(
    {
        "BrokenPipeError",
        "ConnectionAbortedError",
        "ConnectionError",
        "ConnectionRefusedError",
        "ConnectionResetError",
        "HTTPError",
        "OSError",
        "OpenClawWeixinProviderError",
        "ProviderCredentialError",
        "ProviderRateLimitError",
        "ProviderResponseError",
        "ProviderTimeoutError",
        "RuntimeError",
        "SSLError",
        "TimeoutError",
        "URLError",
        "WeComProviderError",
    }
)


class NotificationTransportError(ValueError):
    """Base class for provider transport contract failures."""


class ProviderResponseError(NotificationTransportError):
    """Raised when a provider response is malformed or rejected."""


class ProviderRateLimitError(NotificationTransportError):
    """Raised when the local transport rate limit would be exceeded."""


class ProviderTimeoutError(NotificationTransportError):
    """Raised when an injected provider does not answer before its deadline."""


class ProviderCredentialError(NotificationTransportError):
    """Raised when a provider credential violates the private-file contract."""


# Short names make the boundary convenient for callers that call this a
# transport rather than a provider.
TransportRateLimitError = ProviderRateLimitError
TransportTimeoutError = ProviderTimeoutError
TransportCredentialError = ProviderCredentialError


def notification_failure_reason(error: BaseException) -> str:
    """Return a bounded diagnostic reason without persisting exception text.

    Provider exceptions may expose ``notification_reason`` when their message
    is an intentionally secret-free machine code.  All other exceptions are
    reduced to their class name so response bodies, credentials, recipients,
    and arbitrary remote error text cannot enter the durable outbox.
    """

    error_type = type(error).__name__
    explicit = getattr(error, "notification_reason", None)
    if (
        type(error).__module__ == "qount.notifications.weixin"
        and error_type == "OpenClawWeixinProviderError"
        and isinstance(explicit, str)
        and explicit.startswith("openclaw_weixin_")
        and len(explicit) <= NOTIFICATION_FAILURE_REASON_MAXIMUM
        and _FAILURE_REASON_RE.fullmatch(explicit)
    ):
        return explicit
    if (
        error_type in _SAFE_FAILURE_TYPE_NAMES
        and len(error_type) <= NOTIFICATION_FAILURE_REASON_MAXIMUM
        and _FAILURE_REASON_RE.fullmatch(error_type)
    ):
        return error_type
    return "NotificationDeliveryError"


def _text(value: object, *, name: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(char) < 32 for char in value)
    ):
        raise ProviderResponseError(f"provider_{name}_invalid")
    return value


def _utc_time(value: object, *, name: str) -> str:
    try:
        parsed = aware_datetime(value)  # type: ignore[arg-type]
    except (AttributeError, TypeError, ValueError) as exc:
        raise ProviderResponseError(f"provider_{name}_invalid") from exc
    return parsed.astimezone(dt.timezone.utc).isoformat()


@dataclass(frozen=True)
class ProviderResponse:
    """Canonical, secret-free result returned by a notification provider."""

    schema_version: int
    provider: str
    delivery_key: str
    status: str
    accepted: bool
    provider_message_id: str | None
    received_at: str
    response_hash: str

    @classmethod
    def create(
        cls,
        *,
        provider: str,
        delivery_key: str,
        status: str,
        accepted: bool,
        provider_message_id: str | None,
        received_at: str,
    ) -> "ProviderResponse":
        core = {
            "schema_version": PROVIDER_RESPONSE_SCHEMA_VERSION,
            "provider": provider,
            "delivery_key": delivery_key,
            "status": status,
            "accepted": accepted,
            "provider_message_id": provider_message_id,
            "received_at": _utc_time(received_at, name="received_at"),
        }
        response = cls(**core, response_hash=canonical_hash(core))
        response.validate()
        return response

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ProviderResponse":
        if not isinstance(value, Mapping):
            raise ProviderResponseError("provider_response_not_object")
        expected = {
            "schema_version",
            "provider",
            "delivery_key",
            "status",
            "accepted",
            "provider_message_id",
            "received_at",
            "response_hash",
        }
        if set(value) != expected:
            raise ProviderResponseError("provider_response_fields_invalid")
        try:
            response = cls(
                schema_version=value["schema_version"],
                provider=value["provider"],
                delivery_key=value["delivery_key"],
                status=value["status"],
                accepted=value["accepted"],
                provider_message_id=value["provider_message_id"],
                received_at=value["received_at"],
                response_hash=value["response_hash"],
            )
        except (KeyError, TypeError) as exc:
            raise ProviderResponseError("provider_response_fields_invalid") from exc
        response.validate()
        return response

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "provider": self.provider,
            "delivery_key": self.delivery_key,
            "status": self.status,
            "accepted": self.accepted,
            "provider_message_id": self.provider_message_id,
            "received_at": self.received_at,
        }

    def validate(self) -> None:
        if self.schema_version != PROVIDER_RESPONSE_SCHEMA_VERSION:
            raise ProviderResponseError("provider_schema_version_invalid")
        _text(self.provider, name="provider", maximum=64)
        if not is_sha256(self.delivery_key):
            raise ProviderResponseError("provider_delivery_key_invalid")
        if self.status not in PROVIDER_RESPONSE_STATUSES:
            raise ProviderResponseError("provider_status_invalid")
        if not isinstance(self.accepted, bool):
            raise ProviderResponseError("provider_accepted_invalid")
        if self.accepted != (self.status in {"ACCEPTED", "DUPLICATE"}):
            raise ProviderResponseError("provider_status_acceptance_mismatch")
        if self.provider_message_id is not None:
            _text(self.provider_message_id, name="message_id", maximum=240)
        if self.accepted and self.provider_message_id is None:
            raise ProviderResponseError("provider_message_id_required")
        if not self.accepted and self.provider_message_id is not None:
            raise ProviderResponseError("provider_message_id_unexpected")
        _utc_time(self.received_at, name="received_at")
        if self.response_hash != canonical_hash(self._core()):
            raise ProviderResponseError("provider_response_hash_invalid")

    def as_dict(self) -> dict[str, Any]:
        return self._core() | {"response_hash": self.response_hash}


class NotificationProvider(Protocol):
    def send(
        self,
        payload: Mapping[str, Any],
        delivery_key: str,
        credential: str | None,
    ) -> Mapping[str, Any]: ...


def _emit_audit(
    sink: Callable[[Mapping[str, Any]], None] | None,
    event: Mapping[str, Any],
) -> None:
    if sink is not None:
        sink(dict(event))


def _symlink_component(path: Path) -> Path | None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink():
            return current
    return None


def load_provider_credential(
    path: str | Path | None,
    *,
    provider: str,
    audit_sink: Callable[[Mapping[str, Any]], None] | None = None,
) -> str | None:
    """Load a provider key only from an exact 0600 file and audit its state.

    The audit intentionally records no key material.  ``path=None`` is a
    supported, explicit no-key mode for local fakes and always emits an audit
    event instead of silently looking at environment variables.
    """

    _text(provider, name="provider", maximum=64)
    credential: str | None = None
    source = "none"
    if path is not None:
        source = "file"
        credential_path = Path(path)
        if not credential_path.is_absolute():
            raise ProviderCredentialError("provider_credential_path_not_absolute")
        if _symlink_component(credential_path) is not None:
            raise ProviderCredentialError("provider_credential_symlink_rejected")
        if credential_path.is_symlink() or not credential_path.is_file():
            raise ProviderCredentialError("provider_credential_file_invalid")
        parent = credential_path.parent
        if parent.is_symlink() or not parent.is_dir():
            raise ProviderCredentialError("provider_credential_parent_invalid")
        if stat.S_IMODE(os.stat(parent, follow_symlinks=False).st_mode) & 0o077:
            raise ProviderCredentialError("provider_credential_parent_mode_invalid")
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(credential_path, flags)
            try:
                file_stat = os.fstat(descriptor)
                if not stat.S_ISREG(file_stat.st_mode):
                    raise ProviderCredentialError(
                        "provider_credential_file_invalid"
                    )
                if stat.S_IMODE(file_stat.st_mode) != 0o600:
                    raise ProviderCredentialError(
                        "provider_credential_mode_invalid"
                    )
                if file_stat.st_uid != os.geteuid():
                    raise ProviderCredentialError(
                        "provider_credential_owner_invalid"
                    )
                encoded = os.read(descriptor, 4_097)
            finally:
                os.close(descriptor)
            if len(encoded) > 4_096:
                raise ProviderCredentialError("provider_credential_value_too_large")
            raw = encoded.decode("utf-8")
        except ProviderCredentialError:
            raise
        except (OSError, UnicodeError) as exc:
            raise ProviderCredentialError("provider_credential_read_failed") from exc
        if not raw or raw != raw.strip() or any(ord(char) < 32 for char in raw):
            raise ProviderCredentialError("provider_credential_value_invalid")
        credential = raw
    _emit_audit(
        audit_sink,
        {
            "event_type": "notification_credential_audit",
            "provider": provider,
            "credential_source": source,
            "credential_present": credential is not None,
            "credential_value_omitted": True,
        },
    )
    return credential


@dataclass(frozen=True)
class RateLimitPolicy:
    """Fail-closed fixed-window rate limit for one injected transport."""

    max_calls: int = 5
    window_seconds: float = 1.0

    def validate(self) -> None:
        if (
            not isinstance(self.max_calls, int)
            or isinstance(self.max_calls, bool)
            or self.max_calls < 1
            or isinstance(self.window_seconds, bool)
            or not isinstance(self.window_seconds, (int, float))
            or not math.isfinite(float(self.window_seconds))
            or self.window_seconds <= 0
        ):
            raise NotificationTransportError("provider_rate_limit_policy_invalid")


class ProviderTransport:
    """Adapt one provider to the two-argument outbox transport contract."""

    def __init__(
        self,
        provider: NotificationProvider | Callable[..., Mapping[str, Any]],
        *,
        provider_name: str = "injected",
        credential_path: str | Path | None = None,
        require_credential: bool = False,
        timeout_seconds: float = 5.0,
        rate_limit: RateLimitPolicy | None = None,
        monotonic_clock: Callable[[], float] | None = None,
        audit_sink: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        if not callable(provider) and not callable(getattr(provider, "send", None)):
            raise TypeError("notification_provider_required")
        _text(provider_name, name="provider", maximum=64)
        if isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
            raise NotificationTransportError("provider_timeout_invalid")
        self.provider = provider
        self.provider_name = provider_name
        self.timeout_seconds = float(timeout_seconds)
        self.rate_limit = rate_limit or RateLimitPolicy()
        self.rate_limit.validate()
        self._clock = monotonic_clock or time.monotonic
        self._rate_timestamps: deque[float] = deque()
        self._rate_lock = threading.Lock()
        self.audit_events: list[dict[str, Any]] = []

        def record(event: Mapping[str, Any]) -> None:
            item = dict(event)
            self.audit_events.append(item)
            _emit_audit(audit_sink, item)

        self._audit = record
        self.credential = load_provider_credential(
            credential_path,
            provider=provider_name,
            audit_sink=record,
        )
        if require_credential and self.credential is None:
            raise ProviderCredentialError("provider_credential_required")

    def _acquire_rate_slot(self) -> None:
        now = float(self._clock())
        with self._rate_lock:
            self._discard_expired_rate_slots(now)
            if len(self._rate_timestamps) >= self.rate_limit.max_calls:
                self._audit(
                    {
                        "event_type": "notification_transport_rate_limited",
                        "provider": self.provider_name,
                        "credential_present": self.credential is not None,
                    }
                )
                raise ProviderRateLimitError("provider_rate_limit_exceeded")
            self._rate_timestamps.append(now)

    def _discard_expired_rate_slots(self, now: float) -> None:
        while (
            self._rate_timestamps
            and now - self._rate_timestamps[0] >= self.rate_limit.window_seconds
        ):
            self._rate_timestamps.popleft()

    def available_rate_slots(self) -> int:
        """Return the calls this transport can accept without local failure."""

        now = float(self._clock())
        with self._rate_lock:
            self._discard_expired_rate_slots(now)
            return self.rate_limit.max_calls - len(self._rate_timestamps)

    def shared_rate_limit_policy(self) -> tuple[str, int, float]:
        """Describe the provider limit used by a shared durable outbox."""

        return (
            self.provider_name,
            self.rate_limit.max_calls,
            float(self.rate_limit.window_seconds),
        )

    def _invoke(
        self,
        payload: Mapping[str, Any],
        delivery_key: str,
    ) -> Mapping[str, Any]:
        sender = getattr(self.provider, "send", None)
        if callable(sender):
            return sender(payload, delivery_key, self.credential)
        return self.provider(payload, delivery_key, self.credential)  # type: ignore[misc]

    def __call__(
        self,
        payload: Mapping[str, Any],
        delivery_key: str,
    ) -> Mapping[str, Any]:
        if not isinstance(payload, Mapping) or not is_sha256(delivery_key):
            raise NotificationTransportError("provider_transport_input_invalid")
        self._acquire_rate_slot()
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="qount-notify")
        future = executor.submit(self._invoke, payload, delivery_key)
        try:
            raw = future.result(timeout=self.timeout_seconds)
        except FutureTimeoutError as exc:
            future.cancel()
            self._audit(
                {
                    "event_type": "notification_transport_timeout",
                    "provider": self.provider_name,
                    "delivery_key": delivery_key,
                    "credential_present": self.credential is not None,
                }
            )
            raise ProviderTimeoutError("provider_timeout") from exc
        except Exception as exc:
            self._audit(
                {
                    "event_type": "notification_transport_provider_failed",
                    "provider": self.provider_name,
                    "delivery_key": delivery_key,
                    "error_type": notification_failure_reason(exc),
                    "credential_present": self.credential is not None,
                }
            )
            raise
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        try:
            response = ProviderResponse.from_mapping(raw)
        except ProviderResponseError:
            self._audit(
                {
                    "event_type": "notification_transport_response_invalid",
                    "provider": self.provider_name,
                    "delivery_key": delivery_key,
                    "credential_present": self.credential is not None,
                }
            )
            raise
        if response.delivery_key != delivery_key:
            self._audit(
                {
                    "event_type": "notification_transport_response_invalid",
                    "provider": self.provider_name,
                    "delivery_key": delivery_key,
                    "credential_present": self.credential is not None,
                }
            )
            raise ProviderResponseError("provider_delivery_key_mismatch")
        if response.provider != self.provider_name:
            self._audit(
                {
                    "event_type": "notification_transport_response_invalid",
                    "provider": self.provider_name,
                    "delivery_key": delivery_key,
                    "credential_present": self.credential is not None,
                }
            )
            raise ProviderResponseError("provider_identity_mismatch")
        self._audit(
            {
                "event_type": "notification_transport_response",
                "provider": self.provider_name,
                "delivery_key": delivery_key,
                "status": response.status,
                "response_hash": response.response_hash,
                "credential_present": self.credential is not None,
            }
        )
        if not response.accepted:
            raise ProviderResponseError("provider_rejected")
        return response.as_dict()


class FakeNotificationProvider:
    """Deterministic provider used by local tests; it never performs I/O."""

    def __init__(
        self,
        *,
        provider_name: str = "fake",
        failures: list[Exception] | None = None,
        responses: list[Mapping[str, Any]] | None = None,
        clock: Callable[[], dt.datetime] | None = None,
    ) -> None:
        self.provider_name = provider_name
        self.failures = deque(failures or [])
        self.responses = deque(responses or [])
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
        self.calls: list[dict[str, Any]] = []
        self._message_ids: dict[str, str] = {}

    def send(
        self,
        payload: Mapping[str, Any],
        delivery_key: str,
        credential: str | None,
    ) -> Mapping[str, Any]:
        self.calls.append(
            {
                "alert_id": payload.get("alert_id"),
                "delivery_key": delivery_key,
                "credential_present": credential is not None,
            }
        )
        if self.failures:
            raise self.failures.popleft()
        if self.responses:
            return dict(self.responses.popleft())
        duplicate = delivery_key in self._message_ids
        message_id = self._message_ids.setdefault(
            delivery_key,
            trace_id("fake_provider_message", {"delivery_key": delivery_key}),
        )
        status = "DUPLICATE" if duplicate else "ACCEPTED"
        return ProviderResponse.create(
            provider=self.provider_name,
            delivery_key=delivery_key,
            status=status,
            accepted=True,
            provider_message_id=message_id,
            received_at=self.clock().isoformat(),
        ).as_dict()


__all__ = [
    "FakeNotificationProvider",
    "NotificationProvider",
    "NotificationTransportError",
    "PROVIDER_RESPONSE_SCHEMA_VERSION",
    "PROVIDER_RESPONSE_STATUSES",
    "ProviderCredentialError",
    "ProviderRateLimitError",
    "ProviderResponse",
    "ProviderResponseError",
    "ProviderTimeoutError",
    "ProviderTransport",
    "RateLimitPolicy",
    "TransportCredentialError",
    "TransportRateLimitError",
    "TransportTimeoutError",
    "load_provider_credential",
    "notification_failure_reason",
]
