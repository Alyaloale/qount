"""A-share source/window qualification and fixed information-study primitives.

No account, order, service or portfolio execution interface exists here.
The qualification path never computes features, rankings or return labels.
"""
from __future__ import annotations

import collections
import concurrent.futures
import csv
import datetime as dt
import io
import json
import math
import os
import statistics
import sys
import zipfile
from pathlib import Path

from qount.research_data.equity_archive import FIELDS, members, number, sha256, write_json

ARTIFACTS = Path('/mnt/e/qount_data/qount/artifacts/equity_selection')
DATASETS = Path('/mnt/e/qount_data/qount/datasets/equity_selection')


def official_calendar(review, start, end, exchange='SSE'):
    """Derive sessions from dated official notices, never from price observations."""
    first, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    if first > last:
        raise ValueError('calendar_reversed_range')
    years = {row['year']: row for row in review['years']}
    if len(years) != len(review['years']):
        raise ValueError('calendar_duplicate_year')
    closed, source_urls = set(), {}
    for year in range(first.year, last.year + 1):
        record = years.get(year)
        status_key = {'SSE': 'sse_status', 'SZSE': 'szse_status'}[exchange]
        if record is None or record.get(status_key, record['status']) != 'verified':
            raise ValueError('calendar_year_not_verified:' + str(year))
        ids, exchange_ids = set(), set()
        annual = False
        for source in record['sources']:
            url = source['url']
            if not url.startswith(('https://www.sse.com.cn/', 'https://big5.sse.com.cn/', 'https://www.szse.cn/',
                                   'https://docs.static.szse.cn/')):
                raise ValueError('calendar_non_exchange_source')
            dt.date.fromisoformat(source['published_date'])
            if source['id'] in ids:
                raise ValueError('calendar_duplicate_source_id')
            ids.add(source['id'])
            if source.get('exchange', 'SSE') == exchange:
                source_urls[source['id']] = url
                exchange_ids.add(source['id'])
                annual |= source['kind'] == 'annual'
        if not annual or not record['closures']:
            raise ValueError('calendar_annual_notice_required')
        for closure in record['closures']:
            a, b = dt.date.fromisoformat(closure['start']), dt.date.fromisoformat(closure['end'])
            if (a > b or a.year != year or b.year != year
                    or not closure['source_ids'] or not set(closure['source_ids']) <= ids):
                raise ValueError('calendar_closure_source_or_range_invalid')
            if set(closure['source_ids']) & exchange_ids:
                closed.update(a + dt.timedelta(days=i) for i in range((b - a).days + 1))
    if first <= dt.date(2015, 9, 3) <= last and dt.date(2015, 9, 3) not in closed:
        raise ValueError('calendar_2015_special_closure_missing')
    if first <= dt.date(2020, 1, 31) <= last and dt.date(2020, 1, 31) not in closed:
        raise ValueError('calendar_2020_extension_missing')
    days = (first + dt.timedelta(days=i) for i in range((last - first).days + 1))
    sessions = tuple(day.strftime('%Y%m%d') for day in days if day.weekday() < 5 and day not in closed)
    if not sessions:
        raise ValueError('calendar_no_sessions')
    return sessions, source_urls


def prefix_locator(symbol, prefixes):
    """Only an archive locator; does not certify dated board/listing identity."""
    code, exchange = symbol.split('.')
    return code[:3] in prefixes.get(exchange, [])


def window_profile(stream, symbol, sessions, study_start, study_end, past_count=252, window=65,
                   calendar_start=None, calendar_end=None):
    """Count past-only data availability on an independent full session index."""
    reader = csv.DictReader(stream)
    if tuple(reader.fieldnames or ()) != FIELDS:
        raise ValueError('selection_schema_mismatch')
    index = {day: i for i, day in enumerate(sessions)}
    coverage_start, coverage_end = calendar_start or sessions[0], calendar_end or sessions[-1]
    present, raw, adjusted, activity = ([0] * len(sessions) for _ in range(4))
    earlier_valid = total = volume_unavailable = 0
    previous = None
    unexpected = []
    for row in reader:
        total += 1
        day = row['trade_date']
        if row['ts_code'] != symbol or len(day) != 8 or not day.isdigit():
            raise ValueError('selection_identity_or_date_mismatch')
        dt.datetime.strptime(day, '%Y%m%d')
        if previous is not None and day <= previous:
            raise ValueError('selection_date_not_strictly_increasing')
        previous = day
        if None in row or any(value is None for value in row.values()):
            raise ValueError('selection_row_width_mismatch')
        values = {name: number(row[name]) for name in ('open', 'high', 'low', 'close',
                  'adj_open', 'adj_high', 'adj_low', 'adj_close', 'adj_factor', 'vol', 'amount')}
        volume_unavailable += values['vol'] is None or values['vol'] <= 0
        raw_ok = all(values[name] is not None and values[name] > 0
                     for name in ('open', 'high', 'low', 'close'))
        if day < coverage_start:
            earlier_valid += raw_ok
            continue
        if day > coverage_end:
            continue
        if day not in index:
            unexpected.append(day)
            continue
        i = index[day]
        present[i], raw[i] = 1, int(raw_ok)
        adjusted[i] = int(all(values[name] is not None and values[name] > 0
                              for name in ('adj_open', 'adj_high', 'adj_low', 'adj_close', 'adj_factor')))
        activity[i] = int(values['amount'] is not None and values['amount'] > 0)
    cumulative_raw = earlier_valid
    rolling = [0, 0, 0, 0]
    vectors = [present, raw, adjusted, activity]
    result = []
    reasons = collections.Counter()
    for i, day in enumerate(sessions):
        cumulative_raw += raw[i]
        for j, vector in enumerate(vectors):
            rolling[j] += vector[i]
            if i >= window:
                rolling[j] -= vector[i - window]
        if not study_start <= day <= study_end:
            continue
        history_ok = cumulative_raw >= past_count
        complete = i >= window - 1 and all(count == window for count in rolling)
        # These labels describe source availability, never investment eligibility.
        reason = ('history_insufficient' if not history_ok else
                  'calendar_row_absent' if rolling[0] != window else
                  'raw_price_missing_or_invalid' if rolling[1] != window else
                  'adjustment_missing_or_invalid' if rolling[2] != window else
                  'amount_missing_zero_or_invalid' if rolling[3] != window else 'window_available')
        reasons[reason] += 1
        result.append((int(history_ok), int(complete), int(history_ok and complete)))
    return {'symbol': symbol, 'rows_streamed': total, 'unexpected_calendar_dates': unexpected,
            'volume_unavailable_rows_not_used_as_amount_feature_gate': volume_unavailable,
            'pre_calendar_valid_price_observations_with_unverified_session_dates': earlier_valid,
            'availability_reason_counts': dict(reasons), 'per_date_counts': result}


def _batch(archive_path, entries, sessions, options):
    profiles, totals = [], [[0, 0, 0] for day in sessions if options['study_start'] <= day <= options['study_end']]
    with zipfile.ZipFile(archive_path) as archive:
        for name, symbol in entries:
            with archive.open(name) as raw_stream:
                result = window_profile(io.TextIOWrapper(raw_stream, encoding='utf-8-sig', newline=''),
                                        symbol, sessions, **options)
            for dst, src in zip(totals, result.pop('per_date_counts'), strict=True):
                for i in range(3):
                    dst[i] += src[i]
            profiles.append(result)
    return profiles, totals


def verify_manifest(root, expected=None):
    path = root / 'manifest.json'
    if expected is not None and sha256(path) != expected:
        raise ValueError('selection_manifest_hash_mismatch')
    manifest = json.loads(path.read_text())
    for relative, digest in manifest.items():
        target = (root / relative).resolve()
        if not target.is_relative_to(root.resolve()) or not target.is_file() or sha256(target) != digest:
            raise ValueError('selection_manifest_file_mismatch:' + relative)
    return manifest


def source_gates(contract, *, calendar_verified):
    evidence = {**contract['source_evidence'], 'independent_calendar_verified': calendar_verified}
    information_missing = [name for name in contract['information_gate_required'] if evidence.get(name) is not True]
    portfolio_missing = [name for name in contract['portfolio_gate_required'] if evidence.get(name) is not True]
    return {'information_missing': information_missing, 'portfolio_missing': portfolio_missing,
            'information_authorized_by_data': not information_missing,
            'portfolio_authorized_by_data': not (information_missing or portfolio_missing)}


def qualify(*, contract_path, calendar_path, out):
    """One immutable WSL/E qualification, preserving data gates and all prior artifacts."""
    contract = json.loads(contract_path.read_text())
    if (contract['phase'] != 'source_and_calendar_qualification'
            or not contract['authorization']['qualification_run'] or contract['orders_authorized']
            or not contract['research_only'] or contract['qualification']['returns_or_rankings']):
        raise ValueError('selection_qualification_contract_invalid')
    archive_path = Path(contract['source']['archive'])
    if (sys.platform != 'linux' or not os.path.ismount('/mnt/e')
            or not archive_path.resolve().is_relative_to(DATASETS)
            or not out.resolve().is_relative_to(ARTIFACTS)):
        raise ValueError('selection_wsl_mounted_e_required')
    if out.exists():
        raise ValueError('selection_immutable_output_exists')
    proposal = contract_path.parent.parent / contract['proposal_file']
    if sha256(proposal) != contract['proposal_sha256']:
        raise ValueError('selection_original_proposal_hash_mismatch')
    if sha256(calendar_path) != contract['calendar_source_review_sha256']:
        raise ValueError('selection_calendar_review_hash_mismatch')
    review = json.loads(calendar_path.read_text())
    q = contract['qualification']
    sessions, sources = official_calendar(review, q['calendar_start'], q['calendar_end'])
    audit_root = Path(contract['source']['audit_root'])
    verify_manifest(audit_root, contract['source']['audit_manifest_sha256'])
    observed = json.loads((audit_root / 'observed-date-coverage.json').read_text())
    observed_dates = {day for day in observed if q['calendar_start'].replace('-', '') <= day <= q['calendar_end'].replace('-', '')}
    expected_dates = set(sessions)
    package_missing_sessions = sorted(expected_dates - observed_dates)
    package_unexpected_dates = sorted(observed_dates - expected_dates)
    before = archive_path.stat()
    if sha256(archive_path) != contract['source']['sha256']:
        raise ValueError('selection_archive_hash_mismatch')
    with zipfile.ZipFile(archive_path) as archive:
        entries = [(info.filename, symbol) for info, symbol in members(archive)
                   if prefix_locator(symbol, q['prefix_locator_not_historical_identity'])]
    study_days = [day for day in sessions if q['study_start'].replace('-', '') <= day <= q['study_end'].replace('-', '')]
    options = {'study_start': q['study_start'].replace('-', ''), 'study_end': q['study_end'].replace('-', ''),
               'past_count': q['past_valid_price_observations'], 'window': q['complete_recent_sessions'],
               'calendar_start': q['calendar_start'].replace('-', ''), 'calendar_end': q['calendar_end'].replace('-', '')}
    totals, profiles = [[0, 0, 0] for _ in study_days], []
    if q['workers'] not in (1, 2, 4):
        raise ValueError('selection_worker_count_invalid')
    batches = [entries[i:i + 32] for i in range(0, len(entries), 32)]
    with concurrent.futures.ProcessPoolExecutor(max_workers=q['workers']) as pool:
        futures = [pool.submit(_batch, archive_path, group, sessions, options) for group in batches]
        progress = 0
        for future in concurrent.futures.as_completed(futures):
            group, counts = future.result()
            profiles.extend(group)
            for dst, src in zip(totals, counts, strict=True):
                for i in range(3):
                    dst[i] += src[i]
            if len(profiles) // 500 > progress:
                progress = len(profiles) // 500
                print(f'ashare_window_files={len(profiles)}/{len(entries)}', flush=True)
    after = archive_path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('selection_archive_changed')
    profiles.sort(key=lambda x: x['symbol'])
    unexpected = {p['symbol']: p['unexpected_calendar_dates'] for p in profiles if p['unexpected_calendar_dates']}
    both_exchanges_verified = all(row['status'] == 'verified' for row in review['years'])
    gates = source_gates(contract, calendar_verified=not (unexpected or package_missing_sessions or package_unexpected_dates)
                         and both_exchanges_verified)
    daily = [{'date': day, 'history_252_available': a, 'recent_65_complete': b,
              'both_available': c, 'is_investment_eligibility': False}
             for day, (a, b, c) in zip(study_days, totals, strict=True)]
    values = [row['both_available'] for row in daily]
    summary = {'study_id': contract['study_id'], 'phase': contract['phase'],
               'research_only': True, 'orders_authorized': False, 'promotion_evidence': False,
               'holdout_role': 'discovery', 'returns_produced': False, 'features_or_rankings_produced': False,
               'imputed_rows': 0, 'files_profiled': len(profiles),
               'rows_streamed': sum(p['rows_streamed'] for p in profiles),
               'study_session_count': len(study_days), 'calendar_session_count': len(sessions),
               'calendar_source_urls': sources, 'calendar_unexpected_dates': unexpected,
               'calendar_matches_observed_rows': not (unexpected or package_missing_sessions or package_unexpected_dates),
               'whole_package_missing_reference_sessions': package_missing_sessions,
               'whole_package_unexpected_dates': package_unexpected_dates,
               'availability_reference_calendar_authority': 'SSE_original_notices',
               'both_exchange_source_calendars_verified': both_exchanges_verified,
               'window_available_min': min(values), 'window_available_median': statistics.median(values),
               'window_available_max': max(values),
               'dates_with_at_least_500_source_windows': sum(v >= q['minimum_cross_section'] for v in values),
               'per_year': {year: {'sessions': len(rows), 'min': min(rows), 'median': statistics.median(rows),
                                  'max': max(rows), 'at_least_500': sum(v >= q['minimum_cross_section'] for v in rows)}
                            for year in sorted({day[:4] for day in study_days})
                            if (rows := [v for day, v in zip(study_days, values) if day.startswith(year)])},
               'locator_is_historical_board_or_security_qualification': False, 'data_gates': gates,
               'next_stage': 'source_evidence_required' if gates['information_missing'] else 'information_study_ready',
               'formal_portfolio_run': False}
    out.mkdir(parents=True, exist_ok=False)
    write_json(out / 'summary.json', summary)
    write_json(out / 'daily-window-availability.json', daily)
    write_json(out / 'security-window-profiles.json', profiles)
    write_json(out / 'calendar-sessions.json', sessions)
    write_json(out / 'calendar-sources.json', review)
    write_json(out / 'contract.json', contract)
    write_json(out / 'source-binding.json', {'archive_sha256': contract['source']['sha256'],
               'audit_manifest_sha256': contract['source']['audit_manifest_sha256'],
               'contract_sha256': sha256(contract_path), 'calendar_source_review_sha256': sha256(calendar_path),
               'module_sha256': sha256(Path(__file__)), 'original_proposal_sha256': sha256(proposal)})
    write_json(out / 'manifest.json', {p.name: sha256(p) for p in sorted(out.iterdir())})
    return {**summary, 'artifact_root': str(out), 'manifest_sha256': sha256(out / 'manifest.json')}


def fixed_features(adjusted_closes, amounts):
    """Pure preregistered formulas. Called only on fixtures until source gate passes."""
    if len(adjusted_closes) != 65 or len(amounts) != 65:
        raise ValueError('selection_features_require_exact_65_session_window')
    if any(v is None or not math.isfinite(v) or v <= 0 for v in [*adjusted_closes, *amounts]):
        return None
    return {'M': math.log(adjusted_closes[-6] / adjusted_closes[-61]),
            'A': math.log(statistics.fmean(amounts[-5:]) / statistics.fmean(amounts[:-5]))}


def fixed_price_strata(rows):
    """Five fixed-count price strata; deterministic ties never read future labels."""
    if len({row['symbol'] for row in rows}) != len(rows):
        raise ValueError('selection_duplicate_symbol')
    if any(not all(math.isfinite(row[key]) for key in ('M', 'A')) for row in rows):
        raise ValueError('selection_nonfinite_feature')
    if len(rows) < 500:
        return None
    strong = sorted(rows, key=lambda row: (-row['M'], row['symbol']))[:len(rows) // 5]
    quotient, remainder = divmod(len(strong), 5)
    if quotient < 20:
        return None
    strata, start = [], 0
    for i in range(5):
        size = quotient + (i < remainder)
        strata.append(strong[start:start + size])
        start += size
    return strata


def information_day(strata, labels):
    """Preserve future unknowns in the original groups, never complete-case reselect."""
    increments, unknown = [], {'top': 0, 'full': 0}
    for layer in strata:
        top = sorted(layer, key=lambda row: (-row['A'], -row['M'], row['symbol']))[:len(layer) // 3]
        outcomes = [[labels.get(row['symbol']) for row in group] for group in (top, layer)]
        for key, values in zip(('top', 'full'), outcomes):
            unknown[key] += sum(v is None or not math.isfinite(v) for v in values)
        if any(v is None or not math.isfinite(v) for values in outcomes for v in values):
            increments.append(None)
        else:
            increments.append(statistics.fmean(outcomes[0]) - statistics.fmean(outcomes[1]))
    return {'increment': None if None in increments else statistics.fmean(increments),
            'per_stratum_increment': increments, 'unknown_labels': unknown,
            'predecision_full_denominator': sum(map(len, strata)),
            'predecision_top_denominator': sum(len(group) // 3 for group in strata)}
