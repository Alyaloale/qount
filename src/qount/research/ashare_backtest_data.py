"""Read-only, exact-session A-share price-proxy panel for WSL research.

Current L/D/P, industry and name fields remain descriptors, never historical
eligibility filters. Adjusted prices are vendor proxies, not certified cash
total returns. This loader has no acquisition, account, order or write API.
"""
from __future__ import annotations

import concurrent.futures
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import math
import os
import sys
import zipfile
from array import array
from dataclasses import dataclass
from pathlib import Path

from qount.research.ashare_selection import (
    ARTIFACTS, DATASETS, official_calendar, prefix_locator, verify_manifest,
)
from qount.research_data.equity_archive import FIELDS, members, sha256

ROOT = Path(__file__).resolve().parents[3]


def _number(value):
    if value is None or isinstance(value, bool):
        return math.nan
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return math.nan
    return result if math.isfinite(result) else math.nan


def _positive(value):
    return math.isfinite(value) and value > 0


@dataclass
class Series:
    symbol: str
    raw_open: array
    raw_close: array
    raw_high: array
    raw_low: array
    pre_close: array
    factor: array
    adj_open: array
    adj_close: array
    amount_cny: array
    volume: array
    history: array
    valid: bytearray
    source_kind: str


def rows_to_series(symbol, rows, sessions, *, source_kind='original_zip', factors=None):
    """Keep missing days on the exchange grid; maturity uses only past raw OHLC.

    ``history[j]`` includes the current session if its raw OHLC are valid.
    Earlier rows (including 2013) count toward maturity without claiming their
    calendar is certified. Rows after the frozen last session are not consumed.
    Existing adjusted fields are preserved; the retired supplement uses the
    same vendor's raw price times its exact same-day factor, without filling.
    """
    if not sessions or tuple(sorted(set(sessions))) != tuple(sessions):
        raise ValueError('backtest_calendar_not_strictly_increasing')
    if source_kind not in ('original_zip', 'tushare_retired'):
        raise ValueError('backtest_unknown_source_kind')
    if source_kind == 'tushare_retired' and factors is None:
        raise ValueError('backtest_retired_factors_required')
    n = len(sessions)
    index = {day: j for j, day in enumerate(sessions)}
    arrays = {key: array('d', [math.nan]) * n for key in (
        'raw_open', 'raw_close', 'raw_high', 'raw_low', 'pre_close', 'factor',
        'adj_open', 'adj_close', 'amount_cny', 'volume')}
    history, present, valid = array('I', [0]) * n, bytearray(n), bytearray(n)
    count, earlier, previous = 0, 0, ''
    for row in rows:
        day = row['trade_date']
        if not isinstance(day, str) or len(day) != 8 or not day.isdigit():
            raise ValueError('backtest_source_date_invalid')
        # The qualified source is sorted; do not inspect any future payload.
        if day > sessions[-1]:
            break
        if row['ts_code'] != symbol or day <= previous:
            raise ValueError('backtest_source_identity_or_date_order')
        dt.datetime.strptime(day, '%Y%m%d')
        previous = day
        raw = {key: _number(row.get(key)) for key in ('open', 'high', 'low', 'close')}
        raw_valid = (all(_positive(value) for value in raw.values())
                     and raw['low'] <= min(raw['open'], raw['close'])
                     <= max(raw['open'], raw['close']) <= raw['high'])
        count += raw_valid
        if day < sessions[0]:
            earlier = count
            continue
        if day not in index:
            raise ValueError('backtest_source_date_outside_frozen_calendar:' + day)
        j = index[day]
        present[j], history[j] = 1, count
        factor = _number(row.get('adj_factor') if source_kind == 'original_zip' else factors.get(day))
        if source_kind == 'original_zip':
            adj_open, adj_close = _number(row.get('adj_open')), _number(row.get('adj_close'))
        else:
            adj_open = _number(raw['open'] * factor)
            adj_close = _number(raw['close'] * factor)
        amount, volume = _number(row.get('amount')), _number(row.get('vol'))
        for key in raw:
            arrays['raw_' + key][j] = raw[key]
        arrays['pre_close'][j] = _number(row.get('pre_close'))
        arrays['factor'][j] = factor
        arrays['adj_open'][j], arrays['adj_close'][j] = adj_open, adj_close
        arrays['amount_cny'][j], arrays['volume'][j] = _number(amount * 1000), volume
        valid[j] = (raw_valid and all(_positive(value) for value in
                    (factor, adj_open, adj_close, arrays['amount_cny'][j], volume)))
    last = earlier
    for j in range(n):
        if present[j]:
            last = history[j]
        else:
            history[j] = last
    return Series(symbol=symbol, **arrays, history=history, valid=valid, source_kind=source_kind)


def _original_batch(archive, entries, sessions):
    result = []
    with zipfile.ZipFile(archive) as source:
        for member, symbol in entries:
            with source.open(member) as stream:
                reader = csv.DictReader(io.TextIOWrapper(stream, encoding='utf-8-sig', newline=''))
                if tuple(reader.fieldnames or ()) != FIELDS:
                    raise ValueError('backtest_original_schema')
                result.append(rows_to_series(symbol, reader, sessions))
    return result


def _response_rows(root, response):
    target = (root / response['file']).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError('backtest_response_path_escape')
    raw = gzip.decompress(target.read_bytes())
    if hashlib.sha256(raw).hexdigest() != response['raw_response_sha256']:
        raise ValueError('backtest_response_raw_hash')
    body = json.loads(raw)
    data = body.get('data')
    if body.get('code') != 0 or not isinstance(data, dict) or data.get('has_more') is not False:
        raise ValueError('backtest_response_incomplete')
    fields = data['fields']
    if len(fields) != len(set(fields)):
        raise ValueError('backtest_response_duplicate_fields')
    rows = [dict(zip(fields, row, strict=True)) for row in data['items']]
    if len(rows) != response['rows'] or (response['api_name'] == 'daily' and len(rows) >= 6000):
        raise ValueError('backtest_response_count_or_pagination')
    symbol = response.get('params', {}).get('ts_code')
    if symbol and any(row.get('ts_code') != symbol for row in rows):
        raise ValueError('backtest_response_identity')
    return rows


def load_panel(contract):
    """Return ``(sessions, {symbol: Series}, metadata_snapshot, diagnostics)``.

    Contract ``source/qualification/calendar/prefix_locators`` follow the dated
    sector-screen contract. Original and retired inventory counts must be
    explicit. Hash/qualification checks precede raw panel reads. Computation
    is limited to four workers and 32-file streaming ZIP batches on mounted E.
    """
    if (contract.get('research_only') is not True or contract.get('orders_authorized') is not False
            or contract.get('promotion_evidence') is not False):
        raise ValueError('backtest_research_flags_required')
    if sys.platform != 'linux' or not os.path.ismount('/mnt/e'):
        raise ValueError('backtest_panel_requires_WSL_mounted_E')
    source, qualification = contract['source'], contract['qualification']
    archive, source_root, qroot = Path(source['archive']), Path(source['root']), Path(qualification['root'])
    if (not all(path.resolve().is_relative_to(DATASETS) for path in (archive, source_root))
            or not qroot.resolve().is_relative_to(ARTIFACTS)):
        raise ValueError('backtest_source_roots_invalid')
    verify_manifest(qroot, qualification['manifest_sha256'])
    receipt = json.loads((qroot / 'summary.json').read_text())
    if (receipt.get('status') != 'vendor_price_proxy_field_application_qualified'
            or receipt.get('research_only') is not True or receipt.get('orders_authorized') is not False
            or receipt.get('adjustment_semantics_verified_for_information_proxy') is not True
            or receipt.get('adjustment_semantics_scope') != 'vendor_defined_adjusted_price_proxy'
            or receipt.get('source_vendor_verified') is not True
            or receipt.get('independent_calendar_verified') is not True
            or receipt.get('cash_total_return_verified') is not False
            or receipt.get('source_archive_sha256') != source['archive_sha256']
            or receipt.get('source_manifest_sha256') != source['manifest_sha256']
            or receipt.get('calendar_review_sha256') != contract['calendar']['sha256']):
        raise ValueError('backtest_scoped_qualification_invalid')
    verify_manifest(source_root, source['manifest_sha256'])
    if sha256(archive) != source['archive_sha256']:
        raise ValueError('backtest_archive_hash_mismatch')
    calendar_path = Path(contract['calendar']['path'])
    if not calendar_path.is_absolute():
        calendar_path = ROOT / calendar_path
    if sha256(calendar_path) != contract['calendar']['sha256']:
        raise ValueError('backtest_calendar_hash_mismatch')
    review = json.loads(calendar_path.read_text())
    cutoff = contract['price_cutoff']
    end = dt.datetime.strptime(cutoff, '%Y%m%d').date().isoformat()
    sessions, _ = official_calendar(review, '2014-01-01', end)
    second, _ = official_calendar(review, '2014-01-01', end, 'SZSE')
    if sessions != second or len(sessions) != 3100 or sessions[-1] != cutoff:
        raise ValueError('backtest_exchange_calendar_mismatch')
    acquisition = json.loads((source_root / 'acquisition.json').read_text())
    if acquisition.get('status') != 'completed' or acquisition.get('completed_requests') != 807:
        raise ValueError('backtest_source_acquisition_incomplete')
    if contract.get('metadata_observed_at') and acquisition['finished_at'] != contract['metadata_observed_at']:
        raise ValueError('backtest_metadata_timestamp_mismatch')
    metadata, retired = {}, {}
    for response in acquisition['responses']:
        if response['api_name'] == 'stock_basic':
            for row in _response_rows(source_root, response):
                symbol = row['ts_code']
                if symbol in metadata:
                    raise ValueError('backtest_metadata_duplicate')
                metadata[symbol] = row
        elif response['role'] == 'missing_retired_same_provider_source_supplement':
            symbol, api = response['params']['ts_code'], response['api_name']
            parts = retired.setdefault(symbol, {})
            if api not in ('daily', 'adj_factor') or api in parts:
                raise ValueError('backtest_retired_duplicate_or_unknown_api')
            parts[api] = _response_rows(source_root, response)
    if len(retired) != contract['expected_retired_securities']:
        raise ValueError('backtest_retired_inventory_mismatch')
    with zipfile.ZipFile(archive) as source_zip:
        entries = [(info.filename, symbol) for info, symbol in members(source_zip)
                   if prefix_locator(symbol, contract['prefix_locators'])]
    if (len(entries) != contract['expected_source_securities']
            or len({symbol for _, symbol in entries}) != len(entries)):
        raise ValueError('backtest_original_inventory_mismatch')
    panel = {}
    batches = [entries[i:i+32] for i in range(0, len(entries), 32)]
    with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
        for batch in pool.map(_original_batch, [str(archive)] * len(batches), batches,
                              [sessions] * len(batches)):
            panel.update((item.symbol, item) for item in batch)
    for symbol, parts in sorted(retired.items()):
        if set(parts) != {'daily', 'adj_factor'} or symbol in panel:
            raise ValueError('backtest_retired_missing_api_or_overlap')
        factors = {row['trade_date']: _number(row['adj_factor']) for row in parts['adj_factor']}
        if len(factors) != len(parts['adj_factor']) or any(not _positive(value) for value in factors.values()):
            raise ValueError('backtest_retired_factor_identity_or_value')
        rows = sorted(parts['daily'], key=lambda row: row['trade_date'])
        panel[symbol] = rows_to_series(symbol, rows, sessions, source_kind='tushare_retired', factors=factors)
    diagnostics = {
        'research_only': True, 'orders_authorized': False, 'promotion_evidence': False,
        'source_original_securities': len(entries), 'source_retired_securities': len(retired),
        'panel_securities': len(panel), 'exchange_sessions': len(sessions),
        'first_session': sessions[0], 'last_session': sessions[-1],
        'valid_security_sessions': sum(sum(item.valid) for item in panel.values()),
        'metadata_observed_at': acquisition['finished_at'],
        'metadata_use': 'snapshot_descriptor_not_historical_PIT_or_selection_filter',
        'future_exit_or_current_status_filter': False, 'missing_price_fills': 0,
        'adjustment_semantics_scope': receipt['adjustment_semantics_scope'],
        'cash_total_return_verified': False, 'historical_PIT_universe': False,
        'pre_calendar_maturity': 'past_valid_raw_OHLC_only_calendar_unverified_before_2014',
        'amount_multiplier_cny': 1000, 'volume_unit': 'vendor_raw_lots',
    }
    return sessions, panel, metadata, diagnostics
