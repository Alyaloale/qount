from verify_mechanism_reality import run_parametric

m00 = run_parametric(adaptive_tier=False, edge_decay=False) # Base
m01 = run_parametric(adaptive_tier=False, edge_decay=True)  # Edge Decay Only

t0_list = m00["trades"]
t1_list = m01["trades"]

# Find trades that entered on the same date and symbol
t0_by_entry = {(t["entry_date"], t["symbol"]): t for t in t0_list}
t1_by_entry = {(t["entry_date"], t["symbol"]): t for t in t1_list}

decay_trades = [t for t in t1_list if t["exit_reason"] == "edge_decay_exit"]

print("=" * 95)
print(f"COUNTERFACTUAL AUDIT: EDGE DECAY EXITS ({len(decay_trades)} trades)")
print("Did early edge-decay exit save money or cut profits short?")
print("=" * 95)
print(f"{'Entry Date':<11} | {'Symbol':<5} | {'Decay Exit Date':<15} | {'Decay PnL':<11} | {'Base Exit Date':<15} | {'Base PnL':<11} | {'PnL Saved ($)':<12}")
print("-" * 95)

total_saved = 0.0
for t in decay_trades:
    key = (t["entry_date"], t["symbol"])
    decay_pnl = t["net_pnl_usd"]
    decay_exit = t["exit_date"]
    
    if key in t0_by_entry:
        base_t = t0_by_entry[key]
        base_pnl = base_t["net_pnl_usd"]
        base_exit = f"{base_t['exit_date']} ({base_t['exit_reason']})"
        saved = decay_pnl - base_pnl
        total_saved += saved
        print(f"{t['entry_date']:<11} | {t['symbol']:<5} | {decay_exit:<15} | ${decay_pnl:+9.2f} | {base_exit:<25} | ${base_pnl:+9.2f} | ${saved:+10.2f}")
    else:
        print(f"{t['entry_date']:<11} | {t['symbol']:<5} | {decay_exit:<15} | ${decay_pnl:+9.2f} | {'[NOT IN BASE]':<25} | {'N/A':<11} | {'N/A':<12}")

print("-" * 95)
print(f"Total Net PnL Difference across matched trades: ${total_saved:+.2f}")

