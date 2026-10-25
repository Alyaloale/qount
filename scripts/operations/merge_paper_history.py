#!/usr/bin/env python3
"""Resume preserved paper accounts in isolated output directories, retaining catchup provenance.

Public inputs must already be cached. This command never downloads data or submits orders.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import math
from pathlib import Path

from qount.contracts import canonical_hash
from qount.dual_engine import run_paper_cycle
from qount.dual_engine.contracts import C60_SYMBOLS, G20_PROXY_SYMBOLS, G20_EXECUTION_SYMBOLS, PaperCycleInput
from qount.dual_engine.market_data import _binance_daily_bar, _tiingo_daily_bar
from qount.research_data.macro_live import write_json
from qount.research_data.paper_daily import NY
from scripts.operations.run_research_paper import etf_step


def read(path):
    return json.loads(Path(path).read_text())


def resume_dual(root, inputs, quotes, market_config, recorded_at):
    root,inputs,quotes=map(Path,(root,inputs,quotes))
    if (root/'continuity.json').exists():
        raise ValueError('dual_output_already_resumed_use_an_untouched_copy')
    state=read(root/'state/program.json')
    historical_end=state['portfolios']['dual-engine-paper-g20']['history'][-1]['marked_at']
    history_start=state['portfolios']['dual-engine-paper-g20']['history'][0]['marked_at']
    latest=max((read(p) for p in (inputs/'inputs').glob('*.json')),key=lambda x:x['observed_at'])
    yahoo={s:read(inputs/'market-cache/yahoo-public'/f'{s}-1d.json') for s in (*G20_PROXY_SYMBOLS,*G20_EXECUTION_SYMBOLS,'BIL')}
    crypto={s:read(quotes/f'{s}-daily.json')['rows'] for s in C60_SYMBOLS}
    first=dt.datetime.fromisoformat(historical_end).date()+dt.timedelta(days=1)
    last=dt.datetime.fromisoformat(latest['observed_at']).date()-dt.timedelta(days=1)
    dates=[first+dt.timedelta(days=n) for n in range((last-first).days+1)]
    model_times=[]
    for day in dates:
        when=dt.datetime.combine(day,dt.time(22,30),dt.timezone.utc)
        # Daily closes available before this decision; next/current unfinished crypto bars are excluded.
        proxy={};marks={};bars={};cutoffs=[];histories={}
        for symbol,source in yahoo.items():
            rows=[r for r in source['rows'] if dt.datetime.combine(dt.date.fromisoformat(r['date']),dt.time(16,15),NY)<=when]
            if len(rows)<100:raise ValueError('dual_equity_warmup_short')
            latest_bar=rows[-1]
            if symbol in G20_PROXY_SYMBOLS:proxy[symbol]=[r['adjClose'] for r in rows[-100:]]
            else:
                marks[symbol]=latest_bar['close'];bars[symbol]=_tiingo_daily_bar(latest_bar,symbol=symbol)
            cutoffs.append(dt.datetime.combine(dt.date.fromisoformat(latest_bar['date']),dt.time(16),NY))
        for symbol,rows in crypto.items():
            closed=[r for r in rows if int(r[6])<int(when.timestamp()*1000)]
            if len(closed)<91:raise ValueError('dual_crypto_warmup_short')
            histories[symbol]=[float(r[4]) for r in closed[-100:]]
            minute=read(quotes/f'{symbol}-{day.day}.json')['rows'][0]
            if int(minute[0])!=int(when.timestamp()*1000):raise ValueError('dual_fill_time_mismatch')
            marks[symbol]=float(minute[1]);bars[symbol]=_binance_daily_bar(closed[-1],symbol=symbol)
            cutoffs.append(dt.datetime.fromtimestamp(int(closed[-1][6])/1000,dt.timezone.utc))
        if day.isoformat() in market_config['g20_rebalance_dates']:
            raise ValueError('monthly_open_requires_separate_causal_input')
        cycle=PaperCycleInput.create(observed_at=when.isoformat(),decision_time=when.isoformat(),
            data_cutoff=max(cutoffs).astimezone(dt.timezone.utc).isoformat(),proxy_closes=proxy,
            crypto_closes=histories,mark_prices=marks,fill_prices=marks,symbol_rules=latest['symbol_rules'],
            source_hashes={'yahoo_public':canonical_hash(yahoo),'binance_public':canonical_hash(dict(histories=histories,marks=marks)),
                           'binance_exchange_rules':canonical_hash(latest['symbol_rules'])},
            market_bars=bars,g20_signal_day=day.isoformat() in market_config['g20_signal_dates'],g20_rebalance_day=False)
        run_paper_cycle(root,cycle)
        model_times.append(cycle.observed_at)
    # The actual restart input is reused at its recorded time; account catchup remains retrospective.
    cycle=PaperCycleInput.from_dict(latest)
    result=run_paper_cycle(root,cycle)
    model_times.append(cycle.observed_at)
    write_json(root/'continuity.json',dict(recorded_at=recorded_at,
        segments=[dict(kind='historical',start=history_start,end=historical_end,
                       note='原账户历史记录，原净值和持仓不改写'),
                  dict(kind='reconstructed',start=model_times[0],end=model_times[-1],recorded_at=recorded_at,
                       note='从旧持仓/现金逐周期补跑；日线只用当时已收盘数据，缺口按22:30 UTC公开1分钟开盘价模拟，现行交易单位回溯近似。')]))
    return dict(cycles=len(model_times),historical_end=historical_end,as_of=result.data_cutoff,
                navs={p['portfolio_id']:p['nav']['points'][-1]['executable'] for p in result.portfolios})


def resume_etf(root, historical, recorded_at):
    root,historical=map(Path,(root,historical))
    cache=read(root/'cache/513100.json');rows=cache['rows']
    replay=read(historical/'baseline-replay.json')['513100.SH']
    prior=replay['MA120_Band1.5pct'];benchmark=replay['Buy_and_Hold']
    old_trades=read(historical/'trades.json')['513100.SH']['MA120_Band1.5pct']
    initial=prior['metrics']['initial_equity']
    end=dt.datetime.strptime(prior['nav'][-1][0],'%Y%m%d').date().isoformat()
    warmup=[r for r in rows if r['date']<=end]
    state,_,_,_=etf_step(None,warmup,genesis=True)
    from qount.api.ledger import parse_personal_assistant_position_ledger
    qty,_=parse_personal_assistant_position_ledger(old_trades,as_of=end.replace('-',''))
    cash=float(old_trades[-1].get('cash_rem',0))
    terminal=cash+qty*warmup[-1]['close']
    if not math.isclose(terminal,prior['metrics']['terminal_equity'],abs_tol=.02):
        raise ValueError('etf_historical_equity_mismatch')
    state.update(cash=cash,quantity=qty)
    state['machine']['executed_state']=float(qty>0)
    if state['machine']['current_target']!=float(qty>0):
        raise ValueError('etf_latest_signal_requires_pending_order_review')
    def date(value):return dt.datetime.strptime(value,'%Y%m%d').date().isoformat()
    bench={date(d):v/initial for d,v in benchmark['nav']}
    original_recorded_at=read(historical/'summary.json')['generated_at']
    observations=[dict(date=date(d),equity=v,positions=[],sample_kind='historical',recorded_at=original_recorded_at,
                       benchmark_nav=bench.get(date(d))) for d,v in prior['nav']]
    benchmark_quantity=benchmark['nav'][-1][1]/warmup[-1]['close']
    trades=[dict(date=date(t['date']),symbol='513100.SH',side=t['action'],quantity=t.get('shares'),
                 price=t.get('price'),cost=t.get('commission'),sample_kind='historical',
                 note=(f"split_ratio={t['split_ratio']}; " if t.get('split_ratio') else '')+(t.get('note') or '历史回放')) for t in old_trades]
    rules=dict(ma=120,band=.015,confirmation=2,lot_size=0,commission_bps=6,slippage_bps=5,cash_apr=.02)
    for day in [r['date'] for r in rows if r['date']>end]:
        subset=[r for r in rows if r['date']<=day]
        state,equity,positions,events=etf_step(state,subset,genesis=False,rules=rules)
        observations.append(dict(date=day,equity=equity,positions=positions,sample_kind='reconstructed',
            recorded_at=recorded_at,source_hash=cache['source_hash'],benchmark_nav=benchmark_quantity*subset[-1]['close']/initial))
        trades.extend(dict(t,sample_kind='reconstructed',recorded_at=recorded_at) for t in events)
    data=dict(schema_version=1,kind='etf',created_at=recorded_at,initial_equity=initial,state=state,
        observations=observations,trades=trades,research_only=True,orders_authorized=False,
        rules=rules,source='tencent_public_raw_and_qfq',continuous=True,observed_at=recorded_at,
        source_hash=cache['source_hash'],last_error=None,benchmark_quantity=benchmark_quantity,
        history_reference=str(historical/'baseline-replay.json'))
    write_json(root/'forward.json',data)
    return dict(historical_observations=len(prior['nav']),reconstructed=len(observations)-len(prior['nav']),
                equity=observations[-1]['equity'],positions=observations[-1]['positions'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dual-root',type=Path,required=True)
    p.add_argument('--dual-inputs',type=Path,required=True)
    p.add_argument('--quotes',type=Path,required=True)
    p.add_argument('--market-config',type=Path,default=Path('deploy/dual_engine/paper-v1.json'))
    p.add_argument('--research-root',type=Path,required=True)
    p.add_argument('--etf-history',type=Path,required=True)
    args=p.parse_args();now=dt.datetime.now(dt.timezone.utc).isoformat()
    print(json.dumps({'dual':resume_dual(args.dual_root,args.dual_inputs,args.quotes,read(args.market_config),now)}))
    print(json.dumps({'etf':resume_etf(args.research_root/'etf',args.etf_history,now)}))

if __name__=='__main__':main()
