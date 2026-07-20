from __future__ import annotations

import json
import unittest

from qount.mini_trend.macro_h41 import parse_h41_html
from qount.mini_trend.macro_h41 import parse_h41_text
from qount.mini_trend.macro_h41 import parse_release_dates
from qount.mini_trend.macro_h41 import report_html_link
from qount.mini_trend.macro_h41 import h41_dataset_data_hash


class MiniTrendMacroH41Test(unittest.TestCase):
    def test_legacy_text_extracts_observation_and_total_assets(self) -> None:
        raw = b"""
5. Consolidated Statement of Condition of All Federal Reserve Banks
Millions of dollars
Assets, liabilities, and capital   Eliminations Wednesday Change since
from Jan 6, 2021 Wednesday Wednesday
Assets
Other assets 34,143
Total assets (0) 7,334,809 - 28,542 +3,185,265
"""
        result = parse_h41_text(raw)
        self.assertEqual(result["observation_date"], "2021-01-06")
        self.assertEqual(result["total_assets_usd_millions"], 7_334_809)
        self.assertEqual(result["format"], "legacy_txt")

    def test_modern_html_extracts_consolidated_table(self) -> None:
        raw = b"""
<table>
<tr><th>Assets, liabilities, and capital</th><th>Eliminations</th>
<th>Wednesday<span>Jan 1, 2025</span></th><th>Change since</th></tr>
<tr><th>Wednesday</th><th>Wednesday</th></tr>
<tr><th>Dec 25, 2024</th><th>Jan 3, 2024</th></tr>
<tr><td>Other assets</td><td></td><td>34,921</td><td>- 2,667</td></tr>
<tr><td>Total assets</td><td>(0)</td><td>6,852,491</td><td>- 33,472</td></tr>
</table>
"""
        result = parse_h41_html(raw)
        self.assertEqual(result["observation_date"], "2025-01-01")
        self.assertEqual(result["total_assets_usd_millions"], 6_852_491)
        self.assertEqual(result["format"], "modern_html")

    def test_release_index_uses_official_nested_month_dates(self) -> None:
        raw = json.dumps(
            [
                {
                    "yearValue": "2025",
                    "Months": [
                        {
                            "MonthName": "January",
                            "MonthValue": "202501",
                            "Dates": ["20250102", "20250109"],
                        }
                    ],
                }
            ]
        ).encode()
        self.assertEqual(parse_release_dates(raw), ["2025-01-02", "2025-01-09"])

    def test_transition_index_finds_linked_html_report(self) -> None:
        raw = b"""
<a href="../h41_technical_qa.htm">Technical Q&amp;A</a>
<a href="h41.htm">HTML</a><a href="h41.pdf">PDF</a>
"""
        self.assertEqual(report_html_link(raw), "h41.htm")

    def test_dataset_hash_ignores_cache_paths_and_hit_state(self) -> None:
        row = {
            "release_date": "2025-01-02",
            "observation_date": "2025-01-01",
            "total_assets_usd_millions": 6_852_491,
            "format": "modern_html",
            "source_layout": "inline_html",
            "observation_to_release_lag_days": 1,
            "sources": [
                {
                    "url": "https://example.test/release",
                    "path": "/first/cache/page.html",
                    "bytes": 100,
                    "sha256": "a" * 64,
                    "cache_hit": False,
                }
            ],
        }
        rerun = {**row, "sources": [{**row["sources"][0], "path": "/other/page.html", "cache_hit": True}]}
        kwargs = {
            "contract_hash": "contract",
            "release_index_sha256": "b" * 64,
            "features": [{"decision_date": "2025-01-03", "value": 1.0}],
        }
        self.assertEqual(
            h41_dataset_data_hash(rows=[row], **kwargs),
            h41_dataset_data_hash(rows=[rerun], **kwargs),
        )


if __name__ == "__main__":
    unittest.main()
