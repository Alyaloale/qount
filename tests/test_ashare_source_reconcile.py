import csv
import io
import unittest
from qount.research.ashare_source_reconcile import compare_original, number
from qount.research_data.equity_archive import FIELDS


def data(**updates):
    row={k:'1' for k in FIELDS};row.update(ts_code='000998.SZ',trade_date='20180828');row.update(updates)
    stream=io.StringIO();w=csv.DictWriter(stream,fieldnames=FIELDS);w.writeheader();w.writerow(row);stream.seek(0);return stream


class SourceReconcileTests(unittest.TestCase):
    def test_json_numbers_and_csv_text_share_parser_without_null_filling(self):
        for value in (10.8142, '10.8142', 2, '2'):
            self.assertEqual(number(value), float(value))
        for value in (None, '', True, float('nan'), float('inf')):
            self.assertIsNone(number(value))
    def test_identity_and_adjusted_application(self):
        p=compare_original(data(),'000998.SZ',1,{'20180828':1});self.assertEqual(p['counts']['adjusted_fields_checked'],4);self.assertEqual(p['counts']['fresh_factor_value_differences'],0)
    def test_missing_fresh_factor_is_explicit(self):self.assertEqual(compare_original(data(),'000998.SZ',1,{})['counts']['fresh_factor_dates_absent'],1)
    def test_revised_factor_not_repaired(self):self.assertEqual(compare_original(data(),'000998.SZ',1,{'20180828':2})['counts']['fresh_factor_value_differences'],1)
    def test_missing_original_factor_not_filled(self):
        p=compare_original(data(adj_factor=''),'000998.SZ',1,{'20180828':1});self.assertEqual(p['counts']['missing_factor_kept_unknown'],1);self.assertNotIn('adjusted_fields_checked',p['counts'])
    def test_constant_anchor_supported(self):
        p=compare_original(data(adj_factor='2',adj_open='3',adj_high='3',adj_low='3',adj_close='3'),'000998.SZ',1.5,{'20180828':2});self.assertEqual(p['counts']['adjusted_construction_differences'],0)
    def test_wrong_construction_is_not_accepted(self):self.assertEqual(compare_original(data(adj_open='2'),'000998.SZ',1)['counts']['adjusted_construction_differences'],1)
    def test_wrong_identity_rejected(self):
        with self.assertRaisesRegex(ValueError,'identity'):compare_original(data(),'000001.SZ',1)
    def test_no_cash_return_certification(self):self.assertFalse(compare_original(data(),'000998.SZ',1)['cash_total_return_certified'])


if __name__=='__main__':unittest.main()
