import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from run_experiments import run_custom_backtest

for mode in ["1X_SPOT", "TRADIFI_MARGIN_2X", "BINANCE_PERP_2X"]:
    res_full = run_custom_backtest(mode=mode, mr_require_green_candle=True, start_date="2020-01-01", end_date="2026-07-30")
    res_recent = run_custom_backtest(mode=mode, mr_require_green_candle=True, start_date="2025-01-01", end_date="2026-07-30")
    print(f"{mode:<20} | Full: Ret {res_full['return_pct']:+6.2f}%, MDD {res_full['mdd_pct']:5.2f}%, PF {res_full['profit_factor']:4.2f}, Calmar {res_full['calmar']:4.2f} | 2025-26: Ret {res_recent['return_pct']:+6.2f}%, MDD {res_recent['mdd_pct']:5.2f}%, Calmar {res_recent['calmar']:4.2f}")
