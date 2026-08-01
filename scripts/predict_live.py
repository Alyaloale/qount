import os
import pickle
import pandas as pd
import numpy as np
import jax
import jax.numpy as jnp
import flax.linen as nn

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "models", "jax_live_ppo.pkl")
DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "processed", "ai_training_dataset.parquet")

class ActorCritic(nn.Module):
    action_dim: int

    @nn.compact
    def __call__(self, x):
        actor = nn.Dense(256)(x)
        actor = nn.leaky_relu(actor)
        actor = nn.Dense(128)(actor)
        actor = nn.leaky_relu(actor)
        actor_mean = nn.Dense(self.action_dim)(actor)
        return actor_mean

def predict_today():
    if not os.path.exists(MODEL_PATH):
        print("Live model not found! Train it first.")
        return
        
    print("Loading live model weights...")
    with open(MODEL_PATH, "rb") as f:
        payload = pickle.load(f)
        
    weights_dict = payload["model_weights"]
    mean_params = payload["scaler_mean"]
    std_params = payload["scaler_std"]
    assets = payload["assets"]
    # We ignore payload["features"] because it's a MultiIndex of tuples
    features_list = ['return_21d', 'return_90d', 'volatility_21d', 'z_score_200d', 'rsi_14d', 'macd_hist', 'macro_vix', 'macro_tnx']
    
    print("Loading latest market data...")
    df = pd.read_parquet(DATA_PATH)
    
    # We want to predict based on the very last day in the dataset
    df_assets = df[df['Ticker'].isin(assets)].copy()
    pivot_feat = df_assets.pivot_table(index=df_assets.index, columns='Ticker', values=features_list)
    pivot_feat.fillna(0, inplace=True)
    
    # Guarantee exact same column ordering as training
    pivot_feat = pivot_feat[payload["features"]]
    
    latest_date = pivot_feat.index[-1]
    print(f"Latest Market Date: {latest_date.date()}")
    
    latest_features_raw = pivot_feat.loc[latest_date].values
    
    # Standard scale using the exact parameters from training
    scaled_features = (latest_features_raw - mean_params) / std_params
    
    # Run through JAX Neural Network
    network = ActorCritic(action_dim=len(assets))
    
    # We only need the mean from the Actor network (deterministic inference)
    action_logits = network.apply(weights_dict, jnp.array(scaled_features, dtype=jnp.float32))
    
    # Apply softmax to get allocation percentages
    exp_a = jnp.exp(action_logits)
    allocations = exp_a / jnp.sum(exp_a)
    
    print("\n==================================================")
    print(f"🤖 AI QUANT ALLOCATION FOR {latest_date.date()}")
    print("==================================================")
    
    alloc_df = pd.DataFrame({
        "Asset": assets,
        "Allocation": np.array(allocations)
    }).sort_values(by="Allocation", ascending=False)
    
    for _, row in alloc_df.iterrows():
        print(f"🔹 {row['Asset']:<6}: {row['Allocation']:.2%}")
        
    print("==================================================\n")

if __name__ == "__main__":
    predict_today()
