import sys
from collections import defaultdict
from qount.research.universal_regime_expectancy import run_regime_backtest, ALL_10_MACRO_SYMBOLS, load_etf_bars

res = run_regime_backtest(
    symbols=ALL_10_MACRO_SYMBOLS,
    mode="1X_SPOT",
    causality_mode="RIGOROUS",
    start_date="2020-01-01",
    end_date="2026-07-30",
    orthogonal_tier_limit=True,
)

trades = res["trades"]
yearly_trades = defaultdict(list)
for t in trades:
    y = t["entry_date"][:4]
    yearly_trades[y].append(t)

spy_bars = load_etf_bars("SPY")
spy_by_year = defaultdict(list)
for b in spy_bars:
    if "2020-01-01" <= b.d <= "2026-07-30":
        spy_by_year[b.d[:4]].append(b)

print(f"{'Year':<6} | {'SPY Ret':<8} | {'Strat Ret':<9} | {'Trades':<6} | {'Wins':<5} | {'Win%':<6} | {'Closed PnL':<11} | {'Symbols Traded'}")
print("-" * 90)

for y in sorted(spy_by_year.keys()):
    sb = spy_by_year[y]
    spy_ret = (sb[-1].c - sb[0].o) / sb[0].o * 100.0
    y_tr = yearly_trades.get(y, [])
    cnt = len(y_tr)
    wins = sum(1 for t in y_tr if t["net_pnl_usd"] > 0)
    wr = (wins / cnt * 100) if cnt > 0 else 0
    pnl = sum(t["net_pnl_usd"] for t in y_tr)
    
    y_curve = [p[1] for p in res["curve"] if p[0].startswith(y)]
    s_ret = ((y_curve[-1] - y_curve[0]) / y_curve[0] * 100) if y_curve else 0.0
    
    syms_cnt = defaultdict(int)
    for t in y_tr:
        syms_cnt[t["symbol"]] += 1
    sym_str = ", ".join(f"{s}:{c}" for s, c in sorted(syms_cnt.items()))
    
    print(f"{y:<6} | {spy_ret:+6.2f}%  | {s_ret:+6.2f}%   | {cnt:<6} | {wins:<5} | {wr:5.1f}% | ${pnl:+8.2f}  | {sym_str}")
