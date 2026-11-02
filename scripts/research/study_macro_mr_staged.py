"""Staged MR allocation vs an information-free first-review budget refill."""
import argparse
import datetime as dt
import hashlib
import json
import math
import statistics
from pathlib import Path

from qount.research.binance_etf_leverage import replay
from qount.research.binance_macro_liquidity import load_capacity_contexts
from qount.research.binance_macro_opportunities import cost_case
from qount.research.macro_depth_execution import DepthExitStress
from qount.research.macro_topup import MRTopupPolicy, verify_topup_replay
from qount.research.macro_mechanism_value import daily_replay
from qount.research_data.bars import NY
from continue_macro_fixed_candidates import CASES, append_inputs
from study_macro_admission_and_simplicity import headline
from study_macro_mechanism_value import cluster_interval
from study_macro_mr_failure import long_inputs


PROFILES = (("control", 1., None), ("mr_topup", 1., "new_mr"),
            ("review_topup", 1., "first_review"), ("half_control", .5, None),
            ("half_mr_topup", .5, "new_mr"), ("half_review_topup", .5, "first_review"))


def review_direction_study():
    """Long-history conditional remaining returns; not a tradable add-on book."""
    book, rows, _, sources = long_inputs()
    prior = json.loads(Path("state/research_runs/binance_macro_history_20261015_final/summary.json").read_text())
    selected = [e for e in prior["events"] if e["setup"] == "mean_reversion" and
                e["nonoverlap"] and not e["outcomes"]["15"]["censored"]]
    events = []
    for e in selected:
        s, i = e["symbol"], e["signal_index"]
        bars = book[s]
        date = dt.datetime.fromtimestamp(bars[i+1].t, NY).date()
        entry = int(dt.datetime.combine(date, dt.time(9, 30), NY).timestamp())
        review_index = next(j for j in range(i+1, len(bars)) if int(dt.datetime.combine(
            dt.datetime.fromtimestamp(bars[j].t, NY).date(), dt.time(9, 30), NY).timestamp()) >= entry+168*3600)
        review_date = dt.datetime.fromtimestamp(bars[review_index].t, NY).date()
        review_time = int(dt.datetime.combine(review_date, dt.time(9, 30), NY).timestamp())
        r = daily_replay({s: bars}, {s: rows["control"][s]}, "original_mr", start=date.isoformat(),
            end=(date+dt.timedelta(days=40)).isoformat(), entry_times={entry})
        assert len(r["trades"]) == 1
        t = r["trades"][0]
        assert t["signal_time"] == e["signal_available"]
        f = rows["control"][s][bars[review_index-1].t]
        alive = t["exit_time"] > review_time
        new_mr = bool(f["entry_tactical"] and f["tactical_setup"] == "mean_reversion")
        label = None
        if alive:
            price = bars[review_index].o*1.0025
            label = (t["exit_price"]-price)/price-.0005*(price+t["exit_price"])/price
        events.append(dict(symbol=s, signal_date=e["signal_date"], review_time=review_time,
            eligible_at_review=alive, new_mr_at_review=new_mr, remaining_net=label,
            price_repaired_at_review=f["hold_price_trend"],
            original_exit_reason=t["exit_reason"], original_exit_time=t["exit_time"]))
    groups = {}
    for name, choose in (("all_survivors", lambda e: e["eligible_at_review"]),
        ("new_mr", lambda e: e["eligible_at_review"] and e["new_mr_at_review"]),
        ("no_new_mr", lambda e: e["eligible_at_review"] and not e["new_mr_at_review"]),
        ("price_repaired", lambda e: e["eligible_at_review"] and e["price_repaired_at_review"]),
        ("not_repaired", lambda e: e["eligible_at_review"] and not e["price_repaired_at_review"])):
        v = [e for e in events if choose(e)]
        values = [e["remaining_net"] for e in v]
        groups[name] = dict(count=len(v), mean=statistics.mean(values) if values else None,
            interval=cluster_interval(v, "remaining_net"),
            median=statistics.median(values) if values else None,
            mean_without_best=(sum(values)-max(values))/(len(values)-1) if len(values)>1 else None)
    return dict(events=events, groups=groups, replay_count=len(events),
        note="Independent per-asset ETF entry shadows from93 preexisting15-session-purged MR events; retain only positions not already exited at the next actual trading open at/after entry+7calendar days. Remaining net is an extra unit bought there and sold with the original episode; not a joint-risk/capacity/funding-tested account, not causal signal alpha or independent OOS."), sources


def lot_pnl(lot, trade, funding, fee):
    paid = 0.
    for row in funding:
        stamp = int(row["fundingTime"])
        if not lot["entry_time"]*1000 <= stamp < trade["exit_time"]*1000:
            continue
        flow = -lot["quantity"]*float(row["markPrice"])*float(row["fundingRate"])
        if trade["exit_reason"] in ("stop", "liquidation_proxy") and stamp >= (trade["exit_time"]-3600)*1000 and flow > 0:
            continue
        paid += flow
    return (lot["quantity"]*(trade["exit_price"]-lot["entry_price"])
        -lot["entry_fee"]-lot["quantity"]*trade["exit_price"]*fee+paid)


def attribution(control, candidate, data, fee):
    key = lambda t: (t["symbol"], t["entry_time"])
    old, new = ({key(t): t for t in r["trades"]} for r in (control, candidate))
    added_lots, path_effects = [], []
    for k in sorted(old.keys() & new.keys()):
        t = new[k]
        lots = t.get("entry_lots", [dict(quantity=t["quantity"], entry_price=t["entry_price"],
            entry_time=t["entry_time"], entry_fee=t["entry_fee"])])
        pnl = [lot_pnl(lot, t, data[k[0]]["funding"], fee) for lot in lots]
        assert math.isclose(sum(pnl), t["net_pnl"], abs_tol=1e-8)
        for lot, value in zip(lots[1:], pnl[1:]):
            added_lots.append(dict(symbol=k[0], initial_time=k[1], **lot, net_pnl=value))
        path_effects.append(dict(symbol=k[0], entry_time=k[1], delta=pnl[0]-old[k]["net_pnl"]))
    removed = [old[k] for k in old.keys()-new.keys()]
    extra = [new[k] for k in new.keys()-old.keys()]
    delta = sum(t["net_pnl"] for t in added_lots)+sum(t["delta"] for t in path_effects)
    delta += sum(t["net_pnl"] for t in extra)-sum(t["net_pnl"] for t in removed)
    assert math.isclose(delta, candidate["headline"]["final_equity"]-control["headline"]["final_equity"], abs_tol=1e-8)
    return dict(added_lots=added_lots, other_path_effects=path_effects,
        removed_episodes=removed, added_episodes=extra, total_delta=delta)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--download", action="store_true", help="Only missing first-review17-minute public capacity windows")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output; keep prior results")
    (book, features, gates, caps), sources, _ = append_inputs("2026-10-26", False)
    # Existing first-review clock is known causally from entry+168h, independent of returns.
    review_caps, records, _ = load_capacity_contexts([("XLEUSDT", 1791381600)],
        Path("state/research_cache/macro_mr_topup_20261026/minutes"), download=args.download)
    caps = {**caps, **review_caps}
    sources += records
    prior = json.loads(Path("state/research_runs/macro_mr_holding_20261026/comparison.json").read_text())
    portfolios, checks = [], []
    count = 0
    for capital in (prior["parameters"]["capital"], 30., 100.):
        for scenario, fee, slip, shock in CASES:
            p = dict(prior["parameters"], capital=capital, fee=fee, slip=slip)
            data = cost_case(book, scenario)
            for profile, utilization, trigger in PROFILES:
                policy = MRTopupPolicy(data, features, caps, fee=fee, slip=slip, trigger=trigger) if trigger else None
                r = replay(data, features, entry_confirmations=gates, entry_liquidity_caps=caps,
                    funding_lease_entry_utilization=utilization, mr_topup_policy=policy,
                    exit_execution_model=DepthExitStress({}, use_depth=False, unknown_extra_slip=0,
                        all_extra_slip=shock) if shock else None, **p)
                verify_topup_replay(r, data, p)
                count += 1
                if profile == "control":
                    old = next(v for v in prior["portfolios"] if v["profile"] == "control" and
                        v["capital"] == capital and v["scenario"] == scenario)
                    assert r["trades"] == old["trades"] and r["curve"] == old["curve"]
                    checks.append(dict(capital=capital, scenario=scenario, exact=True))
                row = dict(profile=profile, initial_utilization=utilization, trigger=trigger,
                    capital=capital, scenario=scenario, headline=headline(r), trades=r["trades"],
                    curve=r["curve"], topup_attempts=r.get("topup_attempts", []),
                    topup_count=sum(len(t.get("topups", [])) for t in r["trades"]))
                if trigger:
                    base_profile = "control" if utilization == 1 else "half_control"
                    base = next(v for v in portfolios if v["profile"] == base_profile and
                        v["capital"] == capital and v["scenario"] == scenario)
                    row["attribution"] = attribution(base, row, data, fee)
                portfolios.append(row)
                print(capital, scenario, profile, r["summary"]["net_return"], r["summary"]["max_drawdown"], row["topup_count"], flush=True)
    directions, long_sources = review_direction_study()
    sources += long_sources
    unique = {r["path"]: r for r in sources}
    for r in unique.values():
        assert hashlib.sha256(Path(r["path"]).read_bytes()).hexdigest() == r["sha256"]
    out = dict(research_only=True, orders_authorized=False, independent_oos=False,
        hypothesis="Separate staging, new MR confirmation and budget utilization: full/half initial sizing under unchanged25% lifetime budget, with no add/new-MR add/first168h-review add.",
        parameters=prior["parameters"], sample_start="2026-04-07", sample_end_exclusive="2026-10-26",
        portfolios=portfolios, control_checks=checks, replay_count=count, direction=directions,
        sources=list(unique.values()),
        limitations=["One addition per episode; original stop/2R trigger, leverage, maturity, lease deadlines and lifetime funding/risk allowances do not reset. Per-lot risk floors disallow funding new losses with old unrealized stop profits.",
            "First-review reference uses current holding eligibility and financial/cost/capacity constraints, deliberately does not require a new entry/no-chase/MR1ATR signal. It is a different budget-rebalance mechanism, not certified new-entry alpha.",
            "Sequential consumed-history research. Only a few added episodes, hypothetical fills/current historical filters, not independent OOS or actual orders."])
    args.output.mkdir(parents=True)
    (args.output/"comparison.json").write_text(json.dumps(out, ensure_ascii=False, allow_nan=False)+"\n")
    lines = ["# MR风险预算的再配置：分批、再确认与定期补足", "",
        "主问题：在保留原盈利持仓、不重置原25%终身预算的条件下，新增MR确认能否兑现额外价值？先发现15U原轨迹无有效增量订单后，顺序追加固定50%首次利用率；再用原7日资金费复核作无新增MR信号的补足对照，未搜索比例或周期。",
        "control=原策略；mr_topup=新同标的MR通过完整原准入后才增；review_topup=首次7日复核后按持仓资格补足，不重新要求入场/不追涨/1ATR信号。half_*初始只用预算一半，但终身风险上限仍25%。",
        "最多一次增仓；旧止损不放宽、原2R触发参考/7日复核/21日最长持有不重置，资金费总额度不刷新；逐笔起息、手续费、混合成本与风险分别核算。",
        "2026-04-07至10-26前，8原生合约、现金0%，基础单边5bp手续费/25bp滑点及真实资金费；双成本10/50bp及不利常规资金费加倍，退出额外冲击另列。原分钟容量/现行档位、数量单位及最小订单继续适用。", "",
        "|本金|成本|规则|累计收益|小时MDD|持仓轮次|额外订单数|", "|---:|---|---|---:|---:|---:|---:|"]
    for r in portfolios:
        h = r["headline"]
        lines.append(f"|{r['capital']:.4f}|{r['scenario']}|{r['profile']}|{h['net_return']:.2%}|{h['max_drawdown']:.2%}|{h['trade_count']}|{r['topup_count']}|")
    lines += ["", "## 主账户基础情景的逐笔增仓收益与路径", ""]
    for r in portfolios:
        if r["capital"] != prior["parameters"]["capital"] or r["scenario"] != "base" or not r["trigger"]:
            continue
        a = r["attribution"]
        lines += [f"### {r['profile']}", "",
            f"相对同初始利用率控制，总增量{a['total_delta']:+.6f} USDT；额外腿净损益{sum(t['net_pnl'] for t in a['added_lots']):+.6f}，其余路径差{sum(t['delta'] for t in a['other_path_effects']):+.6f}。",
            json.dumps(a["added_lots"], ensure_ascii=False), ""]
    lines += ["## 长期事件：首次复核之后是否还有收益", "",
        directions["note"], "", "|7日后仍持仓组别|事件数|剩余单位名义净收益均值|季度块95%区间|去掉最好后均值|",
        "|---|---:|---:|---|---:|"]
    for name, row in directions["groups"].items():
        value = row["interval"]
        mean = f"{row['mean']:.2%}" if row["mean"] is not None else "—"
        interval = str(value["interval95"]) if value else "—"
        trimmed = f"{row['mean_without_best']:.2%}" if row["mean_without_best"] is not None else "—"
        lines.append(f"|{name}|{row['count']}|{mean}|{interval}|{trimmed}|")
    lines += ["", "该方向诊断忽略联合资金/容量约束、原生资金费及真实成交；同资产预先去重不消除跨资产同期依赖。存活筛选只用首次复核时已发生的退出，不能把剩余均值当实际增仓收益。", "",
        f"{count}次完整账户回放及{directions['replay_count']}次ETF单事件回放；12组旧控制逐值复现；每笔增仓独立费用/资金费、终身预算及资金费复核核对，{len(unique)}份输入hash一致。", ""]
    lines += ["- "+s for s in out["limitations"]]
    lines += ["", "仅离线研究，生产源码、参数、权限、服务均未改。", "",
        "复现：`PYTHONPATH=src ./.venv/bin/python scripts/research/study_macro_mr_staged.py --output <新目录>`", ""]
    (args.output/"report.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
