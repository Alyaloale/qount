import os
import jax
import jax.numpy as jnp
from flax import struct
import flax.linen as nn
import optax
import numpy as np

# ============================================================================
# 1. 动态交易成本模型 (Dynamic Transaction Cost Model)
# ============================================================================
def compute_dynamic_cost(delta_weights, volatility_t, slip_multiplier=1.0):
    """
    根据标的的波动率和固定摩擦，计算动态交易成本。
    c_t = spread/2 * |dw| + k * sigma * |dw| + fixed
    """
    fixed_spread = 0.001 # 基础点差假设
    volatility_impact = 0.02 * volatility_t # 高波动率带来极高的滑点
    
    # delta_weights: (num_assets,)
    cost_per_asset = (fixed_spread + volatility_impact) * jnp.abs(delta_weights)
    return jnp.sum(cost_per_asset) * slip_multiplier

# ============================================================================
# 2. 独立影子风控官 (Independent Safety Controller)
# ============================================================================
class SafetyController:
    """
    Safety Controller不追求收益，只监测极端风险并掌控最终的拨付比例(Alpha_t)。
    """
    @staticmethod
    def compute_alpha(drawdown, avg_volatility, uncertainty, corr_spike):
        # 1. 回撤风控
        dd_factor = jnp.exp(-10.0 * jnp.maximum(0.0, drawdown - 0.05)) # 超过5%回撤急剧收缩
        
        # 2. 极端波动风控
        vol_factor = jnp.exp(-5.0 * jnp.maximum(0.0, avg_volatility - 0.50)) # 年化波动过高则收缩
        
        # 3. 相关性崩塌风控 (如果股债同跌)
        corr_factor = jnp.exp(-2.0 * jnp.maximum(0.0, corr_spike))
        
        # 4. 模型分歧风控 (MC Dropout 方差)
        uncert_factor = jnp.exp(-5.0 * uncertainty)
        
        # 综合安全系数 Alpha_t (0到1之间，1代表完全信任Actor，0代表全现金)
        alpha_t = dd_factor * vol_factor * corr_factor * uncert_factor
        return jnp.clip(alpha_t, 0.0, 1.0)

    @staticmethod
    def apply_intervention(actor_weights, alpha_t, num_assets):
        # 强制混合: alpha * 风险配置 + (1 - alpha) * 绝对现金
        cash_weights = jnp.zeros(num_assets).at[-1].set(1.0) # 最后一个是BIL(现金)
        final_weights = alpha_t * actor_weights + (1.0 - alpha_t) * cash_weights
        return final_weights / jnp.sum(final_weights)

# ============================================================================
# 3. 强化学习环境 (完整的马尔可夫决策过程)
# ============================================================================
@struct.dataclass
class EnvState:
    current_step: jnp.ndarray
    portfolio_value: jnp.ndarray
    previous_weights: jnp.ndarray
    drawdown: jnp.ndarray
    high_water_mark: jnp.ndarray
    drawdown_duration: jnp.ndarray

@struct.dataclass
class EnvParams:
    features: jnp.ndarray      # (T, seq_len, num_features)
    returns: jnp.ndarray       # (T, num_assets)
    volatility: jnp.ndarray    # (T, num_assets) 用于动态滑点
    corr_spike: jnp.ndarray    # (T,) 股债相关性异常指标
    max_steps: int
    num_assets: int
    cost_multiplier: float     # 用于压力测试 (1x, 1.5x, 2x成本)
    no_trade_threshold: float  # 无交易区

class JaxSequencePortfolioEnv:
    def __init__(self, features, returns, volatility, corr_spike, cost_multiplier=1.0):
        self.num_assets = returns.shape[1]
        self.max_steps = features.shape[0] - 1
        self.default_params = EnvParams(
            features=jnp.array(features, dtype=jnp.float32),
            returns=jnp.array(returns, dtype=jnp.float32),
            volatility=jnp.array(volatility, dtype=jnp.float32),
            corr_spike=jnp.array(corr_spike, dtype=jnp.float32),
            max_steps=self.max_steps,
            num_assets=self.num_assets,
            cost_multiplier=cost_multiplier,
            no_trade_threshold=0.03
        )

    def reset(self, key, params):
        start_step = jax.random.randint(key, shape=(), minval=0, maxval=params.max_steps // 2)
        init_weights = jnp.zeros(params.num_assets).at[-1].set(1.0)
        state = EnvState(
            current_step=start_step,
            portfolio_value=jnp.float32(1.0),
            previous_weights=init_weights,
            drawdown=jnp.float32(0.0),
            high_water_mark=jnp.float32(1.0),
            drawdown_duration=jnp.float32(0.0)
        )
        return self._get_obs(state, params), state

    def _get_obs(self, state, params):
        obs_seq = params.features[state.current_step]
        context = jnp.concatenate([
            jnp.array([state.drawdown, state.high_water_mark, state.drawdown_duration]),
            state.previous_weights
        ])
        context_tiled = jnp.tile(context, (obs_seq.shape[0], 1))
        return jnp.concatenate([obs_seq, context_tiled], axis=-1)

    def step(self, key, state, action_weights, params, uncertainty=0.0):
        # 1. 获取当期市场风险指标
        current_vol = jnp.mean(params.volatility[state.current_step])
        current_corr = params.corr_spike[state.current_step]
        
        # 2. 独立安全控制器介入 (Safety Controller)
        alpha_t = SafetyController.compute_alpha(state.drawdown, current_vol, uncertainty, current_corr)
        safe_weights = SafetyController.apply_intervention(action_weights, alpha_t, params.num_assets)
        
        # 3. 无交易区检查 (No-Trade Zone)
        max_diff = jnp.max(jnp.abs(safe_weights - state.previous_weights))
        actual_weights = jax.lax.select(max_diff < params.no_trade_threshold, state.previous_weights, safe_weights)
        
        # 4. 动态交易成本扣除
        delta_w = actual_weights - state.previous_weights
        transaction_cost = compute_dynamic_cost(delta_w, params.volatility[state.current_step], params.cost_multiplier)
        
        # 5. 市场结算
        future_returns = params.returns[state.current_step]
        portfolio_return = jnp.sum(actual_weights * future_returns)
        net_return = jnp.maximum(portfolio_return - transaction_cost, -0.9999)
        
        new_value = state.portfolio_value * (1.0 + net_return)
        new_hwm = jnp.maximum(state.high_water_mark, new_value)
        new_dd = (new_hwm - new_value) / new_hwm
        new_duration = jax.lax.select(new_dd > 0.0, state.drawdown_duration + 1.0, 0.0)
        
        # 6. 计算连续的、软性约束奖励
        turnover = jnp.sum(jnp.abs(delta_w))
        log_return = jnp.log(new_value / state.portfolio_value)
        dd_penalty = jax.lax.select(new_dd < 0.05, new_dd**2, new_dd**2 + 100.0 * (new_dd - 0.05)**4)
        concentration = jnp.sum(actual_weights ** 2)
        
        reward = log_return * 100.0 - (0.5 * turnover) - (5.0 * dd_penalty) - (0.1 * concentration) - (0.5 * uncertainty)
        
        # 熔断退出条件
        done = (state.current_step + 1 >= params.max_steps)
        new_state = EnvState(state.current_step + 1, new_value, actual_weights, new_dd, new_hwm, new_duration)
        return self._get_obs(new_state, params), new_state, reward, done, {"portfolio_value": new_value, "alpha": alpha_t}

# ============================================================================
# 4. 核心网络: 多尺度时间编码 + 专家门控(MoE) + 分布式 Critic
# ============================================================================
class AttentionBlock(nn.Module):
    num_heads: int
    qkv_features: int

    @nn.compact
    def __call__(self, x, deterministic=True):
        attn = nn.MultiHeadDotProductAttention(self.num_heads, self.qkv_features, out_features=x.shape[-1], dropout_rate=0.1, deterministic=deterministic)(x, x)
        x = nn.LayerNorm()(x + attn)
        ff = nn.Dense(x.shape[-1] * 2)(x)
        ff = nn.gelu(ff)
        ff = nn.Dropout(0.1, deterministic=deterministic)(ff)
        ff = nn.Dense(x.shape[-1])(ff)
        return nn.LayerNorm()(x + ff)

class QountUltimateBrain(nn.Module):
    action_dim: int
    num_quantiles: int = 32
    num_experts: int = 5

    @nn.compact
    def __call__(self, x, deterministic=True):
        seq_len = x.shape[1]
        x = nn.Dense(128)(x)
        x = x + self.param('pos_emb', nn.initializers.normal(0.02), (1, seq_len, 128))
        x = nn.Dropout(0.1, deterministic=deterministic)(x)
        
        # 多尺度时间编码 (Multi-Scale Temporal Encoder)
        fast_path = jnp.mean(AttentionBlock(4, 128)(x[:, -21:, :], deterministic), axis=1) # 短期突变
        slow_path = jnp.mean(AttentionBlock(8, 128)(AttentionBlock(8, 128)(x, deterministic), deterministic), axis=1) # 长期宏观
        fused = nn.Dropout(0.1, deterministic=deterministic)(nn.gelu(nn.Dense(256)(jnp.concatenate([fast_path, slow_path], axis=-1))))

        # 阶段 A: 市场预判监督头
        aux_pred = nn.Dense(1)(fused)
        
        # 阶段 B: MoE Actor
        regime_probs = nn.softmax(nn.Dense(self.num_experts)(fused), axis=-1)
        experts = jnp.stack([nn.Dense(self.action_dim)(nn.leaky_relu(nn.Dense(128)(fused))) for _ in range(self.num_experts)], axis=1)
        actor_logits = jnp.sum(jnp.expand_dims(regime_probs, axis=-1) * experts, axis=1)
        actor_mean = nn.softmax(actor_logits, axis=-1) # 这是 Actor 的纯粹意图
        
        # 分布式 Critic (CVaR Estimator)
        quantiles = jnp.sort(nn.Dense(self.num_quantiles)(nn.leaky_relu(nn.Dense(256)(fused))), axis=-1)

        return actor_mean, quantiles, aux_pred, regime_probs

# ============================================================================
# 5. 课程学习预训练存根 (Behavioral Cloning Teacher)
# ============================================================================
def teacher_policy(features, current_dd):
    pass

# ============================================================================
# 6. 严防未来函数的安全数据加载器 (Strict Data Loader)
# ============================================================================
def prepare_strict_rl_dataset(parquet_path, seq_len=90, trading_assets=None):
    """
    负责构建无未来函数泄漏的三维特征矩阵和奖励矩阵。
    """
    import pandas as pd
    
    if trading_assets is None:
        trading_assets = ['TQQQ', 'SOXL', 'FAS', 'CURE', 'URTY', 'DRN', 'ERX', 'TMF', 'BIL']
        
    df = pd.read_parquet(parquet_path)
    
    # 1. 构建次日真实收益矩阵 (Target Returns)
    # 警告：绝对不能用当天的收益！必须用 shift(-1) 拿到 [t 到 t+1] 的真实收益
    prices = df.pivot(columns='Ticker', values='Close')[trading_assets]
    returns_matrix = prices.pct_change().shift(-1)
    
    # 2. 构建当日真实波动率矩阵 (用于动态滑点)
    volatility_matrix = prices.pct_change().rolling(21).std() * np.sqrt(252)
    
    # 3. 提取特异性风险 (如股债相关性崩塌)
    corr_spike = df[df['Ticker'] == 'QQQ']['corr_spy_tlt_63d'].values # 以任意代理的行数对齐
    
    # 4. 构建三维特征 Tensor (T, seq_len, Features)
    # 为保证特征绝对安全，所有特征在 build_features 时已经基于历史滑动窗口计算
    feature_cols = [c for c in df.columns if c not in ['Ticker', 'Close', 'Open', 'High', 'Low', 'Volume', 'target_fwd_return_21d']]
    
    # 按照相同的交易日历构建 3D 矩阵
    dates = sorted(list(df.index.unique()))
    T = len(dates)
    
    features_3d = []
    aligned_returns = []
    aligned_vols = []
    aligned_corrs = []
    
    for t in range(seq_len, T - 1): # -1 是为了确保最后一天有 shift(-1) 的收益率
        # (seq_len, num_features)
        date_t = dates[t]
        
        # 为了防漏，直接检查这一天的收益率是否为空
        if pd.isna(returns_matrix.loc[date_t]).any():
            continue
            
        aligned_returns.append(returns_matrix.loc[date_t].values)
        aligned_vols.append(volatility_matrix.loc[date_t].values)
        aligned_corrs.append(corr_spike[t])
        
        # TODO: 将所有标的的特征拼接到一个 (seq_len, num_features) 矩阵里
        # 这里需要复杂的 groupby 构建，暂时存根
        # features_3d.append(...) 
        
    return aligned_returns, aligned_vols, aligned_corrs

print("QOUNT ULTIMATE ARCHITECTURE LOADED: Dynamic Costs, Shadow Safety Controller, Multi-Scale MoE Brain, and Strict Dataloader initialized.")
