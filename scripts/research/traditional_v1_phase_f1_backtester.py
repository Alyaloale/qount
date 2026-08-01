import pandas as pd
import numpy as np
import os
import random

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed", "ai_training_dataset.parquet")
OUT_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "traditional-v1-phase-f1.md")

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

def get_trading_days(dates_series, nth_day):
    res = []
    for (yr, mo), group in dates_series.groupby([dates_series.index.year, dates_series.index.month]):
        idx = min(nth_day - 1, len(group) - 1)
        res.append(group.index[idx])
    return pd.Index(res)

def simulate_g_t1_open(df, daily_close_ret, open_to_close, valid_dates, mom_63d, assets, risk_w=0.10, cost_bps=20, random_delays=None, exclude_asset=None):
    dates_series = pd.Series(valid_dates, index=valid_dates)
    last_days = []
    for (yr, mo), group in dates_series.groupby([dates_series.index.year, dates_series.index.month]):
        last_days.append(group.index[-1])
    sig_dates = pd.Index(last_days)
    
    valid_assets = [a for a in assets if a != exclude_asset]
    
    signals = {}
    for date in sig_dates:
        row_score = mom_63d.loc[date, valid_assets]
        top_asset = row_score.idxmax()
        target_w = pd.Series(0.0, index=daily_close_ret.columns)
        target_w[top_asset] = risk_w
        target_w['BIL'] = 1.0 - risk_w
        signals[date] = {"weights": target_w, "asset": top_asset}
        
    valid_dates_list = list(valid_dates)
    exec_map = {}
    for i, sig_date in enumerate(valid_dates_list):
        if sig_date in signals:
            if random_delays is not None:
                delay = random_delays.get(sig_date, 1) # default 1 = T+1
            else:
                delay = 1
            exec_idx = min(i + delay, len(valid_dates_list) - 1)
            exec_map[valid_dates_list[exec_idx]] = signals[sig_date]
            
    current_weights = pd.Series(0.0, index=daily_close_ret.columns)
    current_weights['BIL'] = 1.0
    
    pnl_series = pd.Series(0.0, index=valid_dates[1:])
    
    for i in range(len(valid_dates_list)-1):
        date = valid_dates_list[i]
        next_date = valid_dates_list[i+1]
        
        if next_date in exec_map:
            target_w = exec_map[next_date]["weights"]
            o_ret = df.pivot_table(index=df.index, columns='Ticker', values='Open').loc[next_date] / \
                    df.pivot_table(index=df.index, columns='Ticker', values='Close').loc[date] - 1
            o_ret = o_ret.fillna(0)
            
            pnl_overnight = (current_weights * o_ret).sum()
            turnover = np.abs(target_w - current_weights).sum()
            cost = turnover * (cost_bps / 10000.0)
            
            i_ret = open_to_close.loc[next_date]
            pnl_intraday = (target_w * i_ret).sum()
            
            daily_pnl = pnl_overnight + pnl_intraday - cost
            current_weights = target_w.copy()
        else:
            c_ret = daily_close_ret.loc[next_date]
            daily_pnl = (current_weights * c_ret).sum()
            
        pnl_series.loc[next_date] = daily_pnl
        
    return pnl_series

def run_phase_f1():
    print("Loading data for Phase F1...")
    df = pd.read_parquet(DATA_PATH)
    
    df_close = df.pivot_table(index=df.index, columns='Ticker', values='Close')
    df_open = df.pivot_table(index=df.index, columns='Ticker', values='Open')
    daily_returns = df_close.pct_change().fillna(0)
    open_to_close = (df_close / df_open - 1).fillna(0)
    
    mom_63d = df.pivot_table(index=df.index, columns='Ticker', values='return_63d')
    assets_to_rotate = ['TQQQ', 'SOXL', 'FAS', 'CURE', 'URTY', 'DRN', 'ERX']
    
    valid_dates = daily_returns.index[(daily_returns.index >= '2018-01-01') & (daily_returns.index <= '2026-07-31')]
    
    risk_levels = [10, 15, 20, 25, 30]
    
    md = "# 📊 Phase F1: 风险前沿测绘 (Risk Frontier)\\n\\n"
    
    # 1. 风险前沿主表
    md += "## 1. 风险暴露与收益对比\\n"
    md += "| 版本 | 风险袖套 | G系列 CAGR | 混合基准 CAGR | Active CAGR | G系列 MaxDD | 混合基准 MaxDD | Sharpe | Calmar | 达标评估 |\\n"
    md += "|---|---|---|---|---|---|---|---|---|---|\\n"
    
    g_rets = {}
    m_rets = {}
    
    for r in risk_levels:
        rw = r / 100.0
        # G series
        g_rets[r] = simulate_g_t1_open(df, daily_returns, open_to_close, valid_dates, mom_63d, assets_to_rotate, risk_w=rw)
        # Mixed Benchmark series
        m_ret = (rw / 2) * daily_returns.loc[valid_dates[1:], 'TQQQ'] + (rw / 2) * daily_returns.loc[valid_dates[1:], 'SOXL'] + (1.0 - rw) * daily_returns.loc[valid_dates[1:], 'BIL']
        m_rets[r] = m_ret
        
        g_c, g_d, g_s, g_cal = calc_metrics(g_rets[r])
        m_c, m_d, m_s, m_cal = calc_metrics(m_rets[r])
        act = g_c - m_c
        
        eval_str = ""
        if r == 25:
            # 25% constraints
            if g_c >= 18 and g_d > -25 and g_s >= 1.0 and g_cal >= 0.8:
                eval_str = "✅ 强目标达成"
            elif g_c >= 18 and g_d > -30:
                eval_str = "⚠️ 高回撤达标"
            else:
                eval_str = "❌ 失败"
        elif r == 20:
            if g_c >= 17 and g_d > -20:
                eval_str = "✅ 优先稳健首选"
        
        md += f"| **G{r}** | {r}% | **{g_c:.2f}%** | {m_c:.2f}% | {act:+.2f}% | **{g_d:.2f}%** | {m_d:.2f}% | {g_s:.2f} | {g_cal:.2f} | {eval_str} |\\n"
        
    md += "\\n## 2. G25 (25%风险袖套) 的折叠交叉验证\\n"
    md += "| Fold | G25 CAGR | 混合基准M25 CAGR | Active CAGR | G25 MaxDD | G25 Sharpe |\\n"
    md += "|---|---|---|---|---|---|\\n"
    
    folds = {
        "Full": ("2018-01-01", "2026-07-31"),
        "2018-19": ("2018-01-01", "2019-12-31"),
        "2020-21": ("2020-01-01", "2021-12-31"),
        "2022-23": ("2022-01-01", "2023-12-31"),
        "2024-26": ("2024-01-01", "2026-07-31")
    }
    
    active_folds = 0
    for f, (st, ed) in folds.items():
        gr = g_rets[25].loc[st:ed]
        mr = m_rets[25].loc[st:ed]
        gc, gd, gs, _ = calc_metrics(gr)
        mc, md_, ms, _ = calc_metrics(mr)
        act = gc - mc
        if f != "Full" and act > 0: active_folds += 1
        md += f"| {f} | {gc:.2f}% | {mc:.2f}% | {act:+.2f}% | {gd:.2f}% | {gs:.2f} |\\n"
        
    md += f"\\n> **稳定性**: {active_folds}/4 个 Fold 取得正向超额。\\n"
    
    md += "\\n## 3. G25 的执行延迟扰动 (Random Delay 0-3 Days)\\n"
    dates_series = pd.Series(valid_dates, index=valid_dates)
    last_days = []
    for (yr, mo), group in dates_series.groupby([dates_series.index.year, dates_series.index.month]):
        last_days.append(group.index[-1])
    sig_dates = pd.Index(last_days)
    
    random_act_cagrs = []
    for i in range(100):
        # random delay from signal date (T+0, T+1, T+2, T+3, T+4) ? User said "随机延迟0—3天", so T+1, T+2, T+3, T+4.
        # Original is T+1 Open. So delay = random in [1, 2, 3, 4]
        r_delays = {d: random.choice([1, 2, 3, 4]) for d in sig_dates}
        rets = simulate_g_t1_open(df, daily_returns, open_to_close, valid_dates, mom_63d, assets_to_rotate, risk_w=0.25, random_delays=r_delays)
        c, _, _, _ = calc_metrics(rets)
        m_c, _, _, _ = calc_metrics(m_rets[25])
        random_act_cagrs.append(c - m_c)
        
    pos_rate = sum(1 for x in random_act_cagrs if x > 0) / len(random_act_cagrs)
    md += f"- **100条路径正 Active CAGR 比例**: **{pos_rate*100:.1f}%**\\n"
    
    md += "\\n## 4. G25 剔除 SOXL 测试\\n"
    g25_no_soxl = simulate_g_t1_open(df, daily_returns, open_to_close, valid_dates, mom_63d, assets_to_rotate, risk_w=0.25, exclude_asset='SOXL')
    gn_c, gn_d, gn_s, _ = calc_metrics(g25_no_soxl)
    act_no_soxl = gn_c - calc_metrics(m_rets[25])[0]
    md += f"- 剔除前 (G25): CAGR={calc_metrics(g_rets[25])[0]:.2f}%, MaxDD={calc_metrics(g_rets[25])[1]:.2f}%\\n"
    md += f"- 剔除后 (无SOXL): CAGR={gn_c:.2f}%, MaxDD={gn_d:.2f}% (Active: {act_no_soxl:+.2f}%)\\n"
    
    # 2026 dependence
    g25_2018_2025 = g_rets[25].loc["2018-01-01":"2025-12-31"]
    m25_2018_2025 = m_rets[25].loc["2018-01-01":"2025-12-31"]
    c1, _, _, _ = calc_metrics(g25_2018_2025)
    c2, _, _, _ = calc_metrics(m25_2018_2025)
    md += f"\\n## 5. G25 扣除 2026 的影响\\n"
    md += f"- **2018-2025 完整年度 CAGR**: **{c1:.2f}%** (混合基准 {c2:.2f}%，Active {c1-c2:+.2f}%)\\n"
    
    with open(OUT_MD, "w") as f:
        f.write(md)
    print(f"Results written to {OUT_MD}")

if __name__ == "__main__":
    run_phase_f1()
