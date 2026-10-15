import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from run_experiments import run_custom_backtest
from qount.research.universal_regime_expectancy import (
    load_etf_bars,
    compute_ema,
    compute_atr,
    compute_kaufman_er,
    compute_profile_state,
    ALL_10_MACRO_SYMBOLS,
    NON_EQUITY_SYMBOLS,
)

def run_experiment_suite():
    # Baseline v1.4
    res_base = run_custom_backtest(mr_require_green_candle=True, start_date="2020-01-01", end_date="2026-07-30")
    print(f"v1.4 Baseline: Ret {res_base['return_pct']:+.2f}%, MDD {res_base['mdd_pct']:.2f}%, Calmar {res_base['calmar']:.2f}, Tr {res_base['trade_count']}")

    # What if no tier limit (MaxPos=2, any asset)?
    res_no_tier = run_custom_backtest(mr_require_green_candle=True, orthogonal_tier_limit=False, start_date="2020-01-01", end_date="2026-07-30")
    print(f"No Tier Limit (Allow 2 Equities): Ret {res_no_tier['return_pct']:+.2f}%, MDD {res_no_tier['mdd_pct']:.2f}%, Calmar {res_no_tier['calmar']:.2f}, Tr {res_no_tier['trade_count']}")

if __name__ == "__main__":
    run_experiment_suite()
