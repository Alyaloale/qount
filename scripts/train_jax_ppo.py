import os
import time
import jax
import jax.numpy as jnp
from flax import struct
import flax.linen as nn
import optax
import pandas as pd
import numpy as np

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "processed", "ai_training_dataset.parquet")

# 1. JAX Environment
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
        # Start randomly during training to increase state diversity
        start_step = jax.random.randint(key, shape=(), minval=0, maxval=params.max_steps // 2)
        
        init_weights = jnp.zeros(params.num_assets)
        init_weights = init_weights.at[-1].set(1.0)
        
        state = EnvState(
            current_step=start_step,
            portfolio_value=jnp.float32(1.0),
            previous_weights=init_weights
        )
        
        obs = params.features[state.current_step]
        return obs, state

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
        reward = jnp.log(1.0 + net_return)
        
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
        
        info = {"portfolio_value": new_portfolio_value}
        
        return next_obs, new_state, reward, done, info

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

# 3. Training Loop (Pure JAX)
def train_ppo(env: JaxPortfolioEnv, total_timesteps=5_000_000, num_envs=2048, num_steps=128):
    params = env.default_params
    num_updates = total_timesteps // (num_envs * num_steps)
    
    network = ActorCritic(action_dim=params.num_assets)
    rng = jax.random.PRNGKey(42)
    rng, init_rng = jax.random.split(rng)
    network_params = network.init(init_rng, jnp.zeros((params.features.shape[1],)))
    
    optimizer = optax.chain(
        optax.clip_by_global_norm(0.5),
        optax.adam(learning_rate=3e-4)
    )
    opt_state = optimizer.init(network_params)
    
    # Initialize envs
    rng, env_rng = jax.random.split(rng)
    reset_rngs = jax.random.split(env_rng, num_envs)
    vmap_reset = jax.vmap(env.reset, in_axes=(0, None))
    obs, env_state = vmap_reset(reset_rngs, params)
    
    vmap_step = jax.vmap(auto_reset_step, in_axes=(None, 0, 0, 0, None))
    
    def _update_step(runner_state, unused):
        network_params, opt_state, obs, env_state, rng = runner_state
        
        # --- Rollout ---
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
        
        # --- GAE ---
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
        
        # Flatten
        b_obs = obs_batch.reshape(-1, obs_batch.shape[-1])
        b_act = action_batch.reshape(-1, action_batch.shape[-1])
        b_logprobs = logprob_batch.reshape(-1)
        b_adv = advantages.reshape(-1)
        b_ret = returns.reshape(-1)
        b_val = value_batch.reshape(-1)
        
        # Normalize advantages
        b_adv = (b_adv - b_adv.mean()) / (b_adv.std() + 1e-8)
        
        # --- PPO Update ---
        def _loss_fn(params, obs, act, old_logprob, adv, ret, old_val):
            mean, std, val = network.apply(params, obs)
            logprob = gaussian_logprob(act, mean, std)
            entropy = gaussian_entropy(std).mean()
            
            ratio = jnp.exp(logprob - old_logprob)
            pg_loss1 = -adv * ratio
            pg_loss2 = -adv * jnp.clip(ratio, 1.0 - 0.2, 1.0 + 0.2)
            pg_loss = jnp.maximum(pg_loss1, pg_loss2).mean()
            
            v_loss = 0.5 * jnp.mean((ret - val) ** 2)
            
            loss = pg_loss + 0.5 * v_loss - 0.02 * entropy
            return loss, (pg_loss, v_loss, entropy)
            
        grad_fn = jax.value_and_grad(_loss_fn, has_aux=True)
        
        # Simplified 4-epoch update for better sample efficiency
        def _epoch_loop(i, val):
            params, opt_st = val
            (loss, aux), grads = grad_fn(params, b_obs, b_act, b_logprobs, b_adv, b_ret, b_val)
            updates, opt_st = optimizer.update(grads, opt_st)
            params = optax.apply_updates(params, updates)
            return (params, opt_st)
            
        network_params, opt_state = jax.lax.fori_loop(0, 4, _epoch_loop, (network_params, opt_state))
        
        return (network_params, opt_state, obs, env_state, rng), loss

    # Compile the entire training loop!
    # By using lax.scan, JAX will fuse 5,000,000 steps into a SINGLE GPU operation!
    print(f"Compiling and running {total_timesteps} steps completely on GPU...")
    start_time = time.time()
    
    runner_state = (network_params, opt_state, obs, env_state, rng)
    runner_state, losses = jax.lax.scan(_update_step, runner_state, None, length=num_updates)
    
    end_time = time.time()
    fps = total_timesteps / (end_time - start_time)
    print(f"✅ Training Finished! FPS: {fps:,.0f} steps/second")
    print(f"Time Taken: {end_time - start_time:.2f} seconds")
    
    network_params = runner_state[0]
    return network_params, network

def main():
    print("Loading data and initializing JAX tensors...")
    df = pd.read_parquet(DATA_PATH)
    
    def prepare_data(df_part):
        assets = ["TQQQ", "SOXL", "FAS", "CURE", "URTY", "DRN", "ERX", "TMF", "BIL"]
        df_assets = df_part[df_part['Ticker'].isin(assets)].copy()
        features_list = ['return_21d', 'return_90d', 'volatility_21d', 'z_score_200d', 'macro_vix', 'macro_tnx']
        
        pivot_feat = df_assets.pivot_table(index=df_assets.index, columns='Ticker', values=features_list)
        pivot_feat.fillna(0, inplace=True)
        pivot_ret = df_assets.pivot_table(index=df_assets.index, columns='Ticker', values='target_fwd_return_21d')
        pivot_ret.fillna(0, inplace=True)
        
        common_dates = pivot_feat.index.intersection(pivot_ret.index)
        
        # Standardize features
        feat_array = pivot_feat.loc[common_dates].values
        feat_mean = feat_array.mean(axis=0)
        feat_std = feat_array.std(axis=0) + 1e-8
        feat_array = (feat_array - feat_mean) / feat_std
        
        return feat_array, pivot_ret.loc[common_dates][assets].values

    train_df = df[df.index < '2022-01-01']
    test_df = df[df.index >= '2022-01-01']
    
    train_feat, train_ret = prepare_data(train_df)
    test_feat, test_ret = prepare_data(test_df)
    
    print(f"JAX Device: {jax.devices()}")
    
    env = JaxPortfolioEnv(train_feat, train_ret, penalty_enabled=True, slip_rate=0.002)
    
    # 5,000,000 steps
    trained_params, network = train_ppo(env, total_timesteps=5_000_000, num_envs=2048, num_steps=128)
    
    print("\nEvaluating Out-Of-Sample (OOS) Performance...")
    # Pure JAX OOS Evaluation
    test_env = JaxPortfolioEnv(test_feat, test_ret, penalty_enabled=True, slip_rate=0.002)
    params = test_env.default_params
    
    key = jax.random.PRNGKey(0)
    obs, state = test_env.reset(key, params)
    # Force start at 0 for testing
    state = state.replace(current_step=jnp.array(0, dtype=jnp.int32))
    obs = params.features[0]
    
    def _test_step(carry, unused):
        obs, state, key = carry
        key, action_key = jax.random.split(key)
        mean, std, val = network.apply(trained_params, obs)
        # Deterministic
        action = mean 
        
        next_obs, next_state, reward, done, info = test_env.step(key, state, action, params)
        return (next_obs, next_state, key), info["portfolio_value"]

    _, values = jax.lax.scan(_test_step, (obs, state, key), None, length=params.max_steps)
    
    final_val = float(values[-1])
    total_return = final_val - 1
    cagr = (final_val ** (1 / 4.5)) - 1
    print(f"OOS Total Return: {total_return:.2%}")
    print(f"OOS CAGR: {cagr:.2%}")

if __name__ == "__main__":
    main()
