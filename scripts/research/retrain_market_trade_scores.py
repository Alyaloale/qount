"""Retrain execution-aligned payoff heads and strictly past OOS calibration."""
from __future__ import annotations

import argparse
from collections import defaultdict
import datetime as dt
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np

from qount.research.market_learning import fit_candidate
from qount.research.market_model_profit import execution_price,replay_asset,summarize_portfolio
from qount.research.market_stages import market_state_machine
from qount.research.market_state_scores import (
    STATE_NAMES,state_feature_matrix,unit_payoff,action_probability_scores,past_score_threshold,
)
from qount.research.market_trade_scores import (
    OUTCOMES,outcome_code,context_matrix,fit_trade_heads,predict_trade_heads,
    fit_score_calibration,calibrated_score,
)
from qount.research.market_state_validation import scores
from train_market_state_scores import all_bars,make_panel
from study_market_model_profit import DAILY,RAW,load_npz,exchange_rules,daily_bars
from study_binance_market_states import load_markets


def json_clean(value):
    if isinstance(value,dict):return {k:json_clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [json_clean(v) for v in value]
    if isinstance(value,np.ndarray):return json_clean(value.tolist())
    if isinstance(value,(float,np.floating)):return float(value) if np.isfinite(value) else None
    if isinstance(value,np.integer):return int(value)
    return value


def economic_panel(parent,panel,decisions,full,markets,raw,filters):
    events={};rows=[]
    for asset,bars in full['crypto'].items():
        stamps=[];values=[]
        for e in raw[asset+'_funding']:
            t=int(e['fundingTime']);i=int(np.searchsorted(bars[:,0],t,side='right')-1)
            if i<0 or t>bars[i,6]:continue
            mark=float(e.get('markPrice') or bars[i,1]);stamps.append(t);values.append(float(e['fundingRate'])*mark)
        events[asset]=(np.array(stamps,np.int64),np.array(values,float))
    error=0.
    for (k,action),d in sorted(decisions.items()):
        group=str(panel['group'][k]);asset=str(panel['asset'][k]);original=int(panel['original_row'][k])
        i=int(parent['bar_index'][original]);close=markets[group][asset][i].c;delay=2 if group=='crypto' else 1
        rules=dict(fee=.0005,slippage=.0002 if group=='crypto' else .0015,tick=filters[asset]['tick'] if group=='crypto' else 0.)
        value=unit_payoff(full[group][asset],i+delay,d,events.get(asset,(np.array([],np.int64),np.array([]))),rules)
        signal_risk=abs(close-d['stop'])+close*2*(rules['fee']+rules['slippage'])
        legacy_net=value['net_unit']/signal_risk
        entry=execution_price(float(full[group][asset][i+delay,1]),d['side'],opening=True,
                              slippage=rules['slippage'],tick=rules['tick'])
        # Exact same per-unit planned risk used by position_size at execution.
        # Future entry belongs to the outcome label, never the input matrix.
        entry_risk=abs(entry-d['stop'])+entry*2*(rules['fee']+rules['slippage'])
        net=value['net_unit']/entry_risk
        error=max(error,abs(legacy_net-float(panel['returns'][k,action])))
        if value['available_at']!=panel['return_available'][k,action]:raise ValueError('retrain_label_clock_drift')
        rows.append(dict(panel_index=k,action=action,known_at=int(panel['known_at'][k]),group=group,
            maturity=value['available_at'],net_R=net,legacy_net_R=legacy_net,net_unit=value['net_unit'],
            entry_price_label=entry,entry_risk_per_unit=entry_risk,signal_risk_per_unit=signal_risk,outcome=outcome_code(value),
            X=context_matrix(panel['X'][k],close,d,action,rules,delay),filled=value['filled']))
    if error>1e-10:raise ValueError('retrain_counterfactual_pnl_drift')
    return {k:np.array([v[k] for v in rows]) for k in rows[0]},error


def quarter_key(stamp):
    d=dt.datetime.fromtimestamp(int(stamp)/1000,dt.timezone.utc)
    return d.year,(d.month-1)//3*3+1


def forecast(panel,trade):
    forecasts=[];fits=[];phase_evaluations=[];path_evaluations=[];calibrations=[];latest={}
    for group in ('crypto','etf_proxy'):
        phases=np.flatnonzero(panel['group']==group);economic=np.flatnonzero(trade['group']==group)
        quarters=defaultdict(list)
        for k in phases:
            year,month=quarter_key(panel['known_at'][k])
            if year>=2022:quarters[year,month].append(int(k))
        history={(head,gate):[] for head in ('direct','path') for gate in ('phase70','net_only')}
        for (year,month),test in sorted(quarters.items()):
            cutoff=int(dt.datetime(year,month,1,tzinfo=dt.timezone.utc).timestamp())*1000;test=np.array(test)
            past=phases[panel['state_available'][phases]<cutoff]
            train=economic[(trade['maturity'][economic]>0)&(trade['maturity'][economic]<cutoff)]
            if len(past)<200 or len(train)<200:continue
            state_model,_=fit_candidate('tree',panel['X'][past],panel['outcome'][past],seed=17)
            state_p=np.zeros((len(test),len(STATE_NAMES)))
            state_p[:,state_model[-1].classes_.astype(int)]=state_model.predict_proba(panel['X'][test])
            support=action_probability_scores(state_p);local={int(k):j for j,k in enumerate(test)}
            evaluate=economic[np.isin(trade['panel_index'][economic],test)]
            model=fit_trade_heads(trade['X'][train],trade['net_R'][train],trade['outcome'][train],trade['action'][train],trade['known_at'][train])
            output=predict_trade_heads(model,trade['X'][evaluate],trade['action'][evaluate])
            if year>=2023:
                phase_evaluations.extend(dict(group=group,index=int(k),outcome=int(panel['outcome'][k]),probabilities=v.tolist()) for k,v in zip(test,state_p))
                path_evaluations.extend(dict(group=group,index=int(i),outcome=int(trade['outcome'][i]),net_R=float(trade['net_R'][i]),
                    probabilities=v.tolist()) for i,v in zip(evaluate,output['probabilities']))
            table={head:np.full((len(test),3),-np.inf) for head in ('direct','path')};economic_lookup={}
            for j,i in enumerate(evaluate):
                k=int(trade['panel_index'][i]);a=int(trade['action'][i]);economic_lookup[k,a]=int(i)
                for head in table:
                    v=output[head+'_mean'][j]
                    if np.isfinite(v):table[head][local[k],a]=v
            bundle_cal={}
            for head in table:
                for gate in ('phase70','net_only'):
                    hist=history[head,gate]
                    threshold=past_score_threshold([r['raw'] for r in hist],[r['known_at'] for r in hist],cutoff)
                    cal=fit_score_calibration(hist,cutoff,threshold=threshold)
                    candidate=table[head].copy()
                    if gate=='phase70':candidate[support<70]=-np.inf
                    actions=candidate.argmax(1);raw_scores=candidate[np.arange(len(test)),actions]
                    mean,lower=calibrated_score(cal,raw_scores)
                    calibrations.append(dict(group=group,head=head,gate=gate,cutoff=cutoff,
                        threshold=threshold,calibration=cal))
                    bundle_cal[head,gate]=dict(calibration=cal,threshold=threshold)
                    for j,k in enumerate(test):
                        a=int(actions[j]);raw_score=float(raw_scores[j]);i=economic_lookup.get((int(k),a))
                        if i is None or not np.isfinite(raw_score):continue
                        forecasts.append(dict(group=group,head=head,gate=gate,index=int(k),action=a,evaluation=year>=2023,
                                known_at=int(panel['known_at'][k]),maturity=int(trade['maturity'][i]),
                                state_support_score=float(support[j,a]),raw_net_R=raw_score,
                                calibrated_net_R=float(mean[j]),mean_minus_error_R=float(lower[j]),threshold=threshold,
                                raw_approved=bool(raw_score>=threshold),
                                calibrated_approved=bool(cal['tail_ready'] and raw_score>=threshold and np.isfinite(mean[j]) and mean[j]>=.10 and lower[j]>0),
                                calibration_tail_valid=cal['tail_ready'],calibration_tail_dates=cal['tail_dates'],
                                actual_net_R=float(trade['net_R'][i]),economic_index=i))
                        hist.append(dict(known_at=int(panel['known_at'][k]),maturity=int(trade['maturity'][i]),
                            raw=raw_score,actual=float(trade['net_R'][i])))
            fits.append(dict(group=group,cutoff=cutoff,phase_train=len(past),economic_train=len(train),
                last_phase_maturity=int(panel['state_available'][past].max()),last_trade_maturity=int(trade['maturity'][train].max()),
                test=len(test),path_classifier_fits=1,conditional_payoff_fits=1,direct_payoff_fits=len(model['direct'])))
            latest[group]=dict(research_only=True,orders_authorized=False,group=group,cutoff=cutoff,
                state_model=state_model,trade_model=model,calibrations=bundle_cal,state_names=list(STATE_NAMES),
                outcome_names=list(OUTCOMES),unknown_probability_estimated=False,
                schema_version='execution_r_tail_v1',R_definition='execution-time planned unit risk, matching position_size',
                decision_thresholds=dict(phase_support=70,net_R_floor=.10,minimum_history_dates=40,minimum_tail_dates=20))
            print('retrain',group,year,month,'phase',len(past),'trade',len(train),flush=True)
    return forecasts,fits,phase_evaluations,path_evaluations,calibrations,latest


def replay(predictions,panel,decisions,markets,raw,filters):
    groups=defaultdict(list)
    for r in predictions:
        if r['evaluation']:groups[r['group'],r['head'],r['gate']].append(r)
    runs=[];curves={};trades=[]
    for (group,head,gate),rows in groups.items():
        for calibrated in (False,True):
            chosen=[r for r in rows if r['calibrated_approved' if calibrated else 'raw_approved']];ds=defaultdict(list)
            for r in chosen:ds[str(panel['asset'][r['index']])].append(decisions[r['index'],r['action']])
            for cost in (1,2):
                sleeves={}
                for a,bars in daily_bars(markets[group],group).items():
                    rules=(dict(tick=0.,step=1.,min_qty=1.,min_notional=0.) if group=='etf_proxy' else filters[a].copy())
                    rules.update(fee=.0005*cost,slippage=(.0015 if group=='etf_proxy' else .0002)*cost,continuous_clock=group=='crypto')
                    s=replay_asset(bars,ds.get(a,[]),[] if group=='etf_proxy' else raw[a+'_funding'],initial=10000/len(markets[group]),rules=rules)
                    s['start_at']=int(bars[0,0]);sleeves[a]=s
                summary,clocks,nav,tt=summarize_portfolio(sleeves,10000,continuous=True);rid=len(runs)
                score_key='calibrated_net_R' if calibrated else 'raw_net_R'
                runs.append(dict(id=rid,group=group,head=head,gate=gate,calibrated=calibrated,cost_multiplier=cost,
                    approved=len(chosen),summary=summary,mean_predicted_R=float(np.mean([r[score_key] for r in chosen])) if chosen else None,
                    mean_actual_R=float(np.mean([r['actual_net_R'] for r in chosen])) if chosen else None))
                curves['times_'+str(rid)]=clocks;curves['nav_'+str(rid)]=nav;trades.extend(dict(run_id=rid,**t) for t in tt)
                print('net',group,head,gate,'cal',calibrated,cost,'approved',len(chosen),'trades',len(tt),'return',round(summary['total_return'],6),flush=True)
    return runs,curves,trades


def latest_scores(parent,markets,states,bundles):
    records=[];assets=sorted(set(parent['asset']))
    for group,bundle in bundles.items():
        for asset,bars in markets[group].items():
            ix=np.flatnonzero(parent['asset']==asset);original=int(ix[np.argmax(parent['known_at'][ix])]);i=int(parent['bar_index'][original]);b=bars[i];r=states[group][asset][b.t]
            known=state_feature_matrix(parent,[original],assets);p=np.zeros((1,len(STATE_NAMES)))
            p[:,bundle['state_model'][-1].classes_.astype(int)]=bundle['state_model'].predict_proba(known);support=action_probability_scores(p)[0]
            candidates=[]
            if r['action_state'] not in ('shock','unknown'):
                for action in range(3):
                    if action==1 and group!='crypto':continue
                    side=1 if action==0 else -1;target=None
                    if action==2:
                        if r['action_state'] not in ('compression','range','wide_range'):continue
                        target=(r['previous_low20']+r['previous_high20'])/2;side=1 if b.c<target else -1
                        if group!='crypto' and side<0:continue
                        stop=r['previous_low20'] if side>0 else r['previous_high20']
                    else:stop=b.c-side*2*r['atr14']
                    if stop<=0:continue
                    rules=dict(fee=.0005,slippage=.0002 if group=='crypto' else .0015)
                    plan=dict(side=side,stop=stop,target=target,max_bars=5)
                    x=context_matrix(known[0],b.c,plan,action,rules,2 if group=='crypto' else 1)
                    candidates.append((action,x))
            action_output=[]
            if candidates:
                actions=np.array([a for a,x in candidates]);output=predict_trade_heads(bundle['trade_model'],np.stack([x for a,x in candidates]),actions)
                for j,(a,x) in enumerate(candidates):
                    cal=bundle['calibrations']['path','phase70'];mean,lower=calibrated_score(cal['calibration'],np.array([output['path_mean'][j]]))
                    qualified=bool(cal['calibration']['tail_ready'] and support[a]>=70 and output['path_mean'][j]>=cal['threshold'] and np.isfinite(mean[0]) and mean[0]>=.10 and lower[0]>0)
                    action_output.append(dict(action=a,state_support_score=float(support[a]),path_probabilities=dict(zip(OUTCOMES,output['probabilities'][j].tolist())),
                        raw_net_R=float(output['path_mean'][j]),calibrated_net_R=float(mean[0]),mean_minus_error_R=float(lower[0]),
                        threshold=cal['threshold'],high_score_support_validated=cal['calibration']['tail_ready'],
                        high_score_support_dates=cal['calibration']['tail_dates'],qualified_research_candidate=qualified))
            records.append(dict(asset=asset,group=group,known_at=int(parent['known_at'][original])*1000,model_cutoff=bundle['cutoff'],
                state_probability_scores={name:None if name=='unknown' else float(p[0,c]*100) for c,name in enumerate(STATE_NAMES)},
                actions=action_output,research_decision='RESEARCH_CANDIDATE' if any(r['qualified_research_candidate'] for r in action_output) else 'CASH',
                execution_revalidation_required=True,orders_authorized=False))
    return records


def report(r):
    lines=['# 执行收益模型修复与重新训练','',
        '保留未来第5期行情状态概率；交易头直接学习实际延迟入场后五期内的净收益路径，去掉未来状态总体收益表。历史已消费，离线研究。','',
        '## 修复','',
        '- 保留所有已知可提出的反事实动作，包括未来入场不成立的零收益；旧11,158标签按旧标尺逐值重现、成熟时间相同。',
        '- 修复R标尺：信号日贴边的极小风险距离会夸大延迟入场交易的R。新标签按实际计划成交价到止损的距离及摩擦归一化，与执行定仓公式一致；实际成交价仅生成标签，绝不进入预测特征，真实价格盈亏不裁剪。',
        '- 新交易头输入当前路径、状态、标的及已知止损/目标/成本几何，不输入实际未来状态、填单价格或退出结果。',
        '- 学习未成交、止损净亏、止盈净赚、其他净赚、其他净亏五种经济路径概率；条件收益回归在推理时积分所有可能结果，真实测试结果只用于评价。',
        '- 对照直接上下文净R回归。路径收益期望不再由未来均线状态决定；未成交收益固定0、经济收益类别预测均值遵守其符号，真实标签/收益不裁剪。',
        '- 选择校准只用过去时间外获选动作且收益已成熟的数据；按日期计样本，至少40日期。两参数正则校准修正最高分选择的高估，按日期聚类估计误差，均非盈利保证。',
        '- 高分尾部单独验证：至少20个过去成熟的不同日期，且日期均值净R减一个均值误差>0，未通过则拒绝出手。整体线性校准不能替代尾部证据。',
        '- 固定净期望≥0.10R、过去得分前10%及保守均值减误差>0才出手。数据不足空仓；同时保留未校准对照及去掉70概率硬门的消融，不根据本轮结果调参数。',
        '- 原日线执行/资金/成本：七币种i+2开盘、ETF代理次会话开盘，初始10,000、等额袖套、1%计划风险/1倍入场，币种5bp+2bp单边及实际资金费、代理5bp+15bp，双摩擦重跑。','',
        '|市场/交易头|概率门|选择校准|成本倍数|批准/实际交易|净收益|CAGR|收盘MDD|预测R/实际R|','|---|---|---|---:|---|---:|---:|---:|---|']
    for x in r['runs']:
        s=x['summary'];lines.append(f"|{x['group']}/{x['head']}|{x['gate']}|{x['calibrated']}|{x['cost_multiplier']}|{x['approved']}/{s['trades']}|{s['total_return']:+.3%}|{s['cagr']:+.3%}|{s['mdd_close']:.3%}|{x['mean_predicted_R']}/{x['mean_actual_R']}|")
    if r.get('score_diagnostics'):
        lines+=['','## 同一批原始高分机会的得分校准','',
            '下表包含被校准拒绝的机会，不按新批准结果重选样本；采用新执行R标尺。预测校准误差下降不等于已验证盈利。','',
            '|市场/头/概率门|机会|原始预测均值|校准均值|实际均值|原始/校准RMSE|','|---|---:|---:|---:|---:|---|']
        for x in r['score_diagnostics']:
            lines.append(f"|{x['group']}/{x['head']}/{x['gate']}|{x['raw_high_score_rows']}|{x['raw_mean']:.4f}|{x['calibrated_mean']:.4f}|{x['actual_mean']:.4f}|{x['raw_rmse']:.4f}/{x['calibrated_rmse']:.4f}|")
    lines+=['','## 限制','',*['- '+x for x in r['limitations']],'']
    return '\n'.join(lines)


def score_diagnostics(predictions):
    out=[]
    for group in ('crypto','etf_proxy'):
        for head in ('direct','path'):
            for gate in ('phase70','net_only'):
                rows=[r for r in predictions if r['evaluation'] and r['group']==group and r['head']==head and r['gate']==gate
                      and r['raw_approved'] and r['calibrated_net_R'] is not None and np.isfinite(r['calibrated_net_R'])]
                if not rows:continue
                raw=np.array([r['raw_net_R'] for r in rows]);cal=np.array([r['calibrated_net_R'] for r in rows]);truth=np.array([r['actual_net_R'] for r in rows])
                out.append(dict(group=group,head=head,gate=gate,raw_high_score_rows=len(rows),
                    raw_mean=float(raw.mean()),calibrated_mean=float(cal.mean()),actual_mean=float(truth.mean()),
                    raw_bias=float(np.mean(raw-truth)),calibrated_bias=float(np.mean(cal-truth)),
                    raw_rmse=float(np.sqrt(np.mean((raw-truth)**2))),calibrated_rmse=float(np.sqrt(np.mean((cal-truth)**2))),
                    insufficient_tail_dates=sum(r['calibration_tail_dates']<20 for r in rows),
                    rejected_tail_evidence=sum(not r['calibration_tail_valid'] for r in rows)))
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if args.output.exists():p.error('retain previous artifacts; choose new directory')
    parent=load_npz(DAILY);markets,_,sources=load_markets();states={g:{a:market_state_machine(b) for a,b in book.items()} for g,book in markets.items()}
    raw=json.loads(RAW.read_text())['data'];filters=exchange_rules();full={g:all_bars(book,g) for g,book in markets.items()}
    panel,decisions,info=make_panel(parent,markets,states,full,filters,raw)
    trade,label_error=economic_panel(parent,panel,decisions,full,markets,raw,filters)
    print('aligned labels',len(trade['outcome']),'counts',np.bincount(trade['outcome'],minlength=len(OUTCOMES)).tolist(),'old label max error',label_error,flush=True)
    forecasts,fits,phase_eval,path_eval,calibrations,bundles=forecast(panel,trade)
    runs,curves,trades=replay(forecasts,panel,decisions,markets,raw,filters)
    phase_summary={};path_summary={}
    for group in ('crypto','etf_proxy'):
        phase_summary[group]=scores([r for r in phase_eval if r['group']==group]);path_summary[group]=scores([r for r in path_eval if r['group']==group])
    result=dict(research_only=True,orders_authorized=False,independent_oos=False,panel=info,
        economic_rows=len(trade['outcome']),outcome_names=list(OUTCOMES),outcome_counts=np.bincount(trade['outcome'],minlength=len(OUTCOMES)).tolist(),
        old_label_max_error=label_error,R_definition='net unit PnL / execution-time planned risk per unit, same as position_size',
        legacy_R_quantiles=np.quantile(trade['legacy_net_R'],[0,.5,.99,1]).tolist(),
        execution_R_quantiles=np.quantile(trade['net_R'],[0,.5,.99,1]).tolist(),
        fits=fits,calibrations=calibrations,runs=runs,phase_summary=phase_summary,path_summary=path_summary,
        score_diagnostics=score_diagnostics(forecasts),
        sources=sources,parameters=dict(calibration_minimum_dates=40,calibration_penalty_dates=50,minimum_tail_dates=20,net_R_floor=.10,
            raw_past_quantile=.90,phase_support_threshold=70,payoff_ridge_alpha=200),
        limitations=['未来行情状态和交易路径概率是不同目标，不能横比其准确率；unknown状态未得到监督概率。',
            '校准/误差扣减仍是有限样本估计，按日期聚类不消除所有序列相关，不能宣称置信收益下界。',
            '五种经济结果严格按净收益和退出原因定义，极少数止损后资金费使净赚会归其他净赚，止盈后净亏归其他净亏。',
            '所有历史已反复消费；新架构/阈值对照不构成独立OOS，也不因某个回放正收益授予实盘资格。',
            'ETF为历史复权代理，缺原生合约/实际分红账本；历史数量规则、盘口和标记价清算未PIT认证，MDD仅收盘。',
            '预测未来第5期状态与延迟后持有5期路径分头建模，分别按自身成熟时间训练；不把状态概率解释为可持仓存活概率。',
            '双摩擦只重跑执行，不重训或偷看结果改变选择；实际资金和生产服务未访问。'])
    args.output.mkdir(parents=True)
    assets=sorted(set(parent['asset']))
    result['model_snapshots']=[]
    for group,bundle in bundles.items():
        bundle['assets']=assets;path=args.output/(group+'_model.joblib');joblib.dump(bundle,path,compress=3)
        result['model_snapshots'].append(dict(group=group,path=str(path),cutoff=bundle['cutoff'],
            sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    inference=latest_scores(parent,markets,states,bundles)
    (args.output/'results.json').write_text(json.dumps(json_clean(result),ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (args.output/'predictions.json').write_text(json.dumps(json_clean(forecasts),ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (args.output/'latest_scores.json').write_text(json.dumps(json_clean(inference),ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (args.output/'trades.json').write_text(json.dumps(trades,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    np.savez_compressed(args.output/'economic_dataset.npz',**trade);np.savez_compressed(args.output/'equity.npz',**curves)
    np.savez_compressed(args.output/'phase_predictions.npz',index=np.array([r['index'] for r in phase_eval]),probabilities=np.array([r['probabilities'] for r in phase_eval]))
    (args.output/'report.md').write_text(report(result))


if __name__=='__main__':main()
