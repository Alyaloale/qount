from verify_mechanism_reality import run_parametric

m10 = run_parametric(adaptive_tier=True, edge_decay=False)
unlocked_m10 = [t for t in m10["trades"] if t.get("unlocked_by_2nd_eq")]
print(f"Unlocked trades in Case 1: {len(unlocked_m10)}")
tot_pnl = sum(t["net_pnl_usd"] for t in unlocked_m10)
print(f"Total PnL of unlocked trades in Case 1: ${tot_pnl:+.2f}")
for t in unlocked_m10:
    print(f"  {t['entry_date']} -> {t['exit_date']} | {t['symbol']} | ${t['net_pnl_usd']:+.2f} | {t['exit_reason']}")
