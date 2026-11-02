"""Compare daily-input forecasts of 1d/3d/1w/2w/1m executable windows."""
from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
import json
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

from qount.research.market_learning import fit_candidate
from qount.research.market_model_profit import replay_asset, summarize_portfolio
from qount.research.market_trading_horizons import (
    HORIZONS, SCHEMA, STATES, horizon_observation, known_at, quarterly_masks, trading_decision,
)
from study_binance_market_states import load_markets
from study_market_model_profit import DAILY, RAW, daily_bars, exchange_rules, load_npz

BASE_FEATURES = ('momentum5_sigma', 'momentum20_sigma', 'efficiency20',
                 'relative_volatility', 'volatility_change5', 'ema50_slope5_atr',
                 'range_position', 'return1_sigma')


def metrics(y, p):
    pred = p.argmax(1)
    return dict(rows=len(y), accuracy=float(np.mean(pred == y)),
        balanced_accuracy=float(np.mean([np.mean(pred[y == c] == c) for c in np.unique(y)])),
        brier=float(np.mean(np.sum((p-np.eye(len(STATES))[y])**2, axis=1))),
        counts={state: int(sum(y == j)) for j, state in enumerate(STATES)})


def frequency(rows, train, test):
    y = np.array([r['y'] for r in rows])
    global_ = (np.bincount(y[train], minlength=len(STATES))+1)/(len(train)+len(STATES))
    result = []
    for k in test:
        own = [i for i in train if rows[i]['asset'] == rows[k]['asset']]
        result.append((np.bincount(y[own], minlength=len(STATES))+20*global_)/(len(own)+20))
    return np.array(result)


def fit_predict(matrix, y, train, test):
    fitted, _ = fit_candidate('tree', matrix[train], y[train], seed=17)
    p = np.full((len(test), len(STATES)), .01/len(STATES))
    p[:, fitted[-1].classes_.astype(int)] += .99*fitted.predict_proba(matrix[test])
    return p


def brier_interval(rows, indices, y, p, reference):
    errors = np.sum((p-np.eye(len(STATES))[y])**2, axis=1)-np.sum((reference-np.eye(len(STATES))[y])**2, axis=1)
    keys = [dt.datetime.fromtimestamp(rows[k]['known_at']/1000, dt.timezone.utc) for k in indices]
    keys = [(d.year, (d.month-1)//3) for d in keys]
    groups = sorted(set(keys))
    sums = np.array([sum(e for e,key in zip(errors,keys) if key == g) for g in groups])
    counts = np.array([keys.count(g) for g in groups])
    draws = np.random.default_rng(17).integers(0, len(groups), (2000, len(groups)))
    means = sums[draws].sum(1)/counts[draws].sum(1)
    return dict(mean=float(errors.mean()), interval95=np.quantile(means,[.025,.975]).tolist(), quarters=len(groups))


def report(result):
    lines = ['# 日线输入：交易期限原生状态预测', '',
        '所有输入均为已完成日线；比较未来1天、3天、1周、2周、约1个月的可执行持仓窗口。不是切换周/月K线，也不以长线方向否决短期机会。', '',
        '状态标签只读取该次入场至到期窗口的价格路径：方向位移、净位移/完整窗口高低范围、相对事前波动率的振幅及可观察双边穿越。不是未来末日的过去20日状态。', '',
        '固定研究标签与V3独立：upward/downward为标准化位移至少±0.5且路径效率至少0.25；其后按振幅≤1判quiet、至少3根日线且双边两次穿越判two_sided、效率≤0.25判choppy，其余mixed。日线不能证明日内路径顺序，1日期限不标two_sided。', '',
        '## 相同日线决策样本上的预测', '',
        '|市场|持仓日/会话|样本|树平衡准确率|频率基线平衡准确率|树－频率Brier差及季度簇95%区间|',
        '|---|---:|---:|---:|---:|---|']
    for r in result['forecasts']:
        m=r['tree']; b=r['frequency']; d=r['paired_brier']
        lines.append(f"|{r['group']}|{r['horizon']}|{m['rows']}|{m['balanced_accuracy']:.2%}|{b['balanced_accuracy']:.2%}|{d['mean']:+.5f} [{d['interval95'][0]:+.5f}, {d['interval95'][1]:+.5f}]|")
    lines += ['', 'Brier差小于0较好。标签重叠、资产相关、历史已消费；分期限挑选仍需后续独立验证。非重叠抽样与逐年结果保存在results.json。', '',
        '## 同一风险规则的净收益探针', '',
        '|市场|期限|路由|摩擦倍数|交易|净收益|CAGR|日收盘MDD|',
        '|---|---:|---|---:|---:|---:|---:|---:|']
    for r in result['runs']:
        s=r['summary']
        lines.append(f"|{r['group']}|{r['horizon']}|{r['policy']}|{r['cost_multiplier']}|{s['trades']}|{s['total_return']:+.3%}|{s['cagr']:+.3%}|{s['mdd_close']:.3%}|")
    lines += ['', 'local_rule直接延续过去同期限路径类别；tree_argmax不设置信门；tree70要求最高单类概率≥70%。只在upward/downward交易，其他状态等待；ETF只做多。没有长周期一致性门。', '', '## 样本与执行假设', '']
    lines += ['- '+x for x in result['limitations']]
    lines += ['', '## 复现', '', '```bash',
        f"OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=src ./.venv/bin/python scripts/research/study_market_trading_horizons.py --output {result['output']}", '```', '']
    return '\n'.join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    if args.output.exists(): parser.error('preserve existing research; choose another output')
    parent=load_npz(DAILY); markets,_,sources=load_markets()
    prices={g:daily_bars(book,g) for g,book in markets.items()}
    raw=json.loads(RAW.read_text())['data']; filters=exchange_rules()
    cols=[list(parent['feature_names']).index(n) for n in BASE_FEATURES]
    if np.any(parent['feature_available_at'][:,cols] > parent['known_at'][:,None]):
        raise ValueError('future_daily_input')
    forecasts=[]; runs=[]; curves={}; predictions={}; trades=[]; latest={}; fold_audit=[]
    windows={}
    for group,book in markets.items():
        assets=sorted(book); delay=2 if group=='crypto' else 1
        last_signal=min(known_at(b[-max(HORIZONS[group])-delay-1],group) for b in book.values())
        windows[group]=dict(first_signal='2023-01-01', last_signal=dt.datetime.fromtimestamp(last_signal/1000,dt.timezone.utc).isoformat(),
            last_price=dt.datetime.fromtimestamp(min(b[-1].t for b in book.values()),dt.timezone.utc).isoformat())
        for horizon in HORIZONS[group]:
            rows=[]; matrix=[]
            for k in np.flatnonzero(parent['group']==group):
                asset=str(parent['asset'][k]); bars=book[asset]
                r=horizon_observation(bars,int(parent['bar_index'][k]),group,horizon)
                if r is None: continue
                r.update(asset=asset, original_row=int(k)); rows.append(r)
                matrix.append(list(parent['X'][k,cols])+r['x']+list(np.eye(len(STATES))[r['current']])+[float(asset==a) for a in assets])
            matrix=np.asarray(matrix,float); y=np.array([r['y'] for r in rows])
            p=np.full((len(rows),len(STATES)),np.nan); reference=p.copy()
            dates=[dt.datetime.fromtimestamp(r['known_at']/1000,dt.timezone.utc) for r in rows]
            quarters=sorted({(d.year,(d.month-1)//3*3+1) for d in dates if d.year>=2023})
            for year,month in quarters:
                cutoff=int(dt.datetime(year,month,1,tzinfo=dt.timezone.utc).timestamp())*1000
                end=int(dt.datetime(year+int(month==10),1 if month==10 else month+3,1,tzinfo=dt.timezone.utc).timestamp())*1000
                train,test=quarterly_masks(rows,cutoff,end)
                test=test[np.array([rows[k]['known_at']<=last_signal for k in test],bool)]
                if len(train)<200 or not len(test): continue
                p[test]=fit_predict(matrix,y,train,test); reference[test]=frequency(rows,train,test)
                fold_audit.append(dict(group=group,horizon=horizon,cutoff=cutoff,end=end,
                    max_training_maturity=max(rows[k]['mature_at'] for k in train),training_rows=len(train),test_rows=len(test)))
            ix=np.flatnonzero(np.isfinite(p).all(1)); yy=y[ix]
            nonoverlap=np.array([k for k in ix if rows[k]['index']%horizon==0],int)
            yearly=[]
            for year in sorted({dates[k].year for k in ix}):
                use=np.array([k for k in ix if dates[k].year==year],int)
                yearly.append(dict(year=year,tree=metrics(y[use],p[use]),frequency=metrics(y[use],reference[use])))
            forecasts.append(dict(group=group,horizon=horizon,tree=metrics(yy,p[ix]),
                frequency=metrics(yy,reference[ix]),persistence=metrics(yy,.99*np.eye(len(STATES))[np.array([rows[k]['current'] for k in ix])]+.01/len(STATES)),
                paired_brier=brier_interval(rows,ix,yy,p[ix],reference[ix]),
                nonoverlap=dict(tree=metrics(y[nonoverlap],p[nonoverlap]),frequency=metrics(y[nonoverlap],reference[nonoverlap])),yearly=yearly))
            key=f'{group}_{horizon}'
            predictions[key+'_row']=np.array([rows[k]['original_row'] for k in ix])
            predictions[key+'_probabilities']=p[ix];predictions[key+'_actual']=yy
            # Final cached-date inference uses only targets matured before that date.
            cutoff=max(r['known_at'] for r in rows)
            train=np.array([k for k,r in enumerate(rows) if r['y']>=0 and r['mature_at']<cutoff],int)
            tail=np.array([max((k for k,r in enumerate(rows) if r['asset']==a),key=lambda k:rows[k]['known_at']) for a in assets],int)
            tail_p=fit_predict(matrix,y,train,tail)
            for k,prob in zip(tail,tail_p):
                latest.setdefault(rows[k]['asset'],{})[str(horizon)]=dict(known_at=rows[k]['known_at'],
                    probabilities=dict(zip(STATES,map(float,prob))))
            for policy in ('local_rule','tree_argmax','tree70'):
                decisions={a:[] for a in assets}
                for k in ix:
                    cls=rows[k]['current'] if policy=='local_rule' else int(p[k].argmax())
                    if policy=='tree70' and p[k].max()<.7: continue
                    d=trading_decision(rows[k],book[rows[k]['asset']],group,cls)
                    if d: decisions[rows[k]['asset']].append(d)
                for cost in (1,2):
                    sleeves={}
                    for a,daily in prices[group].items():
                        rules=(dict(tick=0.,step=1.,min_qty=1.,min_notional=0.) if group=='etf_proxy' else filters[a].copy())
                        rules.update(fee=.0005*cost,slippage=(.0015 if group=='etf_proxy' else .0002)*cost,continuous_clock=group=='crypto')
                        s=replay_asset(daily,decisions[a],[] if group=='etf_proxy' else raw[a+'_funding'],initial=10000/len(assets),rules=rules)
                        s['start_at']=int(daily[0,0]);sleeves[a]=s
                    summary,times,nav,tt=summarize_portfolio(sleeves,10000,continuous=True)
                    rid=len(runs);runs.append(dict(id=rid,group=group,horizon=horizon,policy=policy,cost_multiplier=cost,summary=summary))
                    curves[f'times_{rid}']=times;curves[f'nav_{rid}']=nav
                    trades.extend(dict(run_id=rid,**t) for t in tt)
            print(group,horizon,'balanced',round(forecasts[-1]['tree']['balanced_accuracy'],4),'brier_delta',round(forecasts[-1]['paired_brier']['mean'],5),flush=True)
    result=dict(schema=SCHEMA,research_only=True,orders_authorized=False,independent_oos=False,output=str(args.output),
        horizons=HORIZONS,state_names=STATES,features=list(BASE_FEATURES)+['8 horizon-local features','current local path onehot','asset onehot'],
        sources=sources,windows=windows,forecasts=forecasts,runs=runs,folds=fold_audit,
        limitations=[
            '统一使用日线输入，币种期限1/3/7/14/30自然日，ETF代理1/3/5/10/21交易会话；1个月为固定近似，不是自然月K线。',
            '币种七标的、ETF/商品八代理；研究预测期从2023起，各市场用最长目标可成熟的同一最后决策日，具体日期见windows；净值延伸至缓存末端以结算最后持仓。',
            '币种信号i+2开盘入场，ETF下一会话开盘；到期为入场+h开盘，标签成熟为到期可见后60秒；特征全部截止信号日。未用当前长线方向否决短线交易。',
            '季度训练仅取此前成熟标签，测试严格限制该季度，预测行不跨折重复；日常滚动标签仍重叠，按季度聚类并另报每标的间隔h根抽样。',
            '固定浅树/80轮/7叶/深3/最小叶60/正则10/种子17，无超参或门槛搜索；标签阈值是待检验的描述假设，不能比较不同期限准确率就认定盈利优势。',
            '首轮v1用净位移/累计日振幅，导致随h增长趋势类别机械稀少；当前v2改为净位移/整个窗口高低范围，旧工件保留，不用于期限排名。',
            '每组合初始10,000、等额袖套、单仓至多1倍名义/1%计划风险；止损距离为事前2*sigma20*sqrt(h)，没有止盈，到期退出，现金收益0。提前止损后可按新的日线信号再入场。',
            '复用日线执行器：日线跳空止损、同根止损优先、真实币种资金费、现行数量档位/ETF整数股、信号日日成交额0.1%容量近似；单边币种5+2bp，ETF5+15bp；双摩擦完整重跑。',
            'local_rule为同期限历史路径延续基准，现金0为收益基准；未与同实际波动风险的被动持有匹配。期限不同导致真实风险/占仓不同，不能仅按CAGR选冠军。',
            '固定存续标的、历史已消费；ETF为复权现金代理且禁止做空，非Binance原生合约；日线不证明盘中顺序、真实成交或尾部安全，MDD只按日收盘。',
            '本实验先筛期限与目标定义，不认证模型校准、独立样本外盈利或实盘权限；未改现有模型、线上策略或服务。'])
    args.output.mkdir(parents=True)
    for name,value in [('results.json',result),('latest_probabilities.json',latest),('trades.json',trades)]:
        (args.output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    np.savez_compressed(args.output/'predictions.npz',**predictions)
    np.savez_compressed(args.output/'equity.npz',**curves)
    (args.output/'report.md').write_text(report(result))
    print('saved',args.output,'fits',len(fold_audit)+10,flush=True)


if __name__=='__main__':
    with threadpool_limits(limits=1):
        main()
