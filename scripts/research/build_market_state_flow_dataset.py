"""Restore native kline fields, trading flow, funding events and cached OI.

Uses retained public caches only. Preserves same-day labels and existing rows;
creates a separate data candidate and never trains or changes production.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
from pathlib import Path
import zipfile

import numpy as np

from qount.research.binance_macro_history import adjusted_bars
from qount.research.market_state_flows import (
    FLOW_NAMES,MARKET_CHANNELS,POSITION_NAMES,asof_indices,gather_windows,
    normalize_market_windows,trading_flows,
)

CRYPTO=Path('state/research_cache/independent_crypto_factors_20261027/panel_seven.json')
ETF=Path('state/research_cache/binance_macro_etf_history_20261015')
METRICS=Path('state/research_cache/position_flow_20261027')
PROXIES={'SPYUSDT':'SPY','QQQUSDT':'QQQ','IWMUSDT':'IWM','SMHUSDT':'SMH',
         'XLEUSDT':'XLE','XAUUSDT':'GLD','CLUSDT':'USO','COPPERUSDT':'CPER'}


def metrics_events():
    book={};duplicates=0;paths=sorted(METRICS.glob('*-metrics-*.zip'))
    for path in paths:
        asset=path.name.split('-metrics-')[0]
        if asset not in ('BTCUSDT','ETHUSDT','SOLUSDT'):continue
        with zipfile.ZipFile(path) as archive:
            with archive.open(archive.namelist()[0]) as stream:
                for row in csv.DictReader(io.TextIOWrapper(stream)):
                    if row['symbol']!=asset:raise ValueError('metrics_symbol_mismatch')
                    stamp=dt.datetime.fromisoformat(row['create_time'])
                    if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=dt.timezone.utc)
                    timestamp=int(stamp.timestamp())*1000
                    values=[]
                    for name in POSITION_NAMES:
                        try:value=float(row[name])
                        except (KeyError,TypeError,ValueError):value=np.nan
                        values.append(value)
                    values=np.array(values,float);key=(asset,timestamp)
                    if key in book:
                        if not np.array_equal(book[key],values,equal_nan=True):raise ValueError('conflicting_metrics_duplicate')
                        duplicates+=1
                    else:book[key]=values
    keys=sorted(book)
    return dict(asset=np.array([k[0] for k in keys]),observed_at=np.array([k[1] for k in keys],np.int64),
        values=np.array([book[k] for k in keys]),archive_files=len(paths),duplicates=duplicates)


def funding_events(raw):
    records=[]
    for asset in sorted(set(key.removesuffix('_funding') for key in raw if key.endswith('_funding'))):
        for row in raw[asset+'_funding']:
            mark=float(row['markPrice']) if row.get('markPrice') else np.nan
            records.append((asset,int(row['fundingTime']),float(row['fundingRate']),mark,str(row.get('rateType',''))))
    records.sort(key=lambda r:(r[0],r[1],r[4]))
    return dict(asset=np.array([r[0] for r in records]),time=np.array([r[1] for r in records],np.int64),
        rate=np.array([r[2] for r in records]),mark_price=np.array([r[3] for r in records]),
        rate_type=np.array([r[4] for r in records]))


def report(r,output):
    lines=['# 完整原生日线、主动成交与合约上下文数据','',
        '已从现有缓存恢复遗漏字段，保持原标的、日线顺序、当天主状态和独立属性标签不变。没有新下载、模型训练或交易。','',
        '## 原生日线与成交动向','',
        '币种主行情从5列扩到9列：O/H/L/C、基础币成交量、计价币成交额、成交笔数、主动买入基础币量、主动买入成交额；另保存原始开/收盘时间。主动卖出量/额由总量减主动买入还原，买卖成交额差只表示成交主动性，不叫真实资金净流入。','',
        '|标的|日线|九列原生完整|资金费率事件|日线可对齐费率|OI等6列新鲜快照（假设可用时点）|','|---|---:|---:|---:|---:|---:|']
    for c in r['coverage']:lines.append(f"|{c['asset']}|{c['rows']}|{c['market_nine_complete']}|{c['funding_events']}|{c['funding_asof_rows']}|{c['position_daily_rows']}|")
    lines+=['','## 资金动向的三种含义','',
        '- 主动成交：买方/卖方发起的成交量和成交额、成交笔数，现有币种日线完整；总成交额同时有买卖双方，差额不代表交易所新增现金。',
        '- 合约敞口：保存OI数量/名义价值及账户/持仓多空比等6列原始快照；OI变化反映未平仓敞口，不等于实际入金。',
        '- 持仓成本：保存资金费率原始结算事件、时间、类型及可用的结算标记价；它是另一类上下文，不用费率替代资金流。','',
        '交易所净充值提现、链上交易所净流入、ETF净申赎/份额变化，这批数据没有可信原始序列，本轮未制造这些字段或用主动买卖差冒充。','',
        '## 时间、缺失和价格口径','',
        '资金费率和OI事件表独立保存；每天只对齐到决策时刻之前的事件。费率发布时滞暂按1分钟、OI快照按5分钟研究假设，均非实测首次发布时间，事件表有明确assumed标记；OI到决策时刻超过20分钟则不作为新鲜日线值。未插值或把缺失填0。','',
        '费率事件保留不规则结算间隔；markPrice缺失维持NaN，不以开盘价代填。末尾超出源缓存cutoff的费率上下文标记为覆盖不足。','',
        'ETF/商品组恢复源缓存quote OHLCV（未再乘adjclose/close），同时保留原五列复权版本、adjclose与复权因子快照。供应商历史quote也不能直接认证为未经任何调整的交易所逐时点原价；快照复权因子没有逐历史时点可用性证明，不作为默认模型通道。原标签继续沿用旧复权价格定义，新旧价格口径需要在后续实验中显式区分。','',
        'ETF代理源缓存没有主动买卖、原生成交额/笔数、资金费率或OI，相关列为NaN并附掩码。分红/拆股事件不在这些缓存里。','',
        '## 文件与输入','',
        '- `dataset.npz`：逐日9列原始行情、原5列版本、主动成交分解、原始时间、n/2n窗口及缺失掩码、OI日线候选及窗口、费率可用事件索引、原标签与目标时间。',
        '- `market_events.npz`：资金费率结算原始事件和OI/多空比原始快照，原始观测时间与假设可用时间分别保存。',
        '- 新市场窗口为`[batch,n,9]`或`[batch,2n,9]`，仅做相对价格对数和其他非负原始字段log1p；训练折标准化尚未拟合。OI输入附逐字段掩码；费率通过事件索引提取原始事件，不强制压成技术指标。',
        '- 这是数据候选；原5通道GRU与既有准确率没有自动迁移到新输入。','',
        '```bash',f'PYTHONPATH=src ./.venv/bin/python scripts/research/build_market_state_flow_dataset.py --output {output}','```','']
    return '\n'.join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=Path('state/research_runs/market_state_current_raw_sequences_20261101/dataset.npz'))
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if args.output.exists():parser.error('preserve prior data; choose another output')
    with np.load(args.source,allow_pickle=False) as z:base={k:z[k] for k in z.files}
    cache=json.loads(CRYPTO.read_text());raw=cache['data'];N=len(base['asset']);known=base['known_at']
    market=np.full((N,9),np.nan);source_time=np.zeros(N,np.int64)
    open_time=np.full(N,-1,np.int64);close_time=np.full(N,-1,np.int64)
    adj_close=np.full(N,np.nan);factor=np.full(N,np.nan)
    for asset in np.unique(base['asset']):
        ix=np.flatnonzero(base['asset']==asset)
        if base['group'][ix[0]]=='crypto':
            rows=np.asarray(raw[str(asset)+'_klines'],float)
            if rows.shape!=(len(ix),12):raise ValueError('source_kline_shape_mismatch')
            assert np.array_equal(rows[:,1:6],base['ohlcv'][ix])
            assert np.array_equal((rows[:,6].astype(np.int64)//1000)*1000+61000,known[ix])
            market[ix]=rows[:,[1,2,3,4,5,7,8,9,10]]
            open_time[ix]=rows[:,0].astype(np.int64);close_time[ix]=rows[:,6].astype(np.int64);source_time[ix]=open_time[ix]
        else:
            path=ETF/f'yahoo-{PROXIES[str(asset)]}-20160101-2026-01-01.json';payload=json.loads(path.read_text())
            record=payload['chart']['result'][0];q=record['indicators']['quote'][0]
            legacy=np.array([[b.o,b.h,b.l,b.c,b.v] for b in adjusted_bars(payload)])
            assert np.array_equal(legacy,base['ohlcv'][ix])
            market[ix,:5]=np.c_[*[np.asarray(q[k],float) for k in ('open','high','low','close','volume')]]
            source_time[ix]=np.asarray(record['timestamp'],np.int64)*1000
            adj_close[ix]=np.asarray(record['indicators']['adjclose'][0]['adjclose'],float)
            factor[ix]=adj_close[ix]/market[ix,3]
    flows=trading_flows(market)
    funds=funding_events(raw);metrics=metrics_events()
    fund_available=funds['time']+60000;metric_available=metrics['observed_at']+300000
    fund_cutoff=int(dt.datetime.fromisoformat(cache['cutoff'].replace('Z','+00:00')).timestamp())*1000
    fund_asof=np.full(N,-1,np.int64);fund_age=np.full(N,-1,np.int64);fund_coverage=np.zeros(N,bool)
    fund_start_n=np.full(N,-1,np.int64);fund_start_two=np.full(N,-1,np.int64)
    position=np.full((N,len(POSITION_NAMES)),np.nan);position_row=np.full(N,-1,np.int64)
    position_observed=np.zeros(N,np.int64);position_available=np.zeros(N,np.int64)
    for asset in np.unique(base['asset']):
        ix=np.flatnonzero(base['asset']==asset);f=np.flatnonzero(funds['asset']==asset)
        if len(f):
            assert np.all(np.diff(funds['time'][f])>0)
            local=asof_indices(funds['time'][f],fund_available[f],known[ix]);good=local>=0
            fund_asof[ix[good]]=f[local[good]];fund_age[ix[good]]=known[ix[good]]-funds['time'][f[local[good]]]
            fund_coverage[ix]=known[ix]<=fund_cutoff
            for key,destination in [('n_window_rows',fund_start_n),('two_n_window_rows',fund_start_two)]:
                for row in ix:
                    history=base[key][row];history=history[history>=0]
                    valid_key='n_valid' if key=='n_window_rows' else 'two_n_valid'
                    if not base[valid_key][row] or fund_asof[row]<0:continue
                    start=open_time[history[0]];first=int(np.searchsorted(funds['time'][f],start,side='left'))
                    if first<len(f) and f[first]<=fund_asof[row]:destination[row]=f[first]
        m=np.flatnonzero(metrics['asset']==asset)
        if len(m):
            local=asof_indices(metrics['observed_at'][m],metric_available[m],known[ix],max_age_ms=20*60000)
            good=local>=0;chosen=m[local[good]]
            position[ix[good]]=metrics['values'][chosen];position_row[ix[good]]=chosen
            position_observed[ix[good]]=metrics['observed_at'][chosen];position_available[ix[good]]=metric_available[chosen]
    market_n,n_mask=gather_windows(market,base['n_window_rows']);market_two,two_mask=gather_windows(market,base['two_n_window_rows'])
    position_n,position_n_mask=gather_windows(position,base['n_window_rows'])
    position_two,position_two_mask=gather_windows(position,base['two_n_window_rows'])
    # Global references always stay within the same asset and its decision clock.
    have=fund_asof>=0
    assert np.all(fund_available[fund_asof[have]]<=known[have])
    assert np.array_equal(funds['asset'][fund_asof[have]],base['asset'][have])
    have_position=position_row>=0
    assert np.all(position_available[have_position]<=known[have_position])
    assert np.all(known[have_position]-position_observed[have_position]<=20*60000)
    assert np.array_equal(metrics['asset'][position_row[have_position]],base['asset'][have_position])
    args.output.mkdir(parents=True)
    inherited={k:base[k] for k in ('asset','group','known_at','horizon','main_state','attributes','attribute_names',
        'label_available_at','target_main_state','target_attributes','target_row','target_mask','target_available_at',
        'target_mode','main_state_names','feature_available_at','n_window_rows','n_valid','two_n_window_rows','two_n_valid')}
    np.savez_compressed(args.output/'dataset.npz',**inherited,
        schema=np.array('daily_native_market_flow_candidate_v1'),research_only=True,orders_authorized=False,label_uses_future=True,
        source_symbol=np.array([str(a) if g=='crypto' else PROXIES[str(a)] for a,g in zip(base['asset'],base['group'])]),
        source_market=np.where(base['group']=='crypto','binance_um_perpetual','yahoo_etf_proxy'),
        quote_currency=np.where(base['group']=='crypto','USDT','USD'),
        volume_unit=np.where(base['group']=='crypto','base_asset_units','proxy_fund_shares'),
        market=market,market_names=np.array(MARKET_CHANNELS),market_mask=np.isfinite(market),legacy_ohlcv=base['ohlcv'],
        source_timestamp_ms=source_time,bar_open_time_ms=open_time,bar_close_time_ms=close_time,
        etf_adjusted_close_snapshot=adj_close,etf_adjustment_factor_snapshot=factor,etf_adjustment_pit_verified=False,
        n_raw_market=market_n,n_model_market=normalize_market_windows(market_n),n_market_mask=n_mask,
        two_n_raw_market=market_two,two_n_model_market=normalize_market_windows(market_two),two_n_market_mask=two_mask,
        trading_flow=flows,trading_flow_names=np.array(FLOW_NAMES),trading_flow_mask=np.isfinite(flows),
        position_values_assumed_asof=position,position_names=np.array(POSITION_NAMES),position_mask=np.isfinite(position),
        position_event_row=position_row,position_observed_at_ms=position_observed,position_available_at_assumed_ms=position_available,
        n_position_values_assumed_asof=position_n,n_position_mask=position_n_mask,
        two_n_position_values_assumed_asof=position_two,two_n_position_mask=position_two_mask,
        funding_asof_event_row=fund_asof,funding_event_age_ms=fund_age,funding_source_coverage_mask=fund_coverage,
        n_funding_start_event_row=fund_start_n,two_n_funding_start_event_row=fund_start_two,
        event_data_file=np.array('market_events.npz'),event_publication_times_assumed=True,
        exchange_cash_deposit_flow_available=False,etf_creation_redemption_flow_available=False)
    np.savez_compressed(args.output/'market_events.npz',research_only=True,orders_authorized=False,
        funding_asset=funds['asset'],funding_time_ms=funds['time'],funding_rate=funds['rate'],
        funding_mark_price=funds['mark_price'],funding_mark_price_mask=np.isfinite(funds['mark_price']),funding_rate_type=funds['rate_type'],
        funding_available_at_assumed_ms=fund_available,funding_source_cutoff_ms=fund_cutoff,
        position_asset=metrics['asset'],position_observed_at_ms=metrics['observed_at'],position_values=metrics['values'],
        position_value_mask=np.isfinite(metrics['values']),position_names=np.array(POSITION_NAMES),
        position_available_at_assumed_ms=metric_available,event_publication_times_assumed=True)
    coverage=[]
    for asset in np.unique(base['asset']):
        rows=base['asset']==asset
        coverage.append(dict(asset=str(asset),group=str(base['group'][rows][0]),rows=int(rows.sum()),
            market_nine_complete=int(np.isfinite(market[rows]).all(1).sum()),
            trading_flow_rows=int(np.isfinite(flows[rows]).all(1).sum()),funding_events=int(sum(funds['asset']==asset)),
            funding_asof_rows=int(sum(fund_asof[rows]>=0)),funding_source_coverage_rows=int(sum(fund_coverage[rows])),
            position_daily_rows=int(np.isfinite(position[rows]).all(1).sum()),
            position_any_field_rows=int(np.isfinite(position[rows]).any(1).sum())))
    result=dict(research_only=True,orders_authorized=False,source=str(args.source),source_caches=[str(CRYPTO),str(ETF),str(METRICS)],
        rows=N,market_fields=MARKET_CHANNELS,flow_fields=FLOW_NAMES,position_fields=POSITION_NAMES,
        funding_event_count=len(funds['time']),funding_mark_price_missing=int(sum(~np.isfinite(funds['mark_price']))),
        position_event_count=len(metrics['observed_at']),metrics_archive_files=metrics['archive_files'],
        identical_metrics_duplicates=metrics['duplicates'],coverage=coverage,
        availability_assumptions=dict(funding_publication_lag_ms=60000,position_publication_lag_ms=300000,
            position_max_age_ms=20*60000,publication_time_verified=False),
        actual_exchange_cash_flow_available=False,etf_creation_redemption_flow_available=False,
        labels_changed=False,models_retrained=False,production_changed=False)
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (args.output/'report.md').write_text(report(result,args.output))
    print('saved',args.output,'funding events',result['funding_event_count'],'position events',result['position_event_count'])
    for row in coverage:print(row)


if __name__=='__main__':main()
