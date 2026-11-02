"""Learn three-state forecasts directly from ordered daily OHLCV windows."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from pathlib import Path

import numpy as np
import sklearn
import torch
from threadpoolctl import threadpool_limits

from qount.research.market_learning import fit_candidate
from qount.research.market_state_neural import OHLCVGRU,forecast,fit_gru
from qount.research.market_state_factorization import purged_quarter
from qount.research.market_state_sequence import CHANNELS,model_window,raw_window,same_day_targets
from compare_market_state_factorizations import asset_frequency,classification_metrics,paired_interval



def sequences(d,multiple):
    count=len(d['asset']);max_length=int(max(d['horizon']))*multiple
    raw=np.full((count,max_length,5),np.nan,np.float64);normalized=np.full_like(raw,np.nan,dtype=np.float32)
    rows=np.full((count,max_length),-1,np.int64);valid=np.zeros(count,bool)
    for a in np.unique(d['asset']):
        ix=np.flatnonzero(d['asset']==a);length=int(d['horizon'][ix[0]])*multiple
        values=d['ohlcv'][ix]
        assert np.all(np.diff(d['known_at'][ix])>0) and np.all(d['horizon'][ix]==length//multiple)
        for k,row in enumerate(ix):
            window=raw_window(values,k,length)
            if window is None:continue
            raw[row,-length:]=window;normalized[row,-length:]=model_window(window)
            rows[row,-length:]=ix[k-length+1:k+1];valid[row]=True
    return raw,normalized,rows,valid


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=Path('state/research_runs/market_state_factorization_20261031_comparison'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--target',choices=('current','next-cycle'),default='current',
        help='current: S_n(k), label matures k+n; next-cycle retains historical S_n(k+n) contrast')
    parser.add_argument('--epochs',type=int,default=20);parser.add_argument('--max-seconds',type=int,default=1200)
    args=parser.parse_args()
    if args.output.exists():parser.error('preserve prior results; choose another output')
    if args.epochs<1:parser.error('positive epochs required')
    torch.set_num_threads(2);torch.use_deterministic_algorithms(True)
    start=time.monotonic()
    with np.load(args.source/'dataset.npz',allow_pickle=False) as z:d={k:z[k] for k in z.files}
    with np.load(args.source/'predictions.npz',allow_pickle=False) as z:previous={k:z[k] for k in z.files}
    original=json.loads((args.source/'results.json').read_text());N=len(d['asset'])
    if args.target=='current':
        targets=same_day_targets(d['merged_three'],d['attributes'],d['label_available_at'])
    else:
        targets=dict(target_main_state=d['target_merged_three'],**{name:d[name] for name in
            ('target_attributes','target_row','target_mask','target_available_at')})
    y=targets['target_main_state'];maturity=targets['target_available_at']
    nraw,nx,nrows,nvalid=sequences(d,1);tworaw,twox,tworows,twovalid=sequences(d,2)
    ready=np.isfinite(d['X']).all(1)&nvalid&twovalid&targets['target_mask']
    source_test_mask=np.isfinite(previous['merged_three_probabilities']).all(1)
    assert np.all(ready[source_test_mask])
    args.output.mkdir(parents=True)
    np.savez_compressed(args.output/'dataset.npz',research_only=True,orders_authorized=False,label_uses_future=True,
        asset=d['asset'],group=d['group'],known_at=d['known_at'],ohlcv=d['ohlcv'],horizon=d['horizon'],
        channels=np.array(CHANNELS),n_raw_ohlcv=nraw,n_model_ohlcv=nx,n_window_rows=nrows,n_valid=nvalid,
        two_n_raw_ohlcv=tworaw,two_n_model_ohlcv=twox,two_n_window_rows=tworows,two_n_valid=twovalid,
        main_state=d['merged_three'],attributes=d['attributes'],attribute_names=d['attribute_names'],
        label_available_at=d['label_available_at'],**targets,target_mode=np.array(args.target),
        main_state_names=d['main_state_names'],feature_available_at=d['known_at'])
    variants=('summary_tree','raw_n_tree','raw_n_gru','raw_2n_gru')
    pred={name:np.full((N,3),np.nan) for name in variants}
    frequency=np.full((N,3),np.nan);quarter_id=np.full(N,-1,np.int64);test_mask=np.zeros(N,bool)
    if args.target=='next-cycle':
        pred['summary_tree']=previous['merged_three_probabilities'].copy()
        specifications=original['folds']
    else:
        specifications=[]
        for group in ('crypto','etf_proxy'):
            times=d['known_at'][(d['group']==group)&ready]
            stamps=[dt.datetime.fromtimestamp(int(t)/1000,dt.timezone.utc) for t in times]
            quarters=sorted({(s.year,(s.month-1)//3*3+1) for s in stamps if s.year>=2023})
            for year,month in quarters:
                cutoff=int(dt.datetime(year,month,1,tzinfo=dt.timezone.utc).timestamp())*1000
                end=int(dt.datetime(year+int(month==10),1 if month==10 else month+3,1,tzinfo=dt.timezone.utc).timestamp())*1000
                specifications.append(dict(group=group,cutoff=cutoff,end=end))
    folds=[]
    for fold in specifications:
        if time.monotonic()-start>args.max_seconds:raise RuntimeError('bounded training budget exhausted')
        group=fold['group'];cutoff=fold['cutoff'];end=fold['end']
        members=np.flatnonzero((d['group']==group)&ready)
        train,test=purged_quarter(members,d['known_at'],maturity,cutoff,end)
        if len(train)<200 or not len(test):continue
        if args.target=='next-cycle':
            assert len(train)==fold['training_rows'] and len(test)==fold['test_rows']
            assert np.all(source_test_mask[test])
        assert maturity[train].max()<cutoff and not test_mask[test].any()
        test_mask[test]=True;quarter_id[test]=cutoff
        frequency[test]=asset_frequency(y,d['asset'],train,test,3)
        names=np.unique(d['asset'][members]);identity=np.array([[a==name for name in names] for a in d['asset']],np.float32)
        asset=np.argmax(identity,axis=1).astype(np.int64);length=int(d['horizon'][test[0]])
        seq_n=np.ascontiguousarray(nx[:,-length:]);seq_two=np.ascontiguousarray(twox[:,-2*length:])
        if args.target=='current':
            matrix=np.c_[d['X'],identity];model,_=fit_candidate('tree',matrix[train],y[train],seed=17)
            p=np.full((len(test),3),.01/3);p[:,model[-1].classes_.astype(int)]+=.99*model.predict_proba(matrix[test])
            pred['summary_tree'][test]=p
        # Same shallow tree as the summary contrast; each lag/column remains distinct.
        matrix=np.c_[seq_n.reshape(N,-1),identity]
        model,_=fit_candidate('tree',matrix[train],y[train],seed=17)
        p=np.full((len(test),3),.01/3);p[:,model[-1].classes_.astype(int)]+=.99*model.predict_proba(matrix[test]);pred['raw_n_tree'][test]=p
        training={}
        for name,sequence in [('raw_n_gru',seq_n),('raw_2n_gru',seq_two)]:
            p,detail,checkpoint=fit_gru(sequence,asset,y,train,test,assets=len(names),epochs=args.epochs,seed=17)
            pred[name][test]=p;train_p=detail.pop('train_prediction')
            detail['train_accuracy']=float(np.mean(train_p.argmax(1)==y[train]));training[name]=detail
            checkpoint.update(asset_names=names.tolist(),cutoff=cutoff,input_length=sequence.shape[1],channels=CHANNELS,
                main_state_names=d['main_state_names'].tolist(),target_mode=args.target,
                label_maturity='k+n' if args.target=='current' else 'k+2n',research_only=True,orders_authorized=False)
            torch.save(checkpoint,args.output/f'{group}_{name}_latest.pt')
        folds.append(dict(group=group,cutoff=cutoff,end=end,training_rows=len(train),test_rows=len(test),
            latest_training_target=int(maturity[train].max()),training=training))
        np.savez_compressed(args.output/'predictions.npz',**pred,quarter_id=quarter_id,frequency=frequency,
            target_mode=np.array(args.target),source_test_mask=source_test_mask,
            main_state_names=d['main_state_names'],research_only=True,orders_authorized=False)
        print(group,cutoff,'train',len(train),'test',len(test),'elapsed',round(time.monotonic()-start,1),flush=True)
    metrics=[];paired=[];yearly=[]
    position=np.zeros(N,np.int64)
    for a in np.unique(d['asset']):
        own=np.flatnonzero(d['asset']==a);position[own]=np.arange(len(own))
    for group in ('crypto','etf_proxy'):
        ix=np.flatnonzero(test_mask&(d['group']==group));ref=frequency[ix]
        for name in variants:
            assert np.array_equal(np.isfinite(pred[name]).all(1),test_mask)
            stats=classification_metrics(y[ix],pred[name][ix],ref)
            stats['frequency_accuracy']=float(np.mean(ref.argmax(1)==y[ix]))
            one=np.eye(3)[y[ix]]
            delta_frequency=np.sum((pred[name][ix]-one)**2,1)-np.sum((ref-one)**2,1)
            stats['versus_frequency_brier']=paired_interval(delta_frequency,quarter_id[ix])
            nonoverlap=position[ix]%(2*int(d['horizon'][ix[0]]))==0
            stats['nonoverlap']=classification_metrics(y[ix][nonoverlap],pred[name][ix][nonoverlap],ref[nonoverlap])
            common=source_test_mask[ix]
            stats['source_common_dates']=classification_metrics(y[ix][common],pred[name][ix][common],ref[common])
            metrics.append(dict(group=group,variant=name,**stats))
            base=pred['summary_tree'][ix];one=np.eye(3)[y[ix]]
            delta=np.sum((pred[name][ix]-one)**2,1)-np.sum((base-one)**2,1)
            paired.append(dict(group=group,variant=name,versus_summary_brier=paired_interval(delta,quarter_id[ix])))
            years=d['known_at'][ix].astype('datetime64[ms]').astype('datetime64[Y]').astype(str)
            for year in np.unique(years):
                chosen=years==year
                yearly.append(dict(group=group,variant=name,year=year,**classification_metrics(y[ix][chosen],pred[name][ix][chosen],ref[chosen])))
    result=dict(research_only=True,orders_authorized=False,independent_oos=False,source=str(args.source),
        versions=dict(torch=torch.__version__,numpy=np.__version__,sklearn=sklearn.__version__),
        parameters=dict(channels=CHANNELS,sequence_order='oldest to current completed daily candle',
            target_mode=args.target,target_state='S_n(k)' if args.target=='current' else 'S_n(k+n)',
            target_maturity='k+n' if args.target=='current' else 'k+2n',
            windows={'crypto':[14,28],'etf_proxy':[10,20]},normalization='log OHLC relative to first window close; log1p volume; GRU channel mean/std fit on each training fold only',
            gru='one layer, hidden32, asset embedding4, layernorm/dropout0.1/linear3 head',
            training=dict(epochs=args.epochs,batch=256,optimizer='AdamW',lr=.001,weight_decay=.001,gradient_clip=1,seed=17,device='cpu',threads=2),
            feature_indicators_in_gru=False,test_selection=False,attributes_retrained=False),
        metrics=metrics,paired=paired,yearly=yearly,folds=folds,elapsed_seconds=time.monotonic()-start,
        limitations=['All historical folds are consumed; no independent unseen test or trading backtest.',
            'Raw n tree isolates input change versus the same summary learner; GRU changes both representation and learner.',
            'Models use five OHLCV channels, not manual technical indicators. Asset identity is a separate learned embedding/onehot.',
            'Input windows contain only completed candles through k. Same-day hindsight S_n(k) matures k+n; historical next-cycle S_n(k+n) matures k+2n.',
            'Current-state and next-cycle forecasts are different tasks; their accuracies do not measure a like-for-like model improvement.',
            'Variable-length groups are left-padded only in storage; models receive exact n or 2n windows, with no padded timesteps.',
            'Zero source volumes are retained; ETF/commodity proxy volume is not Binance contract volume.',
            'Single fixed seed/architecture/epoch count is a pilot; negative results do not exclude stronger sequence models.',
            'This experiment trains main-state prediction; attribute targets remain in the dataset and attribute heads were not retrained.'])
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (args.output/'report.md').write_text(report(result,args.output))
    print('saved',args.output,'elapsed',round(result['elapsed_seconds'],1),flush=True)


def report(r,output):
    mode=r['parameters'].get('target_mode','next-cycle')
    description=('目标为当天S_n(k)，离线标签用[k-n+1,k+n]共2n根，监督答案到k+n才成熟；输入只读截至k收盘的历史日线。n表示状态参考尺度，不是预测偏移或固定持仓天数。'
        if mode=='current' else '历史对照目标为S_n(k+n)，到k+2n成熟；其准确率不能与当天状态任务直接当作模型提升比较。')
    lines=['# 原始日线序列：'+('当天状态估计' if mode=='current' else '下一周期状态预测对照'),'',
        description,'',f"同一批日线、三类主状态、{len(r['folds'])}个季度测试窗口，训练只使用测试开始前已成熟标签。逐根OHLCV由GRU学习表示；12项摘要浅树在同一目标上作对照。",'',
        '|市场|输入与模型|准确率|频率基线准确率|平衡准确率|上行识别率|下行识别率|概率误差相对基线改善|',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    for m in r['metrics']:
        lines.append(f"|{m['group']}|{m['variant']}|{m['accuracy']:.2%}|{m['frequency_accuracy']:.2%}|{m['balanced_accuracy']:.2%}|{m['class_recall'][0]:.2%}|{m['class_recall'][1]:.2%}|{m['brier_skill']:+.2%}|")
    lines+=['','正改善才表示概率误差低于资产历史频率；四方案共用同一目标，原始准确率也可直接比较。','',
        '|市场|方案相对旧摘要模型的Brier差（负为改善）|季度簇95%区间|','|---|---|---|']
    for p in r['paired']:
        if p['variant']=='summary_tree':continue
        delta=p['versus_summary_brier'];lines.append(f"|{p['group']} / {p['variant']}|{delta['mean']:+.6f}|{delta['interval95']}|")
    lines+=['','## 与频率基线及非重叠记录比较','',
        '|市场 / 模型|相对频率Brier差95%区间|每2n根取一条的记录数|非重叠概率改善|','|---|---|---:|---:|']
    for m in r['metrics']:
        lines.append(f"|{m['group']} / {m['variant']}|{m['versus_frequency_brier']['interval95']}|{m['nonoverlap']['rows']}|{m['nonoverlap']['brier_skill']:+.2%}|")
    lines+=['','## 数据形状与时点','',
        '币种输入为[n=14,5]或[28,5]，ETF代理为[10,5]或[20,5]。列为O/H/L/C/V，顺序从最早到当天收盘。价格相对窗口首日收盘做对数缩放、成交量log1p；原始未缩放OHLCV及对应每根全局行号同时保存在dataset.npz，GRU训练期再拟合通道均值/标准差。','',
        '数据集中不同组仅为存储左侧补NaN；模型裁剪到本组实际窗口，未使用填充时间步。当天任务target_row[k]=k、target_available_at[k]=label_available_at[k]；尚缺未来n根的尾部保留输入但无监督标签。实际使用可每日输出当天估计，但历史准确率仅在标签成熟后计算。','',
        'dataset.npz保留三类状态和独立属性；本轮训练主状态头，未重训属性头。predictions.npz保存逐条预测；各组每种GRU的最后一折权重及训练缩放保存在latest.pt。','',
        '## 配置与限制','','```json',json.dumps(r['parameters'],ensure_ascii=False,indent=2),'```','',*['- '+x for x in r['limitations']],'',
        '```bash',f"PYTHONPATH=src uv run --no-project --with 'torch==2.9.1' --with numpy --with scikit-learn --python .venv/bin/python python scripts/research/compare_market_state_raw_sequences.py --output {output} --target {mode} --epochs {r['parameters']['training']['epochs']}",'```','']
    return '\n'.join(lines)


if __name__=='__main__':
    with threadpool_limits(limits=1):main()
