"""Describe current-state training data and switching-event support; no fits."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from qount.research.market_state_factorization import purged_quarter

STATES=('upward','downward','sideways')


def spells(d):
    """Count actual spells, never storage chunks; retain edge censoring."""
    y=d['main_state'];count=len(y);age=np.zeros(count,int);remaining=np.zeros(count,int)
    prior=np.full(count,-1,int);new=np.zeros(count,bool);left_seen=np.zeros(count,bool);segments=[]
    for asset in np.unique(d['asset']):
        rows=np.flatnonzero(d['asset']==asset);prior[rows[1:]]=y[rows[:-1]];start=0
        for end in range(1,len(rows)+1):
            if end<len(rows) and y[rows[end]]==y[rows[start]]:continue
            part=rows[start:end];state=int(y[part[0]])
            if state>=0:
                left=start>0 and y[rows[start-1]]>=0
                right=end<len(rows) and y[rows[end]]>=0
                age[part]=np.arange(1,len(part)+1);remaining[part]=np.arange(len(part),0,-1)
                new[part[0]]=left;left_seen[part]=left
                segments.append(dict(asset=str(asset),group=str(d['group'][part[0]]),state=state,
                    start=int(part[0]),end=int(part[-1]),length=len(part),left_observed=bool(left),right_observed=bool(right),
                    previous_state=int(prior[part[0]]) if left else None,n=int(d['horizon'][part[0]])))
            start=end
    assert sum(s['length'] for s in segments)==int((y>=0).sum())
    assert int(new.sum())==sum(s['left_observed'] for s in segments)
    return segments,age,remaining,prior,new,left_seen


def distribution(d,mask,age,prior,new,left_seen):
    y=d['main_state'];rows=np.flatnonzero(mask);counts=np.bincount(y[rows],minlength=3)
    matrix=np.zeros((3,3),int);risk=rows[prior[rows]>=0]
    np.add.at(matrix,(prior[risk],y[risk]),1)
    events=rows[new[rows]];changes=matrix.copy();np.fill_diagonal(changes,0)
    assert int(changes.sum())==len(events)
    first_two=mask&left_seen&(age>=1)&(age<=2)
    phase=np.array([np.sum(mask&(y==c)&phase_mask) for c in range(3) for phase_mask in
        (left_seen&(age==1),left_seen&(age==2),(age>=3)&(age<d['horizon']),age>=d['horizon'])]).reshape(3,4)
    return dict(rows=len(rows),class_counts=counts.tolist(),class_share=(counts/max(len(rows),1)).tolist(),
        transition_rows=len(events),transition_share=len(events)/max(len(risk),1),first_two_rows=int(first_two.sum()),
        first_two_share=float(first_two.sum()/max(len(rows),1)),no_change_rows=int(np.trace(matrix)),
        transition_matrix=changes.tolist(),daily_transition_matrix=matrix.tolist(),
        phase_columns=['new_day1','new_day2','day3_to_n_minus1','day_n_on'],phase_by_class=phase.tolist(),
        expected_switches_per_random_batch256=256*len(events)/max(len(rows),1))


def duration_summary(segments):
    result=[]
    for group in ('crypto','etf_proxy'):
        for state in (None,0,1,2):
            own=[s for s in segments if s['group']==group and (state is None or s['state']==state)]
            complete=[s for s in own if s['left_observed'] and s['right_observed']]
            length=np.array([s['length'] for s in complete]);n=own[0]['n']
            buckets=[('1-2',length<=2),('3-4',(length>=3)&(length<=4)),('5_to_n-1',(length>=5)&(length<n)),
                     ('n_to_2n-1',(length>=n)&(length<2*n)),('2n_on',length>=2*n)]
            result.append(dict(group=group,state='all' if state is None else STATES[state],observed_spells=len(own),
                complete_spells=len(complete),left_censored=sum(not s['left_observed'] for s in own),
                right_censored=sum(not s['right_observed'] for s in own),n=n,
                mean=float(length.mean()),median=float(np.median(length)),p25=float(np.quantile(length,.25)),
                p75=float(np.quantile(length,.75)),p90=float(np.quantile(length,.9)),maximum=int(length.max()),
                buckets=[dict(name=name,spells=int(mask.sum()),spell_share=float(mask.mean()),days=int(length[mask].sum()),
                    day_share=float(length[mask].sum()/length.sum())) for name,mask in buckets],
                length_counts={str(k):int(sum(length==k)) for k in np.unique(length)}))
    return result


def report(r,output):
    lines=['# 当天状态数据集：类别、持续段与切换分布','',
        '本轮只分析既有数据，不改标签、不改采样、不重训模型。全历史可用分布用于诊断；未来训练权重必须按当折成熟训练数据计算。','',
        f"原始日线{r['raw_rows']:,}条，已标注{r['labeled_rows']:,}条，未标注{r['unlabeled_rows']:,}条。四方案比较沿用n/2n共同历史mask，可用{r['input_ready_rows']:,}条；这是可用于各时点划分的历史样本总量，不是一个静态训练集。",'',
        '## 类别与阶段占比','',
        '|市场|可用样本|上行|下行|震荡|切换当天|新状态前两根|','|---|---:|---:|---:|---:|---:|---:|']
    for s in r['scopes']:
        if s['scope']=='input_ready':lines.append(f"|{s['group']}|{s['rows']}|{s['class_share'][0]:.2%}|{s['class_share'][1]:.2%}|{s['class_share'][2]:.2%}|{s['transition_rows']} / {s['transition_share']:.2%}|{s['first_two_share']:.2%}|")
    lines+=['','普通随机采样多数为延续样本。每批256条预计含切换日币种14.50、ETF22.82；属于少数，但并非几乎不可见。延续标签不是错误标签，长段也不能简单删除；只做三类平衡不能改变同一类内部的起点/延续比例。','',
        '## 训练与测试的切换占比','',
        '|市场|首次训练折 切换/样本|末次训练折 切换/样本|全部训练折切换率范围|测试切换率|','|---|---|---|---|---|']
    for group in ('crypto','etf_proxy'):
        fs=[x for x in r['folds'] if x['group']==group];a=fs[0]['train'];b=fs[-1]['train'];test=next(x for x in r['scopes'] if x['group']==group and x['scope']=='quarterly_test')
        low=min(x['train']['transition_share'] for x in fs);high=max(x['train']['transition_share'] for x in fs)
        lines.append(f"|{group}|{a['transition_rows']}/{a['rows']}|{b['transition_rows']}/{b['rows']}|{low:.2%}–{high:.2%}|{test['transition_share']:.2%}|")
    lines+=['','切换占比跨训练折相对稳定，未见成熟时间清除把切换样本系统性剔除的证据。扩展训练折重复使用历史，不能把各折样本数相加当独立样本。','',
        '## 四种实际切换','',
        '|切换类型|币种事件|ETF代理事件|','|---|---:|---:|']
    for a,b in [(0,2),(2,0),(1,2),(2,1),(0,1),(1,0)]:
        values=[next(x for x in r['transition_types'] if x['group']==g and x['from_state']==STATES[a] and x['to_state']==STATES[b])['events'] for g in ('crypto','etf_proxy')]
        lines.append(f'|{STATES[a]} → {STATES[b]}|{values[0]}|{values[1]}|')
    lines+=['','现有标签的上/下方向反转全部经由震荡，没有直接反转监督样本。这是当前标签定义的分布，不能推断真实市场不会急转。监督切换时不应强行六类等量；币种进入上行209次、下行205次，数量近乎对称。','',
        '## 完整段长度','',
        '只统计前后边界都观察到的真实连续段，不把5天存储块当状态段，也不把截尾段当完整长度。','',
        '|市场|完整段|段长中位数|P25–P75|均值|≤2根 段占比/日占比|≥n根 日占比|','|---|---:|---:|---|---:|---|---:|']
    for s in r['durations']:
        if s['state']!='all':continue
        short=s['buckets'][0];long=sum(x['day_share'] for x in s['buckets'][-2:])
        lines.append(f"|{s['group']}|{s['complete_spells']}|{s['median']:.0f}|{s['p25']:.0f}–{s['p75']:.0f}|{s['mean']:.2f}|{short['spell_share']:.2%} / {short['day_share']:.2%}|{long:.2%}|")
    lines+=['','短段占用的日样本权重很小，继续删1–2根段难以改变训练分布；长度≥n的段贡献约四分之三日样本，逐日损失自然偏重长段内部。币种n14，ETF n10，ETF长度单位为交易日。','',
        '## 切换时的历史方向证据','',
        '在当天标签刚进入新趋势时，检查模型已经知道的历史收盘变化。下表为变化方向与新状态同向的比例，仅作描述，不等于可预测性检验；这些统计没有加入模型输入。','',
        '|市场|新状态|事件|最近1日同向|最近3日同向|过去n根净变化同向|','|---|---|---:|---:|---:|---:|']
    for x in r['history_direction_support']:
        if x['phase']=='switch_day':lines.append(f"|{x['group']}|{x['new_state']}|{x['rows']}|{x['last1_same_direction']:.2%}|{x['last3_same_direction']:.2%}|{x['past_n_candles_same_direction']:.2%}|")
    lines+=['','新趋势起点的整个历史窗口通常仍显示旧方向，而第三根以后的历史n根方向同向比例达到87%–92%。近期1/3日存在一些变化线索，但不能据此断言足够预测未来确认结果。这个条件分布差异比单纯类别不平衡更贴近当前滞后问题；尚不能把它归因于标签错误或证明实时不可识别。','',
        '## 相关性与质量','',
        '相邻n根输入共享币种92.86%、ETF90%的K线；相邻2n标签窗口共享96.43%/95%。大量样本是高度相近的窗口。','']
    for x in r['concurrency']:lines.append(f"- {x['group']}：{x['event_asset_days']}个切换资产日，对应{x['distinct_event_dates']}个日期；这些日期仍非独立事件数。")
    lines+=['','## 研究判断','',
        '先保留三类主状态和原始日线。后续最小对照应在每个成熟训练折内对状态类别、起点/延续阶段及四类切换分别统计或采样；保留自然分布测试，用切换召回、误报、识别延迟评价，防止只提升切换样本而损伤稳定段。段龄可用于离线采样/监督，不能作为实时输入，也不新增“转换待确认”主状态。','',
        '需要先验证起点权重/切换辅助监督的增量，不能仅凭分布就认定某个权重或架构有效。另应检查双侧标签起点与近期可见变化的对齐，而非自动移动边界。完整段长只用于本轮诊断；若以后按段长选训练样本，段结束及确认时间也必须早于训练截止，不能使用最终全数据段长筛选历史训练折。','',
        '## 限制与复现','',*['- '+x for x in r['limitations']],'',
        '```bash',f'PYTHONPATH=src ./.venv/bin/python scripts/research/study_market_state_dataset_distribution.py --output {output}','```','']
    return '\n'.join(lines)


def plot_distribution(r,output):
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import font_manager
    import matplotlib.pyplot as plt
    for font in ('/System/Library/Fonts/Supplemental/Arial Unicode.ttf','/System/Library/Fonts/STHeiti Light.ttc'):
        if Path(font).exists():
            font_manager.fontManager.addfont(font);plt.rcParams['font.family']=font_manager.FontProperties(fname=font).get_name();break
    plt.rcParams['axes.unicode_minus']=False
    fig,axes=plt.subplots(4,2,figsize=(13,16));fig.subplots_adjust(hspace=.5,wspace=.3,top=.92,bottom=.08)
    colors=('#D84A4A','#148B6A','#3979BD');names=('上行','下行','震荡')
    for column,(group,title) in enumerate([('crypto','币种 n=14'),('etf_proxy','ETF代理 n=10')]):
        s=next(x for x in r['scopes'] if x['group']==group and x['scope']=='input_ready')
        values=np.array(s['class_share'])*100;ax=axes[0,column];ax.bar(names,values,color=colors)
        ax.set_title(title+'：主状态占比');ax.set_ylabel('日样本 %');ax.set_ylim(0,70)
        for k,v in enumerate(values):ax.text(k,v+1,f'{v:.2f}%',ha='center')
        phase=np.array(s['phase_by_class']).sum(0);v=np.r_[phase[:2],s['rows']-phase[:2].sum()]/s['rows']*100
        ax=axes[1,column];ax.bar(['切换首根','第二根','其余延续'],v,color=['#D79B25','#D9B66C','#8C969E']);ax.set_ylim(0,100)
        ax.set_title('起点与延续的日样本占比');ax.set_ylabel('日样本 %')
        for k,a in enumerate(v):ax.text(k,a+1,f'{a:.2f}%',ha='center')
        ax=axes[2,column];matrix=np.array(s['transition_matrix']);ax.imshow(matrix,cmap='Blues',vmin=0,vmax=max(matrix.max(),1))
        ax.set_xticks(range(3),names);ax.set_yticks(range(3),names);ax.set_xlabel('新状态');ax.set_ylabel('旧状态');ax.set_title('真实标签切换次数（不含延续）')
        for i in range(3):
            for j in range(3):ax.text(j,i,'—' if i==j else str(matrix[i,j]),ha='center',va='center',color='white' if matrix[i,j]>matrix.max()*.6 else '#303941',fontsize=14)
        duration=next(x for x in r['durations'] if x['group']==group and x['state']=='all');n=duration['n'];b=duration['buckets'];x=np.arange(5)
        ax=axes[3,column];ax.bar(x-.18,[v['spell_share']*100 for v in b],width=.36,label='段数量占比',color='#9365BD')
        ax.bar(x+.18,[v['day_share']*100 for v in b],width=.36,label='日样本占比',color='#3979BD')
        ax.set_xticks(x,['1–2','3–4',f'5–{n-1}',f'{n}–{2*n-1}',f'≥{2*n}']);ax.set_xlabel('完整状态段长度（根日线）');ax.set_ylabel('%');ax.set_title('段数量与样本权重');ax.legend(frameon=False,fontsize=9)
    for ax in np.r_[axes[:2].ravel(),axes[3].ravel()]:
        ax.spines['top'].set_visible(False);ax.spines['right'].set_visible(False);ax.grid(axis='y',alpha=.15)
    fig.suptitle('两周尺度日线数据分布：状态、切换与连续段',fontsize=18,y=.975)
    fig.text(.5,.947,'34,468条共同输入与标签可用记录；完整段统计剔除两端未观察边界',ha='center',fontsize=11)
    fig.text(.08,.025,'切换与段龄均为事后标签诊断，不能直接作为实时输入或交易过滤条件。未修改标签或训练模型。',fontsize=10,color='#50595F')
    fig.savefig(output/'distribution.png',dpi=160);fig.savefig(output/'distribution.svg');plt.close(fig)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=Path('state/research_runs/market_state_current_raw_sequences_20261101'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--plot',action='store_true',help='optional matplotlib PNG/SVG summary')
    args=parser.parse_args()
    if args.output.exists():parser.error('preserve prior analyses')
    with np.load(args.source/'dataset.npz',allow_pickle=False) as z:d={k:z[k] for k in z.files}
    with np.load(args.source/'predictions.npz',allow_pickle=False) as z:p={k:z[k] for k in z.files}
    config=json.loads((args.source/'results.json').read_text());y=d['main_state'];N=len(y)
    assert str(d['target_mode'])=='current' and np.array_equal(d['target_main_state'],y)
    valid=y>=0;ready=d['n_valid']&d['two_n_valid']&d['target_mask'];test=np.isfinite(p['raw_n_gru']).all(1)
    segment,age,remaining,prior,new,left_seen=spells(d)
    scopes=[];folds=[];years=[];assets=[];concurrency=[];evidence=[]
    for group in ('crypto','etf_proxy'):
        group_mask=d['group']==group
        for name,mask in [('all_labeled',valid),('input_ready',ready),('quarterly_test',test)]:
            scopes.append(dict(group=group,scope=name,**distribution(d,group_mask&mask,age,prior,new,left_seen)))
        clock=d['known_at'].astype('datetime64[ms]').astype('datetime64[Y]').astype(str)
        for year in np.unique(clock[group_mask&ready]):
            years.append(dict(group=group,year=str(year),**distribution(d,group_mask&ready&(clock==year),age,prior,new,left_seen)))
        for asset in np.unique(d['asset'][group_mask]):
            assets.append(dict(group=group,asset=str(asset),**distribution(d,ready&(d['asset']==asset),age,prior,new,left_seen)))
        events=np.flatnonzero(group_mask&ready&new);dates=d['known_at'][events]//86400000
        _,counts=np.unique(dates,return_counts=True)
        concurrency.append(dict(group=group,event_asset_days=len(events),distinct_event_dates=len(counts),
            event_days_on_dates_with_multiple_assets=int(counts[counts>=2].sum()),
            maximum_assets_switching_same_date=int(counts.max()),
            concurrent_date_counts={str(k):int(sum(counts==k)) for k in np.unique(counts)}))
        # Descriptive historical support for the hindsight new state, never model features.
        rows=np.flatnonzero(group_mask&ready);n=int(d['horizon'][rows[0]])
        raw=d['n_raw_ohlcv'][rows,-n:];closes=np.log(raw[:,:,3])
        returns={'last1':closes[:,-1]-closes[:,-2], 'last3':closes[:,-1]-closes[:,-4],
                 'past_n_candles':closes[:,-1]-closes[:,0]}
        for phase,mask in [('switch_day',new[rows]),('new_first_two',left_seen[rows]&(age[rows]<=2)),('day_three_on',age[rows]>=3)]:
            for state in (0,1):
                own=mask&(y[rows]==state);sign=1 if state==0 else -1
                record=dict(group=group,phase=phase,new_state=STATES[state],rows=int(own.sum()))
                for name,values in returns.items():
                    record[name+'_same_direction']=float(np.mean(values[own]*sign>0))
                    record[name+'_median_log_return']=float(np.median(values[own]))
                evidence.append(record)
    for fold in config['folds']:
        group=fold['group'];members=np.flatnonzero((d['group']==group)&ready)
        train,evaluation=purged_quarter(members,d['known_at'],d['target_available_at'],fold['cutoff'],fold['end'])
        assert len(train)==fold['training_rows'] and len(evaluation)==fold['test_rows']
        assert d['target_available_at'][train].max()<fold['cutoff']
        train_mask=np.zeros(N,bool);train_mask[train]=True;test_mask=np.zeros(N,bool);test_mask[evaluation]=True
        folds.append(dict(group=group,cutoff=fold['cutoff'],end=fold['end'],
            train=distribution(d,train_mask,age,prior,new,left_seen),test=distribution(d,test_mask,age,prior,new,left_seen)))
    # Exact observed transition-type counts, including preceding/following duration support.
    transitions=[]
    for asset in np.unique(d['asset']):
        own=[s for s in segment if s['asset']==asset]
        for before,after in zip(own,own[1:]):
            if not after['left_observed']:continue
            assert before['state']==after['previous_state'] and before['end']+1==after['start']
            transitions.append(dict(asset=str(asset),group=after['group'],row=after['start'],from_state=before['state'],
                to_state=after['state'],previous_observed_length=before['length'],next_observed_length=after['length'],
                previous_complete=before['left_observed'] and before['right_observed'],
                next_complete=after['left_observed'] and after['right_observed'],
                input_ready=bool(ready[after['start']]),evaluation=bool(test[after['start']]),
                available_at=int(d['label_available_at'][after['start']])))
    assert len(transitions)==int(new.sum())
    events=[]
    for group in ('crypto','etf_proxy'):
        for a in range(3):
            for b in range(3):
                if a==b:continue
                own=[t for t in transitions if t['group']==group and t['from_state']==a and t['to_state']==b and t['input_ready']]
                length=np.array([t['next_observed_length'] for t in own if t['next_complete']])
                events.append(dict(group=group,from_state=STATES[a],to_state=STATES[b],events=len(own),
                    complete_next_spells=len(length),next_median_length=float(np.median(length)) if len(length) else None,
                    next_short_le2=int(sum(length<=2))))
    volume_quality=[]
    for group in ('crypto','etf_proxy'):
        mask=(d['group']==group)&ready
        volume_quality.append(dict(group=group,zero_volume_rows=int(sum(mask&(d['ohlcv'][:,4]==0))),
            zero_volume_switch_days=int(sum(mask&new&(d['ohlcv'][:,4]==0))),
            input_window_shared_fraction=(int(d['horizon'][mask][0])-1)/int(d['horizon'][mask][0]),
            target_window_shared_fraction=(2*int(d['horizon'][mask][0])-1)/(2*int(d['horizon'][mask][0]))))
    result=dict(research_only=True,orders_authorized=False,source=str(args.source),states=STATES,
        raw_rows=N,labeled_rows=int(valid.sum()),input_ready_rows=int(ready.sum()),unlabeled_rows=int((~valid).sum()),
        scopes=scopes,durations=duration_summary(segment),transition_types=events,folds=folds,years=years,assets=assets,
        concurrency=concurrency,history_direction_support=evidence,quality_and_overlap=volume_quality,
        definitions=dict(switch_day='S_n(k) differs from previous valid S_n(k-1), no new training class',
            first_two='first two observed days after a known labeled predecessor; descriptive hindsight age only',
            complete_spell='both preceding and following labels observed and different; no storage chunks',
            input_ready='same n and 2n history masks used by current model comparison',
            history_direction='sign of historical 1-day/3-day or n-candle close change; a descriptive proxy, not proof of observability',
            maturity='same-day S_n(k) label matures at k+n; per-fold distribution uses only mature training labels'),
        limitations=['No labels, inputs, sampling weights or models changed; no new neural training.',
            'Full-spell duration, true age and switch flags use hindsight labels; never inference features or live filters.',
            'Boundary dates inherit the retrospective label definition and do not prove a real economic transition.',
            'Historical-return sign is not sufficient to determine whether a change could have been predicted.',
            'Expanding training folds reuse historical rows; summing their sizes does not give independent sample count.'])
    args.output.mkdir(parents=True)
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (args.output/'report.md').write_text(report(result,args.output))
    if args.plot:plot_distribution(result,args.output)
    np.savez_compressed(args.output/'annotations.npz',asset=d['asset'],group=d['group'],known_at=d['known_at'],
        state=y,age=age,remaining_observed=remaining,previous_state=prior,switch_day=new,observed_predecessor=left_seen,
        input_ready=ready,evaluation=test,research_only=True,orders_authorized=False,hindsight_diagnostics_only=True)
    print('saved',args.output)
    for s in scopes:
        print(s['group'],s['scope'],'rows',s['rows'],'class',s['class_counts'],'switch',s['transition_rows'],s['transition_share'],'first2',s['first_two_rows'],s['first_two_share'])
    for s in result['durations']:
        if s['state']=='all':print('durations',s)
    print('transition types',events)
    print('concurrency',concurrency)


if __name__=='__main__':main()
