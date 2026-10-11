"""Stream and qualify a user-supplied equity archive without return labels."""
from __future__ import annotations

import collections
import concurrent.futures
import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
import re
import stat
import sys
import zipfile
from pathlib import Path

FIELDS = ('ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'pre_close',
          'change', 'pct_chg', 'vol', 'amount', 'adj_factor', 'adj_close',
          'adj_open', 'adj_high', 'adj_low')
PRICES = ('open', 'high', 'low', 'close')
ADJUSTED = ('adj_factor', 'adj_close', 'adj_open', 'adj_high', 'adj_low')
MEMBER = re.compile(r'stocks/([0-9]{6})_(SH|SZ|BJ)\.csv')
STORAGE = Path('/mnt/e/qount_data/qount/artifacts/equity_selection')


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def number(value):
    if value is None or not value.strip():
        return None
    try:
        result = float(value)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def profile_member(stream, expected_code):
    """Audit every record; report issues instead of dropping or repairing rows."""
    reader = csv.DictReader(stream)
    if tuple(reader.fieldnames or ()) != FIELDS:
        raise ValueError('equity_archive_schema_mismatch:' + expected_code)
    issues, missing, dates = collections.Counter(), collections.Counter(), collections.Counter()
    total = complete = partial = zero_activity = factor_changes = preclose_breaks = 0
    previous_date = previous_close = previous_factor = None
    first_adj = last_adj = None
    ratio_min = ratio_max = None
    ratio_errors = 0
    for row in reader:
        total += 1
        if None in row or any(value is None for value in row.values()):
            issues['row_width'] += 1
        if row.get('ts_code') != expected_code:
            issues['symbol_mismatch'] += 1
        day = row.get('trade_date', '')
        try:
            if not re.fullmatch(r'[0-9]{8}', day):
                raise ValueError()
            dt.date(int(day[:4]), int(day[4:6]), int(day[6:]))
        except (ValueError, TypeError):
            issues['invalid_date'] += 1
            day = None
        if day is not None:
            dates[day] += 1
            if previous_date is not None and day <= previous_date:
                issues['duplicate_or_unordered_date'] += 1
            previous_date = day
        values = {key: number(row.get(key)) for key in FIELDS[2:]}
        for key, value in values.items():
            if value is None:
                missing[key] += 1
                if row.get(key, '') not in ('', None):
                    issues['invalid_numeric_' + key] += 1
        if any(values[key] is None or values[key] <= 0 for key in PRICES):
            issues['missing_or_nonpositive_ohlc'] += 1
        else:
            if (values['low'] > min(values['open'], values['close'])
                    or values['high'] < max(values['open'], values['close'])
                    or values['low'] > values['high']):
                issues['invalid_ohlc_envelope'] += 1
        if any(values[key] is None or values[key] < 0 for key in ('vol', 'amount')):
            issues['missing_or_negative_activity'] += 1
        if values['vol'] == 0 or values['amount'] == 0:
            zero_activity += 1
        if values['pre_close'] is not None and previous_close is not None:
            if abs(values['pre_close'] - previous_close) > 1e-6 * max(1., previous_close):
                preclose_breaks += 1
        previous_close = values['close']
        present = sum(values[key] is not None for key in ADJUSTED)
        if 0 < present < len(ADJUSTED):
            partial += 1
        if present == len(ADJUSTED):
            if any(values[key] <= 0 for key in ADJUSTED):
                issues['nonpositive_adjustment'] += 1
            elif all(values[key] is not None and values[key] > 0 for key in PRICES):
                complete += 1
                if day is not None:
                    first_adj = min(first_adj, day) if first_adj else day
                    last_adj = max(last_adj, day) if last_adj else day
                ratios = [values['adj_' + key] / values[key] for key in PRICES]
                if max(ratios) - min(ratios) > 1e-6 * max(ratios):
                    ratio_errors += 1
                anchor = ratios[0] / values['adj_factor']
                ratio_min = min(ratio_min, anchor) if ratio_min is not None else anchor
                ratio_max = max(ratio_max, anchor) if ratio_max is not None else anchor
        factor = values['adj_factor']
        if factor is not None and previous_factor is not None and factor != previous_factor:
            factor_changes += 1
        previous_factor = factor
    if not total:
        issues['empty_file'] += 1
    anchor_consistent = (ratio_min is not None and ratio_max is not None
                         and ratio_max - ratio_min <= 1e-6 * ratio_max)
    profile = {'symbol': expected_code, 'rows': total, 'first_date': min(dates) if dates else None,
               'last_date': max(dates) if dates else None, 'unique_dates': len(dates),
               'duplicate_dates': sum(n - 1 for n in dates.values()), 'issues': dict(issues),
               'missing_numeric_fields': dict(missing), 'zero_activity_rows': zero_activity,
               'complete_adjustment_rows': complete, 'partial_adjustment_rows': partial,
               'first_complete_adjustment_date': first_adj, 'last_complete_adjustment_date': last_adj,
               'adjusted_ohlc_ratio_mismatches': ratio_errors,
               'adjustment_anchor_consistent': anchor_consistent,
               'adjustment_anchor_min': ratio_min, 'adjustment_anchor_max': ratio_max,
               'observed_factor_changes': factor_changes,
               'pre_close_differs_from_previous_observed_close': preclose_breaks}
    return profile, dates


def members(archive):
    seen, files = set(), []
    for info in archive.infolist():
        if info.filename in seen:
            raise ValueError('equity_archive_duplicate_member')
        seen.add(info.filename)
        if info.flag_bits & 1 or stat.S_ISLNK(info.external_attr >> 16):
            raise ValueError('equity_archive_encrypted_or_symlink_member')
        if info.is_dir() and info.filename == 'stocks/':
            continue
        match = MEMBER.fullmatch(info.filename)
        if not match:
            raise ValueError('equity_archive_unexpected_member')
        files.append((info, match.group(1) + '.' + match.group(2)))
    if not files:
        raise ValueError('equity_archive_empty')
    return files


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def profile_batch(archive_path, entries):
    profiles, coverage = [], collections.Counter()
    with zipfile.ZipFile(archive_path) as archive:
        for name, symbol, size, crc in entries:
            with archive.open(name) as stream:
                profile, dates = profile_member(io.TextIOWrapper(stream, encoding='utf-8-sig', newline=''), symbol)
            profiles.append({**profile, 'member': name, 'uncompressed_bytes': size, 'zip_crc32': crc})
            coverage.update(dates)
    return profiles, coverage


def audit_archive(*, archive_path, expected_sha256, out, workers=4):
    """WSL/E-only full structural audit. Never computes returns or selects names."""
    if (sys.platform != 'linux' or not os.path.ismount('/mnt/e')
            or not out.resolve().is_relative_to(STORAGE)
            or not archive_path.resolve().is_relative_to(Path('/mnt/e/qount_data/qount/datasets/equity_selection'))):
        raise ValueError('equity_archive_wsl_mounted_e_required')
    if out.exists():
        raise ValueError('equity_archive_immutable_output_exists')
    if workers not in (1, 2, 4):
        raise ValueError('equity_archive_worker_count_invalid')
    before = archive_path.stat()
    if sha256(archive_path) != expected_sha256:
        raise ValueError('equity_archive_source_hash_mismatch')
    profiles, coverage, exchanges, prefixes = [], collections.Counter(), collections.Counter(), collections.Counter()
    with zipfile.ZipFile(archive_path) as archive:
        entries = [(i.filename, symbol, i.file_size, format(i.CRC, '08x')) for i, symbol in members(archive)]
    batches = [entries[i:i + 64] for i in range(0, len(entries), 64)]
    pool = concurrent.futures.ProcessPoolExecutor(max_workers=workers) if workers > 1 else None
    futures = [pool.submit(profile_batch, archive_path, batch) for batch in batches] if pool else []
    try:
        results = (future.result() for future in concurrent.futures.as_completed(futures)) if pool else (
            profile_batch(archive_path, batch) for batch in batches)
        next_progress = 500
        for group, dates in results:
            profiles.extend(group)
            coverage.update(dates)
            if len(profiles) >= next_progress:
                print(f'equity_csvs_audited={len(profiles)}/{len(entries)}', flush=True)
                next_progress += 500
    finally:
        if pool:
            pool.shutdown(wait=True, cancel_futures=True)
    profiles.sort(key=lambda p: p['member'])
    for profile in profiles:
        symbol = profile['symbol']
        exchanges[symbol.split('.')[1]] += 1
        prefixes[symbol.split('.')[1] + ':' + symbol[:3]] += 1
    after = archive_path.stat()
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise ValueError('equity_archive_source_changed_during_audit')
    issue_totals, missing = collections.Counter(), collections.Counter()
    for profile in profiles:
        issue_totals.update(profile['issues'])
        missing.update(profile['missing_numeric_fields'])
    rows = sum(p['rows'] for p in profiles)
    summary = {'schema_version': 1, 'source_sha256': expected_sha256, 'archive_bytes': before.st_size,
               'cpu_workers': workers,
               'csv_files': len(profiles), 'rows': rows, 'exchange_file_counts': dict(exchanges),
               'code_prefix_counts': dict(sorted(prefixes.items())), 'first_date': min(coverage) if coverage else None,
               'last_date': max(coverage) if coverage else None, 'distinct_observed_dates': len(coverage),
               'files_without_valid_dates': sum(p['first_date'] is None for p in profiles),
               'file_first_date_counts': dict(sorted(collections.Counter(p['first_date'] for p in profiles if p['first_date']).items())),
               'file_last_date_counts': dict(sorted(collections.Counter(p['last_date'] for p in profiles if p['last_date']).items())),
               'issue_totals': dict(issue_totals), 'files_with_structural_issues': sum(bool(p['issues']) for p in profiles),
               'missing_numeric_fields': dict(missing),
               'complete_adjustment_rows': sum(p['complete_adjustment_rows'] for p in profiles),
               'partial_adjustment_rows': sum(p['partial_adjustment_rows'] for p in profiles),
               'files_with_no_complete_adjustment': sum(p['complete_adjustment_rows'] == 0 for p in profiles),
               'adjusted_ohlc_ratio_mismatches': sum(p['adjusted_ohlc_ratio_mismatches'] for p in profiles),
               'files_with_inconsistent_adjustment_anchor': sum(p['complete_adjustment_rows'] > 0
                       and not p['adjustment_anchor_consistent'] for p in profiles),
               'zero_activity_rows': sum(p['zero_activity_rows'] for p in profiles),
               'source_vendor_verified': False, 'volume_amount_units_verified': False,
               'historical_universe_verified': False, 'corporate_actions_verified': False,
               'historical_tradability_verified': False, 'us_individual_equity_files': 0,
               'low_frequency_required': False, 'research_only': True, 'orders_authorized': False,
               'holdout_role': 'discovery', 'returns_produced': False, 'imputed_rows': 0,
               'qualification': 'structural_audit_only_not_investment_or_execution_evidence'}
    out.mkdir(parents=True, exist_ok=False)
    write_json(out / 'summary.json', summary)
    write_json(out / 'members.json', profiles)
    write_json(out / 'observed-date-coverage.json', dict(sorted(coverage.items())))
    write_json(out / 'source-binding.json', {'archive': str(archive_path), 'sha256': expected_sha256,
                   'audit_module_sha256': sha256(Path(__file__)), 'rows_repaired': 0,
                   'archive_read_to_eof_crc_checked': True})
    manifest = {p.name: sha256(p) for p in sorted(out.iterdir())}
    write_json(out / 'manifest.json', manifest)
    return {**summary, 'artifact_root': str(out), 'manifest_sha256': sha256(out / 'manifest.json')}
