import sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from run_experiments import run_custom_backtest

res_base = run_custom_backtest(mr_require_green_candle=False)
res_opt = run_custom_backtest(mr_require_green_candle=True)

trades_base = res_base["trades"]
trades_opt = res_opt["trades"]

print(f"Base Trades: {len(trades_base)}, Return: {res_base['return_pct']:+.2f}%, MDD: {res_base['mdd_pct']:.2f}%")
print(f"Opt Trades:  {len(trades_opt)}, Return: {res_opt['return_pct']:+.2f}%, MDD: {res_opt['mdd_pct']:.2f}%")

# Attribution by symbol for Opt
sym_data = defaultdict(lambda: {"count": 0, "wins": 0, "pnl": 0.0})
for t in trades_opt:
    s = t["symbol"]
    sym_data[s]["count"] += 1
    sym_data[s]["pnl"] += t["net_pnl_usd"]
    if t["net_pnl_usd"] > 0:
        sym_data[s]["wins"] += 1

print("\n--- Opt Symbol Attribution ---")
for s in sorted(sym_data.keys(), key=lambda x: sym_data[x]["pnl"], reverse=True):
    d = sym_data[s]
    wr = d["wins"] / d["count"] * 100 if d["count"] else 0
    print(f"{s:<6}: PnL = ${d['pnl']:>7.2f}, Trades = {d['count']:>2}, WinRate = {wr:>5.1f}%")

# Attribution by setup type for Opt
setup_pnl = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0, "losses": 0, "win_pnl": 0.0, "loss_pnl": 0.0})
for t in trades_opt:
    base_type = t["type"].replace("_TP50", "")
    setup_pnl[base_type]["count"] += 1
    setup_pnl[base_type]["pnl"] += t["net_pnl_usd"]
    if t["net_pnl_usd"] > 0:
        setup_pnl[base_type]["wins"] += 1
        setup_pnl[base_type]["win_pnl"] += t["net_pnl_usd"]
    else:
        setup_pnl[base_type]["losses"] += 1
        setup_pnl[base_type]["loss_pnl"] += abs(t["net_pnl_usd"])

print("\n--- Opt Setup Breakdown ---")
for st, d in setup_pnl.items():
    wr = d["wins"] / d["count"] * 100 if d["count"] else 0
    pf = d["win_pnl"] / d["loss_pnl"] if d["loss_pnl"] > 0 else 999
    print(f"{st:<16}: PnL = ${d['pnl']:>7.2f}, Trades = {d['count']:>2}, WinRate = {wr:>5.1f}%, PF = {pf:4.2f}")

# Check Annual returns for Opt
print("\n--- Opt Annual Breakdown ---")

# let's calculate annual slices
years = ["2020", "2021", "2022", "2023", "2024", "2025-2026"]
for yr in years:
    s_d = f"{yr}-01-01" if "-" not in yr else "2025-01-01"
    e_d = f"{yr}-12-31" if "-" not in yr else "2026-07-30"
    r_yr = run_custom_backtest(
        start_date=s_d,
        end_date=e_d,
        mr_require_green_candle=True,
    )
    print(f"{yr:<9}: Ret = {r_yr['return_pct']:>+6.2f}%, MDD = {r_yr['mdd_pct']:>5.2f}%, Win = {r_yr['win_rate']:>5.1f}%, Trades = {r_yr['trade_count']:>2}")
