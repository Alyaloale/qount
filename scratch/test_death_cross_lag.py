import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from qount.research.universal_regime_expectancy import (
    DailyBar,
    load_etf_bars,
    compute_ema,
    compute_atr,
    compute_kaufman_er,
    compute_profile_state,
    ALL_10_MACRO_SYMBOLS,
    NON_EQUITY_SYMBOLS,
)
from run_experiments import run_custom_backtest

# We can duplicate run_custom_backtest but parameterize macro_bear_mode: "BOTH", "PRICE_ONLY", "CROSS_ONLY"
def run_lag_test(macro_mode="BOTH"):
    # Read spy bars
    spy_bars = load_etf_bars("SPY", data_dir="data/raw")
    spy_closes = [b.c for b in spy_bars]
    spy_ema50 = compute_ema(spy_closes, 50)
    spy_ema200 = compute_ema(spy_closes, 200)
    spy_dict = {
        b.d: (i, b, spy_ema50[i], spy_ema200[i]) for i, b in enumerate(spy_bars)
    }

    # We can test by running custom logic
    # Let's inspect what happens in 2020 if price was above EMA200
    # In 2020, SPY crossed above EMA200 on 2020-05-26 (Close $299)
    # But EMA50 crossed above EMA200 on 2020-07-09 (Close $314)
    # Between 05-26 and 07-09 is 32 trading days (~1.5 months)
    pass

if __name__ == "__main__":
    pass
