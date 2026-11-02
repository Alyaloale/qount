"""Future-state probabilities -> conditional net R -> selective entry scores."""
from __future__ import annotations

import argparse
from collections import defaultdict
import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np
import joblib

from qount.research.market_learning import fit_candidate
from qount.research.market_model_profit import replay_asset,summarize_portfolio
from qount.research.market_stages import market_state_machine
from qount.research.market_state_scores import (
    STATE_NAMES,ACTIONS,FEATURES,state_code,state_feature_matrix,unit_payoff,payoff_table,action_scores,action_probability_scores,past_score_threshold,
)
from qount.research.market_state_validation import scores as classification_scores
from qount.research_data.bars import NY
from study_binance_market_states import load_markets
from study_market_model_profit import DAILY,RAW,FILTERS,load_npz,exchange_rules,daily_bars


def all_bars(book,group):
    out={}
    for a,bars in book.items():
        values=[]
        for b in bars:
            if group=='crypto':start=(b.t+1-86400)*1000
            else:
                day=dt.datetime.fromtimestamp(b.t,NY).date();start=int(dt.datetime.combine(day,dt.time(9,30),NY).timestamp())*1000
            values.append([start,b.o,b.h,b.l,b.c,b.v,b.t*1000+999])
        out[a]=np.array(values,float)
    return out


def make_panel(parent,markets,states,full,filters,raw):
    names=list(parent['feature_names']);cols=[names.index(n) for n in FEATURES]
    event_map={};missing_marks=0
    for asset,bars in full['crypto'].items():
        stamps=[];values=[]
        for e in raw[asset+'_funding']:
            stamp=int(e['fundingTime']);j=int(np.searchsorted(bars[:,0],stamp,side='right')-1)
            if j<0 or stamp>bars[j,6]:continue
            mark=float(e.get('markPrice') or bars[j,1]);missing_marks+=not bool(e.get('markPrice'))
            stamps.append(stamp);values.append(float(e['fundingRate'])*mark)
        event_map[asset]=(np.array(stamps,np.int64),np.array(values,float))
    rows=[];decisions={};assets=sorted(set(parent['asset']))
    for original in np.flatnonzero(parent['bar_index']%5==0):
        a=str(parent['asset'][original]);g=str(parent['group'][original]);i=int(parent['bar_index'][original])
        b=markets[g][a][i];r=states[g][a][b.t];bars=full[g][a];entry=i+(2 if g=='crypto' else 1)
        if i+5>=len(bars) or entry+5>=len(bars):continue
        future=markets[g][a][i+5];future_state=state_code(states[g][a][future.t]['action_state'])
        state_available=(future.t+(61 if g=='crypto' else 60))*1000
        known=int(parent['known_at'][original])*1000
        if np.any(parent['feature_available_at'][original,cols]>parent['known_at'][original]):raise ValueError('state_score_future_feature')
        features=parent['X'][original,cols].astype(float)
        current=state_code(parent['state'][original]);matrix=state_feature_matrix(parent,[original],assets)[0]
        rules=dict(fee=.0005,slippage=.0002 if g=='crypto' else .0015,
                   tick=filters[a]['tick'] if g=='crypto' else 0.)
        returns=np.full(len(ACTIONS),np.nan);available=np.zeros(len(ACTIONS),np.int64);eligible=np.zeros(len(ACTIONS),bool)
        for action in range(len(ACTIONS)):
            if r['action_state'] in ('shock','unknown'):continue
            if action==1 and g!='crypto':continue
            side=1 if action==0 else -1
            target=None
            if action==2:
                if r['action_state'] not in ('compression','range','wide_range'):continue
                low=r['previous_low20'];high=r['previous_high20'];target=(low+high)/2
                side=1 if b.c<target else -1
                if g!='crypto' and side<0:continue
                stop=low if side>0 else high
            else:stop=b.c-side*2*r['atr14']
            if stop<=0:continue
            d=dict(known_at=known,entry_at=int(bars[entry,0]),side=side,stop=stop,target=target,
                   fraction=1.,max_bars=5,capacity=float(b.v*b.c*.001),original_row=int(original))
            events=event_map.get(a,(np.array([],np.int64),np.array([],float)))
            value=unit_payoff(bars,entry,d,events,rules)
            risk=abs(b.c-stop)+b.c*2*(rules['fee']+rules['slippage'])
            returns[action]=value['net_unit']/risk;available[action]=value['available_at'];eligible[action]=True
            decisions[len(rows),action]=d
        rows.append(dict(asset=a,group=g,original_row=int(original),known_at=known,current_state=current,
            outcome=future_state,state_available=state_available,X=matrix,returns=returns,
            return_available=available,eligible=eligible))
    data={k:np.array([r[k] for r in rows]) for k in rows[0]}
    return data,decisions,dict(rows=len(rows),state_names=list(STATE_NAMES),action_names=list(ACTIONS),
        numeric_features=list(FEATURES),future_state_horizon=5,unknown_training_rows=int(sum(data['outcome']==STATE_NAMES.index('unknown'))),
        unknown_probability_estimated=False,
        economic_labels=int(np.isfinite(data['returns']).sum()),missing_settlement_marks=missing_marks)


def transition_probabilities(data,train,test):
    y=data['outcome'][train];global_p=(np.bincount(y,minlength=len(STATE_NAMES))+1.)/(len(y)+len(STATE_NAMES))
    output=[]
    for k in test:
        labels=y[data['current_state'][train]==data['current_state'][k]]
        p=(np.bincount(labels,minlength=len(STATE_NAMES))+50*global_p)/(len(labels)+50)
        # Unknown has no historical supervised examples; do not invent an
        # estimated unknown-state probability or claim an OOD detector here.
        p[-1]=0.;p/=p.sum();output.append(p)
    return np.array(output)


def train_forecasts(data):
    fits=[];evaluations=[];saved=[];thresholds=[]
    for group in ('crypto','etf_proxy'):
        group_rows=np.flatnonzero(data['group']==group);history={m:[] for m in ('transition','linear','tree')}
        groups=defaultdict(list)
        for k in group_rows:
            t=dt.datetime.fromtimestamp(int(data['known_at'][k])/1000,dt.timezone.utc)
            if t.year>=2022:groups[t.year,(t.month-1)//3*3+1].append(int(k))
        for (year,month),test in sorted(groups.items()):
            cutoff=int(dt.datetime(year,month,1,tzinfo=dt.timezone.utc).timestamp())*1000;test=np.array(test)
            train=group_rows[data['state_available'][group_rows]<cutoff]
            if len(train)<200:continue
            # Payoff labels have a later clock than future-state labels when
            # entry is delayed. Never train the payoff head on immature PnL.
            eligible=data['return_available'][group_rows]
            past_returns=data['returns'][group_rows].copy();past_returns[(eligible==0)|(eligible>=cutoff)]=np.nan
            state_valid=data['state_available'][group_rows]<cutoff
            past_returns[~state_valid]=np.nan
            table=payoff_table(data['outcome'][group_rows],past_returns,data['known_at'][group_rows])
            last_payoff=int(np.max(eligible[(eligible>0)&(eligible<cutoff)])) if np.any((eligible>0)&(eligible<cutoff)) else 0
            for model in history:
                if model=='transition':p=transition_probabilities(data,train,test)
                else:
                    fitted,diagnostic=fit_candidate(model,data['X'][train],data['outcome'][train],seed=17)
                    p=np.zeros((len(test),len(STATE_NAMES)));p[:,fitted[-1].classes_.astype(int)]=fitted.predict_proba(data['X'][test])
                expected,conservative=action_scores(p,table)
                expected[~data['eligible'][test]]=-np.inf;conservative[~data['eligible'][test]]=-np.inf
                best=np.argmax(conservative,axis=1);best_score=conservative[np.arange(len(test)),best]
                prior=history[model];cut=past_score_threshold([r['best_score'] for r in prior],[r['known_at'] for r in prior],cutoff)
                fits.append(dict(group=group,model=model,cutoff=cutoff,train=len(train),test=len(test),
                    last_state_maturity=int(data['state_available'][train].max()),last_payoff_maturity=last_payoff))
                if year>=2023:
                    evaluations.append(dict(group=group,model=model,year=year,month=month,
                        scores=classification_scores([dict(outcome=int(data['outcome'][k]),probabilities=v.tolist()) for k,v in zip(test,p)])))
                    thresholds.append(dict(group=group,model=model,cutoff=cutoff,threshold=None if not np.isfinite(cut) else cut,
                        history_forecasts=len(prior),state_train=len(train),last_state_maturity=int(data['state_available'][train].max()),
                        last_payoff_maturity=last_payoff,payoff_state_dates=table['date_counts'].tolist(),
                        payoff_mean_R=table['mean'].tolist(),payoff_mean_error=table['error'].tolist()))
                    for j,k in enumerate(test):saved.append(dict(group=group,model=model,index=int(k),known_at=int(data['known_at'][k]),
                        probabilities=p[j].tolist(),expected=expected[j].tolist(),score=conservative[j].tolist(),
                        best_action=int(best[j]),best_score=float(best_score[j]),threshold=None if not np.isfinite(cut) else cut))
                prior.extend(dict(best_score=float(v),known_at=int(data['known_at'][k])) for k,v in zip(test,best_score))
            print('state probabilities',group,year,month,'past states',len(train),'predict',len(test),flush=True)
    return saved,fits,evaluations,thresholds


def backtests(data,decisions,predictions,markets,raw,filters):
    grouped=defaultdict(list)
    for r in predictions:grouped[r['group'],r['model']].append(r)
    runs=[];curves={};trades=[]
    for (group,model),rows in grouped.items():
        bars=daily_bars(markets[group],group)
        for policy in ('all_best','score_010','score_025','past_top_decile','state70_score010','state70_top_decile'):
            ds=defaultdict(list);approved=0;possible=sum(np.any(data['eligible'][r['index']]) for r in rows)
            for r in rows:
                k=r['index'];a=r['best_action'];score=r['best_score']
                if policy.startswith('state70'):
                    support=action_probability_scores(np.array([r['probabilities']]))[0]
                    candidates=np.array(r['score'],float);candidates[support<70]=-np.inf
                    a=int(np.argmax(candidates));score=float(candidates[a])
                threshold=(-np.inf if policy=='all_best' else .10 if policy in ('score_010','state70_score010')
                           else .25 if policy=='score_025' else r['threshold'])
                take=np.isfinite(score) and threshold is not None and score>=threshold
                if take and (k,a) in decisions:
                    ds[str(data['asset'][k])].append(decisions[k,a]);approved+=1
            for cost in (1,2):
                sleeves={}
                for asset,values in bars.items():
                    rules=(dict(tick=0.,step=1.,min_qty=1.,min_notional=0.) if group=='etf_proxy' else filters[asset].copy())
                    rules.update(fee=.0005*cost,slippage=(.0015 if group=='etf_proxy' else .0002)*cost,continuous_clock=group=='crypto')
                    book=replay_asset(values,ds.get(asset,[]),[] if group=='etf_proxy' else raw[asset+'_funding'],initial=10000/len(bars),rules=rules)
                    book['start_at']=int(values[0,0]);sleeves[asset]=book
                summary,clocks,nav,tt=summarize_portfolio(sleeves,10000,continuous=True)
                rid=len(runs);runs.append(dict(id=rid,group=group,model=model,policy=policy,cost_multiplier=cost,
                    opportunity_rows=int(possible),approved_signals=approved,approval_rate=approved/possible if possible else 0.,summary=summary))
                curves['times_'+str(rid)]=clocks;curves['nav_'+str(rid)]=nav;trades.extend(dict(run_id=rid,**t) for t in tt)
                print('replay',group,model,policy,cost,'approved',approved,'trades',len(tt),'return',round(summary['total_return'],6),flush=True)
    return runs,curves,trades


def save_snapshots(parent,data,result,predictions,output):
    """Reconstruct four last-quarter bundles and verify archived forecasts."""
    snapshots=[];examples=[];assets=sorted(set(parent['asset']))
    for group in ('crypto','etf_proxy'):
        for model in ('linear','tree'):
            fold=max((f for f in result['fits'] if f['group']==group and f['model']==model),key=lambda f:f['cutoff'])
            cutoff=fold['cutoff'];train=np.flatnonzero((data['group']==group)&(data['state_available']<cutoff))
            fitted,_=fit_candidate(model,data['X'][train],data['outcome'][train],seed=17)
            records=[r for r in predictions if r['group']==group and r['model']==model and r['known_at']>=cutoff]
            pp=np.zeros((len(records),len(STATE_NAMES)));pp[:,fitted[-1].classes_.astype(int)]=fitted.predict_proba(data['X'][[r['index'] for r in records]])
            error=float(np.max(abs(pp-np.array([r['probabilities'] for r in records]))))
            if error>1e-12:raise ValueError('state_score_snapshot_reproduction')
            context=next(r for r in result['thresholds'] if r['group']==group and r['model']==model and r['cutoff']==cutoff)
            table=dict(mean=np.array(context['payoff_mean_R']),error=np.array(context['payoff_mean_error']),date_counts=np.array(context['payoff_state_dates']))
            bundle=dict(research_only=True,orders_authorized=False,group=group,model=model,cutoff=cutoff,
                classifier=fitted,feature_names=list(FEATURES),assets=assets,state_names=list(STATE_NAMES),
                actions=list(ACTIONS),payoff_table=table,threshold=context['threshold'],state_probability_threshold=70.,
                unknown_probability_estimated=False)
            path=output/(group+'_'+model+'.joblib');joblib.dump(bundle,path,compress=3)
            snapshots.append(dict(group=group,model=model,path=str(path),cutoff=cutoff,
                max_probability_reproduction_error=error,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            latest=[]
            for asset in sorted(set(data['asset'][data['group']==group])):
                candidates=np.flatnonzero(parent['asset']==asset);latest.append(int(candidates[np.argmax(parent['known_at'][candidates])]))
            probability=np.zeros((len(latest),len(STATE_NAMES)))
            probability[:,fitted[-1].classes_.astype(int)]=fitted.predict_proba(state_feature_matrix(parent,latest,assets))
            expected,score=action_scores(probability,table);support=action_probability_scores(probability)
            for j,k in enumerate(latest):
                current=str(parent['state'][k]).split(':')[0];eligible=np.array([True,group=='crypto',current in ('compression','range','wide_range')])
                if current in ('shock','unknown'):eligible[:]=False
                pos=float(parent['X'][k,list(parent['feature_names']).index('range_position')])
                if group=='etf_proxy' and pos>=.5:eligible[2]=False
                candidates=score[j].copy();candidates[(support[j]<70)|~eligible]=-np.inf;a=int(np.argmax(candidates))
                cut=context['threshold'];take=bool(cut is not None and np.isfinite(candidates[a]) and candidates[a]>=cut)
                examples.append(dict(group=group,model=model,asset=str(parent['asset'][k]),known_at=int(parent['known_at'][k])*1000,
                    state_probability_scores={s:None if s=='unknown' else float(100*probability[j,c]) for c,s in enumerate(STATE_NAMES)},
                    unknown_probability_estimated=False,
                    action_support_scores=dict(zip(ACTIONS,support[j].tolist())),expected_net_R=dict(zip(ACTIONS,expected[j].tolist())),
                    conservative_net_R=dict(zip(ACTIONS,score[j].tolist())),threshold=cut,
                    research_decision=ACTIONS[a] if take else 'CASH',orders_authorized=False))
    return snapshots,examples


def summarize_forecasts(data,predictions):
    summary=[];calibration=[]
    for group in ('crypto','etf_proxy'):
        for model in ('transition','linear','tree'):
            rows=[r for r in predictions if r['group']==group and r['model']==model]
            summary.append(dict(group=group,model=model,scores=classification_scores([
                dict(outcome=int(data['outcome'][r['index']]),probabilities=r['probabilities']) for r in rows])))
            outcomes=[]
            for r in rows:
                support=action_probability_scores(np.array([r['probabilities']]))[0]
                candidates=np.array([float(v) if v is not None else -np.inf for v in r['score']]);candidates[support<70]=-np.inf
                a=int(np.argmax(candidates));threshold=r['threshold']
                if threshold is not None and candidates[a]>=max(.10,threshold):
                    actual_support=action_probability_scores(np.eye(len(STATE_NAMES))[[int(data['outcome'][r['index']])]])[0,a]/100
                    outcomes.append([r['expected'][a],candidates[a],float(data['returns'][r['index'],a]),support[a]/100,actual_support])
            means=np.mean(outcomes,axis=0).tolist() if outcomes else [None]*5
            calibration.append(dict(group=group,model=model,count=len(outcomes),expected_net_R=means[0],
                conservative_score_R=means[1],realized_net_R=means[2],
                mean_state_support_probability=means[3],actual_state_support_rate=means[4]))
    return summary,calibration


def report(r):
    lines=['# 未来状态概率与出手得分','',
        '先预测未来第5期行情状态的完整概率向量，再用过去成熟交易结果估计各状态/动作净R。历史已消费，离线探索，不是独立OOS。','',
        '## 定义','',
        '- 12个状态语义，unknown没有训练样本，不声称学会未知状态；当前规则状态是输入，未来规则状态才是监督标签。',
        '- 18个数值特征＋缺失指示、当前状态与标的ID。状态转移频率、逻辑回归、浅树固定对照，逐季拟合，仅使用成熟标签。',
        '- 各动作净R标签使用单单位完整反事实（含不成交零收益），不是仅从已执行或盈利交易学习。动作：2ATR多/空、区间中点回归，ETF只做多。',
        '- 每个未来状态的条件净R按日期汇总，再以50个日期收缩；期望净R=Σ状态概率×对应动作条件净R。保守得分再扣一个加权均值估计误差，非置信保证。',
        '- 每类状态分数=100×概率。做多支持组为上升趋势/上破/下破失败；做空为下降趋势/下破/上破失败；区间为收敛/常态/宽震荡。三组不含冲击/过渡/未知，支持分数不是盈利概率。',
        '- 主选择：对应策略支持概率≥70分，并且保守净R得分≥max(0.10R，过去时间外最佳动作得分的90%日期加权分位)，不足30历史日期则空仓。固定阈值与单层阈值对照全部保留，不根据测试收益挑阈值。',
        '- 先选一个最高分动作，得分过阈值才提交候选；实际仍受入场几何、整数数量、最小金额、容量及已有持仓限制。',
        '- 交易/成本/10,000初始资金和日线入场延迟沿用上一轮：币种i+2开盘、ETF次会话开盘；实际最多持有5期，收益成熟比未来第5期状态更晚，两个头分别排除未成熟数据。',
        '- 每标的独立等额袖套、1%计划止损风险、入场最多1倍；币种5bp佣金＋2bp摩擦/边、ETF5bp＋15bp，另重跑双摩擦。现金0利息，ETF复权代理不冒充原生合约。','',
        '|市场/概率模型|出手阈值|成本倍数|批准/机会|实际交易|净收益|CAGR|收盘MDD|','|---|---|---:|---|---:|---:|---:|---:|']
    for row in r['runs']:
        s=row['summary'];lines.append(f"|{row['group']}/{row['model']}|{row['policy']}|{row['cost_multiplier']}|{row['approved_signals']}/{row['opportunity_rows']} ({row['approval_rate']:.1%})|{s['trades']}|{s['total_return']:+.3%}|{s['cagr']:+.3%}|{s['mdd_close']:.3%}|")
    lines+=['','## 限制','',*['- '+v for v in r['limitations']],'']
    if 'classification_summary' in r:
        lines+=['## 状态概率与高分净R校准','',
            '|市场/模型|状态准确率|平衡准确率|Brier↓|','|---|---:|---:|---:|']
        for x in r['classification_summary']:
            s=x['scores'];lines.append(f"|{x['group']}/{x['model']}|{s['accuracy']:.2%}|{s['balanced_accuracy']:.2%}|{s['brier']:.5f}|")
        lines+=['','|市场/模型|通过主阈值的机会|预计净R均值|保守得分均值|实际净R均值（含不成交0）|','|---|---:|---:|---:|---:|']
        for x in r['score_calibration']:
            lines.append(f"|{x['group']}/{x['model']}|{x['count']}|{x['expected_net_R']}|{x['conservative_score_R']}|{x['realized_net_R']}|")
        lines+=['','状态预测Brier改善不等于条件收益表已校准；高分段样本少、净R失配，不认证盈利。',
            'latest_scores.json是保留数据末端的研究推理：币种至2026-10-27，ETF代理至2025-12-31，不是本次实时行情。unknown没有监督样本，显示未估计；已知11状态概率条件归一化，不声称覆盖所有未知行情。','']
    return '\n'.join(lines)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--reuse-training',type=Path);args=p.parse_args()
    if args.output.exists():p.error('preserve prior artifacts; use a new directory')
    parent=load_npz(DAILY);markets,_,sources=load_markets();raw=json.loads(RAW.read_text())['data'];filters=exchange_rules()
    states={g:{a:market_state_machine(b) for a,b in book.items()} for g,book in markets.items()}
    full={g:all_bars(book,g) for g,book in markets.items()}
    data,decisions,info=make_panel(parent,markets,states,full,filters,raw);print('panel',info,flush=True)
    if args.reuse_training:
        prior=json.loads((args.reuse_training/'results.json').read_text())
        reference={v['path']:v['sha256'] for v in prior['sources']}
        if reference.get(str(DAILY))!=hashlib.sha256(DAILY.read_bytes()).hexdigest():raise ValueError('state_score_training_cache_mismatch')
        old=load_npz(args.reuse_training/'dataset.npz')
        if any(not np.array_equal(data[k],old[k],equal_nan=True) if data[k].dtype.kind in 'fc' else not np.array_equal(data[k],old[k]) for k in data):
            raise ValueError('state_score_panel_cache_mismatch')
        predictions=json.loads((args.reuse_training/'predictions.json').read_text())
        for r in predictions:
            r['expected']=[float(v) if v is not None else -np.inf for v in r['expected']]
            r['score']=[float(v) if v is not None else -np.inf for v in r['score']]
            r['best_score']=float(r['best_score']) if r['best_score'] is not None else -np.inf
        fits,evaluations,thresholds=prior['fits'],prior['evaluations'],prior['thresholds']
    else:predictions,fits,evaluations,thresholds=train_forecasts(data)
    runs,curves,trades=backtests(data,decisions,predictions,markets,raw,filters)
    result=dict(research_only=True,orders_authorized=False,independent_oos=False,panel=info,fits=fits,
        training_reused_from=str(args.reuse_training) if args.reuse_training else None,
        actual_classifier_fits=0 if args.reuse_training else sum(f['model']!='transition' for f in fits),
        evaluations=evaluations,thresholds=thresholds,runs=runs,sources=sources+[
            dict(path=str(v),sha256=hashlib.sha256(v.read_bytes()).hexdigest()) for v in (DAILY,RAW,FILTERS)],
        limitations=['未来行情状态由固定规则定义，并非自然状态真值；不能把高延续率当作交易优势。',
            '状态概率模型和条件收益表都可能失配；误差扣减只是启发式，不能解释为收益下界或95%盈利保证。',
            '所有历史已消费，存续标的名单、代理行情与历史规则缺失限制保留；没有独立新时期验证。',
            '反事实标签不做资金/手数过滤，实际回放另做约束；高经济得分不保证小账户可下单，未增加杠杆或调整生产风险。',
            '阈值分位只使用此前时间外预测，不使用当前季度得分分布/未来收益；固定阈值敏感性全部保留，不据结果选冠军。',
            '未来5期状态与延迟后持有5期净收益期限不同，条件收益表使用更晚成熟时间；状态预测不是盘中止损概率。',
            '日线无法还原真实盘口、订单延迟与盘中极值顺序，止损优先、资金费保守处理；MDD仅收盘采样。'])
    args.output.mkdir(parents=True);np.savez_compressed(args.output/'dataset.npz',**data)
    result['model_snapshots'],examples=save_snapshots(parent,data,result,predictions,args.output)
    result['snapshot_reconstruction_fits']=len(result['model_snapshots'])
    result['classification_summary'],result['score_calibration']=summarize_forecasts(data,predictions)
    (args.output/'latest_scores.json').write_text(json.dumps(examples,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    clean=[dict(r,expected=[v if np.isfinite(v) else None for v in r['expected']],
                score=[v if np.isfinite(v) else None for v in r['score']],
                best_score=r['best_score'] if np.isfinite(r['best_score']) else None) for r in predictions]
    (args.output/'predictions.json').write_text(json.dumps(clean,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (args.output/'trades.json').write_text(json.dumps(trades,ensure_ascii=False,indent=2)+'\n')
    np.savez_compressed(args.output/'equity.npz',**curves);(args.output/'report.md').write_text(report(result))


if __name__=='__main__':main()
