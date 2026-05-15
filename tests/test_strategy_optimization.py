from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path

if "ccxt" not in sys.modules:
    class _StubExchange:
        def __init__(self, options=None) -> None:
            self.options = options or {}

    sys.modules["ccxt"] = types.SimpleNamespace(
        binance=_StubExchange,
        binanceus=_StubExchange,
    )

from qount.candidate_filter import CandidateFilter
from qount.executor import Executor
from qount.journal import Journal
from qount.models import AccountSnapshot
from qount.models import AIDecision
from qount.models import Candle
from qount.models import ExecutionResult
from qount.models import MarketSnapshotBundle
from qount.models import PositionSnapshot
from qount.models import RiskVerdict
from qount.models import SymbolSnapshot
from qount.models import ValidatedDecision
from qount.models import utc_now
from qount.orchestrator import Orchestrator
from qount.review import ReviewService
from qount.risk_engine import RiskEngine
from qount.settings import Settings


def make_settings(project_root: Path, **overrides) -> Settings:
    defaults = dict(
        project_root=project_root,
        state_dir=project_root / "state",
        snapshot_dir=project_root / "state" / "snapshots",
        decision_dir=project_root / "state" / "decisions",
        log_dir=project_root / "state" / "logs",
        db_path=project_root / "state" / "qount.db",
        system_prompt_path=project_root / "prompts" / "system_prompt_v1.txt",
        decision_prompt_path=project_root / "prompts" / "decision_prompt_v1.txt",
        mode="paper",
        exchange_id="binanceus",
        market_type="spot",
        live_enable=False,
        live_confirmation=None,
        openai_base_url="http://127.0.0.1:8318/v1",
        openai_api_key="test",
        ai_model="gpt-5.4-mini",
        ai_timeout_seconds=30,
        symbols=("BTC/USDT", "ETH/USDT"),
        timeframe="5m",
        lookback_bars=200,
        quote_currency="USDT",
        paper_starting_quote=200.0,
        max_open_positions=1,
        max_entry_size_pct=0.30,
        max_risk_per_trade_pct=0.01,
        min_open_size_pct=0.10,
        min_take_profit_pct=0.015,
        daily_loss_limit_pct=0.03,
        min_notional_quote=25.0,
        cooldown_bars_after_losses=3,
        estimated_fee_pct=0.0004,
        estimated_slippage_pct=0.0002,
        risk_sizing_enable=True,
        risk_sizing_include_cost=True,
        min_effective_stop_loss_pct=0.005,
        max_effective_stop_loss_pct=0.03,
        candidate_trend_timeframe="1h",
        min_expected_edge_pct=0.0015,
        flip_cooldown_bars=2,
        min_hold_bars=2,
        same_symbol_reentry_cooldown_bars=3,
        trailing_profit_arm_pct=0.01,
        trailing_profit_retrace_pct=0.005,
        partial_take_profit_enable=True,
        partial_take_profit_trigger_pct=0.012,
        partial_take_profit_step_pct=0.012,
        partial_take_profit_fraction=0.50,
        partial_take_profit_max_times=1,
        breakeven_stop_buffer_pct=0.0012,
        dynamic_protective_refresh_enable=True,
        run_delay_seconds=60,
        preflight_cache_seconds=900,
        http_proxy=None,
        https_proxy=None,
        binance_api_key=None,
        binance_api_secret=None,
        contract_leverage=3,
        contract_margin_mode="isolated",
        notify_webhook_url=None,
    )
    defaults.update(overrides)
    settings = Settings(**defaults)
    settings.ensure_directories()
    return settings


def make_symbol(
    symbol: str,
    timestamp_ms: int,
    close: float,
    *,
    atr_pct: float,
    range_pct: float,
    volume_ratio: float,
    higher_bias: str | None = None,
) -> SymbolSnapshot:
    recent_candle = Candle(
        timestamp_ms=timestamp_ms,
        open=close * 0.995,
        high=close * (1.0 + range_pct / 2.0),
        low=close * (1.0 - range_pct / 2.0),
        close=close,
        volume=1000.0,
    )
    higher_timeframe = None
    if higher_bias is not None:
        higher_timeframe = {
            "timeframe": "1h",
            "return_12bars": 0.02 if higher_bias == "long" else -0.02 if higher_bias == "short" else 0.0,
            "sma_fast_ratio": 0.01 if higher_bias == "long" else -0.01 if higher_bias == "short" else 0.0,
            "sma_slow_ratio": 0.02 if higher_bias == "long" else -0.02 if higher_bias == "short" else 0.0,
            "rsi_14": 58.0 if higher_bias == "long" else 42.0 if higher_bias == "short" else 50.0,
            "trend_bias": higher_bias,
        }
    return SymbolSnapshot(
        symbol=symbol,
        timeframe="5m",
        last_price=close,
        indicators={
            "return_1bar": 0.003,
            "return_24bars": 0.02,
            "sma_fast_ratio": 0.005,
            "sma_slow_ratio": 0.01,
            "rsi_14": 55.0,
            "atr_14_pct": atr_pct,
            "volume_ratio_20": volume_ratio,
            "range_pct": range_pct,
        },
        recent_candles=[recent_candle],
        exchange_min_cost_quote=5.0,
        exchange_min_amount=0.001,
        exchange_amount_step=0.001,
        higher_timeframe=higher_timeframe,
    )


def make_bundle(
    *,
    timestamp_ms: int,
    symbols: list[SymbolSnapshot],
    open_positions: list[PositionSnapshot] | None = None,
    equity_quote: float = 200.0,
    free_quote: float = 200.0,
) -> MarketSnapshotBundle:
    return MarketSnapshotBundle(
        generated_at=utc_now(),
        timeframe="5m",
        symbols=symbols,
        account=AccountSnapshot(
            quote_currency="USDT",
            equity_quote=equity_quote,
            free_quote=free_quote,
            open_positions=open_positions or [],
            mode="paper",
            market_type="spot",
        ),
    )


def make_decision(symbol: str, action: str, *, confidence: float = 0.8, take_profit_pct: float = 0.02) -> ValidatedDecision:
    return ValidatedDecision(
        decision=AIDecision(
            timestamp=utc_now().isoformat(),
            symbol=symbol,
            action=action,
            size_pct=0.10 if action != "hold" else 0.0,
            take_profit_pct=take_profit_pct,
            stop_loss_pct=0.01 if action != "hold" else 0.0,
            ttl_minutes=30,
            confidence=confidence,
            reason="test",
            prompt_version="v1",
        ),
        valid=True,
        errors=[],
        raw_payload={"symbol": symbol, "action": action},
    )


def record_run(
    journal: Journal,
    settings: Settings,
    *,
    bundle: MarketSnapshotBundle,
    decision_action: str,
    final_action: str,
    symbol: str,
    confidence: float = 0.8,
    raw_payload_extra: dict | None = None,
    risk_reasons: list[str] | None = None,
) -> None:
    run_id = journal.start_run(settings.mode)
    journal.record_snapshot(run_id, bundle)
    validated = make_decision(symbol, decision_action, confidence=confidence)
    if raw_payload_extra:
        merged_raw_payload = dict(validated.raw_payload or {})
        merged_raw_payload.update(raw_payload_extra)
        validated = ValidatedDecision(
            decision=validated.decision,
            valid=validated.valid,
            errors=validated.errors,
            raw_payload=merged_raw_payload,
        )
    journal.record_validated_decision(run_id, validated)
    journal.record_risk(
        run_id,
        RiskVerdict(
            status="approved",
            final_action=final_action,
            symbol=symbol,
            final_size_pct=0.10 if final_action != "hold" else 0.0,
            take_profit_pct=0.02,
            stop_loss_pct=0.01 if final_action != "hold" else 0.0,
            ttl_minutes=30,
            reasons=risk_reasons or ["ok"],
            confidence=confidence,
            approved=True,
        ),
    )
    journal.finish_run(run_id, "completed", {"run_id": run_id})


class FakeExchange:
    def __init__(self, candles_by_symbol: dict[str, list[list[float]]]) -> None:
        self.candles_by_symbol = candles_by_symbol

    def fetch_ohlcv(self, symbol: str, timeframe: str, since: int, limit: int):
        return self.candles_by_symbol[symbol]


class FakeReviewService(ReviewService):
    def __init__(self, settings: Settings, journal: Journal, candles_by_symbol: dict[str, list[list[float]]]) -> None:
        super().__init__(settings, journal)
        self._candles_by_symbol = candles_by_symbol

    def _exchange(self):
        return FakeExchange(self._candles_by_symbol)


class FakeTradeExchange:
    def __init__(
        self,
        *,
        average_price: float = 1.45,
        open_orders: list[dict] | None = None,
        conditional_open_orders: list[dict] | None = None,
    ) -> None:
        self.average_price = average_price
        self.created_orders: list[dict] = []
        self.cancelled_orders: list[tuple[str, str | None]] = []
        self._open_orders = list(open_orders or [])
        self._conditional_open_orders = list(conditional_open_orders or [])

    def load_time_difference(self) -> None:
        return None

    def load_markets(self) -> dict[str, dict]:
        return {
            "XRP/USDT:USDT": {
                "symbol": "XRP/USDT:USDT",
                "id": "XRPUSDT",
                "contract": True,
                "linear": True,
                "swap": True,
                "limits": {
                    "cost": {"min": 5.0},
                    "amount": {"min": 0.1},
                },
                "precision": {
                    "amount": 0.1,
                    "price": 0.0001,
                },
            }
        }

    def set_margin_mode(self, margin_mode: str, symbol: str) -> None:
        return None

    def set_leverage(self, leverage: int, symbol: str) -> None:
        return None

    def fetch_balance(self) -> dict:
        return {
            "free": {"USDT": 100.0},
            "total": {"USDT": 100.0},
            "used": {"USDT": 0.0},
            "info": {
                "assets": [
                    {
                        "asset": "USDT",
                        "marginBalance": "100.0",
                        "availableBalance": "100.0",
                        "walletBalance": "100.0",
                    }
                ]
            },
        }

    def amount_to_precision(self, symbol: str, amount: float) -> str:
        return f"{amount:.1f}"

    def create_order(self, symbol: str, type: str, side: str, amount: float, price=None, params=None):
        params = params or {}
        order_id = str(len(self.created_orders) + 1)
        order = {
            "id": order_id,
            "status": "closed" if type == "market" else "open",
            "symbol": symbol,
            "type": type,
            "side": side,
            "amount": amount,
            "filled": amount if type == "market" else 0.0,
            "average": self.average_price if type == "market" else None,
            "clientOrderId": params.get("newClientOrderId") or params.get("clientAlgoId"),
            "info": dict(params),
        }
        self.created_orders.append(order)
        if type != "market":
            if params.get("stopPrice") is not None:
                self._conditional_open_orders.append(order)
            else:
                self._open_orders.append(order)
        return order

    def fetch_open_orders(self, symbol: str, params=None):
        params = params or {}
        source = self._conditional_open_orders if params.get("trigger") else self._open_orders
        return [order for order in source if order.get("symbol") == symbol]

    def cancel_order(self, id: str, symbol: str | None = None, params=None):
        self.cancelled_orders.append((id, symbol))
        self._open_orders = [order for order in self._open_orders if str(order.get("id")) != str(id)]
        self._conditional_open_orders = [order for order in self._conditional_open_orders if str(order.get("id")) != str(id)]
        return {"id": id, "symbol": symbol}


class FakeTradeExchangePool:
    def __init__(self, exchange: FakeTradeExchange) -> None:
        self.exchange = exchange

    def private(self):
        return self.exchange


class StrategyOptimizationTests(unittest.TestCase):
    def test_portfolio_filtered_hold_is_excluded_from_symbol_history_and_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(root)
            journal = Journal(settings.db_path)
            journal.ensure_schema()

            run_id = journal.start_run(settings.mode)
            bundle = make_bundle(
                timestamp_ms=600_000,
                symbols=[
                    make_symbol("BTC/USDT", 600_000, 100.0, atr_pct=0.0010, range_pct=0.0012, volume_ratio=0.60, higher_bias="long"),
                    make_symbol("ETH/USDT", 600_000, 200.0, atr_pct=0.0011, range_pct=0.0013, volume_ratio=0.65, higher_bias="long"),
                ],
            )
            journal.record_snapshot(run_id, bundle)
            journal.record_validated_decision(
                run_id,
                ValidatedDecision(
                    decision=AIDecision(
                        timestamp=utc_now().isoformat(),
                        symbol="BTC/USDT",
                        action="hold",
                        size_pct=0.0,
                        take_profit_pct=0.0,
                        stop_loss_pct=0.0,
                        ttl_minutes=0,
                        confidence=0.0,
                        reason="candidate_filter:no_eligible_symbols",
                        prompt_version="v1",
                    ),
                    valid=True,
                    errors=[],
                    raw_payload={
                        "symbol": "BTC/USDT",
                        "action": "hold",
                        "scope": "portfolio",
                        "candidate_filter_generated": True,
                    },
                ),
            )
            journal.record_risk(
                run_id,
                RiskVerdict(
                    status="approved",
                    final_action="hold",
                    symbol="BTC/USDT",
                    final_size_pct=0.0,
                    take_profit_pct=0.0,
                    stop_loss_pct=0.0,
                    ttl_minutes=0,
                    reasons=["candidate_filter:no_eligible_symbols"],
                    confidence=0.0,
                    approved=True,
                ),
            )
            journal.finish_run(run_id, "completed", {"run_id": run_id})

            self.assertEqual(journal.get_recent_signal_actions(limit=5), [])
            self.assertEqual(journal.get_signal_review_candidates(limit=5), [])

    def test_orchestrator_filtered_hold_uses_resolved_contract_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("SOL/USDT", "XRP/USDT"),
            )
            orchestrator = Orchestrator(settings)
            bundle = make_bundle(
                timestamp_ms=600_000,
                symbols=[
                    make_symbol("SOL/USDT:USDT", 600_000, 100.0, atr_pct=0.0010, range_pct=0.0012, volume_ratio=0.60, higher_bias="short"),
                    make_symbol("XRP/USDT:USDT", 600_000, 200.0, atr_pct=0.0011, range_pct=0.0013, volume_ratio=0.65, higher_bias="short"),
                ],
            )

            class _StubMarket:
                def fetch_bundle(self, journal):
                    return bundle

            class _StubCandidateResult:
                status = "filtered_hold"
                filtered_bundle = None
                summary = {
                    "status": "filtered_hold",
                    "selected_symbols": [],
                    "symbols": [],
                }

            class _StubCandidateFilter:
                def apply(self, bundle):
                    return _StubCandidateResult()

            orchestrator.market = _StubMarket()
            orchestrator.candidate_filter = _StubCandidateFilter()

            result = orchestrator.run_once()

            self.assertEqual(result["action"], "hold")
            latest_order = orchestrator.journal.get_order_history(mode=settings.mode, limit=1)[-1]
            self.assertEqual(latest_order["symbol"], "SOL/USDT:USDT")
            self.assertEqual(latest_order["raw_json"]["reasons"], ["ok"])

    def test_candidate_filter_prefers_tradeable_symbol_and_respects_open_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(root)
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            filter_service = CandidateFilter(settings, journal)

            bundle = make_bundle(
                timestamp_ms=600_000,
                symbols=[
                    make_symbol("BTC/USDT", 600_000, 100.0, atr_pct=0.0010, range_pct=0.0012, volume_ratio=0.60, higher_bias="short"),
                    make_symbol("ETH/USDT", 600_000, 200.0, atr_pct=0.0040, range_pct=0.0050, volume_ratio=1.20, higher_bias="long"),
                ],
            )
            result = filter_service.apply(bundle)
            self.assertEqual(result.status, "selected")
            self.assertEqual(result.summary["selected_symbols"], ["ETH/USDT"])

            managed_bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=bundle.symbols,
                open_positions=[
                    PositionSnapshot(
                        symbol="BTC/USDT",
                        quantity=1.0,
                        mark_price=100.0,
                        market_value_quote=100.0,
                        side="long",
                        average_entry_price=98.0,
                        notional_quote=100.0,
                    )
                ],
                equity_quote=200.0,
                free_quote=100.0,
            )
            managed = filter_service.apply(managed_bundle)
            self.assertEqual(managed.summary["selected_symbols"], ["BTC/USDT"])

    def test_candidate_filter_uses_open_position_headroom_and_softens_flat_bias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                max_open_positions=2,
                symbols=("SOL/USDT", "XRP/USDT"),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            filter_service = CandidateFilter(settings, journal)

            managed_bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[
                    make_symbol("SOL/USDT:USDT", 900_000, 100.0, atr_pct=0.0040, range_pct=0.0045, volume_ratio=1.20, higher_bias="long"),
                    make_symbol("XRP/USDT:USDT", 900_000, 200.0, atr_pct=0.0042, range_pct=0.0048, volume_ratio=1.25, higher_bias="flat"),
                ],
                open_positions=[
                    PositionSnapshot(
                        symbol="SOL/USDT:USDT",
                        quantity=1.0,
                        mark_price=100.0,
                        market_value_quote=100.0,
                        side="long",
                        average_entry_price=98.0,
                        notional_quote=100.0,
                    )
                ],
                equity_quote=200.0,
                free_quote=100.0,
            )
            managed = filter_service.apply(managed_bundle)
            self.assertEqual(managed.summary["selected_symbols"], ["SOL/USDT:USDT", "XRP/USDT:USDT"])
            xrp_summary = next(item for item in managed.summary["symbols"] if item["symbol"] == "XRP/USDT:USDT")
            self.assertTrue(xrp_summary["eligible"])
            self.assertIn("higher_timeframe_flat_bias_soft_penalty", xrp_summary["reasons"])

    def test_candidate_filter_blocks_recent_reentry_before_ai(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(root)
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            filter_service = CandidateFilter(settings, journal)

            previous_close_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[make_symbol("BTC/USDT", 300_000, 99.0, atr_pct=0.0040, range_pct=0.0045, volume_ratio=1.10, higher_bias="long")],
                open_positions=[
                    PositionSnapshot(
                        symbol="BTC/USDT",
                        quantity=1.0,
                        mark_price=99.0,
                        market_value_quote=99.0,
                        side="long",
                        average_entry_price=97.0,
                        notional_quote=99.0,
                    )
                ],
                equity_quote=200.0,
                free_quote=101.0,
            )
            record_run(journal, settings, bundle=previous_close_bundle, decision_action="close", final_action="close", symbol="BTC/USDT")

            reentry_bundle = make_bundle(
                timestamp_ms=600_000,
                symbols=[make_symbol("BTC/USDT", 600_000, 100.0, atr_pct=0.0040, range_pct=0.0050, volume_ratio=1.10, higher_bias="long")],
            )
            filtered = filter_service.apply(reentry_bundle)

            self.assertEqual(filtered.status, "filtered_hold")
            btc_summary = filtered.summary["symbols"][0]
            self.assertIn("same_symbol_reentry_cooldown_active:1<3", btc_summary["reasons"])

    def test_candidate_filter_blocks_countertrend_short_candidates_before_ai(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            filter_service = CandidateFilter(settings, journal)

            symbol = make_symbol("XRP/USDT:USDT", 600_000, 1.5, atr_pct=0.0025, range_pct=0.0020, volume_ratio=1.30, higher_bias="short")
            symbol.indicators["return_1bar"] = 0.0010
            symbol.indicators["return_24bars"] = 0.0040
            symbol.indicators["sma_fast_ratio"] = 0.0008
            symbol.indicators["sma_slow_ratio"] = 0.0005
            bundle = make_bundle(
                timestamp_ms=600_000,
                symbols=[symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )

            filtered = filter_service.apply(bundle)
            self.assertEqual(filtered.status, "filtered_hold")
            xrp_summary = filtered.summary["symbols"][0]
            self.assertIn("short_setup_countertrend_drift", xrp_summary["reasons"])
            self.assertIn("short_setup_latest_bar_rebound", xrp_summary["reasons"])

    def test_candidate_filter_softens_moderately_low_volume_when_directional_bias_is_clear(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("SOL/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            filter_service = CandidateFilter(settings, journal)

            symbol = make_symbol("SOL/USDT:USDT", 600_000, 100.0, atr_pct=0.0030, range_pct=0.0032, volume_ratio=0.55, higher_bias="long")
            bundle = make_bundle(
                timestamp_ms=600_000,
                symbols=[symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )

            filtered = filter_service.apply(bundle)

            self.assertEqual(filtered.status, "selected")
            self.assertEqual(filtered.summary["selected_symbols"], ["SOL/USDT:USDT"])
            sol_summary = filtered.summary["symbols"][0]
            self.assertTrue(sol_summary["eligible"])
            self.assertIn("low_volume_soft_penalty", sol_summary["reasons"])

    def test_candidate_filter_marks_terminal_short_extension_as_soft_penalty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("SOL/USDT:USDT", "XRP/USDT:USDT"),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            filter_service = CandidateFilter(settings, journal)

            sol_symbol = make_symbol("SOL/USDT:USDT", 600_000, 100.0, atr_pct=0.0040, range_pct=0.0045, volume_ratio=1.25, higher_bias="short")
            sol_symbol.indicators["return_1bar"] = -0.0010
            sol_symbol.indicators["return_24bars"] = -0.0030
            sol_symbol.indicators["rsi_14"] = 35.0
            sol_symbol.indicators["sma_fast_ratio"] = -0.0015
            sol_symbol.indicators["sma_slow_ratio"] = -0.0012
            sol_symbol.recent_candles[-1].open = 100.70
            sol_symbol.recent_candles[-1].high = 100.75
            sol_symbol.recent_candles[-1].low = 99.95
            sol_symbol.recent_candles[-1].close = 100.0

            xrp_symbol = make_symbol("XRP/USDT:USDT", 600_000, 1.50, atr_pct=0.0040, range_pct=0.0045, volume_ratio=0.95, higher_bias="short")
            xrp_symbol.indicators["return_1bar"] = -0.0012
            xrp_symbol.indicators["return_24bars"] = -0.0030
            xrp_symbol.indicators["rsi_14"] = 32.0
            xrp_symbol.indicators["sma_fast_ratio"] = -0.0015
            xrp_symbol.indicators["sma_slow_ratio"] = -0.0012
            xrp_symbol.recent_candles[-1].open = 1.511
            xrp_symbol.recent_candles[-1].high = 1.512
            xrp_symbol.recent_candles[-1].low = 1.499
            xrp_symbol.recent_candles[-1].close = 1.500

            bundle = make_bundle(
                timestamp_ms=600_000,
                symbols=[sol_symbol, xrp_symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )

            filtered = filter_service.apply(bundle)

            self.assertEqual(filtered.status, "selected")
            xrp_summary = next(item for item in filtered.summary["symbols"] if item["symbol"] == "XRP/USDT:USDT")
            sol_summary = next(item for item in filtered.summary["symbols"] if item["symbol"] == "SOL/USDT:USDT")
            self.assertTrue(xrp_summary["eligible"])
            self.assertIn("short_setup_late_breakdown_soft_penalty", xrp_summary["reasons"])
            self.assertNotIn("short_setup_late_breakdown_soft_penalty", sol_summary["reasons"])
            self.assertLess(xrp_summary["score"], sol_summary["score"])

    def test_candidate_filter_marks_climactic_terminal_short_extension_as_soft_penalty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("SOL/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            filter_service = CandidateFilter(settings, journal)

            symbol = make_symbol("SOL/USDT:USDT", 900_000, 90.64, atr_pct=0.0018, range_pct=0.0044, volume_ratio=2.99, higher_bias="short")
            symbol.indicators["return_1bar"] = -0.0041
            symbol.indicators["return_24bars"] = -0.0060
            symbol.indicators["rsi_14"] = 30.0
            symbol.indicators["sma_fast_ratio"] = -0.0044
            symbol.indicators["sma_slow_ratio"] = -0.0052
            symbol.recent_candles[-1].open = 91.00
            symbol.recent_candles[-1].high = 91.03
            symbol.recent_candles[-1].low = 90.63
            symbol.recent_candles[-1].close = 90.64
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )

            filtered = filter_service.apply(bundle)

            self.assertEqual(filtered.status, "selected")
            sol_summary = filtered.summary["symbols"][0]
            self.assertTrue(sol_summary["eligible"])
            self.assertIn("short_setup_late_breakdown_soft_penalty", sol_summary["reasons"])

    def test_candidate_filter_adds_pre_breakdown_watch_for_early_continuation_short(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("SOL/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            filter_service = CandidateFilter(settings, journal)

            symbol = make_symbol("SOL/USDT:USDT", 900_000, 91.0, atr_pct=0.00165, range_pct=0.00121, volume_ratio=0.73, higher_bias="short")
            symbol.indicators["return_1bar"] = -0.00055
            symbol.indicators["return_24bars"] = -0.00197
            symbol.indicators["rsi_14"] = 46.9
            symbol.indicators["sma_fast_ratio"] = -0.00093
            symbol.indicators["sma_slow_ratio"] = -0.00142
            symbol.recent_candles[-1].open = 91.05
            symbol.recent_candles[-1].high = 91.07
            symbol.recent_candles[-1].low = 90.96
            symbol.recent_candles[-1].close = 91.0
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )

            filtered = filter_service.apply(bundle)

            self.assertEqual(filtered.status, "selected")
            sol_summary = filtered.summary["symbols"][0]
            self.assertTrue(sol_summary["eligible"])
            self.assertIn("low_volatility_soft_penalty", sol_summary["reasons"])
            self.assertIn("short_setup_pre_breakdown_watch", sol_summary["reasons"])
            self.assertNotIn("short_setup_late_breakdown_soft_penalty", sol_summary["reasons"])

    def test_candidate_filter_still_blocks_hard_low_volume_and_hard_low_volatility(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("SOL/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            filter_service = CandidateFilter(settings, journal)

            symbol = make_symbol("SOL/USDT:USDT", 600_000, 100.0, atr_pct=0.0012, range_pct=0.0013, volume_ratio=0.40, higher_bias="long")
            bundle = make_bundle(
                timestamp_ms=600_000,
                symbols=[symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )

            filtered = filter_service.apply(bundle)

            self.assertEqual(filtered.status, "filtered_hold")
            sol_summary = filtered.summary["symbols"][0]
            self.assertFalse(sol_summary["eligible"])
            self.assertIn("low_volume", sol_summary["reasons"])
            self.assertIn("low_volatility", sol_summary["reasons"])

    def test_risk_engine_allows_second_symbol_when_position_headroom_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                max_open_positions=2,
                symbols=("SOL/USDT:USDT", "XRP/USDT:USDT"),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            strong_symbol = make_symbol("XRP/USDT:USDT", 900_000, 1.5, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="short")
            strong_symbol.indicators["return_24bars"] = -0.0030
            strong_symbol.indicators["sma_fast_ratio"] = -0.0020
            strong_symbol.indicators["sma_slow_ratio"] = -0.0030
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[
                    make_symbol("SOL/USDT:USDT", 900_000, 100.0, atr_pct=0.0040, range_pct=0.0045, volume_ratio=1.20, higher_bias="long"),
                    strong_symbol,
                ],
                open_positions=[
                    PositionSnapshot(
                        symbol="SOL/USDT:USDT",
                        quantity=1.0,
                        mark_price=100.0,
                        market_value_quote=100.0,
                        side="long",
                        average_entry_price=98.0,
                        notional_quote=100.0,
                    )
                ],
                equity_quote=200.0,
                free_quote=100.0,
            )

            verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "sell"), bundle)
            self.assertEqual(verdict.final_action, "sell")
            self.assertNotIn("max_open_positions_reached", verdict.reasons)

    def test_risk_engine_blocks_thin_edge_reentry_and_too_fast_close(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(root)
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            thin_bundle = make_bundle(
                timestamp_ms=600_000,
                symbols=[make_symbol("BTC/USDT", 600_000, 100.0, atr_pct=0.0008, range_pct=0.0009, volume_ratio=1.10, higher_bias="long")],
            )
            thin_verdict = risk_engine.evaluate(make_decision("BTC/USDT", "buy", take_profit_pct=0.0010), thin_bundle)
            self.assertEqual(thin_verdict.final_action, "hold")
            self.assertTrue(any(reason.startswith("expected_edge_below_minimum") for reason in thin_verdict.reasons))

            previous_close_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[make_symbol("BTC/USDT", 300_000, 99.0, atr_pct=0.0040, range_pct=0.0045, volume_ratio=1.10, higher_bias="long")],
                open_positions=[
                    PositionSnapshot(
                        symbol="BTC/USDT",
                        quantity=1.0,
                        mark_price=99.0,
                        market_value_quote=99.0,
                        side="long",
                        average_entry_price=97.0,
                        notional_quote=99.0,
                    )
                ],
                equity_quote=200.0,
                free_quote=101.0,
            )
            record_run(journal, settings, bundle=previous_close_bundle, decision_action="close", final_action="close", symbol="BTC/USDT")

            reentry_bundle = make_bundle(
                timestamp_ms=600_000,
                symbols=[make_symbol("BTC/USDT", 600_000, 100.0, atr_pct=0.0040, range_pct=0.0050, volume_ratio=1.10, higher_bias="long")],
            )
            reentry_verdict = risk_engine.evaluate(make_decision("BTC/USDT", "buy"), reentry_bundle)
            self.assertEqual(reentry_verdict.final_action, "hold")
            self.assertTrue(any(reason.startswith("same_symbol_reentry_cooldown_active") for reason in reentry_verdict.reasons))

            with tempfile.TemporaryDirectory() as tmp2:
                root2 = Path(tmp2)
                settings2 = make_settings(root2)
                journal2 = Journal(settings2.db_path)
                journal2.ensure_schema()
                risk_engine2 = RiskEngine(settings2, journal2)
                previous_open_bundle = make_bundle(
                    timestamp_ms=300_000,
                    symbols=[make_symbol("BTC/USDT", 300_000, 98.0, atr_pct=0.0040, range_pct=0.0045, volume_ratio=1.10, higher_bias="long")],
                )
                record_run(journal2, settings2, bundle=previous_open_bundle, decision_action="buy", final_action="buy", symbol="BTC/USDT")
                close_bundle = make_bundle(
                    timestamp_ms=600_000,
                    symbols=[make_symbol("BTC/USDT", 600_000, 100.0, atr_pct=0.0040, range_pct=0.0050, volume_ratio=1.10, higher_bias="long")],
                    open_positions=[
                        PositionSnapshot(
                            symbol="BTC/USDT",
                            quantity=1.0,
                            mark_price=100.0,
                            market_value_quote=100.0,
                            side="long",
                            average_entry_price=98.0,
                            notional_quote=100.0,
                        )
                    ],
                    equity_quote=200.0,
                    free_quote=100.0,
                )
                close_verdict = risk_engine2.evaluate(make_decision("BTC/USDT", "close"), close_bundle)
                self.assertEqual(close_verdict.final_action, "hold")
                self.assertTrue(any(reason.startswith("min_hold_bars_active") for reason in close_verdict.reasons))

    def test_risk_engine_blocks_same_direction_reentry_after_forced_loss_close(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("SOL/USDT:USDT",),
                same_symbol_reentry_cooldown_bars=3,
                cooldown_bars_after_losses=3,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            previous_close_bundle = make_bundle(
                timestamp_ms=600_000,
                symbols=[make_symbol("SOL/USDT:USDT", 600_000, 100.0, atr_pct=0.0040, range_pct=0.0045, volume_ratio=1.20, higher_bias="short")],
                open_positions=[
                    PositionSnapshot(
                        symbol="SOL/USDT:USDT",
                        quantity=1.0,
                        mark_price=100.0,
                        market_value_quote=100.0,
                        side="short",
                        average_entry_price=99.0,
                        notional_quote=100.0,
                    )
                ],
            )
            record_run(
                journal,
                settings,
                bundle=previous_close_bundle,
                decision_action="hold",
                final_action="close",
                symbol="SOL/USDT:USDT",
                risk_reasons=["management_adverse_hold_to_close"],
            )

            reentry_symbol = make_symbol("SOL/USDT:USDT", 2_100_000, 99.3, atr_pct=0.0040, range_pct=0.0045, volume_ratio=1.20, higher_bias="short")
            reentry_symbol.indicators["return_1bar"] = -0.0015
            reentry_symbol.indicators["return_24bars"] = -0.0040
            reentry_symbol.indicators["sma_fast_ratio"] = -0.0012
            reentry_symbol.indicators["sma_slow_ratio"] = -0.0011
            reentry_bundle = make_bundle(
                timestamp_ms=2_100_000,
                symbols=[reentry_symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )

            reentry_verdict = risk_engine.evaluate(make_decision("SOL/USDT:USDT", "sell"), reentry_bundle)

            self.assertEqual(reentry_verdict.final_action, "hold")
            self.assertTrue(any(reason.startswith("loss_reentry_cooldown_active:") for reason in reentry_verdict.reasons))

    def test_risk_engine_expected_edge_is_market_driven_not_take_profit_capped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(root, min_expected_edge_pct=0.0012)
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            symbol = make_symbol("BTC/USDT", 600_000, 100.0, atr_pct=0.0022, range_pct=0.0020, volume_ratio=1.10, higher_bias="long")
            symbol.indicators["return_1bar"] = 0.0006
            symbol.indicators["return_24bars"] = 0.0012
            bundle = make_bundle(
                timestamp_ms=600_000,
                symbols=[symbol],
            )

            small_tp = make_decision("BTC/USDT", "buy", take_profit_pct=0.0010)
            wide_tp = make_decision("BTC/USDT", "buy", take_profit_pct=0.0500)

            small_tp_edge = risk_engine._expected_edge_pct(small_tp, symbol)
            wide_tp_edge = risk_engine._expected_edge_pct(wide_tp, symbol)

            self.assertAlmostEqual(small_tp_edge, wide_tp_edge)
            self.assertGreater(small_tp_edge, settings.min_expected_edge_pct)
            self.assertEqual(risk_engine.evaluate(small_tp, bundle).final_action, "buy")
            self.assertEqual(risk_engine.evaluate(wide_tp, bundle).final_action, "buy")

    def test_risk_engine_requires_directional_alignment_for_open_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
                min_expected_edge_pct=0.0025,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            weak_symbol = make_symbol("XRP/USDT:USDT", 600_000, 1.5, atr_pct=0.0040, range_pct=0.0040, volume_ratio=0.80, higher_bias="short")
            weak_symbol.indicators["return_24bars"] = -0.0005
            weak_symbol.indicators["sma_fast_ratio"] = -0.0002
            weak_symbol.indicators["sma_slow_ratio"] = -0.0001
            weak_symbol.indicators["return_1bar"] = 0.0002
            weak_symbol.indicators["volume_ratio_20"] = 0.50
            weak_bundle = make_bundle(
                timestamp_ms=600_000,
                symbols=[weak_symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )
            weak_verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "sell"), weak_bundle)
            self.assertEqual(weak_verdict.final_action, "hold")
            self.assertIn("open_signal_return_24bars_too_weak", weak_verdict.reasons)
            self.assertIn("open_signal_low_volume", weak_verdict.reasons)

            moderate_symbol = make_symbol("XRP/USDT:USDT", 750_000, 1.5, atr_pct=0.0040, range_pct=0.0040, volume_ratio=0.68, higher_bias="short")
            moderate_symbol.indicators["return_1bar"] = -0.0008
            moderate_symbol.indicators["return_24bars"] = -0.0008
            moderate_symbol.indicators["sma_fast_ratio"] = -0.0012
            moderate_symbol.indicators["sma_slow_ratio"] = -0.0011
            moderate_bundle = make_bundle(
                timestamp_ms=750_000,
                symbols=[moderate_symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )
            moderate_verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "sell"), moderate_bundle)
            self.assertEqual(moderate_verdict.final_action, "sell")

            strong_symbol = make_symbol("XRP/USDT:USDT", 900_000, 1.5, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="short")
            strong_symbol.indicators["return_24bars"] = -0.0030
            strong_symbol.indicators["sma_fast_ratio"] = -0.0020
            strong_symbol.indicators["sma_slow_ratio"] = -0.0030
            strong_bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[strong_symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )
            strong_verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "sell"), strong_bundle)
            self.assertEqual(strong_verdict.final_action, "sell")

            breakout_symbol = make_symbol("XRP/USDT:USDT", 1_200_000, 1.5, atr_pct=0.0026, range_pct=0.0020, volume_ratio=1.35, higher_bias="short")
            breakout_symbol.indicators["return_1bar"] = -0.0008
            breakout_symbol.indicators["return_24bars"] = 0.0050
            breakout_symbol.indicators["sma_fast_ratio"] = -0.0014
            breakout_symbol.indicators["sma_slow_ratio"] = 0.0007
            breakout_bundle = make_bundle(
                timestamp_ms=1_200_000,
                symbols=[breakout_symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )
            breakout_verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "sell"), breakout_bundle)
            self.assertEqual(breakout_verdict.final_action, "sell")

    def test_risk_engine_allows_higher_timeframe_long_reclaim_to_clear_edge_floor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
                min_expected_edge_pct=0.0015,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            reclaim_long = make_symbol("XRP/USDT:USDT", 900_000, 1.5029, atr_pct=0.00239, range_pct=0.00166, volume_ratio=0.99, higher_bias="long")
            reclaim_long.indicators["return_1bar"] = 0.00040
            reclaim_long.indicators["return_24bars"] = 0.00007
            reclaim_long.indicators["sma_fast_ratio"] = 0.00222
            reclaim_long.indicators["sma_slow_ratio"] = -0.00441
            reclaim_long.indicators["rsi_14"] = 53.4
            reclaim_long.higher_timeframe = {
                "timeframe": "1h",
                "trend_bias": "long",
                "return_12bars": 0.0478,
                "sma_fast_ratio": 0.0134,
                "sma_slow_ratio": 0.0301,
                "rsi_14": 68.9,
            }
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[reclaim_long],
                equity_quote=200.0,
                free_quote=200.0,
            )

            verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "buy"), bundle)

            self.assertEqual(verdict.final_action, "buy")
            self.assertFalse(any(reason.startswith("expected_edge_below_minimum") for reason in verdict.reasons))

    def test_risk_engine_allows_higher_timeframe_long_reversal_when_local_oversold_reclaims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            reversal_long = make_symbol("XRP/USDT:USDT", 900_000, 1.4865, atr_pct=0.00237, range_pct=0.00256, volume_ratio=1.42, higher_bias="long")
            reversal_long.indicators["return_1bar"] = 0.00128
            reversal_long.indicators["return_24bars"] = -0.00602
            reversal_long.indicators["sma_fast_ratio"] = -0.00238
            reversal_long.indicators["sma_slow_ratio"] = -0.00784
            reversal_long.indicators["rsi_14"] = 31.5
            reversal_long.higher_timeframe = {
                "timeframe": "1h",
                "trend_bias": "long",
                "return_12bars": 0.0368,
                "sma_fast_ratio": -0.0016,
                "sma_slow_ratio": 0.0176,
                "rsi_14": 65.3,
            }
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[reversal_long],
                equity_quote=200.0,
                free_quote=200.0,
            )

            verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "buy"), bundle)

            self.assertEqual(verdict.final_action, "buy")
            self.assertNotIn("open_signal_return_24bars_too_weak", verdict.reasons)
            self.assertNotIn("open_signal_sma_fast_conflict", verdict.reasons)
            self.assertNotIn("open_signal_sma_slow_conflict", verdict.reasons)

    def test_risk_engine_allows_higher_timeframe_long_fast_pullback_even_if_fast_sma_lags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            fast_pullback_long = make_symbol("XRP/USDT:USDT", 900_000, 1.4735, atr_pct=0.00433, range_pct=0.00441, volume_ratio=1.85, higher_bias="long")
            fast_pullback_long.indicators["return_1bar"] = -0.00217
            fast_pullback_long.indicators["return_24bars"] = 0.00416
            fast_pullback_long.indicators["sma_fast_ratio"] = -0.00220
            fast_pullback_long.indicators["sma_slow_ratio"] = 0.00554
            fast_pullback_long.indicators["rsi_14"] = 52.9
            fast_pullback_long.higher_timeframe = {
                "timeframe": "1h",
                "trend_bias": "long",
                "return_12bars": 0.0348,
                "sma_fast_ratio": 0.0238,
                "sma_slow_ratio": 0.0310,
                "rsi_14": 77.4,
            }
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[fast_pullback_long],
                equity_quote=200.0,
                free_quote=200.0,
            )

            verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "buy"), bundle)

            self.assertEqual(verdict.final_action, "buy")
            self.assertNotIn("open_signal_sma_fast_conflict", verdict.reasons)

    def test_risk_engine_blocks_terminal_short_extension_even_when_other_signals_align(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            stretched_short = make_symbol("XRP/USDT:USDT", 900_000, 1.50, atr_pct=0.0040, range_pct=0.0045, volume_ratio=0.95, higher_bias="short")
            stretched_short.indicators["return_1bar"] = -0.0012
            stretched_short.indicators["return_24bars"] = -0.0030
            stretched_short.indicators["rsi_14"] = 32.0
            stretched_short.indicators["sma_fast_ratio"] = -0.0015
            stretched_short.indicators["sma_slow_ratio"] = -0.0012
            stretched_short.recent_candles[-1].open = 1.511
            stretched_short.recent_candles[-1].high = 1.512
            stretched_short.recent_candles[-1].low = 1.499
            stretched_short.recent_candles[-1].close = 1.500
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[stretched_short],
                equity_quote=200.0,
                free_quote=200.0,
            )

            verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "sell"), bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertIn("fresh_entry_late_breakdown", verdict.reasons)

    def test_risk_engine_blocks_terminal_long_extension_even_when_other_signals_align(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            stretched_long = make_symbol("XRP/USDT:USDT", 900_000, 1.50, atr_pct=0.0040, range_pct=0.0045, volume_ratio=0.95, higher_bias="long")
            stretched_long.indicators["return_1bar"] = 0.0012
            stretched_long.indicators["return_24bars"] = 0.0030
            stretched_long.indicators["rsi_14"] = 68.0
            stretched_long.indicators["sma_fast_ratio"] = 0.0015
            stretched_long.indicators["sma_slow_ratio"] = 0.0012
            stretched_long.recent_candles[-1].open = 1.489
            stretched_long.recent_candles[-1].high = 1.501
            stretched_long.recent_candles[-1].low = 1.488
            stretched_long.recent_candles[-1].close = 1.500
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[stretched_long],
                equity_quote=200.0,
                free_quote=200.0,
            )

            verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "buy"), bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertIn("fresh_entry_late_breakout", verdict.reasons)

    def test_risk_engine_blocks_low_participation_long_extension_with_moderate_rsi(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("SOL/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            late_long = make_symbol("SOL/USDT:USDT", 900_000, 93.46, atr_pct=0.00325, range_pct=0.00182, volume_ratio=0.74, higher_bias="long")
            late_long.indicators["return_1bar"] = 0.0015
            late_long.indicators["return_24bars"] = 0.00376
            late_long.indicators["rsi_14"] = 59.2
            late_long.indicators["sma_fast_ratio"] = 0.00558
            late_long.indicators["sma_slow_ratio"] = 0.00834
            late_long.recent_candles[-1].open = 93.32
            late_long.recent_candles[-1].high = 93.48
            late_long.recent_candles[-1].low = 93.31
            late_long.recent_candles[-1].close = 93.46
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[late_long],
                equity_quote=200.0,
                free_quote=200.0,
            )

            verdict = risk_engine.evaluate(make_decision("SOL/USDT:USDT", "buy"), bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertIn("fresh_entry_late_breakout", verdict.reasons)

    def test_risk_engine_blocks_climactic_terminal_short_extension_even_when_volume_expands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("SOL/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            climactic_short = make_symbol("SOL/USDT:USDT", 900_000, 90.64, atr_pct=0.0018, range_pct=0.0044, volume_ratio=2.99, higher_bias="short")
            climactic_short.indicators["return_1bar"] = -0.0041
            climactic_short.indicators["return_24bars"] = -0.0060
            climactic_short.indicators["rsi_14"] = 30.0
            climactic_short.indicators["sma_fast_ratio"] = -0.0044
            climactic_short.indicators["sma_slow_ratio"] = -0.0052
            climactic_short.recent_candles[-1].open = 91.00
            climactic_short.recent_candles[-1].high = 91.03
            climactic_short.recent_candles[-1].low = 90.63
            climactic_short.recent_candles[-1].close = 90.64
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[climactic_short],
                equity_quote=200.0,
                free_quote=200.0,
            )

            verdict = risk_engine.evaluate(make_decision("SOL/USDT:USDT", "sell"), bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertIn("fresh_entry_late_breakdown", verdict.reasons)

    def test_risk_engine_blocks_climactic_terminal_long_extension_even_when_volume_expands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            climactic_long = make_symbol("XRP/USDT:USDT", 900_000, 1.4577, atr_pct=0.00178, range_pct=0.00466, volume_ratio=3.32, higher_bias="long")
            climactic_long.indicators["return_1bar"] = 0.00344
            climactic_long.indicators["return_24bars"] = 0.00462
            climactic_long.indicators["rsi_14"] = 39.2
            climactic_long.indicators["sma_fast_ratio"] = 0.00105
            climactic_long.indicators["sma_slow_ratio"] = 0.00347
            climactic_long.recent_candles[-1].open = 1.4528
            climactic_long.recent_candles[-1].high = 1.4586
            climactic_long.recent_candles[-1].low = 1.4518
            climactic_long.recent_candles[-1].close = 1.4577
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[climactic_long],
                equity_quote=200.0,
                free_quote=200.0,
            )

            verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "buy"), bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertIn("fresh_entry_late_breakout", verdict.reasons)

    def test_risk_engine_blocks_overextended_long_chase_even_without_close_at_extreme(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("SOL/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            stretched_long = make_symbol("SOL/USDT:USDT", 900_000, 91.31, atr_pct=0.00207, range_pct=0.00383, volume_ratio=2.40, higher_bias="long")
            stretched_long.indicators["return_1bar"] = 0.00187
            stretched_long.indicators["return_24bars"] = 0.00695
            stretched_long.indicators["rsi_14"] = 71.7
            stretched_long.indicators["sma_fast_ratio"] = 0.00176
            stretched_long.indicators["sma_slow_ratio"] = 0.00463
            stretched_long.recent_candles[-1].open = 91.13
            stretched_long.recent_candles[-1].high = 91.41
            stretched_long.recent_candles[-1].low = 91.06
            stretched_long.recent_candles[-1].close = 91.31
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[stretched_long],
                equity_quote=200.0,
                free_quote=200.0,
            )

            verdict = risk_engine.evaluate(make_decision("SOL/USDT:USDT", "buy"), bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertIn("fresh_entry_late_breakout", verdict.reasons)

    def test_risk_engine_keeps_pre_breakdown_short_available_despite_soft_low_volatility(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("SOL/USDT:USDT",),
                min_expected_edge_pct=0.0015,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            early_short = make_symbol("SOL/USDT:USDT", 900_000, 91.0, atr_pct=0.00165, range_pct=0.00121, volume_ratio=0.73, higher_bias="short")
            early_short.indicators["return_1bar"] = -0.00055
            early_short.indicators["return_24bars"] = -0.00197
            early_short.indicators["rsi_14"] = 46.9
            early_short.indicators["sma_fast_ratio"] = -0.00093
            early_short.indicators["sma_slow_ratio"] = -0.00142
            early_short.recent_candles[-1].open = 91.05
            early_short.recent_candles[-1].high = 91.07
            early_short.recent_candles[-1].low = 90.96
            early_short.recent_candles[-1].close = 91.0
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[early_short],
                equity_quote=200.0,
                free_quote=200.0,
            )

            verdict = risk_engine.evaluate(make_decision("SOL/USDT:USDT", "sell"), bundle)

            self.assertEqual(verdict.final_action, "sell")

    def test_risk_engine_keeps_clean_flat_bias_short_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("SOL/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            flat_bias_short = make_symbol("SOL/USDT:USDT", 900_000, 100.0, atr_pct=0.0040, range_pct=0.0045, volume_ratio=1.20, higher_bias="flat")
            flat_bias_short.indicators["return_1bar"] = -0.0010
            flat_bias_short.indicators["return_24bars"] = -0.0030
            flat_bias_short.indicators["rsi_14"] = 41.0
            flat_bias_short.indicators["sma_fast_ratio"] = -0.0015
            flat_bias_short.indicators["sma_slow_ratio"] = -0.0012
            flat_bias_short.recent_candles[-1].open = 100.55
            flat_bias_short.recent_candles[-1].high = 100.60
            flat_bias_short.recent_candles[-1].low = 99.95
            flat_bias_short.recent_candles[-1].close = 100.0
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[flat_bias_short],
                equity_quote=200.0,
                free_quote=200.0,
            )

            verdict = risk_engine.evaluate(make_decision("SOL/USDT:USDT", "sell"), bundle)

            self.assertEqual(verdict.final_action, "sell")

    def test_risk_engine_rejects_thin_flat_bias_short_when_extra_edge_buffer_is_not_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("SOL/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            flat_bias_short = make_symbol("SOL/USDT:USDT", 900_000, 90.62, atr_pct=0.00175, range_pct=0.00353, volume_ratio=1.64, higher_bias="flat")
            flat_bias_short.indicators["return_1bar"] = -0.002312
            flat_bias_short.indicators["return_24bars"] = -0.004832
            flat_bias_short.indicators["rsi_14"] = 38.1
            flat_bias_short.indicators["sma_fast_ratio"] = -0.00345
            flat_bias_short.indicators["sma_slow_ratio"] = -0.00460
            flat_bias_short.recent_candles[-1].open = 90.82
            flat_bias_short.recent_candles[-1].high = 90.84
            flat_bias_short.recent_candles[-1].low = 90.52
            flat_bias_short.recent_candles[-1].close = 90.62
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[flat_bias_short],
                equity_quote=200.0,
                free_quote=200.0,
            )

            verdict = risk_engine.evaluate(make_decision("SOL/USDT:USDT", "sell"), bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertTrue(any(reason.startswith("expected_edge_below_minimum") for reason in verdict.reasons))

    def test_risk_engine_management_hold_can_escalate_to_close_when_position_turns_adverse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            adverse_short = make_symbol("XRP/USDT:USDT", 900_000, 1.5, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="long")
            adverse_short.indicators["return_1bar"] = 0.0020
            adverse_short.indicators["return_24bars"] = 0.0030
            adverse_short.indicators["sma_fast_ratio"] = 0.0015
            adverse_short.indicators["sma_slow_ratio"] = 0.0012
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[adverse_short],
                open_positions=[
                    PositionSnapshot(
                        symbol="XRP/USDT:USDT",
                        quantity=10.0,
                        mark_price=1.5,
                        market_value_quote=15.0,
                        side="short",
                        average_entry_price=1.52,
                        notional_quote=15.0,
                    )
                ],
                equity_quote=200.0,
                free_quote=190.0,
            )

            verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "hold"), bundle)
            self.assertEqual(verdict.final_action, "close")
            self.assertIn("management_adverse_hold_to_close", verdict.reasons)

    def test_risk_engine_management_hold_preserves_aligned_higher_timeframe_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            adverse_short = make_symbol("XRP/USDT:USDT", 900_000, 1.5, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="short")
            adverse_short.indicators["return_1bar"] = 0.0020
            adverse_short.indicators["return_24bars"] = 0.0030
            adverse_short.indicators["sma_fast_ratio"] = 0.0015
            adverse_short.indicators["sma_slow_ratio"] = 0.0012
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[adverse_short],
                open_positions=[
                    PositionSnapshot(
                        symbol="XRP/USDT:USDT",
                        quantity=10.0,
                        mark_price=1.5,
                        market_value_quote=15.0,
                        side="short",
                        average_entry_price=1.52,
                        notional_quote=15.0,
                    )
                ],
                equity_quote=200.0,
                free_quote=190.0,
            )

            verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "hold"), bundle)
            self.assertEqual(verdict.final_action, "hold")
            self.assertNotIn("management_adverse_hold_to_close", verdict.reasons)

    def test_risk_engine_management_close_can_be_rejected_when_position_still_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            supportive_short = make_symbol("XRP/USDT:USDT", 900_000, 1.5, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="short")
            supportive_short.indicators["return_1bar"] = -0.0015
            supportive_short.indicators["return_24bars"] = -0.0030
            supportive_short.indicators["sma_fast_ratio"] = -0.0015
            supportive_short.indicators["sma_slow_ratio"] = -0.0012
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[supportive_short],
                open_positions=[
                    PositionSnapshot(
                        symbol="XRP/USDT:USDT",
                        quantity=10.0,
                        mark_price=1.5,
                        market_value_quote=15.0,
                        side="short",
                        average_entry_price=1.52,
                        notional_quote=15.0,
                    )
                ],
                equity_quote=200.0,
                free_quote=190.0,
            )

            verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "close"), bundle)
            self.assertEqual(verdict.final_action, "hold")
            self.assertIn("management_close_rejected_position_still_supported", verdict.reasons)

    def test_risk_engine_enforces_min_open_size_and_take_profit_floor_for_futures_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            short_symbol = make_symbol("XRP/USDT:USDT", 900_000, 1.5, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="short")
            short_symbol.indicators["return_1bar"] = -0.0020
            short_symbol.indicators["return_24bars"] = -0.0030
            short_symbol.indicators["sma_fast_ratio"] = -0.0015
            short_symbol.indicators["sma_slow_ratio"] = -0.0012
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[short_symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )
            decision = ValidatedDecision(
                decision=AIDecision(
                    timestamp=utc_now().isoformat(),
                    symbol="XRP/USDT:USDT",
                    action="sell",
                    size_pct=0.04,
                    take_profit_pct=0.007,
                    stop_loss_pct=0.0035,
                    ttl_minutes=15,
                    confidence=0.70,
                    reason="test",
                    prompt_version="v1",
                ),
                valid=True,
                errors=[],
                raw_payload={"symbol": "XRP/USDT:USDT", "action": "sell"},
            )

            verdict = risk_engine.evaluate(decision, bundle)

            self.assertEqual(verdict.final_action, "sell")
            self.assertGreaterEqual(verdict.final_size_pct, settings.min_open_size_pct)
            self.assertEqual(verdict.take_profit_pct, settings.min_take_profit_pct)

    def test_risk_engine_sizes_futures_entries_from_stop_loss_distance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
                max_entry_size_pct=0.30,
                max_risk_per_trade_pct=0.01,
                min_open_size_pct=0.10,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            short_symbol = make_symbol("XRP/USDT:USDT", 900_000, 1.5, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="short")
            short_symbol.indicators["return_1bar"] = -0.0020
            short_symbol.indicators["return_24bars"] = -0.0030
            short_symbol.indicators["sma_fast_ratio"] = -0.0015
            short_symbol.indicators["sma_slow_ratio"] = -0.0012
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[short_symbol],
                equity_quote=1_000.0,
                free_quote=1_000.0,
            )
            decision = ValidatedDecision(
                decision=AIDecision(
                    timestamp=utc_now().isoformat(),
                    symbol="XRP/USDT:USDT",
                    action="sell",
                    size_pct=0.30,
                    take_profit_pct=0.04,
                    stop_loss_pct=0.03,
                    ttl_minutes=15,
                    confidence=0.80,
                    reason="test",
                    prompt_version="v1",
                ),
                valid=True,
                errors=[],
                raw_payload={"symbol": "XRP/USDT:USDT", "action": "sell"},
            )

            verdict = risk_engine.evaluate(decision, bundle)

            expected_cap = settings.max_risk_per_trade_pct / (
                settings.contract_leverage
                * (settings.max_effective_stop_loss_pct + (settings.estimated_fee_pct + settings.estimated_slippage_pct) * 2.0)
            )
            self.assertEqual(verdict.final_action, "sell")
            self.assertAlmostEqual(verdict.final_size_pct, expected_cap, places=6)
            self.assertTrue(any(reason.startswith("risk_sized_down:") for reason in verdict.reasons))

    def test_risk_engine_rejects_exchange_minimum_when_it_breaks_risk_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
                max_entry_size_pct=0.30,
                max_risk_per_trade_pct=0.01,
                min_open_size_pct=0.10,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            short_symbol = make_symbol("XRP/USDT:USDT", 900_000, 1.5, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="short")
            short_symbol.indicators["return_1bar"] = -0.0020
            short_symbol.indicators["return_24bars"] = -0.0030
            short_symbol.indicators["sma_fast_ratio"] = -0.0015
            short_symbol.indicators["sma_slow_ratio"] = -0.0012
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[short_symbol],
                equity_quote=100.0,
                free_quote=100.0,
            )
            decision = ValidatedDecision(
                decision=AIDecision(
                    timestamp=utc_now().isoformat(),
                    symbol="XRP/USDT:USDT",
                    action="sell",
                    size_pct=0.30,
                    take_profit_pct=0.04,
                    stop_loss_pct=0.03,
                    ttl_minutes=15,
                    confidence=0.80,
                    reason="test",
                    prompt_version="v1",
                ),
                valid=True,
                errors=[],
                raw_payload={"symbol": "XRP/USDT:USDT", "action": "sell"},
            )

            verdict = risk_engine.evaluate(decision, bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertFalse(verdict.approved)
            self.assertIn("risk_budget_below_exchange_minimum", verdict.reasons)

    def test_risk_engine_trailing_profit_retrace_forces_close_after_meaningful_giveback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            open_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[make_symbol("XRP/USDT:USDT", 300_000, 1.50, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="short")],
                equity_quote=200.0,
                free_quote=200.0,
            )
            record_run(journal, settings, bundle=open_bundle, decision_action="sell", final_action="sell", symbol="XRP/USDT:USDT", confidence=0.90)

            supportive_symbol = make_symbol("XRP/USDT:USDT", 900_000, 1.477, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="short")
            supportive_symbol.indicators["return_1bar"] = -0.0015
            supportive_symbol.indicators["return_24bars"] = -0.0030
            supportive_symbol.indicators["sma_fast_ratio"] = -0.0015
            supportive_symbol.indicators["sma_slow_ratio"] = -0.0012
            supportive_bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[supportive_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="XRP/USDT:USDT",
                        quantity=10.0,
                        mark_price=1.477,
                        market_value_quote=14.77,
                        side="short",
                        average_entry_price=1.50,
                        notional_quote=15.0,
                    )
                ],
                equity_quote=200.0,
                free_quote=190.0,
            )

            recent_actions = journal.get_recent_signal_actions(limit=10, symbol="XRP/USDT:USDT")
            last_open = next(item for item in recent_actions if item["final_action"] == "sell")
            peak_key = risk_engine._trailing_profit_peak_key("XRP/USDT:USDT", int(last_open["run_id"]))
            journal.set_runtime_state(peak_key, 0.015333333333333309)

            retraced_symbol = make_symbol("XRP/USDT:USDT", 1_200_000, 1.489, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="short")
            retraced_symbol.indicators["return_1bar"] = -0.0002
            retraced_symbol.indicators["return_24bars"] = -0.0010
            retraced_symbol.indicators["sma_fast_ratio"] = -0.0002
            retraced_symbol.indicators["sma_slow_ratio"] = -0.0004
            retraced_bundle = make_bundle(
                timestamp_ms=1_200_000,
                symbols=[retraced_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="XRP/USDT:USDT",
                        quantity=10.0,
                        mark_price=1.489,
                        market_value_quote=14.89,
                        side="short",
                        average_entry_price=1.50,
                        notional_quote=15.0,
                    )
                ],
                equity_quote=200.0,
                free_quote=190.0,
            )

            second_verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "hold"), retraced_bundle)
            self.assertEqual(second_verdict.final_action, "close")
            self.assertTrue(any(reason.startswith("management_trailing_profit_retrace:") for reason in second_verdict.reasons))

    def test_risk_engine_partial_take_profit_closes_fraction_and_arms_breakeven_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            open_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[make_symbol("XRP/USDT:USDT", 300_000, 1.50, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="long")],
                equity_quote=200.0,
                free_quote=200.0,
            )
            record_run(journal, settings, bundle=open_bundle, decision_action="buy", final_action="buy", symbol="XRP/USDT:USDT", confidence=0.90)

            profitable_symbol = make_symbol("XRP/USDT:USDT", 900_000, 1.5195, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="long")
            profitable_symbol.indicators["return_1bar"] = 0.0010
            profitable_symbol.indicators["return_24bars"] = 0.0040
            profitable_symbol.indicators["sma_fast_ratio"] = 0.0015
            profitable_symbol.indicators["sma_slow_ratio"] = 0.0012
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[profitable_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="XRP/USDT:USDT",
                        quantity=16.6,
                        mark_price=1.5195,
                        market_value_quote=25.2237,
                        side="long",
                        average_entry_price=1.50,
                        notional_quote=25.2237,
                    )
                ],
                equity_quote=202.0,
                free_quote=193.0,
            )

            verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "hold"), bundle)
            recent_actions = journal.get_recent_signal_actions(limit=10, symbol="XRP/USDT:USDT")
            last_open = next(item for item in recent_actions if item["final_action"] == "buy")

            self.assertEqual(verdict.final_action, "close")
            self.assertAlmostEqual(verdict.close_fraction, settings.partial_take_profit_fraction)
            self.assertEqual(verdict.management_open_run_id, last_open["run_id"])
            self.assertAlmostEqual(
                verdict.remaining_stop_price or 0.0,
                1.50 * (1.0 + max(settings.breakeven_stop_buffer_pct, 0.013 - settings.trailing_profit_retrace_pct)),
            )
            self.assertTrue(any(reason.startswith("partial_take_profit:") for reason in verdict.reasons))

    def test_risk_engine_full_take_profit_still_applies_when_partial_is_too_small(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            open_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[make_symbol("XRP/USDT:USDT", 300_000, 1.50, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="long")],
                equity_quote=200.0,
                free_quote=200.0,
            )
            record_run(journal, settings, bundle=open_bundle, decision_action="buy", final_action="buy", symbol="XRP/USDT:USDT", confidence=0.90)

            profitable_symbol = make_symbol("XRP/USDT:USDT", 900_000, 1.531, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="long")
            profitable_symbol.exchange_min_amount = 10.0
            profitable_symbol.indicators["return_1bar"] = 0.0010
            profitable_symbol.indicators["return_24bars"] = 0.0040
            profitable_symbol.indicators["sma_fast_ratio"] = 0.0015
            profitable_symbol.indicators["sma_slow_ratio"] = 0.0012
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[profitable_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="XRP/USDT:USDT",
                        quantity=16.6,
                        mark_price=1.531,
                        market_value_quote=25.4146,
                        side="long",
                        average_entry_price=1.50,
                        notional_quote=25.4146,
                    )
                ],
                equity_quote=202.0,
                free_quote=193.0,
            )

            verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "hold"), bundle)

            self.assertEqual(verdict.final_action, "close")
            self.assertAlmostEqual(verdict.close_fraction, 1.0)
            self.assertIn("partial_take_profit_skipped_below_min_amount", verdict.reasons)
            self.assertTrue(any(reason.startswith("management_take_profit_hit:") for reason in verdict.reasons))

    def test_risk_engine_second_partial_uses_higher_trigger_and_does_not_full_close_early(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
                partial_take_profit_max_times=2,
                partial_take_profit_trigger_pct=0.012,
                partial_take_profit_step_pct=0.012,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            open_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[make_symbol("XRP/USDT:USDT", 300_000, 1.50, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="long")],
                equity_quote=200.0,
                free_quote=200.0,
            )
            record_run(journal, settings, bundle=open_bundle, decision_action="buy", final_action="buy", symbol="XRP/USDT:USDT", confidence=0.90)
            recent_actions = journal.get_recent_signal_actions(limit=10, symbol="XRP/USDT:USDT")
            last_open = next(item for item in recent_actions if item["final_action"] == "buy")
            done_key = risk_engine._partial_take_profit_done_key("XRP/USDT:USDT", int(last_open["run_id"]))
            breakeven_key = risk_engine._breakeven_stop_armed_key("XRP/USDT:USDT", int(last_open["run_id"]))
            peak_key = risk_engine._trailing_profit_peak_key("XRP/USDT:USDT", int(last_open["run_id"]))
            journal.set_runtime_state(done_key, {"count": 1})
            journal.set_runtime_state(breakeven_key, {"armed": True})
            journal.set_runtime_state(peak_key, 0.021)

            mid_symbol = make_symbol("XRP/USDT:USDT", 900_000, 1.5315, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="long")
            mid_symbol.indicators["return_1bar"] = 0.0008
            mid_symbol.indicators["return_24bars"] = 0.0040
            mid_symbol.indicators["sma_fast_ratio"] = 0.0012
            mid_symbol.indicators["sma_slow_ratio"] = 0.0011
            mid_bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[mid_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="XRP/USDT:USDT",
                        quantity=8.3,
                        mark_price=1.5315,
                        market_value_quote=12.71145,
                        side="long",
                        average_entry_price=1.50,
                        notional_quote=12.71145,
                    )
                ],
                equity_quote=202.0,
                free_quote=193.0,
            )

            mid_verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "hold"), mid_bundle)

            self.assertEqual(mid_verdict.final_action, "hold")
            self.assertAlmostEqual(mid_verdict.close_fraction, 1.0)
            self.assertTrue(mid_verdict.protective_refresh_only)
            self.assertFalse(any(reason.startswith("management_take_profit_hit:") for reason in mid_verdict.reasons))

            high_symbol = make_symbol("XRP/USDT:USDT", 1_200_000, 1.5375, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="long")
            high_symbol.indicators["return_1bar"] = 0.0010
            high_symbol.indicators["return_24bars"] = 0.0045
            high_symbol.indicators["sma_fast_ratio"] = 0.0013
            high_symbol.indicators["sma_slow_ratio"] = 0.0012
            high_bundle = make_bundle(
                timestamp_ms=1_200_000,
                symbols=[high_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="XRP/USDT:USDT",
                        quantity=8.3,
                        mark_price=1.5375,
                        market_value_quote=12.76125,
                        side="long",
                        average_entry_price=1.50,
                        notional_quote=12.76125,
                    )
                ],
                equity_quote=202.0,
                free_quote=193.0,
            )

            high_verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "hold"), high_bundle)

            self.assertEqual(high_verdict.final_action, "close")
            self.assertAlmostEqual(high_verdict.close_fraction, settings.partial_take_profit_fraction)
            self.assertTrue(any(reason.startswith("partial_take_profit:") and "|count=2" in reason for reason in high_verdict.reasons))
            self.assertIsNone(high_verdict.remaining_take_profit_price)

    def test_executor_partial_live_futures_close_replaces_remaining_protective_orders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                mode="live",
                market_type="future",
                symbols=("XRP/USDT:USDT",),
                exchange_id="binance",
                binance_api_key="k",
                binance_api_secret="s",
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            exchange = FakeTradeExchange(
                open_orders=[
                    {
                        "id": "tp-1",
                        "symbol": "XRP/USDT:USDT",
                        "type": "TAKE_PROFIT_MARKET",
                        "clientOrderId": "qount-tp-123",
                        "info": {"clientOrderId": "qount-tp-123"},
                    },
                    {
                        "id": "sl-1",
                        "symbol": "XRP/USDT:USDT",
                        "type": "STOP_MARKET",
                        "clientOrderId": "qount-sl-456",
                        "info": {"clientOrderId": "qount-sl-456"},
                    },
                ]
            )
            executor = Executor(settings, journal, exchange_pool=FakeTradeExchangePool(exchange))
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[make_symbol("XRP/USDT:USDT", 900_000, 1.52, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="long")],
                open_positions=[
                    PositionSnapshot(
                        symbol="XRP/USDT:USDT",
                        quantity=16.6,
                        mark_price=1.52,
                        market_value_quote=25.232,
                        side="long",
                        average_entry_price=1.50,
                        notional_quote=25.232,
                    )
                ],
                equity_quote=202.0,
                free_quote=193.0,
            )
            verdict = RiskVerdict(
                status="modified",
                final_action="close",
                symbol="XRP/USDT:USDT",
                final_size_pct=0.0,
                take_profit_pct=0.0,
                stop_loss_pct=0.0,
                ttl_minutes=0,
                reasons=["partial_take_profit:0.013000>=0.012000|fraction=0.5000"],
                confidence=0.80,
                approved=True,
                close_fraction=0.5,
                management_open_run_id=123,
                remaining_take_profit_price=1.53,
                remaining_stop_price=1.5018,
            )

            result = executor.execute(verdict, bundle)

            self.assertEqual(result.action, "close")
            self.assertEqual(result.quantity, 8.3)
            self.assertTrue(result.raw["partial_close"])
            self.assertEqual(result.raw["remaining_quantity"], 8.3)
            self.assertEqual(sorted(order_id for order_id, _ in exchange.cancelled_orders), ["sl-1", "tp-1"])
            self.assertEqual(len(exchange.created_orders), 3)
            self.assertEqual(exchange.created_orders[0]["type"], "market")
            self.assertEqual(exchange.created_orders[1]["type"], "TAKE_PROFIT_MARKET")
            self.assertEqual(exchange.created_orders[2]["type"], "STOP_MARKET")
            self.assertEqual(exchange.created_orders[1]["amount"], 8.3)
            self.assertEqual(exchange.created_orders[2]["amount"], 8.3)
            self.assertEqual(result.raw["remaining_protective_orders"][1]["trigger_price"], 1.5018)

    def test_executor_rejects_partial_close_before_cancel_when_remaining_quantity_is_too_small(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                mode="live",
                market_type="future",
                symbols=("XRP/USDT:USDT",),
                exchange_id="binance",
                binance_api_key="k",
                binance_api_secret="s",
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            exchange = FakeTradeExchange(
                open_orders=[
                    {
                        "id": "tp-1",
                        "symbol": "XRP/USDT:USDT",
                        "type": "TAKE_PROFIT_MARKET",
                        "clientOrderId": "qount-tp-123",
                        "info": {"clientOrderId": "qount-tp-123"},
                    }
                ]
            )
            executor = Executor(settings, journal, exchange_pool=FakeTradeExchangePool(exchange))
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[make_symbol("XRP/USDT:USDT", 900_000, 1.52, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="long")],
                open_positions=[
                    PositionSnapshot(
                        symbol="XRP/USDT:USDT",
                        quantity=0.15,
                        mark_price=1.52,
                        market_value_quote=0.228,
                        side="long",
                        average_entry_price=1.50,
                        notional_quote=0.228,
                    )
                ],
                equity_quote=202.0,
                free_quote=193.0,
            )
            verdict = RiskVerdict(
                status="modified",
                final_action="close",
                symbol="XRP/USDT:USDT",
                final_size_pct=0.0,
                take_profit_pct=0.0,
                stop_loss_pct=0.0,
                ttl_minutes=0,
                reasons=["partial_take_profit:0.013000>=0.012000|fraction=0.5000"],
                confidence=0.80,
                approved=True,
                close_fraction=0.5,
                management_open_run_id=123,
                remaining_take_profit_price=1.53,
                remaining_stop_price=1.5018,
            )

            result = executor.execute(verdict, bundle)

            self.assertEqual(result.status, "live_rejected")
            self.assertEqual(result.raw["reason"], "partial_remaining_below_market_min_amount")
            self.assertEqual(exchange.cancelled_orders, [])
            self.assertEqual(exchange.created_orders, [])

    def test_orchestrator_records_partial_take_profit_state_after_successful_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                mode="live",
                market_type="future",
                symbols=("XRP/USDT:USDT",),
            )
            orchestrator = Orchestrator(settings)
            verdict = RiskVerdict(
                status="modified",
                final_action="close",
                symbol="XRP/USDT:USDT",
                final_size_pct=0.0,
                take_profit_pct=0.0,
                stop_loss_pct=0.0,
                ttl_minutes=0,
                reasons=["partial_take_profit:0.013000>=0.012000|fraction=0.5000"],
                confidence=0.80,
                approved=True,
                close_fraction=0.5,
                management_open_run_id=123,
                remaining_take_profit_price=1.53,
                remaining_stop_price=1.5018,
            )
            result = ExecutionResult(
                status="closed",
                mode="live",
                symbol="XRP/USDT:USDT",
                action="close",
                side="sell",
                quantity=8.3,
                notional_quote=12.616,
                pnl_quote=None,
                external_order_id="1",
                raw={
                    "partial_close": True,
                    "remaining_quantity": 8.3,
                    "emergency_flatten": None,
                },
            )

            orchestrator._record_successful_position_management(verdict, result)

            done_key = orchestrator.risk_engine._partial_take_profit_done_key("XRP/USDT:USDT", 123)
            breakeven_key = orchestrator.risk_engine._breakeven_stop_armed_key("XRP/USDT:USDT", 123)
            self.assertEqual(orchestrator.journal.get_runtime_state(done_key, {})["count"], 1)
            self.assertTrue(orchestrator.journal.get_runtime_state(breakeven_key, {})["armed"])

    def test_risk_engine_hold_can_request_trailing_protective_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            open_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[make_symbol("XRP/USDT:USDT", 300_000, 1.50, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="long")],
                equity_quote=200.0,
                free_quote=200.0,
            )
            record_run(journal, settings, bundle=open_bundle, decision_action="buy", final_action="buy", symbol="XRP/USDT:USDT", confidence=0.90)
            recent_actions = journal.get_recent_signal_actions(limit=10, symbol="XRP/USDT:USDT")
            last_open = next(item for item in recent_actions if item["final_action"] == "buy")
            done_key = risk_engine._partial_take_profit_done_key("XRP/USDT:USDT", int(last_open["run_id"]))
            breakeven_key = risk_engine._breakeven_stop_armed_key("XRP/USDT:USDT", int(last_open["run_id"]))
            peak_key = risk_engine._trailing_profit_peak_key("XRP/USDT:USDT", int(last_open["run_id"]))
            journal.set_runtime_state(done_key, {"count": 1})
            journal.set_runtime_state(breakeven_key, {"armed": True})
            journal.set_runtime_state(peak_key, 0.018)

            managed_symbol = make_symbol("XRP/USDT:USDT", 900_000, 1.5225, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="long")
            managed_symbol.indicators["return_1bar"] = 0.0005
            managed_symbol.indicators["return_24bars"] = 0.0040
            managed_symbol.indicators["sma_fast_ratio"] = 0.0010
            managed_symbol.indicators["sma_slow_ratio"] = 0.0012
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[managed_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="XRP/USDT:USDT",
                        quantity=8.3,
                        mark_price=1.5225,
                        market_value_quote=12.63675,
                        side="long",
                        average_entry_price=1.50,
                        notional_quote=12.63675,
                    )
                ],
                equity_quote=202.0,
                free_quote=193.0,
            )

            verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "hold"), bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertTrue(verdict.protective_refresh_only)
            self.assertEqual(verdict.protective_refresh_reason, "trailing_stop_refresh")
            self.assertAlmostEqual(verdict.remaining_stop_price or 0.0, 1.50 * (1.0 + (0.018 - settings.trailing_profit_retrace_pct)))
            self.assertEqual(verdict.status, "modified")

    def test_executor_hold_refreshes_live_protective_orders_when_targets_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                mode="live",
                market_type="future",
                symbols=("XRP/USDT:USDT",),
                exchange_id="binance",
                binance_api_key="k",
                binance_api_secret="s",
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            exchange = FakeTradeExchange(
                open_orders=[
                    {
                        "id": "tp-1",
                        "symbol": "XRP/USDT:USDT",
                        "type": "TAKE_PROFIT_MARKET",
                        "side": "sell",
                        "amount": 8.3,
                        "clientOrderId": "qount-tp-123",
                        "info": {"clientOrderId": "qount-tp-123", "stopPrice": "1.5300"},
                    },
                    {
                        "id": "sl-1",
                        "symbol": "XRP/USDT:USDT",
                        "type": "STOP_MARKET",
                        "side": "sell",
                        "amount": 8.3,
                        "clientOrderId": "qount-sl-456",
                        "info": {"clientOrderId": "qount-sl-456", "stopPrice": "1.5018"},
                    },
                ]
            )
            executor = Executor(settings, journal, exchange_pool=FakeTradeExchangePool(exchange))
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[make_symbol("XRP/USDT:USDT", 900_000, 1.5225, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="long")],
                open_positions=[
                    PositionSnapshot(
                        symbol="XRP/USDT:USDT",
                        quantity=8.3,
                        mark_price=1.5225,
                        market_value_quote=12.63675,
                        side="long",
                        average_entry_price=1.50,
                        notional_quote=12.63675,
                    )
                ],
                equity_quote=202.0,
                free_quote=193.0,
            )
            verdict = RiskVerdict(
                status="modified",
                final_action="hold",
                symbol="XRP/USDT:USDT",
                final_size_pct=0.0,
                take_profit_pct=0.0,
                stop_loss_pct=0.0,
                ttl_minutes=0,
                reasons=["trailing_stop_refresh"],
                confidence=0.80,
                approved=True,
                protective_refresh_only=True,
                protective_refresh_reason="trailing_stop_refresh",
                management_open_run_id=123,
                remaining_take_profit_price=1.53,
                remaining_stop_price=1.5195,
            )

            result = executor.execute(verdict, bundle)

            self.assertEqual(result.status, "protective_refreshed")
            self.assertEqual(result.action, "hold")
            self.assertEqual(sorted(order_id for order_id, _ in exchange.cancelled_orders), ["sl-1", "tp-1"])
            self.assertEqual(len(exchange.created_orders), 2)
            self.assertEqual(exchange.created_orders[0]["type"], "TAKE_PROFIT_MARKET")
            self.assertEqual(exchange.created_orders[1]["type"], "STOP_MARKET")
            self.assertEqual(result.raw["replacement_orders"][1]["trigger_price"], 1.5195)

    def test_executor_hold_skips_protective_refresh_when_orders_are_current(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                mode="live",
                market_type="future",
                symbols=("XRP/USDT:USDT",),
                exchange_id="binance",
                binance_api_key="k",
                binance_api_secret="s",
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            exchange = FakeTradeExchange(
                open_orders=[
                    {
                        "id": "tp-1",
                        "symbol": "XRP/USDT:USDT",
                        "type": "TAKE_PROFIT_MARKET",
                        "side": "sell",
                        "amount": 8.3,
                        "clientOrderId": "qount-tp-123",
                        "info": {"clientOrderId": "qount-tp-123", "stopPrice": "1.5300"},
                    },
                    {
                        "id": "sl-1",
                        "symbol": "XRP/USDT:USDT",
                        "type": "STOP_MARKET",
                        "side": "sell",
                        "amount": 8.3,
                        "clientOrderId": "qount-sl-456",
                        "info": {"clientOrderId": "qount-sl-456", "stopPrice": "1.5195"},
                    },
                ]
            )
            executor = Executor(settings, journal, exchange_pool=FakeTradeExchangePool(exchange))
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[make_symbol("XRP/USDT:USDT", 900_000, 1.5225, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="long")],
                open_positions=[
                    PositionSnapshot(
                        symbol="XRP/USDT:USDT",
                        quantity=8.3,
                        mark_price=1.5225,
                        market_value_quote=12.63675,
                        side="long",
                        average_entry_price=1.50,
                        notional_quote=12.63675,
                    )
                ],
                equity_quote=202.0,
                free_quote=193.0,
            )
            verdict = RiskVerdict(
                status="modified",
                final_action="hold",
                symbol="XRP/USDT:USDT",
                final_size_pct=0.0,
                take_profit_pct=0.0,
                stop_loss_pct=0.0,
                ttl_minutes=0,
                reasons=["trailing_stop_refresh"],
                confidence=0.80,
                approved=True,
                protective_refresh_only=True,
                protective_refresh_reason="trailing_stop_refresh",
                management_open_run_id=123,
                remaining_take_profit_price=1.53,
                remaining_stop_price=1.5195,
            )

            result = executor.execute(verdict, bundle)

            self.assertEqual(result.status, "noop")
            self.assertEqual(result.raw["reason"], "protective_refresh_already_current")
            self.assertEqual(exchange.cancelled_orders, [])
            self.assertEqual(exchange.created_orders, [])

    def test_executor_hold_recognizes_current_conditional_protection_without_refreshing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                mode="live",
                market_type="future",
                symbols=("XRP/USDT:USDT",),
                exchange_id="binance",
                binance_api_key="k",
                binance_api_secret="s",
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            exchange = FakeTradeExchange(
                conditional_open_orders=[
                    {
                        "id": "tp-algo-1",
                        "symbol": "XRP/USDT:USDT",
                        "type": "market",
                        "side": "sell",
                        "amount": 8.3,
                        "clientOrderId": "qount-tp-123",
                        "triggerPrice": 1.53,
                        "stopPrice": 1.53,
                        "info": {
                            "clientAlgoId": "qount-tp-123",
                            "orderType": "TAKE_PROFIT_MARKET",
                            "stopPrice": "1.5300",
                            "triggerPrice": "1.5300",
                        },
                    },
                    {
                        "id": "sl-algo-1",
                        "symbol": "XRP/USDT:USDT",
                        "type": "market",
                        "side": "sell",
                        "amount": 8.3,
                        "clientOrderId": "qount-sl-456",
                        "triggerPrice": 1.5195,
                        "stopPrice": 1.5195,
                        "info": {
                            "clientAlgoId": "qount-sl-456",
                            "orderType": "STOP_MARKET",
                            "stopPrice": "1.5195",
                            "triggerPrice": "1.5195",
                        },
                    },
                ]
            )
            executor = Executor(settings, journal, exchange_pool=FakeTradeExchangePool(exchange))
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[make_symbol("XRP/USDT:USDT", 900_000, 1.5225, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="long")],
                open_positions=[
                    PositionSnapshot(
                        symbol="XRP/USDT:USDT",
                        quantity=8.3,
                        mark_price=1.5225,
                        market_value_quote=12.63675,
                        side="long",
                        average_entry_price=1.50,
                        notional_quote=12.63675,
                    )
                ],
                equity_quote=202.0,
                free_quote=193.0,
            )
            verdict = RiskVerdict(
                status="modified",
                final_action="hold",
                symbol="XRP/USDT:USDT",
                final_size_pct=0.0,
                take_profit_pct=0.0,
                stop_loss_pct=0.0,
                ttl_minutes=0,
                reasons=["trailing_stop_refresh"],
                confidence=0.80,
                approved=True,
                protective_refresh_only=True,
                protective_refresh_reason="trailing_stop_refresh",
                management_open_run_id=123,
                remaining_take_profit_price=1.53,
                remaining_stop_price=1.5195,
            )

            result = executor.execute(verdict, bundle)

            self.assertEqual(result.status, "noop")
            self.assertEqual(result.raw["reason"], "protective_refresh_already_current")
            self.assertEqual(exchange.cancelled_orders, [])
            self.assertEqual(exchange.created_orders, [])

    def test_executor_places_reduce_only_protective_orders_for_live_futures_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                mode="live",
                market_type="future",
                symbols=("XRP/USDT:USDT",),
                exchange_id="binance",
                binance_api_key="k",
                binance_api_secret="s",
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            exchange = FakeTradeExchange(average_price=1.4495)
            executor = Executor(settings, journal, exchange_pool=FakeTradeExchangePool(exchange))
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[make_symbol("XRP/USDT:USDT", 900_000, 1.4495, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="short")],
                equity_quote=200.0,
                free_quote=100.0,
            )

            verdict = RiskVerdict(
                status="approved",
                final_action="sell",
                symbol="XRP/USDT:USDT",
                final_size_pct=0.20,
                take_profit_pct=0.007,
                stop_loss_pct=0.0035,
                ttl_minutes=15,
                reasons=["ok"],
                confidence=0.66,
                approved=True,
            )

            result = executor.execute(verdict, bundle)

            self.assertEqual(result.action, "sell")
            self.assertEqual(len(exchange.created_orders), 3)
            self.assertEqual(exchange.created_orders[0]["type"], "market")
            self.assertEqual(exchange.created_orders[1]["type"], "TAKE_PROFIT_MARKET")
            self.assertEqual(exchange.created_orders[2]["type"], "STOP_MARKET")
            protective_orders = result.raw["protective_orders"]
            self.assertEqual(len(protective_orders), 2)
            self.assertLess(protective_orders[0]["trigger_price"], result.raw["entry_price"])
            self.assertGreater(protective_orders[1]["trigger_price"], result.raw["entry_price"])
            self.assertTrue(protective_orders[0]["client_order_id"].startswith("qount-tp-"))
            self.assertTrue(protective_orders[1]["client_order_id"].startswith("qount-sl-"))

    def test_executor_cancels_existing_managed_protective_orders_before_live_close(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                mode="live",
                market_type="future",
                symbols=("XRP/USDT:USDT",),
                exchange_id="binance",
                binance_api_key="k",
                binance_api_secret="s",
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            exchange = FakeTradeExchange(
                open_orders=[
                    {
                        "id": "tp-1",
                        "symbol": "XRP/USDT:USDT",
                        "type": "TAKE_PROFIT_MARKET",
                        "clientOrderId": "qount-tp-123",
                        "info": {"clientOrderId": "qount-tp-123"},
                    },
                    {
                        "id": "sl-1",
                        "symbol": "XRP/USDT:USDT",
                        "type": "STOP_MARKET",
                        "clientOrderId": "qount-sl-456",
                        "info": {"clientOrderId": "qount-sl-456"},
                    },
                    {
                        "id": "manual-1",
                        "symbol": "XRP/USDT:USDT",
                        "type": "STOP_MARKET",
                        "clientOrderId": "manual-order",
                        "info": {"clientOrderId": "manual-order"},
                    },
                ]
            )
            executor = Executor(settings, journal, exchange_pool=FakeTradeExchangePool(exchange))
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[make_symbol("XRP/USDT:USDT", 900_000, 1.45, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="short")],
                open_positions=[
                    PositionSnapshot(
                        symbol="XRP/USDT:USDT",
                        quantity=10.0,
                        mark_price=1.45,
                        market_value_quote=14.5,
                        side="short",
                        average_entry_price=1.46,
                        notional_quote=14.5,
                    )
                ],
                equity_quote=200.0,
                free_quote=190.0,
            )
            verdict = RiskVerdict(
                status="approved",
                final_action="close",
                symbol="XRP/USDT:USDT",
                final_size_pct=0.0,
                take_profit_pct=0.0,
                stop_loss_pct=0.0,
                ttl_minutes=0,
                reasons=["ok"],
                confidence=0.80,
                approved=True,
            )

            result = executor.execute(verdict, bundle)

            self.assertEqual(result.action, "close")
            self.assertEqual(exchange.created_orders[0]["type"], "market")
            self.assertEqual(sorted(order_id for order_id, _ in exchange.cancelled_orders), ["sl-1", "tp-1"])
            canceled = result.raw["pre_close_cleanup"]["canceled"]
            self.assertEqual(len(canceled), 2)
            self.assertEqual(result.raw["post_close_cleanup"]["errors"], [])

    def test_executor_cleans_orphan_managed_protective_orders_when_no_position_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                mode="live",
                market_type="future",
                symbols=("XRP/USDT:USDT",),
                exchange_id="binance",
                binance_api_key="k",
                binance_api_secret="s",
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            exchange = FakeTradeExchange(
                open_orders=[
                    {
                        "id": "tp-1",
                        "symbol": "XRP/USDT:USDT",
                        "type": "TAKE_PROFIT_MARKET",
                        "clientOrderId": "qount-tp-123",
                        "info": {"clientOrderId": "qount-tp-123"},
                    },
                    {
                        "id": "sl-1",
                        "symbol": "XRP/USDT:USDT",
                        "type": "STOP_MARKET",
                        "clientOrderId": "qount-sl-456",
                        "info": {"clientOrderId": "qount-sl-456"},
                    },
                    {
                        "id": "manual-1",
                        "symbol": "XRP/USDT:USDT",
                        "type": "STOP_MARKET",
                        "clientOrderId": "manual-order",
                        "info": {"clientOrderId": "manual-order"},
                    },
                ]
            )
            executor = Executor(settings, journal, exchange_pool=FakeTradeExchangePool(exchange))
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[make_symbol("XRP/USDT:USDT", 900_000, 1.45, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="short")],
                open_positions=[],
                equity_quote=200.0,
                free_quote=200.0,
            )

            cleanup = executor.cleanup_orphan_managed_orders(bundle)

            self.assertEqual(sorted(order_id for order_id, _ in exchange.cancelled_orders), ["sl-1", "tp-1"])
            self.assertEqual(len(cleanup["canceled"]), 2)
            self.assertEqual(cleanup["errors"], [])
            self.assertEqual([order["id"] for order in exchange.fetch_open_orders("XRP/USDT:USDT")], ["manual-1"])

    def test_signal_review_reports_cost_aware_aggregates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(root)
            journal = Journal(settings.db_path)
            journal.ensure_schema()

            btc_buy_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[make_symbol("BTC/USDT", 300_000, 100.0, atr_pct=0.0040, range_pct=0.0050, volume_ratio=1.10, higher_bias="long")],
            )
            record_run(journal, settings, bundle=btc_buy_bundle, decision_action="buy", final_action="buy", symbol="BTC/USDT", confidence=0.90)

            eth_hold_bundle = make_bundle(
                timestamp_ms=600_000,
                symbols=[make_symbol("ETH/USDT", 600_000, 200.0, atr_pct=0.0035, range_pct=0.0040, volume_ratio=1.10, higher_bias="long")],
            )
            record_run(journal, settings, bundle=eth_hold_bundle, decision_action="hold", final_action="hold", symbol="ETH/USDT", confidence=0.20)

            btc_close_bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[make_symbol("BTC/USDT", 900_000, 102.0, atr_pct=0.0040, range_pct=0.0045, volume_ratio=1.10, higher_bias="long")],
                open_positions=[
                    PositionSnapshot(
                        symbol="BTC/USDT",
                        quantity=1.0,
                        mark_price=102.0,
                        market_value_quote=102.0,
                        side="long",
                        average_entry_price=100.0,
                        notional_quote=102.0,
                    )
                ],
                equity_quote=204.0,
                free_quote=102.0,
            )
            record_run(journal, settings, bundle=btc_close_bundle, decision_action="close", final_action="close", symbol="BTC/USDT", confidence=0.55)

            service = FakeReviewService(
                settings,
                journal,
                candles_by_symbol={
                    "BTC/USDT": [
                        [300_000, 100.0, 100.5, 99.8, 100.0, 1000.0],
                        [600_000, 100.0, 101.8, 99.9, 101.5, 1200.0],
                        [900_000, 102.0, 102.2, 101.8, 102.0, 1200.0],
                        [1_200_000, 102.0, 102.1, 98.8, 99.0, 1300.0],
                    ],
                    "ETH/USDT": [
                        [600_000, 200.0, 201.0, 199.8, 200.0, 1000.0],
                        [900_000, 206.0, 206.2, 205.8, 206.0, 1100.0],
                    ],
                },
            )
            report = service.signal_review(limit=10, horizon_bars=1, threshold_pct=0.003)
            overall = report["aggregate"]["overall"]
            self.assertEqual(report["aggregate"]["reviewed"], 3)
            self.assertIn("avg_net_edge_pct", overall)
            self.assertIn("by_symbol", report["aggregate"])
            self.assertIn("BTC/USDT", report["aggregate"]["by_symbol"])
            self.assertIn("high", report["aggregate"]["by_confidence"])
            self.assertEqual(report["aggregate"]["by_confidence"]["low"]["missed_move"], 1)
            self.assertEqual(report["aggregate"]["by_action"]["buy"]["good"], 1)
            self.assertAlmostEqual(report["aggregate"]["by_symbol"]["BTC/USDT"]["flip_rate"], 1.0)

    def test_signal_review_reports_lifecycle_risk_and_excursion_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()

            entry_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[make_symbol("XRP/USDT:USDT", 300_000, 1.50, atr_pct=0.0040, range_pct=0.0045, volume_ratio=1.20, higher_bias="short")],
                equity_quote=200.0,
                free_quote=200.0,
            )
            record_run(
                journal,
                settings,
                bundle=entry_bundle,
                decision_action="sell",
                final_action="sell",
                symbol="XRP/USDT:USDT",
                confidence=0.90,
            )

            service = FakeReviewService(
                settings,
                journal,
                candles_by_symbol={
                    "XRP/USDT:USDT": [
                        [300_000, 1.50, 1.505, 1.495, 1.50, 1000.0],
                        [600_000, 1.50, 1.51, 1.44, 1.45, 1500.0],
                    ],
                },
            )
            report = service.signal_review(limit=10, horizon_bars=1, threshold_pct=0.003)
            reviewed = [item for item in report["reviews"] if item.get("status") == "reviewed"]

            self.assertEqual(len(reviewed), 1)
            item = reviewed[0]
            self.assertEqual(item["decision_lifecycle"], "fresh_entry")
            self.assertAlmostEqual(item["planned_risk_pct_of_equity"], 0.336, places=6)
            self.assertAlmostEqual(item["mfe_pct"], 4.0, places=6)
            self.assertAlmostEqual(item["mae_pct"], 0.6666666667, places=6)
            self.assertAlmostEqual(item["giveback_pct"], 0.6666666667, places=6)
            self.assertGreater(item["future_R"], 9.0)
            self.assertEqual(report["aggregate"]["by_lifecycle"]["fresh_entry"]["reviewed"], 1)
            self.assertAlmostEqual(report["aggregate"]["overall"]["avg_mfe_pct"], 4.0, places=6)

    def test_signal_review_reports_context_and_candidate_reason_slices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(root)
            journal = Journal(settings.db_path)
            journal.ensure_schema()

            entry_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[make_symbol("BTC/USDT", 300_000, 100.0, atr_pct=0.0040, range_pct=0.0050, volume_ratio=1.10, higher_bias="long")],
            )
            record_run(
                journal,
                settings,
                bundle=entry_bundle,
                decision_action="buy",
                final_action="buy",
                symbol="BTC/USDT",
                confidence=0.90,
                raw_payload_extra={
                    "candidate_filter": {
                        "symbols": [
                            {
                                "symbol": "BTC/USDT",
                                "eligible": True,
                                "manage_only": False,
                                "reasons": ["candidate_ok"],
                            }
                        ]
                    }
                },
            )

            management_hold_bundle = make_bundle(
                timestamp_ms=600_000,
                symbols=[make_symbol("BTC/USDT", 600_000, 101.0, atr_pct=0.0038, range_pct=0.0042, volume_ratio=1.05, higher_bias="long")],
                open_positions=[
                    PositionSnapshot(
                        symbol="BTC/USDT",
                        quantity=1.0,
                        mark_price=101.0,
                        market_value_quote=101.0,
                        side="long",
                        average_entry_price=100.0,
                        notional_quote=101.0,
                    )
                ],
                equity_quote=201.0,
                free_quote=100.0,
            )
            record_run(
                journal,
                settings,
                bundle=management_hold_bundle,
                decision_action="hold",
                final_action="hold",
                symbol="BTC/USDT",
                confidence=0.40,
                raw_payload_extra={
                    "candidate_filter": {
                        "symbols": [
                            {
                                "symbol": "BTC/USDT",
                                "eligible": True,
                                "manage_only": True,
                                "reasons": ["position_management"],
                            }
                        ]
                    }
                },
            )

            management_close_bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[make_symbol("BTC/USDT", 900_000, 102.0, atr_pct=0.0040, range_pct=0.0045, volume_ratio=1.10, higher_bias="long")],
                open_positions=[
                    PositionSnapshot(
                        symbol="BTC/USDT",
                        quantity=1.0,
                        mark_price=102.0,
                        market_value_quote=102.0,
                        side="long",
                        average_entry_price=100.0,
                        notional_quote=102.0,
                    )
                ],
                equity_quote=204.0,
                free_quote=102.0,
            )
            record_run(
                journal,
                settings,
                bundle=management_close_bundle,
                decision_action="close",
                final_action="close",
                symbol="BTC/USDT",
                confidence=0.55,
                raw_payload_extra={
                    "candidate_filter": {
                        "symbols": [
                            {
                                "symbol": "BTC/USDT",
                                "eligible": True,
                                "manage_only": True,
                                "reasons": ["position_management"],
                            }
                        ]
                    }
                },
            )

            service = FakeReviewService(
                settings,
                journal,
                candles_by_symbol={
                    "BTC/USDT": [
                        [300_000, 100.0, 100.5, 99.8, 100.0, 1000.0],
                        [600_000, 100.0, 101.8, 99.9, 101.5, 1200.0],
                        [900_000, 102.0, 102.2, 101.8, 102.0, 1200.0],
                        [1_200_000, 102.0, 102.1, 98.8, 99.0, 1300.0],
                    ],
                },
            )
            report = service.signal_review(limit=10, horizon_bars=1, threshold_pct=0.003)
            by_context = report["aggregate"]["by_context"]
            by_candidate_reason = report["aggregate"]["by_candidate_reason"]

            self.assertEqual(by_context["entry"]["reviewed"], 1)
            self.assertEqual(by_context["management"]["reviewed"], 2)
            self.assertEqual(by_candidate_reason["counts"]["candidate_ok"], 1)
            self.assertEqual(by_candidate_reason["counts"]["position_management"], 2)
            self.assertEqual(by_candidate_reason["position_management"]["reviewed"], 2)
            self.assertTrue(any(item["decision_context"] == "management" for item in report["reviews"] if item.get("status") == "reviewed"))

    def test_signal_review_treats_favorable_management_hold_as_good_hold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()

            short_hold_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[make_symbol("XRP/USDT:USDT", 300_000, 1.50, atr_pct=0.0035, range_pct=0.0038, volume_ratio=1.10, higher_bias="short")],
                open_positions=[
                    PositionSnapshot(
                        symbol="XRP/USDT:USDT",
                        quantity=10.0,
                        mark_price=1.50,
                        market_value_quote=15.0,
                        side="short",
                        average_entry_price=1.52,
                        notional_quote=15.0,
                    )
                ],
                equity_quote=200.0,
                free_quote=190.0,
            )
            record_run(
                journal,
                settings,
                bundle=short_hold_bundle,
                decision_action="hold",
                final_action="hold",
                symbol="XRP/USDT:USDT",
                confidence=0.70,
                raw_payload_extra={
                    "candidate_filter": {
                        "symbols": [
                            {
                                "symbol": "XRP/USDT:USDT",
                                "eligible": True,
                                "manage_only": True,
                                "reasons": ["position_management"],
                            }
                        ]
                    }
                },
            )

            service = FakeReviewService(
                settings,
                journal,
                candles_by_symbol={
                    "XRP/USDT:USDT": [
                        [300_000, 1.50, 1.51, 1.49, 1.50, 1000.0],
                        [600_000, 1.50, 1.45, 1.44, 1.45, 1500.0],
                    ],
                },
            )
            report = service.signal_review(limit=10, horizon_bars=1, threshold_pct=0.003)
            reviewed = [item for item in report["reviews"] if item.get("status") == "reviewed"]
            self.assertEqual(len(reviewed), 1)
            item = reviewed[0]
            self.assertEqual(item["decision_context"], "management")
            self.assertEqual(item["position_side_before_action"], "short")
            self.assertEqual(item["outcome"], "good_hold")
            self.assertLess(item["market_future_return_pct"], 0.0)
            self.assertGreater(item["position_future_return_pct"], 0.0)

    def test_signal_review_reports_blocked_sell_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()

            blocked_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[make_symbol("XRP/USDT:USDT", 300_000, 1.5, atr_pct=0.0025, range_pct=0.0020, volume_ratio=1.30, higher_bias="short")],
                equity_quote=200.0,
                free_quote=200.0,
            )
            run_id = journal.start_run(settings.mode)
            journal.record_snapshot(run_id, blocked_bundle)
            journal.record_validated_decision(run_id, make_decision("XRP/USDT:USDT", "sell", confidence=0.60))
            journal.record_risk(
                run_id,
                RiskVerdict(
                    status="rejected",
                    final_action="hold",
                    symbol="XRP/USDT:USDT",
                    final_size_pct=0.0,
                    take_profit_pct=0.02,
                    stop_loss_pct=0.01,
                    ttl_minutes=30,
                    reasons=["expected_edge_below_minimum:0.001500<0.002500"],
                    confidence=0.60,
                    approved=False,
                ),
            )
            journal.finish_run(run_id, "completed", {"run_id": run_id})

            service = FakeReviewService(
                settings,
                journal,
                candles_by_symbol={
                    "XRP/USDT:USDT": [
                        [300_000, 1.50, 1.51, 1.49, 1.50, 1000.0],
                        [600_000, 1.50, 1.45, 1.44, 1.45, 1500.0],
                    ],
                },
            )
            report = service.signal_review(limit=10, horizon_bars=1, threshold_pct=0.003)
            blocked_summary = report["aggregate"]["blocked_sell"]
            self.assertEqual(blocked_summary["reviewed"], 1)
            self.assertEqual(blocked_summary["by_reason"]["expected_edge_below_minimum"], 1)


if __name__ == "__main__":
    unittest.main()
