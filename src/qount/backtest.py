from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .exchange_utils import build_exchange
from .exchange_utils import market_amount_step
from .exchange_utils import resolve_market_symbols
from .journal import Journal
from .market import MIN_COMPLETED_CANDLES
from .market import _latest_completed_candles
from .market import build_higher_timeframe_context_from_completed_candles
from .market import build_paper_account_snapshot
from .market import build_symbol_snapshot
from .models import Candle
from .models import MarketSnapshotBundle
from .models import utc_now
from .orchestrator import Orchestrator
from .review import ReviewService
from .settings import Settings
from .trade_policy import timeframe_to_ms


def parse_backtest_datetime(raw: str) -> datetime:
    value = raw.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _max_drawdown_pct(equity_curve: list[dict[str, Any]]) -> float | None:
    peak: float | None = None
    max_drawdown = 0.0
    for item in equity_curve:
        equity = float(item.get("equity_quote") or 0.0)
        if peak is None or equity > peak:
            peak = equity
            continue
        if peak > 0.0:
            drawdown = (peak - equity) / peak * 100.0
            if drawdown > max_drawdown:
                max_drawdown = drawdown
    return max_drawdown if peak is not None else None


class HistoricalCandleExchange:
    def __init__(self, candles_by_key: dict[tuple[str, str], list[list[float]]]) -> None:
        self._candles_by_key = candles_by_key

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: int | None = None,
        limit: int | None = None,
    ) -> list[list[float]]:
        rows = self._candles_by_key[(symbol, timeframe)]
        filtered = [row for row in rows if since is None or int(row[0]) >= since]
        if limit is not None:
            return filtered[:limit]
        return filtered


class HistoricalReviewService(ReviewService):
    def __init__(
        self,
        settings: Settings,
        journal: Journal,
        candles_by_key: dict[tuple[str, str], list[list[float]]],
    ) -> None:
        super().__init__(settings, journal)
        self._historical_exchange = HistoricalCandleExchange(candles_by_key)

    def _exchange(self):
        return self._historical_exchange


class HistoricalMarketGateway:
    def __init__(
        self,
        settings: Settings,
        journal: Journal,
        *,
        start: datetime,
        end: datetime,
        review_horizon_bars: int,
        max_bars: int | None = None,
        public_exchange: Any | None = None,
    ) -> None:
        self.settings = settings
        self.journal = journal
        self.start = start.astimezone(timezone.utc)
        self.end = end.astimezone(timezone.utc)
        self.review_horizon_bars = max(review_horizon_bars, 0)
        self.max_bars = max_bars
        self.public_exchange = public_exchange or build_exchange(settings, private=False)
        self.markets = self.public_exchange.load_markets()
        self.resolved_symbols = resolve_market_symbols(self.markets, settings.symbols, settings)
        self.timeframe_ms = timeframe_to_ms(settings.timeframe)
        self.base_candles_by_symbol: dict[str, list[Candle]] = {}
        self.base_rows_by_symbol: dict[str, list[list[float]]] = {}
        self.base_index_by_timestamp: dict[str, dict[int, int]] = {}
        self.higher_candles_by_symbol: dict[str, list[Candle]] = {}
        self.candidate_timestamps: list[int] = []
        self._cursor = 0
        self._last_bundle: MarketSnapshotBundle | None = None
        self._prepare_candles()

    def _fetch_ohlcv_range(
        self,
        *,
        symbol: str,
        timeframe: str,
        start_ms: int,
        end_ms: int,
    ) -> list[list[float]]:
        rows: list[list[float]] = []
        cursor = max(start_ms, 0)
        last_timestamp: int | None = None
        timeframe_ms = timeframe_to_ms(timeframe)
        while cursor <= end_ms:
            batch = self.public_exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=cursor, limit=1000)
            if not batch:
                break
            added = 0
            for row in batch:
                timestamp = int(row[0])
                if timestamp < start_ms:
                    continue
                if last_timestamp is not None and timestamp <= last_timestamp:
                    continue
                rows.append(
                    [
                        timestamp,
                        float(row[1]),
                        float(row[2]),
                        float(row[3]),
                        float(row[4]),
                        float(row[5]),
                    ]
                )
                last_timestamp = timestamp
                added += 1
            if added == 0:
                break
            cursor = int(rows[-1][0]) + timeframe_ms
        return [row for row in rows if int(row[0]) <= end_ms]

    def _prepare_candles(self) -> None:
        start_ms = int(self.start.timestamp() * 1000)
        end_ms = int(self.end.timestamp() * 1000)
        warmup_bars = MIN_COMPLETED_CANDLES
        fetch_start_ms = start_ms - (warmup_bars * self.timeframe_ms)
        fetch_end_ms = end_ms + (self.review_horizon_bars * self.timeframe_ms)

        for symbol in self.resolved_symbols:
            rows = self._fetch_ohlcv_range(
                symbol=symbol,
                timeframe=self.settings.timeframe,
                start_ms=fetch_start_ms,
                end_ms=fetch_end_ms,
            )
            candles = [
                Candle(
                    timestamp_ms=int(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
                for row in rows
            ]
            if len(candles) < MIN_COMPLETED_CANDLES:
                raise ValueError(f"not_enough_backtest_candles:{symbol}:{len(candles)}")
            self.base_rows_by_symbol[symbol] = rows
            self.base_candles_by_symbol[symbol] = candles
            self.base_index_by_timestamp[symbol] = {
                candle.timestamp_ms: index for index, candle in enumerate(candles)
            }

        candidate_timestamps = [
            candle.timestamp_ms
            for candle in self.base_candles_by_symbol[self.resolved_symbols[0]]
            if start_ms <= candle.timestamp_ms <= end_ms
        ]
        candidate_timestamps = [
            timestamp
            for timestamp in candidate_timestamps
            if all(
                timestamp in self.base_index_by_timestamp[symbol]
                and self.base_index_by_timestamp[symbol][timestamp] + 1 >= MIN_COMPLETED_CANDLES
                for symbol in self.resolved_symbols
            )
        ]
        if self.max_bars is not None:
            candidate_timestamps = candidate_timestamps[: max(self.max_bars, 0)]
        self.candidate_timestamps = candidate_timestamps

        trend_timeframe = (self.settings.candidate_trend_timeframe or "").strip()
        if not trend_timeframe or trend_timeframe == self.settings.timeframe:
            return
        trend_timeframe_ms = timeframe_to_ms(trend_timeframe)
        if trend_timeframe_ms <= self.timeframe_ms:
            return
        higher_fetch_start_ms = start_ms - (MIN_COMPLETED_CANDLES * trend_timeframe_ms)
        higher_fetch_end_ms = end_ms + trend_timeframe_ms
        for symbol in self.resolved_symbols:
            rows = self._fetch_ohlcv_range(
                symbol=symbol,
                timeframe=trend_timeframe,
                start_ms=higher_fetch_start_ms,
                end_ms=higher_fetch_end_ms,
            )
            self.higher_candles_by_symbol[symbol] = [
                Candle(
                    timestamp_ms=int(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
                for row in rows
            ]

    def has_next(self) -> bool:
        return self._cursor < len(self.candidate_timestamps)

    def candles_for_review(self) -> dict[tuple[str, str], list[list[float]]]:
        return {
            (symbol, self.settings.timeframe): rows
            for symbol, rows in self.base_rows_by_symbol.items()
        }

    def _higher_timeframe_context(self, symbol: str, now_ms: int) -> dict[str, Any] | None:
        trend_timeframe = (self.settings.candidate_trend_timeframe or "").strip()
        if not trend_timeframe or trend_timeframe == self.settings.timeframe:
            return None
        trend_timeframe_ms = timeframe_to_ms(trend_timeframe)
        candles = self.higher_candles_by_symbol.get(symbol) or []
        completed = [candle for candle in candles if candle.timestamp_ms + trend_timeframe_ms <= now_ms]
        if len(completed) < MIN_COMPLETED_CANDLES:
            return None
        return build_higher_timeframe_context_from_completed_candles(
            timeframe=trend_timeframe,
            completed_candles=completed,
        )

    def next_bundle(self) -> MarketSnapshotBundle:
        if not self.has_next():
            raise StopIteration("historical_backtest_exhausted")
        timestamp = self.candidate_timestamps[self._cursor]
        self._cursor += 1
        now_ms = timestamp + self.timeframe_ms + 1
        latest_prices: dict[str, float] = {}
        symbol_snapshots = []

        for symbol in self.resolved_symbols:
            index = self.base_index_by_timestamp[symbol][timestamp]
            completed_candles = self.base_candles_by_symbol[symbol][: index + 1]
            market = self.markets[symbol]
            higher_timeframe = self._higher_timeframe_context(symbol, now_ms)
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

        bundle = MarketSnapshotBundle(
            generated_at=datetime.fromtimestamp((now_ms - 1) / 1000.0, tz=timezone.utc),
            timeframe=self.settings.timeframe,
            symbols=symbol_snapshots,
            account=build_paper_account_snapshot(
                settings=self.settings,
                journal=self.journal,
                latest_prices=latest_prices,
            ),
        )
        self._last_bundle = bundle
        return bundle

    def final_account_snapshot(self) -> dict[str, Any] | None:
        if self._last_bundle is None:
            return None
        latest_prices = {snapshot.symbol: snapshot.last_price for snapshot in self._last_bundle.symbols}
        account = build_paper_account_snapshot(
            settings=self.settings,
            journal=self.journal,
            latest_prices=latest_prices,
        )
        return {
            "quote_currency": account.quote_currency,
            "equity_quote": account.equity_quote,
            "free_quote": account.free_quote,
            "open_positions": [
                {
                    "symbol": position.symbol,
                    "quantity": position.quantity,
                    "side": position.side,
                    "average_entry_price": position.average_entry_price,
                    "mark_price": position.mark_price,
                    "notional_quote": position.notional_quote,
                    "unrealized_pnl_quote": position.unrealized_pnl_quote,
                }
                for position in account.open_positions
            ],
        }


class BacktestService:
    def __init__(
        self,
        settings: Settings,
        *,
        public_exchange: Any | None = None,
        orchestrator_factory: Any | None = None,
    ) -> None:
        self.settings = settings
        self.public_exchange = public_exchange
        self.orchestrator_factory = orchestrator_factory or Orchestrator

    def _artifact_dir(self, start: datetime, end: datetime, explicit: str | None) -> Path:
        if explicit:
            return Path(explicit).expanduser()
        stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        label = f"{start.strftime('%Y%m%dT%H%M')}-{end.strftime('%Y%m%dT%H%M')}"
        return self.settings.project_root / "state" / "backtests" / f"{stamp}-{label}"

    def _isolated_settings(self, artifact_dir: Path, starting_quote: float | None) -> Settings:
        return replace(
            self.settings,
            mode="paper",
            live_enable=False,
            notify_webhook_url=None,
            state_dir=artifact_dir,
            snapshot_dir=artifact_dir / "snapshots",
            decision_dir=artifact_dir / "decisions",
            log_dir=artifact_dir / "logs",
            db_path=artifact_dir / "qount.db",
            paper_starting_quote=self.settings.paper_starting_quote if starting_quote is None else starting_quote,
        )

    def run(
        self,
        *,
        start: datetime,
        end: datetime,
        review_horizon_bars: int = 3,
        review_threshold_pct: float = 0.003,
        starting_quote: float | None = None,
        max_bars: int | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        if end <= start:
            raise ValueError("backtest_end_must_be_after_start")

        out_dir = self._artifact_dir(start, end, artifact_dir)
        isolated_settings = self._isolated_settings(out_dir, starting_quote)
        isolated_settings.ensure_directories()

        historical_orchestrator = self.orchestrator_factory(isolated_settings)
        historical_orchestrator._write_json_artifact = lambda path, payload: None  # type: ignore[method-assign]
        historical_orchestrator.notifier.send = lambda payload: None  # type: ignore[method-assign]

        market_gateway = HistoricalMarketGateway(
            isolated_settings,
            historical_orchestrator.journal,
            start=start,
            end=end,
            review_horizon_bars=review_horizon_bars,
            max_bars=max_bars,
            public_exchange=self.public_exchange,
        )
        historical_orchestrator.market = market_gateway  # type: ignore[assignment]

        run_summaries: list[dict[str, Any]] = []
        while market_gateway.has_next():
            bundle = market_gateway.next_bundle()
            cycle_summary = historical_orchestrator._process_cycle(  # type: ignore[attr-defined]
                bundle,
                orphan_cleanup={"canceled": [], "errors": []},
            )
            if cycle_summary.get("sub_runs"):
                run_summaries.extend(cycle_summary["sub_runs"])
            else:
                run_summaries.append(cycle_summary)

        review_service = HistoricalReviewService(
            isolated_settings,
            historical_orchestrator.journal,
            market_gateway.candles_for_review(),
        )
        review_report = review_service.signal_review(
            limit=max(len(run_summaries), 1),
            horizon_bars=review_horizon_bars,
            threshold_pct=review_threshold_pct,
        )

        orders = historical_orchestrator.journal.get_order_history(mode=isolated_settings.mode)
        equity_curve = historical_orchestrator.journal.get_equity_series(mode=isolated_settings.mode, limit=max(len(run_summaries), 1_000_000))
        final_account = market_gateway.final_account_snapshot()
        if final_account is not None:
            equity_curve.append(
                {
                    "timestamp": run_summaries[-1]["generated_at"] if run_summaries else utc_now().isoformat(),
                    "equity_quote": float(final_account["equity_quote"]),
                    "free_quote": float(final_account["free_quote"]),
                    "mode": isolated_settings.mode,
                }
            )
        closed_orders = [
            order for order in orders
            if order["status"] == "paper_closed" and order.get("pnl_quote") is not None
        ]
        wins = sum(1 for order in closed_orders if float(order.get("pnl_quote") or 0.0) > 0.0)
        losses = sum(1 for order in closed_orders if float(order.get("pnl_quote") or 0.0) < 0.0)
        total_realized_pnl_quote = sum(float(order.get("pnl_quote") or 0.0) for order in closed_orders)
        final_equity_quote = None if final_account is None else float(final_account["equity_quote"])
        total_return_pct = None
        if final_equity_quote is not None and isolated_settings.paper_starting_quote > 0.0:
            total_return_pct = (
                (final_equity_quote - isolated_settings.paper_starting_quote)
                / isolated_settings.paper_starting_quote
                * 100.0
            )

        result = {
            "mode": "backtest",
            "exchange_id": isolated_settings.exchange_id,
            "market_type": isolated_settings.market_type,
            "timeframe": isolated_settings.timeframe,
            "symbols": list(isolated_settings.symbols),
            "start_utc": start.astimezone(timezone.utc).isoformat(),
            "end_utc": end.astimezone(timezone.utc).isoformat(),
            "artifact_dir": str(out_dir),
            "db_path": str(isolated_settings.db_path),
            "bars_requested": len(market_gateway.candidate_timestamps),
            "runs_completed": len(run_summaries),
            "paper_starting_quote": isolated_settings.paper_starting_quote,
            "final_account": final_account,
            "performance": {
                "final_equity_quote": final_equity_quote,
                "total_realized_pnl_quote": total_realized_pnl_quote,
                "total_return_pct": total_return_pct,
                "max_drawdown_pct": _max_drawdown_pct(equity_curve),
                "closed_trades": len(closed_orders),
                "wins": wins,
                "losses": losses,
            },
            "order_stats": {
                "paper_filled": sum(1 for order in orders if order["status"] == "paper_filled"),
                "paper_closed": sum(1 for order in orders if order["status"] == "paper_closed"),
                "noop": sum(1 for order in orders if order["status"] == "noop"),
                "paper_rejected": sum(1 for order in orders if order["status"] == "paper_rejected"),
            },
            "review": {
                "count": review_report.get("count"),
                "aggregate": review_report.get("aggregate"),
            },
        }

        (out_dir / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "review.json").write_text(json.dumps(review_report, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
