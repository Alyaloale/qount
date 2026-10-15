import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from run_full_cycle_optimizations import run_diagnostic_experiment

res = run_diagnostic_experiment(
    start_date="2020-01-01",
    end_date="2026-07-30",
    stagnant_exit_days=30,
    min_rs60=-0.03,
)

curve = dict(res['curve'])
dates = sorted(list(curve.keys()))

years = ['2020', '2021', '2022', '2023', '2024', '2025', '2026']
prev_end_nav = 1000.0

print(f"{'Year':<6} | {'Start NAV':<9} | {'End NAV':<9} | {'Year Return':<11} | {'Within-Year MDD':<15}")
print('-' * 60)
for y in years:
    y_dates = [d for d in dates if d.startswith(y)]
    if not y_dates: continue
    start_nav = prev_end_nav
    end_nav = curve[y_dates[-1]]
    ret = (end_nav / start_nav - 1.0) * 100.0
    
    peak = start_nav
    mdd = 0.0
    for d in y_dates:
        v = curve[d]
        if v > peak: peak = v
        dd = (peak - v) / peak
        if dd > mdd: mdd = dd
    print(f"{y:<6} | ${start_nav:>8.2f} | ${end_nav:>8.2f} | {ret:>+10.2f}% | {mdd*100:>14.2f}%")
    prev_end_nav = end_nav

print(f"\nOverall Return: {res['return_pct']:+.2f}%, MDD: {res['mdd_pct']:.2f}%, Calmar: {res['calmar']:.2f}, Trades: {res['trade_count']}")
