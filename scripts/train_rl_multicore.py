import os
import numpy as np
import pandas as pd
import gymnasium as gym
from gymnasium import spaces
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import SubprocVecEnv, DummyVecEnv
import multiprocessing
import warnings
warnings.filterwarnings('ignore')

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "processed", "ai_training_dataset.parquet")

class PortfolioEnv(gym.Env):
    """
    自定义强化学习交易环境 (按月调仓)
    """
    def __init__(self, df, is_training=True):
        super(PortfolioEnv, self).__init__()
        
        # 定义可用资产 (7核心 + 避险长债 + 现金等价物)
        self.assets = ["TQQQ", "SOXL", "FAS", "CURE", "URTY", "DRN", "ERX", "TMF", "BIL"]
        self.num_assets = len(self.assets)
        
        # 准备数据 (Pivot 宽表)
        self.dates, self.features, self.returns = self._prepare_data(df)
        self.max_steps = len(self.dates) - 1
        
        # 动作空间: 连续值 [-1, 1]，后续通过 Softmax 转换为仓位比例 (0~100%)
        self.action_space = spaces.Box(low=-1, high=1, shape=(self.num_assets,), dtype=np.float32)
        
        # 状态空间: 每只资产 6 个特征 (动量, 波动, Z-score, 宏观等)
        obs_dim = self.features.shape[1]
        self.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(obs_dim,), dtype=np.float32)
        
        self.is_training = is_training
        self.current_step = 0
        self.portfolio_value = 1.0
        self.history = []

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
        self.history = [(self.dates[self.current_step], self.portfolio_value)]
        return self.features[self.current_step].astype(np.float32), {}

    def step(self, action):
        exp_a = np.exp(action)
        weights = exp_a / np.sum(exp_a)
        
        future_returns = self.returns[self.current_step]
        portfolio_return = np.sum(weights * future_returns)
        self.portfolio_value *= (1 + portfolio_return)
        
        reward = np.log(1 + portfolio_return)
        if portfolio_return < -0.10:
            reward -= 0.5 
            
        self.current_step += 21
        done = self.current_step >= self.max_steps
        truncated = False
        
        if not done:
            self.history.append((self.dates[self.current_step], self.portfolio_value))
            next_obs = self.features[self.current_step].astype(np.float32)
        else:
            next_obs = self.features[-1].astype(np.float32)
            
        info = {'portfolio_value': self.portfolio_value, 'date': self.dates[self.current_step] if not done else self.dates[-1]}
        return next_obs, float(reward), done, truncated, info


def make_env(df, is_training):
    """
    Utility function for multiprocess env.
    """
    def _init():
        return PortfolioEnv(df, is_training)
    return _init

def train_and_evaluate_rl():
    print("Loading data for RL...")
    df = pd.read_parquet(DATA_PATH)
    
    train_df = df[df.index < '2022-01-01'].copy()
    test_df  = df[df.index >= '2022-01-01'].copy()
    
    # 获取 CPU 核心数，留出 2 个核心给其他系统进程
    num_cpu = max(1, multiprocessing.cpu_count() - 2)
    print(f"Initializing Vectorized Environment with {num_cpu} parallel CPU cores...")
    
    # 向量化训练环境
    train_env = SubprocVecEnv([make_env(train_df, True) for i in range(num_cpu)])
    # 测试环境不需要并行
    test_env = DummyVecEnv([make_env(test_df, False)])
    
    print("\nInitializing PPO Agent...")
    # 调整 batch_size 和 n_steps 以适配多核并行 (batch_size 应该是并行数和 n_steps 的某种合理组合)
    # n_steps 表示每个环境收集多少步数据，总的 buffer 规模 = n_steps * num_cpu
    model = PPO("MlpPolicy", train_env, verbose=1, learning_rate=0.0003, n_steps=2048, batch_size=256, ent_coef=0.01)
    
    print("Training PPO Agent (Simulating millions of trading days)...")
    model.learn(total_timesteps=5000000)
    print("Training Complete!")
    
    print("\n==============================================")
    print("RL Agent OOS Backtest (2022-01 to 2026-07)")
    print("==============================================")
    
    obs = test_env.reset()
    done = False
    
    while not done:
        action, _states = model.predict(obs, deterministic=True)
        obs, reward, done, info = test_env.step(action)
    
    final_value = info[0]['portfolio_value']
    total_return = final_value - 1
    cagr = (final_value ** (1 / 4.5)) - 1
    
    print(f"Total Return: {total_return:.2%}")
    print(f"CAGR:         {cagr:.2%}")
    print("==============================================")

if __name__ == "__main__":
    train_and_evaluate_rl()
