#!/bin/bash
# Verify stale-data mechanism implementation on WSL with GPU environment

set -e

echo "=== Stale-Data Mechanism Verification ==="
echo "Date: $(date)"
echo ""

cd /mnt/c/Users/alyaloale/Code/qount
source venv/bin/activate

echo "1. Testing numpy backend..."
python3 scripts/research/test_stale_mechanism.py 2>&1 | tee /tmp/stale_test_output.txt

echo ""
echo "2. Running native kernel parity tests..."
python3 -m pytest tests/test_etf_trader_native.py -xvs -k "parity" 2>&1 | tee -a /tmp/stale_test_output.txt

echo ""
echo "3. Verifying ABI version updated correctly..."
python3 -c "
from qount.research.etf_trader.generator import native
print(f'ECON_FIELDS: {len(native.ECON_FIELDS)} fields')
print(f'ASSET_FIELDS: {len(native.ASSET_FIELDS)} fields (added STALE)')
print(f'SCALAR_FIELDS: {len(native.SCALAR_FIELDS)} fields (added STALE_SHARE, STALE_DECAY)')
print(f'Expected ABI: {len(native.ECON_FIELDS) * 10000 + len(native.ASSET_FIELDS) * 100 + len(native.SCALAR_FIELDS)}')
print(f'Native available: {native.available()}')
if native.available():
    native.load()
    lib = native._lib
    print(f'Kernel ABI: {lib.qount_kernel_abi()}')
"

echo ""
echo "4. Quick autocorrelation sanity check..."
python3 << 'PYEOF'
import numpy as np
from qount.research.etf_trader.generator.params import sample_world
from qount.research.etf_trader.generator.specs import ACCOUNT_SPECS
from qount.research.etf_trader.generator.structural import simulate_world

# Generate 5 CN worlds and check autocorr distribution
autocorrs = []
for seed in [100, 200, 300, 400, 500]:
    spec = ACCOUNT_SPECS["cn"]
    params = sample_world("cn", np.random.default_rng(seed))
    w = simulate_world(spec, params, years=2.0, warmup_years=1.0, backend="auto")
    log_r = np.diff(np.log(w.data.close_adj[w.start:, :4]), axis=0)
    ac = np.array([np.corrcoef(log_r[:-1, i], log_r[1:, i])[0, 1] for i in range(4)])
    # Weight by stale: CSI300=0.2, CSI500=0.8, ChiNext=1.0, SSE50=0.0
    weighted = np.average(ac, weights=[0.2, 0.8, 1.0, 0.0])
    autocorrs.append(weighted)
    print(f"Seed {seed}: {ac} → weighted {weighted:.4f}")

autocorrs = np.array(autocorrs)
print(f"\nWeighted autocorr across 5 worlds: mean={autocorrs.mean():.4f}, std={autocorrs.std():.4f}")
print(f"Expected: mean > 0.02 (target range [0.021, 0.081] from real CSI indices)")
PYEOF

echo ""
echo "=== Verification Complete ==="
echo "Output saved to /tmp/stale_test_output.txt"
