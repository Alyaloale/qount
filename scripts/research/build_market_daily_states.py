"""Build one canonical label per asset/day, then preserve labels in sequences."""
from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
import json
from pathlib import Path

import numpy as np

from qount.research.market_daily_states import daily_targets, state_chunks
from qount.research.market_regimes import REGIMES, environment_rows
from qount.research.market_trading_horizons import HORIZONS
from study_binance_market_states import load_markets
from study_market_model_profit import DAILY, load_npz


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--chunk-size',type=int,default=5)
    args=p.parse_args()
    if args.output.exists(): p.error('preserve old experiments; choose a new output')
    if args.chunk_size<1: p.error('chunk size must be positive')
    parent=load_npz(DAILY); markets,_,sources=load_markets()
    env={g:{a:environment_rows(b) for a,b in book.items()} for g,book in markets.items()}
    asset=parent['asset']; group=parent['group']; n=len(asset)
    known=parent['known_at'].astype(np.int64)*1000
    state=np.full(n,-1,np.int16)
    for k in range(n):
        g=str(group[k]);a=str(asset[k]);i=int(parent['bar_index'][k])
        label=env[g][a][markets[g][a][i].t]['regime']
        if label in REGIMES: state[k]=REGIMES.index(label)
    future=daily_targets(asset,state,known,maximum=30)
    # 30 cash sessions exceed one month; cash targets stop at 21 sessions.
    etf=group=='etf_proxy'
    for key in ('future_state','future_row'):
        future[key][etf,21:]=-1
    future['future_available_at'][etf,21:]=0
    future['future_mask'][etf,21:]=False
    spells,chunks=state_chunks(asset,state,known,maximum=args.chunk_size)
    chunk_rows=np.full((len(chunks),args.chunk_size),-1,np.int64)
    spell_ids=np.full(n,-1,np.int64)
    for j,c in enumerate(chunks):
        chunk_rows[j,:c['length']]=c['rows'];spell_ids[c['rows']]=c['spell_id']
    valid=future['future_mask']
    target_rows=future['future_row'][valid]
    source_rows=np.broadcast_to(np.arange(n)[:,None],valid.shape)[valid]
    assert np.array_equal(future['future_state'][valid],state[target_rows])
    assert np.all(asset[source_rows]==asset[target_rows])
    assert np.all(future['future_available_at'][valid]>known[source_rows])
    assert all(np.all(state[c['rows']]==c['state']) for c in chunks)
    assert sorted(k for c in chunks for k in c['rows'])==np.flatnonzero(state>=0).tolist()
    assert np.all(parent['feature_available_at']<=parent['known_at'][:,None])
    summary=[]
    for g in markets:
        members=group==g
        ss=[s for s in spells if str(group[s['first_row']])==g]
        complete=[s for s in ss if not s['right_censored']]
        summary.append(dict(group=g,rows=int(sum(members)),assets=len(markets[g]),
            state_counts={name:int(sum(state[members]==j)) for j,name in enumerate(REGIMES)},
            spells=len(ss),complete_spells=len(complete),
            completed_lengths=dict(sorted(Counter(s['length'] for s in complete).items())),
            short_complete_spells=sum(s['length']<args.chunk_size for s in complete),
            long_complete_spells=sum(s['length']>args.chunk_size for s in complete),
            right_censored=sum(s['right_censored'] for s in ss)))
    result=dict(schema='market_daily_state_sequences_v1',research_only=True,orders_authorized=False,
        label_definition='existing causal V3 daily structural rule, baseline only; not future-window majority',
        standalone_one_day_trading=False,trading_horizons=HORIZONS,
        chunk_size_is_storage_only=args.chunk_size,rows=n,spells=len(spells),chunks=len(chunks),
        future_observed_cells=int(valid.sum()),summaries=summary,sources=sources,
        limitations=[
            '逐日标签暂复用现有V3日线结构规则作为基线，不是人工真值或自然拐点认证；是否忠实描述短期反弹需结合价格图继续检验，不能靠切块方式弥补标签语义问题。',
            'V3当天标签可由当日已完成日线计算，state_available_at=known_at；若以后采用事后拐点重标，必须另记确认时刻，不能沿用当天成熟时间。',
            'future_state[:,j]是同一标的第j+1个后续实际日线观测的状态；逐日保留切换，不输出五日多数类，不用段后继复制整段。',
            '3/7/14/30自然日或3/5/10/21交易会话为候选交易期限；不新增独立1日交易任务，但预测序列仍包含其中每一天的标签。',
            '五天只控制训练/存储切块上限；真实状态段不被重定义。短段保留实际长度，长段可分块并共享spell_id；填充为-1并配mask，绝不复制末状态补足。',
            '尾段为右删失，不能据缓存结束认定状态结束；短块终止若依赖下一状态，available_at保守取该下一天标签可用时刻；未来标签按每一天独立成熟。',
            '训练必须同时限制输入known_at及逐目标future_available_at在训练截止之前；不能随机打散重叠序列。相关性/评价需按日期与状态段处理，分块不等于独立样本。',
            '固定15个存续标的、历史已消费；币种缓存止于2026-10-26，ETF/商品现金代理止于2025-12-31；非实时状态、非Binance全市场原生合约认证。',
            '只完成数据组织、标注基线和关键验证，未重训、未运行新收益实验或修改生产；此前固定窗口分类结果保留为历史对照，不据其选定交易期限。'])
    args.output.mkdir(parents=True)
    np.savez_compressed(args.output/'dataset.npz',
        X=parent['X'],feature_names=parent['feature_names'],
        feature_available_at=parent['feature_available_at']*1000,
        default_feature_mask=parent['default_feature_mask'],asset=asset,group=group,
        bar_index=parent['bar_index'],known_at=known,daily_state=state,state_available_at=known,
        state_names=np.array(REGIMES),spell_id=spell_ids,**future,
        chunk_rows=chunk_rows,chunk_mask=chunk_rows>=0,
        chunk_state=np.array([c['state'] for c in chunks],np.int16),
        chunk_available_at=np.array([c['available_at'] for c in chunks],np.int64),
        chunk_right_censored=np.array([c['short_right_censored'] for c in chunks],bool))
    for name,value in [('results.json',result),('spells.json',spells),('chunks.json',chunks)]:
        (args.output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    lines=['# 逐日市场状态标签与可变长样本', '',
        '先逐日标注，再识别连续状态段，最后按长度上限切训练/存储块。预测序列保留每一天的状态；不再用固定五天的多数状态替代每日标签。', '',
        '例如：下跌3天＋上涨10天 → 下跌[3]、上涨[5]、上涨[5]。上涨两个块共享同一段ID。若预测窗口横跨转折，目标是[跌、跌、跌、涨、涨]，而不是一个“跌”或“涨”标签。', '',
        '|市场|逐日观测|状态段|完整段|不足5天的完整段|超过5天的完整段|尾部删失段|',
        '|---|---:|---:|---:|---:|---:|---:|']
    for s in summary:
        lines.append(f"|{s['group']}|{s['rows']}|{s['spells']}|{s['complete_spells']}|{s['short_complete_spells']}|{s['long_complete_spells']}|{s['right_censored']}|")
    lines+=['',f"共{n:,}个每日标签，{len(chunks):,}块，{int(valid.sum()):,}个实际可观察未来日目标。",'',
        '日标签是当前V3规则的初版基线；标签是否符合交易尺度与样本组织是否正确是两个问题。本轮未宣称已解决自然阶段真值或预测增量。','',
        'dataset.npz包含X、逐字段可用时间、daily_state、逐日future_state/future_mask/future_available_at、共享spell_id，以及短块chunk_rows/chunk_mask。所有时间统一毫秒。', '',
        '## 限制与使用', '',*['- '+v for v in result['limitations']],'',
        '```bash',f'PYTHONPATH=src ./.venv/bin/python scripts/research/build_market_daily_states.py --chunk-size {args.chunk_size} --output {args.output}','```','']
    (args.output/'report.md').write_text('\n'.join(lines))
    print(json.dumps(dict(rows=n,spells=len(spells),chunks=len(chunks),future_cells=int(valid.sum()),summaries=summary),ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
