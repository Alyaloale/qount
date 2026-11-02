"""Descriptive return attribution for the deployed macro rule; no order access.

Reuse retained native and ETF replays. Rebuild the native control once to avoid
confusing an old risk budget or a still-open terminal valuation with this rule.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

from continue_macro_fixed_candidates import append_inputs
from qount.research.binance_etf_leverage import replay
from qount.research.binance_macro_history import adjusted_bars


NATIVE = Path("state/research_runs/macro_fixed_candidates_20261026_final/comparison.json")
PROXY = Path("state/research_runs/macro_mechanism_value_20261026_reviewed/comparison.json")


def regression(y, factors, lags):
    """OLS with Bartlett Newey-West covariance and n/(n-k) correction.

    Normal 95% intervals are descriptive, without search or selection correction.
    A cash benchmark of zero is used; the intercept is not a risk-free alpha.
    """
    names = ["intercept", *factors]
    x = np.column_stack([np.ones(len(y)), *factors.values()])
    y = np.asarray(y, dtype=float)
    n, k = x.shape
    assert n > k + max(lags) and np.isfinite(x).all() and np.isfinite(y).all()
    beta, _, rank, _ = np.linalg.lstsq(x, y, rcond=None)
    assert rank == k
    residual = y - x @ beta
    assert np.max(np.abs(x.T @ residual)) < 1e-8
    # Independent scalar identity checks the one-factor coefficient calculation.
    if k == 2:
        expected = np.cov(x[:, 1], y, ddof=0)[0, 1] / np.var(x[:, 1])
        assert math.isclose(beta[1], expected, abs_tol=1e-10)
    bread = np.linalg.inv(x.T @ x)
    score = x * residual[:, None]
    covariance_results = {}
    for lag in lags:
        meat = score.T @ score
        for j in range(1, lag + 1):
            cross = score[j:].T @ score[:-j]
            meat += (1 - j / (lag + 1)) * (cross + cross.T)
        covariance = bread @ meat @ bread * n / (n - k)
        assert np.allclose(covariance, covariance.T, atol=1e-12)
        assert np.linalg.eigvalsh(covariance).min() > -1e-12
        if lag == 0:
            # HC1 covariance, constructed directly from each observation.
            direct = sum(residual[i] ** 2 * np.outer(bread @ x[i], bread @ x[i])
                         for i in range(n)) * n / (n - k)
            assert np.allclose(covariance, direct, atol=1e-12)
        se = np.sqrt(np.maximum(np.diag(covariance), 0))
        covariance_results[str(lag)] = {
            name: dict(estimate=float(b), standard_error=float(s),
                       interval95=[float(b - 1.96 * s), float(b + 1.96 * s)])
            for name, b, s in zip(names, beta, se)
        }
    total = float(np.sum((y - y.mean()) ** 2))
    return dict(observations=n, r_squared=1 - float(residual @ residual) / total,
                mean_daily_return=float(y.mean()), hac=covariance_results,
                coefficients=dict(zip(names, map(float, beta))))


def aligned_regressions(curve, factors, native=False):
    """Match valuation timestamps before differencing; never pad missing assets."""
    own = {int(p.get("time", p.get("t"))): p.get("equity", p.get("nav")) for p in curve}
    if native:
        own = {t: v for t, v in own.items() if t % 86400 == 0}
    models = {}
    for label, names in (("SPY_full", ["SPY"]),
                         ("SPY_common", ["SPY"]),
                         ("four_factor", ["SPY", "IWM", "XLE", "OIL"])):
        required = list(factors) if label != "SPY_full" else ["SPY"]
        times = sorted(set(own).intersection(*(set(factors[s]) for s in required)))
        assert len(times) > 70
        if native:
            assert set(np.diff(times)) == {86400}
        else:
            # All long-window ETF factors have precisely the same session axis.
            assert all([t for t in factors[s] if times[0] <= t <= times[-1]] == times
                       for s in required)
        nav = np.array([own[t] for t in times])
        y = nav[1:] / nav[:-1] - 1
        xs = {}
        for s in names:
            price = np.array([factors[s][t] for t in times])
            xs[s] = price[1:] / price[:-1] - 1
        result = regression(y, xs, [0, 5, 21] if native else [0, 5, 21, 63])
        result.update(start=dt.datetime.fromtimestamp(times[0], dt.timezone.utc).isoformat(),
                      end=dt.datetime.fromtimestamp(times[-1], dt.timezone.utc).isoformat(),
                      clock="UTC midnight" if native else "New York session close",
                      cumulative_return=float(nav[-1] / nav[0] - 1))
        models[label] = result
    return models


def attribution(trades, capital, fee):
    grouped = {"asset": defaultdict(lambda: defaultdict(float)),
               "setup": defaultdict(lambda: defaultdict(float))}
    rows = []
    for t in trades:
        assert t["feature_available"] < t["entry_time"] < t["exit_time"]
        price = t["quantity"] * (t["exit_price"] - t["entry_price"])
        fees = t["entry_fee"] + t["quantity"] * t["exit_price"] * fee
        net = price + t["funding"] - fees
        assert math.isclose(net, t["net_pnl"], abs_tol=1e-9)
        row = dict(symbol=t["symbol"], setup=t["tactical_setup"],
                   entry=dt.datetime.fromtimestamp(t["entry_time"], dt.timezone.utc).isoformat(),
                   exit=dt.datetime.fromtimestamp(t["exit_time"], dt.timezone.utc).isoformat(),
                   exit_reason=t["exit_reason"], quantity=t["quantity"],
                   price_pnl=price, funding=t["funding"], fees=fees, net_pnl=net,
                   notional_return=net / t["notional_usdt"])
        rows.append(row)
        for dimension, key in (("asset", t["symbol"]), ("setup", t["tactical_setup"])):
            for field in ("price_pnl", "funding", "fees", "net_pnl"):
                grouped[dimension][key][field] += row[field]
            grouped[dimension][key]["count"] += 1
    profits = sorted((r["net_pnl"] for r in rows if r["net_pnl"] > 0), reverse=True)
    net = sum(r["net_pnl"] for r in rows)
    return dict(trades=rows, grouped=grouped, net_pnl=net,
                initial_capital=capital, top_two_share_of_net=sum(profits[:2]) / net,
                fixed_ledger_pnl_without_top_two=net - sum(profits[:2]),
                note="Fixed-ledger concentration is not an omission replay or a tradable filter.")


def write_report(output, data, live):
    summary = data["native_summary"]
    attrib = data["attribution"]
    account = live["performance"]["summary"]
    lines = ["# 现行实盘宏观策略：回归与收益归因（2026-11-02）", "",
        "结论：当前实盘没有本策略归属成交，不能估计实盘alpha；已消费的原生历史盈利集中在两笔交易，成本及本金敏感，新增因子回归未确认稳定正截距。暂不支持据此扩大本金或杠杆。", "",
        "## 当前实盘事实", "",
        f"只读核对时间：{live['checked_at']}；账户观测：{live['assets']['observed_at']}。",
        f"策略`{live['strategy']['strategy_id']}`，25%压力预算，AUTO/空仓；USDT权益{live['assets']['futures_equity_usdt']:.8f}。",
        f"现策略归属成交{live['strategy']['accounting']['assigned_fill_count']}；账户有效段{account['start']}—{account['end']}，{account['observation_count']}点，收益/净损益/观测MDD均0。",
        "账户段包含手动及旧策略范围，不是本策略收益；收益没有变动，R²未定义，机械拟合零beta不能证明有效避险或零alpha。旧136个缺项不跨段拼接，BNB残额未估值。",
        f"最近正式决策{live['strategy']['last_decision']['created_at']}为HOLD_NO_SIGNAL、候选0；下一允许入场{live['strategy']['next_entry_at']}。",
        "本轮没有触发交易周期、通知、服务变更或参数发布。", "",
        "## 原生合约历史：按现行预算复现", "",
        "2026-04-07至2026-10-26（右端不含），资产池为SPY/QQQ/SMH/IWM/XLE/XAU/COPPER/CL对应的USDT合约；初始15.27112826 USDT，现金基准0%。单边手续费5bp/滑点25bp，历史逐时点资金费，原容量/离散数量/档位、7/21天期限、止损及续期规则。当前档位历史套用，小时成交近似；不是独立OOS或实盘收益。",
        f"本轮重新执行当前控制，完整曲线及7笔交易与保留结果逐值一致。期末权益{summary['final_equity']:.8f}、累计净收益{summary['net_return']:.2%}、小时MDD{summary['max_drawdown']:.2%}；7笔全部闭合，无截尾损益。",
        "10月15日前的旧报告32.78%包含当时期末估值；本次32.56%已包含10月21日末笔XLE实际模拟退出，两者不是同一截止日。", "",
        "|收益来源|笔数|净损益 USDT|", "|---|---:|---:|"]
    for name, r in attrib["grouped"]["asset"].items():
        lines.append(f"|{name}|{int(r['count'])}|{r['net_pnl']:+.6f}|")
    lines += ["", f"两笔最大盈利为7月24日IWM及9月30日XLE，贡献净利润{attrib['top_two_share_of_net']:.2%}。其余五笔在固定原账本下合计仅{attrib['fixed_ledger_pnl_without_top_two']:+.6f} USDT；这不是剔除机会后重跑的收益。",
        f"MR入口3笔贡献{attrib['grouped']['setup']['mean_reversion']['net_pnl']/attrib['net_pnl']:.2%}净利润；样本过少，不据此删除其他入口。资金费合计{summary['funding']:+.6f}、手续费{summary['fees']:.6f}；滑点已嵌入成交价，不重复扣减。", "",
        "|初始本金 USDT|基础净收益|基础小时MDD|双成本净收益|", "|---:|---:|---:|---:|"]
    capital_values = sorted({r["capital"] for r in data["cost_and_capital_sensitivity"]})
    for capital in capital_values:
        rows = {r["scenario"]: r["headline"] for r in data["cost_and_capital_sensitivity"] if r["capital"] == capital}
        lines.append(f"|{capital:.4f}|{rows['base']['net_return']:.2%}|{rows['base']['max_drawdown']:.2%}|{rows['double_cost']['net_return']:.2%}|")
    lines += ["", "双成本是单边10bp手续费/50bp滑点及不利Regular资金费加倍，改变准入路径，仅形成1笔交易；不能当作固定7笔交易简单扣费。15.2711本金下，基础成本外所有退出另加50bp/200bp不利冲击，收益为26.15%/7.41%、小时MDD14.14%/20.07%。",
        "相同策略在30/100本金下收益不能按比例放大，原容量、离散数量和风险门改变实际敞口。最大观测名义敞口约3.25倍；20倍名义上限、50倍设置杠杆均不是实际仓位。25%压力预算不是账户最大损失承诺。", "",
        "## 新增回归：同期暴露解释能力", "",
        "模型为每日账户简单净收益=截距+同期因子收益×系数+残差。原生因子用SPY/IWM/XLE/CL标记价格；UTC午夜同端点，小时Bar开盘时间加1小时才对应收盘估值。不补齐上市前数据。因子是毛价格收益、现金基准0%，没有扣无风险利率；截距不称严格Jensen alpha。",
        "OLS用NumPy计算，Bartlett Newey–West协方差以n/(n-k)修正；下表95%区间用21期HAC、正态近似。另保留5期及长窗63期敏感性。方法参考[statsmodels HAC文档](https://www.statsmodels.org/stable/generated/statsmodels.stats.sandwich_covariance.cov_hac.html)。", "",
        "|原生历史模型|日收益观测数|R²|每日截距 bp|截距95%区间 bp|", "|---|---:|---:|---:|---|"]
    for name, label in (("SPY_full", "SPY，4月8日起"), ("SPY_common", "SPY，6月12日起"), ("four_factor", "四因子，6月12日起")):
        m = data["native_models"][name]
        a = m["hac"]["21"]["intercept"]
        lo, hi = a["interval95"]
        lines.append(f"|{label}|{m['observations']}|{m['r_squared']:.2%}|{a['estimate']*10000:+.2f}|[{lo*10000:+.2f}, {hi*10000:+.2f}]|")
    lines += ["", "四因子相对同窗SPY的R²由6.78%升至17.81%，但截距区间跨零；不能把剩余82.19%未解释波动称作alpha。XLE系数0.495在5期HAC下区间略高于零，21期则跨零，显著性不稳。201/136个日收益仍只有7次交易机会，HAC不能消除少事件、历史选参或时变暴露偏差。", "",
        "## 长窗机制对照：2017–2025 ETF代理", "",
        "初始10,000美元等值、不杠杆、现金0%、下一交易日09:30开盘、单边5bp/25bp，日线止损及原7/21天持有。原生10:00、跳空/准入、资金费、容量和清算约束没有迁入，故不是实盘策略九年回测。四因子为调整价格SPY/IWM/XLE/USO；每组2261个共同收盘至收盘收益。", "",
        "|机制|净CAGR|日MDD|四因子截距×252|95%区间|", "|---|---:|---:|---:|---|"]
    for row in data["proxy_regressions"]:
        a = row["models"]["four_factor"]["hac"]["21"]["intercept"]
        lo, hi = a["interval95"]
        lines.append(f"|{row['profile']}|{row['summary']['cagr_pct']:.2f}%|{row['summary']['max_drawdown_pct']:.2f}%|{a['estimate']*252:.2%}|[{lo*252:.2%}, {hi*252:.2%}]|")
    lines += ["", "截距×252是年化算术回归截距，不是CAGR或可实现超额组合收益。三组均未显示稳健正截距；完整混合/趋势机制的原始长期净表现也弱。5/21/63期HAC及单/四因子口径均没有给出显著正截距，不能用短窗32.56%覆盖长窗失败。",
        "此前93个非重叠MR方向事件的15日净均值1.45%，去同期预估SPY beta后−0.17%、季度簇95%区间[−0.84%,0.51%]。这与MR的市场修复暴露解释相容，尚未证明独立选资产alpha；本轮未重新运行该事件研究。", "",
        "## 判断与最有价值的后续问题", "",
        "保留现状作为小额执行实验有其信息价值，但现有证据不支持扩大资金或杠杆。优先检验权益MR的退出：固定相同入场、仓位与风险保护，比较结构失效退出和短期修复持有，并以相同资金占用的SPY/现金作对照。此前直接放宽原生MR持仓已使收益32.56%降至24.77%，不能把ETF固定15日优势直接迁入生产。",
        "全部历史已消费、当前资产池事后确定、回归模型只解释同期线性关系。完整系数、区间、交易归因及12组成本/本金对照在[analysis.json](analysis.json)，实时事实在[live_snapshot.json](live_snapshot.json)。",
        "资金、时间与逐笔损益恒等式、完整控制复现、OLS正规方程/单因子标量身份、HAC零阶与HC1一致性及协方差半正定均通过。没有运行全仓库测试，未更改生产逻辑。", "",
        "复现：`PYTHONPATH=src ./.venv/bin/python scripts/research/analyze_live_macro_regression.py --output <含live_snapshot.json的新目录>`。复用缓存，不下载、不下单。", ""]
    (output / "report.md").write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    target = args.output / "analysis.json"
    if target.exists():
        parser.error("retain previous analysis; choose a new output directory")
    live = json.loads((args.output / "live_snapshot.json").read_text())
    assert live["strategy"]["strategy_id"] == "rolling7_risk_no_chase_mr_signal_gap_1atr"
    assert live["strategy"]["risk_fraction"] == .25
    assert live["strategy"]["accounting"]["assigned_fill_count"] == 0
    native = json.loads(NATIVE.read_text())
    proxy = json.loads(PROXY.read_text())
    (book, signals, gates, caps), _, _ = append_inputs(native["sample_end_exclusive"], False)
    current = replay(book, signals, entry_confirmations=gates,
                     entry_liquidity_caps=caps, **native["parameters"])
    retained = next(r for r in native["portfolios"] if r["profile"] == "control"
                    and r["scenario"] == "base" and r["capital"] == native["parameters"]["capital"])
    assert current["curve"] == retained["curve"]
    assert current["trades"] == retained["trades"]
    capital = native["parameters"]["capital"]
    attrib = attribution(current["trades"], capital, native["parameters"]["fee"])
    assert math.isclose(capital + attrib["net_pnl"], current["summary"]["final_equity"], abs_tol=1e-9)
    mapping = dict(SPY="SPYUSDT", IWM="IWMUSDT", XLE="XLEUSDT", OIL="CLUSDT")
    # Hourly Bar.t is the bar OPEN; the close valuation is available an hour later.
    native_factors = {name: {b.t + 3600: b.c for b in book[s]["mark"]}
                      for name, s in mapping.items()}
    native_models = aligned_regressions(current["curve"], native_factors, native=True)
    proxy_mapping = dict(SPY="SPY", IWM="IWM", XLE="XLE", OIL="USO")
    proxy_factors = {}
    for name, ticker in proxy_mapping.items():
        path = next(Path(s["path"]) for s in proxy["sources"]
                    if Path(s["path"]).name.startswith("yahoo-" + ticker + "-"))
        proxy_factors[name] = {b.t: b.c for b in adjusted_bars(json.loads(path.read_text()))}
    long_results = []
    for row in proxy["portfolios"]:
        if row["profile"] not in {"original_all", "original_mr", "original_trend"} or row["vol_target"] is not None:
            continue
        long_results.append(dict(profile=row["profile"], summary=row["summary"],
                                 models=aligned_regressions(row["curve"], proxy_factors)))
    sensitivity = [dict(capital=r["capital"], scenario=r["scenario"], headline=r["headline"])
                   for r in native["portfolios"] if r["profile"] == "control"]
    out = dict(research_only=True, orders_authorized=False, independent_oos=False,
        live_snapshot=str(args.output / "live_snapshot.json"),
        live_regression=dict(status="NOT_ESTIMABLE", reason="no_assigned_strategy_fills_and_zero_variance_account_segment"),
        hypothesis="Does retained performance show stable returns beyond contemporaneous market exposure?",
        sources=dict(native=str(NATIVE), proxy=str(PROXY)),
        native_exact_curve_and_trade_reproduction=True, native_parameters=native["parameters"],
        native_summary=current["summary"], attribution=attrib, native_models=native_models,
        cost_and_capital_sensitivity=sensitivity, proxy_regressions=long_results,
        methodology="Simple daily net account returns regressed on contemporaneous gross price factors; "
                     "cash benchmark zero, OLS intercept in return per observation, Bartlett HAC; "
                     "normal 95% intervals with n/(n-k) correction. No prediction model fitting or tuning.",
        limitations=[
            "Current live strategy has no assigned fills; zero-variance account observations cannot establish strategy alpha or R-squared.",
            "Native history ends 2026-10-26 exclusive, not the live check date; all history has already been consumed.",
            "Seven native trades are not 201 independent opportunities. HAC does not correct selection bias or guarantee valid small-event inference.",
            "ETF proxy study is unlevered and omits native gap/admission/funding/capacity rules; its coefficients are mechanism diagnostics, not live estimates.",
            "A constant-beta regression does not capture changing exposures, nonlinear timing, or all risk premia; intercept is not causal alpha.",
            "Factors are gross adjusted prices or native mark prices, not net executable buy-and-hold portfolios; risk-free return is not subtracted.",
            "Native four-factor and full SPY models differ in start date; SPY_common provides an identical-sample comparison.",
            "Current instrument universe and venue tiers applied to past observations are not point-in-time historical certification.",
            "Zero cash returns, hourly fill/stop proxies, no verified order-book or liquidation execution; 25% stress budget is not maximum account loss.",
        ])
    args.output.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    write_report(args.output, out, live)
    for label, model in native_models.items():
        print("native", label, json.dumps(model, ensure_ascii=False))
    for r in long_results:
        print("proxy", r["profile"], json.dumps(r["models"], ensure_ascii=False))
    print("saved", target)


if __name__ == "__main__":
    main()
