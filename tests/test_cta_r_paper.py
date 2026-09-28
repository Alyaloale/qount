import datetime as dt
import tempfile
from pathlib import Path
import unittest

from qount.research.cta_r_inputs import CTA_R_ETF_SYMBOLS, write_seed_zip
from qount.research.cta_r_paper import build_cta_r_paper_snapshot


class CtaRPaperTests(unittest.TestCase):
    def _seed(self, root: Path) -> Path:
        start = dt.date(2020, 1, 1)
        rows = {}
        for offset in range(330):
            date = start + dt.timedelta(days=offset)
            for symbol in CTA_R_ETF_SYMBOLS:
                rows.setdefault(symbol, []).append((date.isoformat(), 100.0 + offset * (1 + CTA_R_ETF_SYMBOLS.index(symbol) / 10)))
        path = root / "seed.zip"
        return write_seed_zip(path, rows, start_date=start.isoformat(), end_date=(start + dt.timedelta(days=329)).isoformat())

    def test_replay_is_deterministic_and_guarded(self):
        with tempfile.TemporaryDirectory() as directory:
            seed = self._seed(Path(directory))
            observed = dt.datetime(2020, 11, 25, tzinfo=dt.timezone.utc)
            first = build_cta_r_paper_snapshot(seed, observed_at=observed)
            second = build_cta_r_paper_snapshot(seed, observed_at=observed)
            self.assertEqual(first, second)
            self.assertEqual(first["schema"], "cta_r_research_paper_v1")
            self.assertFalse(first["orders_authorized"])
            self.assertTrue(first["points"])

    def test_stale_seed_is_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            seed = self._seed(Path(directory))
            result = build_cta_r_paper_snapshot(
                seed,
                observed_at=dt.datetime(2022, 1, 1, tzinfo=dt.timezone.utc),
            )
            self.assertEqual(result["status"], "insufficient")
            self.assertIn("series_stale", result["reason_codes"])


if __name__ == "__main__":
    unittest.main()
