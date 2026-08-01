import pandas as pd
import numpy as np
import os
import itertools
from datetime import datetime

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed", "ai_training_dataset.parquet")
OUT_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "traditional-v1-phase-b2.md")

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

def get_top_5_drawdowns(returns):
    cum_ret = (1 + returns).cumprod()
    running_max = cum_ret.cummax()
    drawdown = (cum_ret - running_max) / running_max
    
    # Identify drawdown periods
    dd_mask = drawdown < 0
    # Group by consecutive drawdown days
    starts = dd_mask & ~dd_mask.shift(1).fillna(False)
    groups = starts.cumsum()
    
    dd_events = []
    for g in groups.unique():
        if g == 0: continue
        period = drawdown[groups == g]
        if len(period) > 0 and period.min() < -0.01: # only consider >1% drops
            dd_events.append({
                'start': period.index[0].date(),
                'end': period.index[-1].date(), # This is just end of underwater, not necessarily recovery
                'valley': period.idxmin().date(),
                'depth': period.min() * 100
            })
            
    dd_events.sort(key=lambda x: x['depth'])
    return dd_events[:5]

def run_orthogonal_ablation():
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
    ma_200_dist = df.pivot_table(index=df.index, columns='Ticker', values='ma_200_dist')
    z_score_252d = df.pivot_table(index=df.index, columns='Ticker', values='z_score_252d')
    
    sma_200 = df_pivot_close / (1 + ma_200_dist)
    sma_200_slope_20 = sma_200.pct_change(20).fillna(0)
    
    assets_to_rotate = ['TQQQ', 'SOXL', 'FAS', 'CURE', 'URTY', 'DRN', 'ERX']
    score = 0.5 * mom_63d + 0.5 * mom_126d
    month_starts = score.groupby([score.index.year, score.index.month]).head(1).index
    valid_dates = score.index[score.index >= '2018-01-01']
    
    folds = {
        "Full": ("2018-01-01", "2026-12-31"),
        "2018-19": ("2018-01-01", "2019-12-31"),
        "2020-21": ("2020-01-01", "2021-12-31"),
        "2022-23": ("2022-01-01", "2023-12-31"),
        "2024-26": ("2024-01-01", "2026-12-31")
    }
    
    # Generate 16 combinations
    # Factor A: Absolute Momentum > 0
    # Factor P: Price > SMA200
    # Factor S: SMA200 Slope > 0
    # Factor Z: Z-trim (Z >= 1.5 -> cut 50%)
    
    combinations = list(itertools.product([False, True], repeat=4))
    
    results = {}
    returns_dict = {}
    
    for comb in combinations:
        has_A, has_P, has_S, has_Z = comb
        name_parts = []
        if has_A: name_parts.append("A")
        if has_P: name_parts.append("P")
        if has_S: name_parts.append("S")
        if has_Z: name_parts.append("Z")
        name = "+".join(name_parts) if name_parts else "M0 (Base)"
        
        current_weights = pd.Series(0.0, index=daily_returns.columns)
        current_weights['BIL'] = 1.0
        strat_returns = []
        
        for date in valid_dates:
            if date in month_starts:
                current_weights[:] = 0.0
                current_weights['BIL'] = 1.0
                
                row_score = score.loc[date, assets_to_rotate]
                qualifying = assets_to_rotate.copy()
                
                if has_A: qualifying = [a for a in qualifying if mom_90d.loc[date, a] > 0]
                if has_P: qualifying = [a for a in qualifying if ma_200_dist.loc[date, a] > 0]
                if has_S: qualifying = [a for a in qualifying if sma_200_slope_20.loc[date, a] > 0]
                    
                if qualifying:
                    q_scores = row_score[qualifying].sort_values(ascending=False)
                    top_assets = q_scores.head(2).index.tolist()
                    w_each = 0.05
                    for a in top_assets:
                        current_weights[a] = w_each
                    current_weights['BIL'] = 1.0 - len(top_assets)*w_each
                    
            daily_w = current_weights.copy()
            if has_Z:
                for a in assets_to_rotate:
                    if daily_w[a] > 0:
                        z = z_score_252d.loc[date, a]
                        if not np.isnan(z) and z >= 1.5:
                            trim = daily_w[a] * 0.5
                            daily_w[a] -= trim
                            daily_w['BIL'] += trim
                            
            daily_pnl = (daily_w * fwd_returns.loc[date]).sum()
            strat_returns.append(daily_pnl)
            
        returns_dict[name] = pd.Series(strat_returns, index=valid_dates)
        
    # Baseline TQQQ 10%
    baseline_tqqq = pd.Series(0.0, index=valid_dates)
    for date in valid_dates:
        t_ret = fwd_returns.loc[date, 'TQQQ']
        b_ret = fwd_returns.loc[date, 'BIL']
        baseline_tqqq.loc[date] = 0.10 * t_ret + 0.90 * b_ret
    returns_dict['Base_TQQQ10'] = baseline_tqqq
    
    # Calculate across folds
    md = "# 📊 Phase B2: 正交消融测试 (Orthogonal Ablation Test)\\n\\n"
    
    for fold_name, (st, ed) in folds.items():
        md += f"## Fold: {fold_name} ({st} to {ed})\\n"
        md += "| 组合名称 (A=动量 P=价格 S=斜率 Z=止盈) | CAGR | MaxDD | Sharpe | Calmar | Active CAGR (vs TQQQ10) |\\n"
        md += "|---|---|---|---|---|---|\\n"
        
        tqqq_rets = returns_dict['Base_TQQQ10'].loc[st:ed]
        t_cagr, t_dd, t_shp, t_cal = calc_metrics(tqqq_rets)
        
        md += f"| Base_TQQQ10 | {t_cagr:.2f}% | {t_dd:.2f}% | {t_shp:.2f} | {t_cal:.2f} | 0.00% |\\n"
        
        # We define a specific order to present them
        show_order = ["M0 (Base)", "A", "P", "S", "Z", "A+P", "S+Z", "A+P+S", "A+P+S+Z", "M0 (Base)"] 
        # Add all others not in show order
        others = [k for k in returns_dict.keys() if k not in show_order and k != 'Base_TQQQ10']
        
        for k in list(dict.fromkeys(show_order[:-1] + others)):
            if k not in returns_dict: continue
            rets = returns_dict[k].loc[st:ed]
            cagr, dd, shp, cal = calc_metrics(rets)
            active_cagr = cagr - t_cagr
            bold_start = "**" if k in ["M0 (Base)", "S", "S+Z", "A+P+S+Z"] else ""
            bold_end = "**" if k in ["M0 (Base)", "S", "S+Z", "A+P+S+Z"] else ""
            md += f"| {bold_start}{k}{bold_end} | {cagr:.2f}% | {dd:.2f}% | {shp:.2f} | {cal:.2f} | {active_cagr:+.2f}% |\\n"
        md += "\\n"
        
    md += "## 最深 5 次回撤事件 (M0, S, S+Z, A+P+S+Z)\\n"
    target_strats = ["M0 (Base)", "S", "S+Z", "A+P+S+Z"]
    for ts in target_strats:
        md += f"### 策略: {ts}\\n"
        md += "| 谷底深度 | 谷底日期 | 开始下跌 | 结束水下 (或仍水下) |\\n"
        md += "|---|---|---|---|\\n"
        events = get_top_5_drawdowns(returns_dict[ts])
        for ev in events:
            md += f"| {ev['depth']:.2f}% | {ev['valley']} | {ev['start']} | {ev['end']} |\\n"
        md += "\\n"
        
    with open(OUT_MD, "w") as f:
        f.write(md)
    print(f"Results written to {OUT_MD}")

if __name__ == "__main__":
    run_orthogonal_ablation()
