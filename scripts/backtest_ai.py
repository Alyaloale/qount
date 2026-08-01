import pandas as pd
import numpy as np
import os
import lightgbm as lgb
import warnings
warnings.filterwarnings('ignore')

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "processed", "ai_training_dataset.parquet")

def run_backtest():
    print("Loading AI dataset...")
    df = pd.read_parquet(DATA_PATH)
    df.sort_index(inplace=True)
    df.dropna(subset=['target_fwd_return_21d'], inplace=True)
    
    features = ['daily_return', 'return_21d', 'return_90d', 'return_126d', 'return_252d', 'volatility_21d', 'z_score_200d', 'macro_vix', 'macro_tnx']
    target = 'target_fwd_return_21d'
    
    # 按照 2024-01-01 切分
    train_df = df[df.index < '2023-01-01']
    val_df   = df[(df.index >= '2023-01-01') & (df.index < '2024-01-01')]
    test_df  = df[df.index >= '2024-01-01'].copy()
    
    # 训练模型 (静默模式)
    print("Training LightGBM on Mac M4...")
    train_data = lgb.Dataset(train_df[features], label=train_df[target])
    val_data = lgb.Dataset(val_df[features], label=val_df[target], reference=train_data)
    
    params = {'objective': 'regression', 'metric': 'rmse', 'boosting_type': 'gbdt', 'learning_rate': 0.05, 'num_leaves': 31, 'verbose': -1, 'random_state': 42}
    model = lgb.train(params, train_data, num_boost_round=1000, valid_sets=[train_data, val_data], callbacks=[lgb.early_stopping(stopping_rounds=50, verbose=False)])
    
    # 对回测集(2024+)进行预测
    test_df['predicted_return_21d'] = model.predict(test_df[features])
    
    # ==========================
    # 策略回测逻辑 (Out-Of-Sample)
    # ==========================
    # 获取所有的交易日 (以SPY为基准获取交易日历)
    test_dates = sorted(test_df.index.unique())
    
    portfolio_ai = 1.0       # AI 策略初始净值
    portfolio_base = 1.0     # Baseline(原策略)初始净值
    
    ai_history = []
    base_history = []
    
    # 每 21 个交易日（约一个月）调仓一次
    rebalance_freq = 21
    
    for i in range(0, len(test_dates) - rebalance_freq, rebalance_freq):
        current_date = test_dates[i]
        future_date = test_dates[i + rebalance_freq]
        
        # 获取调仓日的截面数据
        cross_section = test_df.loc[current_date]
        if isinstance(cross_section, pd.Series):
            cross_section = cross_section.to_frame().T
            
        # 过滤出核心的 7 个板块 (剔除宏观和对冲资产参与轮动)
        core_assets = ["TQQQ", "SOXL", "FAS", "CURE", "URTY", "DRN", "ERX"]
        cs_core = cross_section[cross_section['Ticker'].isin(core_assets)]
        
        if cs_core.empty:
            continue
            
        # ---------------------------
        # Baseline: 原版 90天动量策略
        # ---------------------------
        cs_core = cs_core.sort_values(by='return_90d', ascending=False)
        top2_base = cs_core.head(2)
        base_return = 0.0
        weight_per_asset = 1.0 / len(top2_base)
        for _, row in top2_base.iterrows():
            if row['return_90d'] > 0: # 绝对动量过滤
                base_return += row['target_fwd_return_21d'] * weight_per_asset
        
        portfolio_base *= (1 + base_return)
        
        # ---------------------------
        # AI Strategy: LightGBM 预测轮动
        # ---------------------------
        # AI不局限于7大板块，它也可以买避险资产如 TMF(美债) 和 UGL(黄金)
        investable_assets = core_assets + ["TMF", "UGL", "BIL"]
        cs_ai = cross_section[cross_section['Ticker'].isin(investable_assets)]
        cs_ai = cs_ai.sort_values(by='predicted_return_21d', ascending=False)
        
        top2_ai = cs_ai.head(2)
        ai_return = 0.0
        weight_per_asset = 1.0 / len(top2_ai)
        for _, row in top2_ai.iterrows():
            if row['predicted_return_21d'] > 0:
                ai_return += row['target_fwd_return_21d'] * weight_per_asset
            else:
                # 极端情况下如果所有资产预测均为负，AI空仓或持有现金等价物(假设收益率为0)
                pass
                
        portfolio_ai *= (1 + ai_return)
        
        ai_history.append((future_date, portfolio_ai))
        base_history.append((future_date, portfolio_base))
        
    ai_df = pd.DataFrame(ai_history, columns=['Date', 'NetValue']).set_index('Date')
    base_df = pd.DataFrame(base_history, columns=['Date', 'NetValue']).set_index('Date')
    
    # 打印最终对比
    print("\n==============================================")
    print("OOS Backtest Results (2024-01 to 2026-07)")
    print("==============================================")
    
    def calc_metrics(series):
        total_return = series.iloc[-1] - 1
        # 年化收益 (约2.5年)
        cagr = (series.iloc[-1] ** (1 / 2.5)) - 1
        # 最大回撤
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
    
    print(f"\n[AI LightGBM Strategy]")
    print(f"Total Return: {ai_tr:.2%}")
    print(f"CAGR:         {ai_cagr:.2%}")
    print(f"Max Drawdown: {ai_mdd:.2%}")
    print("==============================================")

if __name__ == "__main__":
    run_backtest()
