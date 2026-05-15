from __future__ import annotations

from typing import Any

from .exchange_utils import call_with_time_sync_retry
from .exchange_utils import ExchangePool
from .exchange_utils import build_exchange
from .exchange_utils import extract_quote_balance
from .exchange_utils import fetch_futures_position_snapshots
from .exchange_utils import resolve_market_symbols
from .journal import Journal
from .settings import Settings


def _accumulate_one_way_realized_pnl(trades: list[dict[str, Any]], quote_currency: str) -> float:
    realized_total = 0.0
    position_qty = 0.0
    average_entry_price = 0.0
    remaining_entry_fees = 0.0

    for trade in sorted(trades, key=lambda item: int(item.get("timestamp") or 0)):
        qty = float(trade.get("amount") or 0.0)
        if qty <= 0:
            continue

        price = float(trade.get("price") or 0.0)
        side = str(trade.get("side") or "").lower()
        signed_qty = qty if side == "buy" else -qty
        fee = trade.get("fee") or {}
        fee_quote = float(fee.get("cost") or 0.0) if fee.get("currency") == quote_currency else 0.0

        if position_qty == 0.0 or position_qty * signed_qty > 0:
            previous_abs_qty = abs(position_qty)
            new_abs_qty = previous_abs_qty + qty
            average_entry_price = (
                ((average_entry_price * previous_abs_qty) + (price * qty)) / new_abs_qty
                if new_abs_qty > 0
                else 0.0
            )
            position_qty += signed_qty
            remaining_entry_fees += fee_quote
            continue

        previous_abs_qty = abs(position_qty)
        closing_qty = min(previous_abs_qty, qty)
        entry_fee_alloc = remaining_entry_fees * (closing_qty / previous_abs_qty) if previous_abs_qty > 0 else 0.0
        exit_fee_alloc = fee_quote * (closing_qty / qty) if qty > 0 else 0.0
        if position_qty > 0:
            realized_total += closing_qty * (price - average_entry_price) - entry_fee_alloc - exit_fee_alloc
        else:
            realized_total += closing_qty * (average_entry_price - price) - entry_fee_alloc - exit_fee_alloc

        remaining_entry_fees = max(remaining_entry_fees - entry_fee_alloc, 0.0)
        position_qty += signed_qty
        opened_qty = qty - closing_qty
        opened_fee_alloc = max(fee_quote - exit_fee_alloc, 0.0)

        if abs(position_qty) <= 1e-12:
            position_qty = 0.0
            average_entry_price = 0.0
            remaining_entry_fees = 0.0
        elif opened_qty > 1e-12:
            position_qty = opened_qty if signed_qty > 0 else -opened_qty
            average_entry_price = price
            remaining_entry_fees = opened_fee_alloc

    return realized_total


class LiveAnalyticsService:
    def __init__(self, settings: Settings, journal: Journal, exchange_pool: ExchangePool | None = None) -> None:
        self.settings = settings
        self.journal = journal
        self.exchange_pool = exchange_pool or ExchangePool(settings)

    def _exchange(self):
        return self.exchange_pool.private()

    def _trade_fee_quote(self, trade: dict[str, Any]) -> float:
        fee = trade.get("fee") or {}
        if fee.get("currency") == self.settings.quote_currency:
            return float(fee.get("cost") or 0.0)
        return 0.0

    def cached_live_overview(self) -> dict[str, Any]:
        snapshot = self.journal.get_latest_snapshot(mode="live") or {}
        account = snapshot.get("account") or {}
        positions = list(account.get("open_positions") or [])
        live_equity = account.get("equity_quote")
        free_quote = account.get("free_quote")
        unrealized_values = [
            float(item["unrealized_pnl_quote"])
            for item in positions
            if item.get("unrealized_pnl_quote") is not None
        ]
        live_curve = self.journal.get_equity_series(mode="live", limit=200)
        if live_equity is not None and (
            not live_curve or float(live_curve[-1]["equity_quote"]) != float(live_equity)
        ):
            live_curve.append(
                {
                    "timestamp": snapshot.get("generated_at") or self.journal.now_iso(),
                    "equity_quote": live_equity,
                    "free_quote": free_quote,
                    "mode": "live",
                }
            )

        return {
            "quote_currency": account.get("quote_currency", self.settings.quote_currency),
            "quote_total": live_equity,
            "quote_free": free_quote,
            "quote_used": None,
            "wallet_balance_quote": None,
            "equity_quote": live_equity,
            "realized_pnl_quote": None,
            "unrealized_pnl_quote": sum(unrealized_values) if unrealized_values else None,
            "market_type": account.get("market_type", self.settings.market_type),
            "positions": positions,
            "recent_trades": [],
            "equity_curve": live_curve,
            "cached": True,
            "snapshot_generated_at": snapshot.get("generated_at"),
        }

    def fetch_live_overview(self) -> dict[str, Any]:
        exchange = self._exchange()
        balance = call_with_time_sync_retry(exchange, exchange.fetch_balance, sync_before=True)
        markets = call_with_time_sync_retry(exchange, exchange.load_markets)
        resolved_symbols = resolve_market_symbols(markets, self.settings.symbols, self.settings)
        quote_balance = extract_quote_balance(balance, self.settings)
        quote_total = quote_balance["quote_total"]
        quote_free = quote_balance["quote_free"]
        quote_used = quote_balance["quote_used"]

        positions: list[dict[str, Any]] = []
        recent_trades: list[dict[str, Any]] = []
        realized_total = 0.0
        unrealized_total = 0.0
        live_equity = quote_balance["margin_balance"]

        if self.settings.contract_market:
            futures_positions = fetch_futures_position_snapshots(
                exchange,
                balance=balance,
                markets=markets,
                resolved_symbols=resolved_symbols,
            )
            for position in futures_positions:
                unrealized = float(position.unrealized_pnl_quote or 0.0)
                unrealized_total += unrealized
                positions.append(
                    {
                        "symbol": position.symbol,
                        "side": position.side,
                        "quantity": position.quantity,
                        "last_price": position.mark_price,
                        "mark_price": position.mark_price,
                        "market_value_quote": position.market_value_quote,
                        "notional_quote": position.notional_quote,
                        "average_entry_price": position.average_entry_price,
                        "unrealized_pnl_quote": unrealized,
                        "leverage": position.leverage,
                        "margin_mode": position.margin_mode,
                        "liquidation_price": position.liquidation_price,
                    }
                )

            for symbol in resolved_symbols:
                trades = call_with_time_sync_retry(exchange, exchange.fetch_my_trades, symbol, limit=200)
                realized_total += _accumulate_one_way_realized_pnl(trades, self.settings.quote_currency)
                for trade in sorted(trades, key=lambda item: int(item.get("timestamp") or 0)):
                    qty = float(trade.get("amount") or 0.0)
                    price = float(trade.get("price") or 0.0)
                    gross_cost = float(trade.get("cost") or (qty * price))
                    recent_trades.append(
                        {
                            "timestamp": trade.get("datetime"),
                            "symbol": symbol,
                            "side": trade.get("side"),
                            "amount": qty,
                            "price": price,
                            "cost": gross_cost,
                            "fee_quote": self._trade_fee_quote(trade),
                            "id": trade.get("id"),
                        }
                    )
        else:
            tickers = call_with_time_sync_retry(exchange, exchange.fetch_tickers, list(resolved_symbols))
            for symbol in resolved_symbols:
                base = symbol.split("/")[0]
                current_qty = float(balance["total"].get(base, 0.0))
                ticker = tickers.get(symbol) or {}
                last_price = float(ticker.get("last") or ticker.get("close") or 0.0)
                trades = call_with_time_sync_retry(exchange, exchange.fetch_my_trades, symbol, limit=100)
                trades = sorted(trades, key=lambda item: int(item.get("timestamp") or 0))

                remaining_qty = 0.0
                remaining_cost = 0.0
                realized_symbol = 0.0
                for trade in trades:
                    qty = float(trade.get("amount") or 0.0)
                    price = float(trade.get("price") or 0.0)
                    gross_cost = float(trade.get("cost") or (qty * price))
                    fee_quote = self._trade_fee_quote(trade)
                    if trade.get("side") == "buy":
                        remaining_qty += qty
                        remaining_cost += gross_cost + fee_quote
                    elif trade.get("side") == "sell":
                        proceeds = gross_cost - fee_quote
                        if remaining_qty > 0:
                            avg_entry_before = remaining_cost / remaining_qty
                            matched_qty = min(qty, remaining_qty)
                            realized_symbol += proceeds - (avg_entry_before * matched_qty)
                            remaining_qty -= matched_qty
                            remaining_cost -= avg_entry_before * matched_qty
                            remaining_qty = max(remaining_qty, 0.0)
                            remaining_cost = max(remaining_cost, 0.0)

                    recent_trades.append(
                        {
                            "timestamp": trade.get("datetime"),
                            "symbol": symbol,
                            "side": trade.get("side"),
                            "amount": qty,
                            "price": price,
                            "cost": gross_cost,
                            "fee_quote": fee_quote,
                            "id": trade.get("id"),
                        }
                    )

                avg_entry = (remaining_cost / remaining_qty) if remaining_qty > 0 else None
                if current_qty > 0:
                    market_value = current_qty * last_price
                    live_equity += market_value
                    unrealized = (current_qty * (last_price - avg_entry)) if avg_entry else None
                    if unrealized is not None:
                        unrealized_total += unrealized
                    positions.append(
                        {
                            "symbol": symbol,
                            "side": "long",
                            "quantity": current_qty,
                            "last_price": last_price,
                            "market_value_quote": market_value,
                            "notional_quote": market_value,
                            "average_entry_price": avg_entry,
                            "unrealized_pnl_quote": unrealized,
                        }
                    )

                realized_total += realized_symbol

        recent_trades.sort(key=lambda item: item["timestamp"] or "", reverse=True)
        live_curve = self.journal.get_equity_series(mode="live", limit=200)
        if not live_curve or live_curve[-1]["equity_quote"] != live_equity:
            live_curve.append(
                {
                    "timestamp": self.journal.now_iso(),
                    "equity_quote": live_equity,
                    "free_quote": quote_free,
                    "mode": "live",
                }
            )

        return {
            "quote_currency": self.settings.quote_currency,
            "quote_total": quote_total,
            "quote_free": quote_free,
            "quote_used": quote_used,
            "wallet_balance_quote": quote_balance["wallet_balance"],
            "equity_quote": live_equity,
            "realized_pnl_quote": realized_total,
            "unrealized_pnl_quote": unrealized_total,
            "market_type": self.settings.market_type,
            "positions": positions,
            "recent_trades": recent_trades[:12],
            "equity_curve": live_curve,
        }
