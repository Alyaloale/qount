"""Single-connection public A-share source supplements, without economic labels."""
from __future__ import annotations

import collections
import contextlib
import datetime as dt
import gzip
import io
import json
import os
import socket
import sys
import time
from pathlib import Path

from qount.research.ashare_selection import DATASETS, prefix_locator, verify_manifest
from qount.research_data.equity_archive import number, sha256, write_json

RAW_FIELDS = ['date', 'code', 'open', 'high', 'low', 'close', 'preclose', 'volume', 'amount', 'tradestatus', 'isST']
FACTOR_FIELDS = ['code', 'dividOperateDate', 'foreAdjustFactor', 'backAdjustFactor', 'adjustFactor']


def select_missing_retired(basic, original_symbols, prefixes, start, end):
    """Retrospective source inventory, never historical board eligibility."""
    fields = ['code', 'code_name', 'ipoDate', 'outDate', 'type', 'status']
    if basic['fields'] != fields:
        raise ValueError('supplement_metadata_schema')
    rows = [dict(zip(fields, row, strict=True)) for row in basic['rows']]
    if len({r['code'] for r in rows}) != len(rows):
        raise ValueError('supplement_duplicate_metadata_code')
    selected = []
    for row in rows:
        if row['type'] != '1' or not row['outDate']:
            continue
        dt.date.fromisoformat(row['outDate'])
        exchange, code = row['code'].split('.')
        symbol = code + '.' + exchange.upper()
        if start <= row['outDate'] <= end and prefix_locator(symbol, prefixes) and symbol not in original_symbols:
            selected.append({**row, 'symbol': symbol, 'historical_board_certified': False})
    return sorted(selected, key=lambda r: r['code'])


def collect_pages(result, expected_fields, save_page, page_size=2000):
    """Preserve each response, including terminal pages; reject masked failures."""
    pages, rows = [], []
    while True:
        if result.error_code != '0' or list(result.fields) != expected_fields:
            raise ValueError('supplement_provider_error_or_schema:' + str(result.error_code))
        page = {'page_number': str(result.cur_page_num), 'error_code': result.error_code,
                'fields': list(result.fields), 'rows': [list(r) for r in result.data]}
        if any(len(row) != len(expected_fields) for row in page['rows']):
            raise ValueError('supplement_response_width')
        save_page(len(pages) + 1, page)
        pages.append({'page_number': page['page_number'], 'rows': len(page['rows'])})
        rows.extend(page['rows'])
        if len(page['rows']) < page_size:
            break
        if len(page['rows']) > page_size:
            raise ValueError('supplement_unexpected_unpaged_response')
        before = str(result.cur_page_num)
        result.cur_row_num = len(result.data)
        advanced = result.next()
        if result.error_code != '0' or str(result.cur_page_num) == before:
            raise ValueError('supplement_pagination_failed_or_stalled')
        if not advanced and result.data:
            raise ValueError('supplement_pagination_false_with_retained_rows')
    return {'fields': expected_fields, 'rows': rows, 'pages': pages, 'protocol_complete': True}


def raw_profile(payload, code, start, end):
    counts = collections.Counter()
    previous = None
    for values in payload['rows']:
        row = dict(zip(RAW_FIELDS, values, strict=True))
        day = row['date']
        dt.date.fromisoformat(day)
        if row['code'] != code or not start <= day <= end or previous is not None and day <= previous:
            raise ValueError('supplement_raw_identity_date_order')
        previous = day
        counts['rows'] += 1
        counts['halted_rows'] += row['tradestatus'] == '0'
        counts['ST_rows'] += row['isST'] == '1'
        counts['missing_activity_rows'] += number(row['volume']) is None or number(row['amount']) is None
        counts['zero_activity_rows'] += number(row['volume']) == 0 or number(row['amount']) == 0
        counts['missing_or_nonpositive_price_rows'] += any(number(row[k]) is None or number(row[k]) <= 0 for k in ('open','high','low','close'))
    return {'code': code, 'counts': dict(counts), 'first_date': payload['rows'][0][0] if payload['rows'] else None,
            'last_date': previous, 'terminal_recovery_or_open_fill_certified': False}


def factor_profile(payload, code, start, end):
    previous = None
    for values in payload['rows']:
        row = dict(zip(FACTOR_FIELDS, values, strict=True))
        day = row['dividOperateDate']
        dt.date.fromisoformat(day)
        if row['code'] != code or not start <= day <= end or previous is not None and day <= previous:
            raise ValueError('supplement_factor_identity_date_order')
        if any(number(row[k]) is None or number(row[k]) <= 0 for k in FACTOR_FIELDS[2:]):
            raise ValueError('supplement_factor_nonpositive_or_nonfinite')
        previous = day
    return {'code': code, 'factor_events': len(payload['rows']), 'empty_event_set_not_imputed': not payload['rows']}


def acquire(*, contract_path, out, sdk_root):
    """Bounded serial collection on WSL/E; preserve partial work on any failure."""
    c = json.loads(contract_path.read_text())
    if c.get('phase') != 'retired_source_supplement' or c.get('research_only') is not True or c.get('orders_authorized') is not False or c.get('returns_produced') is not False:
        raise ValueError('supplement_contract_invalid')
    if sys.platform != 'linux' or not os.path.ismount('/mnt/e') or not out.resolve().is_relative_to(DATASETS) or out.exists():
        raise ValueError('supplement_requires_wsl_and_new_e_dataset')
    if c['network']['connections'] != 1 or c['network']['automatic_retries'] or not 2 <= c['network']['maximum_protocol_requests'] < 50000:
        raise ValueError('supplement_public_network_budget_invalid')
    sdk = c['sdk']
    if sha256(Path(sdk['wheel'])) != sdk['wheel_sha256'] or sdk_root.resolve() != Path(sdk['adapter_root']).resolve():
        raise ValueError('supplement_sdk_binding')
    for name, digest in sdk['adapter_files'].items():
        if sha256(sdk_root / name) != digest:
            raise ValueError('supplement_sdk_file_drift:' + name)
    metadata_root, audit_root = Path(c['metadata']['root']), Path(c['original_audit']['root'])
    verify_manifest(metadata_root, c['metadata']['manifest_sha256'])
    verify_manifest(audit_root, c['original_audit']['manifest_sha256'])
    original = {p['symbol'] for p in json.loads((audit_root / 'members.json').read_text())}
    selected = select_missing_retired(json.loads((metadata_root / 'stock-basic.json').read_text()), original,
        c['prefix_locator_not_historical_board'], c['study_start'], c['study_end'])
    if len(selected) != c['expected_missing_retired_count']:
        raise ValueError('supplement_selection_count_drift')
    out.mkdir(parents=True, exist_ok=False)
    write_json(out / 'contract.json', c)
    write_json(out / 'selected-source-identities.json', selected)
    record = {'research_only': True, 'orders_authorized': False, 'promotion_evidence': False,
              'returns_produced': False, 'signals_or_rankings_produced': False, 'fields_imputed': 0,
              'source': 'BaoStock anonymous public API; separate from owner-attested Tushare archive',
              'automatic_retries': False, 'connections': 1, 'private_credentials_read': False,
              'status': 'running', 'executing_module_sha256': sha256(Path(__file__)),
              'started_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'protocol_requests': 0,
              'completed_securities': 0, 'selected_securities': len(selected), 'profiles': []}
    socket.setdefaulttimeout(c['network']['socket_timeout_seconds'])
    sys.path.insert(0, str(sdk_root)); sys.dont_write_bytecode = True
    import baostock as bs
    import baostock.util.socketutil as sock
    original_send = sock.send_msg
    last_request = 0.0
    def send(message):
        nonlocal last_request
        if record['protocol_requests'] >= c['network']['maximum_protocol_requests']:
            raise RuntimeError('supplement_protocol_budget_exhausted')
        pause = c['network']['minimum_request_spacing_seconds'] - (time.monotonic() - last_request)
        if pause > 0:
            time.sleep(pause)
        record['protocol_requests'] += 1
        last_request = time.monotonic()
        response = original_send(message)
        if not response or not response.strip():
            raise RuntimeError('supplement_empty_protocol_response_no_retry')
        return response
    sock.send_msg = send
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            login = bs.login()
            if login.error_code != '0':
                raise RuntimeError('supplement_anonymous_login_failed:' + login.error_code)
        for i, stock in enumerate(selected):
            stem = stock['code'].replace('.', '-')
            def save(kind):
                def write(page, value):
                    path = out / 'raw-pages' / f'{stem}-{kind}-{page}.json.gz'
                    path.parent.mkdir(exist_ok=True)
                    with gzip.open(path, 'wt', encoding='utf-8') as stream:
                        json.dump(value, stream, ensure_ascii=False, separators=(',', ':'))
                return write
            with contextlib.redirect_stdout(io.StringIO()):
                raw = collect_pages(bs.query_history_k_data_plus(stock['code'], ','.join(RAW_FIELDS),
                    start_date=c['raw_start'], end_date=c['study_end'], frequency='d', adjustflag='3'), RAW_FIELDS, save('raw'))
                factors = collect_pages(bs.query_adjust_factor(code=stock['code'], start_date=c['factor_start'],
                    end_date=c['study_end']), FACTOR_FIELDS, save('factor'))
            profile = raw_profile(raw, stock['code'], c['raw_start'], c['study_end'])
            profile.update(factor_profile(factors, stock['code'], c['factor_start'], c['study_end']))
            profile['raw_pages'], profile['factor_pages'] = raw['pages'], factors['pages']
            record['profiles'].append(profile)
            record['completed_securities'] = i + 1
            write_json(out / 'status.json', {k: v for k, v in record.items() if k != 'profiles'})
            if (i + 1) % 10 == 0 or i + 1 == len(selected):
                print(f'supplement_securities={i+1}/{len(selected)} requests={record["protocol_requests"]}', flush=True)
        with contextlib.redirect_stdout(io.StringIO()):
            logout = bs.logout()
            if logout.error_code != '0':
                raise RuntimeError('supplement_anonymous_logout_failed:' + logout.error_code)
        record['status'] = 'completed'
    except BaseException as exc:
        record.update(status='failed_partial_preserved', error_type=type(exc).__name__, error=str(exc))
    finally:
        sock.send_msg = original_send
        record['finished_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
        counts = collections.Counter()
        for p in record['profiles']:
            counts.update(p['counts'])
        record['counts'] = dict(counts)
        record['factor_events'] = sum(p['factor_events'] for p in record['profiles'])
        write_json(out / 'summary.json', record)
        write_json(out / 'manifest.json', {str(p.relative_to(out)): sha256(p) for p in sorted(out.rglob('*')) if p.is_file()})
    return {k: v for k, v in record.items() if k != 'profiles'}
