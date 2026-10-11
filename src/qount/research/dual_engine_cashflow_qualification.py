"""Coverage audit only: no strategy replay, payments, returns or ranking."""
from __future__ import annotations

import calendar
import concurrent.futures
import csv
import datetime as dt
import hashlib
import io
import json
import math
import shutil
import zipfile
from pathlib import Path

from qount.research.dual_engine_cashflow_data import UTC
from qount.research.dual_engine_execution_study import verify_manifest
from qount.research.dual_engine_expansion import require_storage
from qount.research.dual_engine_information_data import fetch, months
from qount.research.dual_engine_optimization import file_hash, write_json


def audit_archive(body, month, kind, contract, funding_minutes):
    interval = 60000 if kind == 'mark' else 3600000
    year, number = map(int, month.split('-'))
    first = int(dt.datetime(year, number, 1, tzinfo=UTC).timestamp() * 1000)
    calendar_slots = set(range(first, first + calendar.monthrange(year, number)[1] * 86400000, interval))
    evaluation = contract['evaluation']
    seen, malformed, invalid, nontraded_quotes = set(), [], [], []
    closes = {}
    count = duplicate = 0

    def scope(t):
        when = dt.datetime.fromtimestamp(t / 1000, UTC)
        day = when.date().isoformat()
        in_eval = evaluation['first'] <= day <= evaluation['last']
        return {'inside_evaluation': in_eval, 'required_funding_minute': kind == 'mark' and t in funding_minutes,
                'required_fill_quote': kind != 'mark' and in_eval and ((when.day in (1, 2) and when.hour == 1) or (day == evaluation['last'] and when.hour == 23)),
                'daily_nav_hour': in_eval and when.hour == 23}

    with zipfile.ZipFile(io.BytesIO(body)) as z:
        names = z.namelist()
        if len(names) != 1 or not names[0].endswith('.csv'):
            raise ValueError('cashflow_qualification_archive_layout')
        with z.open(names[0]) as stream:
            for raw in csv.reader(io.TextIOWrapper(stream)):
                if not raw[0].isdigit():
                    continue
                t, end = int(raw[0]), int(raw[6])
                t = t // 1000 if t >= 10**14 else t
                end = end // 1000 if end >= 10**14 else end
                opening, high, low, close = map(float, raw[1:5])
                flags = scope(t)
                duplicate += t in seen
                seen.add(t)
                if end != t + interval - 1:
                    malformed.append({'timestamp_ms': t, 'end_ms': end, **flags})
                if (t not in calendar_slots or any(not math.isfinite(v) or v <= 0 for v in (opening, high, low, close))
                        or not low <= min(opening, close) <= max(opening, close) <= high):
                    invalid.append({'timestamp_ms': t, **flags})
                if flags['required_fill_quote'] and float(raw[5]) <= 0:
                    nontraded_quotes.append({'timestamp_ms': t, **flags})
                when = dt.datetime.fromtimestamp(t / 1000, UTC)
                if kind == 'spot' and evaluation['first'] <= when.date().isoformat() <= evaluation['last'] and when.hour == 23:
                    closes[when.date().isoformat()] = close
                count += 1
    missing = sorted(calendar_slots - seen)
    missing_scope = [(t, scope(t)) for t in missing]
    missing_hours = {t // 3600000 for t, flags in missing_scope if flags['inside_evaluation']} if kind == 'mark' else set()
    bad_required = [x for x in malformed + invalid if x['required_funding_minute'] or x['required_fill_quote']]
    report = {'kind': kind, 'month': month, 'raw_rows': count, 'duplicate_rows': duplicate,
        'missing_slots': len(missing), 'missing_inside_evaluation': sum(f['inside_evaluation'] for _, f in missing_scope),
        'missing_required_funding_minutes': sum(f['required_funding_minute'] for _, f in missing_scope),
        'missing_required_fill_quotes': sum(f['required_fill_quote'] for _, f in missing_scope),
        'missing_daily_nav_hours': sum(f['daily_nav_hour'] and (kind != 'mark' or (t // 60000) % 60 == 59) for t, f in missing_scope),
        'incomplete_mark_stress_hours': len(missing_hours), 'noncanonical_close_rows': len(malformed),
        'invalid_ohlc_or_calendar_rows': len(invalid), 'malformed_required_observations': len(bad_required),
        'zero_volume_required_fill_quotes': len(nontraded_quotes),
        'missing_sample_utc': [dt.datetime.fromtimestamp(t / 1000, UTC).isoformat() for t in missing[:30]],
        'malformed_sample': (malformed + invalid + nontraded_quotes)[:30],
        'strict_original_gate_passed': not missing and not malformed and not invalid and not duplicate}
    return report, closes


def run_coverage_audit(*, contract_path: Path, prior_partial_root: Path, out: Path):
    require_storage(out)
    if out.exists():
        raise ValueError('immutable_cashflow_coverage_audit_exists')
    c = json.loads(contract_path.read_text())
    verify_manifest(Path(c['information_root']), expected_hash=c['information_manifest_sha256'])
    partial = json.loads((prior_partial_root / 'failure-manifest.json').read_text())
    for name, h in partial['files'].items():
        if file_hash(prior_partial_root / name) != h:
            raise ValueError('cashflow_partial_archive_changed')
    info = json.loads((Path(c['information_root']) / 'information.json').read_text())
    events = [e for e in info['funding_events']['BTCUSDT'] if c['evaluation']['first'] <= e['day'] <= c['evaluation']['last']]
    needed = {v for e in events for v in (e['timestamp_ms'] // 60000 * 60000 - 60000, e['timestamp_ms'] // 60000 * 60000)}
    out.mkdir(parents=True)
    (out / 'archives').mkdir()
    (out / 'checksums').mkdir()
    shutil.copyfile(contract_path, out / 'contract.json')
    shutil.copyfile(__file__, out / 'coverage-auditor.py')
    jobs = [(m, k) for m in months(c['acquisition']['first_month'], c['acquisition']['last_month']) for k in ('spot', 'perp', 'mark')]

    def task(item):
        month, kind = item
        interval = '1m' if kind == 'mark' else '1h'
        name = f'{kind}-BTCUSDT-{interval}-{month}.zip'
        part = 'spot/monthly/klines' if kind == 'spot' else 'futures/um/monthly/' + ('markPriceKlines' if kind == 'mark' else 'klines')
        url = f'https://data.binance.vision/data/{part}/BTCUSDT/{interval}/BTCUSDT-{interval}-{month}.zip'
        reused = (prior_partial_root / 'archives' / name).exists()
        try:
            if reused:
                body = (prior_partial_root / 'archives' / name).read_bytes()
                checksum = (prior_partial_root / 'checksums' / (name + '.CHECKSUM')).read_bytes()
            else:
                checksum, body = fetch(url + '.CHECKSUM'), fetch(url)
            h = hashlib.sha256(body).hexdigest()
            if checksum.decode().split()[0] != h:
                raise ValueError('cashflow_coverage_checksum_failed')
            (out / 'archives' / name).write_bytes(body)
            (out / 'checksums' / (name + '.CHECKSUM')).write_bytes(checksum)
            report, closes = audit_archive(body, month, kind, c, needed)
            return {**report, 'url': url, 'sha256': h, 'reused_partial_archive': reused, 'observed_at': dt.datetime.now(UTC).isoformat(), 'source_status': 'official_checksum_verified'}, closes
        except Exception as exc:
            return {'kind': kind, 'month': month, 'url': url, 'source_status': 'unqualified', 'error': type(exc).__name__ + ': ' + str(exc)}, {}

    reports, closes = [], {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for report, daily in pool.map(task, jobs):
            reports.append(report)
            closes.update(daily)
            print(report['kind'], report['month'], report['source_status'], flush=True)
    if file_hash(Path(c['btc_cache'])) != c['btc_cache_sha256']:
        raise ValueError('cashflow_original_cache_changed')
    cached = json.loads(Path(c['btc_cache']).read_text())['rows']
    differences = [d for d, v in closes.items() if abs(v - cached[d][0]) > 1e-8 or abs(v - info['flow']['BTCUSDT'][d]['close']) > 1e-8]
    counts = {name: sum(r.get(name, 0) for r in reports) for name in ('raw_rows', 'missing_slots', 'missing_inside_evaluation',
        'missing_required_funding_minutes', 'missing_required_fill_quotes', 'missing_daily_nav_hours', 'incomplete_mark_stress_hours',
        'noncanonical_close_rows', 'invalid_ohlc_or_calendar_rows', 'malformed_required_observations', 'zero_volume_required_fill_quotes')}
    result = {'research_only': True, 'orders_authorized': False, 'promotion_evidence': False,
        'role': 'complete planned source coverage audit, not a replay or data imputation', 'planned_archives': len(jobs),
        'checksum_qualified_archives': sum(r['source_status'] == 'official_checksum_verified' for r in reports),
        'unqualified_sources': sum(r['source_status'] != 'official_checksum_verified' for r in reports), 'counts': counts,
        'spot_close_bridge_days': len(closes), 'spot_close_bridge_differences': differences, 'archives': reports,
        'candidate_trials_consumed': 0, 'curve_count': 0, 'economic_cashflow_conclusion': None,
        'original_qualification_gate_changed': False, 'strategy_clock_or_windows_changed': False}
    write_json(out / 'coverage-audit.json', result)
    write_json(out / 'manifest.json', {'research_only': True, 'orders_authorized': False,
        'files': {str(p.relative_to(out)): file_hash(p) for p in sorted(out.rglob('*')) if p.is_file()}})
    return result
