"""Test stale-data mechanism implementation for CN short-term autocorrelation."""
import numpy as np
from qount.research.etf_trader.generator.params import sample_world
from qount.research.etf_trader.generator.specs import ACCOUNT_SPECS
from qount.research.etf_trader.generator.structural import simulate_world

def test_stale_mechanism():
    print("=== Testing Stale-Data Mechanism ===\n")
    
    # Test CN world with stale mechanism
    spec = ACCOUNT_SPECS["cn"]
    params = sample_world("cn", np.random.default_rng(777))
    print(f"CN world parameters:")
    print(f"  stale_share={params.stale_share:.4f}")
    print(f"  stale_decay={params.stale_decay:.4f}\n")
    
    # Check asset-specific stale values
    print("Asset-specific stale values:")
    asset_names = ["CSI300", "CSI500", "ChiNext", "SSE50", "Gold", "Bond", "QDII-NASDAQ", "QDII-SP500"]
    for i, (a, name) in enumerate(zip(spec.assets, asset_names)):
        print(f"  {name:15s}: stale={a.stale}")
    
    # Test numpy backend
    print("\n--- Testing numpy backend ---")
    w_np = simulate_world(spec, params, years=1.0, warmup_years=0.5, backend="numpy")
    print(f"Simulated {w_np.data.T} days")
    
    # Compute lag-1 autocorrelation for CN A-share equities
    log_r = np.diff(np.log(w_np.data.close_adj[w_np.start:, :4]), axis=0)
    autocorr_np = np.array([np.corrcoef(log_r[:-1, i], log_r[1:, i])[0, 1] for i in range(4)])
    print(f"\nLag-1 autocorr (numpy):")
    for name, ac in zip(asset_names[:4], autocorr_np):
        print(f"  {name:15s}: {ac:+.4f}")
    print(f"  Mean (weighted by stale): {np.average(autocorr_np, weights=[0.2, 0.8, 1.0, 0.0]):.4f}")
    
    # Test native backend
    print("\n--- Testing native backend ---")
    try:
        w_nat = simulate_world(spec, params, years=1.0, warmup_years=0.5, backend="native")
        print(f"Simulated {w_nat.data.T} days")
        
        # Compute lag-1 autocorrelation
        log_r_nat = np.diff(np.log(w_nat.data.close_adj[w_nat.start:, :4]), axis=0)
        autocorr_nat = np.array([np.corrcoef(log_r_nat[:-1, i], log_r_nat[1:, i])[0, 1] for i in range(4)])
        print(f"\nLag-1 autocorr (native):")
        for name, ac in zip(asset_names[:4], autocorr_nat):
            print(f"  {name:15s}: {ac:+.4f}")
        print(f"  Mean (weighted by stale): {np.average(autocorr_nat, weights=[0.2, 0.8, 1.0, 0.0]):.4f}")
        
        # Check parity
        print("\n--- Parity check ---")
        max_diff = np.abs(w_np.data.close_adj[w_np.start:] - w_nat.data.close_adj[w_nat.start:]).max()
        print(f"Max abs diff in close_adj: {max_diff:.2e}")
        if max_diff < 1e-8:
            print("✓ Numpy and native agree to rounding")
        else:
            print(f"✗ Difference exceeds tolerance")
            
    except Exception as e:
        print(f"Native backend unavailable: {e}")
        print("(Expected on Mac without compiler; will work on WSL with ziglang)")
    
    # Test US world (stale should be disabled)
    print("\n--- Testing US world (stale=0) ---")
    params_us = sample_world("us", np.random.default_rng(888))
    print(f"US world stale_share={params_us.stale_share:.4f}, stale_decay={params_us.stale_decay:.4f}")
    w_us = simulate_world(ACCOUNT_SPECS["us"], params_us, years=0.5, warmup_years=0.3, backend="numpy")
    log_r_us = np.diff(np.log(w_us.data.close_adj[w_us.start:, :3]), axis=0)
    autocorr_us = np.array([np.corrcoef(log_r_us[:-1, i], log_r_us[1:, i])[0, 1] for i in range(3)])
    print(f"Lag-1 autocorr (SPY, QQQ, IWM): {autocorr_us}")
    print(f"Mean: {autocorr_us.mean():.4f} (expected ≈ 0 for US)")
    
    print("\n=== Test Complete ===")

if __name__ == "__main__":
    test_stale_mechanism()
