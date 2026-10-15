from verify_mechanism_reality import run_parametric

m00 = run_parametric(adaptive_tier=False, edge_decay=False)
m10 = run_parametric(adaptive_tier=True, edge_decay=False)

# Let's map trades by (entry_date, symbol)
t0_map = {(t['entry_date'], t['symbol']): t for t in m00['trades']}
t1_map = {(t['entry_date'], t['symbol']): t for t in m10['trades']}

# Trades in both
common_keys = set(t0_map.keys()) & set(t1_map.keys())
only_t0 = set(t0_map.keys()) - set(t1_map.keys())
only_t1 = set(t1_map.keys()) - set(t0_map.keys())

print(f"Common trades: {len(common_keys)}")
print(f"Trades only in Case 0: {len(only_t0)}")
print(f"Trades only in Case 1: {len(only_t1)}")

# PnL comparison
pnl_common_in_0 = sum(t0_map[k]['net_pnl_usd'] for k in common_keys)
pnl_common_in_1 = sum(t1_map[k]['net_pnl_usd'] for k in common_keys)
pnl_only_0 = sum(t0_map[k]['net_pnl_usd'] for k in only_t0)
pnl_only_1 = sum(t1_map[k]['net_pnl_usd'] for k in only_t1)

print(f"Common trades PnL in Case 0: ${pnl_common_in_0:+.2f}")
print(f"Common trades PnL in Case 1: ${pnl_common_in_1:+.2f}")
print(f"Trades only in Case 0 PnL: ${pnl_only_0:+.2f}")
print(f"Trades only in Case 1 PnL: ${pnl_only_1:+.2f}")

print("\nWhat are the trades only in Case 0?")
for k in sorted(only_t0):
    t = t0_map[k]
    print(f"  Only Case 0: {t['entry_date']} -> {t['exit_date']} | {t['symbol']} | ${t['net_pnl_usd']:+.2f} | {t['exit_reason']}")

print("\nWhat are the trades only in Case 1?")
for k in sorted(only_t1):
    t = t1_map[k]
    print(f"  Only Case 1: {t['entry_date']} -> {t['exit_date']} | {t['symbol']} | ${t['net_pnl_usd']:+.2f} | {t['exit_reason']}")

