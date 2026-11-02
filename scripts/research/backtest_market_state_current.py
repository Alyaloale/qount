"""Fixed trading mappings of retained current-state forecasts; no fitting."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from qount.research.market_state_dataset import CurrentStateDataset,DEFAULT_ROOT,DAY_MS
from qount.research.market_state_profit import complete_history,execution_schedule,portfolio,replay

MODEL_POLICIES=('model_long_cash','model_long_short','model_probability_signed')
BENCHMARKS=('buy_hold','ma20_60_long_cash')
LABELS=dict(model_long_cash='模型：上行做多／其余现金',model_long_short='模型：上多／下空／震荡现金',
    model_probability_signed='模型：仓位=P上行−P下行',buy_hold='七标的初始等额买持（永续）',ma20_60_long_cash='规则：MA20>MA60做多／否则现金')
FILTERS=Path('state/research_cache/small_account_breakout_v01_20261013/exchange-info.json')


def load(path):
    with np.load(path,allow_pickle=False) as z:return {k:z[k] for k in z.files}


def rules_for(assets):
    data=json.loads(FILTERS.read_text());book={x['symbol']:x for x in data['symbols']};result={}
    for asset in assets:
        filters={x['filterType']:x for x in book[asset]['filters']};lot=filters['MARKET_LOT_SIZE']
        step=float(lot['stepSize']) or float(filters['LOT_SIZE']['stepSize'])
        result[asset]=dict(step=step,min_qty=float(lot['minQty']),max_qty=float(lot['maxQty']),
            min_notional=float(filters['MIN_NOTIONAL']['notional']),tick=float(filters['PRICE_FILTER']['tickSize']))
    return result


def policy_weights(name,p,close,index):
    if name=='buy_hold':return np.ones(len(index))
    if name=='model_long_cash':return (p.argmax(1)==0).astype(float)
    if name=='model_long_short':return np.array([1.,-1.,0.])[p.argmax(1)]
    if name=='model_probability_signed':return p[:,0]-p[:,1]
    if name=='ma20_60_long_cash':
        if np.any(index<59):raise ValueError('profit_ma_warmup_incomplete')
        cumulative=np.r_[0.,np.cumsum(close)]
        fast=(cumulative[index+1]-cumulative[index-19])/20
        slow=(cumulative[index+1]-cumulative[index-59])/60
        return (fast>slow).astype(float)
    raise ValueError('profit_unknown_policy')


def plots(r,curves,out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib import font_manager
    from matplotlib.ticker import PercentFormatter
    font=Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
    if font.exists():
        font_manager.fontManager.addfont(str(font));plt.rcParams['font.family']=font_manager.FontProperties(fname=str(font)).get_name()
    plt.rcParams['axes.unicode_minus']=False
    fig,axes=plt.subplots(2,1,figsize=(15,10),sharex=True,gridspec_kw={'height_ratios':[2.1,1],'hspace':.18})
    fig.subplots_adjust(left=.085,right=.97,top=.87,bottom=.1)
    selected=[x for x in r['runs'] if x['scenario']=='base' and x['seed'] in (None,17)]
    colors=dict(model_long_cash='#D34C44',model_long_short='#8754A8',model_probability_signed='#3978B6',buy_hold='#66747A',ma20_60_long_cash='#188668')
    x=mdates.date2num(curves['open_at'].astype('datetime64[ms]'))
    for run in selected:
        nav=curves[run['id']];normalized=nav/r['initial'];label=LABELS[run['policy']]
        axes[0].plot(x,normalized,label=label,lw=1.5,color=colors[run['policy']])
        sampled=curves['samples_'+run['id']];sample_x=mdates.date2num(curves['sample_at'].astype('datetime64[ms]'))
        axes[1].plot(sample_x,sampled/np.maximum.accumulate(sampled)-1,lw=1.2,color=colors[run['policy']])
    axes[0].set_yscale('log');axes[0].set_ylabel('净值倍数（对数轴）');axes[0].legend(frameon=False,fontsize=10,loc='upper left')
    axes[1].set_ylabel('采样回撤');axes[1].yaxis.set_major_formatter(PercentFormatter(1))
    axes[1].xaxis.set_major_locator(mdates.YearLocator());axes[1].xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    for ax in axes:ax.grid(alpha=.22);ax.spines[['top','right']].set_visible(False)
    fig.suptitle('现有状态模型 · 固定映射的净收益回放',x=.085,ha='left',y=.965,fontsize=18)
    fig.text(.085,.925,f"{r['start'][:10]}—{r['end'][:10]} UTC  |  初始{r['initial']:,.0f} USDT  |  默认种子17  |  手续费5bp＋滑点2bp／单边",fontsize=11)
    fig.text(.085,.034,'资金费按历史费率、日开盘价估算；交易规则使用固定缓存快照。模型信号收盘后1分钟可用，在随后日线开盘执行。',fontsize=10,color='#4C5960')
    fig.text(.085,.012,'回撤按日线开盘／成交后／收盘采样。历史已消费，无新训练或阈值搜索；结果为成本假设下的离线回放。',fontsize=10,color='#4C5960')
    fig.savefig(out/'equity_and_drawdown.png',dpi=165);plt.close(fig)


def write_report(r,out):
    lines=['# 现有市场状态模型：首次收益率回测','',
        f"初始{r['initial']:,.0f} USDT；{r['start']}至{r['end']} UTC，{r['holding_days']}个日线持有区间。7币种初始等额分配独立资金，不跨标的再平衡。",
        '只使用已保存的季度前推预测，不重新训练、不使用实际标签定仓，也不搜索策略参数。主表为当前默认种子17，其他种子完整保留。','',
        '## 仓位与成交','',
        '三条固定模型映射：上行做多其余现金；上行做多下行做空震荡现金；仓位=P上行−P下行。模型策略每日再平衡，开盘目标名义额最多为子账户权益1倍。',
        '基线为相同合约的固定初始数量买入持有，以及MA20>MA60做多否则现金。现金收益假设0。n=14是状态参考尺度，不强制持有14天；独立早期阶段概率未用于本轮仓位。',
        '信号在原日线收盘后1分钟可用。因只有日线执行价格，在此后第一个日线开盘执行：原K线k的信号在k+2日开盘成交，约等待23小时59分。不把k+1日开盘误作可成交时点。',
        '基准费用：单边手续费5bp、滑点2bp，另加不利tick取整；数量按市场手数取整，遵守最低数量/名义额，减仓按reduce-only近似。规则是2026-10-13缓存快照，不是历史时点完整规则。',
        '使用实际资金费率事件；结算标记价缺失，不补入模型或数据集，回测按当日开盘价估算名义额。开盘一分钟内的结算基准先归旧持仓，压力情景取旧/新持仓较不利支付，日内支付按高/低价取不利情景。',
        '仅1%维持保证金压力检查；若日内不利价格与资金费下触线，保守记为子账户破产，不冒充精确强平模型。最大回撤为日线开盘/成交后/收盘采样，非分钟级真实最大回撤。',
        '已检查调仓名义额低于已知前日及实际执行日成交额的0.1%。这只约束回放容量，不替代真实盘口滑点。','',
        '## 基准成本结果（种子17）','',
        '| 策略 | 终值USDT | 总收益 | 净CAGR | 日线采样MDD | Calmar | 平均总敞口 | 调仓订单 |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for run in r['runs']:
        if run['scenario']!='base' or run['seed'] not in (None,17):continue
        v=run['summary'];calmar=f"{v['calmar']:.2f}" if v['calmar'] is not None else '—'
        lines.append(f"| {LABELS[run['policy']]} | {v['final_equity']:,.2f} | {v['total_return']:+.2%} | {v['cagr']:+.2%} | {v['mdd_daily_sampled']:.2%} | {calmar} | {v['average_gross_exposure']:.2%} | {v['orders']} |")
    lines += ['', '## 成本及资金费压力','', '| 策略 | 情景 | CAGR | MDD | 手续费USDT | 滑点/取整USDT | 资金费净收支USDT |','|---|---|---:|---:|---:|---:|---:|']
    for run in r['runs']:
        if run['seed'] not in (None,17):continue
        v=run['summary'];c=v['components']
        lines.append(f"| {LABELS[run['policy']]} | {run['scenario']} | {v['cagr']:+.2%} | {v['mdd_daily_sampled']:.2%} | {c['fees']:.2f} | {c['slippage_and_rounding']:.2f} | {c['funding_pnl']:+.2f} |")
    lines += ['', 'base=5bp手续费+2bp滑点；double_cost=10bp+4bp；adverse_funding=基准摩擦、不利资金费价格与结算顺序。各情景独立重放仓位和成本，不能视为简单静态扣费。','',
        '## 模型种子复核','', '| 策略 | 种子 | CAGR | MDD | Calmar |','|---|---:|---:|---:|---:|']
    for run in r['runs']:
        if run['scenario']!='base' or run['seed'] is None:continue
        v=run['summary'];calmar=f"{v['calmar']:.2f}" if v['calmar'] is not None else '—'
        lines.append(f"| {LABELS[run['policy']]} | {run['seed']} | {v['cagr']:+.2%} | {v['mdd_daily_sampled']:.2%} | {calmar} |")
    lines += ['', '## 逐年净收益（2023和2026为不完整年度）','', '| 策略 | 2023 | 2024 | 2025 | 2026至结束 |','|---|---:|---:|---:|---:|']
    for run in r['runs']:
        if run['scenario']!='base' or run['seed'] not in (None,17):continue
        y=run['summary']['yearly_returns'];lines.append('| '+LABELS[run['policy']]+' | '+' | '.join(f"{y[k]:+.2%}" if k in y else '—' for k in ('2023','2024','2025','2026'))+' |')
    lines += ['', '## 每标的净收益（种子17，基准成本）','', '| 标的 | 模型多/现 | 模型多/空/现 | 概率仓位 | 买持 | MA20/60 |','|---|---:|---:|---:|---:|---:|']
    selected={run['policy']:run for run in r['runs'] if run['scenario']=='base' and run['seed'] in (None,17)}
    for asset in r['assets']:
        lines.append('| '+asset+' | '+' | '.join(f"{selected[name]['per_asset'][asset]['total_return']:+.2%}" for name in MODEL_POLICIES+BENCHMARKS)+' |')
    long=selected['model_long_cash'];initial_asset=r['initial']/len(r['assets'])
    contributions={a:v['final_equity']-initial_asset for a,v in long['per_asset'].items()};largest=max(contributions,key=contributions.get)
    other_initial=r['initial']-initial_asset
    other_final=sum(v['final_equity'] for a,v in long['per_asset'].items() if a!=largest)
    net=long['summary']['final_equity']-r['initial']
    share=contributions[largest]/net if net else 0
    lines += ['', '## 收益集中度与仓位','',
        f"模型多/现金的最大收益来源为{largest}，贡献{contributions[largest]:,.2f} USDT，占组合净利润{share:.2%}。其余原资金子账户合计收益{other_final/other_initial-1:+.2%}；这是收益来源诊断，不是事后删赢家再优化策略。",
        f"模型多/现金平均总敞口{long['summary']['average_gross_exposure']:.2%}，均线基线{selected['ma20_60_long_cash']['summary']['average_gross_exposure']:.2%}。低回撤伴随较低仓位，不能单独据此认定模型择时更优。"]
    lines += ['', '![净值及回撤](equity_and_drawdown.png)','',
        '限制：模型选择历史已消费、只有7个当前保留标的、非全市场无幸存者偏差测试；日线延迟执行与真实00:01成交不同。资金费标价和历史交易规则近似，会限制净收益精度。没有实盘订单。',
        '官方参考：[资金费机制](https://www.binance.com/en/support/faq/detail/360033525031)、[资金费历史字段](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)、[订单错误/最小名义额](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/error-code)。',
        '完整每次回放、逐标的风险与成本见results.json；全部净值见equity_curves.npz；逐笔调仓见orders.json。']
    (out/'report.md').write_text('\n'.join(lines)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--dataset',type=Path,default=DEFAULT_ROOT)
    parser.add_argument('--run',type=Path,default=Path('state/research_runs/market_state_transition_default_20261101'))
    parser.add_argument('--comparison',type=Path,default=Path('state/research_runs/market_state_transition_repair_20261101'))
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--initial',type=float,default=10000)
    parser.add_argument('--plot',action='store_true');args=parser.parse_args()
    if args.output.exists():parser.error('preserve existing runs')
    if args.initial<=0:parser.error('positive initial capital required')
    ds=CurrentStateDataset(args.dataset);d=ds.data;current=load(args.run/'predictions.npz');saved=load(args.comparison/'predictions.npz')
    if bool(current['smoke_only']):raise ValueError('profit_smoke_predictions_disallowed')
    np.testing.assert_array_equal(current['source_row'],d['source_row']);np.testing.assert_array_equal(saved['source_row'],d['source_row'])
    probabilities=saved['probabilities'][:,0];seeds=saved['seeds'].tolist()
    np.testing.assert_allclose(current['probabilities'],probabilities[seeds.index(17)],atol=2e-7,rtol=0,equal_nan=True)
    valid=np.isfinite(probabilities).all((0,2));clocks=None;contexts={};history=complete_history(ds);rules=rules_for(ds.asset_names)
    funding=load(args.dataset/'funding_events.npz')
    for asset in ds.asset_names:
        rows=np.flatnonzero((d['asset']==asset)&valid);fill=execution_schedule(d['decision_at'][rows],d['bar_open_at'][rows])
        if clocks is None:clocks=np.r_[fill,fill[-1]+DAY_MS]
        np.testing.assert_array_equal(clocks,np.r_[fill,fill[-1]+DAY_MS])
        book=history[asset];index=np.searchsorted(book['open_at'],clocks)
        np.testing.assert_array_equal(book['open_at'][index],clocks)
        signal=np.searchsorted(book['open_at'],d['bar_open_at'][rows]);np.testing.assert_array_equal(book['open_at'][signal],d['bar_open_at'][rows])
        chosen=funding['asset']==asset
        if not chosen.any():raise ValueError('profit_missing_funding_asset')
        contexts[asset]=dict(rows=rows,market=book['market'][index],known=d['decision_at'][rows],
            known_quote=d['market'][rows,5],full_close=book['market'][:,3],signal_index=signal,
            funding_time=funding['observed_at'][chosen],funding_rate=funding['rate'][chosen])
    source_hash=hashlib.sha256((args.dataset/'dataset.npz').read_bytes()).hexdigest()
    prior=json.loads((args.comparison/'results.json').read_text())
    if prior['dataset_sha256']!=source_hash:raise ValueError('profit_forecast_dataset_hash_mismatch')
    current_info=json.loads((args.run/'results.json').read_text())
    for fit in current_info['folds']:
        if fit['latest_training_label']>=fit['cutoff']:raise ValueError('profit_forecast_training_maturity')
    args.output.mkdir(parents=True);runs=[];orders=[]
    sampled_clock=np.r_[np.column_stack((clocks[:-1],clocks[:-1]+1,clocks[1:]-1)).reshape(-1),clocks[-1],clocks[-1]+1]
    curves=dict(open_at=clocks,sample_at=sampled_clock)
    for scenario,multiplier,adverse in (('base',1.,False),('double_cost',2.,False),('adverse_funding',1.,True)):
        cases=[(name,i,seed) for name in MODEL_POLICIES for i,seed in enumerate(seeds)]+[(name,0,None) for name in BENCHMARKS]
        for policy,i,seed in cases:
            sleeves={}
            for asset,c in contexts.items():
                weight=policy_weights(policy,probabilities[i,c['rows']],c['full_close'],c['signal_index'])
                rule=dict(rules[asset],fee=.0005*multiplier,slippage=.0002*multiplier)
                sleeves[asset]=replay(c['market'],clocks,weight,c['known'],c['known_quote'],c['funding_time'],c['funding_rate'],
                    initial=args.initial/len(ds.asset_names),rules=rule,fixed_quantity=policy=='buy_hold',adverse_funding=adverse)
            summary,nav=portfolio(sleeves,clocks,args.initial)
            run_id=f'{policy}_seed{seed}_{scenario}';curves[run_id]=nav
            curves['samples_'+run_id]=np.sum([s['samples'] for s in sleeves.values()],axis=0)
            if len(curves['samples_'+run_id])!=len(sampled_clock):raise ValueError('profit_sampled_curve_clock')
            per_asset={a:portfolio({a:s},clocks,args.initial/len(ds.asset_names))[0] for a,s in sleeves.items()}
            runs.append(dict(id=run_id,policy=policy,seed=seed,scenario=scenario,summary=summary,per_asset=per_asset))
            for asset,s in sleeves.items():orders.extend(dict(run=run_id,asset=asset,**order) for order in s['orders'])
            print(run_id,'CAGR',round(summary['cagr']*100,2),'MDD',round(summary['mdd_daily_sampled']*100,2),flush=True)
    assert source_hash==hashlib.sha256((args.dataset/'dataset.npz').read_bytes()).hexdigest()
    result=dict(research_only=True,orders_authorized=False,independent_oos=False,models_retrained=False,threshold_search=False,
        initial=args.initial,assets=ds.asset_names,start=str(clocks[0].astype('datetime64[ms]')),end=str(clocks[-1].astype('datetime64[ms]')),
        holding_days=len(clocks)-1,signal_rows=int(valid.sum()),dataset=str(args.dataset),dataset_sha256=source_hash,
        forecast_source=str(args.run),comparison_source=str(args.comparison),execution_delay_hours=float((clocks[0]-contexts[ds.asset_names[0]]['known'][0])/3600000),
        rules_snapshot=str(FILTERS),funding_mark_proxy='daily open; adverse scenario daily high/low and settlement-window minimum',
        base_fee=.0005,base_slippage=.0002,maintenance_margin_stress=.01,stage_probabilities_used=False,runs=runs)
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (args.output/'orders.json').write_text(json.dumps(orders,ensure_ascii=False,separators=(',',':'))+'\n')
    np.savez_compressed(args.output/'equity_curves.npz',**curves)
    if args.plot:plots(result,curves,args.output)
    write_report(result,args.output)


if __name__=='__main__':main()
