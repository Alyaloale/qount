import os
import numpy as np
import pandas as pd
import gymnasium as gym
from gymnasium import spaces
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv
import torch.nn as nn
from typing import Callable
import multiprocessing
import warnings
warnings.filterwarnings('ignore')

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "processed", "ai_training_dataset.parquet")
REPORT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "experiments_v4_report.txt")

class PortfolioEnv(gym.Env):
    def __init__(self, df, is_training=True, penalty_enabled=True, slip_rate=0.002):
        super(PortfolioEnv, self).__init__()
        
        self.assets = ["TQQQ", "SOXL", "FAS", "CURE", "URTY", "DRN", "ERX", "TMF", "BIL"]
        self.num_assets = len(self.assets)
        
        self.dates, self.features, self.returns = self._prepare_data(df)
        self.max_steps = len(self.dates) - 1
        
        self.action_space = spaces.Box(low=-1, high=1, shape=(self.num_assets,), dtype=np.float32)
        obs_dim = self.features.shape[1]
        self.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(obs_dim,), dtype=np.float32)
        
        self.is_training = is_training
        self.penalty_enabled = penalty_enabled
        self.slip_rate = slip_rate
        
        self.current_step = 0
        self.portfolio_value = 1.0
        self.previous_weights = None

    def _prepare_data(self, df):
        df_assets = df[df['Ticker'].isin(self.assets)].copy()
        features_list = ['return_21d', 'return_90d', 'volatility_21d', 'z_score_200d', 'macro_vix', 'macro_tnx']
        
        pivot_feat = df_assets.pivot_table(index=df_assets.index, columns='Ticker', values=features_list)
        pivot_feat.fillna(0, inplace=True)
        
        pivot_ret = df_assets.pivot_table(index=df_assets.index, columns='Ticker', values='target_fwd_return_21d')
        pivot_ret.fillna(0, inplace=True)
        
        common_dates = pivot_feat.index.intersection(pivot_ret.index)
        pivot_feat = pivot_feat.loc[common_dates]
        pivot_ret = pivot_ret.loc[common_dates]
        
        feat_array = pivot_feat.values 
        ret_array = pivot_ret[self.assets].values
        dates = common_dates.tolist()
        
        return dates, feat_array, ret_array

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        if self.is_training:
            self.current_step = np.random.randint(0, self.max_steps // 2)
        else:
            self.current_step = 0
            
        self.portfolio_value = 1.0
        self.previous_weights = np.zeros(self.num_assets)
        self.previous_weights[-1] = 1.0
        return self.features[self.current_step].astype(np.float32), {}

    def step(self, action):
        exp_a = np.exp(action)
        weights = exp_a / np.sum(exp_a)
        
        turnover = np.sum(np.abs(weights - self.previous_weights))
        transaction_cost = turnover * self.slip_rate
        
        future_returns = self.returns[self.current_step]
        portfolio_return = np.sum(weights * future_returns)
        
        net_return = portfolio_return - transaction_cost
        
        if net_return <= -1.0:
            net_return = -0.9999
            
        self.portfolio_value *= (1 + net_return)
        
        reward = np.log(1 + net_return)
        
        if self.penalty_enabled and net_return < -0.10:
            reward -= 0.2 
            
        self.previous_weights = weights
        self.current_step += 21
        
        done = self.current_step >= self.max_steps
        truncated = False
        
        if not done:
            next_obs = self.features[self.current_step].astype(np.float32)
        else:
            next_obs = self.features[-1].astype(np.float32)
            
        info = {'portfolio_value': self.portfolio_value, 'date': self.dates[self.current_step] if not done else self.dates[-1]}
        return next_obs, float(reward), done, truncated, info

def make_env(df, is_training):
    def _init():
        return PortfolioEnv(df, is_training=is_training, penalty_enabled=True, slip_rate=0.002)
    return _init

def linear_schedule(initial_value: float) -> Callable[[float], float]:
    """Linear learning rate schedule."""
    def func(progress_remaining: float) -> float:
        return progress_remaining * initial_value
    return func

def main():
    df = pd.read_parquet(DATA_PATH)
    train_df = df[df.index < '2022-01-01'].copy()
    test_df  = df[df.index >= '2022-01-01'].copy()
    
    print("\n========== STARTING EXPERIMENT: V4_DeepArch_CPU_Optimized ==========")
    
    # Use DummyVecEnv for stability
    train_env = DummyVecEnv([make_env(train_df, True)])
    test_env = DummyVecEnv([make_env(test_df, False)])
    
    # Advanced Network Architecture: 
    # Deeper layers (256, 128) and LeakyReLU for better non-linear financial modeling
    policy_kwargs = dict(
        activation_fn=nn.LeakyReLU,
        net_arch=dict(pi=[256, 128], vf=[256, 128])
    )
    
    # Hyperparameter tuning for 30%+ CAGR:
    # 1. Linear LR decay (starts at 5e-4, drops to 0 over training)
    # 2. Higher ent_coef (0.02) to force exploration of different asset combinations
    # 3. gamma=0.999 (longer term horizon)
    # 4. device="cpu" - For small MLPs, CPU is often FASTER than CUDA because it avoids PCIe transfer latency overhead.
    model = PPO("MlpPolicy", train_env, verbose=1, 
                learning_rate=linear_schedule(0.0005), 
                n_steps=4096, 
                batch_size=512, 
                gamma=0.999,
                ent_coef=0.02,
                policy_kwargs=policy_kwargs,
                device="cpu") # Force CPU to maximize FPS for small networks
                
    model.learn(total_timesteps=5000000)
    
    obs = test_env.reset()
    done = False
    while not done:
        action, _states = model.predict(obs, deterministic=True)
        obs, reward, done, info = test_env.step(action)
    
    final_value = info[0]['portfolio_value']
    total_return = final_value - 1
    cagr = (final_value ** (1 / 4.5)) - 1
    
    result_str = f"Experiment [V4_DeepArch_CPU_Optimized]\nTotal Return: {total_return:.2%}\nCAGR: {cagr:.2%}\n\n"
    print(result_str)
    
    with open(REPORT_PATH, "w") as f:
        f.write(result_str)

if __name__ == "__main__":
    main()
