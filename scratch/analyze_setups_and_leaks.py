import sys
from collections import defaultdict
from qount.research.universal_regime_expectancy import (
    run_regime_backtest,
    ALL_10_MACRO_SYMBOLS,
)

res = run_regime_backtest(
    symbols=ALL_10_MACRO_SYMBOLS,
    mode="1X_SPOT",
    causality_mode="RIGOROUS",
    start_date="2020-01-01",
    end_date="2026-07-30",
    orthogonal_tier_limit=True,
)

trades = res["trades"]

print("--- XLU Trades Detail ---")
for t in trades:
    if t["symbol"] == "XLU":
        print(f"{t['entry_date']} -> {t['exit_date']} | {t['type']:<22} | PnL: ${t['net_pnl_usd']:>6.2f} | Reason: {t['exit_reason']}")

print("\n--- Trades by Setup Type ---")
setup_pnl = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0, "losses": 0, "win_pnl": 0.0, "loss_pnl": 0.0})
for t in trades:
    base_type = t["type"].replace("_TP50", "")
    setup_pnl[base_type]["count"] += 1
    setup_pnl[base_type]["pnl"] += t["net_pnl_usd"]
    if t["net_pnl_usd"] > 0:
        setup_pnl[base_type]["wins"] += 1
        setup_pnl[base_type]["win_pnl"] += t["net_pnl_usd"]
    else:
        setup_pnl[base_type]["losses"] += 1
        setup_pnl[base_type]["loss_pnl"] += abs(t["net_pnl_usd"])

for st, d in setup_pnl.items():
    wr = d["wins"] / d["count"] * 100 if d["count"] else 0
    pf = d["win_pnl"] / d["loss_pnl"] if d["loss_pnl"] > 0 else 999
    print(f"{st:<16}: PnL = ${d['pnl']:>7.2f}, Trades = {d['count']:>2}, WinRate = {wr:>5.1f}%, PF = {pf:4.2f}")

print("\n--- Trades by Symbol and Setup Type ---")
sym_setup = defaultdict(lambda: defaultdict(float))
for t in trades:
    base_type = t["type"].replace("_TP50", "")
    sym_setup[t["symbol"]][base_type] += t["net_pnl_usd"]

for sym in sorted(sym_setup.keys()):
    p_dict = sym_setup[sym]
    parts = [f"{k}: ${v:+.2f}" for k, v in p_dict.items()]
    print(f"{sym:<5}: " + ", ".join(parts))
