import pandas as pd
import numpy as np
import os
import lightgbm as lgb
import warnings
from sklearn.metrics import classification_report
warnings.filterwarnings('ignore')

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "processed", "ai_training_dataset.parquet")

def run_classifier_backtest():
    print("Loading AI dataset...")
    df = pd.read_parquet(DATA_PATH)
    df.sort_index(inplace=True)
    df.dropna(subset=['target_fwd_return_21d'], inplace=True)
    
    # 重新定义目标：是否发生 -15% 以上的暴跌 (1 为暴跌，0 为安全)
    df['is_crash'] = (df['target_fwd_return_21d'] <= -0.15).astype(int)
    
    features = ['daily_return', 'return_21d', 'return_90d', 'return_126d', 'return_252d', 'volatility_21d', 'z_score_200d', 'macro_vix', 'macro_tnx']
    target = 'is_crash'
    
    # 压力测试: 测试 2022 年股债双杀熊市
    train_df = df[df.index < '2020-01-01']
    val_df   = df[(df.index >= '2020-01-01') & (df.index < '2021-01-01')]
    test_df  = df[(df.index >= '2021-01-01') & (df.index < '2023-12-31')].copy()
    
    print(f"Crash samples in Train: {train_df['is_crash'].sum()} / {len(train_df)}")
    
    # 训练分类器 (处理样本不平衡 is_unbalance=True)
    print("Training LightGBM Classifier on Mac M4...")
    train_data = lgb.Dataset(train_df[features], label=train_df[target])
    val_data = lgb.Dataset(val_df[features], label=val_df[target], reference=train_data)
    
    params = {
        'objective': 'binary', 
        'metric': 'auc', 
        'boosting_type': 'gbdt', 
        'learning_rate': 0.05, 
        'num_leaves': 15,       # 降低树的深度防止过拟合
        'is_unbalance': True,   # 因为暴跌是少数事件，必须开启不平衡处理
        'verbose': -1, 
        'random_state': 42
    }
    
    model = lgb.train(
        params, train_data, num_boost_round=1000, 
        valid_sets=[train_data, val_data], 
        callbacks=[lgb.early_stopping(stopping_rounds=50, verbose=False)]
    )
    
    # 获取验证集AUC
    test_df['crash_prob'] = model.predict(test_df[features])
    
    # ==========================
    # 混合策略回测逻辑 
    # ==========================
    test_dates = sorted(test_df.index.unique())
    portfolio_ai = 1.0       # 混合策略净值
    portfolio_base = 1.0     # 原策略净值
    ai_history, base_history = [], []
    
    rebalance_freq = 21
    CRASH_THRESHOLD = 0.25   # 降低阈值：预测暴跌概率大于 25% 时就触发防守
    
    for i in range(0, len(test_dates) - rebalance_freq, rebalance_freq):
        current_date = test_dates[i]
        future_date = test_dates[i + rebalance_freq]
        
        cross_section = test_df.loc[current_date]
        if isinstance(cross_section, pd.Series):
            cross_section = cross_section.to_frame().T
            
        core_assets = ["TQQQ", "SOXL", "FAS", "CURE", "URTY", "DRN", "ERX"]
        cs_core = cross_section[cross_section['Ticker'].isin(core_assets)]
        
        if cs_core.empty:
            continue
            
        # ---------- 原策略 (90天动量) ----------
        cs_core = cs_core.sort_values(by='return_90d', ascending=False)
        top2_base = cs_core.head(2)
        base_return = 0.0
        
        # 寻找 TMF (避险债券) 的未来收益，如果没有则假定为 0 (现金)
        tmf_row = cross_section[cross_section['Ticker'] == 'TMF']
        tmf_fwd_ret = tmf_row['target_fwd_return_21d'].values[0] if not tmf_row.empty else 0.0
        
        weight_per_asset = 1.0 / len(top2_base)
        for _, row in top2_base.iterrows():
            if row['return_90d'] > 0:
                base_return += row['target_fwd_return_21d'] * weight_per_asset
        portfolio_base *= (1 + base_return)
        
        # ---------- AI 辅助安全网策略 ----------
        ai_return = 0.0
        for _, row in top2_base.iterrows():
            # 只有当原始动量 > 0 时才考虑买入
            if row['return_90d'] > 0:
                # 触发 AI 安全网检查
                if row['crash_prob'] > CRASH_THRESHOLD:
                    # 警报！预测即将暴跌，强制买入 TMF 避险
                    ai_return += tmf_fwd_ret * weight_per_asset
                else:
                    # 正常安全，跟随动量猛干
                    ai_return += row['target_fwd_return_21d'] * weight_per_asset
                    
        portfolio_ai *= (1 + ai_return)
        
        ai_history.append((future_date, portfolio_ai))
        base_history.append((future_date, portfolio_base))
        
    ai_df = pd.DataFrame(ai_history, columns=['Date', 'NetValue']).set_index('Date')
    base_df = pd.DataFrame(base_history, columns=['Date', 'NetValue']).set_index('Date')
    
    print("\n==============================================")
    print("AI Safety Net Backtest (2024-01 to 2026-07)")
    print("==============================================")
    
    def calc_metrics(series):
        total_return = series.iloc[-1] - 1
        cagr = (series.iloc[-1] ** (1 / 2.5)) - 1
        roll_max = series.cummax()
        drawdown = series / roll_max - 1
        max_dd = drawdown.min()
        return total_return, cagr, max_dd
        
    ai_tr, ai_cagr, ai_mdd = calc_metrics(ai_df['NetValue'])
    base_tr, base_cagr, base_mdd = calc_metrics(base_df['NetValue'])
    
    print(f"[Original Strategy (90d Momentum)]")
    print(f"Total Return: {base_tr:.2%}")
    print(f"CAGR:         {base_cagr:.2%}")
    print(f"Max Drawdown: {base_mdd:.2%}")
    
    print(f"\n[Hybrid: Momentum + AI Crash Detection]")
    print(f"Total Return: {ai_tr:.2%}")
    print(f"CAGR:         {ai_cagr:.2%}")
    print(f"Max Drawdown: {ai_mdd:.2%}")
    print("==============================================")

if __name__ == "__main__":
    run_classifier_backtest()
