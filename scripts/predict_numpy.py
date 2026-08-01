import os
import pickle
import numpy as np
import pandas as pd

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "models", "jax_live_ppo.pkl")
DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "processed", "ai_training_dataset.parquet")

def leaky_relu(x, alpha=0.01):
    return np.maximum(alpha * x, x)

def dense(x, kernel, bias):
    return np.dot(x, kernel) + bias

def predict_today():
    if not os.path.exists(MODEL_PATH):
        print("Live model not found! Train it first.")
        return
        
    print("Loading live model weights (Pure NumPy)...")
    with open(MODEL_PATH, "rb") as f:
        payload = pickle.load(f)
        
    weights_dict = payload["model_weights"]
    mean_params = payload["scaler_mean"]
    std_params = payload["scaler_std"]
    assets = payload["assets"]
    
    print("Loading latest market data...")
    df = pd.read_parquet(DATA_PATH)
    
    df_assets = df[df['Ticker'].isin(assets)].copy()
    pivot_feat = df_assets.pivot_table(index=df_assets.index, columns='Ticker', values=['return_21d', 'return_90d', 'volatility_21d', 'z_score_200d', 'rsi_14d', 'macd_hist', 'macro_vix', 'macro_tnx'])
    pivot_feat.fillna(0, inplace=True)
    
    # Guarantee exact same column ordering as training
    pivot_feat = pivot_feat[payload["features"]]
    
    latest_date = pivot_feat.index[-1]
    print(f"Latest Market Date: {latest_date.date()}")
    
    latest_features_raw = pivot_feat.loc[latest_date].values
    
    # Standard scale using the exact parameters from training
    scaled_features = (latest_features_raw - mean_params) / std_params
    
    # Pure NumPy Forward Pass (no JAX dependency)
    # The Flax layer names for Actor Critic are usually Dense_0, Dense_1, Dense_2, etc.
    # Actor network: Dense_0 (256) -> LeakyRelu -> Dense_1 (128) -> LeakyRelu -> Dense_2 (action_dim)
    w0 = weights_dict['params']['Dense_0']['kernel']
    b0 = weights_dict['params']['Dense_0']['bias']
    w1 = weights_dict['params']['Dense_1']['kernel']
    b1 = weights_dict['params']['Dense_1']['bias']
    w2 = weights_dict['params']['Dense_2']['kernel']
    b2 = weights_dict['params']['Dense_2']['bias']
    
    x = scaled_features
    x = dense(x, w0, b0)
    x = leaky_relu(x)
    x = dense(x, w1, b1)
    x = leaky_relu(x)
    action_logits = dense(x, w2, b2)
    
    # Apply softmax to get allocation percentages
    exp_a = np.exp(action_logits - np.max(action_logits)) # Subtract max for numerical stability
    allocations = exp_a / np.sum(exp_a)
    
    print("\n==================================================")
    print(f"🤖 AI QUANT ALLOCATION FOR {latest_date.date()}")
    print("==================================================")
    
    alloc_df = pd.DataFrame({
        "Asset": assets,
        "Allocation": allocations
    }).sort_values(by="Allocation", ascending=False)
    
    for _, row in alloc_df.iterrows():
        print(f"🔹 {row['Asset']:<6}: {row['Allocation']:.2%}")
        
    print("==================================================\n")

if __name__ == "__main__":
    predict_today()
