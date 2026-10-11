"""Source integrity, raw price/adjustment qualification and immutable outputs."""
import csv
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from qount.research_data.equity_archive import FIELDS, audit_archive, members, profile_member, sha256


def csv_stream(rows):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(FIELDS)
    writer.writerows(rows)
    stream.seek(0)
    return stream


def row(day='20200102', factor=2., anchor=.5):
    return ['000001.SZ', day, 10, 12, 9, 11, 10, 1, 10, 100, 200,
            factor, 11 * factor * anchor, 10 * factor * anchor, 12 * factor * anchor, 9 * factor * anchor]


class EquityArchiveTests(unittest.TestCase):
    def test_adjustment_anchor_and_dates_without_return_labels(self):
        profile, dates = profile_member(csv_stream([row(), row('20200103', factor=3.)]), '000001.SZ')
        self.assertEqual(profile['rows'], 2)
        self.assertEqual(profile['complete_adjustment_rows'], 2)
        self.assertEqual(profile['observed_factor_changes'], 1)
        self.assertTrue(profile['adjustment_anchor_consistent'])
        self.assertEqual(profile['adjustment_anchor_min'], .5)
        self.assertEqual(profile['issues'], {})
        self.assertEqual(dates['20200103'], 1)
        self.assertNotIn('returns', profile)

    def test_missing_adjustments_are_never_filled(self):
        empty = row(); empty[11:] = [''] * 5
        partial = row('20200103'); partial[12] = ''
        profile, _ = profile_member(csv_stream([empty, partial]), '000001.SZ')
        self.assertEqual(profile['complete_adjustment_rows'], 0)
        self.assertEqual(profile['partial_adjustment_rows'], 1)
        self.assertEqual(profile['missing_numeric_fields']['adj_close'], 2)
        self.assertIsNone(profile['adjustment_anchor_min'])

    def test_symbol_dates_and_nonfinite_numeric_are_reported(self):
        bad = row('20200230'); bad[0] = '000002.SZ'; bad[2] = 'nan'
        profile, _ = profile_member(csv_stream([bad, row(), row()]), '000001.SZ')
        self.assertEqual(profile['issues']['invalid_date'], 1)
        self.assertEqual(profile['issues']['symbol_mismatch'], 1)
        self.assertEqual(profile['issues']['invalid_numeric_open'], 1)
        self.assertEqual(profile['duplicate_dates'], 1)
        self.assertEqual(profile['rows'], 3)

    def test_adjustment_mixed_ohlc_and_changing_anchor_detected(self):
        bad = row(); bad[13] *= 2
        profile, _ = profile_member(csv_stream([bad, row('20200103', anchor=.6)]), '000001.SZ')
        self.assertEqual(profile['adjusted_ohlc_ratio_mismatches'], 1)
        self.assertFalse(profile['adjustment_anchor_consistent'])

    def test_zero_activity_and_price_envelope_remain_observed(self):
        bad = row(); bad[9] = 0; bad[4] = 13
        profile, _ = profile_member(csv_stream([bad]), '000001.SZ')
        self.assertEqual(profile['zero_activity_rows'], 1)
        self.assertEqual(profile['issues']['invalid_ohlc_envelope'], 1)

    def test_wrong_schema_and_empty_csv(self):
        with self.assertRaisesRegex(ValueError, 'schema_mismatch'):
            profile_member(io.StringIO('date,close\n20200102,10'), '000001.SZ')
        profile, _ = profile_member(csv_stream([]), '000001.SZ')
        self.assertEqual(profile['issues']['empty_file'], 1)

    def test_zip_paths_and_non_csv_members_are_rejected(self):
        for name in ('../secret.csv', 'stocks/.env', 'stocks/000001_SZ.py', 'stocks/AAPL.csv'):
            memory = io.BytesIO()
            with zipfile.ZipFile(memory, 'w') as archive:
                archive.writestr(name, 'unused')
            with zipfile.ZipFile(memory) as archive:
                with self.assertRaisesRegex(ValueError, 'unexpected_member'):
                    members(archive)

    def test_wsl_external_storage_required(self):
        with self.assertRaisesRegex(ValueError, 'wsl_mounted_e_required'):
            audit_archive(archive_path=Path('/tmp/stocks.zip'), expected_sha256='0' * 64, out=Path('/tmp/audit'))

    def test_full_audit_checksum_binding_and_immutable_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root / 'raw.zip'; out = root / 'audit'
            with zipfile.ZipFile(source, 'w') as archive:
                archive.writestr('stocks/000001_SZ.csv', csv_stream([row()]).getvalue())
            with patch('qount.research_data.equity_archive.sys.platform', 'linux'), \
                 patch('qount.research_data.equity_archive.os.path.ismount', return_value=True), \
                 patch('qount.research_data.equity_archive.STORAGE', root), \
                 patch('pathlib.Path.is_relative_to', return_value=True):
                with self.assertRaisesRegex(ValueError, 'source_hash_mismatch'):
                    audit_archive(archive_path=source, expected_sha256='0' * 64, out=out, workers=1)
                self.assertFalse(out.exists())
                result = audit_archive(archive_path=source, expected_sha256=sha256(source), out=out, workers=1)
                self.assertEqual(result['rows'], 1)
                self.assertFalse(result['returns_produced'])
                self.assertFalse(result['historical_universe_verified'])
                self.assertTrue((out / 'manifest.json').is_file())
                with self.assertRaisesRegex(ValueError, 'immutable_output_exists'):
                    audit_archive(archive_path=source, expected_sha256=sha256(source), out=out, workers=1)


if __name__ == '__main__':
    unittest.main()
