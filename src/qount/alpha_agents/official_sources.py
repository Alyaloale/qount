"""Bounded, no-proxy retrieval for official research source documents."""

from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Mapping, Sequence

from qount.alpha_agents.information_events import DEFAULT_ALLOWED_SOURCE_DOMAINS


OFFICIAL_SOURCE_DOCUMENT_VERSION = "official_source_document_v0.1"
DEFAULT_MAX_SOURCE_BYTES = 512_000
DEFAULT_MAX_LLM_EXCERPT_CHARS = 12_000
DEFAULT_ALLOWED_GITHUB_REPOSITORIES = (("binance", "binance-public-data"),)
_ALLOWED_CONTENT_TYPES = frozenset(
    {
        "application/json",
        "application/vnd.github.raw+json",
        "application/xml",
        "text/html",
        "text/plain",
        "text/xml",
    }
)
_SPACE = re.compile(r"\s+")


def _utc_timestamp(value: str | None = None) -> str:
    if value is None:
        return dt.datetime.now(dt.UTC).isoformat()
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("source_observed_at_must_be_timezone_aware")
    return parsed.astimezone(dt.UTC).isoformat()


def _domain_allowed(hostname: str, allowed_domains: Sequence[str]) -> bool:
    host = hostname.lower().rstrip(".")
    return any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains)


def validate_official_source_url(
    url: str,
    *,
    allowed_domains: Sequence[str] = DEFAULT_ALLOWED_SOURCE_DOMAINS,
    allowed_github_repositories: Sequence[tuple[str, str]] = (
        DEFAULT_ALLOWED_GITHUB_REPOSITORIES
    ),
) -> tuple[str, ...]:
    errors: list[str] = []
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        errors.append("source_url_not_https")
    if not parsed.hostname:
        errors.append("source_url_hostname_missing")
        return tuple(errors)
    if parsed.username is not None or parsed.password is not None:
        errors.append("source_url_embedded_credentials")
    try:
        if parsed.port not in {None, 443}:
            errors.append("source_url_nonstandard_port")
    except ValueError:
        errors.append("source_url_port_invalid")
    try:
        ipaddress.ip_address(parsed.hostname)
    except ValueError:
        pass
    else:
        errors.append("source_url_ip_literal_forbidden")
    if not _domain_allowed(parsed.hostname, allowed_domains):
        errors.append("source_domain_not_allowed")
    if parsed.hostname in {"github.com", "api.github.com"}:
        parts = tuple(part for part in parsed.path.split("/") if part)
        if parsed.hostname == "api.github.com":
            repository = parts[1:3] if len(parts) >= 3 and parts[0] == "repos" else ()
        else:
            repository = parts[:2] if len(parts) >= 2 else ()
        normalized_allowed = {
            (owner.lower(), name.lower())
            for owner, name in allowed_github_repositories
        }
        if tuple(part.lower() for part in repository) not in normalized_allowed:
            errors.append("source_github_repository_not_allowed")
    elif parsed.hostname.endswith(".github.com"):
        errors.append("source_github_host_not_supported")
    return tuple(errors)


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._in_title = False
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
        self.text_parts.append(data)


def _decode_source(body: bytes, content_type_header: str) -> str:
    charset = "utf-8"
    for part in content_type_header.split(";")[1:]:
        name, separator, value = part.strip().partition("=")
        if separator and name.lower() == "charset" and value.strip():
            charset = value.strip().strip('"')
            break
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _text_and_title(body: bytes, content_type_header: str) -> tuple[str, str]:
    decoded = _decode_source(body, content_type_header)
    media_type = content_type_header.split(";", 1)[0].strip().lower()
    if media_type == "text/html":
        parser = _VisibleTextParser()
        parser.feed(decoded)
        title = _SPACE.sub(" ", " ".join(parser.title_parts)).strip()
        text = _SPACE.sub(" ", " ".join(parser.text_parts)).strip()
        return text, title
    return _SPACE.sub(" ", decoded).strip(), ""


@dataclass(frozen=True)
class OfficialSourceDocument:
    source_url: str
    final_url: str
    observed_at: str
    status_code: int
    content_type: str
    byte_count: int
    source_hash: str
    title: str
    text_excerpt: str
    body: bytes = field(repr=False)
    schema_version: str = OFFICIAL_SOURCE_DOCUMENT_VERSION

    def to_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_url": self.source_url,
            "final_url": self.final_url,
            "observed_at": self.observed_at,
            "status_code": self.status_code,
            "content_type": self.content_type,
            "byte_count": self.byte_count,
            "source_hash": self.source_hash,
            "title": self.title,
            "environment_proxy_used": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        }


def build_official_source_document(
    *,
    source_url: str,
    final_url: str,
    body: bytes,
    content_type_header: str,
    observed_at: str,
    status_code: int = 200,
    allowed_domains: Sequence[str] = DEFAULT_ALLOWED_SOURCE_DOMAINS,
    maximum_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
    maximum_excerpt_chars: int = DEFAULT_MAX_LLM_EXCERPT_CHARS,
) -> OfficialSourceDocument:
    source_errors = validate_official_source_url(
        source_url, allowed_domains=allowed_domains
    )
    final_errors = validate_official_source_url(
        final_url, allowed_domains=allowed_domains
    )
    if source_errors:
        raise ValueError(f"invalid_source_url:{','.join(source_errors)}")
    if final_errors:
        raise ValueError(f"invalid_final_url:{','.join(final_errors)}")
    if status_code != 200:
        raise ValueError(f"source_http_status_not_200:{status_code}")
    if maximum_source_bytes <= 0 or len(body) > maximum_source_bytes:
        raise ValueError("source_body_size_exceeded")
    if maximum_excerpt_chars <= 0:
        raise ValueError("source_excerpt_limit_invalid")
    media_type = content_type_header.split(";", 1)[0].strip().lower()
    if media_type not in _ALLOWED_CONTENT_TYPES:
        raise ValueError(f"source_content_type_not_allowed:{media_type}")
    text, title = _text_and_title(body, content_type_header)
    if not text:
        raise ValueError("source_visible_text_empty")
    return OfficialSourceDocument(
        source_url=source_url,
        final_url=final_url,
        observed_at=_utc_timestamp(observed_at),
        status_code=status_code,
        content_type=media_type,
        byte_count=len(body),
        source_hash=hashlib.sha256(body).hexdigest(),
        title=title[:500],
        # The normalized source text has no surrounding whitespace, but a bounded
        # slice can end on a separator. Preserve the source body/hash while keeping
        # the structured excerpt valid for downstream evidence contracts.
        text_excerpt=text[:maximum_excerpt_chars].strip(),
        body=body,
    )


def fetch_official_source_document(
    url: str,
    *,
    observed_at: str | None = None,
    allowed_domains: Sequence[str] = DEFAULT_ALLOWED_SOURCE_DOMAINS,
    maximum_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
    timeout_seconds: int = 20,
) -> OfficialSourceDocument:
    errors = validate_official_source_url(url, allowed_domains=allowed_domains)
    if errors:
        raise ValueError(f"invalid_source_url:{','.join(errors)}")
    if timeout_seconds <= 0:
        raise ValueError("source_timeout_invalid")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    hostname = urllib.parse.urlparse(url).hostname or ""
    accept = (
        "application/vnd.github.raw+json"
        if hostname == "api.github.com"
        else "text/html,application/json,text/plain,application/xml,text/xml"
    )
    request = urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": "qount-research-source-fetch/0.1",
        },
    )
    with opener.open(request, timeout=timeout_seconds) as response:
        body = response.read(maximum_source_bytes + 1)
        return build_official_source_document(
            source_url=url,
            final_url=response.geturl(),
            body=body,
            content_type_header=response.headers.get("Content-Type", ""),
            observed_at=_utc_timestamp(observed_at),
            status_code=int(response.status),
            allowed_domains=allowed_domains,
            maximum_source_bytes=maximum_source_bytes,
        )


def official_source_llm_context(
    document: OfficialSourceDocument,
) -> Mapping[str, Any]:
    return {
        **document.to_metadata(),
        "text_excerpt": document.text_excerpt,
        "source_hash_verified": (
            hashlib.sha256(document.body).hexdigest() == document.source_hash
        ),
        "llm_may_claim_web_search": False,
    }
