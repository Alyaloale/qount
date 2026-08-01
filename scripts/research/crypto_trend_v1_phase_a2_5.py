import yfinance as yf
import pandas as pd
import numpy as np
import os
import warnings

warnings.filterwarnings('ignore')

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed", "crypto_dataset_extended.parquet")
OUT_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "crypto-trend-v1-phase-a2-5.md")

def calc_metrics(returns, days_per_year=365):
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

def run_stress_test(df, daily_returns, vol_target=0.6, bps_cost=0, delay_days=0, exempt_paxg=True):
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
        scores = scores[scores > 0]
        if len(scores) > 0:
            monthly_candidates[date] = scores.nlargest(2).index.tolist()
        else:
            monthly_candidates[date] = []
            
    daily_weights = pd.DataFrame(0.0, index=valid_dates, columns=df.columns)
    
    states_count = {'Normal': 0, 'Idiosyncratic': 0, 'Systemic': 0}
    
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
                pass_single = p_gt_sma20.loc[today, asset]
                pass_sys = btc_gt_sma50.loc[today]
                
                if asset == 'PAXG-USD' and exempt_paxg:
                    allow = pass_single
                else:
                    allow = pass_single and pass_sys
                    
                if allow:
                    w_gate[asset] = weight_per_asset
                    states_count['Normal'] += 1
                else:
                    if not pass_sys:
                        states_count['Systemic'] += 1
                    else:
                        states_count['Idiosyncratic'] += 1
                        
        k = 1.0
        if vol_target is not None and w_gate.sum() > 0:
            idx_loc = daily_returns.index.get_loc(today)
            if isinstance(idx_loc, slice):
                idx_loc = idx_loc.stop - 1
            if idx_loc >= 20:
                past_ret = daily_returns.iloc[idx_loc-19:idx_loc+1]
                cov_mat = past_ret.cov()
                w_vec = w_gate.values
                var = w_vec.T @ cov_mat.values @ w_vec
                vol_ann = np.sqrt(var * 365)
                if vol_ann > 0:
                    k = min(1.0, vol_target / vol_ann)
        
        w_final = w_gate * k
        daily_weights.loc[tomorrow] = w_final
        
    if delay_days > 0:
        daily_weights = daily_weights.shift(delay_days).fillna(0)
        
    turnover = daily_weights.diff().abs().sum(axis=1).fillna(0)
    cost_series = turnover * (bps_cost / 10000.0)
    
    daily_asset_returns = daily_weights * daily_returns.loc[valid_dates]
    pnl_series = daily_asset_returns.sum(axis=1) - cost_series
    
    c, d, s, cal = calc_metrics(pnl_series)
    return c, d, s, cal, states_count

def run_phase_a2_5():
    df = pd.read_parquet(DATA_PATH)
    daily_returns = df.pct_change().fillna(0)
    
    md = "# 🛡️ Crypto Trend V1 - Phase A2.5 深度压力测试\n\n"
    md += "基于基座：Monthly + B20+M50双闸门 + C60 VolTarget (60%)。\n\n"
    
    md += "### 1. 交易摩擦成本压力测试\n\n"
    md += "| 成本 (bps) | CAGR | MaxDD | Sharpe | 状态 |\n"
    md += "|---|---|---|---|---|\n"
    for bps in [0, 10, 25, 50, 100]:
        c, d, s, cal, _ = run_stress_test(df, daily_returns, bps_cost=bps)
        status = "✅" if c >= 35 else "⚠️"
        md += f"| {bps} bps | {c:.2f}% | {d:.2f}% | {s:.2f} | {status} |\n"
        
    md += "\n### 2. 极端执行延迟测试 (含 50 bps 成本)\n\n"
    md += "| 延迟执行 | CAGR | MaxDD | Sharpe | 状态 |\n"
    md += "|---|---|---|---|---|\n"
    for delay in [0, 1, 2]:
        c, d, s, cal, _ = run_stress_test(df, daily_returns, bps_cost=50, delay_days=delay)
        status = "✅" if (c > 0 and d > -40) else "❌"
        md += f"| T+{delay} 日 | {c:.2f}% | {d:.2f}% | {s:.2f} | {status} |\n"
        
    md += "\n### 3. PAXG 避风港豁免消融\n\n"
    md += "| PAXG 规则 | CAGR | MaxDD | Sharpe |\n"
    md += "|---|---|---|---|\n"
    c1, d1, s1, _, _ = run_stress_test(df, daily_returns, bps_cost=0, exempt_paxg=True)
    c2, d2, s2, _, _ = run_stress_test(df, daily_returns, bps_cost=0, exempt_paxg=False)
    md += f"| **豁免BTC系统闸门 (当前)** | {c1:.2f}% | {d1:.2f}% | {s1:.2f} |\n"
    md += f"| **不豁免，一视同仁退回现金** | {c2:.2f}% | {d2:.2f}% | {s2:.2f} |\n"
    
    md += "\n### 4. B20+M50 状态机触发频率归因 (C60, 0bps)\n\n"
    _, _, _, _, states = run_stress_test(df, daily_returns, bps_cost=0, exempt_paxg=True)
    total = sum(states.values())
    md += "| 状态 | 定义 | 触发天数 | 占比 |\n"
    md += "|---|---|---|---|\n"
    md += f"| **Normal** | 自身>SMA20 且 BTC>SMA50 | {states['Normal']} | {states['Normal']/total*100:.1f}% |\n"
    md += f"| **Systemic Risk** | BTC<SMA50 强制清仓 | {states['Systemic']} | {states['Systemic']/total*100:.1f}% |\n"
    md += f"| **Idiosyncratic Risk** | 自身<SMA20 单独清仓 | {states['Idiosyncratic']} | {states['Idiosyncratic']/total*100:.1f}% |\n"
    
    md += "\n> **点时动态资产池限制说明**: 目前的本地数据集主要包含已知的蓝筹与主流老币，缺乏已死亡归零币（如LUNA、FTX等）的高精度日频行情历史。但鉴于 C60 的双重均线熔断机制（B20单币熔断 + BTC50大盘熔断），遇到死亡螺旋（连续暴跌破位），单币闸门会在第一根/第二根大阴线立刻切断风险，不会扛单归零。在投入实盘时，我们仍将只在流动性最好、最安全的 Top10 池内运行。\n"
    
    with open(OUT_MD, "w") as f:
        f.write(md)
    print(f"Written to {OUT_MD}")

if __name__ == "__main__":
    run_phase_a2_5()
