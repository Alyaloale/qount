import yfinance as yf
import pandas as pd
import numpy as np
import os
import warnings

warnings.filterwarnings('ignore')

CRYPTO_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed", "crypto_dataset_extended.parquet")
TRAD_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed", "ai_training_dataset.parquet")
OUT_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "crypto-trend-v1-phase-a3-real.md")

def calc_metrics(returns, days_per_year=252):
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

def get_c60_returns():
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
        
    pnl = (daily_weights * daily_returns.loc[valid_dates]).sum(axis=1)
    return pnl

def get_g20_full_returns():
    df = pd.read_parquet(TRAD_DATA_PATH)
    df = df.reset_index().pivot(index='Date', columns='Ticker', values='Close')
    assets = ['TQQQ', 'SOXL', 'FAS', 'CURE', 'URTY', 'DRN', 'ERX']
    df_assets = df[assets].ffill()
    daily_returns = df_assets.pct_change().fillna(0)
    
    mom_63 = df_assets.pct_change(63).fillna(0)
    # Full cycle starts from 2018-01-01
    valid_dates = df.index[(df.index >= '2018-01-01') & (df.index <= '2026-07-31')]
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
    
    g20 = pnl_series * 0.235 + bil_ret * 0.765
    return g20, bil_ret

def compute_monthly_rebalanced_portfolio(g20_ret, c60_ret_us, bil_ret, w_c60=0.05):
    # Base allocations
    g20_w = 1.0 - w_c60
    c60_w = w_c60
    
    port_val = 1.0
    port_ret = pd.Series(0.0, index=g20_ret.index)
    
    g20_dollars = port_val * g20_w
    c60_dollars = port_val * c60_w
    
    months = g20_ret.index.to_period('M')
    
    for i in range(len(g20_ret)):
        date = g20_ret.index[i]
        r_g = g20_ret.iloc[i]
        
        # If C60 is alive
        if date >= pd.to_datetime('2020-05-01'):
            r_c = c60_ret_us.loc[date]
        else:
            r_c = bil_ret.loc[date] # Use BIL as cash proxy before 2020
            
        # Rebalance at the start of a new month
        if i > 0 and months[i] != months[i-1]:
            total = g20_dollars + c60_dollars
            g20_dollars = total * g20_w
            c60_dollars = total * c60_w
            
        g20_dollars *= (1 + r_g)
        c60_dollars *= (1 + r_c)
        
        new_port_val = g20_dollars + c60_dollars
        port_ret.iloc[i] = (new_port_val / port_val) - 1.0
        port_val = new_port_val
        
    return port_ret

def run_real_rebalance():
    c60 = get_c60_returns()
    g20, bil = get_g20_full_returns()
    
    c60_idx = (1 + c60).cumprod()
    c60_us = (c60_idx.reindex(g20.index).ffill().pct_change().fillna(0))
    # Correct first valid day
    c60_start = c60.index[0]
    if c60_start in c60_us.index:
        c60_us.loc[c60_start] = (c60_idx.loc[c60_start] / 1.0) - 1.0
        
    md = "# 🛡️ GC5 组合真实部署审计报告\n\n"
    
    # 1. Full cycle G20 vs Common cycle
    g20_common = g20.loc['2020-05-01':]
    c_g_c, d_g_c, s_g_c, _ = calc_metrics(g20_common)
    c_g_f, d_g_f, s_g_f, _ = calc_metrics(g20)
    
    md += "### 1. 基准口径修正\n"
    md += "| 基线 | 区间 | CAGR | MaxDD | Sharpe |\n"
    md += "|---|---|---|---|---|\n"
    md += f"| **G20_Common** | 2020.05-2026.07 | {c_g_c:.2f}% | {d_g_c:.2f}% | {s_g_c:.2f} |\n"
    md += f"| **G20_Full** | 2018.01-2026.07 | {c_g_f:.2f}% | {d_g_f:.2f}% | {s_g_f:.2f} |\n\n"
    
    # 2. Monthly Rebalanced Full Cycle GC5 vs GC7.5
    gc5_real = compute_monthly_rebalanced_portfolio(g20, c60_us, bil, w_c60=0.05)
    gc75_real = compute_monthly_rebalanced_portfolio(g20, c60_us, bil, w_c60=0.075)
    
    c_gc5, d_gc5, s_gc5, cal_gc5 = calc_metrics(gc5_real)
    c_gc75, d_gc75, s_gc75, cal_gc75 = calc_metrics(gc75_real)
    
    md += "### 2. 全周期真实再平衡审计 (2018.01-2026.07)\n"
    md += "规则：跨袖套资金**仅在每月第一个美股交易日**发生再平衡。2020年5月前，C60配额存于现金(BIL)。周末不产生跨市场资金流动，权重自然漂移。\n\n"
    md += "| 组合 | 再平衡频率 | CAGR | MaxDD | Sharpe | Calmar |\n"
    md += "|---|---|---|---|---|---|\n"
    md += f"| **GC5 (95/5)** | 月度 (Monthly) | **{c_gc5:.2f}%** | **{d_gc5:.2f}%** | **{s_gc5:.2f}** | **{cal_gc5:.2f}** |\n"
    md += f"| **GC7.5 (92.5/7.5)** | 月度 (Monthly) | **{c_gc75:.2f}%** | **{d_gc75:.2f}%** | **{s_gc75:.2f}** | **{cal_gc75:.2f}** |\n\n"
    
    # 3. Risk Contribution (Volatility)
    # Covariance over the common period
    cov_mat = pd.DataFrame({'G20': g20_common, 'C60': c60_us.loc['2020-05-01':]}).cov() * 252
    w = np.array([0.95, 0.05])
    port_var = w.T @ cov_mat.values @ w
    
    # Marginal Risk Contribution
    mrc = (cov_mat.values @ w) / np.sqrt(port_var)
    rc = (w * mrc) / np.sqrt(port_var)
    rc_c60 = rc[1] * 100
    
    md += "### 3. 风险贡献穿透审计 (GC5, 共同区间)\n"
    md += f"- **C60 资本权重**: 5.00%\n"
    md += f"- **C60 波动率风险贡献 (RC_vol)**: **{rc_c60:.2f}%** (硬上限: ≤25%)\n"
    md += f"> 状态: {'✅ 通过' if rc_c60 <= 25 else '❌ 超标'}\n\n"
    
    with open(OUT_MD, "w") as f:
        f.write(md)
    print("Done")

if __name__ == "__main__":
    run_real_rebalance()
