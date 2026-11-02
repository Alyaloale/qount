"""Build a compact daily dataset and past-fitted behavior profiles from caches."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import numpy as np

from qount.research.market_learning import behavior_summary
from qount.research.market_learning_data import ALL_FEATURES, FEATURE_DESCRIPTIONS, STYLE_NAMES, TARGET_NAMES, build_dataset, metric_snapshots
from qount.research.market_stages import market_state_machine
from study_binance_market_states import load_markets


def stamp(text):return int(dt.datetime.fromisoformat(text).replace(tzinfo=dt.timezone.utc).timestamp())
def date(t):return dt.datetime.fromtimestamp(int(t),dt.timezone.utc).strftime("%Y-%m-%d %H:%M")


def readme(info,profiles):
    lines=["# Binance币种与ETF市场学习数据集", "",
        f"{info['rows']:,}行日线观测，{info['features']}个原始特征，15个标的，4个分别定义的未来目标；另有显式缺失掩码、经济类别、原描述状态及序列索引。",
        "research_only=true / orders_authorized=false。币种来自原生USDT合约公开缓存；ETF/商品来自信号代理，不是完整Binance合约执行数据。", "",
        "## 文件与时间", "",
        "- dataset.npz：NumPy压缩数组，`np.load(path, allow_pickle=False)`即可读取；没有对象反序列化。",
        "- feature_schema.json：特征名、来源、覆盖率、目标定义和时间假设。",
        "- behavior_profiles.json：只用历史拟合的四类行为质心、稳定性和逐标的画像。",
        "- known_at为完成日线后的固定60秒发布缓冲；币种秒精度尾时间先向上补齐到完整UTC日，再加60秒。ETF按原保守16:00纽约收盘加60秒。",
        "- maturity[:,j]为目标j可用时间；y=-1、maturity=0表示未成熟或不适用，不能放入训练。最新尾部保留特征，不编造未来标签。",
        "- previous_row/next_row仅连接同标的相邻真实观测；不填造ETF周末K线。序列窗口必须沿这些索引构造，不能跨标的拼接。", "",
        "## 特征组", "",
        "|组|内容|限制|", "|---|---|---|",
        "|价格结构/阶段|原19项强度、趋势、状态年龄、区间、突破和相对市场特征|当时已完成的行情；状态标签不是自然真值|",
        "|行为风格|126期波动、效率、beta/相关、自相关、下跌比例、尾部、距高点回撤|滚动风格，不能当永久类别|",
        "|活跃度/流动性代理|成交金额、相对活跃度、收益/成交额、日内振幅与隔夜缺口|ETF成交额为原始收盘价×成交量近似，不是盘口/可成交量证明|",
        "|合约与成交行为|7/21天资金费、主动买卖量差、OI变化及持仓比率|资金费/主动量仅币种；OI只在BTC/ETH/SOL已有档案可用处出现|", "",
        "## 目标", "",
        "|目标|定义|用途|", "|---|---|---|",
        "|direction5 / direction20|未来收盘位移超过±0.5×已知sigma20×√h分上/下，否则中性|预测后续结果，不是复述当前状态|",
        "|range5|当前处于区间时，后5期每根收盘是否留在固定先前20期边界内|区间维持/失效分类|",
        "|break_survival3|当前突破观察/确认事件，后3期是否均保持在原边界外|突破维持；相邻事件标签重叠|", "",
        "所有目标不含交易仓位、成本或成交，不等于净收益。训练要按目标各自成熟时间过滤，缩放/填补/聚类只在训练窗口拟合。", "",
        "## 经济类别与数据覆盖", "",
        "|标的|类别|行数|首个可用特征|最后可用特征|", "|---|---|---:|---|---|"]
    for r in info["assets"]:
        lines.append(f"|{r['asset']}|{r['category']}|{r['rows']}|{date(r['first'])}|{date(r['last'])}|")
    lines += ["", "## 数据识别的四种行为类", "",
        "固定K=4，仅作行为压缩假设。拟合截止2025-10-01，画像为2025年末收盘（含下一分钟缓冲）；类别按质心波动率排序，编号不是永久经济含义。币种基准为BTC，ETF/商品代理基准为SPY，相关/beta不代表相对同一指数。",
        f"历史风格样本轮廓系数{profiles['silhouette']:.3f}；另两个固定种子的调整Rand系数为{profiles['seed_adjusted_rand']}。这些不是预测正确率。",
        "资产均衡加权，超出训练类99%距离范围允许标为-1，不强行归类。", "",
        "|行为类|年化波动质心|趋势效率|市场beta|市场相关|距126期高点回撤|该时点成员|",
        "|---|---:|---:|---:|---:|---:|---|"]
    for r in profiles["groups"]:
        c=r["centroid"]
        lines.append(f"|B{r['cluster']}|{c['volatility126_annual']:.1%}|{c['efficiency20_median126']:.3f}|{c['benchmark_beta126']:.2f}|{c['benchmark_corr126']:.2f}|{c['drawdown126']:.1%}|{','.join(r['members']) or '无'}|")
    lines += ["", "|标的|行为类|126期年化波动|市场相关|市场beta|趋势效率|距126期高点回撤|",
        "|---|---|---:|---:|---:|---:|---:|"]
    for r in profiles["by_asset"]:
        c=r["style"]
        lines.append(f"|{r['asset']}|{'B'+str(r['cluster']) if r['cluster']>=0 else '范围外'}|{c['volatility126_annual']:.1%}|{c['benchmark_corr126']:.2f}|{c['benchmark_beta126']:.2f}|{c['efficiency20_median126']:.3f}|{c['drawdown126']:.1%}|")
    lines += ["", "## 必须保留的限制", ""]+["- "+s for s in info["limitations"]]
    return "\n".join(lines)+"\n"


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error("retain prior dataset; choose new output")
    markets,panel,sources=load_markets()
    states={g:{s:market_state_machine(bars) for s,bars in book.items()} for g,book in markets.items()}
    metrics,metric_sources=metric_snapshots("state/research_cache/position_flow_20261027")
    print("Cached metric snapshots",len(metrics),"archives",len(metric_sources),flush=True)
    data=build_dataset(markets,states,panel,metrics,etf_cache="state/research_cache/binance_macro_etf_history_20261015")
    profiles=behavior_summary(data,stamp("2025-10-01"),asof=stamp("2026-01-01T00:02:00"))
    assets=[]
    for asset in sorted(set(data["asset"])):
        mask=data["asset"]==asset
        assets.append(dict(asset=str(asset),category=str(data["economic_category"][mask][0]),rows=int(mask.sum()),
            first=int(data["known_at"][mask].min()),last=int(data["known_at"][mask].max())))
    fields=[]
    for j,name in enumerate(ALL_FEATURES):
        fields.append(dict(name=name,column=j,definition=FEATURE_DESCRIPTIONS[name],
            clip="[-8,8]" if j<19 else None,style_feature=name in STYLE_NAMES,
            available_fraction={g:float(np.mean(~data["missing"][data["group"]==g,j])) for g in ("crypto","etf_proxy")},
            missing_assets=[str(a) for a in sorted(set(data["asset"])) if np.all(data["missing"][data["asset"]==a,j])]))
    info=dict(rows=len(data["X"]),features=len(ALL_FEATURES),targets=list(TARGET_NAMES),fields=fields,assets=assets,
        sources=sources,metrics_archive_paths=metric_sources,valid_metric_days=len(metrics),
        target_available=[int(np.sum(data["y"][:,j]>=0)) for j in range(4)],
        publication_buffer_seconds=60,metrics_publication_lag_assumption_seconds=300,metrics_max_age_seconds=1200,
        format="npz arrays without pickle; NaN+explicit missing mask; censored labels -1 with maturity 0",
        research_only=True,orders_authorized=False,independent_oos=False,
        limitations=[
            "固定15个当前存续标的，不覆盖全币安、退市币或完整时点资格；历史已消费。",
            "ETF/商品复权代理不是Binance原生合约历史；成交额为近似，资金费/OI留缺失，不从币种回填。",
            "一分钟行情缓冲和五分钟metrics发布延迟是保守研究假设，不证明档案在历史时点实际可下载。",
            "缺失掩码区分没有来源和真实0；不得把填补后的0称作真实资金费、OI或流量。",
            "行为类由过去126期特征计算，每期可以变化；四类是固定压缩假设，聚类稳定不等于预测有效。",
            "神经网络若学习当前规则标签，只能证明会复述规则；必须另用未来结果和时间顺序检验。",
            "数据集没有盘口、逐笔成交、清算可靠性、完整交易成本/账户状态；尚不是可用RL交易环境。",
            "未新增下载/服务/定时器/订单，原数据与生产状态保留；小型衍生数据保存于Mac。" ])
    args.output.mkdir(parents=True)
    np.savez_compressed(args.output/"dataset.npz",**data)
    (args.output/"feature_schema.json").write_text(json.dumps(info,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
    (args.output/"behavior_profiles.json").write_text(json.dumps(profiles,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
    (args.output/"README.md").write_text(readme(info,profiles))
    print(json.dumps(dict(output=str(args.output),rows=len(data["X"]),features=len(ALL_FEATURES),
                         size_bytes=(args.output/"dataset.npz").stat().st_size)))


if __name__=="__main__":main()
