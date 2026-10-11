"""Dated, no-order sector/stock research queue; no forward labels or portfolio.

Industry descriptors are a present-day vendor snapshot, never historical PIT.
Financial and catalyst evidence belongs to a separate cited diligence overlay.
"""
from __future__ import annotations

import collections
import concurrent.futures
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import math
import os
import statistics
import sys
import zipfile
from pathlib import Path

from qount.research.ashare_selection import ARTIFACTS, DATASETS, official_calendar, prefix_locator, verify_manifest
from qount.research_data.equity_archive import FIELDS, members, number, sha256, write_json

ROOT = Path(__file__).resolve().parents[3]
RULES = {
    'price_sessions': 61, 'history_valid_raw_observations': 252,
    'liquidity_sessions': 20, 'amount_multiplier_cny': 1000,
    'minimum_median_amount_cny': 20_000_000, 'minimum_sector_members': 10,
    'sector_sort': 'median_change60_desc_then_industry_ascending',
    'sector_gate': 'median_change20_gt_zero_and_positive20_fraction_ge_half',
    'sector_count': 5, 'stocks_per_sector': 2,
    'stock_sort': 'change60_desc_then_symbol_ascending',
    'volatility': 'population_std_60_log_changes_times_sqrt252_diagnostic_only',
    'metadata_use': '20261009_descriptor_snapshot_not_historical_PIT',
    'financials_and_catalysts': 'separate_cited_review_no_numeric_score_or_rank_rewrite',
}


def window_inputs(rows, symbol, sessions, cutoff):
    """Only consume the closed prefix; missing exchange sessions remain missing."""
    if cutoff not in sessions or sessions.index(cutoff) < 60:
        raise ValueError('screen_cutoff_not_supported')
    days = sessions[sessions.index(cutoff)-60:sessions.index(cutoff)+1]
    wanted, window = set(days), {}
    history, previous = 0, ''
    for row in rows:
        day = row['trade_date']
        # Sorted archive contract lets us stop before accessing any later prices.
        if day > cutoff:
            break
        if row['ts_code'] != symbol or day <= previous:
            raise ValueError('screen_identity_or_date_order')
        dt.datetime.strptime(day, '%Y%m%d')
        previous = day
        raw = [number(row[k]) for k in ('open', 'high', 'low', 'close')]
        raw_valid = (all(x is not None and x > 0 for x in raw)
                     and raw[2] <= min(raw[0], raw[3]) <= max(raw[0], raw[3]) <= raw[1])
        history += raw_valid
        if day in wanted:
            window[day] = {'raw_valid': raw_valid, 'close': number(row['adj_close']),
                           'factor': number(row['adj_factor']), 'amount': number(row['amount']),
                           'volume': number(row['vol']), 'raw_close': raw[3]}
    return {'symbol': symbol, 'history': history, 'days': list(days),
            'window': [window.get(day) for day in days]}


def features(inputs):
    """Price strength is a screening feature, not a future-return result."""
    result = {'symbol': inputs['symbol'], 'status': 'signal_available'}
    window = inputs['window']
    reason = ('history_insufficient' if inputs['history'] < 252 else
              'calendar_window_missing' if len(window) != 61 or any(x is None for x in window) else
              'price_or_adjustment_invalid' if any(not x['raw_valid'] or any(
                  x[k] is None or x[k] <= 0 for k in ('close', 'factor')) for x in window) else
              'activity_missing_or_nonpositive' if any(any(x[k] is None or x[k] <= 0
                  for k in ('amount', 'volume')) for x in window) else None)
    if reason:
        return {**result, 'status': reason}
    closes = [x['close'] for x in window]
    amount = statistics.median(x['amount'] for x in window[-20:]) * 1000
    if amount < 20_000_000:
        return {**result, 'status': 'below_liquidity_floor', 'median_amount20_cny': amount}
    changes = [math.log(b/a) for a, b in zip(closes, closes[1:])]
    return {**result, 'change20': closes[-1]/closes[-21]-1,
            'change60': closes[-1]/closes[0]-1,
            'vol60_annualized': statistics.pstdev(changes)*math.sqrt(252),
            'median_amount20_cny': amount, 'raw_close_at_cutoff': window[-1]['raw_close']}


def build_queue(signals, metadata):
    """One fixed industry funnel. Later diligence never silently replaces names."""
    groups, all_rows = collections.defaultdict(list), []
    if len({x['symbol'] for x in signals}) != len(signals):
        raise ValueError('screen_duplicate_symbol')
    for signal in signals:
        descriptor = metadata.get(signal['symbol'], {})
        row = {**signal, 'name': descriptor.get('name'), 'industry': descriptor.get('industry'),
               'metadata_list_status': descriptor.get('list_status'),
               'metadata_market': descriptor.get('market'),
               'metadata_list_date': descriptor.get('list_date'),
               'eligibility': 'pending_dated_ST_board_and_tradability',
               'research_bucket': 'C_screen_flag_only'}
        # Industry, listing and risk-warning exclusions use the stated current
        # descriptor snapshot, not an assertion of cutoff-date eligibility.
        if row['status'] == 'signal_available':
            if not row['industry']:
                row['status'] = 'industry_descriptor_missing'
            elif not row['name'] or row['metadata_list_status'] != 'L' or row['metadata_market'] != '主板':
                row['status'] = 'descriptor_scope_excluded'
            elif 'ST' in row['name'].upper() or '退' in row['name']:
                row['status'] = 'descriptor_risk_warning_excluded'
            else:
                groups[row['industry']].append(row)
        all_rows.append(row)
    sectors = []
    for industry, rows in groups.items():
        n = len(rows)
        m20, m60 = (statistics.median(row[k] for row in rows) for k in ('change20', 'change60'))
        breadth = sum(row['change20'] > 0 for row in rows)/n
        status = ('insufficient_members' if n < 10 else 'weak_recent_breadth'
                  if m20 <= 0 or breadth < .5 else 'sector_available')
        sectors.append({'industry': industry, 'members': n, 'median_change20': m20,
                        'median_change60': m60, 'positive20_fraction': breadth, 'status': status})
    sectors.sort(key=lambda x: (-x['median_change60'], x['industry']))
    selected = [x for x in sectors if x['status'] == 'sector_available'][:5]
    queue = []
    for rank, sector in enumerate(selected, 1):
        sector['selected_sector_rank'] = rank
        stocks = sorted(groups[sector['industry']], key=lambda x: (-x['change60'], x['symbol']))
        for stock_rank, row in enumerate(stocks[:2], 1):
            queue.append({**row, 'sector_rank': rank, 'stock_rank_in_sector': stock_rank,
                          'queue_position': len(queue)+1})
    return sectors, queue, all_rows


def _batch(archive_path, entries, sessions, cutoff):
    result = []
    with zipfile.ZipFile(archive_path) as archive:
        for name, symbol in entries:
            with archive.open(name) as member:
                reader = csv.DictReader(io.TextIOWrapper(member, encoding='utf-8-sig', newline=''))
                if tuple(reader.fieldnames or ()) != FIELDS:
                    raise ValueError('screen_original_schema')
                inputs = window_inputs(reader, symbol, sessions, cutoff)
                result.append((inputs, features(inputs)))
    return result


def run(*, contract_path, out):
    contract = json.loads(contract_path.read_text())
    if (contract.get('phase') != 'sector_company_wind_research_queue'
            or contract.get('rules') != RULES or contract.get('research_only') is not True
            or contract.get('orders_authorized') is not False or contract.get('promotion_evidence') is not False
            or contract.get('authorization') != {'screen': True, 'future_labels': False,
                'portfolio': False, 'automatic_restart': False, 'production_or_account_access': False}):
        raise ValueError('screen_contract_invalid')
    if (sys.platform != 'linux' or not os.path.ismount('/mnt/e')
            or not out.resolve().is_relative_to(ARTIFACTS) or out.exists()):
        raise ValueError('screen_fresh_mounted_E_required')
    for relative, digest in contract['implementation_sha256'].items():
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT) or sha256(path) != digest:
            raise ValueError('screen_implementation_mismatch:' + relative)
    if not {'src/qount/research/ashare_sector_screen.py', 'src/qount/research/ashare_selection.py',
            'src/qount/research_data/equity_archive.py'} <= set(contract['implementation_sha256']):
        raise ValueError('screen_unbound_dependencies')
    source, qualification = contract['source'], contract['qualification']
    qroot = Path(qualification['root'])
    verify_manifest(qroot, qualification['manifest_sha256'])
    q = json.loads((qroot/'summary.json').read_text())
    if (q.get('adjustment_semantics_verified_for_information_proxy') is not True
            or q.get('adjustment_semantics_scope') != 'vendor_defined_adjusted_price_proxy'
            or q.get('source_vendor_verified') is not True
            or q.get('independent_calendar_verified') is not True
            or q.get('source_archive_sha256') != source['archive_sha256']
            or q.get('source_manifest_sha256') != source['manifest_sha256']
            or q.get('calendar_review_sha256') != contract['calendar']['sha256']):
        raise ValueError('screen_scoped_qualification_invalid')
    archive, source_root = Path(source['archive']), Path(source['root'])
    if not all(p.resolve().is_relative_to(DATASETS) for p in (archive, source_root)):
        raise ValueError('screen_dataset_path_invalid')
    verify_manifest(source_root, source['manifest_sha256'])
    if sha256(archive) != source['archive_sha256']:
        raise ValueError('screen_archive_hash_mismatch')
    calendar = ROOT / contract['calendar']['path']
    if sha256(calendar) != contract['calendar']['sha256']:
        raise ValueError('screen_calendar_hash_mismatch')
    review = json.loads(calendar.read_text())
    cutoff = contract['price_cutoff']
    end = dt.datetime.strptime(cutoff, '%Y%m%d').date().isoformat()
    sessions, _ = official_calendar(review, '2014-01-01', end)
    other, _ = official_calendar(review, '2014-01-01', end, 'SZSE')
    if sessions != other or sessions[-1] != cutoff:
        raise ValueError('screen_calendar_cutoff_mismatch')
    acquisition = json.loads((source_root/'acquisition.json').read_text())
    if acquisition['finished_at'] != contract['metadata_observed_at'] or acquisition['status'] != 'completed':
        raise ValueError('screen_descriptor_timestamp_mismatch')
    metadata = {}
    for response in acquisition['responses']:
        if response['api_name'] != 'stock_basic':
            continue
        raw = gzip.decompress((source_root/response['file']).read_bytes())
        if hashlib.sha256(raw).hexdigest() != response['raw_response_sha256']:
            raise ValueError('screen_descriptor_raw_hash')
        body = json.loads(raw)
        if body['code'] != 0 or body['data']['has_more'] is not False:
            raise ValueError('screen_descriptor_incomplete')
        rows = [dict(zip(body['data']['fields'], row, strict=True)) for row in body['data']['items']]
        if len(rows) != response['rows']:
            raise ValueError('screen_descriptor_count')
        for row in rows:
            if row['ts_code'] in metadata:
                raise ValueError('screen_descriptor_duplicate')
            metadata[row['ts_code']] = row
    with zipfile.ZipFile(archive) as z:
        entries = [(info.filename, symbol) for info, symbol in members(z)
                   if prefix_locator(symbol, contract['prefix_locators'])]
    if len(entries) != contract['expected_source_securities']:
        raise ValueError('screen_source_inventory_mismatch')
    out.mkdir(parents=True)
    write_json(out/'contract.json', contract)
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    signals = []
    batches = [entries[i:i+32] for i in range(0, len(entries), 32)]
    with gzip.open(out/'signal-inputs.jsonl.gz', 'wt', encoding='utf-8') as stream:
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
            for batch in pool.map(_batch, [str(archive)]*len(batches), batches,
                                  [sessions]*len(batches), [cutoff]*len(batches)):
                for inputs, signal in batch:
                    stream.write(json.dumps(inputs, allow_nan=False, separators=(',', ':'))+'\n')
                    signals.append(signal)
    sectors, queue, rows = build_queue(signals, metadata)
    write_json(out/'sectors.json', sectors)
    write_json(out/'queue.json', queue)
    write_json(out/'security-signals.json', rows)
    summary = {'research_only': True, 'orders_authorized': False, 'promotion_evidence': False,
               'study_id': contract['study_id'], 'status': 'historical_price_research_queue',
               'started_at': started, 'finished_at': dt.datetime.now(dt.timezone.utc).isoformat(),
               'price_cutoff': cutoff, 'metadata_observed_at': contract['metadata_observed_at'],
               'contract_sha256': sha256(contract_path), 'source_securities': len(entries),
               'signal_available_before_descriptors': sum(x['status']=='signal_available' for x in signals),
               'sector_members_after_descriptors': sum(x['status']=='signal_available' for x in rows),
               'status_counts': dict(collections.Counter(x['status'] for x in rows)),
               'sector_count': len(sectors), 'selected_sectors': sum('selected_sector_rank' in x for x in sectors),
               'queue_count': len(queue), 'current_trade_day_list': False,
               'historical_PIT_universe': False, 'future_labels_produced': False,
               'returns_or_NAV_evaluated': False, 'fundamentals_scored': False,
               'new_registered_rule_sets': 1, 'parameter_searches': 0,
               'financial_and_catalyst_review': 'separate_evidence_overlay_pending',
               'forward_observation': 'waiting_for_fresh_dated_eligible_snapshot_no_scheduler',
               'artifact_root': str(out)}
    write_json(out/'summary.json', summary)
    write_json(out/'forward-registry.json', {'registered_at': summary['finished_at'],
               'study_id': contract['study_id'], 'frozen_queue_sha256': sha256(out/'queue.json'),
               'status': summary['forward_observation'], 'backdated_forward_evidence': False,
               'next_step': 'fresh same-provider prices and dated eligibility; then timestamp a new snapshot',
               'orders_authorized': False, 'scheduled': False})
    write_json(out/'manifest.json', {p.name: sha256(p) for p in sorted(out.iterdir()) if p.is_file()})
    return {**summary, 'manifest_sha256': sha256(out/'manifest.json')}
