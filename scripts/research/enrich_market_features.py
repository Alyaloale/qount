"""Audit the saved dataset and append useful cached, asof-safe source features."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np

from qount.research.market_feature_enrichment import (
    FIELDS,NEW_NAMES,UNVERIFIED,QUALITY,csv_proxy_records,enrich,hourly_snapshots,intraday_metric_snapshots,proxy_records,
)
from qount.research.market_learning_data import FEATURE_DESCRIPTIONS
from qount.research.market_state_profiles import CATEGORIES
from qount.research.market_stages import market_state_machine
from study_binance_market_states import load_markets


RULES={
    "price_state":"Completed own/benchmark signal OHLC, fixed state calculations; one-minute publication buffer",
    "price_activity":"Known daily quote turnover, or ETF raw close*volume proxy; not executable depth",
    "crypto_derivatives":"Settled funding/Kline taker flow or published metric observations; no ETF backfill",
    "price_path":"Own completed OHLC path only, no centered/future window",
    "peer_context":"Same completed clock, fixed representative peers, not point-in-time full universe",
    "crypto_activity":"Binance Kline counts and already settled funding; no constant settlement interval",
    "macro_context":"Backward asof across13 ETF proxies, each source calculated separately; max96h age",
    "global_context":"Backward asof retained EEM/EFA/DBC/IEF/BIL adjusted closes, NY16:00+60s; max96h age; no stitching",
    "metrics_intraday":"Same UTC day, >=260 valid5m OI observations, <=15m gaps, assumed5m release lag",
    "spot_perpetual":"Exactly24 matched spot/futures hourly bars, all completed plus60s buffer",
    "calendar":"Underlying bar's UTC crypto or New York ETF calendar, never future observed trading dates",
}


def source_group(name):
    if name.startswith(("funding_","taker_","oi_","top_position")):return "crypto_derivatives"
    if name.startswith(("turnover_","illiquidity_")):return "price_activity"
    return "price_state"


def old_metadata(name):
    """Exact window/units, rather than guessing from a column-name suffix."""
    metadata={
        'ema20_distance_atr':('ATR units','EMA20 recursive history; ATR14'),
        'ema50_distance_atr':('ATR units','EMA50 recursive history; ATR14'),
        'ema200_distance_atr':('ATR units','EMA200 recursive history; ATR14'),
        'momentum5_sigma':('sigma units','5-bar return; sigma20'),
        'momentum20_sigma':('sigma units','20-bar return; sigma20'),
        'efficiency20':('fraction','20 price changes'),
        'signed_efficiency20':('signed fraction','20 price changes'),
        'relative_volatility':('log ratio','sigma20 / median of up to252 strictly prior available sigma20; 200-bar warmup'),
        'volatility_change5':('log ratio','sigma20 now versus five bars ago'),
        'ema50_slope5_atr':('ATR units','EMA50 five-bar change; ATR14'),
        'range_position':('fraction; can exceed [0,1]','strictly prior20 highs/lows'),
        'action_age':('log count','consecutive causal action/event state observations'),
        'direction_age':('log count','consecutive causal raw-direction observations'),
        'event_age':('fraction of three bars','active causal event history'),
        'event_distance_atr':('signed ATR units','fixed event boundary; current ATR14'),
        'return1_sigma':('previous sigma units','1-bar return; strictly previous sigma20'),
        'benchmark_direction':('direction code -1/0/+1','benchmark close/EMA50, five-bar EMA50 slope and20-bar momentum agreement'),
        'benchmark_efficiency':('fraction','20 benchmark price changes'),
        'relative_momentum20_sigma':('sigma units','20-bar own/benchmark returns; own sigma20'),
        'volatility126_annual':('annualized return fraction','126 log returns; sqrt365.25 crypto / sqrt252 ETF'),
        'efficiency20_median126':('fraction','126 completed ER20 observations; extends145 bars'),
        'benchmark_beta126':('return beta','126 paired own/benchmark log returns'),
        'benchmark_corr126':('correlation','126 paired own/benchmark log returns'),
        'return_autocorr126':('correlation','125 lag-one pairs inside126 log returns'),
        'absolute_return_autocorr126':('correlation','125 lag-one absolute-return pairs inside126 returns'),
        'negative_return_fraction126':('fraction','126 log returns'),
        'left_tail_frequency126':('fraction','126 log returns; threshold minus2 within-window sigma'),
        'drawdown126':('fraction','126 closes including current; distance from within-window high'),
        'gap_share20':('ratio; not bounded by1','20 gaps/returns, requiring21 closes'),
        'turnover_log20':('log quote-currency amount','20 daily quote turnover observations'),
        'turnover_relative20_126':('log ratio','20/126 daily quote turnover observations'),
        'illiquidity_proxy20':('return per million quote currency','20 paired returns/quote turnovers'),
        'intraday_range_atr':('ATR units','current high-low; ATR14'),
        'funding_rate7d':('summed rate fraction','7 completed UTC days; actual settlements'),
        'funding_rate21d':('summed rate fraction','21 completed UTC days; actual settlements'),
        'funding_change7d':('rate fraction difference','last7 versus preceding7 completed UTC days'),
        'taker_imbalance3d':('signed fraction','3 completed UTC days, quote-weighted'),
        'taker_imbalance20d':('signed fraction','20 completed UTC days, quote-weighted'),
        'oi_contract_change1d':('log ratio','daily asof observations exactly1 calendar day apart'),
        'oi_contract_change7d':('log ratio','daily asof observations exactly7 calendar days apart'),
        'oi_price_divergence7d':('log ratio difference','7-calendar-day OI quantity/price changes'),
        'top_position_account_log_ratio':('log reported-ratio quotient','same old asof tail; position/account mapping assumed'),
        'oi_notional_turnover20':('days of turnover','asof reported OI quote value / mean20 daily quote turnover'),
        'lower_boundary_distance_sigma20':('sigma units','strictly prior20 low; known sigma20'),
        'upper_boundary_distance_sigma20':('sigma units','strictly prior20 high; known sigma20'),
    }
    return metadata[name]


SOURCE_FIELDS={
    'price_state':'completed adjusted OHLC (ETF) or native perpetual OHLC (crypto); BTC/SPY benchmark; causal state machine',
    'price_activity':'Kline quote asset volume; ETF raw close * reported volume',
    'crypto_derivatives':'settled fundingRate/fundingTime; Kline quote/taker-buy quote; metrics sum_open_interest/value and reported ratios',
    'price_path':'completed open/high/low/close; trailing state volatility20',
    'peer_context':'completed peer close and EMA50; fixed representative lists, not full-universe breadth',
    'crypto_activity':'12-column Kline fields7/8 (quote turnover/trade count, zero-based); actual fundingTime/fundingRate',
    'macro_context':'13 Yahoo retained snapshots: adjusted OHLC, NY close +60s; see source inventory',
    'global_context':'retained etf_trader_p2 CSV Date/Adj Close for EEM/EFA/DBC/IEF/BIL; existing TLT derived return',
    'metrics_intraday':'create_time, sum_open_interest, sum_toptrader_long_short_ratio, count_long_short_ratio, sum_taker_long_short_vol_ratio',
    'spot_perpetual':'paired native spot/perpetual hourly open/close, quote volume, taker-buy quote volume',
    'calendar':'underlying bar timestamp and known UTC/New York calendar',
}


def field_schema(data):
    schema=[]
    for j,name in enumerate(data["feature_names"]):
        name=str(name)
        if j<45:
            group=source_group(name)
            definition=FEATURE_DESCRIPTIONS[name]
            units,window=old_metadata(name)
        else:
            _,group,definition,units,window=FIELDS[j-45]
        unverified=name in UNVERIFIED or name=="top_position_account_log_ratio"
        quality=name in QUALITY
        status="archive_mapping_unverified" if unverified else "source_quality_metadata" if quality else "research_candidate"
        coverage={}
        for g in ("crypto","etf_proxy"):
            mask=data["group"]==g
            values=data["X"][mask,j]
            finite=values[np.isfinite(values)]
            coverage[g]=dict(available=int(len(finite)),rows=int(mask.sum()),
                fraction=float(len(finite)/mask.sum()),constant=bool(len(finite)>0 and np.ptp(finite)==0),
                minimum=float(np.min(finite)) if len(finite) else None,
                maximum=float(np.max(finite)) if len(finite) else None)
        if name=='top_position_account_log_ratio':
            definition+='; historical position/account interpretation is an unverified archive-to-API mapping'
        schema.append(dict(name=name,column=j,group=group,definition=definition,units=units,window=window,
            source_fields=SOURCE_FIELDS[group],
            availability_rule=RULES[group],missing_rule="NaN+mask; no interpolation; absent source or incomplete window stays absent",
            semantic_status=status,default_model_input=bool(data["default_feature_mask"][j]),
            clip="[-8,8]" if j<19 else None,coverage=coverage,
            fully_missing_assets=[str(a) for a in sorted(set(data["asset"])) if np.all(data["missing"][data["asset"]==a,j])]))
    return schema


def correlations(data,threshold=.995):
    output=[]
    for group in ("crypto","etf_proxy"):
        a=data["X"][data["group"]==group].astype(float)
        for j in range(a.shape[1]):
            for k in range(j):
                mask=np.isfinite(a[:,j])&np.isfinite(a[:,k])
                if mask.sum()<300:continue
                x,y=a[mask,j],a[mask,k]
                if np.std(x)<1e-12 or np.std(y)<1e-12:continue
                r=float(np.corrcoef(x,y)[0,1])
                if abs(r)>=threshold:
                    output.append(dict(group=group,left=str(data["feature_names"][k]),
                        right=str(data["feature_names"][j]),observations=int(mask.sum()),correlation=r))
    return sorted(output,key=lambda r:-abs(r["correlation"]))


def audit(old,data):
    preserved=all(np.array_equal(old[k],data[k]) for k in old if k not in ('X','missing','feature_names'))
    prefix=np.array_equal(old["X"],data["X"][:,:old["X"].shape[1]],equal_nan=True)
    categories=all(CATEGORIES[str(a)]==str(c) for a,c in zip(data["asset"],data["economic_category"]))
    violations=int(np.sum(np.isfinite(data["X"])&(data["feature_available_at"]>data["known_at"][:,None])))
    if not preserved or not prefix or not categories or violations:raise ValueError("dataset_preservation_or_clock_failure")
    return dict(original_inputs_equal=prefix,targets_times_sequences_equal=preserved,
        category_mapping_valid=categories,future_feature_violations=violations,
        assets=sorted(set(map(str,data["asset"]))),economic_categories=dict(Counter(map(str,data["economic_category"]))),
        venue_groups=dict(Counter(map(str,data["group"]))),state_values=sorted(set(map(str,data["state"]))),
        target_counts=[dict(target=str(name),counts={str(k):int(v) for k,v in zip(*np.unique(data["y"][:,j],return_counts=True))})
                       for j,name in enumerate(data["target_names"])],
        number_near_duplicate_pairs=None)


def build_views(data,schema):
    groups=np.array([r["group"] for r in schema])
    use=data["default_feature_mask"]
    common=use&~np.isin(groups,["crypto_derivatives","crypto_activity","metrics_intraday","spot_perpetual"])
    crypto=use&~np.isin(groups,["spot_perpetual"])
    data["common_feature_mask"]=common
    data["crypto_feature_mask"]=crypto
    data["microstructure_feature_mask"]=use.copy()
    data["crypto_view_rows"]=data["group"]=="crypto"
    index={str(n):i for i,n in enumerate(data["feature_names"])}
    data["microstructure_view_rows"]=(data["group"]=="crypto")&np.isfinite(data["X"][:,index["perpetual_spot_premium_close"]])&np.isfinite(data["X"][:,index["oi_quantity_growth_intraday"]])


def report(result):
    lines=["# 市场数据审查与特征工程增补", "",
        f"原{result['old_features']}项输入已逐值保留，新增{result['new_features']}项，现共{result['features']}项、{result['rows']:,}行。标签/成熟时间/序列不变。",
        "先做数据和特征审查，本轮没有重新训练模型，也未证明新增信息具有净预测或盈利增量。", "",
        "## 找到并复用的现成数据", "",
        "|来源|原先缺口|此次处理|", "|---|---|---|",
        "|完整OHLC路径|只有少量形态和波动特征|补实体、收盘位置、区间扩张、快慢波动、偏度、支撑阻力年龄、历史MDD|",
        "|七币种12列日K|成交笔数未使用|补成交笔数、平均成交额变化、真实资金费结算次数/分布|",
        "|13份长期宏观ETF和2026尾段|TLT/UUP/XLI/XLB/XLU未进学习数据|加入美元/长债价格代理、权益广度、周期/防御和商品/权益差异，严格向后匹配|",
        "|5份已有全球ETF日线CSV|EEM/EFA/DBC/IEF/BIL未进学习数据|补新兴/非美权益、广义商品、债券久期相对价格与现金ETF总回报；不是收益率或无风险利率|",
        "|912份5分钟metrics档案|只取日末少量字段|加入日内OI增长/路径波动；原始比率单独标记语义风险|",
        "|三份小时现货/永续缓存|没有进入日线学习输入|24小时完整配对后加入溢价、现货流、现货与合约流分歧和日内路径|",
        "|2026原生ETF合约/39份深度成交档案|当前ETF学习样本停在2025年，且盘口只是片段|不把它们回填到2016–2025代理历史；保留为执行层/后续原生样本来源|", "",
        "## 数据类别与字段说明", "",
        "经济身份、当期状态、数值特征、时间、目标和序列索引分别保留。行为类仍需只在训练窗口拟合，不能把2025年末画像回填早年。",
        "每个字段补齐公式、单位、历史窗口、数据源类别、可用时间规则、缺失处理、覆盖率和默认入模状态，见feature_schema.json。",
        "TLT是长久期国债价格代理，不是收益率/实际利率；UUP是美元ETF代理，不是即时美元指数。",
        "OI是未平仓量水平，成交笔数是交易活动，账户比/持仓比是不同统计对象，均不等同可识别主力净流入。", "",
        "## 新特征覆盖", "",
        "|组|字段数|币种完整数据格占比|ETF代理完整数据格占比|", "|---|---:|---:|---:|"]
    for group in sorted({r['group'] for r in result['fields'][45:]}):
        selected=[r for r in result['fields'][45:] if r['group']==group]
        a=np.mean([r['coverage']['crypto']['fraction'] for r in selected])
        b=np.mean([r['coverage']['etf_proxy']['fraction'] for r in selected])
        lines.append(f"|{group}|{len(selected)}|{a:.2%}|{b:.2%}|")
    lines += ["", "## 默认使用与隔离", "",
        f"默认入模{result['default_features']}项；语义未独立核实的原始比率及来源质量字段保留但默认不入模。", "",
        "- common_feature_mask：价格路径/市场上下文等共同视图。",
        "- crypto_feature_mask / crypto_view_rows：币种成交与衍生品视图。",
        f"- microstructure_feature_mask / microstructure_view_rows：完整小时现货/合约与日内OI共同覆盖的{result['microstructure_rows']}行。",
        "- 报告字段默认掩码不是金融结论；模型选择特征、填补、缩放和降冗余必须在训练窗口重算。", "",
        "## 审查结果", "",
        f"旧输入相同：{result['audit']['original_inputs_equal']}；标签/时间/序列相同：{result['audit']['targets_times_sequences_equal']}；未来特征时间违规：{result['audit']['future_feature_violations']}。",
        f"发现{len(result['redundancy'])}对在至少300个共同观测上绝对相关≥0.995的字段，保留诊断，不按全样本统计自动删列。", "",
        "|市场|字段一|字段二|共同观测|相关|", "|---|---|---|---:|---:|"]
    for r in result['redundancy'][:30]:lines.append(f"|{r['group']}|{r['left']}|{r['right']}|{r['observations']}|{r['correlation']:+.5f}|")
    lines += ["", "## 读取", "", "```python", "import numpy as np",
        "with np.load('dataset.npz', allow_pickle=False) as z:", "    d = {k: z[k] for k in z.files}",
        "rows = d['microstructure_view_rows']  # 共同视图可使用全部行",
        "cols = d['microstructure_feature_mask']  # 或 common_feature_mask / crypto_feature_mask",
        "X = d['X'][rows][:, cols]",
        "missing = d['missing'][rows][:, cols]",
        "# y/maturity只用于目标成熟后的训练；不可放入X。填补/缩放仅在训练窗口拟合。",
        "```", "", "feature_schema.json中的dataset_arrays描述全部数组形状与类型；fields描述每个数值字段。"]
    lines += ["", "## 限制", ""]+["- "+v for v in result['limitations']]
    return "\n".join(lines)+"\n"


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input",type=Path,default=Path("state/research_runs/market_learning_dataset_20261030_reviewed/dataset.npz"))
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():p.error("retain old dataset; choose new output")
    with np.load(args.input,allow_pickle=False) as z:old={k:z[k] for k in z.files}
    if old['X'].shape[1]!=45:p.error("expected frozen45-feature input")
    markets,panel,sources=load_markets()
    states={g:{s:market_state_machine(b) for s,b in book.items()} for g,book in markets.items()}
    raw=json.loads(Path("state/research_cache/independent_crypto_factors_20261027/panel_seven.json").read_text())
    proxies,macro_sources=proxy_records("state/research_cache/binance_macro_etf_history_20261015","state/research_cache/macro_native_tail_20261026")
    global_proxies,global_sources=csv_proxy_records('state/research_cache/etf_trader_p2')
    proxies.update(global_proxies)
    hourly,hourly_sources=hourly_snapshots("state/research_cache/position_flow_20261027")
    metrics,metric_sources,rejected=intraday_metric_snapshots("state/research_cache/position_flow_20261027")
    print('Sources loaded:',len(macro_sources),'macro files;',len(hourly),'paired days;',len(metrics),'valid metric days',flush=True)
    data=enrich(old,markets,states,raw,panel,proxies,hourly,metrics)
    schema=field_schema(data)
    build_views(data,schema)
    checked=audit(old,data)
    redundant=correlations(data)
    checked['number_near_duplicate_pairs']=len(redundant)
    source_paths=sorted(set(macro_sources+global_sources+hourly_sources+metric_sources+[s['path'] for s in sources]))
    source_inventory=[dict(path=str(path),size_bytes=Path(path).stat().st_size,
        sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest()) for path in source_paths]
    result=dict(rows=len(data['X']),old_features=45,new_features=len(NEW_NAMES),features=data['X'].shape[1],
        default_features=int(data['default_feature_mask'].sum()),microstructure_rows=int(data['microstructure_view_rows'].sum()),
        fields=schema,audit=checked,redundancy=redundant,sources=source_inventory,
        dataset_arrays={k:dict(shape=list(v.shape),dtype=str(v.dtype)) for k,v in data.items()},
        source_counts=dict(macro_files=len(macro_sources),global_etf_files=len(global_sources),hourly_files=len(hourly_sources),complete_paired_days=len(hourly),
                           metrics_archives=len(metric_sources),complete_metrics_days=len(metrics),rejected_metric_days=rejected),
        parent_dataset=str(args.input),parent_sha256=hashlib.sha256(args.input.read_bytes()).hexdigest(),
        research_only=True,orders_authorized=False,predictive_increment_verified=False,
        limitations=[
            "新增输入是有明确机制含义的研究候选，不代表已证实预测/盈利增量；本轮不重训模型。",
            "原45项、标签及时间保留；发现旧top_position_account_log_ratio的档案映射仍含假设，默认隔离而不改写旧结果。",
            "reported_*字段只表示原档案数值与变化，未证明其API映射/聚合窗口和可获利交易者身份；默认不入模。",
            "一分钟日线、五分钟metrics发布延迟是研究假设，非完整历史发布时点认证。",
            "宏观特征向后匹配、最多96h并记录年龄；2026各快照分别计算派生量，不拼接价位或回写旧历史，EMA暖启动仍是近似。",
            "全球ETF CSV截至2026-10-01，超过96h保持缺失；BIL是调整价总回报代理而非无风险利率，TLT-IEF是相对价格动量而非收益率曲线。",
            "BTC/ETH/SOL小时及OI只覆盖三个离散时段；其余币和ETF保留缺失，不把缺失补为0或跨日沿用旧值。",
            "当前标的列表有存续选择偏差，ETF/商品仍是复权代理；盘口/逐笔片段和跨平台钱包数据未强行接入。",
            "其他缓存的A股指数超出本次Binance币种/ETF代理范围，OKX小时线为其他交易所；没有混作同一市场的原生数据。",
            "全样本覆盖率/相关性仅作审计，不能用于未来回测的全样本预处理或筛选。",
            "源质量元数据与行情信息分开，默认不让模型以缓存年代/采样时段代替市场因果信息。",
            "实盘、服务、交易权限、旧原始缓存和旧数据集未改；没有新增下载。" ])
    args.output.mkdir(parents=True)
    np.savez_compressed(args.output/'dataset.npz',**data)
    (args.output/'feature_schema.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (args.output/'report.md').write_text(report(result))
    print(json.dumps(dict(output=str(args.output),shape=list(data['X'].shape),default_features=result['default_features'],
                         microstructure_rows=result['microstructure_rows'],near_duplicate_pairs=len(redundant))))


if __name__=='__main__':main()
