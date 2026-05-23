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

from qount.exchange_utils import ExchangePool
from qount.journal import Journal
from qount.analytics import LiveAnalyticsService
from qount.exchange_utils import call_with_time_sync_retry
from qount.market import MarketGateway
from qount.models import AccountSnapshot
from qount.models import MarketSnapshotBundle
from qount.models import PositionSnapshot
from qount.models import SymbolSnapshot
from qount.models import utc_now
from qount.safety import LiveSafetyChecks
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
        mode="live",
        exchange_id="binance",
        market_type="future",
        live_enable=True,
        live_confirmation="I_UNDERSTAND_LIVE_TRADING",
        openai_base_url="http://127.0.0.1:8318/v1",
        openai_api_key="test",
        ai_model="gpt-5.4-mini",
        ai_timeout_seconds=30,
        rule_mode="strict",
        symbols=("SOL/USDT", "XRP/USDT"),
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
        binance_api_key="key",
        binance_api_secret="secret",
        contract_leverage=3,
        contract_margin_mode="isolated",
        notify_webhook_url=None,
    )
    defaults.update(overrides)
    settings = Settings(**defaults)
    settings.ensure_directories()
    return settings


class FakePublicExchange:
    def __init__(self) -> None:
        self.fetch_time_calls = 0
        self.load_markets_calls = 0

    def fetch_time(self) -> int:
        self.fetch_time_calls += 1
        return 1_778_505_000_000

    def load_markets(self):
        self.load_markets_calls += 1
        return {
            "SOL/USDT:USDT": {
                "symbol": "SOL/USDT:USDT",
                "id": "SOLUSDT",
                "base": "SOL",
                "quote": "USDT",
                "swap": True,
                "contract": True,
                "linear": True,
                "settle": "USDT",
                "limits": {"cost": {"min": 5.0}, "amount": {"min": 0.1}},
                "precision": {"amount": 1},
                "info": {"filters": [{"filterType": "LOT_SIZE", "stepSize": "0.1"}]},
            },
            "XRP/USDT:USDT": {
                "symbol": "XRP/USDT:USDT",
                "id": "XRPUSDT",
                "base": "XRP",
                "quote": "USDT",
                "swap": True,
                "contract": True,
                "linear": True,
                "settle": "USDT",
                "limits": {"cost": {"min": 5.0}, "amount": {"min": 0.1}},
                "precision": {"amount": 1},
                "info": {"filters": [{"filterType": "LOT_SIZE", "stepSize": "0.1"}]},
            },
        }


class FakePrivateExchange:
    def __init__(self) -> None:
        self.load_time_difference_calls = 0
        self.fetch_balance_calls = 0
        self.fetch_position_mode_calls = 0

    def load_time_difference(self) -> None:
        self.load_time_difference_calls += 1

    def fetch_balance(self):
        self.fetch_balance_calls += 1
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

    def fetch_position_mode(self, params=None):
        self.fetch_position_mode_calls += 1
        return {"hedged": False}


class TimestampRecoveringExchange(FakePrivateExchange):
    def __init__(self) -> None:
        super().__init__()
        self.load_markets_calls = 0
        self.fetch_my_trades_calls = 0
        self.fetch_positions_calls = 0
        self._first_trade_call = True

    def fetch_balance(self):
        self.fetch_balance_calls += 1
        return {
            "free": {"USDT": 120.0},
            "total": {"USDT": 120.0},
            "used": {"USDT": 0.0},
            "info": {
                "assets": [
                    {
                        "asset": "USDT",
                        "marginBalance": "120.0",
                        "availableBalance": "120.0",
                        "walletBalance": "120.0",
                    }
                ],
                "positions": [
                    {
                        "symbol": "XRPUSDT",
                        "positionAmt": "10",
                    }
                ],
            },
        }

    def load_markets(self):
        self.load_markets_calls += 1
        return {
            "XRP/USDT:USDT": {
                "symbol": "XRP/USDT:USDT",
                "id": "XRPUSDT",
                "base": "XRP",
                "quote": "USDT",
                "swap": True,
                "contract": True,
                "linear": True,
                "settle": "USDT",
            }
        }

    def fetch_positions(self, symbols=None):
        self.fetch_positions_calls += 1
        return [
            {
                "symbol": "XRP/USDT:USDT",
                "side": "long",
                "contracts": 10.0,
                "entryPrice": 1.5,
                "markPrice": 1.4,
                "notional": 14.0,
                "unrealizedPnl": 1.0,
                "marginMode": "isolated",
                "leverage": 3,
                "liquidationPrice": 2.0,
            }
        ]

    def fetch_my_trades(self, symbol: str, limit: int = 200):
        self.fetch_my_trades_calls += 1
        if self._first_trade_call:
            self._first_trade_call = False
            raise Exception('binance {"code":-1021,"msg":"Timestamp for this request was 1000ms ahead of the server\'s time."}')
        return [
            {
                "id": "t-open",
                "datetime": "2026-05-12T09:55:00Z",
                "timestamp": 1_778_572_500_000,
                "side": "sell",
                "amount": 10.0,
                "price": 1.5,
                "cost": 15.0,
                "fee": {"currency": "USDT", "cost": 0.01},
            },
            {
                "id": "t-close",
                "datetime": "2026-05-12T10:00:00Z",
                "timestamp": 1_778_572_800_000,
                "side": "buy",
                "amount": 10.0,
                "price": 1.4,
                "cost": 14.0,
                "fee": {"currency": "USDT", "cost": 0.01},
            },
        ]

    def fetch_position_mode(self, params=None):
        self.fetch_position_mode_calls += 1
        return {"hedged": False}


class FakeExchangePool(ExchangePool):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.public_exchange = FakePublicExchange()
        self.private_exchange = FakePrivateExchange()

    def public(self):
        return self.public_exchange

    def private(self):
        return self.private_exchange


class AnalyticsExchangePool(ExchangePool):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.private_exchange = TimestampRecoveringExchange()

    def private(self):
        return self.private_exchange


class PositionDetailsExchange(FakePrivateExchange):
    def __init__(self) -> None:
        super().__init__()
        self.fetch_positions_calls = 0

    def fetch_balance(self):
        self.fetch_balance_calls += 1
        return {
            "free": {"USDT": 160.0},
            "total": {"USDT": 160.0},
            "used": {"USDT": 0.0},
            "info": {
                "assets": [
                    {
                        "asset": "USDT",
                        "marginBalance": "160.0",
                        "availableBalance": "150.0",
                        "walletBalance": "160.0",
                    }
                ],
                "positions": [
                    {
                        "symbol": "XRPUSDT",
                        "positionAmt": "16.6",
                    }
                ],
            },
        }

    def fetch_positions(self, symbols=None):
        self.fetch_positions_calls += 1
        return [
            {
                "symbol": "XRP/USDT:USDT",
                "side": "long",
                "contracts": 16.6,
                "entryPrice": 1.4579,
                "markPrice": 1.4545,
                "notional": 24.1447,
                "unrealizedPnl": -0.05644,
                "marginMode": "isolated",
                "leverage": 3,
                "liquidationPrice": 0.97744952,
            }
        ]


class PositionDetailsPool(ExchangePool):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.private_exchange = PositionDetailsExchange()

    def private(self):
        return self.private_exchange


class TransientNetworkExchange:
    def __init__(self) -> None:
        self.load_markets_calls = 0

    def load_markets(self):
        self.load_markets_calls += 1
        if self.load_markets_calls == 1:
            raise Exception("HTTPSConnectionPool Max retries exceeded with url: /fapi/v1/exchangeInfo (Caused by SSLError(SSLEOFError(8, '[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol')))")
        return {
            "ETH/USDT:USDT": {
                "symbol": "ETH/USDT:USDT",
            }
        }


class ExchangeThrottlingTests(unittest.TestCase):
    def test_call_with_time_sync_retry_retries_transient_ssl_network_errors(self) -> None:
        exchange = TransientNetworkExchange()

        markets = call_with_time_sync_retry(
            exchange,
            exchange.load_markets,
            retry_attempts=3,
            retry_delay_seconds=0.0,
        )

        self.assertEqual(exchange.load_markets_calls, 2)
        self.assertIn("ETH/USDT:USDT", markets)

    def test_full_preflight_uses_cache_on_second_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(root)
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            pool = FakeExchangePool(settings)
            safety = LiveSafetyChecks(settings, journal, exchange_pool=pool)

            first = safety.run()
            second = safety.run(allow_cached_ok=True)

            self.assertTrue(first["live_guard"]["ok"])
            self.assertTrue(second["cached"])
            self.assertEqual(pool.public_exchange.fetch_time_calls, 1)
            self.assertEqual(pool.public_exchange.load_markets_calls, 1)
            self.assertEqual(pool.private_exchange.fetch_balance_calls, 1)
            self.assertEqual(pool.private_exchange.fetch_position_mode_calls, 1)

    def test_validate_bundle_primes_cached_preflight_without_extra_exchange_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(root)
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            pool = FakeExchangePool(settings)
            safety = LiveSafetyChecks(settings, journal, exchange_pool=pool)

            bundle = MarketSnapshotBundle(
                generated_at=utc_now(),
                timeframe="5m",
                symbols=[
                    SymbolSnapshot(
                        symbol="SOL/USDT:USDT",
                        timeframe="5m",
                        last_price=150.0,
                        indicators={},
                        recent_candles=[],
                        exchange_min_cost_quote=5.0,
                        exchange_min_amount=0.1,
                        exchange_amount_step=0.1,
                        higher_timeframe=None,
                    ),
                    SymbolSnapshot(
                        symbol="XRP/USDT:USDT",
                        timeframe="5m",
                        last_price=1.5,
                        indicators={},
                        recent_candles=[],
                        exchange_min_cost_quote=5.0,
                        exchange_min_amount=0.1,
                        exchange_amount_step=0.1,
                        higher_timeframe=None,
                    ),
                ],
                account=AccountSnapshot(
                    quote_currency="USDT",
                    equity_quote=100.0,
                    free_quote=100.0,
                    open_positions=[
                        PositionSnapshot(
                            symbol="XRP/USDT:USDT",
                            quantity=10.0,
                            mark_price=1.5,
                            market_value_quote=15.0,
                            side="long",
                            average_entry_price=1.4,
                            notional_quote=15.0,
                        )
                    ],
                    mode="live",
                    market_type="future",
                ),
            )

            checks = safety.validate_bundle(bundle)
            cached = safety.cached_preflight()

            self.assertTrue(checks["live_guard"]["ok"])
            self.assertIsNotNone(cached)
            self.assertEqual(pool.public_exchange.fetch_time_calls, 0)
            self.assertEqual(pool.public_exchange.load_markets_calls, 0)
            self.assertEqual(pool.private_exchange.fetch_balance_calls, 0)
            self.assertEqual(pool.private_exchange.fetch_position_mode_calls, 0)

    def test_exchange_pool_reuses_same_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(root)
            pool = ExchangePool(settings)
            self.assertIs(pool.public(), pool.public())

    def test_live_analytics_retries_timestamp_ahead_error_and_returns_realized_pnl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(root, symbols=("XRP/USDT",))
            journal = Journal(settings.db_path)
            journal.ensure_schema()
            pool = AnalyticsExchangePool(settings)
            analytics = LiveAnalyticsService(settings, journal, exchange_pool=pool)

            overview = analytics.fetch_live_overview()

            self.assertEqual(pool.private_exchange.fetch_balance_calls, 1)
            self.assertEqual(pool.private_exchange.load_markets_calls, 1)
            self.assertEqual(pool.private_exchange.fetch_positions_calls, 1)
            self.assertEqual(pool.private_exchange.fetch_my_trades_calls, 2)
            self.assertGreaterEqual(pool.private_exchange.load_time_difference_calls, 2)
            self.assertAlmostEqual(overview["realized_pnl_quote"], 0.98, places=6)
            self.assertEqual(len(overview["recent_trades"]), 2)
            self.assertEqual(overview["positions"][0]["symbol"], "XRP/USDT:USDT")
            self.assertEqual(overview["positions"][0]["average_entry_price"], 1.5)
            self.assertIs(pool.private(), pool.private())

    def test_market_gateway_uses_fetch_positions_for_futures_entry_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(root, symbols=("XRP/USDT",))
            pool = PositionDetailsPool(settings)
            gateway = MarketGateway(settings, exchange_pool=pool)
            markets = {
                "XRP/USDT:USDT": {
                    "symbol": "XRP/USDT:USDT",
                    "id": "XRPUSDT",
                    "base": "XRP",
                    "quote": "USDT",
                    "swap": True,
                    "contract": True,
                    "linear": True,
                    "settle": "USDT",
                }
            }

            account = gateway._fetch_live_account(markets, {"XRP/USDT:USDT": 1.4545})

            self.assertEqual(pool.private_exchange.fetch_balance_calls, 1)
            self.assertEqual(pool.private_exchange.fetch_positions_calls, 1)
            self.assertEqual(len(account.open_positions), 1)
            position = account.open_positions[0]
            self.assertEqual(position.symbol, "XRP/USDT:USDT")
            self.assertAlmostEqual(position.average_entry_price or 0.0, 1.4579)
            self.assertAlmostEqual(position.mark_price, 1.4545)
            self.assertAlmostEqual(position.unrealized_pnl_quote or 0.0, -0.05644)
            self.assertEqual(position.margin_mode, "isolated")
            self.assertAlmostEqual(position.liquidation_price or 0.0, 0.97744952)


if __name__ == "__main__":
    unittest.main()
