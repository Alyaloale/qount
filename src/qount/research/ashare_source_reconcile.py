"""Same-vendor field/application qualification, never economic return accuracy."""
from __future__ import annotations

import collections
import concurrent.futures
import csv
import gzip
import io
import json
import math
import os
import zipfile
from pathlib import Path

from qount.research.ashare_selection import ARTIFACTS, official_calendar, prefix_locator, verify_manifest
from qount.research_data.equity_archive import FIELDS, number as csv_number, sha256, write_json


def number(value):
    """Accept provider JSON numbers and original CSV text without filling nulls."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    return csv_number(value)


def response_rows(path):
    with gzip.open(path,'rt') as stream:
        v=json.load(stream)
    d=v.get('data')
    if v.get('code')!=0 or not d or d.get('has_more') is not False:
        raise ValueError('reconcile_response_not_complete')
    rows=[dict(zip(d['fields'],r,strict=True)) for r in d['items']]
    return rows


def compare_original(stream, symbol, anchor_multiplier, fresh_factors=None):
    reader=csv.DictReader(stream)
    if tuple(reader.fieldnames or ())!=FIELDS:raise ValueError('reconcile_original_schema')
    counts=collections.Counter();samples=[];previous=''
    for row in reader:
        day=row['trade_date']
        if row['ts_code']!=symbol or day<=previous:raise ValueError('reconcile_original_identity_order')
        previous=day;counts['rows']+=1
        f=number(row['adj_factor'])
        if f is None or f<=0:
            counts['missing_factor_kept_unknown']+=1
            continue
        if fresh_factors is not None and '20130101'<=day<='20260930':
            counts['existing_factor_dates_checked']+=1
            fresh=fresh_factors.get(day)
            counts['fresh_factor_dates_absent']+=fresh is None
            changed=fresh is not None and not math.isclose(f,fresh,rel_tol=1e-10,abs_tol=1e-8)
            counts['fresh_factor_value_differences']+=changed
            if (fresh is None or changed) and len(samples)<10:samples.append({'date':day,'original_factor':f,'fresh_factor':fresh})
        if '20140101'<=day<='20260930':
            for field in ('open','high','low','close'):
                raw,adjusted=number(row[field]),number(row['adj_'+field])
                if raw is None or raw<=0 or adjusted is None or adjusted<=0:
                    counts['unavailable_adjusted_fields_kept_unknown']+=1
                    continue
                expected=raw*f*anchor_multiplier
                counts['adjusted_fields_checked']+=1
                counts['adjusted_construction_differences']+=not math.isclose(adjusted,expected,rel_tol=1e-6,abs_tol=1e-8)
    return {'symbol':symbol,'counts':dict(counts),'factor_difference_samples':samples,
            'fixed_anchor_multiplier':anchor_multiplier,'cash_total_return_certified':False}


def _batch(archive, entries, fresh):
    result=[]
    with zipfile.ZipFile(archive) as z:
        for row in entries:
            with z.open(row['member']) as f:
                result.append(compare_original(io.TextIOWrapper(f,encoding='utf-8-sig',newline=''),row['symbol'],
                    row['adjustment_anchor_min'],fresh.get(row['symbol'])))
    return result


def reconcile(*, source_root, qualification_contract, scope_contract, calendar_path, out):
    if not os.path.ismount('/mnt/e') or not out.resolve().is_relative_to(ARTIFACTS) or out.exists():
        raise ValueError('reconcile_requires_new_E_artifact')
    manifest=verify_manifest(source_root)
    acquisition=json.loads((source_root/'acquisition.json').read_text())
    c=json.loads((source_root/'contract.json').read_text())
    if acquisition['status']!='completed' or acquisition['completed_requests']!=807:
        raise ValueError('reconcile_incomplete_acquisition')
    q=json.loads(qualification_contract.read_text());archive=Path(q['source']['archive'])
    scope=json.loads(scope_contract.read_text())
    if (scope.get('phase')!='vendor_price_proxy_qualification' or scope.get('research_only') is not True
        or scope.get('orders_authorized') is not False
        or scope.get('adjustment_semantics_scope')!='vendor_defined_adjusted_price_proxy'
        or sha256(qualification_contract)!=scope['original_qualification_sha256']
        or sha256(source_root/'contract.json')!=scope['source_acquisition_contract_sha256']
        or sha256(source_root/'manifest.json')!=scope['source_manifest_sha256']
        or sha256(calendar_path)!=scope['calendar_review_sha256']):
        raise ValueError('reconcile_scoped_qualification_binding')
    code_root=scope_contract.parent.parent
    for name,digest in scope['evidence_bindings'].items():
        if sha256(code_root/name)!=digest:raise ValueError('reconcile_evidence_binding:'+name)
    evidence_root=Path(scope['prior_bridge_evidence']['root'])
    verify_manifest(evidence_root,scope['prior_bridge_evidence']['manifest_sha256'])
    if sha256(archive)!=q['source']['sha256']:raise ValueError('reconcile_archive_hash')
    audit=Path(q['source']['audit_root']);verify_manifest(audit,q['source']['audit_manifest_sha256'])
    originals=json.loads((audit/'members.json').read_text())
    entries=[r for r in originals if prefix_locator(r['symbol'],q['qualification']['prefix_locator_not_historical_identity'])]
    if len(entries)!=3211:raise ValueError('reconcile_original_inventory')
    sessions,_=official_calendar(json.loads(calendar_path.read_text()),'2014-01-01','2026-09-30')
    second,_=official_calendar(json.loads(calendar_path.read_text()),'2014-01-01','2026-09-30','SZSE')
    if sessions!=second:raise ValueError('reconcile_exchange_calendars')
    fresh={};retired={};calendar_counts={};raw_quote=None;dividends=[]
    for request in acquisition['responses']:
        rows=response_rows(source_root/request['file'])
        if len(rows)!=request['rows']:raise ValueError('reconcile_row_count')
        if request['role']=='same_source_factor_reproducibility':
            series={r['trade_date']:number(r['adj_factor']) for r in rows}
            if len(series)!=len(rows) or any(v is None or v<=0 for v in series.values()):
                raise ValueError('reconcile_factor_identity_value')
            fresh[request['params']['ts_code']]=series
        elif request['role']=='missing_retired_same_provider_source_supplement':
            retired.setdefault(request['params']['ts_code'],{})[request['api_name']]=rows
        elif request['role']=='calendar_crosscheck':
            days=tuple(sorted(r['cal_date'] for r in rows if r['is_open']==1 or r['is_open']=='1'))
            if days!=sessions:raise ValueError('reconcile_vendor_calendar_difference')
            calendar_counts[request['params']['exchange']]=len(days)
        elif request['role']=='fixed_anomaly_raw_quote_reproducibility':raw_quote=rows
        elif request['role']=='fixed_anomaly_corporate_action_diagnostic_not_cash_ledger':dividends=rows
    if len(fresh)!=408 or len(retired)!=196:raise ValueError('reconcile_target_count')
    prior=json.loads((evidence_root/'security-evidence-profiles.json').read_text())
    flagged={r['symbol'] for r in prior if r['counts'].get('factor_reference_mismatches',0)>0
             and prefix_locator(r['symbol'],q['qualification']['prefix_locator_not_historical_identity'])}
    if flagged!=set(fresh):raise ValueError('reconcile_flagged_identity_drift')
    prior_cases=sum(r['counts'].get('factor_reference_mismatches',0) for r in prior if r['symbol'] in flagged)
    if prior_cases!=838:raise ValueError('reconcile_prior_bridge_count_drift')
    profiles=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(_batch,archive,entries[i:i+32],fresh) for i in range(0,len(entries),32)]
        for f in concurrent.futures.as_completed(futures):profiles.extend(f.result())
    totals=collections.Counter()
    for p in profiles:totals.update(p['counts'])
    retired_profiles=[]
    for symbol,parts in sorted(retired.items()):
        raw,factors=parts['daily'],parts['adj_factor'];factor={r['trade_date']:number(r['adj_factor']) for r in factors}
        if len(factor)!=len(factors) or any(v is None or v<=0 for v in factor.values()):raise ValueError('reconcile_retired_factor')
        dates=[r['trade_date'] for r in raw]
        if len(set(dates))!=len(dates):raise ValueError('reconcile_retired_raw_duplicates')
        retired_profiles.append({'symbol':symbol,'raw_rows':len(raw),'factor_rows':len(factors),
            'raw_dates_missing_same_day_factor':sum(d not in factor for d in dates),
            'first_raw_date':min(dates) if dates else None,'last_raw_date':max(dates) if dates else None,
            'empty_raw_kept_unknown':not raw,'terminal_recovery_or_fill_certified':False})
    quote_counts=collections.Counter()
    if raw_quote is not None:
        bydate={r['trade_date']:r for r in raw_quote}
        with zipfile.ZipFile(archive) as z:
            with z.open('stocks/000998_SZ.csv') as f:
                for row in csv.DictReader(io.TextIOWrapper(f,encoding='utf-8-sig',newline='')):
                    if row['trade_date'] in bydate:
                        for field in ('open','high','low','close','pre_close'):
                            quote_counts['fields_checked']+=1
                            quote_counts['differences']+=not math.isclose(number(row[field]),number(bydate[row['trade_date']][field]),rel_tol=1e-8,abs_tol=1e-8)
    passed=(totals['fresh_factor_dates_absent']==0 and totals['fresh_factor_value_differences']==0
        and totals['adjusted_construction_differences']==0 and quote_counts['differences']==0)
    result={'research_only':True,'orders_authorized':False,'promotion_evidence':False,'returns_produced':False,
        'status':'vendor_price_proxy_field_application_qualified' if passed else 'source_reconciliation_pending',
        'source_vendor_verified':True,'independent_calendar_verified':True,
        'adjustment_semantics_verified_for_information_proxy':passed,
        'adjustment_semantics_scope':'vendor_defined_adjusted_price_proxy',
        'corporate_action_economic_accuracy_verified':False,'cash_total_return_verified':False,
        'historical_asof_factor_vintages_verified':False,'portfolio_authorized_by_data':False,
        'original_mainboard_locator_files':len(profiles),'same_source_factor_securities':len(fresh),
        'same_source_full_factor_requery_scope':'408 prior flagged originals; 196 missing retired targets',
        'other_original_files_not_api_requeried':len(profiles)-len(fresh),
        'other_original_source_posture':'owner_attested; adjusted construction checked; not historical API vintage certified',
        'prior_bridge_cases_in_fully_reconciled_factor_series':prior_cases,
        'counts':dict(totals),'fixed_raw_quote_reproducibility':dict(quote_counts),
        'calendar_counts':calendar_counts,'retired_target_count':len(retired_profiles),
        'retired_raw_rows':sum(r['raw_rows'] for r in retired_profiles),
        'retired_factor_rows':sum(r['factor_rows'] for r in retired_profiles),
        'retired_raw_dates_without_same_day_factor':sum(r['raw_dates_missing_same_day_factor'] for r in retired_profiles),
        'retired_empty_raw_sets':sum(r['empty_raw_kept_unknown'] for r in retired_profiles),
        'fixed_anomaly_dividend_records':len(dividends),
        'bridge_residual_posture':'vendor_reproduced_nonbridge; not_a_vendor_guaranteed_identity; economic_explanation_unverified',
        'source_manifest_sha256':sha256(source_root/'manifest.json'),'source_archive_sha256':q['source']['sha256'],
        'scoped_qualification_contract_sha256':sha256(scope_contract),
        'adjustment_semantics_review_sha256':scope['adjustment_semantics_review_sha256'],
        'calendar_review_sha256':sha256(calendar_path),'module_sha256':sha256(Path(__file__)),
        'precision':'fixed_anchor_raw_times_factor; rel_tol_1e-6_abs_tol_1e-8; no_rounding_bfill_or_provider_splice'}
    out.mkdir(parents=True,exist_ok=False)
    for name,value in [('summary.json',result),('original-profiles.json',sorted(profiles,key=lambda x:x['symbol'])),
                        ('retired-profiles.json',retired_profiles),('contract.json',c),
                        ('scoped-qualification-contract.json',scope)]:write_json(out/name,value)
    write_json(out/'manifest.json',{p.name:sha256(p) for p in sorted(out.iterdir())})
    return result
