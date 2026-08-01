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
REPORT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "v2_safety_replay_report.md")

# ==========================================
# V2 Baseline Model Definitions (Unmodified)
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
        # Using the same 128-dim heavy model as original V2
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
        chunk_size = num_updates // 2
        for chunk in range(2):
            runner_state, _ = jax.lax.scan(_update_step, runner_state, None, length=chunk_size)
            
        return runner_state[0]
    return train

# ==========================================
# Safety Projection Evaluator (Pure Python)
# ==========================================
def run_playback_eval(network_params, features, returns, slip_rate=0.002, safety_mode='baseline'):
    """
    safety_mode:
    - 'baseline': raw softmax weights
    - 'P0': Max 25% single asset, remainder to BIL
    - 'P1': Max 25% single asset + 3x Leverage capped at 1.5
    - 'P3': P1 + Hard Drawdown State Machine
    - 'P4': P3 + Deadband 5%
    """
    # Assets: "TQQQ", "SOXL", "FAS", "CURE", "URTY", "DRN", "ERX", "TMF", "BIL"
    # Indices 0 to 6 are 3x ETFs. 7 is TMF (3x bond). 8 is BIL.
    LEVERAGED_3X_INDICES = [0, 1, 2, 3, 4, 5, 6, 7]
    BIL_INDEX = 8
    
    network = TransformerActorCritic(action_dim=returns.shape[1])
    
    max_steps = features.shape[0] - 1
    steps_arr = np.arange(0, max_steps, 21)
    
    portfolio_value = 1.0
    previous_weights = np.zeros(returns.shape[1])
    previous_weights[BIL_INDEX] = 1.0
    
    running_max = 1.0
    in_cooldown = 0
    
    cagr, max_dd = 0.0, 0.0
    pnl_history = []
    
    for step_idx in steps_arr:
        # Get raw action from frozen model
        obs = features[step_idx]
        obs_batched = np.expand_dims(obs, 0)
        mean, _, _ = network.apply(network_params, obs_batched)
        action = np.squeeze(mean, 0)
        
        # Softmax
        exp_a = np.exp(action)
        w_raw = exp_a / np.sum(exp_a)
        
        w_target = np.copy(w_raw)
        
        # Apply Safety Projections
        if safety_mode != 'baseline':
            # P0: Max 25% single asset
            w_target = np.clip(w_target, 0.0, 0.25)
            
            if safety_mode in ['P1', 'P3', 'P4']:
                # P1: Leverage exposure limit E_max = 1.5
                E_t = 3.0 * np.sum(w_target[LEVERAGED_3X_INDICES])
                if E_t > 1.5:
                    scaling_factor = 1.5 / E_t
                    w_target[LEVERAGED_3X_INDICES] = w_target[LEVERAGED_3X_INDICES] * scaling_factor
                    
            if safety_mode in ['P3', 'P4']:
                # P3: Hard Drawdown State Machine
                current_dd = (portfolio_value - running_max) / running_max
                
                if in_cooldown > 0:
                    w_target[:] = 0.0
                    w_target[BIL_INDEX] = 1.0
                    in_cooldown -= 1
                else:
                    if current_dd < -0.12:
                        w_target[:] = 0.0
                        w_target[BIL_INDEX] = 1.0
                        in_cooldown = 10 # 10 trading periods cooldown
                    elif current_dd < -0.10:
                        # 3x ETF total cap 15%
                        total_3x = np.sum(w_target[LEVERAGED_3X_INDICES])
                        if total_3x > 0.15:
                            w_target[LEVERAGED_3X_INDICES] = w_target[LEVERAGED_3X_INDICES] * (0.15 / total_3x)
                    elif current_dd < -0.08:
                        # Risk halved
                        w_target[LEVERAGED_3X_INDICES] = w_target[LEVERAGED_3X_INDICES] * 0.5
            
            # Put remainder in BIL
            remainder = 1.0 - np.sum(w_target)
            if remainder > 0:
                w_target[BIL_INDEX] += remainder
            w_target = w_target / np.sum(w_target)
            
            if safety_mode == 'P4':
                # P4: Deadband 5%
                turnover_intent = 0.5 * np.sum(np.abs(w_target - previous_weights))
                if turnover_intent < 0.05:
                    w_target = previous_weights
        
        # Execute Step
        turnover = 0.5 * np.sum(np.abs(w_target - previous_weights))
        t_cost = turnover * slip_rate
        
        ret_fwd = returns[step_idx]
        port_ret = np.sum(w_target * ret_fwd) - t_cost
        
        portfolio_value *= (1.0 + port_ret)
        running_max = max(running_max, portfolio_value)
        pnl_history.append(portfolio_value)
        previous_weights = w_target

    years = max_steps / 252.0
    cagr = (portfolio_value ** (1 / years)) - 1.0 if years > 0 else 0.0
    
    if len(pnl_history) > 0:
        pnl_arr = np.array(pnl_history)
        running_max_arr = np.maximum.accumulate(pnl_arr)
        drawdowns = (pnl_arr - running_max_arr) / running_max_arr
        max_dd = np.min(drawdowns)
        
    return cagr * 100, max_dd * 100

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

def main():
    print("🚀 [START] V2 Safety Playback Replay...", flush=True)
    df = pd.read_parquet(DATA_PATH).sort_index()
    assets = ["TQQQ", "SOXL", "FAS", "CURE", "URTY", "DRN", "ERX", "TMF", "BIL"]
    # We use the old basic features so we accurately replay the V2 state
    base_features = ['return_21d', 'return_90d', 'volatility_21d', 'z_score_252d', 'rsi_14d', 'macd_hist', 'vix_level', 'tnx_level']
    
    windows = [
        {"name": "2018-2019", "train_end": "2017-12-31", "test_start": "2018-01-01", "test_end": "2019-12-31"},
        {"name": "2020-2021", "train_end": "2019-12-31", "test_start": "2020-01-01", "test_end": "2021-12-31"},
        {"name": "2022-2023", "train_end": "2021-12-31", "test_start": "2022-01-01", "test_end": "2023-12-31"},
        {"name": "2024-End",  "train_end": "2023-12-31", "test_start": "2024-01-01", "test_end": "2099-12-31"}
    ]
    
    md_content = "# 🛡️ V2-P0至P4 投影层回放审计报告 (Playback)\n\n"
    md_content += "> 不重新训练，针对同一个高集中度 Actor 逐层施加约束，测试原始选股信号是否真实存在 Alpha。\n\n"
    
    modes = ['baseline', 'P0', 'P1', 'P3', 'P4']
    
    for w in windows:
        print(f"\n  -> Fold {w['name']}...", flush=True)
        md_content += f"### 周期: {w['name']}\n"
        md_content += "| 安全层版本 | 规则说明 | CAGR | Max DD |\n|---|---|---|---|\n"
        
        train_df = df[(df.index >= "2010-01-01") & (df.index <= w['train_end'])]
        test_df = df[(df.index >= w['test_start']) & (df.index <= w['test_end'])]
        
        df_assets = train_df[train_df['Ticker'].isin(assets)].copy()
        pivot_feat = df_assets.pivot_table(index=df_assets.index, columns='Ticker', values=base_features).fillna(0)
        pivot_ret = df_assets.pivot_table(index=df_assets.index, columns='Ticker', values='target_fwd_return_21d').fillna(0)
        common_dates = pivot_feat.index.intersection(pivot_ret.index)
        train_feat_df, train_ret = pivot_feat.loc[common_dates], pivot_ret.loc[common_dates][assets].values
        
        df_assets_t = test_df[test_df['Ticker'].isin(assets)].copy()
        pivot_feat_t = df_assets_t.pivot_table(index=df_assets_t.index, columns='Ticker', values=base_features).fillna(0)
        pivot_ret_t = df_assets_t.pivot_table(index=df_assets_t.index, columns='Ticker', values='target_fwd_return_21d').fillna(0)
        common_dates_t = pivot_feat_t.index.intersection(pivot_ret_t.index)
        test_feat_df, test_ret = pivot_feat_t.loc[common_dates_t], pivot_ret_t.loc[common_dates_t][assets].values
        
        train_mean = train_feat_df.values.mean(axis=0)
        train_std = train_feat_df.values.std(axis=0) + 1e-8
        train_feat = (train_feat_df.values - train_mean) / train_std
        test_feat = (test_feat_df[train_feat_df.columns].values - train_mean) / train_std
        
        train_seq = create_sequences(train_feat, 30)
        test_seq = create_sequences(test_feat, 30)
        
        train_env = JaxSequencePortfolioEnv(train_seq, train_ret, slip_rate=0.002)
        train_fn = make_train_fn(train_env, hp_lr=0.0003, hp_ent=0.02, total_timesteps=2_000_000)
        jit_train = jax.jit(train_fn)
        
        # Train once for seed 42
        trained_params = jit_train(jax.random.PRNGKey(42))
        
        # Playback evaluation for each mode
        for mode in modes:
            print(f"     -> Testing Mode {mode}...", flush=True)
            cagr, dd = run_playback_eval(trained_params, test_seq, test_ret, slip_rate=0.002, safety_mode=mode)
            
            rule_desc = "原始输出 (无约束)" if mode == 'baseline' else \
                        "单资产25%上限 (盈余转BIL)" if mode == 'P0' else \
                        "P0 + 杠杆敞口上限1.5倍" if mode == 'P1' else \
                        "P1 + 回撤状态机(硬熔断)" if mode == 'P3' else \
                        "P3 + 5%交易死区" # P4
                        
            md_content += f"| {mode} | {rule_desc} | {cagr:.2f}% | {dd:.2f}% |\n"
            
    with open(REPORT_PATH, "w") as f:
        f.write(md_content)
    print(f"\n✅ Playback Replay Complete. Report at: {REPORT_PATH}", flush=True)

if __name__ == "__main__":
    main()
