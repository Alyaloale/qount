"""ETF-only replication: trailing 60/90 calendar days or sessions vs future14.

Uses retained Yahoo OHLCV and adjusted-close snapshots, with explicit price and
adjusted-return targets. No trading backtest, downloads or state-label inputs.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from scipy.stats import rankdata, spearmanr
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits

from study_past_window_future14 import correlations, metric, standardized_rank

SOURCE = Path('state/research_cache/binance_macro_etf_history_20261015')
EQUITY = {'SPY','QQQ','IWM','SMH','XLB','XLE','XLI','XLU'}
NY = ZoneInfo('America/New_York')


def load_source(root):
    book = {}; hashes = {}
    for path in sorted(root.glob('yahoo-*.json')):
        r = json.loads(path.read_text())['chart']['result'][0]
        name = r['meta']['symbol']
        if r['meta']['instrumentType'] != 'ETF':
            raise ValueError('non_etf_source')
        dates = np.array([dt.datetime.fromtimestamp(t, NY).date().toordinal() for t in r['timestamp']])
        q = r['indicators']['quote'][0]
        bars = np.column_stack([q[k] for k in ('open','high','low','close','volume')]).astype(float)
        adj = np.array(r['indicators']['adjclose'][0]['adjclose'],float)
        if (not np.isfinite(bars).all() or not np.isfinite(adj).all() or
            np.any(bars[:,:4]<=0) or np.any(bars[:,4]<0) or np.any(adj<=0) or np.any(np.diff(dates)<=0) or
            np.any(bars[:,1]<np.maximum(bars[:,0],bars[:,3])) or
            np.any(bars[:,2]>np.minimum(bars[:,0],bars[:,3]))):
            raise ValueError('invalid_source_ohlcv_or_clock')
        factor = adj/bars[:,3]
        adjusted = bars.copy(); adjusted[:,:4] *= factor[:,None]
        book[name] = dict(dates=dates, price=bars, adjusted=adjusted)
        hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    calendar = book[next(iter(book))]['dates']
    if any(not np.array_equal(b['dates'],calendar) for b in book.values()):
        raise ValueError('non_common_source_sessions')
    return book, hashes


def features(bars, dates, anchors, unit):
    close = bars[:,3]; volume = bars[:,4]
    ret = np.r_[np.nan,np.diff(np.log(close))]
    out = {}
    for w in (60,90):
        fields = []
        for t in anchors:
            start = t-w+1 if unit=='sessions' else np.searchsorted(dates,dates[t]-w+1)
            reference = t-w if unit=='sessions' else np.searchsorted(dates,dates[t]-w,side='right')-1
            b = bars[start:t+1]; c = b[:,3]; r = ret[start:t+1]; v = b[:,4]
            n = len(b); logc = np.log(c); x = np.arange(n)-(n-1)/2
            change = np.log(close[t]/close[reference]); vol = r.std()
            slope = np.dot(logc-logc.mean(),x)/np.dot(x,x)
            hi = b[:,1].max(); lo = b[:,2].min()
            recent = b[-5:]; prior = b[:-5]
            # Close-weighted share volume is only a price/volume proxy, not VWAP.
            vals = dict(momentum=change,close_over_mean=close[t]/c.mean()-1,
                        price_zscore=(logc[-1]-logc.mean())/logc.std(),
                        log_price_slope=slope,slope_over_vol=slope/vol,
                        range_location=(close[t]-lo)/(hi-lo),
                        drawdown_from_high=close[t]/hi-1,rise_from_low=close[t]/lo-1,
                        signed_path_efficiency=change/abs(r).sum(),
                        positive_day_fraction=(r>0).mean(),realized_volatility=vol,
                        downside_volatility=np.sqrt((np.minimum(r,0)**2).mean()),
                        mean_daily_range=((b[:,1]-b[:,2])/c).mean(),
                        recent5_vol_over_window=r[-5:].std()/vol,
                        recent5_volume_activity=np.log1p(recent[:,4].mean())-np.log1p(prior[:,4].mean()),
                        current_relative_volume=np.log1p(volume[t])-np.log1p(np.median(v)),
                        return_volume_correlation=np.corrcoef(r,np.log1p(v))[0,1],
                        close_over_volume_weighted_close=close[t]/np.average(c,weights=v)-1)
            for col,name in enumerate(('open','high','low','close','volume')):
                vals['raw_log_mean_'+name] = np.log1p(b[:,col].mean()) if name=='volume' else np.log(b[:,col].mean())
            fields.append(vals)
        for name in fields[0]:
            out[f'{name}_{w}d'] = np.array([f[name] for f in fields])
    for lag in range(90):
        j = anchors-lag
        past = j[:,None]+np.arange(-29,1)[None,:]
        out[f'daily_return_lag{lag}'] = ret[j]
        out[f'daily_volume_activity_lag{lag}'] = np.log1p(volume[j])-np.log1p(np.median(volume[past],axis=1))
    matrix = np.column_stack(list(out.values()))
    if not np.isfinite(matrix).all():
        raise ValueError('nonfinite_derived_feature')
    return list(out),matrix


def iso(ordinal):
    return dt.date.fromordinal(int(ordinal)).isoformat()


def stats(X,Y,names,assets,dates,seed):
    rho = np.array([correlations(x,y) for x,y in zip(X,Y)])
    mean = rho.mean(0); rx = np.array([standardized_rank(x) for x in X])
    ry = np.array([(y-y.mean())/y.std() for y in Y])
    quarters = np.array([iso(d)[:4]+'Q'+str((dt.date.fromordinal(int(d)).month-1)//3+1) for d in dates])
    years = np.array([dt.date.fromordinal(int(d)).year for d in dates])
    groups = sorted(set(quarters)); rng = np.random.default_rng(seed)
    sums = np.array([(rx[:,quarters==q]*ry[:,quarters==q,None]).sum((0,1)) for q in groups])
    counts = np.array([(quarters==q).sum()*len(assets) for q in groups])
    draws = rng.integers(len(groups),size=(2000,len(groups)))
    boot = sums[draws].sum(1)/counts[draws].sum(1)[:,None]
    ci = np.quantile(boot,[.025,.975],axis=0)
    shifts = rng.integers(90,X.shape[1]-90,size=499)
    null = np.array([np.einsum('atf,at->f',rx,np.roll(ry,int(s),axis=1))/Y.size for s in shifts])
    maxnull = abs(null).max(1)
    equity = np.array([a in EQUITY for a in assets])
    peryear = {str(y):np.array([correlations(x[years==y],z[years==y]) for x,z in zip(X,Y)]).mean(0) for y in sorted(set(years))}
    ranking = []
    for j,name in enumerate(names):
        ranking.append(dict(feature=name,raw_level=name.startswith('raw_'),mean_spearman=float(mean[j]),
                            equity_mean_spearman=float(rho[equity,j].mean()),
                            same_sign_assets=int((np.sign(rho[:,j])==np.sign(mean[j])).sum()),
                            asset_correlations={a:float(rho[i,j]) for i,a in enumerate(assets)},
                            yearly_correlations={y:float(v[j]) for y,v in peryear.items()},
                            fixed_rank_quarter_ci95=ci[:,j].tolist(),
                            circular_shift_p=float((1+(abs(null[:,j])>=abs(mean[j])).sum())/500),
                            search_wide_shift_p=float((1+(maxnull>=abs(mean[j])).sum())/500)))
    ranking.sort(key=lambda r:abs(r['mean_spearman']),reverse=True)
    top = [r for r in ranking if not r['raw_level']][:6]
    for r in top:
        j=names.index(r['feature'])
        bins=np.array([np.minimum((rankdata(x[:,j])-1)*5//len(dates),4).astype(int) for x in X])
        r['quintiles']=[dict(bin=k+1,rows=int((bins==k).sum()),up_fraction=float(Y[bins==k].mean())) for k in range(5)]
    # Check scalar SciPy independently for the leading three correlations.
    for row in ranking[:3]:
        j=names.index(row['feature'])
        direct=np.mean([spearmanr(x[:,j],y).statistic for x,y in zip(X,Y)])
        if abs(direct-row['mean_spearman'])>1e-12:
            raise ValueError('independent_spearman_mismatch')
    return ranking,quarters,years


def forward(X,Y,names,assets,dates,maturity,ranking,quarters,years):
    fixed = {'fixed_rise60':'rise_from_low_60d',
             'fixed_top':next(r['feature'] for r in ranking if not r['raw_level'])}
    models = ['frequency','select60','select90',*fixed]
    preds = {m:np.full(Y.shape,np.nan) for m in models}; folds=[]
    for year in range(2020,2026):
        for month in (1,4,7,10):
            start=dt.date(year,month,1).toordinal()
            end=dt.date(year+int(month==10),1 if month==10 else month+3,1).toordinal()
            # Exclude labels maturing on cutoff date, conservatively independent of close hours.
            tr=maturity<start; te=(dates>=start)&(dates<end)
            if not te.any():continue
            cr=np.array([correlations(x[tr],y[tr]) for x,y in zip(X,Y)]).mean(0)
            f=dict(year=year,month=month,train_dates=int(tr.sum()),test_dates=int(te.sum()),
                   last_training_maturity=iso(maturity[tr].max()),selections={})
            for ai in range(len(assets)):
                preds['frequency'][ai,te]=(Y[ai,tr].sum()+1)/(tr.sum()+2)
            for m in models[1:]:
                candidates=([names.index(fixed[m])] if m in fixed else
                            [j for j,n in enumerate(names) if n.endswith('_'+m[-2:]+'d') and not n.startswith('raw_')])
                j=candidates[int(np.argmax(abs(cr[candidates])))];f['selections'][m]=names[j]
                # Each ETF gets its own prevalence and coefficient, fitted only to matured history.
                for ai in range(len(assets)):
                    fitted=np.sort(X[ai,tr,j])
                    trainx=np.searchsorted(fitted,X[ai,tr,j],side='right')/len(fitted)
                    testx=np.searchsorted(fitted,X[ai,te,j],side='right')/len(fitted)
                    est=LogisticRegression(C=1.,max_iter=200).fit(trainx[:,None],Y[ai,tr])
                    preds[m][ai,te]=est.predict_proba(testx[:,None])[:,1]
            folds.append(f)
    valid=np.isfinite(preds['frequency'][0]); q=quarters[valid]; uq=sorted(set(q))
    rng=np.random.default_rng(20261102);draw=rng.integers(len(uq),size=(4000,len(uq)))
    result={}
    for m,p in preds.items():
        result[m]=metric(Y[:,valid].ravel(),p[:,valid].ravel(),preds['frequency'][:,valid].ravel())
        delta=(p[:,valid]-Y[:,valid])**2-(preds['frequency'][:,valid]-Y[:,valid])**2
        sums=np.array([delta[:,q==k].sum() for k in uq]);counts=np.array([(q==k).sum()*len(assets) for k in uq])
        ci=sums[draw].sum(1)/counts[draw].sum(1)
        result[m]['brier_delta_quarter_ci95']=np.quantile(ci,[.025,.975]).tolist()
        result[m]['by_year']={str(y):metric(Y[:,valid&(years==y)].ravel(),p[:,valid&(years==y)].ravel(),preds['frequency'][:,valid&(years==y)].ravel()) for y in range(2020,2026)}
        result[m]['by_asset']={a:metric(Y[ai,valid],p[ai,valid],preds['frequency'][ai,valid]) for ai,a in enumerate(assets)}
    return result,preds,folds,dict(first=iso(dates[valid][0]),last=iso(dates[valid][-1]))


def experiment(book,unit,price,output):
    assets=sorted(book);all_dates=book[assets[0]]['dates'];n=len(all_dates)
    # All variants share warmup and a full 14-session tail; prices are paired on identical anchors.
    anchors=np.arange(118,n-14)
    endpoints=(anchors+14 if unit=='sessions' else np.searchsorted(all_dates,all_dates[anchors]+14,side='right')-1)
    maturity=(all_dates[endpoints] if unit=='sessions' else all_dates[anchors]+14)
    tied=np.array([book[a][price][endpoints,3]==book[a][price][anchors,3] for a in assets])
    keep=~tied.any(0);anchors=anchors[keep];endpoints=endpoints[keep];maturity=maturity[keep]
    X=[];Y=[];R=[];checks=0
    for asset in assets:
        b=book[asset][price];names,x=features(b,all_dates,anchors,unit)
        ret=b[endpoints,3]/b[anchors,3]-1
        X.append(x);Y.append(ret>0);R.append(ret)
        for t in (250,1250,2000):
            _,full=features(b,all_dates,np.array([t]),unit)
            _,prefix=features(b[:t+1],all_dates[:t+1],np.array([t]),unit)
            np.testing.assert_array_equal(full,prefix);checks+=1
        # Independent scalar recomputation of every target and both low-distance columns.
        for i,(t,e) in enumerate(zip(anchors,endpoints)):
            if bool(ret[i]>0)!=(float(b[e,3])>float(b[t,3])):raise ValueError('target_mismatch')
            for w in (60,90):
                start=t-w+1 if unit=='sessions' else next(k for k in range(max(0,t-100),t+1) if all_dates[k]>=all_dates[t]-w+1)
                low=min(float(row[2]) for row in b[start:t+1])
                expected=float(b[t,3])/low-1
                if abs(x[i,names.index(f'rise_from_low_{w}d')]-expected)>1e-12:raise ValueError('low_distance_mismatch')
    X=np.array(X);Y=np.array(Y);R=np.array(R);dates=all_dates[anchors]
    ranking,quarters,years=stats(X,Y,names,assets,dates,20261101)
    metrics,pred,folds,test=forward(X,Y,names,assets,dates,maturity,ranking,quarters,years)
    result=dict(research_only=True,orders_authorized=False,independent_oos=False,
                assets=assets,unit=unit,price_basis=price,first_date=iso(dates[0]),last_date=iso(dates[-1]),
                target='last available close on/before t+14 calendar days' if unit=='calendar' else 'close 14 sessions later',
                horizon_sessions_range=[int((endpoints-anchors).min()),int((endpoints-anchors).max())],
                dates=len(dates),rows=Y.size,features=len(names),up_fraction=float(Y.mean()),
                tie_rows_excluded=int(tied.sum()),common_dates_excluded_for_ties=int((~keep).sum()),
                prefix_checks=checks,independent_target_checks=Y.size,independent_low_distance_checks=2*Y.size,
                first_forward_date=test['first'],last_forward_date=test['last'],
                fixed_top_feature=next(r['feature'] for r in ranking if not r['raw_level']),
                fixed_top_is_post_selection=True,ranking=ranking,forward_metrics=metrics,folds=folds)
    output.mkdir()
    (output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    with (output/'ranking.csv').open('w') as f:
        cols=['feature','raw_level','mean_spearman','equity_mean_spearman','same_sign_assets','search_wide_shift_p']
        writer=csv.DictWriter(f,fieldnames=cols);writer.writeheader();writer.writerows({k:r[k] for k in cols} for r in ranking)
    # Compact outputs: retain top six features, targets and predictions, not four full feature cubes.
    selected=[names.index(r['feature']) for r in ranking[:6]]
    np.savez_compressed(output/'observations.npz',assets=assets,dates=dates,endpoint_dates=all_dates[endpoints],
                        target_maturity=maturity,up=Y,returns=R,feature_names=np.array(names)[selected],features=X[:,:,selected],
                        **{f'prediction_{k}':v for k,v in pred.items()})
    print(unit,price,'rows',Y.size,'top',[(r['feature'],round(r['mean_spearman'],4)) for r in ranking[:5]],
          'forward', {k:round(v['brier'],5) for k,v in metrics.items()},flush=True)
    return result


def report(results,output,hashes):
    main=results['calendar_price'];lookup={r['feature']:r for r in main['ranking']}
    lines=['# ETF过去60/90天与未来14天涨跌','',
           f"主结果：{main['first_date']}—{main['last_date']}，{main['dates']:,}个共同交易日期×13只ETF={main['rows']:,}条；上涨比例{main['up_fraction']:.2%}。",
           'ETF池：'+', '.join(main['assets'])+'。其中股票ETF为SPY、QQQ、IWM、SMH、XLB、XLE、XLI、XLU；其余为债券/商品/美元产品。',
           '仅使用现有2016—2025年Yahoo缓存，未下载或宣称2026实时行情。全部为当前挑选且存续的ETF，存在名单选择和幸存者偏差。','',
           '## 研究判断','',
           '原始水平中60天平均low与未来涨跌相关绝对值最高（−0.0685），但这种价格水平关系受生命周期和市场阶段影响，不能当作跨期固定价格阈值。',
           '比例特征中，13只ETF总体以60自然日累计涨幅最强（−0.0538），90日为−0.0454，呈弱反转关系；10/13只同为负，但QQQ、GLD、TLT为正且接近零。8只股票ETF中，60日斜率/波动率更强（−0.0808），因此“最相关”依赖资产池，不能将商品、债券与股票当同质样本。',
           '60日涨幅最低/最高20%组未来上涨61.14%/53.28%，两者都超过50%；全样本上涨57.32%，不能将“此前涨得多”直接解释为更可能下跌。此前币种实验最强的60日低点距离，在ETF仅−0.0228，前推表现弱于频率基线；两实验样本年代不同，不能把差异全归因于市场类型。',
           '固定60日涨幅模型前推准确率57.01%、Brier0.24476，频率基线56.74%/0.24521；测试区间永远猜上涨也有56.83%。Brier改善季度簇95%区间[−0.00180,+0.00089]跨零，且固定候选为本轮事后挑选。自动按成熟历史选择60/90日特征的Brier分别0.24621/0.24657，均较基线差。',
           '主结果226个候选的最小搜索校正移位p为0.052，60日涨幅为0.266；不据此确认稳定预测优势。调整收盘价口径最强比例特征仍为60日涨幅（−0.0488）。若全部改用交易日口径，最强比例特征变为90日有符号路径效率（−0.0685），前推同样没有基线外优势。','',
           '## 口径','',
           '- 主结果使用过去60/90自然日内的完整交易日OHLCV；目标取14自然日后当日或之前最近交易日的收盘价，与当前收盘比较。没有用未来交易日的价格填假日。',
           '- 同时计算过去60/90个交易日、未来14个交易日的对照；所有口径使用相同起止候选锚点，平价日按各自口径剔除并报告。',
           '- price使用供应商quote价格，未再乘adjclose/close；不能认证为未经历史拆股调整的原始逐时点价格，也不含现金分红收益。',
           '- adjusted将OHLC乘缓存adjclose/close，目标比较adjclose，只是含分配调整的收益代理；不是实际付款日现金账本、税后收益或已认证PIT数据。',
           '- 原生ETF缓存只有OHLCV，无主动买卖量/额、成交笔数和真实资金净流入；不补造这些特征。',
           '- CPER有47根原始成交量为0的日线，按有效零值保留；成交量对数统一使用log1p，活动量为log1p(当前量)−log1p(历史中位量)，未将零值当缺失或填造交易。',
           '- 每口径226个候选：60/90窗口各23项，另90个历史交易日的日收益/相对成交量各一项；单日滞后统一按交易日计。',
           '- 各ETF先计算Spearman，再等权平均；原始水平标记raw，8只股票ETF的均值另存。季度簇区间为固定全样本秩协方差贡献重采样；移位p为依赖平稳近似的探索性检验。',
           '- 只做端点方向统计，无策略执行、初始资金、成本、净收益或回撤结论。既有历史已用于研究，前推不能宣称新独立样本外。','',
           '## 主结果排名','', '|特征|平均Spearman|股票ETF均值|同号数量|搜索校正移位p|','|---|---:|---:|---:|---:|']
    for r in main['ranking'][:15]:
        lines.append(f"|{r['feature']}|{r['mean_spearman']:+.4f}|{r['equity_mean_spearman']:+.4f}|{r['same_sign_assets']}/13|{r['search_wide_shift_p']:.3f}|")
    lines+=['','## 60/90天相同特征比较','', '|特征|60自然日|90自然日|','|---|---:|---:|']
    for f in ['rise_from_low','drawdown_from_high','momentum','realized_volatility','downside_volatility','mean_daily_range','recent5_volume_activity','current_relative_volume','range_location','log_price_slope']:
        lines.append(f"|{f}|{lookup[f+'_60d']['mean_spearman']:+.4f}|{lookup[f+'_90d']['mean_spearman']:+.4f}|")
    lines+=['','## 各ETF最强比例特征（主结果，事后排名）','', '|ETF|上涨比例|特征|Spearman|','|---|---:|---|---:|']
    with np.load(output/'calendar_price'/'observations.npz') as z:
        for ai,a in enumerate(main['assets']):
            candidates=[r for r in main['ranking'] if not r['raw_level'] and '_lag' not in r['feature']]
            best=max(candidates,key=lambda r:abs(r['asset_correlations'][a]))
            lines.append(f"|{a}|{z['up'][ai].mean():.2%}|{best['feature']}|{best['asset_correlations'][a]:+.4f}|")
    lines+=['','## 最强比例特征的分年稳定性与分组','']
    for r in [r for r in main['ranking'] if not r['raw_level']][:4]:
        lines += [f"- {r['feature']}：年相关 {r['yearly_correlations']}；最低/最高20%组上涨比例 {r['quintiles'][0]['up_fraction']:.2%}/{r['quintiles'][-1]['up_fraction']:.2%}。"]
    lines+=['','分组阈值使用全历史，是描述统计，不能当实时胜率。','',
            '## 按季度成熟时点前推','',
            '2020—2025年，每季度仅用此前已成熟标签选择/拟合；每ETF单独拟合训练期秩缩放与单变量逻辑回归，C=1固定，无测试期调参。频率基线逐ETF使用成熟历史上涨频率。',
            'select60/select90只在对应比例特征里按训练期平均相关选择；fixed_rise60沿用上一轮预先确定的低点距离，fixed_top是在本轮全历史排名后选择，属于事后复核。','',
            '|口径|模型|准确率|平衡准确率|AUC|Brier↓|Brier差95%季度区间|','|---|---|---:|---:|---:|---:|---|']
    for key,r in results.items():
        for model,m in r['forward_metrics'].items():
            ci=m['brier_delta_quarter_ci95']
            lines.append(f"|{key}|{model}|{m['accuracy']:.2%}|{m['balanced_accuracy']:.2%}|{m['auc']:.4f}|{m['brier']:.5f}|[{ci[0]:+.5f},{ci[1]:+.5f}]|")
    lines+=['','## 日期/复权敏感性','', '|口径|样本|上涨比例|最强比例特征|相关|','|---|---:|---:|---|---:|']
    for key,r in results.items():
        top=next(x for x in r['ranking'] if not x['raw_level'])
        lines.append(f"|{key}|{r['rows']:,}|{r['up_fraction']:.2%}|{top['feature']}|{top['mean_spearman']:+.4f}|")
    lines+=['','## 验证与复现','',
            f"4口径共{sum(r['prefix_checks'] for r in results.values())}次真实历史前缀不变性检查、{sum(r['independent_target_checks'] for r in results.values()):,}条目标和{sum(r['independent_low_distance_checks'] for r in results.values()):,}个低点距离数值独立标量复核、12项SciPy相关复核通过。",
            '缓存元数据均为ETF、共同日期一致，OHLC/成交量/adjclose均完整有效。全部源文件SHA256保存在sources.json；未修改源数据、模型、生产或原币种结果。',
            '复现：`PYTHONPATH=src ./.venv/bin/python scripts/research/study_etf_window_future14.py --output 新目录`。',
            '完整逐年/逐ETF相关、分位组与逐年/逐ETF前推指标在各口径results.json；排名在ranking.csv；紧凑目标/概率/前六特征在observations.npz。',
            'NYSE交易时段/休市来源：https://www.nyse.com/markets/hours-calendars 。']
    (output/'report.md').write_text('\n'.join(lines)+'\n')
    (output/'sources.json').write_text(json.dumps(hashes,indent=2)+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,default=SOURCE)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if args.output.exists():p.error('preserve old output; choose a new path')
    book,hashes=load_source(args.source);args.output.mkdir(parents=True)
    results={}
    for unit,price in [('calendar','price'),('calendar','adjusted'),('sessions','price'),('sessions','adjusted')]:
        key=f'{unit}_{price}';results[key]=experiment(book,unit,price,args.output/key)
    report(results,args.output,hashes)
    print('complete',args.output,flush=True)


if __name__=='__main__':
    with threadpool_limits(limits=2):main()
