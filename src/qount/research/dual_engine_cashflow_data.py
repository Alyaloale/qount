"""Immutable public double-leg prices and bounded funding marks, WSL/E only."""
from __future__ import annotations

import calendar
import concurrent.futures
import csv
import datetime as dt
import hashlib
import io
import json
import math
import zipfile
from pathlib import Path

from qount.research.dual_engine_expansion import require_storage
from qount.research.dual_engine_execution_study import verify_manifest
from qount.research.dual_engine_information_data import fetch, months
from qount.research.dual_engine_optimization import file_hash, write_json

UTC = dt.timezone.utc


def bars(body: bytes, month: str, interval_ms: int):
    """Strict, complete calendar bars, including the spot microsecond transition."""
    year, number = map(int, month.split('-'))
    first = int(dt.datetime(year, number, 1, tzinfo=UTC).timestamp() * 1000)
    count = calendar.monthrange(year, number)[1] * 86400000 // interval_ms
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        names = z.namelist()
        if len(names) != 1 or not names[0].endswith('.csv'):
            raise ValueError('cashflow_archive_layout')
        with z.open(names[0]) as stream:
            seen = 0
            for raw in csv.reader(io.TextIOWrapper(stream)):
                if not raw[0].isdigit():
                    if seen or raw[0] != 'open_time':
                        raise ValueError('cashflow_archive_header')
                    continue
                stamp = int(raw[0])
                stamp = stamp // 1000 if stamp >= 10**14 else stamp
                close_stamp = int(raw[6])
                close_stamp = close_stamp // 1000 if close_stamp >= 10**14 else close_stamp
                values = [float(x) for x in raw[1:5]]
                if (stamp != first + seen * interval_ms or close_stamp != stamp + interval_ms - 1
                        or any(not math.isfinite(x) or x <= 0 for x in values)
                        or not values[2] <= min(values[0], values[3]) <= max(values[0], values[3]) <= values[1]):
                    raise ValueError('cashflow_bar_calendar_or_ohlc')
                yield stamp, values
                seen += 1
            if seen != count:
                raise ValueError('cashflow_missing_calendar_bar')


def reduce_prices(body, month, kind, needed_minutes):
    daily, selected = {}, {}
    interval = 60000 if kind == 'mark' else 3600000
    for stamp, (opening, high, low, close) in bars(body, month, interval):
        when = dt.datetime.fromtimestamp(stamp / 1000, UTC)
        day = when.date().isoformat()
        row = daily.setdefault(day, {})
        if kind == 'mark':
            highs = row.setdefault('mark_hour_high', [0.0] * 24)
            highs[when.hour] = max(highs[when.hour], high)
            row['mark_close'] = close
            if stamp in needed_minutes:
                selected[str(stamp)] = {'open': opening, 'low': low, 'high': high}
        else:
            if when.hour in (1, 23):
                row[f'{kind}_open{when.hour}'] = opening
            row[kind + '_close'] = close
    return daily, selected


def acquire(contract, out: Path):
    require_storage(out)
    if out.exists():
        raise ValueError('immutable_cashflow_input_exists')
    old_root = Path(contract['information_root'])
    verify_manifest(old_root, expected_hash=contract['information_manifest_sha256'])
    cache = Path(contract['btc_cache'])
    if file_hash(cache) != contract['btc_cache_sha256']:
        raise ValueError('cashflow_original_cache_changed')
    info = json.loads((old_root / 'information.json').read_text())
    first, last = contract['evaluation']['first'], contract['evaluation']['last']
    events = [e for e in info['funding_events']['BTCUSDT'] if first <= e['day'] <= last]
    for e in events:
        when = dt.datetime.fromtimestamp(e['timestamp_ms'] / 1000, UTC)
        if ((when.day in (1, 2) and when.hour == 1) or (e['day'] == last and when.hour == 23)):
            raise ValueError('cashflow_funding_collides_with_declared_trade_hour')
    for day in (dt.date.fromisoformat(first) + dt.timedelta(days=i) for i in range((dt.date.fromisoformat(last) - dt.date.fromisoformat(first)).days + 1)):
        if not info['funding']['BTCUSDT'].get(day.isoformat(), {}).get('complete'):
            raise ValueError('cashflow_incomplete_funding_day')
    needed = {m for e in events for m in (e['timestamp_ms'] // 60000 * 60000 - 60000, e['timestamp_ms'] // 60000 * 60000)}
    out.mkdir(parents=True)
    (out / 'archives').mkdir()
    (out / 'checksums').mkdir()

    def task(item):
        month, kind = item
        interval = '1m' if kind == 'mark' else '1h'
        part = 'spot/monthly/klines' if kind == 'spot' else 'futures/um/monthly/' + ('markPriceKlines' if kind == 'mark' else 'klines')
        name = f'BTCUSDT-{interval}-{month}.zip'
        url = f'https://data.binance.vision/data/{part}/BTCUSDT/{interval}/{name}'
        checksum = fetch(url + '.CHECKSUM')
        body = fetch(url)
        sha = hashlib.sha256(body).hexdigest()
        if sha != checksum.decode().split()[0]:
            raise ValueError('cashflow_official_checksum_failed')
        filename = kind + '-' + name
        (out / 'archives' / filename).write_bytes(body)
        (out / 'checksums' / (filename + '.CHECKSUM')).write_bytes(checksum)
        daily, marks = reduce_prices(body, month, kind, needed)
        return daily, marks, {'kind': kind, 'month': month, 'url': url, 'sha256': sha, 'file': 'archives/' + filename,
                             'observed_at': dt.datetime.now(UTC).isoformat()}

    jobs = [(m, k) for m in months(contract['acquisition']['first_month'], contract['acquisition']['last_month']) for k in ('spot', 'perp', 'mark')]
    prices, minute, provenance = {}, {}, []
    with concurrent.futures.ThreadPoolExecutor(max_workers=contract['acquisition']['workers']) as pool:
        for daily, marks, record in pool.map(task, jobs):
            for day, values in daily.items():
                prices.setdefault(day, {}).update(values)
            if set(minute) & set(marks):
                raise ValueError('cashflow_duplicate_mark_minute')
            minute.update(marks)
            provenance.append(record)
            print('qualified archive', record['kind'], record['month'], flush=True)
    enriched = []
    for event in events:
        stamp = event['timestamp_ms'] // 60000 * 60000
        pair = [minute[str(stamp - 60000)], minute[str(stamp)]]
        enriched.append({**event, 'mark_proxy': pair[1]['open'], 'mark_lower': min(r['low'] for r in pair),
                         'mark_upper': max(r['high'] for r in pair)})
    prices = {day: row for day, row in sorted(prices.items()) if first <= day <= last}
    cached = json.loads(cache.read_text())['rows']
    for day, row in prices.items():
        if abs(row['spot_close'] - cached[day][0]) > 1e-8 or abs(row['spot_close'] - info['flow']['BTCUSDT'][day]['close']) > 1e-8:
            raise ValueError('cashflow_spot_close_bridge_failed')
        if len(row['mark_hour_high']) != 24 or min(row['mark_hour_high']) <= 0:
            raise ValueError('cashflow_hourly_mark_missing')
    write_json(out / 'prices.json', prices)
    write_json(out / 'funding.json', enriched)
    write_json(out / 'provenance.json', {'archives': provenance, 'spot_close_bridge_rows': len(prices),
        'information_manifest_sha256': contract['information_manifest_sha256'], 'btc_cache_sha256': contract['btc_cache_sha256'],
        'mark_status': 'minute proxy with signed lower/upper bounds; not exact exchange receipts', 'vintage_status': 'current official historical archives, publication vintage unverified',
        'funding_rest_probe': '2026-10-05 WSL public fapi request failed Network is unreachable; no credentials or alternate routing',
        'research_only': True, 'orders_authorized': False})
    write_json(out / 'manifest.json', {'research_only': True, 'orders_authorized': False,
        'files': {str(p.relative_to(out)): file_hash(p) for p in sorted(out.rglob('*')) if p.is_file()}})
    return {'days': len(prices), 'events': len(enriched), 'archives': len(jobs), 'manifest_sha256': file_hash(out / 'manifest.json')}
