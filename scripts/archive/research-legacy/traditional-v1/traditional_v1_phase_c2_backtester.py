import pandas as pd
import numpy as np
import os
import itertools

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed", "ai_training_dataset.parquet")
OUT_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "traditional-v1-phase-c2.md")

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

def run_phase_c2():
    print("Loading data for Phase C2...")
    if not os.path.exists(DATA_PATH):
        print(f"Error: {DATA_PATH} not found.")
        return
        
    df = pd.read_parquet(DATA_PATH)
    
    df_pivot_close = df.pivot_table(index=df.index, columns='Ticker', values='Close')
    daily_returns = df_pivot_close.pct_change().fillna(0)
    fwd_returns = daily_returns.shift(-1).fillna(0)
    
    mom_63d = df.pivot_table(index=df.index, columns='Ticker', values='return_63d')
    mom_126d = df.pivot_table(index=df.index, columns='Ticker', values='return_126d')
    mom_comp = 0.5 * mom_63d + 0.5 * mom_126d
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
    
    # Top 2 M0 configurations from Phase C1
    top_m0s = [
        {"name": "63_Top1", "score_df": mom_63d, "k": 1, "day": 1},
        {"name": "Comp_Top3", "score_df": mom_comp, "k": 3, "day": 1}
    ]
    
    z_thresholds = [1.25, 1.5, 1.75, 2.0]
    trim_ratios = [0.25, 0.50, 0.75]
    
    dates_series = pd.Series(valid_dates, index=valid_dates)
    reb_dates_cache = {1: get_trading_days(dates_series, 1)}
    
    returns_dict = {}
    m0_baselines = {}
    
    # Pre-calculate M0 baselines
    for m0 in top_m0s:
        reb_dates = reb_dates_cache[m0["day"]]
        score_df = m0["score_df"]
        k = m0["k"]
        
        current_weights = pd.Series(0.0, index=daily_returns.columns)
        strat_returns = []
        for date in valid_dates:
            if date in reb_dates:
                current_weights[:] = 0.0
                row_score = score_df.loc[date, assets_to_rotate]
                q_scores = row_score.sort_values(ascending=False)
                top_assets = q_scores.head(k).index.tolist()
                w_each = 0.10 / k
                for a in top_assets:
                    current_weights[a] = w_each
                current_weights['BIL'] = 1.0 - len(top_assets)*w_each
            daily_pnl = (current_weights * fwd_returns.loc[date]).sum()
            strat_returns.append(daily_pnl)
        m0_baselines[m0["name"]] = pd.Series(strat_returns, index=valid_dates)
    
    # Calculate Z combinations
    for m0 in top_m0s:
        reb_dates = reb_dates_cache[m0["day"]]
        score_df = m0["score_df"]
        k = m0["k"]
        
        for z_thresh, trim_r in itertools.product(z_thresholds, trim_ratios):
            comb_name = f"{m0['name']}_Z{z_thresh}_Trim{int(trim_r*100)}"
            
            current_weights = pd.Series(0.0, index=daily_returns.columns)
            strat_returns = []
            
            for date in valid_dates:
                if date in reb_dates:
                    current_weights[:] = 0.0
                    row_score = score_df.loc[date, assets_to_rotate]
                    q_scores = row_score.sort_values(ascending=False)
                    top_assets = q_scores.head(k).index.tolist()
                    w_each = 0.10 / k
                    for a in top_assets:
                        current_weights[a] = w_each
                    current_weights['BIL'] = 1.0 - len(top_assets)*w_each
                    
                daily_w = current_weights.copy()
                # Apply Z-trim daily
                for a in assets_to_rotate:
                    if daily_w[a] > 0:
                        z = z_score_252d.loc[date, a]
                        if not np.isnan(z) and z >= z_thresh:
                            trim = daily_w[a] * trim_r
                            daily_w[a] -= trim
                            daily_w['BIL'] += trim
                            
                daily_pnl = (daily_w * fwd_returns.loc[date]).sum()
                strat_returns.append(daily_pnl)
                
            returns_dict[comb_name] = pd.Series(strat_returns, index=valid_dates)
            
    # Baseline TQQQ 10%
    baseline_tqqq = pd.Series(0.0, index=valid_dates)
    for date in valid_dates:
        baseline_tqqq.loc[date] = 0.10 * fwd_returns.loc[date, 'TQQQ'] + 0.90 * fwd_returns.loc[date, 'BIL']
    returns_dict['Base_TQQQ10'] = baseline_tqqq
    
    md = "# 📊 Phase C2: 平衡型主版本 (M0 + Z) 参数测试\\n\\n"
    
    # Calculate robust score for each comb
    combo_scores = []
    
    for comb_name in returns_dict.keys():
        if comb_name == 'Base_TQQQ10': continue
        
        m0_base_name = "63_Top1" if "63_Top1" in comb_name else "Comp_Top3"
        m0_rets = m0_baselines[m0_base_name]
        
        fold_sharpes, fold_calmars, fold_act_cagrs = [], [], []
        fold_dds = []
        full_cagr_loss = 0
        
        for fold_name, (st, ed) in list(folds.items())[1:]:
            rets = returns_dict[comb_name].loc[st:ed]
            tqqq_rets = returns_dict['Base_TQQQ10'].loc[st:ed]
            
            cagr, dd, shp, cal = calc_metrics(rets)
            b_cagr, _, _, _ = calc_metrics(tqqq_rets)
            
            fold_sharpes.append(shp)
            fold_calmars.append(cal)
            fold_act_cagrs.append(cagr - b_cagr)
            fold_dds.append(dd)
            
        full_cagr, _, _, _ = calc_metrics(returns_dict[comb_name].loc["2018-01-01":"2026-07-31"])
        m0_full_cagr, _, _, _ = calc_metrics(m0_rets.loc["2018-01-01":"2026-07-31"])
        cagr_loss = m0_full_cagr - full_cagr
            
        worst_dd = min(fold_dds)
        score_val = np.median(fold_sharpes) + np.median(fold_calmars) - 0.5 * np.std(fold_act_cagrs)
        
        # Check Alpha in Full
        full_alpha, full_beta = calc_alpha_beta(returns_dict[comb_name].loc["2018-01-01":"2026-07-31"], 
                                                returns_dict['Base_TQQQ10'].loc["2018-01-01":"2026-07-31"],
                                                fwd_returns.loc["2018-01-01":"2026-07-31", 'BIL'])
                                                
        combo_scores.append({
            'name': comb_name,
            'base': m0_base_name,
            'score': score_val,
            'worst_dd': worst_dd,
            'cagr_loss': cagr_loss,
            'alpha': full_alpha,
            'med_sharpe': np.median(fold_sharpes),
            'med_calmar': np.median(fold_calmars)
        })
        
    combo_df = pd.DataFrame(combo_scores)
    combo_df = combo_df.sort_values(by='score', ascending=False)
    
    md += "## 参数组合总览 (按平衡得分排序)\\n"
    md += "评分公式: `Median(Sharpe) + Median(Calmar) - 0.5 * Std(ActiveCAGR)`\\n"
    md += "硬约束: WorstDD > -10%, Alpha >= 0, CAGR 损失 <= 0.75%\\n\\n"
    
    md += "| 排名 | 参数组合 | 基座 | 综合评分 | 最差DD | Full Alpha | CAGR损失 | 中位数Sharpe | 中位数Calmar | 达标 |\n"
    md += "|---|---|---|---|---|---|---|---|---|---|\\n"
    
    for i, row in enumerate(combo_df.itertuples()):
        passes = (row.worst_dd > -10.0) and (row.alpha >= 0) and (row.cagr_loss <= 0.75)
        pass_str = "✅" if passes else "❌"
        md += f"| {i+1} | {row.name} | {row.base} | {row.score:.2f} | {row.worst_dd:.2f}% | {row.alpha:+.2f}% | {row.cagr_loss:.2f}% | {row.med_sharpe:.2f} | {row.med_calmar:.2f} | {pass_str} |\\n"
        
    md += "\\n## Top 3 最强平衡参数组合 详情\\n"
    passing = combo_df[(combo_df['worst_dd'] > -10.0) & (combo_df['alpha'] >= 0) & (combo_df['cagr_loss'] <= 0.75)]
    top3 = passing.head(3)['name'].tolist()
    
    if not top3:
        md += "> ⚠️ 没有组合同时满足硬约束，输出得分最高的前三组代替。\\n"
        top3 = combo_df.head(3)['name'].tolist()
        
    for name in top3:
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
        md += "\\n"
        
    with open(OUT_MD, "w") as f:
        f.write(md)
    print(f"Results written to {OUT_MD}")

if __name__ == "__main__":
    run_phase_c2()
