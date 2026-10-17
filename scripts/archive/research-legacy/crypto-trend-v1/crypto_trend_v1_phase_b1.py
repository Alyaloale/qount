import yfinance as yf
import pandas as pd
import numpy as np
import os
import warnings

warnings.filterwarnings('ignore')

CRYPTO_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed", "crypto_dataset_extended.parquet")
TRAD_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed", "ai_training_dataset.parquet")
OUT_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "crypto-trend-v1-phase-b1.md")

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

def get_c60_signals():
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
    
    monthly_signals = {}
    monthly_candidates = {}
    
    for date in sig_dates:
        if date not in mom_90.index:
            continue
        scores = mom_90.loc[date].copy()
        scores = scores[scores > 0]
        cands = scores.nlargest(2).index.tolist() if len(scores) > 0 else []
        monthly_candidates[date] = cands
        
        M = btc_gt_sma50.loc[date]
        N = sum(p_gt_sma20.loc[date, asset] for asset in cands)
        k = 1.0
        
        valid_cands = [a for a in cands if (p_gt_sma20.loc[date, a] and (M or a == 'PAXG-USD'))]
        if valid_cands:
            w_gate = pd.Series(0.0, index=df.columns)
            weight_per_asset = 1.0 / len(valid_cands)
            for a in valid_cands:
                w_gate[a] = weight_per_asset
                
            idx_loc = daily_returns.index.get_loc(date)
            if isinstance(idx_loc, slice):
                idx_loc = idx_loc.stop - 1
            if idx_loc >= 20:
                past_ret = daily_returns.iloc[idx_loc-19:idx_loc+1]
                var = w_gate.values.T @ past_ret.cov().values @ w_gate.values
                vol_ann = np.sqrt(var * 365)
                if vol_ann > 0:
                    k = min(1.0, 0.60 / vol_ann)
                    
        monthly_signals[date] = {'M': M, 'N': N, 'k': k}

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
    
    # Map signals to daily so we can access them on the first US day
    signal_series_M = pd.Series(False, index=valid_dates)
    signal_series_N = pd.Series(0, index=valid_dates)
    signal_series_k = pd.Series(1.0, index=valid_dates)
    
    curr_sig = {'M': False, 'N': 0, 'k': 1.0}
    for i in range(len(dates_list)):
        today = dates_list[i]
        if today in monthly_signals:
            curr_sig = monthly_signals[today]
        if i < len(dates_list) - 1:
            tomorrow = dates_list[i+1]
            signal_series_M.loc[tomorrow] = curr_sig['M']
            signal_series_N.loc[tomorrow] = curr_sig['N']
            signal_series_k.loc[tomorrow] = curr_sig['k']

    return pnl, signal_series_M, signal_series_N, signal_series_k

def get_g20_full_returns():
    df = pd.read_parquet(TRAD_DATA_PATH)
    df = df.reset_index().pivot(index='Date', columns='Ticker', values='Close')
    assets = ['TQQQ', 'SOXL', 'FAS', 'CURE', 'URTY', 'DRN', 'ERX']
    df_assets = df[assets].ffill()
    daily_returns = df_assets.pct_change().fillna(0)
    
    mom_63 = df_assets.pct_change(63).fillna(0)
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

def run_b1():
    c60, sig_M, sig_N, sig_k = get_c60_signals()
    g20, bil = get_g20_full_returns()
    
    c60_idx = (1 + c60).cumprod()
    c60_us = (c60_idx.reindex(g20.index).ffill().pct_change().fillna(0))
    c60_start = c60.index[0]
    if c60_start in c60_us.index:
        c60_us.loc[c60_start] = (c60_idx.loc[c60_start] / 1.0) - 1.0
        
    def compute_dyn_rebalanced(g20_ret, c60_ret_us, bil_ret, mode='F5', avg_weight=None):
        port_val = 1.0
        port_ret = pd.Series(0.0, index=g20_ret.index)
        
        g20_w = 1.0
        c60_w = 0.0
        
        g20_dollars = port_val * g20_w
        c60_dollars = port_val * c60_w
        
        months = g20_ret.index.to_period('M')
        
        # Track historical weights
        weight_history = []
        
        for i in range(len(g20_ret)):
            date = g20_ret.index[i]
            r_g = g20_ret.iloc[i]
            
            if date >= pd.to_datetime('2020-05-01'):
                r_c = c60_ret_us.loc[date]
            else:
                r_c = bil_ret.loc[date]
                
            if i > 0 and months[i] != months[i-1]:
                # determine target weight
                target_c60 = 0.05
                if mode == 'F5': target_c60 = 0.05
                elif mode == 'F10': target_c60 = 0.10
                elif mode == 'F15': target_c60 = 0.15
                elif mode == 'F_AVG' and avg_weight is not None:
                    target_c60 = avg_weight
                elif mode in ['D15', 'D20']:
                    if date >= pd.to_datetime('2020-05-01') and date in sig_M.index:
                        M = sig_M.loc[date]
                        N = sig_N.loc[date]
                        k = sig_k.loc[date]
                        
                        if not M or N == 0:
                            target_c60 = 0.025
                        elif M and N == 1:
                            target_c60 = 0.075 if mode == 'D15' else 0.10
                        elif M and N == 2 and k < 0.75:
                            target_c60 = 0.10 if mode == 'D15' else 0.15
                        elif M and N == 2 and k >= 0.75:
                            target_c60 = 0.15 if mode == 'D15' else 0.20
                    else:
                        # before 2020-05
                        target_c60 = 0.05
                        
                total = g20_dollars + c60_dollars
                g20_dollars = total * (1 - target_c60)
                c60_dollars = total * target_c60
                weight_history.append(target_c60)
                
            g20_dollars *= (1 + r_g)
            c60_dollars *= (1 + r_c)
            
            new_port_val = g20_dollars + c60_dollars
            port_ret.iloc[i] = (new_port_val / port_val) - 1.0
            port_val = new_port_val
            
        avg_w = np.mean(weight_history) if weight_history else 0.05
        return port_ret, avg_w

    f5, _ = compute_dyn_rebalanced(g20, c60_us, bil, 'F5')
    f10, _ = compute_dyn_rebalanced(g20, c60_us, bil, 'F10')
    f15, _ = compute_dyn_rebalanced(g20, c60_us, bil, 'F15')
    d15, d15_avg = compute_dyn_rebalanced(g20, c60_us, bil, 'D15')
    d20, d20_avg = compute_dyn_rebalanced(g20, c60_us, bil, 'D20')
    
    f_avg_d15, _ = compute_dyn_rebalanced(g20, c60_us, bil, 'F_AVG', avg_weight=d15_avg)
    f_avg_d20, _ = compute_dyn_rebalanced(g20, c60_us, bil, 'F_AVG', avg_weight=d20_avg)
    
    md = "# 🛡️ Phase B1: Dynamic C60 Allocation 审计报告\n\n"
    
    md += "### 1. 静态配额与动态状态机收益 (2018.01 - 2026.07)\n\n"
    md += "| 策略版本 | 机制 | 平均C60权重 | CAGR | MaxDD | Sharpe | Calmar |\n"
    md += "|---|---|---|---|---|---|---|\n"
    
    def add_row(name, mech, w, ret):
        c, d, s, cal = calc_metrics(ret)
        return f"| **{name}** | {mech} | {w*100:.2f}% | {c:.2f}% | {d:.2f}% | {s:.2f} | {cal:.2f} |\n"
        
    md += add_row("F5", "固定5%", 0.05, f5)
    md += add_row("F10", "固定10%", 0.10, f10)
    md += add_row("F15", "固定15%", 0.15, f15)
    md += "|---|---|---|---|---|---|---|\n"
    md += add_row("D15", "状态机 [2.5, 7.5, 10, 15]", d15_avg, d15)
    md += add_row("D20", "状态机 [2.5, 10, 15, 20]", d20_avg, d20)
    md += "|---|---|---|---|---|---|---|\n"
    md += add_row("F_Avg_D15", "等效D15平均权重", d15_avg, f_avg_d15)
    md += add_row("F_Avg_D20", "等效D20平均权重", d20_avg, f_avg_d20)
    
    c_d15, _, _, _ = calc_metrics(d15)
    c_fd15, _, _, _ = calc_metrics(f_avg_d15)
    aa_d15 = c_d15 - c_fd15
    
    c_d20, _, _, _ = calc_metrics(d20)
    c_fd20, _, _, _ = calc_metrics(f_avg_d20)
    aa_d20 = c_d20 - c_fd20
    
    md += "\n### 2. 动态配置阿尔法 (Allocation Alpha) 检验\n\n"
    md += "公式: `AllocationAlpha = CAGR_Dynamic - CAGR_FixedSameAverageWeight`\n\n"
    
    md += "| 动态版本 | 对标固定版本 | 动态 CAGR | 对标固定 CAGR | Allocation Alpha | 状态 |\n"
    md += "|---|---|---|---|---|---|\n"
    md += f"| **D15** | F_{d15_avg*100:.1f}% | {c_d15:.2f}% | {c_fd15:.2f}% | **{aa_d15:+.2f}%** | {'✅ 增量有效' if aa_d15 > 0.5 else '❌ 无效择时'} |\n"
    md += f"| **D20** | F_{d20_avg*100:.1f}% | {c_d20:.2f}% | {c_fd20:.2f}% | **{aa_d20:+.2f}%** | {'✅ 增量有效' if aa_d20 > 0.5 else '❌ 无效择时'} |\n"

    with open(OUT_MD, "w") as f:
        f.write(md)
    print("Done")

if __name__ == "__main__":
    run_b1()
