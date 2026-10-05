"""Public, immutable information snapshots for offline G20/C60 research.

Settlement event times and closed spot bars are separate from retrieval times.
Latest macro history is explicitly revision-exposed, not a vintage archive.
"""
from __future__ import annotations

import concurrent.futures
import csv
import datetime as dt
import hashlib
import io
import json
import math
import statistics as stats
import urllib.request
import zipfile
from pathlib import Path

from qount.research.dual_engine_optimization import file_hash, write_json
from qount.research.dual_engine_execution_study import verify_manifest, load_cache
from qount.research.dual_engine_expansion import require_storage

SYMBOLS = ('BTCUSDT', 'ETHUSDT')
NFCI_URL = 'https://www.chicagofed.org/-/media/publications/nfci/nfci-data-series-csv.csv'
CURVE_URL = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=T10Y3M&cosd=2017-09-01&coed=2026-07-30'


def months(first, last):
    year, month = map(int, first.split('-'))
    while f'{year:04}-{month:02}' <= last:
        yield f'{year:04}-{month:02}'
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def fetch(url):
    if not url.startswith(('https://data.binance.vision/data/', 'https://www.chicagofed.org/')):
        raise ValueError('information_source_not_allowlisted')
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'qount-public-research/1.0'}), timeout=30) as response:
        if not response.url.startswith(('https://data.binance.vision/', 'https://www.chicagofed.org/')):
            raise ValueError('information_redirect_not_allowlisted')
        return response.read()


def zip_rows(body):
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        names = archive.namelist()
        if len(names) != 1 or not names[0].endswith('.csv'):
            raise ValueError('information_archive_layout_invalid')
        return list(csv.reader(io.StringIO(archive.read(names[0]).decode())))


def parse_funding(body, month):
    rows = zip_rows(body)
    if rows[0] != ['calc_time', 'funding_interval_hours', 'last_funding_rate']:
        raise ValueError('funding_archive_schema_changed')
    events = []
    for raw in rows[1:]:
        stamp, interval, rate = int(raw[0]), float(raw[1]), float(raw[2])
        when = dt.datetime.fromtimestamp(stamp / 1000, dt.timezone.utc)
        if when.strftime('%Y-%m') != month or not 0 < interval <= 24 or not math.isfinite(rate) or abs(rate) > 1:
            raise ValueError('funding_event_invalid')
        events.append({'timestamp_ms': stamp, 'day': when.date().isoformat(), 'interval_hours': interval, 'rate': rate})
    if not events or len({r['timestamp_ms'] for r in events}) != len(events):
        raise ValueError('funding_event_empty_or_duplicate')
    return sorted(events, key=lambda r: r['timestamp_ms'])


def parse_flow(body, month):
    result = {}
    for raw in zip_rows(body):
        if not raw[0].isdigit():
            continue
        stamp = int(raw[0]); divisor = 1_000_000 if stamp >= 10**14 else 1000
        when = dt.datetime.fromtimestamp(stamp / divisor, dt.timezone.utc)
        day = when.date().isoformat()
        close_stamp = int(raw[6]); close_divisor = 1_000_000 if close_stamp >= 10**14 else 1000
        closed = dt.datetime.fromtimestamp(close_stamp / close_divisor, dt.timezone.utc)
        quote, taker = float(raw[7]), float(raw[10])
        close = float(raw[4])
        if when.strftime('%Y-%m') != month or closed.date() != when.date() or day in result:
            raise ValueError('flow_calendar_invalid')
        if any(not math.isfinite(v) for v in (quote, taker, close)) or close <= 0 or quote <= 0 or not 0 <= taker <= quote:
            raise ValueError('flow_value_invalid')
        result[day] = {'quote': quote, 'taker_buy_quote': taker, 'close': close,
                       'imbalance': 2 * taker / quote - 1, 'closed_at': closed.isoformat()}
    if not result:
        raise ValueError('flow_archive_empty')
    return result


def parse_macro(body):
    rows = csv.DictReader(io.StringIO(body.decode('utf-8-sig')))
    if not {'Friday_of_Week', 'NFCI', 'Credit', 'Risk', 'Leverage'}.issubset(rows.fieldnames or []):
        raise ValueError('nfci_schema_changed')
    result = {}
    for raw in rows:
        date = dt.datetime.strptime(raw['Friday_of_Week'], '%m/%d/%Y').date()
        if not dt.date(2017, 9, 1) <= date <= dt.date(2026, 7, 30):
            continue
        values = {k: float(raw[k]) for k in ('NFCI', 'Credit', 'Risk', 'Leverage')}
        if date.weekday() != 4 or any(not math.isfinite(v) for v in values.values()) or date.isoformat() in result:
            raise ValueError('nfci_row_invalid')
        # Friday + seven days is later than the normal Wednesday/holiday Thursday.
        result[date.isoformat()] = {**values, 'usable_from': (date + dt.timedelta(days=7)).isoformat()}
    return result


def parse_curve(body):
    rows = csv.DictReader(io.StringIO(body.decode('utf-8-sig')))
    if rows.fieldnames != ['observation_date', 'T10Y3M']:
        raise ValueError('curve_schema_changed')
    result = {}
    for raw in rows:
        day = raw['observation_date']
        dt.date.fromisoformat(day)
        if '2017-09-01' <= day <= '2026-07-30' and raw['T10Y3M'] not in ('', '.'):
            value = float(raw['T10Y3M'])
            if day in result or not math.isfinite(value): raise ValueError('curve_row_invalid')
            result[day] = value
    return result


def funding_feature(daily, day):
    """Use through yesterday; rank seven-day means against preceding 180 means."""
    cutoff = dt.date.fromisoformat(day) - dt.timedelta(days=1)
    days = [(cutoff - dt.timedelta(days=i)).isoformat() for i in range(187)]
    if any(d not in daily or not daily[d]['complete'] for d in days): return None
    values = [daily[d]['sum_rate'] for d in reversed(days)]
    current = stats.fmean(values[-7:])
    previous = [stats.fmean(values[i:i + 7]) for i in range(180)]
    rank = (sum(v < current for v in previous) + .5 * sum(v == current for v in previous)) / len(previous)
    return {'cutoff': cutoff.isoformat(), 'mean7': current, 'percentile180': rank,
            'crowded': current > 0 and rank >= .75}


def flow_feature(rows, day):
    cutoff = dt.date.fromisoformat(day) - dt.timedelta(days=1)
    days = [(cutoff - dt.timedelta(days=i)).isoformat() for i in range(20)]
    if any(d not in rows for d in days): return None
    quote = sum(rows[d]['quote'] for d in days)
    buy = sum(rows[d]['taker_buy_quote'] for d in days)
    return {'cutoff': cutoff.isoformat(), 'imbalance20': 2 * buy / quote - 1}


def macro_features(snapshot, dates):
    output = {}
    for t, day in enumerate(dates):
        ready = [d for d, r in snapshot['nfci'].items() if r['usable_from'] <= day]
        d = max(ready) if ready else None
        nfci = snapshot['nfci'][d] if d and (dt.date.fromisoformat(day) - dt.date.fromisoformat(d)).days <= 21 else None
        cutoff = dates[t - 2] if t >= 2 else ''
        available = [d for d in snapshot['curve'] if d <= cutoff]
        c = max(available) if available else None
        curve = snapshot['curve'][c] if c and (dt.date.fromisoformat(day) - dt.date.fromisoformat(c)).days <= 7 else None
        output[t] = {'nfci': nfci, 'nfci_observation': d if nfci else None,
                     'curve': curve, 'curve_observation': c if curve is not None else None,
                     'vintage_status': 'latest_snapshot_revision_exposed_not_PIT'}
    return output


def acquire(*, out, prior_open_root, pit_cache, curve_csv, curve_receipt):
    require_storage(out)
    if out.exists(): raise ValueError('immutable_information_output_exists')
    old_files = verify_manifest(prior_open_root)
    cache, cache_hashes = load_cache(pit_cache)
    receipt = json.loads(curve_receipt.read_text())
    if receipt['url'] != CURVE_URL or receipt['sha256'] != file_hash(curve_csv):
        raise ValueError('curve_relay_identity_invalid')
    out.mkdir(parents=True)
    (out / 'archives').mkdir()
    (out / 'checksums').mkdir()
    provenance = []

    def archive(task):
        kind, symbol, month = task
        filename = f'{symbol}-fundingRate-{month}.zip' if kind == 'funding' else f'{symbol}-1d-{month}.zip'
        path = f'futures/um/monthly/fundingRate/{symbol}' if kind == 'funding' else f'spot/monthly/klines/{symbol}/1d'
        url = f'https://data.binance.vision/data/{path}/{filename}'
        relative = 'archives/' + filename
        reused = kind == 'flow' and relative in old_files
        body = (prior_open_root / relative).read_bytes() if reused else fetch(url)
        checksum = fetch(url + '.CHECKSUM')
        if checksum.decode().split()[0] != hashlib.sha256(body).hexdigest(): raise ValueError('published_archive_checksum_mismatch:' + filename)
        (out / relative).write_bytes(body)
        (out / 'checksums' / (filename + '.CHECKSUM')).write_bytes(checksum)
        parsed = parse_funding(body, month) if kind == 'funding' else parse_flow(body, month)
        return task, parsed, {'url': url, 'file': relative, 'sha256': file_hash(out / relative),
                              'reused': reused, 'observed_at': dt.datetime.now(dt.timezone.utc).isoformat()}

    tasks = [('funding', s, m) for s in SYMBOLS for m in months('2020-06', '2026-08')]
    tasks += [('flow', s, m) for s in SYMBOLS for m in months('2020-12', '2026-08')]
    events = {s: [] for s in SYMBOLS}; flow = {s: {} for s in SYMBOLS}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for (kind, symbol, month), rows, source in pool.map(archive, tasks):
            provenance.append(source)
            if kind == 'funding': events[symbol].extend(rows)
            else:
                if set(flow[symbol]) & set(rows): raise ValueError('flow_duplicate_day')
                flow[symbol].update(rows)
            if len(provenance) % 24 == 0: print(json.dumps({'archives_verified': len(provenance)}), flush=True)
    funding = {}; bridges = 0
    for symbol in SYMBOLS:
        history = sorted(events[symbol], key=lambda e: e['timestamp_ms'])
        if len({e['timestamp_ms'] for e in history}) != len(history): raise ValueError('funding_duplicate_event')
        daily = {}
        for e in history: daily.setdefault(e['day'], []).append(e)
        funding[symbol] = {d: {'sum_rate': sum(e['rate'] for e in es), 'events': len(es),
                              'covered_hours': sum(e['interval_hours'] for e in es),
                              'complete': abs(sum(e['interval_hours'] for e in es) - 24) < 1e-9}
                           for d, es in daily.items()}
        for d, raw in flow[symbol].items():
            previous = cache[symbol].get(d)
            if previous is not None:
                if raw['close'] != previous[0] or raw['quote'] != previous[1]: raise ValueError('new_flow_old_price_bridge_mismatch')
                bridges += 1
    nfci = fetch(NFCI_URL); (out / 'nfci.csv').write_bytes(nfci)
    (out / 'curve.csv').write_bytes(curve_csv.read_bytes())
    write_json(out / 'curve-relay.json', receipt)
    snapshot = {'funding': funding, 'funding_events': events, 'flow': flow,
                'nfci': parse_macro(nfci), 'curve': parse_curve(curve_csv.read_bytes())}
    write_json(out / 'information.json', snapshot)
    write_json(out / 'provenance.json', {'archives': provenance, 'prior_open_manifest_sha256': file_hash(prior_open_root / 'manifest.json'),
        'cache_sha256': cache_hashes, 'price_quote_bridge_rows': bridges,
        'nfci_url': NFCI_URL, 'macro_observed_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'vintage_status': {'crypto': 'current_official_archives_event_time_reconstructed_not_contemporaneous_vintages',
                           'macro': 'latest_snapshot_revision_exposed_not_PIT'},
        'funding_usage': 'information_only; no perpetual positions, margin, shorts or funding income',
        'limitations': ['variable intervals retained; incomplete daily coverage is missing, never zero',
                        'NFCI Friday+7d safety lag does not resolve vintage revisions',
                        'REST open-interest/basis short retention cannot supply this historical period']})
    write_json(out / 'manifest.json', {'research_only': True, 'orders_authorized': False,
        'files': {str(p.relative_to(out)): file_hash(p) for p in sorted(out.rglob('*')) if p.is_file()}})
    return {'archives': len(provenance), 'bridge_rows': bridges,
            'funding_events': {s: len(es) for s, es in events.items()},
            'flow_days': {s: len(rows) for s, rows in flow.items()}, 'nfci_rows': len(snapshot['nfci']), 'curve_rows': len(snapshot['curve'])}
