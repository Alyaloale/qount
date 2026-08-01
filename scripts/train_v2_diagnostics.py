import os
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
REPORT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "diagnostic_report_round1.md")

# ==========================================
# 1. UNMODIFIED ENVIRONMENT & NETWORK (ROUND 1)
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
    penalty_enabled: bool

class JaxSequencePortfolioEnv:
    def __init__(self, features_seq, returns, penalty_enabled=True, slip_rate=0.002):
        self.num_assets = returns.shape[1]
        self.max_steps = features_seq.shape[0] - 1
        
        self.default_params = EnvParams(
            features=jnp.array(features_seq, dtype=jnp.float32),
            returns=jnp.array(returns, dtype=jnp.float32),
            max_steps=self.max_steps,
            num_assets=self.num_assets,
            slip_rate=slip_rate,
            penalty_enabled=penalty_enabled
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
        x = nn.Dense(features=128)(x)
        seq_len = x.shape[1]
        pos_emb = self.param('pos_emb', nn.initializers.normal(stddev=0.02), (1, seq_len, 128))
        x = x + pos_emb
        x = TransformerEncoderBlock(num_heads=8, qkv_features=128)(x)
        x = TransformerEncoderBlock(num_heads=8, qkv_features=128)(x)
        x = TransformerEncoderBlock(num_heads=8, qkv_features=128)(x)
        x = TransformerEncoderBlock(num_heads=8, qkv_features=128)(x)
        x = jnp.mean(x, axis=1)
        x = nn.Dense(256)(x)
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
        chunk_size = num_updates // 5
        for chunk in range(5):
            runner_state, _ = jax.lax.scan(_update_step, runner_state, None, length=chunk_size)
            jax.debug.print("    [JAX Log] Training {p}% complete...", p=(chunk+1)*20)
            
        return runner_state[0]
    return train

# ==========================================
# 2. DETAILED DIAGNOSTIC EVALUATION
# ==========================================
def evaluate_model_detailed(network_params, test_env, test_params):
    network = TransformerActorCritic(action_dim=test_params.num_assets)
    
    def _eval_step(state, obs):
        obs_batched = jnp.expand_dims(obs, 0)
        mean, std, _ = network.apply(network_params, obs_batched)
        action = jnp.squeeze(mean, 0)
        exp_a = jnp.exp(action)
        weights = exp_a / jnp.sum(exp_a)
        
        turnover = jnp.sum(jnp.abs(weights - state.previous_weights))
        transaction_cost = turnover * test_params.slip_rate
        
        future_returns = test_params.returns[state.current_step]
        portfolio_return = jnp.sum(weights * future_returns)
        net_return = portfolio_return - transaction_cost
        new_value = state.portfolio_value * (1.0 + net_return)
        
        # Contribution calculation (Asset Return * Weight)
        tqqq_contrib = weights[0] * future_returns[0]
        soxl_contrib = weights[1] * future_returns[1]
        
        new_state = EnvState(
            current_step=state.current_step + 21,
            portfolio_value=new_value,
            previous_weights=weights
        )
        return new_state, (new_value, net_return, turnover, weights, tqqq_contrib, soxl_contrib)

    init_weights = jnp.zeros(test_params.num_assets).at[-1].set(1.0)
    init_state = EnvState(current_step=jnp.array(0), portfolio_value=jnp.float32(1.0), previous_weights=init_weights)
    steps = jnp.arange(0, test_params.max_steps, 21)
    obs_seq = jnp.take(test_params.features, steps, axis=0)
    
    final_state, (p_values, net_returns, turnovers, weights_history, tqqq_ctb, soxl_ctb) = jax.lax.scan(_eval_step, init_state, obs_seq)
    
    # Calculate Detailed Metrics
    years = test_params.max_steps / 252.0
    cagr = (final_state.portfolio_value ** (1 / years)) - 1.0 if years > 0 else 0.0
    
    # Max Drawdown
    running_max = jax.lax.associative_scan(jnp.maximum, p_values)
    drawdowns = (p_values - running_max) / running_max
    max_dd = jnp.min(drawdowns)
    
    # Sharpe & Sortino (assuming approx risk free rate = 0 for simplification in net_return)
    mean_ret = jnp.mean(net_returns)
    std_ret = jnp.std(net_returns) + 1e-8
    downside_std = jnp.std(jnp.minimum(0, net_returns)) + 1e-8
    sharpe = (mean_ret / std_ret) * jnp.sqrt(12) # ~12 months per year since steps are 21 days
    sortino = (mean_ret / downside_std) * jnp.sqrt(12)
    
    # Turnover
    annual_turnover = jnp.sum(turnovers) / years
    
    # Position analysis
    max_single_weight = jnp.max(weights_history)
    avg_bil_weight = jnp.mean(weights_history[:, -1])
    
    # Top 10 days contribution
    top_10_returns = jnp.sort(net_returns)[-10:]
    top_10_sum = jnp.sum(top_10_returns)
    total_return_sum = jnp.sum(net_returns)
    top_10_ratio = top_10_sum / (total_return_sum + 1e-8)
    
    metrics = {
        "cagr": cagr * 100,
        "max_dd": max_dd * 100,
        "sharpe": sharpe,
        "sortino": sortino,
        "ann_turnover": annual_turnover,
        "max_weight": max_single_weight * 100,
        "avg_bil": avg_bil_weight * 100,
        "tqqq_ctb_sum": jnp.sum(tqqq_ctb) * 100,
        "soxl_ctb_sum": jnp.sum(soxl_ctb) * 100,
        "top_10_ratio": top_10_ratio * 100
    }
    return metrics

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

def prepare_and_train(df, assets, features, train_start, train_end, test_start, test_end, slip_rate=0.002, seed=42):
    train_df_raw = df[(df.index >= train_start) & (df.index <= train_end)]
    test_df_raw = df[(df.index >= test_start) & (df.index <= test_end)]
    
    def prepare_data(df_part):
        df_assets = df_part[df_part['Ticker'].isin(assets)].copy()
        pivot_feat = df_assets.pivot_table(index=df_assets.index, columns='Ticker', values=features).fillna(0)
        pivot_ret = df_assets.pivot_table(index=df_assets.index, columns='Ticker', values='target_fwd_return_21d').fillna(0)
        common_dates = pivot_feat.index.intersection(pivot_ret.index)
        return pivot_feat.loc[common_dates], pivot_ret.loc[common_dates][assets].values

    train_feat_df, train_ret = prepare_data(train_df_raw)
    test_feat_df, test_ret = prepare_data(test_df_raw)
    
    train_mean = train_feat_df.values.mean(axis=0)
    train_std = train_feat_df.values.std(axis=0) + 1e-8
    train_feat = (train_feat_df.values - train_mean) / train_std
    test_feat = (test_feat_df[train_feat_df.columns].values - train_mean) / train_std

    train_seq = create_sequences(train_feat, 30)
    test_seq = create_sequences(test_feat, 30)

    train_env = JaxSequencePortfolioEnv(train_seq, train_ret, penalty_enabled=True, slip_rate=slip_rate)
    test_env = JaxSequencePortfolioEnv(test_seq, test_ret, penalty_enabled=False, slip_rate=slip_rate)

    # Use 2M steps for rapid automated testing per user instruction ("没必要都800万步")
    train_fn = make_train_fn(train_env, hp_lr=0.0003, hp_ent=0.02, total_timesteps=2_000_000)
    jit_train = jax.jit(train_fn)
    trained_params = jit_train(jax.random.PRNGKey(seed))
    
    metrics = evaluate_model_detailed(trained_params, test_env, test_env.default_params)
    return trained_params, metrics, test_env, test_env.default_params

def main():
    print("🚀 [START] QOUNT Transformer ROUND 1: DIAGNOSTICS...", flush=True)
    df = pd.read_parquet(DATA_PATH).sort_index()
    assets = ["TQQQ", "SOXL", "FAS", "CURE", "URTY", "DRN", "ERX", "TMF", "BIL"]
    base_features = ['return_21d', 'return_90d', 'volatility_21d', 'z_score_200d', 'rsi_14d', 'macd_hist', 'macro_vix', 'macro_tnx']
    
    md_content = "# 🛡️ 第一轮诊断：模型深层归因报告 (Diagnostics)\n\n"
    md_content += "> 目的：在不改变任何模型结构的情况下，查明 2020-2023 失败原因、收益归因以及摩擦成本极限。\n\n"
    
    # ---------------------------------------------------------
    # 1. 统一基准实验矩阵 (4 Folds x 5 Seeds)
    # ---------------------------------------------------------
    print("\n==================================================", flush=True)
    print("Task 1: 4 Folds x 5 Seeds Baseline Matrix (2M steps per seed)", flush=True)
    md_content += "## 1. 统一基准实验矩阵 (4 Folds x 5 Seeds)\n"
    
    windows = [
        {"name": "2018-2019", "train_end": "2017-12-31", "test_start": "2018-01-01", "test_end": "2019-12-31"},
        {"name": "2020-2021", "train_end": "2019-12-31", "test_start": "2020-01-01", "test_end": "2021-12-31"},
        {"name": "2022-2023", "train_end": "2021-12-31", "test_start": "2022-01-01", "test_end": "2023-12-31"},
        {"name": "2024-End",  "train_end": "2023-12-31", "test_start": "2024-01-01", "test_end": "2099-12-31"}
    ]
    
    seeds = [42, 43, 44, 45, 46]
    matrix_cagr = {w['name']: [] for w in windows}
    
    for w in windows:
        print(f"\n  -> Fold {w['name']}...", flush=True)
        md_content += f"### 周期: {w['name']}\n"
        md_content += "| Seed | CAGR | Max DD | Sharpe | Ann Turnover | Max Pos | Top 10% Ratio |\n"
        md_content += "|---|---|---|---|---|---|---|\n"
        
        for seed in seeds:
            print(f"     -> Seed {seed}...", flush=True)
            trained_params, metrics, test_env, test_params = prepare_and_train(
                df, assets, base_features, "2010-01-01", w['train_end'], w['test_start'], w['test_end'], 0.002, seed
            )
            matrix_cagr[w['name']].append(float(metrics['cagr']))
            md_content += f"| {seed} | {metrics['cagr']:.2f}% | {metrics['max_dd']:.2f}% | {metrics['sharpe']:.2f} | {metrics['ann_turnover']:.2f} | {metrics['max_weight']:.2f}% | {metrics['top_10_ratio']:.2f}% |\n"
            
            # For 2024 fold, save attribution specifically for Seed 42 as representative
            if w['name'] == "2024-End" and seed == 42:
                attr_2024 = metrics
            # For Slippage Test, save the 2010-2021 model (which corresponds to 2022-2023 fold train set)
            if w['name'] == "2022-2023" and seed == 42:
                frozen_params = trained_params
                frozen_test_env = test_env
                frozen_test_params = test_params
                
    # ---------------------------------------------------------
    # 2. 2024 收益归因
    # ---------------------------------------------------------
    print("\n==================================================", flush=True)
    print("Task 2: Return Attribution for 2024-End", flush=True)
    md_content += "\n## 2. 2024 收益归因分析\n"
    md_content += "| 归因指标 | 结果 |\n|---|---|\n"
    md_content += f"| TQQQ 收益贡献 | {attr_2024['tqqq_ctb_sum']:.2f}% |\n"
    md_content += f"| SOXL 收益贡献 | {attr_2024['soxl_ctb_sum']:.2f}% |\n"
    md_content += f"| 前10个交易日贡献率 | {attr_2024['top_10_ratio']:.2f}% |\n"
    md_content += f"| 最大单资产仓位 | {attr_2024['max_weight']:.2f}% |\n"
    md_content += f"| 平均 BIL 避险仓位 | {attr_2024['avg_bil']:.2f}% |\n"
    
    # ---------------------------------------------------------
    # 3. 补齐零成本基线 (Slippage Curve)
    # ---------------------------------------------------------
    print("\n==================================================", flush=True)
    print("Task 3: Slippage Curve on Frozen Model (2022-2023 Test Set)", flush=True)
    md_content += "\n## 3. 补齐零成本基线 (Slippage Curve: 2022-2023)\n"
    md_content += "| 滑点率 | CAGR | Max DD | 结论 |\n|---|---|---|---|\n"
    
    slip_rates = [0.0, 0.0005, 0.0010, 0.0020, 0.0050, 0.0100]
    for slip in slip_rates:
        print(f"  -> Testing Slippage {slip*100:.2f}%...", flush=True)
        # Update slip rate dynamically
        modified_params = frozen_test_params.replace(slip_rate=slip)
        m = evaluate_model_detailed(frozen_params, frozen_test_env, modified_params)
        conclusion = "通过" if float(m['cagr']) > 0 else "摩擦磨损"
        md_content += f"| {slip*100:.2f}% | {float(m['cagr']):.2f}% | {float(m['max_dd']):.2f}% | {conclusion} |\n"
    
    # ---------------------------------------------------------
    # Save Report
    # ---------------------------------------------------------
    with open(REPORT_PATH, "w") as f:
        f.write(md_content)
    print(f"\n✅ Diagnostics Complete. Report generated at: {REPORT_PATH}", flush=True)

if __name__ == "__main__":
    main()
