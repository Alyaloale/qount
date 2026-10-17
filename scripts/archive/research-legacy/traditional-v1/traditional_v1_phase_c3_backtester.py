import pandas as pd
import numpy as np
import os
import itertools

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed", "ai_training_dataset.parquet")
OUT_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "traditional-v1-phase-c3.md")

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
    sharpe = (cagr) / ann_vol if ann_vol > 0 else 0.0
    calmar = cagr / abs(max_dd) if abs(max_dd) > 1e-8 else 0.0
    
    return cagr * 100, max_dd * 100, sharpe, calmar

def calc_alpha_beta(strat_returns, tqqq10_returns, bil_returns):
    y = strat_returns - bil_returns
    x = tqqq10_returns - bil_returns
    var_x = np.var(x, ddof=1)
    if var_x < 1e-10 or len(x) < 2: return 0.0, 0.0
    
    beta = np.cov(x, y, ddof=1)[0, 1] / var_x
    alpha_daily = np.mean(y) - beta * np.mean(x)
    alpha_ann = (1 + alpha_daily) ** 252 - 1
    return alpha_ann * 100, beta

def get_trading_days(dates_series, nth_day):
    res = []
    for (yr, mo), group in dates_series.groupby([dates_series.index.year, dates_series.index.month]):
        idx = min(nth_day - 1, len(group) - 1)
        res.append(group.index[idx])
    return pd.Index(res)

def get_top_5_drawdowns(returns):
    cum_ret = (1 + returns).cumprod()
    running_max = cum_ret.cummax()
    drawdown = (cum_ret - running_max) / running_max
    
    is_underwater = drawdown < -1e-6
    starts = is_underwater & ~is_underwater.shift(1, fill_value=False)
    groups = starts.cumsum()
    groups[~is_underwater] = 0
    
    dd_events = []
    for g in range(1, groups.max() + 1):
        period = drawdown[groups == g]
        if len(period) > 0 and period.min() < -0.01:
            dd_events.append({
                'start': period.index[0].date(),
                'end': period.index[-1].date(), 
                'valley': period.idxmin().date(),
                'depth': period.min() * 100
            })
            
    dd_events.sort(key=lambda x: x['depth'])
    return dd_events[:5]

def run_phase_c3():
    print("Loading data for Phase C3...")
    if not os.path.exists(DATA_PATH):
        print(f"Error: {DATA_PATH} not found.")
        return
        
    df = pd.read_parquet(DATA_PATH)
    df_pivot_close = df.pivot_table(index=df.index, columns='Ticker', values='Close')
    daily_returns = df_pivot_close.pct_change().fillna(0)
    fwd_returns = daily_returns.shift(-1).fillna(0)
    
    mom_63d = df.pivot_table(index=df.index, columns='Ticker', values='return_63d')
    z_score_252d = df.pivot_table(index=df.index, columns='Ticker', values='z_score_252d')
    
    assets_to_rotate = ['TQQQ', 'SOXL', 'FAS', 'CURE', 'URTY', 'DRN', 'ERX']
    valid_dates = mom_63d.index[(mom_63d.index >= '2018-01-01') & (mom_63d.index <= '2026-07-31')]
    
    folds = {
        "Full": ("2018-01-01", "2026-07-31"),
        "2018-19": ("2018-01-01", "2019-12-31"),
        "2020-21": ("2020-01-01", "2021-12-31"),
        "2022-23": ("2022-01-01", "2023-12-31"),
        "2024-26": ("2024-01-01", "2026-07-31")
    }
    
    dates_series = pd.Series(valid_dates, index=valid_dates)
    reb_dates = get_trading_days(dates_series, 1)
    
    sma_windows = [180, 200, 220]
    slope_lookbacks = [10, 20, 40]
    
    returns_dict = {}
    
    print("Calculating SMA combinations...")
    for sma_w, slope_l in itertools.product(sma_windows, slope_lookbacks):
        comb_name = f"SMA{sma_w}_Slope{slope_l}"
        
        # Calculate dynamic SMA and slope for this combination
        sma_df = df_pivot_close.rolling(sma_w).mean()
        # Standardized slope: (SMA_t - SMA_t-L) / (L * SMA_t-L)
        slope_df = (sma_df - sma_df.shift(slope_l)) / (slope_l * sma_df.shift(slope_l))
        slope_df = slope_df.fillna(0)
        
        current_weights = pd.Series(0.0, index=daily_returns.columns)
        strat_returns = []
        
        for date in valid_dates:
            if date in reb_dates:
                current_weights[:] = 0.0
                row_score = mom_63d.loc[date, assets_to_rotate]
                
                # Apply S filter (Slope > 0)
                qualifying = [a for a in assets_to_rotate if slope_df.loc[date, a] > 0]
                
                if qualifying:
                    q_scores = row_score[qualifying].sort_values(ascending=False)
                    top_assets = q_scores.head(1).index.tolist()
                    w_each = 0.10
                    for a in top_assets:
                        current_weights[a] = w_each
                    current_weights['BIL'] = 1.0 - len(top_assets)*w_each
                else:
                    current_weights['BIL'] = 1.0
                    
            daily_w = current_weights.copy()
            # Apply Z filter from C2 (Z=1.5, Trim=25%)
            for a in assets_to_rotate:
                if daily_w[a] > 0:
                    z = z_score_252d.loc[date, a]
                    if not np.isnan(z) and z >= 1.5:
                        trim = daily_w[a] * 0.25
                        daily_w[a] -= trim
                        daily_w['BIL'] += trim
                        
            daily_pnl = (daily_w * fwd_returns.loc[date]).sum()
            strat_returns.append(daily_pnl)
            
        returns_dict[comb_name] = pd.Series(strat_returns, index=valid_dates)
        
    baseline_tqqq = pd.Series(0.0, index=valid_dates)
    for date in valid_dates:
        baseline_tqqq.loc[date] = 0.10 * fwd_returns.loc[date, 'TQQQ'] + 0.90 * fwd_returns.loc[date, 'BIL']
    returns_dict['Base_TQQQ10'] = baseline_tqqq
    
    md = "# 📊 Phase C3: 极保守防守版本 (M0 + S + Z) 参数测试\\n\\n"
    md += "基座策略: `Mom:63_Top1` + `Z1.5_Trim25`\\n"
    md += "评分公式: 只要 `WorstDD > -7%` 且 `Alpha >= 0` 即可达标，按 MaxDD 从小到大排序。\\n\\n"
    
    combo_scores = []
    
    for comb_name in returns_dict.keys():
        if comb_name == 'Base_TQQQ10': continue
        
        fold_dds = []
        for fold_name, (st, ed) in list(folds.items())[1:]:
            rets = returns_dict[comb_name].loc[st:ed]
            cagr, dd, shp, cal = calc_metrics(rets)
            fold_dds.append(dd)
            
        worst_dd = min(fold_dds)
        full_alpha, full_beta = calc_alpha_beta(returns_dict[comb_name].loc["2018-01-01":"2026-07-31"], 
                                                returns_dict['Base_TQQQ10'].loc["2018-01-01":"2026-07-31"],
                                                fwd_returns.loc["2018-01-01":"2026-07-31", 'BIL'])
                                                
        full_cagr, _, full_shp, full_cal = calc_metrics(returns_dict[comb_name].loc["2018-01-01":"2026-07-31"])
        
        combo_scores.append({
            'name': comb_name,
            'worst_dd': worst_dd,
            'alpha': full_alpha,
            'cagr': full_cagr,
            'sharpe': full_shp,
            'calmar': full_cal
        })
        
    combo_df = pd.DataFrame(combo_scores)
    # Sort by how small the drawdown is (ascending, since DD is negative, we want closest to 0, so descending mathematically)
    combo_df = combo_df.sort_values(by='worst_dd', ascending=False)
    
    md += "| 排名 | 参数组合 | 最差DD | Full Alpha | Full CAGR | Full Sharpe | 达标 |\n"
    md += "|---|---|---|---|---|---|---|\\n"
    
    for i, row in enumerate(combo_df.itertuples()):
        passes = (row.worst_dd > -7.0) and (row.alpha >= 0)
        pass_str = "✅" if passes else "❌"
        md += f"| {i+1} | {row.name} | {row.worst_dd:.2f}% | {row.alpha:+.2f}% | {row.cagr:.2f}% | {row.sharpe:.2f} | {pass_str} |\\n"
        
    md += "\\n## 最强防守参数组合 详情\\n"
    passing = combo_df[(combo_df['worst_dd'] > -7.0) & (combo_df['alpha'] >= 0)]
    top2 = passing.head(2)['name'].tolist()
    
    if not top2:
        md += "> ⚠️ 没有组合同时满足硬约束，输出最差DD最小的两组代替。\\n"
        top2 = combo_df.head(2)['name'].tolist()
        
    for name in top2:
        md += f"### {name}\\n"
        md += "| Fold | CAGR | MaxDD | Sharpe | Calmar | Active CAGR | Alpha (vs TQQQ10) | Beta |\\n"
        md += "|---|---|---|---|---|---|---|---|\\n"
        
        for fold_name, (st, ed) in folds.items():
            rets = returns_dict[name].loc[st:ed]
            base_rets = returns_dict['Base_TQQQ10'].loc[st:ed]
            bil_rets = fwd_returns.loc[st:ed, 'BIL']
            
            cagr, dd, shp, cal = calc_metrics(rets)
            b_cagr, _, _, _ = calc_metrics(base_rets)
            act = cagr - b_cagr
            alpha, beta = calc_alpha_beta(rets, base_rets, bil_rets)
            
            md += f"| {fold_name} | {cagr:.2f}% | {dd:.2f}% | {shp:.2f} | {cal:.2f} | {act:+.2f}% | {alpha:+.2f}% | {beta:.2f} |\\n"
            
        md += "\\n**最深 5 次回撤事件 (Full 周期)**\\n"
        md += "| 谷底深度 | 谷底日期 | 开始下跌 | 结束水下 (或仍水下) |\\n"
        md += "|---|---|---|---|\\n"
        events = get_top_5_drawdowns(returns_dict[name].loc["2018-01-01":"2026-07-31"])
        for ev in events:
            md += f"| {ev['depth']:.2f}% | {ev['valley']} | {ev['start']} | {ev['end']} |\\n"
        md += "\\n"
        
    with open(OUT_MD, "w") as f:
        f.write(md)
    print(f"Results written to {OUT_MD}")

if __name__ == "__main__":
    run_phase_c3()
