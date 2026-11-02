"""Two-week label boundaries and small-segment diagnostics, offline only."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import datetime as dt
import json
from pathlib import Path

import numpy as np

from qount.research.market_daily_states import LOCAL_STATES, state_chunks
from qount.research.market_state_boundaries import window_refinement
from qount.research_data.bars import Bar

BASE=Path('state/research_runs/market_daily_states_20261031_centered_2n_five_classes')
POLICIES=('baseline','noise_only','boundary_only','combined','supported_boundary','conservative_combined','pair_boundary','pair_combined')


def segments(states):
    boundaries=np.r_[0,np.flatnonzero(np.diff(states)!=0)+1,len(states)]
    return [(int(a),int(b),int(states[a])) for a,b in zip(boundaries[:-1],boundaries[1:]) if states[a]>=0]


def diagnostic(bars,states,n):
    closes=np.array([b.c for b in bars]);log=np.log(closes)
    true=np.r_[bars[0].h-bars[0].l,[max(b.h-b.l,abs(b.h-a.c),abs(b.l-a.c)) for a,b in zip(bars[:-1],bars[1:])]]
    atr=np.array([np.median(true[max(0,i-n):i]) if i else true[0] for i in range(len(bars))])
    runs=segments(states);result=[]
    for j,(a,b,state) in enumerate(runs):
        if a==0 or b==len(states) or states[a-1]<0 or states[b]<0:continue
        anchor=closes[a-1];unit=max(float(atr[a]),1e-10)
        excursion=float(np.max(np.abs(closes[a:b]-anchor))/unit)
        net=float((closes[b-1]-anchor)/unit)
        sandwich=bool(j>0 and j+1<len(runs) and runs[j-1][2]==runs[j+1][2])
        result.append(dict(length=b-a,state=state,excursion_atr=excursion,net_atr=net,
                           sandwich=sandwich,start=a,end=b-1))
    short=[r for r in result if r['length']<=2]
    weak=[r for r in short if r['sandwich'] and r['excursion_atr']<1. and r['state'] in (2,3,4)]
    trend=[r for r in result if r['state'] in (0,1)]
    mismatches=[r for r in trend if r['net_atr']*(1 if r['state']==0 else -1)<0]
    direct=[]
    for i in range(1,len(states)):
        if states[i] not in (0,1) or states[i-1] not in (0,1) or states[i]==states[i-1]:continue
        left=max(0,i-4);right=min(len(states),i+3)
        pivot=left+int(np.argmax(closes[left:right]) if states[i-1]==0 else np.argmin(closes[left:right]))
        direct.append(abs(pivot-(i-1)))
    # Price-defined shock bars are a diagnostic, not ground-truth regimes.
    shocks=[];matched=[]
    for i in range(1,len(states)):
        if states[i]<0:continue
        if abs(closes[i]-closes[i-1])>=2*max(atr[i],1e-10):
            shocks.append(i)
            if states[i]==(0 if closes[i]>closes[i-1] else 1):matched.append(i)
    return dict(complete_segments=len(result),short_segments=len(short),
        short_by_state=dict(Counter(LOCAL_STATES[r['state']] for r in short)),
        short_weak_nondirectional_islands=len(weak),
        median_length=float(np.median([r['length'] for r in result])),
        trend_segments=len(trend),trend_wrong_net_direction=len(mismatches),
        direct_reversals=len(direct),direct_exact_pivot=sum(d==0 for d in direct),
        direct_pivot_abs_error_sum=int(sum(direct)),
        large_price_bars=shocks,matched_large_price_bars=matched,
        weak_islands=weak)


def aggregate(rows):
    keys=('complete_segments','short_segments','short_weak_nondirectional_islands',
          'trend_segments','trend_wrong_net_direction','direct_reversals','direct_exact_pivot','direct_pivot_abs_error_sum')
    result={k:sum(r[k] for r in rows) for k in keys}
    result.update(large_price_bars=sum(len(r['large_price_bars']) for r in rows),
        matched_large_price_bars=sum(len(r['matched_large_price_bars']) for r in rows),
        median_asset_segment_length=float(np.median([r['median_length'] for r in rows])))
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,default=BASE)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--policy',choices=(*POLICIES[1:],'group_conservative'),default='noise_only')
    args=p.parse_args()
    if args.output.exists():p.error('preserve old evidence; choose a new output')
    with np.load(args.source/'dataset.npz',allow_pickle=False) as z:data={k:z[k] for k in z.files}
    variants={name:data['daily_state'][:,2].copy() for name in (*POLICIES,'selected')}
    changes=[];asset_metrics=[];rows_count=len(data['asset'])
    for asset in sorted(set(data['asset'])):
        ix=np.flatnonzero(data['asset']==asset);group=str(data['group'][ix[0]]);n=int(data['horizon'][ix[0],2])
        effective=('pair_combined' if group=='crypto' else 'noise_only') if args.policy=='group_conservative' else args.policy
        bars=[Bar(int(data['known_at'][row]//1000)-(61 if group=='crypto' else 60),*data['ohlcv'][row]) for row in ix]
        before=data['daily_state'][ix,2]
        for k in np.flatnonzero(before>=0):
            outcome=window_refinement(bars[k-n+1:k+n+1],n)
            assert outcome['baseline']==before[k],(asset,k)
            for policy in POLICIES:variants[policy][ix[k]]=outcome[policy]
            variants['selected'][ix[k]]=outcome[effective]
            if outcome[effective]!=before[k]:
                changes.append(dict(asset=str(asset),group=group,row=int(ix[k]),
                    close_date=dt.datetime.fromtimestamp(bars[k].t,dt.timezone.utc).date().isoformat(),
                    before=LOCAL_STATES[before[k]],after=LOCAL_STATES[outcome[effective]],
                    noise_candidate=outcome['noise_reason'] is not None,
                    boundary_changed=bool(outcome['pair_boundary']!=before[k]) if effective.startswith('pair_') else (outcome['boundary_changed'] if effective!='noise_only' else False),
                    local_leg=outcome['leg']))
        for policy in (*POLICIES,'selected'):
            stats=diagnostic(bars,variants[policy][ix],n)
            asset_metrics.append(dict(asset=str(asset),group=group,policy=policy,**stats))
        print(asset,effective,'changed',int(sum(variants['selected'][ix]!=before)),flush=True)
    comparisons=[]
    for group in ('crypto','etf_proxy'):
        for policy in (*POLICIES,'selected'):
            own=[r for r in asset_metrics if r['group']==group and r['policy']==policy]
            result=aggregate(own)
            base={r['asset']:set(r['matched_large_price_bars']) for r in asset_metrics if r['group']==group and r['policy']=='baseline'}
            result['previously_matched_large_bars_lost']=sum(len(base[r['asset']]-set(r['matched_large_price_bars'])) for r in own)
            result['changed_days']=int(sum((data['group']==group)&(variants[policy]!=variants['baseline'])))
            comparisons.append(dict(group=group,policy=policy,**result))
    revised={k:v.copy() for k,v in data.items()}
    revised['schema']=np.array('centered_2n_daily_states_v3_two_week_boundaries')
    revised['daily_state'][:,2]=variants['selected']
    mask=revised['next_period_mask'][:,2]
    destination=revised['next_period_row'][mask,2]
    revised['next_period_state'][mask,2]=revised['daily_state'][destination,2]
    spells,chunks=state_chunks(revised['asset'],revised['daily_state'][:,2],revised['state_available_at'][:,2],maximum=5)
    revised['spell_id'][:,2]=-1
    for chunk in chunks:revised['spell_id'][chunk['rows'],2]=chunk['spell_id']
    # The bounded raw-window mechanism must preserve all maturity clocks and masks.
    for key in ('ohlcv','known_at','local_features','causal_input_state','state_available_at','next_period_available_at','next_period_mask'):
        assert np.array_equal(revised[key],data[key],equal_nan=True) if revised[key].dtype.kind in 'fc' else np.array_equal(revised[key],data[key])
    assert np.array_equal(revised['daily_state'][:,[0,1,3]],data['daily_state'][:,[0,1,3]])
    revised['two_week_label_changed']=variants['selected']!=variants['baseline']
    revised['boundary_policy']=np.array(args.policy)
    result=dict(research_only=True,orders_authorized=False,rows=rows_count,
        source=str(args.source),selected_policy=args.policy,parameters=dict(radius=3,maximum_noise_days=2,
            minimum_swing_atr=1.5,strong_leg_atr=2.,minimum_leg_efficiency=.55,
            maximum_noise_excursion_atr=1.,marginal_compression_band=[.55,.65]),
        comparisons=comparisons,asset_metrics=asset_metrics,changed_days=len(changes),
        limitations=[
            '仅研究两周尺度：币种n14/ETF代理n10，其他尺度标签、原价格与模型输入不变；五类标签和概率不突出时的输出解释保持分开。',
            '机制对照为原标签、弱短段处理、直接价格峰谷处理、两者合并，以及要求既有连续趋势核心支持的保守边界/合并。直接峰谷法产生更多短段，被拒绝作为当前候选；没有参数网格或收益优化。',
            '所有局部证据、价格峰谷与短段检查均限制在原始[k-n+1,k+n]窗口；不递归合并全局日标签，不消费其他日标签的额外未来。标签/下一周期目标的k+n/k+2n成熟时间不变。',
            '短段处理针对同一个2n窗口内邻近重心证据形成的不超过2根弱收缩小岛，幅度不足局部1个典型振幅、收缩比位于0.55至0.65，且两边均支持轮动/低效率状态。只消除弱收缩，不把轮动反改成收缩；不按持续时间删除趋势段，强收缩保留。',
            '局部证据小岛不是全局最终标签段的同义词；少量修改会落在全局较长弱收缩段的边缘。必须用完整序列复核新增短段和实际价格幅度，不能仅凭局部条件宣称全部都是噪声。',
            '价格边界以收盘变化归属为准：波段拥有(左拐点,右拐点]，峰/谷当日结束前一段，下一根开始后一段。直接峰谷对照只对附近3根且幅度至少2个典型振幅、方向效率至少0.55的局部波段调整，但已因碎段增加而拒绝。',
            '保守边界另要求同一原始窗口内至少3个连续重心位置已有同向趋势支持，当前日距离该核心不超过2根；不因峰谷新造孤立趋势，既有相反趋势只允许强价格日且方向相容时更改。',
            '成对边界方案更严格：同窗口的7个重心证据只允许一个A|B切换，两侧各至少3点且涉及趋势；只在中心±2根内的内部峰谷、两边变化均≥1个典型日振幅时挪动已有边界。只能在已有A/B间归属，不新造第三状态。',
            '典型日振幅在标注窗口内按log真振幅中位数近似；独立诊断使用短段开始前n根真振幅中位数。两种单位不同，不能把局部弱证据规则视作已验证的全局噪声真值。',
            '短段未必是噪声，低幅度或更平滑也不证明标签更正确；保留旧标签、机制分解、变更日期及强价格日诊断，需结合着色曲线评价。',
            '当前推荐group_conservative：币种采用成对边界+弱短段，ETF代理只采用弱短段，因为边界候选在ETF上增加碎段。该选择来自本轮已消费历史的描述性诊断，不是独立样本外资格。',
            '固定存续15标的、已消费历史；未重训模型、回测盈利、下载数据或更改生产。'])
    args.output.mkdir(parents=True)
    np.savez_compressed(args.output/'dataset.npz',**revised)
    np.savez_compressed(args.output/'two_week_variants.npz',**variants)
    with (args.output/'daily_states.csv').open('w',newline='') as stream:
        writer=csv.writer(stream)
        writer.writerow(['group','asset','close_date_utc','known_at_ms','open','high','low','close','volume',
                         *map(str,revised['scale_names']),*[str(s)+'_label_available_ms' for s in revised['scale_names']]])
        for row in range(rows_count):
            g=str(revised['group'][row]);stamp=int(revised['known_at'][row]//1000)-(61 if g=='crypto' else 60)
            writer.writerow([g,str(revised['asset'][row]),dt.datetime.fromtimestamp(stamp,dt.timezone.utc).date().isoformat(),
                int(revised['known_at'][row]),*revised['ohlcv'][row],
                *[LOCAL_STATES[c] if c>=0 else 'unlabeled' for c in revised['daily_state'][row]],
                *revised['state_available_at'][row]])
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    (args.output/'changes.json').write_text(json.dumps(changes,ensure_ascii=False,indent=2)+'\n')
    lines=['# 两周尺度：边界归属与短段噪声实验','',f'本目录dataset.npz采用：`{args.policy}`。selected行是最终数据；其他方法仅保留机制对照。','',
        '|市场|方法|完整段|≤2根短段|弱夹心段|趋势段净方向错误|标签变化日|强价格日原匹配丢失|',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    for r in comparisons:lines.append(f"|{r['group']}|{r['policy']}|{r['complete_segments']}|{r['short_segments']}|{r['short_weak_nondirectional_islands']}|{r['trend_wrong_net_direction']}/{r['trend_segments']}|{r['changed_days']}|{r['previously_matched_large_bars_lost']}|")
    lines+=['','弱夹心段指A→B→A、B≤2根、收盘偏离不足之前n根典型振幅且B为非方向性类别；是诊断，不是噪声真值。强价格日指单日收盘变化≥之前n根典型振幅2倍，标签匹配只作防误删检查。', '',
        '## 限制与执行','',*['- '+v for v in result['limitations']],'',
        '```bash',f'PYTHONPATH=src ./.venv/bin/python scripts/research/study_market_state_boundaries.py --source {args.source} --policy {args.policy} --output {args.output}','```','']
    (args.output/'report.md').write_text('\n'.join(lines))
    print('saved',args.output,'changed_days',len(changes),flush=True)


if __name__=='__main__':main()
