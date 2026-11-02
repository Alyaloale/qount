"""Daily OHLCV + bounded, recency-weighted state at each trading scale."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

from qount.research.market_daily_states import LOCAL_STATES, centered_daily_state, local_daily_state, state_chunks, summarize_state_probabilities
from qount.research.market_learning import fit_candidate
from qount.research.market_trading_horizons import HORIZONS, known_at
from study_binance_market_states import load_markets


def scores(y,p):
    pred=p.argmax(1)
    return dict(rows=len(y),accuracy=float(np.mean(pred==y)),
        balanced_accuracy=float(np.mean([np.mean(pred[y==c]==c) for c in np.unique(y)])),
        brier=float(np.mean(np.sum((p-np.eye(len(LOCAL_STATES))[y])**2,axis=1))))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--pilot',action='store_true')
    p.add_argument('--past-only',action='store_true',help='historical past-only contrast; default labels may inspect future n days')
    args=p.parse_args()
    centered=not args.past_only
    if args.output.exists():p.error('preserve old output; choose another directory')
    markets,_,sources=load_markets();records=[];lookup={}
    for g,book in markets.items():
        for a,bars in sorted(book.items()):
            for k,b in enumerate(bars):
                lookup[g,a,k]=len(records)
                records.append((g,a,k,b))
    count=len(records);scales=('3days','1week','2weeks','1month')
    state=np.full((count,4),-1,np.int16);target=state.copy()
    causal_state=state.copy();label_available=np.zeros((count,4),np.int64)
    horizon=np.zeros((count,4),np.int16);features=np.full((count,4,6),np.nan)
    target_row=np.full((count,4),-1,np.int64);maturity=np.zeros((count,4),np.int64)
    clocks=np.array([known_at(b,g) for g,a,k,b in records],np.int64)
    asset=np.array([a for g,a,k,b in records]);group=np.array([g for g,a,k,b in records])
    for row,(g,a,k,b) in enumerate(records):
        for j,n in enumerate(HORIZONS[g]):
            horizon[row,j]=n
            causal=local_daily_state(markets[g][a],k,n)
            causal_state[row,j]=causal['state']
            if causal['features'] is not None:features[row,j]=causal['features']
            label=centered_daily_state(markets[g][a],k,n) if centered else causal
            state[row,j]=label['state']
            if label['state']>=0:
                label_available[row,j]=known_at(markets[g][a][k+n],g) if centered else clocks[row]
    for row,(g,a,k,b) in enumerate(records):
        for j,n in enumerate(HORIZONS[g]):
            destination=lookup.get((g,a,k+n))
            if destination is not None and state[destination,j]>=0:
                target[row,j]=state[destination,j];target_row[row,j]=destination
                maturity[row,j]=label_available[destination,j]
    mask=target>=0
    for j in range(4):
        valid=np.flatnonzero(mask[:,j]);dest=target_row[valid,j]
        assert np.array_equal(target[valid,j],state[dest,j])
        assert np.all(clocks[valid]<maturity[valid,j])
        assert np.all(asset[valid]==asset[dest])
    spell_ids=np.full((count,4),-1,np.int64);chunk_list=[];summaries=[]
    for j,scale in enumerate(scales):
        spells,chunks=state_chunks(asset,state[:,j],label_available[:,j],maximum=5)
        for c in chunks:
            spell_ids[c['rows'],j]=c['spell_id'];chunk_list.append(dict(scale=scale,**c))
        for g in markets:
            selected=[s for s in spells if group[s['first_row']]==g]
            complete=[s for s in selected if not s['right_censored']]
            summaries.append(dict(group=g,scale=scale,n=HORIZONS[g][j],
                labeled_days=int(np.sum((group==g)&(state[:,j]>=0))),spells=len(selected),
                short_complete_spells=sum(s['length']<5 for s in complete),
                complete_spells=len(complete),
                median_complete_length=float(np.median([s['length'] for s in complete])),
                state_counts={name:int(np.sum((group==g)&(state[:,j]==c))) for c,name in enumerate(LOCAL_STATES)}))
    pilot=[];latest={};prediction_arrays={}
    if args.pilot:
        for g in markets:
            members=np.flatnonzero(group==g);names=sorted(set(asset[members]))
            year=2026 if g=='crypto' else 2025
            month=7 if g=='crypto' else 10
            cutoff=int(dt.datetime(year,month,1,tzinfo=dt.timezone.utc).timestamp())*1000
            end=int(dt.datetime(year+int(month==10),1 if month==10 else month+3,1,tzinfo=dt.timezone.utc).timestamp())*1000
            common=(group==g)&mask.all(1)&(clocks>=cutoff)&(clocks<end)&(causal_state>=0).all(1)
            test=np.flatnonzero(common)
            identity=np.array([[a==name for name in names] for a in asset],float)
            for j,scale in enumerate(scales):
                # Centered labels are NEVER current-time model inputs.
                matrix=np.c_[features[:,j],np.eye(len(LOCAL_STATES))[np.maximum(causal_state[:,j],0)],identity]
                train=np.flatnonzero((group==g)&mask[:,j]&(maturity[:,j]<cutoff)&(causal_state[:,j]>=0))
                assert np.all(clocks[train]<cutoff)
                model,_=fit_candidate('tree',matrix[train],target[train,j],seed=17)
                proba=np.full((len(test),len(LOCAL_STATES)),.01/len(LOCAL_STATES))
                proba[:,model[-1].classes_.astype(int)]+=.99*model.predict_proba(matrix[test])
                frequency=(np.bincount(target[train,j],minlength=len(LOCAL_STATES))+1)/(len(train)+len(LOCAL_STATES))
                baseline=np.tile(frequency,(len(test),1))
                pilot.append(dict(group=g,scale=scale,horizon=HORIZONS[g][j],cutoff=cutoff,end=end,
                    training_rows=len(train),max_training_label_maturity=int(maturity[train,j].max()),
                    tree=scores(target[test,j],proba),frequency=scores(target[test,j],baseline),
                    causal_state_baseline=scores(target[test,j],.99*np.eye(len(LOCAL_STATES))[causal_state[test,j]]+.01/len(LOCAL_STATES))))
                prediction_arrays[g+'_'+scale+'_row']=test
                prediction_arrays[g+'_'+scale+'_probabilities']=proba
                for a in names:
                    row=int(members[np.flatnonzero(asset[members]==a)[-1]])
                    # Refit only before this cached inference time; never use future targets.
                    # The pilot model is older than this date, so its existing fit is causal.
                    pr=np.full(len(LOCAL_STATES),.01/len(LOCAL_STATES))
                    pr[model[-1].classes_.astype(int)]+=.99*model.predict_proba(matrix[[row]])[0]
                    latest.setdefault(a,{})[scale]=dict(known_at=int(clocks[row]),n=HORIZONS[g][j],
                        causal_input_state=LOCAL_STATES[causal_state[row,j]],next_period_probabilities=dict(zip(LOCAL_STATES,map(float,pr))),
                        forecast_summary=summarize_state_probabilities(dict(zip(LOCAL_STATES,map(float,pr)))),
                        model_training_cutoff=cutoff)
                print('pilot',g,scale,'train',len(train),'test',len(test),flush=True)
    schema='centered_2n_daily_states_v2_five_classes' if centered else 'local_recency_daily_states_v2_five_classes'
    result=dict(schema=schema,research_only=True,orders_authorized=False,
        rows=count,state_names=LOCAL_STATES,scales=scales,horizons=HORIZONS,
        uncertainty_is_training_class=False,unlabeled_value=-1,
        formula=('state_n[k]=f(OHLCV[k-n+1:k+n+1]); target_n[k]=state_n[k+n]' if centered else 'state_n[k]=f(OHLCV[k-n-1:k+1]); target_n[k]=state_n[k+n]'),
        label_uses_future=centered,window_bars='2n: n through k and n after k' if centered else 'n+2 inclusive',weight_half_life='n/3 bars, fixed exploratory assumption',
        summaries=summaries,pilot=pilot,sources=sources,
        limitations=[
            ('owner最新允许离线标注参考未来n根：以截至k的n根加未来n根，精确窗口[k-n+1,k+n]共2n根；每日滚动标注，不按2n固定分组。' if centered else '历史对照：局部[k-n-1,k]共n+2根，仅过去。'),
            '每根日线分别拥有3天/1周/2周/1个月尺度标签；币种n=3/7/14/30，ETF代理n=3/5/10/21个交易会话；取消独立1日交易候选。',
            '离线标签允许未来上下文，模型local_features和causal_input_state仍只读截至k的局部数据；禁止将尚未成熟的中心日标签作为当天模型特征。以k为中心指数衰减，半衰期n/3固定，未按收益调参。',
            ('中心标签用2n窗口加权价格回归斜率描述k日方向；按局部波动标准化，强度>=±0.5且斜率/日振幅>=0.10判趋势；中心振幅/外侧振幅<=0.65判收缩。剩余样本有两次及以上局部均值穿越归轮动，否则归低效率震荡，包括有斜率但方向进展不足的窗口。这是待检验标注规则，不是自然真值。' if centered else '历史过去窗口规则仅作对照，未获预测/盈利资格。'),
            '监督类别只包含上行、下行、轮动、收缩、低效率震荡五种可观察结构；不包含转换/待确认/unknown。未来或历史不足以标注的行用-1和mask表示数据缺失，不是第六类。',
            '模型保持五类完整概率向量；输出展示层才可标uncertain/待确认，不回写训练标签。辅助解释函数沿用可配置70%研究阈值且要求最高概率唯一，不表示概率已校准；本轮未调门槛或重训。',
            '标签每天滚动，连续段可短于/长于n；5天只作为段内存储分块上限，短块mask、长块共享spell_id，尾部右删失，不固定状态持续长度。',
            ('state_n[k]到k+n收盘后60秒才成熟；next_period_state=state_n[k+n]到k+2n收盘后60秒才成熟，按实际成熟时刻过滤训练。末n根当前标签及末2n根下一周期目标不足均mask，不复制状态补齐。' if centered else '过去窗口标签当日成熟，下一周期目标在k+n成熟。'),
            '包含全部缓存日线OHLCV；历史不足或未来确认不足都保留行并标-1。当前图的标签是事后分类，不能当作当时可见的信号或实际成交路径。',
            '8个固定浅树最小试训若启用，只用于检查相同规则下一周期的训练/预测链；仅一个季度切片、历史已消费，不据其选定最佳周期，未运行新的盈利回测。',
            '固定存续15标的；币种至2026-10-26，ETF/商品为至2025-12-31的复权现金代理，非Binance完整原生合约历史；未改线上策略、服务或权限。'])
    args.output.mkdir(parents=True)
    prices=np.array([[b.o,b.h,b.l,b.c,b.v] for g,a,k,b in records],float)
    np.savez_compressed(args.output/'dataset.npz',schema=np.array(schema),asset=asset,group=group,known_at=clocks,
        ohlcv=prices,ohlcv_names=np.array(['open','high','low','close','volume']),
        daily_state=state,state_available_at=label_available,
        label_uses_future=np.array(centered),label_window_bars=horizon*(2 if centered else 1)+(0 if centered else 2),
        state_names=np.array(LOCAL_STATES),scale_names=np.array(scales),horizon=horizon,
        local_features=features,causal_input_state=causal_state,feature_available_at=clocks,
        spell_id=spell_ids,next_period_state=target,next_period_row=target_row,
        next_period_available_at=maturity,next_period_mask=mask)
    with (args.output/'daily_states.csv').open('w',newline='') as f:
        writer=csv.writer(f);writer.writerow(['group','asset','close_date_utc','known_at_ms','open','high','low','close','volume',*scales])
        for r,(g,a,k,b) in enumerate(records):
            writer.writerow([g,a,dt.datetime.fromtimestamp(b.t,dt.timezone.utc).date().isoformat(),clocks[r],*prices[r],
                *[LOCAL_STATES[c] if c>=0 else 'unlabeled' for c in state[r]]])
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    (args.output/'chunks.json').write_text(json.dumps(chunk_list,ensure_ascii=False,indent=2)+'\n')
    (args.output/'latest_probabilities.json').write_text(json.dumps(latest,ensure_ascii=False,indent=2)+'\n')
    if prediction_arrays:np.savez_compressed(args.output/'pilot_predictions.npz',**prediction_arrays)
    lines=['# 前后2n窗口的逐日日线状态' if centered else '# 过去窗口日线状态对照', '',
        '**同一套规则标注和预测：** '+result['formula'], '',
        '**五类结构标签：** 上行、下行、轮动、收缩、低效率震荡。待确认只属于模型概率输出解释，不是监督类别；-1仅表示数据不足而未标注。', '',
        '每天分别计算不同参考尺度的标签，不把K线变成周/月线，也不固定每段长度。模型预测下一个同尺度周期的状态。', '',
        '|市场|参考尺度|n|有标签日线|完整状态段|不足5天的完整段|状态段中位长度|',
        '|---|---|---:|---:|---:|---:|---:|']
    for s in summaries:lines.append(f"|{s['group']}|{s['scale']}|{s['n']}|{s['labeled_days']}|{s['complete_spells']}|{s['short_complete_spells']}|{s['median_complete_length']}|")
    lines+=['','daily_states.csv每行是真实日线OHLCV和四个尺度的当日标签；dataset.npz同时包含同规则下一周期目标、可用时刻及尾部mask。']
    if pilot:
        lines+=['','## 固定参数最小试训', '', '|市场|尺度|测试行|树平衡准确率|频率基线平衡准确率|树Brier|', '|---|---|---:|---:|---:|---:|']
        for r in pilot:lines.append(f"|{r['group']}|{r['scale']}|{r['tree']['rows']}|{r['tree']['balanced_accuracy']:.2%}|{r['frequency']['balanced_accuracy']:.2%}|{r['tree']['brier']:.5f}|")
    else:
        lines+=['','本轮只重建数据标签和图，未执行模型训练。']
    lines+=['','## 边界与假设','',*['- '+x for x in result['limitations']],'',
        '```bash',f'OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=src ./.venv/bin/python scripts/research/build_market_local_daily_states.py '+('--pilot ' if args.pilot else '')+('--past-only ' if args.past_only else '')+f'--output {args.output}','```','']
    (args.output/'report.md').write_text('\n'.join(lines))
    print('saved',args.output,'daily_rows',count,'next_period_labels',int(mask.sum()),flush=True)


if __name__=='__main__':
    with threadpool_limits(limits=1):main()
