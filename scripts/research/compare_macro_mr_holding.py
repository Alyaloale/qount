"""Test MR repair time on native contracts, retaining original cost and risk gates."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from qount.research.binance_etf_leverage import replay
from qount.research.binance_macro_opportunities import cost_case
from qount.research.macro_depth_execution import DepthExitStress
from continue_macro_fixed_candidates import CASES, append_inputs
from study_macro_admission_and_simplicity import headline, verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("retain previous evidence; choose a new output")
    prior_path = Path("state/research_runs/macro_fixed_candidates_20261026_reviewed/comparison.json")
    prior = json.loads(prior_path.read_text())
    (book, signals, gates, caps), sources, _ = append_inputs("2026-10-26", False)
    held = {s: [dict(f, hold_structural=True) for f in fs] for s, fs in signals.items()}
    portfolios, controls = [], []
    for capital in (prior["parameters"]["capital"], 30., 100.):
        for case, fee, slip, shock in CASES:
            p = dict(prior["parameters"], capital=capital, fee=fee, slip=slip)
            data = cost_case(book, case)
            for profile, fs in (("control", signals), ("mr_repair_window", held)):
                result = replay(data, fs, entry_confirmations=gates, entry_liquidity_caps=caps,
                    exit_execution_model=DepthExitStress({}, use_depth=False, unknown_extra_slip=0,
                        all_extra_slip=shock) if shock else None, **p)
                verify(result, data, p)
                if profile == "control":
                    old = next(r for r in prior["portfolios"] if r["profile"] == "control"
                        and r["capital"] == capital and r["scenario"] == case)
                    assert result["trades"] == old["trades"]
                    assert result["curve"] == old["curve"]
                    controls.append(dict(capital=capital, scenario=case, exact_reproduction=True))
                portfolios.append(dict(profile=profile, capital=capital, scenario=case,
                    headline=headline(result), trades=result["trades"], curve=result["curve"]))
                print(capital, case, profile, result["summary"]["net_return"],
                      result["summary"]["max_drawdown"], len(result["trades"]), flush=True)
    # Freeze each control entry separately: changing exits can otherwise change opportunities.
    primary = next(r for r in portfolios if r["profile"] == "control" and
        r["scenario"] == "base" and r["capital"] == prior["parameters"]["capital"])
    shadows = []
    for t in primary["trades"]:
        if t["tactical_setup"] != "mean_reversion":
            continue
        only = {k: dict(g, eligible=g["eligible"] and k == (t["symbol"], t["entry_time"]))
                for k, g in gates.items()}
        pair = {}
        for profile, fs in (("control", signals), ("mr_repair_window", held)):
            p = dict(prior["parameters"], capital=t["equity_before_entry"])
            result = replay(book, fs, entry_confirmations=only, entry_liquidity_caps=caps, **p)
            verify(result, book, p)
            assert len(result["trades"]) == 1
            pair[profile] = result["trades"][0]
            assert pair[profile]["quantity"] == t["quantity"]
        assert pair["control"] == t
        shadows.append(pair)
    for r in sources:
        assert hashlib.sha256(Path(r["path"]).read_bytes()).hexdigest() == r["sha256"]
    out = dict(research_only=True, orders_authorized=False, independent_oos=False,
        hypothesis="MR initial structural gate remains; after entry allow repair until original21-day horizon, stop/trailing/risk/funding-cash caps remain. Trend holdings unchanged.",
        sample_start="2026-04-07", sample_end_exclusive="2026-10-26", parameters=prior["parameters"],
        portfolios=portfolios, frozen_entry_shadows=shadows, control_checks=controls, sources=sources,
        replay_count=len(portfolios)+2*len(shadows),
        limitations=["No MR trend-off exit or trend eligibility veto at funding review; financial lease approval and lifetime budget remain mandatory. This is part of the treatment, not an accidental release of risk caps.",
            "Already consumed short native history; current filters/brackets applied historically, hourly stop/fill proxy. Not live profit or independent OOS."])
    args.output.mkdir(parents=True)
    (args.output/"comparison.json").write_text(json.dumps(out, ensure_ascii=False, allow_nan=False)+"\n")
    lines = ["# MR修复窗口：原生合约迁移检验", "",
        "只改变MR持仓期间的趋势资格退出和续期趋势资格：保留初始趋势/原生1ATR/不追涨/成本/容量准入；保留25%预算、2ATR止损/移动止损、资金费及现金/终身预算约束、7天复核与最长21自然日。趋势入口不改。",
        "2026-04-07至10-26（不含），8原生合约；单边5bp/25bp、真实资金费，双成本10/50bp及不利常规资金费加倍；退出冲击另列，现金0%。", "",
        "|本金|情景|规则|收益|小时MDD|闭合/总数|截尾损益|",
        "|---:|---|---|---:|---:|---:|---:|"]
    for r in portfolios:
        h = r["headline"]
        lines.append(f"|{r['capital']:.4f}|{r['scenario']}|{r['profile']}|{h['net_return']:.2%}|{h['max_drawdown']:.2%}|{h['closed_count']}/{h['trade_count']}|{h['censored_pnl']:+.6f}|")
    lines += ["", "## 同一MR入场的影子", ""]
    for pair in shadows:
        a, b = pair["control"], pair["mr_repair_window"]
        lines.append(f"- {a['symbol']} / {a['entry_time']} / 数量{a['quantity']}：原{a['exit_reason']}净损益{a['net_pnl']:+.6f}；候选{b['exit_reason']}净损益{b['net_pnl']:+.6f}；差{b['net_pnl']-a['net_pnl']:+.6f} USDT。")
    lines += ["", f"{len(controls)}组旧控制成交及曲线精确复现；{out['replay_count']}次回放逐笔核算。", ""]
    lines += ["- "+s for s in out["limitations"]]
    lines += ["", "仅离线研究，不改生产参数、配置或权限。", "",
        "复现：`PYTHONPATH=src ./.venv/bin/python scripts/research/compare_macro_mr_holding.py --output <新目录>`", ""]
    (args.output/"report.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
