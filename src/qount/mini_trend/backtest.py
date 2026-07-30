"""MiniTrend research backtest runner.

The engine is intentionally small: daily close rebalancing, spot long/cash only, no exchange IO.
Promotion-grade runs must supply true exchange filters/fees; the defaults here are research
plumbing, not live evidence.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from qount.research_data.market_data import Bar
from qount.mini_trend.config import MiniTrendConfig
from qount.mini_trend.execution import compute_orders
from qount.mini_trend.models import Position, Scorecard, SymbolFilter
from qount.mini_trend.risk import evaluate_risk
from qount.mini_trend.scorecard import build_scorecard, max_drawdown_pct
from qount.mini_trend.signals import target_weights


@dataclass(frozen=True)
class BacktestResult:
    config: MiniTrendConfig
    scorecard: Scorecard
    summary: dict
    equity: list[dict]
    orders: list[dict]
    blocked_symbols: list[dict]


def research_filters(symbols: Sequence[str], *, min_notional: float = 10.0) -> dict[str, SymbolFilter]:
    return {s: SymbolFilter(amount_step=1e-8, min_amount=1e-8, min_notional=min_notional) for s in symbols}


def align_bars(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    universe: Sequence[str],
) -> dict[str, list[Bar]]:
    mapped = {s: {b.ts_ms: b for b in bars_by_symbol.get(s, [])} for s in universe}
    mapped = {s: rows for s, rows in mapped.items() if rows}
    if len(mapped) != len(universe):
        missing = sorted(set(universe) - set(mapped))
        raise ValueError(f"missing bars for symbols: {','.join(missing)}")
    common = sorted(set.intersection(*(set(rows) for rows in mapped.values())))
    if not common:
        raise ValueError("no common bars across universe")
    return {s: [mapped[s][ts] for ts in common] for s in universe}


def _equity(cash: float, balances: Mapping[str, float], prices: Mapping[str, float]) -> float:
    return cash + sum(qty * prices.get(symbol, 0.0) for symbol, qty in balances.items())


def _execute_orders(
    *,
    cash: float,
    balances: dict[str, float],
    orders: Sequence,
    prices: Mapping[str, float],
    taker_fee: float,
    slippage: float,
) -> tuple[float, float, float, list[dict]]:
    events: list[dict] = []
    fee_total = 0.0
    notional_total = 0.0
    for order in sorted(orders, key=lambda o: 0 if o.side == "sell" else 1):
        price = prices[order.symbol]
        if order.side == "buy":
            spend = min(order.quote_qty, cash / (1.0 + taker_fee))
            if spend <= 0:
                continue
            fill_price = price * (1.0 + slippage)
            base_qty = spend / fill_price
            fee = spend * taker_fee
            cash -= spend + fee
            balances[order.symbol] = balances.get(order.symbol, 0.0) + base_qty
            notional = spend
        else:
            base_qty = min(order.base_qty, balances.get(order.symbol, 0.0))
            if base_qty <= 0:
                continue
            fill_price = price * (1.0 - slippage)
            notional = base_qty * fill_price
            fee = notional * taker_fee
            cash += notional - fee
            balances[order.symbol] = max(0.0, balances.get(order.symbol, 0.0) - base_qty)
        fee_total += fee
        notional_total += notional
        events.append(
            {
                "symbol": order.symbol,
                "side": order.side,
                "base_qty": base_qty,
                "price": round(fill_price, 10),
                "notional_usdt": round(notional, 8),
                "fee_usdt": round(fee, 8),
                "reason": order.reason,
            }
        )
    return cash, fee_total, notional_total, events


def run_backtest(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    cfg: MiniTrendConfig | None = None,
    *,
    filters: Mapping[str, SymbolFilter] | None = None,
    taker_fee: float = 0.001,
    slippage: float = 0.0002,
) -> BacktestResult:
    cfg = cfg or MiniTrendConfig()
    aligned = align_bars(bars_by_symbol, cfg.universe)
    filter_source = "supplied" if filters is not None else "research_default"
    filters = dict(filters or research_filters(cfg.universe))
    n = len(next(iter(aligned.values())))
    warmup = max(cfg.gate_sma, cfg.trend_sma, cfg.slow_sma, cfg.vol_lookback + 1, cfg.atr_lookback)
    if n <= warmup:
        raise ValueError(f"need more than {warmup} aligned bars, got {n}")

    cash = cfg.capital_cap_usdt
    balances = {s: 0.0 for s in cfg.universe}
    equity_rows: list[dict] = []
    order_rows: list[dict] = []
    blocked_rows: list[dict] = []
    equity_values: list[float] = []
    fee_total = 0.0
    notional_total = 0.0
    coverage_values: list[float] = []

    for i in range(warmup, n):
        window = {s: list(aligned[s][: i + 1]) for s in cfg.universe}
        prices = {s: window[s][-1].close for s in cfg.universe}
        pre_equity = _equity(cash, balances, prices)
        prior_equity = equity_values[-1] if equity_values else cfg.capital_cap_usdt
        daily_pnl_pct = pre_equity / prior_equity - 1.0 if prior_equity > 0 else 0.0
        weekly_base = equity_values[-7] if len(equity_values) >= 7 else cfg.capital_cap_usdt
        weekly_pnl_pct = pre_equity / weekly_base - 1.0 if weekly_base > 0 else 0.0

        signal = target_weights(window, cfg)
        positions = {s: Position(s, balances.get(s, 0.0)) for s in cfg.universe}
        risk = evaluate_risk(
            signal,
            filters,
            prices,
            cfg,
            positions=positions,
            daily_pnl_pct=daily_pnl_pct,
            weekly_pnl_pct=weekly_pnl_pct,
        )
        coverage_values.append(risk.min_notional_coverage)
        for item in risk.blocked_symbols:
            row = asdict(item) | {"date": window[cfg.gate_symbol][-1].date}
            blocked_rows.append(row)

        plan = compute_orders(risk, balances, prices, filters, cfg, mode="backtest", armed=False)
        cash, fees, notional, fills = _execute_orders(
            cash=cash,
            balances=balances,
            orders=plan.orders,
            prices=prices,
            taker_fee=taker_fee,
            slippage=slippage,
        )
        fee_total += fees
        notional_total += notional
        date = window[cfg.gate_symbol][-1].date
        for fill in fills:
            order_rows.append(fill | {"date": date})
        end_equity = _equity(cash, balances, prices)
        equity_values.append(end_equity)
        equity_rows.append(
            {
                "date": date,
                "equity": round(end_equity, 8),
                "cash": round(cash, 8),
                "gross_target": round(sum(risk.targets.values()), 8),
                "risk_reasons": risk.reasons,
                "orders": len(fills),
            }
        )

    metrics = {
        "total_return_pct": (equity_values[-1] / cfg.capital_cap_usdt - 1.0) * 100.0,
        "max_drawdown_pct": max_drawdown_pct(equity_values),
        "fee_to_notional_pct": (fee_total / notional_total * 100.0) if notional_total > 0 else 0.0,
        "order_count": len(order_rows),
        "min_notional_coverage": min(coverage_values) if coverage_values else 1.0,
        "stop_reentry_count": 0,
        "unmanaged_position_count": 0,
        "schema_error_count": 0,
    }
    scorecard = build_scorecard(
        metrics,
        cfg=cfg,
        mode="backtest",
        window={"start": equity_rows[0]["date"], "end": equity_rows[-1]["date"]},
        blocked_symbols=blocked_rows,
    )
    summary = {
        "strategy": cfg.strategy,
        "mode": "backtest",
        "start": equity_rows[0]["date"],
        "end": equity_rows[-1]["date"],
        "bars": len(equity_rows),
        "final_equity": round(equity_values[-1], 8),
        "total_return_pct": round(metrics["total_return_pct"], 8),
        "max_drawdown_pct": round(metrics["max_drawdown_pct"], 8),
        "order_count": len(order_rows),
        "fee_usdt": round(fee_total, 8),
        "notional_usdt": round(notional_total, 8),
        "scorecard_verdict": scorecard.verdict,
        "filter_source": filter_source,
    }
    return BacktestResult(cfg, scorecard, summary, equity_rows, order_rows, blocked_rows)


def _write_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def _write_jsonl(path: Path, rows: Sequence[dict]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(tmp, path)


def write_backtest_artifact(result: BacktestResult, output_dir: str | Path) -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_json(out / "config.json", asdict(result.config))
    _write_json(out / "summary.json", result.summary)
    _write_json(out / "scorecard.json", asdict(result.scorecard))
    _write_jsonl(out / "equity.jsonl", result.equity)
    _write_jsonl(out / "orders.jsonl", result.orders)
    _write_jsonl(out / "blocked_symbols.jsonl", result.blocked_symbols)
    return out
