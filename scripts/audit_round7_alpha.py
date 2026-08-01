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
REPORT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "v4_round7_alpha_attribution.md")

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

def run_playback(network_params, features, ret_daily, dates_arr, eval_start_idx):
    LEVERAGED_3X_INDICES = list(range(8))
    BIL_INDEX = 8
    network = TransformerActorCritic(action_dim=9)
    
    portfolio_value = 1.0
    previous_weights = np.zeros(9)
    previous_weights[BIL_INDEX] = 1.0
    
    daily_returns_arr = []
    daily_costs_arr = []
    
    slip_rate = 0.005
    fixed_vol = 0.10
    
    for step_idx in range(eval_start_idx, len(dates_arr)):
        obs = features[step_idx]
        obs_batched = np.expand_dims(obs, 0)
        mean, _, _ = network.apply(network_params, obs_batched)
        action = np.squeeze(mean, 0)
        
        exp_a = np.exp(action)
        w_target = exp_a / np.sum(exp_a)
        
        w_target = np.clip(w_target, 0.0, 0.30)
        tech_w = w_target[0] + w_target[1]
        if tech_w > 0.30:
            w_target[0] *= 0.30 / (tech_w + 1e-8)
            w_target[1] *= 0.30 / (tech_w + 1e-8)
            
        total_3x = np.sum(w_target[LEVERAGED_3X_INDICES])
        if total_3x > fixed_vol:
            w_target[LEVERAGED_3X_INDICES] *= (fixed_vol / (total_3x + 1e-8))
            
        remainder = 1.0 - np.sum(w_target[:8])
        w_target[BIL_INDEX] = max(remainder, 0.0)
        w_target = w_target / np.sum(w_target)
        
        turnover = 0.5 * np.sum(np.abs(w_target - previous_weights))
        t_cost = turnover * slip_rate
        
        port_ret = np.sum(w_target * ret_daily[step_idx]) - t_cost
        
        daily_returns_arr.append(port_ret)
        daily_costs_arr.append(t_cost)
        previous_weights = w_target

    return np.array(daily_returns_arr), np.array(daily_costs_arr)

def run_simple_baseline(test_ret_daily, dates_arr, eval_start_idx):
    fixed_risk = 0.10
    daily_returns_arr = []
    daily_costs_arr = []
    
    prev_w_tqqq = 0.0
    prev_w_bil = 1.0
    
    for step_idx in range(eval_start_idx, len(dates_arr)):
        w_tqqq = fixed_risk
        w_bil = 1.0 - fixed_risk
        turnover = 0.5 * (abs(w_tqqq - prev_w_tqqq) + abs(w_bil - prev_w_bil))
        t_cost = turnover * 0.005
        
        ret = fixed_risk * test_ret_daily[step_idx, 0] + (1 - fixed_risk) * test_ret_daily[step_idx, 8] - t_cost
        daily_returns_arr.append(ret)
        daily_costs_arr.append(t_cost)
        
        # update prev weights simulating daily rebalancing
        # In reality, daily rebalancing is assumed
        prev_w_tqqq = w_tqqq
        prev_w_bil = w_bil
        
    return np.array(daily_returns_arr), np.array(daily_costs_arr)

def cagr_from_rets(rets):
    years = len(rets) / 252.0
    return (np.prod(1.0 + rets) ** (1 / years)) - 1.0 if years > 0 else 0.0

def dd_from_rets(rets):
    cum = np.cumprod(1.0 + rets)
    run_max = np.maximum.accumulate(cum)
    dd = (cum - run_max) / (run_max + 1e-8)
    return np.min(dd) if len(dd) > 0 else 0.0
    
def active_max_dd(act_rets):
    cum = np.cumprod(1.0 + act_rets)
    run_max = np.maximum.accumulate(cum)
    dd = (cum - run_max) / (run_max + 1e-8)
    return np.min(dd) if len(dd) > 0 else 0.0

def main():
    print("🚀 [START] V4 Round 7: Active Return Attribution...", flush=True)
    df = pd.read_parquet(DATA_PATH).sort_index()
    assets = ["TQQQ", "SOXL", "FAS", "CURE", "URTY", "DRN", "ERX", "TMF", "BIL"]
    base_features = ['return_21d', 'return_90d', 'volatility_21d', 'z_score_252d', 'ma_200_dist', 'rsi_14d', 'macd_hist', 'vix_level', 'tnx_level', 'corr_spy_tlt_63d']
    
    end_dt_str = str(df.index.max().date())
    
    folds = [
        {"name": "2018-2019", "train_end": "2017-12-31", "test_start": "2018-01-01", "test_end": "2019-12-31"},
        {"name": "2020-2021", "train_end": "2019-12-31", "test_start": "2020-01-01", "test_end": "2021-12-31"},
        {"name": "2022-2023", "train_end": "2021-12-31", "test_start": "2022-01-01", "test_end": "2023-12-31"},
        {"name": "2024-End", "train_end": "2023-12-31", "test_start": "2024-01-01", "test_end": end_dt_str}
    ]
    seeds = [41, 42, 43, 44, 45]
    
    all_qount_rets = []
    all_simp_rets = []
    all_q_costs = []
    all_s_costs = []
    all_states = []
    
    for fold in folds:
        print(f"\n⚙️ Processing Fold {fold['name']}...", flush=True)
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
        
        train_fn = make_train_fn(train_env, hp_lr=0.0003, hp_ent=0.02, total_timesteps=150_000) 
        jit_train = jax.jit(train_fn)
        
        fold_qount_rets_sum = None
        fold_q_costs_sum = None
        
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
        
        eval_start_idx = 0
        for i, d in enumerate(unique_dates):
            if pd.to_datetime(d) >= test_start_ts:
                eval_start_idx = i
                break
                
        # Generate states for attribution
        state_labels = []
        for i in range(eval_start_idx, len(unique_dates)):
            past_63_tqqq = np.prod(1.0 + test_hist_ret[i-63:i, 0]) - 1.0 if i >= 63 else 0
            past_63_tmf = np.prod(1.0 + test_hist_ret[i-63:i, 7]) - 1.0 if i >= 63 else 0
            vol_tqqq = np.std(test_hist_ret[i-21:i, 0]) * np.sqrt(252) if i >= 21 else 0.5
            
            # Stock/Bond conditions
            is_stk_up = past_63_tqqq >= 0
            is_bnd_up = past_63_tmf >= 0
            
            # Vol conditions
            is_hi_vol = vol_tqqq > 0.60
            is_lo_vol = vol_tqqq < 0.40
            
            # Trend conditions
            is_strong_trend = past_63_tqqq > 0.20
            is_sideways = abs(past_63_tqqq) < 0.10
            
            lbls = []
            if is_stk_up and is_bnd_up: lbls.append("StockUp_BondUp")
            if is_stk_up and not is_bnd_up: lbls.append("StockUp_BondDown")
            if not is_stk_up and is_bnd_up: lbls.append("StockDown_BondUp")
            if not is_stk_up and not is_bnd_up: lbls.append("StockDown_BondDown")
            
            if is_hi_vol: lbls.append("HighVol")
            if is_lo_vol: lbls.append("LowVol")
            
            if is_strong_trend: lbls.append("StrongTrend")
            if is_sideways: lbls.append("Sideways")
            
            state_labels.append(lbls)
        
        all_states.extend(state_labels)

        for seed in seeds:
            print(f"    - Seed {seed}...", flush=True)
            trained_params = jit_train(jax.random.PRNGKey(seed))
            q_rets, q_costs = run_playback(trained_params, test_seq, test_ret_daily, unique_dates, eval_start_idx)
            
            if fold_qount_rets_sum is None:
                fold_qount_rets_sum = q_rets
                fold_q_costs_sum = q_costs
            else:
                fold_qount_rets_sum += q_rets
                fold_q_costs_sum += q_costs
                
        jax.clear_caches()
        
        # Average over seeds
        q_rets_avg = fold_qount_rets_sum / len(seeds)
        q_costs_avg = fold_q_costs_sum / len(seeds)
        
        # Run Baseline
        s_rets, s_costs = run_simple_baseline(test_ret_daily, unique_dates, eval_start_idx)
        
        all_qount_rets.extend(q_rets_avg)
        all_simp_rets.extend(s_rets)
        all_q_costs.extend(q_costs_avg)
        all_s_costs.extend(s_costs)

    all_qount_rets = np.array(all_qount_rets)
    all_simp_rets = np.array(all_simp_rets)
    all_q_costs = np.array(all_q_costs)
    all_s_costs = np.array(all_s_costs)
    
    active_rets = all_qount_rets - all_simp_rets
    
    # Calculate overall metrics
    q_cagr = cagr_from_rets(all_qount_rets)
    s_cagr = cagr_from_rets(all_simp_rets)
    active_cagr = (1+q_cagr) - (1+s_cagr)
    
    tracking_err = np.std(active_rets) * np.sqrt(252)
    ir = active_cagr / (tracking_err + 1e-8)
    
    act_dd = active_max_dd(active_rets)
    
    win_days = np.sum(active_rets > 0)
    lose_days = np.sum(active_rets < 0)
    daily_win_rate = win_days / len(active_rets)
    
    up_days = all_simp_rets > 0
    up_capture = np.mean(all_qount_rets[up_days]) / (np.mean(all_simp_rets[up_days]) + 1e-8) if np.sum(up_days)>0 else 0
    down_days = all_simp_rets < 0
    down_capture = np.mean(all_qount_rets[down_days]) / (np.mean(all_simp_rets[down_days]) - 1e-8) if np.sum(down_days)>0 else 0
    
    # Cost diff
    cost_diff_annual = (np.mean(all_q_costs) - np.mean(all_s_costs)) * 252 * 100
    
    # State grouping
    state_metrics = {}
    for i, labels in enumerate(all_states):
        for lbl in labels:
            if lbl not in state_metrics:
                state_metrics[lbl] = []
            state_metrics[lbl].append(active_rets[i])
            
    md = f"# 📊 QOUNT AI 第7轮：Transformer主动Alpha归因测试 (F10 vs TQQQ10%)\n\n"
    md += "## 1. 核心主动归因指标 (全体样本平均)\n"
    md += "| 指标 | 数值 | 说明 |\n"
    md += "|---|---|---|\n"
    md += f"| QOUNT CAGR | {q_cagr*100:.2f}% | 模型组合绝对年化 |\n"
    md += f"| SimpleTQQQ CAGR | {s_cagr*100:.2f}% | 基准绝对年化 |\n"
    md += f"| Active CAGR | {active_cagr*100:.2f}% | 模型超额年化收益 |\n"
    md += f"| Tracking Error (TE) | {tracking_err*100:.2f}% | 主动收益的年化波动率 |\n"
    md += f"| Information Ratio (IR) | {ir:.2f} | 衡量单位主动风险换取的超额 |\n"
    md += f"| Active Max DD | {act_dd*100:.2f}% | 相对基准的最深相对回撤 |\n"
    md += f"| 日胜率 | {daily_win_rate*100:.1f}% | 跑赢基准的交易日占比 |\n"
    md += f"| 上涨捕获率 | {up_capture*100:.1f}% | 基准上涨时，模型能吃到的比例 |\n"
    md += f"| 下跌捕获率 | {down_capture*100:.1f}% | 基准下跌时，模型承担的损失比例 |\n"
    md += f"| 额外摩擦成本 | {cost_diff_annual:.2f}%/年 | 模型相对简单基准每年多付的交易损耗 |\n\n"
    
    md += "## 2. 市场状态切割 (主动收益拆解)\n"
    md += "| 市场状态 | 样本天数 | 平均日主动收益(bps) | 状态内年化超额 | 状态内IR |\n"
    md += "|---|---|---|---|---|\n"
    
    for state in ["StockUp_BondUp", "StockUp_BondDown", "StockDown_BondUp", "StockDown_BondDown", "HighVol", "LowVol", "StrongTrend", "Sideways"]:
        if state in state_metrics:
            rets = np.array(state_metrics[state])
            n = len(rets)
            mean_bps = np.mean(rets) * 10000
            ann_ret = np.mean(rets) * 252
            te_state = np.std(rets) * np.sqrt(252) + 1e-8
            ir_state = ann_ret / te_state
            md += f"| {state} | {n} | {mean_bps:.2f} | {ann_ret*100:.2f}% | {ir_state:.2f} |\n"

    with open(REPORT_PATH, "w") as f:
        f.write(md)
    print(f"\n✅ Attribution Complete. Report at: {REPORT_PATH}", flush=True)

if __name__ == "__main__":
    main()
