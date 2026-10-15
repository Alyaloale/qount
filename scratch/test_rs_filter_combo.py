import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from run_full_cycle_optimizations import run_diagnostic_experiment

print("Testing RS filters combined with 30d stagnant exit...")
for rs in [None, -0.05, -0.03, 0.0]:
    f = run_diagnostic_experiment(start_date="2020-01-01", end_date="2026-07-30", stagnant_exit_days=30, min_rs60=rs)
    r = run_diagnostic_experiment(start_date="2025-01-01", end_date="2026-07-30", stagnant_exit_days=30, min_rs60=rs)
    lbl = f"min_rs60 = {rs}" if rs is not None else "No min_rs"
    print(f"{lbl:<20} | Full: {f['return_pct']:>+6.2f}% (MDD {f['mdd_pct']:5.2f}%, Calmar {f['calmar']:4.2f}, Tr {f['trade_count']:<3}) | 2025-26: {r['return_pct']:>+6.2f}% (MDD {r['mdd_pct']:5.2f}%, Calmar {r['calmar']:4.2f})")
