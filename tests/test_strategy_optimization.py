from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from datetime import timezone
import json
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
from qount.backtest import BacktestService
from qount.entry_quality import assess_fresh_entry
from qount.entry_quality import build_traditional_signal_context
from qount.hourly_model import fit_symbol_hourly_return_model
from qount.hourly_model import score_hourly_return_model_signal
from qount.executor import Executor
from qount.journal import Journal
from qount.market import build_higher_timeframe_context_from_completed_candles
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
from qount.main import build_parser
from qount.orchestrator import Orchestrator
from qount.research_profile import apply_research_profile
from qount.research_profile import setup_model_horizon_bars_for_profile
from qount.research_profile import setup_model_split_higher_phase_for_profile
from qount.review import ReviewService
from qount.risk_engine import RiskEngine
from qount.settings import Settings
from qount.setup_model import build_setup_model_feature_map
from qount.setup_model import fit_setup_edge_model
from qount.setup_model import score_setup_edge_model_signal
from qount.setup_model import SetupEdgeModelService
from qount.walk_forward import parse_walk_forward_window
from qount.walk_forward import _performance_summary
from qount.walk_forward import WalkForwardService


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
        rule_mode="strict",
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
        hourly_model_enable=False,
        hourly_model_path=project_root / "state" / "models" / "hourly_return_model.json",
        setup_model_enable=False,
        setup_model_path=project_root / "state" / "models" / "setup_edge_model.json",
        min_expected_edge_pct=0.0015,
        max_net_directional_exposure_pct=0.40,
        max_correlated_directional_exposure_pct=0.30,
        third_same_direction_edge_buffer_pct=0.00075,
        alt_short_edge_penalty_pct=0.00075,
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
    higher_phase: str | None = None,
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
            "trend_direction": higher_bias,
            "trend_phase": (
                higher_phase
                if higher_phase is not None
                else "trend" if higher_bias in {"long", "short"} else "range"
            ),
            "trend_strength": 1.25 if higher_bias in {"long", "short"} else 0.0,
            "fast_sma_slope": 0.001 if higher_bias == "long" else -0.001 if higher_bias == "short" else 0.0,
            "slow_sma_slope": 0.0006 if higher_bias == "long" else -0.0006 if higher_bias == "short" else 0.0,
            "distance_to_fast_sma": 0.01 if higher_bias == "long" else -0.01 if higher_bias == "short" else 0.0,
            "distance_to_slow_sma": 0.02 if higher_bias == "long" else -0.02 if higher_bias == "short" else 0.0,
            "distance_from_12bar_extreme": -0.004 if higher_bias in {"long", "short"} else None,
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


def make_decision(
    symbol: str,
    action: str,
    *,
    confidence: float = 0.8,
    size_pct: float | None = None,
    take_profit_pct: float = 0.02,
    stop_loss_pct: float | None = None,
) -> ValidatedDecision:
    return ValidatedDecision(
        decision=AIDecision(
            timestamp=utc_now().isoformat(),
            symbol=symbol,
            action=action,
            size_pct=(0.10 if action != "hold" else 0.0) if size_pct is None else size_pct,
            take_profit_pct=take_profit_pct,
            stop_loss_pct=(0.01 if action != "hold" else 0.0) if stop_loss_pct is None else stop_loss_pct,
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
    decision_size_pct: float | None = None,
    decision_take_profit_pct: float = 0.02,
    decision_stop_loss_pct: float | None = None,
    final_size_pct: float | None = None,
    final_take_profit_pct: float | None = None,
    final_stop_loss_pct: float | None = None,
    risk_debug: dict | None = None,
    order_result: ExecutionResult | None = None,
) -> None:
    run_id = journal.start_run(settings.mode)
    journal.record_snapshot(run_id, bundle)
    validated = make_decision(
        symbol,
        decision_action,
        confidence=confidence,
        size_pct=decision_size_pct,
        take_profit_pct=decision_take_profit_pct,
        stop_loss_pct=decision_stop_loss_pct,
    )
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
            final_size_pct=(0.10 if final_action != "hold" else 0.0) if final_size_pct is None else final_size_pct,
            take_profit_pct=(0.02 if final_take_profit_pct is None else final_take_profit_pct),
            stop_loss_pct=((0.01 if final_action != "hold" else 0.0) if final_stop_loss_pct is None else final_stop_loss_pct),
            ttl_minutes=30,
            reasons=risk_reasons or ["ok"],
            confidence=confidence,
            approved=True,
            risk_debug=risk_debug,
        ),
    )
    if order_result is not None:
        journal.record_order(run_id, order_result)
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


class FakeHistoricalExchange:
    def __init__(self, candles_by_key: dict[tuple[str, str], list[list[float]]]) -> None:
        self.candles_by_key = candles_by_key

    def load_markets(self) -> dict[str, dict]:
        markets: dict[str, dict] = {}
        for symbol, _timeframe in self.candles_by_key:
            if symbol in markets:
                continue
            base, quote_with_settle = symbol.split("/")
            quote = quote_with_settle.split(":")[0]
            amount_precision = 0.001 if base in {"BTC", "ETH"} else 0.1 if base == "XRP" else 0.01
            min_cost = 50.0 if base == "BTC" else 20.0 if base == "ETH" else 5.0
            markets[symbol] = {
                "symbol": symbol,
                "id": f"{base}{quote}",
                "base": base,
                "quote": quote,
                "settle": quote,
                "contract": True,
                "linear": True,
                "swap": True,
                "limits": {
                    "cost": {"min": min_cost},
                    "amount": {"min": amount_precision},
                },
                "precision": {
                    "amount": amount_precision,
                    "price": 0.0001,
                },
            }
        return markets

    def fetch_ohlcv(self, symbol: str, timeframe: str, since: int | None = None, limit: int | None = None):
        rows = self.candles_by_key[(symbol, timeframe)]
        filtered = [row for row in rows if since is None or int(row[0]) >= since]
        if limit is not None:
            return filtered[:limit]
        return filtered


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
    def test_eth_only_research_profile_applies_canonical_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="spot",
                live_enable=True,
                rule_mode="strict",
                symbols=("BTC/USDT", "SOL/USDT"),
                max_open_positions=3,
                hourly_model_enable=True,
                setup_model_enable=False,
            )

            profiled = apply_research_profile(settings, "eth-only")

            self.assertEqual(profiled.market_type, "future")
            self.assertFalse(profiled.live_enable)
            self.assertEqual(profiled.rule_mode, "bottom_line")
            self.assertEqual(profiled.symbols, ("ETH/USDT",))
            self.assertEqual(profiled.max_open_positions, 1)
            self.assertFalse(profiled.hourly_model_enable)
            self.assertTrue(profiled.setup_model_enable)
            self.assertEqual(
                profiled.setup_model_path,
                root / "state" / "models" / "setup_edge_model_short_rebound_phase6.json",
            )
            self.assertAlmostEqual(profiled.trailing_profit_arm_pct, 0.0018)
            self.assertAlmostEqual(profiled.trailing_profit_retrace_pct, 0.003)

    def test_eth_only_research_profile_defaults_match_phase6_setup_model(self) -> None:
        self.assertEqual(setup_model_horizon_bars_for_profile("eth-only", None), 6)
        self.assertTrue(setup_model_split_higher_phase_for_profile("eth-only", None))
        self.assertEqual(setup_model_horizon_bars_for_profile(None, None), 3)
        self.assertFalse(setup_model_split_higher_phase_for_profile(None, None))
        self.assertEqual(setup_model_horizon_bars_for_profile("eth-only", 4), 4)
        self.assertFalse(setup_model_split_higher_phase_for_profile("eth-only", False))

    def test_backtest_parser_accepts_eth_only_research_profile(self) -> None:
        parser = build_parser()

        args = parser.parse_args(
            [
                "backtest",
                "--start",
                "2026-03-06T00:00:00+00:00",
                "--end",
                "2026-03-06T01:00:00+00:00",
                "--research-profile",
                "eth-only",
            ]
        )

        self.assertEqual(args.command, "backtest")
        self.assertEqual(args.research_profile, "eth-only")

    def test_train_setup_model_parser_accepts_eth_only_research_profile(self) -> None:
        parser = build_parser()

        args = parser.parse_args(
            [
                "train-setup-model",
                "--research-profile",
                "eth-only",
            ]
        )

        self.assertEqual(args.command, "train-setup-model")
        self.assertEqual(args.research_profile, "eth-only")

    def test_walk_forward_summary_reads_nested_review_overall_metrics(self) -> None:
        summary = _performance_summary(
            {
                "performance": {"realized_return_pct": 0.2, "open_positions": 0},
                "order_stats": {"paper_filled": 1, "paper_closed": 1},
                "review": {
                    "aggregate": {
                        "reviewed": 4,
                        "overall": {
                            "reviewed": 4,
                            "avg_net_edge_pct": -0.01,
                            "good": 1,
                            "bad": 2,
                            "flat": 1,
                            "missed_move": 0,
                        },
                    }
                },
                "setup_model": {"backtest_window": {"oos_safe": True}},
            }
        )

        self.assertEqual(summary["reviewed"], 4)
        self.assertEqual(summary["review_avg_net_edge_pct"], -0.01)
        self.assertEqual(summary["review_good"], 1)
        self.assertEqual(summary["review_bad"], 2)
        self.assertEqual(summary["review_flat"], 1)
        self.assertEqual(summary["review_missed_move"], 0)

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

    def test_orchestrator_adds_entry_viability_preview_to_ai_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
            )
            orchestrator = Orchestrator(settings)
            symbol = make_symbol(
                "XRP/USDT:USDT",
                900_000,
                1.4084,
                atr_pct=0.00187,
                range_pct=0.00426,
                volume_ratio=4.09,
                higher_bias="short",
                higher_phase="trend",
            )
            symbol.indicators["return_1bar"] = -0.00255
            symbol.indicators["return_24bars"] = -0.00354
            symbol.indicators["rsi_14"] = 30.32
            symbol.indicators["sma_fast_ratio"] = -0.00258
            symbol.indicators["sma_slow_ratio"] = -0.00350
            symbol.recent_candles[-1].open = 1.4119
            symbol.recent_candles[-1].high = 1.4130
            symbol.recent_candles[-1].low = 1.4070
            symbol.recent_candles[-1].close = 1.4084
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )
            captured_context: dict[str, object] = {}

            class _StubMarket:
                def fetch_bundle(self, journal):
                    return bundle

            class _StubAIClient:
                def request_decision(self, ai_bundle):
                    captured_context.update(ai_bundle.symbols[0].candidate_context or {})
                    payload = {
                        "timestamp": utc_now().isoformat(),
                        "symbol": ai_bundle.symbols[0].symbol,
                        "action": "hold",
                        "size_pct": 0.0,
                        "take_profit_pct": 0.0,
                        "stop_loss_pct": 0.0,
                        "ttl_minutes": 0,
                        "confidence": 0.51,
                        "reason": "preview_capture_test",
                        "prompt_version": "v1",
                    }
                    return {"stub": True}, json.dumps(payload), "stub-model"

            orchestrator.market = _StubMarket()
            orchestrator.ai_client = _StubAIClient()

            result = orchestrator.run_once()

            self.assertEqual(result["symbol"], "XRP/USDT:USDT")
            self.assertEqual(result["action"], "hold")
            preview = captured_context.get("entry_viability_preview")
            self.assertIsInstance(preview, dict)
            self.assertEqual(preview["preview_action"], "sell")
            self.assertIn("expected_edge", preview)
            summary_preview = result["candidate_filter"]["symbols"][0]["entry_viability_preview"]
            self.assertEqual(summary_preview["preview_action"], "sell")

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

    def test_orchestrator_run_once_processes_multiple_symbols_in_same_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                max_open_positions=2,
                symbols=("SOL/USDT", "XRP/USDT"),
            )
            orchestrator = Orchestrator(settings)

            strong_sol = make_symbol("SOL/USDT:USDT", 900_000, 90.71, atr_pct=0.0016556551215455202, range_pct=0.003625178512578252, volume_ratio=3.5673327420468857, higher_bias="short")
            strong_sol.indicators["return_1bar"] = -0.0004392225760403434
            strong_sol.indicators["return_24bars"] = -0.0014260640631855726
            strong_sol.indicators["sma_fast_ratio"] = -0.0022833969639953766
            strong_sol.indicators["sma_slow_ratio"] = -0.0018457939655330824
            strong_sol.indicators["rsi_14"] = 29.896907216494498
            strong_sol.higher_timeframe = {
                "timeframe": "1h",
                "trend_bias": "short",
                "return_12bars": -0.009770926066659524,
                "sma_fast_ratio": -0.002860630796421515,
                "sma_slow_ratio": -0.008330955001970564,
                "rsi_14": 37.41379310344829,
            }

            strong_xrp = make_symbol("XRP/USDT:USDT", 900_000, 1.45, atr_pct=0.0038, range_pct=0.0041, volume_ratio=1.30, higher_bias="short")
            strong_xrp.indicators["return_1bar"] = -0.0002
            strong_xrp.indicators["return_24bars"] = 0.0008
            strong_xrp.indicators["sma_fast_ratio"] = -0.0028
            strong_xrp.indicators["sma_slow_ratio"] = -0.0059
            strong_xrp.indicators["rsi_14"] = 40.0

            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[strong_sol, strong_xrp],
                equity_quote=200.0,
                free_quote=200.0,
            )

            class _StubMarket:
                def fetch_bundle(self, journal):
                    return bundle

            class _StubAIClient:
                def request_decision(self, ai_bundle):
                    symbol = ai_bundle.symbols[0].symbol
                    payload = {
                        "timestamp": utc_now().isoformat(),
                        "symbol": symbol,
                        "action": "sell",
                        "size_pct": 0.10,
                        "take_profit_pct": 0.02,
                        "stop_loss_pct": 0.01,
                        "ttl_minutes": 30,
                        "confidence": 0.72,
                        "reason": "multi_symbol_cycle_test",
                        "prompt_version": "v1",
                    }
                    return {"stub": True}, json.dumps(payload), "stub-model"

            orchestrator.market = _StubMarket()
            orchestrator.ai_client = _StubAIClient()

            result = orchestrator.run_once()

            self.assertEqual(result["status"], "cycle_completed")
            self.assertEqual(result["processed_runs"], 2)
            self.assertEqual(result["processed_symbols"], ["SOL/USDT:USDT", "XRP/USDT:USDT"])
            orders = orchestrator.journal.get_order_history(mode=settings.mode)
            filled = [order for order in orders if order["status"] == "paper_filled"]
            self.assertEqual(len(filled), 2)
            symbols = [order["symbol"] for order in filled]
            self.assertEqual(symbols, ["SOL/USDT:USDT", "XRP/USDT:USDT"])

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

    def test_candidate_filter_uses_latest_action_for_reentry_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(root)
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            filter_service = CandidateFilter(settings, journal)

            oldest_close_bundle = make_bundle(
                timestamp_ms=0,
                symbols=[make_symbol("BTC/USDT", 0, 99.0, atr_pct=0.0040, range_pct=0.0045, volume_ratio=1.10, higher_bias="long")],
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
            record_run(journal, settings, bundle=oldest_close_bundle, decision_action="close", final_action="close", symbol="BTC/USDT")

            latest_close_bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[make_symbol("BTC/USDT", 900_000, 100.0, atr_pct=0.0040, range_pct=0.0045, volume_ratio=1.10, higher_bias="long")],
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
            record_run(journal, settings, bundle=latest_close_bundle, decision_action="close", final_action="close", symbol="BTC/USDT")

            reentry_bundle = make_bundle(
                timestamp_ms=1_200_000,
                symbols=[make_symbol("BTC/USDT", 1_200_000, 101.0, atr_pct=0.0040, range_pct=0.0050, volume_ratio=1.10, higher_bias="long")],
            )
            filtered = filter_service.apply(reentry_bundle)

            self.assertEqual(filtered.status, "filtered_hold")
            btc_summary = filtered.summary["symbols"][0]
            self.assertIn("same_symbol_reentry_cooldown_active:1<3", btc_summary["reasons"])

    def test_candidate_filter_reentry_cooldown_survives_intervening_holds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(root)
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            filter_service = CandidateFilter(settings, journal)

            close_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[make_symbol("BTC/USDT", 300_000, 100.0, atr_pct=0.0040, range_pct=0.0045, volume_ratio=1.10, higher_bias="long")],
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
            record_run(journal, settings, bundle=close_bundle, decision_action="close", final_action="close", symbol="BTC/USDT")

            hold_bundle = make_bundle(
                timestamp_ms=600_000,
                symbols=[make_symbol("BTC/USDT", 600_000, 100.5, atr_pct=0.0040, range_pct=0.0045, volume_ratio=1.10, higher_bias="long")],
                equity_quote=200.0,
                free_quote=200.0,
            )
            record_run(journal, settings, bundle=hold_bundle, decision_action="hold", final_action="hold", symbol="BTC/USDT")

            reentry_bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[make_symbol("BTC/USDT", 900_000, 101.0, atr_pct=0.0040, range_pct=0.0050, volume_ratio=1.10, higher_bias="long")],
            )
            filtered = filter_service.apply(reentry_bundle)

            self.assertEqual(filtered.status, "filtered_hold")
            btc_summary = filtered.summary["symbols"][0]
            self.assertIn("same_symbol_reentry_cooldown_active:2<3", btc_summary["reasons"])

    def test_candidate_filter_extends_eth_reclaim_short_reentry_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                trailing_profit_arm_pct=0.0025,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            filter_service = CandidateFilter(settings, journal)

            previous_close_bundle = make_bundle(
                timestamp_ms=600_000,
                symbols=[make_symbol("ETH/USDT:USDT", 600_000, 2_050.0, atr_pct=0.0040, range_pct=0.0045, volume_ratio=1.20, higher_bias="short", higher_phase="reclaim")],
                open_positions=[
                    PositionSnapshot(
                        symbol="ETH/USDT:USDT",
                        quantity=0.05,
                        mark_price=2_050.0,
                        market_value_quote=102.5,
                        side="short",
                        average_entry_price=2_070.0,
                        notional_quote=102.5,
                    )
                ],
                equity_quote=200.0,
                free_quote=100.0,
            )
            record_run(
                journal,
                settings,
                bundle=previous_close_bundle,
                decision_action="close",
                final_action="close",
                symbol="ETH/USDT:USDT",
                raw_payload_extra={"entry_thesis": {"setup_phase": "short_rebound_fail_confirmed", "higher_timeframe_phase": "reclaim"}},
                risk_debug={"entry_thesis": {"setup_phase": "short_rebound_fail_confirmed", "higher_timeframe_phase": "reclaim"}},
            )

            reentry_symbol = make_symbol("ETH/USDT:USDT", 1_500_000, 2_040.0, atr_pct=0.0040, range_pct=0.0045, volume_ratio=1.20, higher_bias="short", higher_phase="reclaim")
            reentry_symbol.indicators["return_1bar"] = -0.0005
            reentry_symbol.indicators["return_24bars"] = -0.0018
            reentry_symbol.indicators["rsi_14"] = 45.0
            reentry_symbol.indicators["sma_fast_ratio"] = -0.0011
            reentry_symbol.indicators["sma_slow_ratio"] = -0.0014
            reentry_bundle = make_bundle(
                timestamp_ms=1_500_000,
                symbols=[reentry_symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )
            filtered = filter_service.apply(reentry_bundle)

            self.assertEqual(filtered.status, "filtered_hold")
            eth_summary = filtered.summary["symbols"][0]
            self.assertIn("same_symbol_reentry_cooldown_active:3<6", eth_summary["reasons"])

    def test_candidate_filter_blocks_long_reentry_after_adverse_loss_cut_before_ai(self) -> None:
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
            filter_service = CandidateFilter(settings, journal)

            previous_close_bundle = make_bundle(
                timestamp_ms=600_000,
                symbols=[make_symbol("SOL/USDT:USDT", 600_000, 100.0, atr_pct=0.0040, range_pct=0.0045, volume_ratio=1.20, higher_bias="long")],
                open_positions=[
                    PositionSnapshot(
                        symbol="SOL/USDT:USDT",
                        quantity=1.0,
                        mark_price=100.0,
                        market_value_quote=100.0,
                        side="long",
                        average_entry_price=101.0,
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
                risk_reasons=["management_adverse_loss_cut:-0.003000<=-0.002500"],
            )

            reentry_bundle = make_bundle(
                timestamp_ms=1_800_000,
                symbols=[make_symbol("SOL/USDT:USDT", 1_800_000, 100.6, atr_pct=0.0040, range_pct=0.0045, volume_ratio=1.20, higher_bias="long")],
                equity_quote=200.0,
                free_quote=200.0,
            )
            filtered = filter_service.apply(reentry_bundle)

            self.assertEqual(filtered.status, "filtered_hold")
            sol_summary = filtered.summary["symbols"][0]
            self.assertIn("loss_reentry_cooldown_active:4<6", sol_summary["reasons"])

    def test_candidate_filter_blocks_countertrend_short_candidates_before_ai(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
                min_hold_bars=1,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            filter_service = CandidateFilter(settings, journal)

            symbol = make_symbol("XRP/USDT:USDT", 600_000, 1.5, atr_pct=0.0025, range_pct=0.0020, volume_ratio=1.30, higher_bias="short")
            symbol.indicators["return_1bar"] = 0.0018
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

    def test_candidate_filter_bottom_line_mode_still_blocks_hard_degraded_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            strict_settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
                min_notional_quote=5.0,
            )
            bottom_line_settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
                min_notional_quote=5.0,
                rule_mode="bottom_line",
            )
            strict_journal = Journal(strict_settings.db_path)
            strict_journal.ensure_schema()
            bottom_line_journal = Journal(bottom_line_settings.db_path)
            bottom_line_journal.ensure_schema()
            strict_filter = CandidateFilter(strict_settings, strict_journal)
            bottom_line_filter = CandidateFilter(bottom_line_settings, bottom_line_journal)

            symbol = make_symbol("XRP/USDT:USDT", 600_000, 1.5, atr_pct=0.0014, range_pct=0.0014, volume_ratio=0.40, higher_bias="flat")
            symbol.indicators["return_1bar"] = 0.0018
            symbol.indicators["return_24bars"] = 0.0040
            symbol.indicators["sma_fast_ratio"] = 0.0008
            symbol.indicators["sma_slow_ratio"] = 0.0005
            bundle = make_bundle(
                timestamp_ms=600_000,
                symbols=[symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )

            strict_filtered = strict_filter.apply(bundle)
            self.assertEqual(strict_filtered.status, "filtered_hold")

            bottom_line_filtered = bottom_line_filter.apply(bundle)
            self.assertEqual(bottom_line_filtered.status, "filtered_hold")
            self.assertEqual(bottom_line_filtered.summary["selected_symbols"], [])
            xrp_summary = bottom_line_filtered.summary["symbols"][0]
            self.assertIn("low_volatility", xrp_summary["reasons"])
            self.assertIn("low_volume", xrp_summary["reasons"])
            self.assertIn("higher_timeframe_flat_bias_soft_penalty", xrp_summary["reasons"])

    def test_candidate_filter_bottom_line_mode_expands_candidate_pool_to_three_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            strict_settings = make_settings(
                root,
                market_type="future",
                symbols=("SOL/USDT:USDT", "ETH/USDT:USDT", "XRP/USDT:USDT", "BTC/USDT:USDT"),
            )
            bottom_line_settings = make_settings(
                root,
                market_type="future",
                symbols=("SOL/USDT:USDT", "ETH/USDT:USDT", "XRP/USDT:USDT", "BTC/USDT:USDT"),
                rule_mode="bottom_line",
            )
            strict_journal = Journal(strict_settings.db_path)
            strict_journal.ensure_schema()
            bottom_line_journal = Journal(bottom_line_settings.db_path)
            bottom_line_journal.ensure_schema()
            strict_filter = CandidateFilter(strict_settings, strict_journal)
            bottom_line_filter = CandidateFilter(bottom_line_settings, bottom_line_journal)

            sol = make_symbol("SOL/USDT:USDT", 600_000, 100.0, atr_pct=0.0042, range_pct=0.0040, volume_ratio=1.30, higher_bias="long")
            xrp = make_symbol("XRP/USDT:USDT", 600_000, 1.5, atr_pct=0.0040, range_pct=0.0038, volume_ratio=1.20, higher_bias="long")
            btc = make_symbol("BTC/USDT:USDT", 600_000, 100_000.0, atr_pct=0.0038, range_pct=0.0036, volume_ratio=1.10, higher_bias="long")
            eth = make_symbol("ETH/USDT:USDT", 600_000, 2_200.0, atr_pct=0.0032, range_pct=0.0032, volume_ratio=0.95, higher_bias="long")
            bundle = make_bundle(
                timestamp_ms=600_000,
                symbols=[sol, xrp, btc, eth],
                equity_quote=200.0,
                free_quote=200.0,
            )

            strict_filtered = strict_filter.apply(bundle)
            bottom_line_filtered = bottom_line_filter.apply(bundle)

            self.assertEqual(strict_filtered.status, "selected")
            self.assertEqual(bottom_line_filtered.status, "selected")
            self.assertEqual(strict_filtered.summary["selected_symbols"], ["SOL/USDT:USDT", "XRP/USDT:USDT"])
            self.assertEqual(
                bottom_line_filtered.summary["selected_symbols"],
                ["SOL/USDT:USDT", "XRP/USDT:USDT", "BTC/USDT:USDT"],
            )

    def test_candidate_filter_allows_mild_short_pullback_inside_strong_higher_timeframe_downtrend(self) -> None:
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

            symbol = make_symbol("SOL/USDT:USDT", 600_000, 91.42, atr_pct=0.0021, range_pct=0.0018, volume_ratio=0.72, higher_bias="short")
            symbol.indicators["return_1bar"] = 0.0007
            symbol.indicators["return_24bars"] = 0.0021
            symbol.indicators["sma_fast_ratio"] = 0.0028
            symbol.indicators["sma_slow_ratio"] = 0.0021
            symbol.indicators["rsi_14"] = 62.0
            bundle = make_bundle(
                timestamp_ms=600_000,
                symbols=[symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )

            filtered = filter_service.apply(bundle)

            self.assertEqual(filtered.status, "selected")
            sol_summary = filtered.summary["symbols"][0]
            self.assertTrue(sol_summary["eligible"])
            self.assertNotIn("short_setup_countertrend_drift", sol_summary["reasons"])
            self.assertNotIn("short_setup_latest_bar_rebound", sol_summary["reasons"])

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

    def test_candidate_filter_marks_moderate_short_breakdown_as_confirmed(self) -> None:
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

            symbol = make_symbol(
                "XRP/USDT:USDT",
                900_000,
                1.4084,
                atr_pct=0.00187,
                range_pct=0.00426,
                volume_ratio=4.09,
                higher_bias="short",
                higher_phase="trend",
            )
            symbol.indicators["return_1bar"] = -0.00255
            symbol.indicators["return_24bars"] = -0.00354
            symbol.indicators["rsi_14"] = 30.32
            symbol.indicators["sma_fast_ratio"] = -0.00258
            symbol.indicators["sma_slow_ratio"] = -0.00350
            symbol.recent_candles[-1].open = 1.4119
            symbol.recent_candles[-1].high = 1.4130
            symbol.recent_candles[-1].low = 1.4070
            symbol.recent_candles[-1].close = 1.4084
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )

            filtered = filter_service.apply(bundle)

            self.assertEqual(filtered.status, "selected")
            xrp_summary = filtered.summary["symbols"][0]
            self.assertEqual(xrp_summary["setup_phase"], "short_breakdown_confirmed")
            self.assertIn("short_setup_breakdown_confirmed", xrp_summary["reasons"])
            self.assertTrue(xrp_summary["setup_confirmed"])

    def test_traditional_signal_context_flags_failed_rebound_breakdown(self) -> None:
        symbol = make_symbol(
            "XRP/USDT:USDT",
            1_778_985_000_000,
            1.4029,
            atr_pct=0.002118061566347253,
            range_pct=0.0027086748877325722,
            volume_ratio=1.1123581133783067,
            higher_bias="short",
            higher_phase="trend",
        )
        symbol.indicators["return_1bar"] = -0.001494661921708218
        symbol.indicators["return_24bars"] = -0.008831425745372323
        symbol.indicators["sma_fast_ratio"] = -0.0016663800413926344
        symbol.indicators["sma_slow_ratio"] = -0.005885922061357074
        symbol.indicators["rsi_14"] = 27.522935779816038
        symbol.higher_timeframe["trend_strength"] = 3.0
        symbol.recent_candles = [
            Candle(timestamp_ms=1_778_983_800_000, open=1.4054, high=1.4083, low=1.4054, close=1.4067, volume=1_013_247.4),
            Candle(timestamp_ms=1_778_984_100_000, open=1.4066, high=1.4076, low=1.4054, close=1.4076, volume=513_950.0),
            Candle(timestamp_ms=1_778_984_400_000, open=1.4075, high=1.4080, low=1.4046, close=1.4053, volume=926_440.9),
            Candle(timestamp_ms=1_778_984_700_000, open=1.4052, high=1.4052, low=1.4035, close=1.4050, volume=1_061_209.3),
            Candle(timestamp_ms=1_778_985_000_000, open=1.4049, high=1.4054, low=1.4016, close=1.4029, volume=1_711_966.4),
        ]

        assessment = assess_fresh_entry(symbol, action="sell")
        context = build_traditional_signal_context(symbol, assessment)

        self.assertEqual(assessment.setup_phase, "short_breakdown_confirmed")
        self.assertIsNotNone(context)
        self.assertEqual(context["pattern_label"], "failed_rebound_breakdown")
        self.assertGreater(context["conviction_score"], 0.55)
        self.assertFalse(context["terminal_risk"])

    def test_candidate_filter_attaches_traditional_signal_context_for_classical_short_breakdown(self) -> None:
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

            symbol = make_symbol(
                "XRP/USDT:USDT",
                1_778_985_000_000,
                1.4029,
                atr_pct=0.002118061566347253,
                range_pct=0.0027086748877325722,
                volume_ratio=1.1123581133783067,
                higher_bias="short",
                higher_phase="trend",
            )
            symbol.indicators["return_1bar"] = -0.001494661921708218
            symbol.indicators["return_24bars"] = -0.008831425745372323
            symbol.indicators["sma_fast_ratio"] = -0.0016663800413926344
            symbol.indicators["sma_slow_ratio"] = -0.005885922061357074
            symbol.indicators["rsi_14"] = 27.522935779816038
            symbol.higher_timeframe["trend_strength"] = 3.0
            symbol.recent_candles = [
                Candle(timestamp_ms=1_778_983_800_000, open=1.4054, high=1.4083, low=1.4054, close=1.4067, volume=1_013_247.4),
                Candle(timestamp_ms=1_778_984_100_000, open=1.4066, high=1.4076, low=1.4054, close=1.4076, volume=513_950.0),
                Candle(timestamp_ms=1_778_984_400_000, open=1.4075, high=1.4080, low=1.4046, close=1.4053, volume=926_440.9),
                Candle(timestamp_ms=1_778_984_700_000, open=1.4052, high=1.4052, low=1.4035, close=1.4050, volume=1_061_209.3),
                Candle(timestamp_ms=1_778_985_000_000, open=1.4049, high=1.4054, low=1.4016, close=1.4029, volume=1_711_966.4),
            ]
            bundle = make_bundle(
                timestamp_ms=1_778_985_000_000,
                symbols=[symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )

            filtered = filter_service.apply(bundle)

            self.assertEqual(filtered.status, "selected")
            summary = filtered.summary["symbols"][0]
            self.assertEqual(summary["setup_phase"], "short_breakdown_confirmed")
            self.assertEqual(
                summary["traditional_signal_context"]["pattern_label"],
                "failed_rebound_breakdown",
            )
            self.assertGreater(
                summary["traditional_signal_context"]["conviction_score"],
                0.55,
            )

    def test_candidate_filter_marks_trend_phase_long_extension_as_soft_penalty(self) -> None:
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

            symbol = make_symbol(
                "SOL/USDT:USDT",
                900_000,
                87.07,
                atr_pct=0.00166,
                range_pct=0.00149,
                volume_ratio=1.02,
                higher_bias="long",
                higher_phase="trend",
            )
            symbol.indicators["return_1bar"] = 0.00046
            symbol.indicators["return_24bars"] = 0.00404
            symbol.indicators["rsi_14"] = 63.2
            symbol.indicators["sma_fast_ratio"] = 0.00222
            symbol.indicators["sma_slow_ratio"] = 0.00299
            symbol.recent_candles[-1].open = 87.04
            symbol.recent_candles[-1].high = 87.10
            symbol.recent_candles[-1].low = 86.97
            symbol.recent_candles[-1].close = 87.07
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )

            filtered = filter_service.apply(bundle)

            self.assertEqual(filtered.status, "selected")
            sol_summary = filtered.summary["symbols"][0]
            self.assertIn("long_setup_late_breakout_soft_penalty", sol_summary["reasons"])
            self.assertEqual(sol_summary["setup_phase"], "long_late_breakout_chase")

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

    def test_candidate_filter_blocks_eth_short_continuation_open_in_short_rebound_research_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                rule_mode="bottom_line",
                setup_model_enable=False,
                setup_model_path=root / "state" / "models" / "setup_edge_model_short_rebound_phase6.json",
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            filter_service = CandidateFilter(settings, journal)

            symbol = make_symbol(
                "ETH/USDT:USDT",
                900_000,
                2_058.11,
                atr_pct=0.00165,
                range_pct=0.00121,
                volume_ratio=0.73,
                higher_bias="short",
                higher_phase="trend",
            )
            symbol.indicators["return_1bar"] = -0.00055
            symbol.indicators["return_24bars"] = -0.00197
            symbol.indicators["rsi_14"] = 46.9
            symbol.indicators["sma_fast_ratio"] = -0.00093
            symbol.indicators["sma_slow_ratio"] = -0.00142
            symbol.recent_candles[-1].open = 2058.20
            symbol.recent_candles[-1].high = 2058.39
            symbol.recent_candles[-1].low = 2057.94
            symbol.recent_candles[-1].close = 2058.11
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )

            filtered = filter_service.apply(bundle)

            self.assertEqual(filtered.status, "filtered_hold")
            self.assertEqual(filtered.summary["selected_symbols"], [])
            summary = filtered.summary["symbols"][0]
            self.assertIn("short_setup_pre_breakdown_watch", summary["reasons"])
            self.assertIn("eth_short_research_blocks_short_continuation_open", summary["reasons"])

    def test_candidate_filter_demotes_low_volatility_fresh_entry_without_continuation_watch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("SOL/USDT:USDT", "BTC/USDT:USDT"),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            filter_service = CandidateFilter(settings, journal)

            weak_sol = make_symbol("SOL/USDT:USDT", 900_000, 91.2, atr_pct=0.00192, range_pct=0.00198, volume_ratio=1.80, higher_bias="short")
            weak_sol.indicators["return_1bar"] = -0.0002
            weak_sol.indicators["return_24bars"] = -0.0007
            weak_sol.indicators["rsi_14"] = 48.0
            weak_sol.indicators["sma_fast_ratio"] = -0.0007
            weak_sol.indicators["sma_slow_ratio"] = -0.0009
            weak_sol.recent_candles[-1].open = 91.28
            weak_sol.recent_candles[-1].high = 91.31
            weak_sol.recent_candles[-1].low = 91.12
            weak_sol.recent_candles[-1].close = 91.2

            clean_btc = make_symbol("BTC/USDT:USDT", 900_000, 103_000.0, atr_pct=0.00202, range_pct=0.00204, volume_ratio=1.60, higher_bias="short")
            clean_btc.indicators["return_1bar"] = -0.0007
            clean_btc.indicators["return_24bars"] = -0.0016
            clean_btc.indicators["rsi_14"] = 46.0
            clean_btc.indicators["sma_fast_ratio"] = -0.0011
            clean_btc.indicators["sma_slow_ratio"] = -0.0014
            clean_btc.recent_candles[-1].open = 103_080.0
            clean_btc.recent_candles[-1].high = 103_110.0
            clean_btc.recent_candles[-1].low = 102_940.0
            clean_btc.recent_candles[-1].close = 103_000.0

            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[weak_sol, clean_btc],
                equity_quote=200.0,
                free_quote=200.0,
            )

            filtered = filter_service.apply(bundle)

            self.assertEqual(filtered.status, "selected")
            sol_summary = next(item for item in filtered.summary["symbols"] if item["symbol"] == "SOL/USDT:USDT")
            btc_summary = next(item for item in filtered.summary["symbols"] if item["symbol"] == "BTC/USDT:USDT")
            self.assertTrue(sol_summary["eligible"])
            self.assertTrue(btc_summary["eligible"])
            self.assertIn("low_volatility_soft_penalty", sol_summary["reasons"])
            self.assertNotIn("short_setup_pre_breakdown_watch", sol_summary["reasons"])
            self.assertGreater(btc_summary["score"], sol_summary["score"])

    def test_build_higher_timeframe_context_reports_reclaim_phase(self) -> None:
        closes = [
            100.0, 101.0, 102.0, 103.0, 104.0, 105.0,
            106.0, 107.0, 108.0, 109.0, 110.0, 111.0,
            112.0, 113.0, 114.0, 115.0, 116.0, 117.0,
            118.0, 119.0, 120.0, 121.0, 122.0, 123.0,
            122.0, 121.0, 119.0, 117.0, 118.0, 121.0,
        ]
        candles = [
            Candle(
                timestamp_ms=idx * 3_600_000,
                open=close - 0.4,
                high=close + 0.6,
                low=close - 0.8,
                close=close,
                volume=1000.0,
            )
            for idx, close in enumerate(closes)
        ]

        context = build_higher_timeframe_context_from_completed_candles(
            timeframe="1h",
            completed_candles=candles,
        )

        self.assertEqual(context["trend_direction"], "long")
        self.assertEqual(context["trend_phase"], "reclaim")
        self.assertGreater(context["fast_sma_slope"], 0.0)
        self.assertIn("distance_from_12bar_extreme", context)

    def test_hourly_model_fit_and_score_tracks_direction(self) -> None:
        def make_hourly_candles(start_price: float, drift: float) -> list[Candle]:
            candles: list[Candle] = []
            close = start_price
            for index in range(96):
                close *= 1.0 + drift + (0.0003 if index % 5 in {1, 2} else -0.00015)
                open_price = close * (1.0 - (0.0008 if drift > 0 else -0.0008))
                high = max(open_price, close) * 1.0012
                low = min(open_price, close) * 0.9988
                candles.append(
                    Candle(
                        timestamp_ms=index * 3_600_000,
                        open=open_price,
                        high=high,
                        low=low,
                        close=close,
                        volume=1_000.0 + (index % 7) * 50.0,
                    )
                )
            return candles

        up_candles = make_hourly_candles(100.0, 0.0010)
        down_candles = make_hourly_candles(100.0, -0.0010)
        up_model = fit_symbol_hourly_return_model(
            symbol="SOL/USDT:USDT",
            candles=up_candles,
            horizon_bars=3,
            ridge_alpha=0.0005,
        )
        down_model = fit_symbol_hourly_return_model(
            symbol="XRP/USDT:USDT",
            candles=down_candles,
            horizon_bars=3,
            ridge_alpha=0.0005,
        )
        model_bundle = {
            "symbols": {
                "SOL/USDT:USDT": up_model,
                "XRP/USDT:USDT": down_model,
            }
        }

        up_signal = score_hourly_return_model_signal(
            symbol="SOL/USDT:USDT",
            completed_candles=up_candles,
            model_bundle=model_bundle,
        )
        down_signal = score_hourly_return_model_signal(
            symbol="XRP/USDT:USDT",
            completed_candles=down_candles,
            model_bundle=model_bundle,
        )

        self.assertIsNotNone(up_signal)
        self.assertIsNotNone(down_signal)
        self.assertEqual(up_signal["direction"], "long")
        self.assertEqual(down_signal["direction"], "short")
        self.assertGreater(up_signal["prediction_strength"], 0.5)
        self.assertGreater(down_signal["prediction_strength"], 0.5)

    def test_candidate_filter_uses_hourly_model_signal_as_soft_rank_bonus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("SOL/USDT:USDT", "XRP/USDT:USDT"),
                rule_mode="bottom_line",
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            filter_service = CandidateFilter(settings, journal)

            aligned = make_symbol("SOL/USDT:USDT", 900_000, 100.0, atr_pct=0.0030, range_pct=0.0030, volume_ratio=1.05, higher_bias="short", higher_phase="trend")
            conflicting = make_symbol("XRP/USDT:USDT", 900_000, 1.50, atr_pct=0.0030, range_pct=0.0030, volume_ratio=1.05, higher_bias="short", higher_phase="trend")
            for symbol in (aligned, conflicting):
                symbol.indicators["return_1bar"] = -0.0004
                symbol.indicators["return_24bars"] = -0.0018
                symbol.indicators["rsi_14"] = 44.0
                symbol.indicators["sma_fast_ratio"] = -0.0011
                symbol.indicators["sma_slow_ratio"] = -0.0015
            aligned.higher_timeframe["model_signal"] = {
                "direction": "short",
                "prediction_strength": 1.4,
                "predicted_return_pct": -0.0020,
            }
            conflicting.higher_timeframe["model_signal"] = {
                "direction": "long",
                "prediction_strength": 1.4,
                "predicted_return_pct": 0.0020,
            }
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[aligned, conflicting],
                equity_quote=200.0,
                free_quote=200.0,
            )

            filtered = filter_service.apply(bundle)

            self.assertEqual(filtered.status, "selected")
            self.assertEqual(filtered.summary["selected_symbols"][0], "SOL/USDT:USDT")
            aligned_summary = next(item for item in filtered.summary["symbols"] if item["symbol"] == "SOL/USDT:USDT")
            conflicting_summary = next(item for item in filtered.summary["symbols"] if item["symbol"] == "XRP/USDT:USDT")
            self.assertGreater(aligned_summary["score"], conflicting_summary["score"])
            self.assertEqual(aligned_summary["hourly_model_signal"]["direction"], "short")

    def test_setup_edge_model_fit_and_score_for_short_breakdown(self) -> None:
        feature_rows = []
        targets = []
        for idx in range(80):
            feature_rows.append([
                -0.0008 - (idx * 0.00001),
                -0.0030 - (idx * 0.00002),
                -0.0012,
                -0.0018,
                -0.35,
                1.10,
                0.0024,
                2.0,
                -0.0004,
                -0.0005,
                0.72,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
            ])
            targets.append(0.00045 + idx * 0.000005)
        model_payload = fit_setup_edge_model(
            symbol_name="XRP/USDT:USDT",
            setup_phase="short_breakdown_confirmed",
            feature_rows=feature_rows,
            targets=targets,
            ridge_alpha=0.0005,
        )
        symbol = make_symbol(
            "XRP/USDT:USDT",
            900_000,
            1.4029,
            atr_pct=0.0021,
            range_pct=0.0027,
            volume_ratio=1.11,
            higher_bias="short",
            higher_phase="trend",
        )
        symbol.indicators["return_1bar"] = -0.0014
        symbol.indicators["return_24bars"] = -0.0088
        symbol.indicators["sma_fast_ratio"] = -0.0016
        symbol.indicators["sma_slow_ratio"] = -0.0058
        symbol.indicators["rsi_14"] = 27.5
        symbol.higher_timeframe["trend_strength"] = 2.0
        symbol.higher_timeframe["fast_sma_slope"] = -0.0004
        symbol.higher_timeframe["slow_sma_slope"] = -0.0005
        symbol.recent_candles = [
            Candle(timestamp_ms=1, open=1.4054, high=1.4083, low=1.4054, close=1.4067, volume=1_013_247.4),
            Candle(timestamp_ms=2, open=1.4066, high=1.4076, low=1.4054, close=1.4076, volume=513_950.0),
            Candle(timestamp_ms=3, open=1.4075, high=1.4080, low=1.4046, close=1.4053, volume=926_440.9),
            Candle(timestamp_ms=4, open=1.4052, high=1.4052, low=1.4035, close=1.4050, volume=1_061_209.3),
            Candle(timestamp_ms=5, open=1.4049, high=1.4054, low=1.4016, close=1.4029, volume=1_711_966.4),
        ]
        assessment = assess_fresh_entry(symbol, action="sell")
        traditional = build_traditional_signal_context(symbol, assessment)
        bundle = {
            "symbols": {
                "XRP/USDT:USDT": {
                    "short_breakdown_confirmed": model_payload,
                }
            }
        }

        signal = score_setup_edge_model_signal(
            symbol=symbol,
            assessment=assessment,
            traditional_signal_context=traditional,
            model_bundle=bundle,
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal["label"], "favorable")
        self.assertEqual(signal["quality"], "weak_favorable")
        self.assertGreater(signal["predicted_edge_pct"], 0.0)
        self.assertGreater(signal["sample_count"], 60)

    def test_setup_edge_model_prefers_matching_higher_timeframe_phase_submodel(self) -> None:
        feature_rows = [[0.0] * 16 for _ in range(20)]
        aggregate_model = fit_setup_edge_model(
            symbol_name="ETH/USDT:USDT",
            setup_phase="short_rebound_fail_confirmed",
            feature_rows=feature_rows,
            targets=[-0.0010] * 20,
            ridge_alpha=0.0005,
        )
        reclaim_model = fit_setup_edge_model(
            symbol_name="ETH/USDT:USDT",
            setup_phase="short_rebound_fail_confirmed",
            feature_rows=feature_rows,
            targets=[0.0042] * 20,
            ridge_alpha=0.0005,
        )
        symbol = make_symbol(
            "ETH/USDT:USDT",
            900_000,
            2400.0,
            atr_pct=0.0020,
            range_pct=0.0021,
            volume_ratio=1.05,
            higher_bias="short",
            higher_phase="reclaim",
        )
        symbol.indicators["return_1bar"] = -0.0004
        symbol.indicators["return_24bars"] = -0.0015
        symbol.indicators["rsi_14"] = 45.0
        symbol.indicators["sma_fast_ratio"] = -0.0011
        symbol.indicators["sma_slow_ratio"] = -0.0014
        symbol.higher_timeframe["trend_strength"] = 1.5
        symbol.recent_candles = [
            Candle(timestamp_ms=1, open=2404.0, high=2405.0, low=2399.0, close=2401.0, volume=1000.0),
            Candle(timestamp_ms=2, open=2401.0, high=2402.0, low=2398.0, close=2399.5, volume=1000.0),
            Candle(timestamp_ms=3, open=2399.5, high=2400.0, low=2396.0, close=2397.0, volume=1000.0),
            Candle(timestamp_ms=4, open=2397.0, high=2399.0, low=2396.5, close=2398.0, volume=1000.0),
            Candle(timestamp_ms=5, open=2398.0, high=2398.5, low=2394.0, close=2395.0, volume=1000.0),
        ]
        assessment = assess_fresh_entry(symbol, action="sell")
        traditional = build_traditional_signal_context(symbol, assessment)
        model_bundle = {
            "symbols": {
                "ETH/USDT:USDT": {
                    "short_rebound_fail_confirmed": {
                        "mode": "by_higher_timeframe_phase",
                        "aggregate": aggregate_model,
                        "by_higher_timeframe_phase": {
                            "reclaim": reclaim_model,
                        },
                    }
                }
            }
        }

        signal = score_setup_edge_model_signal(
            symbol=symbol,
            assessment=assessment,
            traditional_signal_context=traditional,
            model_bundle=model_bundle,
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal["higher_timeframe_phase"], "reclaim")
        self.assertEqual(signal["label"], "favorable")
        self.assertEqual(signal["quality"], "strong_favorable")
        self.assertGreater(signal["predicted_edge_pct"], 0.0)

    def test_setup_edge_model_signal_exposes_training_window_metadata(self) -> None:
        feature_rows = [[0.0] * 16 for _ in range(20)]
        model_payload = fit_setup_edge_model(
            symbol_name="XRP/USDT:USDT",
            setup_phase="short_breakdown_confirmed",
            feature_rows=feature_rows,
            targets=[0.0015] * 20,
            ridge_alpha=0.0005,
        )
        symbol = make_symbol(
            "XRP/USDT:USDT",
            900_000,
            1.4029,
            atr_pct=0.0021,
            range_pct=0.0027,
            volume_ratio=1.11,
            higher_bias="short",
            higher_phase="trend",
        )
        symbol.indicators["return_1bar"] = -0.0014
        symbol.indicators["return_24bars"] = -0.0088
        symbol.indicators["sma_fast_ratio"] = -0.0016
        symbol.indicators["sma_slow_ratio"] = -0.0058
        symbol.indicators["rsi_14"] = 27.5
        symbol.higher_timeframe["trend_strength"] = 2.0
        symbol.higher_timeframe["fast_sma_slope"] = -0.0004
        symbol.higher_timeframe["slow_sma_slope"] = -0.0005
        symbol.recent_candles = [
            Candle(timestamp_ms=1, open=1.4054, high=1.4083, low=1.4054, close=1.4067, volume=1_013_247.4),
            Candle(timestamp_ms=2, open=1.4066, high=1.4076, low=1.4054, close=1.4076, volume=513_950.0),
            Candle(timestamp_ms=3, open=1.4075, high=1.4080, low=1.4046, close=1.4053, volume=926_440.9),
            Candle(timestamp_ms=4, open=1.4052, high=1.4052, low=1.4035, close=1.4050, volume=1_061_209.3),
            Candle(timestamp_ms=5, open=1.4049, high=1.4054, low=1.4016, close=1.4029, volume=1_711_966.4),
        ]
        assessment = assess_fresh_entry(symbol, action="sell")
        traditional = build_traditional_signal_context(symbol, assessment)
        model_bundle = {
            "version": "setup_edge_ridge_v1",
            "timeframe": "5m",
            "higher_timeframe": "1h",
            "horizon_bars": 3,
            "trained_at": "2026-05-24T00:00:00+00:00",
            "training_cutoff_utc": "2026-05-24T00:15:00+00:00",
            "training_window": {
                "sample_window_start_utc": "2026-05-20T00:00:00+00:00",
                "sample_window_end_utc": "2026-05-24T00:00:00+00:00",
                "training_cutoff_utc": "2026-05-24T00:15:00+00:00",
                "lookback_days": 4,
                "horizon_bars": 3,
                "timeframe": "5m",
                "higher_timeframe": "1h",
                "example_count": 20,
            },
            "symbols": {
                "XRP/USDT:USDT": {
                    "short_breakdown_confirmed": model_payload,
                }
            },
        }

        signal = score_setup_edge_model_signal(
            symbol=symbol,
            assessment=assessment,
            traditional_signal_context=traditional,
            model_bundle=model_bundle,
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal["training_cutoff_utc"], "2026-05-24T00:15:00+00:00")
        self.assertEqual(signal["training_window"]["sample_window_start_utc"], "2026-05-20T00:00:00+00:00")
        self.assertEqual(signal["training_window"]["sample_window_end_utc"], "2026-05-24T00:00:00+00:00")

    def test_candidate_filter_attaches_setup_model_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
                setup_model_enable=True,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()

            symbol = make_symbol(
                "XRP/USDT:USDT",
                1_778_985_000_000,
                1.4029,
                atr_pct=0.002118061566347253,
                range_pct=0.0027086748877325722,
                volume_ratio=1.1123581133783067,
                higher_bias="short",
                higher_phase="trend",
            )
            symbol.indicators["return_1bar"] = -0.001494661921708218
            symbol.indicators["return_24bars"] = -0.008831425745372323
            symbol.indicators["sma_fast_ratio"] = -0.0016663800413926344
            symbol.indicators["sma_slow_ratio"] = -0.005885922061357074
            symbol.indicators["rsi_14"] = 27.522935779816038
            symbol.higher_timeframe["trend_strength"] = 2.0
            symbol.higher_timeframe["fast_sma_slope"] = -0.0004
            symbol.higher_timeframe["slow_sma_slope"] = -0.0005
            symbol.recent_candles = [
                Candle(timestamp_ms=1, open=1.4054, high=1.4083, low=1.4054, close=1.4067, volume=1_013_247.4),
                Candle(timestamp_ms=2, open=1.4066, high=1.4076, low=1.4054, close=1.4076, volume=513_950.0),
                Candle(timestamp_ms=3, open=1.4075, high=1.4080, low=1.4046, close=1.4053, volume=926_440.9),
                Candle(timestamp_ms=4, open=1.4052, high=1.4052, low=1.4035, close=1.4050, volume=1_061_209.3),
                Candle(timestamp_ms=5, open=1.4049, high=1.4054, low=1.4016, close=1.4029, volume=1_711_966.4),
            ]
            assessment = assess_fresh_entry(symbol, action="sell")
            traditional = build_traditional_signal_context(symbol, assessment)
            feature_map = build_setup_model_feature_map(symbol, assessment, traditional)
            model_payload = fit_setup_edge_model(
                symbol_name="XRP/USDT:USDT",
                setup_phase="short_breakdown_confirmed",
                feature_rows=[list(feature_map.values()) for _ in range(80)],
                targets=[0.0015] * 80,
                ridge_alpha=0.0005,
            )
            settings.setup_model_path.parent.mkdir(parents=True, exist_ok=True)
            settings.setup_model_path.write_text(
                json.dumps(
                    {
                        "symbols": {
                            "XRP/USDT:USDT": {
                                "short_breakdown_confirmed": model_payload,
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            filter_service = CandidateFilter(settings, journal)
            bundle = make_bundle(
                timestamp_ms=1_778_985_000_000,
                symbols=[symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )

            filtered = filter_service.apply(bundle)

            self.assertEqual(filtered.status, "selected")
            summary = filtered.summary["symbols"][0]
            self.assertEqual(summary["setup_model_signal"]["label"], "favorable")
            self.assertGreater(summary["setup_model_signal"]["predicted_edge_pct"], 0.0)

    def test_candidate_filter_blocks_unfavorable_short_rebound_fail_setup_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                setup_model_enable=True,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            feature_rows = [[0.0] * 16 for _ in range(33)]
            model_payload = fit_setup_edge_model(
                symbol_name="ETH/USDT:USDT",
                setup_phase="short_rebound_fail_confirmed",
                feature_rows=feature_rows,
                targets=[-0.0016] * 33,
                ridge_alpha=0.0005,
            )
            settings.setup_model_path.parent.mkdir(parents=True, exist_ok=True)
            settings.setup_model_path.write_text(
                json.dumps(
                    {
                        "symbols": {
                            "ETH/USDT:USDT": {
                                "short_rebound_fail_confirmed": model_payload
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            filter_service = CandidateFilter(settings, journal)

            symbol = make_symbol(
                "ETH/USDT:USDT",
                900_000,
                2_027.22,
                atr_pct=0.0024,
                range_pct=0.0023,
                volume_ratio=1.15,
                higher_bias="short",
                higher_phase="pullback",
            )
            symbol.indicators["return_1bar"] = -0.0024
            symbol.indicators["return_24bars"] = 0.00005
            symbol.indicators["rsi_14"] = 43.8
            symbol.indicators["sma_fast_ratio"] = -0.00196
            symbol.indicators["sma_slow_ratio"] = -0.00056
            symbol.recent_candles = [
                Candle(timestamp_ms=1, open=2037.0, high=2038.0, low=2032.0, close=2034.0, volume=1_000.0),
                Candle(timestamp_ms=2, open=2034.0, high=2035.0, low=2030.0, close=2031.0, volume=1_050.0),
                Candle(timestamp_ms=3, open=2031.0, high=2033.0, low=2029.0, close=2032.0, volume=1_100.0),
                Candle(timestamp_ms=4, open=2032.0, high=2033.0, low=2028.0, close=2029.5, volume=1_150.0),
                Candle(timestamp_ms=5, open=2033.0, high=2034.0, low=2027.0, close=2027.22, volume=1_300.0),
            ]
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )

            filtered = filter_service.apply(bundle)

            self.assertEqual(filtered.status, "filtered_hold")
            summary = filtered.summary["symbols"][0]
            self.assertIn("setup_model_unfavorable_short_rebound_fail", summary["reasons"])

    def test_candidate_filter_blocks_weak_eth_pullback_short_rebound_fail_setup_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                setup_model_enable=True,
                rule_mode="bottom_line",
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            settings.setup_model_path.parent.mkdir(parents=True, exist_ok=True)
            settings.setup_model_path.write_text(
                json.dumps(
                    {
                        "symbols": {
                            "ETH/USDT:USDT": {
                                "short_rebound_fail_confirmed": {
                                    "feature_means": [0.0] * 16,
                                    "feature_stds": [1.0] * 16,
                                    "weights": [0.0] * 16,
                                    "bias": 0.00085,
                                    "metrics": {
                                        "sample_count": 33,
                                        "mae_pct": 0.00160,
                                        "positive_edge_rate": 0.1818,
                                        "avg_target_edge_pct": -0.00160,
                                    },
                                }
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            filter_service = CandidateFilter(settings, journal)

            symbol = make_symbol(
                "ETH/USDT:USDT",
                900_000,
                2_323.49,
                atr_pct=0.0021,
                range_pct=0.0021,
                volume_ratio=3.05,
                higher_bias="short",
                higher_phase="pullback",
            )
            symbol.indicators["return_1bar"] = -0.0024
            symbol.indicators["return_24bars"] = -0.00128
            symbol.indicators["rsi_14"] = 33.1
            symbol.indicators["sma_fast_ratio"] = -0.00275
            symbol.indicators["sma_slow_ratio"] = -0.00198
            symbol.recent_candles = [
                Candle(timestamp_ms=1, open=2335.0, high=2336.0, low=2329.0, close=2332.0, volume=1_000.0),
                Candle(timestamp_ms=2, open=2332.0, high=2333.0, low=2326.0, close=2328.0, volume=1_100.0),
                Candle(timestamp_ms=3, open=2328.0, high=2330.0, low=2324.0, close=2327.0, volume=1_150.0),
                Candle(timestamp_ms=4, open=2327.0, high=2328.0, low=2321.0, close=2326.0, volume=1_300.0),
                Candle(timestamp_ms=5, open=2329.0, high=2330.0, low=2320.0, close=2323.49, volume=3_200.0),
            ]
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )

            filtered = filter_service.apply(bundle)

            self.assertEqual(filtered.status, "filtered_hold")
            summary = filtered.summary["symbols"][0]
            self.assertEqual(summary["setup_model_signal"]["quality"], "weak_favorable")
            self.assertIn("setup_model_weak_pullback_short_rebound_fail", summary["reasons"])

    def test_candidate_filter_blocks_low_sample_weak_eth_pullback_short_rebound_fail_setup_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                setup_model_enable=True,
                rule_mode="bottom_line",
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            settings.setup_model_path.parent.mkdir(parents=True, exist_ok=True)
            settings.setup_model_path.write_text(
                json.dumps(
                    {
                        "symbols": {
                            "ETH/USDT:USDT": {
                                "short_rebound_fail_confirmed": {
                                    "feature_means": [0.0] * 16,
                                    "feature_stds": [1.0] * 16,
                                    "weights": [0.0] * 16,
                                    "bias": 0.00167,
                                    "metrics": {
                                        "sample_count": 11,
                                        "mae_pct": 0.00056,
                                        "positive_edge_rate": 0.1818,
                                        "avg_target_edge_pct": -0.00196,
                                    },
                                }
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            filter_service = CandidateFilter(settings, journal)

            symbol = make_symbol(
                "ETH/USDT:USDT",
                900_000,
                2_027.22,
                atr_pct=0.0024,
                range_pct=0.0023,
                volume_ratio=1.15,
                higher_bias="short",
                higher_phase="pullback",
            )
            symbol.indicators["return_1bar"] = -0.0024
            symbol.indicators["return_24bars"] = 0.00005
            symbol.indicators["rsi_14"] = 43.8
            symbol.indicators["sma_fast_ratio"] = -0.00196
            symbol.indicators["sma_slow_ratio"] = -0.00056
            symbol.recent_candles = [
                Candle(timestamp_ms=1, open=2037.0, high=2038.0, low=2032.0, close=2034.0, volume=1_000.0),
                Candle(timestamp_ms=2, open=2034.0, high=2035.0, low=2030.0, close=2031.0, volume=1_050.0),
                Candle(timestamp_ms=3, open=2031.0, high=2033.0, low=2029.0, close=2032.0, volume=1_100.0),
                Candle(timestamp_ms=4, open=2032.0, high=2033.0, low=2028.0, close=2029.5, volume=1_150.0),
                Candle(timestamp_ms=5, open=2033.0, high=2034.0, low=2027.0, close=2027.22, volume=1_300.0),
            ]
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )

            filtered = filter_service.apply(bundle)

            self.assertEqual(filtered.status, "filtered_hold")
            summary = filtered.summary["symbols"][0]
            self.assertIn("setup_model_weak_pullback_short_rebound_fail", summary["reasons"])

    def test_candidate_filter_blocks_eth_range_noise_short_without_breakdown_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                partial_take_profit_trigger_pct=0.03,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            filter_service = CandidateFilter(settings, journal)

            symbol = make_symbol(
                "ETH/USDT:USDT",
                900_000,
                2_048.22,
                atr_pct=0.0022,
                range_pct=0.0021,
                volume_ratio=1.05,
                higher_bias="short",
                higher_phase="trend",
            )
            symbol.indicators["return_1bar"] = -0.00009
            symbol.indicators["return_24bars"] = -0.00959
            symbol.indicators["rsi_14"] = 29.3
            symbol.indicators["sma_fast_ratio"] = -0.0012
            symbol.indicators["sma_slow_ratio"] = -0.0013
            symbol.recent_candles[-1].open = 2055.0
            symbol.recent_candles[-1].high = 2056.0
            symbol.recent_candles[-1].low = 2048.0
            symbol.recent_candles[-1].close = 2048.22
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )

            filtered = filter_service.apply(bundle)

            self.assertEqual(filtered.status, "filtered_hold")
            summary = filtered.summary["symbols"][0]
            self.assertIn("eth_short_range_noise_requires_breakdown_structure", summary["reasons"])

    def test_candidate_filter_blocks_eth_fresh_range_noise_plain_open_in_short_research_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                rule_mode="bottom_line",
                setup_model_enable=False,
                setup_model_path=root / "state" / "models" / "setup_edge_model_short_rebound_phase6.json",
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            filter_service = CandidateFilter(settings, journal)

            symbol = make_symbol(
                "ETH/USDT:USDT",
                900_000,
                2_049.88,
                atr_pct=0.00533,
                range_pct=0.00685,
                volume_ratio=1.36,
                higher_bias="long",
                higher_phase="trend",
            )
            symbol.indicators["return_1bar"] = 0.00264
            symbol.indicators["return_24bars"] = 0.01632
            symbol.indicators["rsi_14"] = 63.62
            symbol.indicators["sma_fast_ratio"] = 0.00139
            symbol.indicators["sma_slow_ratio"] = 0.01040
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )

            filtered = filter_service.apply(bundle)

            self.assertEqual(filtered.status, "filtered_hold")
            self.assertEqual(filtered.summary["selected_symbols"], [])
            summary = filtered.summary["symbols"][0]
            self.assertIn("eth_short_research_blocks_fresh_outside_short_trend_family_open", summary["reasons"])

    def test_risk_engine_blocks_eth_fresh_long_open_in_short_research_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                rule_mode="bottom_line",
                setup_model_enable=False,
                setup_model_path=root / "state" / "models" / "setup_edge_model_short_rebound_phase6.json",
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            symbol = make_symbol(
                "ETH/USDT:USDT",
                900_000,
                2_049.88,
                atr_pct=0.00533,
                range_pct=0.00440,
                volume_ratio=0.95,
                higher_bias="short",
                higher_phase="trend",
            )
            symbol.indicators["return_1bar"] = 0.00050
            symbol.indicators["return_24bars"] = 0.00300
            symbol.indicators["rsi_14"] = 55.0
            symbol.indicators["sma_fast_ratio"] = 0.00040
            symbol.indicators["sma_slow_ratio"] = 0.00080
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )

            long_verdict = risk_engine.evaluate(make_decision("ETH/USDT:USDT", "buy"), bundle)
            short_verdict = risk_engine.evaluate(make_decision("ETH/USDT:USDT", "sell"), bundle)

            self.assertEqual(long_verdict.final_action, "hold")
            self.assertIn("eth_short_research_blocks_fresh_long_open", long_verdict.reasons)
            self.assertEqual(short_verdict.final_action, "sell")
            self.assertNotIn("eth_short_research_blocks_fresh_long_open", short_verdict.reasons)

    def test_risk_engine_blocks_eth_fresh_reclaim_short_open_with_weak_trend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                rule_mode="bottom_line",
                setup_model_enable=False,
                setup_model_path=root / "state" / "models" / "setup_edge_model_short_rebound_phase6.json",
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            reclaim_symbol = make_symbol(
                "ETH/USDT:USDT",
                900_000,
                2_316.88,
                atr_pct=0.00195,
                range_pct=0.00214,
                volume_ratio=1.23,
                higher_bias="short",
                higher_phase="reclaim",
            )
            reclaim_symbol.higher_timeframe["trend_strength"] = 1.447231
            reclaim_symbol.indicators["return_1bar"] = -0.00183
            reclaim_symbol.indicators["return_24bars"] = -0.00360
            reclaim_symbol.indicators["rsi_14"] = 39.58
            reclaim_symbol.indicators["sma_fast_ratio"] = -0.00116
            reclaim_symbol.indicators["sma_slow_ratio"] = -0.00090
            reclaim_bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[reclaim_symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )

            trend_symbol = make_symbol(
                "ETH/USDT:USDT",
                900_000,
                2_316.88,
                atr_pct=0.00195,
                range_pct=0.00214,
                volume_ratio=1.23,
                higher_bias="short",
                higher_phase="trend",
            )
            trend_symbol.higher_timeframe["trend_strength"] = 3.0
            trend_symbol.indicators["return_1bar"] = -0.00183
            trend_symbol.indicators["return_24bars"] = -0.00360
            trend_symbol.indicators["rsi_14"] = 39.58
            trend_symbol.indicators["sma_fast_ratio"] = -0.00116
            trend_symbol.indicators["sma_slow_ratio"] = -0.00090
            trend_bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[trend_symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )
            local_breakdown_symbol = make_symbol(
                "ETH/USDT:USDT",
                900_000,
                2_316.88,
                atr_pct=0.00163,
                range_pct=0.00341,
                volume_ratio=3.13,
                higher_bias="short",
                higher_phase="reclaim",
            )
            local_breakdown_symbol.higher_timeframe["trend_strength"] = 1.447231
            local_breakdown_symbol.indicators["return_1bar"] = -0.00186
            local_breakdown_symbol.indicators["return_24bars"] = -0.00085
            local_breakdown_symbol.indicators["rsi_14"] = 39.58
            local_breakdown_symbol.indicators["sma_fast_ratio"] = -0.00116
            local_breakdown_symbol.indicators["sma_slow_ratio"] = -0.00090
            local_breakdown_bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[local_breakdown_symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )

            reclaim_verdict = risk_engine.evaluate(make_decision("ETH/USDT:USDT", "sell"), reclaim_bundle)
            trend_verdict = risk_engine.evaluate(make_decision("ETH/USDT:USDT", "sell"), trend_bundle)
            local_breakdown_verdict = risk_engine.evaluate(
                make_decision("ETH/USDT:USDT", "sell"),
                local_breakdown_bundle,
            )

            self.assertEqual(reclaim_verdict.final_action, "hold")
            self.assertIn("eth_short_research_blocks_fresh_reclaim_short_open", reclaim_verdict.reasons)
            self.assertEqual(trend_verdict.final_action, "sell")
            self.assertNotIn("eth_short_research_blocks_fresh_reclaim_short_open", trend_verdict.reasons)
            self.assertEqual(local_breakdown_verdict.final_action, "sell")
            self.assertNotIn(
                "eth_short_research_blocks_fresh_reclaim_short_open",
                local_breakdown_verdict.reasons,
            )

    def test_candidate_filter_blocks_low_score_eth_trend_short_rebound_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                rule_mode="bottom_line",
                setup_model_enable=False,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            filter_service = CandidateFilter(settings, journal)

            symbol = make_symbol(
                "ETH/USDT:USDT",
                900_000,
                2_021.46,
                atr_pct=0.001959686845858228,
                range_pct=0.0039031195274702936,
                volume_ratio=1.6271538576041533,
                higher_bias="short",
                higher_phase="trend",
            )
            symbol.indicators["return_1bar"] = -0.003681743579127983
            symbol.indicators["return_24bars"] = 0.0005246485844387916
            symbol.indicators["rsi_14"] = 29.810568295114535
            symbol.indicators["sma_fast_ratio"] = -0.005939565109419287
            symbol.indicators["sma_slow_ratio"] = -0.0032029385918863618
            symbol.higher_timeframe = {
                "timeframe": "1h",
                "return_12bars": -0.02000423166439047,
                "sma_fast_ratio": 0.0009229332332498785,
                "sma_slow_ratio": -0.004420474509451822,
                "rsi_14": 34.145492516533224,
                "trend_bias": "short",
                "trend_direction": "short",
                "trend_phase": "trend",
                "trend_strength": 3.0,
                "fast_sma_slope": -0.0016997234272143613,
                "slow_sma_slope": -0.0001408360983272683,
                "distance_to_fast_sma": 0.0009229332332498785,
                "distance_to_slow_sma": -0.004420474509451822,
                "distance_from_12bar_extreme": -0.010883432452059916,
            }
            symbol.recent_candles = [
                Candle(timestamp_ms=1, open=2020.4, high=2020.6, low=2019.23, close=2019.86, volume=3422.357),
                Candle(timestamp_ms=2, open=2019.86, high=2020.54, low=2017.04, close=2019.56, volume=6894.667),
                Candle(timestamp_ms=3, open=2019.55, high=2022.0, low=2018.95, close=2019.29, volume=6154.979),
                Candle(timestamp_ms=4, open=2019.29, high=2021.81, low=2018.5, close=2020.28, volume=5656.815),
                Candle(timestamp_ms=5, open=2020.28, high=2021.31, low=2017.22, close=2019.37, volume=8436.573),
                Candle(timestamp_ms=6, open=2019.37, high=2020.19, low=2018.34, close=2018.98, volume=3838.74),
                Candle(timestamp_ms=7, open=2018.98, high=2023.85, low=2018.98, close=2022.83, volume=7253.955),
                Candle(timestamp_ms=8, open=2022.84, high=2025.69, low=2022.38, close=2024.72, volume=10891.657),
                Candle(timestamp_ms=9, open=2024.73, high=2027.0, low=2024.37, close=2026.87, volume=7457.033),
                Candle(timestamp_ms=10, open=2026.87, high=2036.06, low=2026.35, close=2033.61, volume=45827.583),
                Candle(timestamp_ms=11, open=2033.62, high=2036.61, low=2032.01, close=2035.08, volume=30611.181),
                Candle(timestamp_ms=12, open=2035.07, high=2035.5, low=2031.5, close=2032.41, volume=9720.049),
                Candle(timestamp_ms=13, open=2032.4, high=2034.79, low=2031.7, close=2032.87, volume=6845.569),
                Candle(timestamp_ms=14, open=2032.86, high=2035.31, low=2032.4, close=2034.99, volume=6795.701),
                Candle(timestamp_ms=15, open=2034.99, high=2041.0, low=2034.99, close=2038.61, volume=19239.676),
                Candle(timestamp_ms=16, open=2038.6, high=2038.93, low=2036.19, close=2037.96, volume=10633.077),
                Candle(timestamp_ms=17, open=2037.96, high=2040.38, low=2037.11, close=2038.67, volume=16831.241),
                Candle(timestamp_ms=18, open=2038.67, high=2039.46, low=2034.62, close=2035.42, volume=10441.832),
                Candle(timestamp_ms=19, open=2035.41, high=2037.07, low=2035.22, close=2036.01, volume=5177.304),
                Candle(timestamp_ms=20, open=2036.02, high=2036.27, low=2033.33, close=2033.75, volume=12374.097),
                Candle(timestamp_ms=21, open=2033.75, high=2034.74, low=2030.58, close=2032.17, volume=10206.608),
                Candle(timestamp_ms=22, open=2032.17, high=2033.01, low=2030.3, close=2031.62, volume=4983.52),
                Candle(timestamp_ms=23, open=2031.62, high=2031.62, low=2027.17, close=2028.93, volume=8383.93),
                Candle(timestamp_ms=24, open=2028.94, high=2028.95, low=2021.06, close=2021.46, volume=20206.624),
            ]
            bundle = make_bundle(timestamp_ms=900_000, symbols=[symbol], equity_quote=200.0, free_quote=200.0)

            filtered = filter_service.apply(bundle)

            self.assertEqual(filtered.status, "filtered_hold")
            summary = filtered.summary["symbols"][0]
            self.assertEqual(summary["setup_phase"], "short_rebound_fail_confirmed")
            self.assertLess(summary["score"], 8.0)
            self.assertIn("eth_short_rebound_fail_trend_low_score", summary["reasons"])

    def test_candidate_filter_blocks_terminal_flush_eth_trend_short_rebound_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                rule_mode="bottom_line",
                setup_model_enable=False,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            filter_service = CandidateFilter(settings, journal)

            symbol = make_symbol(
                "ETH/USDT:USDT",
                900_000,
                2_016.23,
                atr_pct=0.0022333052989277793,
                range_pct=0.006040977467848442,
                volume_ratio=5.512083828630007,
                higher_bias="short",
                higher_phase="trend",
            )
            symbol.indicators["return_1bar"] = -0.002587238926320623
            symbol.indicators["return_24bars"] = -0.001797154258215805
            symbol.indicators["rsi_14"] = 22.156573116690964
            symbol.indicators["sma_fast_ratio"] = -0.00783488109073227
            symbol.indicators["sma_slow_ratio"] = -0.005629683697096821
            symbol.higher_timeframe = {
                "timeframe": "1h",
                "return_12bars": -0.02000423166439047,
                "sma_fast_ratio": 0.0009229332332498785,
                "sma_slow_ratio": -0.004420474509451822,
                "rsi_14": 34.145492516533224,
                "trend_bias": "short",
                "trend_direction": "short",
                "trend_phase": "trend",
                "trend_strength": 3.0,
                "fast_sma_slope": -0.0016997234272143613,
                "slow_sma_slope": -0.0001408360983272683,
                "distance_to_fast_sma": 0.0009229332332498785,
                "distance_to_slow_sma": -0.004420474509451822,
                "distance_from_12bar_extreme": -0.010883432452059916,
            }
            symbol.recent_candles = [
                Candle(timestamp_ms=1, open=2019.86, high=2020.54, low=2017.04, close=2019.56, volume=6894.667),
                Candle(timestamp_ms=2, open=2019.55, high=2022.0, low=2018.95, close=2019.29, volume=6154.979),
                Candle(timestamp_ms=3, open=2019.29, high=2021.81, low=2018.5, close=2020.28, volume=5656.815),
                Candle(timestamp_ms=4, open=2020.28, high=2021.31, low=2017.22, close=2019.37, volume=8436.573),
                Candle(timestamp_ms=5, open=2019.37, high=2020.19, low=2018.34, close=2018.98, volume=3838.74),
                Candle(timestamp_ms=6, open=2018.98, high=2023.85, low=2018.98, close=2022.83, volume=7253.955),
                Candle(timestamp_ms=7, open=2022.84, high=2025.69, low=2022.38, close=2024.72, volume=10891.657),
                Candle(timestamp_ms=8, open=2024.73, high=2027.0, low=2024.37, close=2026.87, volume=7457.033),
                Candle(timestamp_ms=9, open=2026.87, high=2036.06, low=2026.35, close=2033.61, volume=45827.583),
                Candle(timestamp_ms=10, open=2033.62, high=2036.61, low=2032.01, close=2035.08, volume=30611.181),
                Candle(timestamp_ms=11, open=2035.07, high=2035.5, low=2031.5, close=2032.41, volume=9720.049),
                Candle(timestamp_ms=12, open=2032.4, high=2034.79, low=2031.7, close=2032.87, volume=6845.569),
                Candle(timestamp_ms=13, open=2032.86, high=2035.31, low=2032.4, close=2034.99, volume=6795.701),
                Candle(timestamp_ms=14, open=2034.99, high=2041.0, low=2034.99, close=2038.61, volume=19239.676),
                Candle(timestamp_ms=15, open=2038.6, high=2038.93, low=2036.19, close=2037.96, volume=10633.077),
                Candle(timestamp_ms=16, open=2037.96, high=2040.38, low=2037.11, close=2038.67, volume=16831.241),
                Candle(timestamp_ms=17, open=2038.67, high=2039.46, low=2034.62, close=2035.42, volume=10441.832),
                Candle(timestamp_ms=18, open=2035.41, high=2037.07, low=2035.22, close=2036.01, volume=5177.304),
                Candle(timestamp_ms=19, open=2036.02, high=2036.27, low=2033.33, close=2033.75, volume=12374.097),
                Candle(timestamp_ms=20, open=2033.75, high=2034.74, low=2030.58, close=2032.17, volume=10206.608),
                Candle(timestamp_ms=21, open=2032.17, high=2033.01, low=2030.3, close=2031.62, volume=4983.52),
                Candle(timestamp_ms=22, open=2031.62, high=2031.62, low=2027.17, close=2028.93, volume=8383.93),
                Candle(timestamp_ms=23, open=2028.94, high=2028.95, low=2021.06, close=2021.46, volume=20206.624),
                Candle(timestamp_ms=24, open=2021.46, high=2022.18, low=2010.0, close=2016.23, volume=71865.788),
            ]
            bundle = make_bundle(timestamp_ms=900_000, symbols=[symbol], equity_quote=200.0, free_quote=200.0)

            filtered = filter_service.apply(bundle)

            self.assertEqual(filtered.status, "filtered_hold")
            summary = filtered.summary["symbols"][0]
            self.assertEqual(summary["setup_phase"], "short_rebound_fail_confirmed")
            self.assertIn("eth_short_rebound_fail_trend_terminal_flush", summary["reasons"])

    def test_candidate_filter_allows_high_score_eth_trend_short_rebound_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                rule_mode="bottom_line",
                setup_model_enable=False,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            filter_service = CandidateFilter(settings, journal)

            symbol = make_symbol(
                "ETH/USDT:USDT",
                900_000,
                2_055.61,
                atr_pct=0.00215716294155299,
                range_pct=0.005107972815855147,
                volume_ratio=1.8277009067492738,
                higher_bias="short",
                higher_phase="trend",
            )
            symbol.indicators["return_1bar"] = -0.003799462065957382
            symbol.indicators["return_24bars"] = 0.0007643473350080754
            symbol.indicators["rsi_14"] = 39.865728900256016
            symbol.indicators["sma_fast_ratio"] = -0.0029619330169842195
            symbol.indicators["sma_slow_ratio"] = -0.005295652242289783
            symbol.higher_timeframe = {
                "timeframe": "1h",
                "return_12bars": -0.00824836475567503,
                "sma_fast_ratio": -0.005721463302713614,
                "sma_slow_ratio": -0.01059632677198874,
                "rsi_14": 34.359356694003736,
                "trend_bias": "short",
                "trend_direction": "short",
                "trend_phase": "trend",
                "trend_strength": 3.0,
                "fast_sma_slope": -0.0006886405232220394,
                "slow_sma_slope": -0.0018564323094651947,
                "distance_to_fast_sma": -0.005721463302713614,
                "distance_to_slow_sma": -0.01059632677198874,
                "distance_from_12bar_extreme": -0.008695230474527915,
            }
            symbol.recent_candles = [
                Candle(timestamp_ms=1, open=2054.04, high=2056.6, low=2050.24, close=2051.87, volume=18248.425),
                Candle(timestamp_ms=2, open=2051.88, high=2057.78, low=2051.46, close=2055.63, volume=13049.761),
                Candle(timestamp_ms=3, open=2055.62, high=2060.71, low=2055.12, close=2058.71, volume=15794.072),
                Candle(timestamp_ms=4, open=2058.71, high=2063.67, low=2057.34, close=2062.1, volume=25601.432),
                Candle(timestamp_ms=5, open=2062.11, high=2063.56, low=2060.0, close=2062.13, volume=9861.05),
                Candle(timestamp_ms=6, open=2062.13, high=2063.84, low=2060.5, close=2062.59, volume=9483.289),
                Candle(timestamp_ms=7, open=2062.6, high=2065.28, low=2060.6, close=2063.08, volume=8906.806),
                Candle(timestamp_ms=8, open=2063.09, high=2066.81, low=2062.44, close=2066.11, volume=9091.605),
                Candle(timestamp_ms=9, open=2066.11, high=2068.32, low=2064.0, close=2067.28, volume=15259.217),
                Candle(timestamp_ms=10, open=2067.28, high=2067.43, low=2061.51, close=2061.95, volume=21327.395),
                Candle(timestamp_ms=11, open=2061.96, high=2062.42, low=2060.3, close=2062.01, volume=8822.581),
                Candle(timestamp_ms=12, open=2062.02, high=2063.74, low=2061.02, close=2062.72, volume=8266.384),
                Candle(timestamp_ms=13, open=2062.73, high=2065.32, low=2061.62, close=2063.18, volume=7596.889),
                Candle(timestamp_ms=14, open=2063.17, high=2066.6, low=2061.54, close=2064.54, volume=8940.594),
                Candle(timestamp_ms=15, open=2064.53, high=2065.27, low=2061.83, close=2062.05, volume=5180.137),
                Candle(timestamp_ms=16, open=2062.06, high=2062.25, low=2058.01, close=2059.19, volume=13460.006),
                Candle(timestamp_ms=17, open=2059.2, high=2060.7, low=2056.68, close=2058.11, volume=12030.37),
                Candle(timestamp_ms=18, open=2058.1, high=2065.34, low=2056.56, close=2063.35, volume=11544.165),
                Candle(timestamp_ms=19, open=2063.36, high=2064.3, low=2061.48, close=2062.15, volume=4087.213),
                Candle(timestamp_ms=20, open=2062.14, high=2065.23, low=2061.7, close=2064.01, volume=5794.864),
                Candle(timestamp_ms=21, open=2064.01, high=2066.3, low=2063.79, close=2064.15, volume=5582.318),
                Candle(timestamp_ms=22, open=2064.15, high=2064.58, low=2060.48, close=2060.81, volume=5681.802),
                Candle(timestamp_ms=23, open=2060.81, high=2065.0, low=2060.46, close=2063.45, volume=4921.559),
                Candle(timestamp_ms=24, open=2063.46, high=2063.88, low=2053.38, close=2055.61, volume=16914.722),
            ]
            bundle = make_bundle(timestamp_ms=900_000, symbols=[symbol], equity_quote=200.0, free_quote=200.0)

            filtered = filter_service.apply(bundle)

            self.assertEqual(filtered.status, "selected")
            summary = filtered.summary["symbols"][0]
            self.assertEqual(summary["setup_phase"], "short_rebound_fail_confirmed")
            self.assertGreaterEqual(summary["score"], 8.0)
            self.assertNotIn("eth_short_rebound_fail_trend_low_score", summary["reasons"])

    def test_candidate_filter_blocks_weak_favorable_eth_reclaim_short_rebound_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                rule_mode="bottom_line",
                setup_model_enable=False,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            filter_service = CandidateFilter(settings, journal)
            filter_service.setup_model_bundle = {
                "symbols": {
                    "ETH/USDT:USDT": {
                        "short_rebound_fail_confirmed": {
                            "bias": 0.0011676390401934057,
                            "weights": [0.0] * 16,
                            "feature_means": [0.0] * 16,
                            "feature_stds": [1.0] * 16,
                            "metrics": {
                                "mae_pct": 0.001625,
                                "positive_edge_rate": 0.42857142857142855,
                                "avg_target_edge_pct": 0.0002192329316656445,
                                "sample_count": 21,
                            },
                        }
                    }
                }
            }

            symbol = make_symbol(
                "ETH/USDT:USDT",
                900_000,
                2023.0,
                atr_pct=0.0019465433232116493,
                range_pct=0.00213544241225899,
                volume_ratio=1.2327784023246116,
                higher_bias="short",
                higher_phase="reclaim",
            )
            symbol.indicators["return_1bar"] = -0.0018305529651504449
            symbol.indicators["return_24bars"] = -0.00359552775451899
            symbol.indicators["rsi_14"] = 27.74001699235336
            symbol.indicators["sma_fast_ratio"] = -0.0022609008010765486
            symbol.indicators["sma_slow_ratio"] = -0.0028540202479042653
            symbol.recent_candles = [
                Candle(timestamp_ms=1772143500000, open=2030.31, high=2031.0, low=2028.69, close=2031.0, volume=3479.148),
                Candle(timestamp_ms=1772143800000, open=2031.0, high=2033.59, low=2030.37, close=2031.38, volume=5142.636),
                Candle(timestamp_ms=1772144100000, open=2031.37, high=2032.06, low=2028.83, close=2028.97, volume=3266.036),
                Candle(timestamp_ms=1772144400000, open=2028.97, high=2029.27, low=2026.19, close=2027.9, volume=5083.36),
                Candle(timestamp_ms=1772144700000, open=2027.91, high=2028.87, low=2026.69, close=2028.51, volume=2202.376),
                Candle(timestamp_ms=1772145000000, open=2028.51, high=2031.58, low=2028.01, close=2029.74, volume=4576.825),
                Candle(timestamp_ms=1772145300000, open=2029.74, high=2034.3, low=2029.73, close=2032.64, volume=5825.927),
                Candle(timestamp_ms=1772145600000, open=2032.63, high=2035.89, low=2031.51, close=2035.74, volume=6099.856),
                Candle(timestamp_ms=1772145900000, open=2035.74, high=2036.94, low=2033.0, close=2035.85, volume=4063.701),
                Candle(timestamp_ms=1772146200000, open=2035.85, high=2035.85, low=2031.01, close=2033.48, volume=3914.1),
                Candle(timestamp_ms=1772146500000, open=2033.47, high=2033.48, low=2030.08, close=2032.15, volume=2778.628),
                Candle(timestamp_ms=1772146800000, open=2032.14, high=2032.2, low=2024.89, close=2027.22, volume=11825.824),
                Candle(timestamp_ms=1772147100000, open=2027.21, high=2027.7, low=2023.03, close=2026.39, volume=8465.326),
                Candle(timestamp_ms=1772147400000, open=2026.39, high=2030.73, low=2025.67, close=2028.98, volume=3735.219),
                Candle(timestamp_ms=1772147700000, open=2028.98, high=2029.3, low=2026.36, close=2028.32, volume=3149.477),
                Candle(timestamp_ms=1772148000000, open=2028.32, high=2031.95, low=2028.31, close=2030.34, volume=3612.563),
                Candle(timestamp_ms=1772148300000, open=2030.34, high=2032.56, low=2029.69, close=2030.32, volume=2992.677),
                Candle(timestamp_ms=1772148600000, open=2030.32, high=2030.99, low=2028.52, close=2030.99, volume=3603.208),
                Candle(timestamp_ms=1772148900000, open=2031.0, high=2031.16, low=2026.52, close=2027.88, volume=5299.722),
                Candle(timestamp_ms=1772149200000, open=2027.88, high=2028.75, low=2025.03, close=2026.38, volume=3472.066),
                Candle(timestamp_ms=1772149500000, open=2026.38, high=2027.56, low=2025.21, close=2025.46, volume=3835.66),
                Candle(timestamp_ms=1772149800000, open=2025.47, high=2027.63, low=2023.25, close=2026.24, volume=7605.686),
                Candle(timestamp_ms=1772150100000, open=2026.24, high=2028.69, low=2025.33, close=2026.71, volume=3997.403),
                Candle(timestamp_ms=1772150400000, open=2026.7, high=2026.71, low=2022.39, close=2023.0, volume=5908.009),
            ]
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )

            filtered = filter_service.apply(bundle)

            self.assertEqual(filtered.status, "filtered_hold")
            self.assertEqual(filtered.summary["selected_symbols"], [])
            summary = filtered.summary["symbols"][0]
            self.assertEqual(summary["setup_model_signal"]["quality"], "weak_favorable")
            self.assertIn("setup_model_weak_reclaim_short_rebound_fail", summary["reasons"])

    def test_candidate_filter_allows_eth_range_noise_short_with_strong_breakdown_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                setup_model_enable=True,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            model_payload = fit_setup_edge_model(
                symbol_name="ETH/USDT:USDT",
                setup_phase="range_noise",
                feature_rows=[[0.0] * 16 for _ in range(40)],
                targets=[-0.00110] * 40,
                ridge_alpha=0.0005,
            )
            settings.setup_model_path.parent.mkdir(parents=True, exist_ok=True)
            settings.setup_model_path.write_text(
                json.dumps(
                    {
                        "symbols": {
                            "ETH/USDT:USDT": {
                                "range_noise": model_payload,
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            filter_service = CandidateFilter(settings, journal)

            symbol = make_symbol(
                "ETH/USDT:USDT",
                900_000,
                2_045.95,
                atr_pct=0.0029,
                range_pct=0.0029,
                volume_ratio=1.30,
                higher_bias="short",
                higher_phase="trend",
            )
            symbol.indicators["return_1bar"] = -0.00009
            symbol.indicators["return_24bars"] = -0.01140
            symbol.indicators["rsi_14"] = 28.2
            symbol.indicators["sma_fast_ratio"] = -0.0019
            symbol.indicators["sma_slow_ratio"] = -0.0013
            symbol.recent_candles = [
                Candle(timestamp_ms=1, open=2068.0, high=2070.0, low=2060.0, close=2062.0, volume=900.0),
                Candle(timestamp_ms=2, open=2062.0, high=2064.0, low=2056.0, close=2058.0, volume=930.0),
                Candle(timestamp_ms=3, open=2058.0, high=2060.0, low=2055.0, close=2057.0, volume=880.0),
                Candle(timestamp_ms=4, open=2057.0, high=2058.0, low=2053.0, close=2054.0, volume=950.0),
                Candle(timestamp_ms=5, open=2058.0, high=2059.0, low=2045.5, close=2045.95, volume=1300.0),
            ]
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )

            filtered = filter_service.apply(bundle)

            self.assertEqual(filtered.status, "selected")
            summary = filtered.summary["symbols"][0]
            self.assertNotIn("eth_short_range_noise_requires_breakdown_structure", summary["reasons"])
            self.assertNotIn("setup_model_unfavorable_eth_range_noise_long", summary["reasons"])
            self.assertEqual(
                summary["entry_thesis_candidate"]["setup_phase"],
                "eth_structural_range_noise_short",
            )

    def test_setup_edge_study_reports_positive_and_negative_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(root, market_type="future")

            class _StubSetupStudyService(SetupEdgeModelService):
                def _collect_examples(self, **kwargs):
                    return [
                        {
                            "symbol": "XRP/USDT:USDT",
                            "timestamp_ms": 1,
                            "setup_phase": "short_breakdown_confirmed",
                            "higher_timeframe_phase": "trend",
                            "traditional_pattern_label": "failed_rebound_breakdown",
                            "target_edge_pct": 0.0012,
                            "conviction_score": 0.72,
                            "terminal_risk": False,
                            "feature_vector": [0.0] * 16,
                        },
                        {
                            "symbol": "XRP/USDT:USDT",
                            "timestamp_ms": 2,
                            "setup_phase": "short_breakdown_confirmed",
                            "higher_timeframe_phase": "trend",
                            "traditional_pattern_label": "failed_rebound_breakdown",
                            "target_edge_pct": 0.0008,
                            "conviction_score": 0.68,
                            "terminal_risk": False,
                            "feature_vector": [0.0] * 16,
                        },
                        {
                            "symbol": "SOL/USDT:USDT",
                            "timestamp_ms": 3,
                            "setup_phase": "short_breakdown_confirmed",
                            "higher_timeframe_phase": "trend",
                            "traditional_pattern_label": "trend_breakdown_pressure",
                            "target_edge_pct": -0.0010,
                            "conviction_score": 0.50,
                            "terminal_risk": False,
                            "feature_vector": [0.0] * 16,
                        },
                        {
                            "symbol": "SOL/USDT:USDT",
                            "timestamp_ms": 4,
                            "setup_phase": "short_breakdown_confirmed",
                            "higher_timeframe_phase": "trend",
                            "traditional_pattern_label": "trend_breakdown_pressure",
                            "target_edge_pct": -0.0006,
                            "conviction_score": 0.45,
                            "terminal_risk": False,
                            "feature_vector": [0.0] * 16,
                        },
                    ]

            report = _StubSetupStudyService(settings).study(
                symbols_filter=None,
                setup_phases=["short_breakdown_confirmed"],
                lookback_days=120,
                horizon_bars=3,
                min_samples=2,
                top_k=4,
            )

            self.assertEqual(report["example_count"], 4)
            self.assertEqual(report["top_positive_patterns"][0]["traditional_pattern_label"], "failed_rebound_breakdown")
            self.assertGreater(report["top_positive_patterns"][0]["avg_target_edge_pct"], 0.0)
            self.assertEqual(report["top_negative_patterns"][0]["traditional_pattern_label"], "trend_breakdown_pressure")
            self.assertLess(report["top_negative_patterns"][0]["avg_target_edge_pct"], 0.0)

    def test_candidate_filter_preserves_ranked_symbol_order_in_filtered_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("SOL/USDT:USDT", "BTC/USDT:USDT"),
                rule_mode="bottom_line",
                max_open_positions=2,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            filter_service = CandidateFilter(settings, journal)

            weak_sol = make_symbol(
                "SOL/USDT:USDT",
                900_000,
                91.2,
                atr_pct=0.00192,
                range_pct=0.00198,
                volume_ratio=1.80,
                higher_bias="short",
                higher_phase="pullback",
            )
            weak_sol.indicators["return_1bar"] = -0.0002
            weak_sol.indicators["return_24bars"] = -0.0007
            weak_sol.indicators["rsi_14"] = 48.0
            weak_sol.indicators["sma_fast_ratio"] = -0.0007
            weak_sol.indicators["sma_slow_ratio"] = -0.0009

            clean_btc = make_symbol(
                "BTC/USDT:USDT",
                900_000,
                103_000.0,
                atr_pct=0.0024,
                range_pct=0.0023,
                volume_ratio=1.60,
                higher_bias="short",
                higher_phase="trend",
            )
            clean_btc.indicators["return_1bar"] = -0.0006
            clean_btc.indicators["return_24bars"] = -0.0018
            clean_btc.indicators["rsi_14"] = 45.0
            clean_btc.indicators["sma_fast_ratio"] = -0.0011
            clean_btc.indicators["sma_slow_ratio"] = -0.0015

            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[weak_sol, clean_btc],
                equity_quote=200.0,
                free_quote=200.0,
            )

            filtered = filter_service.apply(bundle)

            self.assertEqual(filtered.status, "selected")
            self.assertEqual(filtered.summary["selected_symbols"][0], "BTC/USDT:USDT")
            self.assertEqual(
                [item.symbol for item in filtered.filtered_bundle.symbols],
                filtered.summary["selected_symbols"],
            )
            self.assertEqual(
                filtered.filtered_bundle.symbols[0].candidate_context["setup_phase"],
                "short_rebound_fail_confirmed",
            )
            self.assertEqual(
                filtered.filtered_bundle.symbols[0].candidate_context["entry_thesis_candidate"]["setup_phase"],
                "short_rebound_fail_confirmed",
            )

    def test_candidate_filter_marks_long_pullback_reclaim_unconfirmed_context(self) -> None:
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

            symbol = make_symbol(
                "SOL/USDT:USDT",
                900_000,
                91.2,
                atr_pct=0.0022,
                range_pct=0.0024,
                volume_ratio=0.80,
                higher_bias="long",
                higher_phase="pullback",
            )
            symbol.indicators["return_1bar"] = 0.0001
            symbol.indicators["return_24bars"] = -0.0020
            symbol.indicators["rsi_14"] = 49.0
            symbol.indicators["sma_fast_ratio"] = -0.0004
            symbol.indicators["sma_slow_ratio"] = 0.0002
            symbol.recent_candles[-1].open = 91.10
            symbol.recent_candles[-1].high = 91.28
            symbol.recent_candles[-1].low = 91.00
            symbol.recent_candles[-1].close = 91.20

            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )

            filtered = filter_service.apply(bundle)

            self.assertEqual(filtered.status, "selected")
            sol_summary = filtered.summary["symbols"][0]
            self.assertEqual(sol_summary["setup_phase"], "long_pullback_reclaim_unconfirmed")
            self.assertFalse(sol_summary["setup_confirmed"])
            self.assertIn("long_setup_pullback_reclaim_unconfirmed", sol_summary["reasons"])
            self.assertEqual(sol_summary["entry_thesis_candidate"]["invalidation_type"], "early_reclaim_failed")

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
            strong_symbol.indicators["return_1bar"] = -0.0002
            strong_symbol.indicators["return_24bars"] = 0.0008
            strong_symbol.indicators["sma_fast_ratio"] = -0.0020
            strong_symbol.indicators["sma_slow_ratio"] = -0.0030
            strong_symbol.indicators["rsi_14"] = 40.0
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
            symbol.indicators["return_1bar"] = 0.0024
            symbol.indicators["return_24bars"] = 0.0050
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
            self.assertEqual(moderate_verdict.final_action, "hold")
            self.assertTrue(any(reason.startswith("expected_edge_below_minimum") for reason in moderate_verdict.reasons))

            strong_symbol = make_symbol("XRP/USDT:USDT", 900_000, 1.5, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="short")
            strong_symbol.indicators["return_1bar"] = -0.0002
            strong_symbol.indicators["return_24bars"] = 0.0008
            strong_symbol.indicators["sma_fast_ratio"] = -0.0020
            strong_symbol.indicators["sma_slow_ratio"] = -0.0030
            strong_symbol.indicators["rsi_14"] = 40.0
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
                min_hold_bars=1,
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

    def test_risk_engine_allows_live_xrp_long_reversal_sample_despite_local_fast_sma_lag(self) -> None:
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

            reversal_long = make_symbol("XRP/USDT:USDT", 900_000, 1.4846, atr_pct=0.0023815938877234685, range_pct=0.0017513134851137922, volume_ratio=1.2023982381742457, higher_bias="long")
            reversal_long.indicators["return_1bar"] = 0.0014165261382799166
            reversal_long.indicators["return_24bars"] = -0.008349475652929095
            reversal_long.indicators["sma_fast_ratio"] = -0.004175540388711041
            reversal_long.indicators["sma_slow_ratio"] = -0.00944120100083412
            reversal_long.indicators["rsi_14"] = 24.725274725274602
            reversal_long.higher_timeframe = {
                "timeframe": "1h",
                "trend_bias": "long",
                "return_12bars": 0.036734408827432175,
                "sma_fast_ratio": -0.001647668045327677,
                "sma_slow_ratio": 0.017512594674252036,
                "rsi_14": 65.22689994532527,
            }
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[reversal_long],
                equity_quote=200.0,
                free_quote=200.0,
            )

            verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "buy", confidence=0.61, take_profit_pct=0.022), bundle)

            self.assertEqual(verdict.final_action, "buy")
            self.assertNotIn("open_signal_return_24bars_too_weak", verdict.reasons)
            self.assertNotIn("open_signal_sma_fast_conflict", verdict.reasons)
            self.assertNotIn("open_signal_sma_slow_conflict", verdict.reasons)

    def test_risk_engine_allows_live_xrp_early_reclaim_signal_despite_local_slow_sma_lag(self) -> None:
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

            reclaim_long = make_symbol("XRP/USDT:USDT", 900_000, 1.4849, atr_pct=0.0034031865329677575, range_pct=0.004831566232720355, volume_ratio=2.7280960654881743, higher_bias="long")
            reclaim_long.indicators["return_1bar"] = 0.0035016835016834502
            reclaim_long.indicators["return_24bars"] = -0.0023431746669344555
            reclaim_long.indicators["sma_fast_ratio"] = 0.004555847044878547
            reclaim_long.indicators["sma_slow_ratio"] = -0.00015795160530551744
            reclaim_long.indicators["rsi_14"] = 45.628415300546315
            reclaim_long.higher_timeframe = {
                "timeframe": "1h",
                "trend_bias": "long",
                "return_12bars": 0.029340362072553194,
                "sma_fast_ratio": -0.006942701798410722,
                "sma_slow_ratio": 0.013822785963154338,
                "rsi_14": 63.61735493988499,
            }
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[reclaim_long],
                equity_quote=200.0,
                free_quote=200.0,
            )

            verdict = risk_engine.evaluate(
                make_decision("XRP/USDT:USDT", "buy", confidence=0.73, take_profit_pct=0.024),
                bundle,
            )

            self.assertEqual(verdict.final_action, "buy")
            self.assertNotIn("open_signal_return_24bars_too_weak", verdict.reasons)
            self.assertNotIn("open_signal_sma_slow_conflict", verdict.reasons)

    def test_risk_engine_allows_live_xrp_early_reclaim_sample_to_clear_edge_floor(self) -> None:
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

            reclaim_long = make_symbol("XRP/USDT:USDT", 900_000, 1.4826, atr_pct=0.002725475518704054, range_pct=0.0017466075507189022, volume_ratio=0.5926134888525437, higher_bias="long")
            reclaim_long.indicators["return_1bar"] = 0.0001343724805160651
            reclaim_long.indicators["return_24bars"] = -0.0051460268662701925
            reclaim_long.indicators["sma_fast_ratio"] = 0.002322997677002281
            reclaim_long.indicators["sma_slow_ratio"] = -0.0008110663004750052
            reclaim_long.indicators["rsi_14"] = 55.98455598455584
            reclaim_long.higher_timeframe = {
                "timeframe": "1h",
                "trend_bias": "long",
                "return_12bars": 0.012987896096831264,
                "sma_fast_ratio": -0.004189041645312974,
                "sma_slow_ratio": 0.01585750127149832,
                "rsi_14": 61.631753031973524,
            }
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[reclaim_long],
                equity_quote=200.0,
                free_quote=200.0,
            )

            verdict = risk_engine.evaluate(
                make_decision("XRP/USDT:USDT", "buy", confidence=0.63, take_profit_pct=0.022),
                bundle,
            )

            self.assertEqual(verdict.final_action, "buy")
            self.assertNotIn("expected_edge_below_minimum", " ".join(verdict.reasons))

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

    def test_risk_engine_keeps_borderline_xrp_reversal_blocked_when_slow_and_trend_return_are_still_too_weak(self) -> None:
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

            borderline_reversal = make_symbol("XRP/USDT:USDT", 900_000, 1.4806, atr_pct=0.0033866579186044078, range_pct=0.004187491557476688, volume_ratio=1.0373471830645344, higher_bias="long")
            borderline_reversal.indicators["return_1bar"] = 0.002505247477825101
            borderline_reversal.indicators["return_24bars"] = -0.010426413581072103
            borderline_reversal.indicators["sma_fast_ratio"] = -0.0024759562749491204
            borderline_reversal.indicators["sma_slow_ratio"] = -0.007220715869230898
            borderline_reversal.indicators["rsi_14"] = 33.235294117646845
            borderline_reversal.higher_timeframe = {
                "timeframe": "1h",
                "trend_bias": "long",
                "return_12bars": 0.029340362072553194,
                "sma_fast_ratio": -0.006942701798410722,
                "sma_slow_ratio": 0.013822785963154338,
                "rsi_14": 63.61735493988499,
            }
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[borderline_reversal],
                equity_quote=200.0,
                free_quote=200.0,
            )

            verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "buy", confidence=0.57, take_profit_pct=0.02), bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertIn("open_signal_return_24bars_too_weak", verdict.reasons)
            self.assertIn("open_signal_sma_fast_conflict", verdict.reasons)
            self.assertIn("open_signal_sma_slow_conflict", verdict.reasons)

    def test_risk_engine_allows_higher_timeframe_short_reclaim_when_higher_timeframe_short_is_strong(self) -> None:
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

            reclaim_short = make_symbol("SOL/USDT:USDT", 900_000, 91.0, atr_pct=0.00296, range_pct=0.00407, volume_ratio=1.64, higher_bias="short")
            reclaim_short.indicators["return_1bar"] = -0.00055
            reclaim_short.indicators["return_24bars"] = 0.00066
            reclaim_short.indicators["sma_fast_ratio"] = -0.00232
            reclaim_short.indicators["sma_slow_ratio"] = -0.00090
            reclaim_short.indicators["rsi_14"] = 41.28
            reclaim_short.higher_timeframe = {
                "timeframe": "1h",
                "trend_bias": "short",
                "return_12bars": -0.0213,
                "sma_fast_ratio": -0.0232,
                "sma_slow_ratio": -0.0086,
                "rsi_14": 46.4,
            }
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[reclaim_short],
                equity_quote=200.0,
                free_quote=200.0,
            )

            verdict = risk_engine.evaluate(make_decision("SOL/USDT:USDT", "sell", confidence=0.66), bundle)

            self.assertEqual(verdict.final_action, "sell")
            self.assertNotIn("open_signal_return_24bars_too_weak", verdict.reasons)

    def test_risk_engine_allows_live_recovery_xrp_short_entry_without_old_risk_blockers(self) -> None:
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

            live_short = make_symbol("XRP/USDT:USDT", 900_000, 1.4634, atr_pct=0.00380, range_pct=0.00444, volume_ratio=0.83, higher_bias="short")
            live_short.indicators["return_1bar"] = 0.00274
            live_short.indicators["return_24bars"] = -0.01514
            live_short.indicators["sma_fast_ratio"] = -0.00032
            live_short.indicators["sma_slow_ratio"] = -0.01046
            live_short.indicators["rsi_14"] = 34.5
            live_short.higher_timeframe = {
                "timeframe": "1h",
                "trend_bias": "short",
                "return_12bars": -0.0213,
                "sma_fast_ratio": -0.0232,
                "sma_slow_ratio": -0.0086,
                "rsi_14": 46.4,
            }
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[live_short],
                equity_quote=200.0,
                free_quote=200.0,
            )

            verdict = risk_engine.evaluate(
                make_decision("XRP/USDT:USDT", "sell", confidence=0.57, take_profit_pct=0.022),
                bundle,
            )

            self.assertEqual(verdict.final_action, "sell")
            self.assertNotIn("expected_edge_below_minimum", " ".join(verdict.reasons))
            self.assertNotIn("open_signal_return_24bars_too_weak", verdict.reasons)
            self.assertNotIn("open_signal_sma_fast_conflict", verdict.reasons)
            self.assertNotIn("open_signal_sma_slow_conflict", verdict.reasons)

    def test_risk_engine_allows_live_sol_short_continuation_sample_to_clear_edge_floor(self) -> None:
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

            continuation_short = make_symbol("SOL/USDT:USDT", 900_000, 90.71, atr_pct=0.0016556551215455202, range_pct=0.003625178512578252, volume_ratio=3.5673327420468857, higher_bias="short")
            continuation_short.indicators["return_1bar"] = -0.0004392225760403434
            continuation_short.indicators["return_24bars"] = -0.0014260640631855726
            continuation_short.indicators["sma_fast_ratio"] = -0.0022833969639953766
            continuation_short.indicators["sma_slow_ratio"] = -0.0018457939655330824
            continuation_short.indicators["rsi_14"] = 29.896907216494498
            continuation_short.higher_timeframe = {
                "timeframe": "1h",
                "trend_bias": "short",
                "return_12bars": -0.009770926066659524,
                "sma_fast_ratio": -0.002860630796421515,
                "sma_slow_ratio": -0.008330955001970564,
                "rsi_14": 37.41379310344829,
            }
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[continuation_short],
                equity_quote=200.0,
                free_quote=200.0,
            )

            verdict = risk_engine.evaluate(
                make_decision("SOL/USDT:USDT", "sell", confidence=0.70, take_profit_pct=0.025),
                bundle,
            )

            self.assertEqual(verdict.final_action, "sell")
            self.assertNotIn("expected_edge_below_minimum", " ".join(verdict.reasons))

    def test_risk_engine_keeps_weak_live_xrp_short_continuation_below_edge_floor(self) -> None:
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

            weak_short = make_symbol("XRP/USDT:USDT", 900_000, 1.4666, atr_pct=0.001484647286746225, range_pct=0.0019762845849801707, volume_ratio=1.916471726589227, higher_bias="short")
            weak_short.indicators["return_1bar"] = -0.000885136515285545
            weak_short.indicators["return_24bars"] = 0.0023224043715848186
            weak_short.indicators["sma_fast_ratio"] = -0.0020346052922407543
            weak_short.indicators["sma_slow_ratio"] = -0.00020723976505243602
            weak_short.indicators["rsi_14"] = 36.423841059602374
            weak_short.higher_timeframe = {
                "timeframe": "1h",
                "trend_bias": "short",
                "return_12bars": -0.011585612286137636,
                "sma_fast_ratio": -0.005180644614558805,
                "sma_slow_ratio": -0.009182984469952804,
                "rsi_14": 36.26271970397775,
            }
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[weak_short],
                equity_quote=200.0,
                free_quote=200.0,
            )

            verdict = risk_engine.evaluate(
                make_decision("XRP/USDT:USDT", "sell", confidence=0.69, take_profit_pct=0.022),
                bundle,
            )

            self.assertEqual(verdict.final_action, "hold")
            self.assertTrue(any(reason.startswith("expected_edge_below_minimum") for reason in verdict.reasons))

    def test_risk_engine_allows_live_xrp_long_fresh_entry_that_drove_overnight_profit_path(self) -> None:
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

            profitable_long = make_symbol("XRP/USDT:USDT", 900_000, 1.4789, atr_pct=0.00445, range_pct=0.00514, volume_ratio=0.66, higher_bias="long")
            profitable_long.indicators["return_1bar"] = 0.00366
            profitable_long.indicators["return_24bars"] = 0.00949
            profitable_long.indicators["sma_fast_ratio"] = 0.00108
            profitable_long.indicators["sma_slow_ratio"] = 0.00881
            profitable_long.indicators["rsi_14"] = 56.69
            profitable_long.higher_timeframe = {
                "timeframe": "1h",
                "trend_bias": "long",
                "return_12bars": 0.0348,
                "sma_fast_ratio": 0.0238,
                "sma_slow_ratio": 0.0310,
                "rsi_14": 77.4,
            }
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[profitable_long],
                equity_quote=200.0,
                free_quote=200.0,
            )

            verdict = risk_engine.evaluate(
                make_decision("XRP/USDT:USDT", "buy", confidence=0.63, take_profit_pct=0.022),
                bundle,
            )

            self.assertEqual(verdict.final_action, "buy")
            self.assertNotIn("fresh_entry_late_breakout", verdict.reasons)
            self.assertNotIn("expected_edge_below_minimum", " ".join(verdict.reasons))

    def test_risk_engine_keeps_live_recovery_xrp_short_management_hold_when_structure_stays_short(self) -> None:
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

            open_symbol = make_symbol("XRP/USDT:USDT", 300_000, 1.4634, atr_pct=0.00380, range_pct=0.00444, volume_ratio=0.83, higher_bias="short")
            open_symbol.indicators["return_1bar"] = 0.00274
            open_symbol.indicators["return_24bars"] = -0.01514
            open_symbol.indicators["sma_fast_ratio"] = -0.00032
            open_symbol.indicators["sma_slow_ratio"] = -0.01046
            record_run(
                journal,
                settings,
                bundle=make_bundle(
                    timestamp_ms=300_000,
                    symbols=[open_symbol],
                    equity_quote=200.0,
                    free_quote=200.0,
                ),
                decision_action="sell",
                final_action="sell",
                symbol="XRP/USDT:USDT",
                confidence=0.57,
            )

            managed_short = make_symbol("XRP/USDT:USDT", 900_000, 1.4716, atr_pct=0.00243, range_pct=0.00197, volume_ratio=0.67, higher_bias="short")
            managed_short.indicators["return_1bar"] = 0.00157
            managed_short.indicators["return_24bars"] = -0.00325
            managed_short.indicators["sma_fast_ratio"] = 0.00459
            managed_short.indicators["sma_slow_ratio"] = -0.00246
            managed_short.indicators["rsi_14"] = 69.75
            managed_short.higher_timeframe = {
                "timeframe": "1h",
                "trend_bias": "short",
                "return_12bars": -0.0213,
                "sma_fast_ratio": -0.0232,
                "sma_slow_ratio": -0.0086,
                "rsi_14": 46.4,
            }
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[managed_short],
                open_positions=[
                    PositionSnapshot(
                        symbol="XRP/USDT:USDT",
                        quantity=33.4,
                        mark_price=1.4716,
                        market_value_quote=49.15294,
                        side="short",
                        average_entry_price=1.464,
                        notional_quote=49.15294,
                    )
                ],
                equity_quote=162.8,
                free_quote=146.7,
            )

            verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "hold", confidence=0.66), bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertEqual(verdict.reasons, ["ok"])
            self.assertNotIn("management_adverse_hold_to_close", verdict.reasons)

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

    def test_risk_engine_blocks_flat_bias_short_flush_and_records_debug(self) -> None:
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

            flat_flush = make_symbol("XRP/USDT:USDT", 900_000, 1.4181, atr_pct=0.00201, range_pct=0.00480, volume_ratio=9.45, higher_bias="flat")
            flat_flush.indicators["return_1bar"] = -0.00274
            flat_flush.indicators["return_24bars"] = -0.01240
            flat_flush.indicators["sma_fast_ratio"] = -0.00935
            flat_flush.indicators["sma_slow_ratio"] = -0.01129
            flat_flush.indicators["rsi_14"] = 14.05
            flat_flush.higher_timeframe = {
                "timeframe": "1h",
                "trend_bias": "flat",
                "return_12bars": 0.00028,
                "sma_fast_ratio": -0.00115,
                "sma_slow_ratio": -0.00894,
                "rsi_14": 53.37,
            }
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[flat_flush],
                equity_quote=157.0,
                free_quote=157.0,
            )

            verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "sell", confidence=0.64), bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertIn("fresh_entry_flat_bias_short_flush", verdict.reasons)
            self.assertIsNotNone(verdict.risk_debug)
            self.assertEqual(verdict.risk_debug["entry_archetype"], "flat_bias_short_flush")
            self.assertEqual(verdict.risk_debug["shadow_open_signal_reasons"], [])
            self.assertGreater(verdict.risk_debug["expected_edge_components"]["final_expected_edge_pct"], settings.min_expected_edge_pct)

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

    def test_risk_engine_blocks_weak_long_reclaim_chase_after_stretched_rebound(self) -> None:
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

            weak_reclaim = make_symbol("SOL/USDT:USDT", 900_000, 87.04, atr_pct=0.00149, range_pct=0.00379, volume_ratio=1.94, higher_bias="long")
            weak_reclaim.indicators["return_1bar"] = 0.00253
            weak_reclaim.indicators["return_24bars"] = 0.00300
            weak_reclaim.indicators["rsi_14"] = 68.04
            weak_reclaim.indicators["sma_fast_ratio"] = 0.00271
            weak_reclaim.indicators["sma_slow_ratio"] = 0.00278
            weak_reclaim.recent_candles[-1].open = 86.83
            weak_reclaim.recent_candles[-1].high = 87.13
            weak_reclaim.recent_candles[-1].low = 86.80
            weak_reclaim.recent_candles[-1].close = 87.04
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[weak_reclaim],
                equity_quote=200.0,
                free_quote=200.0,
            )

            verdict = risk_engine.evaluate(make_decision("SOL/USDT:USDT", "buy", confidence=0.62), bundle)

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

    def test_risk_engine_blocks_overextended_short_chase_before_full_capitulation(self) -> None:
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

            stretched_short = make_symbol("SOL/USDT:USDT", 900_000, 89.78, atr_pct=0.0024, range_pct=0.0046, volume_ratio=4.20, higher_bias="short")
            stretched_short.indicators["return_1bar"] = -0.0016
            stretched_short.indicators["return_24bars"] = -0.0042
            stretched_short.indicators["rsi_14"] = 33.0
            stretched_short.indicators["sma_fast_ratio"] = -0.0048
            stretched_short.indicators["sma_slow_ratio"] = -0.0055
            stretched_short.recent_candles[-1].open = 90.20
            stretched_short.recent_candles[-1].high = 90.26
            stretched_short.recent_candles[-1].low = 89.74
            stretched_short.recent_candles[-1].close = 89.78
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[stretched_short],
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

    def test_risk_engine_blocks_high_rsi_long_chase_even_without_climactic_volume(self) -> None:
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

            hot_long = make_symbol("XRP/USDT:USDT", 900_000, 1.4696, atr_pct=0.00356, range_pct=0.00265, volume_ratio=0.79, higher_bias="long")
            hot_long.indicators["return_1bar"] = 0.00136
            hot_long.indicators["return_24bars"] = 0.01212
            hot_long.indicators["rsi_14"] = 78.06
            hot_long.indicators["sma_fast_ratio"] = 0.00376
            hot_long.indicators["sma_slow_ratio"] = 0.01460
            hot_long.recent_candles[-1].open = 1.4676
            hot_long.recent_candles[-1].high = 1.4702
            hot_long.recent_candles[-1].low = 1.4663
            hot_long.recent_candles[-1].close = 1.4696
            hot_long.higher_timeframe = {
                "timeframe": "1h",
                "trend_bias": "long",
                "return_12bars": 0.03171,
                "sma_fast_ratio": 0.02344,
                "sma_slow_ratio": 0.02813,
                "rsi_14": 70.41,
            }
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[hot_long],
                equity_quote=200.0,
                free_quote=200.0,
            )

            verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "buy", confidence=0.64), bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertIn("fresh_entry_late_breakout", verdict.reasons)

    def test_risk_engine_keeps_profitable_eth_reclaim_short_when_downside_follow_through_is_intact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                trailing_profit_arm_pct=0.0025,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            open_symbol = make_symbol(
                "ETH/USDT:USDT",
                300_000,
                2_070.0,
                atr_pct=0.0040,
                range_pct=0.0040,
                volume_ratio=1.20,
                higher_bias="short",
                higher_phase="reclaim",
            )
            open_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[open_symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )
            entry_thesis = {
                "version": 1,
                "direction": "short",
                "higher_timeframe_direction": "short",
                "higher_timeframe_phase": "reclaim",
                "setup_phase": "short_rebound_fail_confirmed",
                "setup_confirmed": True,
                "invalidation_type": "rebound_fail_reclaimed",
                "follow_through_bars": 2,
                "trigger_bar_timestamp_ms": 300_000,
            }
            record_run(
                journal,
                settings,
                bundle=open_bundle,
                decision_action="sell",
                final_action="sell",
                symbol="ETH/USDT:USDT",
                confidence=0.80,
                risk_debug={"entry_thesis": entry_thesis},
                raw_payload_extra={"entry_thesis": entry_thesis},
            )

            degraded_symbol = make_symbol(
                "ETH/USDT:USDT",
                1_200_000,
                2_060.0,
                atr_pct=0.0030,
                range_pct=0.0031,
                volume_ratio=0.90,
                higher_bias="short",
                higher_phase="reclaim",
            )
            degraded_symbol.indicators["return_1bar"] = -0.0008
            degraded_symbol.indicators["return_24bars"] = -0.0048
            degraded_symbol.indicators["rsi_14"] = 20.8
            degraded_symbol.indicators["sma_fast_ratio"] = -0.0058
            degraded_symbol.indicators["sma_slow_ratio"] = -0.0008
            degraded_symbol.recent_candles[-1].open = 2_067.0
            degraded_symbol.recent_candles[-1].high = 2_068.0
            degraded_symbol.recent_candles[-1].low = 2_057.0
            degraded_symbol.recent_candles[-1].close = 2_060.0
            degraded_bundle = make_bundle(
                timestamp_ms=1_200_000,
                symbols=[degraded_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="ETH/USDT:USDT",
                        quantity=0.05,
                        mark_price=2_060.0,
                        market_value_quote=103.0,
                        side="short",
                        average_entry_price=2_070.0,
                        notional_quote=103.0,
                    )
                ],
                equity_quote=200.0,
                free_quote=190.0,
            )

            verdict = risk_engine.evaluate(make_decision("ETH/USDT:USDT", "close", confidence=0.72), degraded_bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertIn("management_close_rejected_entry_thesis_still_supported", verdict.reasons)

    def test_risk_engine_closes_profitable_eth_reclaim_short_after_rebound_degrades_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                trailing_profit_arm_pct=0.0025,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            open_symbol = make_symbol(
                "ETH/USDT:USDT",
                300_000,
                2_070.0,
                atr_pct=0.0040,
                range_pct=0.0040,
                volume_ratio=1.20,
                higher_bias="short",
                higher_phase="reclaim",
            )
            open_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[open_symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )
            entry_thesis = {
                "version": 1,
                "direction": "short",
                "higher_timeframe_direction": "short",
                "higher_timeframe_phase": "reclaim",
                "setup_phase": "short_rebound_fail_confirmed",
                "setup_confirmed": True,
                "invalidation_type": "rebound_fail_reclaimed",
                "follow_through_bars": 2,
                "trigger_bar_timestamp_ms": 300_000,
            }
            record_run(
                journal,
                settings,
                bundle=open_bundle,
                decision_action="sell",
                final_action="sell",
                symbol="ETH/USDT:USDT",
                confidence=0.80,
                risk_debug={"entry_thesis": entry_thesis},
                raw_payload_extra={"entry_thesis": entry_thesis},
            )

            rebound_symbol = make_symbol(
                "ETH/USDT:USDT",
                1_200_000,
                2_064.0,
                atr_pct=0.0030,
                range_pct=0.0033,
                volume_ratio=1.10,
                higher_bias="short",
                higher_phase="reclaim",
            )
            rebound_symbol.indicators["return_1bar"] = 0.0016
            rebound_symbol.indicators["return_24bars"] = -0.0006
            rebound_symbol.indicators["rsi_14"] = 56.0
            rebound_symbol.indicators["sma_fast_ratio"] = 0.0005
            rebound_symbol.indicators["sma_slow_ratio"] = -0.0006
            rebound_symbol.recent_candles[-1].open = 2_058.0
            rebound_symbol.recent_candles[-1].high = 2_065.0
            rebound_symbol.recent_candles[-1].low = 2_057.0
            rebound_symbol.recent_candles[-1].close = 2_064.0
            rebound_bundle = make_bundle(
                timestamp_ms=1_200_000,
                symbols=[rebound_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="ETH/USDT:USDT",
                        quantity=0.05,
                        mark_price=2_064.0,
                        market_value_quote=103.2,
                        side="short",
                        average_entry_price=2_070.0,
                        notional_quote=103.2,
                    )
                ],
                equity_quote=200.0,
                free_quote=190.0,
            )

            verdict = risk_engine.evaluate(make_decision("ETH/USDT:USDT", "close", confidence=0.72), rebound_bundle)

            self.assertEqual(verdict.final_action, "close")
            self.assertNotIn("management_close_rejected_entry_thesis_still_supported", verdict.reasons)

    def test_risk_engine_rejects_eth_short_ai_close_for_trend_range_noise_without_confirmed_reversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                partial_take_profit_trigger_pct=0.03,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            open_symbol = make_symbol(
                "ETH/USDT:USDT",
                300_000,
                2_052.0,
                atr_pct=0.0030,
                range_pct=0.0030,
                volume_ratio=1.10,
                higher_bias="short",
                higher_phase="trend",
            )
            open_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[open_symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )
            record_run(journal, settings, bundle=open_bundle, decision_action="sell", final_action="sell", symbol="ETH/USDT:USDT", confidence=0.80)

            rebound_symbol = make_symbol(
                "ETH/USDT:USDT",
                1_200_000,
                2_053.83,
                atr_pct=0.00207,
                range_pct=0.00171,
                volume_ratio=0.49,
                higher_bias="short",
                higher_phase="trend",
            )
            rebound_symbol.indicators["return_1bar"] = 0.00090
            rebound_symbol.indicators["return_24bars"] = 0.00351
            rebound_symbol.indicators["rsi_14"] = 52.6
            rebound_symbol.indicators["sma_fast_ratio"] = 0.00071
            rebound_symbol.indicators["sma_slow_ratio"] = -0.00209
            rebound_bundle = make_bundle(
                timestamp_ms=1_200_000,
                symbols=[rebound_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="ETH/USDT:USDT",
                        quantity=0.05,
                        mark_price=2_053.83,
                        market_value_quote=102.6915,
                        side="short",
                        average_entry_price=2_052.0,
                        notional_quote=102.6915,
                    )
                ],
                equity_quote=200.0,
                free_quote=190.0,
            )

            verdict = risk_engine.evaluate(make_decision("ETH/USDT:USDT", "close", confidence=0.78), rebound_bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertIn(
                "management_close_rejected_eth_short_trend_range_noise_reversal_not_confirmed",
                verdict.reasons,
            )

    def test_risk_engine_rejects_eth_short_ai_close_on_exhaustion_breakdown_flush(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                partial_take_profit_trigger_pct=0.03,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            open_symbol = make_symbol(
                "ETH/USDT:USDT",
                300_000,
                2_042.98,
                atr_pct=0.0030,
                range_pct=0.0030,
                volume_ratio=1.10,
                higher_bias="short",
                higher_phase="trend",
            )
            open_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[open_symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )
            record_run(journal, settings, bundle=open_bundle, decision_action="sell", final_action="sell", symbol="ETH/USDT:USDT", confidence=0.80)

            flush_symbol = make_symbol(
                "ETH/USDT:USDT",
                1_200_000,
                2_018.52,
                atr_pct=0.00463,
                range_pct=0.01289,
                volume_ratio=7.50,
                higher_bias="short",
                higher_phase="exhaustion",
            )
            flush_symbol.indicators["return_1bar"] = -0.01197
            flush_symbol.indicators["return_24bars"] = -0.01537
            flush_symbol.indicators["rsi_14"] = 29.34
            flush_symbol.indicators["sma_fast_ratio"] = -0.01365
            flush_symbol.indicators["sma_slow_ratio"] = -0.01711
            flush_symbol.higher_timeframe["trend_strength"] = 3.0
            flush_symbol.higher_timeframe["distance_from_12bar_extreme"] = -0.00071
            flush_symbol.recent_candles[-1].open = 2_042.99
            flush_symbol.recent_candles[-1].high = 2_043.10
            flush_symbol.recent_candles[-1].low = 2_017.09
            flush_symbol.recent_candles[-1].close = 2_018.52
            flush_bundle = make_bundle(
                timestamp_ms=1_200_000,
                symbols=[flush_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="ETH/USDT:USDT",
                        quantity=0.05,
                        mark_price=2_018.52,
                        market_value_quote=100.926,
                        side="short",
                        average_entry_price=2_042.98,
                        notional_quote=100.926,
                    )
                ],
                equity_quote=200.0,
                free_quote=190.0,
            )

            verdict = risk_engine.evaluate(make_decision("ETH/USDT:USDT", "close", confidence=0.74), flush_bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertIn(
                "management_close_rejected_eth_short_exhaustion_breakdown_flush_still_expanding",
                verdict.reasons,
            )

    def test_risk_engine_rejects_eth_short_ai_close_on_exhaustion_range_noise_after_flush(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                partial_take_profit_trigger_pct=0.03,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            open_symbol = make_symbol(
                "ETH/USDT:USDT",
                300_000,
                2_042.98,
                atr_pct=0.0030,
                range_pct=0.0030,
                volume_ratio=1.10,
                higher_bias="short",
                higher_phase="trend",
            )
            open_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[open_symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )
            record_run(journal, settings, bundle=open_bundle, decision_action="sell", final_action="sell", symbol="ETH/USDT:USDT", confidence=0.80)

            range_noise_symbol = make_symbol(
                "ETH/USDT:USDT",
                1_500_000,
                2_020.80,
                atr_pct=0.00380,
                range_pct=0.00410,
                volume_ratio=1.25,
                higher_bias="short",
                higher_phase="exhaustion",
            )
            range_noise_symbol.indicators["return_1bar"] = 0.00110
            range_noise_symbol.indicators["return_24bars"] = -0.01050
            range_noise_symbol.indicators["rsi_14"] = 39.0
            range_noise_symbol.indicators["sma_fast_ratio"] = 0.00040
            range_noise_symbol.indicators["sma_slow_ratio"] = -0.01020
            range_noise_symbol.higher_timeframe["distance_from_12bar_extreme"] = -0.00180
            range_noise_symbol.recent_candles[-1].open = 2_018.58
            range_noise_symbol.recent_candles[-1].high = 2_023.10
            range_noise_symbol.recent_candles[-1].low = 2_016.80
            range_noise_symbol.recent_candles[-1].close = 2_020.80
            range_noise_bundle = make_bundle(
                timestamp_ms=1_500_000,
                symbols=[range_noise_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="ETH/USDT:USDT",
                        quantity=0.05,
                        mark_price=2_020.80,
                        market_value_quote=101.04,
                        side="short",
                        average_entry_price=2_042.98,
                        notional_quote=101.04,
                    )
                ],
                equity_quote=200.0,
                free_quote=190.0,
            )

            verdict = risk_engine.evaluate(make_decision("ETH/USDT:USDT", "close", confidence=0.74), range_noise_bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertIn(
                "management_close_rejected_eth_short_exhaustion_range_noise_reversal_not_confirmed",
                verdict.reasons,
            )

    def test_risk_engine_allows_eth_short_ai_close_on_strong_rebound_bar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                partial_take_profit_trigger_pct=0.03,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            open_symbol = make_symbol(
                "ETH/USDT:USDT",
                300_000,
                2_070.0,
                atr_pct=0.0030,
                range_pct=0.0030,
                volume_ratio=1.10,
                higher_bias="short",
                higher_phase="reclaim",
            )
            open_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[open_symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )
            record_run(journal, settings, bundle=open_bundle, decision_action="sell", final_action="sell", symbol="ETH/USDT:USDT", confidence=0.80)

            strong_rebound_symbol = make_symbol(
                "ETH/USDT:USDT",
                1_200_000,
                2_053.0,
                atr_pct=0.00312,
                range_pct=0.00506,
                volume_ratio=2.05,
                higher_bias="short",
                higher_phase="reclaim",
            )
            strong_rebound_symbol.indicators["return_1bar"] = 0.00396
            strong_rebound_symbol.indicators["return_24bars"] = -0.0140
            strong_rebound_symbol.indicators["rsi_14"] = 24.8
            strong_rebound_symbol.indicators["sma_fast_ratio"] = -0.00466
            strong_rebound_symbol.indicators["sma_slow_ratio"] = -0.00854
            strong_rebound_bundle = make_bundle(
                timestamp_ms=1_200_000,
                symbols=[strong_rebound_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="ETH/USDT:USDT",
                        quantity=0.05,
                        mark_price=2_053.0,
                        market_value_quote=102.65,
                        side="short",
                        average_entry_price=2_062.0,
                        notional_quote=102.65,
                    )
                ],
                equity_quote=200.0,
                free_quote=190.0,
            )

            verdict = risk_engine.evaluate(make_decision("ETH/USDT:USDT", "close", confidence=0.74), strong_rebound_bundle)

            self.assertEqual(verdict.final_action, "close")
            self.assertNotIn(
                "management_close_rejected_eth_short_trend_range_noise_reversal_not_confirmed",
                verdict.reasons,
            )

    def test_risk_engine_rejects_structural_eth_range_noise_short_close_while_flush_extends(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                partial_take_profit_trigger_pct=0.03,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            entry_thesis = {
                "version": 2,
                "direction": "short",
                "higher_timeframe_direction": "short",
                "higher_timeframe_phase": "trend",
                "setup_phase": "eth_structural_range_noise_short",
                "setup_confirmed": True,
                "invalidation_type": "structural_breakdown_reclaimed",
                "follow_through_bars": 2,
            }
            open_symbol = make_symbol(
                "ETH/USDT:USDT",
                300_000,
                2_042.98,
                atr_pct=0.0050,
                range_pct=0.0054,
                volume_ratio=1.86,
                higher_bias="short",
                higher_phase="trend",
            )
            open_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[open_symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )
            record_run(
                journal,
                settings,
                bundle=open_bundle,
                decision_action="sell",
                final_action="sell",
                symbol="ETH/USDT:USDT",
                confidence=0.64,
                final_take_profit_pct=0.05,
                risk_debug={"entry_thesis": entry_thesis},
            )

            flush_symbol = make_symbol(
                "ETH/USDT:USDT",
                1_200_000,
                2_005.42,
                atr_pct=0.0060,
                range_pct=0.0088,
                volume_ratio=1.86,
                higher_bias="short",
                higher_phase="exhaustion",
            )
            flush_symbol.indicators["return_1bar"] = -0.007448761921731051
            flush_symbol.indicators["return_24bars"] = -0.015686813456498028
            flush_symbol.indicators["rsi_14"] = 21.099533863449352
            flush_symbol.indicators["sma_fast_ratio"] = -0.017211933105997224
            flush_symbol.indicators["sma_slow_ratio"] = -0.022512635927485314
            flush_symbol.higher_timeframe["distance_from_12bar_extreme"] = -0.0007084398470166287
            flush_bundle = make_bundle(
                timestamp_ms=1_200_000,
                symbols=[flush_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="ETH/USDT:USDT",
                        quantity=0.05,
                        mark_price=2_005.42,
                        market_value_quote=100.271,
                        side="short",
                        average_entry_price=2_042.98,
                        notional_quote=100.271,
                    )
                ],
                equity_quote=200.0,
                free_quote=190.0,
            )

            verdict = risk_engine.evaluate(make_decision("ETH/USDT:USDT", "close", confidence=0.68), flush_bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertIn("management_close_rejected_entry_thesis_still_supported", verdict.reasons)

    def test_risk_engine_partial_take_profit_still_applies_when_ai_requests_close(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                trailing_profit_arm_pct=0.01,
                partial_take_profit_trigger_pct=0.012,
                partial_take_profit_step_pct=0.012,
                partial_take_profit_fraction=0.50,
                partial_take_profit_max_times=1,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            entry_thesis = {
                "version": 2,
                "direction": "short",
                "higher_timeframe_direction": "short",
                "higher_timeframe_phase": "trend",
                "setup_phase": "eth_structural_range_noise_short",
                "setup_confirmed": True,
                "invalidation_type": "structural_breakdown_reclaimed",
                "follow_through_bars": 2,
            }
            open_symbol = make_symbol(
                "ETH/USDT:USDT",
                300_000,
                2_042.98,
                atr_pct=0.0050,
                range_pct=0.0054,
                volume_ratio=1.86,
                higher_bias="short",
                higher_phase="trend",
            )
            open_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[open_symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )
            record_run(
                journal,
                settings,
                bundle=open_bundle,
                decision_action="sell",
                final_action="sell",
                symbol="ETH/USDT:USDT",
                confidence=0.64,
                final_take_profit_pct=0.05,
                risk_debug={"entry_thesis": entry_thesis},
            )

            retraced_symbol = make_symbol(
                "ETH/USDT:USDT",
                1_200_000,
                1_990.52,
                atr_pct=0.0060,
                range_pct=0.0088,
                volume_ratio=2.75,
                higher_bias="short",
                higher_phase="exhaustion",
            )
            retraced_symbol.indicators["return_1bar"] = -0.00454588644785725
            retraced_symbol.indicators["return_24bars"] = -0.024833309654567648
            retraced_symbol.indicators["rsi_14"] = 16.277719725995354
            retraced_symbol.indicators["sma_fast_ratio"] = -0.013401105049050566
            retraced_symbol.indicators["sma_slow_ratio"] = -0.026238225574870766
            retraced_bundle = make_bundle(
                timestamp_ms=1_200_000,
                symbols=[retraced_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="ETH/USDT:USDT",
                        quantity=0.058888255955481986,
                        mark_price=1_990.52,
                        market_value_quote=117.2,
                        side="short",
                        average_entry_price=2_042.98,
                        notional_quote=117.2,
                    )
                ],
                equity_quote=200.0,
                free_quote=190.0,
            )

            verdict = risk_engine.evaluate(make_decision("ETH/USDT:USDT", "close", confidence=0.81), retraced_bundle)

            self.assertEqual(verdict.final_action, "close")
            self.assertTrue(verdict.approved)
            self.assertAlmostEqual(verdict.close_fraction, 0.50)
            self.assertTrue(any(reason.startswith("partial_take_profit:") for reason in verdict.reasons))
            self.assertNotIn("management_close_rejected_entry_thesis_still_supported", verdict.reasons)

    def test_risk_engine_trailing_retrace_overrides_supported_structural_eth_close_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                trailing_profit_arm_pct=0.01,
                trailing_profit_retrace_pct=0.002,
                partial_take_profit_max_times=0,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            entry_thesis = {
                "version": 2,
                "direction": "short",
                "higher_timeframe_direction": "short",
                "higher_timeframe_phase": "trend",
                "setup_phase": "eth_structural_range_noise_short",
                "setup_confirmed": True,
                "invalidation_type": "structural_breakdown_reclaimed",
                "follow_through_bars": 2,
            }
            open_symbol = make_symbol(
                "ETH/USDT:USDT",
                300_000,
                2_042.98,
                atr_pct=0.0050,
                range_pct=0.0054,
                volume_ratio=1.86,
                higher_bias="short",
                higher_phase="trend",
            )
            open_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[open_symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )
            record_run(
                journal,
                settings,
                bundle=open_bundle,
                decision_action="sell",
                final_action="sell",
                symbol="ETH/USDT:USDT",
                confidence=0.64,
                final_take_profit_pct=0.05,
                risk_debug={"entry_thesis": entry_thesis},
            )

            recent_actions = journal.get_recent_signal_actions(limit=10, symbol="ETH/USDT:USDT")
            last_open = next(item for item in recent_actions if item["final_action"] == "sell")
            peak_key = risk_engine._trailing_profit_peak_key("ETH/USDT:USDT", int(last_open["run_id"]))
            journal.set_runtime_state(peak_key, 0.0330)

            retraced_symbol = make_symbol(
                "ETH/USDT:USDT",
                1_200_000,
                1_980.27,
                atr_pct=0.0060,
                range_pct=0.0060,
                volume_ratio=1.10,
                higher_bias="short",
                higher_phase="trend",
            )
            retraced_symbol.indicators["return_1bar"] = 0.0023841341189334564
            retraced_symbol.indicators["return_24bars"] = -0.0328729524609539
            retraced_symbol.indicators["rsi_14"] = 13.117081695063334
            retraced_symbol.indicators["sma_fast_ratio"] = -0.008926370683568274
            retraced_symbol.indicators["sma_slow_ratio"] = -0.02801887374158951
            retraced_bundle = make_bundle(
                timestamp_ms=1_200_000,
                symbols=[retraced_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="ETH/USDT:USDT",
                        quantity=0.029444127977740993,
                        mark_price=1_980.27,
                        market_value_quote=58.30732331048115,
                        side="short",
                        average_entry_price=2_042.98,
                        notional_quote=58.30732331048115,
                    )
                ],
                equity_quote=200.0,
                free_quote=190.0,
            )

            verdict = risk_engine.evaluate(make_decision("ETH/USDT:USDT", "close", confidence=0.79), retraced_bundle)

            self.assertEqual(verdict.final_action, "close")
            self.assertTrue(any(reason.startswith("management_trailing_profit_retrace:") for reason in verdict.reasons))
            self.assertNotIn("management_close_rejected_entry_thesis_still_supported", verdict.reasons)

    def test_risk_engine_allows_structural_eth_range_noise_short_close_on_confirmed_reversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            entry_thesis = {
                "version": 2,
                "direction": "short",
                "higher_timeframe_direction": "short",
                "higher_timeframe_phase": "trend",
                "setup_phase": "eth_structural_range_noise_short",
                "setup_confirmed": True,
                "invalidation_type": "structural_breakdown_reclaimed",
                "follow_through_bars": 2,
            }
            open_symbol = make_symbol(
                "ETH/USDT:USDT",
                300_000,
                2_042.98,
                atr_pct=0.0050,
                range_pct=0.0054,
                volume_ratio=1.86,
                higher_bias="short",
                higher_phase="trend",
            )
            open_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[open_symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )
            record_run(
                journal,
                settings,
                bundle=open_bundle,
                decision_action="sell",
                final_action="sell",
                symbol="ETH/USDT:USDT",
                confidence=0.64,
                final_take_profit_pct=0.05,
                risk_debug={"entry_thesis": entry_thesis},
            )

            rebound_symbol = make_symbol(
                "ETH/USDT:USDT",
                1_200_000,
                2_020.0,
                atr_pct=0.0060,
                range_pct=0.0060,
                volume_ratio=1.70,
                higher_bias="short",
                higher_phase="exhaustion",
            )
            rebound_symbol.indicators["return_1bar"] = 0.0036
            rebound_symbol.indicators["return_24bars"] = -0.0100
            rebound_symbol.indicators["rsi_14"] = 53.0
            rebound_symbol.indicators["sma_fast_ratio"] = 0.0012
            rebound_symbol.indicators["sma_slow_ratio"] = -0.0110
            rebound_bundle = make_bundle(
                timestamp_ms=1_200_000,
                symbols=[rebound_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="ETH/USDT:USDT",
                        quantity=0.05,
                        mark_price=2_020.0,
                        market_value_quote=101.0,
                        side="short",
                        average_entry_price=2_042.98,
                        notional_quote=101.0,
                    )
                ],
                equity_quote=200.0,
                free_quote=190.0,
            )

            verdict = risk_engine.evaluate(make_decision("ETH/USDT:USDT", "close", confidence=0.74), rebound_bundle)

            self.assertEqual(verdict.final_action, "close")
            self.assertNotIn("management_close_rejected_entry_thesis_still_supported", verdict.reasons)

    def test_risk_engine_keeps_profitable_eth_reclaim_short_on_single_rebound_bar_below_fast_sma(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                trailing_profit_arm_pct=0.0025,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            open_symbol = make_symbol(
                "ETH/USDT:USDT",
                300_000,
                2_070.0,
                atr_pct=0.0040,
                range_pct=0.0040,
                volume_ratio=1.20,
                higher_bias="short",
                higher_phase="reclaim",
            )
            open_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[open_symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )
            entry_thesis = {
                "version": 1,
                "direction": "short",
                "higher_timeframe_direction": "short",
                "higher_timeframe_phase": "reclaim",
                "setup_phase": "short_rebound_fail_confirmed",
                "setup_confirmed": True,
                "invalidation_type": "rebound_fail_reclaimed",
                "follow_through_bars": 2,
                "trigger_bar_timestamp_ms": 300_000,
            }
            record_run(
                journal,
                settings,
                bundle=open_bundle,
                decision_action="sell",
                final_action="sell",
                symbol="ETH/USDT:USDT",
                confidence=0.80,
                risk_debug={"entry_thesis": entry_thesis},
                raw_payload_extra={"entry_thesis": entry_thesis},
            )

            weak_rebound_symbol = make_symbol(
                "ETH/USDT:USDT",
                1_200_000,
                2_015.37,
                atr_pct=0.00246,
                range_pct=0.00535,
                volume_ratio=3.11,
                higher_bias="short",
                higher_phase="reclaim",
            )
            weak_rebound_symbol.indicators["return_1bar"] = 0.001168
            weak_rebound_symbol.indicators["return_24bars"] = -0.008496
            weak_rebound_symbol.indicators["rsi_14"] = 30.89
            weak_rebound_symbol.indicators["sma_fast_ratio"] = -0.002687
            weak_rebound_symbol.indicators["sma_slow_ratio"] = -0.006307
            weak_rebound_symbol.recent_candles[-1].open = 2_014.0
            weak_rebound_symbol.recent_candles[-1].high = 2_017.0
            weak_rebound_symbol.recent_candles[-1].low = 2_009.0
            weak_rebound_symbol.recent_candles[-1].close = 2_015.37
            weak_rebound_bundle = make_bundle(
                timestamp_ms=1_200_000,
                symbols=[weak_rebound_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="ETH/USDT:USDT",
                        quantity=0.05,
                        mark_price=2_015.37,
                        market_value_quote=100.7685,
                        side="short",
                        average_entry_price=2_023.0,
                        notional_quote=100.7685,
                    )
                ],
                equity_quote=200.0,
                free_quote=190.0,
            )

            verdict = risk_engine.evaluate(make_decision("ETH/USDT:USDT", "hold", confidence=0.69), weak_rebound_bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertNotIn(
                "management_entry_thesis_invalidated:rebound_fail_profit_protection_exit",
                verdict.reasons,
            )

    def test_risk_engine_rejects_ai_close_on_profitable_eth_reclaim_short_when_bearish_pressure_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                trailing_profit_arm_pct=0.0025,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            open_symbol = make_symbol(
                "ETH/USDT:USDT",
                300_000,
                2_070.0,
                atr_pct=0.0040,
                range_pct=0.0040,
                volume_ratio=1.20,
                higher_bias="short",
                higher_phase="reclaim",
            )
            open_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[open_symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )
            entry_thesis = {
                "version": 1,
                "direction": "short",
                "higher_timeframe_direction": "short",
                "higher_timeframe_phase": "reclaim",
                "setup_phase": "short_rebound_fail_confirmed",
                "setup_confirmed": True,
                "invalidation_type": "rebound_fail_reclaimed",
                "follow_through_bars": 2,
                "trigger_bar_timestamp_ms": 300_000,
            }
            record_run(
                journal,
                settings,
                bundle=open_bundle,
                decision_action="sell",
                final_action="sell",
                symbol="ETH/USDT:USDT",
                confidence=0.80,
                risk_debug={"entry_thesis": entry_thesis},
                raw_payload_extra={"entry_thesis": entry_thesis},
            )

            sticky_short_symbol = make_symbol(
                "ETH/USDT:USDT",
                1_200_000,
                2_055.0,
                atr_pct=0.0030,
                range_pct=0.0034,
                volume_ratio=1.25,
                higher_bias="short",
                higher_phase="reclaim",
            )
            sticky_short_symbol.indicators["return_1bar"] = 0.0009
            sticky_short_symbol.indicators["return_24bars"] = -0.0021
            sticky_short_symbol.indicators["rsi_14"] = 39.0
            sticky_short_symbol.indicators["sma_fast_ratio"] = 0.0002
            sticky_short_symbol.indicators["sma_slow_ratio"] = -0.0028
            sticky_short_bundle = make_bundle(
                timestamp_ms=1_200_000,
                symbols=[sticky_short_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="ETH/USDT:USDT",
                        quantity=0.05,
                        mark_price=2_055.0,
                        market_value_quote=102.75,
                        side="short",
                        average_entry_price=2_064.0,
                        notional_quote=102.75,
                    )
                ],
                equity_quote=200.0,
                free_quote=190.0,
            )

            verdict = risk_engine.evaluate(make_decision("ETH/USDT:USDT", "close", confidence=0.71), sticky_short_bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertIn("management_close_rejected_entry_thesis_still_supported", verdict.reasons)

    def test_risk_engine_keeps_profitable_eth_trend_short_rebound_fail_when_bearish_pressure_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                trailing_profit_arm_pct=0.0025,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            open_symbol = make_symbol(
                "ETH/USDT:USDT",
                300_000,
                2_055.61,
                atr_pct=0.0030,
                range_pct=0.0030,
                volume_ratio=1.05,
                higher_bias="short",
                higher_phase="trend",
            )
            open_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[open_symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )
            entry_thesis = {
                "version": 1,
                "direction": "short",
                "higher_timeframe_direction": "short",
                "higher_timeframe_phase": "trend",
                "setup_phase": "short_rebound_fail_confirmed",
                "setup_confirmed": True,
                "invalidation_type": "rebound_fail_reclaimed",
                "follow_through_bars": 2,
                "trigger_bar_timestamp_ms": 300_000,
                "entry_price": 2055.61,
                "entry_sma_fast_ratio": -0.0029,
                "entry_sma_slow_ratio": -0.0052,
                "entry_return_24bars": 0.0007,
                "entry_rsi_14": 39.8,
            }
            record_run(
                journal,
                settings,
                bundle=open_bundle,
                decision_action="sell",
                final_action="sell",
                symbol="ETH/USDT:USDT",
                confidence=0.80,
                risk_debug={"entry_thesis": entry_thesis},
                raw_payload_extra={"entry_thesis": entry_thesis},
            )

            mild_rebound_symbol = make_symbol(
                "ETH/USDT:USDT",
                1_200_000,
                2_042.96,
                atr_pct=0.0027,
                range_pct=0.0038,
                volume_ratio=2.14,
                higher_bias="short",
                higher_phase="trend",
            )
            mild_rebound_symbol.indicators["return_1bar"] = 0.00274
            mild_rebound_symbol.indicators["return_24bars"] = -0.0095
            mild_rebound_symbol.indicators["rsi_14"] = 32.8
            mild_rebound_symbol.indicators["sma_fast_ratio"] = -0.0056
            mild_rebound_symbol.indicators["sma_slow_ratio"] = -0.0094
            mild_rebound_bundle = make_bundle(
                timestamp_ms=1_200_000,
                symbols=[mild_rebound_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="ETH/USDT:USDT",
                        quantity=0.05,
                        mark_price=2_042.96,
                        market_value_quote=102.148,
                        side="short",
                        average_entry_price=2_055.61,
                        notional_quote=102.148,
                    )
                ],
                equity_quote=200.0,
                free_quote=190.0,
            )

            verdict = risk_engine.evaluate(make_decision("ETH/USDT:USDT", "hold", confidence=0.72), mild_rebound_bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertNotIn(
                "management_entry_thesis_invalidated:rebound_fail_profit_protection_exit",
                verdict.reasons,
            )

    def test_risk_engine_keeps_profitable_eth_continuation_short_on_weak_rebound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                trailing_profit_arm_pct=0.0025,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            open_symbol = make_symbol(
                "ETH/USDT:USDT",
                300_000,
                2_055.61,
                atr_pct=0.0030,
                range_pct=0.0030,
                volume_ratio=1.05,
                higher_bias="short",
                higher_phase="trend",
            )
            open_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[open_symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )
            entry_thesis = {
                "version": 1,
                "direction": "short",
                "higher_timeframe_direction": "short",
                "higher_timeframe_phase": "trend",
                "setup_phase": "short_continuation_confirmed",
                "setup_confirmed": True,
                "invalidation_type": "continuation_follow_through_failed",
                "follow_through_bars": 2,
                "trigger_bar_timestamp_ms": 300_000,
                "entry_price": 2055.61,
            }
            record_run(
                journal,
                settings,
                bundle=open_bundle,
                decision_action="sell",
                final_action="sell",
                symbol="ETH/USDT:USDT",
                confidence=0.80,
                risk_debug={"entry_thesis": entry_thesis},
                raw_payload_extra={"entry_thesis": entry_thesis},
            )

            weak_rebound_symbol = make_symbol(
                "ETH/USDT:USDT",
                1_200_000,
                2_047.80,
                atr_pct=0.0027,
                range_pct=0.0030,
                volume_ratio=1.10,
                higher_bias="short",
                higher_phase="trend",
            )
            weak_rebound_symbol.indicators["return_1bar"] = 0.00100
            weak_rebound_symbol.indicators["return_24bars"] = 0.00180
            weak_rebound_symbol.indicators["rsi_14"] = 47.0
            weak_rebound_symbol.indicators["sma_fast_ratio"] = 0.00060
            weak_rebound_symbol.indicators["sma_slow_ratio"] = -0.0040
            weak_rebound_bundle = make_bundle(
                timestamp_ms=1_200_000,
                symbols=[weak_rebound_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="ETH/USDT:USDT",
                        quantity=0.05,
                        mark_price=2_047.80,
                        market_value_quote=102.39,
                        side="short",
                        average_entry_price=2_055.61,
                        notional_quote=102.39,
                    )
                ],
                equity_quote=200.0,
                free_quote=190.0,
            )

            verdict = risk_engine.evaluate(make_decision("ETH/USDT:USDT", "hold", confidence=0.72), weak_rebound_bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertNotIn(
                "management_entry_thesis_invalidated:directional_follow_through_lost",
                verdict.reasons,
            )

    def test_risk_engine_allows_ai_close_on_profitable_eth_reclaim_short_when_reversal_confirms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                trailing_profit_arm_pct=0.0025,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            open_symbol = make_symbol(
                "ETH/USDT:USDT",
                300_000,
                2_070.0,
                atr_pct=0.0040,
                range_pct=0.0040,
                volume_ratio=1.20,
                higher_bias="short",
                higher_phase="reclaim",
            )
            open_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[open_symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )
            entry_thesis = {
                "version": 1,
                "direction": "short",
                "higher_timeframe_direction": "short",
                "higher_timeframe_phase": "reclaim",
                "setup_phase": "short_rebound_fail_confirmed",
                "setup_confirmed": True,
                "invalidation_type": "rebound_fail_reclaimed",
                "follow_through_bars": 2,
                "trigger_bar_timestamp_ms": 300_000,
            }
            record_run(
                journal,
                settings,
                bundle=open_bundle,
                decision_action="sell",
                final_action="sell",
                symbol="ETH/USDT:USDT",
                confidence=0.80,
                risk_debug={"entry_thesis": entry_thesis},
                raw_payload_extra={"entry_thesis": entry_thesis},
            )

            reversal_symbol = make_symbol(
                "ETH/USDT:USDT",
                1_200_000,
                2_058.0,
                atr_pct=0.0032,
                range_pct=0.0052,
                volume_ratio=1.9,
                higher_bias="short",
                higher_phase="reclaim",
            )
            reversal_symbol.indicators["return_1bar"] = 0.0021
            reversal_symbol.indicators["return_24bars"] = -0.0012
            reversal_symbol.indicators["rsi_14"] = 54.0
            reversal_symbol.indicators["sma_fast_ratio"] = 0.0011
            reversal_symbol.indicators["sma_slow_ratio"] = -0.0010
            reversal_bundle = make_bundle(
                timestamp_ms=1_200_000,
                symbols=[reversal_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="ETH/USDT:USDT",
                        quantity=0.05,
                        mark_price=2_058.0,
                        market_value_quote=102.9,
                        side="short",
                        average_entry_price=2_064.0,
                        notional_quote=102.9,
                    )
                ],
                equity_quote=200.0,
                free_quote=190.0,
            )

            verdict = risk_engine.evaluate(make_decision("ETH/USDT:USDT", "close", confidence=0.74), reversal_bundle)

            self.assertEqual(verdict.final_action, "close")
            self.assertNotIn("management_close_rejected_entry_thesis_still_supported", verdict.reasons)

    def test_risk_engine_records_shadow_open_signal_reasons_when_expected_edge_blocks_first(self) -> None:
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

            thin_short = make_symbol("XRP/USDT:USDT", 900_000, 1.4674, atr_pct=0.00148, range_pct=0.00198, volume_ratio=1.92, higher_bias="short")
            thin_short.indicators["return_1bar"] = -0.00089
            thin_short.indicators["return_24bars"] = 0.00232
            thin_short.indicators["sma_fast_ratio"] = -0.00203
            thin_short.indicators["sma_slow_ratio"] = -0.00021
            thin_short.indicators["rsi_14"] = 36.42
            thin_short.higher_timeframe = {
                "timeframe": "1h",
                "trend_bias": "short",
                "return_12bars": -0.01159,
                "sma_fast_ratio": -0.00518,
                "sma_slow_ratio": -0.00918,
                "rsi_14": 36.26,
            }
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[thin_short],
                equity_quote=157.0,
                free_quote=157.0,
            )

            verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "sell", confidence=0.69), bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertTrue(any(reason.startswith("expected_edge_below_minimum") for reason in verdict.reasons))
            self.assertIsNotNone(verdict.risk_debug)
            self.assertEqual(verdict.risk_debug["entry_archetype"], "plain_open")
            self.assertIn("open_signal_return_24bars_too_weak", verdict.risk_debug["shadow_open_signal_reasons"])
            self.assertLess(
                verdict.risk_debug["expected_edge_components"]["final_expected_edge_pct"],
                settings.min_expected_edge_pct,
            )

    def test_risk_engine_builds_entry_viability_preview_for_short_breakdown_candidate(self) -> None:
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

            symbol = make_symbol(
                "XRP/USDT:USDT",
                900_000,
                1.4084,
                atr_pct=0.00187,
                range_pct=0.00426,
                volume_ratio=4.09,
                higher_bias="short",
                higher_phase="trend",
            )
            symbol.indicators["return_1bar"] = -0.00255
            symbol.indicators["return_24bars"] = -0.00354
            symbol.indicators["rsi_14"] = 30.32
            symbol.indicators["sma_fast_ratio"] = -0.00258
            symbol.indicators["sma_slow_ratio"] = -0.00350
            symbol.recent_candles[-1].open = 1.4119
            symbol.recent_candles[-1].high = 1.4130
            symbol.recent_candles[-1].low = 1.4070
            symbol.recent_candles[-1].close = 1.4084
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )
            candidate_context = {
                "eligible": True,
                "manage_only": False,
                "score": 9.0,
                "higher_timeframe_bias": "short",
                "higher_timeframe_phase": "trend",
                "setup_phase": "short_breakdown_confirmed",
                "setup_confirmed": True,
                "entry_thesis_candidate": {
                    "version": 1,
                    "direction": "short",
                    "higher_timeframe_direction": "short",
                    "higher_timeframe_phase": "trend",
                    "setup_phase": "short_breakdown_confirmed",
                    "setup_confirmed": True,
                    "invalidation_type": "breakdown_reclaimed",
                    "follow_through_bars": 1,
                },
                "reasons": ["short_setup_breakdown_confirmed"],
            }

            preview = risk_engine.entry_viability_preview(
                bundle=bundle,
                symbol_snapshot=symbol,
                candidate_context=candidate_context,
            )

            self.assertIsNotNone(preview)
            self.assertEqual(preview["preview_action"], "sell")
            self.assertEqual(preview["shadow_open_signal_reasons"], [])
            self.assertGreaterEqual(
                preview["expected_edge"]["required_threshold_pct"],
                settings.min_expected_edge_pct,
            )
            self.assertIn("edge_surplus_pct", preview["expected_edge"])

    def test_risk_engine_tightens_plain_alt_short_edge_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("BTC/USDT:USDT", "SOL/USDT:USDT"),
                min_expected_edge_pct=0.0010,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            btc_short = make_symbol("BTC/USDT:USDT", 900_000, 103_000.0, atr_pct=0.0019, range_pct=0.0021, volume_ratio=0.80, higher_bias="short")
            btc_short.indicators["return_1bar"] = -0.00055
            btc_short.indicators["return_24bars"] = -0.00197
            btc_short.indicators["sma_fast_ratio"] = -0.00093
            btc_short.indicators["sma_slow_ratio"] = -0.00142
            btc_short.indicators["rsi_14"] = 46.9
            btc_short.higher_timeframe = {
                "timeframe": "1h",
                "trend_bias": "short",
                "return_12bars": -0.01159,
                "sma_fast_ratio": -0.00518,
                "sma_slow_ratio": -0.00918,
                "rsi_14": 36.26,
            }
            btc_short.recent_candles[-1].open = 103_050.0
            btc_short.recent_candles[-1].high = 103_070.0
            btc_short.recent_candles[-1].low = 102_960.0
            btc_short.recent_candles[-1].close = 103_000.0
            sol_short = make_symbol("SOL/USDT:USDT", 900_000, 89.20, atr_pct=0.0019, range_pct=0.0021, volume_ratio=0.80, higher_bias="short")
            sol_short.indicators["return_1bar"] = -0.0007
            sol_short.indicators["return_24bars"] = -0.0008
            sol_short.indicators["sma_fast_ratio"] = -0.0010
            sol_short.indicators["sma_slow_ratio"] = -0.0012
            sol_short.indicators["rsi_14"] = 44.5
            sol_short.higher_timeframe = {
                "timeframe": "1h",
                "trend_bias": "short",
                "return_12bars": -0.0060,
                "sma_fast_ratio": -0.0040,
                "sma_slow_ratio": -0.0050,
                "rsi_14": 43.0,
            }
            bundle_btc = make_bundle(
                timestamp_ms=900_000,
                symbols=[btc_short],
                equity_quote=200.0,
                free_quote=200.0,
            )
            bundle_sol = make_bundle(
                timestamp_ms=900_000,
                symbols=[sol_short],
                equity_quote=200.0,
                free_quote=200.0,
            )

            btc_verdict = risk_engine.evaluate(make_decision("BTC/USDT:USDT", "sell", confidence=0.68), bundle_btc)
            sol_verdict = risk_engine.evaluate(make_decision("SOL/USDT:USDT", "sell", confidence=0.68), bundle_sol)

            self.assertEqual(btc_verdict.final_action, "sell")
            self.assertEqual(sol_verdict.final_action, "hold")
            self.assertTrue(any(reason.startswith("expected_edge_below_minimum") for reason in sol_verdict.reasons))

    def test_risk_engine_rejects_correlated_third_short_when_group_exposure_would_breach_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"),
                max_open_positions=3,
                max_correlated_directional_exposure_pct=0.25,
                max_net_directional_exposure_pct=0.40,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            sol_short = make_symbol("SOL/USDT:USDT", 900_000, 89.20, atr_pct=0.0044, range_pct=0.0041, volume_ratio=1.65, higher_bias="short")
            sol_short.indicators["return_1bar"] = -0.0012
            sol_short.indicators["return_24bars"] = -0.0064
            sol_short.indicators["sma_fast_ratio"] = -0.0032
            sol_short.indicators["sma_slow_ratio"] = -0.0062
            sol_short.indicators["rsi_14"] = 35.4
            sol_short.higher_timeframe = {
                "timeframe": "1h",
                "trend_bias": "short",
                "return_12bars": -0.0190,
                "sma_fast_ratio": -0.0080,
                "sma_slow_ratio": -0.0120,
                "rsi_14": 37.1,
            }
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[sol_short],
                open_positions=[
                    PositionSnapshot(
                        symbol="BTC/USDT:USDT",
                        quantity=0.001,
                        mark_price=100_000.0,
                        market_value_quote=60.0,
                        side="short",
                        average_entry_price=101_000.0,
                        notional_quote=60.0,
                    ),
                    PositionSnapshot(
                        symbol="ETH/USDT:USDT",
                        quantity=0.02,
                        mark_price=3_000.0,
                        market_value_quote=60.0,
                        side="short",
                        average_entry_price=3_050.0,
                        notional_quote=60.0,
                    ),
                ],
                equity_quote=200.0,
                free_quote=160.0,
            )

            verdict = risk_engine.evaluate(make_decision("SOL/USDT:USDT", "sell", confidence=0.73), bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertTrue(any(reason.startswith("portfolio_correlated_directional_exposure_limit") for reason in verdict.reasons))
            self.assertIsNotNone(verdict.risk_debug)
            portfolio_context = verdict.risk_debug["portfolio_context"]
            self.assertEqual(portfolio_context["target_group"], "crypto_beta")
            self.assertGreater(float(portfolio_context["projected_correlated_exposure_pct"]), 0.25)

    def test_risk_engine_requires_extra_edge_for_third_same_direction_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"),
                max_open_positions=3,
                min_expected_edge_pct=0.0010,
                max_correlated_directional_exposure_pct=0.35,
                max_net_directional_exposure_pct=0.40,
                third_same_direction_edge_buffer_pct=0.00075,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            btc_short = make_symbol("BTC/USDT:USDT", 900_000, 103_000.0, atr_pct=0.0019, range_pct=0.0021, volume_ratio=0.80, higher_bias="short")
            btc_short.indicators["return_1bar"] = -0.0012
            btc_short.indicators["return_24bars"] = -0.0048
            btc_short.indicators["sma_fast_ratio"] = -0.0010
            btc_short.indicators["sma_slow_ratio"] = -0.0012
            btc_short.indicators["rsi_14"] = 44.5
            btc_short.higher_timeframe = {
                "timeframe": "1h",
                "trend_bias": "short",
                "return_12bars": -0.0060,
                "sma_fast_ratio": -0.0040,
                "sma_slow_ratio": -0.0050,
                "rsi_14": 43.0,
            }
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[btc_short],
                open_positions=[
                    PositionSnapshot(
                        symbol="ETH/USDT:USDT",
                        quantity=0.02,
                        mark_price=3_000.0,
                        market_value_quote=60.0,
                        side="short",
                        average_entry_price=3_050.0,
                        notional_quote=60.0,
                    ),
                    PositionSnapshot(
                        symbol="SOL/USDT:USDT",
                        quantity=0.67,
                        mark_price=89.5,
                        market_value_quote=60.0,
                        side="short",
                        average_entry_price=90.2,
                        notional_quote=60.0,
                    ),
                ],
                equity_quote=200.0,
                free_quote=160.0,
            )

            verdict = risk_engine.evaluate(make_decision("BTC/USDT:USDT", "sell", confidence=0.66), bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertTrue(any(reason.startswith("expected_edge_below_minimum") for reason in verdict.reasons))
            self.assertIsNotNone(verdict.risk_debug)
            components = verdict.risk_debug["expected_edge_components"]
            self.assertAlmostEqual(components["required_threshold_pct"], 0.00225, places=6)
            self.assertAlmostEqual(components["weak_same_direction_edge_buffer_pct"], 0.0005, places=6)
            self.assertAlmostEqual(verdict.risk_debug["portfolio_context"]["third_same_direction_edge_buffer_pct"], 0.00075, places=6)

    def test_risk_engine_requires_extra_edge_for_second_same_direction_weak_short(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("BTC/USDT:USDT", "ETH/USDT:USDT"),
                max_open_positions=3,
                min_expected_edge_pct=0.0010,
                max_correlated_directional_exposure_pct=0.35,
                max_net_directional_exposure_pct=0.40,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            btc_short = make_symbol("BTC/USDT:USDT", 900_000, 103_000.0, atr_pct=0.0019, range_pct=0.0021, volume_ratio=0.80, higher_bias="short")
            btc_short.indicators["return_1bar"] = -0.0007
            btc_short.indicators["return_24bars"] = -0.0008
            btc_short.indicators["sma_fast_ratio"] = -0.0010
            btc_short.indicators["sma_slow_ratio"] = -0.0012
            btc_short.indicators["rsi_14"] = 44.5
            btc_short.higher_timeframe = {
                "timeframe": "1h",
                "trend_bias": "short",
                "return_12bars": -0.0060,
                "sma_fast_ratio": -0.0040,
                "sma_slow_ratio": -0.0050,
                "rsi_14": 43.0,
            }
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[btc_short],
                open_positions=[
                    PositionSnapshot(
                        symbol="ETH/USDT:USDT",
                        quantity=0.02,
                        mark_price=3_000.0,
                        market_value_quote=60.0,
                        side="short",
                        average_entry_price=3_050.0,
                        notional_quote=60.0,
                    ),
                ],
                equity_quote=200.0,
                free_quote=160.0,
            )

            verdict = risk_engine.evaluate(make_decision("BTC/USDT:USDT", "sell", confidence=0.68), bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertTrue(any(reason.startswith("expected_edge_below_minimum") for reason in verdict.reasons))
            self.assertIsNotNone(verdict.risk_debug)
            components = verdict.risk_debug["expected_edge_components"]
            self.assertAlmostEqual(components["required_threshold_pct"], 0.0015, places=6)
            self.assertAlmostEqual(components["weak_same_direction_edge_buffer_pct"], 0.0005, places=6)

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

            flat_bias_short = make_symbol("SOL/USDT:USDT", 900_000, 100.0, atr_pct=0.0044, range_pct=0.0048, volume_ratio=1.45, higher_bias="flat")
            flat_bias_short.indicators["return_1bar"] = -0.0013
            flat_bias_short.indicators["return_24bars"] = -0.0042
            flat_bias_short.indicators["rsi_14"] = 39.5
            flat_bias_short.indicators["sma_fast_ratio"] = -0.0019
            flat_bias_short.indicators["sma_slow_ratio"] = -0.0016
            flat_bias_short.recent_candles[-1].open = 100.48
            flat_bias_short.recent_candles[-1].high = 100.52
            flat_bias_short.recent_candles[-1].low = 99.88
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

    def test_risk_engine_blocks_weak_short_exhaustion_flush_plain_open_sample(self) -> None:
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

            exhaustion_short = make_symbol("SOL/USDT:USDT", 900_000, 85.79, atr_pct=0.0022063843604815674, range_pct=0.004429420678400858, volume_ratio=5.916335732178943, higher_bias="short")
            exhaustion_short.indicators["return_1bar"] = -0.0004660375160199237
            exhaustion_short.indicators["return_24bars"] = -0.009010049670786446
            exhaustion_short.indicators["sma_fast_ratio"] = -0.0038800568945998037
            exhaustion_short.indicators["sma_slow_ratio"] = -0.007397658492844461
            exhaustion_short.indicators["rsi_14"] = 13.26530612244865
            exhaustion_short.higher_timeframe = {
                "timeframe": "1h",
                "trend_bias": "short",
                "return_12bars": -0.0010443258296588542,
                "sma_fast_ratio": -0.004643992677521802,
                "sma_slow_ratio": -0.011245848606950326,
                "rsi_14": 55.102040816326735,
            }
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[exhaustion_short],
                equity_quote=200.0,
                free_quote=200.0,
            )

            verdict = risk_engine.evaluate(
                make_decision("SOL/USDT:USDT", "sell", confidence=0.63, take_profit_pct=0.02, stop_loss_pct=0.008),
                bundle,
            )

            self.assertEqual(verdict.final_action, "hold")
            self.assertIn("fresh_entry_short_exhaustion_flush", verdict.reasons)
            self.assertEqual(verdict.risk_debug["entry_archetype"], "short_exhaustion_flush")

    def test_risk_engine_does_not_grant_pre_break_bonus_to_weak_low_volume_rebound_short(self) -> None:
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

            weak_watch_short = make_symbol("XRP/USDT:USDT", 900_000, 1.4067, atr_pct=0.001980318678975105, range_pct=0.002061562522215202, volume_ratio=0.6506507054409769, higher_bias="short")
            weak_watch_short.indicators["return_1bar"] = 0.0009250035577059723
            weak_watch_short.indicators["return_24bars"] = -0.00438813787246084
            weak_watch_short.indicators["sma_fast_ratio"] = -0.0003967525507635461
            weak_watch_short.indicators["sma_slow_ratio"] = -0.003712381885464966
            weak_watch_short.indicators["rsi_14"] = 42.26804123711363
            weak_watch_short.higher_timeframe = {
                "timeframe": "1h",
                "trend_bias": "short",
                "return_12bars": -0.005599659767507759,
                "sma_fast_ratio": -0.0070015041141946455,
                "sma_slow_ratio": -0.008565833836368775,
                "rsi_14": 36.07843137254905,
            }
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[weak_watch_short],
                equity_quote=200.0,
                free_quote=200.0,
            )

            verdict = risk_engine.evaluate(
                make_decision("XRP/USDT:USDT", "sell", confidence=0.63, take_profit_pct=0.02, stop_loss_pct=0.0075),
                bundle,
            )

            self.assertEqual(verdict.final_action, "hold")
            self.assertTrue(any(reason.startswith("expected_edge_below_minimum") for reason in verdict.reasons))
            self.assertEqual(
                verdict.risk_debug["expected_edge_components"]["bonuses"]["pre_break_continuation_bonus_pct"],
                0.0,
            )

    def test_risk_engine_blocks_weak_eth_short_continuation_even_when_base_edge_is_close(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            weak_eth_continuation = make_symbol(
                "ETH/USDT:USDT",
                900_000,
                2058.11,
                atr_pct=0.002006695463313418,
                range_pct=0.001953248368648897,
                volume_ratio=0.701164052974016,
                higher_bias="short",
                higher_phase="trend",
            )
            weak_eth_continuation.indicators["return_1bar"] = -0.0005244780714747099
            weak_eth_continuation.indicators["return_24bars"] = -0.006012866084537438
            weak_eth_continuation.indicators["sma_fast_ratio"] = -0.0022417656823607857
            weak_eth_continuation.indicators["sma_slow_ratio"] = -0.005246284146385949
            weak_eth_continuation.indicators["rsi_14"] = 48.69109947644002
            weak_eth_continuation.recent_candles[-1].open = 2059.20
            weak_eth_continuation.recent_candles[-1].high = 2060.70
            weak_eth_continuation.recent_candles[-1].low = 2056.68
            weak_eth_continuation.recent_candles[-1].close = 2058.11
            weak_eth_continuation.higher_timeframe = {
                "timeframe": "1h",
                "trend_bias": "short",
                "trend_direction": "short",
                "trend_phase": "trend",
                "trend_strength": 3.0,
                "return_12bars": -0.00824836475567503,
                "sma_fast_ratio": -0.005721463302713614,
                "sma_slow_ratio": -0.01059632677198874,
                "rsi_14": 34.359356694003736,
            }
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[weak_eth_continuation],
                equity_quote=200.0,
                free_quote=200.0,
            )

            verdict = risk_engine.evaluate(
                make_decision("ETH/USDT:USDT", "sell", confidence=0.64, take_profit_pct=0.0, stop_loss_pct=0.0045),
                bundle,
            )

            self.assertEqual(verdict.final_action, "hold")
            self.assertTrue(any(reason.startswith("expected_edge_below_minimum") for reason in verdict.reasons))
            self.assertEqual(
                verdict.risk_debug["expected_edge_components"]["bonuses"]["pre_break_continuation_bonus_pct"],
                0.0,
            )
            self.assertEqual(
                verdict.risk_debug["expected_edge_components"]["fresh_entry_bias_adjustments"]["weak_pre_break_continuation_short_penalty_pct"],
                -0.00020,
            )

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

    def test_risk_engine_closes_profitable_long_when_local_momentum_cools_after_extension(self) -> None:
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

            cooled_long = make_symbol("SOL/USDT:USDT", 900_000, 93.12, atr_pct=0.00405, range_pct=0.00289, volume_ratio=0.98, higher_bias="long")
            cooled_long.indicators["return_1bar"] = 0.00269
            cooled_long.indicators["return_24bars"] = 0.00583
            cooled_long.indicators["sma_fast_ratio"] = 0.00324
            cooled_long.indicators["sma_slow_ratio"] = 0.00791
            cooled_long.indicators["rsi_14"] = 50.45
            cooled_long.higher_timeframe = {
                "timeframe": "1h",
                "trend_bias": "long",
                "return_12bars": 0.0314,
                "sma_fast_ratio": 0.0200,
                "sma_slow_ratio": 0.0234,
                "rsi_14": 69.3,
            }
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[cooled_long],
                open_positions=[
                    PositionSnapshot(
                        symbol="SOL/USDT:USDT",
                        quantity=0.78,
                        mark_price=93.12,
                        market_value_quote=72.63,
                        side="long",
                        average_entry_price=92.39,
                        notional_quote=72.63,
                    )
                ],
                equity_quote=201.0,
                free_quote=176.0,
            )

            verdict = risk_engine.evaluate(make_decision("SOL/USDT:USDT", "hold", confidence=0.78), bundle)

            self.assertEqual(verdict.final_action, "close")
            self.assertIn("management_profitable_long_momentum_cooldown_close", verdict.reasons)

    def test_risk_engine_keeps_profitable_long_open_while_local_rsi_remains_hot(self) -> None:
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

            still_hot_long = make_symbol("SOL/USDT:USDT", 900_000, 93.10, atr_pct=0.00328, range_pct=0.00471, volume_ratio=1.01, higher_bias="long")
            still_hot_long.indicators["return_1bar"] = -0.00064
            still_hot_long.indicators["return_24bars"] = 0.02612
            still_hot_long.indicators["sma_fast_ratio"] = 0.00691
            still_hot_long.indicators["sma_slow_ratio"] = 0.01737
            still_hot_long.indicators["rsi_14"] = 73.16
            still_hot_long.higher_timeframe = {
                "timeframe": "1h",
                "trend_bias": "long",
                "return_12bars": 0.0357,
                "sma_fast_ratio": 0.0208,
                "sma_slow_ratio": 0.0227,
                "rsi_14": 63.2,
            }
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[still_hot_long],
                open_positions=[
                    PositionSnapshot(
                        symbol="SOL/USDT:USDT",
                        quantity=0.78,
                        mark_price=93.10,
                        market_value_quote=72.61,
                        side="long",
                        average_entry_price=92.39,
                        notional_quote=72.61,
                    )
                ],
                equity_quote=201.0,
                free_quote=176.0,
            )

            verdict = risk_engine.evaluate(make_decision("SOL/USDT:USDT", "hold", confidence=0.78), bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertNotIn("management_profitable_long_momentum_cooldown_close", verdict.reasons)

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

    def test_journal_recent_signal_actions_includes_entry_thesis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()

            entry_symbol = make_symbol(
                "XRP/USDT:USDT",
                300_000,
                1.50,
                atr_pct=0.0040,
                range_pct=0.0040,
                volume_ratio=1.20,
                higher_bias="short",
                higher_phase="trend",
            )
            record_run(
                journal,
                settings,
                bundle=make_bundle(timestamp_ms=300_000, symbols=[entry_symbol], equity_quote=200.0, free_quote=200.0),
                decision_action="sell",
                final_action="sell",
                symbol="XRP/USDT:USDT",
                confidence=0.90,
                risk_debug={
                    "entry_thesis": {
                        "direction": "short",
                        "setup_phase": "short_continuation_confirmed",
                        "higher_timeframe_phase": "trend",
                        "invalidation_type": "continuation_follow_through_failed",
                        "follow_through_bars": 2,
                    }
                },
            )

            recent_actions = journal.get_recent_signal_actions(limit=5, symbol="XRP/USDT:USDT")

            self.assertEqual(len(recent_actions), 1)
            self.assertEqual(recent_actions[0]["entry_setup_phase"], "short_continuation_confirmed")
            self.assertEqual(recent_actions[0]["entry_higher_timeframe_phase"], "trend")
            self.assertEqual(recent_actions[0]["entry_thesis"]["invalidation_type"], "continuation_follow_through_failed")

    def test_risk_engine_management_close_can_be_rejected_when_entry_thesis_still_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
                min_hold_bars=1,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            entry_symbol = make_symbol(
                "XRP/USDT:USDT",
                300_000,
                1.4067,
                atr_pct=0.0020,
                range_pct=0.0020,
                volume_ratio=0.72,
                higher_bias="short",
                higher_phase="trend",
            )
            entry_symbol.indicators["return_1bar"] = 0.0002
            entry_symbol.indicators["return_24bars"] = -0.0044
            entry_symbol.indicators["sma_fast_ratio"] = -0.0009
            entry_symbol.indicators["sma_slow_ratio"] = -0.0014
            record_run(
                journal,
                settings,
                bundle=make_bundle(timestamp_ms=300_000, symbols=[entry_symbol], equity_quote=200.0, free_quote=200.0),
                decision_action="sell",
                final_action="sell",
                symbol="XRP/USDT:USDT",
                confidence=0.62,
                risk_debug={
                    "entry_thesis": {
                        "direction": "short",
                        "setup_phase": "short_continuation_confirmed",
                        "setup_confirmed": True,
                        "higher_timeframe_phase": "trend",
                        "follow_through_bars": 2,
                    }
                },
            )

            manage_symbol = make_symbol(
                "XRP/USDT:USDT",
                600_000,
                1.4076,
                atr_pct=0.0020,
                range_pct=0.0016,
                volume_ratio=0.33,
                higher_bias="short",
                higher_phase="trend",
            )
            manage_symbol.indicators["return_1bar"] = 0.00064
            manage_symbol.indicators["return_24bars"] = -0.00403
            manage_symbol.indicators["sma_fast_ratio"] = 0.00050
            manage_symbol.indicators["sma_slow_ratio"] = -0.00299
            manage_symbol.indicators["rsi_14"] = 38.1
            bundle = make_bundle(
                timestamp_ms=600_000,
                symbols=[manage_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="XRP/USDT:USDT",
                        quantity=85.3,
                        mark_price=1.4076,
                        market_value_quote=120.08,
                        side="short",
                        average_entry_price=1.4067,
                        notional_quote=120.08,
                    )
                ],
                equity_quote=199.92,
                free_quote=180.0,
            )

            verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "close", confidence=0.72), bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertIn("management_close_rejected_entry_thesis_still_supported", verdict.reasons)

    def test_risk_engine_bottom_line_mode_still_rejects_close_when_entry_thesis_still_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
                rule_mode="bottom_line",
                min_hold_bars=1,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            entry_symbol = make_symbol(
                "XRP/USDT:USDT",
                300_000,
                1.4067,
                atr_pct=0.0020,
                range_pct=0.0020,
                volume_ratio=0.72,
                higher_bias="short",
                higher_phase="trend",
            )
            entry_symbol.indicators["return_1bar"] = 0.0002
            entry_symbol.indicators["return_24bars"] = -0.0044
            entry_symbol.indicators["sma_fast_ratio"] = -0.0009
            entry_symbol.indicators["sma_slow_ratio"] = -0.0014
            record_run(
                journal,
                settings,
                bundle=make_bundle(timestamp_ms=300_000, symbols=[entry_symbol], equity_quote=200.0, free_quote=200.0),
                decision_action="sell",
                final_action="sell",
                symbol="XRP/USDT:USDT",
                confidence=0.62,
                risk_debug={
                    "entry_thesis": {
                        "direction": "short",
                        "setup_phase": "short_continuation_confirmed",
                        "setup_confirmed": True,
                        "higher_timeframe_phase": "trend",
                        "follow_through_bars": 2,
                        "invalidation_type": "continuation_follow_through_failed",
                    }
                },
            )

            manage_symbol = make_symbol(
                "XRP/USDT:USDT",
                600_000,
                1.4076,
                atr_pct=0.0020,
                range_pct=0.0016,
                volume_ratio=0.33,
                higher_bias="short",
                higher_phase="trend",
            )
            manage_symbol.indicators["return_1bar"] = 0.00064
            manage_symbol.indicators["return_24bars"] = -0.00403
            manage_symbol.indicators["sma_fast_ratio"] = 0.00050
            manage_symbol.indicators["sma_slow_ratio"] = -0.00299
            manage_symbol.indicators["rsi_14"] = 38.1
            bundle = make_bundle(
                timestamp_ms=600_000,
                symbols=[manage_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="XRP/USDT:USDT",
                        quantity=85.3,
                        mark_price=1.4076,
                        market_value_quote=120.08,
                        side="short",
                        average_entry_price=1.4067,
                        notional_quote=120.08,
                    )
                ],
                equity_quote=199.92,
                free_quote=180.0,
            )

            verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "close", confidence=0.72), bundle)

            self.assertEqual(verdict.final_action, "hold")
            self.assertIn("management_close_rejected_entry_thesis_still_supported", verdict.reasons)

    def test_risk_engine_forces_close_when_entry_thesis_invalidates(self) -> None:
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

            record_run(
                journal,
                settings,
                bundle=make_bundle(
                    timestamp_ms=300_000,
                    symbols=[make_symbol("XRP/USDT:USDT", 300_000, 1.4067, atr_pct=0.0020, range_pct=0.0020, volume_ratio=0.72, higher_bias="short", higher_phase="trend")],
                    equity_quote=200.0,
                    free_quote=200.0,
                ),
                decision_action="sell",
                final_action="sell",
                symbol="XRP/USDT:USDT",
                confidence=0.62,
                risk_debug={
                    "entry_thesis": {
                        "direction": "short",
                        "setup_phase": "short_continuation_confirmed",
                        "setup_confirmed": True,
                        "higher_timeframe_phase": "trend",
                        "follow_through_bars": 2,
                    }
                },
            )

            invalidated_symbol = make_symbol(
                "XRP/USDT:USDT",
                1_200_000,
                1.4110,
                atr_pct=0.0020,
                range_pct=0.0018,
                volume_ratio=0.60,
                higher_bias="short",
                higher_phase="trend",
            )
            invalidated_symbol.indicators["return_1bar"] = 0.0019
            invalidated_symbol.indicators["return_24bars"] = 0.0018
            invalidated_symbol.indicators["sma_fast_ratio"] = 0.0015
            invalidated_symbol.indicators["sma_slow_ratio"] = -0.0002
            invalidated_symbol.indicators["rsi_14"] = 51.0
            bundle = make_bundle(
                timestamp_ms=1_200_000,
                symbols=[invalidated_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="XRP/USDT:USDT",
                        quantity=85.3,
                        mark_price=1.4110,
                        market_value_quote=120.37,
                        side="short",
                        average_entry_price=1.4067,
                        notional_quote=120.37,
                    )
                ],
                equity_quote=199.63,
                free_quote=180.0,
            )

            verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "hold", confidence=0.72), bundle)

            self.assertEqual(verdict.final_action, "close")
            self.assertTrue(any(reason.startswith("management_entry_thesis_invalidated:") for reason in verdict.reasons))

    def test_risk_engine_keeps_short_breakdown_open_while_thesis_still_holds(self) -> None:
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

            record_run(
                journal,
                settings,
                bundle=make_bundle(
                    timestamp_ms=300_000,
                    symbols=[make_symbol("XRP/USDT:USDT", 300_000, 1.4084, atr_pct=0.00187, range_pct=0.00426, volume_ratio=4.09, higher_bias="short", higher_phase="trend")],
                    equity_quote=200.0,
                    free_quote=200.0,
                ),
                decision_action="sell",
                final_action="sell",
                symbol="XRP/USDT:USDT",
                confidence=0.62,
                risk_debug={
                    "entry_thesis": {
                        "direction": "short",
                        "setup_phase": "short_breakdown_confirmed",
                        "setup_confirmed": True,
                        "higher_timeframe_phase": "trend",
                        "follow_through_bars": 1,
                        "invalidation_type": "breakdown_reclaimed",
                    }
                },
            )

            invalidated_symbol = make_symbol(
                "XRP/USDT:USDT",
                600_000,
                1.4076,
                atr_pct=0.00195,
                range_pct=0.00156,
                volume_ratio=0.33,
                higher_bias="short",
                higher_phase="trend",
            )
            invalidated_symbol.indicators["return_1bar"] = 0.00064
            invalidated_symbol.indicators["return_24bars"] = -0.00403
            invalidated_symbol.indicators["sma_fast_ratio"] = 0.00050
            invalidated_symbol.indicators["sma_slow_ratio"] = -0.00299
            invalidated_symbol.indicators["rsi_14"] = 38.12
            bundle = make_bundle(
                timestamp_ms=600_000,
                symbols=[invalidated_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="XRP/USDT:USDT",
                        quantity=85.3,
                        mark_price=1.4076,
                        market_value_quote=120.08,
                        side="short",
                        average_entry_price=1.4084,
                        notional_quote=120.08,
                    )
                ],
                equity_quote=200.07,
                free_quote=180.0,
            )

            verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "hold", confidence=0.69), bundle)

            self.assertEqual(verdict.final_action, "hold")

    def test_risk_engine_forces_close_when_short_breakdown_thesis_invalidates(self) -> None:
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

            record_run(
                journal,
                settings,
                bundle=make_bundle(
                    timestamp_ms=300_000,
                    symbols=[make_symbol("XRP/USDT:USDT", 300_000, 1.4084, atr_pct=0.00187, range_pct=0.00426, volume_ratio=4.09, higher_bias="short", higher_phase="trend")],
                    equity_quote=200.0,
                    free_quote=200.0,
                ),
                decision_action="sell",
                final_action="sell",
                symbol="XRP/USDT:USDT",
                confidence=0.62,
                risk_debug={
                    "entry_thesis": {
                        "direction": "short",
                        "setup_phase": "short_breakdown_confirmed",
                        "setup_confirmed": True,
                        "higher_timeframe_phase": "trend",
                        "follow_through_bars": 1,
                        "invalidation_type": "breakdown_reclaimed",
                    }
                },
            )

            invalidated_symbol = make_symbol(
                "XRP/USDT:USDT",
                600_000,
                1.4105,
                atr_pct=0.00195,
                range_pct=0.00156,
                volume_ratio=0.50,
                higher_bias="short",
                higher_phase="trend",
            )
            invalidated_symbol.indicators["return_1bar"] = 0.0018
            invalidated_symbol.indicators["return_24bars"] = -0.0007
            invalidated_symbol.indicators["sma_fast_ratio"] = 0.0016
            invalidated_symbol.indicators["sma_slow_ratio"] = -0.0005
            invalidated_symbol.indicators["rsi_14"] = 46.5
            bundle = make_bundle(
                timestamp_ms=600_000,
                symbols=[invalidated_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="XRP/USDT:USDT",
                        quantity=85.3,
                        mark_price=1.4105,
                        market_value_quote=120.33,
                        side="short",
                        average_entry_price=1.4084,
                        notional_quote=120.33,
                    )
                ],
                equity_quote=199.82,
                free_quote=180.0,
            )

            verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "hold", confidence=0.69), bundle)

            self.assertEqual(verdict.final_action, "close")
            self.assertTrue(any(reason.startswith("management_entry_thesis_invalidated:") for reason in verdict.reasons))

    def test_risk_engine_bottom_line_mode_keeps_ai_open_intent_and_tight_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            strict_settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
                min_notional_quote=5.0,
            )
            bottom_line_settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
                min_notional_quote=5.0,
                rule_mode="bottom_line",
            )
            strict_journal = Journal(strict_settings.db_path)
            strict_journal.ensure_schema()
            bottom_line_journal = Journal(bottom_line_settings.db_path)
            bottom_line_journal.ensure_schema()
            strict_risk_engine = RiskEngine(strict_settings, strict_journal)
            bottom_line_risk_engine = RiskEngine(bottom_line_settings, bottom_line_journal)

            weak_short = make_symbol("XRP/USDT:USDT", 900_000, 1.5, atr_pct=0.0016, range_pct=0.0015, volume_ratio=0.40, higher_bias="short")
            weak_short.indicators["return_1bar"] = 0.0008
            weak_short.indicators["return_24bars"] = 0.0004
            weak_short.indicators["sma_fast_ratio"] = 0.0002
            weak_short.indicators["sma_slow_ratio"] = 0.0001
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[weak_short],
                equity_quote=200.0,
                free_quote=200.0,
            )
            decision = make_decision(
                "XRP/USDT:USDT",
                "sell",
                size_pct=0.04,
                take_profit_pct=0.005,
                stop_loss_pct=0.006,
            )

            strict_verdict = strict_risk_engine.evaluate(decision, bundle)
            self.assertEqual(strict_verdict.final_action, "hold")
            self.assertTrue(any(reason.startswith("expected_edge_below_minimum") for reason in strict_verdict.reasons))

            bottom_line_verdict = bottom_line_risk_engine.evaluate(decision, bundle)
            self.assertEqual(bottom_line_verdict.final_action, "sell")
            self.assertAlmostEqual(bottom_line_verdict.final_size_pct, 0.04, places=9)
            self.assertAlmostEqual(bottom_line_verdict.take_profit_pct, 0.005, places=9)
            self.assertAlmostEqual(bottom_line_verdict.stop_loss_pct, 0.006, places=9)
            self.assertTrue(bottom_line_verdict.approved)

    def test_risk_engine_bottom_line_mode_allows_ai_close_before_min_hold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            strict_settings = make_settings(
                root,
                market_type="future",
                symbols=("BTC/USDT:USDT",),
            )
            bottom_line_settings = make_settings(
                root,
                market_type="future",
                symbols=("BTC/USDT:USDT",),
                rule_mode="bottom_line",
            )
            strict_journal = Journal(strict_settings.db_path)
            strict_journal.ensure_schema()
            bottom_line_journal = Journal(bottom_line_settings.db_path)
            bottom_line_journal.ensure_schema()
            strict_risk_engine = RiskEngine(strict_settings, strict_journal)
            bottom_line_risk_engine = RiskEngine(bottom_line_settings, bottom_line_journal)

            previous_open_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[make_symbol("BTC/USDT:USDT", 300_000, 98.0, atr_pct=0.0040, range_pct=0.0045, volume_ratio=1.10, higher_bias="long")],
            )
            previous_open_bundle.account.market_type = "future"
            record_run(strict_journal, strict_settings, bundle=previous_open_bundle, decision_action="buy", final_action="buy", symbol="BTC/USDT:USDT")
            record_run(bottom_line_journal, bottom_line_settings, bundle=previous_open_bundle, decision_action="buy", final_action="buy", symbol="BTC/USDT:USDT")

            close_bundle = make_bundle(
                timestamp_ms=600_000,
                symbols=[make_symbol("BTC/USDT:USDT", 600_000, 100.0, atr_pct=0.0040, range_pct=0.0050, volume_ratio=1.10, higher_bias="long")],
                open_positions=[
                    PositionSnapshot(
                        symbol="BTC/USDT:USDT",
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
            close_bundle.account.market_type = "future"

            strict_verdict = strict_risk_engine.evaluate(make_decision("BTC/USDT:USDT", "close"), close_bundle)
            self.assertEqual(strict_verdict.final_action, "hold")
            self.assertTrue(any(reason.startswith("min_hold_bars_active") for reason in strict_verdict.reasons))

            bottom_line_verdict = bottom_line_risk_engine.evaluate(make_decision("BTC/USDT:USDT", "close"), close_bundle)
            self.assertEqual(bottom_line_verdict.final_action, "close")
            self.assertTrue(bottom_line_verdict.approved)

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

    def test_risk_engine_bottom_line_mode_still_applies_trailing_profit_retrace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
                rule_mode="bottom_line",
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
            recent_actions = journal.get_recent_signal_actions(limit=10, symbol="XRP/USDT:USDT")
            last_open = next(item for item in recent_actions if item["final_action"] == "sell")
            peak_key = risk_engine._trailing_profit_peak_key("XRP/USDT:USDT", int(last_open["run_id"]))
            journal.set_runtime_state(peak_key, 0.015333333333333309)

            verdict = risk_engine.evaluate(make_decision("XRP/USDT:USDT", "hold"), retraced_bundle)

            self.assertEqual(verdict.final_action, "close")
            self.assertTrue(any(reason.startswith("management_trailing_profit_retrace:") for reason in verdict.reasons))

    def test_risk_engine_persists_initial_trailing_peak_before_retrace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                trailing_profit_arm_pct=0.0018,
                trailing_profit_retrace_pct=0.0030,
                partial_take_profit_enable=False,
                dynamic_protective_refresh_enable=False,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            entry_thesis = {
                "version": 1,
                "direction": "short",
                "higher_timeframe_direction": "short",
                "higher_timeframe_phase": "reclaim",
                "setup_phase": "short_rebound_fail_confirmed",
                "setup_confirmed": True,
                "invalidation_type": "rebound_fail_reclaimed",
                "follow_through_bars": 2,
                "trigger_bar_timestamp_ms": 300_000,
            }
            open_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[
                    make_symbol(
                        "ETH/USDT:USDT",
                        300_000,
                        2_316.88,
                        atr_pct=0.00163,
                        range_pct=0.00341,
                        volume_ratio=3.13,
                        higher_bias="short",
                        higher_phase="reclaim",
                    )
                ],
                equity_quote=200.0,
                free_quote=200.0,
            )
            record_run(
                journal,
                settings,
                bundle=open_bundle,
                decision_action="sell",
                final_action="sell",
                symbol="ETH/USDT:USDT",
                confidence=0.80,
                risk_debug={"entry_thesis": entry_thesis},
                raw_payload_extra={"entry_thesis": entry_thesis},
            )
            recent_actions = journal.get_recent_signal_actions(limit=10, symbol="ETH/USDT:USDT")
            last_open = next(item for item in recent_actions if item["final_action"] == "sell")
            peak_key = risk_engine._trailing_profit_peak_key("ETH/USDT:USDT", int(last_open["run_id"]))

            armed_symbol = make_symbol(
                "ETH/USDT:USDT",
                900_000,
                2_312.65,
                atr_pct=0.00166,
                range_pct=0.00128,
                volume_ratio=1.53,
                higher_bias="short",
                higher_phase="reclaim",
            )
            armed_symbol.indicators["return_1bar"] = -0.00021183326560425542
            armed_symbol.indicators["return_24bars"] = -0.0079189742225807
            armed_symbol.indicators["rsi_14"] = 28.091797705057687
            armed_symbol.indicators["sma_fast_ratio"] = -0.0022470455844656456
            armed_symbol.indicators["sma_slow_ratio"] = -0.002634670626639024
            armed_position = PositionSnapshot(
                symbol="ETH/USDT:USDT",
                quantity=0.05179379165084078,
                mark_price=2_312.65,
                market_value_quote=119.78091226131694,
                side="short",
                average_entry_price=2_316.88,
                notional_quote=119.78091226131694,
            )
            armed_bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[armed_symbol],
                open_positions=[armed_position],
                equity_quote=200.21908773868307,
                free_quote=180.0,
            )

            first_verdict = risk_engine.evaluate(make_decision("ETH/USDT:USDT", "hold"), armed_bundle)

            self.assertEqual(first_verdict.final_action, "hold")
            expected_peak = risk_engine._position_return_pct(armed_position, armed_symbol)
            stored_peak = journal.get_runtime_state(peak_key, None)
            self.assertIsNotNone(stored_peak)
            self.assertAlmostEqual(float(stored_peak), float(expected_peak or 0.0))

            retraced_symbol = make_symbol(
                "ETH/USDT:USDT",
                1_200_000,
                2_314.69,
                atr_pct=0.00164,
                range_pct=0.00185,
                volume_ratio=0.97,
                higher_bias="short",
                higher_phase="reclaim",
            )
            retraced_symbol.indicators["return_1bar"] = 0.0008821049445442153
            retraced_symbol.indicators["return_24bars"] = -0.005007866433969332
            retraced_symbol.indicators["rsi_14"] = 39.47968963943391
            retraced_symbol.indicators["sma_fast_ratio"] = -0.001247708638818068
            retraced_symbol.indicators["sma_slow_ratio"] = -0.0017478939288763096
            retraced_bundle = make_bundle(
                timestamp_ms=1_200_000,
                symbols=[retraced_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="ETH/USDT:USDT",
                        quantity=0.05179379165084078,
                        mark_price=2_314.69,
                        market_value_quote=119.88657159628465,
                        side="short",
                        average_entry_price=2_316.88,
                        notional_quote=119.88657159628465,
                    )
                ],
                equity_quote=200.11342840371535,
                free_quote=180.0,
            )

            second_verdict = risk_engine.evaluate(make_decision("ETH/USDT:USDT", "hold"), retraced_bundle)

            self.assertEqual(second_verdict.final_action, "close")
            self.assertTrue(any(reason.startswith("management_trailing_profit_retrace:") for reason in second_verdict.reasons))

    def test_risk_engine_uses_tighter_retrace_for_eth_reclaim_short(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT",),
                trailing_profit_arm_pct=0.0018,
                trailing_profit_retrace_pct=0.0030,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            open_symbol = make_symbol(
                "ETH/USDT:USDT",
                300_000,
                2_316.88,
                atr_pct=0.00163,
                range_pct=0.00341,
                volume_ratio=3.13,
                higher_bias="short",
                higher_phase="reclaim",
            )
            open_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[open_symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )
            entry_thesis = {
                "version": 1,
                "direction": "short",
                "higher_timeframe_direction": "short",
                "higher_timeframe_phase": "reclaim",
                "setup_phase": "short_rebound_fail_confirmed",
                "setup_confirmed": True,
                "invalidation_type": "rebound_fail_reclaimed",
                "follow_through_bars": 2,
                "trigger_bar_timestamp_ms": 300_000,
            }
            record_run(
                journal,
                settings,
                bundle=open_bundle,
                decision_action="sell",
                final_action="sell",
                symbol="ETH/USDT:USDT",
                confidence=0.80,
                risk_debug={"entry_thesis": entry_thesis},
                raw_payload_extra={"entry_thesis": entry_thesis},
            )
            recent_actions = journal.get_recent_signal_actions(limit=10, symbol="ETH/USDT:USDT")
            last_open = next(item for item in recent_actions if item["final_action"] == "sell")
            peak_key = risk_engine._trailing_profit_peak_key("ETH/USDT:USDT", int(last_open["run_id"]))
            journal.set_runtime_state(peak_key, 0.001825)

            retraced_symbol = make_symbol(
                "ETH/USDT:USDT",
                1_200_000,
                2_314.69,
                atr_pct=0.00164,
                range_pct=0.00185,
                volume_ratio=0.97,
                higher_bias="short",
                higher_phase="reclaim",
            )
            retraced_symbol.indicators["return_1bar"] = 0.00088
            retraced_symbol.indicators["return_24bars"] = -0.00501
            retraced_symbol.indicators["rsi_14"] = 39.48
            retraced_symbol.indicators["sma_fast_ratio"] = -0.00125
            retraced_symbol.indicators["sma_slow_ratio"] = -0.00175
            retraced_bundle = make_bundle(
                timestamp_ms=1_200_000,
                symbols=[retraced_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="ETH/USDT:USDT",
                        quantity=0.0518,
                        mark_price=2_314.69,
                        market_value_quote=119.89,
                        side="short",
                        average_entry_price=2_316.88,
                        notional_quote=119.89,
                    )
                ],
                equity_quote=200.0,
                free_quote=180.0,
            )

            verdict = risk_engine.evaluate(make_decision("ETH/USDT:USDT", "hold"), retraced_bundle)

            self.assertEqual(verdict.final_action, "close")
            self.assertTrue(any(reason.startswith("management_trailing_profit_retrace:") for reason in verdict.reasons))

    def test_risk_engine_bottom_line_mode_cuts_adverse_loser_before_full_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("SOL/USDT:USDT",),
                rule_mode="bottom_line",
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            risk_engine = RiskEngine(settings, journal)

            open_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[make_symbol("SOL/USDT:USDT", 300_000, 100.0, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="short")],
                equity_quote=200.0,
                free_quote=200.0,
            )
            record_run(journal, settings, bundle=open_bundle, decision_action="sell", final_action="sell", symbol="SOL/USDT:USDT", confidence=0.90)

            adverse_symbol = make_symbol("SOL/USDT:USDT", 900_000, 100.36, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.10, higher_bias="short")
            adverse_symbol.indicators["return_1bar"] = 0.0018
            adverse_symbol.indicators["return_24bars"] = 0.0028
            adverse_symbol.indicators["sma_fast_ratio"] = 0.0012
            adverse_symbol.indicators["sma_slow_ratio"] = 0.0008
            bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[adverse_symbol],
                open_positions=[
                    PositionSnapshot(
                        symbol="SOL/USDT:USDT",
                        quantity=1.0,
                        mark_price=100.36,
                        market_value_quote=100.36,
                        side="short",
                        average_entry_price=100.0,
                        notional_quote=100.36,
                    )
                ],
                equity_quote=199.64,
                free_quote=190.0,
            )

            verdict = risk_engine.evaluate(make_decision("SOL/USDT:USDT", "hold"), bundle)

            self.assertEqual(verdict.final_action, "close")
            self.assertTrue(any(reason.startswith("management_adverse_loss_cut:") for reason in verdict.reasons))

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

    def test_signal_review_separates_directionless_and_candidate_aligned_missed_moves(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("ETH/USDT:USDT", "XRP/USDT:USDT"),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()

            eth_hold_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[
                    make_symbol(
                        "ETH/USDT:USDT",
                        300_000,
                        100.0,
                        atr_pct=0.0040,
                        range_pct=0.0050,
                        volume_ratio=1.10,
                        higher_bias="short",
                    )
                ],
            )
            record_run(
                journal,
                settings,
                bundle=eth_hold_bundle,
                decision_action="hold",
                final_action="hold",
                symbol="ETH/USDT:USDT",
                confidence=0.45,
                raw_payload_extra={
                    "candidate_filter": {
                        "symbols": [
                            {
                                "symbol": "ETH/USDT:USDT",
                                "eligible": True,
                                "manage_only": False,
                                "reasons": ["short_setup_late_breakdown_soft_penalty"],
                            }
                        ]
                    }
                },
            )

            xrp_blocked_bundle = make_bundle(
                timestamp_ms=600_000,
                symbols=[
                    make_symbol(
                        "XRP/USDT:USDT",
                        600_000,
                        1.50,
                        atr_pct=0.0040,
                        range_pct=0.0050,
                        volume_ratio=1.10,
                        higher_bias="short",
                    )
                ],
            )
            record_run(
                journal,
                settings,
                bundle=xrp_blocked_bundle,
                decision_action="sell",
                final_action="hold",
                symbol="XRP/USDT:USDT",
                confidence=0.60,
                raw_payload_extra={
                    "candidate_filter": {
                        "symbols": [
                            {
                                "symbol": "XRP/USDT:USDT",
                                "eligible": True,
                                "manage_only": False,
                                "reasons": ["short_setup_rebound_fail_confirmed"],
                            }
                        ]
                    }
                },
                risk_reasons=["expected_edge_below_minimum:0.001000<0.001500"],
            )

            service = FakeReviewService(
                settings,
                journal,
                candles_by_symbol={
                    "ETH/USDT:USDT": [
                        [300_000, 100.0, 100.2, 99.8, 100.0, 1000.0],
                        [600_000, 100.0, 100.6, 99.9, 100.5, 1100.0],
                    ],
                    "XRP/USDT:USDT": [
                        [600_000, 1.50, 1.51, 1.49, 1.50, 1000.0],
                        [900_000, 1.50, 1.51, 1.43, 1.44, 1100.0],
                    ],
                },
            )
            report = service.signal_review(limit=10, horizon_bars=1, threshold_pct=0.003)
            reviewed = [item for item in report["reviews"] if item.get("status") == "reviewed"]
            by_symbol = {item["symbol"]: item for item in reviewed}

            eth_item = by_symbol["ETH/USDT:USDT"]
            self.assertEqual(eth_item["outcome"], "missed_move")
            self.assertEqual(eth_item["candidate_direction"], "short")
            self.assertLess(eth_item["candidate_aligned_future_return_pct"], 0.0)
            self.assertEqual(eth_item["candidate_opportunity_edge_pct"], 0.0)
            self.assertFalse(eth_item["missed_candidate_move"])

            xrp_item = by_symbol["XRP/USDT:USDT"]
            self.assertEqual(xrp_item["outcome"], "missed_move")
            self.assertEqual(xrp_item["candidate_direction"], "short")
            self.assertGreater(xrp_item["candidate_opportunity_edge_pct"], 0.0)
            self.assertTrue(xrp_item["missed_candidate_move"])

            overall = report["aggregate"]["overall"]
            self.assertEqual(overall["missed_move"], 2)
            self.assertEqual(overall["missed_candidate_move"], 1)
            self.assertEqual(overall["missed_move_not_candidate_aligned"], 1)

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

    def test_signal_review_reports_setup_phase_and_higher_timeframe_phase_slices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("SOL/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()

            symbol = make_symbol(
                "SOL/USDT:USDT",
                300_000,
                90.0,
                atr_pct=0.0040,
                range_pct=0.0045,
                volume_ratio=1.20,
                higher_bias="long",
                higher_phase="reclaim",
            )
            symbol.candidate_context = {
                "eligible": True,
                "manage_only": False,
                "score": 4.2,
                "higher_timeframe_bias": "long",
                "higher_timeframe_phase": "reclaim",
                "bars_since_last_action": None,
                "setup_phase": "long_pullback_reclaim_confirmed",
                "setup_confirmed": True,
                "phase_match_score": 0.65,
                "reasons": ["long_setup_pullback_reclaim_confirmed"],
            }
            entry_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )
            record_run(
                journal,
                settings,
                bundle=entry_bundle,
                decision_action="buy",
                final_action="buy",
                symbol="SOL/USDT:USDT",
                confidence=0.88,
                raw_payload_extra={
                    "entry_thesis": {
                        "direction": "long",
                        "setup_phase": "long_pullback_reclaim_confirmed",
                        "higher_timeframe_phase": "reclaim",
                        "invalidation_type": "reclaim_failed",
                    },
                    "candidate_filter": {
                        "symbols": [
                            {
                                "symbol": "SOL/USDT:USDT",
                                "eligible": True,
                                "manage_only": False,
                                "reasons": ["long_setup_pullback_reclaim_confirmed"],
                            }
                        ]
                    }
                },
            )

            service = FakeReviewService(
                settings,
                journal,
                candles_by_symbol={
                    "SOL/USDT:USDT": [
                        [300_000, 90.0, 90.2, 89.8, 90.0, 1000.0],
                        [600_000, 90.0, 91.8, 89.9, 91.5, 1200.0],
                    ],
                },
            )
            report = service.signal_review(limit=10, horizon_bars=1, threshold_pct=0.003)
            reviewed = [item for item in report["reviews"] if item.get("status") == "reviewed"]

            self.assertEqual(len(reviewed), 1)
            self.assertEqual(reviewed[0]["setup_phase"], "long_pullback_reclaim_confirmed")
            self.assertEqual(reviewed[0]["higher_timeframe_phase"], "reclaim")
            self.assertIn("by_setup_phase", report["aggregate"])
            self.assertIn("long_pullback_reclaim_confirmed", report["aggregate"]["by_setup_phase"])
            self.assertIn("reclaim", report["aggregate"]["by_higher_timeframe_phase"])
            self.assertIn("by_entry_thesis", report["aggregate"])
            self.assertIn(
                "long:long_pullback_reclaim_confirmed:reclaim_failed",
                report["aggregate"]["by_entry_thesis"],
            )

    def test_signal_review_replay_current_risk_populates_entry_thesis_slices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()

            symbol = make_symbol(
                "XRP/USDT:USDT",
                300_000,
                1.50,
                atr_pct=0.0020,
                range_pct=0.0020,
                volume_ratio=0.72,
                higher_bias="short",
                higher_phase="trend",
            )
            symbol.indicators["return_1bar"] = 0.0002
            symbol.indicators["return_24bars"] = -0.0044
            symbol.indicators["sma_fast_ratio"] = -0.0009
            symbol.indicators["sma_slow_ratio"] = -0.0014
            symbol.indicators["rsi_14"] = 42.0
            bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[symbol],
                equity_quote=200.0,
                free_quote=200.0,
            )
            record_run(
                journal,
                settings,
                bundle=bundle,
                decision_action="sell",
                final_action="sell",
                symbol="XRP/USDT:USDT",
                confidence=0.62,
                raw_payload_extra={
                    "candidate_filter": {
                        "symbols": [
                            {
                                "symbol": "XRP/USDT:USDT",
                                "eligible": True,
                                "manage_only": False,
                                "higher_timeframe_phase": "trend",
                                "setup_phase": "short_continuation_confirmed",
                                "setup_confirmed": True,
                                "reasons": ["short_setup_pre_breakdown_watch"],
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
                        [300_000, 1.50, 1.505, 1.495, 1.50, 1000.0],
                        [600_000, 1.50, 1.51, 1.44, 1.45, 1500.0],
                    ],
                },
            )
            report = service.signal_review(limit=10, horizon_bars=1, threshold_pct=0.003, replay_current_risk=True)

            self.assertIn("short:short_continuation_confirmed:continuation_follow_through_failed", report["aggregate"]["by_entry_thesis"])
            reviewed = [item for item in report["reviews"] if item.get("status") == "reviewed"]
            self.assertEqual(reviewed[0]["entry_thesis_key"], "short:short_continuation_confirmed:continuation_follow_through_failed")

    def test_signal_review_separates_candidate_ok_ai_hold_and_reports_cycle_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT"),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()

            sol_entry_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[make_symbol("SOL/USDT:USDT", 300_000, 90.0, atr_pct=0.0042, range_pct=0.0040, volume_ratio=1.20, higher_bias="short")],
                open_positions=[
                    PositionSnapshot(
                        symbol="BTC/USDT:USDT",
                        quantity=0.001,
                        mark_price=100_000.0,
                        market_value_quote=60.0,
                        side="short",
                        average_entry_price=101_000.0,
                        notional_quote=60.0,
                    )
                ],
                equity_quote=200.0,
                free_quote=180.0,
            )
            record_run(
                journal,
                settings,
                bundle=sol_entry_bundle,
                decision_action="sell",
                final_action="sell",
                symbol="SOL/USDT:USDT",
                confidence=0.84,
                raw_payload_extra={
                    "candidate_filter": {
                        "symbols": [
                            {
                                "symbol": "SOL/USDT:USDT",
                                "eligible": True,
                                "manage_only": False,
                                "reasons": ["candidate_ok"],
                            }
                        ]
                    }
                },
            )

            eth_entry_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[make_symbol("ETH/USDT:USDT", 300_000, 200.0, atr_pct=0.0040, range_pct=0.0038, volume_ratio=1.10, higher_bias="short")],
                open_positions=[
                    PositionSnapshot(
                        symbol="BTC/USDT:USDT",
                        quantity=0.001,
                        mark_price=100_000.0,
                        market_value_quote=60.0,
                        side="short",
                        average_entry_price=101_000.0,
                        notional_quote=60.0,
                    ),
                    PositionSnapshot(
                        symbol="SOL/USDT:USDT",
                        quantity=0.67,
                        mark_price=90.0,
                        market_value_quote=60.0,
                        side="short",
                        average_entry_price=91.0,
                        notional_quote=60.0,
                    ),
                ],
                equity_quote=200.0,
                free_quote=160.0,
            )
            record_run(
                journal,
                settings,
                bundle=eth_entry_bundle,
                decision_action="sell",
                final_action="sell",
                symbol="ETH/USDT:USDT",
                confidence=0.72,
                raw_payload_extra={
                    "candidate_filter": {
                        "symbols": [
                            {
                                "symbol": "ETH/USDT:USDT",
                                "eligible": True,
                                "manage_only": False,
                                "reasons": ["candidate_ok"],
                            }
                        ]
                    }
                },
            )

            xrp_hold_bundle = make_bundle(
                timestamp_ms=300_000,
                symbols=[make_symbol("XRP/USDT:USDT", 300_000, 1.50, atr_pct=0.0030, range_pct=0.0030, volume_ratio=1.00, higher_bias="short")],
                equity_quote=200.0,
                free_quote=160.0,
            )
            record_run(
                journal,
                settings,
                bundle=xrp_hold_bundle,
                decision_action="hold",
                final_action="hold",
                symbol="XRP/USDT:USDT",
                confidence=0.28,
                raw_payload_extra={
                    "candidate_filter": {
                        "symbols": [
                            {
                                "symbol": "XRP/USDT:USDT",
                                "eligible": True,
                                "manage_only": False,
                                "reasons": ["candidate_ok"],
                            }
                        ]
                    }
                },
            )

            xrp_penalty_hold_bundle = make_bundle(
                timestamp_ms=600_000,
                symbols=[make_symbol("XRP/USDT:USDT", 600_000, 1.50, atr_pct=0.0022, range_pct=0.0021, volume_ratio=0.58, higher_bias="short")],
                equity_quote=200.0,
                free_quote=200.0,
            )
            record_run(
                journal,
                settings,
                bundle=xrp_penalty_hold_bundle,
                decision_action="hold",
                final_action="hold",
                symbol="XRP/USDT:USDT",
                confidence=0.20,
                raw_payload_extra={
                    "candidate_filter": {
                        "symbols": [
                            {
                                "symbol": "XRP/USDT:USDT",
                                "eligible": True,
                                "manage_only": False,
                                "reasons": ["low_volume_soft_penalty"],
                            }
                        ]
                    }
                },
            )

            service = FakeReviewService(
                settings,
                journal,
                candles_by_symbol={
                    "SOL/USDT:USDT": [
                        [300_000, 90.0, 90.3, 89.7, 90.0, 1200.0],
                        [600_000, 90.0, 90.1, 87.8, 88.0, 1500.0],
                    ],
                    "ETH/USDT:USDT": [
                        [300_000, 200.0, 200.4, 199.6, 200.0, 1200.0],
                        [600_000, 200.0, 204.2, 199.8, 204.0, 1500.0],
                    ],
                    "XRP/USDT:USDT": [
                        [300_000, 1.50, 1.503, 1.497, 1.50, 900.0],
                        [600_000, 1.50, 1.501, 1.499, 1.50, 900.0],
                        [900_000, 1.50, 1.501, 1.499, 1.50, 900.0],
                    ],
                },
            )
            report = service.signal_review(limit=10, horizon_bars=1, threshold_pct=0.003)

            self.assertEqual(report["aggregate"]["by_hold_path"]["candidate_ok_ai_hold"]["reviewed"], 1)
            self.assertEqual(report["aggregate"]["by_hold_path"]["candidate_penalty_ai_hold"]["reviewed"], 1)
            cycle_summary = report["aggregate"]["cycle_summary"]
            self.assertEqual(cycle_summary["cycles_reviewed"], 2)
            first_cycle = cycle_summary["cycles"][0]
            self.assertEqual(first_cycle["processed_count"], 3)
            self.assertEqual(first_cycle["start_short_notional_quote"], 60.0)
            self.assertEqual(first_cycle["end_short_notional_quote"], 180.0)
            self.assertIn("SOL/USDT:USDT", first_cycle["contributors"])
            self.assertIn("ETH/USDT:USDT", first_cycle["capacity_symbols"])

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

    def test_signal_review_reports_edge_buckets_and_decision_control_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT", "SOL/USDT:USDT", "BTC/USDT:USDT"),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()

            record_run(
                journal,
                settings,
                bundle=make_bundle(
                    timestamp_ms=300_000,
                    symbols=[make_symbol("XRP/USDT:USDT", 300_000, 1.50, atr_pct=0.0020, range_pct=0.0020, volume_ratio=1.10, higher_bias="short")],
                    equity_quote=200.0,
                    free_quote=200.0,
                ),
                decision_action="sell",
                final_action="hold",
                symbol="XRP/USDT:USDT",
                confidence=0.35,
                risk_reasons=["expected_edge_below_minimum:0.001000<0.001500"],
                risk_debug={
                    "entry_archetype": "plain_open",
                    "shadow_open_signal_reasons": ["open_signal_return_24bars_too_weak"],
                    "expected_edge_components": {
                        "final_expected_edge_pct": 0.0010,
                        "required_threshold_pct": 0.0015,
                        "required_threshold_gap_pct": 0.0005,
                        "volatility_component_pct": 0.0020,
                        "directional_component_pct": 0.0001,
                    },
                },
            )
            record_run(
                journal,
                settings,
                bundle=make_bundle(
                    timestamp_ms=600_000,
                    symbols=[make_symbol("SOL/USDT:USDT", 600_000, 90.0, atr_pct=0.0035, range_pct=0.0030, volume_ratio=1.20, higher_bias="short")],
                    equity_quote=200.0,
                    free_quote=200.0,
                ),
                decision_action="sell",
                final_action="sell",
                symbol="SOL/USDT:USDT",
                confidence=0.70,
                decision_size_pct=0.10,
                decision_take_profit_pct=0.02,
                decision_stop_loss_pct=0.01,
                final_size_pct=0.07,
                final_take_profit_pct=0.015,
                final_stop_loss_pct=0.008,
                risk_debug={
                    "entry_archetype": "flat_bias_short",
                    "shadow_open_signal_reasons": [],
                    "expected_edge_components": {
                        "final_expected_edge_pct": 0.0018,
                        "required_threshold_pct": 0.0015,
                        "required_threshold_gap_pct": -0.0003,
                        "volatility_component_pct": 0.0035,
                        "directional_component_pct": 0.0003,
                    },
                },
            )
            record_run(
                journal,
                settings,
                bundle=make_bundle(
                    timestamp_ms=900_000,
                    symbols=[make_symbol("BTC/USDT:USDT", 900_000, 100.0, atr_pct=0.0050, range_pct=0.0045, volume_ratio=1.25, higher_bias="long")],
                    equity_quote=200.0,
                    free_quote=200.0,
                ),
                decision_action="buy",
                final_action="buy",
                symbol="BTC/USDT:USDT",
                confidence=0.92,
                risk_debug={
                    "entry_archetype": "higher_timeframe_long_reclaim_long",
                    "shadow_open_signal_reasons": [],
                    "expected_edge_components": {
                        "final_expected_edge_pct": 0.0026,
                        "required_threshold_pct": 0.0015,
                        "required_threshold_gap_pct": -0.0011,
                        "volatility_component_pct": 0.0050,
                        "directional_component_pct": 0.0005,
                    },
                },
            )

            service = FakeReviewService(
                settings,
                journal,
                candles_by_symbol={
                    "XRP/USDT:USDT": [
                        [300_000, 1.50, 1.505, 1.495, 1.50, 1000.0],
                        [600_000, 1.50, 1.49, 1.46, 1.47, 1200.0],
                    ],
                    "SOL/USDT:USDT": [
                        [600_000, 90.0, 90.2, 89.8, 90.0, 1100.0],
                        [900_000, 90.0, 90.1, 87.0, 87.5, 1400.0],
                    ],
                    "BTC/USDT:USDT": [
                        [900_000, 100.0, 100.4, 99.8, 100.0, 1100.0],
                        [1_200_000, 100.0, 104.0, 99.9, 103.5, 1500.0],
                    ],
                },
            )
            report = service.signal_review(limit=10, horizon_bars=1, threshold_pct=0.003)

            self.assertEqual(report["aggregate"]["decision_control"]["ai_open_decisions"], 3)
            self.assertEqual(report["aggregate"]["decision_control"]["risk_veto_after_ai_open"], 1)
            self.assertEqual(report["aggregate"]["decision_control"]["size_override_count"], 1)
            self.assertEqual(report["aggregate"]["decision_control"]["take_profit_override_count"], 1)
            self.assertEqual(report["aggregate"]["decision_control"]["stop_loss_override_count"], 1)
            self.assertEqual(report["aggregate"]["by_primary_risk_reason"]["expected_edge_below_minimum"]["reviewed"], 1)
            self.assertEqual(report["aggregate"]["by_entry_archetype"]["flat_bias_short"]["reviewed"], 1)
            self.assertEqual(set(report["aggregate"]["by_expected_edge_bucket"].keys()), {"low", "mid", "high"})
            self.assertEqual(set(report["aggregate"]["by_volatility_bucket"].keys()), {"low", "mid", "high"})

    def test_signal_review_study_compares_multiple_horizons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT", "SOL/USDT:USDT", "BTC/USDT:USDT"),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()

            for timestamp_ms, symbol, price, future_bias, edge, volatility in (
                (300_000, "XRP/USDT:USDT", 1.50, "short", 0.0012, 0.0020),
                (600_000, "SOL/USDT:USDT", 90.0, "short", 0.0019, 0.0035),
                (900_000, "BTC/USDT:USDT", 100.0, "long", 0.0027, 0.0050),
            ):
                record_run(
                    journal,
                    settings,
                    bundle=make_bundle(
                        timestamp_ms=timestamp_ms,
                        symbols=[make_symbol(symbol, timestamp_ms, price, atr_pct=volatility, range_pct=max(volatility - 0.0005, 0.0015), volume_ratio=1.15, higher_bias=future_bias)],
                        equity_quote=200.0,
                        free_quote=200.0,
                    ),
                    decision_action="buy" if future_bias == "long" else "sell",
                    final_action="buy" if future_bias == "long" else "sell",
                    symbol=symbol,
                    confidence=0.75,
                    risk_debug={
                        "entry_archetype": "plain_open",
                        "shadow_open_signal_reasons": [],
                        "expected_edge_components": {
                            "final_expected_edge_pct": edge,
                            "required_threshold_pct": 0.0015,
                            "required_threshold_gap_pct": 0.0015 - edge,
                            "volatility_component_pct": volatility,
                            "directional_component_pct": 0.0003,
                        },
                    },
                )

            service = FakeReviewService(
                settings,
                journal,
                candles_by_symbol={
                    "XRP/USDT:USDT": [
                        [300_000, 1.50, 1.505, 1.495, 1.50, 1000.0],
                        [600_000, 1.50, 1.49, 1.46, 1.47, 1200.0],
                        [900_000, 1.47, 1.48, 1.44, 1.45, 1200.0],
                    ],
                    "SOL/USDT:USDT": [
                        [600_000, 90.0, 90.2, 89.8, 90.0, 1100.0],
                        [900_000, 90.0, 89.0, 87.5, 88.0, 1400.0],
                        [1_200_000, 88.0, 88.2, 86.7, 87.0, 1400.0],
                    ],
                    "BTC/USDT:USDT": [
                        [900_000, 100.0, 100.4, 99.8, 100.0, 1100.0],
                        [1_200_000, 100.0, 103.5, 99.9, 103.0, 1500.0],
                        [1_500_000, 103.0, 104.5, 102.9, 104.0, 1500.0],
                    ],
                },
            )
            study = service.signal_review_study(limit=10, horizons=[1, 2], threshold_pct=0.003)

            self.assertEqual(study["horizons"], [1, 2])
            self.assertEqual(len(study["comparison"]), 2)
            self.assertEqual(study["comparison"][0]["direction_consistency"], "baseline")
            self.assertIn("edge_monotonicity", study["comparison"][1])
            self.assertIn("1", study["by_horizon"])
            self.assertIn("by_expected_edge_bucket", study["by_horizon"]["1"])

    def test_execution_cost_audit_reports_slippage_fee_and_exposure_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                mode="live",
                market_type="future",
                symbols=("XRP/USDT:USDT",),
                max_open_positions=3,
                max_entry_size_pct=0.30,
                contract_leverage=6,
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()

            record_run(
                journal,
                settings,
                bundle=make_bundle(
                    timestamp_ms=300_000,
                    symbols=[make_symbol("XRP/USDT:USDT", 300_000, 1.50, atr_pct=0.0030, range_pct=0.0030, volume_ratio=1.10, higher_bias="short")],
                    equity_quote=156.0,
                    free_quote=156.0,
                ),
                decision_action="sell",
                final_action="sell",
                symbol="XRP/USDT:USDT",
                confidence=0.80,
                final_size_pct=0.30,
                final_stop_loss_pct=0.0075,
                order_result=ExecutionResult(
                    status="closed",
                    mode="live",
                    symbol="XRP/USDT:USDT",
                    action="sell",
                    side="sell",
                    quantity=20.0,
                    notional_quote=29.8,
                    pnl_quote=None,
                    external_order_id="entry-1",
                    raw={
                        "entry_order": {
                            "id": "entry-1",
                            "type": "market",
                            "side": "sell",
                            "filled": 20.0,
                            "average": 1.49,
                            "cost": 29.8,
                            "fee": {
                                "cost": 0.01192,
                                "rate": 0.0004,
                            },
                        },
                        "entry_price": 1.49,
                    },
                ),
            )

            service = ReviewService(settings, journal)
            report = service.execution_cost_audit(limit=10, mode="live")

            self.assertEqual(report["market_orders_analyzed"], 1)
            self.assertAlmostEqual(report["overall"]["avg_fee_rate_pct"], 0.04, places=6)
            self.assertAlmostEqual(report["by_symbol"]["XRP/USDT:USDT"]["p50_abs_slippage_pct"], 0.6666666667, places=6)
            geometry = report["exposure_geometry"]
            self.assertAlmostEqual(geometry["configured_same_direction_multiple_of_equity"], 5.4, places=6)
            self.assertAlmostEqual(geometry["single_stop_drawdown_pct_of_equity"], 1.35, places=6)
            self.assertAlmostEqual(geometry["stops_to_daily_loss_limit"], 2.2222222222, places=6)

    def test_executor_paper_future_supports_short_open_and_partial_close(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT:USDT",),
            )
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            executor = Executor(settings, journal)

            open_bundle = make_bundle(
                timestamp_ms=900_000,
                symbols=[make_symbol("XRP/USDT:USDT", 900_000, 1.50, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="short")],
                equity_quote=200.0,
                free_quote=200.0,
            )
            open_verdict = RiskVerdict(
                status="approved",
                final_action="sell",
                symbol="XRP/USDT:USDT",
                final_size_pct=0.10,
                take_profit_pct=0.02,
                stop_loss_pct=0.01,
                ttl_minutes=30,
                reasons=["ok"],
                confidence=0.70,
                approved=True,
            )

            open_result = executor.execute(open_verdict, open_bundle)

            self.assertEqual(open_result.status, "paper_filled")
            self.assertEqual(open_result.side, "sell")
            portfolio = journal.get_runtime_state("paper_portfolio", {})
            position = portfolio["positions"]["XRP/USDT:USDT"]
            self.assertEqual(position["side"], "short")
            self.assertAlmostEqual(position["margin_quote"], 20.0, places=6)
            self.assertAlmostEqual(float(portfolio["free_quote"]), 180.0, places=6)

            close_bundle = make_bundle(
                timestamp_ms=1_200_000,
                symbols=[make_symbol("XRP/USDT:USDT", 1_200_000, 1.45, atr_pct=0.0040, range_pct=0.0040, volume_ratio=1.20, higher_bias="short")],
                equity_quote=199.0,
                free_quote=180.0,
            )
            close_verdict = RiskVerdict(
                status="modified",
                final_action="close",
                symbol="XRP/USDT:USDT",
                final_size_pct=0.0,
                take_profit_pct=0.0,
                stop_loss_pct=0.0,
                ttl_minutes=0,
                reasons=["partial_take_profit:test"],
                confidence=0.75,
                approved=True,
                close_fraction=0.5,
            )

            close_result = executor.execute(close_verdict, close_bundle)

            self.assertEqual(close_result.status, "paper_closed")
            self.assertEqual(close_result.side, "buy")
            self.assertGreater(float(close_result.pnl_quote or 0.0), 0.0)
            self.assertTrue(close_result.raw["partial_close"])
            self.assertAlmostEqual(float(close_result.raw["remaining_quantity"] or 0.0), 20.0, places=6)
            self.assertAlmostEqual(float(close_result.raw["released_margin_quote"] or 0.0), 10.0, places=6)
            updated_portfolio = journal.get_runtime_state("paper_portfolio", {})
            updated_position = updated_portfolio["positions"]["XRP/USDT:USDT"]
            self.assertEqual(updated_position["side"], "short")
            self.assertAlmostEqual(float(updated_position["margin_quote"]), 10.0, places=6)
            self.assertAlmostEqual(float(updated_portfolio["free_quote"]), 191.0, places=6)

    def test_backtest_service_runs_isolated_historical_futures_paper_backtest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("XRP/USDT",),
                candidate_trend_timeframe="",
                setup_model_enable=True,
                setup_model_path=root / "state" / "models" / "setup_edge_model.json",
            )
            settings.setup_model_path.parent.mkdir(parents=True, exist_ok=True)
            settings.setup_model_path.write_text(
                json.dumps(
                    {
                        "version": "setup_edge_ridge_v1",
                        "timeframe": "5m",
                        "higher_timeframe": "1h",
                        "horizon_bars": 3,
                        "trained_at": "2024-01-03T00:00:00+00:00",
                        "training_cutoff_utc": "2024-01-03T00:15:00+00:00",
                        "training_window": {
                            "sample_window_start_utc": "2024-01-01T00:00:00+00:00",
                            "sample_window_end_utc": "2024-01-03T00:00:00+00:00",
                            "training_cutoff_utc": "2024-01-03T00:15:00+00:00",
                            "lookback_days": 2,
                            "horizon_bars": 3,
                            "timeframe": "5m",
                            "higher_timeframe": "1h",
                            "example_count": 20,
                        },
                        "symbols": {},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            base_ts = 1_735_689_600_000  # 2025-01-01 00:00:00 UTC
            timeframe_ms = 5 * 60_000
            rows_5m: list[list[float]] = []
            close = 1.60
            for idx in range(70):
                previous_close = close
                if idx < 55:
                    close = previous_close * 0.9994
                elif idx < 60:
                    close = previous_close * 0.9960
                else:
                    close = previous_close * 1.0005
                open_price = previous_close
                high = max(open_price, close) * 1.0015
                low = min(open_price, close) * 0.9985
                rows_5m.append(
                    [
                        base_ts + (idx * timeframe_ms),
                        round(open_price, 6),
                        round(high, 6),
                        round(low, 6),
                        round(close, 6),
                        1000.0,
                    ]
                )

            fake_exchange = FakeHistoricalExchange(
                {
                    ("XRP/USDT:USDT", "5m"): rows_5m,
                }
            )

            class _StubAIClient:
                def request_decision(self, bundle):
                    symbol = bundle.symbols[0].symbol
                    if bundle.account.open_positions:
                        payload = {
                            "timestamp": utc_now().isoformat(),
                            "symbol": symbol,
                            "action": "hold",
                            "size_pct": 0.0,
                            "take_profit_pct": 0.0,
                            "stop_loss_pct": 0.0,
                            "ttl_minutes": 30,
                            "confidence": 0.40,
                            "reason": "paper_manage_hold",
                            "prompt_version": "v1",
                        }
                    else:
                        payload = {
                            "timestamp": utc_now().isoformat(),
                            "symbol": symbol,
                            "action": "sell",
                            "size_pct": 0.10,
                            "take_profit_pct": 0.02,
                            "stop_loss_pct": 0.01,
                            "ttl_minutes": 30,
                            "confidence": 0.70,
                            "reason": "paper_backtest_short_entry",
                            "prompt_version": "v1",
                        }
                    return {"stub": True}, json.dumps(payload), "stub-model"

            def _orchestrator_factory(backtest_settings: Settings) -> Orchestrator:
                orchestrator = Orchestrator(backtest_settings)
                orchestrator.ai_client = _StubAIClient()
                return orchestrator

            service = BacktestService(
                settings,
                public_exchange=fake_exchange,
                orchestrator_factory=_orchestrator_factory,
            )

            result = service.run(
                start=datetime.fromtimestamp(rows_5m[48][0] / 1000, tz=timezone.utc),
                end=datetime.fromtimestamp(rows_5m[64][0] / 1000, tz=timezone.utc),
                review_horizon_bars=3,
                review_threshold_pct=0.003,
            )

            self.assertEqual(result["mode"], "backtest")
            self.assertGreaterEqual(result["runs_completed"], 10)
            self.assertGreaterEqual(result["order_stats"]["paper_filled"], 1)
            self.assertGreater(result["performance"]["final_equity_quote"], settings.paper_starting_quote)
            self.assertIn("realized_return_pct", result["performance"])
            self.assertIn("unrealized_return_pct", result["performance"])
            self.assertIn("open_unrealized_pnl_quote", result["performance"])
            self.assertIn("open_positions", result["performance"])
            self.assertIn("aggregate", result["review"])
            self.assertGreater(result["review"]["aggregate"]["reviewed"], 0)
            self.assertIsNotNone(result["setup_model"])
            self.assertEqual(result["setup_model"]["path"], str(settings.setup_model_path))
            self.assertTrue(result["setup_model"]["backtest_window"]["oos_safe"])
            self.assertEqual(result["audit_context"]["rule_mode"], settings.rule_mode)
            self.assertEqual(result["audit_context"]["market_type"], settings.market_type)
            self.assertEqual(result["audit_context"]["paper_starting_quote"], settings.paper_starting_quote)
            review_payload = json.loads(Path(result["artifact_dir"], "review.json").read_text(encoding="utf-8"))
            self.assertIn("setup_model", review_payload)
            self.assertEqual(review_payload["setup_model"]["training_cutoff_utc"], "2024-01-03T00:15:00+00:00")
            self.assertTrue(review_payload["setup_model"]["backtest_window"]["oos_safe"])
            self.assertTrue(Path(result["artifact_dir"], "summary.json").exists())
            self.assertTrue(Path(result["artifact_dir"], "review.json").exists())

    def test_backtest_service_supports_multi_symbol_same_cycle_processing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                root,
                market_type="future",
                symbols=("SOL/USDT", "XRP/USDT"),
                max_open_positions=2,
                candidate_trend_timeframe="",
            )

            base_ts = 1_735_689_600_000
            timeframe_ms = 5 * 60_000

            def build_rows(start_price: float) -> list[list[float]]:
                rows = []
                close = start_price
                for idx in range(72):
                    previous_close = close
                    if idx < 56:
                        close = previous_close * 0.9992
                    elif idx < 62:
                        close = previous_close * 0.9970
                    else:
                        close = previous_close * 0.9995
                    open_price = previous_close
                    high = max(open_price, close) * 1.0015
                    low = min(open_price, close) * 0.9985
                    rows.append(
                        [
                            base_ts + (idx * timeframe_ms),
                            round(open_price, 6),
                            round(high, 6),
                            round(low, 6),
                            round(close, 6),
                            1000.0,
                        ]
                    )
                return rows

            fake_exchange = FakeHistoricalExchange(
                {
                    ("SOL/USDT:USDT", "5m"): build_rows(90.0),
                    ("XRP/USDT:USDT", "5m"): build_rows(1.45),
                }
            )

            class _StubAIClient:
                def request_decision(self, bundle):
                    symbol = bundle.symbols[0].symbol
                    if any(position.symbol == symbol for position in bundle.account.open_positions):
                        payload = {
                            "timestamp": utc_now().isoformat(),
                            "symbol": symbol,
                            "action": "hold",
                            "size_pct": 0.0,
                            "take_profit_pct": 0.0,
                            "stop_loss_pct": 0.0,
                            "ttl_minutes": 30,
                            "confidence": 0.40,
                            "reason": "paper_manage_hold",
                            "prompt_version": "v1",
                        }
                    else:
                        payload = {
                            "timestamp": utc_now().isoformat(),
                            "symbol": symbol,
                            "action": "sell",
                            "size_pct": 0.10,
                            "take_profit_pct": 0.02,
                            "stop_loss_pct": 0.01,
                            "ttl_minutes": 30,
                            "confidence": 0.70,
                            "reason": "paper_backtest_multi_symbol_entry",
                            "prompt_version": "v1",
                        }
                    return {"stub": True}, json.dumps(payload), "stub-model"

            def _orchestrator_factory(backtest_settings: Settings) -> Orchestrator:
                orchestrator = Orchestrator(backtest_settings)
                orchestrator.ai_client = _StubAIClient()
                return orchestrator

            service = BacktestService(
                settings,
                public_exchange=fake_exchange,
                orchestrator_factory=_orchestrator_factory,
            )

            result = service.run(
                start=datetime.fromtimestamp(base_ts / 1000, tz=timezone.utc) + timedelta(minutes=48 * 5),
                end=datetime.fromtimestamp(base_ts / 1000, tz=timezone.utc) + timedelta(minutes=64 * 5),
                review_horizon_bars=3,
                review_threshold_pct=0.003,
            )

            self.assertEqual(result["mode"], "backtest")
            self.assertGreater(result["runs_completed"], result["bars_requested"])
            self.assertGreaterEqual(result["order_stats"]["paper_filled"], 2)
            self.assertIn("aggregate", result["review"])
            self.assertGreater(result["review"]["aggregate"]["reviewed"], 0)

    def test_walk_forward_trains_before_window_and_records_oos_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = apply_research_profile(
                make_settings(
                    root,
                    market_type="future",
                    symbols=("BTC/USDT",),
                    candidate_trend_timeframe="",
                    setup_model_enable=True,
                    setup_model_path=root / "state" / "models" / "setup_edge_model.json",
                ),
                "eth-only",
            )

            base_ts = 1_735_689_600_000
            timeframe_ms = 5 * 60_000
            rows_5m: list[list[float]] = []
            close = 1.60
            for idx in range(620):
                previous_close = close
                if idx % 80 < 58:
                    close = previous_close * 0.9995
                elif idx % 80 < 66:
                    close = previous_close * 0.9955
                else:
                    close = previous_close * 1.0007
                open_price = previous_close
                high = max(open_price, close) * 1.0015
                low = min(open_price, close) * 0.9985
                rows_5m.append(
                    [
                        base_ts + (idx * timeframe_ms),
                        round(open_price, 6),
                        round(high, 6),
                        round(low, 6),
                        round(close, 6),
                        1000.0 + idx,
                    ]
                )
            rows_1h = rows_5m[::12]
            fake_exchange = FakeHistoricalExchange(
                {
                    ("ETH/USDT:USDT", "5m"): rows_5m,
                    ("ETH/USDT:USDT", "1h"): rows_1h,
                }
            )

            class _StubAIClient:
                def request_decision(self, bundle):
                    symbol = bundle.symbols[0].symbol
                    action = "hold" if bundle.account.open_positions else "sell"
                    payload = {
                        "timestamp": utc_now().isoformat(),
                        "symbol": symbol,
                        "action": action,
                        "size_pct": 0.0 if action == "hold" else 0.10,
                        "take_profit_pct": 0.0 if action == "hold" else 0.02,
                        "stop_loss_pct": 0.0 if action == "hold" else 0.01,
                        "ttl_minutes": 30,
                        "confidence": 0.70 if action == "sell" else 0.40,
                        "reason": "walk_forward_stub",
                        "prompt_version": "v1",
                    }
                    return {"stub": True}, json.dumps(payload), "stub-model"

            def _orchestrator_factory(backtest_settings: Settings) -> Orchestrator:
                orchestrator = Orchestrator(backtest_settings)
                orchestrator.ai_client = _StubAIClient()
                return orchestrator

            start = datetime.fromtimestamp(rows_5m[500][0] / 1000, tz=timezone.utc)
            end = datetime.fromtimestamp(rows_5m[540][0] / 1000, tz=timezone.utc)
            service = WalkForwardService(
                settings,
                public_exchange=fake_exchange,
                orchestrator_factory=_orchestrator_factory,
            )

            result = service.run(
                windows=[parse_walk_forward_window(f"synthetic={start.isoformat()},{end.isoformat()}")],
                symbols_filter=None,
                setup_phases=["short_breakdown_confirmed"],
                train_lookback_days=1,
                horizon_bars=3,
                gap_bars=1,
                min_samples=1,
                ridge_alpha=0.0005,
                split_higher_phase=False,
                review_horizon_bars=3,
                review_threshold_pct=0.003,
                starting_quote=None,
                max_bars_per_window=12,
                research_profile="eth-only",
            )

            self.assertEqual(result["mode"], "walk_forward")
            self.assertTrue(result["complete"])
            self.assertEqual(result["max_bars_per_window"], 12)
            self.assertEqual(result["window_count"], 1)
            self.assertEqual(result["aggregate"]["oos_safe_windows"], 1)
            self.assertEqual(result["audit_context"]["rule_mode"], settings.rule_mode)
            self.assertEqual(result["audit_context"]["market_type"], settings.market_type)
            self.assertEqual(result["audit_context"]["paper_starting_quote"], settings.paper_starting_quote)
            self.assertEqual(result["audit_context"]["research_profile"], "eth-only")
            window = result["windows"][0]
            self.assertEqual(window["label"], "synthetic")
            training_cutoff = datetime.fromisoformat(window["training"]["training_cutoff_utc"])
            self.assertLess(training_cutoff, start)
            self.assertTrue(window["backtest"]["setup_model_oos_safe"])
            self.assertTrue(Path(window["model_path"]).exists())
            self.assertEqual(Path(window["model_path"]).name, "setup_edge_model_short_rebound_phase6.json")
            partial_payload = json.loads(Path(result["artifact_dir"], "walk_forward.partial.json").read_text(encoding="utf-8"))
            self.assertFalse(partial_payload["complete"])
            self.assertEqual(partial_payload["max_bars_per_window"], 12)
            self.assertEqual(partial_payload["window_count"], 1)
            self.assertEqual(partial_payload["audit_context"]["research_profile"], "eth-only")
            child_summary = json.loads(Path(window["backtest_artifact_dir"], "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(child_summary["audit_context"]["research_profile"], "eth-only")
            self.assertTrue(Path(result["artifact_dir"], "walk_forward.json").exists())


if __name__ == "__main__":
    unittest.main()
