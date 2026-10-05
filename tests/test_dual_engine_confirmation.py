import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from qount.research.dual_engine_confirmation import append_equity, extend_rate_snapshot, targets_for_version
from qount.research.dual_engine_optimization import EquityPanel, write_json, file_hash


class ConfirmationTests(unittest.TestCase):
    def version_fixture(self, root, source):
        contract = root / "contract.json"
        write_json(contract, {"g20": {}})
        return {"strategy_contract_path": str(contract), "strategy_contract_sha256": "contract",
                "source_sha256": {source: "locked"}, "artifact_root": str(root),
                "study_id": "dual_engine_nextgen_20261004", "line": "g20", "rule": "g20"}

    def test_metadata_module_update_does_not_invalidate_unchanged_strategy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            v = self.version_fixture(root, "src/qount/research/dual_engine_registry.py")
            def digest(path):
                if str(path) == v["strategy_contract_path"]:
                    return "contract"
                return "locked" if str(path).startswith(str(root / "source")) else "new_metadata"
            with patch("qount.research.dual_engine_confirmation.old.file_hash", side_effect=digest), patch(
                    "qount.research.dual_engine_confirmation.new.equity_targets", return_value=({}, [])):
                self.assertEqual(targets_for_version(v, None, None, {}, {}, {}, {}), ({}, 1.))

    def test_changed_signal_module_or_tampered_frozen_copy_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            v = self.version_fixture(root, "src/qount/research/dual_engine_nextgen.py")
            for mode in ("current", "frozen"):
                def digest(path):
                    if str(path) == v["strategy_contract_path"]:
                        return "contract"
                    frozen = str(path).startswith(str(root / "source"))
                    return "wrong" if (frozen and mode == "frozen") or (not frozen and mode == "current") else "locked"
                with self.subTest(mode=mode), patch("qount.research.dual_engine_confirmation.old.file_hash", side_effect=digest):
                    with self.assertRaises(ValueError):
                        targets_for_version(v, None, None, {}, {}, {}, {})

    def fixture(self, root):
        first = dt.date(2026, 7, 1)
        dates = tuple((first + dt.timedelta(days=i)).isoformat() for i in range(30))
        original = tuple(100. + i for i in range(30))
        panel = EquityPanel(dates, {s: original for s in ("SPY", "BIL")},
                            {s: original for s in ("SPY", "BIL")}, {s: original for s in ("SPY", "BIL")})
        days = [first + dt.timedelta(days=i) for i in range(92)]
        for symbol in panel.closes:
            raw = [2. * (100 + i) for i in range(92)]
            adjusted = [3. * (100 + i) for i in range(92)]
            value = {"chart": {"result": [{"meta": {"symbol": symbol},
                "timestamp": [int(dt.datetime.combine(d, dt.time(20), dt.timezone.utc).timestamp()) for d in days],
                "indicators": {"quote": [{"close": raw, "open": raw}], "adjclose": [{"adjclose": adjusted}]}}]}}
            write_json(root / f"{symbol}.source.json", value)
        self.manifest(root)
        return panel

    def manifest(self, root):
        write_json(root / "manifest.json", {"files": {p.name: file_hash(p) for p in root.glob("*.source.json")}})

    def test_bridge_preserves_every_original_price_and_adjusts_units(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            panel = self.fixture(root)
            extended, errors = append_equity(panel, root)
            self.assertEqual(extended.dates[:30], panel.dates)
            for name in ("closes", "total_closes", "total_opens"):
                for s in panel.closes:
                    self.assertEqual(getattr(extended, name)[s][:30], getattr(panel, name)[s])
                    self.assertAlmostEqual(getattr(extended, name)[s][-1], 191.)
            self.assertLess(max(errors.values()), 1e-14)

    def test_overlap_revision_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            panel = self.fixture(root)
            p = root / "SPY.source.json"
            value = json.loads(p.read_text())
            value["chart"]["result"][0]["indicators"]["quote"][0]["close"][5] *= 1.2
            write_json(p, value)
            self.manifest(root)
            with self.assertRaisesRegex(ValueError, "overlap_revision"):
                append_equity(panel, root)

    def test_late_gap_rejected_without_forward_fill(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            panel = self.fixture(root)
            p = root / "BIL.source.json"
            value = json.loads(p.read_text())
            value["chart"]["result"][0]["indicators"]["quote"][0]["open"][40] = None
            write_json(p, value)
            self.manifest(root)
            with self.assertRaisesRegex(ValueError, "invalid_row"):
                append_equity(panel, root)

    def test_rate_extension_preserves_frozen_vintage_on_old_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            prior, fresh, out = (base / s for s in ("prior", "fresh", "out"))
            prior.mkdir()
            fresh.mkdir()
            for series in ("DFII10", "T10YIE"):
                (prior / f"{series}.csv").write_text("DATE,value\n2026-07-30,1.0\n")
                (fresh / f"{series}.csv").write_text("DATE,value\n2026-07-30,99.0\n2026-09-30,2.0\n")
            for root in (prior, fresh):
                write_json(root / "manifest.json", {"files": {p.name: file_hash(p) for p in root.glob("*.csv")}})
            with patch("qount.research.dual_engine_confirmation.ex.require_storage"):
                result = extend_rate_snapshot(prior_root=prior, fresh_root=fresh, out=out)
            self.assertEqual(result["preserved_through"], {"DFII10": "2026-07-30", "T10YIE": "2026-07-30"})
            self.assertIn("2026-07-30,1.0", (out / "DFII10.csv").read_text())
            self.assertNotIn("99.0", (out / "DFII10.csv").read_text())
            with patch("qount.research.dual_engine_confirmation.ex.require_storage"):
                with self.assertRaisesRegex(ValueError, "snapshot_exists"):
                    extend_rate_snapshot(prior_root=prior, fresh_root=fresh, out=out)
