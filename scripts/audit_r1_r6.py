import os
import jax
import jax.numpy as jnp
import pandas as pd
import numpy as np
from flax import struct
import flax.linen as nn
import optax
import warnings

warnings.filterwarnings('ignore')

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "processed", "ai_training_dataset.parquet")

# (Copying the network definition from previous script so we can load the weights)
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

@struct.dataclass
class EnvParams:
    features: jnp.ndarray
    returns: jnp.ndarray
    max_steps: int
    num_assets: int
    slip_rate: float
    max_weight: float
    max_tech_weight: float
    max_total_3x: float

@struct.dataclass
class EnvState:
    current_step: jnp.ndarray
    portfolio_value: jnp.ndarray
    previous_weights: jnp.ndarray

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
            max_weight=0.30,
            max_tech_weight=0.30,
            max_total_3x=0.40
        )

    def reset(self, key, params):
        start_step = jax.random.randint(key, shape=(), minval=0, maxval=params.max_steps // 2)
        init_weights = jnp.zeros(params.num_assets).at[-1].set(1.0)
        state = EnvState(current_step=start_step, portfolio_value=jnp.float32(1.0), previous_weights=init_weights)
        return params.features[state.current_step], state

    def step(self, key, state, action, params):
        exp_a = jnp.exp(action)
        weights = exp_a / jnp.sum(exp_a)
        weights = jnp.clip(weights, 0.0, params.max_weight)
        tech_w = weights[0] + weights[1]
        tech_scale = jnp.where(tech_w > params.max_tech_weight, params.max_tech_weight / (tech_w + 1e-8), 1.0)
        weights = weights.at[0].mul(tech_scale)
        weights = weights.at[1].mul(tech_scale)
        total_3x_w = jnp.sum(weights[:8])
        total_scale = jnp.where(total_3x_w > params.max_total_3x, params.max_total_3x / (total_3x_w + 1e-8), 1.0)
        weights = weights.at[:8].mul(total_scale)
        remainder = 1.0 - jnp.sum(weights)
        weights = weights.at[-1].add(jnp.maximum(0.0, remainder))
        weights = weights / jnp.sum(weights)
        
        turnover = 0.5 * jnp.sum(jnp.abs(weights - state.previous_weights))
        transaction_cost = turnover * params.slip_rate
        net_return = jnp.sum(weights * params.returns[state.current_step]) - transaction_cost
        new_portfolio_value = state.portfolio_value * (1.0 + net_return)
        new_step = state.current_step + 21
        done = new_step >= params.max_steps
        obs_idx = jnp.minimum(new_step, params.max_steps)
        return params.features[obs_idx], EnvState(current_step=new_step, portfolio_value=new_portfolio_value, previous_weights=weights), 0.0, done, {}

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
                return (next_obs, next_env_state, rng), (obs, action, reward, value, logprob, done)
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
        # Using 50k steps for faster pre-training just to get a stable base for audit
        chunk_size = num_updates // 4
        for chunk in range(4):
            runner_state, _ = jax.lax.scan(_update_step, runner_state, None, length=chunk_size)
        return runner_state[0]
    return train

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

def run_playback_eval(network_params, features, test_hist_ret, test_ret_daily, test_df, mode, mode_name="R3"):
    LEVERAGED_3X_INDICES = list(range(8))
    BIL_INDEX = 8
    network = TransformerActorCritic(action_dim=9)
    max_steps = features.shape[0] - 1
    steps_arr = np.arange(0, max_steps, 1)
    portfolio_value = 1.0
    previous_weights = np.zeros(9)
    previous_weights[BIL_INDEX] = 1.0
    running_max = 1.0
    
    in_cooldown = 0
    recovery_stage = 0
    recovery_timer = 0
    
    # Audit lists
    audit_records = []
    
    # State tracking lists
    state_machine_trigger_count = 0
    state_machine_days = 0
    dual_bear_trigger_days = 0
    recovery_try_count = 0
    recovery_success_count = 0
    active_risk_modify_days = 0
    
    slip_rate = 0.005
    dates = test_df.index.tolist()
        
    for step_idx in steps_arr:
        date_str = dates[step_idx].strftime('%Y-%m-%d')
        obs = features[step_idx]
        obs_batched = np.expand_dims(obs, 0)
        mean, _, _ = network.apply(network_params, obs_batched)
        action = np.squeeze(mean, 0)
        
        exp_a = np.exp(action)
        w_raw = exp_a / np.sum(exp_a)
        w_target = np.copy(w_raw)
        
        w_target = np.clip(w_target, 0.0, 0.30)
        tech_w = w_target[0] + w_target[1]
        if tech_w > 0.30:
            w_target[0] *= 0.30 / (tech_w + 1e-8)
            w_target[1] *= 0.30 / (tech_w + 1e-8)
            
        dynamic_3x_cap = 0.40
        w_raw_3x = np.sum(w_target[:8])
        k_t = 1.0
        hat_sigma = 0.0
            
        if mode in ['R1', 'R2', 'R3', 'R4', 'R5', 'R6']:
            vol_target = {'R1': 0.15, 'R2': 0.12, 'R3': 0.10, 'R4': 0.12, 'R5': 0.12, 'R6': 0.12}[mode]
            if step_idx > 63:
                past_ret_21 = test_hist_ret[step_idx-21:step_idx]
                past_ret_63 = test_hist_ret[step_idx-63:step_idx]
                port_ret_21 = past_ret_21 @ w_target
                port_ret_63 = past_ret_63 @ w_target
                sigma_21 = np.std(port_ret_21) * np.sqrt(252)
                sigma_63 = np.std(port_ret_63) * np.sqrt(252)
                hat_sigma = max(sigma_21, sigma_63)
                if hat_sigma > 0:
                    k_t = min(1.0, vol_target / hat_sigma)
            dynamic_3x_cap = 0.40 * k_t
            
        current_dd = (portfolio_value - running_max) / running_max
        bil_req = 0.0
        
        pre_state_cap = dynamic_3x_cap
        
        if mode in ['R4', 'R5', 'R6']:
            if in_cooldown > 0:
                dynamic_3x_cap = 0.0
                in_cooldown -= 1
                state_machine_days += 1
                if in_cooldown == 0 and mode == 'R6':
                    recovery_stage = 1
                    recovery_timer = 3
                    recovery_try_count += 1
            else:
                if current_dd < -0.12:
                    dynamic_3x_cap = 0.0
                    in_cooldown = 10
                    recovery_stage = 0
                    state_machine_trigger_count += 1
                    state_machine_days += 1
                elif current_dd < -0.08:
                    dynamic_3x_cap *= 0.35
                    recovery_stage = 0
                    state_machine_days += 1
                elif current_dd < -0.05:
                    dynamic_3x_cap *= 0.70
                    recovery_stage = 0
                    state_machine_days += 1
                else:
                    if mode == 'R6' and recovery_stage > 0:
                        state_machine_days += 1
                        if recovery_stage == 1:
                            dynamic_3x_cap = min(dynamic_3x_cap, 0.10)
                        elif recovery_stage == 2:
                            dynamic_3x_cap = min(dynamic_3x_cap, 0.20)
                        recovery_timer -= 1
                        if recovery_timer <= 0:
                            recovery_stage += 1
                            recovery_timer = 3
                            if recovery_stage > 2:
                                recovery_stage = 0
                                recovery_success_count += 1
                                
        if mode in ['R5', 'R6']:
            if step_idx > 63:
                past_63_tqqq = np.prod(1.0 + test_hist_ret[step_idx-63:step_idx, 0]) - 1.0
                past_63_tmf = np.prod(1.0 + test_hist_ret[step_idx-63:step_idx, 7]) - 1.0
                std_tqqq = np.std(test_hist_ret[step_idx-63:step_idx, 0])
                std_tmf = np.std(test_hist_ret[step_idx-63:step_idx, 7])
                if std_tqqq > 1e-8 and std_tmf > 1e-8:
                    corr_63 = np.corrcoef(test_hist_ret[step_idx-63:step_idx, 0], test_hist_ret[step_idx-63:step_idx, 7])[0, 1]
                else:
                    corr_63 = 0.0
                if past_63_tqqq < 0 and past_63_tmf < 0 and corr_63 > 0:
                    dynamic_3x_cap = min(dynamic_3x_cap, 0.15)
                    dual_bear_trigger_days += 1
                    if w_target[7] > 0.10:
                        w_target[7] = 0.10
                        
        total_3x = np.sum(w_target[LEVERAGED_3X_INDICES])
        if total_3x > dynamic_3x_cap:
            w_target[LEVERAGED_3X_INDICES] *= (dynamic_3x_cap / (total_3x + 1e-8))
            
        if mode in ['R4', 'R5', 'R6'] and in_cooldown == 0:
            if current_dd < -0.12:
                bil_req = 1.0
            elif current_dd < -0.08:
                bil_req = 0.75
            elif current_dd < -0.05:
                bil_req = 0.50
                
        remainder = 1.0 - np.sum(w_target[:8])
        w_target[BIL_INDEX] = max(remainder, bil_req)
        w_target = w_target / np.sum(w_target)
        
        w_exec_3x = np.sum(w_target[:8])
        
        if abs(w_exec_3x - w_raw_3x) > 0.01:
            active_risk_modify_days += 1
        
        turnover = 0.5 * np.sum(np.abs(w_target - previous_weights))
        t_cost = turnover * slip_rate
        ret_fwd = test_ret_daily[step_idx]
        port_ret = np.sum(w_target * ret_fwd) - t_cost
        
        portfolio_value *= (1.0 + port_ret)
        running_max = max(running_max, portfolio_value)
        previous_weights = w_target
        
        # AUDIT TRACE
        if mode_name == 'R3' and '2020-02-01' <= date_str <= '2020-05-31':
            audit_records.append({
                "Date": date_str,
                "Actor Raw 3x": f"{w_raw_3x:.4f}",
                "Sigma_hat": f"{hat_sigma:.4f}",
                "k_t": f"{k_t:.4f}",
                "Exec 3x": f"{w_exec_3x:.4f}",
                "Daily Ret": f"{port_ret:.4f}",
                "DD": f"{current_dd:.4f}"
            })
            
    stats = {
        "state_machine_trigger_count": state_machine_trigger_count,
        "state_machine_days": state_machine_days,
        "dual_bear_trigger_days": dual_bear_trigger_days,
        "recovery_try_count": recovery_try_count,
        "recovery_success_count": recovery_success_count,
        "active_risk_modify_days": active_risk_modify_days,
        "audit_df": pd.DataFrame(audit_records) if len(audit_records) > 0 else None
    }
    return stats

def main():
    print("🚀 [START] Audit R1-R6...", flush=True)
    df = pd.read_parquet(DATA_PATH).sort_index()
    assets = ["TQQQ", "SOXL", "FAS", "CURE", "URTY", "DRN", "ERX", "TMF", "BIL"]
    base_features = ['return_21d', 'return_90d', 'volatility_21d', 'z_score_252d', 'ma_200_dist', 'rsi_14d', 'macd_hist', 'vix_level', 'tnx_level', 'corr_spy_tlt_63d']
    
    # We only need 2020-2021 fold, Seed 42 for audit, and we can run R4-R6 to get trigger counts
    train_end = "2019-12-31"
    test_start = "2020-01-01"
    test_end = "2021-12-31"
    seed = 42
    
    train_df = df[(df.index >= "2010-01-01") & (df.index <= train_end)]
    df_assets = train_df[train_df['Ticker'].isin(assets)].copy()
    pivot_feat = df_assets.pivot_table(index=df_assets.index, columns='Ticker', values=base_features).fillna(0)
    pivot_ret = df_assets.pivot_table(index=df_assets.index, columns='Ticker', values='target_fwd_return_21d').fillna(0)
    common = pivot_feat.index.intersection(pivot_ret.index)
    train_feat_df, train_ret = pivot_feat.loc[common], pivot_ret.loc[common][assets].values
    
    train_mean = train_feat_df.values.mean(axis=0)
    train_std = train_feat_df.values.std(axis=0) + 1e-8
    train_feat = (train_feat_df.values - train_mean) / train_std
    train_seq = create_sequences(train_feat, 30)
    
    train_env = JaxSequencePortfolioEnv(train_seq, train_ret)
    # Quick train
    train_fn = make_train_fn(train_env, hp_lr=0.0003, hp_ent=0.02, total_timesteps=100_000) 
    jit_train = jax.jit(train_fn)
    trained_params = jit_train(jax.random.PRNGKey(seed))
    
    test_df = df[(df.index >= test_start) & (df.index <= test_end)]
    df_assets_t = test_df[test_df['Ticker'].isin(assets)].copy()
    pivot_feat_t = df_assets_t.pivot_table(index=df_assets_t.index, columns='Ticker', values=base_features).fillna(0)
    pivot_ret_t = df_assets_t.pivot_table(index=df_assets_t.index, columns='Ticker', values='Close').pct_change().shift(-1).fillna(0)
    common_t = pivot_feat_t.index.intersection(pivot_ret_t.index)
    test_feat_df, test_ret_daily = pivot_feat_t.loc[common_t], pivot_ret_t.loc[common_t][assets].values
    test_hist_ret = df_assets_t.pivot_table(index=df_assets_t.index, columns='Ticker', values='Close').pct_change().fillna(0).loc[common_t][assets].values
    test_feat = (test_feat_df[base_features].values - train_mean) / train_std if len(base_features) == test_feat_df.shape[1] else (test_feat_df.values - train_mean) / train_std
    test_seq = create_sequences(test_feat, 30)
    
    print("--- 1. 审计 R3 2020年回撤问题 ---")
    res_r3 = run_playback_eval(trained_params, test_seq, test_hist_ret, test_ret_daily, test_df, 'R3', 'R3')
    audit_df = res_r3['audit_df']
    audit_df.to_csv("../v4_audit_R3_2020.csv", index=False)
    print("Exported audit trace to v4_audit_R3_2020.csv")
    
    print("\n--- 2. 统计 R4-R6 门控触发 ---")
    for mode in ['R4', 'R5', 'R6']:
        res = run_playback_eval(trained_params, test_seq, test_hist_ret, test_ret_daily, test_df, mode, mode)
        print(f"[{mode}] 熔断触发: {res['state_machine_trigger_count']}次 | 熔断状态天数: {res['state_machine_days']}天 | "
              f"双杀门天数: {res['dual_bear_trigger_days']}天 | 再入场尝试: {res['recovery_try_count']}次 | 再入场成功: {res['recovery_success_count']}次 | "
              f"风控实质改动天数: {res['active_risk_modify_days']}天")

if __name__ == "__main__":
    main()
