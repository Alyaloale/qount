import yfinance as yf
import pandas as pd
import numpy as np
import os
import warnings

warnings.filterwarnings('ignore')

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed", "crypto_dataset_extended.parquet")
OUT_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "crypto-trend-v1-phase-a1-5.md")

# Extended Universe
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

def download_data():
    print("Downloading crypto data...")
    df_list = []
    for ticker in TICKERS:
        print(f"Downloading {ticker}...")
        data = yf.download(ticker, start="2018-01-01", end="2026-08-01", progress=False)
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.droplevel(1)
        data = data[['Close']].copy()
        data.columns = [ticker]
        df_list.append(data)
    
    df = pd.concat(df_list, axis=1)
    df.ffill(inplace=True)
    df.to_parquet(DATA_PATH)
    return df

def simulate_baseline(daily_returns, moms, sig_dates, valid_dates, df, exclude_ticker=None):
    mom_df = moms[90].copy()
    if exclude_ticker:
        mom_df = mom_df.drop(columns=[exclude_ticker])
        
    pnl_series = pd.Series(0.0, index=valid_dates)
    current_weights = pd.Series(0.0, index=df.columns)
    
    targets = {}
    daily_weights = pd.DataFrame(0.0, index=valid_dates, columns=df.columns)
    
    for date in sig_dates:
        if date not in mom_df.index:
            continue
        scores = mom_df.loc[date].copy()
        scores = scores[scores > 0]
        w = pd.Series(0.0, index=df.columns)
        if len(scores) > 0:
            top_assets = scores.nlargest(2).index
            w[top_assets] = 1.0 / len(top_assets)
        targets[date] = w
        
    for i in range(len(valid_dates)-1):
        today = valid_dates[i]
        tomorrow = valid_dates[i+1]
        if today in targets:
            current_weights = targets[today]
        daily_weights.loc[tomorrow] = current_weights
        
    daily_asset_returns = daily_weights * daily_returns
    pnl_series = daily_asset_returns.sum(axis=1)
    
    c, d, s, _ = calc_metrics(pnl_series)
    return c, d, s, pnl_series, daily_weights, daily_asset_returns

def run_phase_a1_5():
    if not os.path.exists(DATA_PATH):
        df = download_data()
    else:
        df = pd.read_parquet(DATA_PATH)
        
    daily_returns = df.pct_change().fillna(0)
    mom_days_list = [90]
    moms = {d: df.pct_change(d).fillna(0) for d in mom_days_list}
    
    valid_dates = df.index[(df.index >= '2020-05-01') & (df.index <= '2026-07-31')]
    daily_returns = daily_returns.loc[valid_dates]
    
    dates_series = pd.Series(valid_dates, index=valid_dates)
    last_days = []
    for (yr, mo), group in dates_series.groupby([dates_series.index.year, dates_series.index.month]):
        last_days.append(group.index[-1])
    sig_dates = pd.Index(last_days)
    
    btc_cagr = calc_metrics(daily_returns['BTC-USD'])[0]
    
    # 1. Base run on full extended pool
    c_full, d_full, s_full, pnl_full, daily_weights_full, asset_pnl_full = simulate_baseline(daily_returns, moms, sig_dates, valid_dates, df)
    
    # 2. Leave one out
    loo_results = []
    for ticker in TICKERS:
        c, d, s, _, _, _ = simulate_baseline(daily_returns, moms, sig_dates, valid_dates, df, exclude_ticker=ticker)
        loo_results.append((ticker, c, d, s))
        
    # 3. Attribution
    contrib = asset_pnl_full.sum()
    hold_days = (daily_weights_full > 0).sum()
    
    md = "# 🛡️ Crypto Trend V1 - Phase A1.5 数据审计\n\n"
    md += f"**基线配置**: 90d, Top2, 绝对动量>0, 月度调仓\n"
    md += f"**资产池**: {', '.join(TICKERS)}\n\n"
    md += f"### 1. 扩展池幸存者偏差审计 (留一法)\n\n"
    md += "| 排除资产 | CAGR | MaxDD | Sharpe |\n"
    md += "|---|---|---|---|\n"
    md += f"| **(全资产池)** | **{c_full:.2f}%** | **{d_full:.2f}%** | **{s_full:.2f}** |\n"
    
    for ticker, c, d, s in loo_results:
        md += f"| 删除 {ticker} | {c:.2f}% | {d:.2f}% | {s:.2f} |\n"
        
    md += "\n### 2. 资产利润贡献度\n\n"
    md += "| 资产 | 入选天数 | 绝对收益贡献 (简单累加) | 比例 |\n"
    md += "|---|---|---|---|\n"
    
    for ticker in TICKERS:
        t_days = hold_days[ticker]
        t_contrib = contrib[ticker] * 100
        prop = (contrib[ticker] / contrib.sum()) * 100 if contrib.sum() != 0 else 0
        md += f"| {ticker} | {t_days} | {t_contrib:.2f}% | {prop:.1f}% |\n"
        
    md += "\n> **结论**: 我们需要确认剔除 SOL/BNB 后策略是否依然有效，以及在增加老币（LTC, BCH 等）后收益是否会严重稀释。\n"
    
    with open(OUT_MD, "w") as f:
        f.write(md)
    print(f"Phase A1.5 complete, written to {OUT_MD}")

if __name__ == "__main__":
    run_phase_a1_5()
