import yfinance as yf
import pandas as pd
import numpy as np
import os
import warnings

warnings.filterwarnings('ignore')

CRYPTO_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed", "crypto_dataset_extended.parquet")
OUT_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "crypto-trend-v1-c60-analysis.md")

def calc_metrics(returns):
    if len(returns) == 0:
        return 0, 0
    cum_ret = (1 + returns).cumprod()
    final_val = cum_ret.iloc[-1]
    # Here we just calculate raw return for the period (not annualized, since we do year by year)
    raw_ret = final_val - 1.0
    running_max = cum_ret.cummax()
    drawdown = (cum_ret - running_max) / running_max
    max_dd = drawdown.min()
    return raw_ret * 100, max_dd * 100

def run_c60_analysis():
    df = pd.read_parquet(CRYPTO_DATA_PATH)
    daily_returns = df.pct_change().fillna(0)
    mom_90 = df.pct_change(90).fillna(0)
    
    valid_dates = df.index[(df.index >= '2020-05-01') & (df.index <= '2026-07-31')]
    dates_list = list(valid_dates)
    dates_series = pd.Series(valid_dates, index=valid_dates)
    
    last_days = []
    for (yr, mo), group in dates_series.groupby([dates_series.index.year, dates_series.index.month]):
        last_days.append(group.index[-1])
    sig_dates = pd.Index(last_days)
    
    sma20 = df.rolling(20).mean()
    sma50 = df.rolling(50).mean()
    
    p_gt_sma20 = df > sma20
    btc_gt_sma50 = (df['BTC-USD'] > sma50['BTC-USD'])
    
    monthly_candidates = {}
    for date in sig_dates:
        if date not in mom_90.index:
            continue
        scores = mom_90.loc[date].copy()
        scores = scores[scores > 0]
        if len(scores) > 0:
            monthly_candidates[date] = scores.nlargest(2).index.tolist()
        else:
            monthly_candidates[date] = []
            
    daily_weights = pd.DataFrame(0.0, index=valid_dates, columns=df.columns)
    
    # Track states per day
    states = pd.Series('Normal', index=valid_dates)
    
    current_candidates = []
    for i in range(len(dates_list)-1):
        today = dates_list[i]
        tomorrow = dates_list[i+1]
        
        if today in monthly_candidates:
            current_candidates = monthly_candidates[today]
            
        w_gate = pd.Series(0.0, index=df.columns)
        sys_blocked = False
        idio_blocked = False
        
        if current_candidates:
            weight_per_asset = 1.0 / len(current_candidates)
            for asset in current_candidates:
                pass_single = p_gt_sma20.loc[today, asset]
                pass_sys = btc_gt_sma50.loc[today]
                
                allow = pass_single if asset == 'PAXG-USD' else (pass_single and pass_sys)
                
                if allow:
                    w_gate[asset] = weight_per_asset
                else:
                    if not pass_sys and asset != 'PAXG-USD':
                        sys_blocked = True
                    else:
                        idio_blocked = True
                        
        if sys_blocked:
            states.loc[tomorrow] = 'Systemic_Cash'
        elif idio_blocked and w_gate.sum() == 0:
            states.loc[tomorrow] = 'Idio_Cash'
        elif w_gate.sum() < 0.99 and w_gate.sum() > 0:
            states.loc[tomorrow] = 'Partial_Cash'
        elif len(current_candidates) == 0:
            states.loc[tomorrow] = 'No_Candidates_Cash'
            
        k = 1.0
        if w_gate.sum() > 0:
            idx_loc = daily_returns.index.get_loc(today)
            if isinstance(idx_loc, slice):
                idx_loc = idx_loc.stop - 1
            if idx_loc >= 20:
                past_ret = daily_returns.iloc[idx_loc-19:idx_loc+1]
                var = w_gate.values.T @ past_ret.cov().values @ w_gate.values
                vol_ann = np.sqrt(var * 365)
                if vol_ann > 0:
                    k = min(1.0, 0.60 / vol_ann)
        
        daily_weights.loc[tomorrow] = w_gate * k
        
    pnl_series = (daily_weights * daily_returns.loc[valid_dates]).sum(axis=1)
    bmk_series = daily_returns.loc[valid_dates, 'BTC-USD']
    
    # Year-by-year analysis
    md = "# 🔍 C60 策略逐年深度剖析\n\n"
    
    for year in range(2020, 2027):
        year_mask = pnl_series.index.year == year
        if not year_mask.any():
            continue
            
        y_pnl = pnl_series[year_mask]
        y_bmk = bmk_series[year_mask]
        y_states = states[year_mask]
        y_weights = daily_weights[year_mask]
        y_asset_pnl = (y_weights * daily_returns.loc[y_pnl.index])
        
        c_pnl, d_pnl = calc_metrics(y_pnl)
        c_bmk, d_bmk = calc_metrics(y_bmk)
        
        sys_pct = (y_states == 'Systemic_Cash').mean() * 100
        norm_pct = (y_states == 'Normal').mean() * 100
        
        # Top contributing assets
        contribs = y_asset_pnl.sum() * 100
        top_assets = contribs[contribs > 0].nlargest(3)
        top_assets_str = ", ".join([f"{k.split('-')[0]}(+{v:.1f}%)" for k, v in top_assets.items()])
        if not top_assets_str: top_assets_str = "无"
        
        md += f"## 📅 {year} 年 (基准 BTC: {c_bmk:+.1f}% | C60: {c_pnl:+.1f}%)\n"
        md += f"- **最大回撤**: 策略 {d_pnl:.1f}% vs BTC {d_bmk:.1f}%\n"
        md += f"- **大盘熔断空仓期**: {sys_pct:.1f}% 的时间被强制空仓防守\n"
        md += f"- **全速进攻期**: {norm_pct:.1f}% 的时间\n"
        md += f"- **利润发动机**: {top_assets_str}\n\n"
        
    with open(OUT_MD, 'w') as f:
        f.write(md)
    print("Done")

if __name__ == "__main__":
    run_c60_analysis()
