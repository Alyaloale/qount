import os
import numpy as np
import pandas as pd
import gymnasium as gym
from gymnasium import spaces
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv
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
        # 过滤并透视数据
        df_assets = df[df['Ticker'].isin(self.assets)].copy()
        features_list = ['return_21d', 'return_90d', 'volatility_21d', 'z_score_200d', 'macro_vix', 'macro_tnx']
        
        # 透视特征矩阵
        pivot_feat = df_assets.pivot_table(index=df_assets.index, columns='Ticker', values=features_list)
        pivot_feat.fillna(0, inplace=True) # 缺失值补0
        
        # 透视未来收益矩阵 (用于计算环境 Reward)
        pivot_ret = df_assets.pivot_table(index=df_assets.index, columns='Ticker', values='target_fwd_return_21d')
        pivot_ret.fillna(0, inplace=True)
        
        # 对齐日期
        common_dates = pivot_feat.index.intersection(pivot_ret.index)
        pivot_feat = pivot_feat.loc[common_dates]
        pivot_ret = pivot_ret.loc[common_dates]
        
        # 将 MultiIndex columns 展平为 1D vector 特征
        feat_array = pivot_feat.values 
        ret_array = pivot_ret[self.assets].values # 确保按 assets 列表顺序
        dates = common_dates.tolist()
        
        return dates, feat_array, ret_array

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        # 如果是训练模式，随机选择一个起点，增加样本多样性；如果是回测，从0开始
        if self.is_training:
            self.current_step = np.random.randint(0, self.max_steps // 2)
        else:
            self.current_step = 0
            
        self.portfolio_value = 1.0
        self.history = [(self.dates[self.current_step], self.portfolio_value)]
        
        return self.features[self.current_step].astype(np.float32), {}

    def step(self, action):
        # 1. 解析动作 (Softmax 保证仓位和为1，且没有做空)
        exp_a = np.exp(action)
        weights = exp_a / np.sum(exp_a)
        
        # 2. 获取真实的未来21天收益率
        future_returns = self.returns[self.current_step]
        
        # 3. 计算投资组合收益 (假设每 21 个交易日也就是约一个月调仓一次)
        portfolio_return = np.sum(weights * future_returns)
        self.portfolio_value *= (1 + portfolio_return)
        
        # 4. 设计奖励函数 (Reward)
        # 核心：复利最大化 (使用对数收益)
        reward = np.log(1 + portfolio_return)
        
        # 惩罚极端回撤：如果单月跌超 10%，给予额外惩罚，逼迫 Agent 学会防守
        if portfolio_return < -0.10:
            reward -= 0.5 
            
        # 5. 时间推进
        # 在这里我们步进 21 天，模拟真实的按月调仓！
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

def train_and_evaluate_rl():
    print("Loading data for RL...")
    df = pd.read_parquet(DATA_PATH)
    
    # 划分数据集 (时间序列)
    train_df = df[df.index < '2022-01-01'].copy()
    test_df  = df[df.index >= '2022-01-01'].copy() # 用 2022-2026 做 OOS 盲测
    
    # 构建环境
    train_env = DummyVecEnv([lambda: PortfolioEnv(train_df, is_training=True)])
    test_env = DummyVecEnv([lambda: PortfolioEnv(test_df, is_training=False)])
    
    print("\nInitializing PPO Agent...")
    model = PPO("MlpPolicy", train_env, verbose=0, learning_rate=0.0003, n_steps=2048, batch_size=64, ent_coef=0.01)
    
    print("Training PPO Agent on Mac M4 (Simulating millions of trading days)...")
    model.learn(total_timesteps=5000000)
    print("Training Complete!")
    
    print("\n==============================================")
    print("RL Agent OOS Backtest (2022-01 to 2026-07)")
    print("==============================================")
    
    # 在测试集上进行纯盲盒回测
    obs = test_env.reset()
    done = False
    
    while not done:
        action, _states = model.predict(obs, deterministic=True)
        obs, reward, done, info = test_env.step(action)
    
    final_value = info[0]['portfolio_value']
    total_return = final_value - 1
    cagr = (final_value ** (1 / 4.5)) - 1 # 2022~2026 约 4.5年
    
    print(f"Total Return: {total_return:.2%}")
    print(f"CAGR:         {cagr:.2%}")
    print("==============================================")
    print("NOTE: PPO creates fully dynamic allocations across 9 assets based on state.")

if __name__ == "__main__":
    train_and_evaluate_rl()
