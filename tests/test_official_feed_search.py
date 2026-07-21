from __future__ import annotations

import hashlib
import json
import unittest

from qount.intelligence import OfficialFeedSearchProvider
from qount.intelligence import SearchProviderError


SEARCHED_AT = "2026-07-21T15:00:00+00:00"


class _Response:
    def __init__(
        self,
        *,
        body: bytes,
        url: str,
        content_type: str,
        status: int = 200,
    ) -> None:
        self.body = body
        self.url = url
        self.headers = {"Content-Type": content_type}
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def read(self, limit: int) -> bytes:
        return self.body[:limit]

    def geturl(self) -> str:
        return self.url


class _Opener:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        return self.response


class OfficialFeedSearchProviderTest(unittest.TestCase):
    def test_binance_catalog_returns_bounded_detail_api_urls(self) -> None:
        endpoint = (
            "https://www.binance.com/bapi/composite/v1/public/cms/article/"
            "catalog/list/query?catalogId=48&pageNo=1&pageSize=20"
        )
        body = json.dumps(
            {
                "success": True,
                "code": "000000",
                "data": {
                    "articles": [
                        {"title": "  First   notice ", "code": "a" * 32},
                        {"title": "Second notice", "code": "b" * 32},
                        {"title": "Rejected code", "code": "not-a-code"},
                    ]
                },
            },
            separators=(",", ":"),
        ).encode()
        opener = _Opener(
            _Response(body=body, url=endpoint, content_type="application/json;charset=UTF-8")
        )
        provider = OfficialFeedSearchProvider(count=2, opener=opener)

        result = provider.search(
            "site:binance.com latest announcement",
            searched_at=SEARCHED_AT,
        )

        self.assertEqual(result.evidence.provider, "official_feed_discovery")
        self.assertEqual(result.evidence.result_count, 2)
        self.assertEqual(result.titles, ("First notice", "Second notice"))
        self.assertEqual(result.evidence.response_hash, hashlib.sha256(body).hexdigest())
        self.assertEqual(
            result.evidence.urls[0],
            "https://www.binance.com/bapi/composite/v1/public/cms/article/"
            f"detail/query?articleCode={'a' * 32}",
        )
        request, timeout = opener.calls[0]
        self.assertEqual(request.full_url, endpoint)
        self.assertEqual(timeout, 20)
        self.assertNotIn("X-subscription-token", request.headers)

    def test_fed_and_sec_rss_return_only_matching_official_domains(self) -> None:
        fixtures = (
            (
                "site:federalreserve.gov latest monetary policy",
                "https://www.federalreserve.gov/feeds/press_all.xml",
                "federalreserve.gov",
            ),
            (
                "site:sec.gov latest digital asset filing",
                "https://www.sec.gov/news/pressreleases.rss",
                "sec.gov",
            ),
        )
        for query, endpoint, domain in fixtures:
            body = (
                "<?xml version='1.0'?><rss><channel>"
                f"<item><title>  Current   release </title><link>https://www.{domain}/news/current</link></item>"
                "<item><title>Injected</title><link>https://example.com/not-official</link></item>"
                f"<item><title>Second</title><link>https://www.{domain}/news/second</link></item>"
                "</channel></rss>"
            ).encode()
            opener = _Opener(
                _Response(body=body, url=endpoint, content_type="application/rss+xml")
            )
            provider = OfficialFeedSearchProvider(count=3, opener=opener)

            with self.subTest(domain=domain):
                result = provider.search(query, searched_at=SEARCHED_AT)

            self.assertEqual(result.evidence.result_count, 2)
            self.assertEqual(result.titles, ("Current release", "Second"))
            self.assertTrue(all(domain in url for url in result.evidence.urls))

    def test_unknown_query_redirect_and_xml_entity_fail_closed(self) -> None:
        endpoint = "https://www.federalreserve.gov/feeds/press_all.xml"
        with self.assertRaisesRegex(SearchProviderError, "query_not_supported"):
            OfficialFeedSearchProvider(opener=_Opener(
                _Response(body=b"", url=endpoint, content_type="text/xml")
            )).search("general web search", searched_at=SEARCHED_AT)

        redirected = OfficialFeedSearchProvider(
            opener=_Opener(
                _Response(
                    body=b"<rss/>",
                    url="https://example.com/redirected.xml",
                    content_type="text/xml",
                )
            )
        )
        with self.assertRaisesRegex(SearchProviderError, "route_invalid"):
            redirected.search(
                "site:federalreserve.gov latest policy",
                searched_at=SEARCHED_AT,
            )

        entity = OfficialFeedSearchProvider(
            opener=_Opener(
                _Response(
                    body=b"<!DOCTYPE rss [<!ENTITY x 'bad'>]><rss/>",
                    url=endpoint,
                    content_type="text/xml",
                )
            )
        )
        with self.assertRaisesRegex(SearchProviderError, "declaration_forbidden"):
            entity.search(
                "site:federalreserve.gov latest policy",
                searched_at=SEARCHED_AT,
            )


if __name__ == "__main__":
    unittest.main()
