"""Market structure first: causal states, break failures and directional labels.

Public retained caches only. Crypto funding is included at actual settlement
marks; ETF OHLC is a signal proxy, never a historical Binance fill assertion.
No credentials, execution client, service or production state is accessed.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import datetime as dt
import hashlib
import json
from pathlib import Path
import statistics

import numpy as np

from qount.research.market_stages import ACTION_STATES, environment_permission, market_state_machine
from qount.research.binance_macro_attack import CONTRACT_SIGNALS
from qount.research.binance_macro_history import adjusted_bars
from qount.research_data.bars import Bar, NY
from study_independent_crypto_factors import SYMBOLS, load_panel


LABELS = dict(compression="低波收敛", range="常态震荡", wide_range="宽幅震荡",
    up_breakout="向上突破观察/确认", down_breakout="向下破位观察/确认",
    up_trend="上升趋势", down_trend="下降趋势", failed_up_breakout="上破失败",
    failed_down_breakout="下破失败", transition="分歧/过渡", shock="冲击/冷却", unknown="数据不足")


def source(path):
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def load_markets():
    path = Path("state/research_cache/independent_crypto_factors_20261027/panel_seven.json")
    panel = load_panel(path)
    raw = json.loads(path.read_text())["data"]
    crypto = {s: [Bar(int(r[6])//1000, *(float(r[k]) for k in (1, 2, 3, 4)), float(r[5]))
                  for r in raw[s+"_klines"]] for s in SYMBOLS}
    root = Path("state/research_cache/binance_macro_etf_history_20261015")
    files = {s: root/f"yahoo-{ticker}-20160101-2026-01-01.json" for s, ticker in CONTRACT_SIGNALS.items()}
    etfs = {s: adjusted_bars(json.loads(p.read_text())) for s, p in files.items()}
    return dict(crypto=crypto, etf_proxy=etfs), panel, [source(path)]+[source(p) for p in files.values()]


def state_statistics(bars, rows, start):
    observed = [rows[b.t] for b in bars if dt.datetime.fromtimestamp(b.t, dt.timezone.utc).strftime("%Y-%m-%d") >= start
                and rows[b.t]["action_state"] != "unknown"]
    states = [r["action_state"] for r in observed]
    counts = Counter(states)
    runs = defaultdict(list)
    transition = Counter()
    last, length = None, 0
    for state in states:
        if state != last:
            if last is not None:
                runs[last].append(length)
                transition[last, state] += 1
            last, length = state, 1
        else:
            length += 1
    if last is not None:
        runs[last].append(length)  # Last run is explicitly censored below.
    last_rows = [r for r in observed[-1:]]
    return dict(observations=len(states), counts=dict(counts),
        spells={s: dict(count=len(v), median_observations=statistics.median(v), maximum_observations=max(v))
                for s, v in runs.items()}, last_spell_censored=True,
        transitions=[dict(before=a, after=b, count=n) for (a, b), n in transition.most_common()],
        latest=last_rows[0] if last_rows else None)


def break_events(bars, rows, start):
    events = {}
    for i, bar in enumerate(bars):
        row = rows[bar.t]
        event = row.get("event")
        if event is None:
            continue
        key = event["started_at"]
        if dt.datetime.fromtimestamp(key, dt.timezone.utc).strftime("%Y-%m-%d") < start:
            continue
        old = events.setdefault(key, dict(side=event["side"], started_at=key,
            boundary=event["boundary"], index=event["index"], confirmed_at=None, failed_at=None))
        if event["status"] == "confirmed" and old["confirmed_at"] is None:
            old["confirmed_at"] = bar.t
        if event["status"] == "failed":
            old["failed_at"] = bar.t
        old["last_observed_at"] = bar.t
    for event in events.values():
        event["censored"] = event["failed_at"] is None and event["index"]+3 >= len(bars)
        event["failed"] = event["failed_at"] is not None
        event["failed_after_confirmation"] = event["failed"] and event["confirmed_at"] is not None
        event["signal_date"] = dt.datetime.fromtimestamp(event["started_at"], dt.timezone.utc).strftime("%Y-%m-%d")
    return list(events.values())


def clustered_mean(events, field):
    clusters = defaultdict(list)
    for e in events:
        date = e["signal_date"]
        clusters[date[:4]+"Q"+str((int(date[5:7])-1)//3+1)].append(e[field])
    if not events:
        return None
    values = [e[field] for e in events]
    result = dict(count=len(values), mean=statistics.mean(values), median=statistics.median(values),
                  positive=sum(v > 0 for v in values), quarter_clusters=len(clusters), interval95=None)
    if len(clusters) >= 4:
        sums = np.array([sum(v) for v in clusters.values()])
        counts = np.array([len(v) for v in clusters.values()])
        draws = np.random.default_rng(301026).integers(0, len(sums), (3000, len(sums)))
        estimates = sums[draws].sum(axis=1)/counts[draws].sum(axis=1)
        result["interval95"] = np.quantile(estimates, [.025, .975]).tolist()
    return result


def opportunity_labels(group, symbol, bars, rows, panel, *, horizon, cost_bp, start):
    """Predefined state routes, no overlapping five/20-session holding per asset.

    These are held-to-horizon opportunity labels, NOT portfolio/backtest fills:
    there are no stops, compounding, discrete lots, margin or liquidity model.
    Daily crypto signal waits one full extra day (open i+2); ETF signal uses
    following session open (i+1). Endpoints are read only to score the outcome.
    """
    delay = 2 if group == "crypto" else 1
    j = SYMBOLS.index(symbol) if group == "crypto" else None
    records, next_allowed, censored = [], 0, 0
    for i, b in enumerate(bars):
        row = rows[b.t]
        date = dt.datetime.fromtimestamp(b.t, dt.timezone.utc).strftime("%Y-%m-%d")
        side = row["route_side"]
        if date < start or i < next_allowed or not side:
            continue
        entry, exit_ = i+delay, i+delay+horizon
        next_allowed = exit_
        if exit_ >= len(bars):
            censored += 1
            continue
        a, z = bars[entry].o, bars[exit_].o
        def open_time(index):
            zone = dt.timezone.utc if group == "crypto" else NY
            day = dt.datetime.fromtimestamp(bars[index].t, zone).date()
            clock = dt.time(0) if group == "crypto" else dt.time(9, 30)
            return int(dt.datetime.combine(day, clock, zone).timestamp())
        entry_time, exit_time = open_time(entry), open_time(exit_)
        assert b.t < entry_time < exit_time
        funding_long = (-float(panel["funding_value"][entry:exit_, j].sum())/a
                        if group == "crypto" else 0.)
        friction = cost_bp/10000 * (1+z/a)
        gross = side*(z/a-1)
        net = gross-friction+side*funding_long
        long_net = z/a-1-friction+funding_long
        records.append(dict(symbol=symbol, signal_date=date, state=row["action_state"], side=side,
            feature_available=b.t, entry_time=entry_time, exit_time=exit_time,
            gross_directional_return=gross, funding_on_notional=side*funding_long,
            assumed_friction=friction, net_label=net, long_at_same_time=long_net,
            excess_to_same_time_long=net-long_net))
    return records, censored


def with_environment(group, symbol, bars, rows_by_asset):
    """Filter local triggers before opportunity selection or outcome access."""
    benchmark = "BTCUSDT" if group == "crypto" else "SPYUSDT"
    independent = group == "etf_proxy" and symbol in ("XAUUSDT", "COPPERUSDT", "CLUSDT")
    peers = list(rows_by_asset) if group == "crypto" else ["SPYUSDT", "QQQUSDT", "SMHUSDT", "IWMUSDT", "XLEUSDT"]
    result, rejections = {}, Counter()
    for bar in bars:
        row = rows_by_asset[symbol][bar.t]
        market = rows_by_asset[benchmark].get(bar.t)
        peer_rows = [rows_by_asset[s].get(bar.t) for s in peers]
        allowed, reason = environment_permission(row, market, [p for p in peer_rows if p is not None],
                                                 systematic=not independent)
        result[bar.t] = dict(row, route_side=row["route_side"] if allowed else 0)
        if row["route_side"] and not allowed:
            rejections[reason] += 1
    return result, dict(rejections)


def event_summary(events):
    output = []
    for side in (1, -1):
        v = [e for e in events if e["side"] == side and not e["censored"]]
        failed = sum(e["failed"] for e in v)
        confirmed = [e for e in v if e["confirmed_at"] is not None]
        output.append(dict(side=side, starts=len(v), failed=failed, failure_rate=failed/len(v) if v else None,
            two_close_confirmed=len(confirmed), failed_after_confirmation=sum(e["failed_after_confirmation"] for e in v),
            censored=sum(e["censored"] for e in events if e["side"] == side)))
    return output


def paired_filter_labels(raw_records, filtered):
    """The SAME preselected local opportunities, split by the causal filter.

    This avoids attributing changed admission calendars to predictive filter
    skill. It remains a conditional outcome comparison, not a strategy PnL.
    """
    accepted, rejected = [], []
    for event in raw_records:
        gate = filtered[event["symbol"]][event["feature_available"]]
        (accepted if gate["route_side"] == event["side"] else rejected).append(event)
    return dict(accepted=clustered_mean(accepted, "net_label"),
                rejected=clustered_mean(rejected, "net_label"))


def fmt(value):
    return "—" if value is None else f"{value:.2%}"


def write_report(result):
    lines = ["# Binance币种与ETF信号市场：状态机研究", "",
        "十种结构/事件路由，冲击和数据不足两个保护覆盖。状态由当时可知信息递推；固定阈值未扫参。",
        "先研究市场分布与信号机会，不将方向标签称作账户收益。所有历史已被研究使用，非独立OOS。", "",
        "## 数据与状态分布", "",
        "|市场|样本|标的数|有效资产观测|", "|---|---|---:|---:|"]
    for group, data in result["markets"].items():
        lines.append(f"|{group}|{data['start']}至{data['last_date']}|{len(data['by_asset'])}|{sum(v['observations'] for v in data['by_asset'].values())}|")
    lines += ["", "|状态|币种占比|ETF代理占比|", "|---|---:|---:|"]
    for state in ACTION_STATES+("shock",):
        values = []
        for group in ("crypto", "etf_proxy"):
            data = result["markets"][group]
            total = sum(v["observations"] for v in data["by_asset"].values())
            values.append(sum(v["counts"].get(state, 0) for v in data["by_asset"].values())/total)
        lines.append(f"|{LABELS[state]}|{values[0]:.2%}|{values[1]:.2%}|")
    lines += ["", "## 20期区间突破后3期内回到原边界内", "",
        "突破需收盘越过过去20期边界至少0.25个先前ATR；边界固定。两次边界外收盘是确认，不保证此后不失败。",
        "|市场|方向|成熟事件|失败数|失败率|两次收盘确认|确认后仍失败|", "|---|---|---:|---:|---:|---:|---:|"]
    for group, data in result["markets"].items():
        for e in data["break_summary"]:
            lines.append(f"|{group}|{'上' if e['side']==1 else '下'}|{e['starts']}|{e['failed']}|{fmt(e['failure_rate'])}|{e['two_close_confirmed']}|{e['failed_after_confirmation']}|")
    lines += ["", "## 固定5期持有的方向机会诊断", "",
        "同标的按事前计划期限去重；跨标的依然相关。币种含真实时点资金费和单边10bp假定摩擦；ETF单边30bp是假定信号摩擦，未包含Binance合约资金费、特殊分红及执行约束。",
        "下表为单笔初始名义金额归一化标签的均值/中位数；不是CAGR、组合净值或有止损的策略业绩。", "",
        "|市场/窗口/路由|状态|机会数|平均净标签|中位数|季度簇95%区间|", "|---|---|---:|---:|---:|---|"]
    for row in result["opportunities"]:
        if row["horizon"] != 5 or row["cost_bp"] != (10 if row["group"] == "crypto" else 30):
            continue
        for state, summary in row["by_state"].items():
            if summary is None:
                continue
            ci = summary["interval95"]
            lines.append(f"|{row['group']}/{row['window']}/{row['routing']}|{LABELS[state]}|{summary['count']}|{fmt(summary['mean'])}|{fmt(summary['median'])}|{fmt(ci[0])+'至'+fmt(ci[1]) if ci else '簇不足'}|")
    lines += ["", "## 同一局部机会集合上的环境过滤", "",
        "固定原局部机会及其时间/方向/名义收益，只按当时环境分为保留和拒绝；不混入重排入场日期的变化。两组并非随机分配。", "",
        "|市场/窗口|保留数|保留平均净标签|拒绝数|拒绝平均净标签|", "|---|---:|---:|---:|---:|"]
    for row in result["paired_environment"]:
        if row["horizon"] != 5 or row["cost_bp"] != (10 if row["group"] == "crypto" else 30):
            continue
        a, b = row["accepted"], row["rejected"]
        lines.append(f"|{row['group']}/{row['window']}|{a['count'] if a else 0}|{fmt(a['mean']) if a else '—'}|{b['count'] if b else 0}|{fmt(b['mean']) if b else '—'}|")
    lines += ["", "## 限制与复现", ""]+["- "+s for s in result["limitations"]]
    lines += ["", "详细逐资产状态、转移、持续时间、突破事件、5/20期及高成本对照见同目录results.json和opportunities.json。",
        "复现：`PYTHONPATH=src ./.venv/bin/python scripts/research/study_binance_market_states.py --output <新目录>`", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("retain previous results; choose a new output")
    markets, panel, sources = load_markets()
    data, opportunities, detailed, paired = {}, [], [], []
    for group, book in markets.items():
        start = "2021-05-01" if group == "crypto" else "2017-01-01"
        by_asset, events, rows_by_asset = {}, [], {}
        for symbol, bars in book.items():
            rows = market_state_machine(bars)
            rows_by_asset[symbol] = rows
            by_asset[symbol] = state_statistics(bars, rows, start)
            events.extend(dict(symbol=symbol, **e) for e in break_events(bars, rows, start))
        effective_start = min(dt.datetime.fromtimestamp(b.t, dt.timezone.utc).strftime("%Y-%m-%d")
            for symbol, bars in book.items() for b in bars
            if dt.datetime.fromtimestamp(b.t, dt.timezone.utc).strftime("%Y-%m-%d") >= start
            and rows_by_asset[symbol][b.t]["action_state"] != "unknown")
        filtered, rejected = {}, {}
        for symbol, bars in book.items():
            filtered[symbol], rejected[symbol] = with_environment(group, symbol, bars, rows_by_asset)
        data[group] = dict(start=effective_start, requested_start=start, environment_rejections=rejected,
            last_date=dt.datetime.fromtimestamp(next(iter(book.values()))[-1].t, dt.timezone.utc).strftime("%Y-%m-%d"),
            by_asset=by_asset, break_events=events, break_summary=event_summary(events))
        costs = (10, 30) if group == "crypto" else (30, 60)
        windows = (("all", start, "9999"), ("2021_2024", start, "2025-01-01"),
            ("2025", "2025-01-01", "2026-01-01"), ("2026", "2026-01-01", "9999")) if group == "crypto" else (
            ("all", start, "9999"), ("2017_2021", start, "2022-01-01"),
            ("2022", "2022-01-01", "2023-01-01"), ("2023_2025", "2023-01-01", "9999"))
        for horizon, cost, routing in ((h, c, r) for h in (5, 20) for c in costs
                                       for r in ("local_only", "environment_confirmed")):
            records, censored = [], 0
            for symbol, bars in book.items():
                rows = rows_by_asset[symbol] if routing == "local_only" else filtered[symbol]
                r, n = opportunity_labels(group, symbol, bars, rows, panel,
                                         horizon=horizon, cost_bp=cost, start=start)
                records += r
                censored += n
            detailed.append(dict(group=group, horizon=horizon, cost_bp=cost, routing=routing, records=records, censored=censored))
            for window, left, right in windows:
                # Require outcomes to mature within the window; never let
                # 2024 signals import 2025 prices into a 2024 label summary.
                chosen = [e for e in records if left <= e["signal_date"] < right and
                    dt.datetime.fromtimestamp(e["exit_time"], dt.timezone.utc).strftime("%Y-%m-%d") < right]
                opportunities.append(dict(group=group, window=window, horizon=horizon, cost_bp=cost, routing=routing,
                    by_state={s: clustered_mean([e for e in chosen if e["state"] == s], "net_label")
                              for s in ACTION_STATES},
                    by_side={str(side): clustered_mean([e for e in chosen if e["side"] == side], "net_label")
                             for side in (-1, 1)},
                    all_opportunities=clustered_mean(chosen, "net_label")))
                if routing == "local_only":
                    paired.append(dict(group=group, window=window, horizon=horizon, cost_bp=cost,
                        **paired_filter_labels(chosen, filtered)))
        print(group, data[group]["last_date"], "states and labels complete", flush=True)
    result = dict(research_only=True, orders_authorized=False, independent_oos=False,
        hypothesis="Causal market structure and breakout-failure events can route distinct trend/range/reversal hypotheses; their conditional outcomes must be checked before portfolio optimization.",
        state_count=10, protective_overrides=["shock", "unknown"], markets=data,
        assumptions=dict(break_lookback=20, break_buffer_previous_atr=.25, confirmation_closes=2,
            failure_window=3, same_direction_break_spacing=5, trend_efficiency=.28,
            volatility_reference="median of up to 252 prior vol20", shock_previous_sigma=3,
            signal_delay_crypto=2, signal_delay_etf_sessions=1, horizons=[5,20],
            costs_crypto_one_way_bp=[10,30], costs_etf_proxy_one_way_bp=[30,60],
            funding_mark_approximations=panel["approximate_marks"]),
        opportunities=opportunities, paired_environment=paired, sources=sources,
        limitations=[
            "十种路由是本次固定研究分类，没有统计定理证明市场天然只有十种；趋势回踩/反弹是趋势内部触发。",
            "固定七币种及八代理存在当前名单/存续选择偏差，不代表所有Binance合约，也不包含已退市失败币。",
            "币种2021年至2026-10-26、ETF2017至2025均已被消费，不把时间分组称作独立OOS。",
            "ETF复权OHLC、GLD/CPER/USO等代理只描述信号市场；不等同Binance原生合约历史、上市时点、资金费或实际收益。",
            "币种2023-10及以前部分资金费结算mark缺失，沿用同日交易开盘近似；完整计数保留。",
            "5/20期方向标签没有仓位、止损、滑点路径、保证金、整手或容量约束；不得解读为账户策略回测。",
            "同标的标签事前去重，跨资产仍有关联；季度簇区间不校正多策略比较和历史选样。",
            "假突破识别发生在回到边界内的收盘；确认过的突破仍可能失败，日线状态有反应延迟。",
            "观察到的价格冲击不能证明流动性危机；盘口价差/深度/OI/基差等验证留待原生合约研究。",
            "本轮未改变实盘、服务、权限或研究注册表；无API调用或新数据下载。" ])
    args.output.mkdir(parents=True)
    for name, payload in (("results.json", result), ("opportunities.json", detailed)):
        (args.output/name).write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)+"\n")
    (args.output/"report.md").write_text(write_report(result))
    print(json.dumps(dict(output=str(args.output), groups=list(data), opportunities=len(opportunities))))


if __name__ == "__main__":
    main()
