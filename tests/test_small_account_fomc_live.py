from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from qount.contracts import canonical_hash
from qount.settings import Settings
from qount.small_account.fomc_adapter import build_fomc_standard_chain
from qount.small_account.fomc_live import FomcLiveError
from qount.small_account.fomc_live import FomcLiveStore
from qount.small_account.fomc_live import _create_fomc_entry_order
from qount.small_account.fomc_live import _execution_artifact
from qount.small_account.fomc_live import _flatten_position
from qount.small_account.fomc_live import _ledger_native_stop_flatten
from qount.small_account.fomc_live import _ledgered_flatten_position
from qount.small_account.fomc_live import _recover_interrupted_fomc_attempt
from qount.small_account.fomc_live import build_fomc_live_account_preflight
from qount.small_account.fomc_live import build_fomc_live_arm
from qount.small_account.fomc_live import dispatch_fomc_live_entry
from qount.small_account.fomc_live import fomc_live_arm_valid
from qount.small_account.fomc_live import manage_fomc_live_position
from qount.small_account.fomc_live import run_fomc_live_cycle
from qount.small_account.fomc_live import set_fomc_live_environment_switch
from qount.small_account.fomc_live import write_fomc_live_environment
from qount.small_account.fomc_runtime import FomcEventDefinition
from qount.small_account.fomc_watcher import FomcStateStore
from qount.small_account.fomc_watcher import load_fomc_event_definition
from scripts.operations.run_fomc_live import main as fomc_live_main
from tests.test_small_account_fomc_adapter import _freeze
from tests.test_small_account_fomc_adapter import _healthy_account
from tests.test_small_account_fomc_adapter import _market
from tests.test_small_account_fomc_adapter import _scan


UTC = dt.timezone.utc
CCXT_SYMBOL = "BTC/USDT:USDT"
ACCOUNT_SCOPE = "d" * 64
ROOT = Path(__file__).resolve().parents[1]
EVENT_CONFIG = ROOT / "deploy" / "events" / "fomc-2026-07.json"


def _event() -> FomcEventDefinition:
    return FomcEventDefinition.create(
        event_name="FOMC-2026-07",
        instrument_key="binance|crypto|perpetual|BTCUSDT|USDT",
        symbol="BTCUSDT",
        source_url="https://www.federalreserve.gov/newsevents/2026-july.htm",
        source_hash="a" * 64,
        cash_only_from="2026-07-29T17:00:00+00:00",
        freeze_at="2026-07-29T17:30:00+00:00",
        statement_at="2026-07-29T18:00:00+00:00",
        press_conference_at="2026-07-29T18:30:00+00:00",
        observation_starts_at="2026-07-29T22:30:00+00:00",
        entry_cutoff_at="2026-07-30T04:00:00+00:00",
        force_exit_at="2026-07-30T11:00:00+00:00",
    )


def _settings(project_root: str, *, api_key: str = "key") -> Settings:
    with patch.dict(
        os.environ,
        {
            "QOUNT_PROJECT_ROOT": project_root,
            "QOUNT_MARKET_TYPE": "future",
            "QOUNT_EXCHANGE_ID": "binance",
            "QOUNT_BINANCE_API_KEY": api_key,
            "QOUNT_BINANCE_API_SECRET": "secret",
        },
        clear=False,
    ):
        return Settings.from_env()


def _parent_chain():
    return build_fomc_standard_chain(
        _event(),
        _freeze(),
        _scan("long"),
        _market(),
        account_snapshot=_healthy_account(),
        orders_authorized=False,
    )


def _scope_for_batch(batch, *, account_scope_hash: str = ACCOUNT_SCOPE) -> dict[str, object]:
    entry, stop = batch.plan.orders
    return {
        "event_id": _event().event_id,
        "account_scope_hash": account_scope_hash,
        "strategy_id": _event().strategy_id,
        "strategy_version": _event().strategy_version,
        "symbol": "BTCUSDT",
        "instrument_key": _event().instrument_key,
        "side": "long",
        "quantity": entry.quantity,
        "reference_entry_price": 102.0,
        "maximum_notional_usdt": float(entry.quantity) * 102.0,
        "maximum_stress_loss_usdt": 1.0,
        "risk_per_unit_usdt": 0.5,
        "target_price": 115.0,
        "stop_price": stop.stop_price,
        "exchange_rules_hash": "f" * 64,
        "price_tick": 0.1,
        "quantity_step": 0.001,
        "minimum_quantity": 0.001,
        "minimum_notional_usdt": 5.0,
        "contract_size": 1.0,
        "leverage": 3.0,
        "margin_mode": "isolated",
        "entry_client_order_id": entry.client_order_id,
        "stop_client_order_id": stop.client_order_id,
        "force_exit_at": _event().force_exit_at,
        "emergency_flatten_allowed": True,
        "maximum_adverse_slippage_bps": 20.0,
    }


def _readiness_for_batch(batch) -> dict[str, object]:
    signal = _scan("long")
    core = {
        "schema_version": 1,
        "artifact_type": "fomc_live_readiness",
        "event_id": _event().event_id,
        "created_at": "2026-07-29T23:16:00+00:00",
        "expires_at": "2026-07-29T23:26:00+00:00",
        "shadow_result_hash": "1" * 64,
        "preflight_hash": "2" * 64,
        "batch_id": batch.manifest.batch_id,
        "manifest_hash": batch.manifest.manifest_hash,
        "plan_hash": batch.plan.plan_hash,
        "signal_identity": {
            "side": signal.side,
            "anchor_candle_id": signal.anchor_candle_id,
            "breakout_candle_id": signal.breakout_candle_id,
            "retest_candle_ids": list(signal.retest_candle_ids),
            "structural_stop_price": signal.structural_stop_price,
            "signal_available_at": signal.signal_available_at,
        },
        "scope": _scope_for_batch(batch),
        "gates": {},
        "blockers": [],
        "verdict": "ready_for_fomc_live_arm",
        "permissions": {
            "orders_authorized": False,
            "private_api_used": True,
            "private_api_order_attempted": False,
            "exchange_mutation_attempted": False,
            "manual_arm_required": True,
        },
    }
    return core | {"readiness_hash": canonical_hash(core)}


def _readiness() -> dict[str, object]:
    return _readiness_for_batch(_parent_chain().batch)


def _readiness_for_event(event: FomcEventDefinition) -> dict[str, object]:
    readiness = _readiness()
    core = {key: value for key, value in readiness.items() if key != "readiness_hash"}
    core["event_id"] = event.event_id
    scope = dict(core["scope"])
    scope["event_id"] = event.event_id
    core["scope"] = scope
    return core | {"readiness_hash": canonical_hash(core)}


def _build_arm(
    readiness: dict[str, object], *, token: str, armed_at: str
) -> dict[str, object]:
    return build_fomc_live_arm(
        readiness,
        arm_token=token,
        armed_at=armed_at,
        confirmed_readiness_hash=str(readiness["readiness_hash"]),
    )


def _attempt(readiness: dict[str, object], arm: dict[str, object]) -> dict[str, object]:
    scope = readiness["scope"]
    assert isinstance(scope, dict)
    core = {
        "schema_version": 1,
        "artifact_type": "fomc_live_single_entry_attempt",
        "event_id": _event().event_id,
        "arm_id": arm["arm_id"],
        "readiness_hash": readiness["readiness_hash"],
        "batch_id": readiness["batch_id"],
        "plan_hash": readiness["plan_hash"],
        "started_at": "2026-07-29T23:17:00+00:00",
        "entry_client_order_id": scope["entry_client_order_id"],
        "stop_client_order_id": scope["stop_client_order_id"],
    }
    return core | {"attempt_hash": canonical_hash(core)}


def _preflight(
    *,
    created_at: str = "2026-07-29T23:18:00+00:00",
    account_scope_hash: str = ACCOUNT_SCOPE,
    positions: list[dict[str, object]] | None = None,
    regular: list[dict[str, object]] | None = None,
    conditional: list[dict[str, object]] | None = None,
    errors: dict[str, object] | None = None,
    verdict: str = "fomc_live_account_preflight_pass",
    equity: float = 200.0,
) -> dict[str, object]:
    core = {
        "schema_version": 1,
        "artifact_type": "fomc_live_account_preflight",
        "event_id": _event().event_id,
        "created_at": created_at,
        "meta": {"read_only": True},
        "account": {
            "credentials_present": True,
            "permissions": {},
            "balance": {
                "quote_total": equity,
                "quote_free": equity,
                "quote_used": 0.0,
                "wallet_balance": equity,
                "margin_balance": equity,
            },
            "position_mode": {"hedged": False},
            "positions": list(positions or []),
            "regular_open_orders": list(regular or []),
            "conditional_open_orders": list(conditional or []),
            "configuration": {"leverage": 3.0, "margin_mode": "isolated"},
            "trading_fee": {"maker": 0.0002, "taker": 0.0004},
            "resolved_symbol": CCXT_SYMBOL,
            "market_rules": {
                "symbol": "BTCUSDT",
                "settle": "USDT",
                "linear": True,
                "swap": True,
                "active": True,
                "price_tick": 0.1,
                "quantity_step": 0.001,
                "minimum_quantity": 0.001,
                "minimum_notional_usdt": 5.0,
                "contract_size": 1.0,
                "exchange_rules_hash": "f" * 64,
            },
            "account_scope_hash": account_scope_hash,
        },
        "expected": {},
        "diagnostics": {
            "errors": dict(errors or {}),
            "gates": {},
            "blockers": list((errors or {}).keys()),
            "verdict": verdict,
        },
    }
    return core | {"preflight_hash": canonical_hash(core)}


def _seed_open_parent(
    ledger,
    batch,
    *,
    stop_acknowledged: bool = False,
    entry_fee: float = 0.04,
    entry_fee_asset: str = "USDT",
) -> None:
    entry, stop = batch.plan.orders
    ledger.record_verified_batch(batch, recorded_at=batch.manifest.created_at)
    ledger.record_position_snapshot(
        symbol=_event().instrument_key,
        quantity=0.0,
        average_cost=0.0,
        realized_trading_pnl=0.0,
        occurred_at="2026-07-29T23:16:00+00:00",
        source_hash="3" * 64,
    )
    ledger.record_nav_mark(
        marked_at="2026-07-29T23:16:01+00:00",
        opening_equity=200.0,
        equity=200.0,
        trading_pnl=0.0,
        residual_tolerance=0.001,
        source_hash="4" * 64,
    )
    ledger.transition_order(
        entry.client_order_id,
        "SUBMITTING",
        event_at="2026-07-29T23:16:01.100000+00:00",
        source_hash="5" * 64,
    )
    ledger.transition_order(
        entry.client_order_id,
        "FILLED",
        event_at="2026-07-29T23:16:02+00:00",
        source_hash="6" * 64,
        exchange_order_id="entry-1",
        executed_quantity=float(entry.quantity),
        average_price=100.0,
    )
    ledger.record_fill(
        client_order_id=entry.client_order_id,
        exchange_trade_id="entry-trade-1",
        quantity=float(entry.quantity),
        price=100.0,
        fee=entry_fee,
        fee_asset=entry_fee_asset,
        occurred_at="2026-07-29T23:16:02+00:00",
        source_hash="6" * 64,
    )
    if stop_acknowledged:
        ledger.transition_order(
            stop.client_order_id,
            "SUBMITTING",
            event_at="2026-07-29T23:16:02.100000+00:00",
            source_hash="7" * 64,
        )
        ledger.transition_order(
            stop.client_order_id,
            "ACKNOWLEDGED",
            event_at="2026-07-29T23:16:02.200000+00:00",
            source_hash="8" * 64,
            exchange_order_id="algo-1",
        )


def _seed_interrupted_parent(ledger, batch) -> None:
    entry = batch.plan.orders[0]
    ledger.record_verified_batch(batch, recorded_at=batch.manifest.created_at)
    ledger.record_position_snapshot(
        symbol=_event().instrument_key,
        quantity=0.0,
        average_cost=0.0,
        realized_trading_pnl=0.0,
        occurred_at="2026-07-29T23:16:00+00:00",
        source_hash="3" * 64,
    )
    ledger.record_nav_mark(
        marked_at="2026-07-29T23:16:01+00:00",
        opening_equity=200.0,
        equity=200.0,
        trading_pnl=0.0,
        residual_tolerance=0.001,
        source_hash="4" * 64,
    )
    ledger.transition_order(
        entry.client_order_id,
        "SUBMITTING",
        event_at="2026-07-29T23:16:01.100000+00:00",
        source_hash="5" * 64,
    )
    ledger.transition_order(
        entry.client_order_id,
        "UNKNOWN",
        event_at="2026-07-29T23:16:01.200000+00:00",
        source_hash="6" * 64,
        reason="simulated_interrupted_entry",
    )


def _protected_execution(batch, scope, stop) -> dict[str, object]:
    entry = batch.plan.orders[0]
    return _execution_artifact(
        _event(),
        {
            "readiness_hash": "1" * 64,
            "batch_id": batch.manifest.batch_id,
            "scope": scope,
        },
        {"arm_id": "2" * 64},
        observed_at="2026-07-29T23:18:00+00:00",
        status="protected",
        entry={
            "id": "entry-1",
            "client_order_id": entry.client_order_id,
            "symbol": "BTCUSDT",
            "side": "buy",
            "status": "closed",
            "filled": float(scope["quantity"]),
            "average": 100.0,
        },
        protection=stop,
        exchange_mutation_attempted=True,
    )


class _FullPreflightExchange:
    def __init__(self) -> None:
        self.options: dict[str, object] = {}
        self.create_calls: list[tuple[object, ...]] = []

    def load_time_difference(self):
        return 0

    def load_markets(self):
        return {
            CCXT_SYMBOL: {
                "id": "BTCUSDT",
                "symbol": CCXT_SYMBOL,
                "base": "BTC",
                "quote": "USDT",
                "settle": "USDT",
                "contract": True,
                "linear": True,
                "swap": True,
                "active": True,
                "contractSize": 1.0,
                "precision": {"price": 0.1, "amount": 0.001},
                "limits": {
                    "amount": {"min": 0.001},
                    "cost": {"min": 5.0},
                },
                "info": {
                    "filters": [
                        {"filterType": "PRICE_FILTER", "tickSize": "0.1"},
                        {
                            "filterType": "LOT_SIZE",
                            "stepSize": "0.001",
                            "minQty": "0.001",
                        },
                        {"filterType": "MIN_NOTIONAL", "notional": "5"},
                    ]
                },
            }
        }

    def fetch_balance(self):
        return {
            "free": {"USDT": 300.0},
            "used": {"USDT": 0.0},
            "total": {"USDT": 300.0},
            "info": {
                "accountAlias": "same-account-alias",
                "assets": [
                    {
                        "asset": "USDT",
                        "walletBalance": "300",
                        "marginBalance": "300",
                        "availableBalance": "300",
                    }
                ],
            },
        }

    def sapiGetAccountApiRestrictions(self):
        return {
            "enableReading": True,
            "enableSpotAndMarginTrading": False,
            "enableFutures": True,
            "enableWithdrawals": False,
            "ipRestrict": True,
        }

    def fetch_position_mode(self, params=None):
        return {"hedged": False}

    def fetch_positions(self):
        return []

    def fetch_open_orders(self, symbol=None, params=None):
        return []

    def fetch_leverages(self, symbols, params=None):
        return {CCXT_SYMBOL: {"symbol": CCXT_SYMBOL, "leverage": 3.0}}

    def fetch_margin_modes(self, symbols, params=None):
        return {CCXT_SYMBOL: {"symbol": CCXT_SYMBOL, "marginMode": "isolated"}}

    def fetch_trading_fee(self, symbol):
        return {"maker": 0.0002, "taker": 0.0004}

    def create_order(self, *args):
        self.create_calls.append(args)
        raise AssertionError("preflight must not create an order")


class _FlattenExchange:
    def __init__(self) -> None:
        self.orders: list[tuple[object, ...]] = []
        self.canceled: list[tuple[object, ...]] = []

    def cancel_order(self, order_id, symbol, params):
        self.canceled.append((order_id, symbol, params))
        return {
            "id": order_id,
            "clientAlgoId": params["clientAlgoId"],
            "status": "canceled",
            "symbol": symbol,
        }

    def fapiPrivateGetAlgoOrder(self, request):
        return {
            "algoId": "stop-1",
            "clientAlgoId": request["clientAlgoId"],
            "algoStatus": "CANCELED",
            "symbol": request["symbol"],
            "side": "SELL",
            "orderType": "STOP_MARKET",
            "workingType": "MARK_PRICE",
            "closePosition": True,
            "stopPrice": 98.0,
        }

    def create_order(self, symbol, order_type, side, amount, price, params):
        self.orders.append((symbol, order_type, side, amount, price, params))
        return {
            "id": "exit-1",
            "clientOrderId": params["newClientOrderId"],
            "status": "closed",
            "filled": amount,
            "average": 100.0,
        }

    def fetch_order(self, order_id, symbol):
        client_id = self.orders[-1][-1]["newClientOrderId"]
        return {
            "id": order_id,
            "clientOrderId": client_id,
            "status": "closed",
            "filled": 0.001,
            "average": 100.0,
        }

    def fetch_order_trades(self, order_id, symbol):
        client_id = self.orders[-1][-1]["newClientOrderId"]
        return [
            {
                "id": "trade-1",
                "order": order_id,
                "clientOrderId": client_id,
                "amount": 0.001,
                "price": 100.0,
                "datetime": "2026-07-30T11:00:01+00:00",
                "fee": {"cost": 0.00004, "currency": "USDT"},
            }
        ]


class _MutationTrackingExchange:
    def __init__(self) -> None:
        self.created: list[tuple[object, ...]] = []
        self.canceled: list[tuple[object, ...]] = []

    def create_order(self, *args):
        self.created.append(args)
        raise AssertionError("unexpected order mutation")

    def cancel_order(self, *args):
        self.canceled.append(args)
        raise AssertionError("unexpected cancel mutation")


class _ExitExchange:
    def __init__(self, quantity: float) -> None:
        self.quantity = quantity
        self.created: list[tuple[object, ...]] = []

    @property
    def client_order_id(self) -> str:
        return str(self.created[0][-1]["newClientOrderId"])

    def create_order(self, symbol, order_type, side, amount, price, params):
        self.created.append((symbol, order_type, side, amount, price, params))
        return {
            "id": "exit-1",
            "clientOrderId": params["newClientOrderId"],
            "symbol": "BTCUSDT",
            "side": side,
            "status": "closed",
            "filled": amount,
            "average": 100.0,
        }

    def fetch_order(self, order_id, symbol):
        return {
            "id": "exit-1",
            "clientOrderId": self.client_order_id,
            "symbol": "BTCUSDT",
            "side": "sell",
            "status": "closed",
            "filled": self.quantity,
            "average": 100.0,
        }

    def fetch_order_trades(self, order_id, symbol):
        return [
            {
                "id": "exit-trade-1",
                "order": "exit-1",
                "clientOrderId": self.client_order_id,
                "amount": self.quantity,
                "price": 100.0,
                "datetime": "2026-07-29T23:16:04+00:00",
                "fee": {"cost": 0.04, "currency": "USDT"},
            }
        ]

    def fetch_ledger(self, code, since, limit):
        return _commission_rows()


class _AlgoStopExchange:
    def __init__(self, stop_client_id: str, quantity: float) -> None:
        self.stop_client_id = stop_client_id
        self.quantity = quantity
        self.algo_requests: list[dict[str, object]] = []

    def fapiPrivateGetAlgoOrder(self, request):
        self.algo_requests.append(dict(request))
        return {
            "algoId": "algo-1",
            "clientAlgoId": self.stop_client_id,
            "algoStatus": "FILLED",
            "symbol": "BTCUSDT",
            "side": "SELL",
            "orderType": "STOP_MARKET",
            "closePosition": True,
            "actualOrderId": "stop-fill-1",
            "executedQty": self.quantity,
            "avgPrice": 99.0,
        }

    def fetch_order_trades(self, order_id, symbol):
        return [
            {
                "id": "stop-trade-1",
                "order": "stop-fill-1",
                "amount": self.quantity,
                "price": 99.0,
                "datetime": "2026-07-29T23:16:04+00:00",
                "fee": {"cost": 0.04, "currency": "USDT"},
            }
        ]

    def fetch_ledger(self, code, since, limit):
        return _commission_rows()


class _TerminalEntryExchange:
    def __init__(
        self,
        *,
        client_order_id: str,
        quantity: float,
        status: str = "EXPIRED",
        fee_asset: str = "USDT",
    ) -> None:
        self.client_order_id = client_order_id
        self.quantity = quantity
        self.status = status
        self.fee_asset = fee_asset
        self.stop_submissions: list[tuple[object, ...]] = []

    def order(self) -> dict[str, object]:
        return {
            "id": "entry-partial-1",
            "clientOrderId": self.client_order_id,
            "symbol": "BTCUSDT",
            "side": "BUY",
            "status": self.status,
            "filled": self.quantity,
            "average": 100.0,
        }

    def fetch_order_trades(self, order_id, symbol):
        return [
            {
                "id": "entry-partial-trade-1",
                "order": "entry-partial-1",
                "clientOrderId": self.client_order_id,
                "amount": self.quantity,
                "price": 100.0,
                "datetime": "2026-07-29T23:16:02+00:00",
                "fee": {"cost": 0.01, "currency": self.fee_asset},
            }
        ]

    def fetch_order(self, order_id, symbol):
        return self.order()

    def create_order(self, symbol, order_type, side, amount, price, params):
        self.stop_submissions.append(
            (symbol, order_type, side, amount, price, params)
        )
        return {
            "id": "algo-1",
            "clientOrderId": params["newClientOrderId"],
            "symbol": "BTCUSDT",
            "type": "STOP_MARKET",
            "workingType": "MARK_PRICE",
            "side": side,
            "status": "open",
            "closePosition": True,
            "stopPrice": params["stopPrice"],
        }


class _TerminalReductionExchange:
    def __init__(self, *, quantity: float) -> None:
        self.quantity = quantity
        self.queried_client_ids: list[str] = []

    def response(self, client_order_id: str) -> dict[str, object]:
        self.queried_client_ids.append(client_order_id)
        return {
            "id": "exit-partial-1",
            "clientOrderId": client_order_id,
            "symbol": "BTCUSDT",
            "side": "SELL",
            "status": "EXPIRED",
            "filled": self.quantity,
            "average": 100.0,
        }

    def fetch_order_trades(self, order_id, symbol):
        return [
            {
                "id": "exit-partial-trade-1",
                "order": "exit-partial-1",
                "amount": self.quantity,
                "price": 100.0,
                "datetime": "2026-07-30T11:00:02+00:00",
                "fee": {"cost": 0.01, "currency": "USDT"},
            }
        ]


def _commission_rows() -> list[dict[str, object]]:
    return [
        {
            "id": "commission-entry",
            "currency": "USDT",
            "datetime": "2026-07-29T23:16:02+00:00",
            "info": {"incomeType": "COMMISSION", "income": "-0.04"},
        },
        {
            "id": "commission-exit",
            "currency": "USDT",
            "datetime": "2026-07-29T23:16:04+00:00",
            "info": {"incomeType": "COMMISSION", "income": "-0.04"},
        },
    ]


class FomcLiveArmTest(unittest.TestCase):
    def test_arm_is_single_use_and_switch_file_stays_private(self) -> None:
        readiness = _readiness()
        token = "t" * 48
        arm = _build_arm(
            readiness,
            token=token,
            armed_at="2026-07-29T23:17:00+00:00",
        )
        with tempfile.TemporaryDirectory() as directory:
            store = FomcLiveStore(directory, _event().event_id)
            store.write_readiness(readiness)
            store.write_arm(arm)
            environment = Path(directory) / "private" / "fomc-live.env"
            write_fomc_live_environment(
                environment, arm=arm, arm_token=token, enabled=False
            )
            self.assertEqual(environment.stat().st_mode & 0o777, 0o600)
            self.assertIn("QOUNT_FOMC_LIVE_ENABLE=false", environment.read_text())
            set_fomc_live_environment_switch(
                environment, arm_id=str(arm["arm_id"]), enabled=True
            )
            self.assertIn("QOUNT_FOMC_LIVE_ENABLE=true", environment.read_text())
            self.assertTrue(
                fomc_live_arm_valid(
                    arm,
                    readiness,
                    arm_token=token,
                    live_switch_enabled=True,
                    live_confirmation=str(arm["arm_id"]),
                    observed_at="2026-07-29T23:18:00+00:00",
                    consumed=False,
                )
            )
            store.consume_arm(arm, consumed_at="2026-07-29T23:18:00+00:00")
            with self.assertRaisesRegex(FomcLiveError, "already_consumed"):
                store.consume_arm(arm, consumed_at="2026-07-29T23:19:00+00:00")

    def test_arm_rejects_expired_readiness(self) -> None:
        with self.assertRaisesRegex(FomcLiveError, "readiness_expired"):
            _build_arm(
                _readiness(),
                token="t" * 48,
                armed_at="2026-07-29T23:26:00+00:00",
            )

    def test_cli_arm_requires_exact_readiness_hash_and_reports_bound_scope(self) -> None:
        event = load_fomc_event_definition(EVENT_CONFIG)
        readiness = _readiness_for_event(event)
        with tempfile.TemporaryDirectory() as directory:
            state_root = Path(directory) / "state"
            environment = Path(directory) / "private" / "fomc-live.env"
            store = FomcLiveStore(state_root, event.event_id)
            store.write_readiness(readiness)
            base = (
                "--event-config",
                str(EVENT_CONFIG),
                "--state-root",
                str(state_root),
                "arm",
                "--environment-file",
                str(environment),
            )
            with (
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                fomc_live_main(base)
            with (
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                fomc_live_main(base + ("--confirm-readiness-hash", "9" * 64))

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = fomc_live_main(
                    base
                    + (
                        "--confirm-readiness-hash",
                        str(readiness["readiness_hash"]),
                    )
                )
            summary = json.loads(output.getvalue())

        scope = readiness["scope"]
        assert isinstance(scope, dict)
        self.assertEqual(status, 0)
        self.assertEqual(summary["readiness_hash"], readiness["readiness_hash"])
        self.assertEqual(summary["plan_hash"], readiness["plan_hash"])
        self.assertEqual(
            summary["account_scope_hash"], scope["account_scope_hash"]
        )
        self.assertEqual(summary["scope"], scope)


class FomcLivePreflightTest(unittest.TestCase):
    def test_credential_swap_changes_account_scope_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            exchange = _FullPreflightExchange()
            first = build_fomc_live_account_preflight(
                _settings(directory, api_key="credential-one"),
                _event(),
                observed_at="2026-07-29T23:16:00+00:00",
                exchange=exchange,
            )
            second = build_fomc_live_account_preflight(
                _settings(directory, api_key="credential-two"),
                _event(),
                observed_at="2026-07-29T23:16:01+00:00",
                exchange=exchange,
            )

        self.assertEqual(
            first["diagnostics"]["verdict"], "fomc_live_account_preflight_pass"
        )
        self.assertEqual(
            second["diagnostics"]["verdict"], "fomc_live_account_preflight_pass"
        )
        self.assertNotEqual(
            first["account"]["account_scope_hash"],
            second["account"]["account_scope_hash"],
        )
        self.assertEqual(exchange.create_calls, [])

    def test_private_and_public_rule_drift_block_dispatch_without_order(self) -> None:
        batch = _parent_chain().batch
        readiness = _readiness_for_batch(batch)
        scope = readiness["scope"]
        assert isinstance(scope, dict)
        signal = _scan("long").as_dict()
        market = _market().as_dict()
        current_shadow = {
            "stage": "ARMED",
            "observed_at": market["observed_at"],
            "signal": signal,
            "market": market,
        }
        baseline = _preflight(account_scope_hash=str(scope["account_scope_hash"]))
        baseline["account"]["market_rules"] = {
            "symbol": "BTCUSDT",
            "settle": "USDT",
            "linear": True,
            "swap": True,
            "active": True,
            "price_tick": 0.1,
            "quantity_step": 0.001,
            "minimum_quantity": 0.001,
            "minimum_notional_usdt": 5.0,
            "contract_size": 1.0,
            "exchange_rules_hash": "f" * 64,
        }
        exchange = _MutationTrackingExchange()

        private_drift = dict(baseline)
        private_drift["account"] = dict(baseline["account"])
        private_drift["account"]["market_rules"] = dict(
            baseline["account"]["market_rules"]
        )
        private_drift["account"]["market_rules"]["exchange_rules_hash"] = "9" * 64
        private_result = dispatch_fomc_live_entry(
            _settings(tempfile.gettempdir()),
            _event(),
            None,
            None,
            readiness,
            {"arm_id": "a" * 64},
            current_shadow,
            private_drift,
            exchange=exchange,
        )
        self.assertIn("private_exchange_rules_changed", private_result["blockers"])

        observed_market = _market()
        public_drift_market = type(observed_market).create(
            symbol=observed_market.symbol,
            observed_at=observed_market.observed_at,
            data_cutoff=observed_market.data_cutoff,
            last_price=observed_market.last_price,
            bid_price=observed_market.bid_price,
            ask_price=observed_market.ask_price,
            mark_price=observed_market.mark_price,
            index_price=observed_market.index_price,
            funding_rate=observed_market.funding_rate,
            price_tick=observed_market.price_tick,
            quantity_step=observed_market.quantity_step,
            minimum_quantity=observed_market.minimum_quantity,
            minimum_notional_usdt=observed_market.minimum_notional_usdt,
            exchange_rules_hash="8" * 64,
            source_hashes=observed_market.source_hashes,
        )
        public_shadow = dict(current_shadow)
        public_shadow["market"] = public_drift_market.as_dict()
        public_result = dispatch_fomc_live_entry(
            _settings(tempfile.gettempdir()),
            _event(),
            None,
            None,
            readiness,
            {"arm_id": "a" * 64},
            public_shadow,
            baseline,
            exchange=exchange,
        )
        self.assertIn("public_exchange_rules_changed", public_result["blockers"])
        self.assertEqual(exchange.created, [])


class FomcLiveDispatchTimeTest(unittest.TestCase):
    def test_trusted_wall_clock_rejects_expired_arm_cutoff_and_stale_quote(self) -> None:
        exchange = _MutationTrackingExchange()
        market = _market().as_dict()

        cases = (
            (
                "manual_arm_expired_before_submit",
                dt.datetime(2026, 7, 29, 23, 20, tzinfo=UTC),
                "2026-07-29T23:19:00+00:00",
                "2026-07-29T23:20:00+00:00",
            ),
            (
                "entry_cutoff_reached_before_submit",
                dt.datetime(2026, 7, 30, 4, 0, tzinfo=UTC),
                "2026-07-30T04:05:00+00:00",
                "2026-07-30T04:00:00+00:00",
            ),
            (
                "quote_stale_before_submit",
                dt.datetime(2026, 7, 29, 23, 20, tzinfo=UTC),
                "2026-07-29T23:25:00+00:00",
                "2026-07-29T23:20:00+00:00",
            ),
        )
        for expected, now, expires_at, preflight_at in cases:
            with self.subTest(expected=expected), patch(
                "qount.small_account.fomc_live.utc_now", return_value=now
            ):
                with self.assertRaisesRegex(FomcLiveError, expected):
                    _create_fomc_entry_order(
                        exchange,
                        _event(),
                        {"expires_at": expires_at},
                        {"observed_at": preflight_at, "market": market},
                        {"created_at": preflight_at},
                        ccxt_symbol=CCXT_SYMBOL,
                        side="buy",
                        quantity=0.001,
                        client_order_id="entry-client",
                    )
        self.assertEqual(exchange.created, [])

    def test_cycle_entry_cutoff_uses_trusted_clock_not_spoofed_observation(self) -> None:
        readiness = _readiness()
        token = "t" * 48
        arm = _build_arm(
            readiness,
            token=token,
            armed_at="2026-07-29T23:17:00+00:00",
        )
        with tempfile.TemporaryDirectory() as directory:
            settings = _settings(directory)
            state_store = FomcStateStore(directory, _event().event_id)
            live_store = FomcLiveStore(directory, _event().event_id)
            live_store.write_readiness(readiness)
            live_store.write_arm(arm)
            with (
                patch(
                    "qount.small_account.fomc_live.utc_now",
                    return_value=dt.datetime(2026, 7, 30, 4, 0, 1, tzinfo=UTC),
                ),
                patch(
                    "qount.small_account.fomc_live.run_fomc_shadow_cycle",
                    return_value={"observed_at": "2026-07-29T23:18:00+00:00"},
                ),
                patch(
                    "qount.small_account.fomc_live.build_fomc_live_account_preflight",
                    return_value=_preflight(),
                ),
                patch(
                    "qount.small_account.fomc_live.dispatch_fomc_live_entry",
                    return_value=_execution_artifact(
                        _event(),
                        readiness,
                        arm,
                        observed_at="2026-07-29T23:18:00+00:00",
                        status="protected",
                        exchange_mutation_attempted=True,
                    ),
                ) as dispatch,
            ):
                result = run_fomc_live_cycle(
                    settings,
                    _event(),
                    state_store,
                    live_store,
                    observed_at="2026-07-29T23:18:00+00:00",
                    arm_token=token,
                    live_switch_enabled=True,
                    live_confirmation=str(arm["arm_id"]),
                    public_exchange=object(),
                    private_exchange=object(),
                )
        self.assertEqual(result["status"], "disarmed")
        self.assertFalse(result["exchange_mutation_attempted"])
        dispatch.assert_not_called()


class FomcLiveFlattenTest(unittest.TestCase):
    def test_flatten_cancels_stop_uses_reduce_only_and_requires_flat_readback(self) -> None:
        exchange = _FlattenExchange()
        with tempfile.TemporaryDirectory() as directory:
            settings = _settings(directory)
            preflight = _preflight(created_at="2026-07-30T11:00:02+00:00")
            with patch(
                "qount.small_account.fomc_live.build_fomc_live_account_preflight",
                return_value=preflight,
            ):
                result = _flatten_position(
                    settings,
                    _event(),
                    exchange=exchange,
                    ccxt_symbol=CCXT_SYMBOL,
                    quantity=0.001,
                    position_side="long",
                    purpose="force-exit",
                    protective_stop={
                        "id": "stop-1",
                        "client_order_id": "stop-client",
                    },
                )
        self.assertTrue(result["flat_readback_verified"])
        self.assertEqual(exchange.canceled[0][0], "stop-1")
        self.assertEqual(exchange.orders[0][2], "sell")
        self.assertTrue(exchange.orders[0][-1]["reduceOnly"])
        self.assertLessEqual(len(exchange.orders[0][-1]["newClientOrderId"]), 36)

    def test_flatten_fails_closed_when_account_is_not_proven_flat(self) -> None:
        exchange = _FlattenExchange()
        with tempfile.TemporaryDirectory() as directory:
            settings = _settings(directory)
            preflight = _preflight(
                verdict="blocked_fomc_live_account_preflight",
                errors={"positions": "unavailable"},
            )
            with patch(
                "qount.small_account.fomc_live.build_fomc_live_account_preflight",
                return_value=preflight,
            ):
                with self.assertRaisesRegex(FomcLiveError, "flatten_readback_failed"):
                    _flatten_position(
                        settings,
                        _event(),
                        exchange=exchange,
                        ccxt_symbol=CCXT_SYMBOL,
                        quantity=0.001,
                        position_side="short",
                        purpose="protection-failure",
                    )

    def test_valid_interrupted_attempt_flat_account_halts_without_resubmission(self) -> None:
        batch = _parent_chain().batch
        readiness = _readiness_for_batch(batch)
        arm = build_fomc_live_arm(
            readiness,
            arm_token="t" * 48,
            armed_at="2026-07-29T23:17:00+00:00",
            confirmed_readiness_hash=str(readiness["readiness_hash"]),
        )
        scope = readiness["scope"]
        assert isinstance(scope, dict)
        preflight = _preflight(account_scope_hash=str(scope["account_scope_hash"]))
        exchange = _MutationTrackingExchange()
        entry_response = {
            "id": "entry-1",
            "clientOrderId": scope["entry_client_order_id"],
            "symbol": "BTCUSDT",
            "side": "BUY",
            "status": "CANCELED",
            "filled": 0.0,
        }
        with tempfile.TemporaryDirectory() as directory:
            settings = _settings(directory)
            store = FomcLiveStore(directory, _event().event_id)
            store.write_attempt(_attempt(readiness, arm))
            state_store = SimpleNamespace(batches_root=Path(directory) / "batches")
            with (
                patch(
                    "qount.small_account.fomc_live.build_fomc_live_account_preflight",
                    return_value=preflight,
                ),
                patch(
                    "qount.small_account.fomc_live._fetch_order_by_client_id",
                    return_value=entry_response,
                ),
                patch(
                    "qount.small_account.fomc_live.read_decision_batch",
                    return_value=batch,
                ),
                patch(
                    "qount.small_account.fomc_live._ledger_flat_without_entry_fill",
                    return_value={"reconciliation": {"passed": True}},
                ),
            ):
                result = _recover_interrupted_fomc_attempt(
                    settings,
                    _event(),
                    store,
                    readiness,
                    arm,
                    observed_at="2026-07-29T23:18:00+00:00",
                    exchange=exchange,
                    state_store=state_store,
                )
        self.assertEqual(result["status"], "halted_interrupted_attempt_flat")
        self.assertFalse(result["permissions"]["exchange_mutation_attempted"])
        self.assertEqual(exchange.created, [])
        self.assertEqual(exchange.canceled, [])

    def test_interrupted_recovery_rejects_user_position_and_order_without_mutation(self) -> None:
        batch = _parent_chain().batch
        readiness = _readiness_for_batch(batch)
        arm = build_fomc_live_arm(
            readiness,
            arm_token="t" * 48,
            armed_at="2026-07-29T23:17:00+00:00",
            confirmed_readiness_hash=str(readiness["readiness_hash"]),
        )
        scope = readiness["scope"]
        assert isinstance(scope, dict)
        preflight = _preflight(
            account_scope_hash=str(scope["account_scope_hash"]),
            positions=[
                {
                    "symbol": CCXT_SYMBOL,
                    "quantity": float(scope["quantity"]),
                    "average_price": 100.0,
                    "notional_usdt": 100.0,
                }
            ],
            regular=[
                {
                    "id": "user-order-1",
                    "client_order_id": "user-owned-client-id",
                    "symbol": CCXT_SYMBOL,
                    "side": "buy",
                    "status": "open",
                }
            ],
            verdict="blocked_fomc_live_account_preflight",
        )
        exchange = _MutationTrackingExchange()
        with tempfile.TemporaryDirectory() as directory:
            settings = _settings(directory)
            store = FomcLiveStore(directory, _event().event_id)
            store.write_attempt(_attempt(readiness, arm))
            with patch(
                "qount.small_account.fomc_live.build_fomc_live_account_preflight",
                return_value=preflight,
            ):
                result = _recover_interrupted_fomc_attempt(
                    settings,
                    _event(),
                    store,
                    readiness,
                    arm,
                    observed_at="2026-07-29T23:18:00+00:00",
                    exchange=exchange,
                )
        self.assertEqual(result["status"], "halted_uncertain")
        self.assertIn("order_ownership_ambiguous", " ".join(result["blockers"]))
        self.assertFalse(result["permissions"]["exchange_mutation_attempted"])
        self.assertEqual(exchange.created, [])
        self.assertEqual(exchange.canceled, [])

    def test_interrupted_recovery_rejects_unowned_position_without_mutation(self) -> None:
        batch = _parent_chain().batch
        readiness = _readiness_for_batch(batch)
        arm = build_fomc_live_arm(
            readiness,
            arm_token="t" * 48,
            armed_at="2026-07-29T23:17:00+00:00",
            confirmed_readiness_hash=str(readiness["readiness_hash"]),
        )
        scope = readiness["scope"]
        assert isinstance(scope, dict)
        expected_quantity = float(scope["quantity"])
        preflight = _preflight(
            account_scope_hash=str(scope["account_scope_hash"]),
            positions=[
                {
                    "symbol": CCXT_SYMBOL,
                    "quantity": expected_quantity + 0.001,
                    "average_price": 100.0,
                    "notional_usdt": 100.0,
                }
            ],
            verdict="blocked_fomc_live_account_preflight",
        )
        entry_response = {
            "id": "entry-1",
            "clientOrderId": scope["entry_client_order_id"],
            "symbol": "BTCUSDT",
            "side": "BUY",
            "status": "FILLED",
            "filled": expected_quantity,
            "average": 100.0,
        }
        exchange = _MutationTrackingExchange()
        with tempfile.TemporaryDirectory() as directory:
            settings = _settings(directory)
            store = FomcLiveStore(directory, _event().event_id)
            store.write_attempt(_attempt(readiness, arm))
            with (
                patch(
                    "qount.small_account.fomc_live.build_fomc_live_account_preflight",
                    return_value=preflight,
                ),
                patch(
                    "qount.small_account.fomc_live._fetch_order_by_client_id",
                    return_value=entry_response,
                ),
            ):
                result = _recover_interrupted_fomc_attempt(
                    settings,
                    _event(),
                    store,
                    readiness,
                    arm,
                    observed_at="2026-07-29T23:18:00+00:00",
                    exchange=exchange,
                )
        self.assertEqual(result["status"], "halted_uncertain")
        self.assertIn("position_not_owned", " ".join(result["blockers"]))
        self.assertFalse(result["permissions"]["exchange_mutation_attempted"])
        self.assertEqual(exchange.created, [])
        self.assertEqual(exchange.canceled, [])

    def test_exact_interrupted_entry_and_stop_allow_one_bounded_flatten(self) -> None:
        batch = _parent_chain().batch
        readiness = _readiness_for_batch(batch)
        arm = build_fomc_live_arm(
            readiness,
            arm_token="t" * 48,
            armed_at="2026-07-29T23:17:00+00:00",
            confirmed_readiness_hash=str(readiness["readiness_hash"]),
        )
        scope = readiness["scope"]
        assert isinstance(scope, dict)
        quantity = float(scope["quantity"])
        owned_stop = {
            "id": "algo-1",
            "client_order_id": scope["stop_client_order_id"],
            "symbol": CCXT_SYMBOL,
            "type": "STOP_MARKET",
            "working_type": "MARK_PRICE",
            "side": "sell",
            "trigger_price": scope["stop_price"],
            "close_position": True,
            "status": "open",
        }
        preflight = _preflight(
            account_scope_hash=str(scope["account_scope_hash"]),
            positions=[
                {
                    "symbol": CCXT_SYMBOL,
                    "quantity": quantity,
                    "average_price": 100.0,
                    "notional_usdt": quantity * 100.0,
                }
            ],
            conditional=[owned_stop],
            verdict="blocked_fomc_live_account_preflight",
        )
        entry_response = {
            "id": "entry-1",
            "clientOrderId": scope["entry_client_order_id"],
            "symbol": "BTCUSDT",
            "side": "BUY",
            "status": "FILLED",
            "filled": quantity,
            "average": 100.0,
        }
        exchange = _MutationTrackingExchange()
        with tempfile.TemporaryDirectory() as directory:
            settings = _settings(directory)
            store = FomcLiveStore(directory, _event().event_id)
            store.write_attempt(_attempt(readiness, arm))
            state_store = SimpleNamespace(batches_root=Path(directory) / "batches")
            with (
                patch(
                    "qount.small_account.fomc_live.build_fomc_live_account_preflight",
                    return_value=preflight,
                ),
                patch(
                    "qount.small_account.fomc_live._fetch_order_by_client_id",
                    return_value=entry_response,
                ),
                patch(
                    "qount.small_account.fomc_live.read_decision_batch",
                    return_value=batch,
                ),
                patch(
                    "qount.small_account.fomc_live._record_recovered_entry_fill",
                    return_value=({}, (), "4" * 64),
                ),
                patch(
                    "qount.small_account.fomc_live._ledgered_flatten_position",
                    return_value=(
                        {"flat_readback_verified": True},
                        {"reconciliation": {"passed": True}},
                    ),
                ) as flatten,
            ):
                result = _recover_interrupted_fomc_attempt(
                    settings,
                    _event(),
                    store,
                    readiness,
                    arm,
                    observed_at="2026-07-29T23:18:00+00:00",
                    exchange=exchange,
                    state_store=state_store,
                )
        self.assertEqual(result["status"], "halted_interrupted_attempt_flat")
        self.assertTrue(result["permissions"]["exchange_mutation_attempted"])
        flatten.assert_called_once()
        self.assertEqual(flatten.call_args.kwargs["protective_stop"], owned_stop)

    def test_terminal_partial_entry_is_ledgered_and_exact_residual_is_flattened_once(self) -> None:
        batch = _parent_chain().batch
        entry = batch.plan.orders[0]
        readiness = _readiness_for_batch(batch)
        arm = build_fomc_live_arm(
            readiness,
            arm_token="t" * 48,
            armed_at="2026-07-29T23:17:00+00:00",
            confirmed_readiness_hash=str(readiness["readiness_hash"]),
        )
        scope = readiness["scope"]
        assert isinstance(scope, dict)
        partial_quantity = round(float(entry.quantity) / 2.0, 3)
        self.assertGreater(partial_quantity, 0.0)
        self.assertLess(partial_quantity, float(entry.quantity))
        preflight = _preflight(
            account_scope_hash=str(scope["account_scope_hash"]),
            positions=[
                {
                    "symbol": CCXT_SYMBOL,
                    "quantity": partial_quantity,
                    "average_price": 100.0,
                    "notional_usdt": partial_quantity * 100.0,
                }
            ],
            verdict="blocked_fomc_live_account_preflight",
        )
        exchange = _TerminalEntryExchange(
            client_order_id=entry.client_order_id,
            quantity=partial_quantity,
        )
        with tempfile.TemporaryDirectory() as directory:
            settings = _settings(directory)
            store = FomcLiveStore(directory, _event().event_id)
            store.write_attempt(_attempt(readiness, arm))
            ledger = store.ledger()
            _seed_interrupted_parent(ledger, batch)
            state_store = SimpleNamespace(batches_root=Path(directory) / "batches")
            with (
                patch(
                    "qount.small_account.fomc_live.build_fomc_live_account_preflight",
                    return_value=preflight,
                ),
                patch(
                    "qount.small_account.fomc_live._fetch_order_by_client_id",
                    return_value=exchange.order(),
                ),
                patch(
                    "qount.small_account.fomc_live.read_decision_batch",
                    return_value=batch,
                ),
                patch(
                    "qount.small_account.fomc_live._ledgered_flatten_position",
                    return_value=(
                        {"flat_readback_verified": True},
                        {"reconciliation": {"passed": True}},
                    ),
                ) as flatten,
            ):
                result = _recover_interrupted_fomc_attempt(
                    settings,
                    _event(),
                    store,
                    readiness,
                    arm,
                    observed_at="2026-07-29T23:18:00+00:00",
                    exchange=exchange,
                    state_store=state_store,
                )

            entry_state = ledger.get_order(entry.client_order_id)
            self.assertEqual(result["status"], "halted_interrupted_attempt_flat")
            self.assertEqual(entry_state["status"], "EXPIRED")
            self.assertAlmostEqual(entry_state["executed_quantity"], partial_quantity)
            self.assertAlmostEqual(
                ledger.position_quantities()[_event().instrument_key], partial_quantity
            )
            flatten.assert_called_once()
            self.assertAlmostEqual(flatten.call_args.kwargs["quantity"], partial_quantity)

    def test_non_usdt_entry_commission_does_not_prevent_owned_emergency_flatten(self) -> None:
        chain = _parent_chain()
        batch = chain.batch
        entry, stop_order = batch.plan.orders
        readiness = _readiness_for_batch(batch)
        arm = _build_arm(
            readiness,
            token="t" * 48,
            armed_at="2026-07-29T23:17:00+00:00",
        )
        scope = readiness["scope"]
        assert isinstance(scope, dict)
        quantity = float(entry.quantity)
        stop = {
            "id": "algo-1",
            "client_order_id": stop_order.client_order_id,
            "symbol": CCXT_SYMBOL,
            "type": "STOP_MARKET",
            "working_type": "MARK_PRICE",
            "side": "sell",
            "trigger_price": stop_order.stop_price,
            "close_position": True,
            "status": "open",
        }
        current_preflight = _preflight(
            created_at="2026-07-29T23:16:00+00:00",
            account_scope_hash=str(scope["account_scope_hash"]),
        )
        owned_position = {
            "symbol": CCXT_SYMBOL,
            "quantity": quantity,
            "average_price": 100.0,
            "notional_usdt": quantity * 100.0,
        }
        protected = _preflight(
            created_at="2026-07-29T23:16:03+00:00",
            account_scope_hash=str(scope["account_scope_hash"]),
            positions=[owned_position],
            conditional=[stop],
        )
        emergency = _preflight(
            created_at="2026-07-29T23:16:04+00:00",
            account_scope_hash=str(scope["account_scope_hash"]),
            positions=[owned_position],
            conditional=[stop],
        )
        exchange = _TerminalEntryExchange(
            client_order_id=entry.client_order_id,
            quantity=quantity,
            status="CLOSED",
            fee_asset="BNB",
        )

        def submit_entry(*args, **kwargs):
            marker = kwargs["mutation_marker"]
            marker["attempted"] = True
            return exchange.order(), {
                "checked_at": "2026-07-29T23:16:01+00:00",
                "arm_expires_at": arm["expires_at"],
                "entry_cutoff_at": _event().entry_cutoff_at,
                "quote_observed_at": "2026-07-29T23:16:00+00:00",
                "preflight_created_at": current_preflight["created_at"],
            }

        with tempfile.TemporaryDirectory() as directory:
            settings = _settings(directory)
            state_store = FomcStateStore(directory, _event().event_id)
            state_store.publish_batch(chain)
            live_store = FomcLiveStore(directory, _event().event_id)
            with (
                patch(
                    "qount.small_account.fomc_live._current_scope_blockers",
                    return_value=(),
                ),
                patch(
                    "qount.small_account.fomc_live._create_fomc_entry_order",
                    side_effect=submit_entry,
                ),
                patch(
                    "qount.small_account.fomc_live.build_fomc_live_account_preflight",
                    side_effect=[protected, emergency],
                ),
                patch(
                    "qount.small_account.fomc_live._fetch_order_by_client_id",
                    return_value=exchange.order(),
                ),
                patch(
                    "qount.small_account.fomc_live._ledgered_flatten_position",
                    return_value=(
                        {"flat_readback_verified": True},
                        {
                            "accounting_complete": False,
                            "unconverted_fill_fees": {"BNB": 0.01},
                        },
                    ),
                ) as flatten,
            ):
                result = dispatch_fomc_live_entry(
                    settings,
                    _event(),
                    state_store,
                    live_store,
                    readiness,
                    arm,
                    {"observed_at": "2026-07-29T23:16:00+00:00"},
                    current_preflight,
                    exchange=exchange,
                )

        self.assertEqual(
            result["status"], "halted_emergency_flattened", result
        )
        flatten.assert_called_once()
        self.assertAlmostEqual(flatten.call_args.kwargs["quantity"], quantity)
        self.assertEqual(flatten.call_args.kwargs["protective_stop"], stop)


class FomcLiveManagementTest(unittest.TestCase):
    def test_transient_management_read_failure_then_force_exit_flattens_once(self) -> None:
        chain = _parent_chain()
        batch = chain.batch
        scope = _scope_for_batch(batch)
        quantity = float(scope["quantity"])
        stop = {
            "id": "algo-1",
            "client_order_id": scope["stop_client_order_id"],
            "symbol": CCXT_SYMBOL,
            "type": "STOP_MARKET",
            "working_type": "MARK_PRICE",
            "side": "sell",
            "trigger_price": scope["stop_price"],
            "close_position": True,
            "status": "open",
        }
        exact_position = {
            "symbol": CCXT_SYMBOL,
            "quantity": quantity,
            "average_price": 100.0,
            "notional_usdt": quantity * 100.0,
        }
        uncertain = _preflight(
            account_scope_hash=ACCOUNT_SCOPE,
            positions=[exact_position],
            conditional=[stop],
            errors={"positions": "temporary timeout"},
            verdict="blocked_fomc_live_account_preflight",
        )
        force_exit = _preflight(
            created_at="2026-07-30T11:00:01+00:00",
            account_scope_hash=ACCOUNT_SCOPE,
            positions=[exact_position],
            conditional=[stop],
        )
        entry = batch.plan.orders[0]
        execution = _execution_artifact(
            _event(),
            {
                "readiness_hash": "1" * 64,
                "batch_id": batch.manifest.batch_id,
                "scope": scope,
            },
            {"arm_id": "2" * 64},
            observed_at="2026-07-29T23:18:00+00:00",
            status="protected",
            entry={
                "id": "entry-1",
                "client_order_id": entry.client_order_id,
                "symbol": "BTCUSDT",
                "side": "buy",
                "status": "closed",
                "filled": quantity,
                "average": 100.0,
            },
            protection=stop,
            exchange_mutation_attempted=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            settings = _settings(directory)
            state_store = FomcStateStore(directory, _event().event_id)
            state_store.publish_batch(chain)
            live_store = FomcLiveStore(directory, _event().event_id)
            _seed_open_parent(live_store.ledger(), batch, stop_acknowledged=True)
            live_store.write_execution(execution)
            exchange = _MutationTrackingExchange()
            with (
                patch(
                    "qount.small_account.fomc_live.build_fomc_live_account_preflight",
                    side_effect=[uncertain, force_exit],
                ),
                patch(
                    "qount.small_account.fomc_live._ledgered_flatten_position",
                    return_value=(
                        {"flat_readback_verified": True},
                        {"reconciliation": {"passed": True}},
                    ),
                ) as flatten,
            ):
                first = manage_fomc_live_position(
                    settings,
                    _event(),
                    live_store,
                    state_store=state_store,
                    observed_at="2026-07-29T23:20:00+00:00",
                    exchange=exchange,
                )
                second = manage_fomc_live_position(
                    settings,
                    _event(),
                    live_store,
                    state_store=state_store,
                    observed_at="2026-07-30T11:00:01+00:00",
                    exchange=exchange,
                )
        self.assertEqual(first["status"], "management_state_uncertain")
        self.assertEqual(second["status"], "force_exit_flattened")
        flatten.assert_called_once()

    def test_exact_owned_wrong_side_or_type_stop_triggers_bounded_flatten(self) -> None:
        for malformed_field, malformed_value in (
            ("side", "buy"),
            ("type", "LIMIT"),
        ):
            with self.subTest(malformed_field=malformed_field):
                chain = _parent_chain()
                batch = chain.batch
                scope = _scope_for_batch(batch)
                quantity = float(scope["quantity"])
                exact_stop = {
                    "id": "algo-1",
                    "client_order_id": scope["stop_client_order_id"],
                    "symbol": CCXT_SYMBOL,
                    "type": "STOP_MARKET",
                    "working_type": "MARK_PRICE",
                    "side": "sell",
                    "trigger_price": scope["stop_price"],
                    "close_position": True,
                    "status": "open",
                }
                malformed_stop = exact_stop | {malformed_field: malformed_value}
                current = _preflight(
                    account_scope_hash=ACCOUNT_SCOPE,
                    positions=[
                        {
                            "symbol": CCXT_SYMBOL,
                            "quantity": quantity,
                            "average_price": 100.0,
                            "notional_usdt": quantity * 100.0,
                        }
                    ],
                    conditional=[malformed_stop],
                    verdict="blocked_fomc_live_account_preflight",
                )
                with tempfile.TemporaryDirectory() as directory:
                    settings = _settings(directory)
                    state_store = FomcStateStore(directory, _event().event_id)
                    state_store.publish_batch(chain)
                    live_store = FomcLiveStore(directory, _event().event_id)
                    _seed_open_parent(
                        live_store.ledger(), batch, stop_acknowledged=True
                    )
                    live_store.write_execution(
                        _protected_execution(batch, scope, exact_stop)
                    )
                    with (
                        patch(
                            "qount.small_account.fomc_live.build_fomc_live_account_preflight",
                            return_value=current,
                        ),
                        patch(
                            "qount.small_account.fomc_live._ledgered_flatten_position",
                            return_value=(
                                {"flat_readback_verified": True},
                                {"reconciliation": {"passed": True}},
                            ),
                        ) as flatten,
                    ):
                        result = manage_fomc_live_position(
                            settings,
                            _event(),
                            live_store,
                            state_store=state_store,
                            observed_at="2026-07-29T23:20:00+00:00",
                            exchange=_MutationTrackingExchange(),
                        )
                self.assertNotEqual(result["status"], "protected")
                self.assertEqual(result["status"], "protection_failure_flattened")
                flatten.assert_called_once()
                self.assertEqual(
                    flatten.call_args.kwargs["protective_stop"], malformed_stop
                )

    def test_mismatched_stop_identity_is_never_accepted_or_mutated(self) -> None:
        chain = _parent_chain()
        batch = chain.batch
        scope = _scope_for_batch(batch)
        quantity = float(scope["quantity"])
        expected_stop = {
            "id": "algo-1",
            "client_order_id": scope["stop_client_order_id"],
            "symbol": CCXT_SYMBOL,
            "type": "STOP_MARKET",
            "working_type": "MARK_PRICE",
            "side": "sell",
            "trigger_price": scope["stop_price"],
            "close_position": True,
            "status": "open",
        }
        foreign_stop = expected_stop | {
            "id": "user-algo-1",
            "client_order_id": "user-stop-client-id",
        }
        current = _preflight(
            account_scope_hash=ACCOUNT_SCOPE,
            positions=[
                {
                    "symbol": CCXT_SYMBOL,
                    "quantity": quantity,
                    "average_price": 100.0,
                    "notional_usdt": quantity * 100.0,
                }
            ],
            conditional=[foreign_stop],
            verdict="blocked_fomc_live_account_preflight",
        )
        with tempfile.TemporaryDirectory() as directory:
            settings = _settings(directory)
            state_store = FomcStateStore(directory, _event().event_id)
            state_store.publish_batch(chain)
            live_store = FomcLiveStore(directory, _event().event_id)
            _seed_open_parent(live_store.ledger(), batch, stop_acknowledged=True)
            live_store.write_execution(
                _protected_execution(batch, scope, expected_stop)
            )
            exchange = _MutationTrackingExchange()
            with (
                patch(
                    "qount.small_account.fomc_live.build_fomc_live_account_preflight",
                    return_value=current,
                ),
                patch(
                    "qount.small_account.fomc_live._ledgered_flatten_position"
                ) as flatten,
            ):
                result = manage_fomc_live_position(
                    settings,
                    _event(),
                    live_store,
                    state_store=state_store,
                    observed_at="2026-07-29T23:20:00+00:00",
                    exchange=exchange,
                )
        self.assertEqual(result["status"], "halted_position_state_changed")
        flatten.assert_not_called()
        self.assertEqual(exchange.created, [])
        self.assertEqual(exchange.canceled, [])

    def test_management_force_exit_uses_trusted_clock_not_spoofed_observation(self) -> None:
        chain = _parent_chain()
        batch = chain.batch
        scope = _scope_for_batch(batch)
        quantity = float(scope["quantity"])
        stop = {
            "id": "algo-1",
            "client_order_id": scope["stop_client_order_id"],
            "symbol": CCXT_SYMBOL,
            "type": "STOP_MARKET",
            "working_type": "MARK_PRICE",
            "side": "sell",
            "trigger_price": scope["stop_price"],
            "close_position": True,
            "status": "open",
        }
        current = _preflight(
            account_scope_hash=ACCOUNT_SCOPE,
            positions=[
                {
                    "symbol": CCXT_SYMBOL,
                    "quantity": quantity,
                    "average_price": 100.0,
                    "notional_usdt": quantity * 100.0,
                }
            ],
            conditional=[stop],
        )
        with tempfile.TemporaryDirectory() as directory:
            settings = _settings(directory)
            state_store = FomcStateStore(directory, _event().event_id)
            state_store.publish_batch(chain)
            live_store = FomcLiveStore(directory, _event().event_id)
            _seed_open_parent(live_store.ledger(), batch, stop_acknowledged=True)
            live_store.write_execution(_protected_execution(batch, scope, stop))
            with (
                patch(
                    "qount.small_account.fomc_live.utc_now",
                    return_value=dt.datetime(2026, 7, 30, 11, 0, 1, tzinfo=UTC),
                ),
                patch(
                    "qount.small_account.fomc_live.build_fomc_live_account_preflight",
                    return_value=current,
                ),
                patch(
                    "qount.small_account.fomc_live._ledgered_flatten_position",
                    return_value=(
                        {"flat_readback_verified": True},
                        {"reconciliation": {"passed": True}},
                    ),
                ) as flatten,
            ):
                result = manage_fomc_live_position(
                    settings,
                    _event(),
                    live_store,
                    state_store=state_store,
                    observed_at="2026-07-29T23:20:00+00:00",
                    exchange=_MutationTrackingExchange(),
                )
        self.assertEqual(result["status"], "force_exit_flattened")
        flatten.assert_called_once()
        self.assertEqual(flatten.call_args.kwargs["purpose"], "force-exit")

    def test_unknown_reduce_retry_reuses_identity_and_never_resubmits(self) -> None:
        batch = _parent_chain().batch
        quantity = float(batch.plan.orders[0].quantity)
        with tempfile.TemporaryDirectory() as directory:
            settings = _settings(directory)
            store = FomcLiveStore(directory, _event().event_id)
            ledger = store.ledger()
            ledger.record_verified_batch(batch, recorded_at=batch.manifest.created_at)
            with patch(
                "qount.small_account.fomc_live._flatten_position",
                side_effect=TimeoutError("unknown submit outcome"),
            ) as submit:
                with self.assertRaises(TimeoutError):
                    _ledgered_flatten_position(
                        settings,
                        _event(),
                        store,
                        batch,
                        exchange=object(),
                        ccxt_symbol=CCXT_SYMBOL,
                        quantity=quantity,
                        position_side="long",
                        purpose="force-exit",
                        protective_stop=None,
                        started_at="2026-07-30T11:00:01+00:00",
                    )
                first_attempts = store.list_reduction_attempts()
                with (
                    patch(
                        "qount.small_account.fomc_live._fetch_order_by_client_id",
                        side_effect=TimeoutError("still unknown"),
                    ),
                    self.assertRaises(TimeoutError),
                ):
                    _ledgered_flatten_position(
                        settings,
                        _event(),
                        store,
                        batch,
                        exchange=object(),
                        ccxt_symbol=CCXT_SYMBOL,
                        quantity=quantity,
                        position_side="long",
                        purpose="force-exit",
                        protective_stop=None,
                        started_at="2026-07-30T11:00:05+00:00",
                    )
                second_attempts = store.list_reduction_attempts()
            self.assertEqual(first_attempts, second_attempts)
            self.assertEqual(len(second_attempts), 1)
            client_id = str(second_attempts[0]["client_order_id"])
            self.assertEqual(ledger.get_order(client_id)["status"], "UNKNOWN")
            submit.assert_called_once()

    def test_terminal_partial_reduction_records_residual_and_never_resubmits(self) -> None:
        batch = _parent_chain().batch
        quantity = float(batch.plan.orders[0].quantity)
        partial_quantity = round(quantity / 2.0, 3)
        residual_quantity = quantity - partial_quantity
        exchange = _TerminalReductionExchange(quantity=partial_quantity)
        residual = _preflight(
            created_at="2026-07-30T11:00:03+00:00",
            positions=[
                {
                    "symbol": CCXT_SYMBOL,
                    "quantity": residual_quantity,
                    "average_price": 100.0,
                    "notional_usdt": residual_quantity * 100.0,
                }
            ],
            verdict="blocked_fomc_live_account_preflight",
        )
        with tempfile.TemporaryDirectory() as directory:
            settings = _settings(directory)
            store = FomcLiveStore(directory, _event().event_id)
            ledger = store.ledger()
            _seed_open_parent(ledger, batch)
            with patch(
                "qount.small_account.fomc_live._flatten_position",
                side_effect=TimeoutError("unknown submit outcome"),
            ) as submit:
                with self.assertRaises(TimeoutError):
                    _ledgered_flatten_position(
                        settings,
                        _event(),
                        store,
                        batch,
                        exchange=exchange,
                        ccxt_symbol=CCXT_SYMBOL,
                        quantity=quantity,
                        position_side="long",
                        purpose="force-exit",
                        protective_stop=None,
                        started_at="2026-07-30T11:00:01+00:00",
                    )
                attempt = store.list_reduction_attempts()[0]
                client_id = str(attempt["client_order_id"])
                with (
                    patch(
                        "qount.small_account.fomc_live._fetch_order_by_client_id",
                        side_effect=lambda *args, **kwargs: exchange.response(
                            str(kwargs["client_order_id"])
                        ),
                    ) as query,
                    patch(
                        "qount.small_account.fomc_live.build_fomc_live_account_preflight",
                        return_value=residual,
                    ),
                    self.assertRaises(FomcLiveError) as terminal,
                ):
                    _ledgered_flatten_position(
                        settings,
                        _event(),
                        store,
                        batch,
                        exchange=exchange,
                        ccxt_symbol=CCXT_SYMBOL,
                        quantity=quantity,
                        position_side="long",
                        purpose="force-exit",
                        protective_stop=None,
                        started_at="2026-07-30T11:00:04+00:00",
                    )
                query.assert_called_once()

                with self.assertRaises(FomcLiveError):
                    _ledgered_flatten_position(
                        settings,
                        _event(),
                        store,
                        batch,
                        exchange=exchange,
                        ccxt_symbol=CCXT_SYMBOL,
                        quantity=quantity,
                        position_side="long",
                        purpose="force-exit",
                        protective_stop=None,
                        started_at="2026-07-30T11:00:05+00:00",
                    )

            reduction_state = ledger.get_order(client_id)
            self.assertIn("residual", str(terminal.exception).lower())
            self.assertEqual(reduction_state["status"], "EXPIRED")
            self.assertAlmostEqual(
                reduction_state["executed_quantity"], partial_quantity
            )
            self.assertAlmostEqual(
                ledger.position_quantities()[_event().instrument_key], residual_quantity
            )
            self.assertEqual(store.list_reduction_attempts(), (attempt,))
            self.assertEqual(exchange.queried_client_ids, [client_id])
            submit.assert_called_once()


class FomcLiveLedgerTest(unittest.TestCase):
    def test_flat_non_usdt_fee_stays_unconverted_and_blocks_risk_increase(self) -> None:
        batch = _parent_chain().batch
        quantity = float(batch.plan.orders[0].quantity)
        exchange = _ExitExchange(quantity)
        post = _preflight(
            created_at="2026-07-29T23:16:05+00:00",
            equity=199.95,
        )
        with tempfile.TemporaryDirectory() as directory:
            settings = _settings(directory)
            store = FomcLiveStore(directory, _event().event_id)
            ledger = store.ledger()
            _seed_open_parent(
                ledger,
                batch,
                entry_fee=0.01,
                entry_fee_asset="BNB",
            )
            with patch(
                "qount.small_account.fomc_live.build_fomc_live_account_preflight",
                return_value=post,
            ):
                flattened, ledger_state = _ledgered_flatten_position(
                    settings,
                    _event(),
                    store,
                    batch,
                    exchange=exchange,
                    ccxt_symbol=CCXT_SYMBOL,
                    quantity=quantity,
                    position_side="long",
                    purpose="force-exit",
                    protective_stop=None,
                    started_at="2026-07-29T23:16:03+00:00",
                )

            self.assertTrue(flattened["flat_readback_verified"])
            self.assertFalse(ledger_state["accounting_complete"])
            self.assertEqual(ledger_state["unconverted_fill_fees"], {"BNB": 0.01})
            self.assertAlmostEqual(ledger_state["recorded_fill_fees_usdt"], 0.04)
            self.assertFalse(ledger_state["reconciliation"]["passed"])
            self.assertFalse(ledger.risk_increase_allowed())

    def test_reduce_only_exit_records_fill_fees_flat_nav_and_reconciliation(self) -> None:
        batch = _parent_chain().batch
        quantity = float(batch.plan.orders[0].quantity)
        exchange = _ExitExchange(quantity)
        post = _preflight(
            created_at="2026-07-29T23:16:05+00:00",
            equity=199.92,
        )
        with tempfile.TemporaryDirectory() as directory:
            settings = _settings(directory)
            store = FomcLiveStore(directory, _event().event_id)
            ledger = store.ledger()
            _seed_open_parent(ledger, batch)
            with patch(
                "qount.small_account.fomc_live.build_fomc_live_account_preflight",
                return_value=post,
            ):
                flattened, ledger_state = _ledgered_flatten_position(
                    settings,
                    _event(),
                    store,
                    batch,
                    exchange=exchange,
                    ccxt_symbol=CCXT_SYMBOL,
                    quantity=quantity,
                    position_side="long",
                    purpose="force-exit",
                    protective_stop=None,
                    started_at="2026-07-29T23:16:03+00:00",
                )

            attempt = store.list_reduction_attempts()[0]
            reduction_order = ledger.get_order(str(attempt["client_order_id"]))
            nav = ledger.latest_nav_mark()
            self.assertTrue(flattened["flat_readback_verified"])
            self.assertEqual(reduction_order["status"], "FILLED")
            self.assertTrue(bool(reduction_order["reduce_only"]))
            self.assertEqual(ledger.position_quantities()[_event().instrument_key], 0.0)
            self.assertAlmostEqual(ledger_state["recorded_fill_fees_usdt"], 0.08)
            self.assertTrue(ledger_state["reconciliation"]["passed"])
            self.assertIsNotNone(nav)
            self.assertAlmostEqual(nav.fees_cumulative, 0.08)
            self.assertTrue(ledger.risk_increase_allowed())

    def test_native_algo_stop_is_queried_ledgered_and_includes_all_open_nav_fees(self) -> None:
        batch = _parent_chain().batch
        entry, stop = batch.plan.orders
        quantity = float(entry.quantity)
        exchange = _AlgoStopExchange(stop.client_order_id, quantity)
        post = _preflight(
            created_at="2026-07-29T23:16:05+00:00",
            equity=198.791,
        )
        with tempfile.TemporaryDirectory() as directory:
            settings = _settings(directory)
            store = FomcLiveStore(directory, _event().event_id)
            ledger = store.ledger()
            _seed_open_parent(ledger, batch, stop_acknowledged=True)
            with patch(
                "qount.small_account.fomc_live.build_fomc_live_account_preflight",
                return_value=post,
            ):
                result = _ledger_native_stop_flatten(
                    settings,
                    _event(),
                    ledger,
                    batch,
                    exchange=exchange,
                    ccxt_symbol=CCXT_SYMBOL,
                    stop_client_order_id=stop.client_order_id,
                    signed_quantity=quantity,
                    observed_at="2026-07-29T23:16:05+00:00",
                )

            self.assertEqual(
                exchange.algo_requests,
                [{"symbol": "BTCUSDT", "clientAlgoId": stop.client_order_id}],
            )
            self.assertEqual(ledger.get_order(stop.client_order_id)["status"], "FILLED")
            self.assertEqual(ledger.position_quantities()[_event().instrument_key], 0.0)
            self.assertAlmostEqual(
                result["ledger_state"]["recorded_fill_fees_usdt"], 0.08
            )
            self.assertTrue(result["ledger_state"]["reconciliation"]["passed"])
            self.assertAlmostEqual(ledger.latest_nav_mark().fees_cumulative, 0.08)
            self.assertTrue(ledger.risk_increase_allowed())


if __name__ == "__main__":
    unittest.main()
