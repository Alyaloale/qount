"""Fixed feature/category/state ablations, with chronological fit/predict clocks."""
from __future__ import annotations

import argparse
from collections import Counter,defaultdict
import datetime as dt
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from qount.research.market_learning import (
    behavior_features,fit_behavior,fit_candidate,model_matrix,range_geometry_from_distances,
)
from qount.research.market_state_profiles import CATEGORIES,KEYS
from qount.research.market_stages import ACTION_STATES
from qount.research.market_state_validation import causal_probabilities,scores
from qount.research.market_feature_enrichment import FIELDS
from compare_market_state_profiles import paired_comparison


TASKS=((0,'direction5',3),(1,'direction20',3),(2,'range5',2),(3,'break_survival3',2))
MAIN=('legacy_tree','enriched_tree','enriched_linear','enriched_mlp',
      'no_micro_tree','numeric_tree','category_tree','state12_tree','state14_tree','behavior_tree','asset_tree')
SECONDARY=('legacy_tree','enriched_tree','no_micro_tree')
MICRO=('micro_no_values','micro_old_oi','micro_all_values')


def date(t):return dt.datetime.fromtimestamp(int(t),dt.timezone.utc).strftime('%Y-%m-%d')
def pct(v):return '—' if v is None else f'{v:.2%}'


def taxonomy(data):
    if set(data['asset'])!=set(CATEGORIES):raise ValueError('taxonomy_asset_set_mismatch')
    if any(CATEGORIES[str(a)]!=c for a,c in zip(data['asset'],data['economic_category'])):
        raise ValueError('taxonomy_category_mismatch')
    if not set(data['state'])<=set(KEYS):raise ValueError('taxonomy_unknown_state')
    economic=[dict(category=c,assets=[a for a,v in CATEGORIES.items() if v==c],
                   rows=int(sum(data['economic_category']==c))) for c in sorted(set(CATEGORIES.values()))]
    coarse=Counter(str(s).split(':')[0] for s in data['state'])
    return dict(economic_categories=economic,structural_states=list(ACTION_STATES),
        protective_states=['shock','unknown'],coarse_counts=dict(coarse),
        state_codes=[dict(state=k,rows=int(sum(data['state']==k))) for k in KEYS],
        possible_coarse_states=12,possible_state_codes=14,observed_state_codes=len(set(data['state'])),
        behavior_categories=4,behavior_unknown_code=-1,
        behavior_rule='Refit only prior style observations each quarter; IDs ordered by volatility, not fixed members',
        semantics='Current rule states are descriptive inputs, not supervised ground-truth labels')


def matrices(data,*,feature_groups=False):
    names=list(map(str,data['feature_names']))
    approved=data['default_feature_mask'].copy()
    legacy=approved.copy();legacy[45:]=False
    old_oi=np.array([j<45 and name.startswith('oi_') for j,name in enumerate(names)])
    micro=np.array([name.startswith(('oi_','reported_','metrics_','perpetual_spot_',
        'spot_taker_','spot_minus_','hourly_','late_session_')) for name in names])
    broad=approved&~micro
    shared=dict(feature_mask=broad,include_asset=False,include_category=False,state_detail=None)
    out={
        'legacy_tree':model_matrix(data,feature_mask=legacy),
        'enriched_tree':model_matrix(data),
        'enriched_linear':model_matrix(data),
        'enriched_mlp':model_matrix(data),
        'no_micro_tree':model_matrix(data,feature_mask=broad),
        'numeric_tree':model_matrix(data,**shared),
        'category_tree':model_matrix(data,**dict(shared,include_category=True)),
        'state12_tree':model_matrix(data,**dict(shared,include_category=True,state_detail='coarse')),
        'state14_tree':model_matrix(data,**dict(shared,include_category=True,state_detail='fine')),
        'asset_tree':model_matrix(data,**dict(shared,include_asset=True,state_detail='fine')),
    }
    out['behavior_tree']=out['state14_tree']
    out['micro_no_values']=out['no_micro_tree']
    out['micro_old_oi']=model_matrix(data,feature_mask=broad|(approved&old_oi))
    out['micro_all_values']=out['enriched_tree']
    if feature_groups:
        families={name:group for name,group,*_ in FIELDS}
        for group in ('price_path','peer_context','crypto_activity','macro_context','global_context','calendar','microstructure'):
            added=np.array([families.get(n) in ('metrics_intraday','spot_perpetual') if group=='microstructure'
                            else families.get(n)==group for n in names])
            out['add_'+group]=model_matrix(data,feature_mask=legacy|(approved&added))
    return out,dict(legacy=int(legacy.sum()),enriched=int(approved.sum()),
                   broad=int(broad.sum()),old_oi=int((old_oi&approved).sum()))


def fold_indices(data,valid,column,cutoff,test_indices,minimum=80):
    train=np.flatnonzero(valid&(data['maturity'][:,column]>0)&(data['maturity'][:,column]<cutoff))
    test=np.asarray(test_indices,int)
    if len(train)<minimum or len(np.unique(data['y'][train,column]))<2:return None
    if np.any(data['known_at'][train]>=cutoff) or np.any(data['known_at'][test]<cutoff):
        raise ValueError('fold_clock_violation')
    return train,test


def records(data,indices,column):
    return [dict(index=int(i),asset=str(data['asset'][i]),category=str(data['economic_category'][i]),
        key=str(data['state'][i]),known_at=int(data['known_at'][i]),mature_at=int(data['maturity'][i,column]),
        outcome=int(data['y'][i,column])) for i in indices]


def fit_probabilities(kind,a,y,b,classes,seed):
    fitted,diagnostics=fit_candidate(kind,a,y,seed=seed)
    actual=fitted[-1].classes_.astype(int)
    result=np.zeros((len(b),classes))
    result[:,actual]=fitted.predict_proba(b)
    if not np.all(np.isfinite(result)) or not np.allclose(result.sum(axis=1),1):
        raise ValueError('invalid_forecast_probabilities')
    return result,diagnostics


def report(result):
    group_mode=result['parameters'].get('feature_group_ablation',False)
    lines=['# '+('新增特征逐组加法消融' if group_mode else '标的、状态类别与增补特征训练对照'),'',
        '离线预测研究；历史已反复消费，结果是按时间顺序的探索验证，不是独立新样本或策略收益。','',
        ('本文件只执行旧特征树与单个新增特征组的direction5/range5对照，不执行NN或身份消融。'
         if group_mode else '本文件执行四个预测目标；5期方向/区间含身份消融、树/线性/三种子MLP，20期方向/3期突破仅比较三组树模型。'),'',
        '## 类别确认','', '|经济类别|标的|观测数|','|---|---|---:|']
    for r in result['taxonomy']['economic_categories']:
        lines.append(f"|{r['category']}|{', '.join(r['assets'])}|{r['rows']}|")
    lines+=['','10个结构/事件状态，加shock/unknown两项共12类；两个突破方向各拆观察/确认，形成14个模型编码。',
        '预热后的数据实际出现13个编码，unknown为0；四个动态行为簇另加未知/分布外，按过去窗口重拟合，不是永久标的身份。','',
        '|状态编码|观测数|','|---|---:|']
    for r in result['taxonomy']['state_codes']:lines.append(f"|{r['state']}|{r['rows']}|")
    lines+=['','## 训练设定','',
        '- 固定2023年起逐季重训、每标的每5期起点；标签必须在季初之前成熟。四目标分别训练，不把未来方向中性类称为震荡路径。',
        '- 币种与ETF代理分开训练；填补/缩放只拟合训练部分。参数沿用前轮，不搜索参数，不做随机验证或测试早停。',
        '- 树80轮/最多7叶/最小叶60/L2=10；逻辑回归C=.1；MLP为32→16、固定40轮、L2=1，种子17/29/41平均，全部种子保留。',
        '- 原特征比较也隔离未核实旧比率：legacy为44项，enriched为89项，去微观结构broad为75项。',
        '- 类别/状态/行为消融均用相同75项，连续状态派生信息保留；只检验额外离散编码的增量。',
        '- 经济类别可由标的ID确定，因此先去掉标的ID检验类别，再单独比较标的ID；不把重复编码误认为独立经济信息。',
        '- 5/20期方向、5期区间和3期突破维持分别报告；后两项条件样本不同，不能相互横比准确率。',
        ('- 本次不训练微观共同覆盖模型；逐组加法微观臂仍在全币种起点预测，属于缺失来源下的探索。'
         if group_mode else '- 微观数据另在三币共同覆盖行比较，逐季先训过去覆盖行、再预测未来覆盖行；相同训练行/测试行。'),'',
        '## 全部时间顺序预测','',
        '|样本层/市场/目标|模型|样本|准确率|平衡准确率|Brier↓|','|---|---|---:|---:|---:|---:|']
    for r in result['evaluations']:
        if r['window']!='all':continue
        s=r['scores']
        lines.append(f"|{r['scope']}/{r['group']}/{r['target']}|{r['model']}|{s['count']}|{pct(s['accuracy'])}|{pct(s['balanced_accuracy'])}|{s['brier']:.5f}|")
    lines+=['','## 相同机会的差异','',
        '差为左模型Brier减右模型Brier，负值较好；季度簇自助法95%区间保留同期间资产相关性。未校正多重比较。',
        '微观覆盖跨三个选择性时间段；季度簇少，区间不用于确认稳定优势。','',
        '|样本层/市场/目标|对照|Brier差|95%区间|','|---|---|---:|---|']
    for r in result['comparisons']:
        c=r['delta']['interval95']
        lines.append(f"|{r['scope']}/{r['group']}/{r['target']}|{r['left']} − {r['right']}|{r['delta']['mean']:+.5f}|{f'[{c[0]:+.5f}, {c[1]:+.5f}]' if c else '不足4季度'}|")
    if result['parameters'].get('feature_group_ablation'):
        lines+=['','本报告实际执行分组加法消融：仅direction5/range5、旧44项树基线与单个新增组；不执行NN、身份消融或微观共同覆盖训练。',
            'ETF没有原生币种活动/微观结构来源，跳过这两组；不会把缺失列当成有效信息反复拟合。',
            '这是整包增补退化后的原因定位，仍使用已消费历史；多组中看起来最优的结果不是独立确认。']
    lines+=['','## 各类别与状态诊断','',
        'results.json包含各经济类别、状态编码、年度、置信度校准/混淆矩阵及每折时间。小样本类别不单独选择策略。',
        'predictions.npz保存每条预测及三个NN种子；列含run_id、row_index、三列概率（二分类第三列NaN），run_names给出映射。','',
        '## 资源与边界','',f"实际拟合{len(result['fits'])}次，耗时{result['elapsed_seconds']:.1f}秒；跳过{len(result['skipped_folds'])}个历史不足折。",'']
    lines+=['- '+s for s in result['limitations']]
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--feature-groups',action='store_true',help='Only old-tree + individual source groups, direction5/range5')
    args=parser.parse_args()
    if args.output.exists():parser.error('Preserve previous experiment; choose a new output')
    started=time.monotonic()
    with np.load(args.dataset,allow_pickle=False) as z:data={k:z[k] for k in z.files}
    kinds=taxonomy(data)
    matrix,feature_counts=matrices(data,feature_groups=args.feature_groups)
    evaluations=[];comparisons=[];diagnostics=[];fits=[];skipped=[];predictions=[];run_names=[]
    behavior_cache={};fold_behavior=[]

    def retain(scope,group,target,runs,column,include_diagnostics=True):
        for name,rows in runs.items():
            if not rows:continue
            run_id=len(run_names);run_names.append(f'{scope}/{group}/{target}/{name}')
            for row in rows:
                p=list(row['probabilities'])
                predictions.append((run_id,row['index'],*(p+[np.nan]*(3-len(p)))))
            years=sorted({date(r['known_at'])[:4] for r in rows})
            for window in ['all']+years:
                selected=rows if window=='all' else [r for r in rows if date(r['known_at']).startswith(window)
                    and date(r['mature_at'])<str(int(window)+1)+'-01-01']
                if selected:evaluations.append(dict(scope=scope,group=group,target=target,model=name,window=window,scores=scores(selected)))
            if include_diagnostics and name in ('asset_prior','legacy_tree','enriched_tree','no_micro_tree',
                    'numeric_tree','category_tree','state12_tree','state14_tree','behavior_tree','asset_tree','micro_all_values'):
                for field in ('category','key'):
                    for value in sorted({r[field] for r in rows}):
                        selected=[r for r in rows if r[field]==value]
                        diagnostics.append(dict(scope=scope,group=group,target=target,model=name,
                            by=field,value=value,scores=scores(selected)))
        contrasts=([('enriched_tree','legacy_tree'),('no_micro_tree','legacy_tree'),('enriched_tree','no_micro_tree'),
                    ('enriched_linear','enriched_tree'),('enriched_mlp','enriched_tree'),
                    ('category_tree','numeric_tree'),('state12_tree','category_tree'),('state14_tree','state12_tree'),
                    ('behavior_tree','state14_tree'),('asset_tree','state14_tree'),('no_micro_tree','asset_tree'),
                    ('enriched_tree','asset_prior'),('enriched_tree','range_geometry')]
                   if scope=='full' else [('micro_all_values','micro_no_values'),('micro_all_values','micro_old_oi'),
                                          ('micro_old_oi','micro_no_values')])
        if args.feature_groups:contrasts=[(name,'legacy_tree') for name in runs if name.startswith('add_')]
        for left,right in contrasts:
            if left in runs and right in runs and runs[left] and runs[right]:
                comparisons.append(dict(scope=scope,group=group,target=target,left=left,right=right,
                    delta=paired_comparison(runs[left],runs[right])))

    for scope in ('full',) if args.feature_groups else ('full','micro'):
        for group in ('crypto','etf_proxy') if scope=='full' else ('crypto',):
            for column,target,classes in ((TASKS[0],TASKS[2]) if args.feature_groups else TASKS if scope=='full' else (TASKS[0],TASKS[2])):
                valid=(data['group']==group)&(data['y'][:,column]>=0)
                valid&=(data['bar_index']%5==0) if scope=='full' else data['microstructure_view_rows']
                samples=records(data,np.flatnonzero(valid),column)
                baseline=causal_probabilities(samples,classes)
                start='2023-01-01' if scope=='full' else '2025-10-01'
                evaluation=[r for r in baseline if date(r['known_at'])>=start]
                lookup={r['index']:r for r in evaluation}
                names=(MAIN if column in (0,2) else SECONDARY) if scope=='full' else MICRO
                if args.feature_groups:
                    names=('legacy_tree',)+tuple(n for n in matrix if n.startswith('add_')
                        and not (group=='etf_proxy' and n in ('add_crypto_activity','add_microstructure')))
                runs={name:[] for name in names}
                runs['asset_prior']=[];runs['pooled_state']=[]
                if target=='range5':runs['range_geometry']=[]
                if 'enriched_mlp' in names:
                    for seed in (17,29,41):runs[f'mlp_seed{seed}']=[]
                quarters=defaultdict(list)
                for r in evaluation:
                    when=dt.datetime.fromtimestamp(r['known_at'],dt.timezone.utc)
                    quarters[when.year,(when.month-1)//3*3+1].append(r['index'])
                for (year,month),test in sorted(quarters.items()):
                    cutoff=int(dt.datetime(year,month,1,tzinfo=dt.timezone.utc).timestamp())
                    split=fold_indices(data,valid,column,cutoff,test)
                    if split is None:
                        skipped.append(dict(scope=scope,group=group,target=target,cutoff=cutoff,
                            test_rows=len(test),reason='less_than80_matured_targets_or_one_class'))
                        continue
                    train,test=split
                    training_latest=int(data['maturity'][train,column].max())
                    for name in ('asset_prior','pooled_state'):
                        runs[name]+=[dict(lookup[i],probabilities=lookup[i]['baseline'] if name=='asset_prior' else lookup[i]['probabilities']) for i in test]
                    if target=='range5':
                        lo=list(data['feature_names']).index('lower_boundary_distance_sigma20')
                        hi=list(data['feature_names']).index('upper_boundary_distance_sigma20')
                        for i in test:
                            p=range_geometry_from_distances(float(data['X'][i,lo]),float(data['X'][i,hi]))
                            runs['range_geometry'].append(dict(lookup[i],probabilities=[1-p,p]))
                    if 'behavior_tree' in names:
                        if cutoff not in behavior_cache:
                            prior=np.flatnonzero((data['known_at']<cutoff)&(data['bar_index']%20==5))
                            behavior_cache[cutoff]=fit_behavior(data,prior)
                            f=behavior_cache[cutoff]
                            fold_behavior.append(dict(cutoff=cutoff,last_feature=int(data['known_at'][prior].max()),
                                centers=f['centers'].tolist(),thresholds=f['thresholds'].tolist(),silhouette=f['silhouette']))
                        fitted=behavior_cache[cutoff]
                        train_behavior,train_labels=behavior_features(data,train,fitted)
                        test_behavior,test_labels=behavior_features(data,test,fitted)
                    for name in names:
                        kind='mlp' if name=='enriched_mlp' else 'linear' if name=='enriched_linear' else 'tree'
                        a,b=matrix[name][train],matrix[name][test]
                        if name=='behavior_tree':a,b=np.c_[a,train_behavior],np.c_[b,test_behavior]
                        batch=[]
                        for seed in (17,29,41) if kind=='mlp' else (17,):
                            p,details=fit_probabilities(kind,a,data['y'][train,column],b,classes,seed)
                            batch.append(p)
                            fits.append(dict(scope=scope,group=group,target=target,model=name,cutoff=cutoff,
                                train_rows=len(train),test_rows=len(test),columns=a.shape[1],
                                last_training_maturity=training_latest,**details))
                            if kind=='mlp':runs[f'mlp_seed{seed}'] += [dict(lookup[i],probabilities=row.tolist()) for i,row in zip(test,p)]
                        runs[name]+=[dict(lookup[i],probabilities=row.tolist()) for i,row in zip(test,np.mean(batch,axis=0))]
                    print(scope,group,target,f'{year}-{month:02}',f'train={len(train)} test={len(test)} fits={len(fits)}',flush=True)
                counts={len(rows) for rows in runs.values()}
                if len(counts)>1:raise ValueError('unpaired_evaluation_origins')
                retain(scope,group,target,runs,column)
    result=dict(research_only=True,orders_authorized=False,independent_oos=False,
        dataset=str(args.dataset),dataset_sha256=hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        taxonomy=kinds,feature_counts=feature_counts,evaluations=evaluations,comparisons=comparisons,
        diagnostics=diagnostics,fits=fits,skipped_folds=skipped,behavior_folds=fold_behavior,
        elapsed_seconds=time.monotonic()-started,
        parameters=dict(evaluation_start='2023-01-01',micro_start='2025-10-01',refit='quarterly',
            full_stride=5,micro_stride=1,minimum_train=80,seed_list=[17,29,41],parameter_search=False,
            feature_group_ablation=args.feature_groups),
        limitations=[
            '原45项中的未核实持仓比率默认隔离，legacy实际44项；不把原论文/上轮45项数值直接当本轮同机会基线。',
            '12状态与14编码是可检验规则设计，不是市场存在唯一固定自然类别的证明；当前unknown样本为零。',
            '类别/状态消融只改变离散编码，连续价格/事件/风险特征保留；行为类别每季重拟合，成员和经济含义并不固定。',
            '所有历史已消费，存续名单/ETF代理/假定发布时间继续限制结论；历史探索不宣称独立OOS。',
            'MLP40轮是固定资源上限，不代表数值收敛；随机种子全部保留，不挑最好种子。',
            '微观仅三币选择性日期；共同覆盖对照控制观测行但不消除时间段选择偏差，不外推至全市场。',
            '数据源缺失模式仍可能编码年代；去微观结构对照与共同覆盖试验用于区分，不能彻底消除影响。',
            '季度簇区间未校正多重比较，20期标签重叠且可能跨季度；区间是探索性诊断。',
            '只评价未来预测；没有成交、仓位、真实成本和账户回放，不报告CAGR/MDD或盈利胜率，不变更实盘。',
        ])
    args.output.mkdir(parents=True)
    array=np.array(predictions,float)
    np.savez_compressed(args.output/'predictions.npz',run_id=array[:,0].astype(int),row_index=array[:,1].astype(int),
        probabilities=array[:,2:].astype(np.float64),run_names=np.array(run_names))
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (args.output/'report.md').write_text(report(result))
    print(json.dumps(dict(output=str(args.output),fits=len(fits),elapsed_seconds=result['elapsed_seconds'])))


if __name__=='__main__':main()
