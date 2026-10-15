import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from run_full_cycle_optimizations import run_diagnostic_experiment

print(f"{'Config':<35} | {'Full Return':<12} | {'Full MDD':<10} | {'Full Calmar':<12} | {'2025-26 Ret':<12} | {'2025-26 MDD':<12}")
print("-" * 100)
for days in [25, 30, 35, None]:
    for mode in ["PRICE_AND_CROSS", "PRICE_ONLY"]:
        f = run_diagnostic_experiment(start_date="2020-01-01", end_date="2026-07-30", macro_bear_mode=mode, stagnant_exit_days=days)
        r = run_diagnostic_experiment(start_date="2025-01-01", end_date="2026-07-30", macro_bear_mode=mode, stagnant_exit_days=days)
        desc = f"{mode} | {days or 45}d"
        print(f"{desc:<35} | {f['return_pct']:>+10.2f}% | {f['mdd_pct']:>8.2f}% | {f['calmar']:>10.2f} | {r['return_pct']:>+10.2f}% | {r['mdd_pct']:>10.2f}%")
