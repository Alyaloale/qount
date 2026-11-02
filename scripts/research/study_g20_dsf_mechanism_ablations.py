"""G20-DSF mechanism, margin-tier and sizing ablations (research-only).

Five experiments on the g20_dual_core_slow_trend_flat line:

E1  Mechanism vs path: the identical 8-ETF pool and rules run on two disjoint
    windows, 2016-01 -> 2022-06 (pre-sample) and 2022-06 -> 2025-12 (the
    development era), pool mode, no crypto legs.
E2  Maintenance-margin tiers: the documented dual-core runs re-evaluated at
    the 0.5% proxy and a 2.5% real-tier level; does 2x/4x survival flip?
E3  Sizing ablation: fixed-quantity lots vs fraction-of-equity resizing at
    every scheduled decision, comparing MDD and gross-leverage trajectories.
E4  (implemented in replay summaries) trade counts, per-symbol concentration
    and a path_evidence flag for samples under 30 trades.
E5  Rule ablations: strict dual-core entry blocking vs relaxed fill, and the
    extra positive rank-momentum entry filter on/off.

Everything stays research_only=true / orders_authorized=false.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from qount.research.binance_macro_history import adjusted_bars
from qount.research.crypto_g20_hourly_portfolio import PortfolioRule, replay
from qount.research.crypto_g20_hourly_swing import features
from qount.strategies.macro_1atr import SIGNAL_MAPPING


ETF_ROOT = Path("state/research_cache/binance_macro_etf_history_20261015")
ETFS = tuple(SIGNAL_MAPPING)
BARRIER = int(datetime(2022, 6, 28, 20, 0, tzinfo=timezone.utc).timestamp())
CAPITAL = 21.25
COST_BP = 10.0
DAILY_RULE = dict(rank_hours=7, trend_hours=63, mean_hours=120, decision_hours=1)


def source(path):
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def build_etf_panel():
    """Eight adjusted Yahoo ETF proxies, full shared history, zero funding."""
    etf_bars, sources = {}, []
    for symbol, ticker in SIGNAL_MAPPING.items():
        path = ETF_ROOT / f"yahoo-{ticker}-20160101-2026-01-01.json"
        etf_bars[symbol] = adjusted_bars(json.loads(path.read_text()))
        sources.append(source(path))
    common = sorted(set.intersection(*(set(b.t for b in bars) for bars in etf_bars.values())))
    if len(common) < 2000:
        raise ValueError("insufficient_etf_history")
    times = np.asarray(common, dtype=np.int64)
    n, m = len(times), len(ETFS)
    arrays = {k: np.zeros((n, m), dtype=float) for k in ("open", "high", "low", "close", "mark_low")}
    by_etf = {s: {b.t: b for b in etf_bars[s]} for s in ETFS}
    for j, symbol in enumerate(ETFS):
        for i, t in enumerate(times):
            b = by_etf[symbol][int(t)]
            arrays["open"][i, j], arrays["high"][i, j] = b.o, b.h
            arrays["low"][i, j], arrays["close"][i, j] = b.l, b.c
            arrays["mark_low"][i, j] = b.l
        # Include the next session open in the conservative intrabar mark-low.
        arrays["mark_low"][:-1, j] = np.minimum(arrays["low"][:-1, j], arrays["open"][1:, j])
    panel = dict(symbols=ETFS, times=times, open=arrays["open"], high=arrays["high"],
                 low=arrays["low"], close=arrays["close"], mark_low=arrays["mark_low"],
                 funding_value=np.zeros((n - 1, m), dtype=float),
                 funding_debit=np.zeros((n - 1, m), dtype=float),
                 periods_per_year=252.0)
    return panel, sources


def build_full_panel():
    spec = importlib.util.spec_from_file_location(
        "base_daily_study", REPO_ROOT / "scripts/research/study_crypto_g20_daily_original_etf.py")
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    return base.build_panel()


def equal_weight_baseline(panel, left, right, capital=CAPITAL, cost_bp=COST_BP):
    """Static equal-weight buy-and-hold of the whole pool, marked at opens."""
    opens = panel["open"][left:right + 1]
    shares = (capital * (1 - cost_bp / 10000.0) / opens.shape[1]) / opens[0]
    nav = (opens * shares).sum(axis=1) / capital
    mdd = float(np.max(1 - nav / np.maximum.accumulate(nav)))
    years = (int(panel["times"][right]) - int(panel["times"][left])) / (365.25 * 86400)
    final = float(nav[-1])
    cagr = final ** (1 / years) - 1 if final > 0 else -1.0
    return dict(final_usdt=round(final * capital, 4), return_pct=round((final - 1) * 100, 2),
                cagr_pct=round(cagr * 100, 2), mdd_pct=round(mdd * 100, 2),
                trades=1, symbols_traded=int(opens.shape[1]))


def run_cells(panel, cells, capital=CAPITAL):
    results, cache = {}, {}
    for key, rule_kwargs, maintenance, start, end in cells:
        rule = PortfolioRule(**{**DAILY_RULE, **rule_kwargs})
        cache_key = (rule.rank_hours, rule.trend_hours, rule.mean_hours)
        if cache_key not in cache:
            cache[cache_key] = features(panel, rule)
        run = replay(panel, cache[cache_key], rule, start=start, end=end,
                     capital=capital, cost_bp=COST_BP, filters=None,
                     maintenance=maintenance, variable_clock=True)
        results[key] = dict(rule=asdict(rule), maintenance=maintenance,
                            cost_bp=COST_BP, summary=run["summary"])
    return results


def fmt(row):
    s = row["summary"]
    liq = s["counts"].get("shared_liquidation", 0)
    top1 = s["top1_positive_pnl_share"]
    return (f"  final={s['final_usdt']:>9.2f}  cagr={s['cagr_pct']:>8.2f}%  "
            f"mdd={s['mdd_pct']:>6.2f}%  bound={s['intraday_drawdown_bound_pct']:>6.2f}%  "
            f"gross(max/mean)={s['max_actual_gross']:.2f}/{s['mean_actual_gross']:.2f}  "
            f"trades={s['trades']:>2}  syms={s['symbols_traded']}  "
            f"top1={'n/a' if top1 is None else f'{top1:.2f}'}  liq={liq}  "
            f"path_evidence={s['path_evidence']}")


def table_rows(results):
    rows = []
    for key, row in results.items():
        s = row["summary"]
        rows.append([key, round(s["final_usdt"], 2), round(s["cagr_pct"], 2),
                     round(s["mdd_pct"], 2), round(s["intraday_drawdown_bound_pct"], 2),
                     round(s["max_actual_gross"], 2), round(s["mean_actual_gross"], 2),
                     s["trades"], s["symbols_traded"],
                     None if s["top1_positive_pnl_share"] is None else round(s["top1_positive_pnl_share"], 2),
                     s["counts"].get("shared_liquidation", 0), s["path_evidence"]])
    return rows


def markdown_table(header, rows):
    lines = ["| " + " | ".join(header) + " |",
             "| " + " | ".join(["---"] * len(header)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join("—" if v is None else str(v) for v in row) + " |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=Path("state/research_runs/g20_dsf_mechanism_ablation_20261102"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    payload = dict(research_only=True, orders_authorized=False,
                   experiments={}, sources={}, notes=[])
    report = ["# G20-DSF 机制、保证金档位与仓位消融", "",
              "> research_only=true · orders_authorized=false · 2026-11-02",
              "> 口径：初始 21.25U，单边 10bp，t=收盘信号、t+1 开盘执行；E1 为 8 个 Yahoo ETF 代理、零资金费。",
              "> trades/symbols/top1/path_evidence 由 replay summary 自动携带（E4 约定：trades<30 一律 path_evidence=true）。", ""]

    # ---- E1: mechanism vs path on two disjoint windows, ETF-only pool ----
    etf_panel, etf_sources = build_etf_panel()
    payload["sources"]["etf_panel"] = etf_sources
    left_a = 121
    right_a = int(np.searchsorted(etf_panel["times"], BARRIER, side="left"))
    left_b = right_a
    right_b = len(etf_panel["times"]) - 1
    e1_cells = []
    for tag, start, end in (("pre", etf_panel["times"][left_a], etf_panel["times"][right_a]),
                            ("era", etf_panel["times"][left_b], etf_panel["times"][right_b])):
        for name, kwargs in (
                ("pool_2slots_2x_dual", dict(max_positions=2, position_gross=1.0, core_mode="pool")),
                ("pool_2slots_1x_dual", dict(max_positions=2, position_gross=0.5, core_mode="pool")),
                ("pool_3slots_2x_dual", dict(max_positions=3, position_gross=2.0 / 3, core_mode="pool")),
                ("pool_2slots_2x_either", dict(max_positions=2, position_gross=1.0, core_mode="pool",
                                               exit_mode="either")),
        ):
            e1_cells.append((f"{name}_{tag}", kwargs, 0.005, start, end))
    e1 = run_cells(etf_panel, e1_cells)
    payload["experiments"]["e1_etf_only_two_windows"] = e1
    payload["experiments"]["e1_baselines"] = {
        "equal_weight_8etf_1x_pre": equal_weight_baseline(etf_panel, left_a, right_a),
        "equal_weight_8etf_1x_era": equal_weight_baseline(etf_panel, left_b, right_b),
    }
    report += ["## E1 机制 vs 路径：同池同规则，2016→2022-06 与 2022-06→2025-12 对照",
               "",
               f"窗口 pre: {datetime.fromtimestamp(int(etf_panel['times'][left_a]), timezone.utc).date()}"
               f" → {datetime.fromtimestamp(int(etf_panel['times'][right_a]), timezone.utc).date()}；"
               f"窗口 era: {datetime.fromtimestamp(int(etf_panel['times'][left_b]), timezone.utc).date()}"
               f" → {datetime.fromtimestamp(int(etf_panel['times'][right_b]), timezone.utc).date()}。",
               "",
               markdown_table(["run", "final", "CAGR%", "MDD%", "bound%", "gross_max", "gross_mean",
                               "trades", "syms", "top1", "liq", "path_ev"],
                              table_rows(e1)),
               "",
               "静态等权 8-ETF 买入持有对照（总 1x）：pre = "
               f"{payload['experiments']['e1_baselines']['equal_weight_8etf_1x_pre']}，era = "
               f"{payload['experiments']['e1_baselines']['equal_weight_8etf_1x_era']}。", ""]

    # ---- E2/E3: maintenance tiers x sizing modes on the full panel ----
    full_panel, full_sources = build_full_panel()
    payload["sources"]["full_panel"] = full_sources
    start = int(full_panel["times"][121])
    end = int(full_panel["times"][-1])
    grid_cells = []
    for mode in ("fixed", "fraction"):
        for total in (1.0, 2.0, 4.0, 6.0):
            for mm in (0.005, 0.025):
                grid_cells.append((
                    f"dual_2slots_{total:g}x_{mode}_mm{mm * 100:g}pct",
                    dict(max_positions=2, position_gross=total / 2, core_mode="dual",
                         exit_mode="dual", position_mode=mode),
                    mm, start, end))
    grid = run_cells(full_panel, grid_cells)
    payload["experiments"]["e2_e3_margin_sizing_grid"] = grid

    e2 = {k: grid[k] for k in grid if "_fixed_" in k}
    e3 = {k: grid[k] for k in grid if "_fraction_" in k}
    report += ["## E2 保证金档位：0.5% 代理 vs 2.5% 真实档（固定数量，双核心 2 仓）",
               "",
               markdown_table(["run", "final", "CAGR%", "MDD%", "bound%", "gross_max", "gross_mean",
                               "trades", "syms", "top1", "liq", "path_ev"],
                              table_rows(e2)),
               "",
               "## E3 仓位消融：固定数量 vs 每决策点按权益重置（双核心 2 仓）",
               "",
               markdown_table(["run", "final", "CAGR%", "MDD%", "bound%", "gross_max", "gross_mean",
                               "trades", "syms", "top1", "liq", "path_ev"],
                              table_rows(e3)),
               ""]

    # ---- E5: core blocking and rank-momentum filter ablations ----
    e5_cells = []
    for total in (1.0, 2.0):
        e5_cells.append((f"dual_2slots_{total:g}x_relaxed_core",
                         dict(max_positions=2, position_gross=total / 2, core_mode="dual_relaxed"),
                         0.005, start, end))
        e5_cells.append((f"dual_2slots_{total:g}x_no_rank_filter",
                         dict(max_positions=2, position_gross=total / 2, core_mode="dual",
                              require_rank_positive=False),
                         0.005, start, end))
    e5 = run_cells(full_panel, e5_cells)
    e5["baseline_dual_2x_rank_filter"] = grid["dual_2slots_2x_fixed_mm0.5pct"]
    e5["baseline_dual_1x_rank_filter"] = grid["dual_2slots_1x_fixed_mm0.5pct"]
    payload["experiments"]["e5_rule_ablations"] = e5
    report += ["## E5 规则消融：双核心封仓 与 rank>0 入场过滤（基线与 E2 的 fixed/mm0.5% 共用）",
               "",
               markdown_table(["run", "final", "CAGR%", "MDD%", "bound%", "gross_max", "gross_mean",
                               "trades", "syms", "top1", "liq", "path_ev"],
                              table_rows(e5)),
               ""]

    # ---- baseline reproduction against the archived study ----
    archived = json.loads((Path("state/research_runs/crypto_g20_daily_original_etf_20261102")
                           / "results.json").read_text())["results"]["dual_2slots_2x_10bp"]["summary"]
    repro = grid["dual_2slots_2x_fixed_mm0.5pct"]["summary"]
    checks = {
        "final_usdt": (repro["final_usdt"], archived["final_usdt"]),
        "mdd_pct": (repro["mdd_pct"], archived["mdd_pct"]),
        "cagr_pct": (repro["cagr_pct"], archived["cagr_pct"]),
        "trades": (repro["trades"], archived["counts"].get("entry", 0)),
    }
    repro_ok = all(abs(a - b) < 1e-6 for a, b in checks.values())
    payload["baseline_reproduction"] = dict(checks={k: dict(new=a, archived=b)
                                                   for k, (a, b) in checks.items()},
                                            match=bool(repro_ok))
    report += ["## 基线复现校验（对照归档 crypto_g20_daily_original_etf_20261102）",
               "",
               f"- 复现一致: **{repro_ok}**（equity 路径不变；单位修正只影响持仓时长字段）",
               ""] + [f"- {k}: new={a} archived={b}" for k, (a, b) in checks.items()] + [""]

    payload["notes"] = [
        "E1 uses adjusted Yahoo daily proxies with fractional quantities and zero funding; "
        "it tests the ranking/trend-exit mechanism, not Binance ETF-perp execution.",
        "Parameter history for (7, 63, 120) is unknown; the pre-2022 window is disjoint from "
        "the development-era results but is not a certified holdout.",
        "Maintenance 2.5% is a flat proxy for one real leverage tier, not a full tier table.",
        "Fraction mode resizes at scheduled decisions only; intrabar gross can still drift.",
    ]

    (args.output / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False, default=str) + "\n")
    (args.output / "report.md").write_text("\n".join(report) + "\n")
    print("baseline reproduction match:", repro_ok)
    for section in ("e1_etf_only_two_windows", "e2_e3_margin_sizing_grid", "e5_rule_ablations"):
        print("==", section)
        for key, row in payload["experiments"][section].items():
            print(key, fmt(row))


if __name__ == "__main__":
    main()
