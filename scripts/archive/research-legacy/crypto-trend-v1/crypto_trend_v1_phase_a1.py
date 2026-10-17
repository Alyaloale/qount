import yfinance as yf
import pandas as pd
import numpy as np
import os
import warnings

warnings.filterwarnings('ignore')

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed", "crypto_dataset.parquet")
OUT_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "crypto-trend-v1-phase-a1.md")

TICKERS = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'BNB-USD', 'PAXG-USD']

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
        
        # Yahoo finance returns MultiIndex columns sometimes, let's fix that
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.droplevel(1)
            
        data = data[['Close']].copy()
        data.columns = [ticker]
        df_list.append(data)
    
    df = pd.concat(df_list, axis=1)
    df.ffill(inplace=True)
    df.to_parquet(DATA_PATH)
    return df

def run_phase_a1():
    if not os.path.exists(DATA_PATH):
        df = download_data()
    else:
        df = pd.read_parquet(DATA_PATH)
        
    daily_returns = df.pct_change().fillna(0)
    
    # Pre-calculate momentum (21, 42, 63, 90 days)
    mom_days_list = [21, 42, 63, 90]
    moms = {d: df.pct_change(d).fillna(0) for d in mom_days_list}
    
    # Valid dates - SOL started trading later, so let's use 2020-05-01 as start
    valid_dates = df.index[(df.index >= '2020-05-01') & (df.index <= '2026-07-31')]
    daily_returns = daily_returns.loc[valid_dates]
    
    # Monthly rebalance dates
    dates_series = pd.Series(valid_dates, index=valid_dates)
    last_days = []
    for (yr, mo), group in dates_series.groupby([dates_series.index.year, dates_series.index.month]):
        last_days.append(group.index[-1])
    sig_dates = pd.Index(last_days)
    
    # Base asset to compare
    btc_ret = daily_returns['BTC-USD']
    btc_cagr, btc_dd, btc_s, _ = calc_metrics(btc_ret)
    
    md = f"# 🚀 Crypto Trend V1 - Phase A1 基线探索\n\n"
    md += f"测试区间: 2020-05-01 至 2026-07-31 (Crypto一年365天交易)\n\n"
    md += f"**基准 (Buy & Hold BTC-USD)**: CAGR = **{btc_cagr:.2f}%**, MaxDD = **{btc_dd:.2f}%**, Sharpe = **{btc_s:.2f}**\n\n"
    md += "| 动量窗口 | 标的选取 | 绝对动量过滤(>0) | CAGR | MaxDD | Sharpe | 评价 |\n"
    md += "|---|---|---|---|---|---|---|\n"
    
    # Test permutations
    for lookback in mom_days_list:
        mom_df = moms[lookback]
        for top_n in [1, 2]:
            for use_cash_filter in [False, True]:
                
                pnl_series = pd.Series(0.0, index=valid_dates)
                current_weights = pd.Series(0.0, index=df.columns)
                
                targets = {}
                for date in sig_dates:
                    if date not in mom_df.index:
                        continue
                        
                    scores = mom_df.loc[date].copy()
                    
                    if use_cash_filter:
                        # Absolute momentum filter
                        scores = scores[scores > 0]
                        
                    if len(scores) == 0:
                        targets[date] = pd.Series(0.0, index=df.columns)
                    else:
                        top_assets = scores.nlargest(top_n).index
                        w = pd.Series(0.0, index=df.columns)
                        w[top_assets] = 1.0 / len(top_assets)
                        targets[date] = w
                
                # Apply targets on T+1
                for i in range(len(valid_dates)-1):
                    today = valid_dates[i]
                    tomorrow = valid_dates[i+1]
                    
                    if today in targets:
                        current_weights = targets[today]
                        
                    pnl_series.loc[tomorrow] = (current_weights * daily_returns.loc[tomorrow]).sum()
                    
                c, d, s, _ = calc_metrics(pnl_series)
                
                filter_str = "是 (空仓转U)" if use_cash_filter else "否 (满仓硬扛)"
                
                verdict = "✅" if (c > btc_cagr and d > -40) else "❌"
                md += f"| {lookback}d | Top {top_n} | {filter_str} | {c:.2f}% | {d:.2f}% | {s:.2f} | {verdict} |\n"
                
    with open(OUT_MD, "w") as f:
        f.write(md)
    print(f"Results written to {OUT_MD}")
        
if __name__ == "__main__":
    run_phase_a1()
