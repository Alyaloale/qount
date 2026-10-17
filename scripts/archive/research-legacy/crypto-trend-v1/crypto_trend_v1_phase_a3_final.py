import yfinance as yf
import pandas as pd
import numpy as np
import os
import warnings

warnings.filterwarnings('ignore')

CRYPTO_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed", "crypto_dataset_extended.parquet")
TRAD_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed", "ai_training_dataset.parquet")
OUT_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "crypto-trend-v1-phase-a3-final.md")

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

def get_c60_returns(df, daily_returns, delay=0, bps=0, drop_sol=False):
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
        if drop_sol and 'SOL-USD' in scores.index:
            scores = scores.drop('SOL-USD')
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
        
    if delay > 0:
        daily_weights = daily_weights.shift(delay).fillna(0)
        
    turnover = daily_weights.diff().abs().sum(axis=1).fillna(0)
    cost = turnover * (bps / 10000.0)
    
    pnl = (daily_weights * daily_returns.loc[valid_dates]).sum(axis=1) - cost
    return pnl

def get_trad_engine():
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
    
    # Target CAGR 17.18%, MaxDD ~ -17.86%
    # Empirically find weight:
    g20 = pnl_series * 0.235 + bil_ret * 0.765
    return g20, bil_ret

def run_phase_a3_final():
    crypto_df = pd.read_parquet(CRYPTO_DATA_PATH)
    crypto_ret = crypto_df.pct_change().fillna(0)
    
    c60 = get_c60_returns(crypto_df, crypto_ret, delay=0, bps=0)
    c60_delay = get_c60_returns(crypto_df, crypto_ret, delay=1, bps=50)
    c60_no_sol = get_c60_returns(crypto_df, crypto_ret, delay=0, bps=0, drop_sol=True)
    
    g20, bil_ret = get_trad_engine()
    aligned_dates = g20.index
    
    # Align crypto to US dates
    c60_idx = (1 + c60).cumprod()
    c60_us = (c60_idx.reindex(aligned_dates).ffill().pct_change().fillna(0))
    c60_us.iloc[0] = (c60_idx.reindex(aligned_dates).ffill().iloc[0] / 1.0) - 1.0
    
    btc = crypto_ret['BTC-USD']
    btc_idx = (1 + btc).cumprod()
    btc_us = (btc_idx.reindex(aligned_dates).ffill().pct_change().fillna(0))
    btc_us.iloc[0] = (btc_idx.reindex(aligned_dates).ffill().iloc[0] / 1.0) - 1.0
    
    paxg = crypto_ret['PAXG-USD']
    paxg_idx = (1 + paxg).cumprod()
    paxg_us = (paxg_idx.reindex(aligned_dates).ffill().pct_change().fillna(0))
    paxg_us.iloc[0] = (paxg_idx.reindex(aligned_dates).ffill().iloc[0] / 1.0) - 1.0
    
    # Align stress test C60
    c60_delay_idx = (1 + c60_delay).cumprod()
    c60_delay_us = c60_delay_idx.reindex(aligned_dates).ffill().pct_change().fillna(0)
    c60_no_sol_idx = (1 + c60_no_sol).cumprod()
    c60_no_sol_us = c60_no_sol_idx.reindex(aligned_dates).ffill().pct_change().fillna(0)
    
    md = "# 🛡️ G20 + C60 联合深度测试报告 (Phase A3 决战)\n\n"
    
    # 1. Base
    c_g20, d_g20, s_g20, cal_g20 = calc_metrics(g20)
    md += f"**G20 组合基线**: CAGR = {c_g20:.2f}%, MaxDD = {d_g20:.2f}%, Sharpe = {s_g20:.2f}\n\n"
    
    # 2. Correlations
    g20_cum = (1 + g20).cumprod()
    g20_dd = (g20_cum - g20_cum.cummax()) / g20_cum.cummax()
    
    corr_all = g20.corr(c60_us)
    corr_down = g20[g20 < 0].corr(c60_us[g20 < 0])
    corr_stress = g20[g20_dd < -0.10].corr(c60_us[g20_dd < -0.10])
    
    p10_g20 = g20.quantile(0.1)
    p10_c60 = c60_us.quantile(0.1)
    tail_mask = (g20 <= p10_g20) & (c60_us <= p10_c60)
    corr_tail = g20[tail_mask].corr(c60_us[tail_mask])
    
    md += "### 1. 深度相关性剖析\n\n"
    md += "| 情境 | G20 状态 | Correlation (G20, C60) |\n"
    md += "|---|---|---|\n"
    md += f"| **全周期 (All)** | 所有交易日 | {corr_all:.3f} |\n"
    md += f"| **下行期 (Down)** | G20 当日收益 < 0 | {corr_down:.3f} |\n"
    md += f"| **危机期 (Stress)** | G20 当前回撤深于 -10% | {corr_stress:.3f} |\n"
    md += f"| **极度尾部 (Tail)** | 双方同处最差 10% 收益日 | {corr_tail:.3f} (样本量:{tail_mask.sum()}) |\n\n"
    
    # 3. Combinations
    md += "### 2. 联合组合资产配置横评 (GC vs Benchmarks)\n\n"
    md += "目标: 寻找使组合达到 **CAGR > 19%**, **MaxDD > -20%**, **Sharpe > 1.2** 的最优配比，并证明超越简单持有 BTC/PAXG。\n\n"
    
    md += "| 组合 / 资产 | CAGR | MaxDD | Sharpe | Calmar | 增量回撤 |\n"
    md += "|---|---|---|---|---|---|\n"
    
    for w_c in [0.025, 0.05, 0.075, 0.10]:
        w_g = 1 - w_c
        
        # C60
        r_c60 = w_g * g20 + w_c * c60_us
        c_c, d_c, s_c, cal_c = calc_metrics(r_c60)
        md += f"| **{w_g*100:.1f}% G20 + {w_c*100:.1f}% C60** | **{c_c:.2f}%** | **{d_c:.2f}%** | **{s_c:.2f}** | **{cal_c:.2f}** | **{d_c - d_g20:+.2f}%** |\n"
        
        # BTC
        r_btc = w_g * g20 + w_c * btc_us
        c_b, d_b, s_b, cal_b = calc_metrics(r_btc)
        md += f"| {w_g*100:.1f}% G20 + {w_c*100:.1f}% BTC | {c_b:.2f}% | {d_b:.2f}% | {s_b:.2f} | {cal_b:.2f} | {d_b - d_g20:+.2f}% |\n"
        
        # PAXG
        r_pax = w_g * g20 + w_c * paxg_us
        c_p, d_p, s_p, cal_p = calc_metrics(r_pax)
        md += f"| {w_g*100:.1f}% G20 + {w_c*100:.1f}% PAXG | {c_p:.2f}% | {d_p:.2f}% | {s_p:.2f} | {cal_p:.2f} | {d_p - d_g20:+.2f}% |\n"
        
        # Cash
        r_cash = w_g * g20 + w_c * bil_ret
        c_cash, d_cash, s_cash, cal_cash = calc_metrics(r_cash)
        md += f"| {w_g*100:.1f}% G20 + {w_c*100:.1f}% Cash | {c_cash:.2f}% | {d_cash:.2f}% | {s_cash:.2f} | {cal_cash:.2f} | {d_cash - d_g20:+.2f}% |\n"
        
        md += "|---|---|---|---|---|---|\n"
        
    md += "\n### 3. GC5 / GC7.5 极限压力测试 (剥夺核心利润与执行滑点)\n\n"
    md += "| 压力情境 | GC5 (95%G20+5%C60) CAGR/MaxDD | GC7.5 (92.5%G20+7.5%C60) CAGR/MaxDD |\n"
    md += "|---|---|---|\n"
    
    # Delay + 50bps
    r5_delay = 0.95 * g20 + 0.05 * c60_delay_us
    c5_d, dd5_d, _, _ = calc_metrics(r5_delay)
    r75_delay = 0.925 * g20 + 0.075 * c60_delay_us
    c75_d, dd75_d, _, _ = calc_metrics(r75_delay)
    md += f"| **Crypto 延迟 T+1 且 50bps 摩擦** | {c5_d:.2f}% / {dd5_d:.2f}% | {c75_d:.2f}% / {dd75_d:.2f}% |\n"
    
    # Drop SOL
    r5_sol = 0.95 * g20 + 0.05 * c60_no_sol_us
    c5_s, dd5_s, _, _ = calc_metrics(r5_sol)
    r75_sol = 0.925 * g20 + 0.075 * c60_no_sol_us
    c75_s, dd75_s, _, _ = calc_metrics(r75_sol)
    md += f"| **物理删除 SOL (剥夺最大引擎)** | {c5_s:.2f}% / {dd5_s:.2f}% | {c75_s:.2f}% / {dd75_s:.2f}% |\n"
    
    # Remove 2021
    # We set c60_us to 0 during 2021
    c60_no_2021 = c60_us.copy()
    c60_no_2021[c60_no_2021.index.year == 2021] = 0
    r5_21 = 0.95 * g20 + 0.05 * c60_no_2021
    c5_21, dd5_21, _, _ = calc_metrics(r5_21)
    r75_21 = 0.925 * g20 + 0.075 * c60_no_2021
    c75_21, dd75_21, _, _ = calc_metrics(r75_21)
    md += f"| **删除 2021 全年 (剥夺 Alt-Season)** | {c5_21:.2f}% / {dd5_21:.2f}% | {c75_21:.2f}% / {dd75_21:.2f}% |\n"
    
    with open(OUT_MD, "w") as f:
        f.write(md)
    print("Done")

if __name__ == "__main__":
    run_phase_a3_final()
