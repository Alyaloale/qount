import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scratch.validate_strategy_proposal import run_causal_regime_backtest, ALL_10_MACRO_SYMBOLS

print("=== Causal Timing Test across all Friction Regimes (2020-2026) ===")
for mode in ['1X_SPOT', 'TRADIFI_MARGIN_2X', 'BINANCE_PERP_2X']:
    # run with causal timing
    # Note: run_causal_regime_backtest in validate_strategy_proposal has spy_lookahead_fixed=True
    pass
