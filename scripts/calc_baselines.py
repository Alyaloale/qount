import os
import pandas as pd
import numpy as np
from datetime import datetime

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "processed", "ai_training_dataset.parquet")
REPORT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "diagnostic_report_baselines.md")

def calc_cagr_dd(returns, days_per_year=252):
    if len(returns) < 100:
        return 0.0, 0.0
    cum_ret = (1 + returns).cumprod()
    final_val = cum_ret.iloc[-1]
    years = len(returns) / days_per_year
    cagr = (final_val ** (1 / years)) - 1.0 if years > 0 else 0.0
    
    running_max = cum_ret.cummax()
    drawdown = (cum_ret - running_max) / running_max
    max_dd = drawdown.min()
    return cagr * 100, max_dd * 100

def run_baselines():
    df = pd.read_parquet(DATA_PATH)
    df = df.sort_index()
    
    windows = [
        {"name": "2018-2019", "start": "2018-01-01", "end": "2019-12-31"},
        {"name": "2020-2021", "start": "2020-01-01", "end": "2021-12-31"},
        {"name": "2022-2023", "start": "2022-01-01", "end": "2023-12-31"},
        {"name": "2024-End",  "start": "2024-01-01", "end": "2099-12-31"}
    ]
    
    # We need a clean pivot table for forward returns
    # target_fwd_return_21d actually looks ahead 21 days, so to simulate a daily strategy 
    # we need the daily return. Let's calculate daily returns from 'Close'.
    
    # Re-calculate exact daily returns
    df_pivot = df.pivot_table(index=df.index, columns='Ticker', values='Close')
    daily_returns = df_pivot.pct_change().fillna(0)
    
    # Re-calculate 21d momentum (based on past 21 days)
    mom_21d = df_pivot.pct_change(periods=21).fillna(0)
    
    # Re-calculate 200d trend for TQQQ
    tqqq_close = df_pivot['TQQQ']
    ma_200 = tqqq_close.rolling(window=200).mean()
    trend_filter_on = tqqq_close > ma_200
    
    results = {}
    
    for w in windows:
        dr = daily_returns[(daily_returns.index >= w['start']) & (daily_returns.index <= w['end'])]
        m21 = mom_21d[(mom_21d.index >= w['start']) & (mom_21d.index <= w['end'])]
        trend = trend_filter_on[(trend_filter_on.index >= w['start']) & (trend_filter_on.index <= w['end'])]
        
        if len(dr) < 50:
            continue
            
        # 1. Buy & Hold BIL (Cash)
        bil_ret = dr['BIL']
        bil_cagr, bil_dd = calc_cagr_dd(bil_ret)
        
        # 2. Buy & Hold TQQQ (Extreme Beta)
        if 'TQQQ' in dr.columns:
            tqqq_ret = dr['TQQQ']
            tqqq_cagr, tqqq_dd = calc_cagr_dd(tqqq_ret)
        else:
            tqqq_cagr, tqqq_dd = 0.0, 0.0
            
        # 2.5 Buy & Hold QQQ (Market Beta)
        if 'QQQ' in dr.columns:
            qqq_ret = dr['QQQ']
            qqq_cagr, qqq_dd = calc_cagr_dd(qqq_ret)
        else:
            qqq_cagr, qqq_dd = 0.0, 0.0
            
        # 3. Simple 21d Momentum Rotation (Top 2 assets, if negative go BIL)
        # We rebalance monthly (every 21 days) to save turnover
        sim_dates = dr.index[::21] 
        # Create a series to hold portfolio daily returns
        mom_strat_returns = pd.Series(0.0, index=dr.index)
        
        assets_to_rotate = ['TQQQ', 'SOXL', 'FAS', 'URTY', 'TLT', 'GLD']
        available_assets = [a for a in assets_to_rotate if a in dr.columns]
        
        current_weights = pd.Series(0.0, index=dr.columns)
        current_weights['BIL'] = 1.0 # default
        
        for date in dr.index:
            if date in sim_dates:
                # Rebalance
                past_mom = m21.loc[date, available_assets].dropna()
                # Get top 1 asset
                if len(past_mom) > 0:
                    top_asset = past_mom.idxmax()
                    top_score = past_mom.max()
                    current_weights[:] = 0.0
                    if top_score > 0:
                        current_weights[top_asset] = 1.0
                    else:
                        current_weights['BIL'] = 1.0
                        
            # Apply weights
            daily_pnl = (current_weights * dr.loc[date]).sum()
            mom_strat_returns.loc[date] = daily_pnl
            
        mom_cagr, mom_dd = calc_cagr_dd(mom_strat_returns)
        
        # 4. Trend Filter + Volatility Target (simplified: QQQ > MA200 -> TQQQ, else -> BIL)
        trend_returns = pd.Series(0.0, index=dr.index)
        for date in dr.index:
            if trend.loc[date]:
                trend_returns.loc[date] = dr.loc[date, 'TQQQ']
            else:
                trend_returns.loc[date] = dr.loc[date, 'BIL']
                
        trend_cagr, trend_dd = calc_cagr_dd(trend_returns)
        
        results[w['name']] = {
            "BIL_CAGR": bil_cagr, "BIL_DD": bil_dd,
            "QQQ_CAGR": qqq_cagr, "QQQ_DD": qqq_dd,
            "TQQQ_CAGR": tqqq_cagr, "TQQQ_DD": tqqq_dd,
            "MOM_CAGR": mom_cagr, "MOM_DD": mom_dd,
            "TREND_CAGR": trend_cagr, "TREND_DD": trend_dd
        }
        
    md = "# 🛡️ 简单趋势策略基准对比 (Simple Baselines)\n\n"
    md += "> Q: 相比一个二十行代码能写出的策略，Transformer 到底多创造了什么？\n\n"
    
    for fold, metrics in results.items():
        md += f"### 周期: {fold}\n"
        md += "| 策略类型 | 策略规则 | CAGR | Max DD |\n"
        md += "|---|---|---|---|\n"
        md += f"| 安全资产 | 全程持有 BIL (现金) | {metrics['BIL_CAGR']:.2f}% | {metrics['BIL_DD']:.2f}% |\n"
        md += f"| 大盘基准 | 全程持有 QQQ (纳指) | {metrics['QQQ_CAGR']:.2f}% | {metrics['QQQ_DD']:.2f}% |\n"
        md += f"| 激进基准 | 全程持有 TQQQ (三倍杠杆) | {metrics['TQQQ_CAGR']:.2f}% | {metrics['TQQQ_DD']:.2f}% |\n"
        md += f"| 动量轮动 | 21日最强资产(跌破买BIL) | **{metrics['MOM_CAGR']:.2f}%** | **{metrics['MOM_DD']:.2f}%** |\n"
        md += f"| 趋势过滤 | QQQ>MA200买TQQQ, 否则BIL | **{metrics['TREND_CAGR']:.2f}%** | **{metrics['TREND_DD']:.2f}%** |\n\n"
        
    with open(REPORT_PATH, "w") as f:
        f.write(md)
    print(f"✅ Baseline report generated at {REPORT_PATH}")

if __name__ == "__main__":
    run_baselines()
