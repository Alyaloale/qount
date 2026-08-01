import pandas as pd
import numpy as np
import os
import lightgbm as lgb
from sklearn.metrics import mean_squared_error, mean_absolute_error
import matplotlib.pyplot as plt

# 路径设置 (假设该脚本在 WSL 或 Mac 的 scripts 目录下运行)
DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "processed", "ai_training_dataset.parquet")

def train_lightgbm():
    print("Loading AI dataset...")
    df = pd.read_parquet(DATA_PATH)
    
    # 【严禁未来数据泄露】必须按时间戳排序
    df.sort_index(inplace=True)
    
    # 丢弃没有目标值的最近 21 天数据 (因为未来 21 天还没发生)
    df.dropna(subset=['target_fwd_return_21d'], inplace=True)
    
    # 定义特征列 (X) 和 目标列 (y)
    features = [
        'daily_return', 'return_21d', 'return_90d', 'return_126d', 'return_252d',
        'volatility_21d', 'z_score_200d', 'macro_vix', 'macro_tnx'
    ]
    target = 'target_fwd_return_21d'
    
    print(f"Features used: {features}")
    
    # 【严格区分验证和回测数据集】 - 时间序列绝对不能随机打乱 (No Random Shuffle)
    # 训练集: 2022年及以前
    # 验证集: 2023年 (用于早停 Early Stopping，防止过拟合)
    # 测试集/回测集: 2024年至今 (完全未见过的数据，用于最终策略回测评估)
    
    train_df = df[df.index < '2023-01-01']
    val_df   = df[(df.index >= '2023-01-01') & (df.index < '2024-01-01')]
    test_df  = df[df.index >= '2024-01-01']
    
    print(f"Train samples: {len(train_df)}")
    print(f"Val samples:   {len(val_df)}")
    print(f"Test samples:  {len(test_df)}")
    
    X_train, y_train = train_df[features], train_df[target]
    X_val, y_val     = val_df[features], val_df[target]
    X_test, y_test   = test_df[features], test_df[target]
    
    # 构建 LightGBM 数据集
    train_data = lgb.Dataset(X_train, label=y_train)
    val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
    
    # 参数设置 (Regression 任务预测真实收益率)
    params = {
        'objective': 'regression',
        'metric': 'rmse',
        'boosting_type': 'gbdt',
        'learning_rate': 0.05,
        'num_leaves': 31,
        'feature_fraction': 0.8,
        'verbose': -1,
        'random_state': 42
    }
    
    print("\nTraining LightGBM model...")
    # 使用 validation_sets 并在 early_stopping 回调中监控
    model = lgb.train(
        params,
        train_data,
        num_boost_round=1000,
        valid_sets=[train_data, val_data],
        callbacks=[lgb.early_stopping(stopping_rounds=50), lgb.log_evaluation(50)]
    )
    
    # 在 OOS 回测集上进行评估
    print("\nEvaluating on Out-Of-Sample (OOS) Test Set...")
    preds = model.predict(X_test, num_iteration=model.best_iteration)
    
    rmse = np.sqrt(mean_squared_error(y_test, preds))
    mae = mean_absolute_error(y_test, preds)
    print(f"Test RMSE: {rmse:.4f}")
    print(f"Test MAE:  {mae:.4f}")
    
    # 输出特征重要性
    importance = model.feature_importance(importance_type='gain')
    feature_imp = pd.DataFrame({'Feature': features, 'Gain': importance}).sort_values(by='Gain', ascending=False)
    print("\nFeature Importance (Top 5):")
    print(feature_imp.head(5))
    
    # 将预测结果合并回 test_df 方便后续写回测逻辑
    test_df_results = test_df.copy()
    test_df_results['predicted_return_21d'] = preds
    
    # 简单统计：当模型预测上涨时，实际上涨的概率 (Directional Accuracy)
    positive_preds = test_df_results[test_df_results['predicted_return_21d'] > 0]
    win_rate = (positive_preds['target_fwd_return_21d'] > 0).mean()
    print(f"\nDirectional Accuracy (When model predicts > 0, actual > 0): {win_rate:.2%}")
    
    return model, test_df_results

if __name__ == "__main__":
    train_lightgbm()
