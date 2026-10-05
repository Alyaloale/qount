import copy
import csv
import datetime as dt
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from qount.research import dual_engine_information_data as d
from qount.research import dual_engine_sources as r

CONTRACT = Path(__file__).resolve().parents[1] / 'config/dual-engine-sources-20261005.json'


def archive(rows):
    output = io.BytesIO(); stream = io.StringIO(); csv.writer(stream).writerows(rows)
    with zipfile.ZipFile(output, 'w') as z: z.writestr('rows.csv', stream.getvalue())
    return output.getvalue()


def history(day, rate=.001, buy=.6):
    cutoff = dt.date.fromisoformat(day)
    daily, flow = {}, {}
    for i in range(200):
        stamp = (cutoff - dt.timedelta(days=i)).isoformat()
        daily[stamp] = {'complete': True, 'sum_rate': rate if i <= 7 else rate * .5}
        flow[stamp] = {'quote': 100., 'taker_buy_quote': buy * 100.}
    return daily, flow


class InformationDataTests(unittest.TestCase):
    def test_settled_funding_signed_and_variable_interval(self):
        stamp = int(dt.datetime(2021, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
        events = d.parse_funding(archive([['calc_time', 'funding_interval_hours', 'last_funding_rate'],
                                         [stamp, 4, -.0002], [stamp + 4 * 3600000, 8, .0001]]), '2021-01')
        self.assertEqual(events[0]['interval_hours'], 4.)
        self.assertEqual(events[0]['rate'], -.0002)

    def test_funding_wrong_month_schema_duplicate_fail(self):
        stamp = 1609459200000
        header = ['calc_time', 'funding_interval_hours', 'last_funding_rate']
        for rows, month in (([['wrong'], [stamp, 8, .01]], '2021-01'),
                            ([header, [stamp, 8, .01]], '2021-02'),
                            ([header, [stamp, 8, .01], [stamp, 8, .01]], '2021-01')):
            with self.assertRaises(ValueError): d.parse_funding(archive(rows), month)

    def test_spot_microseconds_and_quote_flow(self):
        for scale in (1, 1000):
            row = [1735689600000 * scale, 1, 1, 1, 100, 1, 1735775999999 * scale,
                   1000, 5, 1, 750, 0]
            parsed = d.parse_flow(archive([row]), '2025-01')['2025-01-01']
            self.assertEqual(parsed['imbalance'], .5)
            self.assertEqual(parsed['quote'], 1000)
        row[10] = 1001
        with self.assertRaises(ValueError): d.parse_flow(archive([row]), '2025-01')

    def test_funding_cutoff_ties_negative_and_missing(self):
        daily, _ = history('2021-01-01')
        feature = d.funding_feature(daily, '2021-01-01')
        self.assertTrue(feature['crowded'])
        self.assertEqual(feature['cutoff'], '2020-12-31')
        changed = copy.deepcopy(daily); changed['2021-01-01']['sum_rate'] = 1.
        self.assertEqual(feature, d.funding_feature(changed, '2021-01-01'))
        for row in changed.values(): row['sum_rate'] = -.001
        self.assertFalse(d.funding_feature(changed, '2021-01-01')['crowded'])
        for row in changed.values(): row['sum_rate'] = .001
        self.assertEqual(d.funding_feature(changed, '2021-01-01')['percentile180'], .5)
        changed['2020-12-31']['complete'] = False
        self.assertIsNone(d.funding_feature(changed, '2021-01-01'))

    def test_flow_quote_weighting_prior_day_missing(self):
        _, rows = history('2021-01-01')
        rows['2020-12-31'] = {'quote': 1900., 'taker_buy_quote': 0.}
        self.assertAlmostEqual(d.flow_feature(rows, '2021-01-01')['imbalance20'], -.4)
        rows['2021-01-01'] = {'quote': 1e12, 'taker_buy_quote': 1e12}
        self.assertAlmostEqual(d.flow_feature(rows, '2021-01-01')['imbalance20'], -.4)
        del rows['2020-12-30']
        self.assertIsNone(d.flow_feature(rows, '2021-01-01'))

    def test_macro_publication_safety_delay_staleness_and_revision_label(self):
        raw = b'Friday_of_Week,NFCI,Credit,Risk,Leverage\n01/01/2021,1,.1,.2,.3\n'
        nfci = d.parse_macro(raw)
        dates = ['2021-01-04', '2021-01-05', '2021-01-06', '2021-01-08', '2021-02-01']
        features = d.macro_features({'nfci': nfci, 'curve': {'2021-01-04': -1.}}, dates)
        self.assertIsNone(features[2]['nfci'])
        self.assertEqual(features[3]['nfci']['usable_from'], '2021-01-08')
        self.assertIsNone(features[0]['curve'])
        self.assertEqual(features[2]['curve'], -1.)
        self.assertIsNone(features[4]['nfci'])
        self.assertIsNone(features[4]['curve'])
        self.assertIn('not_PIT', features[3]['vintage_status'])

    def test_macro_schema_and_missing_curve_not_zero(self):
        with self.assertRaises(ValueError): d.parse_macro(b'date,value\n2021-01-01,0\n')
        self.assertEqual(d.parse_curve(b'observation_date,T10Y3M\n2021-01-04,\n2021-01-05,-.1\n'),
                         {'2021-01-05': -.1})

    def test_sources_storage_and_network_allowlist(self):
        with self.assertRaises(ValueError): d.fetch('https://example.com/private')
        with self.assertRaises(ValueError):
            d.acquire(out=Path('/tmp/qount-not-authority'), prior_open_root=Path('unused'),
                      pit_cache=Path('unused'), curve_csv=Path('unused'), curve_receipt=Path('unused'))


class SourcesTests(unittest.TestCase):
    def test_frozen_inventory_and_qualification(self):
        c = r.read_contract(CONTRACT)
        self.assertEqual(c['planned_curves'], 4 * (len(r.G20_CONTROLS + r.G20_CANDIDATES + r.C60_CONTROLS + r.C60_CANDIDATES)))
        self.assertEqual(c['selection_exclusions'], r.SELECTION_EXCLUSIONS)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'contract.json'
            for key, value in [('selection_exclusions', []), ('source_contract', {}), ('mechanisms', {})]:
                changed = copy.deepcopy(c); changed[key] = value; path.write_text(json.dumps(changed))
                with self.assertRaises(ValueError): r.read_contract(path)

    def crypto(self, rule, information):
        axis = SimpleNamespace(dates=('2021-01-01', '2021-01-02'))
        assets = {k: SimpleNamespace(symbol=s) for k, s in [('btc', 'BTCUSDT'), ('eth', 'ETHUSDT'), ('alt', 'ALTUSDT')]}
        original = {0: {'btc': .4, 'eth': .3, 'alt': .2}}
        with patch.object(r.tenth, 'crypto_targets', return_value=(original, ['same-universe'])):
            return r.crypto_targets(axis, assets, {}, rule, information)

    def test_funding_core_all_and_factorial_use_real_targets(self):
        daily, flow = history('2021-01-01')
        negative, _ = history('2021-01-01', rate=-.001)
        info = {'funding': {'BTCUSDT': daily, 'ETHUSDT': negative}, 'flow': {'BTCUSDT': flow, 'ETHUSDT': flow}}
        self.assertEqual(self.crypto('funding_core', info)[0][0], {'btc': .2, 'eth': .3, 'alt': .2})
        self.assertEqual(self.crypto('funding_all', info)[0][0], {'btc': .2, 'eth': .15, 'alt': .1})
        self.assertEqual(self.crypto('funding_flow', info)[0], self.crypto('funding_all', info)[0])
        info['flow']['BTCUSDT'] = history('2021-01-01', buy=.4)[1]
        self.assertEqual(self.crypto('flow_entry', info)[0][0], {'eth': .3})
        self.assertEqual(self.crypto('funding_flow', info)[0][0], {'eth': .15})
        self.assertEqual(self.crypto('flow_entry', info)[1]['original_selection'], ['same-universe'])

    def test_missing_information_is_neutral_and_recorded(self):
        info = {'funding': {s: {} for s in d.SYMBOLS}, 'flow': {s: {} for s in d.SYMBOLS}}
        for rule in r.C60_CANDIDATES:
            aims, audit = self.crypto(rule, info)
            self.assertEqual(aims[0], {'btc': .4, 'eth': .3, 'alt': .2})
            self.assertEqual(audit['information_decisions'][0]['funding'], {s: None for s in d.SYMBOLS})

    def test_macro_defense_is_funded_and_original_selection_preserved(self):
        from qount.dual_engine.contracts import G20_EXECUTION_TO_PROXY
        key = next(iter(G20_EXECUTION_TO_PROXY))
        panel = SimpleNamespace(dates=('2021-01-08', '2021-01-11', '2021-01-12'))
        info = {'nfci': {'2021-01-01': {'NFCI': 1., 'Credit': 1., 'usable_from': '2021-01-08'}}, 'curve': {}}
        with patch.object(r.tenth, 'equity_targets', return_value=({0: {key: .6, 'GLD': .2, 'BIL': .2}}, ['same'])), patch.object(r.old, 'g20_signals', return_value=[0]):
            for rule in r.G20_CANDIDATES:
                aims, audit = r.equity_targets(panel, {}, rule, {}, info)
                self.assertAlmostEqual(sum(aims[0].values()), 1.)
                self.assertAlmostEqual(aims[0][key], .3)
                self.assertAlmostEqual(aims[0]['GLD' if rule == 'credit_gold' else 'BIL'], .5)
                self.assertEqual(audit['original_selection'], ['same'])

    def test_all_controls_exact_and_candidates_prefix_and_cash_conserve(self):
        from test_dual_engine_regimes import panel_fixture, assets_fixture
        c = r.read_contract(CONTRACT); panel = panel_fixture()
        rates = {k: [0.] * len(panel.dates) for k in ('DFII10', 'T10YIE')}
        missing = {'funding': {s: {} for s in d.SYMBOLS}, 'flow': {s: {} for s in d.SYMBOLS}, 'nfci': {}, 'curve': {}}
        for rule in r.G20_CONTROLS:
            self.assertEqual(r.equity_targets(panel, c['g20'], rule, rates, missing), r.tenth.equity_targets(panel, c['g20'], rule, rates))
        axis, assets = assets_fixture()
        for rule in r.C60_CONTROLS:
            self.assertEqual(r.crypto_targets(axis, assets, c['c60'], rule, missing), r.tenth.crypto_targets(axis, assets, c['c60'], rule))
        closes, opens = r.base.crypto_prices(axis, assets, {a.symbol: dict(zip(axis.dates[a.start:a.start + len(a.closes)], a.closes)) for a in assets.values()})
        settings = {**c['c60'], 'start': axis.dates[365]}
        aims, _ = r.crypto_targets(axis, assets, settings, 'funding_flow', missing)
        run = r.candidate_replay('c60', 'funding_flow', axis.dates, closes, opens, aims, settings=settings, delay=1, cost=50, assets=assets)
        future = copy.deepcopy(missing); future['flow']['BTCUSDT'][axis.dates[-1]] = {'quote': 1e20, 'taker_buy_quote': 0}
        later, _ = r.crypto_targets(axis, assets, settings, 'funding_flow', future)
        self.assertEqual(aims, later)
        cash = nav = 1.; units = {}
        for row in run['records']:
            day = row['date']; delta = {k: row['units'].get(k, 0.) - units.get(k, 0.) for k in set(units) | set(row['units'])}
            cash -= sum(q * opens[k][day] for k, q in delta.items()) + sum(abs(q) * opens[k][day] for k, q in delta.items()) * .005
            self.assertAlmostEqual(cash, row['cash'], places=10)
            self.assertAlmostEqual(cash + sum(q * closes[k][day] for k, q in row['units'].items()), row['nav'], places=10)
            self.assertAlmostEqual(nav * (1 + row['return']), row['nav'], places=10)
            units = row['units']; nav = row['nav']
