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
from datetime import datetime

warnings.filterwarnings('ignore')

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "processed", "ai_training_dataset.parquet")
REPORT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "v3_experiments_report.md")

# 1. Environment State and Params
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
    deadband: float          # V3-A: Deadband for no-trade zone
    max_weight: float        # V3-B: Max weight per asset

class JaxSequencePortfolioEnv:
    def __init__(self, features_seq, returns, penalty_enabled=True, slip_rate=0.002, deadband=0.0, max_weight=1.0):
        self.num_assets = returns.shape[1]
        self.max_steps = features_seq.shape[0] - 1
        
        self.default_params = EnvParams(
            features=jnp.array(features_seq, dtype=jnp.float32),
            returns=jnp.array(returns, dtype=jnp.float32),
            max_steps=self.max_steps,
            num_assets=self.num_assets,
            slip_rate=slip_rate,
            penalty_enabled=penalty_enabled,
            deadband=deadband,
            max_weight=max_weight
        )

    def reset(self, key, params):
        start_step = jax.random.randint(key, shape=(), minval=0, maxval=params.max_steps // 2)
        init_weights = jnp.zeros(params.num_assets).at[-1].set(1.0)
        state = EnvState(
            current_step=start_step,
            portfolio_value=jnp.float32(1.0),
            previous_weights=init_weights
        )
        return params.features[state.current_step], state

    def step(self, key, state, action, params):
        # 1. Softmax Risk Intention
        exp_a = jnp.exp(action)
        weights = exp_a / jnp.sum(exp_a)
        
        # 2. V3-B: Safe Projection (Max Weight)
        weights = jnp.clip(weights, 0.0, params.max_weight)
        # Re-normalize (put remainder in cash/BIL which is the last asset)
        remainder = 1.0 - jnp.sum(weights)
        weights = weights.at[-1].add(jnp.maximum(0.0, remainder))
        weights = weights / jnp.sum(weights)
        
        # 3. V3-A: Portfolio-Level Deadband (No-trade zone)
        intended_turnover = 0.5 * jnp.sum(jnp.abs(weights - state.previous_weights))
        weights = jax.lax.cond(
            intended_turnover < params.deadband,
            lambda: state.previous_weights,
            lambda: weights
        )
        
        turnover = 0.5 * jnp.sum(jnp.abs(weights - state.previous_weights))
        transaction_cost = turnover * params.slip_rate
        
        # V3: Quadratic turnover penalty
        penalty_turn = transaction_cost + 5.0 * (transaction_cost ** 2)
        
        future_returns = params.returns[state.current_step]
        portfolio_return = jnp.sum(weights * future_returns)
        net_return = portfolio_return - penalty_turn
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

class TransformerEncoderBlock(nn.Module):
    num_heads: int
    qkv_features: int

    @nn.compact
    def __call__(self, inputs):
        x = nn.LayerNorm()(inputs)
        attn_out = nn.MultiHeadDotProductAttention(
            num_heads=self.num_heads, qkv_features=self.qkv_features, out_features=inputs.shape[-1]
        )(x, x)
        x = inputs + attn_out
        
        y = nn.LayerNorm()(x)
        y = nn.Dense(features=inputs.shape[-1] * 2)(y)
        y = nn.gelu(y)
        y = nn.Dense(features=inputs.shape[-1])(y)
        return x + y

class TransformerActorCritic(nn.Module):
    action_dim: int

    @nn.compact
    def __call__(self, x):
        # Downsized for faster experimentation (2 layers, 64 dims, 4 heads)
        x = nn.Dense(features=64)(x)
        
        seq_len = x.shape[1]
        pos_emb = self.param('pos_emb', nn.initializers.normal(stddev=0.02), (1, seq_len, 64))
        x = x + pos_emb
        
        x = TransformerEncoderBlock(num_heads=4, qkv_features=64)(x)
        x = TransformerEncoderBlock(num_heads=4, qkv_features=64)(x)
        
        x = jnp.mean(x, axis=1)
        
        x = nn.Dense(128)(x)
        x = nn.leaky_relu(x)
        
        actor = nn.Dense(64)(x)
        actor = nn.leaky_relu(actor)
        actor_mean = nn.Dense(self.action_dim)(actor)
        actor_log_std = self.param('log_std', nn.initializers.zeros, (self.action_dim,))
        actor_std = jnp.exp(actor_log_std)

        critic = nn.Dense(64)(x)
        critic = nn.leaky_relu(critic)
        critic = nn.Dense(1)(critic)

        return actor_mean, actor_std, jnp.squeeze(critic, axis=-1)

def gaussian_logprob(action, mean, std):
    var = std ** 2
    log_scale = jnp.log(std)
    return -0.5 * jnp.sum(((action - mean) ** 2) / var + 2 * log_scale + jnp.log(2 * jnp.pi), axis=-1)

def gaussian_entropy(std):
    return jnp.sum(0.5 + 0.5 * jnp.log(2 * jnp.pi) + jnp.log(std), axis=-1)

def make_train_fn(env: JaxSequencePortfolioEnv, hp_lr, hp_ent, total_timesteps, num_envs=64, num_steps=128):
    params = env.default_params
    num_updates = total_timesteps // (num_envs * num_steps)
    
    update_epochs = 4
    num_minibatches = 8
    batch_size = num_envs * num_steps
    minibatch_size = batch_size // num_minibatches
    
    def train(rng):
        network = TransformerActorCritic(action_dim=params.num_assets)
        rng, init_rng = jax.random.split(rng)
        dummy_obs = jnp.zeros((1, params.features.shape[1], params.features.shape[2]))
        network_params = network.init(init_rng, dummy_obs)
        
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
            
            b_obs = obs_batch.reshape(-1, obs_batch.shape[-2], obs_batch.shape[-1])
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

        # Print progress during training block using chunking
        runner_state = (network_params, opt_state, obs, env_state, rng)
        chunk_size = num_updates // 4
        for chunk in range(4):
            runner_state, _ = jax.lax.scan(_update_step, runner_state, None, length=chunk_size)
            jax.debug.print("    [JAX] Training chunk {c}/4 complete...", c=chunk+1)
            
        return runner_state[0]

    return train

def evaluate_model(network_params, test_env, test_params):
    network = TransformerActorCritic(action_dim=test_params.num_assets)
    
    def _eval_step(state, obs):
        obs_batched = jnp.expand_dims(obs, 0)
        mean, std, _ = network.apply(network_params, obs_batched)
        action = jnp.squeeze(mean, 0)
        
        exp_a = jnp.exp(action)
        weights = exp_a / jnp.sum(exp_a)
        
        weights = jnp.clip(weights, 0.0, test_params.max_weight)
        remainder = 1.0 - jnp.sum(weights)
        weights = weights.at[-1].add(jnp.maximum(0.0, remainder))
        weights = weights / jnp.sum(weights)
        
        intended_turnover = 0.5 * jnp.sum(jnp.abs(weights - state.previous_weights))
        weights = jax.lax.cond(
            intended_turnover < test_params.deadband,
            lambda: state.previous_weights,
            lambda: weights
        )
        
        turnover = 0.5 * jnp.sum(jnp.abs(weights - state.previous_weights))
        transaction_cost = turnover * test_params.slip_rate
        penalty_turn = transaction_cost + 5.0 * (transaction_cost ** 2)
        
        future_returns = test_params.returns[state.current_step]
        portfolio_return = jnp.sum(weights * future_returns)
        net_return = portfolio_return - penalty_turn
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
    final_state, _ = jax.lax.scan(_eval_step, init_state, obs_seq)
    
    total_return = final_state.portfolio_value - 1.0
    years = test_params.max_steps / 252.0
    cagr = (final_state.portfolio_value ** (1 / years)) - 1.0 if years > 0 else 0.0
    return cagr * 100, total_return * 100

def create_sequences(features, seq_len=30):
    T, F = features.shape
    seq_features = np.zeros((T, seq_len, F))
    for i in range(T):
        start_idx = max(0, i - seq_len + 1)
        window = features[start_idx : i + 1]
        if len(window) < seq_len:
            pad = np.repeat(window[0:1], seq_len - len(window), axis=0)
            window = np.vstack([pad, window])
        seq_features[i] = window
    return seq_features

def run_experiment(df, assets, features, train_start, train_end, test_start, test_end, slip_rate, deadband, max_weight, seed=42):
    train_df_raw = df[(df.index >= train_start) & (df.index <= train_end)]
    test_df_raw = df[(df.index >= test_start) & (df.index <= test_end)]
    
    if len(test_df_raw) < 100:
        return 0.0, 0.0
        
    def prepare_data(df_part):
        df_assets = df_part[df_part['Ticker'].isin(assets)].copy()
        pivot_feat = df_assets.pivot_table(index=df_assets.index, columns='Ticker', values=features)
        pivot_feat.fillna(0, inplace=True)
        pivot_ret = df_assets.pivot_table(index=df_assets.index, columns='Ticker', values='target_fwd_return_21d')
        pivot_ret.fillna(0, inplace=True)
        common_dates = pivot_feat.index.intersection(pivot_ret.index)
        return pivot_feat.loc[common_dates], pivot_ret.loc[common_dates][assets].values

    train_feat_df, train_ret = prepare_data(train_df_raw)
    test_feat_df, test_ret = prepare_data(test_df_raw)
    
    train_mean = train_feat_df.values.mean(axis=0)
    train_std = train_feat_df.values.std(axis=0) + 1e-8
    train_feat = (train_feat_df.values - train_mean) / train_std
    test_feat_df = test_feat_df[train_feat_df.columns]
    test_feat = (test_feat_df.values - train_mean) / train_std

    train_seq = create_sequences(train_feat, 30)
    test_seq = create_sequences(test_feat, 30)

    train_env = JaxSequencePortfolioEnv(train_seq, train_ret, penalty_enabled=True, slip_rate=slip_rate, deadband=deadband, max_weight=max_weight)
    test_env = JaxSequencePortfolioEnv(test_seq, test_ret, penalty_enabled=False, slip_rate=slip_rate, deadband=deadband, max_weight=max_weight)

    # 阶段A：快速筛选 (Fast screening) - 2 Million steps instead of 8 Million
    train_fn = make_train_fn(train_env, hp_lr=0.0005, hp_ent=0.02, total_timesteps=2_000_000)
    jit_train = jax.jit(train_fn)
    trained_params = jit_train(jax.random.PRNGKey(seed))
    
    cagr, tot_ret = evaluate_model(trained_params, test_env, test_env.default_params)
    return cagr, tot_ret

def main():
    print("🚀 [START] QOUNT Transformer V3 Fast Screening Matrix...", flush=True)
    df = pd.read_parquet(DATA_PATH)
    df = df.sort_index()
    
    assets = ["TQQQ", "SOXL", "FAS", "CURE", "URTY", "DRN", "ERX", "TMF", "BIL"]
    base_features = ['return_21d', 'return_90d', 'volatility_21d', 'z_score_252d', 'ma_200_dist', 'rsi_14d', 'macd_hist', 'vix_level', 'vix_slope', 'tnx_level', 'corr_spy_tlt_63d']
    
    print("==================================================", flush=True)
    print("Phase A: Fast Screening Models on Failure Folds (2M steps)", flush=True)
    
    candidates = [
        {"name": "V3-Baseline", "deadband": 0.0, "max_weight": 1.0},
        {"name": "V3-A (Deadband 5%)", "deadband": 0.05, "max_weight": 1.0},
        {"name": "V3-B (Deadband 5% + Max 30%)", "deadband": 0.05, "max_weight": 0.30},
    ]
    
    critical_folds = [
        {"name": "2020-2021", "train_end": "2019-12-31", "test_start": "2020-01-01", "test_end": "2021-12-31"},
        {"name": "2022-2023", "train_end": "2021-12-31", "test_start": "2022-01-01", "test_end": "2023-12-31"}
    ]
    
    results_md = "# 🛡️ QOUNT AI V3 快速筛选诊断矩阵\n\n"
    
    for cand in candidates:
        print(f"\n⚙️ Testing Candidate: {cand['name']}", flush=True)
        results_md += f"## 模型版本: {cand['name']}\n"
        results_md += f"- 配置: Deadband={cand['deadband']*100}%, Max_Weight={cand['max_weight']*100}%\n"
        results_md += "| 测试周期 (Fold) | Seed 42 CAGR | Seed 43 CAGR | 平均 CAGR |\n|---|---|---|---|\n"
        
        for fold in critical_folds:
            print(f"  -> Fold {fold['name']}...", flush=True)
            cagrs = []
            for seed in [42, 43]:
                print(f"     -> Seed {seed}...", flush=True)
                # Note: We test under high slippage condition (0.5%) to see if deadband helps
                cagr, _ = run_experiment(df, assets, base_features, "2010-01-01", fold['train_end'], fold['test_start'], fold['test_end'], slip_rate=0.005, deadband=cand['deadband'], max_weight=cand['max_weight'], seed=seed)
                cagrs.append(float(cagr))
                print(f"        Result: {cagr:.2f}%", flush=True)
                
            avg_cagr = np.mean(cagrs)
            results_md += f"| {fold['name']} | {cagrs[0]:.2f}% | {cagrs[1]:.2f}% | **{avg_cagr:.2f}%** |\n"

    with open(REPORT_PATH, "w") as f:
        f.write(results_md)
    print(f"\n✅ Fast Screening Complete. Report generated at: {REPORT_PATH}", flush=True)
    
if __name__ == "__main__":
    main()
