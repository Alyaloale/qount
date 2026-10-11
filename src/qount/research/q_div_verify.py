"""Independent raw-source checks for the bounded Q-DIV snapshot (no strategy imports)."""
from __future__ import annotations

import collections
import datetime as dt
import gzip
import hashlib
import importlib.util
import json
import math
import statistics
from pathlib import Path


def verify(*, contract_path, technical_root, snapshot_root, financial_root, helper_path, out):
    def read(path):return json.loads(Path(path).read_text())
    def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    counts=collections.Counter();errors=collections.defaultdict(float)
    def equal(a,b,kind):
        assert a==b,(kind,a,b);counts[kind]+=1
    def close(a,b,kind):
        difference=abs(a-b);errors[kind]=max(errors[kind],difference)
        assert math.isfinite(a) and math.isfinite(b) and difference<=2e-7+abs(b)*2e-9,(kind,a,b)
        counts[kind]+=1
    def manifest(root):
        root=Path(root)
        for name,digest in read(root/'manifest.json').items():
            path=(root/name).resolve();assert path.is_relative_to(root.resolve())
            equal(sha(path),digest,'artifact_digest')
    def public(root):
        root=Path(root);receipt=read(root/'acquisition.json');assert receipt['status']=='completed'
        equal(receipt['contract_sha256'],sha(root/'contract.json'),'acquisition_contract')
        rows=[]
        for response in receipt['responses']:
            path=(root/response['file']).resolve();assert path.is_relative_to(root.resolve())
            raw=gzip.decompress(path.read_bytes())
            equal(hashlib.sha256(raw).hexdigest(),response['raw_response_sha256'],'response_raw_digest')
            value=json.loads(raw);assert value['code']==0 and value['data']['has_more'] is False
            data=value['data'];items=[dict(zip(data['fields'],r,strict=True)) for r in data['items']]
            equal(len(items),response['rows'],'response_rows')
            rows.append((response,items))
        return rows
    c=read(contract_path);technical_root=Path(technical_root);snapshot_root=Path(snapshot_root)
    out=Path(out)
    assert not out.exists() and out.resolve().is_relative_to(Path('/mnt/e/qount_data/qount/artifacts/equity_selection'))
    manifest(technical_root);manifest(snapshot_root)
    equal(sha(technical_root/'contract.json'),sha(contract_path),'technical_contract')
    equal(sha(snapshot_root/'contract.json'),sha(contract_path),'snapshot_contract')
    shortlist=read(technical_root/'shortlist.json');selected=read(snapshot_root/'selected.json')
    reviewed=read(snapshot_root/'reviewed.json');summary=read(snapshot_root/'summary.json')
    equal(collections.Counter(r['status'] for r in reviewed),collections.Counter(summary['counts']),'review_status_counts')
    equal([r['symbol'] for r in shortlist], [r['symbol'] for r in reviewed],'review_inventory')
    financial=collections.defaultdict(dict);index={};rates={};basic={};st=set()
    for response,rows in public(financial_root):
        financial[response['params']['ts_code']][response['api_name']]=rows
    for source in c['snapshot_public_sources']:
        for response,rows in public(source['root']):
            api=response['api_name']
            for r in rows:
                if api=='index_daily':index[r['trade_date']]=r['close']/r['pre_close']-1
                elif api=='shibor':rates[r['date']]=r['on']/100/252
                elif api=='daily_basic':basic[(r['ts_code'],r['trade_date'])]=r
                elif api=='stock_st':st.add(r['ts_code'])
    equal(sha(helper_path),'4f4f94e098a617f149c07e1118fa430d2f7748f0a6e3016669e28555b2ef1f7a','raw_verifier_helper')
    spec=importlib.util.spec_from_file_location('qdiv_raw_source_verifier',helper_path)
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    sessions,metadata,panel=helper.source_panel(c,{r['symbol'] for r in shortlist})
    j=len(sessions)-1;asof=c['price_cutoff'];now=dt.datetime.strptime(asof,'%Y%m%d').date()
    mx=[index[d]-rates[sessions[k-1]] for k,d in enumerate(sessions) if k>=len(sessions)-120]
    xmean=statistics.fmean(mx);xx=sum((v-xmean)**2 for v in mx)
    for r in shortlist:
        code=r['symbol'];marks,quotes,history=panel[code]
        assert code not in st and history[j]>=252 and all(math.isfinite(x) for x in marks[j-219:j+1])
        ma60=statistics.fmean(marks[j-59:j+1]);ma120=statistics.fmean(marks[j-119:j+1])
        ma200=statistics.fmean(marks[j-199:j+1]);lag=statistics.fmean(marks[j-219:j-19])
        close(r['Bias60'],marks[j]/ma60-1,'Bias60');close(r['Bias120'],marks[j]/ma120-1,'Bias120')
        close(r['MA200'],ma200,'MA200');close(r['MA200_lag20'],lag,'MA200_lag20')
        close(r['return60'],marks[j]/marks[j-60]-1,'return60')
        close(r['ADV20_cny'],statistics.fmean(quotes[k][4] for k in range(j-19,j+1)),'ADV20')
        close(r['volume5_div60'],statistics.fmean(quotes[k][5] for k in range(j-4,j+1))/statistics.fmean(quotes[k][5] for k in range(j-59,j+1)),'volume_ratio')
        close(r['turnover20_percent'],statistics.fmean(basic[(code,d)]['turnover_rate'] for d in sessions[-20:]),'turnover20')
        my=[marks[k]/marks[k-1]-1-rates[sessions[k-1]] for k in range(j-119,j+1)]
        ymean=statistics.fmean(my);beta=sum((x-xmean)*(y-ymean) for x,y in zip(mx,my))/xx
        residual=[y-ymean-beta*(x-xmean) for x,y in zip(mx,my)]
        close(r['IVOL'],math.sqrt(statistics.fmean(e*e for e in residual))*math.sqrt(252),'IVOL')
        close(r['beta'],beta,'beta')
        assert marks[j]>ma200>=lag and -.03<=r['Bias60']<=.12 and r['Bias120']<.20 and r['return60']<=.30 and r['volume5_div60']<=.85
    def reports(rows,fields):
        grouped=collections.defaultdict(list)
        for row in rows:
            announced=max(row.get('ann_date') or '',row.get('f_ann_date') or '')
            if str(row['report_type'])=='1' and announced<asof and row['end_date']<=asof:
                grouped[row['end_date']].append((announced,row))
        result={}
        for period,values in grouped.items():
            latest=max(a for a,_ in values);current=[r for a,r in values if a==latest]
            assert len({tuple(r.get(f) for f in fields)+(str(r.get('comp_type')),) for r in current})==1
            result[period]=current[0]
        return result
    def ttm(rows,period,field):
        value=rows[period][field]
        if not period.endswith('1231'):
            previous=str(int(period[:4])-1)
            value+=rows[previous+'1231'][field]-rows[previous+period[4:]][field]
        return value
    for row in selected:
        code=row['symbol'];data=financial[code]
        inc=reports(data['income'],['n_income_attr_p']);cf=reports(data['cashflow'],['n_cashflow_act'])
        bal=reports(data['balancesheet'],['total_hldr_eqy_exc_min_int','total_liab','total_assets'])
        period=max(inc);previous=str(int(period[:4])-1)+period[4:]
        equal(period,row['quality']['period'],'latest_period')
        assert all(str(r['comp_type'])=='1' for r in (inc[period],cf[period],bal[period]))
        profit=ttm(inc,period,'n_income_attr_p');cfo=ttm(cf,period,'n_cashflow_act')
        roe=profit/statistics.fmean([bal[p]['total_hldr_eqy_exc_min_int'] for p in (period,previous)])
        leverage=bal[period]['total_liab']/bal[period]['total_assets']
        assert profit>0 and roe>=.08 and cfo/profit>=.8 and leverage<.7
        close(profit,row['quality']['parent_profit_TTM_cny'],'profit_TTM')
        close(cfo,row['quality']['CFO_TTM_cny'],'CFO_TTM');close(roe,row['quality']['ROE_TTM'],'ROE_TTM')
        close(cfo/profit,row['quality']['CFO_to_parent_profit_TTM'],'CFO_profit')
        events={}
        for r in data['dividend']:
            if (r['div_proc']=='实施' and r.get('imp_ann_date') and r['imp_ann_date']<asof
                    and r.get('ex_date') and r['ex_date']<=asof and r.get('pay_date') and r['pay_date']<=asof
                    and r.get('cash_div_tax') and r['cash_div_tax']>0):
                events[(r['end_date'],r['ex_date'],r['pay_date'])]=r
        assert {now.year-3,now.year-2,now.year-1}<={int(k[0][:4]) for k in events}
        total=sum(r['cash_div_tax']*r['base_share'] for (_,_,paid),r in events.items()
                  if (now-dt.timedelta(days=365)).strftime('%Y%m%d')<paid<=asof)
        dy=total/basic[(code,asof)]['total_mv'];assert dy>=.025
        close(dy,row['yield_TTM'],'dividend_yield')
    vintage_audit=collections.Counter()
    for data in financial.values():
        for api in ('income','cashflow','balancesheet'):
            groups_by_date=collections.defaultdict(list)
            for r in data[api]:
                if str(r.get('report_type'))=='1':
                    groups_by_date[(r['end_date'],max(r.get('ann_date') or '',r.get('f_ann_date') or ''))].append(r)
            for rows in groups_by_date.values():
                vintage_audit['period_announcement_groups']+=1
                if len(rows)>1:
                    vintage_audit['multiple_rows_same_period_announcement']+=1
                    fields=sorted(set(rows[0])-{'update_flag'})
                    if len({tuple(r.get(k) for k in fields) for r in rows})>1:
                        vintage_audit['conflicting_values_same_period_announcement']+=1
    ordered=sorted([r for r in reviewed if r['status']=='pass'],key=lambda r:(r['IVOL'],r['symbol']))
    expected=[];groups=collections.Counter()
    for r in ordered[:20]:
        if groups[r['industry']]<3:
            expected.append(r['symbol']);groups[r['industry']]+=1
    equal([r['symbol'] for r in selected],expected,'selected_ranks_and_slots')
    assert len(selected)<=20 and all(r['target_weight']<=.08+1e-12 for r in selected)
    for group in groups:
        assert sum(r['target_weight'] for r in selected if r['industry']==group)<=.20+1e-12
    close(sum(r['target_weight'] for r in selected)+summary['target_cash_weight'],1.,'cash_and_weights')
    result={'status':'passed_bounded_snapshot_checks','research_only':True,'orders_authorized':False,
            'promotion_evidence':False,'shortlist_price_IVOL_checked':len(shortlist),
            'selected_financial_dividend_checked':len(selected),'checks':dict(counts),'max_errors':dict(errors),
            'financial_revision_audit':dict(vintage_audit),
            'not_independently_reselected':['full3407_maturity_liquidity_turnover_funnel','all124_technical_passers',
                'unselected_financial_fail_or_unknown','proportional_weight_optimum'],
            'historical_PIT_certified':False,'returns_produced':False,
            'contract_sha256':sha(contract_path),'technical_manifest_sha256':sha(technical_root/'manifest.json'),
            'snapshot_manifest_sha256':sha(snapshot_root/'manifest.json')}
    out.mkdir(parents=True);(out/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    (out/'manifest.json').write_text(json.dumps({'verification.json':sha(out/'verification.json')},indent=2)+'\n')
    return result
