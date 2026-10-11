"""Causal windows, immutable sources and one fixed price/activity hypothesis."""
import csv
import datetime as dt
import io
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qount.research.ashare_selection import (
    fixed_features, fixed_price_strata, information_day, official_calendar,
    prefix_locator, qualify, source_gates, verify_manifest, window_profile,
)
from qount.research_data.equity_archive import FIELDS, sha256


def sessions(n=12):
    start = dt.date(2021, 1, 4)
    return tuple((start + dt.timedelta(days=i)).strftime('%Y%m%d')
                 for i in range(n * 2) if (start + dt.timedelta(days=i)).weekday() < 5)[:n]


def stream(days, missing_adjustments=(), zero_activity=(), missing_volume=(), symbol='000001.SZ'):
    value = io.StringIO(newline='')
    writer = csv.writer(value); writer.writerow(FIELDS)
    for day in days:
        row = [symbol, day, 10, 12, 9, 11, 10, 1, 10,
               '' if day in missing_volume else 100, 0 if day in zero_activity else 200, 2, 11, 10, 12, 9]
        if day in missing_adjustments:
            row[11:] = [''] * 5
        writer.writerow(row)
    value.seek(0)
    return value


def calendar_record(year, closures):
    return {'year': year, 'status': 'verified',
            'sources': [{'id': 'synthetic_fixture_' + str(year),
                         'url': 'https://www.sse.com.cn/fixture-not-a-real-source',
                         'published_date': f'{year-1}-12-25', 'kind': 'annual'}],
            'closures': [{'start': a, 'end': b, 'source_ids': ['synthetic_fixture_' + str(year)],
                          'reason': 'synthetic unit-test fixture'} for a, b in closures]}


class AshareSelectionTests(unittest.TestCase):
    def test_official_calendar_uses_notices_not_adjusted_work_weekends(self):
        review = {'years': [calendar_record(2021, [('2021-01-01', '2021-01-03')])]}
        days, _ = official_calendar(review, '2021-01-01', '2021-01-10')
        self.assertEqual(days, ('20210104', '20210105', '20210106', '20210107', '20210108'))

    def test_missing_calendar_year_or_unverified_year_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'year_not_verified'):
            official_calendar({'years': []}, '2021-01-01', '2021-01-03')
        record = calendar_record(2021, [('2021-01-01', '2021-01-01')]); record['status'] = 'pending'
        with self.assertRaisesRegex(ValueError, 'year_not_verified'):
            official_calendar({'years': [record]}, '2021-01-01', '2021-01-03')

    def test_calendar_rejects_non_primary_or_unbound_closure_source(self):
        record = calendar_record(2021, [('2021-01-01', '2021-01-01')])
        record['sources'][0]['url'] = 'https://example.com/calendar'
        with self.assertRaisesRegex(ValueError, 'non_exchange'):
            official_calendar({'years': [record]}, '2021-01-01', '2021-01-03')
        record = calendar_record(2021, [('2021-01-01', '2021-01-01')])
        record['closures'][0]['source_ids'] = ['unknown']
        with self.assertRaisesRegex(ValueError, 'closure_source'):
            official_calendar({'years': [record]}, '2021-01-01', '2021-01-03')

    def test_calendar_special_closures_must_be_explicit(self):
        for year, start, end, expected in [(2015, '2015-09-01', '2015-09-07', '2015_special'),
                                           (2020, '2020-01-27', '2020-02-04', '2020_extension')]:
            record = calendar_record(year, [(f'{year}-01-01', f'{year}-01-01')])
            with self.assertRaisesRegex(ValueError, expected):
                official_calendar({'years': [record]}, start, end)

    def test_SSE_verification_does_not_certify_SZSE(self):
        record = calendar_record(2021, [('2021-01-01', '2021-01-01')])
        record.update(status='pending', sse_status='verified', szse_status='pending')
        self.assertEqual(official_calendar({'years': [record]}, '2021-01-01', '2021-01-04')[0], ('20210104',))
        with self.assertRaisesRegex(ValueError, 'year_not_verified'):
            official_calendar({'years': [record]}, '2021-01-01', '2021-01-04', 'SZSE')

    def test_prior_history_and_consecutive_windows_are_causal(self):
        days = sessions()
        a = window_profile(stream(days), '000001.SZ', days, days[0], days[-1], past_count=3, window=3)
        b = window_profile(stream(days[:5]), '000001.SZ', days, days[0], days[-1], past_count=3, window=3)
        self.assertEqual(a['per_date_counts'][:5], b['per_date_counts'][:5])
        self.assertEqual(a['per_date_counts'][:3], [(0, 0, 0), (0, 0, 0), (1, 1, 1)])
        self.assertEqual(b['per_date_counts'][5], (1, 0, 0))
        self.assertEqual(b['availability_reason_counts']['calendar_row_absent'], 7)

    def test_missing_exchange_session_is_not_compressed(self):
        days = sessions()
        value = window_profile(stream(days[:4] + days[5:]), '000001.SZ', days, days[0], days[-1],
                               past_count=3, window=3)
        self.assertEqual([row[2] for row in value['per_date_counts'][3:8]], [1, 0, 0, 0, 1])

    def test_adjustment_missing_and_zero_amount_do_not_get_imputed(self):
        days = sessions()
        a = window_profile(stream(days, missing_adjustments=(days[4],)), '000001.SZ', days,
                           days[0], days[-1], past_count=3, window=3)
        b = window_profile(stream(days, zero_activity=(days[4],)), '000001.SZ', days,
                           days[0], days[-1], past_count=3, window=3)
        self.assertEqual(a['availability_reason_counts']['adjustment_missing_or_invalid'], 3)
        self.assertEqual(b['availability_reason_counts']['amount_missing_zero_or_invalid'], 3)
        self.assertTrue(a['per_date_counts'][-1][2])

    def test_volume_is_disclosed_but_not_an_extra_amount_signal_gate(self):
        days = sessions()
        a = window_profile(stream(days, missing_volume=(days[4],)), '000001.SZ', days,
                           days[0], days[-1], past_count=3, window=3)
        self.assertTrue(a['per_date_counts'][4][2])
        self.assertEqual(a['volume_unavailable_rows_not_used_as_amount_feature_gate'], 1)

    def test_prefix_locator_is_only_a_current_file_locator(self):
        prefixes = {'SH': ['600', '601', '603', '605'], 'SZ': ['000', '001', '002', '003']}
        self.assertTrue(prefix_locator('600001.SH', prefixes))
        self.assertTrue(prefix_locator('002001.SZ', prefixes))
        self.assertFalse(prefix_locator('300001.SZ', prefixes))
        self.assertFalse(prefix_locator('920001.BJ', prefixes))

    def test_rows_outside_calendar_are_visible_not_repaired(self):
        days = sessions()
        value = window_profile(stream((days[0], '20210109', *days[5:])), '000001.SZ', days,
                               days[0], days[-1], past_count=1, window=1)
        self.assertEqual(value['unexpected_calendar_dates'], ['20210109'])

    def test_covered_holiday_before_first_session_is_not_pre_calendar_history(self):
        days = sessions()
        value = window_profile(stream(('20210101', *days)), '000001.SZ', days, days[0], days[-1],
                               past_count=2, window=1, calendar_start='20210101', calendar_end=days[-1])
        self.assertEqual(value['unexpected_calendar_dates'], ['20210101'])
        self.assertEqual(value['pre_calendar_valid_price_observations_with_unverified_session_dates'], 0)
        self.assertEqual(value['per_date_counts'][0][0], 0)

    def test_schema_identity_and_date_order_reject_ambiguous_inputs(self):
        days = sessions()
        with self.assertRaisesRegex(ValueError, 'schema'):
            window_profile(io.StringIO('date,close\n20210104,1'), '000001.SZ', days, days[0], days[-1])
        with self.assertRaisesRegex(ValueError, 'identity'):
            window_profile(stream(days, symbol='000002.SZ'), '000001.SZ', days, days[0], days[-1])
        with self.assertRaisesRegex(ValueError, 'increasing'):
            window_profile(stream(days[::-1]), '000001.SZ', days, days[0], days[-1])

    def test_fixed_features_skip_last_five_price_intervals_and_nonoverlap_amount(self):
        prices = list(range(1, 66)); amounts = [2.] * 60 + [6.] * 5
        result = fixed_features(prices, amounts)
        self.assertAlmostEqual(result['M'], math.log(60 / 5))
        self.assertAlmostEqual(result['A'], math.log(3))
        prices[-5:] = [1000.] * 5
        self.assertEqual(result, fixed_features(prices, amounts))

    def test_fixed_features_do_not_fill_missing_or_nonpositive_data(self):
        for bad in (None, 0, float('nan'), float('inf'), -1):
            prices, amounts = [1.] * 65, [1.] * 65
            prices[10] = bad
            self.assertIsNone(fixed_features(prices, amounts))
        with self.assertRaisesRegex(ValueError, 'exact_65'):
            fixed_features([1.] * 64, [1.] * 65)

    def test_price_strata_preserve_ties_without_activity_leakage(self):
        rows = [{'symbol': f'{i:06d}', 'M': 1., 'A': float(i)} for i in range(503)]
        layers = fixed_price_strata(rows)
        self.assertEqual([len(x) for x in layers], [20] * 5)
        self.assertEqual(layers[0][0]['symbol'], '000000')
        self.assertEqual(layers[-1][-1]['symbol'], '000099')
        self.assertIsNone(fixed_price_strata(rows[:499]))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            fixed_price_strata(rows + [rows[0]])

    def test_stratum_remainder_and_unknown_labels_preserve_original_denominators(self):
        rows = [{'symbol': f'{i:06d}', 'M': -float(i), 'A': float(i)} for i in range(515)]
        layers = fixed_price_strata(rows)
        self.assertEqual([len(x) for x in layers], [21, 21, 21, 20, 20])
        labels = {row['symbol']: float(row['A']) / 100 for row in rows}
        result = information_day(layers, labels)
        self.assertGreater(result['increment'], 0)
        del labels[layers[0][-1]['symbol']]
        unknown = information_day(layers, labels)
        self.assertIsNone(unknown['increment'])
        self.assertEqual(unknown['predecision_full_denominator'], 103)
        self.assertEqual(unknown['predecision_top_denominator'], 33)
        self.assertEqual(unknown['unknown_labels'], {'top': 1, 'full': 1})

    def test_source_gates_do_not_treat_owner_activation_as_data_certification(self):
        contract = {'source_evidence': {'vendor': False, 'adjustment': False, 'PIT': False},
                    'information_gate_required': ['vendor', 'adjustment', 'independent_calendar_verified'],
                    'portfolio_gate_required': ['PIT']}
        gates = source_gates(contract, calendar_verified=True)
        self.assertEqual(gates['information_missing'], ['vendor', 'adjustment'])
        self.assertFalse(gates['portfolio_authorized_by_data'])

    def test_manifest_detects_mutation_and_path_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'file').write_text('a')
            manifest = root / 'manifest.json'; manifest.write_text(json.dumps({'file': sha256(root / 'file')}))
            verify_manifest(root, sha256(manifest))
            (root / 'file').write_text('b')
            with self.assertRaisesRegex(ValueError, 'file_mismatch'):
                verify_manifest(root)
            manifest.write_text(json.dumps({'../escape': 'anything'}))
            with self.assertRaisesRegex(ValueError, 'file_mismatch'):
                verify_manifest(root)

    def test_qualification_rejects_mac_before_archive_or_output_access(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'contract.json'
            path.write_text(json.dumps({'phase': 'source_and_calendar_qualification',
                 'authorization': {'qualification_run': True}, 'orders_authorized': False,
                 'research_only': True, 'qualification': {'returns_or_rankings': False},
                 'source': {'archive': '/unread-source.zip'}}))
            with patch('qount.research.ashare_selection.sys.platform', 'darwin'):
                with self.assertRaisesRegex(ValueError, 'wsl_mounted_e'):
                    qualify(contract_path=path, calendar_path=root / 'unread.json', out=root / 'out')
            self.assertFalse((root / 'out').exists())


if __name__ == '__main__':
    unittest.main()
