import sys
sys.path.append("scratch")
from test_short_simulation import run_bidirectional_backtest

res = run_bidirectional_backtest(allow_short=True)
short_trades = [t for t in res["trades"] if t.get("direction") == "SHORT" and t["entry_date"].startswith("2022")]

print(f"{'Entry Date':<11} | {'Exit Date':<11} | {'Symbol':<5} | {'Net PnL':<10} | {'Exit Reason':<16} | {'Type':<16}")
print("-" * 80)
for t in short_trades:
    ed = t['entry_date']
    xd = t['exit_date']
    sym = t['symbol']
    pnl = t['net_pnl_usd']
    reason = t['exit_reason']
    ttype = t['type']
    print(f"{ed:<11} | {xd:<11} | {sym:<5} | ${pnl:+8.2f} | {reason:<16} | {ttype:<16}")
