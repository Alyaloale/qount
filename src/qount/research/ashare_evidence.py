"""Source forensics for the supplied A-share archive; never financial labels.

Matching a vendor's published examples is corroboration, not proof of origin.
"""
from __future__ import annotations

import collections
import concurrent.futures
import csv
import io
import json
import math
import os
import sys
import zipfile
from pathlib import Path

from qount.research.ashare_selection import ARTIFACTS, DATASETS, official_calendar, verify_manifest
from qount.research_data.equity_archive import FIELDS, members, number, sha256, write_json


def forensic_profile(stream, symbol, sessions, policy, examples):
    """Check units/adjustment identities without constructing any return outcome."""
    reader = csv.DictReader(stream)
    if tuple(reader.fieldnames or ()) != FIELDS:
        raise ValueError('evidence_schema_mismatch')
    index = {day: i for i, day in enumerate(sessions)}
    counts = collections.Counter()
    scale_pass = {str(scale): 0 for scale in policy['amount_over_volume_scales']}
    samples = []
    previous = None
    last_adjusted = None
    bridge_max = 0.0
    example_results = []
    for row in reader:
        counts['rows'] += 1
        day = row['trade_date']
        if row['ts_code'] != symbol or (previous and day <= previous['date']):
            raise ValueError('evidence_identity_or_order_mismatch')
        values = {key: number(row[key]) for key in (
            'open', 'high', 'low', 'close', 'pre_close', 'change', 'pct_chg',
            'vol', 'amount', 'adj_factor', 'adj_open', 'adj_high', 'adj_low', 'adj_close')}
        positive = lambda *keys: all(values[k] is not None and values[k] > 0 for k in keys)
        if positive('low', 'high', 'vol', 'amount'):
            counts['amount_volume_rows'] += 1
            for scale in policy['amount_over_volume_scales']:
                implied = values['amount'] * scale / values['vol']
                tolerance = policy['vwap_price_tolerance_cny']
                scale_pass[str(scale)] += values['low'] - tolerance <= implied <= values['high'] + tolerance
        if positive('close', 'pre_close'):
            if values['change'] is not None:
                counts['change_checked'] += 1
                counts['change_mismatch'] += abs(values['change'] - (values['close'] - values['pre_close'])) > policy['change_tolerance_cny']
            if values['pct_chg'] is not None:
                counts['pct_checked'] += 1
                counts['pct_mismatch'] += abs(values['pct_chg'] - 100 * (values['close'] / values['pre_close'] - 1)) > policy['pct_tolerance_percentage_points']
        if positive('adj_factor', 'adj_close', 'close'):
            last_adjusted = {'date': day, 'raw_close': values['close'], 'adjusted_close': values['adj_close'],
                             'factor': values['adj_factor']}
        if day in index and previous and previous['date'] in index:
            consecutive = index[day] == index[previous['date']] + 1
            if not consecutive:
                counts['calendar_gaps_not_bridged'] += 1
            elif (positive('adj_factor', 'pre_close') and previous['factor'] is not None
                  and previous['factor'] > 0 and previous['close'] is not None and previous['close'] > 0):
                counts['consecutive_factor_pairs'] += 1
                factor_changed = not math.isclose(values['adj_factor'], previous['factor'], rel_tol=1e-10, abs_tol=0)
                counts['factor_changed_pairs'] += factor_changed
                implied_reference = previous['close'] * previous['factor'] / values['adj_factor']
                error = abs(implied_reference - values['pre_close'])
                bridge_max = max(bridge_max, error)
                mismatch = error > policy['reference_price_tolerance_cny']
                counts['factor_reference_mismatches'] += mismatch
                counts['factor_changed_reference_mismatches'] += mismatch and factor_changed
                if mismatch and len(samples) < policy['maximum_mismatch_examples_per_security']:
                    samples.append({'date': day, 'previous_date': previous['date'],
                        'factor_changed': factor_changed, 'recorded_reference': values['pre_close'],
                        'factor_implied_reference': implied_reference, 'absolute_error_cny': error})
        for sample in examples.get(symbol, {}).get(day, []):
            mismatches = [key for key, expected in sample['values'].items()
                          if values[key] is None or not math.isclose(values[key], expected, rel_tol=0, abs_tol=sample['absolute_tolerance'])]
            example_results.append({'source_id': sample['source_id'], 'date': day, 'fields_checked': len(sample['values']),
                                    'mismatched_fields': mismatches, 'origin_certified': False})
        previous = {'date': day, 'close': values['close'], 'factor': values['adj_factor']}
    return {'symbol': symbol, 'counts': dict(counts), 'amount_over_volume_scale_pass_counts': scale_pass,
            'maximum_factor_reference_error_cny': bridge_max, 'factor_reference_mismatch_examples': samples,
            'last_adjusted_observation': last_adjusted, 'public_example_checks': example_results}


def _batch(archive_path, entries, sessions, policy, examples):
    result = []
    with zipfile.ZipFile(archive_path) as archive:
        for member, symbol in entries:
            with archive.open(member) as raw:
                result.append(forensic_profile(io.TextIOWrapper(raw, encoding='utf-8-sig', newline=''),
                                               symbol, sessions, policy, examples))
    return result


def audit_evidence(*, contract_path, calendar_path, examples_path, out):
    contract = json.loads(contract_path.read_text())
    if (contract.get('phase') != 'source_evidence_forensics' or contract.get('research_only') is not True
            or contract.get('orders_authorized') is not False or contract.get('returns_or_rankings') is not False):
        raise ValueError('evidence_contract_invalid')
    archive_path = Path(contract['source']['archive'])
    if (sys.platform != 'linux' or not os.path.ismount('/mnt/e')
            or not archive_path.resolve().is_relative_to(DATASETS)
            or not out.resolve().is_relative_to(ARTIFACTS) or out.exists()):
        raise ValueError('evidence_requires_wsl_and_fresh_e_output')
    for path, expected in ((archive_path, contract['source']['sha256']),
                           (calendar_path, contract['calendar_sha256']),
                           (examples_path, contract['examples_sha256'])):
        if sha256(path) != expected:
            raise ValueError('evidence_input_hash_mismatch:' + path.name)
    audit_root = Path(contract['source']['audit_root'])
    verify_manifest(audit_root, contract['source']['audit_manifest_sha256'])
    sessions, _ = official_calendar(json.loads(calendar_path.read_text()), '2014-01-01', '2026-09-30')
    example_packet = json.loads(examples_path.read_text())
    examples = {}
    for row in example_packet['examples']:
        examples.setdefault(row['symbol'], {}).setdefault(row['date'], []).append(row)
    with zipfile.ZipFile(archive_path) as archive:
        entries = [(info.filename, symbol) for info, symbol in members(archive)]
    before = archive_path.stat()
    profiles = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_batch, archive_path, entries[i:i+32], sessions, contract['policy'], examples)
                   for i in range(0, len(entries), 32)]
        progress = 0
        for future in concurrent.futures.as_completed(futures):
            profiles.extend(future.result())
            if len(profiles) // 1000 > progress:
                progress = len(profiles) // 1000
                print(f'evidence_files={len(profiles)}/{len(entries)}', flush=True)
    after = archive_path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('evidence_source_changed')
    profiles.sort(key=lambda p: p['symbol'])
    totals, scales = collections.Counter(), collections.Counter()
    checks = []
    for profile in profiles:
        totals.update(profile['counts'])
        scales.update(profile['amount_over_volume_scale_pass_counts'])
        checks.extend({'symbol': profile['symbol'], **check} for check in profile['public_example_checks'])
    expected_checks = len(example_packet['examples'])
    latest = [p['last_adjusted_observation'] for p in profiles if p['last_adjusted_observation']]
    summary = {'research_only': True, 'orders_authorized': False, 'promotion_evidence': False,
        'returns_produced': False, 'features_or_rankings_produced': False, 'source_vendor_verified': False,
        'adjustment_semantics_verified': False, 'amount_units_verified': False,
        'evidence_posture': 'algebra_and_published_example_corroboration_not_origin_or_corporate_action_certification',
        'files_profiled': len(profiles), 'counts': dict(totals), 'scale_pass_counts': dict(scales),
        'public_examples_expected': expected_checks, 'public_examples_observed': len(checks),
        'public_examples_missing': expected_checks - len(checks),
        'public_examples_with_mismatch': sum(bool(c['mismatched_fields']) for c in checks),
        'latest_adjusted_observations': len(latest),
        'latest_adjusted_equals_raw_close': sum(math.isclose(p['adjusted_close'], p['raw_close'], rel_tol=1e-8, abs_tol=1e-8) for p in latest),
        'maximum_factor_reference_error_cny': max(p['maximum_factor_reference_error_cny'] for p in profiles),
        'data_gate_transition': 'none_requires_provenance_and_semantics_evidence',
        'calendar_scope': 'SSE_reference_only_SZSE_source_gaps_preserved'}
    out.mkdir(parents=True, exist_ok=False)
    for name, value in [('summary.json', summary), ('security-evidence-profiles.json', profiles),
                        ('public-example-checks.json', checks), ('contract.json', contract),
                        ('public-examples.json', example_packet), ('source-binding.json', {
                            'source_sha256': sha256(archive_path), 'calendar_sha256': sha256(calendar_path),
                            'examples_sha256': sha256(examples_path), 'contract_sha256': sha256(contract_path),
                            'module_sha256': sha256(Path(__file__))})]:
        write_json(out / name, value)
    write_json(out / 'manifest.json', {p.name: sha256(p) for p in sorted(out.iterdir())})
    return {**summary, 'artifact_root': str(out), 'manifest_sha256': sha256(out / 'manifest.json')}
