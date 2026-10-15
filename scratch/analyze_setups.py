from collections import defaultdict
from qount.research.universal_regime_expectancy import run_regime_backtest

res = run_regime_backtest()
trades = res["trades"]
by_type = defaultdict(lambda: {"count": 0, "wins": 0, "pnl": 0.0, "losses": 0, "loss_pnl": 0.0, "win_pnl": 0.0})
for t in trades:
    tp = t["type"]
    p = t["net_pnl_usd"]
    by_type[tp]["count"] += 1
    by_type[tp]["pnl"] += p
    if p > 0:
        by_type[tp]["wins"] += 1
        by_type[tp]["win_pnl"] += p
    else:
        by_type[tp]["losses"] += 1
        by_type[tp]["loss_pnl"] += p

print("=" * 80)
print(f"Total return: {res['return_pct']:.2f}%, MDD: {res['mdd_pct']:.2f}%, Calmar: {res['calmar']:.2f}")
print("=" * 80)
for tp, d in by_type.items():
    wr = d["wins"] / d["count"] * 100 if d["count"] > 0 else 0
    pf = (d["win_pnl"] / abs(d["loss_pnl"])) if d["loss_pnl"] != 0 else 999
    c = d["count"]
    pnl = d["pnl"]
    print(f"{tp:25s} | Count: {c:3d} | Net PnL: ${pnl:8.2f} | WinRate: {wr:5.1f}% | PF: {pf:.2f}")
