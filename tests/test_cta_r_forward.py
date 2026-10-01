import datetime as dt
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from qount.research import cta_r_forward as fwd
from qount.research.cta_r_inputs import CTA_R_ETF_SYMBOLS
from qount.research.cta_r_paper import build_cta_r_paper_snapshot

ANCHOR = dt.date(2020, 1, 6)  # Monday


def _dates(n):
    out, day = [], ANCHOR
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += dt.timedelta(days=1)
    return out


def _series(n=420, scale_before=None):
    dates = _dates(n)
    out = {}
    for k, symbol in enumerate(CTA_R_ETF_SYMBOLS):
        price, values = 10.0 + k, {}
        for i, day in enumerate(dates):
            price *= math.exp(0.0004 * (k - 3) + 0.012 * math.sin(i / (7 + k)) + 0.004 * math.cos(i * (k + 1)))
            values[day] = price * (scale_before[1] if scale_before and day < scale_before[0] else 1.0)
        out[symbol] = values
    return dates, out


class CtaRForwardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dates, series = _series()
        self.genesis = self.dates[330]  # 330 % 21 != 0: the sidecar reset day is not a rebalance day
        self.patch = mock.patch.dict(fwd.CONTRACT, {"calendar_anchor_date": ANCHOR.isoformat(),
                                                     "genesis_date": self.genesis})
        self.patch.start()
        self.seed = self.root / "seed.zip"
        fwd.write_seed(self.seed, series, fetched_at=dt.datetime(2021, 8, 1, tzinfo=dt.timezone.utc))

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_genesis_then_bars_match_frozen_sidecar_replay(self):
        panel = fwd.load_panel(self.seed)
        entries, reasons = fwd.advance(panel, [])
        self.assertEqual(reasons, [])
        self.assertEqual(entries[0]["kind"], "genesis")
        self.assertEqual(entries[0]["date"], self.genesis)
        self.assertEqual(len(entries), 1 + len(self.dates) - 331)
        self.assertTrue(any(e.get("rebalanced") for e in entries[1:]))
        ref = build_cta_r_paper_snapshot(self.seed, observed_at=dt.datetime(2021, 8, 1, tzinfo=dt.timezone.utc),
                                         simulation_start_date=self.genesis)
        self.assertAlmostEqual(entries[-1]["equity"], ref["final_equity"], delta=1e-4)
        self.assertLess(entries[-1]["stress_equity"], entries[-1]["equity"])

    def test_ledger_is_immutable_under_later_qfq_rewrite(self):
        path = self.root / "ledger.jsonl"
        panel = fwd.load_panel(self.seed)
        first, _ = fwd.advance(fwd.Panel(panel.dates[:360], {s: v[:360] for s, v in panel.prices.items()},
                                         {s: v[:360] for s, v in panel.returns.items()}, panel.sha256), [])
        fwd.append_ledger(path, first)
        recorded = path.read_text()
        # Vendor re-adjusts history (distribution): everything before day 200 scaled by 0.97.
        _, rewritten = _series(scale_before=(self.dates[200], 0.97))
        fwd.write_seed(self.seed, rewritten, fetched_at=dt.datetime(2021, 9, 1, tzinfo=dt.timezone.utc))
        ledger = fwd.read_ledger(path)
        more, reasons = fwd.advance(fwd.load_panel(self.seed), ledger)
        self.assertEqual(reasons, [])
        self.assertEqual(more[0]["date"], self.dates[360])
        self.assertEqual(more[0]["previous_hash"], ledger[-1]["record_hash"])
        fwd.append_ledger(path, more)
        self.assertTrue(path.read_text().startswith(recorded))
        self.assertEqual(len(fwd.read_ledger(path)), len(first) + len(more))
        self.assertLess(fwd.replay_drift(fwd.load_panel(self.seed), fwd.read_ledger(path)), 1e-9)

    def test_tampered_or_foreign_ledger_is_rejected(self):
        path = self.root / "ledger.jsonl"
        entries, _ = fwd.advance(fwd.load_panel(self.seed), [])
        fwd.append_ledger(path, entries)
        lines = path.read_text().splitlines()
        bad = json.loads(lines[3])
        bad["equity"] += 1.0
        path.write_text("\n".join(lines[:3] + [json.dumps(bad, sort_keys=True)] + lines[4:]) + "\n")
        with self.assertRaises(fwd.CtaRForwardError):
            fwd.read_ledger(path)

    def test_rerun_without_new_dates_appends_nothing(self):
        panel = fwd.load_panel(self.seed)
        entries, _ = fwd.advance(panel, [])
        again, reasons = fwd.advance(panel, entries)
        self.assertEqual((again, reasons), ([], []))
        summary = fwd.forward_summary(entries, drift=fwd.replay_drift(panel, entries))
        self.assertEqual(summary["bars"], len(entries) - 1)
        self.assertFalse(summary["contract"]["orders_authorized"])

    def test_anchor_mismatch_is_hard_error(self):
        with mock.patch.dict(fwd.CONTRACT, {"calendar_anchor_date": "2015-01-05"}):
            with self.assertRaises(fwd.CtaRForwardError):
                fwd.load_panel(self.seed)


class TencentFetchTests(unittest.TestCase):
    def test_chunks_parse_qfq_and_drop_unsettled_day(self):
        calls = []

        def getter(url):
            calls.append(url)
            param = url.split("param=")[1]
            market_code = param.split(",")[0]
            rows = [["2026-09-29", "1", "4.416", "1", "1", "1"], ["2026-09-30", "1", "4.5", "1", "1", "1"]]
            return json.dumps({"data": {market_code: {"qfqday": rows}}}).encode()

        observed = dt.datetime(2026, 9, 30, 6, 0, tzinfo=dt.timezone.utc)  # 14:00 Shanghai, market open
        out = fwd.fetch_tencent_series(getter, observed_at=observed)
        self.assertEqual(set(out), set(CTA_R_ETF_SYMBOLS))
        self.assertEqual(out["510300"], {"2026-09-29": 4.416})
        self.assertTrue(any("sz159915" in u for u in calls))
        self.assertGreater(len(calls), len(CTA_R_ETF_SYMBOLS))  # multi-chunk
        late = fwd.fetch_tencent_series(getter, observed_at=dt.datetime(2026, 9, 30, 10, 0, tzinfo=dt.timezone.utc))
        self.assertIn("2026-09-30", late["510300"])

    def test_unadjusted_only_response_is_rejected(self):
        def getter(url):
            market_code = url.split("param=")[1].split(",")[0]
            return json.dumps({"data": {market_code: {"day": [["2026-09-29", "1", "2", "1", "1", "1"]]}}}).encode()

        with self.assertRaises(fwd.CtaRForwardError):
            fwd.fetch_tencent_series(getter, observed_at=dt.datetime(2026, 9, 30, 10, tzinfo=dt.timezone.utc))


if __name__ == "__main__":
    unittest.main()
