"""Prepare observed, manifest-bound required quotes without filling mark gaps."""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import shutil
import zipfile
from pathlib import Path

from qount.research.dual_engine_cashflow_data import UTC
from qount.research.dual_engine_execution_study import verify_manifest
from qount.research.dual_engine_expansion import require_storage
from qount.research.dual_engine_optimization import file_hash, write_json
from qount.research.dual_engine_cashflow_mark_repair import raw_marks


def merge_mark_day(monthly_body, daily_body, day, needed):
    """Union of real observations; neither source's absent rows replace known rows."""
    date = dt.date.fromisoformat(day)
    first = int(dt.datetime.combine(date, dt.time(), UTC).timestamp() * 1000)
    observed = {}
    for body in (monthly_body, daily_body):
        for t, values, _ in raw_marks(body):
            if first <= t < first + 86400000:
                if t in observed and any(abs(x - y) > 1e-8 for x, y in zip(values, observed[t], strict=True)):
                    raise ValueError('cashflow_observed_mark_union_conflict')
                observed[t] = values
    highs, counts, selected = [0.0] * 24, [0] * 24, {}
    p = {'mark_hour_high': highs}
    for t, (opening, high, low, close) in sorted(observed.items()):
        hour = (t - first) // 3600000
        highs[hour] = max(highs[hour], high)
        counts[hour] += 1
        if t == first + 86340000:
            p['mark_close'] = close
        if t in needed:
            selected[str(t)] = {'open': opening, 'high': high, 'low': low}
    p['mark_hour_complete'] = [n == 60 for n in counts]
    return {day: p}, selected


def reduce_observed(body, kind, first, last, needed):
    """Only real observations are reduced. Completeness never implies imputation."""
    prices, marks, counts = {}, {}, {}
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        with z.open(z.namelist()[0]) as stream:
            for raw in csv.reader(io.TextIOWrapper(stream)):
                if not raw[0].isdigit():
                    continue
                t = int(raw[0])
                t = t // 1000 if t >= 10**14 else t
                when = dt.datetime.fromtimestamp(t / 1000, UTC)
                day = when.date().isoformat()
                if kind == 'mark' and t in needed:
                    marks[str(t)] = {'open': float(raw[1]), 'high': float(raw[2]), 'low': float(raw[3])}
                if not first <= day <= last:
                    continue
                p = prices.setdefault(day, {})
                if kind == 'mark':
                    highs = p.setdefault('mark_hour_high', [0.0] * 24)
                    highs[when.hour] = max(highs[when.hour], float(raw[2]))
                    counts.setdefault(day, [0] * 24)[when.hour] += 1
                    if when.hour == 23 and when.minute == 59:
                        p['mark_close'] = float(raw[4])
                else:
                    if when.hour in (1, 23):
                        p[kind + '_open' + str(when.hour)] = float(raw[1])
                    if when.hour == 23:
                        p[kind + '_close'] = float(raw[4])
    for day, row in counts.items():
        prices[day]['mark_hour_complete'] = [n == 60 for n in row]
    return prices, marks


def prepare_inputs(*, contract_path: Path, coverage_root: Path, out: Path, mark_repair_root: Path | None = None):
    require_storage(out)
    if out.exists():
        raise ValueError('immutable_cashflow_observed_input_exists')
    c = json.loads(contract_path.read_text())
    verify_manifest(coverage_root)
    audit = json.loads((coverage_root / 'coverage-audit.json').read_text())
    counts = audit['counts']
    repair = None
    if mark_repair_root is not None:
        verify_manifest(mark_repair_root)
        repair = json.loads((mark_repair_root / 'repair-result.json').read_text())
        if not repair['qualified'] or repair['coverage_manifest_sha256'] != file_hash(coverage_root / 'manifest.json'):
            raise ValueError('cashflow_observed_mark_repair_unqualified')
    critical = ('missing_required_fill_quotes',
                'malformed_required_observations', 'zero_volume_required_fill_quotes', 'invalid_ohlc_or_calendar_rows')
    if (audit['checksum_qualified_archives'] != 207 or audit['unqualified_sources']
            or audit['spot_close_bridge_differences'] or any(counts[k] for k in critical)
            or any(a.get('duplicate_rows', 0) for a in audit['archives'])):
        raise ValueError('cashflow_required_observations_unqualified')
    if (repair is None and (counts['missing_required_funding_minutes'] or counts['missing_daily_nav_hours'])) or any(
            a['kind'] != 'mark' and a.get('missing_daily_nav_hours') for a in audit['archives']):
        raise ValueError('cashflow_required_mark_observations_unqualified')
    verify_manifest(Path(c['information_root']), expected_hash=c['information_manifest_sha256'])
    first, last = c['evaluation']['first'], c['evaluation']['last']
    info = json.loads((Path(c['information_root']) / 'information.json').read_text())
    events = [e for e in info['funding_events']['BTCUSDT'] if first <= e['day'] <= last]
    needed = {v for e in events for v in (e['timestamp_ms'] // 60000 * 60000 - 60000, e['timestamp_ms'] // 60000 * 60000)}
    out.mkdir(parents=True)
    (out / 'archives').mkdir()
    (out / 'checksums').mkdir()
    prices, minute, provenance = {}, {}, []
    for a in audit['archives']:
        name = f"{a['kind']}-BTCUSDT-{'1m' if a['kind'] == 'mark' else '1h'}-{a['month']}.zip"
        path = coverage_root / 'archives' / name
        for sub, filename in (('archives', name), ('checksums', name + '.CHECKSUM')):
            try:
                os.link(coverage_root / sub / filename, out / sub / filename)
            except OSError:
                shutil.copyfile(coverage_root / sub / filename, out / sub / filename)
        daily, selected = reduce_observed(path.read_bytes(), a['kind'], first, last, needed)
        for day, row in daily.items():
            prices.setdefault(day, {}).update(row)
        minute.update(selected)
        provenance.append({**a, 'file': 'archives/' + name})
    if repair is not None:
        for a in repair['records']:
            name = Path(a['file']).name
            for sub, filename in (('archives', name), ('checksums', name + '.CHECKSUM')):
                try:
                    os.link(mark_repair_root / sub / filename, out / sub / filename)
                except OSError:
                    shutil.copyfile(mark_repair_root / sub / filename, out / sub / filename)
            daily, selected = merge_mark_day(
                (coverage_root / 'archives' / f"mark-BTCUSDT-1m-{a['day'][:7]}.zip").read_bytes(),
                (mark_repair_root / 'archives' / name).read_bytes(), a['day'], needed)
            for day, row in daily.items():
                prices.setdefault(day, {}).update(row)
            for stamp, values in selected.items():
                if stamp in minute and minute[stamp] != values:
                    raise ValueError('cashflow_mark_repair_funding_overlap_differs')
                minute[stamp] = values
            provenance.append({**a, 'file': 'archives/' + name, 'source_resolution': 'official_daily_observed'})
    expected_days = [dt.date.fromisoformat(first) + dt.timedelta(days=i) for i in range((dt.date.fromisoformat(last) - dt.date.fromisoformat(first)).days + 1)]
    for date in expected_days:
        day = date.isoformat()
        if not info['funding']['BTCUSDT'].get(day, {}).get('complete'):
            raise ValueError('cashflow_incomplete_funding_day')
        p = prices.get(day, {})
        required = ('spot_close', 'mark_close', 'mark_hour_high', 'mark_hour_complete')
        if not all(k in p for k in required):
            raise ValueError('cashflow_required_nav_price_missing')
    enriched = []
    for e in events:
        t = e['timestamp_ms'] // 60000 * 60000
        if str(t - 60000) not in minute or str(t) not in minute:
            raise ValueError('cashflow_required_funding_mark_minute_missing')
        pair = minute[str(t - 60000)], minute[str(t)]
        enriched.append({**e, 'mark_proxy': pair[1]['open'], 'mark_lower': min(p['low'] for p in pair), 'mark_upper': max(p['high'] for p in pair)})
    remaining_hours = sum(not complete for p in prices.values() for complete in p['mark_hour_complete'])
    if repair is None and remaining_hours != counts['incomplete_mark_stress_hours']:
        raise ValueError('cashflow_stress_coverage_reduction')
    write_json(out / 'prices.json', {d: p for d, p in sorted(prices.items())})
    write_json(out / 'funding.json', enriched)
    write_json(out / 'provenance.json', {'archives': provenance, 'coverage_root': str(coverage_root),
        'coverage_manifest_sha256': file_hash(coverage_root / 'manifest.json'), 'coverage_counts': counts,
        'input_qualification_scope': c['input_qualification_scope'], 'incomplete_stress_hours': remaining_hours,
        'mark_repair_root': str(mark_repair_root) if repair else None,
        'mark_repair_manifest_sha256': file_hash(mark_repair_root / 'manifest.json') if repair else None,
        'added_observed_mark_rows': repair['added_observed_rows'] if repair else 0,
        'imputed_prices': 0, 'information_manifest_sha256': c['information_manifest_sha256'], 'btc_cache_sha256': c['btc_cache_sha256'],
        'research_only': True, 'orders_authorized': False})
    write_json(out / 'manifest.json', {'research_only': True, 'orders_authorized': False,
        'files': {str(p.relative_to(out)): file_hash(p) for p in sorted(out.rglob('*')) if p.is_file()}})
    return {'days': len(prices), 'funding_events': len(enriched), 'imputed_prices': 0,
            'incomplete_stress_hours': remaining_hours}
