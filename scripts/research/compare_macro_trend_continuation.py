"""Close the retained censored trade and test two fixed trend lease mechanisms."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import qount.research.binance_etf_leverage as model
from qount.research.binance_macro_attack import CONTRACT_SIGNALS, MACRO_TEN
from qount.research.binance_macro_history import adjusted_bars
from qount.research.binance_macro_liquidity import load_capacity_contexts
from qount.research.binance_macro_opportunities import cost_case
from qount.research.lines.macro_1atr import inputs
from qount.research.macro_depth_execution import DepthExitStress
from qount.research.macro_trend_lease import review_profitable_trend
from qount.research_data.archives import timestamp
from qount.research_data.bars import NY
from qount.research_data.binance_history import load_cached_history
from qount.strategies.macro_1atr import scaled_features
from qount.strategies.macro_episodes import episode_confirmations
from qount.strategies.macro_features import build_macro_features
from qount.strategies.macro_gates import mean_reversion_gap_confirmations
from study_macro_admission_and_simplicity import headline, verify


CACHE = Path("state/research_cache")
RUNS = Path("state/research_runs")
OLD = CACHE/"binance_macro_attack_20261015"
TAIL = CACHE/"macro_native_tail_20261022"
ROOTS = [CACHE/n for n in ("binance_macro_prefix_20260407_20260611", "binance_macro_earlier_20260611_20260730", "binance_macro_attack_20261015")]
PROFILES = ("control", "trend_roll21", "profitable_trend_roll21")


def extended_inputs(download_minutes=False):
    old_book, old_signals, old_gates, old_caps, sources = inputs(OLD, ROOTS,
        CACHE/"binance_macro_liquidity_20261015", "2026-04-07", "2026-10-15")
    book, native, excluded = load_cached_history(ROOTS+[TAIL], tuple(CONTRACT_SIGNALS),
        timestamp("2026-04-07"), timestamp("2026-10-22"), OLD/"exchange-info.json")
    if excluded:
        raise ValueError("missing_extended_native_inputs:"+str(excluded))
    sources += native
    fetched, revisions = [], {}
    cutoff, end = timestamp("2026-10-15"), timestamp("2026-10-22")
    for ticker in sorted(set(MACRO_TEN) | set(CONTRACT_SIGNALS.values())):
        old_path = OLD/f"yahoo-{ticker}-20250101-2026-10-15.json"
        new_path = TAIL/f"yahoo-{ticker}-20250101-2026-10-22.json"
        old_payload, new_payload = json.loads(old_path.read_text()), json.loads(new_path.read_text())
        old_bars, fresh = adjusted_bars(old_payload), adjusted_bars(new_payload)
        events = new_payload["chart"]["result"][0].get("events", {})
        actions = [v for group in events.values() for v in group.values() if cutoff <= int(v["date"]) < end]
        if actions:
            raise ValueError("new_corporate_action_requires_point_in_time_adjustment:"+ticker)
        old_prices = {b.t: b.c for b in old_bars}
        revisions[ticker] = max(abs(b.c/old_prices[b.t]-1) for b in fresh if b.t in old_prices)
        if revisions[ticker] > 1e-5:
            raise ValueError("material_adjustment_revision:"+ticker)
        # Retain the exact old bars; only append the newly completed sessions.
        bars = old_bars+[b for b in fresh if cutoff <= b.t < end]
        assert [b.t for b in bars] == sorted({b.t for b in bars})
        assert dt.datetime.fromtimestamp(bars[-1].t, NY).date().isoformat() == "2026-10-21"
        source = dict(path=str(new_path), sha256=hashlib.sha256(new_path.read_bytes()).hexdigest())
        sources.append(source)
        fetched.append((ticker, bars, [dt.datetime.fromtimestamp(b.t, NY).date().isoformat() for b in bars], source))
    signals = scaled_features(build_macro_features(fetched, CONTRACT_SIGNALS)[0])
    for symbol in old_signals:
        assert [f for f in signals[symbol] if f["available"] < cutoff] == old_signals[symbol], symbol
    anchors = episode_confirmations(book, signals, "no_chase")
    gaps = mean_reversion_gap_confirmations(book, signals, anchors)
    gates = {key: {**g, "eligible": g["eligible"] and gaps[key]["eligible"],
                   "reason": gaps[key]["reason"] if g["eligible"] else g["reason"]} for key, g in anchors.items()}
    assert {k: v for k, v in gates.items() if k[1] < cutoff} == old_gates
    new_keys = [key for key in gates if key not in old_caps]
    new_caps, rows, _ = load_capacity_contexts(new_keys, TAIL/"minutes", download=download_minutes)
    sources += rows
    caps = {**old_caps, **new_caps}
    assert set(gates) <= set(caps)
    return (old_book, old_signals, old_gates, old_caps), (book, signals, gates, caps), sources, revisions


def profile_parameters(parameters, name):
    p = copy.deepcopy(parameters)
    if name != "control":
        p["funding_lease_setups"] = ("breakout", "pullback", "mean_reversion")
        for setup in ("breakout", "pullback"):
            p["tactical_setup_policies"][setup]["max_hold_hours"] = 504
    return p


def write_report(output):
    lines = ["# 宏观策略延长样本与趋势续期实验", "",
        "初始15.27112826USDT、25%压力预算、原20x名义上限、现行档位历史套用、原分钟容量、现金0%。",
        "旧窗2026-04-07至10-15；延长至10-22（右端均不含）。新段事后回放，不能冒充当时前向或独立OOS。",
        "旧日线/特征前缀逐项不变，只追加新完成日；13只代理新段无公司行动，旧调整价格重取差异小于1e-5。",
        "基础单边手续费5bp、滑点25bp及实际资金费；双成本10/50bp及不利常规资金费加倍；50bp额外退出冲击不改变事前准入成本。", "",
        "## 两个固定机制", "",
        "- trend_roll21：突破/回撤最长7→21天，仍按原hold_tactical退出；每7天重新检查资金费、现金与原终身风险预算。",
        "- profitable_trend_roll21：同上，趋势续期还要求按当时开盘价估算的即时退出净损益非负；不使用未来价格。",
        "- 均值回归、初始风险、成本门、不追涨、止损及容量均保留；不是提前为21天成本放宽准入。", "",
        "|窗口|机制|成本|收益|小时MDD|交易数|已闭合损益|末端截尾损益|", "|---|---|---|---:|---:|---:|---:|---:|"]
    for r in output["portfolios"]:
        s = r["headline"]
        lines.append(f"|{r['window']}|{r['profile']}|{r['scenario']}|{s['net_return']:.2%}|{s['max_drawdown']:.2%}|{s['trade_count']}|{s['closed_pnl']:+.5f}|{s['censored_pnl']:+.5f}|")
    lines += ["", "## 原末端持仓的自然结果", ""]
    for r in output["portfolios"]:
        if r["window"] != "extended" or r["profile"] != "control" or r["scenario"] != "base":
            continue
        old = output["old_censored_trade"]
        matching = [t for t in r["trades"] if (t["symbol"], t["entry_time"]) == (old["symbol"], old["entry_time"])]
        for t in matching:
            lines.append(f"- {t['symbol']} 入场{dt.datetime.fromtimestamp(t['entry_time'],dt.timezone.utc).isoformat()}，"
                f"原截尾损益{old['net_pnl']:+.5f}，延长后损益{t['net_pnl']:+.5f}、退出{t['exit_reason']}、"
                f"退出时点{dt.datetime.fromtimestamp(t['exit_time'],dt.timezone.utc).isoformat()}。")
    lines += ["", "## 验证与限制", "",
        f"- {output['replay_count']}次回放，旧基础/双成本精确复现；延长回放的旧末端强制估值之前净值前缀一致。",
        "- 逐笔核对实际资金费、手续费、现金、预算、信息可用时点；每笔续期不扩大原终身资金费和压力预算。",
        "- 新公开尾段只验证原信号后续路径，时间短且已观察；不作为新候选独立样本外认证。",
        "- 现行交易单位/档位历史套用、小时止损路径、退出容量和真实原生止损仍为近似。",
        "- 研究不改变生产源码、配置、权限或定时器。", "",
        "复现：`PYTHONPATH=src ./.venv/bin/python scripts/research/compare_macro_trend_continuation.py --output <新目录>`", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--download-minutes", action="store_true", help="Only missing public 17-minute capacity windows.")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output; previous evidence is retained")
    old_bundle, new_bundle, sources, revisions = extended_inputs(args.download_minutes)
    control_path = RUNS/"macro_risk_candidate_20261020/with_policy_parity.json"
    retained = json.loads(control_path.read_text())["results"]
    venue_path = RUNS/"macro_leverage_cash_review_20261019/venue_snapshot.json"
    venue = json.loads(venue_path.read_text())
    for book, *_ in (old_bundle, new_bundle):
        for symbol, data in book.items():
            data["rule"] = dict(data["rule"], leverage_brackets=venue["symbols"][symbol]["brackets"])
    original_review = model.review_lease
    portfolios, checks, old_controls, count = [], [], {}, 0
    for window, bundle in (("old", old_bundle), ("extended", new_bundle)):
        book, signals, gates, caps = bundle
        for scenario, fee, slip, shock in (("base", .0005, .0025, 0), ("double_cost", .001, .005, 0), ("exit50bp", .0005, .0025, .005)):
            if window == "old" and shock:
                continue
            p = copy.deepcopy(retained["risk25_all_base"]["parameters"])
            p.pop("omission")
            p.pop("extra_exit_slip")
            p.update(fee=fee, slip=slip)
            data = cost_case(book, scenario)
            for name in PROFILES:
                pp = profile_parameters(p, name)
                with patch.object(model, "review_lease", review_profitable_trend if name == "profitable_trend_roll21" else original_review):
                    result = model.replay(data, signals, entry_confirmations=gates, entry_liquidity_caps=caps,
                        exit_execution_model=DepthExitStress({}, use_depth=False, all_extra_slip=shock) if shock else None, **pp)
                verify(result, data, pp)
                count += 1
                for t in result["trades"]:
                    for review in t.get("funding_lease_reviews", []):
                        assert review["time"] < t["entry_time"]+t["max_hold_hours"]*3600
                        assert review["funding_cost_cap"] == t["funding_cost_cap_usdt"]
                        if review["allowed"]:
                            assert review["stress_risk"] <= review["risk_budget"]+1e-8
                            assert review["cumulative_cost_with_reserve"] <= t["funding_cost_cap_usdt"]+1e-8
                if window == "old" and name == "control":
                    old = retained[f"risk25_all_{scenario}"]
                    assert result["trades"] == old["trades"] and result["curve"] == old["curve"]
                    checks.append(scenario+": exact retained old control")
                    old_controls[scenario] = result
                if window == "extended" and name == "control" and not shock:
                    old_curve = old_controls[scenario]["curve"]
                    assert result["curve"][:len(old_curve)-1] == old_curve[:-1]
                    checks.append(scenario+": old NAV prefix unchanged before terminal forced valuation")
                row = dict(window=window, profile=name, scenario=scenario, parameters=pp,
                    headline=headline(result), trades=result["trades"], curve=result["curve"])
                portfolios.append(row)
                print(window, name, scenario, json.dumps(row["headline"]), flush=True)
    for path in (control_path, venue_path):
        sources.append(dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    unique = {s["path"]: s for s in sources}
    for source in unique.values():
        assert hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest() == source["sha256"]
    output = dict(research_only=True, orders_authorized=False, independent_oos=False,
        hypothesis="A seven-day trend position may continue after causal rolling funding/risk reviews; compare requiring known net profit. First resolve old terminal valuation using actual later prices.",
        sample_start="2026-04-07", old_end_exclusive="2026-10-15", end_exclusive="2026-10-22",
        initial_capital=retained["risk25_all_base"]["parameters"]["capital"],
        replay_count=count, checks=checks, overlap_adjusted_price_revisions=revisions,
        sources=list(unique.values()), old_censored_trade=retained["risk25_all_base"]["trades"][-1], portfolios=portfolios,
        code=[dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in
            (Path(__file__), Path("src/qount/research/macro_trend_lease.py"), Path("src/qount/research/binance_etf_leverage.py"))])
    args.output.mkdir(parents=True)
    (args.output/"comparison.json").write_text(json.dumps(output, ensure_ascii=False, allow_nan=False)+"\n")
    (args.output/"report.md").write_text(write_report(output))
    print("saved", args.output, "replays", count, flush=True)


if __name__ == "__main__":
    main()
