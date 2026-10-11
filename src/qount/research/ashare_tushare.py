"""Mac-memory Tushare transport and immutable public-response acquisition."""
from __future__ import annotations

import collections
import datetime as dt
import gzip
import hashlib
import json
import ssl
import sys
import time
import urllib.request
from pathlib import Path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('tushare_credential_redirect_refused')


def validate_response(raw, *, secret, api, params, fields):
    """Check export safety, schema, explicit paging and source identities."""
    if secret.encode() in raw:
        raise ValueError('tushare_response_contains_credential_refuse_export')
    value = json.loads(raw)
    if value.get('code') != 0:
        raise ValueError('tushare_provider_error:' + str(value.get('code')) + ':' + str(value.get('msg') or ''))
    data = value.get('data')
    expected = fields.split(',')
    if not isinstance(data, dict) or data.get('fields') != expected or not isinstance(data.get('items'), list):
        raise ValueError('tushare_response_schema')
    if data.get('has_more') is not False:
        raise ValueError('tushare_incomplete_or_unspecified_paging')
    rows = data['items']
    if any(not isinstance(r, list) or len(r) != len(expected) for r in rows):
        raise ValueError('tushare_response_width')
    if api in ('adj_factor', 'daily'):
        identities = set()
        for r in rows:
            row = dict(zip(expected, r, strict=True))
            day = row['trade_date']
            dt.datetime.strptime(day, '%Y%m%d')
            if row['ts_code'] != params['ts_code'] or not params['start_date'] <= day <= params['end_date']:
                raise ValueError('tushare_response_identity_or_range')
            if day in identities:
                raise ValueError('tushare_duplicate_date')
            identities.add(day)
        if api == 'daily' and len(rows) >= 6000:
            raise ValueError('tushare_daily_at_documented_limit')
    elif api == 'stock_basic':
        index = expected.index('ts_code')
        if len({r[index] for r in rows}) != len(rows) or len(rows) >= 6000:
            raise ValueError('tushare_master_duplicate_or_limit')
    return {'rows':len(rows), 'fields':expected, 'has_more':False, 'provider_code':0}


def acquire(*, contract_path, token, put_public, receipt_path):
    """One serial Mac HTTPS run; callback receives only credential-free bytes."""
    c = json.loads(contract_path.read_text())
    if (sys.platform != 'darwin' or c.get('phase') != 'tushare_same_source_supplement'
        or c.get('research_only') is not True or c.get('orders_authorized') is not False
        or c.get('returns_produced') is not False or c.get('credential_host') != 'Mac_memory_only'
        or c['network']['automatic_retries'] or c['network']['connections'] != 1):
        raise ValueError('tushare_source_contract_or_host')
    if not token or not token.isalnum():
        raise ValueError('tushare_invalid_credential_shape')
    if receipt_path.exists():
        raise ValueError('tushare_fresh_receipt_required')
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    record = {'research_only':True,'orders_authorized':False,'promotion_evidence':False,
        'returns_produced':False,'signals_or_rankings_produced':False,'credentials_persisted_or_exported':False,
        'started_at':dt.datetime.now(dt.timezone.utc).isoformat(),'status':'running',
        'contract_sha256':hashlib.sha256(contract_path.read_bytes()).hexdigest(),
        'module_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'planned_requests':len(c['requests']),'completed_requests':0,'responses':[]}
    last = 0.0
    try:
        put_public('contract.json', contract_path.read_bytes())
        for i, spec in enumerate(c['requests'], 1):
            if i > c['network']['maximum_requests']:
                raise RuntimeError('tushare_request_budget')
            pause = c['network']['minimum_spacing_seconds']-(time.monotonic()-last)
            if pause>0:
                time.sleep(pause)
            last = time.monotonic()
            request = urllib.request.Request('https://api.tushare.pro',
                data=json.dumps({'api_name':spec['api_name'],'token':token,'params':spec['params'],'fields':spec['fields']}).encode(),
                headers={'Content-Type':'application/json','User-Agent':'qount-research-source/1'}, method='POST')
            with opener.open(request, timeout=c['network']['timeout_seconds']) as response:
                raw = response.read(c['network']['maximum_response_bytes']+1)
                if len(raw)>c['network']['maximum_response_bytes']:
                    raise RuntimeError('tushare_response_size_budget')
                if token.encode() in raw:
                    raise RuntimeError('tushare_response_contains_credential_refuse_export')
                # Preserve an unsuccessful public provider response before validation;
                # never preserve a request body, token, headers or opener state.
                name = f'raw/{i:04d}-{spec["id"]}.json.gz'
                put_public(name, gzip.compress(raw, mtime=0))
                checked = validate_response(raw, secret=token, api=spec['api_name'],params=spec['params'],fields=spec['fields'])
            record['responses'].append({**spec,**checked,'file':name,'raw_response_sha256':hashlib.sha256(raw).hexdigest()})
            record['completed_requests'] = i
            if i%20==0 or i==len(c['requests']):
                receipt_path.write_text(json.dumps({k:v for k,v in record.items() if k!='responses'},indent=2)+'\n')
                print(f'tushare_requests={i}/{len(c["requests"])}',flush=True)
        record['status'] = 'completed'
    except BaseException as exc:
        record.update(status='failed_partial_preserved',error_type=type(exc).__name__,error=str(exc).replace(token,'[redacted]'))
    finally:
        token = None
        record['finished_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
        record['row_counts_by_api'] = dict(collections.Counter())
        counts = collections.Counter()
        for r in record['responses']:
            counts[r['api_name']] += r['rows']
        record['row_counts_by_api'] = dict(counts)
        receipt_path.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
        put_public('acquisition.json',receipt_path.read_bytes())
    return {k:v for k,v in record.items() if k!='responses'}
