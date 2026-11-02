"""Publish the current complete-only dataset from retained native-flow data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from qount.research.market_state_dataset import ATTRIBUTE_NAMES,DEFAULT_ROOT,SCHEMA,STATE_NAMES,validate_arrays,validate_market_inputs
from qount.research.market_state_flows import MARKET_CHANNELS,trading_flows

SOURCE=Path('state/research_runs/market_state_native_flow_dataset_20261101')


def funding_complete(source,events,rows):
    """No missing rates, stale final event, internal gap or uncovered source tail."""
    valid=np.zeros(len(rows),bool);max_gap=8*3600000+60000
    for j,row in enumerate(rows):
        if not source['funding_source_coverage_mask'][row]:continue
        first=int(source['two_n_funding_start_event_row'][row]);last=int(source['funding_asof_event_row'][row])
        if first<0 or last<first:continue
        part=slice(first,last+1);times=events['funding_time_ms'][part]
        parent=source['two_n_window_rows'][row];parent=parent[parent>=0]
        if not len(parent):continue
        start=source['bar_open_time_ms'][parent[0]]
        if (np.any(events['funding_asset'][part]!=source['asset'][row])
                or not np.isfinite(events['funding_rate'][part]).all()
                or np.any(events['funding_available_at_assumed_ms'][part]>source['known_at'][row])
                or np.any(np.diff(times)<=0) or np.any(np.diff(times)>max_gap)
                or times[0]<start or times[0]-start>max_gap
                or source['known_at'][row]-times[-1]>max_gap):continue
        valid[j]=True
    return valid


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=SOURCE)
    parser.add_argument('--output',type=Path,default=DEFAULT_ROOT);args=parser.parse_args()
    if args.output.exists():parser.error('preserve previous artifacts; choose another output')
    with np.load(args.source/'dataset.npz',allow_pickle=False) as z:s={k:z[k] for k in z.files}
    with np.load(args.source/'market_events.npz',allow_pickle=False) as z:e={k:z[k] for k in z.files}
    if str(s['target_mode'])!='current':raise ValueError('source_must_target_same_day')
    count=len(s['asset']);active=np.ones(count,bool);excluded=[]
    def require(name,condition):
        nonlocal active
        removed=active&~condition;excluded.append(dict(reason=name,rows=int(removed.sum())));active&=condition
    require('ETF/proxy raw flow fields incomplete: group excluded',s['group']=='crypto')
    require('n/2n completed input history insufficient',s['n_valid']&s['two_n_valid'])
    require('same-day state or label confirmation incomplete',s['target_mask']&(s['main_state']>=0)&(s['label_available_at']>0))
    require('native nine-channel observation incomplete',np.isfinite(s['market']).all(1))
    require('native n/2n input window incomplete',np.isfinite(s['n_raw_market']).all((1,2))&np.isfinite(s['two_n_raw_market']).all((1,2)))
    require('independent attribute targets incomplete',np.isfinite(s['attributes']).all(1))
    window_rows=s['two_n_window_rows'];safe=np.maximum(window_rows,0)
    window_clock=(window_rows>=0).all(1)&np.all(s['asset'][safe]==s['asset'][:,None],axis=1)
    window_clock&=np.all(s['known_at'][safe]==s['known_at'][:,None]-86400000*np.arange(window_rows.shape[1]-1,-1,-1)[None,:],axis=1)
    require('native input window has calendar gaps or another asset',window_clock)
    input_complete=(s['group']=='crypto')&s['n_valid']&s['two_n_valid']&window_clock
    input_complete&=np.isfinite(s['n_raw_market']).all((1,2))&np.isfinite(s['two_n_raw_market']).all((1,2))
    rows=np.flatnonzero(active);have_funding=funding_complete(s,e,rows)
    complete_fund=np.zeros(count,bool);complete_fund[rows]=have_funding
    require('funding source window incomplete',complete_fund)
    rows=np.flatnonzero(active);n=int(s['horizon'][rows[0]])
    if np.any(s['horizon'][rows]!=n):raise ValueError('mixed_reference_scales_need_separate_datasets')
    # Every active row has a known predecessor label; this is supervision only.
    previous=rows-1
    if (np.any(previous<0) or np.any(s['asset'][previous]!=s['asset'][rows])
            or np.any(s['main_state'][previous]<0)):raise ValueError('missing_predecessor_label')
    label_rows=rows[:,None]+np.arange(-n+1,n+1)[None,:]
    if np.any(label_rows<0) or np.any(label_rows>=count):raise ValueError('invalid_label_context')
    if np.any(s['asset'][label_rows]!=s['asset'][rows,None]):raise ValueError('cross_asset_label_context')
    if not np.array_equal(s['known_at'][label_rows[:,-1]],s['label_available_at'][rows]):raise ValueError('label_maturity_source_mismatch')
    data=dict(schema=np.array(SCHEMA),research_only=np.array(True),orders_authorized=np.array(False),
        source_dataset=np.array(str(args.source/'dataset.npz')),source_row=rows,
        target_mode=np.array('current'),target_offset_sessions=np.array(0),reference_sessions=np.array(n),
        asset=s['asset'][rows],source_symbol=s['source_symbol'][rows],market_type=np.array('binance_usdm_perpetual'),
        quote_currency=np.array('USDT'),volume_unit=np.array('base_asset_units'),
        bar_open_at=s['bar_open_time_ms'][rows],bar_close_at=s['bar_close_time_ms'][rows],
        decision_at=s['known_at'][rows],market_available_at=s['known_at'][rows],
        market=s['market'][rows],market_names=np.array(MARKET_CHANNELS),
        n_raw_market=s['n_raw_market'][rows],n_scaled_market=s['n_model_market'][rows],n_source_rows=s['n_window_rows'][rows],
        two_n_raw_market=s['two_n_raw_market'][rows],two_n_scaled_market=s['two_n_model_market'][rows],two_n_source_rows=s['two_n_window_rows'][rows],
        state=s['main_state'][rows],state_names=np.array(STATE_NAMES),attributes=s['attributes'][rows],attribute_names=np.array(ATTRIBUTE_NAMES),
        previous_state_label=s['main_state'][previous],switch_label=s['main_state'][rows]!=s['main_state'][previous],
        label_available_at=s['label_available_at'][rows],label_context_source_rows=label_rows,
        flow_diagnostics=trading_flows(s['market'][rows]),flow_names=s['trading_flow_names'],
        n_funding_start=s['n_funding_start_event_row'][rows],two_n_funding_start=s['two_n_funding_start_event_row'][rows],
        funding_stop=s['funding_asof_event_row'][rows]+1,funding_inputs_default_enabled=np.array(False),
        excluded_input_blocks=np.array(['ETF/proxy group','OI and long/short snapshots','funding markPrice',
            'adjustment-factor snapshots','exchange net deposits','ETF net creations','true spell age and remaining duration']),
        default_model_input_blocks=np.array(['native_market_sequence']),normalization=np.array('window-relative log OHLC; log1p native nonnegative activity; fold scaler fitted on training rows only'))
    checked=validate_arrays(data)
    args.output.mkdir(parents=True)
    np.savez_compressed(args.output/'dataset.npz',**data)
    np.savez_compressed(args.output/'funding_events.npz',asset=e['funding_asset'],observed_at=e['funding_time_ms'],
        rate=e['funding_rate'],rate_type=e['funding_rate_type'],available_at_assumed=e['funding_available_at_assumed_ms'],
        availability_verified=False,publication_lag_ms=60000,default_model_input=False,research_only=True,orders_authorized=False)
    latest_rows=np.array([np.flatnonzero(input_complete&(s['asset']==a))[-1] for a in np.unique(data['asset'])])
    latest=dict(schema=np.array(SCHEMA+'_inputs'),research_only=True,orders_authorized=False,
        asset=s['asset'][latest_rows],source_row=latest_rows,reference_sessions=np.array(n),market_names=np.array(MARKET_CHANNELS),
        market=s['market'][latest_rows],bar_open_at=s['bar_open_time_ms'][latest_rows],bar_close_at=s['bar_close_time_ms'][latest_rows],
        decision_at=s['known_at'][latest_rows],market_available_at=s['known_at'][latest_rows],
        n_raw_market=s['n_raw_market'][latest_rows],n_scaled_market=s['n_model_market'][latest_rows],n_source_rows=s['n_window_rows'][latest_rows],
        two_n_raw_market=s['two_n_raw_market'][latest_rows],two_n_scaled_market=s['two_n_model_market'][latest_rows],two_n_source_rows=s['two_n_window_rows'][latest_rows],
        funding_inputs_default_enabled=False)
    validate_market_inputs(latest)
    np.savez_compressed(args.output/'latest_inputs.npz',**latest)
    groups=[]
    for a in np.unique(data['asset']):
        own=data['asset']==a
        groups.append(dict(asset=str(a),rows=int(own.sum()),states=np.bincount(data['state'][own],minlength=3).tolist(),switches=int(data['switch_label'][own].sum())))
    result=dict(schema=SCHEMA,research_only=True,orders_authorized=False,source=str(args.source),
        source_rows=count,active_rows=len(rows),mutually_exclusive_row_exclusions=excluded,
        model_inputs=dict(default=['native_market_sequence'],channels=list(MARKET_CHANNELS),n=n,two_n=2*n,
            incomplete_blocks_used=False,funding_enabled=False,funding_reason='complete rate events retained; first publication times not independently verified'),
        labels=dict(target='S_n(k)',offset=0,maturity='k+n',main_states=list(STATE_NAMES),attributes=list(ATTRIBUTE_NAMES),
            changed_is_auxiliary_supervision=True,uncertain_is_class=False),
        excluded_blocks=data['excluded_input_blocks'].tolist(),assets=groups,validation=checked,
        latest_complete_input_rows=len(latest_rows),
        original_labels_changed=False,original_artifacts_moved_or_deleted=False,models_retrained=False)
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    lines=['# 当前完整样本集','',
        '当前入口仅包含完整币种数据。候选中的ETF、OI/多空结构、结算标记价等不完整字段不进入当前模型。原候选和历史实验保留。','',
        f'源{count:,}行，当前{len(rows):,}行、7币种；n={n}。默认输入[n,9]，可选[2n,9]，无NaN、无填充时间步。当前数据只对应两周参考尺度。','',
        '模型估计当天S_n(k)，标签由[k-n+1,k+n]确定，到k+n才成熟。switch_label是当前与前一天标签是否不同的辅助监督，绝不作为输入；仍只有上行/下行/震荡三类。','',
        '## 筛除计数（按顺序互斥）','', '|原因|筛除行|','|---|---:|']
    for item in excluded:lines.append(f"|{item['reason']}|{item['rows']}|")
    lines+=['','## 使用口径','',
        '- `dataset.npz`：完整原生九列及n/2n输入、独立标签、UTC毫秒时间、源行号、辅助切换监督。',
        '- `latest_inputs.npz`：每币缓存末日的完整行情输入，不保存未来标签；尚未成熟的标签不用于训练，不表示推断必须等待n天。当前只是缓存末日，并非实时行情。',
        '- `funding_events.npz`：只保留完整费率/时间/类型，排除缺失markPrice。原始事件上下文完整，发布时间仍为1分钟研究假设；默认不进入模型，需要显式允许假设时间才能读取。',
        '- 原始行情的成交主动性已经包含于九列。主动卖出及买卖差是代数诊断，不额外拼入默认模型输入；不称实际入金流。',
        '- 数据只做窗口内量纲缩放，未拟合全历史标准化器；均值/标准差只能用各折训练行计算。',
        '- 训练使用label_available_at < 截止时间；测试按decision_at顺序，不按随机行划分。',
        '- 所有状态、属性、previous_state_label、switch_label和label_context_source_rows属于监督/核对字段，禁止作为输入。',
        '- 这是当前数据入口；旧五列模型准确率不代表九列输入结果。未重训完整模型，未改变生产。','',
        '```python','from qount.research.market_state_dataset import CurrentStateDataset',
        'ds = CurrentStateDataset()','x = ds.inputs([0, 1], lookback="n")  # market [2, 14, 9], asset_index',
        'y = ds.targets([0, 1])  # state, attributes, changed, available_at','```','',
        '```bash',f'PYTHONPATH=src ./.venv/bin/python scripts/research/build_market_state_complete_dataset.py --output {args.output}','```','']
    (args.output/'report.md').write_text('\n'.join(lines))
    print('published',args.output,checked,'exclusions',excluded)


if __name__=='__main__':main()
