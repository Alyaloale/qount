"""Issuer parsing, assumed payment timing, streaming and concentration diagnostics."""
import datetime as dt
from functools import partial
from pathlib import Path
import sys
import tempfile
import unittest
from xml.sax.saxutils import escape
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/research"))
from compare_g20_long_cash import bil_distributions, payment_policy, bil_amount_conflicts, simulate, paired_diagnostics, SYMBOLS
from qount.dual_engine import g20_cash as ledger
from qount.research.dual_engine_optimization import EquityPanel
from qount.research.g20_cash_execution import CashFriction, rebalance_cash


def issuer_xlsx(path, rows):
    strings = [str(v) for row in rows for v in row]
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    values = ''.join('<si><t>' + escape(v) + '</t></si>' for v in strings)
    data = []
    for i, row in enumerate(rows):
        cells = ''.join(f'<c r="{chr(65+j)}{i+1}" t="s"><v>{sum(len(r) for r in rows[:i])+j}</v></c>' for j in range(len(row)))
        data.append(f'<row>{cells}</row>')
    with ZipFile(path, 'w') as z:
        z.writestr('xl/sharedStrings.xml', f'<sst {ns}>{values}</sst>')
        z.writestr('xl/worksheets/sheet1.xml', f'<worksheet {ns}><sheetData>{"".join(data)}</sheetData></worksheet>')


class G20LongCashTests(unittest.TestCase):
    def test_issuer_amount_sums_distribution_components_and_preserves_pay_date(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'issuer.xlsx'
            issuer_xlsx(p, [['Fund', 'BIL', 'id', '01/02/2026', '01/02/2026', '01/06/2026', '.2', '.03', '.04']])
            row = bil_distributions(p)['2026-01-02']
            self.assertAlmostEqual(row['amount'], .27)
            self.assertEqual(row['pay_date'], '2026-01-06')

    def test_invalid_in_scope_row_rejected_without_repair(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'issuer.xlsx'
            issuer_xlsx(p, [['Fund', 'BIL', 'id', '01/06/2026', '01/02/2026', '01/02/2026', '.2']])
            with self.assertRaisesRegex(ValueError, 'BIL_issuer_distribution_invalid'):
                bil_distributions(p)

    def test_outside_scope_source_error_does_not_enter_experiment(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'issuer.xlsx'
            issuer_xlsx(p, [
                ['Fund', 'BIL', 'id', '03/03/2008', '02/05/2008', '02/11/2008', '.1'],
                ['Fund', 'BIL', 'id', '01/02/2026', '01/02/2026', '01/06/2026', '.2']])
            self.assertEqual(list(bil_distributions(p)), ['2026-01-02'])

    def test_lag_counts_sessions_and_tail_stays_unspendable(self):
        dates = ('2026-01-02', '2026-01-05', '2026-01-06')
        event = dict(date=int(dt.datetime(2026, 1, 2, 9, 30, tzinfo=ledger.NY).timestamp()), amount=.1)
        cache = {'SMH': dict(events=dict(dividends={'one': event}))}
        p = payment_policy(cache, dates, {}, 2)
        self.assertEqual(p['pay_dates']['vaneck']['2026-01-02'], '2026-01-06')
        self.assertIsNone(payment_policy(cache, dates, {}, 5)['pay_dates']['vaneck']['2026-01-02'])
        self.assertIsNone(payment_policy(cache, dates, {}, None)['pay_dates']['vaneck']['2026-01-02'])

    def test_bil_issuer_date_and_amount_override_assumed_timing(self):
        dates = ('2026-01-02', '2026-01-05')
        stamp = int(dt.datetime(2026, 1, 2, 9, 30, tzinfo=ledger.NY).timestamp())
        cache = {'BIL': dict(rows=[dict(date=d, open=10., high=10., low=10., close=10., adjClose=10.) for d in dates],
                            events=dict(dividends={'one': dict(date=stamp, amount=.09)}))}
        issuer = {'2026-01-02': dict(symbol='BIL', ex_date='2026-01-02', pay_date='2026-01-06', amount=.1, source='issuer')}
        policy = payment_policy(cache, dates, issuer, 0)
        _, actions, _ = ledger.normalize_cache(cache, policy)
        self.assertEqual(actions[dates[0]][0]['amount'], .1)
        self.assertEqual(actions[dates[0]][0]['pay_date'], '2026-01-06')

    def test_missing_bil_pay_date_cannot_silently_become_assumed(self):
        stamp = int(dt.datetime(2026, 1, 2, 9, 30, tzinfo=ledger.NY).timestamp())
        cache = {'BIL': dict(events=dict(dividends={'one': dict(date=stamp, amount=.1)}))}
        with self.assertRaisesRegex(ValueError, 'BIL_issuer_pay_date_missing'):
            payment_policy(cache, ('2026-01-02', '2026-01-05'), {}, 5)

    def test_issuer_zero_and_yahoo_positive_conflict_is_preserved(self):
        stamp = int(dt.datetime(2022, 3, 1, 9, 30, tzinfo=ledger.NY).timestamp())
        cache = {'BIL': dict(events=dict(dividends={'one': dict(date=stamp, amount=.022)}))}
        issuer = {'2022-03-01': dict(amount=0., pay_date='2022-03-07')}
        conflicts = bil_amount_conflicts(cache, issuer)
        self.assertEqual(conflicts[0]['issuer_amount'], 0.)
        self.assertEqual(conflicts[0]['yahoo_physical_amount'], .022)
        self.assertEqual(issuer['2022-03-01']['amount'], 0.)

    def fixture(self):
        dates = ('2025-12-31', '2026-01-02', '2026-01-05', '2026-01-06')
        panel = EquityPanel(dates, {}, {}, {})
        prices = {s: {d: dict(open=10., close=10.) for d in dates} for s in SYMBOLS}
        for d in dates[2:]:
            prices['SOXL'][d] = dict(open=5., close=5.)
        actions = {dates[1]: [dict(kind='dividend', symbol='SOXL', amount=1., pay_date=dates[3], amount_source='fixture', source='fixture')],
                   dates[2]: [dict(kind='split', symbol='SOXL', ratio=2.)]}
        return panel, prices, actions, {0: {'SOXL': .2, 'BIL': .8}, 1: {'BIL': 1.}}

    def test_streaming_matches_full_history_step_with_split_and_dividend(self):
        p, prices, actions, targets = self.fixture()
        f = CashFriction()
        r = simulate(p, prices, actions, targets, capital=1000., friction=f, delay=1, start='2026-01-02')
        data = ledger.new_account('2026-10-26T00:00:00+00:00')
        data['initial_equity'] = data['layer']['sleeves']['g20']['cash'] = 1000.
        for i in range(1, len(p.dates)):
            day = p.dates[i]
            if i-1 in targets:
                data['pending'] = dict(target=targets[i-1], decision_date=p.dates[i-1],
                    available_at=dt.datetime.combine(dt.date.fromisoformat(p.dates[i-1]), dt.time(16), ledger.NY).isoformat())
            data = ledger.step(data, day=day, bar={s: prices[s][day] for s in SYMBOLS}, actions=actions.get(day, []), decision=None,
                opening=dt.datetime.combine(dt.date.fromisoformat(day), dt.time(9, 30), ledger.NY),
                observed_at='2026-10-26T00:00:00+00:00', reconstructed=True, historical_replay=True,
                execution_symbols=SYMBOLS, rebalance=partial(rebalance_cash, friction=f))
        self.assertEqual(r['records'], data['observations'])
        self.assertEqual(r['trades'], data['trades'])
        self.assertEqual(r['income'], data['income'])
        self.assertEqual(r['metrics']['split_count'], 1)

    def test_reverse_split_fractional_claim_rejected_not_invented(self):
        p, prices, actions, targets = self.fixture()
        actions[p.dates[2]] = [dict(kind='split', symbol='SOXL', ratio=.1)]
        with self.assertRaisesRegex(ValueError, 'fractional_split_requires_reconciliation'):
            simulate(p, prices, actions, targets, capital=1000., friction=CashFriction(), delay=1, start='2026-01-02')

    def test_paired_concentration_and_calendar_validation(self):
        a = dict(metrics=dict(capital=100.), records=[dict(date='2023-12-29', equity=100.), dict(date='2024-12-31', equity=100.)])
        b = dict(metrics=dict(capital=100.), records=[dict(date='2023-12-29', equity=100.), dict(date='2024-12-31', equity=110.)])
        d = paired_diagnostics(a, b)
        self.assertAlmostEqual(d['contribution_by_year']['2023'], 0.)
        self.assertAlmostEqual(d['leave_year_terms_out']['2024'], 0.)
        b['records'][0]['date'] = '2023-12-28'
        with self.assertRaisesRegex(ValueError, 'calendar_invalid'):
            paired_diagnostics(a, b)


if __name__ == '__main__':
    unittest.main()
