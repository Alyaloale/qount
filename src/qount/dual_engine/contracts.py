"""Frozen, order-free contracts for the Qount Dual-Engine paper program."""

from __future__ import annotations

import math
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from qount.contracts import canonical_hash
from qount.contracts import is_sha256
from qount.contracts import trace_id
from qount.contracts.trace import aware_datetime


DUAL_ENGINE_SCHEMA_VERSION = 1
DUAL_ENGINE_PROGRAM_ID = "dual-engine-paper"
DUAL_ENGINE_PROGRAM_VERSION = "1.1.0"
G20_STRATEGY_ID = "dual-engine-g20"
C60_STRATEGY_ID = "dual-engine-c60"
G20_STRATEGY_VERSION = "1.0.0"
C60_STRATEGY_VERSION = "1.0.0"

G20_EXECUTION_TO_PROXY = {
    "TQQQ": "QQQ",
    "SOXL": "SMH",
    "FAS": "XLF",
    "CURE": "XLV",
    "URTY": "IWM",
    "DRN": "VNQ",
    "ERX": "XLE",
}
G20_EXECUTION_SYMBOLS = tuple(G20_EXECUTION_TO_PROXY)
G20_PROXY_SYMBOLS = tuple(G20_EXECUTION_TO_PROXY.values())
C60_SYMBOLS = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "LTCUSDT",
    "BCHUSDT",
    "DOTUSDT",
    "PAXGUSDT",
)
PAPER_PORTFOLIO_IDS = (
    "dual-engine-paper-g20",
    "dual-engine-paper-c60",
    "dual-engine-paper-gc5",
    "dual-engine-paper-d15",
)


class DualEngineContractError(ValueError):
    """A frozen Dual-Engine input or artifact is invalid."""


def _json_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize tuples and nested mappings to their canonical JSON shape."""

    return json.loads(
        json.dumps(value, allow_nan=False, ensure_ascii=True, sort_keys=True)
    )


def _finite(value: object, *, name: str, minimum: float | None = None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DualEngineContractError(f"{name}_invalid") from exc
    if not math.isfinite(number) or (minimum is not None and number < minimum):
        raise DualEngineContractError(f"{name}_invalid")
    return number


def _time(value: str, *, name: str) -> str:
    try:
        return aware_datetime(value).isoformat()
    except (AttributeError, TypeError, ValueError) as exc:
        raise DualEngineContractError(f"{name}_invalid") from exc


def _hash_mapping(value: Mapping[str, str], *, name: str) -> dict[str, str]:
    normalized = {str(key): str(item) for key, item in value.items()}
    if not normalized or any(not key or not is_sha256(item) for key, item in normalized.items()):
        raise DualEngineContractError(f"{name}_invalid")
    return dict(sorted(normalized.items()))


def _paper_number(
    value: object,
    *,
    name: str,
    minimum: float | None = None,
) -> float:
    if isinstance(value, bool):
        raise DualEngineContractError(f"{name}_invalid")
    return _finite(value, name=name, minimum=minimum)


@dataclass(frozen=True)
class DualEnginePaperContract:
    schema_version: int
    program_id: str
    program_version: str
    forward_not_before: str
    initial_capital_usd_eq: float
    reporting_asset: str
    g20_risk_weight: float
    g20_cost_bps: float
    c60_cost_bps: float
    c60_stress_cost_bps: float
    c60_volatility_target: float
    c60_volatility_window: int
    d15_budgets: tuple[float, float, float, float]
    usd_usdt_parity_assumed: bool
    orders_authorized: bool
    private_api_used: bool
    contract_hash: str

    @classmethod
    def frozen_v1(cls) -> "DualEnginePaperContract":
        core = {
            "schema_version": DUAL_ENGINE_SCHEMA_VERSION,
            "program_id": DUAL_ENGINE_PROGRAM_ID,
            "program_version": DUAL_ENGINE_PROGRAM_VERSION,
            "forward_not_before": "2026-01-01T00:00:00+00:00",
            "initial_capital_usd_eq": 10_000.0,
            "reporting_asset": "USD_EQ",
            "g20_risk_weight": 0.20,
            "g20_cost_bps": 20.0,
            "c60_cost_bps": 25.0,
            "c60_stress_cost_bps": 50.0,
            "c60_volatility_target": 0.60,
            "c60_volatility_window": 20,
            "d15_budgets": (0.025, 0.075, 0.10, 0.15),
            "usd_usdt_parity_assumed": True,
            "orders_authorized": False,
            "private_api_used": False,
        }
        contract = cls(**core, contract_hash=canonical_hash(core))
        contract.validate()
        return contract

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "program_id": self.program_id,
            "program_version": self.program_version,
            "forward_not_before": self.forward_not_before,
            "initial_capital_usd_eq": self.initial_capital_usd_eq,
            "reporting_asset": self.reporting_asset,
            "g20_risk_weight": self.g20_risk_weight,
            "g20_cost_bps": self.g20_cost_bps,
            "c60_cost_bps": self.c60_cost_bps,
            "c60_stress_cost_bps": self.c60_stress_cost_bps,
            "c60_volatility_target": self.c60_volatility_target,
            "c60_volatility_window": self.c60_volatility_window,
            "d15_budgets": self.d15_budgets,
            "usd_usdt_parity_assumed": self.usd_usdt_parity_assumed,
            "orders_authorized": self.orders_authorized,
            "private_api_used": self.private_api_used,
        }

    def validate(self) -> None:
        if self.schema_version != DUAL_ENGINE_SCHEMA_VERSION:
            raise DualEngineContractError("dual_engine_contract_schema_invalid")
        if self.program_id != DUAL_ENGINE_PROGRAM_ID or self.program_version != DUAL_ENGINE_PROGRAM_VERSION:
            raise DualEngineContractError("dual_engine_contract_identity_invalid")
        normalized_start = _time(
            self.forward_not_before,
            name="dual_engine_forward_not_before",
        )
        if self.reporting_asset != "USD_EQ":
            raise DualEngineContractError("dual_engine_reporting_asset_invalid")
        if _finite(self.initial_capital_usd_eq, name="dual_engine_capital", minimum=0.0) <= 0:
            raise DualEngineContractError("dual_engine_capital_invalid")
        for name in (
            "g20_risk_weight",
            "g20_cost_bps",
            "c60_cost_bps",
            "c60_stress_cost_bps",
            "c60_volatility_target",
        ):
            _finite(getattr(self, name), name=f"dual_engine_{name}", minimum=0.0)
        if (
            normalized_start != "2026-01-01T00:00:00+00:00"
            or self.initial_capital_usd_eq != 10_000.0
            or self.g20_risk_weight != 0.20
            or self.g20_cost_bps != 20.0
            or self.c60_cost_bps != 25.0
            or self.c60_stress_cost_bps != 50.0
            or self.c60_volatility_target != 0.60
        ):
            raise DualEngineContractError("dual_engine_frozen_parameter_changed")
        if self.c60_volatility_window != 20 or self.d15_budgets != (0.025, 0.075, 0.10, 0.15):
            raise DualEngineContractError("dual_engine_frozen_parameter_changed")
        if self.orders_authorized is not False or self.private_api_used is not False:
            raise DualEngineContractError("dual_engine_order_guard_invalid")
        if self.usd_usdt_parity_assumed is not True:
            raise DualEngineContractError("dual_engine_reporting_assumption_invalid")
        if self.contract_hash != canonical_hash(self._core()):
            raise DualEngineContractError("dual_engine_contract_hash_invalid")

    def as_dict(self) -> dict[str, Any]:
        return self._core() | {"contract_hash": self.contract_hash}


@dataclass(frozen=True)
class PaperCycleInput:
    """One verified market event consumed by the stateful paper runtime."""

    schema_version: int
    observed_at: str
    decision_time: str
    data_cutoff: str
    proxy_closes: Mapping[str, tuple[float, ...]]
    crypto_closes: Mapping[str, tuple[float, ...]]
    mark_prices: Mapping[str, float]
    fill_prices: Mapping[str, float]
    symbol_rules: Mapping[str, Mapping[str, float]]
    source_hashes: Mapping[str, str]
    g20_signal_day: bool
    g20_rebalance_day: bool
    market_data_complete: bool
    blockers: tuple[str, ...]
    cycle_hash: str

    @classmethod
    def create(
        cls,
        *,
        observed_at: str,
        decision_time: str,
        data_cutoff: str,
        proxy_closes: Mapping[str, Sequence[float]],
        crypto_closes: Mapping[str, Sequence[float]],
        mark_prices: Mapping[str, float],
        fill_prices: Mapping[str, float],
        symbol_rules: Mapping[str, Mapping[str, float]],
        source_hashes: Mapping[str, str],
        g20_signal_day: bool,
        g20_rebalance_day: bool,
        market_data_complete: bool = True,
        blockers: Sequence[str] = (),
    ) -> "PaperCycleInput":
        core = {
            "schema_version": DUAL_ENGINE_SCHEMA_VERSION,
            "observed_at": _time(observed_at, name="paper_cycle_observed_at"),
            "decision_time": _time(decision_time, name="paper_cycle_decision_time"),
            "data_cutoff": _time(data_cutoff, name="paper_cycle_data_cutoff"),
            "proxy_closes": {
                str(symbol): tuple(float(value) for value in values)
                for symbol, values in sorted(proxy_closes.items())
            },
            "crypto_closes": {
                str(symbol): tuple(float(value) for value in values)
                for symbol, values in sorted(crypto_closes.items())
            },
            "mark_prices": {
                str(symbol): float(value) for symbol, value in sorted(mark_prices.items())
            },
            "fill_prices": {
                str(symbol): float(value) for symbol, value in sorted(fill_prices.items())
            },
            "symbol_rules": {
                str(symbol): {
                    str(key): float(value) for key, value in sorted(rule.items())
                }
                for symbol, rule in sorted(symbol_rules.items())
            },
            "source_hashes": _hash_mapping(source_hashes, name="paper_cycle_sources"),
            "g20_signal_day": bool(g20_signal_day),
            "g20_rebalance_day": bool(g20_rebalance_day),
            "market_data_complete": bool(market_data_complete),
            "blockers": tuple(str(value) for value in blockers),
        }
        cycle = cls(**core, cycle_hash=canonical_hash(core))
        cycle.validate()
        return cycle

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "observed_at": self.observed_at,
            "decision_time": self.decision_time,
            "data_cutoff": self.data_cutoff,
            "proxy_closes": {key: tuple(value) for key, value in self.proxy_closes.items()},
            "crypto_closes": {key: tuple(value) for key, value in self.crypto_closes.items()},
            "mark_prices": dict(self.mark_prices),
            "fill_prices": dict(self.fill_prices),
            "symbol_rules": {key: dict(value) for key, value in self.symbol_rules.items()},
            "source_hashes": dict(self.source_hashes),
            "g20_signal_day": self.g20_signal_day,
            "g20_rebalance_day": self.g20_rebalance_day,
            "market_data_complete": self.market_data_complete,
            "blockers": self.blockers,
        }

    def validate(self) -> None:
        if self.schema_version != DUAL_ENGINE_SCHEMA_VERSION:
            raise DualEngineContractError("paper_cycle_schema_invalid")
        observed = aware_datetime(self.observed_at)
        decision = aware_datetime(self.decision_time)
        cutoff = aware_datetime(self.data_cutoff)
        if cutoff > decision or decision > observed:
            raise DualEngineContractError("paper_cycle_time_order_invalid")
        if set(self.proxy_closes) != set(G20_PROXY_SYMBOLS):
            raise DualEngineContractError("paper_cycle_proxy_universe_invalid")
        if set(self.crypto_closes) != set(C60_SYMBOLS):
            raise DualEngineContractError("paper_cycle_crypto_universe_invalid")
        for symbol, values in (*self.proxy_closes.items(), *self.crypto_closes.items()):
            minimum = 64 if symbol in G20_PROXY_SYMBOLS else 91
            if len(values) < minimum or any(_finite(value, name=f"paper_cycle_close:{symbol}", minimum=0.0) <= 0 for value in values):
                raise DualEngineContractError(f"paper_cycle_history_invalid:{symbol}")
        execution_universe = {*G20_EXECUTION_SYMBOLS, "BIL", *C60_SYMBOLS}
        if set(self.mark_prices) != execution_universe or any(_finite(value, name=f"paper_cycle_mark:{symbol}", minimum=0.0) <= 0 for symbol, value in self.mark_prices.items()):
            raise DualEngineContractError("paper_cycle_mark_prices_invalid")
        if set(self.fill_prices) != execution_universe or any(_finite(value, name=f"paper_cycle_fill:{symbol}", minimum=0.0) <= 0 for symbol, value in self.fill_prices.items()):
            raise DualEngineContractError("paper_cycle_fill_prices_invalid")
        if set(self.symbol_rules) != execution_universe:
            raise DualEngineContractError("paper_cycle_symbol_rules_invalid")
        for symbol, rule in self.symbol_rules.items():
            if set(rule) != {"step_size", "minimum_notional"}:
                raise DualEngineContractError(
                    f"paper_cycle_symbol_rule_fields_invalid:{symbol}"
                )
            if (
                _finite(
                    rule["step_size"],
                    name=f"paper_cycle_step:{symbol}",
                    minimum=0.0,
                ) <= 0.0
                or _finite(
                    rule["minimum_notional"],
                    name=f"paper_cycle_min_notional:{symbol}",
                    minimum=0.0,
                ) < 0.0
            ):
                raise DualEngineContractError(
                    f"paper_cycle_symbol_rule_invalid:{symbol}"
                )
        _hash_mapping(self.source_hashes, name="paper_cycle_sources")
        if any(
            not isinstance(value, bool)
            for value in (
                self.g20_signal_day,
                self.g20_rebalance_day,
                self.market_data_complete,
            )
        ):
            raise DualEngineContractError("paper_cycle_flags_invalid")
        if self.market_data_complete is not (not self.blockers):
            raise DualEngineContractError("paper_cycle_quality_invalid")
        if self.cycle_hash != canonical_hash(self._core()):
            raise DualEngineContractError("paper_cycle_hash_invalid")

    def as_dict(self) -> dict[str, Any]:
        return self._core() | {"cycle_hash": self.cycle_hash}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PaperCycleInput":
        expected = {
            "schema_version", "observed_at", "decision_time", "data_cutoff",
            "proxy_closes", "crypto_closes", "mark_prices", "fill_prices",
            "symbol_rules", "source_hashes", "g20_signal_day",
            "g20_rebalance_day", "market_data_complete", "blockers",
            "cycle_hash",
        }
        if set(value) != expected:
            raise DualEngineContractError("paper_cycle_fields_invalid")
        cycle = cls(
            schema_version=int(value["schema_version"]),
            observed_at=str(value["observed_at"]),
            decision_time=str(value["decision_time"]),
            data_cutoff=str(value["data_cutoff"]),
            proxy_closes={
                str(symbol): tuple(float(item) for item in values)
                for symbol, values in dict(value["proxy_closes"]).items()
            },
            crypto_closes={
                str(symbol): tuple(float(item) for item in values)
                for symbol, values in dict(value["crypto_closes"]).items()
            },
            mark_prices={
                str(symbol): float(item)
                for symbol, item in dict(value["mark_prices"]).items()
            },
            fill_prices={
                str(symbol): float(item)
                for symbol, item in dict(value["fill_prices"]).items()
            },
            symbol_rules={
                str(symbol): {
                    str(name): float(item)
                    for name, item in dict(rule).items()
                }
                for symbol, rule in dict(value["symbol_rules"]).items()
            },
            source_hashes={
                str(name): str(item)
                for name, item in dict(value["source_hashes"]).items()
            },
            g20_signal_day=value["g20_signal_day"],
            g20_rebalance_day=value["g20_rebalance_day"],
            market_data_complete=value["market_data_complete"],
            blockers=tuple(str(item) for item in value["blockers"]),
            cycle_hash=str(value["cycle_hash"]),
        )
        cycle.validate()
        return cycle


@dataclass(frozen=True)
class PaperProgramSnapshot:
    """Verified, secret-free source for the Dashboard paper read model."""

    schema_version: int
    program_id: str
    program_version: str
    generated_at: str
    data_cutoff: str
    forward_start_at: str
    status: str
    contract_hash: str
    source_hashes: Mapping[str, str]
    orders_authorized: bool
    private_api_used: bool
    exchange_mutation_attempted: bool
    reporting_asset: str
    usd_usdt_parity_assumed: bool
    portfolios: tuple[Mapping[str, Any], ...]
    benchmarks: tuple[Mapping[str, Any], ...]
    history_reference: Mapping[str, Any]
    latest_decision: Mapping[str, Any]
    audit_last_hash: str
    audit_row_count: int
    snapshot_hash: str

    @classmethod
    def create(
        cls,
        *,
        generated_at: str,
        data_cutoff: str,
        forward_start_at: str,
        status: str,
        contract_hash: str,
        source_hashes: Mapping[str, str],
        portfolios: Sequence[Mapping[str, Any]],
        benchmarks: Sequence[Mapping[str, Any]] = (),
        history_reference: Mapping[str, Any] | None = None,
        latest_decision: Mapping[str, Any],
        audit_last_hash: str,
        audit_row_count: int,
    ) -> "PaperProgramSnapshot":
        core = {
            "schema_version": DUAL_ENGINE_SCHEMA_VERSION,
            "program_id": DUAL_ENGINE_PROGRAM_ID,
            "program_version": DUAL_ENGINE_PROGRAM_VERSION,
            "generated_at": _time(generated_at, name="paper_snapshot_generated_at"),
            "data_cutoff": _time(data_cutoff, name="paper_snapshot_data_cutoff"),
            "forward_start_at": _time(forward_start_at, name="paper_snapshot_forward_start"),
            "status": str(status),
            "contract_hash": str(contract_hash),
            "source_hashes": _hash_mapping(source_hashes, name="paper_snapshot_sources"),
            "orders_authorized": False,
            "private_api_used": False,
            "exchange_mutation_attempted": False,
            "reporting_asset": "USD_EQ",
            "usd_usdt_parity_assumed": True,
            "portfolios": tuple(_json_mapping(value) for value in portfolios),
            "benchmarks": tuple(_json_mapping(value) for value in benchmarks),
            "history_reference": _json_mapping(history_reference or {"status": "unavailable"}),
            "latest_decision": _json_mapping(latest_decision),
            "audit_last_hash": str(audit_last_hash),
            "audit_row_count": int(audit_row_count),
        }
        snapshot = cls(**core, snapshot_hash=canonical_hash(core))
        snapshot.validate()
        return snapshot

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "program_id": self.program_id,
            "program_version": self.program_version,
            "generated_at": self.generated_at,
            "data_cutoff": self.data_cutoff,
            "forward_start_at": self.forward_start_at,
            "status": self.status,
            "contract_hash": self.contract_hash,
            "source_hashes": dict(self.source_hashes),
            "orders_authorized": self.orders_authorized,
            "private_api_used": self.private_api_used,
            "exchange_mutation_attempted": self.exchange_mutation_attempted,
            "reporting_asset": self.reporting_asset,
            "usd_usdt_parity_assumed": self.usd_usdt_parity_assumed,
            "portfolios": [dict(value) for value in self.portfolios],
            "benchmarks": [dict(value) for value in self.benchmarks],
            "history_reference": dict(self.history_reference),
            "latest_decision": dict(self.latest_decision),
            "audit_last_hash": self.audit_last_hash,
            "audit_row_count": self.audit_row_count,
        }

    def validate(self) -> None:
        if self.schema_version != DUAL_ENGINE_SCHEMA_VERSION or self.program_id != DUAL_ENGINE_PROGRAM_ID or self.program_version != DUAL_ENGINE_PROGRAM_VERSION:
            raise DualEngineContractError("paper_snapshot_identity_invalid")
        generated = aware_datetime(self.generated_at)
        cutoff = aware_datetime(self.data_cutoff)
        start = aware_datetime(self.forward_start_at)
        if cutoff > generated or start > generated:
            raise DualEngineContractError("paper_snapshot_time_order_invalid")
        if self.status not in {"shadow", "paper", "blocked", "stale", "unavailable"}:
            raise DualEngineContractError("paper_snapshot_status_invalid")
        if not is_sha256(self.contract_hash) or not is_sha256(self.audit_last_hash):
            raise DualEngineContractError("paper_snapshot_hash_reference_invalid")
        _hash_mapping(self.source_hashes, name="paper_snapshot_sources")
        if self.orders_authorized is not False or self.private_api_used is not False or self.exchange_mutation_attempted is not False:
            raise DualEngineContractError("paper_snapshot_order_guard_invalid")
        if self.reporting_asset != "USD_EQ" or self.usd_usdt_parity_assumed is not True:
            raise DualEngineContractError("paper_snapshot_reporting_invalid")
        ids = [str(row.get("portfolio_id", "")) for row in self.portfolios]
        if tuple(ids) != PAPER_PORTFOLIO_IDS:
            raise DualEngineContractError("paper_snapshot_portfolios_invalid")
        allowed_symbols = {*G20_EXECUTION_SYMBOLS, "BIL", *C60_SYMBOLS}
        expected_labels = {
            "dual-engine-paper-g20": "G20",
            "dual-engine-paper-c60": "C60",
            "dual-engine-paper-gc5": "GC5",
            "dual-engine-paper-d15": "D15",
        }
        for portfolio in self.portfolios:
            expected_portfolio_fields = {
                "portfolio_id", "label", "status", "initial_capital",
                "reporting_asset", "nav", "allocation", "holdings",
                "latest_execution", "latest_decision",
            }
            if set(portfolio) != expected_portfolio_fields:
                raise DualEngineContractError("paper_snapshot_portfolio_fields_invalid")
            portfolio_id = str(portfolio["portfolio_id"])
            if (
                portfolio["label"] != expected_labels[portfolio_id]
                or portfolio["status"] != "paper"
                or portfolio["reporting_asset"] != "USD_EQ"
                or _paper_number(
                    portfolio["initial_capital"],
                    name="paper_snapshot_initial_capital",
                    minimum=0.0,
                ) != 10_000.0
            ):
                raise DualEngineContractError("paper_snapshot_portfolio_identity_invalid")
            nav = portfolio["nav"]
            if not isinstance(nav, Mapping) or set(nav) != {
                "signal", "executable", "portfolio_realized",
                "portfolio_realized_status", "since_start_return_fraction",
                "current_drawdown_fraction", "max_drawdown_fraction",
                "cumulative_cost", "cumulative_stress_cost", "points",
            }:
                raise DualEngineContractError("paper_snapshot_nav_fields_invalid")
            signal_nav = _paper_number(
                nav["signal"], name="paper_snapshot_signal_nav", minimum=0.0
            )
            executable_nav = _paper_number(
                nav["executable"],
                name="paper_snapshot_executable_nav",
                minimum=0.0,
            )
            if (
                signal_nav <= 0.0
                or executable_nav <= 0.0
                or nav["portfolio_realized"] is not None
                or nav["portfolio_realized_status"]
                != "unavailable_no_real_fills"
            ):
                raise DualEngineContractError("paper_snapshot_nav_invalid")
            for name in (
                "since_start_return_fraction",
                "current_drawdown_fraction",
                "max_drawdown_fraction",
                "cumulative_cost",
                "cumulative_stress_cost",
            ):
                minimum = 0.0 if name.startswith("cumulative_") else None
                _paper_number(nav[name], name=f"paper_snapshot_{name}", minimum=minimum)
            if nav["cumulative_stress_cost"] < nav["cumulative_cost"] - 1e-9:
                raise DualEngineContractError("paper_snapshot_stress_cost_invalid")
            points = nav["points"]
            if not isinstance(points, list) or not points:
                raise DualEngineContractError("paper_snapshot_nav_points_invalid")
            for point in points:
                if not isinstance(point, Mapping) or set(point) != {
                    "marked_at", "signal", "executable"
                }:
                    raise DualEngineContractError("paper_snapshot_nav_point_invalid")
                if aware_datetime(str(point["marked_at"])) > generated:
                    raise DualEngineContractError("paper_snapshot_nav_point_time_invalid")
                if (
                    _paper_number(
                        point["signal"],
                        name="paper_snapshot_point_signal",
                        minimum=0.0,
                    ) <= 0.0
                    or _paper_number(
                        point["executable"],
                        name="paper_snapshot_point_executable",
                        minimum=0.0,
                    ) <= 0.0
                ):
                    raise DualEngineContractError("paper_snapshot_nav_point_invalid")
            allocation = portfolio["allocation"]
            if not isinstance(allocation, Mapping) or set(allocation) != {
                "g20_budget", "c60_budget", "cash", "cash_weight"
            }:
                raise DualEngineContractError("paper_snapshot_allocation_fields_invalid")
            g20_budget = _paper_number(
                allocation["g20_budget"],
                name="paper_snapshot_g20_budget",
                minimum=0.0,
            )
            c60_budget = _paper_number(
                allocation["c60_budget"],
                name="paper_snapshot_c60_budget",
                minimum=0.0,
            )
            cash_weight = _paper_number(
                allocation["cash_weight"],
                name="paper_snapshot_cash_weight",
                minimum=0.0,
            )
            _paper_number(
                allocation["cash"],
                name="paper_snapshot_cash",
                minimum=0.0,
            )
            if (
                not math.isclose(g20_budget + c60_budget, 1.0, abs_tol=1e-12)
                or cash_weight > 1.0 + 1e-9
            ):
                raise DualEngineContractError("paper_snapshot_allocation_invalid")
            holdings = portfolio["holdings"]
            if not isinstance(holdings, list):
                raise DualEngineContractError("paper_snapshot_holdings_invalid")
            holding_symbols: list[str] = []
            for holding in holdings:
                if not isinstance(holding, Mapping) or set(holding) != {
                    "symbol", "quantity", "mark_price", "market_value",
                    "actual_weight",
                }:
                    raise DualEngineContractError("paper_snapshot_holding_fields_invalid")
                symbol = str(holding["symbol"])
                holding_symbols.append(symbol)
                if symbol not in allowed_symbols:
                    raise DualEngineContractError("paper_snapshot_holding_symbol_invalid")
                for name in ("quantity", "mark_price", "market_value"):
                    if _paper_number(
                        holding[name],
                        name=f"paper_snapshot_holding_{name}",
                        minimum=0.0,
                    ) <= 0.0:
                        raise DualEngineContractError("paper_snapshot_holding_invalid")
                weight = _paper_number(
                    holding["actual_weight"],
                    name="paper_snapshot_holding_weight",
                    minimum=0.0,
                )
                if weight > 1.0 + 1e-9:
                    raise DualEngineContractError("paper_snapshot_holding_weight_invalid")
            if len(holding_symbols) != len(set(holding_symbols)):
                raise DualEngineContractError("paper_snapshot_holding_duplicate")
            execution = portfolio["latest_execution"]
            if not isinstance(execution, Mapping) or set(execution) != {
                "count", "orders_routed", "fills"
            }:
                raise DualEngineContractError("paper_snapshot_execution_fields_invalid")
            fills = execution["fills"]
            if (
                not isinstance(execution["count"], int)
                or isinstance(execution["count"], bool)
                or not isinstance(fills, list)
                or execution["count"] != len(fills)
                or execution["orders_routed"] is not False
            ):
                raise DualEngineContractError("paper_snapshot_execution_invalid")
            for fill in fills:
                if not isinstance(fill, Mapping) or set(fill) != {
                    "sleeve_id", "symbol", "side", "quantity",
                    "reference_price", "notional", "cost", "stress_cost",
                }:
                    raise DualEngineContractError("paper_snapshot_fill_fields_invalid")
                if (
                    fill["sleeve_id"] not in {"g20", "c60"}
                    or fill["symbol"] not in allowed_symbols
                    or fill["side"] not in {"buy", "sell"}
                ):
                    raise DualEngineContractError("paper_snapshot_fill_identity_invalid")
                for name in ("quantity", "reference_price", "notional"):
                    if _paper_number(
                        fill[name],
                        name=f"paper_snapshot_fill_{name}",
                        minimum=0.0,
                    ) <= 0.0:
                        raise DualEngineContractError("paper_snapshot_fill_invalid")
                cost = _paper_number(
                    fill["cost"], name="paper_snapshot_fill_cost", minimum=0.0
                )
                stress_cost = _paper_number(
                    fill["stress_cost"],
                    name="paper_snapshot_fill_stress_cost",
                    minimum=0.0,
                )
                if stress_cost < cost - 1e-9:
                    raise DualEngineContractError("paper_snapshot_fill_stress_invalid")
            decision = portfolio["latest_decision"]
            if not isinstance(decision, Mapping) or set(decision) != {
                "g20_selected", "c60_candidates", "btc_system_gate",
                "eligible_count", "volatility_scalar", "d15_c60_budget",
            }:
                raise DualEngineContractError("paper_snapshot_portfolio_decision_invalid")
            if (
                decision["g20_selected"] not in G20_EXECUTION_SYMBOLS
                or not isinstance(decision["c60_candidates"], list)
                or any(item not in C60_SYMBOLS for item in decision["c60_candidates"])
                or not isinstance(decision["btc_system_gate"], bool)
                or not isinstance(decision["eligible_count"], int)
                or isinstance(decision["eligible_count"], bool)
                or decision["eligible_count"] not in {0, 1, 2}
                or _paper_number(
                    decision["volatility_scalar"],
                    name="paper_snapshot_volatility_scalar",
                    minimum=0.0,
                ) > 1.0
                or decision["d15_c60_budget"] not in {0.025, 0.075, 0.10, 0.15}
            ):
                raise DualEngineContractError("paper_snapshot_portfolio_decision_invalid")
        if self.benchmarks:
            raise DualEngineContractError("paper_snapshot_benchmarks_not_ready")
        if dict(self.history_reference) != {
            "status": "owner_authorized_ytd_replay",
            "start_at": "2026-01-01T00:00:00+00:00",
            "method": "tiingo_daily_open_and_binance_minute",
            "curve_role": "simulated_not_realized",
        }:
            raise DualEngineContractError("paper_snapshot_history_reference_invalid")
        latest = self.latest_decision
        if not isinstance(latest, Mapping) or set(latest) != {
            "decision_time", "data_cutoff", "cycle_hash", "g20", "c60",
            "d15_c60_budget", "intent_ids", "intent_hashes", "reason_codes",
        }:
            raise DualEngineContractError("paper_snapshot_latest_decision_invalid")
        if (
            aware_datetime(str(latest["data_cutoff"]))
            > aware_datetime(str(latest["decision_time"]))
            or aware_datetime(str(latest["decision_time"])) > generated
            or not is_sha256(str(latest["cycle_hash"]))
            or latest["d15_c60_budget"] not in {0.025, 0.075, 0.10, 0.15}
            or not isinstance(latest["g20"], Mapping)
            or not isinstance(latest["c60"], Mapping)
            or any(
                not isinstance(values, list)
                or not values
                or any(not is_sha256(str(item)) for item in values)
                for values in (latest["intent_ids"], latest["intent_hashes"])
            )
            or latest["reason_codes"] != [
                "PAPER_ONLY",
                "ORDERS_NOT_AUTHORIZED",
                "USD_USDT_PARITY_ASSUMED",
                "OWNER_AUTHORIZED_YTD_REPLAY",
            ]
        ):
            raise DualEngineContractError("paper_snapshot_latest_decision_invalid")
        if self.audit_row_count < 1:
            raise DualEngineContractError("paper_snapshot_audit_invalid")
        if self.snapshot_hash != canonical_hash(self._core()):
            raise DualEngineContractError("paper_snapshot_hash_invalid")

    def as_dict(self) -> dict[str, Any]:
        return self._core() | {"snapshot_hash": self.snapshot_hash}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PaperProgramSnapshot":
        expected = {
            "schema_version", "program_id", "program_version", "generated_at",
            "data_cutoff", "forward_start_at", "status", "contract_hash",
            "source_hashes", "orders_authorized", "private_api_used",
            "exchange_mutation_attempted", "reporting_asset",
            "usd_usdt_parity_assumed", "portfolios", "benchmarks",
            "history_reference", "latest_decision", "audit_last_hash",
            "audit_row_count", "snapshot_hash",
        }
        if set(value) != expected:
            raise DualEngineContractError("paper_snapshot_fields_invalid")
        for name in (
            "orders_authorized",
            "private_api_used",
            "exchange_mutation_attempted",
            "usd_usdt_parity_assumed",
        ):
            if not isinstance(value[name], bool):
                raise DualEngineContractError("paper_snapshot_flags_invalid")
        snapshot = cls(
            schema_version=int(value["schema_version"]),
            program_id=str(value["program_id"]),
            program_version=str(value["program_version"]),
            generated_at=str(value["generated_at"]),
            data_cutoff=str(value["data_cutoff"]),
            forward_start_at=str(value["forward_start_at"]),
            status=str(value["status"]),
            contract_hash=str(value["contract_hash"]),
            source_hashes=dict(value["source_hashes"]),
            orders_authorized=value["orders_authorized"],
            private_api_used=value["private_api_used"],
            exchange_mutation_attempted=value["exchange_mutation_attempted"],
            reporting_asset=str(value["reporting_asset"]),
            usd_usdt_parity_assumed=value["usd_usdt_parity_assumed"],
            portfolios=tuple(dict(row) for row in value["portfolios"]),
            benchmarks=tuple(dict(row) for row in value["benchmarks"]),
            history_reference=dict(value["history_reference"]),
            latest_decision=dict(value["latest_decision"]),
            audit_last_hash=str(value["audit_last_hash"]),
            audit_row_count=int(value["audit_row_count"]),
            snapshot_hash=str(value["snapshot_hash"]),
        )
        snapshot.validate()
        return snapshot


def paper_snapshot_id(snapshot: PaperProgramSnapshot) -> str:
    snapshot.validate()
    return trace_id("paper_program_snapshot", {"snapshot_hash": snapshot.snapshot_hash})
