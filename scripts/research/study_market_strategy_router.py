"""Pure state classifier -> probability threshold -> traditional strategy rules."""
from __future__ import annotations

import argparse
from collections import Counter,defaultdict
import datetime as dt
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np

from qount.research.market_strategy_router import (
    STATE_NAMES,STRATEGIES,StrategyRoute,state_probabilities,route_strategy,traditional_entry,
)
from qount.research.market_stages import market_state_machine
from qount.research.market_state_scores import FEATURES,state_feature_matrix
from qount.research.market_model_profit import replay_asset,summarize_portfolio
from qount.research_data.bars import NY
from study_market_model_profit import load_npz,DAILY,RAW,exchange_rules,daily_bars
from study_binance_market_states import load_markets


REFERENCE=Path('state/research_runs/market_trade_retrain_20261031_execution_r')
PANEL=Path('state/research_runs/market_state_scores_20261031_probability_gated/dataset.npz')


def known_time(bar,group):return (bar.t+(61 if group=='crypto' else 60))*1000


def open_time(bar,group):
    if group=='crypto':return (bar.t+1-86400)*1000
    day=dt.datetime.fromtimestamp(bar.t,NY).date()
    return int(dt.datetime.combine(day,dt.time(9,30),NY).timestamp())*1000


def model_route(book,time,bars,group,threshold):
    position=int(np.searchsorted(book['known_at'],time,side='right')-1)
    if position<0:return StrategyRoute(None,0.,None,'no_available_forecast'),0
    index=int(book['bar_index'][position]);source=int(book['known_at'][position])
    if index+5>=len(bars) or time>=known_time(bars[index+5],group):
        return StrategyRoute(None,0.,None,'expired_forecast'),source
    p={STATE_NAMES[j]:float(v) for j,v in enumerate(book['probabilities'][position]) if STATE_NAMES[j]!='unknown'}
    return route_strategy(p,threshold=threshold),source


def proposed_entries(markets,states,books,policy):
    decisions={g:defaultdict(list) for g in markets};stats={g:Counter() for g in markets}
    threshold=.70 if policy=='model70' else 0.
    for group,assets in markets.items():
        for asset,bars in assets.items():
            for i,b in enumerate(bars):
                known=known_time(b,group)
                if known<1672531200000:continue
                stats[group]['observations']+=1
                f=states[group][asset][b.t]
                if policy=='rules_only':
                    state=f['action_state'];route=StrategyRoute(state,1.,STRATEGIES[state],'current_rule_state');source=known
                else:route,source=model_route(books[asset],known,bars,group,threshold)
                if route.strategy is None:stats[group]['wait:'+route.reason]+=1;continue
                stats[group]['enabled:'+route.strategy]+=1
                entry=traditional_entry(route,b,f,allow_short=group=='crypto')
                if entry is None:stats[group]['no_strategy_setup']+=1;continue
                at=i+(2 if group=='crypto' else 1)
                if at>=len(bars):stats[group]['no_next_entry_bar']+=1;continue
                entry_at=open_time(bars[at],group);entry_source=source
                # Recheck routing using only model messages available by the
                # scheduled entry time; pending permissions may expire/change.
                if policy!='rules_only':
                    entry_route,entry_source=model_route(books[asset],entry_at,bars,group,threshold)
                    if entry_route.strategy!=route.strategy:stats[group]['expired_or_changed_before_entry']+=1;continue
                if source>known or entry_source>entry_at or known>=entry_at:raise ValueError('router_time_violation')
                decisions[group][asset].append(dict(entry,known_at=known,entry_at=entry_at,
                    capacity=float(b.v*b.c*.001),state=route.state,state_probability=route.probability,
                    model_known_at=source,entry_model_known_at=entry_source))
                stats[group]['proposed:'+entry['strategy']]+=1
    return decisions,{g:dict(s) for g,s in stats.items()}


def report(result):
    lines=['# 状态概率模型＋传统量化策略路由','',
        '模型接口只返回状态概率；概率阈值负责策略许可，入场、仓位、止盈止损由确定性策略/风控负责。离线研究，未部署。','',
        '## 路由与策略','',
        '|未来状态|策略|','|---|---|']
    for state,strategy in STRATEGIES.items():lines.append(f'|{state}|{strategy or "等待/保护，不开新仓"}|')
    lines+=['','每5期状态预测在有效期内供逐日策略检查使用；默认精确单状态概率≥70%，没有合并看涨/震荡组分数。',
        '状态不确定、预测过期、压缩/过渡/冲击/未知则不授权新入场；达到阈值仍须满足策略自己的形态。',
        '已有仓位按开仓策略原止损/目标/期限退出，不因模型改变而无条件反手；同标的一仓、不叠仓。','',
        '## 相同策略库的固定对照','',
        '|市场/路由|成本倍数|提议/实际交易|净收益|CAGR|收盘MDD|','|---|---:|---|---:|---:|---:|']
    for x in result['runs']:
        s=x['summary'];lines.append(f"|{x['group']}/{x['policy']}|{x['cost_multiplier']}|{x['proposals']}/{s['trades']}|{s['total_return']:+.3%}|{s['cagr']:+.3%}|{s['mdd_close']:.3%}|")
    if result.get('strategy_results'):
        lines+=['','## 按实际开仓策略拆分（基础成本）','',
            '|市场/路由/策略|交易|净盈亏|','|---|---:|---:|']
        for x in result['strategy_results']:
            if x['cost_multiplier']==1:lines.append(f"|{x['group']}/{x['policy']}/{x['strategy']}|{x['trades']}|{x['net_pnl']:.4f}|")
    lines+=['','## 边界','',*['- '+x for x in result['limitations']],'']
    return '\n'.join(lines)


def strategy_results(runs,decisions,trades):
    lookup={(d['policy'],d['asset'],d['known_at']):d for d in decisions};groups={}
    for trade in trades:
        run=runs[trade['run_id']];entry=lookup[run['policy'],trade['asset'],trade['known_at']]
        key=(run['id'],entry['strategy'])
        if key not in groups:groups[key]=dict(group=run['group'],policy=run['policy'],cost_multiplier=run['cost_multiplier'],strategy=entry['strategy'],trades=0,net_pnl=0.)
        groups[key]['trades']+=1;groups[key]['net_pnl']+=trade['net_pnl']
    return list(groups.values())


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if args.output.exists():p.error('preserve old results; choose a new directory')
    parent=load_npz(DAILY);panel=load_npz(PANEL);archive=load_npz(REFERENCE/'phase_predictions.npz')
    markets,_,sources=load_markets();states={g:{a:market_state_machine(b) for a,b in book.items()} for g,book in markets.items()}
    books={}
    for asset in sorted(set(panel['asset'])):
        use=[j for j,k in enumerate(archive['index']) if panel['asset'][k]==asset]
        ix=archive['index'][use];order=np.argsort(panel['known_at'][ix]);ix=ix[order]
        books[str(asset)]=dict(known_at=panel['known_at'][ix],bar_index=parent['bar_index'][panel['original_row'][ix]],probabilities=archive['probabilities'][use][order])
    raw=json.loads(RAW.read_text())['data'];filters=exchange_rules();runs=[];curves={};trades=[];decisions=[];diagnostics=[]
    for policy in ('rules_only','model_argmax','model70'):
        proposed,stats=proposed_entries(markets,states,books,policy)
        diagnostics.append(dict(policy=policy,stats=stats))
        for group,assets in markets.items():
            for a,entries in proposed[group].items():decisions.extend(dict(group=group,asset=a,policy=policy,**d) for d in entries)
            for cost in (1,2):
                sleeves={}
                for a,bars in daily_bars(assets,group).items():
                    rules=(dict(tick=0.,step=1.,min_qty=1.,min_notional=0.) if group=='etf_proxy' else filters[a].copy())
                    rules.update(fee=.0005*cost,slippage=(.0015 if group=='etf_proxy' else .0002)*cost,continuous_clock=group=='crypto')
                    s=replay_asset(bars,proposed[group].get(a,[]),[] if group=='etf_proxy' else raw[a+'_funding'],initial=10000/len(assets),rules=rules)
                    s['start_at']=int(bars[0,0]);sleeves[a]=s
                summary,clocks,nav,tt=summarize_portfolio(sleeves,10000,continuous=True);rid=len(runs)
                runs.append(dict(id=rid,policy=policy,group=group,cost_multiplier=cost,
                    proposals=sum(len(v) for v in proposed[group].values()),summary=summary))
                curves['times_'+str(rid)]=clocks;curves['nav_'+str(rid)]=nav;trades.extend(dict(run_id=rid,**t) for t in tt)
                print(policy,group,cost,'trades',len(tt),'return',round(summary['total_return'],6),flush=True)
    args.output.mkdir(parents=True);pure={};routed=[];snapshots=[];assets=sorted(set(parent['asset']))
    for group,book in markets.items():
        old=joblib.load(REFERENCE/(group+'_model.joblib'))
        bundle=dict(classifier=old['state_model'],assets=assets,feature_names=list(FEATURES),state_names=list(STATE_NAMES[:-1]),
            horizon_observations=5,cutoff=old['cutoff'],unknown_probability_estimated=False,research_only=True,orders_authorized=False)
        path=args.output/(group+'_state_model.joblib');joblib.dump(bundle,path,compress=3)
        snapshots.append(dict(group=group,path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        for asset,bars in book.items():
            ix=np.flatnonzero(parent['asset']==asset);k=int(ix[np.argmax(parent['known_at'][ix])]);b=bars[int(parent['bar_index'][k])]
            probabilities=state_probabilities(bundle['classifier'],state_feature_matrix(parent,[k],assets))[0];pure[asset]=probabilities
            route=route_strategy(probabilities);entry=traditional_entry(route,b,states[group][asset][b.t],allow_short=group=='crypto')
            routed.append(dict(asset=asset,known_at=int(parent['known_at'][k])*1000,model_cutoff=bundle['cutoff'],
                selected_state=route.state,state_probability=route.probability,enabled_strategy=route.strategy,
                route_reason=route.reason,strategy_has_entry_setup=entry is not None,orders_authorized=False))
    result=dict(research_only=True,orders_authorized=False,independent_oos=False,architecture='state_probabilities -> deterministic_router -> traditional_strategy -> risk_execution',
        threshold=.70,runs=runs,diagnostics=diagnostics,model_snapshots=snapshots,sources=sources,
        strategy_results=strategy_results(runs,decisions,trades),
        limitations=['状态分类器复用已训练且已核对的浅树，未为简化接口重复训练；纯模型工件不包含收益头、校准器或策略阈值。',
            '传统策略均为固定研究规则，不因有经济解释就取得盈利资格；本次没有搜索策略参数或概率阈值。',
            '每状态概率条件于11个已知训练状态，unknown没有可信概率；低置信度/预测过期由路由器拒绝。',
            '概率每5期更新，策略逐日检查；开仓前重新验证当时已收到的概率及有效期，不能用后来的预测提前取消历史订单。',
            '币种日线i+2开盘、ETF次会话开盘；初始10,000、等额袖套、最多1%计划风险/1倍名义入场，宽震荡半风险；5+2bp/5+15bp单边摩擦、实际币种资金费及双摩擦压力。',
            '压缩只等待后续突破、过渡/冲击/未知不开新仓；预测切换不自动撤掉旧仓保护或保证立即平仓。',
            '所有历史已消费、15个固定存续标的，ETF为复权现金代理且不做空，旧交易规则非PIT认证，MDD仅收盘，未接实盘。'])
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (args.output/'model_probabilities.json').write_text(json.dumps(pure,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (args.output/'routed_signals.json').write_text(json.dumps(routed,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (args.output/'decisions.json').write_text(json.dumps(decisions,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (args.output/'trades.json').write_text(json.dumps(trades,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    np.savez_compressed(args.output/'equity.npz',**curves);(args.output/'report.md').write_text(report(result))


if __name__=='__main__':main()
