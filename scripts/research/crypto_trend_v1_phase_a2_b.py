import yfinance as yf
import pandas as pd
import numpy as np
import os
import warnings

warnings.filterwarnings('ignore')

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed", "crypto_dataset_extended.parquet")
OUT_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "crypto-trend-v1-phase-a2-b.md")

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

def simulate_a2_b(df, daily_returns, variant):
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
    
    # Pre-calculate boolean masks for gates
    p_gt_sma20 = df > sma20
    p_gt_sma50 = df > sma50
    btc_gt_sma50 = p_gt_sma50['BTC-USD']
    p_gt_sma20_2d = p_gt_sma20 & p_gt_sma20.shift(1).fillna(False)
    
    # B20H state
    state_b20h = pd.DataFrame(False, index=df.index, columns=df.columns)
    for col in df.columns:
        s = pd.Series(False, index=df.index)
        current = False
        col_idx = df.columns.get_loc(col)
        for i in range(len(df)):
            if not p_gt_sma20.iloc[i, col_idx]:
                current = False
            elif p_gt_sma20_2d.iloc[i, col_idx]:
                current = True
            s.iloc[i] = current
        state_b20h[col] = s
    
    monthly_candidates = {}
    for date in sig_dates:
        if date not in mom_90.index:
            continue
        scores = mom_90.loc[date].copy()
        scores = scores[scores > 0]
        if len(scores) > 0:
            top_assets = scores.nlargest(2).index.tolist()
        else:
            top_assets = []
        monthly_candidates[date] = top_assets
        
    daily_weights = pd.DataFrame(0.0, index=valid_dates, columns=df.columns)
    
    current_candidates = []
    for i in range(len(dates_list)-1):
        today = dates_list[i]
        tomorrow = dates_list[i+1]
        
        if today in monthly_candidates:
            current_candidates = monthly_candidates[today]
            
        w = pd.Series(0.0, index=df.columns)
        
        if current_candidates:
            num_assets = len(current_candidates)
            weight_per_asset = 1.0 / num_assets
            
            for asset in current_candidates:
                # Apply gates
                allow = True
                if variant == 'B20':
                    allow = p_gt_sma20.loc[today, asset]
                elif variant == 'B50':
                    allow = p_gt_sma50.loc[today, asset]
                elif variant == 'B20H':
                    allow = state_b20h.loc[today, asset]
                elif variant == 'BM50':
                    if asset != 'PAXG-USD':
                        allow = btc_gt_sma50.loc[today]
                    else:
                        allow = True # Gold unaffected by BTC market gate
                elif variant == 'B20+M50':
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

def run_phase_a2_b():
    df = pd.read_parquet(DATA_PATH)
    daily_returns = df.pct_change().fillna(0)
    
    variants = ['B0', 'B20', 'B50', 'B20H', 'BM50', 'B20+M50']
    
    md = "# 🛡️ Crypto Trend V1 - Phase A2-B 日度均线风险闸门测试\n\n"
    md += "基于 Phase A1.5 全资产池，90日动量 Top2，绝对动量>0。\n\n"
    md += "| 版本 | 日度风控说明 | CAGR | MaxDD | Sharpe | 推荐度 |\n"
    md += "|---|---|---|---|---|---|\n"
    
    for v in variants:
        c, d, s = simulate_a2_b(df, daily_returns, v)
        desc = ""
        if v == 'B0': desc = "无日度风控"
        elif v == 'B20': desc = "资产 < SMA20 退出"
        elif v == 'B50': desc = "资产 < SMA50 退出"
        elif v == 'B20H': desc = "资产 < SMA20 退出，站上2日进入"
        elif v == 'BM50': desc = "BTC < SMA50 退出所有"
        elif v == 'B20+M50': desc = "资产 < SMA20 且 BTC > SMA50"
        
        md += f"| **{v}** | {desc} | {c:.2f}% | {d:.2f}% | {s:.2f} |  |\n"
        
    with open(OUT_MD, "w") as f:
        f.write(md)
    print(f"Written to {OUT_MD}")

if __name__ == "__main__":
    run_phase_a2_b()
