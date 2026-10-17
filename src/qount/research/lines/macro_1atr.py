"""Selected macro rules on retained native caches; no account access or tuning."""
from __future__ import annotations

from pathlib import Path

from qount.research.binance_etf_leverage import replay
from qount.research.binance_macro_attack import macro_features, directional_book
from qount.research.binance_macro_liquidity import load_capacity_contexts
from qount.research.binance_macro_opportunities import cost_case
from qount.research.engine.evaluation import nav_metrics
from qount.research_data.binance_history import load_cached_history
from qount.research_data.archives import timestamp
from qount.strategies.macro_episodes import episode_confirmations
from qount.strategies.macro_gates import mean_reversion_gap_confirmations


def inputs(cache, roots, liquidity, start, end):
    features, sources = macro_features(cache, end)
    data, native_sources, excluded = load_cached_history(roots, tuple(features),
        timestamp(start), timestamp(end), cache/"exchange-info.json")
    if excluded:
        raise ValueError(f"selected_macro_inputs_missing:{','.join(excluded)}")
    book, signals = directional_book(data, features, "long", 20/3)
    anchors = episode_confirmations(book, signals, "no_chase")
    gaps = mean_reversion_gap_confirmations(book, signals, anchors)
    gates = {key:{**c, "eligible":c["eligible"] and gaps[key]["eligible"],
                  "reason":gaps[key]["reason"] if c["eligible"] else c["reason"]}
             for key,c in anchors.items()}
    caps, minutes, _ = load_capacity_contexts(anchors, liquidity)
    return book, signals, gates, caps, sources+native_sources+minutes


def run(book, signals, gates, caps, *, capital, fee, slip, controls, scenario):
    original = replay(cost_case(book, scenario), signals, capital=capital, fee=fee, slip=slip,
                      entry_liquidity_caps=caps, entry_confirmations=gates, **controls)
    nav = [dict(t=p["time"], nav=p["equity"]/capital, equity=p["equity"]) for p in original["curve"]]
    summary = original["summary"]
    trades = original["trades"]
    return dict(nav=nav, trades=trades, summary=dict(
        **nav_metrics(nav), initial_capital=capital, trade_count=len(trades),
        final_equity=summary["final_equity"], symbols=list(book),
        sample_kind="consumed_historical_exploration", scenario=scenario,
        hypothesis="所选宏观规则在原生合约、资金费、离散仓位及成本约束下的净表现与成本敏感性。",
        conclusion="当前宏观规则的已消费历史回放；不是实盘收益或独立样本外验证。",
        baselines={"cash":{"total_return_pct":0.0, "max_drawdown_pct":0.0}},
        closed_trades=sum(t["exit_reason"] != "end_of_sample" for t in trades),
        censored_trades=sum(t["exit_reason"] == "end_of_sample" for t in trades),
        fees_usdt=summary["fees"], funding_usdt=summary["funding"],
        retained_replay_summary=summary,
        limitations=["原选定规则，不重新选参；只复用保留的公开输入",
                     "小时撮合及容量/清算近似，小时收盘回撤不能约束盘中最大损失",
                     "ETF代理信号与原生合约分开，当前交易规则历史套用仍是近似",
                     "样本末尾持仓估值截尾，非真实退出；现金基准0%，未建同风险买持对照",
                     "不同成本情景会改变成交路径，不能按固定成交简单扣费"] ))
