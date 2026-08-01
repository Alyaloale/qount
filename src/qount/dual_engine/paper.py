"""Stateful, network-isolated paper accounting for the Dual-Engine program."""

from __future__ import annotations

import fcntl
import json
import math
import os
from pathlib import Path
import stat
import tempfile
from typing import Any, Mapping, Sequence

from qount.contracts import MarketSnapshot
from qount.contracts import canonical_hash
from qount.contracts.trace import aware_datetime

from qount.dual_engine.contracts import C60_SYMBOLS
from qount.dual_engine.contracts import DUAL_ENGINE_PROGRAM_ID
from qount.dual_engine.contracts import DUAL_ENGINE_PROGRAM_VERSION
from qount.dual_engine.contracts import DualEngineContractError
from qount.dual_engine.contracts import DualEnginePaperContract
from qount.dual_engine.contracts import G20_EXECUTION_SYMBOLS
from qount.dual_engine.contracts import PAPER_PORTFOLIO_IDS
from qount.dual_engine.contracts import PaperCycleInput
from qount.dual_engine.contracts import PaperProgramSnapshot
from qount.dual_engine.strategy import C60Decision
from qount.dual_engine.strategy import G20Decision
from qount.dual_engine.strategy import build_c60_decision
from qount.dual_engine.strategy import build_g20_decision
from qount.dual_engine.strategy import build_strategy_intents
from qount.dual_engine.strategy import d15_c60_budget


PAPER_STATE_SCHEMA_VERSION = 1
_ZERO_HASH = "0" * 64
_PORTFOLIO_LABELS = {
    "dual-engine-paper-g20": "G20",
    "dual-engine-paper-c60": "C60",
    "dual-engine-paper-gc5": "GC5",
    "dual-engine-paper-d15": "D15",
}


class DualEnginePaperRuntimeError(DualEngineContractError):
    """The paper state cannot be advanced deterministically."""


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        + b"\n"
    )


def _ensure_private_directory(path: Path) -> None:
    if path.is_symlink():
        raise DualEnginePaperRuntimeError("paper_state_root_symlink_forbidden")
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    if not path.is_dir():
        raise DualEnginePaperRuntimeError("paper_state_root_invalid")
    mode = stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode)
    if mode != 0o700:
        os.chmod(path, 0o700)


def _atomic_json(path: Path, value: Mapping[str, Any], *, mode: int = 0o600) -> None:
    _ensure_private_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = -1
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def _read_json(path: Path, *, name: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise DualEnginePaperRuntimeError(f"{name}_file_invalid")
    if stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode) != 0o600:
        raise DualEnginePaperRuntimeError(f"{name}_mode_invalid")
    raw = path.read_bytes()
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise DualEnginePaperRuntimeError(f"{name}_duplicate_key:{key}")
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=reject_duplicates)
    except DualEnginePaperRuntimeError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DualEnginePaperRuntimeError(f"{name}_json_invalid") from exc
    if not isinstance(value, dict) or _canonical_bytes(value) != raw:
        raise DualEnginePaperRuntimeError(f"{name}_not_canonical")
    return value


def _positive(value: object, *, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DualEnginePaperRuntimeError(f"{name}_invalid") from exc
    if not math.isfinite(number) or number <= 0.0:
        raise DualEnginePaperRuntimeError(f"{name}_invalid")
    return number


def _nonnegative(value: object, *, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DualEnginePaperRuntimeError(f"{name}_invalid") from exc
    if not math.isfinite(number) or number < 0.0:
        raise DualEnginePaperRuntimeError(f"{name}_invalid")
    return number


def _floor_step(quantity: float, step: float) -> float:
    if quantity <= 0.0:
        return 0.0
    units = math.floor((quantity + 1e-12) / step)
    return round(units * step, 12)


def _symbol_rule(
    symbol: str,
    rules: Mapping[str, Mapping[str, float]],
    *,
    fractional: bool,
) -> tuple[float, float]:
    if fractional:
        return 1e-12, 0.0
    row = rules.get(symbol, {})
    default_step = 1.0 if symbol in {*G20_EXECUTION_SYMBOLS, "BIL"} else 1e-8
    step = _positive(row.get("step_size", default_step), name=f"paper_step:{symbol}")
    minimum = _nonnegative(row.get("minimum_notional", 0.0), name=f"paper_min_notional:{symbol}")
    return step, minimum


def _cost_bps(
    symbol: str,
    contract: DualEnginePaperContract,
    *,
    signal: bool,
    stress: bool = False,
) -> float:
    if signal:
        return 0.0
    if symbol in C60_SYMBOLS:
        return contract.c60_stress_cost_bps if stress else contract.c60_cost_bps
    if symbol in {*G20_EXECUTION_SYMBOLS, "BIL"}:
        return contract.g20_cost_bps
    raise DualEnginePaperRuntimeError(f"paper_cost_symbol_unknown:{symbol}")


def _layer_nav(layer: Mapping[str, Any], marks: Mapping[str, float]) -> float:
    equity = 0.0
    for sleeve in layer["sleeves"].values():
        equity += float(sleeve["cash"])
        for symbol, quantity in sleeve["positions"].items():
            if symbol not in marks:
                raise DualEnginePaperRuntimeError(f"paper_mark_missing:{symbol}")
            equity += float(quantity) * float(marks[symbol])
    if not math.isfinite(equity) or equity <= 0.0:
        raise DualEnginePaperRuntimeError("paper_layer_nav_invalid")
    return equity


def _aggregate_positions(layer: Mapping[str, Any]) -> dict[str, float]:
    positions: dict[str, float] = {}
    for sleeve in layer["sleeves"].values():
        for symbol, quantity in sleeve["positions"].items():
            positions[symbol] = positions.get(symbol, 0.0) + float(quantity)
    return {
        symbol: quantity
        for symbol, quantity in sorted(positions.items())
        if abs(quantity) > 1e-12
    }


def _rebalance_layer(
    layer: dict[str, Any],
    *,
    sleeve_budgets: Mapping[str, float],
    sleeve_targets: Mapping[str, Mapping[str, float]],
    marks: Mapping[str, float],
    fills: Mapping[str, float],
    rules: Mapping[str, Mapping[str, float]],
    contract: DualEnginePaperContract,
    signal: bool,
) -> tuple[float, list[dict[str, Any]]]:
    if set(sleeve_budgets) != set(layer["sleeves"]) or set(sleeve_targets) != set(layer["sleeves"]):
        raise DualEnginePaperRuntimeError("paper_sleeve_identity_mismatch")
    if not math.isclose(sum(sleeve_budgets.values()), 1.0, abs_tol=1e-12):
        raise DualEnginePaperRuntimeError("paper_sleeve_budget_invalid")
    total_nav = _layer_nav(layer, marks)
    desired: dict[str, dict[str, float]] = {}
    for sleeve_id, budget in sleeve_budgets.items():
        weights = sleeve_targets[sleeve_id]
        if any(float(value) < 0.0 for value in weights.values()) or sum(float(value) for value in weights.values()) > 1.0 + 1e-12:
            raise DualEnginePaperRuntimeError("paper_sleeve_target_invalid")
        sleeve_nav = total_nav * float(budget)
        desired[sleeve_id] = {}
        for symbol, weight in weights.items():
            if symbol not in fills:
                raise DualEnginePaperRuntimeError(f"paper_fill_missing:{symbol}")
            step, minimum = _symbol_rule(symbol, rules, fractional=signal)
            raw_quantity = sleeve_nav * float(weight) / float(fills[symbol])
            quantity = raw_quantity if signal else _floor_step(raw_quantity, step)
            if quantity * float(fills[symbol]) + 1e-12 < minimum:
                quantity = 0.0
            desired[sleeve_id][symbol] = quantity

    global_cash = sum(float(sleeve["cash"]) for sleeve in layer["sleeves"].values())
    costs = 0.0
    stress_costs = 0.0
    executions: list[dict[str, Any]] = []

    for sleeve_id in sorted(layer["sleeves"]):
        current = layer["sleeves"][sleeve_id]["positions"]
        for symbol in sorted(set(current) | set(desired[sleeve_id])):
            old = float(current.get(symbol, 0.0))
            wanted = float(desired[sleeve_id].get(symbol, 0.0))
            if wanted >= old - 1e-12:
                continue
            quantity = old - wanted
            price = float(fills[symbol])
            notional = quantity * price
            cost = notional * _cost_bps(symbol, contract, signal=signal) / 10_000.0
            stress_cost = notional * _cost_bps(
                symbol,
                contract,
                signal=signal,
                stress=True,
            ) / 10_000.0
            global_cash += notional - cost
            costs += cost
            stress_costs += stress_cost
            current[symbol] = wanted
            executions.append({
                "sleeve_id": sleeve_id,
                "symbol": symbol,
                "side": "sell",
                "quantity": quantity,
                "reference_price": price,
                "notional": notional,
                "cost": cost,
                "stress_cost": stress_cost,
            })

    required_cash = 0.0
    for sleeve_id in sorted(layer["sleeves"]):
        current = layer["sleeves"][sleeve_id]["positions"]
        for symbol, wanted in desired[sleeve_id].items():
            requested = max(0.0, float(wanted) - float(current.get(symbol, 0.0)))
            price = float(fills[symbol])
            cost_rate = _cost_bps(symbol, contract, signal=signal) / 10_000.0
            required_cash += requested * price * (1.0 + cost_rate)
    funding_scalar = (
        1.0
        if required_cash <= global_cash + 1e-12
        else global_cash / required_cash
    )

    for sleeve_id in sorted(layer["sleeves"]):
        current = layer["sleeves"][sleeve_id]["positions"]
        for symbol in sorted(desired[sleeve_id]):
            old = float(current.get(symbol, 0.0))
            wanted = float(desired[sleeve_id][symbol])
            if wanted <= old + 1e-12:
                continue
            price = float(fills[symbol])
            step, minimum = _symbol_rule(symbol, rules, fractional=signal)
            cost_rate = _cost_bps(symbol, contract, signal=signal) / 10_000.0
            requested = (wanted - old) * funding_scalar
            affordable = global_cash / (price * (1.0 + cost_rate))
            quantity = min(requested, affordable)
            if not signal:
                quantity = _floor_step(quantity, step)
            notional = quantity * price
            if quantity <= 0.0 or notional + 1e-12 < minimum:
                continue
            cost = notional * cost_rate
            stress_cost = notional * _cost_bps(
                symbol,
                contract,
                signal=signal,
                stress=True,
            ) / 10_000.0
            global_cash -= notional + cost
            if global_cash < -1e-7:
                raise DualEnginePaperRuntimeError("paper_negative_cash")
            global_cash = max(0.0, global_cash)
            costs += cost
            stress_costs += stress_cost
            current[symbol] = old + quantity
            executions.append({
                "sleeve_id": sleeve_id,
                "symbol": symbol,
                "side": "buy",
                "quantity": quantity,
                "reference_price": price,
                "notional": notional,
                "cost": cost,
                "stress_cost": stress_cost,
            })

    desired_cash = {}
    for sleeve_id, sleeve in layer["sleeves"].items():
        marked_positions = sum(
            float(quantity) * float(marks[symbol])
            for symbol, quantity in sleeve["positions"].items()
        )
        desired_cash[sleeve_id] = max(
            0.0,
            total_nav * float(sleeve_budgets[sleeve_id]) - marked_positions,
        )
    desired_cash_total = sum(desired_cash.values())
    if desired_cash_total > 0.0:
        allocations = {
            sleeve_id: global_cash * value / desired_cash_total
            for sleeve_id, value in desired_cash.items()
        }
    else:
        first = sorted(layer["sleeves"])[0]
        allocations = {sleeve_id: 0.0 for sleeve_id in layer["sleeves"]}
        allocations[first] = global_cash
    residual = global_cash - sum(allocations.values())
    allocations[sorted(allocations)[0]] += residual
    for sleeve_id, sleeve in layer["sleeves"].items():
        sleeve["cash"] = allocations[sleeve_id]
        sleeve["positions"] = {
            symbol: quantity
            for symbol, quantity in sorted(sleeve["positions"].items())
            if abs(float(quantity)) > 1e-12
        }
    layer["cumulative_cost"] = float(layer.get("cumulative_cost", 0.0)) + costs
    layer["cumulative_stress_cost"] = float(
        layer.get("cumulative_stress_cost", 0.0)
    ) + stress_costs
    return costs, executions


def _rebalance_single_sleeve(
    layer: dict[str, Any],
    *,
    sleeve_id: str,
    target: Mapping[str, float],
    marks: Mapping[str, float],
    fills: Mapping[str, float],
    rules: Mapping[str, Mapping[str, float]],
    contract: DualEnginePaperContract,
    signal: bool,
) -> tuple[float, list[dict[str, Any]]]:
    """Rebalance with cash fenced inside one sleeve.

    GC5 and D15 only cross-rebalance on the G20 monthly execution event.  A
    daily C60 rebalance therefore must not borrow cash from, or resize, G20.
    """

    if sleeve_id not in layer["sleeves"]:
        return 0.0, []
    isolated = {
        "sleeves": {sleeve_id: layer["sleeves"][sleeve_id]},
        "cumulative_cost": 0.0,
        "cumulative_stress_cost": 0.0,
    }
    cost, executions = _rebalance_layer(
        isolated,
        sleeve_budgets={sleeve_id: 1.0},
        sleeve_targets={sleeve_id: target},
        marks=marks,
        fills=fills,
        rules=rules,
        contract=contract,
        signal=signal,
    )
    layer["cumulative_cost"] = float(layer.get("cumulative_cost", 0.0)) + cost
    layer["cumulative_stress_cost"] = float(
        layer.get("cumulative_stress_cost", 0.0)
    ) + float(isolated["cumulative_stress_cost"])
    return cost, executions


def _new_layer(sleeve_ids: Sequence[str], capital: float) -> dict[str, Any]:
    return {
        "sleeves": {
            sleeve_id: {"cash": capital / len(sleeve_ids), "positions": {}}
            for sleeve_id in sleeve_ids
        },
        "cumulative_cost": 0.0,
        "cumulative_stress_cost": 0.0,
    }


def _new_portfolio(portfolio_id: str, capital: float) -> dict[str, Any]:
    sleeve_ids = (
        ("g20",)
        if portfolio_id.endswith("-g20")
        else ("c60",)
        if portfolio_id.endswith("-c60")
        else ("g20", "c60")
    )
    return {
        "portfolio_id": portfolio_id,
        "initial_capital": capital,
        "signal": _new_layer(sleeve_ids, capital),
        "executable": _new_layer(sleeve_ids, capital),
        "peak_executable_nav": capital,
        "max_drawdown_fraction": 0.0,
        "history": [],
        "latest_executions": [],
    }


def _budgets(portfolio_id: str, d15_budget: float) -> dict[str, float]:
    if portfolio_id.endswith("-g20"):
        return {"g20": 1.0}
    if portfolio_id.endswith("-c60"):
        return {"c60": 1.0}
    if portfolio_id.endswith("-gc5"):
        return {"g20": 0.95, "c60": 0.05}
    if portfolio_id.endswith("-d15"):
        return {"g20": 1.0 - d15_budget, "c60": d15_budget}
    raise DualEnginePaperRuntimeError("paper_portfolio_id_invalid")


def _targets(
    portfolio: Mapping[str, Any],
    g20_weights: Mapping[str, float],
    c60_weights: Mapping[str, float],
) -> dict[str, Mapping[str, float]]:
    result: dict[str, Mapping[str, float]] = {}
    if "g20" in portfolio["signal"]["sleeves"]:
        result["g20"] = dict(g20_weights)
    if "c60" in portfolio["signal"]["sleeves"]:
        result["c60"] = dict(c60_weights)
    return result


def _snapshot_market(cycle: PaperCycleInput) -> MarketSnapshot:
    prices = dict(cycle.mark_prices)
    return MarketSnapshot.create(
        decision_time=cycle.decision_time,
        data_cutoff=cycle.data_cutoff,
        prices=prices,
        funding={},
        features={
            "program_id": DUAL_ENGINE_PROGRAM_ID,
            "cycle_hash": cycle.cycle_hash,
            "g20_signal_day": cycle.g20_signal_day,
            "g20_rebalance_day": cycle.g20_rebalance_day,
        },
        exchange_rules_hash=canonical_hash({"symbol_rules": cycle.symbol_rules}),
        account_snapshot_hash=None,
        data_quality={
            "complete": cycle.market_data_complete,
            "blockers": cycle.blockers,
            "account_snapshot_linked": False,
        },
        source_hashes=cycle.source_hashes,
    )


def _initial_state(
    contract: DualEnginePaperContract,
    cycle: PaperCycleInput,
) -> dict[str, Any]:
    forward_not_before = aware_datetime(contract.forward_not_before)
    start = max(forward_not_before, aware_datetime(cycle.decision_time)).isoformat()
    core = {
        "schema_version": PAPER_STATE_SCHEMA_VERSION,
        "program_id": DUAL_ENGINE_PROGRAM_ID,
        "program_version": DUAL_ENGINE_PROGRAM_VERSION,
        "contract_hash": contract.contract_hash,
        "forward_start_at": start,
        "last_cycle_hash": None,
        "last_data_cutoff": None,
        "sequence": 0,
        "audit_last_hash": _ZERO_HASH,
        "pending_g20_target": None,
        "pending_g20_selected": None,
        "current_g20_target": None,
        "current_g20_selected": None,
        "current_d15_budget": None,
        "portfolios": {
            portfolio_id: _new_portfolio(
                portfolio_id,
                contract.initial_capital_usd_eq,
            )
            for portfolio_id in PAPER_PORTFOLIO_IDS
        },
    }
    return core | {"state_hash": canonical_hash(core)}


def _validate_state(state: Mapping[str, Any], contract: DualEnginePaperContract) -> None:
    required = {
        "schema_version", "program_id", "program_version", "contract_hash",
        "forward_start_at", "last_cycle_hash", "last_data_cutoff", "sequence",
        "audit_last_hash", "pending_g20_target", "pending_g20_selected",
        "current_g20_target", "current_g20_selected", "current_d15_budget",
        "portfolios", "state_hash",
    }
    if set(state) != required:
        raise DualEnginePaperRuntimeError("paper_state_fields_invalid")
    if state["schema_version"] != PAPER_STATE_SCHEMA_VERSION or state["program_id"] != DUAL_ENGINE_PROGRAM_ID or state["program_version"] != DUAL_ENGINE_PROGRAM_VERSION:
        raise DualEnginePaperRuntimeError("paper_state_identity_invalid")
    if state["contract_hash"] != contract.contract_hash:
        raise DualEnginePaperRuntimeError("paper_state_contract_mismatch")
    if set(state["portfolios"]) != set(PAPER_PORTFOLIO_IDS):
        raise DualEnginePaperRuntimeError("paper_state_portfolios_invalid")
    core = {key: value for key, value in state.items() if key != "state_hash"}
    if state["state_hash"] != canonical_hash(core):
        raise DualEnginePaperRuntimeError("paper_state_hash_invalid")


def _advance_portfolio(
    portfolio: dict[str, Any],
    *,
    budgets: Mapping[str, float],
    targets: Mapping[str, Mapping[str, float]],
    cycle: PaperCycleInput,
    contract: DualEnginePaperContract,
    cross_rebalance: bool,
) -> None:
    all_executions: list[dict[str, Any]] = []
    for layer_name in ("signal", "executable"):
        layer = portfolio[layer_name]
        if cross_rebalance:
            _, executions = _rebalance_layer(
                layer,
                sleeve_budgets=budgets,
                sleeve_targets=targets,
                marks=cycle.mark_prices,
                fills=cycle.fill_prices,
                rules=cycle.symbol_rules,
                contract=contract,
                signal=layer_name == "signal",
            )
        else:
            _, executions = _rebalance_single_sleeve(
                layer,
                sleeve_id="c60",
                target=targets.get("c60", {}),
                marks=cycle.mark_prices,
                fills=cycle.fill_prices,
                rules=cycle.symbol_rules,
                contract=contract,
                signal=layer_name == "signal",
            )
        if layer_name == "executable":
            all_executions.extend(executions)
    signal_equity = _layer_nav(portfolio["signal"], cycle.mark_prices)
    executable_equity = _layer_nav(portfolio["executable"], cycle.mark_prices)
    peak = max(float(portfolio["peak_executable_nav"]), executable_equity)
    drawdown = executable_equity / peak - 1.0
    maximum_drawdown = min(float(portfolio["max_drawdown_fraction"]), drawdown)
    portfolio["peak_executable_nav"] = peak
    portfolio["max_drawdown_fraction"] = maximum_drawdown
    portfolio["latest_executions"] = all_executions
    portfolio["history"].append({
        "marked_at": cycle.observed_at,
        "data_cutoff": cycle.data_cutoff,
        "signal_nav": signal_equity / float(portfolio["initial_capital"]),
        "executable_nav": executable_equity / float(portfolio["initial_capital"]),
        "executable_equity": executable_equity,
        "current_drawdown_fraction": drawdown,
        "cumulative_cost": float(portfolio["executable"]["cumulative_cost"]),
        "cumulative_stress_cost": float(
            portfolio["executable"]["cumulative_stress_cost"]
        ),
    })


def _portfolio_row(
    portfolio: Mapping[str, Any],
    *,
    budgets: Mapping[str, float],
    cycle: PaperCycleInput,
    g20: G20Decision,
    c60: C60Decision,
    d15_budget: float,
) -> dict[str, Any]:
    history = list(portfolio["history"])
    latest = history[-1]
    executable_positions = _aggregate_positions(portfolio["executable"])
    executable_equity = float(latest["executable_equity"])
    holdings = []
    for symbol, quantity in executable_positions.items():
        mark = float(cycle.mark_prices[symbol])
        market_value = quantity * mark
        holdings.append({
            "symbol": symbol,
            "quantity": quantity,
            "mark_price": mark,
            "market_value": market_value,
            "actual_weight": market_value / executable_equity,
        })
    cash = sum(
        float(sleeve["cash"])
        for sleeve in portfolio["executable"]["sleeves"].values()
    )
    return {
        "portfolio_id": portfolio["portfolio_id"],
        "label": _PORTFOLIO_LABELS[portfolio["portfolio_id"]],
        "status": "paper",
        "initial_capital": float(portfolio["initial_capital"]),
        "reporting_asset": "USD_EQ",
        "nav": {
            "signal": float(latest["signal_nav"]),
            "executable": float(latest["executable_nav"]),
            "portfolio_realized": None,
            "portfolio_realized_status": "unavailable_no_real_fills",
            "since_start_return_fraction": float(latest["executable_nav"]) - 1.0,
            "current_drawdown_fraction": float(latest["current_drawdown_fraction"]),
            "max_drawdown_fraction": float(portfolio["max_drawdown_fraction"]),
            "cumulative_cost": float(latest["cumulative_cost"]),
            "cumulative_stress_cost": float(latest["cumulative_stress_cost"]),
            "points": [
                {
                    "marked_at": row["marked_at"],
                    "signal": row["signal_nav"],
                    "executable": row["executable_nav"],
                }
                for row in history
            ],
        },
        "allocation": {
            "g20_budget": float(budgets.get("g20", 0.0)),
            "c60_budget": float(budgets.get("c60", 0.0)),
            "cash": cash,
            "cash_weight": cash / executable_equity,
        },
        "holdings": holdings,
        "latest_execution": {
            "count": len(portfolio["latest_executions"]),
            "orders_routed": False,
            "fills": list(portfolio["latest_executions"]),
        },
        "latest_decision": {
            "g20_selected": g20.selected_symbol,
            "c60_candidates": list(c60.candidates),
            "btc_system_gate": c60.btc_system_gate,
            "eligible_count": c60.eligible_count,
            "volatility_scalar": c60.volatility_scalar,
            "d15_c60_budget": d15_budget,
        },
    }


def _build_snapshot(
    state: Mapping[str, Any],
    *,
    contract: DualEnginePaperContract,
    cycle: PaperCycleInput,
    g20: G20Decision,
    c60: C60Decision,
    intents: Sequence[Any],
) -> PaperProgramSnapshot:
    d15_budget = float(state["current_d15_budget"])
    rows = tuple(
        _portfolio_row(
            state["portfolios"][portfolio_id],
            budgets=_budgets(portfolio_id, d15_budget),
            cycle=cycle,
            g20=g20,
            c60=c60,
            d15_budget=d15_budget,
        )
        for portfolio_id in PAPER_PORTFOLIO_IDS
    )
    latest_decision = {
        "decision_time": cycle.decision_time,
        "data_cutoff": cycle.data_cutoff,
        "cycle_hash": cycle.cycle_hash,
        "g20": g20.as_dict(),
        "c60": c60.as_dict(),
        "d15_c60_budget": d15_budget,
        "intent_ids": [intent.decision_id for intent in intents],
        "intent_hashes": [intent.intent_hash for intent in intents],
        "reason_codes": [
            "PAPER_ONLY",
            "ORDERS_NOT_AUTHORIZED",
            "USD_USDT_PARITY_ASSUMED",
            "OWNER_AUTHORIZED_YTD_REPLAY",
        ],
    }
    return PaperProgramSnapshot.create(
        generated_at=cycle.observed_at,
        data_cutoff=cycle.data_cutoff,
        forward_start_at=str(state["forward_start_at"]),
        status="paper",
        contract_hash=contract.contract_hash,
        source_hashes=dict(cycle.source_hashes) | {
            "paper_state": str(state["state_hash"]),
        },
        portfolios=rows,
        benchmarks=(),
        history_reference={
            "status": "owner_authorized_ytd_replay",
            "start_at": "2026-01-01T00:00:00+00:00",
            "method": "tiingo_daily_open_and_binance_minute",
            "curve_role": "simulated_not_realized",
        },
        latest_decision=latest_decision,
        audit_last_hash=str(state["audit_last_hash"]),
        audit_row_count=int(state["sequence"]),
    )


def _append_audit(path: Path, row: Mapping[str, Any]) -> None:
    _ensure_private_directory(path.parent)
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, _canonical_bytes(row))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _validate_audit(path: Path, state: Mapping[str, Any]) -> None:
    sequence = int(state["sequence"])
    if sequence == 0 and not path.exists():
        return
    if path.is_symlink() or not path.is_file():
        raise DualEnginePaperRuntimeError("paper_audit_file_invalid")
    if stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode) != 0o600:
        raise DualEnginePaperRuntimeError("paper_audit_mode_invalid")
    lines = path.read_bytes().splitlines(keepends=True)
    if len(lines) != sequence:
        raise DualEnginePaperRuntimeError("paper_audit_count_invalid")
    previous = _ZERO_HASH
    latest: Mapping[str, Any] | None = None
    expected_fields = {
        "schema_version", "sequence", "event_type", "observed_at",
        "cycle_hash", "state_content_hash", "previous_hash",
        "orders_authorized", "orders_routed", "row_hash",
    }
    for expected_sequence, raw in enumerate(lines, start=1):
        def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise DualEnginePaperRuntimeError(
                        f"paper_audit_duplicate_key:{key}"
                    )
                result[key] = value
            return result
        try:
            row = json.loads(raw, object_pairs_hook=reject_duplicates)
        except DualEnginePaperRuntimeError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DualEnginePaperRuntimeError("paper_audit_json_invalid") from exc
        if (
            not isinstance(row, dict)
            or set(row) != expected_fields
            or _canonical_bytes(row) != raw
            or row["schema_version"] != PAPER_STATE_SCHEMA_VERSION
            or row["sequence"] != expected_sequence
            or row["event_type"] != "dual_engine_paper_cycle"
            or row["previous_hash"] != previous
            or row["orders_authorized"] is not False
            or row["orders_routed"] is not False
        ):
            raise DualEnginePaperRuntimeError("paper_audit_row_invalid")
        audit_core = {key: value for key, value in row.items() if key != "row_hash"}
        if row["row_hash"] != canonical_hash(audit_core):
            raise DualEnginePaperRuntimeError("paper_audit_hash_invalid")
        previous = str(row["row_hash"])
        latest = row
    if latest is None or previous != state["audit_last_hash"]:
        raise DualEnginePaperRuntimeError("paper_audit_head_invalid")
    state_content = {
        key: value
        for key, value in state.items()
        if key not in {"state_hash", "audit_last_hash"}
    }
    if latest["state_content_hash"] != canonical_hash(state_content):
        raise DualEnginePaperRuntimeError("paper_audit_state_mismatch")


def run_paper_cycle(
    root: str | Path,
    cycle: PaperCycleInput,
    *,
    contract: DualEnginePaperContract | None = None,
) -> PaperProgramSnapshot:
    """Advance all four portfolios once and atomically publish a verified snapshot."""

    contract = contract or DualEnginePaperContract.frozen_v1()
    contract.validate()
    cycle.validate()
    if not cycle.market_data_complete:
        raise DualEnginePaperRuntimeError(
            "paper_cycle_market_data_blocked:" + ",".join(cycle.blockers)
        )
    state_root = Path(root).expanduser().resolve()
    if state_root == Path("/") or not state_root.is_absolute():
        raise DualEnginePaperRuntimeError("paper_state_root_invalid")
    _ensure_private_directory(state_root)
    state_path = state_root / "state" / "program.json"
    audit_path = state_root / "state" / "audit.jsonl"
    snapshot_path = state_root / "current" / "paper_program_snapshot.json"
    lock_path = state_root / "paper.lock"
    with lock_path.open("a+") as lock_handle:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        if state_path.exists():
            state = _read_json(state_path, name="paper_state")
            _validate_state(state, contract)
            _validate_audit(audit_path, state)
        else:
            state = _initial_state(contract, cycle)
        if state["last_cycle_hash"] == cycle.cycle_hash:
            existing = PaperProgramSnapshot.from_dict(
                _read_json(snapshot_path, name="paper_snapshot")
            )
            if (
                existing.source_hashes.get("paper_state") != state["state_hash"]
                or existing.audit_last_hash != state["audit_last_hash"]
                or existing.audit_row_count != state["sequence"]
            ):
                raise DualEnginePaperRuntimeError(
                    "paper_snapshot_state_mismatch"
                )
            return existing
        if state["last_data_cutoff"] is not None and aware_datetime(cycle.data_cutoff) <= aware_datetime(str(state["last_data_cutoff"])):
            raise DualEnginePaperRuntimeError("paper_cycle_not_forward")

        g20 = build_g20_decision(cycle.proxy_closes, contract=contract)
        c60 = build_c60_decision(cycle.crypto_closes, contract=contract)
        initializing = state["current_g20_target"] is None
        if cycle.g20_signal_day or initializing:
            state["pending_g20_target"] = dict(g20.target_weights)
            state["pending_g20_selected"] = g20.selected_symbol
        if cycle.g20_rebalance_day or initializing:
            if state["pending_g20_target"] is None:
                raise DualEnginePaperRuntimeError("paper_g20_pending_target_missing")
            state["current_g20_target"] = dict(state["pending_g20_target"])
            state["current_g20_selected"] = str(state["pending_g20_selected"])
            state["pending_g20_target"] = None
            state["pending_g20_selected"] = None
            state["current_d15_budget"] = d15_c60_budget(c60, contract=contract)
        elif state["current_d15_budget"] is None:
            state["current_d15_budget"] = d15_c60_budget(c60, contract=contract)

        snapshot = _snapshot_market(cycle)
        current_g20 = G20Decision(
            selected_symbol=str(state["current_g20_selected"]),
            momentum_63d=g20.momentum_63d,
            target_weights=dict(state["current_g20_target"]),
            state_hash=canonical_hash({
                "selected_symbol": state["current_g20_selected"],
                "target_weights": state["current_g20_target"],
                "source_state_hash": g20.state_hash,
            }),
        )
        intents = build_strategy_intents(
            snapshot,
            current_g20,
            c60,
            evidence_hash=cycle.cycle_hash,
        )

        d15_budget = float(state["current_d15_budget"])
        for portfolio_id in PAPER_PORTFOLIO_IDS:
            portfolio = state["portfolios"][portfolio_id]
            targets = _targets(
                portfolio,
                state["current_g20_target"],
                c60.target_weights,
            )
            _advance_portfolio(
                portfolio,
                budgets=_budgets(portfolio_id, d15_budget),
                targets=targets,
                cycle=cycle,
                contract=contract,
                cross_rebalance=bool(cycle.g20_rebalance_day or initializing),
            )

        next_sequence = int(state["sequence"]) + 1
        state["last_cycle_hash"] = cycle.cycle_hash
        state["last_data_cutoff"] = cycle.data_cutoff
        state["sequence"] = next_sequence
        state_content = {
            key: value
            for key, value in state.items()
            if key not in {"state_hash", "audit_last_hash"}
        }
        content_hash = canonical_hash(state_content)
        audit_core = {
            "schema_version": PAPER_STATE_SCHEMA_VERSION,
            "sequence": next_sequence,
            "event_type": "dual_engine_paper_cycle",
            "observed_at": cycle.observed_at,
            "cycle_hash": cycle.cycle_hash,
            "state_content_hash": content_hash,
            "previous_hash": state["audit_last_hash"],
            "orders_authorized": False,
            "orders_routed": False,
        }
        audit_row = audit_core | {"row_hash": canonical_hash(audit_core)}
        state["audit_last_hash"] = audit_row["row_hash"]
        state_without_hash = {key: value for key, value in state.items() if key != "state_hash"}
        state["state_hash"] = canonical_hash(state_without_hash)
        _validate_state(state, contract)
        paper_snapshot = _build_snapshot(
            state,
            contract=contract,
            cycle=cycle,
            g20=current_g20,
            c60=c60,
            intents=intents,
        )
        _append_audit(audit_path, audit_row)
        _atomic_json(state_path, state)
        _atomic_json(snapshot_path, paper_snapshot.as_dict())
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        return paper_snapshot


def read_paper_snapshot(root: str | Path) -> PaperProgramSnapshot:
    path = Path(root).expanduser().resolve() / "current" / "paper_program_snapshot.json"
    return PaperProgramSnapshot.from_dict(_read_json(path, name="paper_snapshot"))
