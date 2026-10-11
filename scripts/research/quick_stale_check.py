"""Quick verification that stale-data mechanism is implemented correctly."""
import sys

# Verify specs.py has stale values
print("1. Checking CN_SPEC asset stale values...")
from qount.research.etf_trader.generator.specs import CN_SPEC
expected = [0.2, 0.8, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0]
actual = [a.stale for a in CN_SPEC.assets]
print(f"   Expected: {expected}")
print(f"   Actual:   {actual}")
assert actual == expected, "Stale values mismatch!"
print("   ✓ Asset stale values correct\n")

# Verify params.py has WorldParams fields
print("2. Checking WorldParams has stale_share and stale_decay...")
from qount.research.etf_trader.generator.params import WorldParams
import inspect
fields = [f.name for f in WorldParams.__dataclass_fields__.values()]
assert 'stale_share' in fields, "stale_share missing!"
assert 'stale_decay' in fields, "stale_decay missing!"
print(f"   ✓ WorldParams fields: stale_share, stale_decay present\n")

# Verify native ABI updated
print("3. Checking native ABI version...")
from qount.research.etf_trader.generator import native
econ_len = len(native.ECON_FIELDS)
asset_len = len(native.ASSET_FIELDS)
scalar_len = len(native.SCALAR_FIELDS)
expected_abi = econ_len * 10000 + asset_len * 100 + scalar_len
print(f"   ECON_FIELDS:   {econ_len} (expected 32)")
print(f"   ASSET_FIELDS:  {asset_len} (expected 8, was 7)")
print(f"   SCALAR_FIELDS: {scalar_len} (expected 35, was 33)")
print(f"   Computed ABI:  {expected_abi}")
assert asset_len == 8, f"ASSET_FIELDS should have 8 fields (added STALE), got {asset_len}"
assert scalar_len == 35, f"SCALAR_FIELDS should have 35 fields (added STALE_SHARE, STALE_DECAY), got {scalar_len}"
assert 'STALE' in native.ASSET_FIELDS, "STALE not in ASSET_FIELDS!"
assert 'STALE_SHARE' in native.SCALAR_FIELDS, "STALE_SHARE not in SCALAR_FIELDS!"
assert 'STALE_DECAY' in native.SCALAR_FIELDS, "STALE_DECAY not in SCALAR_FIELDS!"
print(f"   ✓ ABI fields correct\n")

# Verify structural.py implementation (syntax check only on Mac)
print("4. Checking structural.py imports and compiles...")
try:
    from qount.research.etf_trader.generator import structural
    print("   ✓ structural.py imports successfully\n")
except Exception as e:
    print(f"   ✗ Import failed: {e}\n")
    sys.exit(1)

print("=== Quick verification passed ===")
print("\nNext steps (requires WSL with numpy/torch):")
print("1. Run full test: python3 scripts/research/test_stale_mechanism.py")
print("2. Verify parity: python3 -m pytest tests/test_etf_trader_native.py -xvs")
print("3. Run 1,000-world acceptance with standard seed 20260930")
