"""Evidence identities must expose uncertainty and must not certify provenance."""
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qount.research.ashare_evidence import forensic_profile, audit_evidence
from qount.research_data.equity_archive import FIELDS

POLICY = {'amount_over_volume_scales': [0.1, 1, 10, 100], 'vwap_price_tolerance_cny': 0.011,
          'change_tolerance_cny': 0.000101, 'pct_tolerance_percentage_points': 0.0051,
          'reference_price_tolerance_cny': 0.015, 'maximum_mismatch_examples_per_security': 2}
DAYS = ['20210104', '20210105', '20210106', '20210107']


def stream(rows):
    out = io.StringIO(newline='')
    writer = csv.DictWriter(out, fieldnames=FIELDS)
    writer.writeheader()
    for row in rows:
        writer.writerow({'ts_code': '000001.SZ', 'trade_date': DAYS[0], 'open': 10, 'high': 11,
            'low': 9, 'close': 10, 'pre_close': 10, 'change': 0, 'pct_chg': 0,
            'vol': 100, 'amount': 100, 'adj_factor': 2, 'adj_close': 10,
            'adj_open': 10, 'adj_high': 11, 'adj_low': 9, **row})
    out.seek(0)
    return out


def profile(rows, examples=None):
    return forensic_profile(stream(rows), '000001.SZ', DAYS, POLICY, examples or {})


class AshareEvidenceTests(unittest.TestCase):
    def test_amount_volume_scale_is_corroboration_only(self):
        value = profile([{}])
        self.assertEqual(value['amount_over_volume_scale_pass_counts'], {'0.1': 0, '1': 0, '10': 1, '100': 0})
        self.assertNotIn('amount_units_verified', value)

    def test_zero_and_nonfinite_activity_not_used_in_scale_denominator(self):
        value = profile([{'vol': 0}, {'trade_date': DAYS[1], 'amount': 'nan'}])
        self.assertEqual(value['counts']['rows'], 2)
        self.assertEqual(value['counts'].get('amount_volume_rows', 0), 0)

    def test_factor_change_reconstructs_ex_rights_reference(self):
        value = profile([{}, {'trade_date': DAYS[1], 'adj_factor': 4, 'pre_close': 5,
                              'close': 5, 'change': 0, 'pct_chg': 0}])
        self.assertEqual(value['counts']['factor_changed_pairs'], 1)
        self.assertEqual(value['counts']['factor_reference_mismatches'], 0)

    def test_calendar_gap_cannot_be_bridged_as_one_day(self):
        value = profile([{}, {'trade_date': DAYS[2], 'adj_factor': 4}])
        self.assertEqual(value['counts']['calendar_gaps_not_bridged'], 1)
        self.assertEqual(value['counts'].get('consecutive_factor_pairs', 0), 0)

    def test_missing_factor_pair_kept_out_of_bridge_count(self):
        value = profile([{}, {'trade_date': DAYS[1], 'adj_factor': ''}])
        self.assertEqual(value['counts'].get('consecutive_factor_pairs', 0), 0)

    def test_factor_mismatch_report_retains_count_and_caps_examples(self):
        value = profile([{'trade_date': day, 'pre_close': 8} for day in DAYS])
        self.assertEqual(value['counts']['factor_reference_mismatches'], 3)
        self.assertEqual(len(value['factor_reference_mismatch_examples']), 2)

    def test_rounding_tolerance_explicitly_applies_to_reference_price(self):
        a = profile([{}, {'trade_date': DAYS[1], 'pre_close': 10.014}])
        b = profile([{}, {'trade_date': DAYS[1], 'pre_close': 10.016}])
        self.assertEqual(a['counts']['factor_reference_mismatches'], 0)
        self.assertEqual(b['counts']['factor_reference_mismatches'], 1)

    def test_reported_change_and_pct_are_checked_independently(self):
        a = profile([{'close': 11, 'change': 1, 'pct_chg': 10}])
        b = profile([{'close': 11, 'change': 0, 'pct_chg': 1}])
        self.assertEqual((a['counts']['change_mismatch'], a['counts']['pct_mismatch']), (0, 0))
        self.assertEqual((b['counts']['change_mismatch'], b['counts']['pct_mismatch']), (1, 1))

    def test_published_sample_match_never_certifies_archive_origin(self):
        example = {'000001.SZ': {DAYS[0]: [{'source_id': 'fixture', 'absolute_tolerance': 1e-8,
                                           'values': {'close': 10, 'adj_factor': 2}}]}}
        check = profile([{}], example)['public_example_checks'][0]
        self.assertEqual(check['fields_checked'], 2)
        self.assertFalse(check['origin_certified'])
        self.assertEqual(check['mismatched_fields'], [])
        self.assertEqual(profile([{'close': 9}], example)['public_example_checks'][0]['mismatched_fields'], ['close'])

    def test_out_of_calendar_rows_do_not_create_reference_pairs(self):
        value = profile([{'trade_date': '20201231'}, {}])
        self.assertEqual(value['counts'].get('consecutive_factor_pairs', 0), 0)

    def test_order_and_identity_mismatch_fail(self):
        for rows in [[{}, {}], [{'ts_code': '000002.SZ'}]]:
            with self.assertRaisesRegex(ValueError, 'identity_or_order'):
                profile(rows)

    def test_mac_and_existing_storage_fail_before_source_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'contract.json'
            p.write_text(json.dumps({'phase': 'source_evidence_forensics', 'research_only': True,
                'orders_authorized': False, 'returns_or_rankings': False,
                'source': {'archive': '/mnt/e/qount_data/qount/datasets/equity_selection/source.zip'}}))
            with patch('qount.research.ashare_evidence.sys.platform', 'darwin'):
                with self.assertRaisesRegex(ValueError, 'requires_wsl'):
                    audit_evidence(contract_path=p, calendar_path=p, examples_path=p, out=Path(tmp))


if __name__ == '__main__':
    unittest.main()
