"""Budgeted Mac-only P1 public data collection; credentials never cross SSH."""
from __future__ import annotations

import base64
import calendar
import collections
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path
import random
import selectors
import ssl
import stat
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
import http.client

from qount.research.ashare_tushare import NoRedirect

ALLOWED = frozenset(('stock_basic','trade_cal','index_classify','index_member_all',
    'income_vip','cashflow_vip','balancesheet_vip','dividend','forecast_vip',
    'express_vip','disclosure_date','daily','daily_basic','adj_factor','stk_limit',
    'suspend_d','namechange','bak_basic','index_daily','shibor','stk_weekly_monthly',
    'stk_holdernumber','new_share','stk_auction','stock_st','st','bse_mapping','index_basic'))
MASTER_FIELDS = 'ts_code,symbol,name,area,industry,fullname,enname,cnspell,market,exchange,curr_type,list_status,list_date,delist_date,is_hs,act_name,act_ent_type'
DIVIDEND_FIELDS = 'ts_code,end_date,ann_date,div_proc,stk_div,stk_bo_rate,stk_co_rate,cash_div,cash_div_tax,record_date,ex_date,pay_date,div_listdate,imp_ann_date,base_date,base_share'


def json_bytes(value):
    return (json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def saved_token(path):
    if sys.platform != 'darwin':
        raise ValueError('credential_Mac_only')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.getuid()):
            raise ValueError('credential_requires_owned_regular_0600')
        lines = stream.read(4096).splitlines()
    if len(lines) != 1 or not lines[0].startswith('TUSHARE_TOKEN='):
        raise ValueError('credential_format')
    token = lines[0].split('=',1)[1]
    if not token or not token.isalnum():
        raise ValueError('credential_shape')
    return token


def check_page(raw, token, api, params, fields=''):
    if token.encode() in raw:
        raise ValueError('credential_in_response_refuse_export')
    value = json.loads(raw)
    if value.get('code') != 0:
        return value, None
    data = value.get('data')
    if (not isinstance(data,dict) or not isinstance(data.get('fields'),list)
            or not data['fields'] or not isinstance(data.get('items'),list)
            or type(data.get('has_more')) is not bool):
        raise ValueError('source_schema_or_paging')
    names, rows = data['fields'], data['items']
    if len(set(names)) != len(names) or any(not isinstance(n,str) for n in names):
        raise ValueError('duplicate_or_invalid_fields')
    if fields and names != fields.split(','):
        raise ValueError('source_fields_mismatch')
    if any(not isinstance(r,list) or len(r)!=len(names) for r in rows):
        raise ValueError('source_row_width')
    for key, expected in (('ts_code',params.get('ts_code')),('trade_date',params.get('trade_date')),
                          ('end_date',params.get('period')),('report_type',params.get('report_type'))):
        if expected and key in names and any(r[names.index(key)] != expected for r in rows):
            raise ValueError('source_identity_or_period:'+key)
    if api == 'trade_cal':
        i = names.index('cal_date')
        if any(not params['start_date'] <= r[i] <= params['end_date'] for r in rows):
            raise ValueError('calendar_date_range')
    if api in ('daily','daily_basic','adj_factor','stk_limit'):
        keys = [(r[names.index('ts_code')],r[names.index('trade_date')]) for r in rows]
        if len(set(keys)) != len(keys):
            raise ValueError('duplicate_market_key_in_page')
    return value, data


def page_continues(data, limit):
    if data['has_more'] and not data['items']:
        raise ValueError('empty_page_claims_more')
    # Even a false flag at the cap requires the next offset to be observed.
    return data['has_more'] or len(data['items']) >= limit


def retryable_provider(code, message):
    if code == 40101:
        return False
    return any(term in str(message).lower() for term in ('每分钟','频率','频次','限流','rate limit','too many'))


def backoff(attempt, *, rate_limited=False):
    return min(120.,(15. if rate_limited else 1.)*2**attempt)+random.uniform(0.,.5)


class WindowsPublicSink:
    """One SSH stream of hash-verified public files, no credentials or requests."""
    def __init__(self, root, script):
        if (not root.startswith('E:/qount_data/qount/datasets/equity_selection/')
                or any(c in root+script for c in "'\n\r")):
            raise ValueError('public_sink_path')
        command = f"pwsh -NoLogo -NoProfile -NonInteractive -File '{script}' -Root '{root}'"
        self.process = subprocess.Popen(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15',
            'qount-win',command],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        self.lock = threading.Lock()
        if self._line() != b'READY':
            self.close()
            raise RuntimeError('public_sink_not_ready')

    def _line(self):
        with selectors.DefaultSelector() as selection:
            selection.register(self.process.stdout, selectors.EVENT_READ)
            if not selection.select(45):
                self.process.kill()
                raise TimeoutError('public_sink_ack_timeout')
        return self.process.stdout.readline().strip()

    def put(self, name, public):
        if len(public)>64_000_000:
            raise ValueError('public_sink_size')
        digest = sha(public)
        packet = json.dumps({'name':name,'sha256':digest,'data':base64.b64encode(public).decode()}).encode()+b'\n'
        with self.lock:
            self.process.stdin.write(packet); self.process.stdin.flush()
            if self._line() != digest.encode():
                raise RuntimeError('public_sink_write_or_hash_failed')

    def close(self):
        if self.process.stdin:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill(); self.process.wait()


class Collector:
    def __init__(self, *, token, sink, local, contract):
        if sys.platform != 'darwin' or contract.get('research_only') is not True or contract.get('orders_authorized') is not False:
            raise ValueError('research_Mac_contract_required')
        self.token, self.sink, self.local, self.contract = token, sink, Path(local), contract
        self.local.mkdir(parents=True,exist_ok=False)
        self.lock = threading.Lock(); self.rate_lock = threading.Lock()
        self.next_request = 0.; self.attempts = 0; self.closed_apis = set(); self.fatal = False
        self.spacing = contract['minimum_spacing_seconds']; self.resume = {}
        self.responses, self.jobs = [], []
        self.started = dt.datetime.now(dt.timezone.utc).isoformat()
        self.sink.put('contract.json',json_bytes(contract))
        (self.local/'contract.json').write_bytes(json_bytes(contract))
        for source in contract.get('reuse_sources',[]):
            path=Path(source['local_jobs'])
            if sha(path.read_bytes())!=source['jobs_sha256']:
                raise ValueError('reuse_jobs_hash_mismatch')
            for line in path.read_text().splitlines():
                prior=json.loads(line)
                if prior['status']=='completed':
                    self.resume[prior['id']]={**prior,'source_root':source['root']}

    def request(self, api, params, fields):
        if api not in ALLOWED:
            raise ValueError('unapproved_endpoint')
        with self.rate_lock:
            if self.fatal or api in self.closed_apis:
                raise RuntimeError('endpoint_stopped')
            if self.attempts >= self.contract['maximum_requests']:
                self.fatal = True
                raise RuntimeError('request_budget_exhausted')
            time.sleep(max(0.,self.next_request-time.monotonic()))
            self.next_request = time.monotonic()+self.spacing
            self.attempts += 1
        opener = urllib.request.build_opener(NoRedirect(),urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        request = urllib.request.Request('https://api.tushare.pro',
            data=json.dumps({'api_name':api,'token':self.token,'params':params,'fields':fields}).encode(),
            headers={'Content-Type':'application/json','User-Agent':'qount-P1-public-source/1'},method='POST')
        with opener.open(request,timeout=self.contract['timeout_seconds']) as response:
            raw = response.read(64_000_001)
        if len(raw)>64_000_000:
            raise ValueError('response_size_budget')
        value,data = check_page(raw,self.token,api,params,fields)
        return raw,value,data

    def fetch_page(self, spec, params, page):
        api=spec['api_name']
        for attempt in range(self.contract['maximum_retries']+1):
            rate_limited=False
            try:
                raw,value,data=self.request(api,params,spec.get('fields',''))
                name=f'raw/{spec["id"]}/{page:04d}-attempt{attempt:02d}.json.gz'
                packed=gzip.compress(raw,mtime=0)
                try:
                    self.sink.put(name,packed)
                except Exception:
                    self.fatal=True
                    raise RuntimeError('public_sink_failed_stop_collection') from None
                item={'job_id':spec['id'],'api_name':api,'params':params,'page':page,'attempt':attempt,
                    'file':name,'raw_sha256':sha(raw),'file_sha256':sha(packed),'code':value.get('code'),
                    'rows':len(data['items']) if data else 0,'fields':data['fields'] if data else None,
                    'has_more':data['has_more'] if data else None}
                with self.lock:
                    self.responses.append(item)
                    with (self.local/'responses.jsonl').open('ab') as stream:
                        stream.write(json.dumps(item,ensure_ascii=False).encode()+b'\n')
                if data is not None:
                    return data,item
                rate_limited=retryable_provider(value.get('code'),value.get('msg'))
                if not rate_limited:
                    with self.rate_lock:
                        self.closed_apis.add(api)
                        if value.get('code')==40101:
                            self.fatal=True
                    raise ValueError('provider_error:'+str(value.get('code'))+':'+str(value.get('msg') or '').replace(self.token,'[redacted]'))
            except (urllib.error.URLError,TimeoutError,ConnectionError,http.client.IncompleteRead,
                    http.client.RemoteDisconnected,ssl.SSLEOFError) as exc:
                if 'public_sink' in str(exc):
                    self.fatal=True
                    raise
                if isinstance(exc,urllib.error.HTTPError) and exc.code not in (429,500,502,503,504):
                    raise
                rate_limited=isinstance(exc,urllib.error.HTTPError) and exc.code==429
                with self.lock:
                    with (self.local/'transport-errors.jsonl').open('a') as stream:
                        stream.write(json.dumps({'job':spec['id'],'page':page,'attempt':attempt,
                            'error_type':type(exc).__name__})+'\n')
            if attempt==self.contract['maximum_retries']:
                raise RuntimeError('transient_retry_budget_exhausted')
            delay=backoff(attempt,rate_limited=rate_limited)
            if rate_limited:
                with self.rate_lock:
                    self.spacing=min(2.,self.spacing*2.)
                    self.next_request=max(self.next_request,time.monotonic()+delay)
            time.sleep(delay)
        raise AssertionError('unreachable_retry_state')

    def job(self, spec, *, keep_rows=False):
        api = spec['api_name']; fields = spec.get('fields',''); limit = spec.get('page_size',5000)
        pages, kept, seen, schema = [], [], set(), None
        status, error = 'completed', None
        try:
            if not keep_rows and spec['id'] in self.resume:
                prior=self.resume[spec['id']]
                if any(prior.get(k)!=spec.get(k) for k in ('api_name','params','fields','page_size','paged')):
                    raise ValueError('reuse_spec_mismatch')
                record={**spec,'status':'reused','pages':prior['pages'],'rows':prior['rows'],
                    'error':None,'source_root':prior['source_root']}
                with self.lock:
                    self.jobs.append(record)
                    with (self.local/'jobs.jsonl').open('ab') as stream:
                        stream.write(json.dumps(record,ensure_ascii=False).encode()+b'\n')
                return record,[]
            for page in range(self.contract['maximum_pages_per_job']):
                params = dict(spec['params'])
                if spec.get('paged',True):
                    params.update(limit=limit,offset=page*limit)
                data,item=self.fetch_page(spec,params,page)
                pages.append(item)
                if schema is not None and schema != data['fields']:
                    raise ValueError('page_schema_changed')
                schema = data['fields']
                fingerprint = sha(json_bytes([schema,data['items']]))
                if data['items'] and fingerprint in seen:
                    raise ValueError('offset_ignored_repeated_page')
                seen.add(fingerprint)
                if keep_rows:
                    kept += [dict(zip(schema,r,strict=True)) for r in data['items']]
                if not spec.get('paged',True):
                    if page_continues(data,limit):
                        raise ValueError('unpaged_response_at_cap_or_incomplete')
                    break
                if not page_continues(data,limit):
                    break
            else:
                raise ValueError('page_budget_exhausted')
        except BaseException as exc:
            status='failed_or_withheld'
            error=type(exc).__name__+':'+str(exc).replace(self.token,'[redacted]')
            if 'public_sink' in error:
                self.fatal=True
        record={**spec,'status':status,'pages':len(pages),'rows':sum(p['rows'] for p in pages),'error':error}
        with self.lock:
            self.jobs.append(record)
            with (self.local/'jobs.jsonl').open('ab') as stream:
                stream.write(json.dumps(record,ensure_ascii=False).encode()+b'\n')
        return record,kept

    def phase(self, name, specs):
        self.sink.put(f'plans/{name}.json',json_bytes(specs))
        (self.local/f'{name}-plan.json').write_bytes(json_bytes(specs))
        with ThreadPoolExecutor(max_workers=self.contract['workers']) as pool:
            futures=[pool.submit(self.job,s) for s in specs]
            for i,future in enumerate(as_completed(futures),1):
                result,_ = future.result()
                if i%25==0 or i==len(specs):
                    print(json.dumps({'phase':name,'jobs_done':i,'jobs_planned':len(specs),
                        'requests':self.attempts,'latest':result['id'],'status':result['status'],
                        'error':result['error']},ensure_ascii=False),flush=True)
                if i%25==0:
                    (self.local/'progress.json').write_bytes(json_bytes(self.summary()))
                if self.fatal:
                    for pending in futures:
                        pending.cancel()
                    raise RuntimeError('collection_stopped_partial_preserved')
        self.sink.put(f'phase-receipts/{name}.json',json_bytes(self.summary()))

    def summary(self):
        with self.lock:
            return {'research_only':True,'orders_authorized':False,'promotion_evidence':False,
                'credential_exported':False,'historical_PIT_certified':False,'returns_produced':False,
                'started_at':self.started,'observed_at':dt.datetime.now(dt.timezone.utc).isoformat(),
                'requests_attempted':self.attempts,'saved_responses':len(self.responses),
                'jobs':dict(collections.Counter(j['status'] for j in self.jobs)),
                'rows_by_api':dict(collections.Counter({a:sum(r['rows'] for r in self.responses if r['api_name']==a)
                    for a in {r['api_name'] for r in self.responses}})),
                'stopped_endpoints':sorted(self.closed_apis),'fatal':self.fatal,
                'effective_minimum_spacing_seconds':self.spacing,'reused_jobs':sum(j['status']=='reused' for j in self.jobs),
                'contract_sha256':sha(json_bytes(self.contract))}

    def finish(self):
        summary=self.summary()
        for name,value in (('responses.json',self.responses),('jobs.json',self.jobs),('summary.json',summary)):
            raw=json_bytes(value); (self.local/name).write_bytes(raw); self.sink.put(name,raw)
        self.token=None
        return summary


def specification(api, params, *, fields='', size=5000, paged=True):
    ident=api+'-'+sha(json_bytes([params,fields,size,paged]))[:20]
    return {'id':ident,'api_name':api,'params':params,'fields':fields,'page_size':size,'paged':paged}


def quarters(start=2013,end=2026,cutoff='20260930'):
    return [f'{y}{md}' for y in range(start,end+1) for md in ('0331','0630','0930','1231') if f'{y}{md}'<=cutoff]


def months(start='20140101',end='20261009'):
    for year in range(int(start[:4]),int(end[:4])+1):
        for month in range(1,13):
            first=f'{year}{month:02d}01';last=f'{year}{month:02d}{calendar.monthrange(year,month)[1]:02d}'
            if last>=start and first<=end:
                yield max(first,start),min(last,end)


def validate_acquisition_contract(contract):
    if (contract.get('maximum_retries') != 5 or contract.get('credential_host') != 'Mac_private_0600_file_and_memory_only'
            or not 1<=contract.get('workers',0)<=8 or contract.get('minimum_spacing_seconds',0)<60/450
            or not 1<=contract.get('maximum_requests',0)<=40000
            or contract.get('cutoff')!='20261009' or contract.get('market_start')!='20140101'
            or set(contract.get('financial_report_types',[]))!={str(i) for i in range(1,13)}):
        raise ValueError('acquisition_scope_or_budget_contract')


def repair_specs(jobs):
    """Only retry failed transport shards, preserving the original inventory."""
    result=[]
    transient=('IncompleteRead:','RemoteDisconnected:','URLError:','TimeoutError:',
               'ConnectionError:','ConnectionResetError:','SSLEOFError:',
               'RuntimeError:transient_retry_budget_exhausted')
    for job in jobs:
        if job['status']!='failed_or_withheld' or job['api_name']=='st':
            continue
        if not (job.get('error') or '').startswith(transient):
            raise ValueError('nontransient_shard_requires_review:'+job['id'])
        spec={k:job[k] for k in ('id','api_name','params','fields','page_size','paged')}
        if spec!=specification(spec['api_name'],spec['params'],fields=spec['fields'],size=spec['page_size'],paged=spec['paged']):
            raise ValueError('repair_identity_mismatch')
        result.append(spec)
    if not result:
        raise ValueError('no_transient_shards_to_repair')
    return result


def collect_repairs(*,contract_path,credential_path,local,root,sink_script,inventory_path,inventory_sha256,seed_path):
    contract=json.loads(Path(contract_path).read_text());validate_acquisition_contract(contract)
    original=Path(inventory_path).read_bytes()
    if sha(original)!=inventory_sha256:
        raise ValueError('repair_inventory_hash_mismatch')
    specs=repair_specs(json.loads(original));seed=Path(seed_path).read_bytes()
    token=saved_token(credential_path);sink=WindowsPublicSink(root,sink_script)
    collector=Collector(token=token,sink=sink,local=local,contract=contract);token=None
    try:
        sink.put('seed.json',seed);(Path(local)/'seed.json').write_bytes(seed)
        receipt={'inventory_sha256':inventory_sha256,'seed_sha256':sha(seed),
            'repair_job_ids':[s['id'] for s in specs],'original_failure_preserved':True}
        sink.put('repair-origin.json',json_bytes(receipt));(Path(local)/'repair-origin.json').write_bytes(json_bytes(receipt))
        collector.phase('repair',specs)
    finally:
        try:result=collector.finish();print(json.dumps(result,ensure_ascii=False),flush=True)
        finally:sink.close()
    return result


def collect_history(*, contract_path, credential_path, local, root, sink_script):
    contract=json.loads(Path(contract_path).read_text());validate_acquisition_contract(contract)
    token=saved_token(credential_path)
    sink=WindowsPublicSink(root,sink_script)
    collector=Collector(token=token,sink=sink,local=local,contract=contract)
    token=None
    try:
        masters, calendars, classifications = [], {}, []
        for exchange in ('SSE','SZSE','BSE'):
            for status in ('L','D','P'):
                spec=specification('stock_basic',{'list_status':status,'exchange':exchange},fields=MASTER_FIELDS,size=6000)
                result,rows=collector.job(spec,keep_rows=True)
                if result['status']!='completed':
                    raise ValueError('master_seed_failed')
                masters+=rows
            result,rows=collector.job(specification('trade_cal',{'exchange':exchange,'start_date':'20130101',
                'end_date':contract['cutoff']},fields='exchange,cal_date,is_open,pretrade_date',size=6000),keep_rows=True)
            if result['status']!='completed':
                raise ValueError('calendar_seed_failed')
            calendars[exchange]=rows
        for source in ('SW2014','SW2021'):
            _,rows=collector.job(specification('index_classify',{'level':'L1','src':source},size=2000),keep_rows=True)
            classifications+=rows
        _,mapping=collector.job(specification('bse_mapping',{},size=1000),keep_rows=True)
        index_metadata=[]
        for market in ('CSI','SSE','SZSE'):
            _,rows=collector.job(specification('index_basic',{'market':market},
                fields='ts_code,name,fullname,market,publisher,index_type,category,base_date,base_point,list_date,weight_rule,desc,exp_date',size=8000),keep_rows=True)
            index_metadata+=rows
        seed={'masters':masters,'calendars':calendars,'industry_classifications':classifications,
            'bse_mapping':mapping,'index_metadata':index_metadata}
        sink.put('seed.json',json_bytes(seed))
        # This small public metadata enables explicit, reviewable coverage plans on Mac.
        (Path(local)/'seed.json').write_bytes(json_bytes(seed))
        codes=sorted({r['ts_code'] for r in masters if r.get('list_date') and r['list_date']<=contract['cutoff']
            and (not r.get('delist_date') or r['delist_date']>='20130101')
            and ((r['ts_code'].endswith('.SH') and r['ts_code'].startswith('6'))
                or (r['ts_code'].endswith('.SZ') and r['ts_code'].startswith(('0','3')))
                or r['ts_code'].endswith('.BJ'))})
        # Financial-only identifiers are captured as unqualified inputs, never
        # promoted into the historical eligible universe by this acquisition.
        extras=set(contract.get('extra_financial_symbols',[]))
        extras.update(r[k] for r in mapping for k in ('o_code','n_code'))
        codes=sorted(set(codes)|extras)
        priority=[specification('stock_st',{'start_date':first,'end_date':last},size=1000)
                  for first,last in months(start=contract['market_start'],end=contract['cutoff'])]
        priority.append(specification('st',{},size=1000))
        for year in range(2013,2027):
            priority.append(specification('new_share',{'start_date':f'{year}0101',
                'end_date':min(f'{year}1231',contract['cutoff'])},size=2000))
        collector.phase('identity-risk',priority)
        # No shortlist, present-day ST filter, or outcome-dependent universe restriction.
        periods=quarters(cutoff=contract['financial_period_cutoff'])
        specs=[]
        for period in reversed(periods):
            for report_type in contract['financial_report_types']:
                for api in ('income_vip','cashflow_vip','balancesheet_vip'):
                    specs.append(specification(api,{'period':period,'report_type':report_type},size=5000))
        collector.phase('financial',specs)
        collector.phase('dividends',[specification('dividend',{'ts_code':code},fields=DIVIDEND_FIELDS,size=2000) for code in codes])
        secondary=[]
        for period in reversed(periods):
            secondary += [specification('forecast_vip',{'period':period},size=3500),
                specification('express_vip',{'period':period},size=5000),
                specification('disclosure_date',{'end_date':period},size=3000)]
        index_codes=set(contract['index_codes'])
        index_codes.update(r['ts_code'] for r in index_metadata if str(r.get('ts_code','')).split('.')[0] in ('H00300','H00905','H00985'))
        for year in range(2013,2027):
            secondary.append(specification('namechange',{'start_date':f'{year}0101','end_date':min(f'{year}1231',contract['cutoff'])},size=5000))
        for code in sorted({r['index_code'] for r in classifications}):
            for flag in ('Y','N'):
                secondary.append(specification('index_member_all',{'l1_code':code,'is_new':flag},size=2000))
        collector.phase('identity-industry-events',secondary)
        days=sorted({r['cal_date'] for rows in calendars.values() for r in rows
            if str(r['is_open'])=='1' and contract['market_start']<=r['cal_date']<=contract['cutoff']},reverse=True)
        specs=[]
        for day in days:
            for api,size in (('daily',6000),('daily_basic',6000),('adj_factor',6000),('stk_limit',5800),('suspend_d',5000)):
                specs.append(specification(api,{'trade_date':day},size=size))
            if day>='20160101':
                specs.append(specification('bak_basic',{'trade_date':day},size=7000))
        collector.phase('market',specs)
        auxiliary=[]
        for year in range(2013,2027):
            params={'start_date':f'{year}0101','end_date':min(f'{year}1231',contract['cutoff'])}
            auxiliary.append(specification('shibor',params,size=2000))
            for code in sorted(index_codes):
                auxiliary.append(specification('index_daily',{'ts_code':code,**params},size=6000))
        collector.phase('index-rates',auxiliary)
    finally:
        try:
            result=collector.finish()
            print(json.dumps(result,ensure_ascii=False),flush=True)
        finally:
            sink.close()
    return result
