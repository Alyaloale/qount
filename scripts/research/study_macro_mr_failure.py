"""Distinguish transient MR trend failure from price failure, without threshold search."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import statistics
from pathlib import Path

from qount.research.binance_etf_leverage import replay
from qount.research.binance_macro_attack import CONTRACT_SIGNALS, macro_features
from qount.research.binance_macro_history import adjusted_bars
from qount.research.binance_macro_opportunities import cost_case
from qount.research.macro_depth_execution import DepthExitStress
from qount.research.macro_mechanism_value import daily_replay, mechanism_rows
from qount.research.macro_mr_exit import PROFILES, holding_profiles
from qount.research_data.archives import timestamp
from qount.research_data.bars import NY
from qount.research_data.regime import compute_ema
from continue_macro_fixed_candidates import CASES, append_inputs
from compare_macro_trend_continuation import CACHE, OLD, TAIL
from study_macro_admission_and_simplicity import headline, verify
from study_macro_mechanism_value import cluster_interval, paired_blocks


RUNS = Path("state/research_runs")
LONG = CACHE / "binance_macro_etf_history_20261015"


def long_inputs():
    fs, sources = macro_features(LONG, "2026-01-01", start_date="2016-01-01")
    book = {s: adjusted_bars(json.loads((LONG/f"yahoo-{t}-20160101-2026-01-01.json").read_text()))
            for s, t in CONTRACT_SIGNALS.items()}
    variants, diagnostics = holding_profiles(book, fs)
    base = {s: mechanism_rows(book[s], fs[s]) for s in book}
    rows = {name: {s: {f["available"]: dict(base[s][f["available"]],
        hold_structural=f["hold_structural"]) for f in stream} for s, stream in values.items()}
        for name, values in variants.items()}
    return book, rows, diagnostics, sources


def native_profiles(features, *, return_bars=False):
    book = {}
    last = max(f["available"] for stream in features.values() for f in stream)
    for symbol, ticker in CONTRACT_SIGNALS.items():
        pieces = ((OLD/f"yahoo-{ticker}-20250101-2026-10-15.json", 0, timestamp("2026-10-15")),
                  (TAIL/f"yahoo-{ticker}-20250101-2026-10-22.json", timestamp("2026-10-15"), timestamp("2026-10-22")),
                  (CACHE/f"macro_native_tail_20261026/yahoo-{ticker}-20250101-2026-10-26.json", timestamp("2026-10-22"), timestamp("2026-10-26")))
        book[symbol] = [b for path, left, right in pieces
                        for b in adjusted_bars(json.loads(path.read_text())) if left <= b.t < right and b.t <= last]
        closes = [b.c for b in book[symbol]]
        e50, e200 = compute_ema(closes, 50), compute_ema(closes, 200)
        original = {f["available"]: f for f in features[symbol]}
        for i in range(200, len(closes)):
            f = original[book[symbol][i].t]
            assert f["structural"] == (closes[i] > e200[i] and e50[i] > e200[i] and closes[i]/closes[i-63] > 1)
    return book if return_bars else holding_profiles(book, features)


def summarize_shadows(events):
    return {name: dict(count=len(v := [e for e in events if e["profile"] == name]),
        paired=cluster_interval(v, "delta"),
        by_year={y: dict(count=len(w := [e for e in v if e["signal_date"].startswith(y)]),
            mean_delta=statistics.mean(e["delta"] for e in w)) for y in sorted({e["signal_date"][:4] for e in v})},
        by_original_exit={reason: dict(count=len(w := [e for e in v if e["control"]["exit_reason"] == reason]),
            mean_delta=statistics.mean(e["delta"] for e in w)) for reason in sorted({e["control"]["exit_reason"] for e in v})})
        for name in PROFILES[1:]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output; retain previous evidence")
    book, rows, long_diagnostics, sources = long_inputs()
    prior = json.loads((RUNS/"macro_mechanism_value_20261026_reviewed/comparison.json").read_text())
    daily, pairs, checks = [], [], []
    for target in (None, .15):
        for profile in PROFILES:
            r = daily_replay(book, rows[profile], "original_mr", vol_target=target)
            r["exit_profile"] = profile
            daily.append(r)
            if profile == "control":
                old = next(v for v in prior["portfolios"] if v["profile"] == "original_mr" and v["vol_target"] == target)
                assert r["trades"] == old["trades"] and r["curve"] == old["curve"]
                checks.append(dict(sample="ETF", vol_target=target, exact_reproduction=True))
            print("ETF", target, profile, r["summary"]["cagr_pct"], r["summary"]["max_drawdown_pct"], flush=True)
        lookup = {r["exit_profile"]: r for r in daily if r["vol_target"] == target}
        for profile in PROFILES[1:]:
            pairs.append(dict(profile=profile, vol_target=target,
                              **paired_blocks(lookup[profile], lookup["control"])))
    daily_shadows, daily_shadow_replays = [], 0
    primary = next(r for r in daily if r["exit_profile"] == "control" and r["vol_target"] is None)
    for t in primary["trades"]:
        if t["exit_reason"] == "end_of_sample":
            continue
        start = dt.datetime.fromtimestamp(t["entry_time"], NY).date()
        results = {}
        for profile in PROFILES:
            r = daily_replay(book, rows[profile], "original_mr", start=start.isoformat(),
                end=(start+dt.timedelta(days=50)).isoformat(), capital=t["equity_at_entry"],
                entry_times={t["entry_time"]})
            daily_shadow_replays += 1
            assert len(r["trades"]) == 1
            trade = r["trades"][0]
            assert abs(trade["quantity"]-t["quantity"]) < 1e-8 and trade["entry_price"] == t["entry_price"]
            results[profile] = trade
        assert results["control"] == t
        for profile in PROFILES[1:]:
            a, b = results["control"], results[profile]
            if b["exit_reason"] == "end_of_sample":
                continue
            daily_shadows.append(dict(profile=profile, symbol=t["symbol"], signal_date=start.isoformat(),
                delta=(b["net_pnl"]-a["net_pnl"])/(t["quantity"]*t["entry_price"]), control=a, candidate=b))
    (native, features, gates, caps), native_sources, _ = append_inputs("2026-10-26", False)
    sources += native_sources
    variants, native_diagnostics = native_profiles(features)
    # Prefix recomputation verifies the new holding states use no future sessions.
    prefix_checks = []
    for cutoff in ("2026-06-30", "2026-08-31", "2026-09-30"):
        short = {s: [f for f in stream if f["available"] < timestamp(cutoff)] for s, stream in features.items()}
        prefix, _ = native_profiles(short)
        for name in PROFILES:
            for s in features:
                assert prefix[name][s] == [f for f in variants[name][s] if f["available"] < timestamp(cutoff)]
        prefix_checks.append(cutoff)
    saved = json.loads((RUNS/"macro_mr_holding_20261026/comparison.json").read_text())
    native_results, native_shadows, count = [], [], 0

    def run(profile, case, params, shock=0, only=None):
        nonlocal count
        data = cost_case(native, case)
        result = replay(data, variants[profile], entry_confirmations=gates if only is None else only,
            entry_liquidity_caps=caps, exit_execution_model=DepthExitStress({}, use_depth=False,
                unknown_extra_slip=0, all_extra_slip=shock) if shock else None, **params)
        verify(result, data, params)
        count += 1
        return result

    for capital in (saved["parameters"]["capital"], 30., 100.):
        for case, fee, slip, shock in CASES:
            p = dict(saved["parameters"], capital=capital, fee=fee, slip=slip)
            for profile in PROFILES:
                r = run(profile, case, p, shock)
                if profile == "control":
                    old = next(v for v in saved["portfolios"] if v["profile"] == "control"
                        and v["capital"] == capital and v["scenario"] == case)
                    assert r["trades"] == old["trades"] and r["curve"] == old["curve"]
                    checks.append(dict(sample="native", capital=capital, scenario=case, exact_reproduction=True))
                native_results.append(dict(profile=profile, scenario=case, capital=capital,
                    headline=headline(r), trades=r["trades"], curve=r["curve"]))
                print("native", capital, case, profile, r["summary"]["net_return"], r["summary"]["max_drawdown"], flush=True)
    # MR opportunities are selected in chronological 21-day nonoverlap order BEFORE gates/outcomes.
    next_allowed, selected = {}, []
    for key, gate in sorted(gates.items(), key=lambda item: (item[0][1], item[0][0])):
        s, now = key
        if gate["setup"] != "mean_reversion" or now+504*3600 > timestamp("2026-10-26") or now < next_allowed.get(s, 0):
            continue
        next_allowed[s] = now+504*3600
        selected.append(key)
    for key in selected:
        only = {k: dict(g, eligible=g["eligible"] and k == key) for k, g in gates.items()}
        for case, fee, slip, _ in CASES[:2]:
            p = dict(saved["parameters"], fee=fee, slip=slip)
            result = {profile: run(profile, case, p, only=only) for profile in PROFILES}
            sizes = {profile: [t["quantity"] for t in r["trades"]] for profile, r in result.items()}
            assert all(v == sizes["control"] for v in sizes.values())
            for profile in PROFILES[1:]:
                a, b = (result[name]["trades"][0] if result[name]["trades"] else None
                        for name in ("control", profile))
                native_shadows.append(dict(profile=profile, scenario=case, symbol=key[0], time=key[1],
                    signal_date=dt.datetime.fromtimestamp(key[1], NY).date().isoformat(),
                    control=a, candidate=b, delta=(b["net_pnl"]-a["net_pnl"])/a["notional_usdt"] if a else None))
    unique = {r["path"]: r for r in sources}
    for r in unique.values():
        assert hashlib.sha256(Path(r["path"]).read_bytes()).hexdigest() == r["sha256"]
    out = dict(research_only=True, orders_authorized=False, independent_oos=False,
        hypothesis="Two fixed failure definitions: two completed-session loss of original qualification, or own/SPY price below EMA200. Entry, stops, horizon and financial constraints unchanged.",
        daily=daily, daily_pairs=pairs, daily_shadows=daily_shadows,
        daily_shadow_summary=summarize_shadows(daily_shadows), native=native_results,
        native_shadows=native_shadows, native_selected_clocks=selected,
        daily_diagnostics=long_diagnostics, native_diagnostics=native_diagnostics,
        prefix_checks=prefix_checks, control_checks=checks, sources=list(unique.values()),
        replay_count=len(daily)+daily_shadow_replays+count)
    args.output.mkdir(parents=True)
    (args.output/"comparison.json").write_text(json.dumps(out, ensure_ascii=False, allow_nan=False)+"\n")
    lines = ["# MR修复失败：双收盘确认与价格失效", "",
        "两个固定机制、不扫阈值：two_closes允许原趋势资格失效一个已完成交易日，连续第二日失效才退出；price200在自身收盘及权益所需SPY收盘仍高于EMA200时持有，放松EMA50/63日收益条件。",
        "原入场/排序不变，最长21自然日、2ATR/移动止损不变；原生每7日复核仍按候选趋势资格及原财务风险/现金/终身预算执行。任何初始入场门都未放宽。", "",
        "ETF：2017–2025、2016暖启动、八代理、10000美元等值、单仓无杠杆、下一开盘、现金0%；原生：2026-04-07至10-26前、8合约、25%压力预算、原容量/档位。基础单边5bp手续费/25bp滑点，原生计真实资金费；双成本10/50bp及不利常规资金费加倍。", "",
        "## ETF账户", "", "|入场仓位|退出规则|CAGR|日MDD|交易数|2020|2022|2025|",
        "|---|---|---:|---:|---:|---:|---:|---:|"]
    for r in daily:
        h = r["summary"]
        lines.append(f"|{r['vol_target']}|{r['exit_profile']}|{h['cagr_pct']:.2f}%|{h['max_drawdown_pct']:.2f}%|{h['trades']}|{h['years']['2020']:.2%}|{h['years']['2022']:.2%}|{h['years']['2025']:.2%}|")
    lines += ["", "## 同一ETF入场的退出增量", "",
        "固定原入场、价格、数量的独立影子，季度整组重抽；后续区间可重叠，不把均值当账户收益。", ""]
    for name, r in out["daily_shadow_summary"].items():
        v = r["paired"]
        lines.append(f"- {name}：{r['count']}对，单位名义净增量{v['mean']:.3%}，季度块95%区间{v['interval95']}；按原退出原因：{json.dumps(r['by_original_exit'], ensure_ascii=False)}。")
    lines += ["", "## 原生账户", "", "|本金|情景|退出规则|收益|小时MDD|交易数|", "|---:|---|---|---:|---:|---:|"]
    for r in native_results:
        h = r["headline"]
        lines.append(f"|{r['capital']:.4f}|{r['scenario']}|{r['profile']}|{h['net_return']:.2%}|{h['max_drawdown']:.2%}|{h['trade_count']}|")
    lines += ["", "## 原生独立MR机会影子", "",
        f"按每资产21日时间去重、最长周期成熟先选{len(selected)}个时点，再保留全部准入拒绝；不是独立OOS，各资产可同期相关。", "",
        "|情景|规则|时点数|控制成交数|平均单位名义增量|", "|---|---|---:|---:|---:|"]
    for case in ("base", "double_cost"):
        for profile in PROFILES[1:]:
            v = [r for r in native_shadows if r["profile"] == profile and r["scenario"] == case]
            accepted = [r["delta"] for r in v if r["delta"] is not None]
            mean = f"{statistics.mean(accepted):.3%}" if accepted else "—"
            lines.append(f"|{case}|{profile}|{len(v)}|{len(accepted)}|{mean}|")
    lines += ["", f"{out['replay_count']}次回放；{len(checks)}组旧控制逐值复现；输入{len(unique)}份hash核对。", "",
        "同一批历史已消费，机制由前序观察提出，不能认定独立OOS或选择调整后的显著性。ETF复权单位、日线止损/09:30与原生小时/10:00、现行档位历史套用和真实IOC差异继续存在；跨时期结果不能直接作资产类别因果结论。",
        "本轮仅离线研究，生产信号、配置、权限和调度不变。", "",
        "复现：`PYTHONPATH=src ./.venv/bin/python scripts/research/study_macro_mr_failure.py --output <新目录>`", ""]
    (args.output/"report.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
