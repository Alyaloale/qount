import yfinance as yf
import pandas as pd
import numpy as np
import os
import warnings

warnings.filterwarnings('ignore')

CRYPTO_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed", "crypto_dataset_extended.parquet")
TRAD_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed", "ai_training_dataset.parquet")
OUT_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "crypto-trend-v1-phase-a3.md")

def calc_metrics(returns, days_per_year=252):
    if len(returns) < 20:
        return 0.0, 0.0, 0.0
    cum_ret = (1 + returns).cumprod()
    final_val = cum_ret.iloc[-1]
    years = len(returns) / days_per_year
    cagr = (final_val ** (1 / years)) - 1.0 if years > 0 else 0.0
    running_max = cum_ret.cummax()
    drawdown = (cum_ret - running_max) / running_max
    max_dd = drawdown.min()
    ann_vol = returns.std() * np.sqrt(days_per_year)
    sharpe = cagr / ann_vol if ann_vol > 0 else 0.0
    
    return cagr * 100, max_dd * 100, sharpe

def get_crypto_c60_returns():
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
    
    current_candidates = []
    for i in range(len(dates_list)-1):
        today = dates_list[i]
        tomorrow = dates_list[i+1]
        
        if today in monthly_candidates:
            current_candidates = monthly_candidates[today]
            
        w_gate = pd.Series(0.0, index=df.columns)
        if current_candidates:
            weight_per_asset = 1.0 / len(current_candidates)
            for asset in current_candidates:
                allow = p_gt_sma20.loc[today, asset] if asset == 'PAXG-USD' else (p_gt_sma20.loc[today, asset] and btc_gt_sma50.loc[today])
                if allow:
                    w_gate[asset] = weight_per_asset
                    
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
    return pnl_series

def get_g20_returns():
    df = pd.read_parquet(TRAD_DATA_PATH)
    df = df.reset_index().pivot(index='Date', columns='Ticker', values='Close')
    assets = ['TQQQ', 'SOXL', 'FAS', 'CURE', 'URTY', 'DRN', 'ERX']
    df_assets = df[assets].ffill()
    daily_returns = df_assets.pct_change().fillna(0)
    
    mom_63 = df_assets.pct_change(63).fillna(0)
    
    valid_dates = df.index[(df.index >= '2020-05-01') & (df.index <= '2026-07-31')]
    dates_list = list(valid_dates)
    dates_series = pd.Series(valid_dates, index=valid_dates)
    
    last_days = []
    for (yr, mo), group in dates_series.groupby([dates_series.index.year, dates_series.index.month]):
        last_days.append(group.index[-1])
    sig_dates = pd.Index(last_days)
    
    targets = {}
    for date in sig_dates:
        if date not in mom_63.index:
            continue
        scores = mom_63.loc[date].copy()
        top_asset = scores.nlargest(1).index
        if len(top_asset) > 0:
            targets[date] = top_asset[0]
            
    pnl_series = pd.Series(0.0, index=valid_dates)
    current_asset = None
    
    for i in range(len(dates_list)-1):
        today = dates_list[i]
        tomorrow = dates_list[i+1]
        
        if today in targets:
            current_asset = targets[today]
            
        if current_asset:
            pnl_series.loc[tomorrow] = daily_returns.loc[tomorrow, current_asset]
            
    bil_ret = df['BIL'].pct_change().fillna(0).reindex(valid_dates).fillna(0)
    
    # 20% Top1 + 80% BIL
    g20_returns = pnl_series * 0.20 + bil_ret * 0.80
    return g20_returns

def run_phase_a3():
    c60_ret = get_crypto_c60_returns()
    g20_ret = get_g20_returns()
    
    aligned_dates = g20_ret.index
    
    c60_idx = (1 + c60_ret).cumprod()
    c60_idx_us = c60_idx.reindex(aligned_dates).ffill()
    c60_ret_us = c60_idx_us.pct_change().fillna(0)
    
    # Fix the start value for c60_ret_us (the first date might be NaN due to pct_change)
    c60_ret_us.iloc[0] = (c60_idx_us.iloc[0] / 1.0) - 1.0
    
    md = "# 🛡️ Crypto Trend V1 - Phase A3 组合混合测试\n\n"
    
    c_g20, d_g20, s_g20 = calc_metrics(g20_ret, 252)
    c_c60, d_c60, s_c60 = calc_metrics(c60_ret_us, 252)
    
    md += "### 1. 单引擎基准 (对齐美股交易日 2020.05-2026.07)\n\n"
    md += "| 引擎 | CAGR | MaxDD | Sharpe |\n"
    md += "|---|---|---|---|\n"
    md += f"| **G20 (20%动量+80%BIL)** | {c_g20:.2f}% | {d_g20:.2f}% | {s_g20:.2f} |\n"
    md += f"| **C60 Crypto** | {c_c60:.2f}% | {d_c60:.2f}% | {s_c60:.2f} |\n\n"
    
    md += "### 2. G20 + Crypto 联合组合测试\n\n"
    md += "基于每日再平衡（Daily Rebalance）计算的简单混合收益：\n\n"
    md += "| Crypto权重 | G20权重 | CAGR | MaxDD | Sharpe | 状态 |\n"
    md += "|---|---|---|---|---|---|\n"
    
    mixes = [0.025, 0.05, 0.075, 0.10]
    for w_c in mixes:
        w_g = 1 - w_c
        port_ret = w_c * c60_ret_us + w_g * g20_ret
        c, d, s = calc_metrics(port_ret, 252)
        status = "🎉 突破20%" if c >= 20 else "稳健"
        md += f"| **{w_c*100:.1f}%** | {w_g*100:.1f}% | {c:.2f}% | {d:.2f}% | {s:.2f} | {status} |\n"
        
    with open(OUT_MD, "w") as f:
        f.write(md)
    print(f"Written to {OUT_MD}")

if __name__ == "__main__":
    run_phase_a3()
