"""Audited discovery providers for the daily intelligence plane."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence

from qount.alpha_agents.official_sources import validate_official_source_url

from .contracts import SearchEvidence


BRAVE_SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
OFFICIAL_FEED_ENDPOINTS = {
    "binance.com": (
        "binance_catalog",
        "https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query?catalogId=48&pageNo=1&pageSize=20",
    ),
    "federalreserve.gov": (
        "rss",
        "https://www.federalreserve.gov/feeds/press_all.xml",
    ),
    "sec.gov": (
        "rss",
        "https://www.sec.gov/news/pressreleases.rss",
    ),
}
OFFICIAL_FEED_PROVIDER_NAME = "official_feed_discovery"
_SITE_QUERY_RE = re.compile(r"(?:^|\s)site:([a-z0-9.-]+)(?:\s|$)", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")
_BINANCE_ARTICLE_CODE_RE = re.compile(r"^[0-9a-f]{32}$")


class SearchProviderError(ValueError):
    """Raised when search discovery cannot preserve its evidence contract."""


@dataclass(frozen=True)
class SearchResponse:
    evidence: SearchEvidence
    titles: tuple[str, ...]
    raw_body: bytes = field(repr=False)


class SearchProvider(Protocol):
    def search(self, query: str, *, searched_at: str) -> SearchResponse: ...


def _utc(value: str) -> str:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SearchProviderError("search_time_must_be_aware")
    return parsed.astimezone(dt.timezone.utc).isoformat()


class BraveSearchProvider:
    """Small, no-proxy Brave Web Search adapter used only for URL discovery."""

    def __init__(
        self,
        *,
        credential: str,
        count: int = 8,
        timeout_seconds: int = 20,
        maximum_response_bytes: int = 512_000,
        opener: Any | None = None,
    ) -> None:
        if not credential or credential != credential.strip():
            raise SearchProviderError("brave_search_credential_invalid")
        if count < 1 or count > 20 or timeout_seconds < 1 or maximum_response_bytes < 1:
            raise SearchProviderError("brave_search_config_invalid")
        self.credential = credential
        self.count = count
        self.timeout_seconds = timeout_seconds
        self.maximum_response_bytes = maximum_response_bytes
        self.opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({})
        )

    def search(self, query: str, *, searched_at: str) -> SearchResponse:
        if not isinstance(query, str) or not query.strip() or len(query) > 500:
            raise SearchProviderError("search_query_invalid")
        url = f"{BRAVE_SEARCH_ENDPOINT}?{urllib.parse.urlencode({'q': query, 'count': self.count, 'safesearch': 'strict'})}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "qount-intelligence-search/1",
                "X-Subscription-Token": self.credential,
            },
        )
        with self.opener.open(request, timeout=self.timeout_seconds) as response:
            if int(response.status) != 200:
                raise SearchProviderError(f"brave_search_http_status:{response.status}")
            raw = response.read(self.maximum_response_bytes + 1)
        if len(raw) > self.maximum_response_bytes:
            raise SearchProviderError("brave_search_response_too_large")
        try:
            payload = json.loads(raw)
            rows = payload["web"]["results"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise SearchProviderError("brave_search_response_invalid") from exc
        urls: list[str] = []
        titles: list[str] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            url_value = row.get("url")
            title_value = row.get("title")
            if not isinstance(url_value, str) or not url_value.startswith("https://"):
                continue
            if url_value in urls:
                continue
            urls.append(url_value)
            titles.append(str(title_value or url_value)[:500])
            if len(urls) >= self.count:
                break
        evidence = SearchEvidence(
            query=query.strip(),
            provider="brave_web_search",
            searched_at=_utc(searched_at),
            result_count=len(urls),
            response_hash=hashlib.sha256(raw).hexdigest(),
            urls=tuple(urls),
        )
        evidence.validate()
        return SearchResponse(evidence=evidence, titles=tuple(titles), raw_body=raw)


def _official_feed_route(query: str) -> tuple[str, str, str]:
    match = _SITE_QUERY_RE.search(query)
    domain = match.group(1).lower().rstrip(".") if match else ""
    route = OFFICIAL_FEED_ENDPOINTS.get(domain)
    if route is None:
        raise SearchProviderError("official_feed_query_not_supported")
    parser_name, endpoint = route
    return domain, parser_name, endpoint


def _official_result(
    *,
    domain: str,
    title: object,
    url: object,
) -> tuple[str, str] | None:
    if not isinstance(url, str):
        return None
    normalized_url = url.strip()
    parsed = urllib.parse.urlparse(normalized_url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if (
        not normalized_url.startswith("https://")
        or (hostname != domain and not hostname.endswith(f".{domain}"))
        or validate_official_source_url(normalized_url)
    ):
        return None
    normalized_title = _SPACE_RE.sub(" ", str(title or normalized_url)).strip()
    return normalized_title[:500], normalized_url


def _parse_binance_catalog(raw: bytes, *, count: int) -> tuple[tuple[str, str], ...]:
    try:
        payload = json.loads(raw)
        if payload.get("success") is not True or payload.get("code") != "000000":
            raise SearchProviderError("official_feed_response_rejected")
        rows = payload["data"]["articles"]
    except SearchProviderError:
        raise
    except (AttributeError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SearchProviderError("official_feed_response_invalid") from exc
    if not isinstance(rows, list):
        raise SearchProviderError("official_feed_response_invalid")
    results: list[tuple[str, str]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        code = row.get("code")
        if not isinstance(code, str) or not _BINANCE_ARTICLE_CODE_RE.fullmatch(code):
            continue
        url = (
            "https://www.binance.com/bapi/composite/v1/public/cms/article/"
            f"detail/query?{urllib.parse.urlencode({'articleCode': code})}"
        )
        result = _official_result(
            domain="binance.com",
            title=row.get("title"),
            url=url,
        )
        if result is not None and result[1] not in {item[1] for item in results}:
            results.append(result)
        if len(results) >= count:
            break
    return tuple(results)


def _parse_official_rss(
    raw: bytes,
    *,
    domain: str,
    count: int,
) -> tuple[tuple[str, str], ...]:
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise SearchProviderError("official_feed_xml_declaration_forbidden")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise SearchProviderError("official_feed_response_invalid") from exc
    results: list[tuple[str, str]] = []
    for item in root.findall(".//item"):
        result = _official_result(
            domain=domain,
            title=item.findtext("title"),
            url=item.findtext("link"),
        )
        if result is not None and result[1] not in {row[1] for row in results}:
            results.append(result)
        if len(results) >= count:
            break
    return tuple(results)


class OfficialFeedSearchProvider:
    """Keyless URL discovery from bounded Binance, Fed, and SEC official feeds."""

    def __init__(
        self,
        *,
        count: int = 3,
        timeout_seconds: int = 20,
        maximum_response_bytes: int = 512_000,
        opener: Any | None = None,
    ) -> None:
        if count < 1 or count > 10 or timeout_seconds < 1 or maximum_response_bytes < 1:
            raise SearchProviderError("official_feed_config_invalid")
        self.count = count
        self.timeout_seconds = timeout_seconds
        self.maximum_response_bytes = maximum_response_bytes
        self.opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({})
        )

    def search(self, query: str, *, searched_at: str) -> SearchResponse:
        if not isinstance(query, str) or not query.strip() or len(query) > 500:
            raise SearchProviderError("search_query_invalid")
        normalized_query = query.strip()
        domain, parser_name, endpoint = _official_feed_route(normalized_query)
        request = urllib.request.Request(
            endpoint,
            headers={
                "Accept": "application/json,application/rss+xml,application/xml,text/xml",
                "User-Agent": "qount-intelligence/0.2 (+https://qount.alyaloale.com/)",
            },
        )
        with self.opener.open(request, timeout=self.timeout_seconds) as response:
            status = int(response.status)
            final_url = response.geturl()
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
            raw = response.read(self.maximum_response_bytes + 1)
        endpoint_parsed = urllib.parse.urlparse(endpoint)
        final_parsed = urllib.parse.urlparse(final_url)
        if (
            status != 200
            or final_parsed.scheme != "https"
            or final_parsed.hostname != endpoint_parsed.hostname
            or final_parsed.path != endpoint_parsed.path
        ):
            raise SearchProviderError("official_feed_route_invalid")
        if len(raw) > self.maximum_response_bytes:
            raise SearchProviderError("official_feed_response_too_large")
        expected_types = (
            {"application/json"}
            if parser_name == "binance_catalog"
            else {"application/rss+xml", "application/xml", "text/xml"}
        )
        if content_type not in expected_types:
            raise SearchProviderError("official_feed_content_type_invalid")
        rows = (
            _parse_binance_catalog(raw, count=self.count)
            if parser_name == "binance_catalog"
            else _parse_official_rss(raw, domain=domain, count=self.count)
        )
        evidence = SearchEvidence(
            query=normalized_query,
            provider=OFFICIAL_FEED_PROVIDER_NAME,
            searched_at=_utc(searched_at),
            result_count=len(rows),
            response_hash=hashlib.sha256(raw).hexdigest(),
            urls=tuple(url for _, url in rows),
        )
        evidence.validate()
        return SearchResponse(
            evidence=evidence,
            titles=tuple(title for title, _ in rows),
            raw_body=raw,
        )


class StaticSearchProvider:
    """Deterministic provider for tests and explicitly configured source plans."""

    def __init__(self, results: Mapping[str, Sequence[tuple[str, str]]]) -> None:
        self.results = {key: tuple(value) for key, value in results.items()}

    def search(self, query: str, *, searched_at: str) -> SearchResponse:
        rows = self.results.get(query, ())
        payload = {
            "query": query,
            "results": [{"title": title, "url": url} for title, url in rows],
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        evidence = SearchEvidence(
            query=query,
            provider="static_source_plan",
            searched_at=_utc(searched_at),
            result_count=len(rows),
            response_hash=hashlib.sha256(raw).hexdigest(),
            urls=tuple(url for _, url in rows),
        )
        evidence.validate()
        return SearchResponse(
            evidence=evidence,
            titles=tuple(title for title, _ in rows),
            raw_body=raw,
        )


__all__ = [
    "BRAVE_SEARCH_ENDPOINT",
    "OFFICIAL_FEED_ENDPOINTS",
    "OFFICIAL_FEED_PROVIDER_NAME",
    "BraveSearchProvider",
    "OfficialFeedSearchProvider",
    "SearchProvider",
    "SearchProviderError",
    "SearchResponse",
    "StaticSearchProvider",
]
