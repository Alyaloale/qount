"""ETF 全栈 ML 打分 —— "买家秀" 机制演示 (research-only, 不碰 live / run-once)

WARNING / 诚实声明
==================
本脚本使用 **合成数据**, 不是真实 ETF。它存在的唯一目的, 是用项目自己实测的统计参数,
把 "2026 ML 最佳实践全栈" 真的训上去, 让 in-sample 漂亮分数 + OOS/PBO 崩塌的真实成色
同时可见。这不是稻草人: 面板参数全部来自 docs/current.md 的真实读数 ——

  - 横截面真信号 IC ≈ 0.05   (项目观测最强 xs_mom rank-IC = 0.052)
  - 资产相关 r̄ ≈ 0.6         (加密 majors r̄ = 0.63)  →  有效广度 ~1.6
  - 12 个标的, 209 周          (L1 top12 / validation 窗口规模)
  - 只有 1 个特征带弱信号, 其余全零  (项目实证: 资金流=反向/零, 基本面=零, 舆情=无数据)

只依赖 numpy + sklearn (本机唯一可用的两个 ML 库)。
"""
from __future__ import annotations

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.neural_network import MLPRegressor
from sklearn.feature_selection import SelectFromModel
from sklearn.inspection import permutation_importance

RNG = np.random.default_rng(20260607)

N_ASSETS = 12
N_WEEKS = 209
TRUE_IC = 0.05          # 项目观测最强横截面 rank-IC
MARKET_CORR = 0.60      # 目标资产两两相关 (majors r̄≈0.63)

# 2026 "最佳实践" 特征清单 —— 只有第 1 个携带真信号, 其余是项目已证伪/无数据的层
FEATURES = [
    "f_momentum",        # 价量动量 —— 唯一弱真信号 (IC≈0.05)
    "f_volatility",      # 价量波动 —— 零
    "f_reversal_1w",     # 短期反转 —— 零
    "f_fund_flow",       # 资金流异动 —— 项目实证: 反向/零
    "f_sentiment_llm",   # LLM 舆情情绪得分 —— 无真实数据, 纯噪声
    "f_xmkt_emb1",       # Transformer 跨市场相关性 embedding —— 噪声
    "f_xmkt_emb2",       # 同上
    "f_xmkt_emb3",       # 同上
    "f_size",            # 规模 —— 零
    "f_fundamental",     # 基本面 —— 项目实证: 零
]
N_FEAT = len(FEATURES)


def spearman_ic(a: np.ndarray, b: np.ndarray) -> float:
    """横截面 rank-IC = 排名后的 Pearson 相关 (numpy 实现, 不依赖 scipy)。"""
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    ra -= ra.mean(); rb -= rb.mean()
    denom = np.sqrt((ra * ra).sum() * (rb * rb).sum())
    return float((ra * rb).sum() / denom) if denom > 0 else 0.0


def make_panel() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """返回 (X[T,N,F] 特征, Y[T,N] 下周横截面收益, asset_returns[T,N] 含市场因子)。"""
    T, N, F = N_WEEKS, N_ASSETS, N_FEAT
    X = RNG.standard_normal((T, N, F))            # 所有特征 ~ N(0,1), 互相独立
    # 真信号: 只有 f_momentum 与下周横截面残差弱相关, 强度校准到 rank-IC≈0.05
    c = TRUE_IC
    resid = c * X[:, :, 0] + np.sqrt(max(1e-9, 1 - c * c)) * RNG.standard_normal((T, N))
    # 市场因子: 制造资产间高相关 -> 有效广度坍缩到 ~1.6 (横截面排名不受其影响)
    sm2 = 1.0
    si2 = sm2 * (1 - MARKET_CORR) / MARKET_CORR
    market = RNG.standard_normal((T, 1)) * np.sqrt(sm2)
    idio = RNG.standard_normal((T, N)) * np.sqrt(si2)
    asset_returns = market + idio + 0.10 * resid   # 真实可观测收益序列
    Y = resid                                      # 预测目标 = 下周横截面残差收益
    return X, Y, asset_returns


def effective_breadth(asset_returns: np.ndarray) -> tuple[float, float]:
    C = np.corrcoef(asset_returns.T)
    N = C.shape[0]
    iu = np.triu_indices(N, k=1)
    rbar = float(np.abs(C[iu]).mean())
    eb = N / (1 + (N - 1) * rbar)
    return rbar, eb


def flatten(X: np.ndarray, Y: np.ndarray, weeks: np.ndarray):
    xs = X[weeks].reshape(-1, N_FEAT)
    ys = Y[weeks].reshape(-1)
    return xs, ys


def oos_weekly_ic(model, X: np.ndarray, Y: np.ndarray, weeks: np.ndarray) -> np.ndarray:
    out = []
    for t in weeks:
        pred = model.predict(X[t])
        out.append(spearman_ic(pred, Y[t]))
    return np.asarray(out)


def main() -> None:
    X, Y, asset_returns = make_panel()
    rbar, eb = effective_breadth(asset_returns)

    train = np.arange(0, 150)
    test = np.arange(150, N_WEEKS)
    Xtr, Ytr = flatten(X, Y, train)

    print("=" * 72)
    print("合成面板 (按 docs/current.md 真实读数校准)")
    print("=" * 72)
    print(f"  标的数 N            = {N_ASSETS}")
    print(f"  周数 T              = {N_WEEKS}  (train {len(train)} / test {len(test)})")
    print(f"  注入真信号 rank-IC  = {TRUE_IC:.3f}  (项目实测最强 xs_mom 0.052)")
    print(f"  实测资产相关 r̄      = {rbar:.3f}  (目标 {MARKET_CORR})")
    print(f"  实测有效广度        = {eb:.2f}  (项目天花板 ~1.6, 1/r̄ 封死)")
    print(f"  携带信号的特征      = 1 / {N_FEAT}  (其余 9 个 = 资金流/舆情/跨市场/基本面 = 项目已证伪或无数据)")

    # ---- 层 1+2: GBDT 基准 + 神经网非线性层 (LightGBM/TabNet/Transformer 的本机替身) ----
    print("\n" + "=" * 72)
    print("训练全栈模型 (GBDT 基准 + 神经网非线性层)")
    print("=" * 72)
    gbdt = GradientBoostingRegressor(n_estimators=300, max_depth=3,
                                     learning_rate=0.05, subsample=0.8,
                                     random_state=0).fit(Xtr, Ytr)
    mlp = MLPRegressor(hidden_layer_sizes=(64, 32), max_iter=600,
                       alpha=1e-4, random_state=0).fit(Xtr, Ytr)

    for name, model in [("GBDT", gbdt), ("神经网(MLP)", mlp)]:
        ic_tr = oos_weekly_ic(model, X, Y, train).mean()
        ic_oos = oos_weekly_ic(model, X, Y, test)
        sign = "符号稳定" if (ic_oos > 0).mean() > 0.6 or (ic_oos < 0).mean() > 0.6 else "符号不稳(随机)"
        tstat = ic_oos.mean() / (ic_oos.std(ddof=1) / np.sqrt(len(ic_oos)) + 1e-12)
        print(f"  {name:10}  IS rank-IC = {ic_tr:+.3f}   OOS rank-IC = {ic_oos.mean():+.3f}"
              f"  (t={tstat:+.2f}, {sign})")
    print("  读法: IS 远高于 OOS = 模型在拟合噪声; OOS≈0 且符号不稳 = 排名≈随机。")

    # ---- 层 4: AutoML 自动选因子 ----
    print("\n" + "=" * 72)
    print("AutoML 自动筛因子 (SelectFromModel, 噪声数据上的过拟合放大器)")
    print("=" * 72)
    sel = SelectFromModel(gbdt, threshold="median", prefit=True)
    chosen = [FEATURES[i] for i in np.where(sel.get_support())[0]]
    noise_chosen = [f for f in chosen if f != "f_momentum"]
    print(f"  AutoML 选中: {chosen}")
    print(f"  其中纯噪声特征 {len(noise_chosen)}/{len(chosen)} 个被自信选入 -> {noise_chosen}")

    # ---- 层 5: SHAP 同族归因 (置换重要性) ----
    print("\n" + "=" * 72)
    print("可解释归因 (permutation importance, SHAP 同族)")
    print("=" * 72)
    Xte, Yte = flatten(X, Y, test)
    pi = permutation_importance(gbdt, Xte, Yte, n_repeats=20, random_state=0)
    order = np.argsort(pi.importances_mean)[::-1]
    for i in order[:5]:
        tag = "  <- 唯一真信号" if FEATURES[i] == "f_momentum" else "  <- 噪声, 归因仍给了它权重"
        print(f"  {FEATURES[i]:16} importance = {pi.importances_mean[i]:+.5f}{tag}")
    print("  读法: 给一个过拟合模型做归因, 归因本身也是噪声 —— 可审计 != 可信。")

    # ---- PBO / CSCV: 搜了 N 个 config 后, IS 赢家在 OOS 还靠前吗 ----
    print("\n" + "=" * 72)
    print("PBO (CSCV): IS 最优配置在 OOS 是否仍优于中位?")
    print("=" * 72)
    configs = [(n, d) for n in (100, 200, 400) for d in (2, 3, 4)]  # 9 个配置
    n_splits, below_median = 8, 0
    for s in range(n_splits):
        cut = RNG.integers(90, 150)
        tr_w, te_w = np.arange(0, cut), np.arange(cut, N_WEEKS)
        xtr, ytr = flatten(X, Y, tr_w)
        is_ic, oos_ic = [], []
        for (n, d) in configs:
            m = GradientBoostingRegressor(n_estimators=n, max_depth=d,
                                          learning_rate=0.05, random_state=s).fit(xtr, ytr)
            is_ic.append(oos_weekly_ic(m, X, Y, tr_w).mean())
            oos_ic.append(oos_weekly_ic(m, X, Y, te_w).mean())
        best = int(np.argmax(is_ic))
        rank = (np.asarray(oos_ic) < oos_ic[best]).mean()  # OOS 百分位
        if rank < 0.5:
            below_median += 1
    pbo = below_median / n_splits
    print(f"  配置网格 = {len(configs)}, 重采样划分 = {n_splits}")
    print(f"  PBO ≈ {pbo:.2f}   (>0.5 = IS 赢家在 OOS 多半翻车; 项目 §7 门控要求远低于此)")

    # ---- 买家秀: 它打出来的 ETF 分数 (带收据) ----
    print("\n" + "=" * 72)
    print("【打分结果】全栈模型对最后一周 12 个 ETF 的打分 (买家秀)")
    print("=" * 72)
    last = N_WEEKS - 1
    scores = gbdt.predict(X[last])
    rank = np.argsort(scores)[::-1]
    for r, i in enumerate(rank, 1):
        print(f"  #{r:2}  ETF_{i:02d}   score = {scores[i]:+.4f}")
    final_oos = oos_weekly_ic(gbdt, X, Y, test).mean()
    print("\n  收据: 上面这张排行榜看起来很果断, 但它的 OOS rank-IC ="
          f" {final_oos:+.3f}")
    print("  即 —— 这个排序与真实下周收益的相关性 ≈ 0, 排名本质是噪声。把真金白银押在它上面")
    print("  就是 docs/current.md 反复埋掉的那个坑 (广度天花板 + 多重检验过拟合)。")


if __name__ == "__main__":
    main()
