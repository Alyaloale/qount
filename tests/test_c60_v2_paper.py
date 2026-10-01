import datetime as dt
import json
import math
import random
import tempfile
import unittest
from pathlib import Path

from qount.dual_engine.contracts import C60_SYMBOLS
from qount.research import c60_v2_paper as paper

LAST_DAY = dt.date(2026, 10, 10)


def _series(days: int = 480, seed: int = 11) -> dict[str, dict[str, float]]:
    rng = random.Random(seed)
    start = LAST_DAY - dt.timedelta(days=days - 1)
    out = {}
    for offset, symbol in enumerate(C60_SYMBOLS):
        price, drift, values = 50.0 + offset, (offset - 4) * 0.001, {}
        for day in range(days):
            price *= math.exp(drift + rng.gauss(0.0, 0.03))
            values[(start + dt.timedelta(days=day)).isoformat()] = price
        out[symbol] = values
    return out


OBSERVED = dt.datetime.combine(LAST_DAY + dt.timedelta(days=1), dt.time(1), tzinfo=dt.timezone.utc)


class C60V2PaperTests(unittest.TestCase):
    def setUp(self):
        self.series = _series()
        self.snapshot = paper.build_snapshot(self.series, observed_at=OBSERVED)

    def test_guards_and_contract(self):
        s = self.snapshot
        self.assertEqual(s["status"], "valid")
        self.assertTrue(s["research_only"])
        self.assertFalse(s["orders_authorized"])
        self.assertFalse(s["promotion_evidence"])
        self.assertFalse(s["contract"]["replaces_frozen_v1"])
        self.assertEqual(s["contract_hash"], paper.CONTRACT_HASH)
        self.assertEqual(s["points"][0]["date"], "2026-01-01")
        self.assertEqual(s["points"][0]["equity"], 10_000.0)

    def test_forward_segment_starts_after_forward_date(self):
        forward = self.snapshot["forward"]
        after = [p for p in self.snapshot["points"] if p["date"] > "2026-09-30"]
        self.assertEqual(forward["bars"], len(after))
        base = [p for p in self.snapshot["points"] if p["date"] <= "2026-09-30"][-1]
        self.assertAlmostEqual(forward["return"], after[-1]["equity"] / base["equity"] - 1.0, places=6)

    def test_candidates_only_change_at_month_end(self):
        holdings_by_month = {}
        for rebalance in self.snapshot["rebalances"]:
            names = frozenset(rebalance["weights"])
            month = rebalance["date"][:7]
            if not rebalance["date"].endswith(("-28", "-29", "-30", "-31")):
                holdings_by_month.setdefault(month, set()).update(names)
        for month, names in holdings_by_month.items():
            self.assertLessEqual(len(names), 2, month)

    def test_ledger_roundtrip_and_replay_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "ledger.jsonl"
            appended = paper.append_ledger(ledger_path, self.snapshot, [])
            self.assertEqual(appended, 1 + self.snapshot["forward"]["bars"])
            ledger = paper.read_ledger(ledger_path)
            again = paper.build_snapshot(self.series, observed_at=OBSERVED, ledger=ledger)
            self.assertEqual(again["status"], "valid")
            self.assertEqual(paper.append_ledger(ledger_path, again, ledger), 0)

            tampered = [dict(e) for e in ledger]
            tampered[0]["equity"] *= 1.01
            bad = paper.build_snapshot(self.series, observed_at=OBSERVED, ledger=tampered)
            self.assertEqual(bad["status"], "insufficient")
            self.assertTrue(bad["reason_codes"][0].startswith("forward_replay_mismatch"))

            lines = ledger_path.read_text().splitlines()
            entry = json.loads(lines[0])
            entry["equity"] += 1.0
            ledger_path.write_text("\n".join([json.dumps(entry)] + lines[1:]) + "\n")
            with self.assertRaises(paper.C60V2PaperError):
                paper.read_ledger(ledger_path)

    def test_stale_series_is_insufficient_and_not_ledgered(self):
        late = OBSERVED + dt.timedelta(days=5)
        stale = paper.build_snapshot(self.series, observed_at=late)
        self.assertIn("series_stale", stale["reason_codes"])
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(paper.append_ledger(Path(tmp) / "l.jsonl", stale, []), 0)

    def test_write_snapshot_is_atomic_and_guarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = paper.write_snapshot(self.snapshot, Path(tmp) / "c60_v2_paper.json")
            self.assertEqual(json.loads(path.read_text())["schema"], paper.SCHEMA)
            self.assertEqual(oct(path.stat().st_mode & 0o777), "0o644")
            with self.assertRaises(paper.C60V2PaperError):
                paper.write_snapshot(dict(self.snapshot, orders_authorized=True), path)


if __name__ == "__main__":
    unittest.main()
