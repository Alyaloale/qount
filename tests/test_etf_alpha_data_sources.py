from __future__ import annotations

import html
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from qount.research.etf_alpha.data_sources import (compare_sessions, equity_calendar, event,
    parse_invesco, parse_ishares, parse_ssga, reconcile_events)
from qount.research.etf_alpha.data_supplement import fee_periods, public_url, source_plan
from qount.research.etf_alpha.data_supplement import import_cached_source, Source
from qount.research.etf_alpha.artifacts import sha256


class IssuerParserTests(unittest.TestCase):
    def test_embedded_full_history_is_used_instead_of_visible_ten_rows(self):
        columns = {"exDate": [20261001, 20090102], "recordDate": [20261001, 20090105],
                   "payableDate": [20261006, 20090109], "totalDistribution": [".3", ".1"]}
        props = {"distributionTableData": [{"name": key, "value": value} for key, value in columns.items()]}
        raw = ('<h1>IEF</h1><table><tr><td>2026-10-01</td></tr></table>'
               '<walrus-render-on-client componentprops="' + html.escape(json.dumps(props), quote=True) + '">').encode()
        rows = parse_ishares(raw, "IEF")
        self.assertEqual([row["ex_date"] for row in rows], ["2009-01-02", "2026-10-01"])
        self.assertEqual(rows[0]["cash_per_share"], .1)
        self.assertFalse(rows[0]["historical_asof_verified"])
        self.assertIsNone(rows[0]["available_at_historical_time"])
        columns["recordDate"].pop()
        props["distributionTableData"] = [{"name": key, "value": value} for key, value in columns.items()]
        with self.assertRaises(ValueError):
            parse_ishares(('<h1>IEF</h1><x componentprops="' + html.escape(json.dumps(props), quote=True) + '">').encode(), "IEF")

    def test_invesco_empty_ticker_response_wrong_identity_and_duplicate_fail(self):
        with self.assertRaises(ValueError):
            parse_invesco(b"{}", "QQQ")
        value = {"cusip": "46090E103", "currencyCode": "USD", "distributions": [
            {"exDate": "2026-09-21", "recordDate": "2026-09-21", "payDate": "2026-10-08",
             "distributionAmountPerUnit": .75143}]}
        row = parse_invesco(json.dumps(value).encode(), "QQQ")[0]
        self.assertEqual(row["pay_date"], "2026-10-08")
        with self.assertRaises(ValueError):
            parse_invesco(json.dumps(value).encode(), "DBC")
        value["distributions"] *= 2
        with self.assertRaises(ValueError):
            parse_invesco(json.dumps(value).encode(), "QQQ")

    def test_capital_gains_are_cash_and_sparse_empty_cells_do_not_shift_columns(self):
        ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        strings = ["TICKER", "EX-DATE", "RECORD DATE", "PAYABLE DATE", "SPY", "BIL", "78462F103", "78468R663",
                   "12/29/2009", "12/31/2009", "01/07/2010"]
        shared = '<sst ' + ns + '>' + ''.join('<si><t>' + text + '</t></si>' for text in strings) + '</sst>'
        def cell(ref, value, string=True):
            return f'<c r="{ref}"' + (' t="s"' if string else '') + f'><v>{value}</v></c>'
        header = ''.join(cell(col + "1", i) for col, i in (("B", 0), ("D", 1), ("E", 2), ("F", 3)))
        rows = []
        for n, s, c in ((2, 4, 6), (3, 5, 7)):
            row = ''.join(cell(col + str(n), val) for col, val in (("B", s), ("C", c), ("D", 8), ("E", 9), ("F", 10)))
            rows.append(f'<row>{row}{cell("H" + str(n), ".003815", False)}</row>')
        sheet = '<worksheet ' + ns + '><sheetData><row>' + header + '</row>' + ''.join(rows) + '</sheetData></worksheet>'
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w") as archive:
            archive.writestr("xl/sharedStrings.xml", shared)
            archive.writestr("xl/worksheets/sheet1.xml", sheet)
        events = parse_ssga(content.getvalue())
        self.assertEqual(len(events), 2)
        self.assertTrue(all(row["cash_per_share"] == .003815 for row in events))
        self.assertEqual(events[0]["pay_date"], "2010-01-07")
        bad = ('<row>' + cell('B4', 5) + cell('C4', 7) + cell('D4', '20080303', False)
               + cell('E4', '20080205', False) + cell('F4', '20080211', False)
               + cell('G4', '.086739', False) + '</row>')
        second = io.BytesIO()
        with zipfile.ZipFile(second, "w") as archive:
            archive.writestr("xl/sharedStrings.xml", shared)
            archive.writestr("xl/worksheets/sheet1.xml", sheet.replace('</sheetData>', bad + '</sheetData>'))
        with self.assertRaises(ValueError):
            parse_ssga(second.getvalue())
        scoped = parse_ssga(second.getvalue(), start='2009-01-02', end='2026-10-01')
        self.assertEqual(len(scoped), 2)

    def test_invalid_cash_and_payment_order_are_rejected(self):
        for cash in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                event("SPY", "2026-01-02", "2026-01-02", "2026-01-03", cash)
        with self.assertRaises(ValueError):
            event("SPY", "2026-01-02", "2026-01-02", "2026-01-01", .5)


class CalendarTests(unittest.TestCase):
    def test_exception_closures_juneteenth_start_and_saturday_new_year(self):
        days = {row["date"]: row for row in equity_calendar("2009-01-02", "2026-10-01")}
        for day in ("2012-10-29", "2012-10-30", "2018-12-05", "2025-01-09", "2022-06-20"):
            self.assertFalse(days[day]["is_session"])
        for day in ("2021-12-31", "2021-06-18", "2012-10-31", "2026-07-02"):
            self.assertTrue(days[day]["is_session"])
        self.assertFalse(days["2026-07-03"]["is_session"])
        self.assertFalse(days["2015-04-03"]["is_session"])

    def test_missing_extra_and_duplicate_sessions_are_detected(self):
        days = equity_calendar("2025-01-06", "2025-01-10")
        self.assertEqual(compare_sessions(days, ("2025-01-06", "2025-01-07", "2025-01-08", "2025-01-10"))["status"], "pass")
        report = compare_sessions(days, ("2025-01-06", "2025-01-06", "2025-01-09", "2025-01-10"))
        self.assertEqual(report["missing_sessions"], ["2025-01-07", "2025-01-08"])
        self.assertEqual(report["unexpected_sessions"], ["2025-01-09"])
        self.assertEqual(report["duplicate_count"], 1)
        self.assertEqual(report["status"], "fail")

    def test_unreviewed_calendar_range_is_rejected(self):
        for start, end in (("2008-01-01", "2009-01-01"), ("2026-01-01", "2027-01-01")):
            with self.assertRaises(ValueError):
                equity_calendar(start, end)


class ClassificationTests(unittest.TestCase):
    def test_cached_source_keeps_actual_observation_time_and_rejects_changed_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / 'cache'
            cache.mkdir()
            path = cache / 'raw.html'
            path.write_text('issuer vintage')
            source = Source('fixture', 'distributions', 'https://www.ishares.com/us/fixture')
            prior = {'url': source.url, 'final_url': source.url, 'fetch_status': 'success',
                     'file': path.name, 'sha256': sha256(path), 'observed_at': '2026-10-02T12:00:00Z'}
            receipt = import_cached_source(source, root / 'new', cache, prior, 'manifest_fixture')
            self.assertEqual(receipt['observed_at'], prior['observed_at'])
            self.assertFalse(receipt['historical_asof_verified'])
            self.assertEqual(receipt['sha256'], prior['sha256'])
            path.write_text('modified')
            with self.assertRaises(ValueError):
                import_cached_source(source, root / 'second', cache, prior, 'manifest_fixture')

    def test_zero_events_rounding_and_unresolved_conflicts_remain_distinct(self):
        official = [{"symbol": "BIL", "ex_date": day, "cash_per_share": cash} for day, cash in
                    (("2009-01-02", 0), ("2009-02-02", .0081), ("2009-03-02", .5))]
        legacy = {("BIL", "2009-02-02"): .008, ("BIL", "2009-03-02"): .25, ("BIL", "2009-04-01"): .001}
        summary, rows = reconcile_events(official, legacy)
        self.assertEqual({row["status"] for row in rows}, {
            "issuer_only_zero", "rounding_compatible", "amount_mismatch_requires_review", "legacy_only"})
        self.assertEqual(summary["BIL"]["issuer_positive_rows"], 2)

    def test_public_urls_forbid_private_hosts_credentials_and_redirect_targets(self):
        for url in ("http://www.sec.gov/a", "https://private.example/a", "https://user:secret@www.sec.gov/a",
                    "https://www.sec.gov/a?token=secret", "https://www.sec.gov:8443/a"):
            with self.assertRaises(ValueError):
                public_url(url)
        urls = [source.url for source in source_plan()]
        self.assertEqual(len(urls), len(set(urls)))
        for url in urls:
            self.assertEqual(public_url(url), url)

    def test_missing_fee_evidence_is_null_not_zero_and_does_not_extend_previous_rate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipts = {source.source_id: {"fetch_status": "failed"} for source in source_plan()}
            p = root / "2025.html"
            p.write_text("Section 31 May 14, 2025 $0.00")
            receipts["sec_2025-2"] = {"fetch_status": "success", "file": p.name, "sha256": "fixture"}
            rows = fee_periods(root, receipts, "2025-05-13", "2026-10-01")
            sec = [row for row in rows if row["fee"] == "SEC_Section31"]
            self.assertEqual(sec[0]["end_exclusive"], "2025-05-14")
            self.assertIsNone(sec[0]["rate"])
            self.assertEqual(sec[1]["rate"], 0)
            self.assertEqual(sec[1]["end_exclusive"], "2026-04-04")
            self.assertIsNone(sec[2]["rate"])
            self.assertFalse(sec[1]["broker_pass_through_verified"])
            self.assertFalse(sec[1]["historical_asof_verified"])
            taf = [row for row in rows if row["fee"] == "FINRA_equity_TAF"]
            self.assertEqual(taf[-1]["start_inclusive"], "2026-10-01")
            self.assertIsNone(taf[-1]["rate"])


if __name__ == "__main__":
    unittest.main()
