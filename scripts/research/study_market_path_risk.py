"""Train aligned path-event probabilities from retained hourly/minute candles."""
from __future__ import annotations

import argparse
from collections import Counter,defaultdict
import datetime as dt
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from qount.research.market_path_risk import (
    ASSETS,HOUR_MS,MINUTE_MS,load_path_sources,aligned_path_label,continuous_range_probability,
)
from qount.research.market_learning import range_geometry_from_distances
from qount.research.market_probability_refinement import fit_geometry_offset,predict_geometry_offset
from qount.research.market_state_validation import scores
from study_binance_market_states import load_markets
from compare_market_state_profiles import paired_comparison


TARGETS=('close5','immediate_path5','scheduled_path5')


def date(t):return dt.datetime.fromtimestamp(int(t),dt.timezone.utc).strftime('%Y-%m-%d')


def source_checks(hours,minutes,markets):
    checked_days=checked_fine=0;price_error=fine_error=0.
    for asset in ASSETS:
        daily={(b.t+1-86400)*1000:b for b in markets['crypto'][asset]}
        for start in sorted({t//86400000*86400000 for t in hours[asset]}):
            clocks=list(range(start,start+86400000,HOUR_MS))
            if not all(t in hours[asset] for t in clocks):continue
            rows=[hours[asset][t] for t in clocks];b=daily[start]
            observed=np.array([rows[0][1],max(r[2] for r in rows),min(r[3] for r in rows),rows[-1][4]])
            price_error=max(price_error,float(np.max(abs(observed/np.array([b.o,b.h,b.l,b.c])-1))))
            checked_days+=1
        for start,row in hours[asset].items():
            clocks=list(range(start,start+HOUR_MS,MINUTE_MS))
            if not all(t in minutes[asset] for t in clocks):continue
            fine=[minutes[asset][t] for t in clocks]
            observed=np.array([fine[0][1],max(r[2] for r in fine),min(r[3] for r in fine),fine[-1][4]])
            fine_error=max(fine_error,float(np.max(abs(observed/row[1:5]-1))));checked_fine+=1
    if price_error>1e-8 or fine_error>1e-8:raise ValueError('path_cross_resolution_source_mismatch')
    return dict(hourly_daily_days=checked_days,hourly_daily_price_error=price_error,
                minute_hour_comparisons=checked_fine,minute_hour_price_error=fine_error)


def build_panel(parent,markets,hours,minutes):
    columns={str(n):j for j,n in enumerate(parent['feature_names'])};rows=[];excluded=Counter()
    for k in np.flatnonzero(np.isin(parent['asset'],ASSETS)&(parent['y'][:,2]>=0)):
        asset=str(parent['asset'][k]);known=int(parent['known_at'][k]);start=known*1000;end=start+5*86400000
        if start//HOUR_MS*HOUR_MS not in hours[asset]:continue
        bars=markets['crypto'][asset];i=int(parent['bar_index'][k]);lower=min(b.l for b in bars[i-20:i]);upper=max(b.h for b in bars[i-20:i])
        coarse=aligned_path_label(hours[asset],start,end,lower,upper)
        exact=aligned_path_label(hours[asset],start,end,lower,upper,minutes=minutes[asset])
        scheduled_start=(start//HOUR_MS+1)*HOUR_MS
        scheduled=aligned_path_label(hours[asset],scheduled_start,scheduled_start+5*86400000,lower,upper)
        if not exact['complete'] or not scheduled['complete']:
            excluded['incomplete_five_day_window']+=1;continue
        if exact['label']>=0 and exact['label']>parent['y'][k,2]:raise ValueError('path_close_subset_violation')
        if scheduled['label']<0:raise ValueError('whole_hour_path_cannot_be_ambiguous')
        if scheduled['label']>parent['y'][k,2]:raise ValueError('scheduled_close_subset_violation')
        low=float(parent['X'][k,columns['lower_boundary_distance_sigma20']]);high=float(parent['X'][k,columns['upper_boundary_distance_sigma20']])
        base=[range_geometry_from_distances(low,high),continuous_range_probability(low,high,wait_days=1/1440),
              continuous_range_probability(low,high,wait_days=1/24)]
        rows.append(dict(asset=asset,known_at=known,original_row=int(k),state=str(parent['state'][k]),
            category=str(parent['economic_category'][k]),lower=lower,upper=upper,X=[low,high,float(parent['X'][k,columns['relative_volatility']])],
            y=[int(parent['y'][k,2]),exact['label'],scheduled['label']],coarse_immediate=coarse['label'],
            maturity=[int(parent['maturity'][k,2]),exact['available_at'] if exact['label']>=0 else 0,scheduled['available_at']],
            window_available_at=exact['available_at'],immediate_end=end//1000,scheduled_start=scheduled_start//1000,
            scheduled_end=scheduled_start//1000+5*86400,refined_cells=exact['refined_cells'],base=base))
    rows.sort(key=lambda r:(r['known_at'],r['asset']))
    if not rows:raise ValueError('no_complete_path_windows')
    panel={k:np.array([r[k] for r in rows]) for k in rows[0]}
    panel['target_names']=np.array(TARGETS)
    panel['feature_names']=np.array(['lower_boundary_distance_sigma20','upper_boundary_distance_sigma20','relative_volatility'])
    panel['X_available_at']=np.repeat(panel['known_at'][:,None],3,axis=1)
    return panel,dict(rows=len(rows),assets=sorted(set(r['asset'] for r in rows)),excluded=dict(excluded),
        coarse_ambiguous=sum(r['coarse_immediate']<0 for r in rows),remaining_ambiguous=sum(r['y'][1]<0 for r in rows),
        minute_refined_cells=sum(r['refined_cells'] for r in rows),
        known_window_start=date(rows[0]['known_at']),known_window_end=date(rows[-1]['known_at']))


def sample_rows(data,indices,column):
    return [dict(index=int(i),asset=str(data['asset'][i]),key=str(data['state'][i]),category=str(data['category'][i]),
        known_at=int(data['known_at'][i]),mature_at=int(data['maturity'][i,column]),outcome=int(data['y'][i,column])) for i in indices]


def censored_brier_bounds(p,y):
    known=y>=0;loss=np.zeros(len(y));loss[known]=2*(p[known]-y[known])**2
    low=loss.copy();high=loss.copy()
    low[~known]=2*np.minimum(p[~known]**2,(1-p[~known])**2)
    high[~known]=2*np.maximum(p[~known]**2,(1-p[~known])**2)
    return dict(rows=len(y),known=int(known.sum()),unknown=int((~known).sum()),lower=float(low.mean()),upper=float(high.mean()))


def write_report(r):
    lines=['# 决策时点对齐的路径风险目标与小模型','',
        '仅研究事件概率，无实盘订单/资金收益；三币缓存三个离散时段，历史已消费。','',
        '## 时点与来源','',
        '- 决策为UTC日线完成后60秒。即时窗口为[决策,决策+120h)，不包含决策前60秒。',
        '- 小时边界不确定时只给可证明的0/1，其余为-1；已有分钟首小时可细化边界，不猜极值时间。',
        '- 另设下一整点开始的120h窗口，距决策59分钟，无边界歧义；它不是即时成交策略。',
        '- 价格边界为闭区间，触及但未越过仍算保持；不等于止损未触发。',
        '- 标签可用时间保守等待整个末小时完成再加60秒；即使实际事件较早发生，也不提前学习。',
        f"- 来源核对：{r['source_checks']}。",
        f"- 样本：{r['panel_summary']}。",'',
        '## 训练对照','',
        '2025-10起逐季预测，训练标签严格早于季初成熟；每日起点重叠，不能把行数当独立样本。',
        '每目标分别训练仅截距/相对波动率offset，L2=20固定；来源相同的资产过去频率为另一基线。',
        ('vol_supported只在过去训练特征的5%—95%区间采用修正，其他样本退回几何；vol_winsor在相同训练区间裁剪训练/预测输入，阈值不看测试。'
         if 'support_quantiles' in r['parameters'] else '首轮尚未测试支持区间处理；后续优化另存。'),
        'broad_history_vol若出现，只控制收盘目标的历史覆盖：同样三币、每日采样、同特征/估计方法，使用更完整过去日线；不把收盘训练标签用于路径头。',
        '路径基线使用连续吸收边界Brownian近似，并对未知等待期价格积分；收盘基线仍只监测5个收盘。两者目标不同，不横比准确率。','',
        '|目标|模型|已知标签/预测|准确率|平衡准确率|Brier↓|','|---|---|---:|---:|---:|---:|']
    for e in r['evaluations']:
        if e['window']!='all':continue
        s=e['scores'];lines.append(f"|{e['target']}|{e['model']}|{s['count']}/{e['forecast_rows']}|{s['accuracy']:.2%}|{s['balanced_accuracy']:.2%}|{s['brier']:.5f}|")
    lines+=['','## 同一机会的概率增量','',
        '|目标|对照|Brier差|季度簇95%区间|','|---|---|---:|---|']
    for c in r['comparisons']:lines.append(f"|{c['target']}|{c['left']} − {c['right']}|{c['delta']['mean']:+.5f}|{c['delta']['interval95']}|")
    lines+=['','## 路径标签与不确定性','',
        '即时路径的Brier区间允许未知标签取0或1，只是部分识别界，不是置信区间；不确定样本未塞进训练。','',
        '|目标|模型|不确定标签|全预测Brier可行区间|','|---|---|---:|---|']
    for b in r['censor_bounds']:lines.append(f"|{b['target']}|{b['model']}|{b['unknown']}|[{b['lower']:.5f},{b['upper']:.5f}]|")
    lines+=['','## 高概率与边界宽度','',
        '阈值固定0.8；不同目标/模型覆盖不同，不挑最高命中率宣称优势。宽度以已知sigma20为单位。','',
        '|目标|模型|样本/覆盖/非重叠数|实际保持率|平均预测|平均区间宽度|','|---|---|---|---:|---:|---:|']
    for s in r['selective']:lines.append(f"|{s['target']}|{s['model']}|{s['count']}/{s['coverage']:.1%}/{s.get('nonoverlap_count','—')}|{s['hit_rate']:.2%}|{s['mean_probability']:.2%}|{s['mean_width_sigma']:.2f}|")
    resource=f"实际{len(r['fits'])}次小拟合；初次运行记录{r['elapsed_seconds']:.1f}秒。" if r.get('incremental_control_fits') else f"实际{len(r['fits'])}次小拟合、{r['elapsed_seconds']:.1f}秒。"
    lines+=['','## 边界','',resource+'数据、成熟时间、预测和完整年度/标的诊断保存在同目录。','']
    lines+=['- '+s for s in r['limitations']]
    lines+=['','来源定义：[Binance公开K线列说明](https://github.com/binance/binance-public-data/)。连续基线由[吸收边界热核](https://www.ma.imperial.ac.uk/~pavl/PavliotisBook.pdf#page=86)积分得到，仅作统计近似。']
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('retain earlier experiments')
    started=time.monotonic()
    with np.load(args.dataset,allow_pickle=False) as z:parent={k:z[k] for k in z.files}
    markets,_,daily_sources=load_markets()
    schema=json.loads((args.dataset.parent/'feature_schema.json').read_text())
    expected={s['path']:s['sha256'] for s in schema['sources']}
    if any(expected.get(s['path'])!=s['sha256'] for s in daily_sources):raise ValueError('path_daily_source_drift')
    hours,minutes,sources=load_path_sources('state/research_cache/position_flow_20261027','state/research_cache/small_account_breakout_v01_20261013')
    checks=source_checks(hours,minutes,markets)
    data,summary=build_panel(parent,markets,hours,minutes)
    print('path panel',summary,'checks',checks,flush=True)
    fits=[];evaluations=[];comparisons=[];predictions=[];run_names=[];bounds=[];selective=[];diagnostics=[]
    for c,target in enumerate(TARGETS):
        test_indices=np.flatnonzero(data['known_at']>=1759276800) #2025-10-01 UTC, fixed before results.
        quarters=defaultdict(list)
        for i in test_indices:
            t=dt.datetime.fromtimestamp(int(data['known_at'][i]),dt.timezone.utc)
            quarters[t.year,(t.month-1)//3*3+1].append(int(i))
        runs={m:[] for m in ('asset_prior','geometry','intercept_offset','vol_offset','vol_supported','vol_winsor')}
        if target=='close5':runs['broad_history_vol']=[]
        broad_base=None
        if target=='close5':
            columns={str(n):j for j,n in enumerate(parent['feature_names'])}
            broad_valid=np.isin(parent['asset'],ASSETS)&(parent['y'][:,2]>=0)
            broad_indices=np.flatnonzero(broad_valid);broad_base=np.full(len(parent['X']),np.nan)
            for i in broad_indices:
                broad_base[i]=range_geometry_from_distances(float(parent['X'][i,columns['lower_boundary_distance_sigma20']]),
                    float(parent['X'][i,columns['upper_boundary_distance_sigma20']]))
        for (year,month),test in sorted(quarters.items()):
            cutoff=int(dt.datetime(year,month,1,tzinfo=dt.timezone.utc).timestamp());test=np.array(test)
            train=np.flatnonzero((data['y'][:,c]>=0)&(data['maturity'][:,c]<cutoff)&(data['maturity'][:,c]>0))
            if len(train)<60 or len(np.unique(data['y'][train,c]))<2:raise ValueError('path_insufficient_mature_training')
            if np.any(data['known_at'][train]>=cutoff):raise ValueError('path_training_clock')
            template=sample_rows(data,test,c)
            prior={}
            for asset in ASSETS:
                y=data['y'][train[data['asset'][train]==asset],c];prior[asset]=(y.sum()+1)/(len(y)+2)
            for model,p in (('asset_prior',np.array([prior[str(data['asset'][i])] for i in test])),('geometry',data['base'][test,c])):
                runs[model]+=[dict(row,probabilities=[1-v,float(v)]) for row,v in zip(template,p)]
            quantiles=np.quantile(data['X'][train,2],[.05,.95])
            for model,columns in (('intercept_offset',[]),('vol_offset',[2]),('vol_winsor',[2])):
                a,b=data['X'][train][:,columns],data['X'][test][:,columns]
                if model=='vol_winsor':a,b=np.clip(a,*quantiles),np.clip(b,*quantiles)
                fitted=fit_geometry_offset(a,data['y'][train,c],data['base'][train,c])
                p=predict_geometry_offset(fitted,b,data['base'][test,c])
                runs[model]+=[dict(row,probabilities=prob.tolist()) for row,prob in zip(template,p)]
                if model=='vol_offset':
                    supported=(data['X'][test,2]>=quantiles[0])&(data['X'][test,2]<=quantiles[1])
                    guarded=p.copy();guarded[~supported]=np.c_[1-data['base'][test[~supported],c],data['base'][test[~supported],c]]
                    runs['vol_supported']+=[dict(row,probabilities=prob.tolist(),support=bool(ok)) for row,prob,ok in zip(template,guarded,supported)]
                fits.append(dict(target=target,model=model,cutoff=cutoff,train_rows=len(train),test_rows=len(test),
                    last_training_maturity=int(data['maturity'][train,c].max()),coefficients=fitted['coefficients'].tolist(),
                    training_support_quantiles=quantiles.tolist(),test_support_fraction=float(np.mean((data['X'][test,2]>=quantiles[0])&(data['X'][test,2]<=quantiles[1])))))
            if target=='close5':
                training=np.flatnonzero(broad_valid&(parent['maturity'][:,2]<cutoff)&(parent['maturity'][:,2]>0))
                value=parent['X'][training,columns['relative_volatility']][:,None]
                fitted=fit_geometry_offset(value,parent['y'][training,2],broad_base[training])
                p=predict_geometry_offset(fitted,data['X'][test][:,[2]],data['base'][test,c])
                runs['broad_history_vol']+=[dict(row,probabilities=prob.tolist()) for row,prob in zip(template,p)]
                fits.append(dict(target=target,model='broad_history_vol',cutoff=cutoff,train_rows=len(training),test_rows=len(test),
                    last_training_maturity=int(parent['maturity'][training,2].max()),coefficients=fitted['coefficients'].tolist(),
                    training_assets=list(ASSETS),source='same three assets, full retained daily history, daily stride'))
            print(target,year,month,'train',len(train),'test',len(test),flush=True)
        for model,rows in runs.items():
            rid=len(run_names);run_names.append(target+'/'+model)
            for row in rows:predictions.append((rid,row['index'],*row['probabilities'],int(row.get('support',-1))))
            for window in ['all']+sorted({date(r['known_at'])[:4] for r in rows}):
                chosen=rows if window=='all' else [r for r in rows if date(r['known_at']).startswith(window) and r['mature_at']>0
                    and date(r['mature_at'])<str(int(window)+1)+'-01-01']
                known=[r for r in chosen if r['outcome']>=0]
                if known:evaluations.append(dict(target=target,model=model,window=window,forecast_rows=len(chosen),scores=scores(known)))
            indices=np.array([r['index'] for r in rows]);p=np.array([r['probabilities'][1] for r in rows]);y=data['y'][indices,c]
            bounds.append(dict(target=target,model=model,**censored_brier_bounds(p,y)))
            chosen=(p>=.8)&(y>=0)
            if chosen.any():
                last={};kept=[]
                for i in sorted(indices[chosen],key=lambda i:(data['known_at'][i],data['asset'][i])):
                    asset=str(data['asset'][i]);start=data['known_at'][i]
                    if start>=last.get(asset,0):kept.append(i);last[asset]=start+5*86400
                selective.append(dict(target=target,model=model,count=int(chosen.sum()),coverage=float(chosen.sum()/len(rows)),
                    unique_clocks=len(set(data['known_at'][indices[chosen]])),nonoverlap_count=len(kept),
                    nonoverlap_hit_rate=float(data['y'][kept,c].mean()),hit_rate=float(y[chosen].mean()),mean_probability=float(p[chosen].mean()),
                    mean_width_sigma=float(data['X'][indices[chosen],:2].sum(1).mean()),
                    same_sample_geometry_brier=float(np.mean(2*(data['base'][indices[chosen],c]-y[chosen])**2)),
                    same_sample_model_brier=float(np.mean(2*(p[chosen]-y[chosen])**2))))
            for asset in ASSETS:
                chosen_rows=[r for r in rows if r['asset']==asset and r['outcome']>=0]
                if chosen_rows:diagnostics.append(dict(target=target,model=model,asset=asset,scores=scores(chosen_rows)))
        for left,right in (('vol_offset','geometry'),('vol_offset','intercept_offset'),('vol_offset','asset_prior')):
            a=[r for r in runs[left] if r['outcome']>=0];b=[r for r in runs[right] if r['outcome']>=0]
            comparisons.append(dict(target=target,left=left,right=right,delta=paired_comparison(a,b)))
        for left,right in (('vol_supported','vol_offset'),('vol_supported','geometry'),('vol_winsor','vol_offset'),('vol_winsor','geometry')):
            a=[r for r in runs[left] if r['outcome']>=0];b=[r for r in runs[right] if r['outcome']>=0]
            comparisons.append(dict(target=target,left=left,right=right,delta=paired_comparison(a,b)))
        if target=='close5':
            for right in ('vol_offset','geometry'):
                comparisons.append(dict(target=target,left='broad_history_vol',right=right,
                    delta=paired_comparison(runs['broad_history_vol'],runs[right])))
    result=dict(research_only=True,orders_authorized=False,independent_oos=False,parent_dataset=str(args.dataset),
        parent_sha256=hashlib.sha256(args.dataset.read_bytes()).hexdigest(),sources=sources,source_checks=checks,panel_summary=summary,
        fits=fits,evaluations=evaluations,comparisons=comparisons,censor_bounds=bounds,selective=selective,diagnostics=diagnostics,
        elapsed_seconds=time.monotonic()-started,
        parameters=dict(evaluation_start='2025-10-01',training_stride=1,refit='quarterly',offset_penalty=20,path_calendar_days=5,
            publication_buffer_seconds=60,minute_refinement='existing first-hour archives only',support_quantiles=[.05,.95]),
        target_definitions=dict(close5='Original five future UTC daily closes inside fixed prior20 bounds',
            immediate_path5='All native trade prices inside bounds on [known_at,known_at+120h); partial-hour ambiguity is -1',
            scheduled_path5='All native trade prices inside bounds for120h from next whole hour,59min after daily decision'),
        limitations=[
            '三币三个离散时段，选择性缓存与历史已消费；季度簇很少，不把区间当可靠显著性认证。',
            '每日5日目标高度重叠，同期三币相关；样本数不是独立试验数，未调参选阈值。',
            '即时路径不确定样本不参与训练，所有预测报告上下界；删去不确定样本仍可能有选择偏差。',
            '59分钟延迟窗口只是可精确标注的风险目标，不是承诺该时点成交；无成交价格/手续费/资金费/止损撮合。',
            '路径使用合约交易价OHLC；不是标记价格止损触发、真实盘口或实际成交的预测。',
            '价格边界允许触及，连续吸收模型只是近似；不能把保持概率当成止损触发概率的补数。',
            '基线使用60秒前最后已完成日线收盘和sigma20，不偷看第一未来小时/分钟价格；Brownian只是近似。',
            '标签成熟保守等末小时完整完成，未用未来日线/小时信息作为特征。',
            'ETF代理与2026原生合约没有相同训练历史，本轮没有拿代理路径冒充ETF合约风险。',
            '原数据、生产策略、账户权限与服务未变；没有新增数据下载。',
        ])
    args.output.mkdir(parents=True)
    np.savez_compressed(args.output/'path_dataset.npz',**data)
    a=np.array(predictions,float)
    np.savez_compressed(args.output/'predictions.npz',run_id=a[:,0].astype(int),row_index=a[:,1].astype(int),
        probabilities=a[:,2:4],feature_supported=a[:,4].astype(np.int8),run_names=np.array(run_names))
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (args.output/'report.md').write_text(write_report(result))
    print(json.dumps(dict(output=str(args.output),fits=len(fits),elapsed_seconds=result['elapsed_seconds'])))


if __name__=='__main__':main()
