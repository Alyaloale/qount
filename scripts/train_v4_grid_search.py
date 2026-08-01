import os
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
REPORT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "v4_grid1_report.md")

# ==========================================
# Environment Definitions
# ==========================================
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
    max_weight: float
    deadband: float
    asymmetric_db: bool

class JaxSequencePortfolioEnv:
    def __init__(self, features_seq, returns):
        self.num_assets = returns.shape[1]
        self.max_steps = features_seq.shape[0] - 1
        self.default_params = EnvParams(
            features=jnp.array(features_seq, dtype=jnp.float32),
            returns=jnp.array(returns, dtype=jnp.float32),
            max_steps=self.max_steps,
            num_assets=self.num_assets,
            slip_rate=0.005,
            max_weight=1.0,
            deadband=0.0,
            asymmetric_db=False
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
        exp_a = jnp.exp(action)
        weights = exp_a / jnp.sum(exp_a)
        
        weights = jnp.clip(weights, 0.0, params.max_weight)
        remainder = 1.0 - jnp.sum(weights)
        weights = weights.at[-1].add(jnp.maximum(0.0, remainder))
        weights = weights / jnp.sum(weights)
        
        is_reducing_risk = (1.0 - weights[-1]) < (1.0 - state.previous_weights[-1])
        eff_deadband = jax.lax.select(params.asymmetric_db & is_reducing_risk, 0.0, params.deadband)
        
        intended_turnover = 0.5 * jnp.sum(jnp.abs(weights - state.previous_weights))
        weights = jax.lax.cond(
            intended_turnover < eff_deadband,
            lambda: state.previous_weights,
            lambda: weights
        )
        
        turnover = 0.5 * jnp.sum(jnp.abs(weights - state.previous_weights))
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
        
        reward = jax.lax.cond(net_return < -0.10, lambda: reward - 0.2, lambda: reward)
        
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
        x = nn.Dense(features=64)(x)
        seq_len = x.shape[1]
        pos_emb = self.param('pos_emb', nn.initializers.normal(stddev=0.02), (1, seq_len, 64))
        x = x + pos_emb
        x = TransformerEncoderBlock(num_heads=4, qkv_features=64)(x)
        x = TransformerEncoderBlock(num_heads=4, qkv_features=64)(x)
        x = jnp.mean(x, axis=1)
        x = nn.Dense(128)(x)
        x = nn.leaky_relu(x)
        actor = nn.Dense(128)(x)
        actor = nn.leaky_relu(actor)
        actor_mean = nn.Dense(self.action_dim)(actor)
        actor_log_std = self.param('log_std', nn.initializers.zeros, (self.action_dim,))
        actor_std = jnp.exp(actor_log_std)
        critic = nn.Dense(128)(x)
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
        optimizer = optax.chain(optax.clip_by_global_norm(0.5), optax.adam(learning_rate=lr_schedule))
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
            gamma = 0.999; gae_lambda = 0.95
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
            
            def _loss_fn(p, o, a, old_lp, adv, ret):
                m, s, v = network.apply(p, o)
                lp = gaussian_logprob(a, m, s)
                ent = gaussian_entropy(s).mean()
                ratio = jnp.exp(lp - old_lp)
                pg_loss1 = -adv * ratio
                pg_loss2 = -adv * jnp.clip(ratio, 1.0 - 0.2, 1.0 + 0.2)
                pg_loss = jnp.maximum(pg_loss1, pg_loss2).mean()
                v_loss = 0.5 * jnp.mean((ret - v) ** 2)
                return pg_loss + 0.5 * v_loss - hp_ent * ent
                
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
        chunk_size = num_updates // 4
        for chunk in range(4):
            runner_state, _ = jax.lax.scan(_update_step, runner_state, None, length=chunk_size)
        return runner_state[0]
    return train

def evaluate_model_detailed(network_params, test_env, test_params):
    network = TransformerActorCritic(action_dim=test_params.num_assets)
    
    def _eval_step(state, step_idx):
        obs = test_params.features[step_idx]
        obs_batched = jnp.expand_dims(obs, 0)
        mean, _, _ = network.apply(network_params, obs_batched)
        action = jnp.squeeze(mean, 0)
        
        exp_a = jnp.exp(action)
        weights = exp_a / jnp.sum(exp_a)
        
        weights = jnp.clip(weights, 0.0, test_params.max_weight)
        remainder = 1.0 - jnp.sum(weights)
        weights = weights.at[-1].add(jnp.maximum(0.0, remainder))
        weights = weights / jnp.sum(weights)
        
        is_reducing_risk = (1.0 - weights[-1]) < (1.0 - state.previous_weights[-1])
        eff_deadband = jax.lax.select(test_params.asymmetric_db & is_reducing_risk, 0.0, test_params.deadband)
        
        intended_turnover = 0.5 * jnp.sum(jnp.abs(weights - state.previous_weights))
        weights = jax.lax.cond(
            intended_turnover < eff_deadband,
            lambda: state.previous_weights,
            lambda: weights
        )
        
        turnover = 0.5 * jnp.sum(jnp.abs(weights - state.previous_weights))
        transaction_cost = turnover * test_params.slip_rate
        
        future_returns = test_params.returns[step_idx]
        portfolio_return = jnp.sum(weights * future_returns)
        net_return = portfolio_return - transaction_cost
        
        new_portfolio_value = state.portfolio_value * (1.0 + net_return)
        
        new_state = EnvState(
            current_step=state.current_step + 1,
            portfolio_value=new_portfolio_value,
            previous_weights=weights
        )
        return new_state, (net_return, new_portfolio_value, weights, turnover)

    init_weights = jnp.zeros(test_params.num_assets).at[-1].set(1.0)
    init_state = EnvState(current_step=0, portfolio_value=jnp.float32(1.0), previous_weights=init_weights)
    steps = jnp.arange(0, test_params.max_steps, 1) # Daily eval
    
    final_state, (daily_returns, port_vals, weights_seq, turnovers) = jax.lax.scan(_eval_step, init_state, steps)
    
    # Calculate metrics
    years = test_params.max_steps / 252.0
    cagr = (final_state.portfolio_value ** (1 / years)) - 1.0 if years > 0 else 0.0
    
    port_vals_arr = np.array(port_vals)
    running_max = np.maximum.accumulate(port_vals_arr)
    drawdowns = (port_vals_arr - running_max) / (running_max + 1e-8)
    max_dd = np.min(drawdowns)
    
    daily_returns_arr = np.array(daily_returns)
    mean_ret = np.mean(daily_returns_arr)
    std_ret = np.std(daily_returns_arr) + 1e-8
    sharpe = (mean_ret / std_ret) * np.sqrt(252)
    
    downside_ret = daily_returns_arr[daily_returns_arr < 0]
    std_down = np.std(downside_ret) + 1e-8 if len(downside_ret) > 0 else 1e-8
    sortino = (mean_ret / std_down) * np.sqrt(252)
    
    annual_turnover = np.sum(np.array(turnovers)) / years if years > 0 else 0.0
    
    weights_arr = np.array(weights_seq)
    max_single_weight = np.max(weights_arr)
    mean_3x = np.mean(np.sum(weights_arr[:, :8], axis=1))
    mean_bil = np.mean(weights_arr[:, 8])
    mean_tech = np.mean(weights_arr[:, 0] + weights_arr[:, 1]) # TQQQ + SOXL
    
    return {
        "CAGR": cagr * 100,
        "Max DD": max_dd * 100,
        "Sharpe": sharpe,
        "Sortino": sortino,
        "Ann Turnover": annual_turnover,
        "Max Single W": max_single_weight * 100,
        "Mean 3x": mean_3x * 100,
        "Mean BIL": mean_bil * 100,
        "Mean Tech": mean_tech * 100
    }

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

def run_experiment(df, assets, base_features, cand, fold, seed):
    train_df = df[(df.index >= "2010-01-01") & (df.index <= fold['train_end'])]
    test_df = df[(df.index >= fold['test_start']) & (df.index <= fold['test_end'])]
    
    df_assets = train_df[train_df['Ticker'].isin(assets)].copy()
    pivot_feat = df_assets.pivot_table(index=df_assets.index, columns='Ticker', values=base_features).fillna(0)
    pivot_ret = df_assets.pivot_table(index=df_assets.index, columns='Ticker', values='target_fwd_return_21d').fillna(0)
    common = pivot_feat.index.intersection(pivot_ret.index)
    train_feat_df, train_ret = pivot_feat.loc[common], pivot_ret.loc[common][assets].values
    
    df_assets_t = test_df[test_df['Ticker'].isin(assets)].copy()
    pivot_feat_t = df_assets_t.pivot_table(index=df_assets_t.index, columns='Ticker', values=base_features).fillna(0)
    pivot_ret_t = df_assets_t.pivot_table(index=df_assets_t.index, columns='Ticker', values='Close').pct_change().shift(-1).fillna(0)
    common_t = pivot_feat_t.index.intersection(pivot_ret_t.index)
    test_feat_df, test_ret_daily = pivot_feat_t.loc[common_t], pivot_ret_t.loc[common_t][assets].values
    
    train_mean = train_feat_df.values.mean(axis=0)
    train_std = train_feat_df.values.std(axis=0) + 1e-8
    train_feat = (train_feat_df.values - train_mean) / train_std
    test_feat = (test_feat_df[train_feat_df.columns].values - train_mean) / train_std
    
    train_seq = create_sequences(train_feat, 30)
    test_seq = create_sequences(test_feat, 30)
    
    train_env = JaxSequencePortfolioEnv(train_seq, train_ret)
    train_env.default_params = EnvParams(
        features=jnp.array(train_seq, dtype=jnp.float32),
        returns=jnp.array(train_ret, dtype=jnp.float32),
        max_steps=train_seq.shape[0]-1,
        num_assets=len(assets),
        slip_rate=0.005,
        max_weight=cand['max_w'],
        deadband=cand['db'],
        asymmetric_db=cand['asym']
    )
    
    test_params = EnvParams(
        features=jnp.array(test_seq, dtype=jnp.float32),
        returns=jnp.array(test_ret_daily, dtype=jnp.float32),
        max_steps=test_seq.shape[0]-1,
        num_assets=len(assets),
        slip_rate=0.005,
        max_weight=cand['max_w'],
        deadband=cand['db'],
        asymmetric_db=cand['asym']
    )
    
    train_fn = make_train_fn(train_env, hp_lr=0.0003, hp_ent=0.02, total_timesteps=2_000_000)
    jit_train = jax.jit(train_fn)
    trained_params = jit_train(jax.random.PRNGKey(seed))
    
    metrics = evaluate_model_detailed(trained_params, train_env, test_params)
    return metrics

def main():
    print("🚀 [START] V4 Grid 1: Deadband Screening Matrix...", flush=True)
    df = pd.read_parquet(DATA_PATH).sort_index()
    assets = ["TQQQ", "SOXL", "FAS", "CURE", "URTY", "DRN", "ERX", "TMF", "BIL"]
    # New macro features included since we are training NEW V4 models
    base_features = ['return_21d', 'return_90d', 'volatility_21d', 'z_score_252d', 'ma_200_dist', 'rsi_14d', 'macd_hist', 'vix_level', 'tnx_level', 'corr_spy_tlt_63d']
    
    folds = [
        {"name": "2020-2021", "train_end": "2019-12-31", "test_start": "2020-01-01", "test_end": "2021-12-31"},
        {"name": "2022-2023", "train_end": "2021-12-31", "test_start": "2022-01-01", "test_end": "2023-12-31"}
    ]
    seeds = [42, 43, 44]
    
    candidates = [
        {"name": "C1 (DB 0%)", "db": 0.0, "asym": False, "max_w": 0.30},
        {"name": "C2 (DB 2%)", "db": 0.02, "asym": False, "max_w": 0.30},
        {"name": "C3 (DB 5%)", "db": 0.05, "asym": False, "max_w": 0.30},
        {"name": "C4 (Asym DB 5%)", "db": 0.05, "asym": True, "max_w": 0.30}
    ]
    
    md = "# 🛡️ QOUNT AI V4 第一轮网格：执行层 Deadband 测试\n\n"
    md += "固定仓位上限 30%，测试不同死区机制对模型性能和换手率的影响。\n\n"
    
    for cand in candidates:
        print(f"\n⚙️ Testing Candidate: {cand['name']}", flush=True)
        md += f"## {cand['name']}\n"
        md += "| 周期 | Seed | CAGR | Max DD | Sharpe | Sortino | 换手率 | 最大单资产 | 平均 3x | 平均 BIL | 平均 科技簇 |\n"
        md += "|---|---|---|---|---|---|---|---|---|---|---|\n"
        
        all_cagr = []
        all_dd = []
        for fold in folds:
            print(f"  -> Fold {fold['name']}...", flush=True)
            for seed in seeds:
                res = run_experiment(df, assets, base_features, cand, fold, seed)
                md += f"| {fold['name']} | {seed} | {res['CAGR']:.2f}% | {res['Max DD']:.2f}% | {res['Sharpe']:.2f} | {res['Sortino']:.2f} | {res['Ann Turnover']:.1f}x | {res['Max Single W']:.1f}% | {res['Mean 3x']:.1f}% | {res['Mean BIL']:.1f}% | {res['Mean Tech']:.1f}% |\n"
                all_cagr.append(res['CAGR'])
                all_dd.append(res['Max DD'])
                print(f"     -> Seed {seed} | CAGR: {res['CAGR']:.2f}% | DD: {res['Max DD']:.2f}% | Turn: {res['Ann Turnover']:.1f}x", flush=True)
        
        med_cagr = np.median(all_cagr)
        worst_dd = np.min(all_dd)
        md += f"| **汇总** | - | **中位数 CAGR: {med_cagr:.2f}%** | **最差 DD: {worst_dd:.2f}%** | - | - | - | - | - | - | - |\n\n"
        
    with open(REPORT_PATH, "w") as f:
        f.write(md)
        
    print(f"\n✅ Grid 1 Complete. Report at: {REPORT_PATH}", flush=True)

if __name__ == "__main__":
    main()
