from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from dataclasses import dataclass
from typing import Any

from qount.artifacts import write_research_json_artifact
from qount.research_data.market_data import Bar
from qount.research_data.market_data import load_funding
from qount.research_data.market_data import load_klines
from qount.settings import Settings

from .exchange_rules import evaluate_period_filter_coverage
from .exchange_rules import rules_from_exchange_info
from .exchange_rules import SymbolRules


BINANCE_RETURNS_VERSION = "alpha_agent_binance_returns_v0.1"


@dataclass(frozen=True)
class BinanceReturnsConfig:
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "BNBUSDT")
    strategy_symbol: str = "ETHUSDT"
    interval: str = "1d"
    start_month: str = "2024-01"
    end_month: str = "2024-03"
    market: str = "um"
    strategy: str = "sma_long_cash"
    fast_window: int = 20
    slow_window: int = 60
    fee_pct: float = 0.0005
    slippage_pct: float = 0.0002
    account_equity_usdt: float = 400.0
    target_notional_fraction: float = 1.0
    leverage: float = 1.0
    include_funding: bool = False
    cache_dir: str = "state/alpha_agents/binance_klines"
    funding_cache_dir: str = "state/alpha_agents/binance_funding"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_month(raw: str) -> tuple[int, int]:
    year, month = raw.split("-", 1)
    return int(year), int(month)


def _sma(values: list[float], end_exclusive: int, window: int) -> float | None:
    if window <= 0 or end_exclusive < window:
        return None
    segment = values[end_exclusive - window : end_exclusive]
    return sum(segment) / len(segment)


def _position(closes: list[float], index: int, config: BinanceReturnsConfig) -> float:
    """Position for return into ``index`` using information through ``index-1``."""

    if index <= 0:
        return 0.0
    fast = _sma(closes, index, config.fast_window)
    slow = _sma(closes, index, config.slow_window)
    if fast is None or slow is None:
        return 0.0
    if config.strategy == "sma_long_cash":
        return 1.0 if fast > slow else 0.0
    if config.strategy == "sma_long_short":
        return 1.0 if fast > slow else -1.0
    raise ValueError(f"unknown strategy: {config.strategy}")


def _pct_return(prev_close: float, close: float) -> float:
    if prev_close <= 0:
        return 0.0
    return (close / prev_close - 1.0) * 100.0


def _align_bars(bars_by_symbol: dict[str, list[Bar]], symbols: tuple[str, ...]) -> list[tuple[int, dict[str, Bar]]]:
    maps = {symbol: {bar.ts_ms: bar for bar in bars_by_symbol[symbol]} for symbol in symbols}
    common = set(maps[symbols[0]])
    for symbol in symbols[1:]:
        common &= set(maps[symbol])
    return [(ts, {symbol: maps[symbol][ts] for symbol in symbols}) for ts in sorted(common)]


def build_binance_returns_dataset(
    config: BinanceReturnsConfig,
    *,
    fetch=None,
    exchange_info: dict[str, Any] | None = None,
    symbol_rules: dict[str, SymbolRules] | None = None,
) -> dict[str, Any]:
    if "BTCUSDT" not in config.symbols:
        raise ValueError("symbols must include BTCUSDT for beta attribution")
    if config.strategy_symbol not in config.symbols:
        raise ValueError("strategy_symbol must be included in symbols")
    if len(config.symbols) < 2:
        raise ValueError("at least two symbols are required")

    start = _parse_month(config.start_month)
    end = _parse_month(config.end_month)
    bars_by_symbol = {
        symbol: load_klines(
            symbol,
            config.interval,
            start=start,
            end=end,
            market=config.market,
            cache_dir=config.cache_dir,
            fetch=fetch,
            skip_missing=True,
        )
        for symbol in config.symbols
    }
    funding = []
    if config.include_funding:
        if config.market != "um":
            raise ValueError("funding is only available for Binance USD-M futures market")
        funding = load_funding(
            config.strategy_symbol,
            start=start,
            end=end,
            cache_dir=config.funding_cache_dir,
            fetch=fetch,
            skip_missing=True,
        )
    aligned = _align_bars(bars_by_symbol, config.symbols)
    if len(aligned) < max(config.fast_window, config.slow_window) + 2:
        raise ValueError("not enough aligned bars for strategy windows")

    strategy_closes = [row[1][config.strategy_symbol].close for row in aligned]
    previous_position = 0.0
    periods: list[dict[str, Any]] = []
    total_turnover = 0.0
    per_turnover_cost_pct = (config.fee_pct + config.slippage_pct) * 100.0
    funding_index = 0
    funding_count = 0
    total_funding_return_pct = 0.0

    for index in range(1, len(aligned)):
        ts, row = aligned[index]
        prev_ts = aligned[index - 1][0]
        prev_row = aligned[index - 1][1]
        symbol_returns = {
            symbol: _pct_return(prev_row[symbol].close, row[symbol].close)
            for symbol in config.symbols
        }
        position = _position(strategy_closes, index, config)
        turnover = abs(position - previous_position)
        cost_pct = turnover * per_turnover_cost_pct
        funding_return_pct = 0.0
        if config.include_funding:
            while funding_index < len(funding) and funding[funding_index].ts_ms <= prev_ts:
                funding_index += 1
            scan_index = funding_index
            while scan_index < len(funding) and funding[scan_index].ts_ms <= ts:
                funding_return_pct += -position * funding[scan_index].rate * 100.0
                funding_count += 1
                scan_index += 1
            funding_index = scan_index
        strategy_gross = position * symbol_returns[config.strategy_symbol]
        strategy_net = strategy_gross - cost_pct + funding_return_pct
        previous_position = position
        total_turnover += turnover
        total_funding_return_pct += funding_return_pct
        periods.append(
            {
                "ts": str(ts),
                "strategy_return_pct": strategy_net,
                "strategy_gross_return_pct": strategy_gross,
                "strategy_position": position,
                "strategy_turnover": turnover,
                "strategy_cost_pct": cost_pct,
                "strategy_funding_return_pct": funding_return_pct,
                "strategy_close": row[config.strategy_symbol].close,
                "btc_return_pct": symbol_returns["BTCUSDT"],
                "top3_equal_weight_return_pct": sum(symbol_returns.values()) / len(symbol_returns),
                "current_live_baseline_return_pct": 0.0,
                "cash_return_pct": 0.0,
            }
        )

    basis = {
        "config": config.to_dict(),
        "first_ts": periods[0]["ts"],
        "last_ts": periods[-1]["ts"],
        "period_count": len(periods),
    }
    data_hash = hashlib.sha256(json.dumps(basis, sort_keys=True).encode("utf-8")).hexdigest()
    filter_diagnostics: dict[str, Any] | None = None
    exchange_rules_source = "binance_public_dump"
    filter_validator_reused = False
    min_notional_coverage = 0.0
    rules = symbol_rules
    if rules is None and exchange_info is not None:
        rules = rules_from_exchange_info(exchange_info, market=config.market)
    if rules is not None:
        filter_diagnostics = evaluate_period_filter_coverage(
            periods,
            rules,
            symbol=config.strategy_symbol,
            account_equity_usdt=config.account_equity_usdt,
            target_notional_fraction=config.target_notional_fraction,
            leverage=config.leverage,
        )
        exchange_rules_source = "runtime_exchange_info"
        filter_validator_reused = True
        min_notional_coverage = float(filter_diagnostics["min_notional_coverage"])
    return {
        "schema_version": BINANCE_RETURNS_VERSION,
        "meta": {
            "point_in_time": True,
            "as_of_join": True,
            "replayable": True,
            "trial_count": 1,
            "exchange_rules_source": exchange_rules_source,
            "filter_validator_reused": filter_validator_reused,
            "costs_included": True,
            "funding_included": config.include_funding,
            "min_notional_coverage": min_notional_coverage,
            "worst_case_cost_buffer_pct": 0.0,
            "effective_breadth": 1.0,
            "label_spec": "SMA strategy period return net of simple turnover cost",
            "benchmark_spec": "cash/BTC/TOP equal-weight/current live baseline",
            "data_spec": "Binance public dump aligned klines",
            "cost_spec": "fee_pct + slippage_pct per unit turnover; funding and filters not verified",
            "kill_line": "block if beta residual or scorecard gate fails",
            "data_hash": data_hash,
        },
        "config": config.to_dict(),
        "diagnostics": {
            "first_ts": periods[0]["ts"],
            "last_ts": periods[-1]["ts"],
            "period_count": len(periods),
            "symbols": list(config.symbols),
            "total_turnover": total_turnover,
            "per_turnover_cost_pct": per_turnover_cost_pct,
            "funding_settlement_count": funding_count,
            "total_funding_return_pct": total_funding_return_pct,
            "filter_diagnostics": filter_diagnostics,
            "note": "Research dataset only; no private Binance API, paper/live state, or order placement.",
        },
        "periods": periods,
    }


def write_binance_returns_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="alpha-agent-binance-returns",
        path_key="artifact_path",
        default_filename="alpha_agent_binance_returns.json",
        explicit_path=explicit_path,
    )
