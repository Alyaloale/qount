#!/usr/bin/env python3
"""Bounded A-share daily absorption proxy and paired exit experiment on WSL/E."""
import argparse
from array import array
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import random
import statistics
import time

from qount.research.ashare_absorption import features, make_entry, simulate
from qount.research.ashare_backtest_data import load_panel

ROOT = Path(__file__).resolve().parents[2]
POLICIES = ['fixed10', 'price', 'price_plus_stall']


def sampled(symbol):
    return int(hashlib.sha256(('qount-ashare-absorption-20261027:' + symbol).encode()).hexdigest()[:8], 16) % 7 == 0


class Stats:
    def __init__(self):
        self.returns = array('d'); self.mdds = array('d'); self.lower = 0.
        self.counts = Counter(); self.paid = self.held = self.giveback = 0.

    def add(self, result):
        self.returns.append(result['return_pct']); self.mdds.append(result['mdd_pct'])
        self.lower += result['lower_return_pct']; self.counts[result['status']] += 1
        self.counts['positive'] += result['return_pct'] > 0
        self.counts['blocked_exit_opens'] += result['blocked_exit_opens']
        self.counts['missing_marks'] += result['missing_marks']
        self.paid += result['fees']; self.held += result['held_sessions']
        self.giveback += result.get('profit_giveback_pct') or 0.

    def summary(self):
        n = len(self.returns)
        return dict(attempts=n, counts=dict(self.counts), mean_return_pct=sum(self.returns)/n,
                    lower_bound_mean_pct=self.lower/n, median_return_pct=statistics.median(self.returns),
                    positive_fraction=self.counts['positive']/n, mean_event_mdd_pct=sum(self.mdds)/n,
                    p95_event_mdd_pct=sorted(self.mdds)[min(n-1, int(.95*n))],
                    average_held_sessions=self.held/n, average_profit_giveback_pct=self.giveback/n,
                    fees_cny=self.paid)


def quarter_bootstrap(dates, *, seed=27):
    """Quarter blocks retain all same-date events; exploratory interval only."""
    means = {day: sum(values)/len(values) for day, values in dates.items() if values}
    blocks = defaultdict(list)
    for day, value in means.items():
        blocks[(day[:4], (int(day[4:6])-1)//3)].append(value)
    groups = list(blocks.values()); randomizer = random.Random(seed)
    if len(groups) < 4:
        return dict(dates=len(means), quarters=len(groups), mean_pct=None, interval95=None)
    draws = []
    for _ in range(1000):
        selected = [randomizer.choice(groups) for _ in groups]
        draws.append(sum(map(sum, selected))/sum(map(len, selected)))
    draws.sort()
    return dict(dates=len(means), quarters=len(groups), mean_pct=sum(means.values())/len(means),
                interval95=[draws[25], draws[974]], interval_role='exploratory_no_multiple_trial_adjustment')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-config', type=Path, default=ROOT/'config/ashare-leader-backtest-20261010.json')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    assert args.out.resolve().is_relative_to(Path('/mnt/e/qount_data/qount/artifacts'))
    args.out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    source = json.loads(args.source_config.read_text())
    source['calendar']['path'] = str(ROOT/source['calendar']['path'])
    sessions, panel, _, diagnostics = load_panel(source, symbol_filter=sampled)
    print('loaded', len(panel), 'stocks', diagnostics['loaded_retired_securities'], 'retired',
          'seconds', round(time.monotonic()-started, 1), flush=True)
    days = defaultdict(list)
    for series in panel.values():
        for event in features(series, sessions):
            days[event['signal_j']].append(event)
    print('signals', sum(map(len, days.values())), 'dates', len(days), flush=True)
    summaries = defaultdict(Stats); paired = defaultdict(lambda: defaultdict(list))
    high_low = defaultdict(dict); attempt_blocks = Counter(); special_exit = Counter()
    variants = [('base10bp', .001, 0), ('stress30bp', .003, 0), ('extra_day10bp', .001, 1)]
    cash = dict(status='cash', return_pct=0., lower_return_pct=0., mdd_pct=0., fees=0.,
                held_sessions=0, profit_giveback_pct=0., blocked_exit_opens=0, missing_marks=0)
    with gzip.open(args.out/'events.jsonl.gz', 'wt') as stream:
        for j, events in sorted(days.items()):
            ordered = sorted(events, key=lambda e: (e['score'], e['symbol']))
            n = len(ordered)//3
            separated = n and ordered[n-1]['score'] < ordered[-n]['score']
            groups = {e['symbol']: ('low' if k < n else 'high' if k >= len(ordered)-n else 'middle')
                      if separated else 'unranked' for k, e in enumerate(ordered)}
            day = sessions[j]; phase = '2015_2021' if day < '20220101' else '2022_2026'
            for event in events:
                group = groups[event['symbol']]; series = panel[event['symbol']]
                for variant, slip, delay in variants:
                    entry, blocked = make_entry(series, sessions, event, slip=slip, delay=delay)
                    if blocked:
                        attempt_blocks[variant+'/'+blocked] += 1
                    outcomes = {p: simulate(series, sessions, entry, p, slip=slip) if entry else dict(cash)
                                for p in POLICIES}
                    for policy, result in outcomes.items():
                        for period in ['all', phase] + ([day[:4]] if variant == 'base10bp' else []):
                            for tag in ['all', group]:
                                summaries[(variant, period, tag, policy)].add(result)
                        if policy == 'price_plus_stall' and result.get('reason') == 'high_volume_low_close_after_profit':
                            special_exit[variant] += 1
                    for period in ['all', phase]:
                        for comparison, left, right in [('stall_minus_price','price_plus_stall','price'),
                                                        ('price_minus_fixed','price','fixed10')]:
                            paired[(variant, period, comparison)][day].append(outcomes[left]['return_pct']-outcomes[right]['return_pct'])
                    if variant == 'base10bp' and group in ('high', 'low'):
                        high_low[(phase, day)].setdefault(group, []).append(outcomes['fixed10']['return_pct'])
                    stream.write(json.dumps(dict(event=event, group=group, variant=variant,
                                                 entry_block=blocked, outcomes=outcomes), allow_nan=False)+'\n')
    entry_differences = defaultdict(lambda: defaultdict(list))
    for (phase, day), values in high_low.items():
        if 'high' in values and 'low' in values:
            difference = statistics.mean(values['high'])-statistics.mean(values['low'])
            entry_differences[phase][day].append(difference)
            entry_differences['all'][day].append(difference)
    output = dict(research_only=True, orders_authorized=False, independent_oos=False,
                  data=diagnostics, sample='SHA256(salt+symbol) first32bits modulo7==0; no current status/industry/return filter',
                  rules=dict(capital_per_event_cny=10000, prior_adv20_minimum_cny=50000000,
                             entry='close above prior20 adjusted highs; prior60 valid sessions and252 past raw observations;20-session signal cooldown',
                             absorption='amount-weighted lower-wick fraction of five PRE-breakout candles; same-date event terciles',
                             exits='fixed10 next-open, or5pct price failure/prior3-close low, optionally high-volume lower-quarter close after5pct close profit',
                             stall_thresholds='prior20 turnover multiple>=1.5; CLV<=-0.5; observed close peak>=1.05 entry reference',
                             execution='next-open;100 raw-share lots;1pct priorADV cap;T+1; +/-4.99pct conservative opening guard; persistent sell retry',
                             delay_sensitivity='extra_day10bp delays entry only; all exit decisions still use the next open',
                             costs='commission3bp min5; transfer3bp before20150801,0.2bp before20220429 else0.1bp (historical approximations); sell stamp10bp before20230828 else5bp; slippage10/30bp each side',
                             signals_through='20260831', source_ends='20260930'),
                  summaries={'/'.join(k): v.summary() for k, v in summaries.items()},
                  entry_high_minus_low={k:quarter_bootstrap(v) for k,v in entry_differences.items()},
                  paired_exit_differences={'/'.join(k):quarter_bootstrap(v) for k,v in paired.items()},
                  entry_blocks=dict(attempt_blocks), stall_exit_counts=dict(special_exit),
                  elapsed_seconds=time.monotonic()-started,
                  limits=['Daily candle/volume proxies do not identify hidden liquidity or investor accounts',
                          'Supplied archive universe, not certified full historical PIT coverage; includes sampled retired identities',
                          'Vendor adjusted-price units, not cash dividend/terminal recovery accounting; no total-return certification',
                          'Independent overlapping10000CNY event accounts, NOT a shared-capital portfolio; no CAGR or portfolio MDD',
                          'Opening guard is conservative but does not certify auctions/limit queues; full-day activity never gates open fill',
                          'Cash entry failures retained; unresolved exits retain zero-to-last-mark bounds, not discarded',
                          'Historical dates already used elsewhere in project;2022+ chronological replication is not independent OOS',
                          'Event terciles are not price/volatility matched; association does not prove money-flow causality'])
    (args.out/'results.json').write_text(json.dumps(output, indent=2, allow_nan=False)+'\n')
    print(json.dumps({k:output[k] for k in ['entry_high_minus_low','paired_exit_differences','entry_blocks','stall_exit_counts','elapsed_seconds']},indent=2), flush=True)


if __name__ == '__main__':
    main()
