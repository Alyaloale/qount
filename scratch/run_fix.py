with open("scratch/test_dynamic_tier_limit.py", "r") as f:
    code = f.read()
code = code.replace("from scratch.run_architectural_experiments import run_experiment_engine\n", "")
with open("scratch/test_dynamic_tier_limit.py", "w") as f:
    f.write(code)
