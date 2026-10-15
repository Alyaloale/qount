import sys
sys.path.append("scratch")
from test_dynamic_tier_limit import run_adaptive_tier_backtest

print(">>> Testing Adaptive Macro Tier + Edge Decay + 0.95% Volatility Floor:")
res = run_adaptive_tier_backtest(edge_decay_exit=True)
print(f"Adaptive (0.85% ATR): Ret={res['return_pct']:+.2f}%, MDD={res['mdd_pct']:.2f}%, Calmar={res['calmar']:.2f}")

with open("scratch/test_dynamic_tier_limit.py", "r") as f:
    code = f.read()
code_95 = code.replace("if (cur_atr / c_now) < 0.0085: continue", "if (cur_atr / c_now) < 0.0095: continue")
with open("scratch/test_dynamic_tier_limit_95.py", "w") as f:
    f.write(code_95)

from test_dynamic_tier_limit_95 import run_adaptive_tier_backtest as run_adaptive_95
res95 = run_adaptive_95(edge_decay_exit=True)
print(f"Adaptive (0.95% ATR): Ret={res95['return_pct']:+.2f}%, MDD={res95['mdd_pct']:.2f}%, Calmar={res95['calmar']:.2f}")

years = ["2020", "2021", "2022", "2023", "2024", "2025", "2026"]
print(f"\n{'Year':<6} | {'0.85% ATR':<15} | {'0.95% ATR'}")
print("-" * 40)
for y in years:
    c85 = [p[1] for p in res["curve"] if p[0].startswith(y)]
    r85 = ((c85[-1] - c85[0]) / c85[0] * 100) if c85 else 0.0
    c95 = [p[1] for p in res95["curve"] if p[0].startswith(y)]
    r95 = ((c95[-1] - c95[0]) / c95[0] * 100) if c95 else 0.0
    print(f"{y:<6} | {r85:+6.2f}%         | {r95:+6.2f}%")

