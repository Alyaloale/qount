"""Falsify profitability of retained market probability models, offline only.

Fixed policies, no training/search: range midpoint reversion with boundary stop;
direction argmax with 2 ATR stop and five-bar expiry. Compare equal-risk rules,
geometry and learned probability gates on the same forecast opportunity pool.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np

from qount.research.market_model_profit import replay_asset,summarize_portfolio
from qount.research.market_path_risk import load_path_sources,HOUR_MS
from qount.research.market_stages import market_state_machine
from qount.research_data.bars import NY
from study_binance_market_states import load_markets


ROOT=Path('state/research_runs')
DAILY=ROOT/'market_feature_enrichment_20261030_final/dataset.npz'
PROB=ROOT/'market_probability_optimization_20261030'
RANGE=ROOT/'market_range_robustness_20261030'
PATH=ROOT/'market_path_risk_20261031_supported'
RAW=Path('state/research_cache/independent_crypto_factors_20261027/panel_seven.json')
FILTERS=Path('state/research_cache/small_account_breakout_v01_20261013/exchange-info.json')


def load_npz(path):
    with np.load(path,allow_pickle=False) as z:return {k:z[k] for k in z.files}


def forecasts(folder,name):
    z=load_npz(folder/'predictions.npz');mask=z['run_id']==list(z['run_names']).index(name)
    indices=z['row_index'][mask];p=z['probabilities'][mask]
    if len(set(indices))!=len(indices):raise ValueError('profit_duplicate_forecast')
    return {int(i):row for i,row in zip(indices,p)}


def gate(p,policy):
    if policy=='all':return 1.
    if policy=='quarter':return .25
    if policy=='p80':return float(p>=.8)
    if policy=='tiers':return 1. if p>=.8 else .5 if p>=.65 else .25 if p>=.5 else 0.
    raise ValueError('profit_unknown_gate')


def exchange_rules():
    j=json.loads(FILTERS.read_text());out={}
    for s in j['symbols']:
        f={r['filterType']:r for r in s['filters']}
        if 'MARKET_LOT_SIZE' not in f:continue
        lot=f['MARKET_LOT_SIZE'];step=float(lot['stepSize'])
        out[s['symbol']]=dict(tick=float(f['PRICE_FILTER']['tickSize']),step=step if step else float(f['LOT_SIZE']['stepSize']),
            min_qty=float(lot['minQty']),max_qty=float(lot['maxQty']),min_notional=float(f['MIN_NOTIONAL']['notional']))
    return out


def daily_bars(book,group):
    result={}
    for asset,bars in book.items():
        values=[]
        for b in bars:
            if group=='crypto':start=(b.t+1-86400)*1000
            else:
                day=dt.datetime.fromtimestamp(b.t,NY).date()
                start=int(dt.datetime.combine(day,dt.time(9,30),NY).timestamp())*1000
            if start<1672531200000:continue
            values.append([start,b.o,b.h,b.l,b.c,b.v,b.t*1000+999])
        result[asset]=np.array(values,float)
    return result


def daily_decisions(data,markets,states,group,task,model,policy):
    if task=='range':
        ps=forecasts(RANGE,group+'/'+model);gs=forecasts(RANGE,group+'/anchor')
    else:
        ps=forecasts(PROB,group+'/direction5/'+model);gs=forecasts(PROB,group+'/direction5/anchor')
    if set(ps)!=set(gs):raise ValueError('profit_forecast_pool_mismatch')
    output=defaultdict(list);skips=defaultdict(int)
    for k in sorted(ps,key=lambda k:(data['known_at'][k],str(data['asset'][k]))):
        asset=str(data['asset'][k]);i=int(data['bar_index'][k]);b=markets[group][asset][i];r=states[group][asset][b.t]
        entry_index=i+(2 if group=='crypto' else 1)
        if entry_index>=len(markets[group][asset]):skips['entry_after_data_end']+=1;continue
        eb=markets[group][asset][entry_index]
        if group=='crypto':entry=(eb.t+1-86400)*1000
        else:
            day=dt.datetime.fromtimestamp(eb.t,NY).date();entry=int(dt.datetime.combine(day,dt.time(9,30),NY).timestamp())*1000
        known=int(data['known_at'][k])*1000
        if known>=entry:raise ValueError('profit_daily_fill_clock')
        if task=='range':
            lower=r['previous_low20'];upper=r['previous_high20'];mid=(lower+upper)/2
            side=1 if b.c<mid else -1;stop=lower if side>0 else upper;target=mid
            fraction=gate(float(ps[k][1]),policy)
        else:
            cls=int(np.argmax(ps[k][:3]));side=cls-1
            if model=='anchor' and policy=='trend':side=1 if r['ema20']>r['ema50'] else -1
            if not side:skips['neutral_direction']+=1;continue
            if policy=='matched_long':side=1
            if policy=='matched_trend':side=1 if r['ema20']>r['ema50'] else -1
            if r['action_state'] in ('shock','unknown'):skips['protective_state']+=1;continue
            stop=b.c-side*2*r['atr14'];target=None;fraction=1.
        if group=='etf_proxy' and side<0:skips['cash_etf_short_disallowed']+=1;continue
        # A past-volume cap, never the future entry candle's realized volume.
        capacity=float(b.v*b.c*.001)
        output[asset].append(dict(known_at=known,entry_at=entry,side=side,stop=stop,target=target,
            fraction=fraction,max_bars=5,capacity=capacity,original_row=k))
    return output,dict(skips),len(ps)


def path_decisions(panel,ps,hours,policy):
    output=defaultdict(list);skips=defaultdict(int)
    for k in sorted(ps,key=lambda k:(panel['known_at'][k],str(panel['asset'][k]))):
        asset=str(panel['asset'][k]);known=int(panel['known_at'][k])*1000;entry=int(panel['scheduled_start'][k])*1000
        # This known last close is reconstructed from prior-day geometry.
        original=int(panel['original_row'][k]);i=int(PARENT['bar_index'][original]);b=MARKETS['crypto'][asset][i]
        low=float(panel['lower'][k]);high=float(panel['upper'][k]);mid=(low+high)/2;side=1 if b.c<mid else -1
        prior=(known//HOUR_MS-1)*HOUR_MS
        if prior not in hours[asset]:skips['missing_known_capacity_bar']+=1;continue
        if int(hours[asset][prior][6])+60001>known:raise ValueError('profit_capacity_clock')
        capacity=float(hours[asset][prior][7])*.001
        output[asset].append(dict(known_at=known,entry_at=entry,side=side,stop=low if side>0 else high,
            target=mid,fraction=gate(float(ps[k][1]),policy),max_bars=120,capacity=capacity,original_row=original))
    return output,dict(skips),len(ps)


def quarter_net_interval(trades):
    # Trade PnL is compounded-size dependent. This is only a diagnostic mean
    # per traded notional, not a confidence interval for portfolio CAGR.
    groups=defaultdict(list)
    for t in trades:
        d=dt.datetime.fromtimestamp(t['entry_at']/1000,dt.timezone.utc)
        groups[d.year,(d.month-1)//3].append(t['net_pnl']/(t['quantity']*t['entry']))
    if len(groups)<4:return dict(quarter_clusters=len(groups),interval95=None)
    sums=np.array([sum(v) for v in groups.values()]);counts=np.array([len(v) for v in groups.values()])
    draws=np.random.default_rng(311026).integers(0,len(sums),(3000,len(sums)))
    return dict(quarter_clusters=len(groups),mean=float(sums.sum()/counts.sum()),
        interval95=np.quantile(sums[draws].sum(1)/counts[draws].sum(1),[.025,.975]).tolist())


def analyze_runs(result,curves,trades):
    diagnostics=[]
    for r in result['runs']:
        chosen=[t for t in trades if t['run_id']==r['id']];s=r['summary'];c=s['components']
        # Freeze original entries/quantities and double all measured friction.
        # This is arithmetic stress on the same trades, not a rebalanced NAV.
        fixed_stress=(c['gross_pnl']-2*(c['fees']+c['slippage_and_rounding'])+c['funding'])/r['capital']
        wins=[t['net_pnl'] for t in chosen if t['net_pnl']>0];losses=[-t['net_pnl'] for t in chosen if t['net_pnl']<0]
        diagnostics.append(dict(run_id=r['id'],fixed_path_double_friction_pnl_over_initial=fixed_stress,
            mean_winner=float(np.mean(wins)) if wins else None,mean_loser=float(np.mean(losses)) if losses else None,
            net_pnl_excluding_top5_static=c['net_pnl']-sum(sorted(wins,reverse=True)[:5]),
            reasons=dict((k,sum(t['reason']==k for t in chosen)) for k in sorted({t['reason'] for t in chosen}))))
    def find(suite,model,policy):
        return next(r for r in result['runs'] if r['suite']==suite and r['model']==model and r['policy']==policy
                    and r['capital']==10000 and r['cost_multiplier']==1)
    comparisons=[]
    pairs=[(('crypto_daily_direction','compact_tree','argmax'),('crypto_daily_direction','compact_tree','matched_long')),
           (('crypto_daily_direction','compact_tree','argmax'),('crypto_daily_direction','compact_tree','matched_trend')),
           (('crypto_daily_range','vol_only','p80'),('crypto_daily_range','anchor','p80')),
           (('crypto_hourly_path','intercept_offset','tiers'),('crypto_hourly_path','geometry','tiers')),
           (('crypto_hourly_path','intercept_offset','tiers'),('crypto_hourly_path','geometry','quarter'))]
    for left,right in pairs:
        try:a,b=find(*left),find(*right)
        except StopIteration:continue
        ca,cb=curves['times_'+str(a['id'])],curves['times_'+str(b['id'])]
        if not np.array_equal(ca,cb):raise ValueError('profit_comparison_calendar')
        returns=[np.diff(np.log(np.r_[10000.,curves['nav_'+str(r['id'])]])) for r in (a,b)]
        groups=defaultdict(float)
        for stamp,v in zip(ca,returns[0]-returns[1]):
            d=dt.datetime.fromtimestamp(int(stamp)/1000,dt.timezone.utc);groups[d.year,(d.month-1)//3]+=float(v)
        values=np.array(list(groups.values()));ci=None
        if len(values)>=4:
            draws=np.random.default_rng(311026).integers(0,len(values),(3000,len(values)))
            ci=np.quantile(values[draws].mean(1),[.025,.975]).tolist()
        comparisons.append(dict(left_run=a['id'],right_run=b['id'],quarter_clusters=len(values),
            mean_quarter_log_excess=float(np.mean(values)),interval95=ci,
            total_return_difference=a['summary']['total_return']-b['summary']['total_return']))
    return dict(trade_payoffs=diagnostics,paired_portfolio_quarters=comparisons,
        note='Quarter block intervals are exploratory, unadjusted for multiple comparisons; fewer than four quarters gives no interval. Static trade deletions/stress are not executable reruns.')


def report(result):
    lines=['# 市场模型盈利能力：固定规则与净收益反证','',
        '离线探索，历史已消费；没有实盘订单。模型预测准确率不能直接解释为交易胜率。','',
        '## 设定','',*['- '+s for s in result['assumptions']],'',
        '|市场/规则|模型/门槛|资金|成本倍数|交易|累计净收益|CAGR|收盘MDD|Calmar|胜率|',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    def pct(v):return '—' if v is None else f'{v:.2%}'
    for r in result['runs']:
        s=r['summary'];lines.append(f"|{r['suite']}|{r['model']}/{r['policy']}|{r['capital']:.4f}|{r['cost_multiplier']}|{s['trades']}|{pct(s['total_return'])}|{pct(s['cagr'])}|{pct(s['mdd_close'])}|{s['calmar'] if s['calmar'] is not None else '—'}|{pct(s['win_rate'])}|")
    lines+=['','## 年度与成本归因','',
        '|市场/模型/门槛/资金/成本倍数|年度收益|价格毛盈亏|佣金|滑点及取整|资金费净额|',
        '|---|---|---:|---:|---:|---:|']
    for r in result['runs']:
        s=r['summary'];c=s['components'];years=', '.join(f'{y}:{v:+.2%}' for y,v in s['yearly_returns'].items())
        lines.append(f"|{r['suite']}/{r['model']}/{r['policy']}/{r['capital']:.4f}/{r['cost_multiplier']}|{years}|{c['gross_pnl']:.4f}|{c['fees']:.4f}|{c['slippage_and_rounding']:.4f}|{c['funding']:.4f}|")
    lines+=['','## 限制','',*['- '+s for s in result['limitations']],'',
        '资金费按[Binance资金费说明](https://www.binance.com/en/support/faq/detail/360033525031)的持仓结算机制；',
        '佣金采用明确假设，非账户费率认证，参见[官方计算口径](https://www.binance.com/en/support/faq/detail/360033544231)。','']
    if 'diagnostics' in result:
        lines+=['## 同路径摩擦压力与配对增量','',
            '两倍成本主表会重新计算数量/准入；下表另冻结原交易时点与数量，只把测得佣金和滑点取整成本翻倍，是静态损益/本金，不是新净值曲线或CAGR。','',
            '|基础成本run|同路径双摩擦损益/本金|平均盈利/平均亏损（货币）|静态去最大五笔盈利后净额|',
            '|---:|---:|---|---:|']
        for d in result['diagnostics']['trade_payoffs']:
            r=result['runs'][d['run_id']]
            if r['cost_multiplier']!=1 or r['capital']!=10000:continue
            lines.append(f"|{d['run_id']}|{d['fixed_path_double_friction_pnl_over_initial']:.3%}|{d['mean_winner']} / {d['mean_loser']}|{d['net_pnl_excluding_top5_static']:.4f}|")
        lines+=['','|左run−右run|累计收益差|季度数|平均季度对数增量/95%区间|','|---|---:|---:|---|']
        for c in result['diagnostics']['paired_portfolio_quarters']:
            lines.append(f"|{c['left_run']}−{c['right_run']}|{c['total_return_difference']:+.3%}|{c['quarter_clusters']}|{c['mean_quarter_log_excess']} / {c['interval95']}|")
        lines+=['',result['diagnostics']['note'],'']
    return '\n'.join(lines)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--controls-only',action='store_true');p.add_argument('--include-controls',action='store_true');args=p.parse_args()
    if args.controls_only and args.include_controls:p.error('choose controls-only or include-controls')
    if args.output.exists():p.error('preserve prior results; choose new directory')
    global PARENT,MARKETS
    PARENT=load_npz(DAILY);MARKETS,_,daily_sources=load_markets()
    states={g:{a:market_state_machine(b) for a,b in book.items()} for g,book in MARKETS.items()}
    raw=json.loads(RAW.read_text())['data'];filters=exchange_rules()
    hours,_,hour_sources=load_path_sources('state/research_cache/position_flow_20261027','state/research_cache/small_account_breakout_v01_20261013')
    panel=load_npz(PATH/'path_dataset.npz');path_prob={m:forecasts(PATH,'scheduled_path5/'+m) for m in ('geometry','intercept_offset')}
    if set(path_prob['geometry'])!=set(path_prob['intercept_offset']):raise ValueError('profit_path_pool_mismatch')
    specs=[]
    # Fixed ablations, no parameter selection after inspecting PnL.
    for group in ('crypto','etf_proxy'):
        bars=daily_bars(MARKETS[group],group)
        for model,policy in [('anchor','all'),('anchor','p80'),('vol_only','p80'),('anchor','tiers'),('vol_only','tiers')]:
            ds,skips,pool=daily_decisions(PARENT,MARKETS,states,group,'range',model,policy)
            specs.append((group+'_daily_range',model,policy,bars,ds,skips,pool,True))
        models=['anchor','compact_tree','compact_tree_shrunk'] if group=='crypto' else ['anchor','strong_tree','mlp_cached_shrunk']
        for model,policy in [('anchor','trend')]+[(m,'argmax') for m in models]:
            ds,skips,pool=daily_decisions(PARENT,MARKETS,states,group,'direction',model,policy)
            specs.append((group+'_daily_direction',model,policy,bars,ds,skips,pool,True))
        if group=='crypto':
            for policy in ('matched_long','matched_trend'):
                ds,skips,pool=daily_decisions(PARENT,MARKETS,states,group,'direction','compact_tree',policy)
                specs.append((group+'_daily_direction','compact_tree',policy,bars,ds,skips,pool,True))
    first=min(int(panel['scheduled_start'][k])*1000 for k in path_prob['geometry'])
    hourly={a:np.stack([r for t,r in sorted(book.items()) if t>=first]) for a,book in hours.items()}
    for model,policy in [('geometry','all'),('geometry','p80'),('intercept_offset','p80'),('geometry','tiers'),('intercept_offset','tiers'),('geometry','quarter')]:
        ds,skips,pool=path_decisions(panel,path_prob[model],hours,policy)
        specs.append(('crypto_hourly_path',model,policy,hourly,ds,skips,pool,False))
    for model,policy in [('geometry','all'),('intercept_offset','p80'),('intercept_offset','tiers')]:
        ds,skips,pool=path_decisions(panel,path_prob[model],hours,policy)
        specs.append(('crypto_hourly_sol_size',model,policy,{'SOLUSDT':hourly['SOLUSDT']},
                      {'SOLUSDT':ds['SOLUSDT']},skips,pool,False))
    if not args.include_controls:
        specs=[s for s in specs if ((s[2] in ('matched_long','matched_trend','quarter') or s[0]=='crypto_hourly_sol_size')==args.controls_only)]
    runs=[];curves={};all_trades=[]
    for suite,model,policy,bars,ds,skips,pool,continuous in specs:
        capitals=[15.27112826] if suite=='crypto_hourly_sol_size' else [10000.,15.27112826] if suite=='crypto_hourly_path' else [10000.]
        for capital in capitals:
            for multiplier in (1,2):
                sleeves={};is_etf=suite.startswith('etf')
                for asset,values in bars.items():
                    rules=(dict(tick=0.,step=1.,min_qty=1.,min_notional=0.) if is_etf else filters[asset].copy())
                    rules.update(fee=.0005*multiplier,slippage=(.0015 if is_etf else .0002)*multiplier,
                                 continuous_clock=not is_etf)
                    funding=[] if is_etf else raw[asset+'_funding']
                    s=replay_asset(values,ds.get(asset,[]),funding,initial=capital/len(bars),rules=rules)
                    s['start_at']=int(values[0,0]);sleeves[asset]=s
                summary,clocks,nav,trades=summarize_portfolio(sleeves,capital,continuous=continuous)
                if summary['max_entry_notional']>1+1e-9:raise ValueError('profit_entry_leverage')
                summary['trade_return_cluster_diagnostic']=quarter_net_interval(trades)
                rid=len(runs);runs.append(dict(id=rid,suite=suite,model=model,policy=policy,capital=capital,
                    cost_multiplier=multiplier,opportunity_pool=pool,signal_skips=skips,
                    first_bar_at=int(next(iter(bars.values()))[0,0]),last_bar_at=int(clocks[-1]),summary=summary))
                curves[f'times_{rid}']=clocks;curves[f'nav_{rid}']=nav
                all_trades.extend(dict(run_id=rid,**t) for t in trades)
                print(rid,suite,model,policy,capital,multiplier,'trades',len(trades),'return',round(summary['total_return'],6),flush=True)
    sources=daily_sources+hour_sources+[dict(path=str(x),sha256=hashlib.sha256(x.read_bytes()).hexdigest()) for x in
        [DAILY,FILTERS,PATH/'predictions.npz',PATH/'path_dataset.npz',PROB/'predictions.npz',RANGE/'predictions.npz']]
    result=dict(research_only=True,orders_authorized=False,independent_oos=False,controls_only=args.controls_only,include_controls=args.include_controls,runs=runs,sources=sources,
        assumptions=[
            '模型不重训，沿用逐季成熟标签训练后的保存预测；固定0.8门槛及0.5/0.65/0.8对应0.25/0.5/1风险倍数，不搜索最优阈值。',
            '区间规则：按已知收盘位于20期固定区间中点的哪侧选方向，目标中点，止损另一侧边界，最多持有5期；方向规则：argmax选跌/中性/涨，中性空仓，止损距信号价2ATR、最多5期，冲击/未知不入场。',
            '币种日线决策后等到下一天00:00（信号bar i+2）；ETF次交易日09:30开盘。小时路径用scheduled_path5预测，在决策后59分钟的01:00入场，最多120小时。不同成交延迟均明确改变收益目标。',
            '每标的固定分配等额独立资金袖套，单次计划止损风险最多袖套1%，入场名义不超过袖套1倍，持有中不叠仓；资金只在该袖套内复利，不事后挪用其他袖套。',
            '币种允许多空；ETF代理仅现金做多，整数股，不假造历史融券或Binance资金费。现金收益0。区间目标收益须覆盖四次假定往返摩擦，否则不入场。',
            '币种单边手续费5bp、滑点/价差/冲击合计2bp；ETF代理5bp＋15bp，另完整重跑两倍摩擦。资金费按实际事件和结算标记收付，缺标记以当根开盘近似并计数。',
            '币种市场单数量/价格按保留2026交易规则取整（非历史PIT认证）；已知前一日量或前一小时成交额0.1%作为容量上限，不使用未来成交量。',
            '同根同时触及止损/目标，止损优先；跳空越过止损按更差开盘，再扣滑点。无法定位的退出根内资金费只收可能借项、不取可能贷项。',
            '基准含现金0、相同机会/相同风险的不使用模型规则与几何概率筛选；逐年及所有失败结果均保留。小时缓存不连续，空白期间袖套空仓，不对该样本计算CAGR。'],
        limitations=[
            '这检验固定交易规则与模型筛选增量，不能单凭一次失败否定所有交易方式，也不能从已反复消费历史认证独立样本外盈利。',
            '小时只有BTC/ETH/SOL的选择性缓存时段，预测329行且重叠，实际交易按持仓去重；来源覆盖筛选不能视为随机市场样本。',
            '日线预测每5期采样，延迟入场和止损目标与原分类标签不同；ETF复权OHLC是研究代理，非可复现的Binance合约成交/分红现金账本。',
            '保留2026交易规则未验证历史变更、账户真实费率、盘口或成交概率；止损按交易价OHLC近似，未模拟标记价清算/ADL/交易所故障。1x入场不代表持有期间名义比例恒定1x。',
            'MDD仅为日/小时收盘采样，不能证明真实同步盘中最大回撤；CAGR仅完整日线研究账本计算。',
            '门槛或风险倍数是实验规则，不是已获授权仓位。资金15.27112826仅做离线规模敏感性，未访问账户或私有API。'])
    if args.controls_only or args.include_controls:
        result['assumptions'] += [
            '补充对照不选参数：matched_long/matched_trend沿用原始8特征树非中性信号日期，替换为恒做多/EMA方向；各自按同1%止损预算重新执行，成交与止损路径可能不同。',
            'quarter为不看概率、固定0.25风险倍数的区间规则，用于区分筛选与机械减仓。SOL-only把15.27112826全部分给唯一最低订单额可满足的SOL，检查三等分是否人为阻断小资金，不据收益选币。']
    if args.include_controls:
        result['limitations'].append('初轮与补充工件保留，当前合并复核版删除了定义不充分的盘中回撤界，只报告收盘MDD；不是新增独立实验样本。')
    result['diagnostics']=analyze_runs(result,curves,all_trades)
    args.output.mkdir(parents=True);(args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    (args.output/'trades.json').write_text(json.dumps(all_trades,ensure_ascii=False,indent=2)+'\n')
    np.savez_compressed(args.output/'equity.npz',**curves);(args.output/'report.md').write_text(report(result))


if __name__=='__main__':main()
