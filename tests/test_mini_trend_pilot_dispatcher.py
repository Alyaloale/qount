from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from qount.mini_trend.forward import TOP3
from qount.mini_trend.futures_recovery import canonical_hash, selected_um_rules
from qount.mini_trend.live_pilot import (
    LIVE_PILOT_CONTRACT,
    LivePilotEvidence,
    LivePilotRequest,
    build_live_pilot_readiness,
)
from qount.mini_trend.pilot_dispatcher import (
    PILOT_DISPATCH_SNAPSHOT_VERSION,
    PILOT_MANUAL_ARM_VERSION,
    _adverse_slippage_bps,
    _record_dispatch_cash_events,
    build_manual_arm,
    build_pilot_dispatch_plan,
    dry_dispatch_evidence,
    fetch_pilot_dispatch_snapshot,
    run_pilot_dispatch,
    verify_dispatch_journal,
)
from qount.models import utc_now
from qount.settings import Settings


def _rules() -> dict:
    steps = {"BTCUSDT": "0.001", "ETHUSDT": "0.001", "BNBUSDT": "0.01"}
    ticks = {"BTCUSDT": "0.1", "ETHUSDT": "0.01", "BNBUSDT": "0.01"}
    return {
        "market": "um",
        "source_type": "runtime_exchange_info",
        "rules": [
            {
                "symbol": symbol,
                "status": "TRADING",
                "min_qty": steps[symbol],
                "step_size": steps[symbol],
                "market_step_size": steps[symbol],
                "tick_size": ticks[symbol],
                "min_notional": "5",
            }
            for symbol in TOP3
        ],
    }


def _preflight() -> dict:
    return {
        "created_at": utc_now().isoformat(),
        "artifact_type": "mini_trend_um_pilot_account_preflight",
        "contract_hash": LIVE_PILOT_CONTRACT.contract_hash,
        "meta": {
            "read_only": True,
            "private_api_order_attempted": False,
            "mutating_account_method_attempted": False,
            "live_orders_allowed": False,
        },
        "evidence": {
            "configured_exchange_route_ok": True,
            "public_api_ok": True,
            "credentials_ok": True,
            "api_key_reading_enabled": True,
            "api_key_withdrawal_disabled": True,
            "api_key_futures_enabled": True,
            "api_key_ip_restricted": True,
            "account_balance_audit_complete": True,
            "position_mode_oneway": True,
            "position_audit_complete": True,
            "unmanaged_position_count": 0,
            "open_order_audit_complete": True,
            "isolated_one_x_verified": True,
        },
    }


def _readiness(*, preflight_hash: str = "p") -> dict:
    evidence = LivePilotEvidence(
        forward_pairs=60,
        forward_active_bars=10,
        paper_days=30,
        dry_run_days=7,
        independent_runtime_verified=True,
        complete_funding_journal=True,
        configured_exchange_route_ok=True,
        public_api_ok=True,
        credentials_ok=True,
        api_key_reading_enabled=True,
        api_key_withdrawal_disabled=True,
        api_key_futures_enabled=True,
        api_key_ip_restricted=True,
        account_balance_audit_complete=True,
        available_balance_usdt=300.0,
        position_mode_oneway=True,
        position_audit_complete=True,
        unmanaged_position_count=0,
        account_flat=True,
        open_order_audit_complete=True,
        open_order_count=0,
        isolated_one_x_verified=True,
        legacy_production_cron_disabled=True,
        legacy_live_guard_disarmed=True,
        rollback_documented=True,
        standard_authority_verified=True,
        authority_batch_id="a" * 64,
        runtime_ledger_snapshot_hash="b" * 64,
        pre_dispatch_reconciliation_hash="c" * 64,
        pre_dispatch_reconciliation_passed=True,
        notification_snapshot_hash="d" * 64,
        daily_brief_hash="e" * 64,
        system_health_snapshot_hash="f" * 64,
        system_health_ready=True,
        release_provenance_verified=True,
        release_git_commit="1" * 40,
        release_version="0.2.1",
        release_source_tree_hash="2" * 64,
        release_provenance_hash="3" * 64,
    )
    payload = build_live_pilot_readiness(
        LivePilotRequest(
            owner_requested_one_month_live=True,
            capital_usdt=100.0,
            start_date="2026-08-01",
        ),
        evidence,
    )
    payload["runtime_sources"] = {"preflight": {"sha256": preflight_hash}}
    payload["created_at"] = utc_now().isoformat()
    return payload


def _projection(rules: dict) -> dict:
    _, rules_hash = selected_um_rules(rules)
    state = {
        "target_weights": {symbol: 0.2 for symbol in TOP3},
        "trail_high": {"BTCUSDT": 11_000.0, "ETHUSDT": 2_200.0, "BNBUSDT": 330.0},
    }
    core = {
        "decision_date": "2026-08-01",
        "decision_available_after": "2026-08-02T00:00:00+00:00",
        "strategy": LIVE_PILOT_CONTRACT.strategy,
        "pre_decision_equity_usdt": 100.0,
        "prices": {"BTCUSDT": 10_000.0, "ETHUSDT": 2_000.0, "BNBUSDT": 300.0},
        "previous_weights": {symbol: 0.0 for symbol in TOP3},
        "desired_weights": {symbol: 0.2 for symbol in TOP3},
        "protective_stop_prices": {
            "BTCUSDT": 9_000.0,
            "ETHUSDT": 1_800.0,
            "BNBUSDT": 270.0,
        },
        "projected_order_intent_count": 3,
        "risk_stage": "fixed",
        "execution_state": state,
        "execution_state_hash": canonical_hash(state),
        "data_hash": "d" * 64,
        "exchange_rules_hash": rules_hash,
    }
    decision = core | {
        "decision_id": canonical_hash(
            {
                "live_pilot_contract_hash": LIVE_PILOT_CONTRACT.contract_hash,
                "decision": core,
            }
        )
    }
    return {
        "created_at": utc_now().isoformat(),
        "artifact_type": "mini_trend_um_pilot_latest_projection",
        "meta": {
            "orders_allowed": False,
            "private_api_order_attempted": False,
            "live_orders_allowed": False,
        },
        "contract": {
            "live_pilot_contract_hash": LIVE_PILOT_CONTRACT.contract_hash,
            "capital_usdt": 100.0,
        },
        "decision": decision,
    }


def _snapshot() -> dict:
    prices = {"BTCUSDT": 10_000.0, "ETHUSDT": 2_000.0, "BNBUSDT": 300.0}
    payload = {
        "created_at": utc_now().isoformat(),
        "schema_version": PILOT_DISPATCH_SNAPSHOT_VERSION,
        "artifact_type": "mini_trend_um_dispatch_account_snapshot",
        "contract_hash": LIVE_PILOT_CONTRACT.contract_hash,
        "meta": {
            "read_only": True,
            "private_api_order_attempted": False,
            "mutating_account_method_attempted": False,
            "live_orders_allowed": False,
        },
        "balance": {"margin_balance": 300.0, "quote_free": 300.0},
        "prices": prices,
        "positions": [],
        "regular_open_orders": [],
        "conditional_open_orders": [],
        "resolved_symbols": {
            "BTCUSDT": "BTC/USDT:USDT",
            "ETHUSDT": "ETH/USDT:USDT",
            "BNBUSDT": "BNB/USDT:USDT",
        },
        "position_mode": {"hedged": False},
        "diagnostics": {"verdict": "account_snapshot_pass"},
    }
    payload["snapshot_hash"] = canonical_hash(
        {
            "contract_hash": payload["contract_hash"],
            "balance": payload["balance"],
            "prices": payload["prices"],
            "positions": payload["positions"],
            "regular_open_orders": payload["regular_open_orders"],
            "conditional_open_orders": payload["conditional_open_orders"],
            "position_mode": payload["position_mode"],
            "resolved_symbols": payload["resolved_symbols"],
        }
    )
    return payload


def _plan(*, mode: str = "dry", switch: bool = False) -> dict:
    rules = _rules()
    readiness = _readiness()
    token = "test-arm-token"
    arm = {
        "schema_version": PILOT_MANUAL_ARM_VERSION,
        "status": "armed",
        "arm_id": "arm-test",
        "contract_hash": LIVE_PILOT_CONTRACT.contract_hash,
        "readiness_hash": readiness["readiness_hash"],
        "readiness_artifact_sha256": "r",
        "arm_token_sha256": hashlib.sha256(token.encode()).hexdigest(),
        "capital_usdt": 100.0,
        "start_date": "2026-08-01",
        "end_date_exclusive": "2026-08-31",
    }
    rules["created_at"] = utc_now().isoformat()
    return build_pilot_dispatch_plan(
        _preflight(),
        _projection(rules),
        readiness,
        rules,
        _snapshot(),
        mode=mode,
        source_hashes={
            "preflight": "p",
            "projection": "x",
            "readiness": "r",
            "exchange_rules": "e",
        },
        arm=arm,
        arm_token=token,
        live_switch_enabled=switch,
        live_confirmation="arm-test" if switch else None,
    )


class MiniTrendPilotDispatcherTest(unittest.TestCase):
    def test_dispatch_cash_events_preserve_binance_income_signs(self) -> None:
        class Exchange:
            def fetch_ledger(self, currency, since, limit):
                self.query = (currency, since, limit)
                return [
                    {
                        "id": "funding-1",
                        "amount": 0.2,
                        "direction": "out",
                        "currency": "USDT",
                        "datetime": "2026-08-02T00:00:10+00:00",
                        "info": {
                            "incomeType": "FUNDING_FEE",
                            "income": "-0.2",
                            "asset": "USDT",
                            "symbol": "BTCUSDT",
                        },
                    },
                    {
                        "id": "transfer-1",
                        "amount": 3.0,
                        "direction": "out",
                        "currency": "USDT",
                        "datetime": "2026-08-02T00:00:11+00:00",
                        "info": {
                            "incomeType": "TRANSFER",
                            "income": "-3.0",
                            "asset": "USDT",
                        },
                    },
                    {
                        "id": "commission-1",
                        "amount": 0.01,
                        "direction": "out",
                        "currency": "USDT",
                        "datetime": "2026-08-02T00:00:12+00:00",
                        "info": {
                            "incomeType": "COMMISSION",
                            "income": "-0.01",
                            "asset": "USDT",
                        },
                    },
                    {
                        "id": "pnl-1",
                        "amount": 1.5,
                        "direction": "in",
                        "currency": "USDT",
                        "datetime": "2026-08-02T00:00:13+00:00",
                        "info": {
                            "incomeType": "REALIZED_PNL",
                            "income": "1.5",
                            "asset": "USDT",
                        },
                    },
                ]

        with tempfile.TemporaryDirectory():
            ledger = mock.Mock()
            evidence = _record_dispatch_cash_events(
                Exchange(),
                ledger,
                after="2026-08-02T00:00:00+00:00",
                through="2026-08-02T00:01:00+00:00",
                fill_fees_usdt=0.01,
            )

        self.assertEqual(evidence["funding_usdt"], -0.2)
        self.assertEqual(evidence["transfer_usdt"], -3.0)
        self.assertEqual(evidence["commission_usdt"], 0.01)
        self.assertEqual(ledger.record_cash_event.call_count, 2)
        self.assertEqual(
            [call.kwargs["amount"] for call in ledger.record_cash_event.call_args_list],
            [-0.2, -3.0],
        )

    def test_dispatch_cash_events_fail_closed_on_unknown_binance_income_type(self) -> None:
        class Exchange:
            def fetch_ledger(self, currency, since, limit):
                return [
                    {
                        "id": "mystery-1",
                        "amount": 1.0,
                        "direction": "in",
                        "currency": "USDT",
                        "datetime": "2026-08-02T00:00:10+00:00",
                        "info": {
                            "incomeType": "WELCOME_BONUS",
                            "income": "1.0",
                            "asset": "USDT",
                        },
                    }
                ]

        with tempfile.TemporaryDirectory(), self.assertRaisesRegex(
            ValueError,
            "account_ledger_event_unclassified:WELCOME_BONUS",
        ):
            _record_dispatch_cash_events(
                Exchange(),
                mock.Mock(),
                after="2026-08-02T00:00:00+00:00",
                through="2026-08-02T00:01:00+00:00",
                fill_fees_usdt=0.0,
            )

    def test_manual_arm_requires_ready_and_exact_hash_confirmation(self) -> None:
        readiness = _readiness()
        arm = build_manual_arm(
            readiness,
            readiness_artifact_sha256="a" * 64,
            confirmed_readiness_hash=readiness["readiness_hash"],
            arm_token="a-long-manual-arm-token",
        )
        self.assertEqual(arm["status"], "armed")
        self.assertEqual(arm["capital_usdt"], 100.0)
        self.assertNotIn("a-long-manual-arm-token", str(arm))
        with self.assertRaisesRegex(ValueError, "does not match"):
            build_manual_arm(
                readiness,
                readiness_artifact_sha256="a" * 64,
                confirmed_readiness_hash="wrong",
                arm_token="a-long-manual-arm-token",
            )

    def test_snapshot_reads_regular_and_conditional_books_without_mutation(self) -> None:
        class Exchange:
            def __init__(self):
                self.options = {}
                self.mutations = []

            def load_time_difference(self):
                return 0

            def load_markets(self):
                return {
                    f"{symbol[:-4]}/USDT:USDT": {
                        "symbol": f"{symbol[:-4]}/USDT:USDT",
                        "base": symbol[:-4],
                        "quote": "USDT",
                        "settle": "USDT",
                        "contract": True,
                        "linear": True,
                        "swap": True,
                    }
                    for symbol in TOP3
                }

            def fetch_balance(self):
                return {
                    "free": {"USDT": 300.0},
                    "used": {"USDT": 0.0},
                    "total": {"USDT": 300.0},
                    "info": {
                        "assets": [
                            {
                                "asset": "USDT",
                                "walletBalance": "300",
                                "marginBalance": "300",
                                "availableBalance": "300",
                            }
                        ]
                    },
                }

            def fetch_position_mode(self, params=None):
                return {"hedged": False}

            def fetch_ticker(self, symbol):
                return {"last": 100.0}

            def fetch_positions(self):
                return []

            def fetch_open_orders(self, symbol=None, params=None):
                if symbol is None:
                    self.all_order_warning_ack = (
                        self.options.get("warnOnFetchOpenOrdersWithoutSymbol") is False
                    )
                return []

            def create_order(self, *args, **kwargs):
                self.mutations.append("create_order")

        with mock.patch.dict(
            "os.environ",
            {
                "QOUNT_MARKET_TYPE": "future",
                "QOUNT_BINANCE_API_KEY": "test-key",
                "QOUNT_BINANCE_API_SECRET": "test-secret",
            },
        ):
            settings = Settings.from_env()
        exchange = Exchange()
        snapshot = fetch_pilot_dispatch_snapshot(settings, exchange=exchange)
        self.assertEqual(snapshot["diagnostics"]["verdict"], "account_snapshot_pass")
        self.assertTrue(exchange.all_order_warning_ack)
        self.assertEqual(exchange.mutations, [])
        self.assertFalse(snapshot["meta"]["private_api_order_attempted"])

    def test_dry_plan_uses_current_book_and_plans_native_stops(self) -> None:
        plan = _plan()
        self.assertEqual(plan["diagnostics"]["verdict"], "dry_dispatch_ready")
        self.assertEqual(len(plan["market_orders"]), 3)
        self.assertEqual(len(plan["stop_orders"]), 3)
        self.assertTrue(all(row["close_position"] for row in plan["stop_orders"]))
        self.assertTrue(all(row["client_order_id"].startswith("qmt-") for row in plan["market_orders"]))
        self.assertFalse(plan["meta"]["live_orders_allowed"])

    def test_unmanaged_order_and_tampered_decision_fail_closed(self) -> None:
        rules = _rules()
        snapshot = _snapshot()
        snapshot["regular_open_orders"] = [{"id": "unmanaged"}]
        projection = _projection(rules)
        projection["decision"]["desired_weights"]["BTCUSDT"] = 0.3
        report = build_pilot_dispatch_plan(
            _preflight(),
            projection,
            _readiness(),
            rules,
            snapshot,
            source_hashes={"preflight": "p"},
        )
        self.assertEqual(report["diagnostics"]["verdict"], "blocked_dispatch")
        self.assertIn("unresolved_regular_open_orders", report["diagnostics"]["blockers"])
        self.assertIn("decision_id_invalid", report["diagnostics"]["blockers"])

    def test_live_requires_independent_switch_and_manual_arm(self) -> None:
        blocked = _plan(mode="live", switch=False)
        ready = _plan(mode="live", switch=True)
        self.assertIn(
            "manual_arm_or_live_switch_invalid", blocked["diagnostics"]["blockers"]
        )
        self.assertEqual(ready["diagnostics"]["verdict"], "blocked_dispatch")
        self.assertIn(
            "standard_live_execution_authority_missing",
            ready["diagnostics"]["blockers"],
        )
        self.assertFalse(ready["meta"]["live_orders_allowed"])

    def test_live_rejects_stale_source_artifacts(self) -> None:
        rules = _rules()
        readiness = _readiness()
        projection = _projection(rules)
        projection["created_at"] = "2020-01-01T00:00:00+00:00"
        rules["created_at"] = utc_now().isoformat()
        report = build_pilot_dispatch_plan(
            _preflight(),
            projection,
            readiness,
            rules,
            _snapshot(),
            mode="live",
            source_hashes={
                "preflight": "p",
                "projection": "x",
                "readiness": "r",
                "exchange_rules": "e",
            },
        )
        self.assertIn(
            "live_source_stale:projection", report["diagnostics"]["blockers"]
        )

    def test_daily_loss_flattens_the_next_dispatch(self) -> None:
        rules = _rules()
        snapshot = _snapshot()
        snapshot["balance"]["margin_balance"] = 294.0
        snapshot["snapshot_hash"] = canonical_hash(
            {
                "contract_hash": snapshot["contract_hash"],
                "balance": snapshot["balance"],
                "prices": snapshot["prices"],
                "positions": snapshot["positions"],
                "regular_open_orders": snapshot["regular_open_orders"],
                "conditional_open_orders": snapshot["conditional_open_orders"],
                "position_mode": snapshot["position_mode"],
                "resolved_symbols": snapshot["resolved_symbols"],
            }
        )
        report = build_pilot_dispatch_plan(
            _preflight(),
            _projection(rules),
            _readiness(),
            rules,
            snapshot,
            source_hashes={
                "preflight": "p",
                "projection": "x",
                "readiness": "r",
                "exchange_rules": "e",
            },
            journal_summary={
                "peak_margin_balance_usdt": 300.0,
                "latest_margin_balance_usdt": 300.0,
                "daily_opening_margin_balance_usdt": {
                    utc_now().date().isoformat(): 300.0
                },
            },
        )
        self.assertTrue(report["halt_after_dispatch"])
        self.assertEqual(report["halt_reason"], "pilot_daily_loss_halt")
        self.assertTrue(
            all(value == 0.0 for value in report["desired_weights"].values())
        )

    def test_adverse_slippage_respects_side(self) -> None:
        self.assertAlmostEqual(
            _adverse_slippage_bps(
                side="buy", reference_price=100.0, average_fill_price=100.25
            ),
            25.0,
        )
        self.assertAlmostEqual(
            _adverse_slippage_bps(
                side="sell", reference_price=100.0, average_fill_price=99.75
            ),
            25.0,
        )

    def test_dry_journal_counts_unique_valid_dates_and_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dispatcher.jsonl"
            first = run_pilot_dispatch(None, _plan(), path)
            duplicate = run_pilot_dispatch(None, _plan(), path)
            evidence = dry_dispatch_evidence(path)
            raw = path.read_text(encoding="utf-8").replace('"status":"valid"', '"status":"bad"')
            path.write_text(raw, encoding="utf-8")
            tampered = dry_dispatch_evidence(path)
        self.assertEqual(first["status"], "dry_validated")
        self.assertEqual(duplicate["status"], "duplicate_dry_noop")
        self.assertEqual(evidence["dry_run_days"], 1)
        self.assertEqual(tampered["dry_run_schema_error_count"], 1)

    def test_live_execution_uses_close_position_stop_and_reconciles(self) -> None:
        plan = _plan(mode="live", switch=True)
        self.assertEqual(plan["diagnostics"]["verdict"], "blocked_dispatch")
        post = _snapshot()
        post["positions"] = [
            {
                "data_symbol": order["symbol"],
                "symbol": order["ccxt_symbol"],
                "side": "long",
                "contracts": order["quantity"],
            }
            for order in plan["market_orders"]
        ]
        post["conditional_open_orders"] = [
            {
                "data_symbol": order["symbol"],
                "symbol": order["ccxt_symbol"],
                "side": "sell",
                "client_order_id": order["client_order_id"],
                "close_position": True,
                "reduce_only": False,
            }
            for order in plan["stop_orders"]
        ]
        post["snapshot_hash"] = canonical_hash(
            {
                "contract_hash": post["contract_hash"],
                "balance": post["balance"],
                "prices": post["prices"],
                "positions": post["positions"],
                "regular_open_orders": post["regular_open_orders"],
                "conditional_open_orders": post["conditional_open_orders"],
                "position_mode": post["position_mode"],
                "resolved_symbols": post["resolved_symbols"],
            }
        )

        class Exchange:
            def __init__(self):
                self.calls = []

            def create_order(self, symbol, type_, side, amount, price, params):
                self.calls.append((symbol, type_, side, amount, price, params))
                return {"id": str(len(self.calls)), "symbol": symbol, "type": type_, "side": side}

            def cancel_order(self, *args, **kwargs):
                self.calls.append(("cancel", args, kwargs))

        exchange = Exchange()
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "qount.mini_trend.pilot_dispatcher.fetch_pilot_dispatch_snapshot",
            return_value=post,
        ):
            result = run_pilot_dispatch(
                mock.Mock(),
                plan,
                Path(tmp) / "dispatcher.jsonl",
                exchange=exchange,
            )
            summary = verify_dispatch_journal(Path(tmp) / "dispatcher.jsonl")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(exchange.calls, [])
        self.assertEqual(summary["executed_decision_ids"], [])


if __name__ == "__main__":
    unittest.main()
