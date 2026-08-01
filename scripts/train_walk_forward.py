import os
import time
import jax
import jax.numpy as jnp
from flax import struct
import flax.linen as nn
import optax
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "processed", "ai_training_dataset.parquet")

# 1. Stateless JAX Environment
@struct.dataclass
class EnvState:
    current_step: jnp.ndarray
    portfolio_value: jnp.ndarray
    previous_weights: jnp.ndarray

@struct.dataclass
class EnvParams:
    features: jnp.ndarray
    returns: jnp.ndarray
    max_steps: int
    num_assets: int
    slip_rate: float
    penalty_enabled: bool

class JaxPortfolioEnv:
    def __init__(self, features, returns, penalty_enabled=True, slip_rate=0.002):
        self.num_assets = returns.shape[1]
        self.max_steps = features.shape[0] - 1
        
        self.default_params = EnvParams(
            features=jnp.array(features, dtype=jnp.float32),
            returns=jnp.array(returns, dtype=jnp.float32),
            max_steps=self.max_steps,
            num_assets=self.num_assets,
            slip_rate=slip_rate,
            penalty_enabled=penalty_enabled
        )

    def reset(self, key, params):
        start_step = jax.random.randint(key, shape=(), minval=0, maxval=params.max_steps // 2)
        init_weights = jnp.zeros(params.num_assets)
        init_weights = init_weights.at[-1].set(1.0) # Start in cash (BIL)
        
        state = EnvState(
            current_step=start_step,
            portfolio_value=jnp.float32(1.0),
            previous_weights=init_weights
        )
        return params.features[state.current_step], state

    def step(self, key, state, action, params):
        exp_a = jnp.exp(action)
        weights = exp_a / jnp.sum(exp_a)
        
        turnover = jnp.sum(jnp.abs(weights - state.previous_weights))
        transaction_cost = turnover * params.slip_rate
        
        future_returns = params.returns[state.current_step]
        portfolio_return = jnp.sum(weights * future_returns)
        
        net_return = portfolio_return - transaction_cost
        net_return = jnp.maximum(net_return, -0.9999)
        
        new_portfolio_value = state.portfolio_value * (1.0 + net_return)
        
        bil_return = future_returns[-1]
        excess_return = net_return - bil_return
        downside_risk = jnp.maximum(0.0, -excess_return)
        reward = excess_return - 2.0 * downside_risk 
        
        reward = jax.lax.cond(
            params.penalty_enabled & (net_return < -0.10),
            lambda: reward - 0.2,
            lambda: reward
        )
        
        new_step = state.current_step + 21
        done = new_step >= params.max_steps
        
        obs_idx = jnp.minimum(new_step, params.max_steps)
        next_obs = params.features[obs_idx]
        
        new_state = EnvState(
            current_step=new_step,
            portfolio_value=new_portfolio_value,
            previous_weights=weights
        )
        return next_obs, new_state, reward, done, {"portfolio_value": new_portfolio_value}

def auto_reset_step(env, key, state, action, params):
    next_obs, next_state, reward, done, info = env.step(key, state, action, params)
    reset_key, _ = jax.random.split(key)
    reset_obs, reset_state = env.reset(reset_key, params)
    
    real_next_obs = jax.lax.select(done, reset_obs, next_obs)
    real_next_state = EnvState(
        current_step=jax.lax.select(done, reset_state.current_step, next_state.current_step),
        portfolio_value=jax.lax.select(done, reset_state.portfolio_value, next_state.portfolio_value),
        previous_weights=jax.lax.select(done, reset_state.previous_weights, next_state.previous_weights)
    )
    return real_next_obs, real_next_state, reward, done, info

# 2. PPO Network
class ActorCritic(nn.Module):
    action_dim: int

    @nn.compact
    def __call__(self, x):
        actor = nn.Dense(256)(x)
        actor = nn.leaky_relu(actor)
        actor = nn.Dense(128)(actor)
        actor = nn.leaky_relu(actor)
        actor_mean = nn.Dense(self.action_dim)(actor)

        actor_log_std = self.param('log_std', nn.initializers.zeros, (self.action_dim,))
        actor_std = jnp.exp(actor_log_std)

        critic = nn.Dense(256)(x)
        critic = nn.leaky_relu(critic)
        critic = nn.Dense(128)(critic)
        critic = nn.leaky_relu(critic)
        critic = nn.Dense(1)(critic)

        return actor_mean, actor_std, jnp.squeeze(critic, axis=-1)

def gaussian_logprob(action, mean, std):
    var = std ** 2
    log_scale = jnp.log(std)
    return -0.5 * jnp.sum(((action - mean) ** 2) / var + 2 * log_scale + jnp.log(2 * jnp.pi), axis=-1)

def gaussian_entropy(std):
    return jnp.sum(0.5 + 0.5 * jnp.log(2 * jnp.pi) + jnp.log(std), axis=-1)

# 3. Main PPO Trainer Factory
def make_train_fn(env: JaxPortfolioEnv, hp_lr, hp_ent, total_timesteps=5_000_000, num_envs=64, num_steps=256):
    params = env.default_params
    num_updates = total_timesteps // (num_envs * num_steps)
    
    update_epochs = 4
    num_minibatches = 8
    batch_size = num_envs * num_steps
    minibatch_size = batch_size // num_minibatches
    
    def train(rng):
        network = ActorCritic(action_dim=params.num_assets)
        rng, init_rng = jax.random.split(rng)
        network_params = network.init(init_rng, jnp.zeros((params.features.shape[1],)))
        
        lr_schedule = optax.linear_schedule(init_value=hp_lr, end_value=1e-5, transition_steps=num_updates * update_epochs * num_minibatches)
        optimizer = optax.chain(
            optax.clip_by_global_norm(0.5),
            optax.adam(learning_rate=lr_schedule)
        )
        opt_state = optimizer.init(network_params)
        
        rng, env_rng = jax.random.split(rng)
        reset_rngs = jax.random.split(env_rng, num_envs)
        vmap_reset = jax.vmap(env.reset, in_axes=(0, None))
        obs, env_state = vmap_reset(reset_rngs, params)
        vmap_step = jax.vmap(auto_reset_step, in_axes=(None, 0, 0, 0, None))
        
        def _update_step(runner_state, unused):
            network_params, opt_state, obs, env_state, rng = runner_state
            
            def _env_step(carry, unused):
                obs, env_state, rng = carry
                rng, action_rng, step_rng = jax.random.split(rng, 3)
                
                mean, std, value = network.apply(network_params, obs)
                action = mean + std * jax.random.normal(action_rng, mean.shape)
                logprob = gaussian_logprob(action, mean, std)
                
                step_rngs = jax.random.split(step_rng, num_envs)
                next_obs, next_env_state, reward, done, info = vmap_step(env, step_rngs, env_state, action, params)
                
                transition = (obs, action, reward, value, logprob, done)
                return (next_obs, next_env_state, rng), transition

            (obs, env_state, rng), transitions = jax.lax.scan(_env_step, (obs, env_state, rng), None, length=num_steps)
            obs_batch, action_batch, reward_batch, value_batch, logprob_batch, done_batch = transitions
            
            _, _, next_value = network.apply(network_params, obs)
            gamma = 0.999
            gae_lambda = 0.95
            
            def _get_advantages(carry, transition):
                gae, next_value = carry
                reward, value, done = transition
                delta = reward + gamma * next_value * (1.0 - done) - value
                gae = delta + gamma * gae_lambda * (1.0 - done) * gae
                return (gae, value), gae
                
            _, advantages = jax.lax.scan(_get_advantages, (jnp.zeros(num_envs), next_value), (reward_batch, value_batch, done_batch), reverse=True)
            returns = advantages + value_batch
            
            b_obs = obs_batch.reshape(-1, obs_batch.shape[-1])
            b_act = action_batch.reshape(-1, action_batch.shape[-1])
            b_logprobs = logprob_batch.reshape(-1)
            b_adv = advantages.reshape(-1)
            b_ret = returns.reshape(-1)
            b_val = value_batch.reshape(-1)
            
            def _loss_fn(p, o, a, old_lp, adv, ret):
                m, s, v = network.apply(p, o)
                lp = gaussian_logprob(a, m, s)
                ent = gaussian_entropy(s).mean()
                
                ratio = jnp.exp(lp - old_lp)
                pg_loss1 = -adv * ratio
                pg_loss2 = -adv * jnp.clip(ratio, 1.0 - 0.2, 1.0 + 0.2)
                pg_loss = jnp.maximum(pg_loss1, pg_loss2).mean()
                v_loss = 0.5 * jnp.mean((ret - v) ** 2)
                
                loss = pg_loss + 0.5 * v_loss - hp_ent * ent
                return loss
                
            grad_fn = jax.value_and_grad(_loss_fn)
            
            def _update_epoch(update_state, unused):
                p, o_st, rng = update_state
                rng, shuffle_rng = jax.random.split(rng)
                permutation = jax.random.permutation(shuffle_rng, batch_size)
                
                def _update_minibatch(mb_state, mb_indices):
                    p, o_st = mb_state
                    mb_obs = jnp.take(b_obs, mb_indices, axis=0)
                    mb_act = jnp.take(b_act, mb_indices, axis=0)
                    mb_adv = jnp.take(b_adv, mb_indices, axis=0)
                    mb_adv = (mb_adv - mb_adv.mean()) / (mb_adv.std() + 1e-8)
                    mb_ret = jnp.take(b_ret, mb_indices, axis=0)
                    mb_logprob = jnp.take(b_logprobs, mb_indices, axis=0)
                    
                    loss, grads = grad_fn(p, mb_obs, mb_act, mb_logprob, mb_adv, mb_ret)
                    updates, o_st = optimizer.update(grads, o_st)
                    p = optax.apply_updates(p, updates)
                    return (p, o_st), None
                    
                mb_indices_reshaped = permutation.reshape((num_minibatches, minibatch_size))
                (p, o_st), _ = jax.lax.scan(_update_minibatch, (p, o_st), mb_indices_reshaped)
                return (p, o_st, rng), None

            update_state = (network_params, opt_state, rng)
            update_state, _ = jax.lax.scan(_update_epoch, update_state, None, length=update_epochs)
            network_params, opt_state, rng = update_state
            
            return (network_params, opt_state, obs, env_state, rng), None

        runner_state = (network_params, opt_state, obs, env_state, rng)
        runner_state, _ = jax.lax.scan(_update_step, runner_state, None, length=num_updates)
        return runner_state[0]

    return train

# 4. Evaluation Engine (Deterministic)
def evaluate_model(network_params, test_env, test_params):
    network = ActorCritic(action_dim=test_params.num_assets)
    
    def _eval_step(state, obs):
        mean, std, _ = network.apply(network_params, obs)
        action = mean 
        exp_a = jnp.exp(action)
        weights = exp_a / jnp.sum(exp_a)
        
        turnover = jnp.sum(jnp.abs(weights - state.previous_weights))
        transaction_cost = turnover * test_params.slip_rate
        
        future_returns = test_params.returns[state.current_step]
        portfolio_return = jnp.sum(weights * future_returns)
        net_return = portfolio_return - transaction_cost
        new_value = state.portfolio_value * (1.0 + net_return)
        
        new_state = EnvState(
            current_step=state.current_step + 21,
            portfolio_value=new_value,
            previous_weights=weights
        )
        return new_state, new_value

    init_weights = jnp.zeros(test_params.num_assets).at[-1].set(1.0)
    init_state = EnvState(
        current_step=jnp.array(0),
        portfolio_value=jnp.float32(1.0),
        previous_weights=init_weights
    )

    steps = jnp.arange(0, test_params.max_steps, 21)
    obs_seq = jnp.take(test_params.features, steps, axis=0)
    
    final_state, val_history = jax.lax.scan(_eval_step, init_state, obs_seq)
    
    total_return = final_state.portfolio_value - 1.0
    
    # Calculate exact trading days in the test set
    total_trading_days = test_params.max_steps
    years = total_trading_days / 252.0
    
    if years > 0:
        cagr = (final_state.portfolio_value ** (1 / years)) - 1.0
    else:
        cagr = 0.0
        
    return cagr * 100, total_return * 100


def main():
    print("Loading raw dataset for Walk-Forward Validation...")
    df = pd.read_parquet(DATA_PATH)
    
    # Ensure index is sorted datetime
    df = df.sort_index()

    windows = [
        {"name": "2016-2017", "train_end": "2015-12-31", "test_end": "2017-12-31"},
        {"name": "2018-2019", "train_end": "2017-12-31", "test_end": "2019-12-31"},
        {"name": "2020-2021", "train_end": "2019-12-31", "test_end": "2021-12-31"},
        {"name": "2022-2023", "train_end": "2021-12-31", "test_end": "2023-12-31"},
        {"name": "2024-End",  "train_end": "2023-12-31", "test_end": "2099-12-31"}
    ]

    assets = ["TQQQ", "SOXL", "FAS", "CURE", "URTY", "DRN", "ERX", "TMF", "BIL"]
    features_list = ['return_21d', 'return_90d', 'volatility_21d', 'z_score_200d', 'rsi_14d', 'macd_hist', 'macro_vix', 'macro_tnx']

    print(f"JAX Device: {jax.devices()}\n")
    
    # Balanced Search parameters
    hp_lr = 0.0005
    hp_ent = 0.02
    
    results = []

    for w in windows:
        print(f"--- Running Window: Test {w['name']} ---")
        train_df_raw = df[df.index <= w['train_end']]
        test_df_raw = df[(df.index > w['train_end']) & (df.index <= w['test_end'])]
        
        if len(test_df_raw) < 100:
             print(f"Skipping {w['name']} - Not enough test data.")
             continue
             
        def prepare_data(df_part):
            df_assets = df_part[df_part['Ticker'].isin(assets)].copy()
            pivot_feat = df_assets.pivot_table(index=df_assets.index, columns='Ticker', values=features_list)
            pivot_feat.fillna(0, inplace=True)
            pivot_ret = df_assets.pivot_table(index=df_assets.index, columns='Ticker', values='target_fwd_return_21d')
            pivot_ret.fillna(0, inplace=True)
            common_dates = pivot_feat.index.intersection(pivot_ret.index)
            return pivot_feat.loc[common_dates], pivot_ret.loc[common_dates][assets].values

        train_feat_df, train_ret = prepare_data(train_df_raw)
        test_feat_df, test_ret = prepare_data(test_df_raw)
        
        # 🚨 STRICT ZERO-LEAKAGE SCALING 🚨
        # Fit scaler ONLY on training data
        train_mean = train_feat_df.values.mean(axis=0)
        train_std = train_feat_df.values.std(axis=0) + 1e-8
        
        train_feat = (train_feat_df.values - train_mean) / train_std
        
        # Apply the TRAIN scaler to TEST data
        # Ensure column alignment just in case
        test_feat_df = test_feat_df[train_feat_df.columns]
        test_feat = (test_feat_df.values - train_mean) / train_std

        train_env = JaxPortfolioEnv(train_feat, train_ret, penalty_enabled=True)
        test_env = JaxPortfolioEnv(test_feat, test_ret, penalty_enabled=False)

        start_time = time.time()
        
        # Compile and Train
        train_fn = make_train_fn(train_env, hp_lr=hp_lr, hp_ent=hp_ent)
        jit_train = jax.jit(train_fn)
        trained_params = jit_train(jax.random.PRNGKey(42))
        
        end_time = time.time()
        
        # Evaluate Out-of-Sample
        cagr, tot_ret = evaluate_model(trained_params, test_env, test_env.default_params)
        
        print(f"✅ Training Time (5M steps): {end_time - start_time:.2f}s")
        print(f"📊 OOS CAGR: {cagr:.2f}% | Total Return: {tot_ret:.2f}%\n")
        
        results.append({
            "Window": w['name'],
            "CAGR": cagr,
            "TotalReturn": tot_ret
        })

    print("==================================================")
    print("🏆 WALK-FORWARD VALIDATION RESULTS 🏆")
    print("==================================================")
    for res in results:
        print(f"Test Period: {res['Window']:<12} | CAGR: {res['CAGR']:>6.2f}% | TotRet: {res['TotalReturn']:>7.2f}%")
    print("==================================================")

if __name__ == "__main__":
    main()
