import yfinance as yf
import pandas as pd
import numpy as np
import os
import warnings

warnings.filterwarnings('ignore')

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed", "crypto_dataset_extended.parquet")
OUT_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "crypto-trend-v1-phase-a2-c.md")

TICKERS = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'BNB-USD', 'XRP-USD', 'ADA-USD', 'LTC-USD', 'BCH-USD', 'DOT-USD', 'PAXG-USD']

def calc_metrics(returns, days_per_year=365):
    if len(returns) < 20:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
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
    
    worst_7 = (cum_ret / cum_ret.shift(7) - 1).min()
    worst_30 = (cum_ret / cum_ret.shift(30) - 1).min()
    
    return cagr * 100, max_dd * 100, sharpe, calmar, worst_7 * 100, worst_30 * 100

def simulate_a2_c(df, daily_returns, vol_target=None):
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
    scale_factors = pd.Series(1.0, index=valid_dates)
    
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
                if asset != 'PAXG-USD':
                    allow = p_gt_sma20.loc[today, asset] and btc_gt_sma50.loc[today]
                else:
                    allow = p_gt_sma20.loc[today, asset]
                if allow:
                    w_gate[asset] = weight_per_asset
                    
        k = 1.0
        if vol_target is not None and w_gate.sum() > 0:
            idx_loc = daily_returns.index.get_loc(today)
            if isinstance(idx_loc, slice):
                idx_loc = idx_loc.stop - 1
            if idx_loc >= 20:
                past_ret = daily_returns.iloc[idx_loc-19:idx_loc+1]
                cov_mat = past_ret.cov()
                w_vec = w_gate.values
                var = w_vec.T @ cov_mat.values @ w_vec
                vol_ann = np.sqrt(var * 365)
                if vol_ann > 0:
                    k = min(1.0, vol_target / vol_ann)
        
        w_final = w_gate * k
        daily_weights.loc[tomorrow] = w_final
        scale_factors.loc[tomorrow] = k
        
    pnl_series = (daily_weights * daily_returns.loc[valid_dates]).sum(axis=1)
    c, d, s, cal, w7, w30 = calc_metrics(pnl_series)
    
    avg_exposure = daily_weights.sum(axis=1).mean() * 100
    cash_days = (daily_weights.sum(axis=1) == 0).sum()
    pct_cash_days = cash_days / len(valid_dates) * 100
    
    return c, d, s, cal, w7, w30, avg_exposure, pct_cash_days

def run_phase_a2_c():
    df = pd.read_parquet(DATA_PATH)
    daily_returns = df.pct_change().fillna(0)
    
    md = "# 🛡️ Crypto Trend V1 - Phase A2-C 波动率目标缩放测试\n\n"
    md += "基于 Phase A2-B (M20+M50)。加入协方差波动率测算，k=min(1, target/vol)。\n\n"
    md += "| 版本 | 目标波动率 | CAGR | MaxDD | Sharpe | Calmar | 均暴露 | 全空仓占比 | 最差7日 | 最差30日 |\n"
    md += "|---|---|---|---|---|---|---|---|---|---|\n"
    
    configs = [
        ('C0', None),
        ('C40', 0.40),
        ('C60', 0.60),
        ('C80', 0.80),
    ]
    
    for name, vt in configs:
        c, d, s, cal, w7, w30, exp, cash_pct = simulate_a2_c(df, daily_returns, vt)
        md += f"| **{name}** | {vt if vt else '无'} | {c:.2f}% | {d:.2f}% | {s:.2f} | {cal:.2f} | {exp:.1f}% | {cash_pct:.1f}% | {w7:.2f}% | {w30:.2f}% |\n"
        
    with open(OUT_MD, "w") as f:
        f.write(md)
    print(f"Written to {OUT_MD}")

if __name__ == "__main__":
    run_phase_a2_c()
