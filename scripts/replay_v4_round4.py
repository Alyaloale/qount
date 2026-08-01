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
REPORT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "v4_round4_report.md")

# ==========================================
# G2 Network (Frozen)
# ==========================================
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

def calc_ewma_vol(returns, span):
    df = pd.Series(returns)
    var = df.ewm(span=span).var()
    return np.sqrt(var.values[-1]) * np.sqrt(252) if len(returns) >= 2 else 0.0

def run_s_playback_eval(network_params, features, hist_ret, ret_daily, dates_arr, mode, eval_start_idx):
    LEVERAGED_3X_INDICES = list(range(8))
    BIL_INDEX = 8
    network = TransformerActorCritic(action_dim=9)
    
    portfolio_value = 1.0
    previous_weights = np.zeros(9)
    previous_weights[BIL_INDEX] = 1.0
    running_max = 1.0
    
    # State tracking
    sm_state = "NORMAL" # NORMAL, CAUTION, DEFENSIVE, KILL, PROBE, RECOVERY
    cooldown_timer = 0
    recovery_stage = 0
    recovery_timer = 0
    
    pnl_history = []
    daily_returns_arr = []
    weights_seq = []
    
    slip_rate = 0.005
    
    # Mode configurations
    enable_ewma_vol = mode in ['S1', 'S5', 'S6']
    enable_soft_dd = mode in ['S2']
    enable_state_machine = mode in ['S3', 'S5', 'S6']
    enable_dual_bear = mode in ['S4', 'S6']
    
    for step_idx in range(eval_start_idx, len(dates_arr)):
        obs = features[step_idx]
        obs_batched = np.expand_dims(obs, 0)
        mean, _, _ = network.apply(network_params, obs_batched)
        action = np.squeeze(mean, 0)
        
        exp_a = np.exp(action)
        w_target = exp_a / np.sum(exp_a)
        
        # G2 base caps
        w_target = np.clip(w_target, 0.0, 0.30)
        tech_w = w_target[0] + w_target[1]
        if tech_w > 0.30:
            w_target[0] *= 0.30 / (tech_w + 1e-8)
            w_target[1] *= 0.30 / (tech_w + 1e-8)
            
        dynamic_3x_cap = 0.40
        g_vol = 1.0
        g_dd = 1.0
        bil_req = 0.0
        shock_triggered = False
        dual_bear_triggered = False
        
        current_dd = (portfolio_value - running_max) / running_max if running_max > 0 else 0.0
        
        # --- Volatility Gate ---
        if enable_ewma_vol:
            past_ret_21 = hist_ret[step_idx-21:step_idx] @ w_target
            sigma_21 = np.std(past_ret_21) * np.sqrt(252) if len(past_ret_21) >= 2 else 0.0
            
            sigma_5_ewma = calc_ewma_vol(hist_ret[step_idx-5:step_idx] @ w_target, span=5)
            sigma_10_ewma = calc_ewma_vol(hist_ret[step_idx-10:step_idx] @ w_target, span=10)
            
            sigma_risk = max(sigma_5_ewma, sigma_10_ewma, sigma_21)
            if sigma_risk > 0:
                g_vol = min(1.0, 0.12 / sigma_risk) # target vol 12%
                
            port_ret_1d = np.sum(previous_weights * ret_daily[step_idx-1]) if step_idx > 0 else 0.0 # Approximation of port ret yesterday
            tqqq_5d = np.prod(1.0 + hist_ret[step_idx-5:step_idx, 0]) - 1.0 if step_idx >= 5 else 0.0
            
            if port_ret_1d < -0.03 or tqqq_5d < -0.15 or (sigma_21 > 0 and sigma_5_ewma / sigma_21 > 1.5):
                shock_triggered = True
                
        # --- Soft DD ---
        if enable_soft_dd:
            d = -current_dd
            if d < 0.03:
                g_dd = 1.0
            elif d < 0.08:
                g_dd = 1.0 - (0.75 * (d - 0.03) / 0.05)
            elif d < 0.12:
                g_dd = 0.25 - (0.25 * (d - 0.08) / 0.04)
            else:
                g_dd = 0.0
                
        # --- Dual Bear ---
        if enable_dual_bear:
            past_63_tqqq = np.prod(1.0 + hist_ret[step_idx-63:step_idx, 0]) - 1.0
            past_63_tmf = np.prod(1.0 + hist_ret[step_idx-63:step_idx, 7]) - 1.0
            std_tqqq = np.std(hist_ret[step_idx-63:step_idx, 0])
            std_tmf = np.std(hist_ret[step_idx-63:step_idx, 7])
            corr_63 = 0.0
            if std_tqqq > 1e-8 and std_tmf > 1e-8:
                corr_63 = np.corrcoef(hist_ret[step_idx-63:step_idx, 0], hist_ret[step_idx-63:step_idx, 7])[0, 1]
            if past_63_tqqq < 0 and past_63_tmf < 0 and corr_63 > 0:
                dual_bear_triggered = True

        # --- State Machine ---
        if enable_state_machine:
            # Check worsening conditions first
            if current_dd <= -0.09 or shock_triggered:
                if sm_state != "KILL":
                    sm_state = "KILL"
                    cooldown_timer = 5
            elif sm_state in ["NORMAL", "CAUTION", "DEFENSIVE"]:
                if current_dd > -0.03:
                    sm_state = "NORMAL"
                elif -0.06 < current_dd <= -0.03:
                    sm_state = "CAUTION"
                elif -0.09 < current_dd <= -0.06:
                    sm_state = "DEFENSIVE"
                    
            if sm_state == "KILL":
                if cooldown_timer > 0:
                    cooldown_timer -= 1
                else:
                    # Can we probe?
                    tqqq_5d = np.prod(1.0 + hist_ret[step_idx-5:step_idx, 0]) - 1.0
                    sigma_5_ewma = calc_ewma_vol(hist_ret[step_idx-5:step_idx] @ w_target, span=5)
                    sigma_21 = np.std(hist_ret[step_idx-21:step_idx] @ w_target) * np.sqrt(252)
                    if tqqq_5d > 0 and sigma_5_ewma < sigma_21 and not dual_bear_triggered:
                        sm_state = "PROBE"
                        recovery_timer = 3
                        
            elif sm_state == "DEFENSIVE":
                # Can also probe from defensive
                tqqq_5d = np.prod(1.0 + hist_ret[step_idx-5:step_idx, 0]) - 1.0
                sigma_5_ewma = calc_ewma_vol(hist_ret[step_idx-5:step_idx] @ w_target, span=5)
                sigma_21 = np.std(hist_ret[step_idx-21:step_idx] @ w_target) * np.sqrt(252)
                if tqqq_5d > 0 and sigma_5_ewma < sigma_21 and not dual_bear_triggered:
                    sm_state = "PROBE"
                    recovery_timer = 3
                    
            elif sm_state == "PROBE":
                recovery_timer -= 1
                if recovery_timer <= 0:
                    sm_state = "RECOVERY"
                    recovery_stage = 1
                    recovery_timer = 3
            
            elif sm_state == "RECOVERY":
                recovery_timer -= 1
                if recovery_timer <= 0:
                    recovery_stage += 1
                    recovery_timer = 3
                    if recovery_stage > 3:
                        sm_state = "NORMAL"
            
            # Apply state rules
            if sm_state == "NORMAL":
                dynamic_3x_cap = 0.40
            elif sm_state == "CAUTION":
                dynamic_3x_cap = 0.25
            elif sm_state == "DEFENSIVE":
                dynamic_3x_cap = 0.10
                bil_req = 0.75
            elif sm_state == "KILL":
                dynamic_3x_cap = 0.0
                bil_req = 1.0
            elif sm_state == "PROBE":
                dynamic_3x_cap = 0.10
            elif sm_state == "RECOVERY":
                if recovery_stage == 1: dynamic_3x_cap = 0.20
                elif recovery_stage == 2: dynamic_3x_cap = 0.30
                else: dynamic_3x_cap = 0.40
        else:
            # If no state machine, apply combinations
            dynamic_3x_cap = 0.40 * g_vol * g_dd
            if shock_triggered:
                dynamic_3x_cap = min(dynamic_3x_cap, 0.10)
                
        if enable_dual_bear and dual_bear_triggered:
            dynamic_3x_cap = min(dynamic_3x_cap, 0.15)
            if w_target[7] > 0.10:
                w_target[7] = 0.10
                
        # Final projection
        total_3x = np.sum(w_target[LEVERAGED_3X_INDICES])
        if total_3x > dynamic_3x_cap:
            w_target[LEVERAGED_3X_INDICES] *= (dynamic_3x_cap / (total_3x + 1e-8))
            
        remainder = 1.0 - np.sum(w_target[:8])
        w_target[BIL_INDEX] = max(remainder, bil_req)
        w_target = w_target / np.sum(w_target)
        
        turnover = 0.5 * np.sum(np.abs(w_target - previous_weights))
        t_cost = turnover * slip_rate
        
        port_ret = np.sum(w_target * ret_daily[step_idx]) - t_cost
        
        portfolio_value *= (1.0 + port_ret)
        running_max = max(running_max, portfolio_value)
        pnl_history.append(portfolio_value)
        daily_returns_arr.append(port_ret)
        weights_seq.append(w_target)
        previous_weights = w_target

    years = len(pnl_history) / 252.0
    cagr = (portfolio_value ** (1 / years)) - 1.0 if years > 0 else 0.0
    
    port_vals_arr = np.array(pnl_history)
    running_max_arr = np.maximum.accumulate(port_vals_arr)
    drawdowns = (port_vals_arr - running_max_arr) / (running_max_arr + 1e-8)
    max_dd = np.min(drawdowns) if len(drawdowns) > 0 else 0.0
    
    daily_returns_arr = np.array(daily_returns_arr)
    mean_ret = np.mean(daily_returns_arr)
    std_ret = np.std(daily_returns_arr) + 1e-8
    sharpe = (mean_ret / std_ret) * np.sqrt(252)
    
    weights_arr = np.array(weights_seq)
    mean_3x = np.mean(np.sum(weights_arr[:, :8], axis=1))
    
    if len(port_vals_arr) > 21:
        ret_21 = (port_vals_arr[21:] - port_vals_arr[:-21]) / (port_vals_arr[:-21] + 1e-8)
        worst_21d = np.min(ret_21)
    else:
        worst_21d = 0.0
        
    sorted_ret = np.sort(daily_returns_arr)
    if len(sorted_ret) > 10:
        ret_no_top10 = sorted_ret[:-10]
        cagr_no_top10 = (np.prod(1.0 + ret_no_top10) ** (1 / years)) - 1.0
    else:
        cagr_no_top10 = 0.0
        
    # Middle 90%
    if len(sorted_ret) > 20:
        trim_cnt = int(len(sorted_ret) * 0.05)
        mid_90_ret = sorted_ret[trim_cnt:-trim_cnt]
        mean_90 = np.mean(mid_90_ret)
    else:
        mean_90 = mean_ret
        
    # Recovery Days Fix
    is_recovering = False
    max_recovery_days = 0
    current_recovery_days = 0
    for dd in drawdowns:
        if dd < 0:
            is_recovering = True
            current_recovery_days += 1
        else:
            if is_recovering:
                max_recovery_days = max(max_recovery_days, current_recovery_days)
            is_recovering = False
            current_recovery_days = 0
    if is_recovering:
        max_recovery_days = max(max_recovery_days, current_recovery_days)
        
    is_recovered_at_end = (drawdowns[-1] == 0)

    return {
        "CAGR": cagr * 100,
        "Max DD": max_dd * 100,
        "Sharpe": sharpe,
        "Mean 3x": mean_3x * 100,
        "Worst 21d": worst_21d * 100,
        "CAGR -Top10": cagr_no_top10 * 100,
        "Mid90 Mean(bps)": mean_90 * 10000,
        "Recovery Days": int(max_recovery_days),
        "Is Recovered": is_recovered_at_end
    }

def main():
    print("🚀 [START] V4 Round 4: Independent S-Series Replay...", flush=True)
    df = pd.read_parquet(DATA_PATH).sort_index()
    assets = ["TQQQ", "SOXL", "FAS", "CURE", "URTY", "DRN", "ERX", "TMF", "BIL"]
    base_features = ['return_21d', 'return_90d', 'volatility_21d', 'z_score_252d', 'ma_200_dist', 'rsi_14d', 'macd_hist', 'vix_level', 'tnx_level', 'corr_spy_tlt_63d']
    
    folds = [
        {"name": "2020-2021", "train_end": "2019-12-31", "test_start": "2020-01-01", "test_end": "2021-12-31"},
        {"name": "2022-2023", "train_end": "2021-12-31", "test_start": "2022-01-01", "test_end": "2023-12-31"}
    ]
    seeds = [42, 43, 44]
    modes = ['S0', 'S1', 'S2', 'S3', 'S4', 'S5', 'S6']
    
    md_content = "# 🛡️ QOUNT AI 第4轮：独立控制组件测试 (S0-S6)\n\n"
    md_content += "使用带预热期（修复冷启动Bug）的环境，测试 EWMA波动率、六阶状态机等独立组件。\n\n"
    
    print("⚙️ Pre-training G2 baselines...", flush=True)
    trained_models = {}
    for fold in folds:
        for seed in seeds:
            train_df = df[(df.index >= "2010-01-01") & (df.index <= fold['train_end'])]
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
            # Use 200k steps for decent stability, fast enough
            train_fn = make_train_fn(train_env, hp_lr=0.0003, hp_ent=0.02, total_timesteps=200_000) 
            jit_train = jax.jit(train_fn)
            trained_params = jit_train(jax.random.PRNGKey(seed))
            trained_models[(fold['name'], seed)] = (trained_params, train_mean, train_std)
    
    for mode in modes:
        print(f"\n⚙️ Testing Mode: {mode}", flush=True)
        md_content += f"## {mode}\n"
        md_content += "| 周期 | Seed | CAGR | Max DD | 恢复天数(期末恢复) | 最差21日 | 扣Top10 CAGR | 中间90%均收(bps) | Sharpe | 平均3x |\n"
        md_content += "|---|---|---|---|---|---|---|---|---|---|\n"
        
        all_cagr = []
        all_dd = []
        cagr_no_top10_list = []
        
        for fold in folds:
            print(f"  -> Fold {fold['name']}...", flush=True)
            for seed in seeds:
                trained_params, train_mean, train_std = trained_models[(fold['name'], seed)]
                
                # Fetch data including 100 days BEFORE test_start to provide history buffer!
                # Ensure we have enough trading days. 100 calendar days is ~70 trading days.
                # Actually let's fetch starting from 150 calendar days prior
                test_start_ts = pd.to_datetime(fold['test_start'])
                buffer_start = test_start_ts - pd.Timedelta(days=150)
                
                test_df = df[(df.index >= buffer_start) & (df.index <= fold['test_end'])]
                df_assets_t = test_df[test_df['Ticker'].isin(assets)].copy()
                pivot_feat_t = df_assets_t.pivot_table(index=df_assets_t.index, columns='Ticker', values=base_features).fillna(0)
                pivot_ret_t = df_assets_t.pivot_table(index=df_assets_t.index, columns='Ticker', values='Close').pct_change().shift(-1).fillna(0)
                common_t = pivot_feat_t.index.intersection(pivot_ret_t.index)
                
                test_feat_df, test_ret_daily = pivot_feat_t.loc[common_t], pivot_ret_t.loc[common_t][assets].values
                test_hist_ret = df_assets_t.pivot_table(index=df_assets_t.index, columns='Ticker', values='Close').pct_change().fillna(0).loc[common_t][assets].values
                
                test_feat = (test_feat_df[base_features].values - train_mean) / train_std if len(base_features) == test_feat_df.shape[1] else (test_feat_df.values - train_mean) / train_std
                test_seq = create_sequences(test_feat, 30)
                
                unique_dates = common_t.tolist()
                
                # Find the index where testing actually starts
                eval_start_idx = 0
                for i, d in enumerate(unique_dates):
                    if pd.to_datetime(d) >= test_start_ts:
                        eval_start_idx = i
                        break
                        
                res = run_s_playback_eval(trained_params, test_seq, test_hist_ret, test_ret_daily, unique_dates, mode, eval_start_idx)
                
                rec_str = f"{res['Recovery Days']}d" + ("(Y)" if res["Is Recovered"] else "(N)")
                md_content += (
                    f"| {fold['name']} | {seed} | {res['CAGR']:.2f}% | {res['Max DD']:.2f}% | "
                    f"{rec_str} | {res['Worst 21d']:.2f}% | {res['CAGR -Top10']:.2f}% | "
                    f"{res['Mid90 Mean(bps)']:.1f} | {res['Sharpe']:.2f} | {res['Mean 3x']:.1f}% |\n"
                )
                all_cagr.append(res['CAGR'])
                all_dd.append(res['Max DD'])
                cagr_no_top10_list.append(res['CAGR -Top10'])
                print(f"     -> Seed {seed} | CAGR: {res['CAGR']:.2f}% | DD: {res['Max DD']:.2f}%", flush=True)
                
        med_cagr = np.median(all_cagr)
        worst_dd = np.min(all_dd)
        med_no_top10 = np.median(cagr_no_top10_list)
        pos_no_top10_cnt = sum(1 for x in cagr_no_top10_list if x > 0)
        
        md_content += f"| **汇总** | - | **中位数: {med_cagr:.2f}%** | **最差 DD: {worst_dd:.2f}%** | - | - | **-Top10: {med_no_top10:.2f}% ({pos_no_top10_cnt}/6)** | - | - | - |\n\n"
        
    with open(REPORT_PATH, "w") as f:
        f.write(md_content)
        
    print(f"\n✅ Round 4 S-Series Complete. Report at: {REPORT_PATH}", flush=True)

if __name__ == "__main__":
    main()
