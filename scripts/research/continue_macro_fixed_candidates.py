"""Append public observations and compare only the retained macro budget candidate."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from qount.research.binance_etf_leverage import replay
from qount.research.binance_macro_attack import CONTRACT_SIGNALS, MACRO_TEN
from qount.research.binance_macro_history import adjusted_bars
from qount.research.binance_macro_liquidity import load_capacity_contexts
from qount.research.binance_macro_opportunities import cost_case
from qount.research.macro_depth_execution import DepthExitStress
from qount.research_data.archives import timestamp
from qount.research_data.bars import NY
from qount.research_data.binance_history import load_cached_history, load_inputs
from qount.research_data.macro_live import fetch_proxy_payload, parse_proxy
from qount.strategies.macro_1atr import scaled_features
from qount.strategies.macro_episodes import episode_confirmations
from qount.strategies.macro_features import build_macro_features
from qount.strategies.macro_gates import mean_reversion_gap_confirmations
from compare_macro_trend_continuation import CACHE, OLD, ROOTS, RUNS, TAIL, extended_inputs
from study_macro_admission_and_simplicity import headline, verify


PRIOR = RUNS / "macro_native_entry_reviewed_20261022/comparison.json"
CASES = (("base", .0005, .0025, 0), ("double_cost", .001, .005, 0),
         ("exit50bp", .0005, .0025, .005), ("exit200bp", .0005, .0025, .02))


def append_inputs(end_date, download):
    _, old, sources, _ = extended_inputs()
    old_book, old_signals, old_gates, old_caps = old
    cutoff, end = timestamp("2026-10-22"), timestamp(end_date)
    if not cutoff < end <= int(dt.datetime.now(dt.timezone.utc).timestamp()) // 86400 * 86400:
        raise ValueError("end_must_be_a_new_completed_UTC_day")
    tail = CACHE / ("macro_native_tail_" + end_date.replace("-", ""))
    load_inputs(tail, cutoff, end, download=download, symbols=tuple(CONTRACT_SIGNALS))
    book, native, excluded = load_cached_history(ROOTS + [TAIL, tail], tuple(CONTRACT_SIGNALS),
        timestamp("2026-04-07"), end, OLD / "exchange-info.json")
    if excluded:
        raise ValueError("missing_native_inputs:" + str(excluded))
    sources += native
    for symbol in book:
        for kind in ("trade", "mark", "funding"):
            prefix = [r for r in book[symbol][kind] if
                      (int(r["fundingTime"]) // 1000 if kind == "funding" else r.t) < cutoff]
            assert prefix == old_book[symbol][kind], (symbol, kind)

    def proxy(ticker):
        path = tail / f"yahoo-{ticker}-20250101-{end_date}.json"
        if not path.exists():
            if not download:
                raise FileNotFoundError(path)
            payload = fetch_proxy_payload(ticker, end-1,
                validate=lambda value: parse_proxy(ticker, value, end-1), max_attempts=4)
            with path.open("x") as stream:
                json.dump(payload, stream, separators=(",", ":"), allow_nan=False)
        payload = json.loads(path.read_text())
        parse_proxy(ticker, payload, end-1)
        action_path = tail / f"yahoo-{ticker}-actions-20261022-{end_date}.json"
        if not action_path.exists():
            if not download:
                raise FileNotFoundError(action_path)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            params = dict(period1=cutoff, period2=end, interval="1d", events="div,splits,capitalGains")
            for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
                try:
                    request = urllib.request.Request("https://"+host+"/v8/finance/chart/"+ticker+"?"+
                        urllib.parse.urlencode(params), headers={"User-Agent": "Mozilla/5.0"})
                    with opener.open(request, timeout=5) as response:
                        action_payload = json.load(response)
                    assert action_payload["chart"]["result"][0]["timestamp"]
                    break
                except (OSError, ValueError, KeyError, TypeError, AssertionError):
                    if host.startswith("query2"):
                        raise
            with action_path.open("x") as stream:
                json.dump(action_payload, stream, separators=(",", ":"), allow_nan=False)
        action_payload = json.loads(action_path.read_text())["chart"]["result"][0]
        fresh = [b for b in adjusted_bars(payload) if b.t < end]
        original = adjusted_bars(json.loads((OLD / f"yahoo-{ticker}-20250101-2026-10-15.json").read_text()))
        prior_tail = adjusted_bars(json.loads((TAIL / f"yahoo-{ticker}-20250101-2026-10-22.json").read_text()))
        previous = original + [b for b in prior_tail if timestamp("2026-10-15") <= b.t < cutoff]
        actions = [row for group in action_payload.get("events", {}).values() for row in group.values()
                   if cutoff <= int(row["date"]) < end]
        if actions:
            raise ValueError("new_corporate_action_requires_PIT_review:" + ticker)
        prices = {b.t: b.c for b in previous}
        revision = max(abs(b.c / prices[b.t] - 1) for b in fresh if b.t in prices)
        if revision > 1e-5:
            raise ValueError("material_adjustment_revision:" + ticker)
        bars = previous + [b for b in fresh if b.t >= cutoff]
        assert [b.t for b in bars] == sorted({b.t for b in bars})
        dates = [dt.datetime.fromtimestamp(b.t, NY).date().isoformat() for b in bars]
        source = dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        return (ticker, bars, dates, source), dict(ticker=ticker, overlap_revision=revision,
            appended_dates=[day for b, day in zip(bars, dates) if b.t >= cutoff], corporate_actions=actions,
            action_source=dict(path=str(action_path), sha256=hashlib.sha256(action_path.read_bytes()).hexdigest()))

    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(proxy, sorted(set(MACRO_TEN) | set(CONTRACT_SIGNALS.values()))))
    signals = scaled_features(build_macro_features([r[0] for r in rows], CONTRACT_SIGNALS)[0])
    for symbol in signals:
        assert [f for f in signals[symbol] if f["available"] < cutoff] == old_signals[symbol], symbol
    anchors = episode_confirmations(book, signals, "no_chase")
    gaps = mean_reversion_gap_confirmations(book, signals, anchors)
    gates = {key: {**g, "eligible": g["eligible"] and gaps[key]["eligible"],
                   "reason": gaps[key]["reason"] if g["eligible"] else g["reason"]}
             for key, g in anchors.items()}
    assert {k: v for k, v in gates.items() if k[1] < cutoff} == old_gates
    caps, minute_sources, _ = load_capacity_contexts([k for k in gates if k not in old_caps],
        tail / "minutes", download=download)
    caps = {**old_caps, **caps}
    assert set(gates) <= set(caps)
    sources += [r[0][3] for r in rows] + [r[1]["action_source"] for r in rows] + minute_sources
    venue_path = RUNS / "macro_leverage_cash_review_20261019/venue_snapshot.json"
    venue = json.loads(venue_path.read_text())
    for symbol in book:
        book[symbol]["rule"] = dict(book[symbol]["rule"],
            leverage_brackets=venue["symbols"][symbol]["brackets"])
    sources.append(dict(path=str(venue_path), sha256=hashlib.sha256(venue_path.read_bytes()).hexdigest()))
    return (book, signals, gates, caps), sources, [r[1] for r in rows]


def flat_week(book, signals, gates, caps, risk, parameters):
    """Preserve all warmup; suppress orders before the observed empty-account week."""
    start = timestamp("2026-10-19")
    failures = {"2026-10-19", "2026-10-20", "2026-10-22"}
    rows = []
    for availability in ("all_inputs_available", "documented_input_failures"):
        allowed = {}
        for key, gate in gates.items():
            date = dt.datetime.fromtimestamp(key[1], NY).date().isoformat()
            disabled = key[1] < start or availability == "documented_input_failures" and date in failures
            allowed[key] = dict(gate, eligible=False, reason="flat_start_or_documented_input_failure") if disabled else gate
        for scenario, fee, slip, shock in CASES:
            p = dict(parameters, fee=fee, slip=slip)
            for profile in ("control", "trend_half_any"):
                data = cost_case(book, scenario)
                result = replay(data, signals, entry_confirmations=allowed, entry_liquidity_caps=caps,
                    entry_risk_controls=risk if profile == "trend_half_any" else None,
                    exit_execution_model=DepthExitStress({}, use_depth=False, unknown_extra_slip=0,
                        all_extra_slip=shock) if shock else None, trace=True, **p)
                verify(result, data, p)
                assert all(t["entry_time"] >= start for t in result["trades"])
                rows.append(dict(availability=availability, profile=profile, scenario=scenario,
                    capital=p["capital"], start="2026-10-19", headline=headline(result),
                    trades=result["trades"], curve=[r for r in result["curve"] if r["time"] >= start],
                    decisions=[r for r in result["decisions"] if r["time"] >= start]))
                print("Flat week", availability, scenario, profile,
                      result["summary"]["net_return"], len(result["trades"]), flush=True)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end", required=True, help="Exclusive completed UTC date")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--download", action="store_true", help="Fetch missing public inputs only")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output; retain prior evidence")
    saved = json.loads(PRIOR.read_text())
    (book, signals, gates, caps), sources, revisions = append_inputs(args.end, args.download)
    print("Public inputs validated; historical prefixes unchanged", flush=True)
    cutoff = timestamp("2026-10-22")
    risk = {key: dict(asof=key[1], multiplier=1 if g["setup"] == "mean_reversion" else .5)
            for key, g in gates.items()}
    portfolios, checks = [], []
    # Replay old controls again with appended features but truncated native bars.
    # This catches changes in shared replay code without reusing a stale result.
    old_book = {s: {**d, **{kind: [r for r in d[kind] if
        (int(r["fundingTime"]) // 1000 if kind == "funding" else r.t) < cutoff]
        for kind in ("trade", "mark", "funding")}} for s, d in book.items()}
    for capital in (saved["parameters"]["capital"], 30., 100.):
        for scenario, fee, slip, shock in CASES:
            p = dict(saved["parameters"], capital=capital, fee=fee, slip=slip)
            for profile in ("control", "trend_half_any"):
                kwargs = dict(entry_confirmations=gates, entry_liquidity_caps=caps,
                    entry_risk_controls=risk if profile == "trend_half_any" else None,
                    exit_execution_model=DepthExitStress({}, use_depth=False,
                        unknown_extra_slip=0, all_extra_slip=shock) if shock else None)
                if capital == saved["parameters"]["capital"]:
                    before = replay(cost_case(old_book, scenario), signals, **kwargs, **p)
                    prior = next(r for r in saved["portfolios"] if r["capital"] == capital
                        and r["gross_cap"] == 20 and r["scenario"] == scenario and r["profile"] == profile)
                    assert before["trades"] == prior["trades"], (profile, scenario, "old trades")
                    assert before["curve"] == prior["curve"], (profile, scenario, "old curve")
                    checks.append(dict(profile=profile, scenario=scenario, exact_old_reproduction=True))
                data = cost_case(book, scenario)
                result = replay(data, signals, trace=True, **kwargs, **p)
                verify(result, data, p)
                interval = [v for v in result["curve"] if v["time"] >= cutoff]
                first = next(v for v in interval if v["time"] == cutoff)["equity"]
                new_trades = [t for t in result["trades"] if t["entry_time"] >= cutoff]
                portfolios.append(dict(profile=profile, scenario=scenario, capital=capital,
                    headline=headline(result), trades=result["trades"], curve=result["curve"],
                    incremental=dict(start_equity=first, end_equity=result["summary"]["final_equity"],
                        net_return=result["summary"]["final_equity"] / first - 1,
                        new_entries=len(new_trades), new_trades=new_trades),
                    new_decisions=[d for d in result["decisions"] if d["time"] >= cutoff]))
                print(capital, scenario, profile, portfolios[-1]["incremental"]["net_return"],
                      portfolios[-1]["incremental"]["new_entries"], flush=True)
    week = flat_week(book, signals, gates, caps, risk, saved["parameters"])
    unique_sources = {r["path"]: r for r in sources}
    for path, row in unique_sources.items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == row["sha256"]
    out = dict(research_only=True, orders_authorized=False, independent_oos=False,
        sample_start="2026-04-07", sample_end_exclusive=args.end, increment_start="2026-10-22",
        hypothesis="Fixed control and retained trend-half-budget candidate on appended observations; no tuning.",
        parameters=saved["parameters"], proxy_checks=revisions, prior_checks=checks,
        sources=list(unique_sources.values()), portfolios=portfolios,
        flat_week=week, documented_failed_entry_dates=["2026-10-19", "2026-10-20", "2026-10-22"],
        replay_count=len(portfolios)+len(checks)+len(week))
    args.output.mkdir(parents=True)
    (args.output / "comparison.json").write_text(json.dumps(out, ensure_ascii=False, allow_nan=False)+"\n")
    lines = ["# 宏观实盘策略：固定候选增量复核", "",
        f"历史窗2026-04-07至{args.end}（右端不含），新增段2026-10-22起；8个原生合约、13个ETF/宏观代理。",
        "控制为现行25%压力预算；唯一候选为突破/回撤12.5%、均值回归仍25%。保留原成本/容量门、排序、单仓、7/21天期限、续期及止损，无参数搜索。",
        "基础每边手续费5bp、滑点25bp及真实历史资金费；双成本10/50bp及不利常规资金费加倍；退出额外50/200bp单独施压，不额外叠加未知盘口2%。现金基准0%。",
        "信号仅用此前完成日线，纽约10:00决策、小时开盘成交近似；分钟容量仅用决策前可用区间。现行交易单位和10月19日档位历史套用。", "",
        "|本金USDT|成本|规则|全窗收益|小时MDD|新增段收益|新增入场|闭合/总笔数|",
        "|---:|---|---|---:|---:|---:|---:|---:|"]
    for r in portfolios:
        h, inc = r["headline"], r["incremental"]
        lines.append(f"|{r['capital']:.4f}|{r['scenario']}|{r['profile']}|{h['net_return']:.2%}|{h['max_drawdown']:.2%}|{inc['net_return']:.2%}|{inc['new_entries']}|{h['closed_count']}/{h['trade_count']}|")
    lines += ["", "## 从真实空仓状态起算的最近一周", "",
        "10月19日UTC起初始15.27112826USDT、无继承仓位；ATR、episode和信号仍使用全部原历史暖启动，只禁止此前开仓。",
        "all_inputs_available假设每个正式周期输入成功；documented_input_failures按current.md记载禁止19/20/22日新入场。后者仅建模已知入场故障，不认证完整线上事件、订单和网络路径。",
        "该反事实检验长期账本与真实空仓起点的差异；错过信号的事后路径不是可交易建议或已损失收益。", "",
        "|输入可用性|成本|规则|周收益|小时MDD|闭合/总笔数|末端估值损益USDT|",
        "|---|---|---|---:|---:|---:|---:|"]
    for r in week:
        h = r["headline"]
        lines.append(f"|{r['availability']}|{r['scenario']}|{r['profile']}|{h['net_return']:.2%}|{h['max_drawdown']:.2%}|{h['closed_count']}/{h['trade_count']}|{h['censored_pnl']:+.6f}|")
    main_row = portfolios[0]
    lines += ["", "## 新段正式决策回放", "", "```json",
        json.dumps(main_row["new_decisions"], ensure_ascii=False, indent=2), "```", "",
        "## 证据与裁决", "",
        f"{len(checks)}组旧窗成交和净值逐值复现；{len(portfolios)}组新窗及{len(week)}组空仓起点账本费用/资金费/现金/风险预算核对通过；旧原生日线、信号和门前缀不变。",
        f"13个代理公司行动与调整价格重取检查通过；{len(unique_sources)}份输入运行后hash一致。",
        "新段按事后可获得公开输入回放，不认证当时数据可获取、正式周期成功或真实可成交。无独立OOS资格；交易机会少，不能用短期空仓证明策略有效。",
        "本轮裁决基于新增入场、完整交易路径和成本敏感性；若新增交易为0，则未增加候选风险收益比较的信息，不提高研究置信度或改变实盘参数。",
        "不修改生产源码、服务、配置或权限。", "",
        f"复现：`PYTHONPATH=src ./.venv/bin/python scripts/research/continue_macro_fixed_candidates.py --end {args.end} --output <新目录>`", ""]
    lines += ["## 空仓起点的逐笔解释", ""]
    for r in week:
        if r["availability"] != "all_inputs_available" or r["scenario"] != "base":
            continue
        for t in r["trades"]:
            entry = dt.datetime.fromtimestamp(t["entry_time"], dt.timezone.utc).isoformat()
            exit_time = dt.datetime.fromtimestamp(t["exit_time"], dt.timezone.utc).isoformat()
            lines.append(f"- {r['profile']}：{t['symbol']} / {t['tactical_setup']}，{entry}入场{t['quantity']}单位，"
                f"{exit_time}按{t['exit_reason']}退出；净损益{t['net_pnl']:+.6f} USDT，"
                f"资金费{t['funding']:+.6f} USDT。")
    lines += ["", "本次错过信号的事后路径不能直接记作漏失盈利，故障本身也不能被视为有益机制。降低趋势预算仍只是风险配置候选；这一个空仓起点交易不足以证明稳定增益。", ""]
    (args.output / "report.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
