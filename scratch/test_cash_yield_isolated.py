from scratch.develop_v17_improvements import run_v17_backtest, print_yearly

print("=== Case 1: v1.6 + Historical Cash Yield Alone ===")
r_c1 = run_v17_backtest(mode="1X_SPOT", enable_cash_overlay=True, macro_mr_filter=False, pullback_boost=False)
print(f"Return: {r_c1['return_pct']:+.2f}%, CAGR: {r_c1['cagr']:.2f}%, MDD: {r_c1['mdd_pct']:.2f}%, Calmar: {r_c1['calmar']:.2f}, WR: {r_c1['win_rate']:.1f}%")
print(f"Total Cash Yield: ${r_c1['total_cash_interest']:.2f}")
print_yearly(r_c1["curve"], r_c1["trades"])

print("\n=== Case 2: v1.6 + Flat 4% Cash Yield Alone (SGOV/Money Market) ===")
r_c2 = run_v17_backtest(mode="1X_SPOT", enable_cash_overlay=True, cash_rate_mode="flat_4pct", macro_mr_filter=False, pullback_boost=False)
print(f"Return: {r_c2['return_pct']:+.2f}%, CAGR: {r_c2['cagr']:.2f}%, MDD: {r_c2['mdd_pct']:.2f}%, Calmar: {r_c2['calmar']:.2f}, WR: {r_c2['win_rate']:.1f}%")
print(f"Total Cash Yield: ${r_c2['total_cash_interest']:.2f}")
print_yearly(r_c2["curve"], r_c2["trades"])

print("\n=== Case 3: TradFi 2X + Historical Cash Yield ===")
r_c3 = run_v17_backtest(mode="TRADIFI_MARGIN_2X", enable_cash_overlay=True, macro_mr_filter=False, pullback_boost=False)
print(f"Return: {r_c3['return_pct']:+.2f}%, CAGR: {r_c3['cagr']:.2f}%, MDD: {r_c3['mdd_pct']:.2f}%, Calmar: {r_c3['calmar']:.2f}, WR: {r_c3['win_rate']:.1f}%")
print(f"Total Cash Yield: ${r_c3['total_cash_interest']:.2f}")
print_yearly(r_c3["curve"], r_c3["trades"])

print("\n=== Case 4: TradFi 2X + Flat 4% Cash Yield ===")
r_c4 = run_v17_backtest(mode="TRADIFI_MARGIN_2X", enable_cash_overlay=True, cash_rate_mode="flat_4pct", macro_mr_filter=False, pullback_boost=False)
print(f"Return: {r_c4['return_pct']:+.2f}%, CAGR: {r_c4['cagr']:.2f}%, MDD: {r_c4['mdd_pct']:.2f}%, Calmar: {r_c4['calmar']:.2f}, WR: {r_c4['win_rate']:.1f}%")
print(f"Total Cash Yield: ${r_c4['total_cash_interest']:.2f}")
print_yearly(r_c4["curve"], r_c4["trades"])
