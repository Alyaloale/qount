"""Paired quarterly GRU comparison of existing vs window-relative activity.

Same complete native-nine dataset, current-state labels, mature training rows,
architecture, optimizer, epoch count and random seeds. No default input change.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import time

import numpy as np
import torch
from threadpoolctl import threadpool_limits

from qount.research.market_state_dataset import CurrentStateDataset,DEFAULT_ROOT
from qount.research.market_state_flows import center_asset_activity,relative_activity_windows
from qount.research.market_state_neural import fit_gru
from compare_market_state_factorizations import asset_frequency,classification_metrics

MODES=('existing','relative_activity')


def metrics(y,p,reference):
    result=classification_metrics(y,p,reference)
    pred=p.argmax(1);confusion=np.zeros((3,3),int)
    np.add.at(confusion,(y,pred),1)
    tp=confusion.diagonal();denom=confusion.sum(0)+confusion.sum(1)
    f1=np.divide(2*tp,denom,out=np.zeros(3,float),where=denom>0)
    result.update(macro_f1=float(f1.mean()),class_f1=f1.tolist(),confusion=confusion.tolist())
    return result


def evaluate(d,rows,p,reference):
    y=d['state'][rows];switch=d['switch_label'][rows]
    result=metrics(y,p,reference)
    result['switch']=metrics(y[switch],p[switch],reference[switch]) if switch.any() else None
    result['continuation']=metrics(y[~switch],p[~switch],reference[~switch]) if (~switch).any() else None
    result['switch_old_state_share']=float(np.mean(p[switch].argmax(1)==d['previous_state_label'][rows[switch]])) if switch.any() else None
    for name,mask in [('trend_switch',switch&(y!=2)),('sideways_switch',switch&(y==2))]:
        result[name+'_rows']=int(mask.sum())
        result[name+'_accuracy']=float(np.mean(p[mask].argmax(1)==y[mask])) if mask.any() else None
    return result


def paired_blocks(d,rows,probabilities,block,draws=2000):
    """Circular date-block bootstrap, keeping all assets and seeds together.

    The history is consumed and blocks only approximate serial dependence;
    intervals describe sensitivity, not independent validation or causal proof.
    """
    y=d['state'][rows];hot=np.eye(3)[y];switch=d['switch_label'][rows]
    accuracy=(probabilities[:,:,rows].argmax(3)==y).mean(0)
    error=((probabilities[:,:,rows]-hot)**2).sum(3).mean(0)
    _,date=np.unique(d['decision_at'][rows],return_inverse=True);days=int(date.max())+1
    count=np.bincount(date,minlength=days);switch_count=np.bincount(date,weights=switch,minlength=days)
    changes=dict(accuracy=accuracy[1]-accuracy[0],brier=error[1]-error[0],switch_accuracy=(accuracy[1]-accuracy[0])*switch)
    rng=np.random.default_rng(20261101+block)
    starts=rng.integers(0,days,size=(draws,int(np.ceil(days/block))))
    selected=((starts[:,:,None]+np.arange(block))%days).reshape(draws,-1)[:,:days]
    result={}
    for name,values in changes.items():
        totals=np.bincount(date,weights=values,minlength=days);weights=switch_count if name=='switch_accuracy' else count
        numerator=totals[selected].sum(1);denominator=weights[selected].sum(1)
        samples=numerator[denominator>0]/denominator[denominator>0]
        result[name]=dict(relative_minus_existing=float(totals.sum()/weights.sum()),interval95=np.quantile(samples,[.025,.975]).tolist())
    return dict(block_dates=block,draws=draws,common_dates=days,changes=result)


def summarize(d,probabilities,reference,fold,seeds):
    valid=np.isfinite(probabilities).all((0,1,3));rows=np.flatnonzero(valid)
    records=[]
    for i,seed in enumerate(seeds):
        for j,mode in enumerate(MODES):
            p=probabilities[i,j]
            record=dict(mode=mode,seed=seed,overall=evaluate(d,rows,p[rows],reference[rows]),
                per_asset={},per_quarter={})
            for a in np.unique(d['asset'][rows]):
                ix=rows[d['asset'][rows]==a];record['per_asset'][str(a)]=evaluate(d,ix,p[ix],reference[ix])
            for q in np.unique(fold[rows]):
                ix=rows[fold[rows]==q]
                record['per_quarter'][str(int(q))]=evaluate(d,ix,p[ix],reference[ix])
            records.append(record)
    scalar=('accuracy','balanced_accuracy','macro_f1','brier','log_loss','brier_skill','switch_old_state_share','trend_switch_accuracy','sideways_switch_accuracy')
    means={}
    for mode in MODES:
        group=[x for x in records if x['mode']==mode]
        average={k:float(np.mean([x['overall'][k] for x in group])) for k in scalar}
        for phase in ('switch','continuation'):
            average[phase]={k:float(np.mean([x['overall'][phase][k] for x in group])) for k in ('accuracy','balanced_accuracy','macro_f1','brier')}
        average['class_recall']=np.mean([x['overall']['class_recall'] for x in group],axis=0).tolist()
        means[mode]=average
    comparisons={}
    for key in ('per_asset','per_quarter'):
        group={}
        for unit in records[0][key]:
            unit_means={mode:{k:float(np.mean([x[key][unit][k] for x in records if x['mode']==mode])) for k in ('accuracy','brier','macro_f1')} for mode in MODES}
            group[unit]=unit_means
        comparisons[key]=group
    return dict(rows=len(rows),first_decision=str(d['decision_at'][rows].min().astype('datetime64[ms]')),
        last_decision=str(d['decision_at'][rows].max().astype('datetime64[ms]')),switch_rows=int(d['switch_label'][rows].sum()),
        records=records,seed_mean=means,comparisons=comparisons,
        frequency=metrics(d['state'][rows],reference[rows],reference[rows]),
        paired_intervals=[paired_blocks(d,rows,probabilities,block) for block in (28,56)])


def write_report(result,out):
    summary=result['summary'];means=summary['seed_mean'];candidate=result['modes'][1]
    a=means['existing'];b=means[candidate]
    if b['accuracy']<a['accuracy'] and b['brier']>a['brier']:
        verdict='本轮候选方案的整体准确率降低、Brier变差，尚不支持替换现有默认归一化；均衡指标与切换方向需单独看。'
    else:verdict='按整体、类别和切换方向分别比较；本轮是已消费历史对照，尚需未消费数据验证。'
    transform=('以输入窗口总量/总额/笔数中位数作参考后取对数' if candidate=='relative_activity'
        else '先按现有方式log1p，再减去该标的成熟训练样本总量/总额/笔数的均值，不减去各窗口活动水平')
    lines=['# 标的间活动归一化对照','',verdict,'',
        f"完整7币种，{summary['rows']:,}条共同测试记录，其中切换首日{summary['switch_rows']}条；决策时间{summary['first_decision']}至{summary['last_decision']} UTC。",
        f"每季度扩展训练，训练标签必须在季度开始前成熟。14根×9通道，GRU32、标的嵌入4、20轮，随机种子{result['seeds']}；模型及训练顺序配对一致。",
        f'候选方案：`{candidate}`。价格均为相对窗口首根收盘价的对数。现有方案对五个活动字段log1p；对照方案{transform}，主动买入字段共用对应总量参考。两组随后均只在训练折拟合通道均值/标准差。',
        '以下指标为各随机种子指标的均值，不是集成模型。未改变标签、缺失字段范围或默认数据入口。','',
        '| 指标 | 现有归一化 | 候选归一化 | 候选−现有 |','|---|---:|---:|---:|']
    for key,title,percent in [('accuracy','准确率',True),('balanced_accuracy','平衡准确率',True),('macro_f1','宏F1',False),('brier','Brier（低优）',False),('brier_skill','相对频率基线Brier改善',True)]:
        a=means['existing'][key];b=means[candidate][key]
        lines.append(f'| {title} | {a:.2%} | {b:.2%} | {(b-a)*100:+.2f}个百分点 |' if percent else f'| {title} | {a:.4f} | {b:.4f} | {b-a:+.4f} |')
    for phase,title in [('switch','切换首日准确率'),('continuation','延续日准确率')]:
        a=means['existing'][phase]['accuracy'];b=means[candidate][phase]['accuracy']
        lines.append(f'| {title} | {a:.2%} | {b:.2%} | {(b-a)*100:+.2f}个百分点 |')
    for key,title in [('trend_switch_accuracy','切换进入上/下行首日准确率'),('sideways_switch_accuracy','切换进入震荡首日准确率')]:
        a=means['existing'][key];b=means[candidate][key]
        lines.append(f'| {title} | {a:.2%} | {b:.2%} | {(b-a)*100:+.2f}个百分点 |')
    lines += ['',f"资产历史状态频率基线准确率：{summary['frequency']['accuracy']:.2%}。",'',
        '| 主状态召回 | 现有归一化 | 候选归一化 |','|---|---:|---:|']
    for j,name in enumerate(('上行','下行','震荡')):
        lines.append(f"| {name} | {means['existing']['class_recall'][j]:.2%} | {means[candidate]['class_recall'][j]:.2%} |")
    predicted={mode:np.asarray([x['overall']['confusion'] for x in summary['records'] if x['mode']==mode]).sum((0,1))/(summary['rows']*len(result['seeds'])) for mode in result['modes']}
    lines += ['', '| 模型预测类别占比 | 现有归一化 | 候选归一化 |','|---|---:|---:|']
    for j,name in enumerate(('上行','下行','震荡')):
        lines.append(f"| {name} | {predicted['existing'][j]:.2%} | {predicted[candidate][j]:.2%} |")
    lines += ['', '切换首日也需分进入方向评价，不能用进入震荡的较高识别率掩盖新趋势起点失败。','',
        '| 切换进入状态 | 测试样本数 | 现有首日召回 | 候选首日召回 |','|---|---:|---:|---:|']
    for j,name in enumerate(('上行','下行','震荡')):
        recalls={mode:float(np.mean([x['overall']['switch']['class_recall'][j] for x in summary['records'] if x['mode']==mode])) for mode in result['modes']}
        count=summary['records'][0]['overall']['switch']['actual_counts'][j]
        lines.append(f"| {name} | {count} | {recalls['existing']:.2%} | {recalls[candidate]:.2%} |")
    lines += ['', '## 随机种子复核','', '| 种子 | 现有准确率 | 候选准确率 | 现有Brier | 候选Brier | 现有切换准确率 | 候选切换准确率 |','|---|---:|---:|---:|---:|---:|---:|']
    for seed in result['seeds']:
        group={x['mode']:x['overall'] for x in summary['records'] if x['seed']==seed};a=group['existing'];b=group[candidate]
        lines.append(f"| {seed} | {a['accuracy']:.2%} | {b['accuracy']:.2%} | {a['brier']:.4f} | {b['brier']:.4f} | {a['switch']['accuracy']:.2%} | {b['switch']['accuracy']:.2%} |")
    for key,title in [('per_asset','币种'),('per_quarter','季度开始日（UTC）')]:
        lines += ['',f'## 按{title}比较','',f'| {title} | 现有准确率 | 候选准确率 | 准确率变化（百分点） | Brier变化（负为改善） |','|---|---:|---:|---:|---:|']
        for name,unit in summary['comparisons'][key].items():
            a=unit['existing'];b=unit[candidate]
            if key=='per_quarter':name=dt.datetime.fromtimestamp(int(name)/1000,dt.timezone.utc).date().isoformat()
            lines.append(f"| {name} | {a['accuracy']:.2%} | {b['accuracy']:.2%} | {100*(b['accuracy']-a['accuracy']):+.2f} | {b['brier']-a['brier']:+.4f} |")
    lines += ['', '## 按日期分块的配对差异区间','',
        '先对种子取均值差，再将同一天的所有币种作为整体，用连续28/56日循环分块bootstrap各2,000次。区间只近似处理时间依赖，不能替代未消费的未来数据。','',
        '| 块长（日） | 指标 | 相对−现有 | 95%区间 |','|---|---|---:|---|']
    for record in summary['paired_intervals']:
        for key,title in [('accuracy','准确率'),('brier','Brier'),('switch_accuracy','切换首日准确率')]:
            v=record['changes'][key];factor=1 if key=='brier' else 100;lo,hi=np.array(v['interval95'])*factor
            lines.append(f"| {record['block_dates']} | {title}{'（百分点）' if factor==100 else ''} | {factor*v['relative_minus_existing']:+.4f} | [{lo:+.4f}, {hi:+.4f}] |")
    lines += ['', '## 解释范围','',
        '这是同一已消费历史上的时间前推、配对研究对照；不宣称独立样本外证明。测试期标签从未用于对应折的训练或标准化，但该历史已被研究，结论需未来数据检验。',
        '只改变活动尺度处理，不能据此评价其他模型或所有归一化方式。窗口中位数会消除部分持续活动水平信息；训练期按标的居中仍未整体胜出，故不能把失败原因仅归结为窗口信息损失。表现差异仍含优化过程和表示方式差异。',
        '状态切换及旧状态滞留率仅事后评价，未作为模型输入。没有交易回测，未新增收益、费用或执行结论。原始完整数据及既有默认归一化不变。',
        '配置、逐折损失、每币种/季度/种子分解见results.json；逐条配对概率见predictions.npz；latest_*权重仅为各方案各种子的最后一折，不是生产模型。']
    (out/'report.md').write_text('\n'.join(lines)+'\n')


def main():
    global MODES
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,default=DEFAULT_ROOT);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seeds',type=int,nargs='+',default=[17,29,43]);parser.add_argument('--epochs',type=int,default=20)
    parser.add_argument('--max-seconds',type=int,default=1800);parser.add_argument('--max-folds',type=int)
    parser.add_argument('--candidate',choices=('relative_activity','asset_centered'),default='relative_activity')
    parser.add_argument('--reuse-existing',type=Path,help='Reuse the identical completed baseline fits and probabilities')
    args=parser.parse_args()
    if args.output.exists():parser.error('preserve existing experiments')
    if args.epochs!=20 or len(set(args.seeds))!=len(args.seeds):parser.error('fixed 20 epochs and distinct seeds required')
    MODES=('existing',args.candidate)
    ds=CurrentStateDataset(args.dataset);d=ds.data;rows=np.arange(len(d['state']));raw=ds.inputs(rows,scaled=False)['market']
    sequences=[ds.inputs(rows)['market'],relative_activity_windows(raw) if args.candidate=='relative_activity' else None]
    if sequences[1] is not None:np.testing.assert_array_equal(sequences[0][:,:,:4],sequences[1][:,:,:4])
    asset=ds.asset_index;y=d['state'];source_hash=hashlib.sha256((args.dataset/'dataset.npz').read_bytes()).hexdigest()
    stamps=[dt.datetime.fromtimestamp(int(t)/1000,dt.timezone.utc) for t in d['decision_at']]
    quarters=sorted({(t.year,(t.month-1)//3*3+1) for t in stamps if t.year>=2023})
    if args.max_folds:quarters=quarters[:args.max_folds]
    probabilities=np.full((len(args.seeds),2,len(rows),3),np.nan);reference=np.full((len(rows),3),np.nan);fold=np.full(len(rows),-1,np.int64)
    fits=[]
    if args.reuse_existing:
        old=json.loads((args.reuse_existing/'results.json').read_text())
        if old['dataset_sha256']!=source_hash or old['seeds']!=args.seeds or old['epochs']!=args.epochs:
            raise ValueError('incompatible_reused_comparison')
        with np.load(args.reuse_existing/'predictions.npz',allow_pickle=False) as saved:
            np.testing.assert_array_equal(saved['source_row'],d['source_row'])
            assert saved['modes'][0]=='existing'
            probabilities[:,0]=saved['probabilities'][:,0]
        fits=[x for x in old['fits'] if x['mode']=='existing']
    args.output.mkdir(parents=True)
    if args.reuse_existing:
        for seed in args.seeds:shutil.copy2(args.reuse_existing/f'latest_existing_{seed}.pt',args.output/f'latest_existing_{seed}.pt')
    start=time.monotonic();torch.set_num_threads(2);torch.use_deterministic_algorithms(True)
    for year,month in quarters:
        cutoff=int(dt.datetime(year,month,1,tzinfo=dt.timezone.utc).timestamp())*1000
        end=int(dt.datetime(year+int(month==10),1 if month==10 else month+3,1,tzinfo=dt.timezone.utc).timestamp())*1000
        train,test=ds.split(cutoff,end)
        if len(train)<200 or not len(test):continue
        assert d['label_available_at'][train].max()<cutoff
        reference[test]=asset_frequency(y,d['asset'],train,test,3);fold[test]=cutoff
        activity_centers=None
        if args.candidate=='asset_centered':sequences[1],activity_centers=center_asset_activity(sequences[0],asset,train)
        for i,seed in enumerate(args.seeds):
            for j,mode in enumerate(MODES):
                if j==0 and args.reuse_existing:
                    assert np.isfinite(probabilities[i,j,test]).all()
                    continue
                if time.monotonic()-start>args.max_seconds:raise RuntimeError('comparison_budget_exceeded_preserved_predictions')
                fit_start=time.monotonic()
                p,detail,checkpoint=fit_gru(sequences[j],asset,y,train,test,assets=len(ds.asset_names),epochs=args.epochs,seed=seed)
                detail.pop('train_prediction');probabilities[i,j,test]=p
                checkpoint['mean']=torch.as_tensor(checkpoint['mean']);checkpoint['scale']=torch.as_tensor(checkpoint['scale'])
                checkpoint.update(normalization=mode,seed=seed,cutoff=cutoff,dataset_schema=str(d['schema']),asset_names=ds.asset_names,
                    target_mode='current',lookback='n',input_length=sequences[j].shape[1],research_only=True,orders_authorized=False)
                if j==1 and activity_centers is not None:checkpoint['activity_centers']=torch.as_tensor(activity_centers)
                torch.save(checkpoint,args.output/f'latest_{mode}_{seed}.pt')
                record=dict(year=year,quarter_month=month,cutoff=cutoff,mode=mode,seed=seed,training_rows=len(train),test_rows=len(test),
                    latest_training_label=int(d['label_available_at'][train].max()),seconds=time.monotonic()-fit_start,**detail)
                fits.append(record)
                print(f"fit {year}-{month:02d} seed={seed} {mode} train={len(train)} test={len(test)} seconds={record['seconds']:.1f}",flush=True)
                np.savez_compressed(args.output/'predictions.npz',probabilities=probabilities,reference=reference,fold_id=fold,
                    source_row=d['source_row'],modes=np.array(MODES),seeds=np.array(args.seeds),research_only=True,orders_authorized=False)
    assert source_hash==hashlib.sha256((args.dataset/'dataset.npz').read_bytes()).hexdigest()
    result=dict(research_only=True,orders_authorized=False,dataset=str(args.dataset),dataset_sha256=source_hash,
        source_unchanged=True,seeds=args.seeds,epochs=args.epochs,modes=list(MODES),independent_oos=False,
        reused_existing=str(args.reuse_existing) if args.reuse_existing else None,
        environment=dict(torch=str(torch.__version__),numpy=np.__version__,threads=2,deterministic=True),
        model=dict(hidden=32,asset_embedding=4,dropout=.1,optimizer='AdamW',learning_rate=.001,weight_decay=.001,batch_size=256),
        fits=fits,elapsed_seconds=time.monotonic()-start,summary=summarize(d,probabilities,reference,fold,args.seeds))
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    write_report(result,args.output);print(json.dumps(result['summary']['seed_mean'],ensure_ascii=False),flush=True)


if __name__=='__main__':
    with threadpool_limits(limits=1):main()
