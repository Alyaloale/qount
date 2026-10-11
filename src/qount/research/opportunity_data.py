"""Immutable official public archives and isolated WSL/E event-label runs."""
from __future__ import annotations

import calendar
import concurrent.futures
import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

from qount.research.opportunity_screen import HOUR, UTC, evaluate, read_contract

STORAGE = Path('/mnt/e/qount_data/qount/artifacts/short_horizon_opportunity')
SOURCE_FILES = ('src/qount/__init__.py', 'src/qount/research/__init__.py',
                'src/qount/research/opportunity_screen.py', 'src/qount/research/opportunity_data.py',
                'src/qount/research_data/__init__.py', 'src/qount/research_data/event_stats.py',
                'scripts/research/opportunity_screen.py', 'tests/test_opportunity_screen.py',
                'config/short-horizon-opportunity-20261009.json')


def source_files(repo):
    # research_data's stable __init__ eagerly imports public support modules.
    # Preserve their real imports; bind all public Python sources in the delivery.
    return sorted(set(SOURCE_FILES) | {p.relative_to(repo).as_posix()
                                      for p in (repo / 'src/qount').rglob('*.py')})


def runtime_source_binding(*, repo=None, expected=None):
    """Bind the modules actually imported, rather than an arbitrary --repo tree."""
    for name, module in list(sys.modules.items()):
        if not (name == 'qount' or name.startswith('qount.')):
            continue
        filename = getattr(module, '__file__', None)
        if filename is None or not filename.endswith('.py'):
            continue
        path = Path(filename).resolve()
        relative = 'src/' + name.replace('.', '/')
        relative += '/__init__.py' if path.name == '__init__.py' else '.py'
        if repo is not None and path != (repo / relative).resolve():
            raise ValueError('opportunity_runtime_not_from_bound_repo:' + name)
        if expected is not None and (relative not in expected or sha(path) != expected[relative]):
            raise ValueError('opportunity_runtime_source_hash_mismatch:' + name)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def storage(out):
    if sys.platform != 'linux' or not os.path.ismount('/mnt/e') or not out.resolve().is_relative_to(STORAGE):
        raise ValueError('opportunity_wsl_mounted_e_required')


def freeze(root):
    inventory = {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob('*'))
                 if p.is_file() and p != root / 'manifest.json'}
    write_json(root / 'manifest.json', inventory)
    return sha(root / 'manifest.json')


def verify_manifest(root):
    expected = json.loads((root / 'manifest.json').read_text())
    actual = {p.relative_to(root).as_posix(): sha(p) for p in root.rglob('*')
              if p.is_file() and p != root / 'manifest.json'}
    if not expected or expected != actual:
        raise ValueError('opportunity_manifest_mismatch')
    return expected


def months(first, last):
    year, month = map(int, first.split('-'))
    while f'{year:04}-{month:02}' <= last:
        yield f'{year:04}-{month:02}'
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def rows(body):
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        if len(z.namelist()) != 1 or not z.namelist()[0].endswith('.csv'):
            raise ValueError('opportunity_archive_layout_invalid')
        return list(csv.reader(io.StringIO(z.read(z.namelist()[0]).decode('utf-8-sig'))))


def parse_prices(body, month, kind):
    """Reject invalid observations; report gaps, never fill/interpolate rows."""
    parsed, rejected = {}, []
    raw = rows(body)
    for n, row in enumerate(raw, 1):
        if n == 1 and row[0] in ('open_time', 'openTime'):
            continue
        try:
            t, closed = int(row[0]), int(row[6])
            t = t // 1000 if t >= 10**14 else t
            closed = closed // 1000 if closed >= 10**14 else closed
            when = dt.datetime.fromtimestamp(t / 1000, UTC)
            o, h, l, c = map(float, row[1:5])
            if (when.strftime('%Y-%m') != month or t % HOUR or closed != t + HOUR - 1
                    or any(not math.isfinite(v) or v <= 0 for v in (o, h, l, c))
                    or not l <= min(o, c) <= max(o, c) <= h):
                raise ValueError('invalid_ohlc_or_calendar')
            item = {'open': o, 'high': h, 'low': l, 'close': c}
            if kind == 'bars':
                q, buy = float(row[7]), float(row[10])
                if not math.isfinite(q) or not math.isfinite(buy) or q <= 0 or not 0 <= buy <= q:
                    raise ValueError('invalid_flow_or_volume')
                item.update(quote=q, buy_quote=buy)
        except (ValueError, IndexError, OverflowError) as error:
            rejected.append({'row': n, 'reason': str(error)[:90]})
            continue
        if t in parsed:
            raise ValueError('opportunity_duplicate_hour')
        parsed[t] = item
    year, m = map(int, month.split('-'))
    first = int(dt.datetime(year, m, 1, tzinfo=UTC).timestamp() * 1000)
    expected = [first + i * HOUR for i in range(calendar.monthrange(year, m)[1] * 24)]
    missing = [t for t in expected if t not in parsed]
    return parsed, {'raw_csv_rows': len(raw), 'valid_hours': len(parsed),
                    'rejected_rows': rejected, 'missing_hours': missing, 'imputed_rows': 0}


def parse_funding(body, month):
    raw = rows(body)
    if not raw or raw[0] != ['calc_time', 'funding_interval_hours', 'last_funding_rate']:
        raise ValueError('opportunity_funding_schema_invalid')
    result = []
    for row in raw[1:]:
        t, interval, rate = int(row[0]), float(row[1]), float(row[2])
        when = dt.datetime.fromtimestamp(t / 1000, UTC)
        if (when.strftime('%Y-%m') != month or not math.isfinite(interval) or not 0 < interval <= 24
                or not math.isfinite(rate) or abs(rate) > 1):
            raise ValueError('opportunity_funding_value_invalid')
        result.append({'timestamp_ms': t, 'interval_hours': interval, 'rate': rate})
    if not result or len({e['timestamp_ms'] for e in result}) != len(result):
        raise ValueError('opportunity_funding_empty_or_duplicate')
    return sorted(result, key=lambda e: e['timestamp_ms']), {'raw_csv_rows': len(raw), 'funding_events': len(result)}


def fetch(url):
    prefix = 'https://data.binance.vision/data/futures/um/monthly/'
    if not url.startswith(prefix):
        raise ValueError('opportunity_public_source_not_allowed')
    request = urllib.request.Request(url, headers={'User-Agent': 'qount-public-research/1.0'})
    with urllib.request.urlopen(request, timeout=30) as response:
        if not response.url.startswith(prefix):
            raise ValueError('opportunity_redirect_not_allowed')
        body = response.read(10_000_001)
        if len(body) > 10_000_000:
            raise ValueError('opportunity_archive_size_unexpected')
        return body


def archive_identity(symbol, month, kind):
    if kind == 'funding':
        filename, subpath = f'{symbol}-fundingRate-{month}.zip', f'fundingRate/{symbol}'
    else:
        filename = f'{symbol}-1h-{month}.zip'
        subpath = f'{"klines" if kind == "bars" else "markPriceKlines"}/{symbol}/1h'
    name = kind + '-' + filename
    return name, f'https://data.binance.vision/data/futures/um/monthly/{subpath}/{filename}'


def load_archives(root, contract, provenance):
    """Reparse raw checksum-bound inputs, independent of derived JSON payloads."""
    data = {s: {'bars': {}, 'marks': {}, 'funding': []} for s in contract['symbols']}
    expected_tasks = {(s, m, k) for s in contract['symbols']
                      for m in months(contract['acquisition']['first_month'], contract['acquisition']['last_month'])
                      for k in ('bars', 'marks', 'funding')}
    seen = set()
    for record in provenance:
        symbol, month, kind = record['symbol'], record['month'], record['kind']
        task = symbol, month, kind
        if task not in expected_tasks or task in seen:
            raise ValueError('opportunity_input_inventory_invalid')
        seen.add(task)
        name, url = archive_identity(*task)
        if record['file'] != 'archives/' + name or record['url'] != url:
            raise ValueError('opportunity_source_identity_mismatch')
        body = (root / record['file']).read_bytes()
        checksum = (root / 'checksums' / (name + '.CHECKSUM')).read_text().split()[0]
        if hashlib.sha256(body).hexdigest() != checksum or checksum != record['sha256']:
            raise ValueError('opportunity_official_checksum_mismatch')
        values, audit = parse_funding(body, month) if kind == 'funding' else parse_prices(body, month, kind)
        if record['audit'] != audit:
            raise ValueError('opportunity_archive_audit_mismatch')
        target = data[symbol][kind]
        if kind == 'funding':
            target.extend(values)
        else:
            if set(target) & set(values):
                raise ValueError('opportunity_cross_archive_duplicate')
            target.update(values)
    if seen != expected_tasks:
        raise ValueError('opportunity_incomplete_archive_inventory')
    for item in data.values():
        item['funding'].sort(key=lambda e: e['timestamp_ms'])
    return data


def cached_archives(roots):
    """Index manifest-listed ZIP/checksum pairs only; no cache mutates in place."""
    result = {}
    for root in roots:
        value = json.loads((root / 'manifest.json').read_text())
        files = value.get('files', value)
        manifest_hash = sha(root / 'manifest.json')
        for name, digest in files.items():
            if not name.startswith('archives/') or not name.endswith('.zip'):
                continue
            checksum = 'checksums/' + Path(name).name + '.CHECKSUM'
            if checksum not in files:
                continue
            if sha(root / name) != digest or sha(root / checksum) != files[checksum]:
                raise ValueError('opportunity_cache_hash_mismatch')
            result.setdefault(Path(name).name, (root / name, root / checksum, manifest_hash))
    return result


def acquire(*, contract_path, out, reuse_roots=()):
    storage(out)
    c = read_contract(contract_path)
    out.mkdir(parents=True, exist_ok=False)
    (out / 'archives').mkdir()
    (out / 'checksums').mkdir()
    write_json(out / 'contract.json', c)
    tasks = [(s, m, k) for s in c['symbols']
             for m in months(c['acquisition']['first_month'], c['acquisition']['last_month'])
             for k in ('bars', 'marks', 'funding')]
    records = []
    cached = cached_archives(reuse_roots)
    def download(task):
        s, m, k = task
        name, url = archive_identity(*task)
        canonical = url.rsplit('/', 1)[1]
        alternate = ('perp-' + canonical) if k == 'bars' else name
        # Bare hourly filenames collide across klines and markPriceKlines.
        match = cached.get(name) or (cached.get(canonical) if k == 'funding' else None) or cached.get(alternate)
        if match is None:
            body, checksum = fetch(url), fetch(url + '.CHECKSUM')
            cache_binding = None
        else:
            body = match[0].read_bytes()
            # Prove kind/URL using the EXPECTED endpoint, not a cached filename.
            checksum = fetch(url + '.CHECKSUM')
            cache_binding = {'root': str(match[0].parents[1]), 'manifest_sha256': match[2],
                             'original_observed_at': None, 'fresh_download_claimed': False}
        digest = hashlib.sha256(body).hexdigest()
        if digest != checksum.decode().split()[0]:
            raise ValueError('opportunity_published_checksum_failed')
        (out / 'archives' / name).write_bytes(body)
        (out / 'checksums' / (name + '.CHECKSUM')).write_bytes(checksum)
        _, audit = parse_funding(body, m) if k == 'funding' else parse_prices(body, m, k)
        return {'symbol': s, 'month': m, 'kind': k, 'file': 'archives/' + name, 'url': url,
                'sha256': digest, 'observed_at': dt.datetime.now(UTC).isoformat() if match is None else None,
                'verified_at': dt.datetime.now(UTC).isoformat(),
                'checksum_observed_at': dt.datetime.now(UTC).isoformat(),
                'checksum_url': url + '.CHECKSUM', 'source_identity_qualified': True,
                'cache_binding': cache_binding, 'audit': audit}
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=c['acquisition']['workers'])
    futures = [pool.submit(download, task) for task in tasks]
    try:
        for future in concurrent.futures.as_completed(futures):
            records.append(future.result())
            if len(records) % 30 == 0:
                print(f'official_archives_qualified={len(records)}/{len(tasks)}', flush=True)
    except Exception as error:
        # Cancel undispatched reads; only bounded already-active downloads finish.
        pool.shutdown(wait=True, cancel_futures=True)
        write_json(out / 'acquisition-failure.json', {'type': type(error).__name__, 'reason': str(error)[:300],
                                                    'returns_run': False, 'automatic_restart': False})
        freeze(out)
        raise
    else:
        pool.shutdown(wait=True)
    records.sort(key=lambda r: (r['symbol'], r['month'], r['kind']))
    write_json(out / 'provenance.json', records)
    load_archives(out, c, records)
    result = {'archives': len(records), 'raw_csv_rows': sum(r['audit']['raw_csv_rows'] for r in records),
              'cache_reused_archives': sum(r['cache_binding'] is not None for r in records),
              'missing_price_hours': sum(len(r['audit'].get('missing_hours', [])) for r in records),
              'invalid_price_rows': sum(len(r['audit'].get('rejected_rows', [])) for r in records),
              'imputed_rows': 0, 'qualification': 'observed_data_gaps_explicit_event_paths_checked_at_run',
              'research_only': True, 'orders_authorized': False, 'returns_run': False}
    write_json(out / 'acquisition-summary.json', result)
    return {**result, 'manifest_sha256': freeze(out)}


def requalify(*, contract_path, input_root, out):
    """Reauthenticate every expected kind/URL by fresh official checksums.

    Source-only repair before economic labels. Existing archives and receipts
    remain immutable; current checksum drift fails closed without redownload.
    """
    storage(out)
    c = read_contract(contract_path)
    verify_manifest(input_root)
    if json.loads((input_root / 'contract.json').read_text()) != c:
        raise ValueError('opportunity_requalification_contract_mismatch')
    prior = json.loads((input_root / 'provenance.json').read_text())
    load_archives(input_root, c, prior)
    index = {(r['symbol'], r['month'], r['kind']): r for r in prior}
    tasks = [(s, m, k) for s in c['symbols']
             for m in months(c['acquisition']['first_month'], c['acquisition']['last_month'])
             for k in ('bars', 'marks', 'funding')]
    if set(index) != set(tasks) or len(prior) != len(tasks):
        raise ValueError('opportunity_requalification_inventory_invalid')
    old_hash = sha(input_root / 'manifest.json')
    out.mkdir(parents=True, exist_ok=False)
    (out / 'archives').mkdir()
    (out / 'checksums').mkdir()
    write_json(out / 'contract.json', c)
    records = []
    def qualify(task):
        name, url = archive_identity(*task)
        r = index[task]
        checksum = fetch(url + '.CHECKSUM')
        body = (input_root / 'archives' / name).read_bytes()
        if hashlib.sha256(body).hexdigest() != checksum.decode().split()[0]:
            raise ValueError('opportunity_expected_endpoint_checksum_mismatch:' + name)
        shutil.copyfile(input_root / 'archives' / name, out / 'archives' / name)
        (out / 'checksums' / (name + '.CHECKSUM')).write_bytes(checksum)
        return {**r, 'url': url, 'file': 'archives/' + name, 'observed_at': None,
                'archive_observed_at': None, 'checksum_observed_at': dt.datetime.now(UTC).isoformat(),
                'checksum_url': url + '.CHECKSUM', 'verified_at': dt.datetime.now(UTC).isoformat(),
                'cache_binding': {'root': str(input_root), 'manifest_sha256': old_hash,
                                  'prior_record': {k: r[k] for k in ('symbol', 'month', 'kind', 'file', 'sha256')},
                                  'fresh_download_claimed': False},
                'source_identity_qualified': True}
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=c['acquisition']['workers'])
    futures = [pool.submit(qualify, task) for task in tasks]
    try:
        for future in concurrent.futures.as_completed(futures):
            records.append(future.result())
            if len(records) % 60 == 0:
                print(f'expected_endpoint_checksums_qualified={len(records)}/{len(tasks)}', flush=True)
    except Exception as error:
        pool.shutdown(wait=True, cancel_futures=True)
        write_json(out / 'qualification-failure.json', {'type': type(error).__name__, 'reason': str(error)[:300],
                                                      'returns_run': False, 'automatic_restart': False})
        freeze(out)
        raise
    else:
        pool.shutdown(wait=True)
    records.sort(key=lambda r: (r['symbol'], r['month'], r['kind']))
    write_json(out / 'provenance.json', records)
    load_archives(out, c, records)
    verify_manifest(input_root)
    if sha(input_root / 'manifest.json') != old_hash:
        raise ValueError('opportunity_requalification_source_changed')
    result = {'expected_endpoint_checksums_qualified': len(records), 'research_only': True,
              'orders_authorized': False, 'returns_run': False, 'fresh_archive_downloads': 0,
              'source_identity_qualified': True, 'prior_input_root': str(input_root),
              'prior_input_manifest_sha256': old_hash}
    write_json(out / 'qualification-summary.json', result)
    return {**result, 'manifest_sha256': freeze(out)}


def run(*, contract_path, input_root, out, repo):
    storage(out)
    c = read_contract(contract_path)
    verify_manifest(input_root)
    if json.loads((input_root / 'contract.json').read_text()) != c:
        raise ValueError('opportunity_input_contract_mismatch')
    records = json.loads((input_root / 'provenance.json').read_text())
    if any(r.get('source_identity_qualified') is not True for r in records):
        raise ValueError('opportunity_expected_endpoint_qualification_required')
    if out.exists():
        raise ValueError('immutable_opportunity_output_exists')
    source_hashes = {name: sha(repo / name) for name in source_files(repo)}
    runtime_source_binding(repo=repo, expected=source_hashes)
    if sha(contract_path) != source_hashes['config/short-horizon-opportunity-20261009.json']:
        raise ValueError('opportunity_source_contract_mismatch')
    out.mkdir(parents=True)
    (out / 'source').mkdir()
    for name in source_hashes:
        p = out / 'source' / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes((repo / name).read_bytes())
    write_json(out / 'source-hashes.json', source_hashes)
    write_json(out / 'contract.json', c)
    write_json(out / 'input-binding.json', {'root': str(input_root), 'manifest_sha256': sha(input_root / 'manifest.json')})
    # Freeze provenance before any economic label is produced.
    write_json(out / 'pre-run.json', {'source_hashes': source_hashes,
                                    'input_manifest_sha256': sha(input_root / 'manifest.json'),
                                    'frozen_at': dt.datetime.now(UTC).isoformat(), 'results_produced': False})
    data = load_archives(input_root, c, json.loads((input_root / 'provenance.json').read_text()))
    result = evaluate(data, c)
    write_json(out / 'events.json', result.pop('events'))
    write_json(out / 'summary.json', result)
    if source_hashes != {name: sha(repo / name) for name in source_files(repo)}:
        raise ValueError('opportunity_source_changed_during_run')
    return {**result, 'manifest_sha256': freeze(out)}


def verify(*, out):
    inventory = verify_manifest(out)
    binding = json.loads((out / 'input-binding.json').read_text())
    inputs = Path(binding['root'])
    verify_manifest(inputs)
    if sha(inputs / 'manifest.json') != binding['manifest_sha256']:
        raise ValueError('opportunity_input_binding_changed')
    source = json.loads((out / 'source-hashes.json').read_text())
    if any(sha(out / 'source' / name) != value for name, value in source.items()):
        raise ValueError('opportunity_frozen_source_changed')
    runtime_source_binding(expected=source)
    c = read_contract(out / 'contract.json')
    if json.loads((inputs / 'contract.json').read_text()) != c:
        raise ValueError('opportunity_verification_contract_mismatch')
    data = load_archives(inputs, c, json.loads((inputs / 'provenance.json').read_text()))
    saved = json.loads((out / 'events.json').read_text())
    summary = json.loads((out / 'summary.json').read_text())
    oracle_errors, paths, cashflows = [], 0, 0
    for key, events in saved.items():
        cost = int(key.split('/')[1].removeprefix('cost')) / 10000
        for e in events:
            if not e['qualified']:
                continue
            paths += 1
            item = data[e['symbol']]
            entry, exit_ = e['entry_ms'], e['exit_ms']
            price = item['bars'][entry]['open']
            gross = item['bars'][exit_]['open'] / price - 1
            fees = cost * (1 + item['bars'][exit_]['open'] / price)
            lower, upper, proxy = [], [], []
            held = [f for f in item['funding'] if entry <= f['timestamp_ms'] < exit_]
            for f in held:
                m = item['marks'][f['timestamp_ms'] // HOUR * HOUR]
                v = [f['rate'] * m[k] / price for k in ('low', 'high')]
                lower.append(min(v)); upper.append(max(v)); proxy.append(f['rate'] * m['open'] / price)
                cashflows += 1
            expected = {'gross_return': gross, 'total_cost': fees, 'funding_paid_proxy': sum(proxy),
                        'net_proxy': gross - fees - sum(proxy), 'net_lower': gross - fees - sum(upper),
                        'net_upper': gross - fees - sum(lower)}
            if any(abs(e[k] - v) > 1e-12 for k, v in expected.items()) or len(held) != len(e['payments']):
                oracle_errors.append(key + ':' + str(entry))
    replay = evaluate(data, c)
    if replay.pop('events') != saved or replay != summary or oracle_errors:
        raise ValueError('opportunity_verification_failed')
    return {'verified': True, 'result_manifest_sha256': sha(out / 'manifest.json'),
            'input_manifest_sha256': binding['manifest_sha256'], 'output_files': len(inventory),
            'raw_archives_reparsed': len(json.loads((inputs / 'provenance.json').read_text())),
            'qualified_cell_event_paths': paths, 'held_cell_funding_events': cashflows,
            'cashflow_oracle_errors': 0, 'deterministic_signal_and_summary_reproduction': True,
            'safe_leverage_certified': False, 'promotion_evidence': False}
