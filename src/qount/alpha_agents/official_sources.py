"""Bounded, no-proxy retrieval for official research source documents."""

from __future__ import annotations

import datetime as dt
import email.utils
import hashlib
import ipaddress
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Mapping, Sequence

from qount.alpha_agents.information_events import DEFAULT_ALLOWED_SOURCE_DOMAINS


OFFICIAL_SOURCE_DOCUMENT_VERSION = "official_source_document_v0.2"
OFFICIAL_SOURCE_PARSER_VERSION = "official_source_parser_v0.2"
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
_MONTH_DATE = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}\b",
    re.IGNORECASE,
)


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
        self._depth = 0
        self._ignored_depth = 0
        self._in_title = False
        self._captures: dict[str, int] = {}
        self.capture_parts: dict[str, list[str]] = {}
        self.meta: dict[str, str] = {}
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name.lower(): (value or "") for name, value in attrs}
        class_names = set(attributes.get("class", "").split())
        element_id = attributes.get("id", "")
        if tag == "meta":
            key = (attributes.get("property") or attributes.get("name") or "").lower()
            content = attributes.get("content", "").strip()
            if key and content:
                self.meta.setdefault(key, content)
        capture_names: list[str] = []
        if element_id == "article":
            capture_names.append("fed_article")
        if "node-details-layout__main-region__content" in class_names:
            capture_names.append("sec_content")
        if "field--name-body" in class_names:
            capture_names.append("article_body")
        if tag == "main" or attributes.get("role") == "main" or element_id in {
            "content",
            "main-content",
        }:
            capture_names.append("main")
        if "article__time" in class_names or any(
            "press-release-lead-in" in value for value in class_names
        ):
            capture_names.append("published")
        if element_id == "lastUpdate" or "date-modified" in class_names:
            capture_names.append("modified")
        for name in capture_names:
            self._captures.setdefault(name, self._depth)
            self.capture_parts.setdefault(name, [])
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1
        if tag == "title":
            self._in_title = True
        self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        self._depth = max(0, self._depth - 1)
        if tag in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1
        if tag == "title":
            self._in_title = False
        for name, depth in tuple(self._captures.items()):
            if depth == self._depth:
                del self._captures[name]

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
        self.text_parts.append(data)
        for name in self._captures:
            self.capture_parts[name].append(data)


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


@dataclass(frozen=True)
class _ExtractedSource:
    text: str
    title: str
    published_at: str | None
    modified_at: str | None
    extractor: str


def _source_timestamp(value: object) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value) / (1000.0 if float(value) > 10_000_000_000 else 1.0)
        try:
            return dt.datetime.fromtimestamp(seconds, tz=dt.UTC).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    text = _SPACE.sub(" ", str(value)).strip()
    match = _MONTH_DATE.search(text)
    if match:
        text = match.group(0)
    try:
        parsed = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = dt.datetime.strptime(text, "%B %d, %Y").replace(tzinfo=dt.UTC)
            except ValueError:
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC).isoformat()


def _mapping_value(value: Mapping[str, Any], names: Sequence[str]) -> object | None:
    for name in names:
        if name in value and value[name] is not None and value[name] != "":
            return value[name]
    return None


def _extract_binance_json(decoded: str) -> _ExtractedSource:
    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise ValueError("source_json_invalid") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("source_json_invalid")
    data = payload.get("data", payload)
    if not isinstance(data, Mapping):
        raise ValueError("source_json_invalid")
    article = data.get("article", data)
    if not isinstance(article, Mapping):
        article = data
    title_value = _mapping_value(article, ("title", "name", "headline"))
    body_value = _mapping_value(
        article,
        ("body", "content", "articleBody", "description", "summary"),
    )
    if body_value is None:
        raise ValueError("source_json_article_body_missing")
    body_text = str(body_value)
    parser = _VisibleTextParser()
    parser.feed(body_text)
    text = _SPACE.sub(" ", " ".join(parser.text_parts)).strip()
    title = _SPACE.sub(" ", str(title_value or "")).strip()
    return _ExtractedSource(
        text=text,
        title=title,
        published_at=_source_timestamp(
            _mapping_value(
                article,
                ("releaseDate", "publishedAt", "publishDate", "published_at"),
            )
        ),
        modified_at=_source_timestamp(
            _mapping_value(
                article,
                ("updateTime", "modifiedAt", "updatedAt", "modified_at"),
            )
        ),
        extractor="binance_article_json",
    )


def _extract_html(decoded: str, *, hostname: str) -> _ExtractedSource:
    parser = _VisibleTextParser()
    parser.feed(decoded)
    preferred = (
        ("fed_article", "federal_reserve_article")
        if hostname.endswith("federalreserve.gov")
        else ("article_body", "sec_press_release_body")
        if hostname.endswith("sec.gov")
        else ("article_body", "html_article_body")
    )
    capture_name, extractor = preferred
    parts = parser.capture_parts.get(capture_name)
    if not parts and hostname.endswith("sec.gov"):
        parts = parser.capture_parts.get("sec_content")
        extractor = "sec_main_content"
    if not parts:
        parts = parser.capture_parts.get("main")
        extractor = "html_main"
    if not parts:
        parts = parser.text_parts
        extractor = "html_visible_fallback"
    title = parser.meta.get("og:title") or " ".join(parser.title_parts)
    published_value = (
        parser.meta.get("article:published_time")
        or parser.meta.get("date")
        or " ".join(parser.capture_parts.get("published", []))
    )
    modified_value = (
        parser.meta.get("article:modified_time")
        or parser.meta.get("last-modified")
        or " ".join(parser.capture_parts.get("modified", []))
    )
    return _ExtractedSource(
        text=_SPACE.sub(" ", " ".join(parts)).strip(),
        title=_SPACE.sub(" ", title).strip(),
        published_at=_source_timestamp(published_value),
        modified_at=_source_timestamp(modified_value),
        extractor=extractor,
    )


def _extract_source(
    body: bytes,
    content_type_header: str,
    *,
    source_url: str,
) -> _ExtractedSource:
    decoded = _decode_source(body, content_type_header)
    media_type = content_type_header.split(";", 1)[0].strip().lower()
    hostname = (urllib.parse.urlparse(source_url).hostname or "").lower()
    if media_type == "application/json" and hostname.endswith("binance.com"):
        return _extract_binance_json(decoded)
    if media_type == "text/html":
        return _extract_html(decoded, hostname=hostname)
    return _ExtractedSource(
        text=_SPACE.sub(" ", decoded).strip(),
        title="",
        published_at=None,
        modified_at=None,
        extractor="plain_text",
    )


def _content_quality(text: str) -> str:
    words = re.findall(r"\w+", text, flags=re.UNICODE)
    if len(text) >= 240 and len(words) >= 35:
        return "substantive"
    if len(text) >= 60 and len(words) >= 8:
        return "limited"
    return "metadata_only"


@dataclass(frozen=True)
class OfficialSourceDocument:
    source_url: str
    final_url: str
    observed_at: str
    status_code: int
    content_type: str
    byte_count: int
    source_hash: str
    body_hash: str
    title: str
    text_excerpt: str
    published_at: str | None
    modified_at: str | None
    parser_version: str
    content_quality: str
    extractor: str
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
            "body_hash": self.body_hash,
            "title": self.title,
            "published_at": self.published_at,
            "modified_at": self.modified_at,
            "parser_version": self.parser_version,
            "content_quality": self.content_quality,
            "extractor": self.extractor,
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
    extracted = _extract_source(body, content_type_header, source_url=final_url)
    if not extracted.text:
        raise ValueError("source_visible_text_empty")
    body_hash = hashlib.sha256(body).hexdigest()
    return OfficialSourceDocument(
        source_url=source_url,
        final_url=final_url,
        observed_at=_utc_timestamp(observed_at),
        status_code=status_code,
        content_type=media_type,
        byte_count=len(body),
        source_hash=body_hash,
        body_hash=body_hash,
        title=extracted.title[:500],
        # The normalized source text has no surrounding whitespace, but a bounded
        # slice can end on a separator. Preserve the source body/hash while keeping
        # the structured excerpt valid for downstream evidence contracts.
        text_excerpt=extracted.text[:maximum_excerpt_chars].strip(),
        published_at=extracted.published_at,
        modified_at=extracted.modified_at,
        parser_version=OFFICIAL_SOURCE_PARSER_VERSION,
        content_quality=_content_quality(extracted.text),
        extractor=extracted.extractor,
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
