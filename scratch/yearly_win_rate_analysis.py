from collections import defaultdict
from qount.research.universal_regime_expectancy import run_regime_backtest, ALL_10_MACRO_SYMBOLS

# 1. Run Corrected v1.6 (with Edge Decay)
res_v16 = run_regime_backtest(edge_decay_exit=True)

# 2. Run Baseline v1.5 (without Edge Decay)
res_v15 = run_regime_backtest(edge_decay_exit=False)

years = ["2020", "2021", "2022", "2023", "2024", "2025", "2026"]

print("=" * 110)
print("QOUNT 通用状态策略：逐年深度胜率与盈亏特征穿透分析 (2020–2026)")
print("=" * 110)

def analyze_year(trades, curve, year_str):
    y_trades = [t for t in trades if t["entry_date"].startswith(year_str)]
    tc = len(y_trades)
    if tc == 0:
        return None
    wins = [t for t in y_trades if t["net_pnl_usd"] > 0]
    losses = [t for t in y_trades if t["net_pnl_usd"] <= 0]
    win_cnt = len(wins)
    loss_cnt = len(losses)
    wr = (win_cnt / tc * 100.0) if tc > 0 else 0.0
    tot_gain = sum(t["net_pnl_usd"] for t in wins)
    tot_loss = abs(sum(t["net_pnl_usd"] for t in losses))
    pf = (tot_gain / tot_loss) if tot_loss > 0 else (999.0 if tot_gain > 0 else 0.0)
    avg_win = (tot_gain / win_cnt) if win_cnt > 0 else 0.0
    avg_loss = (tot_loss / loss_cnt) if loss_cnt > 0 else 0.0
    payoff = (avg_win / avg_loss) if avg_loss > 0 else 0.0
    net_pnl = tot_gain - tot_loss

    # Curve within year
    y_points = [p for p in curve if p[0].startswith(year_str)]
    y_start = y_points[0][1]
    y_end = y_points[-1][1]
    ret = (y_end - y_start) / y_start * 100.0
    peak = y_start
    mdd = 0.0
    for d, val in y_points:
        if val > peak: peak = val
        dd = (peak - val) / peak
        if dd > mdd: mdd = dd

    # Exit reason counts
    exit_counts = defaultdict(int)
    for t in y_trades:
        exit_counts[t["exit_reason"]] += 1

    # Top symbols
    sym_pnl = defaultdict(float)
    for t in y_trades:
        sym_pnl[t["symbol"]] += t["net_pnl_usd"]

    return {
        "year": year_str, "trades": tc, "wins": win_cnt, "losses": loss_cnt,
        "win_rate": wr, "pf": pf, "avg_win": avg_win, "avg_loss": avg_loss,
        "payoff": payoff, "net_pnl": net_pnl, "return_pct": ret, "mdd_pct": mdd * 100.0,
        "exits": dict(exit_counts), "sym_pnl": dict(sym_pnl)
    }

print(f"{'年份':<6} | {'成交':<5} | {'胜/负':<7} | {'胜率 %':<7} | {'盈亏比(PF)':<10} | {'平均盈利':<9} | {'平均亏损':<9} | {'盈亏报酬比':<10} | {'净收益率':<9} | {'年内最大回撤'}")
print("-" * 110)

all_stats_v16 = []
for y in years:
    s = analyze_year(res_v16["trades"], res_v16["curve"], y)
    all_stats_v16.append(s)
    print(f"{s['year']:<6} | {s['trades']:<5} | {s['wins']}/{s['losses']:<5} | {s['win_rate']:5.1f}%  | {s['pf']:7.2f}    | ${s['avg_win']:7.2f} | ${s['avg_loss']:7.2f} | {s['payoff']:7.2f}    | {s['return_pct']:+6.2f}%   | {s['mdd_pct']:5.2f}%")

print("\n" + "=" * 110)
print("修正前后核心胜率与风控指标对照 (v1.5 Baseline vs v1.6 Corrected with Edge Decay)")
print("=" * 110)
print(f"{'年份':<6} | {'v1.5 胜率':<10} | {'v1.6 胜率':<10} | {'v1.5 盈亏比':<11} | {'v1.6 盈亏比':<11} | {'v1.5 回撤':<10} | {'v1.6 回撤':<10} | {'v1.5 收益':<10} | {'v1.6 收益'}")
print("-" * 110)

for y in years:
    s15 = analyze_year(res_v15["trades"], res_v15["curve"], y)
    s16 = analyze_year(res_v16["trades"], res_v16["curve"], y)
    print(f"{y:<6} | {s15['win_rate']:5.1f}%     | {s16['win_rate']:5.1f}%     | {s15['pf']:6.2f}      | {s16['pf']:6.2f}      | {s15['mdd_pct']:5.2f}%    | {s16['mdd_pct']:5.2f}%    | {s15['return_pct']:+6.2f}%    | {s16['return_pct']:+6.2f}%")

print("\n" + "=" * 110)
print("各年度离场成因分布与标的造血/失血穿透 (v1.6 Corrected)")
print("=" * 110)

for s in all_stats_v16:
    exits_str = ", ".join(f"{k}:{v}" for k, v in sorted(s["exits"].items(), key=lambda x: x[1], reverse=True))
    best_sym = max(s["sym_pnl"].items(), key=lambda x: x[1])
    worst_sym = min(s["sym_pnl"].items(), key=lambda x: x[1])
    print(f"【{s['year']}年】 收益: {s['return_pct']:+6.2f}%, 回撤: {s['mdd_pct']:5.2f}%, 胜率: {s['win_rate']:5.1f}%, 盈亏比: {s['pf']:.2f}")
    print(f"   ↳ 离场分布: {exits_str}")
    print(f"   ↳ 最佳标的: {best_sym[0]} (${best_sym[1]:+.2f}) | 最差标的: {worst_sym[0]} (${worst_sym[1]:+.2f})")

