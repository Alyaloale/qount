import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qount.research.q_div import DataUnknown, dividends, fundamentals
from qount.research.q_div_review import diagnose, growth, paid_events, run_review


def report(period, **values):
    return {'ts_code': '600001.SH', 'end_date': period, 'ann_date': '20260801',
            'f_ann_date': '20260801', 'report_type': '1', 'comp_type': '1', **values}


def event(year, paid, cash=1, shares=10000):
    return {'ts_code': '600001.SH', 'end_date': str(year) + '1231',
            'div_proc': '实施', 'imp_ann_date': '20230601', 'ex_date': paid,
            'pay_date': paid, 'cash_div_tax': cash, 'base_share': shares}


def fixture():
    income = [report(p, n_income_attr_p=x * 1e6) for p, x in
              [('20231231', 80), ('20241231', 100), ('20251231', 120),
               ('20260630', 80), ('20250630', 50)]]
    cashflow = [report(p, n_cashflow_act=x * 1e6) for p, x in
                [('20231231', 90), ('20241231', 110), ('20251231', 130),
                 ('20260630', 100), ('20250630', 60)]]
    balance = [report(p, total_hldr_eqy_exc_min_int=x * 1e6,
                      total_liab=600e6, total_assets=1000e6)
               for p, x in [('20260630', 700), ('20250630', 600)]]
    divs = [event(2023, '20240610'), event(2024, '20250610'), event(2025, '20260610')]
    financial = dict(income=income, cashflow=cashflow, balancesheet=balance, dividend=divs)
    quality = fundamentals(income, cashflow, balance, '20260930')
    candidate = {'symbol': '600001.SH', 'rank': 1, 'target_weight': .08,
                 'name': '测试', 'industry': '测试', 'total_mv_10k': 200000,
                 'quality': quality, 'yield_TTM': .05}
    return candidate, financial


class QDivReviewTests(unittest.TestCase):
    def test_payment_window_and_fiscal_year_are_distinct(self):
        c, f = fixture()
        f['dividend'].append(event(2024, '20260201', cash=.2))
        c['yield_TTM'] = .06
        result = diagnose(c, f, '20260930')
        self.assertEqual(result['paid_cash_365d_cny'], 120e6)
        self.assertAlmostEqual(result['cash_paid_365d_to_latest_TTM_profit'], .8)
        self.assertAlmostEqual(result['annual'][1]['cash_to_matched_fiscal_profit'], 1.2)
        self.assertAlmostEqual(result['annual'][2]['cash_to_matched_fiscal_profit'], 100 / 120)
        self.assertAlmostEqual(result['CFO_TTM_to_paid_cash_365d'], 170 / 120)
        self.assertAlmostEqual(result['PE_parent_TTM_A_quote_proxy'], 2000 / 150)
        self.assertAlmostEqual(result['latest_YTD_parent_profit_growth'], .6)
        self.assertNotIn('trailing_cash_exceeds_latest_TTM_profit', result['flags'])

    def test_proposals_future_announcements_and_future_payments_are_excluded(self):
        old = event(2025, '20260610')
        rows = [old, {**old, 'div_proc': '预案', 'cash_div_tax': 100},
                {**old, 'pay_date': '20261010'}, {**old, 'ex_date': '20261010'},
                {**old, 'imp_ann_date': '20260930'}]
        self.assertEqual(len(paid_events(rows, '20260930')), 1)
        self.assertEqual(paid_events(rows, '20260930')[0]['cash_cny'], 100e6)

    def test_exact_window_boundary_excluded_and_asof_payment_included(self):
        a = event(2024, '20250930')
        b = event(2025, '20260930')
        result = paid_events([a, b], '20260930')
        self.assertFalse(result[0]['in_trailing_payment_window'])
        self.assertTrue(result[1]['in_trailing_payment_window'])

    def test_duplicate_revisions_collapse_without_inventing_first_public_date(self):
        a = event(2025, '20260610')
        b = {**a, 'imp_ann_date': '20260601'}
        for rows in ([a, b], [b, a]):
            result = paid_events(rows, '20260930')
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]['implementation_announcement'], '20260601')
        with self.assertRaisesRegex(DataUnknown, 'conflicting_paid_event'):
            paid_events([a, {**a, 'cash_div_tax': 2}], '20260930')

    def test_share_changes_use_each_event_base_instead_of_adding_DPS(self):
        a = event(2025, '20260201', cash=1, shares=10000)
        b = event(2025, '20260601', cash=.5, shares=20000)
        self.assertEqual(sum(e['cash_cny'] for e in paid_events([a, b], '20260930')), 200e6)

    def test_missing_old_base_makes_annual_cash_unknown_without_guessing(self):
        c, f = fixture()
        f['dividend'][0]['base_share'] = None
        result = diagnose(c, f, '20260930')
        self.assertIsNone(result['annual'][0]['paid_for_fiscal_year_through_cutoff_cny'])
        self.assertIsNone(result['annual'][0]['cash_to_matched_fiscal_profit'])
        self.assertEqual(result['paid_cash_365d_cny'], 100e6)

    def test_missing_recent_base_and_nonfinite_values_fail_closed(self):
        for shares in (None, float('nan'), -1):
            with self.subTest(shares=shares), self.assertRaises(DataUnknown):
                paid_events([event(2025, '20260610', shares=shares)], '20260930')

    def test_nonpositive_growth_denominator_stays_unknown(self):
        self.assertIsNone(growth(10, 0))
        self.assertIsNone(growth(10, -10))
        self.assertEqual(growth(-10, 10), -2)

    def test_cash_exceeds_latest_profit_is_diagnostic_without_changing_candidate(self):
        c, f = fixture()
        f['dividend'][-1]['cash_div_tax'] = 1.6
        c['yield_TTM'] = .08
        original = copy.deepcopy(c)
        result = diagnose(c, f, '20260930')
        self.assertIn('trailing_cash_exceeds_latest_TTM_profit', result['flags'])
        self.assertEqual(c, original)
        self.assertFalse(result['future_dividend_forecast'])
        self.assertFalse(result['historical_PIT_certified'])

    def test_source_identity_and_snapshot_mismatch_rejected(self):
        c, f = fixture()
        f['income'][0]['ts_code'] = '600002.SH'
        with self.assertRaisesRegex(ValueError, 'identity'):
            diagnose(c, f, '20260930')
        c, f = fixture()
        c['quality']['CFO_TTM_cny'] += 100
        with self.assertRaisesRegex(ValueError, 'quality_snapshot'):
            diagnose(c, f, '20260930')
        c, f = fixture()
        c['yield_TTM'] = .08
        with self.assertRaisesRegex(ValueError, 'yield_snapshot'):
            diagnose(c, f, '20260930')

    def test_missing_annual_profit_is_unknown_not_zero(self):
        c, f = fixture()
        f['income'] = [r for r in f['income'] if r['end_date'] != '20231231']
        result = diagnose(c, f, '20260930')
        self.assertIsNone(result['annual'][0]['parent_profit_cny'])
        self.assertIsNone(result['annual'][0]['cash_to_matched_fiscal_profit'])

    def test_invalid_research_boundary_stops_before_output(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'plan.json'
            path.write_text(json.dumps({'research_only': True, 'orders_authorized': True}))
            out = Path(temp) / 'out'
            with self.assertRaisesRegex(ValueError, 'research_boundary'):
                run_review(path, out)
            self.assertFalse(out.exists())

    def test_source_contract_hash_failure_stops_before_output(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'plan.json'
            base = Path(temp) / 'base.json'
            base.write_text('{}')
            path.write_text(json.dumps({'research_only': True, 'orders_authorized': False,
                                        'promotion_evidence': False, 'new_strategy_rules': 0,
                                        'strategy_contract': str(base), 'strategy_contract_sha256': 'bad'}))
            with self.assertRaisesRegex(ValueError, 'strategy_contract_hash'):
                run_review(path, Path(temp) / 'out')
