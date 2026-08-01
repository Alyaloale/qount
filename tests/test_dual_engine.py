from __future__ import annotations

from dataclasses import replace
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlparse

from qount.contracts import canonical_hash
from qount.dual_engine import C60_SYMBOLS
from qount.dual_engine import DualEngineContractError
from qount.dual_engine import DualEnginePaperContract
from qount.dual_engine import DualEngineMarketConfig
from qount.dual_engine import NoScheduledPaperEvent
from qount.dual_engine import G20_EXECUTION_TO_PROXY
from qount.dual_engine import PAPER_PORTFOLIO_IDS
from qount.dual_engine import PaperCycleInput
from qount.dual_engine import build_c60_decision
from qount.dual_engine import build_g20_decision
from qount.dual_engine import collect_market_cycle
from qount.dual_engine import d15_c60_budget
from qount.dual_engine import read_paper_snapshot
from qount.dual_engine import run_paper_cycle


def _series(start: float, daily: float, count: int = 100) -> tuple[float, ...]:
    return tuple(start + daily * index for index in range(count))


def _proxy_history(selected: str) -> dict[str, tuple[float, ...]]:
    return {
        proxy: _series(100.0, 1.0 if execution == selected else -0.05)
        for execution, proxy in G20_EXECUTION_TO_PROXY.items()
    }


def _crypto_history(*, btc_up: bool = True) -> dict[str, tuple[float, ...]]:
    values = {symbol: _series(100.0, -0.02) for symbol in C60_SYMBOLS}
    values["BTCUSDT"] = _series(100.0, 0.30 if btc_up else -0.20)
    values["PAXGUSDT"] = _series(100.0, 0.50)
    values["ETHUSDT"] = _series(100.0, 0.40)
    return values


def _cycle(
    day: int,
    *,
    selected: str = "TQQQ",
    signal: bool = False,
    rebalance: bool = False,
    marks: dict[str, float] | None = None,
) -> PaperCycleInput:
    prices = {
        symbol: 100.0
        for symbol in (*G20_EXECUTION_TO_PROXY, "BIL", *C60_SYMBOLS)
    }
    prices.update(marks or {})
    rules = {
        symbol: {
            "step_size": 1.0 if symbol in {*G20_EXECUTION_TO_PROXY, "BIL"} else 0.000001,
            "minimum_notional": 0.0 if symbol in {*G20_EXECUTION_TO_PROXY, "BIL"} else 5.0,
        }
        for symbol in prices
    }
    return PaperCycleInput.create(
        observed_at=f"2026-08-{day:02d}T22:00:00+00:00",
        decision_time=f"2026-08-{day:02d}T21:59:00+00:00",
        data_cutoff=f"2026-08-{day:02d}T21:00:00+00:00",
        proxy_closes=_proxy_history(selected),
        crypto_closes=_crypto_history(),
        mark_prices=prices,
        fill_prices=prices,
        symbol_rules=rules,
        source_hashes={"fixture": canonical_hash({"day": day})},
        g20_signal_day=signal,
        g20_rebalance_day=rebalance,
    )


class DualEngineStrategyTest(unittest.TestCase):
    def test_g20_uses_one_x_proxy_top1_without_absolute_gate(self) -> None:
        history = _proxy_history("SOXL")
        decision = build_g20_decision(history)

        self.assertEqual(decision.selected_symbol, "SOXL")
        self.assertEqual(decision.target_weights, {"BIL": 0.8, "SOXL": 0.2})

        all_negative = {
            symbol: _series(200.0, -0.2 - index / 100.0)
            for index, symbol in enumerate(history)
        }
        negative_decision = build_g20_decision(all_negative)
        self.assertEqual(sum(negative_decision.target_weights.values()), 1.0)
        self.assertIn(negative_decision.selected_symbol, G20_EXECUTION_TO_PROXY)

    def test_c60_keeps_rejected_weight_in_cash_and_paxg_is_btc_gate_exempt(self) -> None:
        decision = build_c60_decision(_crypto_history(btc_up=False))

        self.assertFalse(decision.btc_system_gate)
        self.assertEqual(decision.candidates, ("PAXGUSDT", "ETHUSDT"))
        self.assertIn("PAXGUSDT", decision.target_weights)
        self.assertNotIn("ETHUSDT", decision.target_weights)
        self.assertLessEqual(sum(decision.target_weights.values()), 0.5)
        self.assertEqual(d15_c60_budget(decision), 0.025)

    def test_frozen_contract_rejects_order_authority_or_parameter_drift(self) -> None:
        contract = DualEnginePaperContract.frozen_v1()
        with self.assertRaises(DualEngineContractError):
            replace(contract, orders_authorized=True).validate()
        with self.assertRaises(DualEngineContractError):
            replace(contract, g20_risk_weight=0.235).validate()


class DualEnginePaperRuntimeTest(unittest.TestCase):
    def test_four_accounts_are_atomic_private_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "paper"
            cycle = _cycle(3, signal=True, rebalance=True)
            first = run_paper_cycle(root, cycle)
            second = run_paper_cycle(root, cycle)

            self.assertEqual(first, second)
            self.assertEqual(
                tuple(row["portfolio_id"] for row in first.portfolios),
                PAPER_PORTFOLIO_IDS,
            )
            self.assertFalse(first.orders_authorized)
            self.assertFalse(first.private_api_used)
            self.assertFalse(first.exchange_mutation_attempted)
            c60 = next(
                row for row in first.portfolios if row["portfolio_id"].endswith("-c60")
            )
            self.assertGreater(
                c60["nav"]["cumulative_stress_cost"],
                c60["nav"]["cumulative_cost"],
            )
            self.assertEqual(read_paper_snapshot(root), first)
            self.assertEqual(
                os.stat(root / "current" / "paper_program_snapshot.json").st_mode
                & 0o777,
                0o600,
            )
            audit_rows = (root / "state" / "audit.jsonl").read_text(
                encoding="ascii"
            ).splitlines()
            self.assertEqual(len(audit_rows), 1)
            self.assertFalse(json.loads(audit_rows[0])["orders_routed"])

    def test_month_end_signal_waits_and_daily_c60_does_not_resize_g20_sleeve(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "paper"
            first = run_paper_cycle(
                root,
                _cycle(3, selected="TQQQ", signal=True, rebalance=True),
            )
            first_gc5 = next(
                row for row in first.portfolios if row["portfolio_id"].endswith("-gc5")
            )
            first_tqqq = next(
                row for row in first_gc5["holdings"] if row["symbol"] == "TQQQ"
            )

            signaled = run_paper_cycle(
                root,
                _cycle(
                    4,
                    selected="SOXL",
                    signal=True,
                    rebalance=False,
                    marks={"TQQQ": 120.0},
                ),
            )
            signaled_gc5 = next(
                row
                for row in signaled.portfolios
                if row["portfolio_id"].endswith("-gc5")
            )
            signaled_tqqq = next(
                row for row in signaled_gc5["holdings"] if row["symbol"] == "TQQQ"
            )
            self.assertEqual(
                signaled.latest_decision["g20"]["selected_symbol"], "TQQQ"
            )
            self.assertEqual(signaled_tqqq["quantity"], first_tqqq["quantity"])

            executed = run_paper_cycle(
                root,
                _cycle(5, selected="ERX", rebalance=True),
            )
            self.assertEqual(
                executed.latest_decision["g20"]["selected_symbol"], "SOXL"
            )
            self.assertEqual(executed.audit_row_count, 3)

    def test_cycle_round_trip_is_hash_strict(self) -> None:
        cycle = _cycle(3, signal=True, rebalance=True)
        self.assertEqual(PaperCycleInput.from_dict(cycle.as_dict()), cycle)
        tampered = cycle.as_dict() | {"g20_signal_day": False}
        with self.assertRaises(DualEngineContractError):
            PaperCycleInput.from_dict(tampered)


class DualEngineMarketDataTest(unittest.TestCase):
    def _config(self) -> DualEngineMarketConfig:
        return DualEngineMarketConfig.from_dict(
            {
                "schema_version": 1,
                "tiingo_token_env": "TIINGO_API_TOKEN",
                "timeout_seconds": 10,
                "history_calendar_days": 450,
                "g20_signal_dates": ["2026-08-31"],
                "g20_rebalance_dates": ["2026-08-03"],
                "orders_authorized": False,
                "private_exchange_api_used": False,
            }
        )

    def test_unscheduled_g20_open_does_not_call_network(self) -> None:
        def forbidden(*_args):
            raise AssertionError("network getter must not be called")

        with self.assertRaises(NoScheduledPaperEvent):
            collect_market_cycle(
                self._config(),
                observed_at="2026-08-04T15:00:00+00:00",
                event="g20-open",
                getter=forbidden,
                environment={"TIINGO_API_TOKEN": "fixture"},
            )

    def test_before_ytd_start_does_not_call_network(self) -> None:
        def forbidden(*_args):
            raise AssertionError("network getter must not be called")

        with self.assertRaisesRegex(NoScheduledPaperEvent, "paper_forward_not_started"):
            collect_market_cycle(
                self._config(),
                observed_at="2025-12-31T22:30:00+00:00",
                event="daily-close",
                getter=forbidden,
                environment={},
            )

    def test_collects_public_histories_later_crypto_quotes_and_g20_first_bar(self) -> None:
        observed_ms = 1_785_769_200_000

        def getter(url, _headers, _timeout):
            path = urlparse(url).path
            if path.startswith("/tiingo/daily/"):
                symbol = path.split("/")[3]
                start = dt.date(2026, 4, 23)
                payload = [
                    {
                        "date": f"{(start + dt.timedelta(days=index)).isoformat()}T00:00:00.000Z",
                        "close": 100.0 + index,
                        "adjClose": 100.0 + index + (1.0 if symbol == "QQQ" else 0.0),
                    }
                    for index in range(100)
                ]
            elif path.startswith("/iex/"):
                payload = [{"date": "2026-08-03T13:30:00.000Z", "open": 101.25}]
            elif path == "/api/v3/klines":
                last_close = observed_ms - 3_600_000
                payload = []
                for index in range(100):
                    close_ms = last_close - (99 - index) * 86_400_000
                    payload.append([close_ms - 86_399_999, "100", "101", "99", str(100 + index / 10), "10", close_ms])
            elif path == "/api/v3/aggTrades":
                payload = [{"p": "110.5", "T": observed_ms - 1_800_000}]
            elif path == "/api/v3/exchangeInfo":
                payload = {
                    "symbols": [
                        {
                            "symbol": symbol,
                            "filters": [
                                {"filterType": "LOT_SIZE", "stepSize": "0.000001"},
                                {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
                            ],
                        }
                        for symbol in C60_SYMBOLS
                    ]
                }
            else:
                raise AssertionError(path)
            return payload, canonical_hash({"url": url, "payload": payload})

        cycle = collect_market_cycle(
            self._config(),
            observed_at="2026-08-03T15:00:00+00:00",
            event="g20-open",
            getter=getter,
            environment={"TIINGO_API_TOKEN": "fixture"},
        )

        self.assertTrue(cycle.g20_rebalance_day)
        self.assertFalse(cycle.g20_signal_day)
        self.assertEqual(cycle.fill_prices["TQQQ"], 101.25)
        self.assertEqual(cycle.fill_prices["PAXGUSDT"], 110.5)
        self.assertEqual(set(cycle.crypto_closes), set(C60_SYMBOLS))
        self.assertEqual(
            set(cycle.source_hashes),
            {"tiingo_public", "binance_public", "binance_exchange_rules"},
        )


if __name__ == "__main__":
    unittest.main()
