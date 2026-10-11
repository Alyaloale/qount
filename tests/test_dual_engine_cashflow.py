"""Meaningful accounting, sign, timing, qualification and corruption tests."""
import datetime as dt
import io
import json
import unittest
import zipfile
from pathlib import Path

from qount.research.dual_engine_cashflow import read_contract, replay
from qount.research.dual_engine_cashflow_data import bars
from qount.research.dual_engine_cashflow_verify import check_ledger
from qount.research.dual_engine_cashflow_qualification import audit_archive
from qount.research.dual_engine_cashflow_inputs import reduce_observed, merge_mark_day
from qount.research.dual_engine_cashflow_mark_repair import qualify_day


def fixture():
    prices = {}
    events = []
    for i in range(33):
        day = dt.date(2021, 1, 1) + dt.timedelta(days=i)
        prices[day.isoformat()] = {'spot_open1': 100, 'spot_open23': 100, 'spot_close': 100,
            'perp_open1': 101, 'perp_open23': 101, 'perp_close': 101, 'mark_close': 101, 'mark_hour_high': [102] * 24}
        for hour in (0, 8, 16):
            stamp = int(dt.datetime.combine(day, dt.time(hour), dt.timezone.utc).timestamp() * 1000) + 1
            events.append({'day': day.isoformat(), 'timestamp_ms': stamp, 'interval_hours': 8,
                'rate': 0.001, 'mark_proxy': 101, 'mark_lower': 100, 'mark_upper': 102})
    return prices, events


class CashflowTests(unittest.TestCase):
    def test_observed_union_preserves_primary_rows_absent_from_daily(self):
        start = int(dt.datetime(2021, 1, 1, tzinfo=dt.timezone.utc).timestamp()) * 1000
        bodies = []
        for missing in (65, 66):
            body = io.BytesIO()
            rows = [f'{start + i * 60000},100,101,99,100,0,{start + (i + 1) * 60000 - 1}' for i in range(1440) if i != missing]
            with zipfile.ZipFile(body, 'w') as z:
                z.writestr('BTC.csv', '\n'.join(rows))
            bodies.append(body.getvalue())
        p, selected = merge_mark_day(*bodies, '2021-01-01', {start + 65 * 60000, start + 66 * 60000})
        self.assertTrue(all(p['2021-01-01']['mark_hour_complete']))
        self.assertEqual(len(selected), 2)
    def test_official_daily_repair_requires_identical_overlap(self):
        start = int(dt.datetime(2021, 1, 1, tzinfo=dt.timezone.utc).timestamp()) * 1000
        body = io.BytesIO()
        rows = [f'{start + i * 60000},100,101,99,100,0,{start + (i + 1) * 60000 - 1}' for i in range(1440)]
        with zipfile.ZipFile(body, 'w') as z:
            z.writestr('BTC.csv', '\n'.join(rows))
        monthly = {start: (100, 101, 99, 100)}
        result = qualify_day(body.getvalue(), '2021-01-01', monthly)
        self.assertEqual(result['added_observed_rows'], 1439)
        self.assertTrue(result['day_complete'])
        monthly[start] = (100, 102, 99, 100)
        with self.assertRaisesRegex(ValueError, 'overlap'):
            qualify_day(body.getvalue(), '2021-01-01', monthly)

    def test_daily_archive_remaining_gap_is_not_filled(self):
        start = int(dt.datetime(2021, 1, 1, tzinfo=dt.timezone.utc).timestamp()) * 1000
        body = io.BytesIO()
        rows = [f'{start + i * 60000},100,101,99,100,0,{start + (i + 1) * 60000 - 1}' for i in range(1440) if i != 65]
        with zipfile.ZipFile(body, 'w') as z:
            z.writestr('BTC.csv', '\n'.join(rows))
        result = qualify_day(body.getvalue(), '2021-01-01', {})
        self.assertFalse(result['day_complete'])
        self.assertEqual(result['remaining_missing_minutes'], 1)
        self.assertEqual(result['imputed_rows'], 0)

    def test_frozen_contract(self):
        c = read_contract(Path('config/dual-engine-cashflow-20261005.json'))
        self.assertEqual(c['curve_count'], 12)
        self.assertFalse(c['orders_authorized'])

    def test_flat_basis_signed_funding_and_full_cost_identity(self):
        p, e = fixture()
        run = replay(p, e, rule='btc_fully_funded_monthly', cost_bps=25, delay=0)
        m = run['metrics']
        self.assertAlmostEqual(m['basis_pnl'], 0)
        self.assertGreater(m['funding_pnl'], 0)
        self.assertAlmostEqual(m['total_return'], m['funding_pnl'] - m['total_fees'])
        self.assertLess(m['ending_wealth_lower'], m['terminal_nav'])
        self.assertGreater(m['ending_wealth_upper'], m['terminal_nav'])
        self.assertEqual(m['closed_episodes'], 2)
        self.assertEqual(check_ledger(run, p, e, 'btc_fully_funded_monthly', 25, 0)['days'], 33)

    def test_negative_funding_is_paid_and_bounds_reverse(self):
        p, e = fixture()
        for event in e:
            event['rate'] *= -1
        run = replay(p, e, rule='btc_fully_funded_monthly', cost_bps=50, delay=1)
        self.assertLess(run['metrics']['funding_pnl'], 0)
        self.assertTrue(all(x['lower'] <= x['payment'] <= x['upper'] for x in run['payments']))
        check_ledger(run, p, e, 'btc_fully_funded_monthly', 50, 1)

    def test_funding_ownership_entry_before_exit_and_delay(self):
        p, e = fixture()
        run = replay(p, e, rule='btc_fully_funded_monthly', cost_bps=25, delay=1)
        first = run['payments'][0]
        self.assertEqual(first['day'], '2021-01-02')
        self.assertEqual(dt.datetime.fromtimestamp(first['timestamp_ms'] / 1000, dt.timezone.utc).hour, 8)
        feb = [x for x in run['payments'] if x['day'] == '2021-02-02']
        self.assertEqual([x['episode_id'] for x in feb], [1, 2, 2])

    def test_cash_has_no_fees_or_fake_wins(self):
        p, e = fixture()
        run = replay(p, e, rule='cash', cost_bps=50, delay=1)
        self.assertEqual(run['metrics']['total_return'], 0)
        self.assertIsNone(run['metrics']['net_closed_win_rate'])
        self.assertEqual(run['trades'], [])
        check_ledger(run, p, e, 'cash', 50, 1)

    def test_no_funding_ablation_keeps_double_leg_costs(self):
        p, e = fixture()
        run = replay(p, e, rule='hedge_no_funding', cost_bps=25, delay=0)
        self.assertEqual(run['metrics']['funding_pnl'], 0)
        self.assertAlmostEqual(run['metrics']['total_return'], -run['metrics']['total_fees'])
        self.assertEqual(len(run['trades']), 4)
        check_ledger(run, p, e, 'hedge_no_funding', 25, 0)

    def test_mark_not_spot_secures_short_collateral(self):
        p, e = fixture()
        p['2021-01-03']['mark_hour_high'][12] = 210
        run = replay(p, e, rule='btc_fully_funded_monthly', cost_bps=25, delay=0)
        self.assertEqual(run['metrics']['margin_breach_hours'], 1)
        self.assertEqual(run['metrics']['qualification'], 'diagnostic_counterfactual_margin_breach')
        check_ledger(run, p, e, 'btc_fully_funded_monthly', 25, 0)
        run['breaches'] = []
        with self.assertRaises(ValueError):
            check_ledger(run, p, e, 'btc_fully_funded_monthly', 25, 0)

    def test_missing_minutes_are_unknown_not_imputed_or_safe(self):
        p, e = fixture()
        p['2021-01-03']['mark_hour_complete'] = [True] * 24
        p['2021-01-03']['mark_hour_complete'][12] = False
        p['2021-01-03']['mark_hour_high'][12] = 0
        run = replay(p, e, rule='btc_fully_funded_monthly', cost_bps=25, delay=0)
        self.assertEqual(run['metrics']['unknown_margin_hours'], 1)
        self.assertEqual(run['metrics']['margin_breach_hours'], 0)
        self.assertEqual(run['metrics']['qualification'], 'diagnostic_incomplete_mark_stress_coverage')
        check_ledger(run, p, e, 'btc_fully_funded_monthly', 25, 0)

    def test_observed_reduction_retains_missing_minute_without_repair(self):
        start = int(dt.datetime(2021, 1, 1, tzinfo=dt.timezone.utc).timestamp()) * 1000
        rows = [f'{start + i * 60000},100,101,99,100,0,{start + (i + 1) * 60000 - 1}' for i in range(1440) if i != 65]
        body = io.BytesIO()
        with zipfile.ZipFile(body, 'w') as z:
            z.writestr('BTC.csv', '\n'.join(rows))
        p, mark = reduce_observed(body.getvalue(), 'mark', '2021-01-01', '2021-01-01', {start})
        self.assertFalse(p['2021-01-01']['mark_hour_complete'][1])
        self.assertEqual(p['2021-01-01']['mark_close'], 100)
        self.assertEqual(list(mark), [str(start)])

    def test_independent_oracle_rejects_fee_cash_and_payment_corruption(self):
        p, e = fixture()
        run = replay(p, e, rule='btc_fully_funded_monthly', cost_bps=25, delay=0)
        for group, key in (('payments', 'payment'), ('trades', 'fees'), ('records', 'wallet')):
            changed = json.loads(json.dumps(run))
            changed[group][0][key] += 0.01
            with self.assertRaises(ValueError):
                check_ledger(changed, p, e, 'btc_fully_funded_monthly', 25, 0)

    def test_missing_duplicate_or_wrong_ohlc_bars_fail_closed(self):
        for row in ('1609459200000,100,99,101,100,0,1609462799999',
                    '1609459200000,100,101,99,100,0,1609462799998'):
            body = io.BytesIO()
            with zipfile.ZipFile(body, 'w') as z:
                z.writestr('BTC.csv', row + '\n')
            with self.assertRaises(ValueError):
                list(bars(body.getvalue(), '2021-01', 3600000))

    def test_undeclared_cost_or_delay_rejected(self):
        p, e = fixture()
        with self.assertRaises(ValueError):
            replay(p, e, rule='btc_fully_funded_monthly', cost_bps=5, delay=0)

    def test_variable_interval_funding_collision_fails_before_income(self):
        p, e = fixture()
        e[0]['timestamp_ms'] += 3600000
        with self.assertRaisesRegex(ValueError, 'collides'):
            replay(p, e, rule='btc_fully_funded_monthly', cost_bps=25, delay=0)

    def test_microsecond_spot_bars_and_continuous_calendar(self):
        opening = int(dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc).timestamp()) * 1000000
        lines = [f'{opening + i * 3600000000},100,101,99,100,0,{opening + (i + 1) * 3600000000 - 1}' for i in range(31 * 24)]
        for rows, valid in ((lines, True), (lines[:-1], False), (lines + lines[-1:], False)):
            body = io.BytesIO()
            with zipfile.ZipFile(body, 'w') as z:
                z.writestr('BTC.csv', '\n'.join(rows) + '\n')
            if valid:
                parsed = list(bars(body.getvalue(), '2025-01', 3600000))
                self.assertEqual(len(parsed), 744)
                self.assertEqual(parsed[0][0], opening // 1000)
            else:
                with self.assertRaises(ValueError):
                    list(bars(body.getvalue(), '2025-01', 3600000))

    def test_coverage_audit_distinguishes_unused_from_required_quote(self):
        c = read_contract(Path('config/dual-engine-cashflow-20261005.json'))
        start = int(dt.datetime(2021, 1, 1, tzinfo=dt.timezone.utc).timestamp()) * 1000
        # Original strict parser rejects both missing slots. The data-only audit
        # must distinguish a scheduled fill from an unrelated mid-month hour.
        for slot, critical in ((1, 1), (11 * 24 + 3, 0)):
            lines = [f'{start + i * 3600000},100,101,99,100,1,{start + (i + 1) * 3600000 - 1}' for i in range(31 * 24) if i != slot]
            body = io.BytesIO()
            with zipfile.ZipFile(body, 'w') as z:
                z.writestr('BTC.csv', '\n'.join(lines) + '\n')
            report, _ = audit_archive(body.getvalue(), '2021-01', 'spot', c, set())
            self.assertEqual(report['missing_slots'], 1)
            self.assertEqual(report['missing_required_fill_quotes'], critical)
            self.assertFalse(report['strict_original_gate_passed'])
            self.assertNotIn('cagr', report)


if __name__ == '__main__':
    unittest.main()
