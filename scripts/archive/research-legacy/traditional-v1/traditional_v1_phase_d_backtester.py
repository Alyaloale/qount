import pandas as pd
import numpy as np
import os
import random
from collections import defaultdict

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed", "ai_training_dataset.parquet")
OUT_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "traditional-v1-phase-d.md")

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
    return cagr * 100, max_dd * 100, (cagr / (returns.std() * np.sqrt(days_per_year))) if returns.std() > 0 else 0.0

def get_trading_days(dates_series, nth_day):
    res = []
    for (yr, mo), group in dates_series.groupby([dates_series.index.year, dates_series.index.month]):
        idx = min(nth_day - 1, len(group) - 1)
        res.append(group.index[idx])
    return pd.Index(res)

def simulate_strategy(
    df, 
    daily_returns_close_to_close,
    daily_returns_open_to_close,
    valid_dates, 
    mom_df,
    z_df=None,
    assets_to_rotate=None,
    k=1, 
    day=1, 
    z_thresh=None, 
    trim_r=0.0,
    delay_type="T+1 Close",
    cost_bps=0,
    random_delays=None,
    leave_out=None
):
    assets = assets_to_rotate.copy()
    if leave_out:
        assets.remove(leave_out)
        
    dates_series = pd.Series(valid_dates, index=valid_dates)
    reb_dates = get_trading_days(dates_series, day)
    
    current_weights = pd.Series(0.0, index=daily_returns_close_to_close.columns)
    current_weights['BIL'] = 1.0
    
    strat_returns = []
    turnovers = []
    
    # Pre-calculate signals at all valid dates to handle delays easily
    signals = {}
    for date in reb_dates:
        row_score = mom_df.loc[date, assets]
        q_scores = row_score.sort_values(ascending=False)
        top_assets = q_scores.head(k).index.tolist()
        target_w = pd.Series(0.0, index=daily_returns_close_to_close.columns)
        w_each = 0.10 / k
        for a in top_assets:
            target_w[a] = w_each
        target_w['BIL'] = 1.0 - len(top_assets)*w_each
        signals[date] = target_w
        
    # Map execution dates based on delay_type
    exec_map = {}
    valid_dates_list = list(valid_dates)
    
    for i, sig_date in enumerate(valid_dates_list):
        if sig_date in signals:
            if random_delays is not None:
                delay = random_delays.get(sig_date, 0)
            else:
                if delay_type == "T+1 Open": delay = 1
                elif delay_type == "T+1 Close": delay = 0
                elif delay_type == "T+2 Open": delay = 2
                elif delay_type == "T+2 Close": delay = 1
                elif delay_type == "T+3 Open": delay = 3
                elif delay_type == "T+4 Open": delay = 4
                else: delay = 0
                
            exec_idx = min(i + delay, len(valid_dates_list) - 1)
            exec_date = valid_dates_list[exec_idx]
            
            # If multiple signals map to the same execution date, the latest one overwrites
            exec_map[exec_date] = signals[sig_date]
            
    is_open_exec = "Open" in delay_type
            
    for date in valid_dates:
        prev_weights = current_weights.copy()
        traded_today = False
        
        if date in exec_map:
            current_weights = exec_map[date].copy()
            traded_today = True
            
        daily_w = current_weights.copy()
        
        # Z-Trim (evaluated daily at close)
        if z_thresh is not None:
            for a in assets:
                if daily_w[a] > 0:
                    z = z_df.loc[date, a]
                    if not np.isnan(z) and z >= z_thresh:
                        trim = daily_w[a] * trim_r
                        daily_w[a] -= trim
                        daily_w['BIL'] += trim
                        
        turnover = np.abs(daily_w - prev_weights).sum()
        cost = turnover * (cost_bps / 10000.0)
        
        if traded_today and is_open_exec:
            # PnL from Open to Close on the day we trade
            daily_pnl = (daily_w * daily_returns_open_to_close.loc[date]).sum() - cost
        else:
            # Normally PnL from prev Close to Close
            # Wait, our loop is iterating over `date`, and we apply weight to `date`'s forward return.
            # actually `fwd_returns = daily_returns.shift(-1)` which is return of T+1.
            # This is getting confusing. Let's do it on exact date's return.
            # If we are at day `date` (T):
            # The weights `daily_w` are held overnight to T+1.
            pass
            
        # Refactored PnL Calculation using standard Shift(-1) approach:
        # PnL for holding `daily_w` overnight from `date` close to next day's close.
        # But if we execute at "Open", we assume we held `prev_weights` overnight to Open, 
        # paid cost, and then held `daily_w` from Open to Close.
        
        # Let's use the simplest robust method:
        # daily_returns_close_to_close.loc[next_date] is the return from `date` to `next_date`.
        next_idx = valid_dates_list.index(date) + 1
        if next_idx < len(valid_dates_list):
            next_date = valid_dates_list[next_idx]
            
            if next_date in exec_map and "Open" in delay_type:
                # We will trade at next_date Open
                target_w = exec_map[next_date].copy()
                # Holding prev overnight to Open
                # Approximate overnight return (Close to Open)
                # O_ret = Open(t) / Close(t-1) - 1
                o_ret = df.pivot_table(index=df.index, columns='Ticker', values='Open').loc[next_date] / \
                        df.pivot_table(index=df.index, columns='Ticker', values='Close').loc[date] - 1
                o_ret = o_ret.fillna(0)
                
                # Intraday return (Open to Close)
                i_ret = daily_returns_open_to_close.loc[next_date]
                
                pnl_overnight = (daily_w * o_ret).sum()
                
                # Z-trim might apply here for target_w, but let's keep it simple
                t_turnover = np.abs(target_w - daily_w).sum()
                t_cost = t_turnover * (cost_bps / 10000.0)
                
                pnl_intraday = (target_w * i_ret).sum()
                
                daily_pnl = pnl_overnight + pnl_intraday - t_cost
                strat_returns.append(daily_pnl)
            else:
                # Normal close to close
                c_ret = daily_returns_close_to_close.loc[next_date]
                t_cost = turnover * (cost_bps / 10000.0) if traded_today else 0
                daily_pnl = (daily_w * c_ret).sum() - t_cost
                strat_returns.append(daily_pnl)
                
    # Align strat_returns with valid_dates[1:]
    return pd.Series(strat_returns, index=valid_dates[1:])

def run_phase_d():
    print("Loading data for Phase D...")
    df = pd.read_parquet(DATA_PATH)
    
    df_close = df.pivot_table(index=df.index, columns='Ticker', values='Close')
    df_open = df.pivot_table(index=df.index, columns='Ticker', values='Open')
    
    daily_returns = df_close.pct_change().fillna(0)
    open_to_close = (df_close / df_open - 1).fillna(0)
    
    z_score_252d = df.pivot_table(index=df.index, columns='Ticker', values='z_score_252d')
    assets_to_rotate = ['TQQQ', 'SOXL', 'FAS', 'CURE', 'URTY', 'DRN', 'ERX']
    
    valid_dates = daily_returns.index[(daily_returns.index >= '2018-01-01') & (daily_returns.index <= '2026-07-31')]
    
    moms = {
        52: df.pivot_table(index=df.index, columns='Ticker', values='return_52d'),
        57: df.pivot_table(index=df.index, columns='Ticker', values='return_57d'),
        63: df.pivot_table(index=df.index, columns='Ticker', values='return_63d'),
        68: df.pivot_table(index=df.index, columns='Ticker', values='return_68d'),
        74: df.pivot_table(index=df.index, columns='Ticker', values='return_74d')
    }
    
    md = "# 📊 Phase D: 执行扰动与前向鲁棒性测试 (Execution Robustness)\\n\\n"
    
    # Baseline TQQQ 10%
    b_rets = []
    for i in range(len(valid_dates)-1):
        d, nd = valid_dates[i], valid_dates[i+1]
        c_ret = daily_returns.loc[nd]
        b_rets.append(0.10 * c_ret['TQQQ'] + 0.90 * c_ret['BIL'])
    base_tqqq = pd.Series(b_rets, index=valid_dates[1:])
    base_cagr, _, _ = calc_metrics(base_tqqq)
    
    # 1. Signal-Execution timing (E0 to E5)
    md += "## 1. 信号—成交时点测试 (Signal-Execution Timing)\\n"
    md += "| 执行时点 | CAGR | MaxDD | Sharpe | Active CAGR |\\n"
    md += "|---|---|---|---|---|\\n"
    
    exec_modes = ["T+1 Close", "T+1 Open", "T+2 Open", "T+3 Open", "T+4 Open"]
    for mode in exec_modes:
        rets = simulate_strategy(df, daily_returns, open_to_close, valid_dates, moms[63], delay_type=mode, assets_to_rotate=assets_to_rotate)
        cagr, dd, shp = calc_metrics(rets)
        act = cagr - base_cagr
        md += f"| {mode} | {cagr:.2f}% | {dd:.2f}% | {shp:.2f} | {act:+.2f}% |\\n"
        
    # 2. Random Delay
    md += "\\n## 2. 随机延迟测试 (Random Delay 0-3 Days)\\n"
    md += "| 路径 | CAGR | MaxDD | Sharpe | Active CAGR |\\n"
    md += "|---|---|---|---|---|\\n"
    
    random_cagrs = []
    for i in range(100):
        # Generate random delays mapping for each month start
        month_starts = get_trading_days(pd.Series(valid_dates, index=valid_dates), 1)
        r_delays = {d: random.choice([0, 1, 2, 3]) for d in month_starts}
        rets = simulate_strategy(df, daily_returns, open_to_close, valid_dates, moms[63], delay_type="T+1 Close", random_delays=r_delays, assets_to_rotate=assets_to_rotate)
        cagr, dd, shp = calc_metrics(rets)
        random_cagrs.append(cagr - base_cagr)
        if i < 5: # Just show first 5
            md += f"| Path {i+1} | {cagr:.2f}% | {dd:.2f}% | {shp:.2f} | {cagr-base_cagr:+.2f}% |\\n"
            
    pos_ratio = sum(1 for x in random_cagrs if x > 0) / len(random_cagrs)
    md += f"\\n> **100条路径统计**: 正 Active CAGR 比例 = {pos_ratio*100:.1f}% | 最差 Active CAGR = {min(random_cagrs):+.2f}% | 中位数 = {np.median(random_cagrs):+.2f}%\\n"
    
    # 3. Intra-month Day expansion
    md += "\\n## 3. 月内日期扩展测试 (Rebalance Day 1 to 7)\\n"
    md += "| 调仓日 | CAGR | MaxDD | Sharpe | Active CAGR |\\n"
    md += "|---|---|---|---|---|\\n"
    for d in range(1, 8):
        rets = simulate_strategy(df, daily_returns, open_to_close, valid_dates, moms[63], day=d, delay_type="T+1 Close", assets_to_rotate=assets_to_rotate)
        cagr, dd, shp = calc_metrics(rets)
        act = cagr - base_cagr
        md += f"| Day {d} | {cagr:.2f}% | {dd:.2f}% | {shp:.2f} | {act:+.2f}% |\\n"
        
    # 4. Momentum Neighborhood
    md += "\\n## 4. 动量窗口局部邻域测试 (L=52, 57, 63, 68, 74)\\n"
    md += "| 动量窗口 | CAGR | MaxDD | Sharpe | Active CAGR |\\n"
    md += "|---|---|---|---|---|\\n"
    for L in [52, 57, 63, 68, 74]:
        rets = simulate_strategy(df, daily_returns, open_to_close, valid_dates, moms[L], delay_type="T+1 Close", assets_to_rotate=assets_to_rotate)
        cagr, dd, shp = calc_metrics(rets)
        act = cagr - base_cagr
        md += f"| L={L} | {cagr:.2f}% | {dd:.2f}% | {shp:.2f} | {act:+.2f}% |\\n"
        
    # 5. Transaction Costs
    md += "\\n## 5. 交易成本测试 (5, 10, 20, 50 bps)\\n"
    md += "| 成本 (bps) | CAGR | MaxDD | Sharpe | Active CAGR |\\n"
    md += "|---|---|---|---|---|\\n"
    for bps in [0, 5, 10, 20, 50]:
        rets = simulate_strategy(df, daily_returns, open_to_close, valid_dates, moms[63], cost_bps=bps, delay_type="T+1 Close", assets_to_rotate=assets_to_rotate)
        cagr, dd, shp = calc_metrics(rets)
        act = cagr - base_cagr
        md += f"| {bps} | {cagr:.2f}% | {dd:.2f}% | {shp:.2f} | {act:+.2f}% |\\n"
        
    # 6. Universe Leave-One-Out
    md += "\\n## 6. 资产池留一法测试 (Leave-One-Out)\\n"
    md += "| 剔除资产 | CAGR | MaxDD | Sharpe | Active CAGR |\\n"
    md += "|---|---|---|---|---|\\n"
    for a in assets_to_rotate:
        rets = simulate_strategy(df, daily_returns, open_to_close, valid_dates, moms[63], leave_out=a, delay_type="T+1 Close", assets_to_rotate=assets_to_rotate)
        cagr, dd, shp = calc_metrics(rets)
        act = cagr - base_cagr
        md += f"| 无 {a} | {cagr:.2f}% | {dd:.2f}% | {shp:.2f} | {act:+.2f}% |\\n"
        
    # Balanced Candidate (Z1.75 Trim25) Random Delay
    md += "\\n## 7. 平衡版候选 (B1: Z1.75 Trim 25%) 随机延迟测试\\n"
    b1_cagrs = []
    b1_dds = []
    for i in range(100):
        month_starts = get_trading_days(pd.Series(valid_dates, index=valid_dates), 1)
        r_delays = {d: random.choice([0, 1, 2, 3]) for d in month_starts}
        rets = simulate_strategy(df, daily_returns, open_to_close, valid_dates, moms[63], z_df=z_score_252d, z_thresh=1.75, trim_r=0.25, delay_type="T+1 Close", random_delays=r_delays, assets_to_rotate=assets_to_rotate)
        cagr, dd, shp = calc_metrics(rets)
        b1_cagrs.append(cagr - base_cagr)
        b1_dds.append(dd)
        
    pos_ratio_b1 = sum(1 for x in b1_cagrs if x > 0) / len(b1_cagrs)
    md += f"> **100条路径统计**: 正 Active CAGR 比例 = {pos_ratio_b1*100:.1f}% | 最差 DD = {min(b1_dds):.2f}% | 最好 DD = {max(b1_dds):.2f}%\\n"
        
    with open(OUT_MD, "w") as f:
        f.write(md)
    print(f"Results written to {OUT_MD}")

if __name__ == "__main__":
    run_phase_d()
