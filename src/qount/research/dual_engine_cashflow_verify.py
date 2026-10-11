"""Independent trade/payment cash oracle; never calls the candidate replay."""
from __future__ import annotations

import datetime as dt
import csv
import io
import json
import math
import statistics
import zipfile
from pathlib import Path

from qount.research.dual_engine_execution_study import verify_manifest
from qount.research.dual_engine_optimization import file_hash


def verify_inputs(inputs, contract):
    """Rebuild reductions directly from raw CSVs; no acquisition parser calls."""
    verify_manifest(inputs)
    prior = Path(contract['information_root'])
    verify_manifest(prior, expected_hash=contract['information_manifest_sha256'])
    info = json.loads((prior / 'information.json').read_text())
    first, last = contract['evaluation']['first'], contract['evaluation']['last']
    funding = [e for e in info['funding_events']['BTCUSDT'] if first <= e['day'] <= last]
    needed = {t for e in funding for t in (e['timestamp_ms'] // 60000 * 60000, e['timestamp_ms'] // 60000 * 60000 - 60000)}
    prices, marks, hour_counts = {}, {}, {}
    input_prices = json.loads((inputs / 'prices.json').read_text())
    rows = 0
    provenance = json.loads((inputs / 'provenance.json').read_text())
    for archive in provenance['archives']:
        path = inputs / archive['file']
        if file_hash(path) != archive['sha256']:
            raise ValueError('cashflow_source_archive_changed')
        checksum = inputs / 'checksums' / (path.name + '.CHECKSUM')
        if checksum.read_text().split()[0] != archive['sha256']:
            raise ValueError('cashflow_source_official_checksum')
        with zipfile.ZipFile(path) as z:
            with z.open(z.namelist()[0]) as source:
                for raw in csv.reader(io.TextIOWrapper(source)):
                    if not raw[0].isdigit():
                        continue
                    t = int(raw[0])
                    t = t // 1000 if t >= 10**14 else t
                    when = dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc)
                    day = when.date().isoformat()
                    rows += 1
                    if archive['kind'] == 'mark' and t in needed:
                        marks[t] = (float(raw[1]), float(raw[2]), float(raw[3]))
                    if not first <= day <= last:
                        continue
                    p = prices.setdefault(day, {})
                    if archive['kind'] == 'mark':
                        hourly = p.setdefault('mark_hour_high', [0.0] * 24)
                        hourly[when.hour] = max(hourly[when.hour], float(raw[2]))
                        hour_counts.setdefault(day, [set() for _ in range(24)])[when.hour].add(t)
                        p['mark_close'] = float(raw[4])
                    else:
                        if when.hour in (1, 23):
                            p[archive['kind'] + '_open' + str(when.hour)] = float(raw[1])
                        p[archive['kind'] + '_close'] = float(raw[4])
    for day, counts in hour_counts.items():
        if 'mark_hour_complete' in input_prices[day]:
            prices[day]['mark_hour_complete'] = [len(n) == 60 for n in counts]
    if prices != input_prices:
        raise ValueError('cashflow_source_price_reduction')
    expected = []
    for e in funding:
        t = e['timestamp_ms'] // 60000 * 60000
        pair = marks[t], marks[t - 60000]
        expected.append({**e, 'mark_proxy': pair[0][0], 'mark_lower': min(p[2] for p in pair), 'mark_upper': max(p[1] for p in pair)})
    if expected != json.loads((inputs / 'funding.json').read_text()):
        raise ValueError('cashflow_source_funding_reduction')
    return {'verified': True, 'raw_rows': rows, 'archives': len(provenance['archives']), 'days': len(prices), 'events': len(expected),
            'exact_exchange_receipts_certified': False, 'publication_vintage_certified': False}


def check_ledger(run, prices, events, rule, cost_bps, delay):
    fee = cost_bps / 10000
    maxima = {'cash': 0.0, 'funding': 0.0, 'fees': 0.0, 'nav': 0.0, 'episodes': 0.0, 'metrics': 0.0}

    def near(key, actual, expected):
        delta = abs(actual - expected)
        maxima[key] = max(maxima[key], delta)
        if not math.isfinite(delta) or delta > 1e-9:
            raise ValueError('cashflow_oracle_' + key)

    timeline = sorted([(e['timestamp_ms'], 0, e) for e in events] +
                      [(t['timestamp_ms'], 1, t) for t in run['trades']], key=lambda x: (x[0], x[1]))
    expected_trades = []
    if rule != 'cash':
        for day in prices:
            d = dt.date.fromisoformat(day)
            if d.day == 1 + delay:
                stamp = int(dt.datetime(d.year, d.month, d.day, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
                if expected_trades:
                    expected_trades.append((stamp, 'close'))
                expected_trades.append((stamp, 'open'))
        final = dt.date.fromisoformat(max(prices))
        expected_trades.append((int(dt.datetime(final.year, final.month, final.day, 23, tzinfo=dt.timezone.utc).timestamp() * 1000), 'close'))
    if [(t['timestamp_ms'], t['side']) for t in run['trades']] != expected_trades:
        raise ValueError('cashflow_oracle_clock')
    cash, quantity, origin, start, open_fee, paid = 1.0, 0.0, 0.0, 0.0, 0.0, 0.0
    actual_payments = iter(run['payments'])
    actual_episodes = iter(run['episodes'])
    pointer = 0
    previous = 1.0
    returns = []
    for row in run['records']:
        day = row['date']
        d = dt.date.fromisoformat(day)
        midnight = int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp() * 1000)
        while pointer < len(timeline) and timeline[pointer][0] < midnight + 86400000:
            stamp, kind, event = timeline[pointer]
            pointer += 1
            if kind == 0:
                if quantity:
                    payment = next(actual_payments)
                    if payment['timestamp_ms'] != stamp or payment['episode_id'] != episode_id:
                        raise ValueError('cashflow_oracle_payment_ownership')
                    near('funding', payment['quantity'], quantity)
                    value = quantity * event['rate'] * event['mark_proxy'] if rule == 'btc_fully_funded_monthly' else 0.0
                    lo = quantity * event['rate'] * (event['mark_lower'] if event['rate'] >= 0 else event['mark_upper']) if rule == 'btc_fully_funded_monthly' else 0.0
                    hi = quantity * event['rate'] * (event['mark_upper'] if event['rate'] >= 0 else event['mark_lower']) if rule == 'btc_fully_funded_monthly' else 0.0
                    near('funding', payment['payment'], value)
                    near('funding', payment['lower'], lo)
                    near('funding', payment['upper'], hi)
                    cash += value
                    paid += value
            else:
                when = dt.datetime.fromtimestamp(stamp / 1000, dt.timezone.utc)
                s, f = prices[when.date().isoformat()]['spot_open' + str(when.hour)], prices[when.date().isoformat()]['perp_open' + str(when.hour)]
                near('cash', event['spot'], s)
                near('cash', event['perp'], f)
                if event['side'] == 'open':
                    if quantity:
                        raise ValueError('cashflow_oracle_already_open')
                    start, paid = cash, 0.0
                    quantity = cash / (2 * s + fee * (s + f))
                    near('cash', event['quantity'], quantity)
                    episode_id = event['episode_id']
                    open_fee = quantity * (s + f) * fee
                    cash -= quantity * s + open_fee
                    origin, spot_origin = f, s
                    near('cash', cash, quantity * s)
                    fee_value = open_fee
                else:
                    near('cash', event['quantity'], quantity)
                    fee_value = quantity * (s + f) * fee
                    cash += quantity * s + quantity * (origin - f) - fee_value
                    ep = next(actual_episodes)
                    if ep['exit_ms'] != stamp or ep['id'] != episode_id:
                        raise ValueError('cashflow_oracle_episode_clock')
                    basis = quantity * (s - spot_origin + origin - f)
                    near('episodes', ep['quantity'], quantity)
                    near('episodes', ep['starting_nav'], start)
                    near('episodes', ep['basis_pnl'], basis)
                    near('episodes', ep['funding'], paid)
                    near('episodes', ep['net_pnl'], basis + paid - open_fee - fee_value)
                    near('episodes', ep['net_pnl'], cash - start)
                    quantity = origin = 0.0
                near('fees', event['fees'], fee_value)
                near('cash', event['wallet_after'], cash)
        nav = cash + quantity * prices[day]['spot_close'] + quantity * (origin - prices[day]['mark_close'])
        near('nav', row['nav'], nav)
        near('cash', row['wallet'], cash)
        near('cash', row['quantity'], quantity)
        near('nav', row['return'], nav / previous - 1)
        returns.append(nav / previous - 1)
        previous = nav
    if quantity or pointer != len(timeline) or next(actual_payments, None) is not None or next(actual_episodes, None) is not None:
        raise ValueError('cashflow_oracle_incomplete_ledger')
    m = run['metrics']
    near('metrics', m['cagr'], math.prod(1 + r for r in returns) ** (365 / len(returns)) - 1)
    peak = 1.0
    drawdown = 0.0
    for row in run['records']:
        peak = max(peak, row['nav'])
        drawdown = min(drawdown, row['nav'] / peak - 1)
    near('metrics', m['max_drawdown'], drawdown)
    vol = statistics.stdev(returns) * math.sqrt(365)
    near('metrics', m['cash_excess_sharpe'], statistics.fmean(returns) * 365 / vol if vol else 0.0)
    total_paid = math.fsum(p['payment'] for p in run['payments'])
    total_basis = math.fsum(e['basis_pnl'] for e in run['episodes'])
    fees = math.fsum(t['fees'] for t in run['trades'])
    near('cash', cash - 1, total_paid + total_basis - fees)
    for name, value in (('funding_pnl', total_paid), ('basis_pnl', total_basis), ('total_fees', fees), ('terminal_nav', cash)):
        near('metrics', m[name], value)
    wins = sum(ep['net_pnl'] > 1e-12 for ep in run['episodes'])
    if m['closed_episodes'] != len(run['episodes']) or m['winning_episodes'] != wins:
        raise ValueError('cashflow_oracle_win_denominator')
    if run['episodes']:
        near('metrics', m['net_closed_win_rate'], wins / len(run['episodes']))
    elif m['net_closed_win_rate'] is not None:
        raise ValueError('cashflow_oracle_cash_win_rate')
    # Separate collateral oracle from the transaction/NAV reconstruction above.
    # It takes verified trades/payments as events and independently reconstructs
    # each hour's separate wallet, never netting spot wealth against short margin.
    changes = {}
    for t in run['trades']:
        changes.setdefault(t['timestamp_ms'] // 3600000, []).append(t)
    settlements = {}
    for p in run['payments']:
        settlements.setdefault(p['timestamp_ms'] // 3600000, []).append(p)
    bank, units, entry = 1.0, 0.0, 0.0
    expected_breaches, expected_unknown = [], []
    for day, p in prices.items():
        date = dt.date.fromisoformat(day)
        begin = int(dt.datetime(date.year, date.month, date.day, tzinfo=dt.timezone.utc).timestamp()) // 3600
        for hour in range(24):
            index = begin + hour
            before = bank
            payments = settlements.get(index, [])
            bank += math.fsum(x['payment'] for x in payments)
            changed = changes.get(index, [])
            for t in changed:
                if t['side'] == 'open':
                    units, entry = t['quantity'], t['perp']
                    bank -= units * t['spot'] + t['fees']
                else:
                    bank += units * t['spot'] + units * (entry - t['perp']) - t['fees']
                    units = entry = 0.0
            if units:
                if not p.get('mark_hour_complete', [True] * 24)[hour]:
                    expected_unknown.append((day, hour))
                if p['mark_hour_high'][hour] <= 0:
                    continue
                available = bank if changed else before + math.fsum(min(x['lower'], 0.0) for x in payments)
                eq = available + units * (entry - p['mark_hour_high'][hour])
                threshold = units * p['mark_hour_high'][hour] * (0.05 + fee)
                if eq <= threshold:
                    expected_breaches.append((day, hour, eq, threshold))
    if len(expected_breaches) != m['margin_breach_hours'] or len(run['breaches']) != len(expected_breaches):
        raise ValueError('cashflow_oracle_margin_count')
    for actual, expected in zip(run['breaches'], expected_breaches, strict=True):
        if (actual['day'], actual['hour']) != expected[:2]:
            raise ValueError('cashflow_oracle_margin_clock')
        near('cash', actual['equity'], expected[2])
        near('cash', actual['reserve'], expected[3])
    if (m.get('unknown_margin_hours', 0) != len(expected_unknown) or
            [(r['day'], r['hour']) for r in run.get('unknown_margin_hours', [])] != expected_unknown):
        raise ValueError('cashflow_oracle_unknown_margin_coverage')
    near('metrics', m['ending_wealth_lower'], cash - total_paid + math.fsum(x['lower'] for x in run['payments']))
    near('metrics', m['ending_wealth_upper'], cash - total_paid + math.fsum(x['upper'] for x in run['payments']))
    return {'errors': maxima, 'days': len(run['records']), 'funding_events': len(run['payments']), 'closed_episodes': len(run['episodes'])}


def verify_study(*, out: Path, repo: Path):
    files = verify_manifest(out)
    r = json.loads((out / 'results.json').read_text())
    c = json.loads((out / 'contract.json').read_text())
    a = json.loads((out / 'input-audit.json').read_text())
    inputs = Path(a['input_root'])
    verify_manifest(inputs, expected_hash=a['manifest_sha256'])
    qualified = verify_inputs(inputs, c)
    prices = json.loads((inputs / 'prices.json').read_text())
    events = json.loads((inputs / 'funding.json').read_text())
    for name, sha in r['source_sha256'].items():
        if file_hash(repo / name) != sha or file_hash(out / 'source' / Path(name).name) != sha:
            raise ValueError('cashflow_execution_source_changed')
    summaries = r['summaries']['cashflow']
    checks = []
    for curve in r['curve_exposures']:
        cost, delay = [int(v[1:]) for v in curve['cell'].split('-')]
        run = json.loads((out / curve['ledger']).read_text())
        if run['metrics'] != summaries[curve['rule']][curve['cell']]:
            raise ValueError('cashflow_oracle_summary')
        checked = check_ledger(run, prices, events, curve['rule'], cost, delay)
        checks.append({'rule': curve['rule'], 'cell': curve['cell'], **checked, 'verified': True})
    if len(checks) != c['curve_count'] or len(files) < 12:
        raise ValueError('cashflow_curve_count')
    gates = {cell: {'positive_net_cagr': m['cagr'] > 0, 'positive_lower_bound_wealth': m['ending_wealth_lower'] > 1,
                   'no_margin_breach': m['margin_breach_hours'] == 0, 'complete_mark_stress_coverage': m['unknown_margin_hours'] == 0}
             for cell, m in summaries['btc_fully_funded_monthly'].items()}
    if r['feasibility_checks'] != gates or r['feasibility_passed'] != all(all(v.values()) for v in gates.values()):
        raise ValueError('cashflow_oracle_feasibility_gate')
    return {'verified': True, 'manifest_sha256': file_hash(out / 'manifest.json'), 'curve_count': len(checks),
            'curves_verified': checks, 'source_files_checked': len(r['source_sha256']), 'output_files_checked': len(files),
            'input_qualification': qualified,
            'research_only': True, 'orders_authorized': False, 'promotion_evidence': False,
            'scope': 'independent transaction/funding cash, fees, paired episodes, returns and metrics; market source qualification separate',
            'historical_margin_tiers_certified': False, 'exact_exchange_funding_receipts_certified': False}
