"""Auditable holding-episode attribution of immutable no-order research ledgers."""
from __future__ import annotations
import datetime as dt
import json
import math
import statistics as stats
import sys
from pathlib import Path
from qount.research.dual_engine_optimization import file_hash, write_json
from qount.research.dual_engine_execution_study import verify_manifest


def regime_features(closes, dates, day, *, symbol):
    index=dates.index(day)
    valid=[closes.get(symbol,{}).get(d) for d in dates[max(0,index-126):index+1]]
    if len(valid)<64 or any(p is None or p<=0 for p in valid):return None
    return {'return21':valid[-1]/valid[-22]-1,'return63':valid[-1]/valid[-64]-1,
            'below_sma20':valid[-1]<stats.fmean(valid[-20:]),'below_sma50':valid[-1]<stats.fmean(valid[-50:])}


def analyze_units(run, dates, closes, opens, *, market, include_daily=False):
    """Continuous positions, net of notional-proportional fee allocation.

    Episodes are NOT trade lots. A still-open episode is explicitly censored.
    Every source/fee reconciles to wealth; observational tags are not causes.
    """
    rows=run['records'];index={d:i for i,d in enumerate(dates)}
    if not rows or any('units' not in r or 'cash' not in r or 'nav' not in r for r in rows):
        return {'status':'weights_only_ledger','position_episode_reconstruction':'unavailable','bars':len(rows),
            'positive_days':sum(r['return']>0 for r in rows),'negative_days':sum(r['return']<0 for r in rows),
            'weighted_exposure':{k:stats.fmean(r['weights'].get(k,0) for r in rows) for k in sorted({k for r in rows for k in r['weights']})},
            'limitation':'No explicit cash/units; do not fabricate fees, fills or closed position PnL.'}
    units={};nav=1.;cash=1.;assets={};active={};episodes=[];daily=[];max_error=0.;peak=1.;peak_day=None;worst=0.;dd_start=dd_end=None
    for row in rows:
        day=row['date'];i=index[day]
        if i<1:raise ValueError('attribution_warmup_insufficient')
        previous=dates[i-1];names=set(units)|set(row['units'])
        for k in names:
            if (units.get(k,0)>0 or row['units'].get(k,0)>0) and day not in opens.get(k,{}):raise ValueError('attribution_missing_open:'+k+':'+day)
        open_nav=nav+sum(u*(opens.get(k,{}).get(day,0)-closes.get(k,{}).get(previous,0)) for k,u in units.items())
        fee=open_nav*row['cost_fraction']
        trades={k:abs(row['units'].get(k,0)-units.get(k,0))*opens.get(k,{}).get(day,0) for k in names}
        notional=sum(trades.values())
        if fee>1e-12 and notional<=1e-14:raise ValueError('fee_without_trade_notional')
        components={}
        for k in sorted(names):
            old,new=units.get(k,0),row['units'].get(k,0)
            opn=opens.get(k,{}).get(day,0);close=closes.get(k,{}).get(day,0);old_close=closes.get(k,{}).get(previous,0)
            overnight=old*(opn-old_close);intraday=new*(close-opn);gross=overnight+intraday
            allocated=fee*trades[k]/notional if notional else 0.;net=gross-allocated
            a=assets.setdefault(k,dict(gross_pnl=0.,overnight_pnl=0.,intraday_pnl=0.,allocated_fees=0.,net_pnl=0.,buy_notional=0.,sell_notional=0.,held_days=0,gain_days=0,loss_days=0,yearly={}))
            for key,value in [('gross_pnl',gross),('overnight_pnl',overnight),('intraday_pnl',intraday),('allocated_fees',allocated),('net_pnl',net)]:a[key]+=value
            a['buy_notional']+=max(new-old,0)*opn;a['sell_notional']+=max(old-new,0)*opn
            a['held_days']+=int(new>1e-12);a['gain_days']+=int(net>1e-12);a['loss_days']+=int(net<-1e-12)
            a['yearly'][day[:4]]=a['yearly'].get(day[:4],0)+net
            if old<=1e-12 and new>1e-12:
                active[k]=dict(asset=k,first=day,entry_signal_date=row.get('signal_date'),entry_price=opn,
                    entry_features=regime_features(closes,dates,previous,symbol=k),market_entry_features=regime_features(closes,dates,previous,symbol=market),
                    gross_pnl=0.,allocated_fees=0.,net_pnl=0.,buy_notional=0.,sell_notional=0.,held_days=0,price_peak=opn,price_path_drawdown=0.)
            if k in active:
                e=active[k];e['gross_pnl']+=gross;e['allocated_fees']+=allocated;e['net_pnl']+=net
                e['buy_notional']+=max(new-old,0)*opn;e['sell_notional']+=max(old-new,0)*opn;e['held_days']+=int(new>1e-12)
                e['price_peak']=max(e['price_peak'],close if new>1e-12 else opn)
                e['price_path_drawdown']=min(e['price_path_drawdown'],(close if new>1e-12 else opn)/e['price_peak']-1)
                if new<=1e-12:
                    e.update(last=day,status='closed',exit_features=regime_features(closes,dates,previous,symbol=k))
                    e['fees_flip_gross_profit']=e['gross_pnl']>=0 and e['net_pnl']<0
                    episodes.append(e);del active[k]
            components[k]=dict(gross_pnl=gross,allocated_fees=allocated,net_pnl=net)
        expected_cash=cash-sum((row['units'].get(k,0)-units.get(k,0))*opens.get(k,{}).get(day,0) for k in names)-fee
        marked_nav=row['cash']+sum(u*closes.get(k,{}).get(day,0) for k,u in row['units'].items())
        error=max(abs(sum(v['net_pnl'] for v in components.values())-(row['nav']-nav)),abs(expected_cash-row['cash']),abs(marked_nav-row['nav']))
        max_error=max(max_error,error)
        daily.append(dict(date=day,nav=row['nav'],return_=row['return'],components=components))
        if row['nav']>=peak:peak=row['nav'];peak_day=day
        drawdown=row['nav']/peak-1
        if drawdown<worst:worst=drawdown;dd_start=peak_day;dd_end=day
        units={k:u for k,u in row['units'].items() if u>1e-12};nav=row['nav'];cash=row['cash']
    if max_error>1e-9 or abs(sum(a['net_pnl'] for a in assets.values())-(nav-1))>1e-9:raise ValueError('holding_attribution_wealth_mismatch')
    for k,e in active.items():
        e.update(last=rows[-1]['date'],status='open_censored',exit_features=None,fees_flip_gross_profit=e['gross_pnl']>=0 and e['net_pnl']<0)
        episodes.append(e)
    for k,a in assets.items():
        related=[e for e in episodes if e['asset']==k];closed=[e for e in related if e['status']=='closed']
        a['closed_profitable_episodes']=sum(e['net_pnl']>0 for e in closed);a['closed_losing_episodes']=sum(e['net_pnl']<0 for e in closed)
        a['open_censored_episodes']=sum(e['status']=='open_censored' for e in related)
        a['fees_flip_episodes']=sum(e['fees_flip_gross_profit'] for e in closed)
        a['largest_loss_episode']=min((e['net_pnl'] for e in closed),default=0)
    dd={}
    for row in daily:
        if dd_end and (dd_start is None or row['date']>dd_start) and row['date']<=dd_end:
            for k,v in row['components'].items():dd[k]=dd.get(k,0)+v['net_pnl']
    output=dict(status='cash_units_reconciled',assets=assets,episodes=episodes,max_daily_pnl_error=max_error,
        net_wealth_change=nav-1,source_net_pnl=sum(a['net_pnl'] for a in assets.values()),
        maximum_drawdown={'fraction':worst,'peak':dd_start,'trough':dd_end,'asset_net_pnl_initial_nav_units':dd},
        methodology='Episode PnL in initial NAV dollars, costs allocated by actual traded notional; observational regime tags, not causal proof; final open positions censored.')
    if include_daily:output['daily']=daily
    return output


def run_inventory(*, registry_root, out, dates, closes, opens, market_symbols, repo, contract_path, input_audit):
    from qount.research.dual_engine_expansion import require_storage
    require_storage(out)
    if out.exists():raise ValueError('immutable_attribution_exists')
    c=json.loads(contract_path.read_text())
    if any(c.get(k)!=v for k,v in {'study_id':'dual_engine_holdings_20261005','research_only':True,'orders_authorized':False,'new_candidate_trials':0,'planned_curves':549,'registered_versions':140}.items()):raise ValueError('holding_analysis_contract_invalid')
    registry_files=verify_manifest(registry_root,expected_hash=c['registry_manifest_sha256'])
    registry=json.loads((registry_root/'registry.json').read_text())
    if len(registry['versions'])!=140 or len(registry['studies'])!=7:raise ValueError('holding_registry_scope_changed')
    out.mkdir(parents=True)
    receipts=[];summaries={};cache={};counts={'curves':0,'unique_ledgers':0,'cash_units':0,'weights_only':0}
    for study in registry['studies']:
        root=Path(study['root']);files=verify_manifest(root,expected_hash=study['manifest_sha256']);r=json.loads((root/'results.json').read_text())
        for exposure in r['curve_exposures']:
            key=exposure['curve'];name=key+'-ledger.json'
            if name not in files:raise ValueError('ledger_not_manifest_bound:'+key)
            line='g20' if 'g20' in key else 'c60'
            digest=files[name];dedup=(line,digest)
            if dedup not in cache:
                ledger=json.loads((root/name).read_text())
                analysis=analyze_units(ledger,dates[line],closes[line],opens[line],market=market_symbols[line])
                target=out/'curves'/(study['study_id']+'/'+key+'.json');target.parent.mkdir(parents=True,exist_ok=True);write_json(target,analysis)
                cache[dedup]=(analysis,str(target.relative_to(out)));counts['unique_ledgers']+=1
            analysis,path=cache[dedup]
            counts['curves']+=1;counts['cash_units' if analysis['status']=='cash_units_reconciled' else 'weights_only']+=1
            record=dict(study_id=study['study_id'],curve=key,line=line,ledger_sha256=digest,analysis_path=path,status=analysis['status'])
            if 'assets' in analysis:
                risk={k:v for k,v in analysis['assets'].items() if k!='BIL'}
                record.update(net_wealth_change=analysis['net_wealth_change'],assets=analysis['assets'],
                    winning_assets=sorted((k for k in risk if risk[k]['net_pnl']>0),key=lambda k:-risk[k]['net_pnl']),
                    losing_assets=sorted((k for k in risk if risk[k]['net_pnl']<0),key=lambda k:risk[k]['net_pnl']),maximum_drawdown=analysis['maximum_drawdown'],
                    closed_profitable_episodes=sum(a['closed_profitable_episodes'] for a in risk.values()),closed_losing_episodes=sum(a['closed_losing_episodes'] for a in risk.values()),
                    fees_flip_episodes=sum(a['fees_flip_episodes'] for a in risk.values()),total_allocated_fees=sum(a['allocated_fees'] for a in analysis['assets'].values()))
            else:record.update(weighted_exposure=analysis['weighted_exposure'],negative_days=analysis['negative_days'],positive_days=analysis['positive_days'])
            summaries[study['study_id']+'/'+key]=record
        receipts.append(dict(study_id=study['study_id'],root=str(root),manifest_sha256=study['manifest_sha256']))
        print(json.dumps({'attributed':study['study_id'],'curves':counts['curves'],'unique_ledgers':counts['unique_ledgers']}),flush=True)
    report=dict(research_only=True,orders_authorized=False,promotion_evidence=False,result_status='completed_frozen_holding_diagnostics',counts=counts,
        registry_root=str(registry_root),registry_manifest_sha256=file_hash(registry_root/'manifest.json'),studies=receipts,summaries=summaries,
        global_trial_count=None,new_candidate_trials=0,scope='all seven G20/C60 studies, all registered curve exposures; exact holding episodes only where explicit cash/units exist')
    if counts['curves']!=549:raise ValueError('holding_curve_scope_incomplete')
    report['input_audit']=input_audit
    write_json(out/'holdings-summary.json',report)
    write_json(out/'contract.json',c)
    sources={repo/'scripts/research/dual_engine_holdings.py',contract_path.resolve()}
    for name,module in tuple(sys.modules.items()):
        file=getattr(module,'__file__',None)
        if name.startswith('qount') and file and Path(file).suffix=='.py':
            path=Path(file).resolve()
            if not path.is_relative_to(repo.resolve()/'src'):raise ValueError('analysis_source_outside_delivery')
            sources.add(path)
    for path in sources:
        dst=out/'source'/path.relative_to(repo);dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(path.read_bytes())
    write_json(out/'manifest.json',dict(research_only=True,orders_authorized=False,files={str(p.relative_to(out)):file_hash(p) for p in sorted(out.rglob('*')) if p.is_file()}))
    return report


def run_from_paths(*, registry_root, out, repo, equity_root, pit_cache, expansion_root, tail_root, inverse_root, open_roots, contract):
    from qount.research import dual_engine_optimization as old
    from qount.research.dual_engine_expansion_data import load_macro
    from qount.research.dual_engine_nextgen_data import load_tail
    from qount.research.dual_engine_regimes_data import load_inverse
    from qount.research.dual_engine_execution_study import load_cache,read_opens
    from qount.research.dual_engine_structural import crypto_prices
    panel,equity_audit=old.load_equity(equity_root,old.read_contract(repo/'config/dual-engine-optimization-20261004.json'))
    panel=load_inverse(load_tail(load_macro(panel,expansion_root),tail_root),inverse_root)
    raw,cache_hashes=load_cache(pit_cache);axis,assets=old.build_crypto_assets(raw)
    union={};source_opens={}
    for root in open_roots:
        data,source_opens[str(root)]=read_opens(root)
        for symbol,series in data.items():
            saved=union.setdefault(symbol,{})
            for day,value in series.items():
                if day in saved and saved[day]!=value:raise ValueError('frozen_open_sources_disagree')
                saved[day]=value
    cr_close,cr_open=crypto_prices(axis,assets,union)
    eq_close={s:dict(zip(panel.dates,v,strict=True)) for s,v in panel.total_closes.items()}
    eq_open={s:dict(zip(panel.dates,v,strict=True)) for s,v in panel.total_opens.items()}
    btc=next(k for k,a in assets.items() if a.symbol=='BTCUSDT')
    audit={'equity':equity_audit,'cache_sha256':cache_hashes,'open_roots':source_opens,'additional_sources':{str(root):verify_manifest(root) for root in (expansion_root,tail_root,inverse_root)},'paths':{'equity_root':str(equity_root),'pit_cache':str(pit_cache)}}
    return run_inventory(registry_root=registry_root,out=out,repo=repo,contract_path=contract,input_audit=audit,dates={'g20':panel.dates,'c60':axis.dates},
        closes={'g20':eq_close,'c60':cr_close},opens={'g20':eq_open,'c60':cr_open},market_symbols={'g20':'SPY','c60':btc})
