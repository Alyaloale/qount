"""Find economic signal value with fixed mechanism ablations on retained ETFs."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np

from qount.research.binance_macro_attack import CONTRACT_SIGNALS, macro_features
from qount.research.binance_macro_history import adjusted_bars, forward_label
from qount.research.macro_mechanism_value import PROFILES, daily_replay, mechanism_rows
from qount.research.engine.evaluation import nav_metrics


CACHE = Path("state/research_cache/binance_macro_etf_history_20261015")
PRIOR = Path("state/research_runs/binance_macro_history_20261015_final/summary.json")


def cluster_interval(events, field, seed=20261026):
    groups = defaultdict(list)
    for e in events:
        if e.get(field) is not None:
            groups[e["signal_date"][:4]+"Q"+str((int(e["signal_date"][5:7])-1)//3+1)].append(e[field])
    if len(groups) < 2:
        return None
    sums = np.array([sum(v) for v in groups.values()])
    counts = np.array([len(v) for v in groups.values()])
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(sums), size=(10000, len(sums)))
    means = sums[draws].sum(axis=1)/counts[draws].sum(axis=1)
    return dict(mean=float(sums.sum()/counts.sum()), clusters=len(groups),
                interval95=np.quantile(means, [.025, .975]).tolist())


def direction_study(book, rows, prior):
    controls = defaultdict(list)
    for s, bars in book.items():
        for i in range(200, len(bars)):
            f = rows[s][bars[i].t]
            label = forward_label(bars, i, 15)
            if f["hold_structural"] and not label["censored"]:
                controls[s, f["date"][:4], "structural"].append(label["base"])
                if f["simple_dip"]:
                    controls[s, f["date"][:4], "dip"].append(label["base"])
    events = []
    for e in prior["events"]:
        if not e["nonoverlap"] or e["outcomes"]["15"]["censored"]:
            continue
        s, i, year = e["symbol"], e["signal_index"], e["year"]
        own, market = book[s], book["SPYUSDT"]
        assert own[i].t == market[i].t == e["signal_available"]
        label = forward_label(own, i, 15)
        assert label == e["outcomes"]["15"]
        x = np.diff(np.log([b.c for b in market[i-126:i+1]]))
        y = np.diff(np.log([b.c for b in own[i-126:i+1]]))
        beta = float(np.cov(x, y, ddof=1)[0, 1]/np.var(x, ddof=1))
        spy = forward_label(market, i, 15)
        event = dict(symbol=s, setup=e["setup"], signal_date=e["signal_date"],
            net=label["base"], spy_gross=spy["gross_return"], beta126=beta,
            beta_adjusted=label["base"]-beta*spy["gross_return"])
        for name in ("structural", "dip"):
            values = controls[s, year, name]
            event[name+"_reference"] = statistics.mean(values) if values else None
            event["excess_"+name] = label["base"]-statistics.mean(values) if values else None
        events.append(event)
    summaries = []
    for name, choose in (("mean_reversion", lambda e: e["setup"] == "mean_reversion"),
                         ("trend", lambda e: e["setup"] != "mean_reversion")):
        selected = [e for e in events if choose(e)]
        summaries.append(dict(cohort=name, count=len(selected),
            statistics={field: cluster_interval(selected, field) for field in
                        ("net", "beta_adjusted", "excess_structural", "excess_dip")},
            by_year={year: dict(count=len(v := [e for e in selected if e["signal_date"].startswith(year)]),
                mean=statistics.mean(e["net"] for e in v),
                beta_adjusted=statistics.mean(e["beta_adjusted"] for e in v))
                for year in sorted({e["signal_date"][:4] for e in selected})},
            by_asset={s: dict(count=len(v := [e for e in selected if e["symbol"] == s]),
                mean=statistics.mean(e["net"] for e in v),
                beta_adjusted=statistics.mean(e["beta_adjusted"] for e in v))
                for s in sorted({e["symbol"] for e in selected})}))
    return dict(events=events, summaries=summaries,
        control_note="Same-ETF/year eligible-day reference is retrospective descriptive matching, not a causal or tradable counterfactual. Control labels overlap. Calendar-quarter bootstrap keeps concurrent assets together; selection/multiple-test bias remains.")


def paired_blocks(a, b):
    assert [p["t"] for p in a["curve"]] == [p["t"] for p in b["curve"]]
    da = np.diff(np.log([p["nav"] for p in a["curve"]]))
    db = np.diff(np.log([p["nav"] for p in b["curve"]]))
    values = da-db
    rng = np.random.default_rng(20261026)
    n, block = len(values), 63
    draws = []
    for _ in range(3000):
        starts = rng.integers(0, n, size=(n+block-1)//block)
        sample = values[(starts[:, None]+np.arange(block)) % n].ravel()[:n]
        draws.append(float(sample.mean()*252))
    return dict(annual_log_excess=float(values.mean()*252),
        interval95=np.quantile(draws, [.025, .975]).tolist(), block_sessions=block)


def frozen_entry_exits(book, rows, primary):
    """Single-opportunity shadows isolate exits; sums are not a portfolio return."""
    results = []
    for trade in primary["trades"]:
        start = dt.datetime.fromtimestamp(trade["entry_time"]).date()
        end = start+dt.timedelta(days=50)
        if trade["exit_reason"] == "end_of_sample":
            continue
        pair = {}
        for holding in ("original", "fixed15"):
            r = daily_replay(book, rows, "original_mr", start=start.isoformat(), end=end.isoformat(),
                holding=holding, entry_times={trade["entry_time"]}, capital=trade["equity_at_entry"])
            assert len(r["trades"]) == 1
            t = r["trades"][0]
            assert (t["symbol"], t["entry_time"], t["entry_price"]) == (trade["symbol"], trade["entry_time"], trade["entry_price"])
            pair[holding] = t
        if pair["fixed15"]["exit_reason"] == "end_of_sample":
            continue
        a, b = pair["original"], pair["fixed15"]
        assert a["quantity"] == b["quantity"]
        assert abs(a["quantity"]-trade["quantity"]) < 1e-8
        assert (a["exit_time"], a["exit_price"]) == (trade["exit_time"], trade["exit_price"])
        notional = a["quantity"]*a["entry_price"]
        results.append(dict(signal_date=start.isoformat(), symbol=trade["symbol"],
            original=a, fixed15=b, net_original=a["net_pnl"]/notional,
            net_fixed15=b["net_pnl"]/notional,
            delta=(b["net_pnl"]-a["net_pnl"])/notional))
    return dict(events=results, statistics=cluster_interval(results, "delta"),
        by_original_exit={reason: dict(count=len(v := [r for r in results if r["original"]["exit_reason"] == reason]),
            mean_delta=statistics.mean(r["delta"] for r in v))
            for reason in sorted({r["original"]["exit_reason"] for r in results})},
        replays=2*sum(t["exit_reason"] != "end_of_sample" for t in primary["trades"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("retain previous results; choose a new output")
    features, sources = macro_features(CACHE, "2026-01-01", start_date="2016-01-01")
    book = {s: adjusted_bars(json.loads((CACHE/f"yahoo-{t}-20160101-2026-01-01.json").read_text()))
            for s, t in CONTRACT_SIGNALS.items()}
    rows = {s: mechanism_rows(book[s], features[s]) for s in book}
    prior = json.loads(PRIOR.read_text())
    direction = direction_study(book, rows, prior)
    portfolios = []
    for target in (None, .15):
        for profile in PROFILES:
            r = daily_replay(book, rows, profile, vol_target=target)
            portfolios.append(r)
            print(target, profile, r["summary"]["cagr_pct"], r["summary"]["max_drawdown_pct"],
                  r["summary"]["trades"], flush=True)
    followups = []
    # Added after the first run: diagnose where the promising event labels vanish.
    for target in (None, .15):
        for name, profile, stops, holding, execution in (
            ("mr_without_stops", "original_mr", False, "original", None),
            ("mr_fixed15_with_stops", "original_mr", True, "fixed15", None),
            ("mr_fixed15", "original_mr", False, "fixed15", None),
            ("mr_fixed15_spy", "original_mr", False, "fixed15", "SPYUSDT"),
            ("simple_dip_fixed15", "simple_dip21", False, "fixed15", None)):
            r = daily_replay(book, rows, profile, vol_target=target, stops=stops,
                             holding=holding, execution_symbol=execution)
            r["profile"] = name
            followups.append(r)
            print("followup", target, name, r["summary"]["cagr_pct"],
                  r["summary"]["max_drawdown_pct"], r["summary"]["trades"], flush=True)
    spy = book["SPYUSDT"]
    first = next(i for i, b in enumerate(spy) if dt.datetime.fromtimestamp(b.t).year >= 2017)
    quantity = 10000/(spy[first].o*1.0025*1.0005)
    spy_curve = [dict(t=spy[first].t-6*3600-1800, nav=1.)]+[
        dict(t=b.t, nav=quantity*b.c/10000) for b in spy[first:]]
    spy_curve[-1]["nav"] *= .9975*.9995
    benchmark = dict(profile="SPY_buy_hold", summary=nav_metrics(spy_curve, sampling="daily_close"), curve=spy_curve)
    exit_shadows = frozen_entry_exits(book, rows, next(r for r in portfolios
        if r["profile"] == "original_mr" and r["vol_target"] is None))
    static_controls = []
    raw_returns = np.array([spy[first].c/spy[first].o-1]+[
        b.c/a.c-1 for a, b in zip(spy[first:], spy[first+1:])])
    for target in (None, .15):
        routed = next(r for r in followups if r["profile"] == "mr_fixed15_spy" and r["vol_target"] == target)
        original = next(r for r in followups if r["profile"] == "mr_fixed15" and r["vol_target"] == target)
        assert [(t["entry_time"],t["exit_time"]) for t in routed["trades"]] == [(t["entry_time"],t["exit_time"]) for t in original["trades"]]
        weight = routed["summary"]["average_open_exposure"]
        values = np.cumprod(1+weight*raw_returns)*(1-weight*.003)
        values[-1] *= 1-weight*.003
        curve = [dict(t=routed["curve"][0]["t"], nav=1.)]+[
            dict(t=b.t, nav=float(v)) for b, v in zip(spy[first:], values)]
        control = dict(profile="posthoc_static_spy", vol_target=target, weight=weight,
            curve=curve, summary=nav_metrics(curve, sampling="daily_close"),
            dynamic_excess=paired_blocks(routed, dict(curve=curve)))
        static_controls.append(control)
    pairs = []
    for target in (None, .15):
        lookup = {r["profile"]: r for r in portfolios if r["vol_target"] == target}
        for a, b in (("original_mr", "structural21"), ("original_mr", "simple_dip21"),
                     ("original_mr", "mr_no_state"), ("original_mr", "mr_own_regime"),
                     ("original_trend", "structural7"), ("original_trend", "trend_no_state"),
                     ("original_all", "structural21"), ("original_all", "original_momentum_rank")):
            pairs.append(dict(candidate=a, reference=b, vol_target=target,
                **paired_blocks(lookup[a], lookup[b])))
        lookup.update({r["profile"]: r for r in followups if r["vol_target"] == target})
        for a, b in (("mr_without_stops", "original_mr"), ("mr_fixed15", "mr_fixed15_with_stops"),
                     ("mr_fixed15", "mr_without_stops"), ("mr_fixed15", "mr_fixed15_spy"),
                     ("mr_fixed15", "simple_dip_fixed15")):
            pairs.append(dict(candidate=a, reference=b, vol_target=target,
                **paired_blocks(lookup[a], lookup[b])))
    for source in sources:
        assert hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest() == source["sha256"]
    out = dict(research_only=True, orders_authorized=False, independent_oos=False,
        start="2017-01-01", end_exclusive="2026-01-01", warmup="2016-01-01", capital=10000,
        fee_each_side=.0005, slip_each_side=.0025, cash_return=0,
        direction=direction, portfolios=portfolios, followups=followups, benchmark=benchmark,
        paired_blocks=pairs, frozen_entry_exits=exit_shadows, static_spy_controls=static_controls, sources=sources,
        limitations=["ETF signal mechanism study, not historical Binance perpetual results. Next-session 09:30 open, not live 10:00; no native 1ATR gap/no-chase, funding, filters, order minimum, liquidation or capacity simulation.",
            "Contemporary adjusted OHLC units, fractional holdings, pretax; dividends embedded in adjustment, not a dated cash ledger. Current asset universe selected ex post; whole history consumed by prior research.",
            "First ten profiles use one unlevered position, previous completed signal, 2ATR stop and close-based trailing effective NEXT session, no same-day reentry, 7/21 calendar-day horizons. Followups separately remove stops or use fixed15 sessions. Current-stop intraday fill ordering is pessimistic; open exposures/vol targets are not matched realized risk.",
            "Vol15 is entry-time exposure cap min(1,15%/past20d volatility), not continuous volatility targeting. End-of-sample liquidation modeled and explicitly marked.",
            "First ten mechanism comparisons were fixed before the initial run. Five followups were selected after seeing event-to-account loss, not independent preregistration. Bootstrap intervals are dependence diagnostics, not selection-adjusted proof of alpha."])
    args.output.mkdir(parents=True)
    (args.output/"comparison.json").write_text(json.dumps(out, ensure_ascii=False, allow_nan=False)+"\n")
    lines = ["# 现行宏观策略的机制价值", "",
        "问题：长期趋势、均值回归、复杂状态分类与跨资产排序，哪些真正提供收益信息？本轮固定机制对照，不搜索成本、窗口或阈值。",
        "2017–2025，2016预热，复用13个代理缓存、8个当前交易资产的ETF代理；10000美元等值、单仓、不杠杆、现金0%。",
        "下一交易日开盘执行、单边手续费5bp/滑点25bp、2ATR止损与因果移动止损、原7/21自然日期限。仅检验ETF层面的机制，不冒充实盘合约结果。", "",
        "## 同资产非重叠方向事件", "",
        "复用旧研究预先按时间去重的93个MR/236个趋势成熟机会，15交易日持有。beta只用信号前126日；区间按日历季度整组重抽，同期跨资产共同保留。",
        "|类型|事件数|净方向均值|95%区间|去SPY beta后均值|95%区间|相对同年同ETF简单买跌均值|95%区间|",
        "|---|---:|---:|---|---:|---|---:|---|"]
    interval = lambda s: f"[{s['interval95'][0]:.2%}, {s['interval95'][1]:.2%}]"
    for r in direction["summaries"]:
        a, b, c = (r["statistics"][f] for f in ("net", "beta_adjusted", "excess_dip"))
        lines.append(f"|{r['cohort']}|{r['count']}|{a['mean']:.2%}|{interval(a)}|{b['mean']:.2%}|{interval(b)}|{c['mean']:.2%}|{interval(c)}|")
    lines += ["", "同年同ETF参考是事后描述性匹配，参考窗口重叠；不是可交易、风险匹配或因果alpha。beta调整也不涵盖全部风险溢价。", "",
        "## 单账户可形成的收益与回撤", "",
        "structural21/7：仅保留原长期/系统趋势门，按63日动量排序；original_mr/trend：拆开两个入口；mr_no_state：去CHOP要求；mr_own_regime：保留自身趋势但移除SPY系统门；simple_dip21：结构趋势内近5日下跌且当天收阳；trend_no_state：移除成交量状态分类；original_momentum_rank：原全入口改为63日动量排序。",
        "除original_all采用原战术分数排序，其余均用63日动量排序。故original_mr/trend并非完整实盘的独立子账户；用于控制排序后比较入口。", "",
        "|仓位规则|机制|CAGR|日MDD|Calmar|交易数|平均开盘暴露|2020|2022|2025|",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in portfolios:
        h = r["summary"]
        lines.append(f"|{'不杠杆全额' if r['vol_target'] is None else '15%波动率入场上限'}|{r['profile']}|{h['cagr_pct']:.2f}%|{h['max_drawdown_pct']:.2f}%|{h['calmar']:.2f}|{h['trades']}|{h['average_open_exposure']:.2%}|{h['years']['2020']:.2%}|{h['years']['2022']:.2%}|{h['years']['2025']:.2%}|")
    lines += ["", "## 顺序追加：方向信息在哪里流失", "",
        "观察事件方向均值为正、原退出账户弱后追加五个机制，不搜索退出天数：去止损仍保留结构退出；固定持有15交易日有/无止损；相同MR入场择时固定买SPY；简单买跌固定15日。后续结果已消费，不当预先未见证据。",
        "固定15日从入场开盘至第15个持有日收盘，不做结构提前退出。SPY版由原资产信号选出入场，实际仅持SPY；风控暴露以实际载体过去波动率定仓。", "",
        "|仓位规则|机制|CAGR|日MDD|Calmar|交易数|平均开盘暴露|2020|2022|2025|",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in followups:
        h = r["summary"]
        lines.append(f"|{r['vol_target']}|{r['profile']}|{h['cagr_pct']:.2f}%|{h['max_drawdown_pct']:.2f}%|{h['calmar']:.2f}|{h['trades']}|{h['average_open_exposure']:.2%}|{h['years']['2020']:.2%}|{h['years']['2022']:.2%}|{h['years']['2025']:.2%}|")
    h = benchmark["summary"]
    lines += ["", f"同窗SPY买持（相同首尾成本）：CAGR {h['cagr_pct']:.2f}%、日MDD {h['max_drawdown_pct']:.2f}%；常驻市场、并非同暴露风险匹配对照。"]
    lines += ["", "## 固定同一入场：退出机制的独立影子对照", "",
        "对原MR单账户每个已闭合入场，独立重建相同载体、价格、数量，再分别运行原退出或固定15日仍保留相同止损。无新入场、无数量路径变化；扩展影子彼此可能重叠，均值不是可实现账户收益。",
        f"成熟事件{len(exit_shadows['events'])}个；固定15日减原退出的单位名义净收益均值{exit_shadows['statistics']['mean']:.2%}，季度块95%区间{interval(exit_shadows['statistics'])}。",
        json.dumps(exit_shadows["by_original_exit"], ensure_ascii=False), "",
        "## 同平均暴露的静态SPY诊断", "",
        "把MR→SPY账户事后平均暴露固定成SPY/现金权重，按日恒权重但忽略再平衡成本，仅计近似首尾摩擦。该基准有意偏有利，权重事后已知，不是可直接部署的策略或严格风险匹配。"]
    for r in static_controls:
        h, e = r["summary"], r["dynamic_excess"]
        lines.append(f"- 入场波控{r['vol_target']}：静态SPY权重{r['weight']:.2%}，CAGR/MDD {h['cagr_pct']:.2f}%/{h['max_drawdown_pct']:.2f}%；MR择时相对它的年化对数差{e['annual_log_excess']:.2%}，63日块95%区间{interval(e)}。")
    lines += ["", "## 配对收益差", "",
        "同一天的账户对数收益差，按63交易日循环块重抽3000次；年化对数收益差不是CAGR差。暴露与实际风险并未强制相等。", "",
        "|仓位规则|候选|参照|年化对数差|95%区间|", "|---|---|---|---:|---|"]
    for r in pairs:
        lines.append(f"|{r['vol_target']}|{r['candidate']}|{r['reference']}|{r['annual_log_excess']:.2%}|{interval(r)}|")
    lines += ["", "## 口径与限制", ""]+["- "+s for s in out["limitations"]]
    lines += ["", "全部年度、资产归因、交易和曲线见comparison.json；未改生产参数、配置或权限。", "",
        "复现：`PYTHONPATH=src ./.venv/bin/python scripts/research/study_macro_mechanism_value.py --output <新目录>`", ""]
    (args.output/"report.md").write_text("\n".join(lines))
    print(json.dumps(direction["summaries"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
