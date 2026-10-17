import yfinance as yf
import pandas as pd
import numpy as np
import os
import warnings

warnings.filterwarnings('ignore')

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed", "crypto_dataset_extended.parquet")
OUT_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "crypto-trend-v1-phase-a2-a.md")

TICKERS = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'BNB-USD', 'XRP-USD', 'ADA-USD', 'LTC-USD', 'BCH-USD', 'DOT-USD', 'PAXG-USD']

def calc_metrics(returns, days_per_year=365):
    if len(returns) < 20:
        return 0.0, 0.0, 0.0, 0.0
    cum_ret = (1 + returns).cumprod()
    final_val = cum_ret.iloc[-1]
    years = len(returns) / days_per_year
    cagr = (final_val ** (1 / years)) - 1.0 if years > 0 else 0.0
    running_max = cum_ret.cummax()
    drawdown = (cum_ret - running_max) / running_max
    max_dd = drawdown.min()
    ann_vol = returns.std() * np.sqrt(days_per_year)
    sharpe = cagr / ann_vol if ann_vol > 0 else 0.0
    calmar = cagr / abs(max_dd) if abs(max_dd) > 0 else 0.0
    return cagr * 100, max_dd * 100, sharpe, calmar

def simulate_a2_a(df, daily_returns, freq, gate):
    mom_90 = df.pct_change(90).fillna(0)
    
    valid_dates = df.index[(df.index >= '2020-05-01') & (df.index <= '2026-07-31')]
    dates_list = list(valid_dates)
    
    dates_series = pd.Series(valid_dates, index=valid_dates)
    
    if freq == 'Monthly':
        last_days = []
        for (yr, mo), group in dates_series.groupby([dates_series.index.year, dates_series.index.month]):
            last_days.append(group.index[-1])
        sig_dates = pd.Index(last_days)
    else: # Weekly (Sunday)
        sig_dates = dates_series.resample('W-SUN').last().dropna().index
        
    sma20 = df.rolling(20).mean()
    sma50 = df.rolling(50).mean()
    
    p_gt_sma20 = df > sma20
    p_gt_sma50 = df > sma50
    btc_gt_sma50 = p_gt_sma50['BTC-USD']
    
    candidates = {}
    for date in sig_dates:
        if date not in mom_90.index:
            closest_dates = mom_90.index[mom_90.index <= date]
            if len(closest_dates) == 0:
                continue
            date_to_use = closest_dates[-1]
        else:
            date_to_use = date
            
        scores = mom_90.loc[date_to_use].copy()
        scores = scores[scores > 0]
        if len(scores) > 0:
            top_assets = scores.nlargest(2).index.tolist()
        else:
            top_assets = []
        candidates[date] = top_assets
        
    daily_weights = pd.DataFrame(0.0, index=valid_dates, columns=df.columns)
    
    current_candidates = []
    for i in range(len(dates_list)-1):
        today = dates_list[i]
        tomorrow = dates_list[i+1]
        
        if today in candidates:
            current_candidates = candidates[today]
            
        w = pd.Series(0.0, index=df.columns)
        if current_candidates:
            num_assets = len(current_candidates)
            weight_per_asset = 1.0 / num_assets
            for asset in current_candidates:
                allow = True
                if gate == '20':
                    allow = p_gt_sma20.loc[today, asset]
                elif gate == '50':
                    allow = p_gt_sma50.loc[today, asset]
                elif gate == '20+M50':
                    if asset != 'PAXG-USD':
                        allow = p_gt_sma20.loc[today, asset] and btc_gt_sma50.loc[today]
                    else:
                        allow = p_gt_sma20.loc[today, asset]
                if allow:
                    w[asset] = weight_per_asset
                    
        daily_weights.loc[tomorrow] = w
        
    pnl_series = (daily_weights * daily_returns.loc[valid_dates]).sum(axis=1)
    c, d, s, _ = calc_metrics(pnl_series)
    return c, d, s

def run_phase_a2_a():
    df = pd.read_parquet(DATA_PATH)
    daily_returns = df.pct_change().fillna(0)
    
    md = "# 🛡️ Crypto Trend V1 - Phase A2-A 调仓频率测试\n\n"
    md += "基于 Phase A1.5 全资产池，90日动量 Top2，绝对动量>0。\n\n"
    md += "| 排名频率 | 风险闸门 | 组合名称 | CAGR | MaxDD | Sharpe |\n"
    md += "|---|---|---|---|---|---|\n"
    
    configs = [
        ('Monthly', '0', 'M0'),
        ('Monthly', '20', 'M20'),
        ('Monthly', '50', 'M50'),
        ('Monthly', '20+M50', 'M20+M50'),
        ('Weekly', '0', 'W0'),
        ('Weekly', '20', 'W20'),
        ('Weekly', '50', 'W50'),
        ('Weekly', '20+M50', 'W20+M50'),
    ]
    
    for freq, gate, name in configs:
        c, d, s = simulate_a2_a(df, daily_returns, freq, gate)
        md += f"| {freq} | SMA{gate} | **{name}** | {c:.2f}% | {d:.2f}% | {s:.2f} |\n"
        
    with open(OUT_MD, "w") as f:
        f.write(md)
    print(f"Written to {OUT_MD}")

if __name__ == "__main__":
    run_phase_a2_a()
