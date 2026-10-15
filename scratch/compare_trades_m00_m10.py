from verify_mechanism_reality import run_parametric

m00 = run_parametric(adaptive_tier=False, edge_decay=False)
m10 = run_parametric(adaptive_tier=True, edge_decay=False)

print(f"Case 0 (Base): Ret={m00['return_pct']:+.2f}%, MDD={m00['mdd_pct']:.2f}%, Final Eq={m00['curve'][-1][1]:.2f}")
print(f"Case 1 (Tier): Ret={m10['return_pct']:+.2f}%, MDD={m10['mdd_pct']:.2f}%, Final Eq={m10['curve'][-1][1]:.2f}")

tot_pnl_0 = sum(t["net_pnl_usd"] for t in m00["trades"])
tot_pnl_1 = sum(t["net_pnl_usd"] for t in m10["trades"])
print(f"Sum of closed trade PnL Case 0: ${tot_pnl_0:+.2f}")
print(f"Sum of closed trade PnL Case 1: ${tot_pnl_1:+.2f}")

# Look at 2021 specifically
pnl_2021_0 = sum(t["net_pnl_usd"] for t in m00["trades"] if t["entry_date"].startswith("2021"))
pnl_2021_1 = sum(t["net_pnl_usd"] for t in m10["trades"] if t["entry_date"].startswith("2021"))
print(f"2021 Closed PnL Case 0: ${pnl_2021_0:+.2f}")
print(f"2021 Closed PnL Case 1: ${pnl_2021_1:+.2f}")

# Look at 2024 specifically
pnl_2024_0 = sum(t["net_pnl_usd"] for t in m00["trades"] if t["entry_date"].startswith("2024"))
pnl_2024_1 = sum(t["net_pnl_usd"] for t in m10["trades"] if t["entry_date"].startswith("2024"))
print(f"2024 Closed PnL Case 0: ${pnl_2024_0:+.2f}")
print(f"2024 Closed PnL Case 1: ${pnl_2024_1:+.2f}")

