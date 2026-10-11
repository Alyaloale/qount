"""Causal timestamps, real gaps, signed funding, sparse statistics and provenance."""
import copy
import datetime as dt
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from qount.research.opportunity_data import parse_prices, parse_funding, freeze, verify_manifest, storage, runtime_source_binding, cached_archives, archive_identity, requalify
from qount.research.opportunity_screen import HOUR, accept_events, signals, label, read_contract, evaluate
from qount.research_data.event_stats import event_summary, sparse_block_intervals

CONTRACT = Path(__file__).resolve().parents[1] / 'config/short-horizon-opportunity-20261009.json'


def contract():
    return read_contract(CONTRACT)


def stamp(day):
    return int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def zip_csv(text):
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w') as z:
        z.writestr('public.csv', text)
    return result.getvalue()


def signal_fixture():
    t = stamp('2021-01-01')
    bars = {t + i * HOUR: {'open': 100., 'high': 101., 'low': 99., 'close': 100.,
                           'quote': 100., 'buy_quote': 50.} for i in range(-170, 12)}
    bars[t - HOUR] = {'open': 100., 'high': 100., 'low': 95., 'close': 98., 'quote': 400., 'buy_quote': 120.}
    bars[t] = {'open': 98., 'high': 100., 'low': 97., 'close': 99., 'quote': 150., 'buy_quote': 90.}
    return t, bars


def label_fixture():
    entry = stamp('2021-01-01') + HOUR
    event = {'entry_ms': entry, 'exit_ms': entry + 6 * HOUR, 'entry_utc': '2021-01-01T01:00:00+00:00',
             'symbol': 'BTCUSDT', 'decision_ms': entry, 'feature_closed_ms': entry - 1}
    bars = {entry + i * HOUR: {'open': 100., 'high': 103., 'low': 97., 'close': 100., 'quote': 100., 'buy_quote': 50.}
            for i in range(7)}
    bars[event['exit_ms']]['open'] = 102.
    marks = {entry + i * HOUR: {'open': 100., 'high': 101., 'low': 99., 'close': 100.} for i in range(7)}
    # Hourly intervals deliberately avoid assuming every market settles three times/day.
    funding = [{'timestamp_ms': entry + i * HOUR, 'interval_hours': 1., 'rate': .001} for i in range(-1, 8)]
    return event, bars, marks, funding


class OpportunityTests(unittest.TestCase):
    def test_frozen_protocol_refuses_parameter_drift_or_orders(self):
        c = contract()
        self.assertEqual(c['candidate_trials_activated'], 1)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'c.json'
            for key, value in (('orders_authorized', True), ('holdout_role', 'validation_v1'),
                               ('signal', {**c['signal'], 'volume_multiple_min': 2})):
                changed = {**c, key: value}
                path.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):
                    read_contract(path)

    def test_closed_signal_and_no_future_dependence(self):
        t, bars = signal_fixture()
        c = contract()
        c['evaluation'] = {'first': '2021-01-01', 'last': '2021-01-01'}
        found, _ = signals(bars, c, 'flow_reclaim')
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['decision_ms'], t + HOUR)
        self.assertLess(found[0]['feature_closed_ms'], found[0]['decision_ms'])
        future = copy.deepcopy(bars)
        for when, row in future.items():
            if when > t:
                row.update(open=10000., high=20000., low=1., close=10000.)
        self.assertEqual([e for e in signals(future, c, 'flow_reclaim')[0] if e['decision_ms'] <= t + HOUR], found)

    def test_gap_cannot_shorten_lookback(self):
        t, bars = signal_fixture()
        del bars[t - 100 * HOUR]
        found, audit = signals(bars, contract(), 'flow_reclaim')
        self.assertEqual(found, [])
        self.assertGreater(audit['missing_feature_windows'], 0)

    def test_flow_ablation_is_control_only(self):
        t, bars = signal_fixture()
        bars[t]['buy_quote'] = 30.
        self.assertEqual(signals(bars, contract(), 'flow_reclaim')[0], [])
        self.assertEqual(len(signals(bars, contract(), 'price_reclaim_control')[0]), 1)
        self.assertEqual(signals(bars, contract(), 'cash')[0], [])

    def test_unknown_feature_plan_blocks_even_an_apparently_passing_summary(self):
        fake = {'events': 100, 'diagnostic_gate_passed': True}
        data = {s: {'bars': {}, 'marks': {}, 'funding': []} for s in contract()['symbols']}
        with patch('qount.research.opportunity_screen.event_summary', side_effect=lambda *a, **k: dict(fake)):
            result = evaluate(data, contract())
        self.assertFalse(result['candidate_diagnostic_gate_passed'])
        self.assertTrue(all(not v['full_signal_plan_known'] for k, v in result['summaries'].items() if k.startswith('flow_reclaim/')))

    def test_global_tie_cooldown_cap_and_delay_without_label_peeking(self):
        first = stamp('2021-01-01')
        candidates = [{'decision_ms': first + i * 72 * HOUR, 'symbol': symbol}
                      for i in range(6) for symbol in ('ETHUSDT', 'BTCUSDT')]
        accepted, audit = accept_events(candidates, contract(), 1)
        self.assertEqual(len(accepted), 4)
        self.assertTrue(all(e['symbol'] == 'BTCUSDT' for e in accepted))
        self.assertEqual(accepted[0]['entry_ms'], first + HOUR)
        self.assertEqual(audit['monthly_cap_rejections'], 4)
        self.assertEqual(audit['cooldown_rejections'], 4)

    def test_calendar_boundary_censored_is_retained(self):
        end = stamp('2026-09-01')
        accepted, audit = accept_events([{'decision_ms': end - 2 * HOUR, 'symbol': 'BTCUSDT'}], contract(), 0)
        self.assertTrue(accepted[0]['censored'])
        self.assertEqual(audit['accepted_events'], 1)

    def test_both_sides_actual_exit_notional_and_signed_funding(self):
        event, bars, marks, funding = label_fixture()
        row = label(event, bars, marks, funding, cost_bps=10, leverage=contract()['leverage_diagnostic'])
        self.assertTrue(row['qualified'])
        self.assertAlmostEqual(row['total_cost'], .001 * 2.02)
        self.assertAlmostEqual(row['funding_paid_proxy'], .006)
        self.assertAlmostEqual(row['net_proxy'], .02 - .00202 - .006)
        self.assertLess(row['net_lower'], row['net_proxy'])
        self.assertLess(row['net_proxy'], row['net_upper'])
        for f in funding:
            f['rate'] *= -1
        negative = label(event, bars, marks, funding, cost_bps=10, leverage=contract()['leverage_diagnostic'])
        self.assertAlmostEqual(negative['funding_paid_proxy'], -.006)
        self.assertLess(negative['net_lower'], negative['net_proxy'])
        self.assertLess(negative['net_proxy'], negative['net_upper'])

    def test_entry_held_exit_not_held_and_variable_intervals(self):
        event, bars, marks, funding = label_fixture()
        funding[-2]['rate'] = .5  # exactly at exit must not be paid
        row = label(event, bars, marks, funding, cost_bps=10, leverage=contract()['leverage_diagnostic'])
        self.assertEqual(row['payments'][0]['timestamp_ms'], event['entry_ms'])
        self.assertEqual(len(row['payments']), 6)
        self.assertAlmostEqual(row['funding_paid_proxy'], .006)

    def test_missing_mark_or_funding_schedule_is_unknown(self):
        event, bars, marks, funding = label_fixture()
        del marks[event['entry_ms'] + HOUR]
        self.assertFalse(label(event, bars, marks, funding, cost_bps=25, leverage=contract()['leverage_diagnostic'])['qualified'])
        event, bars, marks, funding = label_fixture()
        funding.pop(3)
        row = label(event, bars, marks, funding, cost_bps=25, leverage=contract()['leverage_diagnostic'])
        self.assertEqual(row['reason'], 'funding_schedule_gap_or_unknown')

    def test_leverage_no_breach_cannot_certify_safe_and_breach_is_hypothetical(self):
        event, bars, marks, funding = label_fixture()
        marks[event['entry_ms']]['low'] = 90.
        row = label(event, bars, marks, funding, cost_bps=25, leverage=contract()['leverage_diagnostic'])
        high = [d for d in row['leverage_diagnostics'] if d['leverage'] == 20]
        self.assertTrue(all(d['assumption_stress_breach'] for d in high))
        self.assertTrue(all(not d['safe_leverage_certified'] for d in row['leverage_diagnostics']))
        self.assertTrue(all(not d['historical_liquidation_verified'] for d in row['leverage_diagnostics']))

    def test_exit_mark_boundary_gap_included_without_next_hour_lookahead(self):
        event, bars, marks, funding = label_fixture()
        marks[event['exit_ms']].update(open=80., low=1.)
        row = label(event, bars, marks, funding, cost_bps=25, leverage=contract()['leverage_diagnostic'])
        self.assertAlmostEqual(row['mark_mae'], -.2)
        self.assertTrue(all(d['assumption_stress_breach'] for d in row['leverage_diagnostics'] if d['leverage'] == 10))
        del marks[event['exit_ms']]
        self.assertFalse(label(event, bars, marks, funding, cost_bps=25, leverage=contract()['leverage_diagnostic'])['qualified'])

    def test_cash_and_small_sample_cannot_claim_success(self):
        g = contract()['gate']
        self.assertIsNone(event_summary([], first_ms=0, last_ms=100, gate=g)['net_lower_win_rate'])
        events = [{'entry_ms': 1000, 'entry_utc': '2021-01-01', 'net_lower': .1, 'net_proxy': .1}]
        self.assertFalse(event_summary(events, first_ms=0, last_ms=10 * 86400000, gate=g)['diagnostic_gate_passed'])

    def test_calendar_cluster_retains_empty_blocks_and_same_week_correlation(self):
        events = [{'entry_ms': 1000, 'net_lower': .02}, {'entry_ms': 2000, 'net_lower': -.01}]
        result = sparse_block_intervals(events, first_ms=0, last_ms=28 * 86400000 - 1)
        self.assertEqual(result['occupied_blocks'], 1)
        self.assertEqual(result['calendar_blocks'], 4)
        self.assertEqual(result['win_rate'], [.5, .5])

    def test_archive_gap_invalid_calendar_and_flow_never_imputed(self):
        t = stamp('2021-01-01')
        valid = f'{t},100,101,99,100,1,{t + HOUR - 1},100,10,1,50,0'
        bad = f'{t + HOUR},100,101,99,100,1,{t + 2 * HOUR - 1},100,10,1,101,0'
        parsed, audit = parse_prices(zip_csv(valid + '\n' + bad), '2021-01', 'bars')
        self.assertEqual(len(parsed), 1)
        self.assertEqual(len(audit['missing_hours']), 743)
        self.assertEqual(len(audit['rejected_rows']), 1)
        self.assertEqual(audit['imputed_rows'], 0)
        micros = valid.replace(str(t), str(t * 1000)).replace(str(t + HOUR - 1), str((t + HOUR) * 1000 - 1))
        self.assertEqual(parse_prices(zip_csv(micros), '2021-01', 'bars')[0], parsed)

    def test_duplicate_hour_and_funding_schema_fail(self):
        t = stamp('2021-01-01')
        row = f'{t},100,101,99,100,0,{t + HOUR - 1},0,0,0,0,0'
        with self.assertRaisesRegex(ValueError, 'duplicate_hour'):
            parse_prices(zip_csv(row + '\n' + row), '2021-01', 'marks')
        with self.assertRaisesRegex(ValueError, 'funding_schema'):
            parse_funding(zip_csv('time,rate\n0,0'), '2021-01')

    def test_manifest_detects_mutation_and_added_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'data.json').write_text('{}')
            freeze(root)
            verify_manifest(root)
            (root / 'extra.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'manifest_mismatch'):
                verify_manifest(root)
            (root / 'extra.json').unlink()
            (root / 'data.json').write_text('[]')
            with self.assertRaisesRegex(ValueError, 'manifest_mismatch'):
                verify_manifest(root)

    def test_actual_imports_cannot_be_bound_to_another_checkout(self):
        with self.assertRaisesRegex(ValueError, 'runtime_not_from_bound_repo'):
            runtime_source_binding(repo=Path('/tmp/different-qount'))
        with self.assertRaisesRegex(ValueError, 'runtime_source_hash_mismatch'):
            runtime_source_binding(expected={})

    def test_reuse_requires_manifest_and_original_checksum_files_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'archives').mkdir()
            (root / 'checksums').mkdir()
            name = 'BTCUSDT-1h-2021-01.zip'
            (root / 'archives' / name).write_bytes(b'public-archive')
            digest = hashlib.sha256(b'public-archive').hexdigest()
            checksum = root / 'checksums' / (name + '.CHECKSUM')
            checksum.write_text(digest + ' ' + name)
            freeze(root)
            self.assertIn(name, cached_archives([root]))
            checksum.write_text('changed')
            with self.assertRaisesRegex(ValueError, 'cache_hash_mismatch'):
                cached_archives([root])

    def test_expected_endpoint_requalification_rejects_trade_as_mark_collision(self):
        c = contract()
        c['symbols'] = ['BTCUSDT']
        c['acquisition'].update(first_month='2021-01', last_month='2021-01')
        t = stamp('2021-01-01')
        trade = zip_csv(f'{t},100,101,99,100,1,{t + HOUR - 1},100,10,1,50,0')
        mark = zip_csv(f'{t},100,102,98,100,0,{t + HOUR - 1},0,0,0,0,0')
        funding = zip_csv(f'calc_time,funding_interval_hours,last_funding_rate\n{t},8,0.001')
        with tempfile.TemporaryDirectory() as temp:
            for collision in (False, True):
                root = Path(temp) / ('collision' if collision else 'correct')
                (root / 'archives').mkdir(parents=True)
                (root / 'checksums').mkdir()
                (root / 'contract.json').write_text(json.dumps(c))
                records, official = [], {}
                for kind, actual in (('bars', trade), ('marks', mark), ('funding', funding)):
                    name, url = archive_identity('BTCUSDT', '2021-01', kind)
                    body = trade if collision and kind == 'marks' else actual
                    digest = hashlib.sha256(body).hexdigest()
                    official[url + '.CHECKSUM'] = (hashlib.sha256(actual).hexdigest() + ' ' + name).encode()
                    (root / 'archives' / name).write_bytes(body)
                    (root / 'checksums' / (name + '.CHECKSUM')).write_text(digest + ' ' + name)
                    _, audit = parse_funding(body, '2021-01') if kind == 'funding' else parse_prices(body, '2021-01', kind)
                    records.append({'symbol': 'BTCUSDT', 'month': '2021-01', 'kind': kind,
                                    'file': 'archives/' + name, 'url': url, 'sha256': digest, 'audit': audit})
                (root / 'provenance.json').write_text(json.dumps(records))
                freeze(root)
                out = root.parent / (root.name + '-qualified')
                with patch('qount.research.opportunity_data.read_contract', return_value=c), \
                        patch('qount.research.opportunity_data.storage'), \
                        patch('qount.research.opportunity_data.fetch', side_effect=lambda url: official[url]) as fetcher:
                    if collision:
                        with self.assertRaisesRegex(ValueError, 'expected_endpoint_checksum_mismatch'):
                            requalify(contract_path=CONTRACT, input_root=root, out=out)
                        self.assertTrue((out / 'qualification-failure.json').exists())
                    else:
                        self.assertEqual(requalify(contract_path=CONTRACT, input_root=root, out=out)['expected_endpoint_checksums_qualified'], 3)
                        verified = json.loads((out / 'provenance.json').read_text())
                        self.assertTrue(all(r['source_identity_qualified'] and r['archive_observed_at'] is None for r in verified))
                        self.assertEqual(fetcher.call_count, 3)
                verify_manifest(root)

    def test_storage_rejects_mac_or_unmounted_output(self):
        with self.assertRaises(ValueError):
            storage(Path('/tmp/opportunity'))


if __name__ == '__main__':
    unittest.main()
