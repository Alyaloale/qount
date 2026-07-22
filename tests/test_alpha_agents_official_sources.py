from __future__ import annotations

import hashlib
import json
import unittest
from unittest.mock import patch

from qount.alpha_agents.official_sources import build_official_source_document
from qount.alpha_agents.official_sources import fetch_official_source_document
from qount.alpha_agents.official_sources import official_source_llm_context
from qount.alpha_agents.official_sources import validate_official_source_url


class _Response:
    status = 200

    def __init__(
        self, *, body: bytes, final_url: str, content_type: str = "text/html; charset=utf-8"
    ) -> None:
        self._body = body
        self._final_url = final_url
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return self._body[:limit]

    def geturl(self) -> str:
        return self._final_url


class _Opener:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.requests = []

    def open(self, request, timeout: int):
        self.requests.append((request, timeout))
        return self.response


class OfficialSourceTests(unittest.TestCase):
    def test_official_html_is_hashed_and_bounded_for_llm_context(self) -> None:
        body = (
            b"<html><head><title>Official Notice</title><script>ignore()</script></head>"
            b"<body><h1>Maintenance</h1><p>The exchange published a notice.</p></body></html>"
        )
        document = build_official_source_document(
            source_url="https://www.binance.com/en/support/announcement/example",
            final_url="https://www.binance.com/en/support/announcement/example",
            body=body,
            content_type_header="text/html; charset=utf-8",
            observed_at="2026-07-19T10:00:00+00:00",
        )
        self.assertEqual(document.source_hash, hashlib.sha256(body).hexdigest())
        self.assertEqual(document.body_hash, document.source_hash)
        self.assertEqual(document.title, "Official Notice")
        self.assertNotIn("ignore", document.text_excerpt)
        context = official_source_llm_context(document)
        self.assertTrue(context["source_hash_verified"])
        self.assertFalse(context["environment_proxy_used"])
        self.assertFalse(context["llm_may_claim_web_search"])
        self.assertNotIn("body", document.to_metadata())
        self.assertEqual(document.parser_version, "official_source_parser_v0.2")

    def test_binance_json_extracts_article_body_and_dates(self) -> None:
        body = json.dumps(
            {
                "data": {
                    "title": "Binance product update",
                    "body": "<p>The exchange will add a product with eligibility and risk terms.</p>"
                    "<p>Users should review the complete schedule and regional restrictions.</p>",
                    "releaseDate": 1784678400000,
                    "updateTime": 1784682000000,
                }
            }
        ).encode()
        url = (
            "https://www.binance.com/bapi/composite/v1/public/cms/article/"
            "detail/query?articleCode=" + "a" * 32
        )
        document = build_official_source_document(
            source_url=url,
            final_url=url,
            body=body,
            content_type_header="application/json",
            observed_at="2026-07-22T04:00:00+00:00",
        )

        self.assertEqual(document.title, "Binance product update")
        self.assertIn("regional restrictions", document.text_excerpt)
        self.assertEqual(document.extractor, "binance_article_json")
        self.assertIsNotNone(document.published_at)
        self.assertIsNotNone(document.modified_at)
        self.assertEqual(document.content_quality, "limited")

    def test_fed_and_sec_extract_scoped_body_without_navigation(self) -> None:
        fixtures = (
            (
                "https://www.federalreserve.gov/newsevents/pressreleases/example.htm",
                b"<html><head><meta property='og:title' content='Fed release'></head>"
                b"<body><nav>Navigation only</nav><div id='article'>"
                b"<p class='article__time'>July 14, 2026</p>"
                b"<p>The Board released substantive discount-rate meeting details for depository institutions and explained the distinction from the federal funds target process.</p>"
                b"<div id='lastUpdate'>Last Update: July 15, 2026</div></div></body></html>",
                "federal_reserve_article",
            ),
            (
                "https://www.sec.gov/newsroom/press-releases/example",
                b"<html><head><meta property='og:title' content='SEC release'></head>"
                b"<body><nav>Navigation only</nav><main id='main-content'>"
                b"<div class='field press-release-lead-in'>Washington D.C., July 16, 2026</div>"
                b"<div class='field field--name-body'>The Commission proposed a detailed rule with scope, transition conditions, and a sixty-day public comment period for affected market participants.</div>"
                b"<div class='date-modified'>Last Reviewed or Updated: July 17, 2026</div>"
                b"</main></body></html>",
                "sec_press_release_body",
            ),
        )
        for url, body, extractor in fixtures:
            with self.subTest(url=url):
                document = build_official_source_document(
                    source_url=url,
                    final_url=url,
                    body=body,
                    content_type_header="text/html",
                    observed_at="2026-07-22T04:00:00+00:00",
                )
                self.assertNotIn("Navigation only", document.text_excerpt)
                self.assertEqual(document.extractor, extractor)
                self.assertIsNotNone(document.published_at)
                self.assertIsNotNone(document.modified_at)

    def test_non_https_credentials_and_unknown_domains_are_rejected(self) -> None:
        errors = validate_official_source_url(
            "http://user:pass@example.com/private"
        )
        self.assertIn("source_url_not_https", errors)
        self.assertIn("source_url_embedded_credentials", errors)
        self.assertIn("source_domain_not_allowed", errors)

    def test_github_domain_requires_explicit_repository_allowlist(self) -> None:
        errors = validate_official_source_url(
            "https://github.com/untrusted/project/blob/main/README.md"
        )
        self.assertIn("source_github_repository_not_allowed", errors)
        self.assertEqual(
            validate_official_source_url(
                "https://api.github.com/repos/binance/binance-public-data/readme"
            ),
            (),
        )

    def test_redirect_is_revalidated_against_allowlist(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid_final_url"):
            build_official_source_document(
                source_url="https://www.sec.gov/Archives/example",
                final_url="https://example.com/copied",
                body=b"filing text",
                content_type_header="text/plain",
                observed_at="2026-07-19T10:00:00+00:00",
            )

    def test_oversized_source_is_rejected_before_llm_context(self) -> None:
        with self.assertRaisesRegex(ValueError, "source_body_size_exceeded"):
            build_official_source_document(
                source_url="https://www.sec.gov/Archives/example",
                final_url="https://www.sec.gov/Archives/example",
                body=b"x" * 11,
                content_type_header="text/plain",
                observed_at="2026-07-19T10:00:00+00:00",
                maximum_source_bytes=10,
            )

    def test_excerpt_truncation_strips_separator_at_boundary(self) -> None:
        document = build_official_source_document(
            source_url="https://www.binance.com/en/support/announcement/example",
            final_url="https://www.binance.com/en/support/announcement/example",
            body=b"<html><body>alpha beta gamma</body></html>",
            content_type_header="text/html",
            observed_at="2026-07-19T10:00:00+00:00",
            maximum_excerpt_chars=6,
        )

        self.assertEqual(document.text_excerpt, "alpha")
        self.assertEqual(document.source_hash, hashlib.sha256(document.body).hexdigest())

    def test_github_raw_api_media_type_is_accepted_as_text(self) -> None:
        document = build_official_source_document(
            source_url="https://api.github.com/repos/binance/binance-public-data/readme",
            final_url="https://api.github.com/repos/binance/binance-public-data/readme",
            body=b"# Binance Public Data\nCHECKSUM files are available.",
            content_type_header="application/vnd.github.raw+json; charset=utf-8",
            observed_at="2026-07-19T10:00:00+00:00",
        )
        self.assertIn("CHECKSUM", document.text_excerpt)

    def test_fetcher_disables_environment_proxy_and_preserves_final_url(self) -> None:
        response = _Response(
            body=b"<html><body>Official release.</body></html>",
            final_url="https://www.federalreserve.gov/newsevents/example.htm",
        )
        opener = _Opener(response)
        with patch(
            "qount.alpha_agents.official_sources.urllib.request.build_opener",
            return_value=opener,
        ) as build_opener:
            document = fetch_official_source_document(
                "https://www.federalreserve.gov/newsevents/example.htm",
                observed_at="2026-07-19T10:00:00+00:00",
            )
        proxy_handler = build_opener.call_args.args[0]
        self.assertEqual(proxy_handler.proxies, {})
        self.assertEqual(document.final_url, response.geturl())
        self.assertEqual(len(opener.requests), 1)
        self.assertIn("text/html", opener.requests[0][0].headers["Accept"])

    def test_github_api_fetcher_requests_raw_media_type(self) -> None:
        url = "https://api.github.com/repos/binance/binance-public-data/readme"
        response = _Response(
            body=b"# Binance Public Data",
            final_url=url,
            content_type="application/vnd.github.raw+json; charset=utf-8",
        )
        opener = _Opener(response)
        with patch(
            "qount.alpha_agents.official_sources.urllib.request.build_opener",
            return_value=opener,
        ):
            document = fetch_official_source_document(
                url,
                observed_at="2026-07-19T10:00:00+00:00",
            )
        self.assertEqual(
            opener.requests[0][0].headers["Accept"],
            "application/vnd.github.raw+json",
        )
        self.assertEqual(document.text_excerpt, "# Binance Public Data")


if __name__ == "__main__":
    unittest.main()
