import pandas as pd
import numpy as np
import os
import itertools

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed", "ai_training_dataset.parquet")
OUT_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "traditional-v1-phase-c1.md")

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

def get_trading_days(dates_series, nth_day):
    # Group by year-month, then take the nth day (0-indexed, so nth_day-1)
    # If a month has fewer trading days than requested, it falls back to the last available day of that month
    res = []
    for (yr, mo), group in dates_series.groupby([dates_series.index.year, dates_series.index.month]):
        idx = min(nth_day - 1, len(group) - 1)
        res.append(group.index[idx])
    return pd.Index(res)

def run_phase_c1():
    print("Loading data...")
    if not os.path.exists(DATA_PATH):
        print(f"Error: {DATA_PATH} not found.")
        return
        
    df = pd.read_parquet(DATA_PATH)
    
    df_pivot_close = df.pivot_table(index=df.index, columns='Ticker', values='Close')
    daily_returns = df_pivot_close.pct_change().fillna(0)
    fwd_returns = daily_returns.shift(-1).fillna(0)
    
    mom_63d = df.pivot_table(index=df.index, columns='Ticker', values='return_63d')
    mom_126d = df.pivot_table(index=df.index, columns='Ticker', values='return_126d')
    mom_90d = df.pivot_table(index=df.index, columns='Ticker', values='return_90d')
    
    assets_to_rotate = ['TQQQ', 'SOXL', 'FAS', 'CURE', 'URTY', 'DRN', 'ERX']
    
    scores = {
        '63': mom_63d,
        '90': mom_90d,
        '126': mom_126d,
        'Comp': 0.5 * mom_63d + 0.5 * mom_126d
    }
    
    valid_dates = mom_63d.index[(mom_63d.index >= '2018-01-01') & (mom_63d.index <= '2026-07-31')]
    
    folds = {
        "Full": ("2018-01-01", "2026-07-31"),
        "2018-19": ("2018-01-01", "2019-12-31"),
        "2020-21": ("2020-01-01", "2021-12-31"),
        "2022-23": ("2022-01-01", "2023-12-31"),
        "2024-26": ("2024-01-01", "2026-07-31")
    }
    
    mom_windows = ['63', '90', '126', 'Comp']
    k_values = [1, 2, 3]
    reb_days = [1, 3, 5]
    
    combinations = list(itertools.product(mom_windows, k_values, reb_days))
    
    dates_series = pd.Series(valid_dates, index=valid_dates)
    reb_dates_cache = {d: get_trading_days(dates_series, d) for d in reb_days}
    
    returns_dict = {}
    
    print(f"Running {len(combinations)} M0 combinations...")
    
    for comb in combinations:
        mom_w, k, r_day = comb
        name = f"Mom:{mom_w}_Top{k}_Day{r_day}"
        
        score_df = scores[mom_w]
        reb_dates = reb_dates_cache[r_day]
        
        current_weights = pd.Series(0.0, index=daily_returns.columns)
        current_weights['BIL'] = 1.0
        strat_returns = []
        
        for date in valid_dates:
            if date in reb_dates:
                current_weights[:] = 0.0
                current_weights['BIL'] = 1.0
                
                row_score = score_df.loc[date, assets_to_rotate]
                
                q_scores = row_score.sort_values(ascending=False)
                top_assets = q_scores.head(k).index.tolist()
                w_each = 0.10 / k
                for a in top_assets:
                    current_weights[a] = w_each
                current_weights['BIL'] = 1.0 - len(top_assets)*w_each
                    
            daily_pnl = (current_weights * fwd_returns.loc[date]).sum()
            strat_returns.append(daily_pnl)
            
        returns_dict[name] = pd.Series(strat_returns, index=valid_dates)
        
    baseline_tqqq = pd.Series(0.0, index=valid_dates)
    for date in valid_dates:
        baseline_tqqq.loc[date] = 0.10 * fwd_returns.loc[date, 'TQQQ'] + 0.90 * fwd_returns.loc[date, 'BIL']
    returns_dict['Base_TQQQ10'] = baseline_tqqq
    
    md = "# 📊 Phase C1: 增长型基线 M0 参数高原测试\\n\\n"
    
    # Calculate robust score for each comb
    combo_scores = []
    
    for comb in combinations:
        mom_w, k, r_day = comb
        name = f"Mom:{mom_w}_Top{k}_Day{r_day}"
        
        fold_cagrs, fold_act_cagrs, fold_sharpes = [], [], []
        fold_dds = []
        
        # Test across folds (excluding Full for median calculation to avoid double counting)
        for fold_name, (st, ed) in list(folds.items())[1:]:
            rets = returns_dict[name].loc[st:ed]
            base_rets = returns_dict['Base_TQQQ10'].loc[st:ed]
            
            cagr, dd, shp, cal = calc_metrics(rets)
            b_cagr, b_dd, b_shp, b_cal = calc_metrics(base_rets)
            
            fold_cagrs.append(cagr)
            fold_act_cagrs.append(cagr - b_cagr)
            fold_sharpes.append(shp)
            fold_dds.append(dd)
            
        worst_dd = min(fold_dds)
        act_cagr_pos = sum(1 for x in fold_act_cagrs if x > 0)
        
        score_val = np.median(fold_act_cagrs) + 0.5 * np.median(fold_sharpes) - 0.5 * np.std(fold_cagrs)
        
        combo_scores.append({
            'name': name,
            'mom': mom_w,
            'k': k,
            'day': r_day,
            'score': score_val,
            'worst_dd': worst_dd,
            'act_cagr_pos': act_cagr_pos,
            'med_act_cagr': np.median(fold_act_cagrs),
            'med_sharpe': np.median(fold_sharpes)
        })
        
    combo_df = pd.DataFrame(combo_scores)
    combo_df = combo_df.sort_values(by='score', ascending=False)
    
    md += "## 参数组合总览 (按鲁棒评分排序)\\n"
    md += "评分公式: `Median(ActiveCAGR) + 0.5 * Median(Sharpe) - 0.5 * Std(CAGR)`\\n"
    md += "硬约束: WorstDD > -12%, 至少 3/4 Fold ActiveCAGR > 0\\n\\n"
    
    md += "| 排名 | 参数组合 | 鲁棒评分 | 最差DD | Active>0 Folds | 中位数 ActiveCAGR | 中位数 Sharpe | 符合约束 |\n"
    md += "|---|---|---|---|---|---|---|---|\\n"
    
    for i, row in enumerate(combo_df.itertuples()):
        passes = (row.worst_dd > -12.0) and (row.act_cagr_pos >= 3)
        pass_str = "✅" if passes else "❌"
        md += f"| {i+1} | {row.name} | {row.score:.2f} | {row.worst_dd:.2f}% | {row.act_cagr_pos}/4 | {row.med_act_cagr:+.2f}% | {row.med_sharpe:.2f} | {pass_str} |\\n"
        
    # Detail top 5 passing
    md += "\\n## Top 5 稳健参数组合 (通过约束) 详情\\n"
    passing = combo_df[(combo_df['worst_dd'] > -12.0) & (combo_df['act_cagr_pos'] >= 3)]
    top5 = passing.head(5)['name'].tolist()
    
    for name in top5:
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
    run_phase_c1()
