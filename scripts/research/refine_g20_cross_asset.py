"""Mechanism repair after diagnosing the retained G20 cross-asset baseline.

No hyperparameter sweep. Old results remain in their original directory.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import json
from pathlib import Path

import numpy as np

from study_g20_cross_asset_mechanisms import (MECHANISMS, buy_hold, etf_sources,
    native_inputs, native_panel, paired_interval, proxy_panel)
from qount.research.g20_cross_asset import Mechanism, YEAR, replay
from qount.research_data.archives import timestamp
from qount.research_data.bars import Bar
from qount.research_data.binance_history import public_get


RULES = {
    "baseline": Mechanism(retain=True),
    "allocation_rank": Mechanism(retain=True, allocation_score=True),
    "cost_replace": Mechanism(retain=True, replacement="cost"),
    "allocation_cost": Mechanism(retain=True, allocation_score=True, replacement="cost"),
    "price_invalidation": Mechanism(retain=True, hold_condition="price"),
    "own_regime": Mechanism(retain=True, regime="own"),
    "allocation_cost_own": Mechanism(retain=True, allocation_score=True, replacement="cost", regime="own"),
    "price_own": Mechanism(retain=True, hold_condition="price", regime="own"),
    "combined": Mechanism(retain=True, allocation_score=True, replacement="cost", hold_condition="price", regime="own"),
    # Follow-up contrasts after the initial mechanism results; not OOS.
    "price_entry": Mechanism(retain=True,hold_condition="price",entry_condition="price",regime="own"),
    "core_only": Mechanism(retain=True,hold_condition="price",entry_condition="price",regime="own",core_symbol="SPYUSDT",core_defensive=False),
    "core_defensive": Mechanism(retain=True,hold_condition="price",entry_condition="price",regime="own",core_symbol="SPYUSDT"),
    "dual_failure_own": Mechanism(retain=True,hold_condition="dual_failure",regime="own"),
    "core_dual_failure": Mechanism(retain=True,hold_condition="dual_failure",entry_condition="price",regime="own",core_symbol="SPYUSDT",core_defensive=False),
}
WINDOWS = {"2017_2025": ("2017-01-03", "2025-12-31"),
           "2017_2020": ("2017-01-03", "2020-12-31"),
           "2021_2023": ("2021-01-04", "2023-12-29"),
           "2024_2025": ("2024-01-02", "2025-12-31")}


def diagnose(panel, run):
    market = panel['symbols'].index('SPYUSDT')
    market_returns = panel['open'][1:, market] / panel['open'][:-1, market] - 1
    selected, flat, excess = {}, [], []
    for i, (p, row) in enumerate(zip(run['picks'], run['curve'])):
        name = p['target'] or 'CASH'
        r = selected.setdefault(name, dict(periods=0, log_growth=0., market_log_growth=0.))
        r['periods'] += 1
        r['log_growth'] += float(np.log1p(row['returns']))
        r['market_log_growth'] += float(np.log1p(market_returns[i]))
        excess.append(np.log1p(row['returns']) - np.log1p(market_returns[i]))
        if p['target'] is None:
            flat.append(float(market_returns[i]))
    return dict(by_selected_asset=selected, flat_periods=len(flat), total_periods=len(run['curve']),
        market_return_during_flat_pct=float((np.prod(1+np.array(flat))-1)*100),
        log_growth_gap_to_spy_pct=float(sum(excess)*100),
        note="Conditioned on the original account's decisions, not a counterfactual deletion or a risk-matched alpha regression.")


def combine(left,right,times,capital):
    assert [r['time'] for r in left['curve']]==[r['time'] for r in right['curve']]
    previous=capital; curve=[]
    for a,b in zip(left['curve'],right['curve']):
        equity=a['equity']+b['equity']
        curve.append(dict(time=a['time'],equity=equity,returns=equity/previous-1,
            price_pnl=a['price_pnl']+b['price_pnl'],funding_pnl=a['funding_pnl']+b['funding_pnl'],costs=a['costs']+b['costs']))
        previous=equity
    nav=np.array([capital,*[r['equity'] for r in curve]])
    years=(times[-1]-times[0])/YEAR;mdd=float(np.max(1-nav/np.maximum.accumulate(nav)))
    cagr=float((nav[-1]/capital)**(1/years)-1)
    return dict(summary=dict(initial=capital,final=float(nav[-1]),return_pct=float((nav[-1]/capital-1)*100),
        cagr_pct=cagr*100,mdd_pct=mdd*100,calmar=cagr/mdd if mdd else None,
        costs=left['summary']['costs']+right['summary']['costs'],
        funding_pnl=left['summary']['funding_pnl']+right['summary']['funding_pnl'],
        child_accounts={'equity_crypto':left['summary'],'commodity':right['summary']},
        note="Two disjoint virtual capital books, equal initial funding, no transfers or optimized ratio; absolute equity summed, not average return percentages."),
        curve=curve,fills=sorted(left['fills']+right['fills'],key=lambda r:r['time']))


def two_books(panel,rule,*,capital,cost_bp,filters=None,capacity=False,native=False):
    names=panel['symbols'];g=panel['groups']
    common=dict(capital=capital/2,cost_bp=cost_bp,filters=filters,capacity=capacity,cap=2 if native else 1)
    left=replay(panel,replace(rule,carrier_risk=native,excluded_symbols=tuple(s for s in names if g[s]=='commodity')),**common)
    right=replay(panel,replace(rule,carrier_risk=native,excluded_symbols=tuple(s for s in names if g[s]!='commodity')),**common)
    return combine(left,right,panel['times'],capital)


def hourly_valuation(book,run,start,end):
    """Rebuild hourly marked NAV from signed cashflows and raw settlements.

    Settlement at an exit instant belongs to the outgoing position; same-time
    funding is processed before fills. This is hourly sampled MDD, not tick MDD.
    """
    events=[]
    for s,d in book.items():
        for r in d['funding']:
            t=int(r['fundingTime'])/1000
            if start<t<=end:
                events.append((t,0,s,float(r['fundingRate']),float(r['markPrice']) if r.get('markPrice') else None,0.))
    for r in run['fills']:
        events.append((r['time'],1,r['symbol'],r['quantity'],r['price'],r['costs']))
    events.sort(key=lambda r:(r[0],r[1]))
    marks={s:{b.t:b.o for b in d['mark']} for s,d in book.items()}
    cash=run['summary']['initial'];q={s:0. for s in book};k=0;nav=[cash];curve=[];funding=0.;max_gross=0.
    for t in range(int(start),int(end)+1,3600):
        while k<len(events) and events[k][0]<=t:
            _,kind,s,value,price,cost=events[k]
            if kind==0 and abs(q[s])>1e-12:
                assert price is not None,'missing_settlement_mark'
                change=-q[s]*value*price;cash+=change;funding+=change
            elif kind==1:
                cash-=value*price+cost;q[s]+=value
            k+=1
        value=cash+sum(quantity*marks[s][t] for s,quantity in q.items() if abs(quantity)>1e-12)
        notional=sum(abs(quantity)*marks[s][t] for s,quantity in q.items() if abs(quantity)>1e-12)
        max_gross=max(max_gross,notional/value if value>0 else float('inf'))
        nav.append(value);curve.append(dict(time=t,equity=value))
    nav=np.asarray(nav)
    assert np.isclose(funding,run['summary']['funding_pnl'],atol=1e-7)
    residual={s:quantity for s,quantity in q.items() if abs(quantity)>1e-10}
    if not residual: assert np.isclose(value,run['summary']['final'],atol=1e-7)
    return dict(hourly_mdd_pct=float(np.max(1-nav/np.maximum.accumulate(nav))*100),marked_final=float(value),
                trade_endpoint_final=run['summary']['final'],max_hourly_mark_gross=float(max_gross),
                funding_pnl=float(funding),terminal_quantities=residual,curve=curve)


def extend_crypto_prefix(book,*,download=False):
    """At most 24 bounded public requests; immutable six-file hourly prefix."""
    import hashlib
    root=Path('state/research_cache/g20_cross_asset_prefix_20261102');root.mkdir(parents=True,exist_ok=True)
    tasks=[(s,kind) for s in ('BTCUSDT','ETHUSDT','SOLUSDT') for kind in ('trade','mark')]
    first=timestamp('2026-04-07')
    def load_one(task):
        s,kind=task;end=book[s][kind][0].t
        path=root/f'{s}-{kind}-{first}-{end}.json'
        requests=0
        if not path.exists():
            if not download: raise FileNotFoundError(path)
            cursor=first*1000;rows=[]
            while cursor<end*1000:
                requests+=1
                assert requests<=4,'bounded_prefix_request_limit'
                endpoint='/fapi/v1/klines' if kind=='trade' else '/fapi/v1/markPriceKlines'
                values=public_get(endpoint,dict(symbol=s,interval='1h',startTime=cursor,endTime=end*1000-1,limit=1500))
                assert values and int(values[0][0])==cursor
                values=[r for r in values if first*1000<=int(r[0])<end*1000]
                rows.extend(values);cursor=int(values[-1][0])+3600000
            assert [int(r[0])//1000 for r in rows]==list(range(first,end,3600))
            assert all(float(r[3])<=min(float(r[1]),float(r[4]))<=max(float(r[1]),float(r[4]))<=float(r[2]) for r in rows)
            with path.open('x') as stream: json.dump(rows,stream,separators=(',',':'),allow_nan=False)
        rows=json.loads(path.read_text())
        assert [int(r[0])//1000 for r in rows]==list(range(first,end,3600))
        assert all(int(r[6])==int(r[0])+3599999 and
                   0<float(r[3])<=min(float(r[1]),float(r[4]))<=max(float(r[1]),float(r[4]))<=float(r[2]) for r in rows)
        prefix=[Bar(int(r[0])//1000,*(float(r[i]) for i in (1,2,3,4)),float(r[5])) for r in rows]
        return s,kind,prefix,dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),public_requests=requests)
    with ThreadPoolExecutor(max_workers=2) as pool: data=list(pool.map(load_one,tasks))
    for s,kind,rows,_ in data: book[s][kind]=rows+book[s][kind]
    return [r[3] for r in data]


def static_spy(panel,fraction,capital=10000.,cost_bp=30):
    """Exact daily static-weight cash book, including each delta fee.

    Fraction is an ex-post exposure-matching diagnostic, never a new policy.
    """
    fee=cost_bp/10000;j=panel['symbols'].index('SPYUSDT');cash=capital;q=0.;previous=capital;curve=[];fills=[]
    for i in range(len(panel['times'])-1):
        price=panel['open'][i,j];equity=cash+q*price
        if fraction*equity>=q*price:
            wanted=fraction*(equity+fee*q*price)/(price*(1+fraction*fee))
        else:
            wanted=fraction*(equity-fee*q*price)/(price*(1-fraction*fee))
        delta=wanted-q;cost=abs(delta)*price*fee;cash-=delta*price+cost;q=wanted
        if abs(delta)>1e-12: fills.append(dict(time=int(panel['times'][i]),symbol='SPYUSDT',quantity=float(delta),price=float(price),costs=float(cost)))
        final_price=panel['open'][i+1,j];value=cash+q*final_price
        if i==len(panel['times'])-2:
            charge=q*final_price*fee;cash+=q*final_price-charge
            fills.append(dict(time=int(panel['times'][i+1]),symbol='SPYUSDT',quantity=-float(q),price=float(final_price),costs=float(charge)))
            value=cash;q=0.
        curve.append(dict(time=int(panel['times'][i+1]),equity=float(value),returns=float(value/previous-1)))
        previous=value
    nav=np.array([capital,*[r['equity'] for r in curve]]);years=(panel['times'][-1]-panel['times'][0])/YEAR
    return dict(summary=dict(final=float(nav[-1]),return_pct=float((nav[-1]/capital-1)*100),
        cagr_pct=float(((nav[-1]/capital)**(1/years)-1)*100),mdd_pct=float(np.max(1-nav/np.maximum.accumulate(nav))*100),
        exposure_fraction=fraction),curve=curve,fills=fills)


def always_spy(panel):
    return dict(panel,features=[{s:dict(f,trend=True,above_mean=True) if s=='SPYUSDT' else dict(f)
                                for s,f in snapshot.items()} for snapshot in panel['features']])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('state/research_runs/g20_cross_asset_refinement_20261102'))
    parser.add_argument('--extend-native',action='store_true')
    parser.add_argument('--download-prefix',action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    bars, sources = etf_sources()
    book, signals, native_sources = native_inputs()
    npanels = {'base': native_panel(book, signals), 'delay1h': native_panel(book, signals, delay_hours=1)}
    filters = {s: d['rule'] for s, d in book.items()}
    native, proxy, controls, curves, checks = {}, {}, {}, {}, []
    for name, rule in RULES.items():
        native[name] = {}
        for scenario, capital, cost, units, capacity, clock in (
            ('small21',21.25,30,filters,True,'base'),
            ('small21_cost60',21.25,60,filters,True,'base'),
            ('small21_delay1h',21.25,30,filters,True,'delay1h'),
            ('filtered1000',1000.,30,filters,True,'base'),
            ('continuous21',21.25,30,None,False,'base'),
            ('small21_clip',21.25,30,filters,True,'base'),
            ('small21_clip_cost60',21.25,60,filters,True,'base'),
            ('filtered1000_clip',1000.,30,filters,True,'base')):
            rr=replace(rule,carrier_risk=True,capacity_mode='clip' if 'clip' in scenario else 'skip')
            run=replay(npanels[clock],rr,capital=capital,cost_bp=cost,filters=units,capacity=capacity)
            native[name][scenario]=run['summary']
            curves['native:'+name+':'+scenario]=run
        print('native',name,round(native[name]['small21']['return_pct'],3),round(native[name]['small21']['mdd_pct'],3),flush=True)
    old=json.loads(Path('state/research_runs/g20_cross_asset_mechanisms_20261102/results.json').read_text())
    for scenario in native['baseline']:
        if 'clip' in scenario: continue
        assert native['baseline'][scenario] == old['native']['retain_carrier_risk'][scenario],scenario
        checks.append('native:'+scenario)
    full_panel, baseline_diagnosis = None, None
    for window,(start,end) in WINDOWS.items():
        panel=proxy_panel(bars,start,end)
        proxy[window]={}
        controls[window]=dict(SPY_buy_hold=buy_hold(panel,['SPYUSDT']),equal_initial_eight=buy_hold(panel,list(panel['symbols'])))
        for name,rule in RULES.items():
            proxy[window][name]={}
            for cost in (0,30,60):
                run=replay(panel,rule,capital=10000.,cap=1,cost_bp=cost)
                proxy[window][name][str(cost)]=run['summary']
                if window=='2017_2025':
                    curves['proxy:'+name+':'+str(cost)]=run
                    if name=='baseline' and cost==30:
                        baseline_diagnosis=diagnose(panel,run)
            if name=='baseline':
                for cost in (30,60):
                    assert proxy[window][name][str(cost)]==old['proxy'][window]['retain_trend'][str(cost)]
                    checks.append('proxy:'+window+':'+str(cost))
        if window=='2017_2025': full_panel=panel
        print('proxy',window,{n:(round(v['30']['cagr_pct'],2),round(v['30']['mdd_pct'],2)) for n,v in proxy[window].items()},flush=True)
    years=(full_panel['times'][-1]-full_panel['times'][0])/YEAR
    diversification={'native':{},'proxy':{}}
    for name in ('baseline','price_own','price_entry'):
        rr=replace(RULES[name],capacity_mode='clip')
        diversification['native'][name]={}
        for scenario,capital,cost,units,capacity,clock in (
            ('small21',21.25,30,filters,True,'base'),('small21_cost60',21.25,60,filters,True,'base'),
            ('small21_delay1h',21.25,30,filters,True,'delay1h'),('filtered1000',1000.,30,filters,True,'base'),
            ('continuous21',21.25,30,None,False,'base')):
            run=two_books(npanels[clock],rr,capital=capital,cost_bp=cost,filters=units,capacity=capacity,native=True)
            diversification['native'][name][scenario]=run['summary']
            curves['dual_native:'+name+':'+scenario]=run
        for window,(start,end) in WINDOWS.items():
            pp=full_panel if window=='2017_2025' else proxy_panel(bars,start,end)
            diversification['proxy'].setdefault(window,{})[name]={}
            for cost in (30,60):
                run=two_books(pp,rr,capital=10000.,cost_bp=cost)
                diversification['proxy'][window][name][str(cost)]=run['summary']
                if window=='2017_2025': curves['dual_proxy:'+name+':'+str(cost)]=run
        print('two-books',name,diversification['native'][name]['small21']['return_pct'],
              diversification['proxy']['2017_2025'][name]['30']['cagr_pct'],flush=True)
    concentration={'native':{},'proxy':{}}
    for s in npanels['base']['symbols']:
        rr=replace(RULES['price_own'],carrier_risk=True,capacity_mode='clip',excluded_symbols=(s,))
        concentration['native'][s]=replay(npanels['base'],rr,capital=21.25,cost_bp=30,filters=filters,capacity=True,keep_records=False)['summary']
    for s in full_panel['symbols']:
        rr=replace(RULES['price_own'],excluded_symbols=(s,))
        concentration['proxy'][s]=replay(full_panel,rr,capital=10000.,cost_bp=30,cap=1,keep_records=False)['summary']
    hourly={}
    for name in ('baseline','price_own','core_only'):
        for scenario in ('small21_clip','small21_clip_cost60','filtered1000_clip'):
            key='native:'+name+':'+scenario
            hourly[key]=hourly_valuation(book,curves[key],npanels['base']['times'][0],npanels['base']['times'][-1])
    matched=static_spy(full_panel,proxy['2017_2025']['core_dual_failure']['30']['mean_gross'])
    curves['proxy:matched_static_spy:30']=matched
    spy_risk=replay(always_spy(full_panel),RULES['core_only'],capital=10000.,cap=1,cost_bp=30)
    curves['proxy:always_spy_risk:30']=spy_risk
    extended={};start_checks={}
    if args.extend_native:
        native_sources+=extend_crypto_prefix(book,download=args.download_prefix)
        epanels={'base':native_panel(book,signals,start='2026-04-07',allow_unlisted=True),
                 'delay1h':native_panel(book,signals,start='2026-04-07',delay_hours=1,allow_unlisted=True)}
        for name in ('baseline','price_own','price_entry','core_only','dual_failure_own','core_dual_failure','SPY_risk_control'):
            extended[name]={}
            for scenario,capital,cost,clock in (('small21',21.25,30,'base'),('small21_cost60',21.25,60,'base'),
                    ('small21_delay1h',21.25,30,'delay1h'),('filtered1000',1000.,30,'base'),('continuous21',21.25,30,'base')):
                units=None if scenario=='continuous21' else filters; capacity=scenario!='continuous21'
                rr=replace(RULES['core_only'] if name=='SPY_risk_control' else RULES[name],carrier_risk=True,capacity_mode='clip')
                used_panel=always_spy(epanels[clock]) if name=='SPY_risk_control' else epanels[clock]
                run=replay(used_panel,rr,capital=capital,cost_bp=cost,filters=units,capacity=capacity)
                extended[name][scenario]=run['summary'];key='extended:'+name+':'+scenario;curves[key]=run
                hourly[key]=hourly_valuation(book,run,epanels[clock]['times'][0],epanels[clock]['times'][-1])
            print('extended',name,extended[name]['small21']['return_pct'],flush=True)
        for name in ('baseline','price_own','price_entry'):
            label='dual_'+name;extended[label]={}
            for scenario,capital,cost,clock in (('small21',21.25,30,'base'),('small21_cost60',21.25,60,'base'),
                    ('small21_delay1h',21.25,30,'delay1h'),('filtered1000',1000.,30,'base'),('continuous21',21.25,30,'base')):
                units=None if scenario=='continuous21' else filters;capacity=scenario!='continuous21'
                run=two_books(epanels[clock],replace(RULES[name],capacity_mode='clip'),capital=capital,cost_bp=cost,
                              filters=units,capacity=capacity,native=True)
                extended[label][scenario]=run['summary'];key='extended:'+label+':'+scenario;curves[key]=run
                hourly[key]=hourly_valuation(book,run,epanels[clock]['times'][0],epanels[clock]['times'][-1])
            print('extended',label,extended[label]['small21']['return_pct'],flush=True)
        for start in ('2026-04-07','2026-05-04','2026-06-01','2026-07-01','2026-08-03','2026-09-01','2026-10-01'):
            panel_=native_panel(book,signals,start=start,allow_unlisted=True)
            run=replay(panel_,replace(RULES['core_dual_failure'],carrier_risk=True,capacity_mode='clip'),
                       capital=21.25,cost_bp=30,filters=filters,capacity=True)
            start_checks[start]=dict(summary=run['summary'],
                hourly_mark=hourly_valuation(book,run,panel_['times'][0],panel_['times'][-1])['hourly_mdd_pct'])
    for name in ('baseline','price_own','price_entry'):
        for scenario in ('small21','small21_cost60','filtered1000'):
            key='dual_native:'+name+':'+scenario
            hourly[key]=hourly_valuation(book,curves[key],npanels['base']['times'][0],npanels['base']['times'][-1])
    paired={}
    for name in RULES:
        if name=='baseline': continue
        paired[name]={
            'proxy':paired_interval(curves['proxy:'+name+':30'],curves['proxy:baseline:30'],blocks=(20,60),annual=years),
            'native':paired_interval(curves['native:'+name+':small21'],curves['native:baseline:small21'])}
    result=dict(research_only=True,orders_authorized=False,independent_oos=False,
        hypothesis="Repair capped-risk ranking, permanent incumbent lock, holding invalidation, and overbroad family gates; no numeric parameter optimization.",
        rules={k:asdict(v) for k,v in RULES.items()},windows=WINDOWS,
        baseline_diagnosis=baseline_diagnosis,prior_controls_exact=checks,
        proxy=proxy,native=native,controls=controls,paired_comparisons=paired,
        diversification=diversification,leave_one_asset_out=concentration,
        hourly_mark_valuation={k:{field:v for field,v in r.items() if field!='curve'} for k,r in hourly.items()},
        extended_native=extended,
        extended_window="2026-04-07 NY10:00 to 2026-10-23 NY10:00; native assets enter only after actual listing and risk warmup",
        fresh_start_checks=start_checks,
        matched_controls=dict(static_spy=matched['summary'],always_spy_risk=spy_risk['summary'],
            paired_core_to_matched=paired_interval(curves['proxy:core_dual_failure:30'],matched,blocks=(20,60),annual=years)),
        sources=sources+native_sources,
        execution="Same common native NY10/11 and prior completed closes; long ETF next session open; native 2x target/60% vol, ETF cap1; costs 0/30/60bp, cash0.",
        limitations=["All samples already consumed; mechanism contrasts and named interactions, not independent OOS.",
            "No untouched OOS; common native Aug3-Oct23 window is retained and an optional Apr7-Oct23 extended execution window uses six bounded official public hourly prefix files. Three cryptos and eight currently selected macro assets; actual listing/risk warmup respected, current filters retrospectively applied.",
            "Allocation score uses capped exposure times historical drift, not a certified expected return. Cost-aware replacement amortizes switching friction over fixed original 63-day signal horizon.",
            "Price invalidation permits the incumbent's momentum to turn negative while its price remains above the original mean; entry still requires both. Own regime removes group-wide gates, it is not less data validation.",
            "ETF adjusted units/fractional holdings/pretax, no native funding or exact dividend timing; cap1 avoids unmodeled borrowing costs."])
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (args.output/'curves.json').write_text(json.dumps(curves,ensure_ascii=False,allow_nan=False)+'\n')
    (args.output/'hourly_mark_curves.json').write_text(json.dumps(hourly,ensure_ascii=False,allow_nan=False)+'\n')


if __name__=='__main__': main()
