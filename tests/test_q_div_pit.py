import unittest

from qount.research.q_div import DataUnknown
from qount.research.q_div_pit import FinancialVersionIndex, row_hash
from tests import test_q_div as fixtures


def dated(value, public='20260801', flag='0'):
    return {'ts_code': '600900.SH', **fixtures.report('20260630', n_income_attr_p=value),
            'ann_date': public, 'f_ann_date': public, 'update_flag': flag}


class FinancialVersionTests(unittest.TestCase):
    def test_strict_clock_future_restatement_and_flag_never_ranks(self):
        original, revision = dated(10), dated(30, '20261010', '1')
        history = FinancialVersionIndex([('income', [revision, original])])
        self.assertEqual(history.section('600900.SH','20260801')[0]['income'], [])
        self.assertEqual(history.section('600900.SH','20261010')[0]['income'][0]['n_income_attr_p'], 10)
        self.assertEqual(history.section('600900.SH','20261011')[0]['income'][0]['n_income_attr_p'], 30)
        self.assertEqual(history.section('600900.SH','20260930'),
                         FinancialVersionIndex([('income',[original])]).section('600900.SH','20260930'))

    def test_conflict_unknown_only_after_its_publication(self):
        history = FinancialVersionIndex([('income', [dated(10), dated(11,flag='1'), dated(20,'20261010')])])
        self.assertEqual(len(history.conflicts), 1)
        self.assertEqual(history.section('600900.SH','20260801')[0]['income'], [])
        with self.assertRaisesRegex(DataUnknown,'ambiguous_same_date'):
            history.section('600900.SH','20260930')
        self.assertEqual(history.section('600900.SH','20261011')[0]['income'][0]['n_income_attr_p'], 20)

    def test_identical_values_collapse_and_inputs_are_immutable(self):
        rows = [dated(10), dated(10,flag='1')]
        history = FinancialVersionIndex([('income',rows)])
        rows[0]['n_income_attr_p'] = 99
        section, _ = history.section('600900.SH','20260930')
        self.assertEqual(len(section['income']),1)
        section['income'][0]['n_income_attr_p'] = 88
        self.assertEqual(history.section('600900.SH','20260930')[0]['income'][0]['n_income_attr_p'],10)

    def test_identical_values_with_different_comp_types_collapse(self):
        rows = [{**dated(10), 'comp_type': '1'}, {**dated(10), 'comp_type': '2'}]
        history = FinancialVersionIndex([('income', rows)])
        self.assertEqual(len(history.conflicts), 0)
        section, _ = history.section('600900.SH', '20260930')
        self.assertEqual(len(section['income']), 1)
        self.assertEqual(section['income'][0]['n_income_attr_p'], 10)

    def test_public_evidence_is_additional_clock_and_does_not_certify_coverage(self):
        row = dated(10)
        history = FinancialVersionIndex([('income',[row])])
        with self.assertRaisesRegex(DataUnknown,'evidence_missing'):
            history.section('600900.SH','20260930',require_public_evidence=True)
        proof = {'row_sha256':row_hash(row),'document_sha256':'1'*64,
                 'document_ref':'fixture-only','public_date':'20260930',
                 'reconciliation':'exact_fields_and_period'}
        history = FinancialVersionIndex([('income',[row])],[proof])
        self.assertEqual(history.section('600900.SH','20260930')[0]['income'],[])
        self.assertEqual(len(history.section('600900.SH','20261001',require_public_evidence=True)[0]['income']),1)
        with self.assertRaisesRegex(ValueError,'precedes_vendor'):
            FinancialVersionIndex([('income',[row])],[{**proof,'public_date':'20260730'}])

    def test_TTM_ROE_cashflow_rolling_and_unknowns(self):
        sources = [(api,[{'ts_code':'600900.SH',**r} for r in rows])
                   for api, rows in zip(('income','cashflow','balancesheet'),fixtures.QDivTests().quality_data())]
        history = FinancialVersionIndex(sources)
        results = list(history.rolling(['20260731','20260930']))
        self.assertEqual(results[0]['status'],'unknown')
        self.assertEqual(results[1]['quality']['parent_profit_TTM_cny'],150)
        self.assertEqual(results[1]['quality']['CFO_TTM_cny'],170)
        self.assertAlmostEqual(results[1]['quality']['ROE_TTM'],150/650)
        self.assertFalse(results[1]['historical_PIT_certified'])
        self.assertTrue(all(r['status']=='unknown' for r in history.rolling(['20260930'],require_public_evidence=True)))

    def test_malformed_publication_quarantined_not_zero(self):
        history = FinancialVersionIndex([('income',[{**dated(10),'f_ann_date':'20261301'}])])
        self.assertEqual(len(history.rejected),1)
        self.assertFalse(history.symbols)
        with self.assertRaises(ValueError):
            list(history.rolling(['20260930','20260930']))

    def test_unrelated_symbols_do_not_change_section_or_conflict_status(self):
        original=dated(10)
        others=[{**dated(value), 'ts_code':f'{symbol:06d}.SZ'}
                for symbol in range(1,2001) for value in (20,30)]
        history=FinancialVersionIndex([('income',[original,*others])])
        expected=FinancialVersionIndex([('income',[original])]).section('600900.SH','20260930')
        self.assertEqual(history.section('600900.SH','20260930'),expected)
        self.assertEqual(history.section('absent','20260930')[0]['income'],[])
        with self.assertRaisesRegex(DataUnknown,'ambiguous_same_date'):
            history.section('000001.SZ','20260930')


if __name__ == '__main__':
    unittest.main()
