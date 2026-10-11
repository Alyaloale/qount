"""Recover absent monthly marks only from checksum-qualified observed daily CSVs."""
from __future__ import annotations

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
from qount.research.dual_engine_information_data import fetch
from qount.research.dual_engine_optimization import file_hash, write_json


def raw_marks(body):
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        if len(z.namelist()) != 1:
            raise ValueError('mark_repair_zip_layout')
        with z.open(z.namelist()[0]) as stream:
            for raw in csv.reader(io.TextIOWrapper(stream)):
                if raw[0].isdigit():
                    yield int(raw[0]), tuple(float(v) for v in raw[1:5]), int(raw[6])


def qualify_day(body, day, monthly):
    start = int(dt.datetime.combine(dt.date.fromisoformat(day), dt.time(), UTC).timestamp() * 1000)
    rows = list(raw_marks(body))
    if not rows or len(rows) > 1440:
        raise ValueError('mark_repair_daily_calendar')
    overlap = added = 0
    previous = start - 60000
    for stamp, values, end in rows:
        opening, high, low, close = values
        if (not start <= stamp < start + 86400000 or (stamp - start) % 60000 or stamp <= previous
                or end != stamp + 59999
                or any(not math.isfinite(v) or v <= 0 for v in values)
                or not low <= min(opening, close) <= max(opening, close) <= high):
            raise ValueError('mark_repair_daily_calendar_or_ohlc')
        if stamp in monthly:
            if any(abs(x - y) > 1e-8 for x, y in zip(values, monthly[stamp], strict=True)):
                raise ValueError('mark_repair_daily_monthly_overlap_differs')
            overlap += 1
        else:
            added += 1
        previous = stamp
    return {'rows': len(rows), 'overlap_rows': overlap, 'added_observed_rows': added,
            'remaining_missing_minutes': 1440 - len(rows), 'day_complete': len(rows) == 1440, 'imputed_rows': 0}


def repair_mark_inputs(*, coverage_root: Path, gap_plan: Path, out: Path):
    require_storage(out)
    if out.exists():
        raise ValueError('immutable_mark_repair_exists')
    plan = json.loads(gap_plan.read_text())
    verify_manifest(coverage_root, expected_hash=plan['source_coverage_manifest_sha256'])
    dates = plan['missing_mark_minutes_by_day']
    monthly = {month: {t: values for t, values, _ in raw_marks((coverage_root / 'archives' / f'mark-BTCUSDT-1m-{month}.zip').read_bytes())}
               for month in sorted({d[:7] for d in dates})}
    out.mkdir(parents=True)
    (out / 'archives').mkdir()
    (out / 'checksums').mkdir()
    shutil.copyfile(gap_plan, out / 'gap-plan.json')
    shutil.copyfile(__file__, out / 'mark-repair-source.py')

    def task(day):
        name = f'mark-BTCUSDT-1m-{day}.zip'
        url = f'https://data.binance.vision/data/futures/um/daily/markPriceKlines/BTCUSDT/1m/BTCUSDT-1m-{day}.zip'
        try:
            checksum, body = fetch(url + '.CHECKSUM'), fetch(url)
            h = hashlib.sha256(body).hexdigest()
            if h != checksum.decode().split()[0]:
                raise ValueError('mark_repair_official_checksum')
            (out / 'archives' / name).write_bytes(body)
            (out / 'checksums' / (name + '.CHECKSUM')).write_bytes(checksum)
            result = qualify_day(body, day, monthly[day[:7]])
            if result['added_observed_rows'] > dates[day]:
                raise ValueError('mark_repair_gap_count_changed')
            return {'day': day, 'kind': 'mark', 'month': day[:7], 'file': 'archives/' + name,
                    'url': url, 'sha256': h, **result, 'qualified': True, 'observed_at': dt.datetime.now(UTC).isoformat()}
        except Exception as exc:
            return {'day': day, 'url': url, 'qualified': False, 'error': type(exc).__name__ + ': ' + str(exc)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        records = list(pool.map(task, sorted(dates)))
    result = {'research_only': True, 'orders_authorized': False, 'promotion_evidence': False,
              'coverage_root': str(coverage_root), 'coverage_manifest_sha256': plan['source_coverage_manifest_sha256'],
              'qualified': all(r['qualified'] for r in records), 'records': records, 'days': len(records),
              'added_observed_rows': sum(r.get('added_observed_rows', 0) for r in records),
              'overlap_rows': sum(r.get('overlap_rows', 0) for r in records), 'imputed_rows': 0,
              'remaining_missing_minutes': sum(r.get('remaining_missing_minutes', 0) for r in records),
              'curve_count': 0, 'candidate_trials_consumed': 0}
    write_json(out / 'repair-result.json', result)
    write_json(out / 'manifest.json', {'research_only': True, 'orders_authorized': False,
        'files': {str(p.relative_to(out)): file_hash(p) for p in sorted(out.rglob('*')) if p.is_file()}})
    return result
