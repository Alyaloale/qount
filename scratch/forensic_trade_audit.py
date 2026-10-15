import sys
from verify_mechanism_reality import run_parametric

m11 = run_parametric(adaptive_tier=True, edge_decay=True)
m00 = run_parametric(adaptive_tier=False, edge_decay=False)

trades_11 = m11["trades"]

# 1. Inspect Mechanism 1: Trades unlocked by the 2nd equity slot
unlocked_trades = [t for t in trades_11 if t.get("unlocked_by_2nd_eq")]
print("=" * 85)
print(f"MECHANISM 1 AUDIT: TRADES UNLOCKED BY 2ND EQUITY SLOT ({len(unlocked_trades)} trades)")
print("=" * 85)
print(f"{'Entry Date':<11} | {'Exit Date':<11} | {'Symbol':<5} | {'Net PnL ($)':<12} | {'Exit Reason':<16}")
print("-" * 75)
unlocked_pnl = 0.0
unlocked_wins = 0
for t in unlocked_trades:
    pnl = t['net_pnl_usd']
    unlocked_pnl += pnl
    if pnl > 0: unlocked_wins += 1
    print(f"{t['entry_date']:<11} | {t['exit_date']:<11} | {t['symbol']:<5} | ${pnl:+9.2f}  | {t['exit_reason']:<16}")

wr = (unlocked_wins / len(unlocked_trades) * 100) if unlocked_trades else 0
print(f"\nTotal PnL from Unlocked 2nd Equity Trades: ${unlocked_pnl:+.2f}, Win Rate: {wr:.1f}% ({unlocked_wins}/{len(unlocked_trades)})")

# 2. Inspect Mechanism 2: Trades that exited via Edge-Decay
decay_trades = [t for t in trades_11 if t.get("exit_reason") == "edge_decay_exit"]
print("\n" + "=" * 85)
print(f"MECHANISM 2 AUDIT: TRADES EXITED VIA EDGE-DECAY ({len(decay_trades)} trades)")
print("=" * 85)
print(f"{'Entry Date':<11} | {'Exit Date':<11} | {'Hold Days':<10} | {'Symbol':<5} | {'Exit PnL ($)':<12}")
print("-" * 65)
decay_pnl = 0.0
decay_wins = 0
for t in decay_trades:
    pnl = t['net_pnl_usd']
    decay_pnl += pnl
    if pnl > 0: decay_wins += 1
    print(f"{t['entry_date']:<11} | {t['exit_date']:<11} | {t['holding_days']:<10} | {t['symbol']:<5} | ${pnl:+9.2f}")

wr_d = (decay_wins / len(decay_trades) * 100) if decay_trades else 0
print(f"\nTotal PnL from Edge-Decay Exits: ${decay_pnl:+.2f}, Avg PnL: ${decay_pnl/len(decay_trades):+.2f}, Win Rate: {wr_d:.1f}%")

