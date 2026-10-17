import pandas as pd
import numpy as np
import os
import random

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed", "ai_training_dataset.parquet")
OUT_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "traditional-v1-phase-f2.md")

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

def simulate_f2_split(df, daily_close_ret, open_to_close, valid_dates, mom_df, assets, risk_w=0.25, cost_bps=20, split_days=[1], random_delays=None):
    valid_dates_list = list(valid_dates)
    
    dates_series = pd.Series(valid_dates, index=valid_dates)
    last_days = []
    for (yr, mo), group in dates_series.groupby([dates_series.index.year, dates_series.index.month]):
        last_days.append(group.index[-1])
    sig_dates = pd.Index(last_days)
    
    signals = {}
    for date in sig_dates:
        row_score = mom_df.loc[date, assets]
        signals[date] = row_score.idxmax()
        
    num_splits = len(split_days)
    
    asset_cols = list(daily_close_ret.columns)
    asset_indices = {asset: i for i, asset in enumerate(asset_cols)}
    daily_tw = np.zeros((len(valid_dates_list), len(asset_cols)))
    daily_tw[:, asset_indices['BIL']] = 1.0
    
    signal_list = [(d, signals[d]) for d in sig_dates]
    
    for idx, (sig_date, new_asset) in enumerate(signal_list):
        i = valid_dates_list.index(sig_date)
        base_delay = random_delays.get(sig_date, 0) - 1 if random_delays else 0
        
        t_dates = [min(i + d + base_delay, len(valid_dates_list) - 1) for d in split_days]
        prev_asset = signal_list[idx-1][1] if idx > 0 else new_asset
        
        new_a = asset_indices[new_asset]
        prev_a = asset_indices[prev_asset]
        bil_a = asset_indices['BIL']
        
        if prev_asset == new_asset:
            start_i = t_dates[0]
            if idx < len(signal_list) - 1:
                next_sig_i = valid_dates_list.index(signal_list[idx+1][0])
                end_i = min(next_sig_i + max(split_days) + 20, len(valid_dates_list))
            else:
                end_i = len(valid_dates_list)
            
            daily_tw[start_i:end_i, :] = 0.0
            daily_tw[start_i:end_i, new_a] = risk_w
            daily_tw[start_i:end_i, bil_a] = 1.0 - risk_w
        else:
            for step, t_idx in enumerate(t_dates):
                step_frac = (step + 1) / num_splits
                if step + 1 < len(t_dates):
                    end_i = t_dates[step+1]
                else:
                    if idx < len(signal_list) - 1:
                        next_sig_i = valid_dates_list.index(signal_list[idx+1][0])
                        end_i = min(next_sig_i + max(split_days) + 20, len(valid_dates_list))
                    else:
                        end_i = len(valid_dates_list)
                        
                daily_tw[t_idx:end_i, :] = 0.0
                daily_tw[t_idx:end_i, new_a] = risk_w * step_frac
                daily_tw[t_idx:end_i, prev_a] = risk_w * (1.0 - step_frac)
                daily_tw[t_idx:end_i, bil_a] = 1.0 - risk_w

    daily_tw_df = pd.DataFrame(daily_tw, index=valid_dates, columns=asset_cols)
    
    # Vectorized execution
    # target_w is what we aim to hold for the day (decided at open of that day)
    target_w = daily_tw_df
    # current weights BEFORE trading today are yesterday's target weights
    current_w = target_w.shift(1).fillna(0)
    current_w.iloc[0, asset_indices['BIL']] = 1.0
    
    diffs = (target_w - current_w).abs().sum(axis=1)
    is_trade_day = diffs > 1e-6
    
    open_prices = df.pivot_table(index=df.index, columns='Ticker', values='Open').loc[valid_dates]
    close_prices = df.pivot_table(index=df.index, columns='Ticker', values='Close').loc[valid_dates]
    
    prev_close = close_prices.shift(1)
    o_ret = (open_prices / prev_close - 1).fillna(0)
    i_ret = open_to_close.loc[valid_dates]
    c_ret = daily_close_ret.loc[valid_dates]
    
    pnl_overnight = (current_w * o_ret).sum(axis=1)
    costs = diffs * (cost_bps / 10000.0)
    pnl_intraday = (target_w * i_ret).sum(axis=1)
    
    daily_pnl = np.where(
        is_trade_day,
        pnl_overnight + pnl_intraday - costs,
        (current_w * c_ret).sum(axis=1)
    )
    
    pnl_series = pd.Series(daily_pnl, index=valid_dates)
    return pnl_series.iloc[1:]

def run_phase_f2():
    print("Loading data for Phase F2...")
    df = pd.read_parquet(DATA_PATH)
    
    df_close = df.pivot_table(index=df.index, columns='Ticker', values='Close')
    df_open = df.pivot_table(index=df.index, columns='Ticker', values='Open')
    daily_returns = df_close.pct_change().fillna(0)
    open_to_close = (df_close / df_open - 1).fillna(0)
    
    assets_to_rotate = ['TQQQ', 'SOXL', 'FAS', 'CURE', 'URTY', 'DRN', 'ERX']
    
    mom_57d = df.pivot_table(index=df.index, columns='Ticker', values='return_57d')
    mom_63d = df.pivot_table(index=df.index, columns='Ticker', values='return_63d')
    mom_68d = df.pivot_table(index=df.index, columns='Ticker', values='return_68d')
    mom_74d = df.pivot_table(index=df.index, columns='Ticker', values='return_74d')
    
    # Ensemble signal F2-D
    rank_57 = mom_57d[assets_to_rotate].rank(axis=1, ascending=False)
    rank_63 = mom_63d[assets_to_rotate].rank(axis=1, ascending=False)
    rank_68 = mom_68d[assets_to_rotate].rank(axis=1, ascending=False)
    rank_74 = mom_74d[assets_to_rotate].rank(axis=1, ascending=False)
    
    ensemble_score = (rank_57 + rank_63 + rank_68 + rank_74) / 4.0
    # For ensemble_score, smaller is better rank. We invert it for our function which uses idxmax()
    ensemble_inverted = 10.0 - ensemble_score 
    
    valid_dates = daily_returns.index[(daily_returns.index >= '2018-01-01') & (daily_returns.index <= '2026-07-31')]
    
    # Mixed Benchmark M25
    rw = 0.25
    m_ret = (rw / 2) * daily_returns.loc[valid_dates[1:], 'TQQQ'] + (rw / 2) * daily_returns.loc[valid_dates[1:], 'SOXL'] + (1.0 - rw) * daily_returns.loc[valid_dates[1:], 'BIL']
    m_c, m_d, _, _ = calc_metrics(m_ret)
    
    # Generate random delays (0-3 days -> T+1 to T+4)
    dates_series = pd.Series(valid_dates, index=valid_dates)
    last_days = []
    for (yr, mo), group in dates_series.groupby([dates_series.index.year, dates_series.index.month]):
        last_days.append(group.index[-1])
    sig_dates = pd.Index(last_days)
    
    # Run Versions
    versions = {
        "F2-A (100% T+1)": {"mom": mom_63d, "split": [1]},
        "F2-B (50% T+1, T+2)": {"mom": mom_63d, "split": [1, 2]},
        "F2-C (33% T+1, T+2, T+3)": {"mom": mom_63d, "split": [1, 2, 3]},
        "F2-D (Ensemble T+1)": {"mom": ensemble_inverted, "split": [1]}
    }
    
    results = {}
    folds = {
        "2018-19": ("2018-01-01", "2019-12-31"),
        "2020-21": ("2020-01-01", "2021-12-31"),
        "2022-23": ("2022-01-01", "2023-12-31"),
        "2024-26": ("2024-01-01", "2026-07-31")
    }
    
    md = "# 📊 Phase F2: G25 执行稳健性攻坚战\\n\\n"
    md += "| 版本 | 2018-2025 CAGR | 满足 >=18% | 跑赢基准 Fold 数 | 满足 >=3/4 | 随机延迟正Active | 满足 >=70% | 延迟中位Active | 满足 >0 | MaxDD | 满足 >-25% | Sharpe | 满足 >=1.0 | 最终裁决 |\\n"
    md += "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\\n"
    
    m_ret_1825 = m_ret.loc["2018-01-01":"2025-12-31"]
    
    for v_name, cfg in versions.items():
        print(f"Running {v_name}...")
        rets = simulate_f2_split(df, daily_returns, open_to_close, valid_dates, cfg["mom"], assets_to_rotate, risk_w=0.25, split_days=cfg["split"])
        c, d, s, cal = calc_metrics(rets)
        
        # 2018-2025 CAGR
        rets_1825 = rets.loc["2018-01-01":"2025-12-31"]
        c1825, _, _, _ = calc_metrics(rets_1825)
        cond1 = c1825 >= 18.0
        
        # Folds
        active_folds = 0
        for f, (st, ed) in folds.items():
            gc = calc_metrics(rets.loc[st:ed])[0]
            mc = calc_metrics(m_ret.loc[st:ed])[0]
            if gc > mc: active_folds += 1
        cond2 = active_folds >= 3
        
        # Random Delay (100 paths)
        r_acts = []
        for _ in range(50): # reduced to 50 for speed
            r_delays = {date: random.choice([1, 2, 3, 4]) for date in sig_dates}
            r_rets = simulate_f2_split(df, daily_returns, open_to_close, valid_dates, cfg["mom"], assets_to_rotate, risk_w=0.25, split_days=cfg["split"], random_delays=r_delays)
            r_acts.append(calc_metrics(r_rets)[0] - m_c)
            
        r_pos = sum(1 for x in r_acts if x > 0) / len(r_acts)
        r_med = np.median(r_acts)
        cond3 = (r_pos * 100) >= 70.0
        cond4 = r_med > 0
        
        # Risk & Sharpe
        cond5 = d > -25.0
        cond6 = s >= 1.0
        
        passed_all = all([cond1, cond2, cond3, cond4, cond5, cond6])
        verdict = "✅ 通过" if passed_all else "❌ 淘汰"
        
        md += f"| **{v_name}** | {c1825:.2f}% | {'✅' if cond1 else '❌'} | {active_folds}/4 | {'✅' if cond2 else '❌'} | {r_pos*100:.1f}% | {'✅' if cond3 else '❌'} | {r_med:+.2f}% | {'✅' if cond4 else '❌'} | {d:.2f}% | {'✅' if cond5 else '❌'} | {s:.2f} | {'✅' if cond6 else '❌'} | {verdict} |\\n"

    md += "\\n> **裁决与下一步指示**: 若全军覆没，则停止推进单引擎 20% 目标，前向部署主版本直接降维锁定为 **G20**。并启动跨资产/防御第二引擎研发立项。\\n"

    with open(OUT_MD, "w") as f:
        f.write(md)
    print(f"Results written to {OUT_MD}")

if __name__ == "__main__":
    run_phase_f2()
