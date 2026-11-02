"""Descriptive statistics for the current complete native-nine-channel dataset.

No missing sources, indicator inputs, neural fits or dataset changes. Derived
ratios below are diagnostic summaries, never added to model input channels.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.stats import kurtosis,rankdata,skew

from qount.research.market_state_dataset import CurrentStateDataset,DEFAULT_ROOT


def summary(x):
    x=np.asarray(x,float);finite=x[np.isfinite(x)]
    if not len(finite):return dict(rows=len(x),finite_rows=0)
    deviation=float(finite.std())
    return dict(rows=len(x),finite_rows=len(finite),mean=float(finite.mean()),std=deviation,
        skewness=float(skew(finite)) if deviation else None,excess_kurtosis=float(kurtosis(finite)) if deviation else None,
        quantiles={str(p):float(np.quantile(finite,p)) for p in (0,.01,.05,.25,.5,.75,.95,.99,1)})


def corr(a,b):
    a=np.asarray(a);b=np.asarray(b);good=np.isfinite(a)&np.isfinite(b);a=a[good];b=b[good]
    if len(a)<3 or not np.std(a) or not np.std(b):return None
    return float(np.corrcoef(rankdata(a),rankdata(b))[0,1])


def auc(actual,score):
    actual=np.asarray(actual,bool);score=np.asarray(score,float);positive=int(actual.sum());negative=len(actual)-positive
    if not positive or not negative:return None
    return float((rankdata(score)[actual].sum()-positive*(positive+1)/2)/(positive*negative))


def diagnostics(d):
    m=d['market'];w=d['n_raw_market'];close=w[:,:,3];previous=close[:,-2];n=close.shape[1]
    if np.any(m[:,4:7]<=0):raise ValueError('diagnostic_denominator_requires_positive_source_volume_and_count')
    values=dict(return1=np.log(close[:,-1]/previous),return3=np.log(close[:,-1]/close[:,-4]),
        window_change=np.log(close[:,-1]/close[:,0]),true_range_pct=100*np.maximum(m[:,1]-m[:,2],np.maximum(abs(m[:,1]-previous),abs(m[:,2]-previous)))/previous,
        signed_body_fraction=(m[:,3]-m[:,0])/(m[:,1]-m[:,2]),close_location=(m[:,3]-m[:,2])/(m[:,1]-m[:,2]),
        open_gap_pct=100*(m[:,0]/previous-1),taker_buy_quote_share=m[:,8]/m[:,5],
        taker_buy_base_share=m[:,7]/m[:,4],taker_quote_imbalance=2*m[:,8]/m[:,5]-1,
        pressure3=2*w[:,-3:,8].sum(1)/w[:,-3:,5].sum(1)-1,
        pressure_window=2*w[:,:,8].sum(1)/w[:,:,5].sum(1)-1,
        relative_quote_volume=m[:,5]/np.median(w[:,:,5],axis=1),relative_trade_count=m[:,6]/np.median(w[:,:,6],axis=1),
        average_trade_quote=m[:,5]/m[:,6],close_vs_vwap_pct=100*(m[:,3]/(m[:,5]/m[:,4])-1),
        window_return_vol=np.std(np.diff(np.log(close),axis=1),axis=1))
    prior_pressure=2*w[:,:-1,8].sum(1)/w[:,:-1,5].sum(1)-1
    earlier_pressure=2*w[:,:-3,8].sum(1)/w[:,:-3,5].sum(1)-1
    values['pressure_change1']=values['taker_quote_imbalance']-prior_pressure
    values['pressure_change3']=values['pressure3']-earlier_pressure
    if any(not np.isfinite(x).all() for x in values.values()):raise ValueError('nonfinite_derived_diagnostic')
    return values


def write_report(r,output):
    o=r['overview'];c=r['correlations']
    native_corr=np.asarray(c['within_asset_mean_spearman']);price_corr=native_corr[:4,:4][np.triu_indices(4,1)]
    phase={(x['state'],x['phase']):x for x in r['state_phase_summaries']}
    median=lambda x,k:x['summaries'][k]['quantiles']['0.5']
    lines=['# 当前完整数据集特征统计','',
        '范围：仅当前七币种、九通道完整日线数据。派生比例仅用于统计诊断，不加入模型输入。未训练模型、未改变数据和标签。',
        f"来源：`{r['source']}`；UTC日线开盘日期 {o['first_date'][:10]} 至 {o['last_date'][:10]}。",'',
        f"共 **{o['rows']:,}条资产日记录、{o['dates']:,}个共同日期、7个币种**；原生字段缺失{o['native_missing']}，整行九字段重复{o['identical_daily_market_rows']}。",
        '输入为过去14根（或28根）日线的开、高、低、收、基础币成交量、USDT成交额、成交笔数、主动买入基础币量、主动买入USDT额。',
        '当前状态标签使用当天前后共28根日线，需未来14天才成熟；属性标签单独保存。所有按状态分组的结果都是事后描述，实时无法事先知道所属组。','',
        '## 样本与标签','',
        '| 主状态 | 数量 | 比例 | 切换首日 |','|---|---:|---:|---:|']
    for j,(name,title) in enumerate(zip(('upward','downward','sideways'),('上行','下行','震荡'))):
        lines.append(f"| {title} | {o['class_counts'][j]:,} | {o['class_share'][j]:.2%} | {phase[name,'switch_day']['rows']} |")
    lines += ['',f"状态切换首日合计{o['switch_rows']}条（{o['switch_share']:.2%}）。训练时只看总体准确率会偏向震荡和延续日，需分别评估三类、切换日和延续日。",
        f"相邻14根输入共享13根日线，28根标签上下文共享27根；每币种隔28天抽取仅剩{o['nonoverlap_2n_records']}条资产日记录，这仍不是独立样本数。",
        f"跨币种日收益相关矩阵第一主成分解释{c['first_return_pc_variance_share']:.2%}方差；相关矩阵参与率{c['linear_correlation_participation_ratio']:.2f}仅衡量横截面线性冗余，不代表独立交易机会数量。",'',
        '## 各币种尺度与尾部','',
        '| 币种 | 日成交额中位数（亿USDT） | 日成交笔数中位数（万） | 日对数收益标准差 | 单日简单收益绝对值>10% | 主动买卖差为负占比 |',
        '|---|---:|---:|---:|---:|---:|']
    for a in r['asset_summaries']:
        lines.append(f"| {a['asset']} | {a['daily_quote_median']/1e8:.2f} | {a['trade_count_median']/1e4:.2f} | {a['return1_std_pct']:.2f}% | {a['absolute_return_gt10pct']:.2%} | {a['flow_negative_share']:.2%} |")
    g=r['global_diagnostic_summaries']
    lines += ['',f"同币种过去14根（含当天）成交额中位数为基准，相对日成交额的P1/P50/P99为 {g['relative_quote_volume']['quantiles']['0.01']:.2f}/{g['relative_quote_volume']['quantiles']['0.5']:.2f}/{g['relative_quote_volume']['quantiles']['0.99']:.2f}倍。",
        f"混合日对数收益超额峰度{g['return1']['excess_kurtosis']:.1f}，日真实振幅P50/P99为{g['true_range_pct']['quantiles']['0.5']:.2f}%/{g['true_range_pct']['quantiles']['0.99']:.2f}%。有厚尾，不能把所有极端日直接删为噪声。",
        '币种间价格及基础币成交量单位不同，不比较混合原始均值。平均每笔成交额=总成交额/成交笔数，不等于大户订单规模。','',
        '## 九通道相关性','',
        f'先逐币种计算全历史Spearman相关，再取均值，避免混合币种量纲。OHLC之间约{price_corr.min():.4f}～{price_corr.max():.4f}；基础量与主动买入基础量约{native_corr[4,7]:.4f}；成交额与主动买入额约{native_corr[5,8]:.4f}；成交额与成交笔数约{native_corr[5,6]:.4f}。',
        '九通道包含大量共享水平信息，但高度相关不等于可以直接删列：主动买入比例的细小变化仍可能提供条件信息，需要同样样本的消融实验。原始价格随时间漂移，相关性不代表因果。','',
        '## 主动交易方向及切换','',
        '定义主动买卖差比例 P=(主动买入USDT额−主动卖出USDT额)/总成交额=2×主动买入额/总成交额−1。每笔成交都有双方，P反映主动成交方向，不是交易所现金净流入。',
        f"全样本P中位数{100*g['taker_quote_imbalance']['quantiles']['0.5']:.2f}%，对应主动买入额占比{50*(1+g['taker_quote_imbalance']['quantiles']['0.5']):.2f}%。上行组也常为负，不能以正负号直接定义涨跌。",'',
        '| 状态及阶段 | 数量 | 当天P中位数 | 近3日P相对前11日变化中位数（百分点） | 相对日成交额中位数 |',
        '|---|---:|---:|---:|---:|']
    for name,title in zip(('upward','downward','sideways'),('上行','下行','震荡')):
        for p,t in [('switch_day','切换首日'),('continuation','延续日')]:
            x=phase[name,p]
            lines.append(f"| {title}/{t} | {x['rows']} | {100*median(x,'taker_quote_imbalance'):.2f}% | {100*median(x,'pressure_change3'):+.2f} | {median(x,'relative_quote_volume'):.2f} |")
    lines += ['',
        '上行与下行切换首日的主动交易方向变化有不同中位数，但分布仍重叠；不能据此宣称可预测切换。新趋势首日成交额中位数并未放大，不应先验地要求所有切换都必须放量。','',
        '| 当天P与收益关系（逐币种Spearman均值） | 相关系数 |','|---|---:|']
    for lag,title in [(0,'当天收益'),(1,'未来1天收益'),(3,'未来3天累计收益')]:
        value=np.mean([x['spearman'] for x in r['flow_return_leadlag'] if x['lag_future_sessions']==lag])
        lines.append(f'| {title} | {value:+.4f} |')
    lines += ['',
        '这里只能支持主动交易方向主要与同期涨跌相关；后续收益的简单单变量关系接近零。非线性、条件关系和对状态识别的增量帮助尚未检验。未来收益仅作为分析结果，未加入输入。','',
        '### 单变量与当前状态关联','',
        '以下AUC先逐币种计算再取均值；上行取原分数，下行取负分数；只度量全历史关联，不是留出测试、不代表未来收益预测能力。标签本来部分由历史路径构造，因此历史收益AUC存在定义上的重叠。','',
        '| 诊断量 | 上行AUC | 下行AUC |','|---|---:|---:|']
    for feature,title in [('return1','当天收益'),('return3','过去3天收益'),('window_change','14根内首末收盘变化（13次日收益）'),('taker_quote_imbalance','当天P'),('pressure3','近3日P'),('pressure_window','14日P'),('pressure_change3','近3日P相对前11日变化')]:
        vals=[np.mean([x['auc'] for x in r['univariate_auc'] if x['feature']==feature and x['state']==s]) for s in ('upward','downward')]
        lines.append(f'| {title} | {vals[0]:.3f} | {vals[1]:.3f} |')
    lines += ['', '## 日历及分布变化','',
        '| 币种 | 周末/工作日日成交额中位数 | 2026/2021成交额中位数 | 2026/2021日收益标准差 |','|---|---:|---:|---:|']
    for w in r['weekday_effects']:
        ys={y['year']:y for y in r['yearly'] if y['asset']==w['asset']};a=ys['2021'];b=ys['2026']
        lines.append(f"| {w['asset']} | {w['quote_weekend_over_weekday']:.2f} | {b['quote_median']/a['quote_median']:.2f} | {b['return_std_pct']/a['return_std_pct']:.2f} |")
    lines += ['',
        '周末按UTC日线开盘日期划分；2021从1月28日开始、2026只到10月12日，年份比较为部分年度样本的描述，不能当作完整年度比较或因果检验。币种生命周期、价格及市场环境均会影响原始成交额。',
        '本数据中周末成交额比工作日低约30%～48%；低成交可能是自然日历规律，不能直接视为资金撤退或状态切换。','',
        '## 状态独立属性（仅标签，非模型输入）','',
        '| 主状态 | 收缩占比 | 路径效率中位数 | 日波动率标签中位数 |','|---|---:|---:|---:|']
    for x,title in zip(r['label_attribute_summaries'],('上行','下行','震荡')):
        lines.append(f"| {title} | {x['compression_share']:.2%} | {median(x,'path_efficiency'):.3f} | {100*median(x,'volatility_daily'):.2f}% |")
    lines += ['',
        '收缩与三类方向均可共存，支持分开表达。路径效率的组间差异部分来自标签定义，不能证明模型能提前识别。','',
        '## 研究判断与下一项有效实验','',
        '当前数据完整性适合继续做离线实验；主要限制是重叠和共振导致的信息冗余、原始尺度与活动水平漂移、切换样本少。数据量不等于独立信息量。',
        '最有价值的后续实验：在这份完整数据的同一时间切分上比较原五通道与九通道，并单独汇报切换首日召回、各类F1和延续日结果；训练折内拟合尺度，按标签成熟时点切分。先检验九通道是否带来增量，不继续堆缺失字段。',
        '本次没有新模型准确率。未使用ETF、OI、资金费或不完整字段。结果为描述统计，不包含交易回测，因此没有新增净收益、成本或执行表现结论。','',
        '完整原始分位数、逐年统计、相关矩阵和描述性AUC：`stats.json`；诊断比例与源行对应：`diagnostics.npz`。',
        '图：`correlations.png`、`feature_diagnostics.png`。']
    (output/'report.md').write_text('\n'.join(lines)+'\n')


def plot_stats(r,output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties
    font=Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
    if font.exists():plt.rcParams['font.family']=FontProperties(fname=str(font)).get_name()
    plt.rcParams.update({'axes.unicode_minus':False,'font.size':10})
    c=r['correlations'];fig,axes=plt.subplots(1,2,figsize=(16,7),layout='constrained')
    for ax,matrix,labels,title in [(axes[0],c['within_asset_mean_spearman'],['O','H','L','C','基础量','成交额','笔数','主动买量','主动买额'],'九原生通道：逐币种Spearman均值'),
        (axes[1],c['return_pearson'],[a.removesuffix('USDT') for a in c['assets']],'币种日对数收益Pearson相关')]:
        matrix=np.array(matrix);im=ax.imshow(matrix,vmin=-1,vmax=1,cmap='RdBu_r')
        ax.set_xticks(range(len(labels)),labels,rotation=45,ha='right');ax.set_yticks(range(len(labels)),labels);ax.set_title(title)
        for i in range(len(labels)):
            for j in range(len(labels)):
                number=f'{matrix[i,j]:.4f}' if ax is axes[0] else f'{matrix[i,j]:.2f}'
                ax.text(j,i,number,ha='center',va='center',color='white' if abs(matrix[i,j])>.65 else 'black',fontsize=8)
    fig.colorbar(im,ax=axes,fraction=.024,pad=.02,label='相关系数')
    fig.suptitle('完整数据集：2021-01-28 至 2026-10-12 · 2,084个日期 × 7币种\n原始水平相关含共同趋势；相关性不代表预测能力',fontsize=14)
    fig.savefig(output/'correlations.png',dpi=160);plt.close(fig)
    fig,axes=plt.subplots(2,2,figsize=(14,9),layout='constrained');colors=['#208353','#c55245','#5f70a0'];names=['上行','下行','震荡']
    phase={(x['state'],x['phase']):x for x in r['state_phase_summaries']}
    for ax,key,title in [(axes[0,0],'taker_quote_imbalance','当天主动买卖差 / 成交额（%）'),(axes[0,1],'pressure_change3','近3日主动方向相对前11日变化（百分点）')]:
        for j,s in enumerate(('upward','downward','sideways')):
            for k,p in enumerate(('switch_day','continuation')):
                q=phase[s,p]['summaries'][key]['quantiles'];pos=j*3+k
                ax.vlines(pos,100*q['0.25'],100*q['0.75'],color=colors[j],linewidth=8,alpha=.4)
                ax.scatter(pos,100*q['0.5'],color=colors[j],s=35)
        ax.axhline(0,color='black',linewidth=.7);ax.set_xticks([0,1,3,4,6,7],[f'{n}\n{p}' for n in names for p in ('切换','延续')]);ax.set_title(title+'\n点=中位数，线=25%～75%分位');ax.grid(axis='y',alpha=.2)
    ax=axes[1,0];assets=[x['asset'].removesuffix('USDT') for x in r['asset_summaries']]
    ax.bar(assets,[x['return1_std_pct'] for x in r['asset_summaries']],color='#527caa');ax.set_title('日对数收益标准差（%）');ax.grid(axis='y',alpha=.2)
    ax=axes[1,1];ax.bar(assets,[x['quote_weekend_over_weekday'] for x in r['weekday_effects']],color='#ba8a43');ax.axhline(1,color='black',linewidth=.8);ax.set_ylim(0,1.1);ax.set_title('周末 / 工作日的日成交额中位数');ax.grid(axis='y',alpha=.2)
    fig.suptitle('完整数据集特征诊断 · 状态分组为事后标签，切换组209 / 205 / 412条\n主动交易方向不是现金净流入；图中差异未证明样本外预测增量',fontsize=13)
    fig.savefig(output/'feature_diagnostics.png',dpi=160);plt.close(fig)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,default=DEFAULT_ROOT)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--plot',action='store_true',help='Render two static diagnostic figures; requires matplotlib')
    args=parser.parse_args()
    if args.output.exists():parser.error('preserve previous analyses')
    ds=CurrentStateDataset(args.dataset);d=ds.data;N=len(d['asset']);f=diagnostics(d);m=d['market'];state=d['state'];change=d['switch_label']
    assert N==sum(int((d['asset']==a).sum()) for a in ds.asset_names)
    raw=[];asset_stats=[];state_stats=[];yearly=[];week=[];univariate=[];leadlag=[];matrices=[]
    feature_names=list(f);derived_matrix=np.c_[*[f[k] for k in feature_names]];diagnostic_correlations=[]
    years=d['bar_open_at'].astype('datetime64[ms]').astype('datetime64[Y]').astype(str)
    weekday=(d['bar_open_at']//86400000+3)%7
    for asset in ds.asset_names:
        ix=np.flatnonzero(d['asset']==asset)
        for j,name in enumerate(d['market_names']):raw.append(dict(asset=asset,field=str(name),**summary(m[ix,j])))
        ranks=np.c_[*[rankdata(m[ix,j]) for j in range(9)]];matrices.append(np.corrcoef(ranks,rowvar=False))
        ranked=np.c_[*[rankdata(derived_matrix[ix,j]) for j in range(len(feature_names))]]
        diagnostic_correlations.append(np.corrcoef(ranked,rowvar=False))
        record=dict(asset=asset,rows=len(ix),price_median=float(np.median(m[ix,3])),daily_quote_median=float(np.median(m[ix,5])),
            trade_count_median=float(np.median(m[ix,6])),return1_std_pct=float(np.std(f['return1'][ix])*100),
            absolute_return_gt5pct=float(np.mean(abs(np.expm1(f['return1'][ix]))>.05)),
            absolute_return_gt10pct=float(np.mean(abs(np.expm1(f['return1'][ix]))>.10)),
            flow_negative_share=float(np.mean(f['taker_quote_imbalance'][ix]<0)),
            return_flow_spearman=corr(f['return1'][ix],f['taker_quote_imbalance'][ix]),
            summaries={name:summary(values[ix]) for name,values in f.items()})
        asset_stats.append(record)
        for year in np.unique(years[ix]):
            take=ix[years[ix]==year]
            yearly.append(dict(asset=asset,year=str(year),rows=len(take),quote_median=float(np.median(m[take,5])),
                trade_count_median=float(np.median(m[take,6])),average_trade_quote_median=float(np.median(f['average_trade_quote'][take])),
                return_std_pct=float(np.std(f['return1'][take])*100),flow_median=float(np.median(f['taker_quote_imbalance'][take])),
                states=np.bincount(state[take],minlength=3).tolist(),switch_share=float(change[take].mean())))
        wknd=weekday[ix]>=5
        week.append(dict(asset=asset,weekend_rows=int(wknd.sum()),weekday_rows=int((~wknd).sum()),
            quote_weekend_over_weekday=float(np.median(m[ix[wknd],5])/np.median(m[ix[~wknd],5])),
            trade_count_weekend_over_weekday=float(np.median(m[ix[wknd],6])/np.median(m[ix[~wknd],6])),
            absolute_return_weekend_over_weekday=float(np.median(abs(f['return1'][ix[wknd]]))/np.median(abs(f['return1'][ix[~wknd]])))))
        for lag in (0,1,3):
            if lag==0:score=f['taker_quote_imbalance'][ix];outcome=f['return1'][ix]
            else:
                contiguous=d['bar_open_at'][ix[lag:]]-d['bar_open_at'][ix[:-lag]]==lag*86400000
                score=f['taker_quote_imbalance'][ix[:-lag]][contiguous]
                outcome=np.log(m[ix[lag:],3]/m[ix[:-lag],3])[contiguous]
            leadlag.append(dict(asset=asset,lag_future_sessions=lag,rows=len(score),spearman=corr(score,outcome)))
        for target,name in [(0,'upward'),(1,'downward')]:
            sign=1 if target==0 else -1
            for feature in ('return1','return3','window_change','taker_quote_imbalance','pressure3','pressure_window','pressure_change1','pressure_change3'):
                score=sign*f[feature][ix]
                univariate.append(dict(asset=asset,state=name,feature=feature,auc=auc(state[ix]==target,score),
                    scope='full-history descriptive association, not held-out predictive skill'))
    for c,name in enumerate(('upward','downward','sideways')):
        for phase,mask in [('all',np.ones(N,bool)),('switch_day',change),('continuation',~change)]:
            ix=np.flatnonzero((state==c)&mask)
            state_stats.append(dict(state=name,phase=phase,rows=len(ix),
                flow_positive_share=float(np.mean(f['taker_quote_imbalance'][ix]>0)),
                n_change_same_direction=float(np.mean(f['window_change'][ix]*(1 if c==0 else -1)>0)) if c<2 else None,
                summaries={name:summary(values[ix]) for name,values in f.items()}))
    dates=np.unique(d['bar_open_at']);books={a:{int(t):float(v) for t,v in zip(d['bar_open_at'][d['asset']==a],f['return1'][d['asset']==a])} for a in ds.asset_names}
    common=sorted(set.intersection(*[set(book) for book in books.values()]))
    returns=np.array([[books[a][t] for a in ds.asset_names] for t in common]);asset_corr=np.corrcoef(returns,rowvar=False)
    eigen=np.linalg.eigvalsh(asset_corr);breadth=float(eigen.sum()**2/(eigen**2).sum())
    position=np.zeros(N,int)
    for a in ds.asset_names:
        ix=np.flatnonzero(d['asset']==a);position[ix]=np.arange(len(ix))
    attributes=[]
    for c,name in enumerate(('upward','downward','sideways')):
        ix=state==c
        attributes.append(dict(state=name,rows=int(ix.sum()),compression_share=float(np.mean(d['attributes'][ix,1])),
            summaries={str(k):summary(d['attributes'][ix,j]) for j,k in enumerate(d['attribute_names'])}))
    result=dict(research_only=True,orders_authorized=False,source=str(args.dataset),scope='complete seven-crypto nine-channel current-state dataset only',
        overview=dict(rows=N,assets=ds.asset_names,dates=len(dates),reference_sessions=int(d['reference_sessions']),
            first_date=str(d['bar_open_at'].min().astype('datetime64[ms]')),last_date=str(d['bar_open_at'].max().astype('datetime64[ms]')),
            class_counts=np.bincount(state,minlength=3).tolist(),class_share=(np.bincount(state,minlength=3)/N).tolist(),
            switch_rows=int(change.sum()),switch_share=float(change.mean()),native_missing=int((~np.isfinite(m)).sum()),
            identical_daily_market_rows=N-len(np.unique(m,axis=0)),all_native_activity_positive=bool(np.all(m[:,4:]>0)),
            nonoverlap_2n_records=int(np.sum(position%(2*int(d['reference_sessions']))==0))),
        raw_field_summaries=raw,asset_summaries=asset_stats,diagnostic_feature_names=feature_names,
        global_diagnostic_summaries={name:summary(values) for name,values in f.items()},state_phase_summaries=state_stats,
        yearly=yearly,weekday_effects=week,univariate_auc=univariate,flow_return_leadlag=leadlag,
        correlations=dict(native_channel_names=d['market_names'].tolist(),within_asset_mean_spearman=np.mean(matrices,axis=0).tolist(),
            diagnostic_names=feature_names,diagnostic_within_asset_mean_spearman=np.mean(diagnostic_correlations,axis=0).tolist(),
            assets=ds.asset_names,common_return_dates=len(common),return_pearson=asset_corr.tolist(),
            first_return_pc_variance_share=float(eigen[-1]/eigen.sum()),linear_correlation_participation_ratio=breadth),
        label_attribute_summaries=attributes,
        limits=['No datasets or model inputs changed; derived diagnostics are not new training channels.',
            'Raw-price and activity summaries are by asset; pooled raw levels have different units and scales.',
            'All state/phase grouping uses retrospective labels, not real-time-known filtering.',
            'Univariate AUC and lead/lag correlations use consumed full history; not independent OOS, causal proof or incremental model tests.',
            'Adjacent 14-session input windows share13 bars; 28-session targets share27; assets are correlated. Nonoverlap records are not independent sample count.',
            'Correlation PCA participation ratio describes cross-sectional linear redundancy, not a count of independent trading opportunities.',
            'Funding/OI/ETF and incomplete fields were not used.'])
    args.output.mkdir(parents=True)
    (args.output/'stats.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    np.savez_compressed(args.output/'diagnostics.npz',source_row=d['source_row'],asset=d['asset'],bar_open_at=d['bar_open_at'],
        names=np.array(feature_names),values=derived_matrix,state=state,switch_label=change,research_only=True,orders_authorized=False,
        model_input_unchanged=True)
    write_report(result,args.output)
    if args.plot:plot_stats(result,args.output)
    print('saved',args.output)
    print('overview',result['overview'])
    print('return PC1',result['correlations']['first_return_pc_variance_share'],'participation',breadth)
    print('mean flow/return spearman by lag',[(lag,float(np.mean([x['spearman'] for x in leadlag if x['lag_future_sessions']==lag]))) for lag in (0,1,3)])
    print('native mean spearman',np.round(np.mean(matrices,axis=0),4))


if __name__=='__main__':main()
