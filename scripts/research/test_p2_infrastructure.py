"""Quick smoke test for P2 training infrastructure (no GPU required).

Tests that all components load and can generate/run a small synthetic episode.
research_only=true / orders_authorized=false / trial=false.
"""

import sys
from pathlib import Path

def test_imports():
    """Test that all modules can be imported."""
    print("Testing imports...")
    from qount.research.etf_trader import universe, costs, scorer, constraints
    from qount.research.etf_trader import env, features, baselines
    from qount.research.etf_trader.generator import structural, params, plausibility
    print("  ✓ Core modules")

    try:
        from qount.research.etf_trader import policy, torch_env, train
        print("  ✓ Training modules (torch)")
        return True
    except ImportError as e:
        print(f"  ⚠ Training modules not available: {e}")
        return False

def test_generator():
    """Test world generation (CPU only)."""
    print("\nTesting world generator...")
    import numpy as np
    from qount.research.etf_trader.generator.structural import simulate_world
    from qount.research.etf_trader.generator.params import sample_world
    from qount.research.etf_trader.generator.specs import ACCOUNT_SPECS

    rng = np.random.default_rng(20261001)
    params = sample_world("us", rng)
    spec = ACCOUNT_SPECS["us"]
    world = simulate_world(spec, params, years=1.0, warmup_years=0.5)

    print(f"  Generated world: {world.data.close_adj.shape[0]} days, {world.data.close_adj.shape[1]} assets")
    print(f"  Start: {world.start}, warmup: {world.warmup}")
    print(f"  ✓ World generation OK")

def test_scorer():
    """Test factor scorer."""
    print("\nTesting factor scorer...")
    import numpy as np
    from qount.research.etf_trader.scorer import score_factors
    from qount.research.etf_trader.universe import ACCOUNTS

    acct = ACCOUNTS["us"]
    n, T = acct.n_risk, 252
    rng = np.random.default_rng(20261001)

    # Synthetic data
    close_adj = np.exp(np.cumsum(rng.normal(0.0005, 0.015, (T, n)), axis=0))
    valuation = {"pe": rng.uniform(10, 25, (T, n)), "div_yield": rng.uniform(0.01, 0.04, (T, n))}

    scores = score_factors(close_adj, acct, valuation)
    print(f"  Scores shape: {scores.shape}")
    print(f"  Factor weights: M={scores.alpha[0]:.3f}, Trend={scores.alpha[1]:.3f}, Value={scores.alpha[2]:.3f}, Risk={scores.alpha[3]:.3f}")
    print(f"  ✓ Scorer OK")

def test_env():
    """Test numpy environment."""
    print("\nTesting numpy environment...")
    import numpy as np
    from qount.research.etf_trader.env import Env
    from qount.research.etf_trader.universe import ACCOUNTS
    from qount.research.etf_trader.costs import cost_params_for

    acct = ACCOUNTS["us"]
    n, T = acct.n_risk, 100
    rng = np.random.default_rng(20261001)

    # Synthetic market data
    close_adj = np.exp(np.cumsum(rng.normal(0.0005, 0.015, (T, n)), axis=0))
    close = close_adj * rng.uniform(80, 200, n)
    open_ = close * rng.uniform(0.99, 1.01, (T, n))

    env = Env(
        close_adj=close_adj, close=close, open=open_,
        adv=rng.uniform(1e7, 1e9, (T, n)),
        sigma=rng.uniform(0.01, 0.03, (T, n)),
        cash_return=np.full(T, 0.00015),
        spread=rng.uniform(0.0001, 0.001, (T, n)),
        reduce_only=np.zeros((T, n), bool),
        buy_blocked=np.zeros((T, n), bool),
        suspended=np.zeros((T, n), bool),
        account=acct,
        costs=cost_params_for(acct),
    )

    # Random actions
    for _ in range(10):
        target = rng.uniform(0, 0.2, n)
        target /= target.sum()
        target *= rng.uniform(0.5, 1.0)
        env.step(target, band=0.02, kappa=0.5)

    print(f"  Ran {env.t} steps")
    print(f"  Final equity: ${env.equity:.2f}")
    print(f"  ✓ Env OK")

def main():
    print("=== P2 Training Infrastructure Smoke Test ===\n")

    has_torch = test_imports()
    test_generator()
    test_scorer()
    test_env()

    if has_torch:
        print("\n✓ All components OK (including torch)")
        print("\nReady for P2 capacity search.")
    else:
        print("\n⚠ Core components OK, but torch not available")
        print("Install torch with: pip install -e '.[research-neural]'")
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())
