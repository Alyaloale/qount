from __future__ import annotations

from math import copysign
from statistics import mean
from typing import Any

from .exchange_utils import ExchangePool
from .exchange_utils import build_exchange
from .exchange_utils import extract_quote_balance
from .exchange_utils import fetch_futures_position_snapshots
from .exchange_utils import market_amount_step
from .exchange_utils import resolve_market_symbols
from .journal import Journal
from .models import AccountSnapshot, Candle, MarketSnapshotBundle, PositionSnapshot, SymbolSnapshot, utc_now
from .settings import Settings
from .trade_policy import timeframe_to_ms


MIN_COMPLETED_CANDLES = 48


def _sma(values: list[float], period: int) -> float:
    return mean(values[-period:])


def _rsi(closes: list[float], period: int = 14) -> float:
    gains: list[float] = []
    losses: list[float] = []
    for prev, current in zip(closes[-period - 1 : -1], closes[-period:]):
        delta = current - prev
        gains.append(max(delta, 0.0))
        losses.append(abs(min(delta, 0.0)))
    avg_gain = mean(gains) if any(gains) else 0.0
    avg_loss = mean(losses) if any(losses) else 0.0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _atr(candles: list[Candle], period: int = 14) -> float:
    ranges: list[float] = []
    previous_close = candles[-period - 1].close
    for candle in candles[-period:]:
        ranges.append(max(candle.high - candle.low, abs(candle.high - previous_close), abs(candle.low - previous_close)))
        previous_close = candle.close
    return mean(ranges)


def _latest_completed_candles(candles: list[Candle], timeframe_ms: int, now_ms: int) -> list[Candle]:
    if not candles:
        raise ValueError("empty_ohlcv")
    usable = candles
    if now_ms < candles[-1].timestamp_ms + timeframe_ms:
        usable = candles[:-1]
    if len(usable) < MIN_COMPLETED_CANDLES:
        raise ValueError(f"not_enough_completed_candles:{len(usable)}")
    return usable


def _trend_bias(returns_12bars: float, sma_fast_ratio: float, sma_slow_ratio: float, rsi_14: float) -> str:
    score = 0.0
    score += copysign(1.0, returns_12bars) if returns_12bars != 0 else 0.0
    score += copysign(1.0, sma_fast_ratio) if sma_fast_ratio != 0 else 0.0
    score += copysign(1.0, sma_slow_ratio) if sma_slow_ratio != 0 else 0.0
    if rsi_14 >= 55.0:
        score += 1.0
    elif rsi_14 <= 45.0:
        score -= 1.0
    if score >= 2.0:
        return "long"
    if score <= -2.0:
        return "short"
    return "flat"


def build_symbol_snapshot(
    *,
    symbol: str,
    timeframe: str,
    completed_candles: list[Candle],
    exchange_min_cost_quote: float | None,
    exchange_min_amount: float | None,
    exchange_amount_step: float | None,
    higher_timeframe: dict[str, Any] | None = None,
) -> SymbolSnapshot:
    closes = [candle.close for candle in completed_candles]
    volumes = [candle.volume for candle in completed_candles]
    last_price = closes[-1]
    indicators = {
        "return_1bar": (closes[-1] / closes[-2]) - 1.0,
        "return_24bars": (closes[-1] / closes[-25]) - 1.0,
        "sma_fast_ratio": (closes[-1] / _sma(closes, 12)) - 1.0,
        "sma_slow_ratio": (closes[-1] / _sma(closes, 48)) - 1.0,
        "rsi_14": _rsi(closes, 14),
        "atr_14_pct": _atr(completed_candles, 14) / closes[-1],
        "volume_ratio_20": volumes[-1] / mean(volumes[-20:-1]),
        "range_pct": (completed_candles[-1].high - completed_candles[-1].low) / closes[-1],
    }
    return SymbolSnapshot(
        symbol=symbol,
        timeframe=timeframe,
        last_price=last_price,
        indicators=indicators,
        recent_candles=completed_candles[-24:],
        exchange_min_cost_quote=exchange_min_cost_quote,
        exchange_min_amount=exchange_min_amount,
        exchange_amount_step=exchange_amount_step,
        higher_timeframe=higher_timeframe,
    )


def build_higher_timeframe_context_from_completed_candles(
    *,
    timeframe: str,
    completed_candles: list[Candle],
) -> dict[str, Any]:
    closes = [candle.close for candle in completed_candles]
    returns_12bars = (closes[-1] / closes[-13]) - 1.0
    sma_fast_ratio = (closes[-1] / _sma(closes, 12)) - 1.0
    sma_slow_ratio = (closes[-1] / _sma(closes, 24)) - 1.0
    rsi_14 = _rsi(closes, 14)
    return {
        "timeframe": timeframe,
        "return_12bars": returns_12bars,
        "sma_fast_ratio": sma_fast_ratio,
        "sma_slow_ratio": sma_slow_ratio,
        "rsi_14": rsi_14,
        "trend_bias": _trend_bias(returns_12bars, sma_fast_ratio, sma_slow_ratio, rsi_14),
    }


def build_paper_account_snapshot(
    *,
    settings: Settings,
    journal: Journal,
    latest_prices: dict[str, float],
) -> AccountSnapshot:
    portfolio = journal.get_runtime_state(
        "paper_portfolio",
        {
            "free_quote": settings.paper_starting_quote,
            "positions": {},
        },
    )
    open_positions: list[PositionSnapshot] = []
    free_quote = float(portfolio["free_quote"])

    if not settings.contract_market:
        equity_quote = free_quote
        for symbol, position in portfolio["positions"].items():
            quantity = float(position["quantity"])
            mark_price = latest_prices[symbol]
            market_value_quote = quantity * mark_price
            equity_quote += market_value_quote
            open_positions.append(
                PositionSnapshot(
                    symbol=symbol,
                    quantity=quantity,
                    mark_price=mark_price,
                    market_value_quote=market_value_quote,
                    side="long",
                    average_entry_price=float(position["average_entry_price"]),
                    notional_quote=market_value_quote,
                )
            )
        return AccountSnapshot(
            quote_currency=settings.quote_currency,
            equity_quote=equity_quote,
            free_quote=free_quote,
            open_positions=open_positions,
            mode=settings.mode,
            market_type=settings.market_type,
        )

    equity_quote = free_quote
    leverage = float(settings.contract_leverage)
    for symbol, position in portfolio["positions"].items():
        quantity = float(position["quantity"])
        mark_price = latest_prices[symbol]
        average_entry_price = float(position["average_entry_price"])
        side = str(position.get("side") or "long")
        margin_quote = float(position.get("margin_quote") or 0.0)
        notional_quote = quantity * mark_price
        unrealized_pnl_quote = (
            (mark_price - average_entry_price) * quantity
            if side == "long"
            else (average_entry_price - mark_price) * quantity
        )
        equity_quote += margin_quote + unrealized_pnl_quote
        open_positions.append(
            PositionSnapshot(
                symbol=symbol,
                quantity=quantity,
                mark_price=mark_price,
                market_value_quote=notional_quote,
                side=side,
                average_entry_price=average_entry_price,
                notional_quote=notional_quote,
                unrealized_pnl_quote=unrealized_pnl_quote,
                leverage=leverage,
                margin_mode=settings.contract_margin_mode,
            )
        )
    return AccountSnapshot(
        quote_currency=settings.quote_currency,
        equity_quote=equity_quote,
        free_quote=free_quote,
        open_positions=open_positions,
        mode=settings.mode,
        market_type=settings.market_type,
    )


class MarketGateway:
    def __init__(self, settings: Settings, exchange_pool: ExchangePool | None = None) -> None:
        self.settings = settings
        self.exchange_pool = exchange_pool or ExchangePool(settings)

    def _build_higher_timeframe_context(self, exchange: Any, symbol: str, now_ms: int) -> dict[str, Any] | None:
        trend_timeframe = (self.settings.candidate_trend_timeframe or "").strip()
        if not trend_timeframe or trend_timeframe == self.settings.timeframe:
            return None
        trend_timeframe_ms = timeframe_to_ms(trend_timeframe)
        if trend_timeframe_ms <= timeframe_to_ms(self.settings.timeframe):
            return None
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=trend_timeframe, limit=max(49, MIN_COMPLETED_CANDLES + 1))
        candles = [
            Candle(
                timestamp_ms=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
            for row in ohlcv
        ]
        completed = _latest_completed_candles(candles, trend_timeframe_ms, now_ms)
        closes = [candle.close for candle in completed]
        returns_12bars = (closes[-1] / closes[-13]) - 1.0
        sma_fast_ratio = (closes[-1] / _sma(closes, 12)) - 1.0
        sma_slow_ratio = (closes[-1] / _sma(closes, 24)) - 1.0
        rsi_14 = _rsi(closes, 14)
        return {
            "timeframe": trend_timeframe,
            "return_12bars": returns_12bars,
            "sma_fast_ratio": sma_fast_ratio,
            "sma_slow_ratio": sma_slow_ratio,
            "rsi_14": rsi_14,
            "trend_bias": _trend_bias(returns_12bars, sma_fast_ratio, sma_slow_ratio, rsi_14),
        }

    def fetch_bundle(self, journal: Journal) -> MarketSnapshotBundle:
        public_exchange = self.exchange_pool.public()
        markets = public_exchange.load_markets()
        resolved_symbols = resolve_market_symbols(markets, self.settings.symbols, self.settings)
        symbol_snapshots: list[SymbolSnapshot] = []
        latest_prices: dict[str, float] = {}
        timeframe_ms = int(public_exchange.parse_timeframe(self.settings.timeframe) * 1000)
        now_ms = int(utc_now().timestamp() * 1000)
        ohlcv_limit = max(self.settings.lookback_bars + 1, MIN_COMPLETED_CANDLES + 1)

        for symbol in resolved_symbols:
            market = markets[symbol]
            ohlcv = public_exchange.fetch_ohlcv(symbol, timeframe=self.settings.timeframe, limit=ohlcv_limit)
            candles = [
                Candle(
                    timestamp_ms=int(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
                for row in ohlcv
            ]
            completed_candles = _latest_completed_candles(candles, timeframe_ms, now_ms)
            higher_timeframe = None
            try:
                higher_timeframe = self._build_higher_timeframe_context(public_exchange, symbol, now_ms)
            except Exception:
                higher_timeframe = None
            snapshot = build_symbol_snapshot(
                symbol=symbol,
                timeframe=self.settings.timeframe,
                completed_candles=completed_candles,
                exchange_min_cost_quote=float((((market.get("limits") or {}).get("cost") or {}).get("min")) or 0.0) or None,
                exchange_min_amount=float((((market.get("limits") or {}).get("amount") or {}).get("min")) or 0.0) or None,
                exchange_amount_step=market_amount_step(market),
                higher_timeframe=higher_timeframe,
            )
            latest_prices[symbol] = snapshot.last_price
            symbol_snapshots.append(snapshot)

        account = build_paper_account_snapshot(settings=self.settings, journal=journal, latest_prices=latest_prices) if self.settings.paper_mode else self._fetch_live_account(markets, latest_prices)
        return MarketSnapshotBundle(
            generated_at=utc_now(),
            timeframe=self.settings.timeframe,
            symbols=symbol_snapshots,
            account=account,
        )

    def refresh_live_account(self, latest_prices: dict[str, float]) -> AccountSnapshot:
        if self.settings.paper_mode:
            raise RuntimeError("refresh_live_account is only valid in live mode")
        public_exchange = self.exchange_pool.public()
        markets = public_exchange.load_markets()
        return self._fetch_live_account(markets, latest_prices)

    def _fetch_live_account(self, markets: dict[str, dict[str, Any]], latest_prices: dict[str, float]) -> AccountSnapshot:
        private_exchange = self.exchange_pool.private()
        sync_clock = getattr(private_exchange, "load_time_difference", None)
        if callable(sync_clock):
            sync_clock()
        balance = private_exchange.fetch_balance()
        quote_balance = extract_quote_balance(balance, self.settings)

        if not self.settings.contract_market:
            free_quote = quote_balance["quote_free"]
            total_quote = quote_balance["quote_total"]
            open_positions: list[PositionSnapshot] = []
            equity_quote = total_quote

            for symbol in resolve_market_symbols(markets, self.settings.symbols, self.settings):
                base_asset = symbol.split("/")[0]
                quantity = float(balance["total"].get(base_asset, 0.0))
                if quantity <= 0:
                    continue
                mark_price = latest_prices[symbol]
                market_value_quote = quantity * mark_price
                if market_value_quote < self.settings.min_notional_quote * 0.5:
                    continue
                equity_quote += market_value_quote
                open_positions.append(
                    PositionSnapshot(
                        symbol=symbol,
                        quantity=quantity,
                        mark_price=mark_price,
                        market_value_quote=market_value_quote,
                        side="long",
                        average_entry_price=None,
                        notional_quote=market_value_quote,
                    )
                )

            return AccountSnapshot(
                quote_currency=self.settings.quote_currency,
                equity_quote=equity_quote,
                free_quote=free_quote,
                open_positions=open_positions,
                mode=self.settings.mode,
                market_type=self.settings.market_type,
            )

        resolved_symbols = resolve_market_symbols(markets, self.settings.symbols, self.settings)
        open_positions = fetch_futures_position_snapshots(
            private_exchange,
            balance=balance,
            markets=markets,
            resolved_symbols=resolved_symbols,
            latest_prices=latest_prices,
            min_notional_quote=self.settings.min_notional_quote * 0.5,
        )

        return AccountSnapshot(
            quote_currency=self.settings.quote_currency,
            equity_quote=quote_balance["margin_balance"],
            free_quote=quote_balance["quote_free"],
            open_positions=open_positions,
            mode=self.settings.mode,
            market_type=self.settings.market_type,
        )
