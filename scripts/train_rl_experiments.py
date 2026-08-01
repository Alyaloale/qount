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
REPORT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "experiments_report.txt")

class PortfolioEnv(gym.Env):
    def __init__(self, df, is_training=True, penalty_enabled=False, slip_rate=0.0):
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
        # Start with 100% in cash (BIL is the last asset)
        self.previous_weights = np.zeros(self.num_assets)
        self.previous_weights[-1] = 1.0
        
        self.history = [(self.dates[self.current_step], self.portfolio_value)]
        return self.features[self.current_step].astype(np.float32), {}

    def step(self, action):
        exp_a = np.exp(action)
        weights = exp_a / np.sum(exp_a)
        
        turnover = np.sum(np.abs(weights - self.previous_weights))
        transaction_cost = turnover * self.slip_rate
        
        future_returns = self.returns[self.current_step]
        portfolio_return = np.sum(weights * future_returns)
        
        net_return = portfolio_return - transaction_cost
        
        # Clamp net_return to prevent portfolio value going <= 0 and causing NaN in np.log
        if net_return <= -1.0:
            net_return = -0.9999
            
        self.portfolio_value *= (1 + net_return)
        
        # Reward is log return
        reward = np.log(1 + net_return)
        
        # Drawdown penalty if enabled (weakened to -0.2)
        if self.penalty_enabled and net_return < -0.10:
            reward -= 0.2 
            
        self.previous_weights = weights
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


def make_env(df, is_training, penalty, slip):
    def _init():
        return PortfolioEnv(df, is_training, penalty_enabled=penalty, slip_rate=slip)
    return _init

def run_experiment(exp_name, train_df, test_df, penalty, slip):
    print(f"\n========== STARTING EXPERIMENT: {exp_name} ==========")
    # DummyVecEnv is faster because IPC overhead of SubprocVecEnv is higher than env step time
    # This also prevents WSL Wsl/Service/E_UNEXPECTED crashes due to shared memory limits
    train_env = DummyVecEnv([make_env(train_df, True, penalty, slip)])
    test_env = DummyVecEnv([make_env(test_df, False, penalty, slip)])
    
    model = PPO("MlpPolicy", train_env, verbose=1, learning_rate=0.0003, n_steps=2048, batch_size=256, ent_coef=0.01)
    model.learn(total_timesteps=5000000)
    
    obs = test_env.reset()
    done = False
    while not done:
        action, _states = model.predict(obs, deterministic=True)
        obs, reward, done, info = test_env.step(action)
    
    final_value = info[0]['portfolio_value']
    total_return = final_value - 1
    cagr = (final_value ** (1 / 4.5)) - 1
    
    result_str = f"Experiment [{exp_name}]\nPenalty Enabled: {penalty} | Slippage Rate: {slip}\nTotal Return: {total_return:.2%}\nCAGR: {cagr:.2%}\n\n"
    print(result_str)
    
    with open(REPORT_PATH, "a") as f:
        f.write(result_str)
        
    train_env.close()
    test_env.close()

def main():
    # Do not delete the report file so V1 results are kept
    pass
        
    df = pd.read_parquet(DATA_PATH)
    train_df = df[df.index < '2022-01-01'].copy()
    test_df  = df[df.index >= '2022-01-01'].copy()
    
    with open(REPORT_PATH, "a") as f:
        f.write("\n\n--- RESUMING OVERNIGHT EXPERIMENTS ---\n\n")
    
    # Exp 1: Aggressive (No penalty, No friction) (ALREADY DONE)
    # run_experiment("V1_Aggressive_NoFriction", train_df, test_df, penalty=False, slip=0.0)
    
    # Exp 2: Realistic (No penalty, With friction 0.2%)
    run_experiment("V2_Aggressive_WithFriction", train_df, test_df, penalty=False, slip=0.002)
    
    # Exp 3: Balanced (Weakened penalty -0.2, With friction 0.2%)
    run_experiment("V3_Balanced_WithFriction", train_df, test_df, penalty=True, slip=0.002)

if __name__ == "__main__":
    main()
