"""Independent WSL/E inventory, raw-hash, pagination and coverage audit for P1."""
from __future__ import annotations
from collections import Counter,defaultdict
import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def read_public(root,receipt):
    root=Path(root).resolve();path=(root/receipt['file']).resolve()
    if not path.is_relative_to(root) or not root.is_relative_to('/mnt/e/qount_data/qount/datasets/equity_selection'):
        raise ValueError('public_input_path_escape')
    packed=path.read_bytes()
    if digest(packed)!=receipt['file_sha256']:
        raise ValueError('compressed_source_hash')
    raw=gzip.decompress(packed)
    if digest(raw)!=receipt.get('raw_sha256'):
        raise ValueError('raw_source_hash')
    value=json.loads(raw)
    if value.get('code')!=receipt['code']:
        raise ValueError('provider_code_receipt')
    if value['code']!=0:
        return None
    data=value.get('data') or {};fields=data.get('fields');rows=data.get('items')
    if (fields!=receipt['fields'] or not isinstance(rows,list) or len(rows)!=receipt['rows']
            or data.get('has_more')!=receipt['has_more'] or type(data.get('has_more')) is not bool
            or any(not isinstance(r,list) or len(r)!=len(fields) for r in rows)):
        raise ValueError('source_dimensions_or_paging')
    return data


def inspect_job(root,job,receipts):
    valid=sorted((r for r in receipts if r['code']==0),key=lambda r:r['params'].get('offset',0))
    if len(valid)!=job['pages'] or sum(r['rows'] for r in valid)!=job['rows']:
        raise ValueError('job_page_inventory')
    size=job['page_size'];seen=set()
    for page,receipt in enumerate(valid):
        if receipt['api_name']!=job['api_name']:
            raise ValueError('job_endpoint_identity')
        expected={**job['params']}
        if job.get('paged',True):
            expected.update(limit=size,offset=page*size)
        if receipt['params']!=expected:
            raise ValueError('page_gap_or_request_mismatch')
        data=read_public(root,receipt)
        if job.get('fields') and data['fields']!=job['fields'].split(','):
            raise ValueError('requested_fields')
        fingerprint=digest(json.dumps([data['fields'],data['items']],sort_keys=True).encode())
        if data['items'] and fingerprint in seen:
            raise ValueError('repeated_page')
        seen.add(fingerprint)
        more=data['has_more'] or len(data['items'])>=size
        if page==len(valid)-1 and more:
            raise ValueError('terminal_page_not_observed')
        if page<len(valid)-1 and not more:
            raise ValueError('unnecessary_or_invalid_page')
        names=data['fields']
        range_field={'stock_st':'trade_date','index_daily':'trade_date','shibor':'date','new_share':'ipo_date'}.get(job['api_name'])
        if range_field and job['params'].get('start_date') and range_field in names:
            column=names.index(range_field)
            if any(not r[column] or not job['params']['start_date']<=r[column]<=job['params']['end_date'] for r in data['items']):
                raise ValueError('source_date_range')
        for row in data['items']:
            if (job['api_name']=='disclosure_date' and job['params'].get('end_date')
                    and 'end_date' in names and row[names.index('end_date')]!=job['params']['end_date']):
                raise ValueError('disclosure_period_identity')
            for key,param in (('ts_code','ts_code'),('trade_date','trade_date'),('end_date','period'),
                    ('report_type','report_type'),('l1_code','l1_code'),('is_new','is_new'),
                    ('list_status','list_status'),('exchange','exchange')):
                if job['params'].get(param) and key in names and row[names.index(key)]!=job['params'][param]:
                    raise ValueError('row_identity_or_period')
        yield data


def select_jobs(planned,selected_ids):
    """Bind a partition to exact planned IDs; never silently discard mistakes."""
    if selected_ids is None:
        return planned
    if (not isinstance(selected_ids,list) or not selected_ids
            or any(not isinstance(i,str) for i in selected_ids)
            or len(set(selected_ids))!=len(selected_ids)):
        raise ValueError('invalid_audit_job_partition')
    if set(selected_ids)-set(planned):
        raise ValueError('audit_partition_contains_unplanned_jobs')
    return {i:planned[i] for i in selected_ids}


def audit(*,root,out,selected_phases=None,index_name='responses.json',jobs_name='jobs.json',job_ids_name=None):
    if sys.platform!='linux' or not os.path.ismount('/mnt/e'):
        raise ValueError('audit_requires_WSL_E')
    root=Path(root).resolve();out=Path(out).resolve()
    if out.exists() or not out.is_relative_to('/mnt/e/qount_data/qount/artifacts/equity_selection'):
        raise ValueError('fresh_E_output_required')
    out.mkdir(parents=True)
    jobs=json.loads((root/jobs_name).read_text());responses=json.loads((root/index_name).read_text())
    contract=json.loads((root/'contract.json').read_text());seed=json.loads((root/'seed.json').read_text())
    phases={p.stem:json.loads(p.read_text()) for p in sorted((root/'plans').glob('*.json'))}
    if selected_phases:
        phases={k:v for k,v in phases.items() if k in selected_phases}
    planned={s['id']:s for specs in phases.values() for s in specs}
    for job in jobs:
        if job['api_name'] in ('stock_basic','trade_cal','index_classify','bse_mapping','index_basic'):
            planned[job['id']]={k:job[k] for k in ('id','api_name','params','fields','page_size','paged')}
    full_planned_count=len(planned)
    if job_ids_name:
        partition=(root/job_ids_name).resolve()
        if not partition.is_relative_to(root):
            raise ValueError('audit_partition_path_escape')
        planned=select_jobs(planned,json.loads(partition.read_text()))
    jobmap={j['id']:j for j in jobs}
    if len(jobmap)!=len(jobs):
        raise ValueError('duplicate_job_identity')
    byjob=defaultdict(list)
    for r in responses:
        byjob[r['job_id']].append(r)
    sources={};source_manifest={}
    for source in contract.get('reuse_sources',[]):
        path=Path(source['root'].replace('E:/','/mnt/e/')).resolve()
        old_jobs=json.loads((path/'jobs.json').read_text());old_responses=json.loads((path/'responses.json').read_text())
        old_byjob=defaultdict(list)
        for r in old_responses:
            old_byjob[r['job_id']].append(r)
        sources[source['root']]=(path,{j['id']:j for j in old_jobs},old_byjob)
        source_manifest[str(path/'jobs.json')]=digest((path/'jobs.json').read_bytes())
        source_manifest[str(path/'responses.json')]=digest((path/'responses.json').read_bytes())
    errors=[];empty=[];rows=Counter();symbols=defaultdict(set);period_counts=Counter();dates=defaultdict(set)
    financial_signatures=defaultdict(set);financial_group_rows=Counter();ann_bad=Counter();dividend_flags=Counter()
    market_missing=Counter();market_missing_sample=[];completed=0;verified_files={};nonempty=Counter()
    masters={r['ts_code']:r for r in seed['masters']}
    financial_metrics={'income_vip':['n_income_attr_p'],'cashflow_vip':['n_cashflow_act'],
        'balancesheet_vip':['total_hldr_eqy_exc_min_int','total_liab','total_assets']}
    for i,(ident,spec) in enumerate(sorted(planned.items()),1):
        job=jobmap.get(ident)
        if not job or job['status'] not in ('completed','reused'):
            errors.append({'id':ident,'reason':'missing_or_failed_job','record':job});continue
        if any(job.get(k)!=spec.get(k) for k in ('api_name','params','fields','page_size','paged')):
            errors.append({'id':ident,'reason':'plan_job_mismatch'});continue
        source_root,source_job,records=root,job,byjob[ident]
        if job['status']=='reused':
            source_root,prior,old_byjob=sources[job['source_root']]
            source_job=prior[ident];records=old_byjob[ident]
        api=spec['api_name'];job_symbols=set();market_keys=set()
        try:
            if source_job['status']!='completed' or any(source_job.get(k)!=job.get(k) for k in
                    ('api_name','params','fields','page_size','paged','rows','pages')):
                raise ValueError('inherited_shard_mismatch')
            for data in inspect_job(source_root,source_job,records):
                names=data['fields'];columns={n:k for k,n in enumerate(names)}
                for row in data['items']:
                    symbol=row[columns['ts_code']] if 'ts_code' in columns else None
                    if symbol:
                        symbols[api].add(symbol);job_symbols.add(symbol)
                    rows[api]+=1
                    day=row[columns['trade_date']] if 'trade_date' in columns else None
                    if day:
                        dates[api].add(day)
                    if api in ('daily','daily_basic','adj_factor','stk_limit'):
                        key=(symbol,day)
                        if key in market_keys:
                            raise ValueError('cross_page_duplicate_market_key')
                        market_keys.add(key)
                    if api in financial_metrics:
                        period=row[columns['end_date']];report_type=str(row[columns['report_type']])
                        period_counts[(api,period,report_type)]+=1
                        if report_type=='1':
                            ann=row[columns['ann_date']];fann=row[columns['f_ann_date']]
                            public=max(ann or '',fann or '')
                            try:
                                dt.datetime.strptime(public,'%Y%m%d')
                            except (TypeError,ValueError):
                                ann_bad[api]+=1;continue
                            group=(api,symbol,period,public)
                            financial_group_rows[group]+=1
                            signature=tuple(row[columns[n]] for n in financial_metrics[api])
                            financial_signatures[group].add(signature)
                    elif api=='dividend':
                        stage=row[columns['div_proc']];dividend_flags['stage:'+str(stage)]+=1
                        if stage=='实施':
                            has_cash = (row[columns['cash_div_tax']] or 0) > 0
                            for field in ('record_date','ex_date','pay_date'):
                                if not row[columns[field]]:
                                    dividend_flags['implemented_missing_'+field]+=1
                            if has_cash and not row[columns['pay_date']]:
                                dividend_flags['implemented_cash_missing_pay_date']+=1
                            if not has_cash and (row[columns['stk_div']] or 0)>0:
                                dividend_flags['implemented_pure_share_distribution']+=1
                            if (row[columns['stk_div']] or 0)>0:
                                dividend_flags['implemented_share_distribution']+=1
            for r in records:
                if r['code']==0:
                    verified_files[str(source_root/r['file'])]=r['file_sha256']
            if not job['rows']:
                empty.append({'id':ident,'api':api,'params':spec['params']})
            else:
                nonempty[api]+=1
            if api in ('daily','daily_basic','adj_factor','stk_limit','bak_basic'):
                day=spec['params']['trade_date']
                expected={s for s,r in masters.items() if r.get('list_date') and r['list_date']<=day
                    and (not r.get('delist_date') or r['delist_date']>=day)}
                missing=expected-job_symbols
                market_missing[api]+=len(missing)
                if missing and len(market_missing_sample)<50:
                    market_missing_sample.append({'api':api,'date':day,'missing_count':len(missing),'sample':sorted(missing)[:10]})
            completed+=1
        except Exception as exc:
            errors.append({'id':ident,'reason':type(exc).__name__+':'+str(exc)})
        if i%1000==0:
            print(json.dumps({'audited_jobs':i,'planned':len(planned),'errors':len(errors)}),flush=True)
    conflicts=[{'api':k[0],'symbol':k[1],'period':k[2],'vendor_public_date':k[3],
        'rows':financial_group_rows[k],'economic_signatures':len(v)} for k,v in financial_signatures.items() if len(v)>1]
    unavailable=sum(e['reason']=='missing_or_failed_job' for e in errors)
    integrity_errors=len(errors)-unavailable
    for receipt in responses:
        if receipt['code']!=0:
            read_public(root,receipt)
            verified_files[str(root/receipt['file'])]=receipt['file_sha256']
    summary={'research_only':True,'orders_authorized':False,'promotion_evidence':False,
        'historical_PIT_certified':False,'historical_backtest_run':False,
        'status':'inventory_failed' if integrity_errors else ('available_inputs_verified_with_gaps' if unavailable else 'inventory_verified'),
        'phases':sorted(phases),'planned_jobs':len(planned),'verified_jobs':completed,'errors':len(errors),
        'full_phase_plan_jobs':full_planned_count,'job_partition':job_ids_name,'audited_job_ids':sorted(planned),
        'unavailable_jobs':unavailable,'integrity_errors':integrity_errors,
        'verified_files':len(verified_files),'rows_by_api':dict(rows),'symbols_by_api':{k:len(v) for k,v in symbols.items()},
        'nonempty_jobs_by_api':dict(nonempty),'empty_jobs':len(empty),
        'date_ranges':{k:{'first':min(v),'last':max(v),'dates':len(v)} for k,v in dates.items() if v},
        'financial_type1_dated_groups':len(financial_signatures),'financial_type1_multiple_record_groups':sum(v>1 for v in financial_group_rows.values()),
        'financial_type1_same_date_conflicts':len(conflicts),'financial_type1_invalid_public_dates':dict(ann_bad),
        'dividend_flags':dict(dividend_flags),'market_missing_vendor_master_symbol_days':dict(market_missing),
        'missing_price_is_not_assumed_tradable_or_zero':True,
        'remaining_qualification':['original_announcement_vintage_and_missing_revisions','independent_historical_universe_and_code_changes',
            'historical_industry_taxonomy_and_in_out_date_publication','rights_issue_and_delisting_settlement_and_cancelled_actions',
            'original_fill_and_historical_tax_fee_semantics','official_total_return_benchmark_identity'],
        'input_root':str(root),'contract_sha256':digest((root/'contract.json').read_bytes()),
        'implementation_sha256':digest(Path(__file__).read_bytes())}
    write(out/'summary.json',summary);write(out/'errors.json',errors);write(out/'empty-jobs.json',empty)
    write(out/'financial-conflicts.json',conflicts)
    write(out/'financial-period-coverage.json',[{'api':k[0],'period':k[1],'report_type':k[2],'rows':v} for k,v in sorted(period_counts.items())])
    write(out/'market-missing-sample.json',market_missing_sample)
    write(out/'symbols-by-api.json',{k:sorted(v) for k,v in symbols.items()})
    write(out/'financial-vs-master.json',{k:{'absent_from_master':sorted(v-set(masters)),
        'master_without_financial_rows':sorted(set(masters)-v)} for k,v in symbols.items() if k in financial_metrics})
    source_manifest.update(verified_files)
    for name in ('contract.json','seed.json',jobs_name,index_name):
        source_manifest[str(root/name)]=digest((root/name).read_bytes())
    for name in phases:
        source_manifest[str(root/'plans'/f'{name}.json')]=digest((root/'plans'/f'{name}.json').read_bytes())
    if job_ids_name:
        source_manifest[str(partition)]=digest(partition.read_bytes())
    write(out/'input-manifest.json',source_manifest)
    write(out/'manifest.json',{p.name:digest(p.read_bytes()) for p in sorted(out.iterdir()) if p.is_file()})
    return summary
