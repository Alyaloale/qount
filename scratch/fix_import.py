with open("scratch/verify_mechanism_reality.py", "r") as f:
    lines = f.readlines()
lines = [l for l in lines if "run_adaptive_tier_backtest" not in l]
with open("scratch/verify_mechanism_reality.py", "w") as f:
    f.writelines(lines)
