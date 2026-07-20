"""Independent, order-free paper runtime for the MiniTrend UM live-pilot candidate."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.grid.data import Bar, Funding
from qount.mini_trend.backtest import align_bars
from qount.mini_trend.forward import TOP3
from qount.mini_trend.futures_funding_veto_shadow_forward import (
    complete_forward_input_prefix,
)
from qount.mini_trend.futures_funding_veto import FundingVetoRegimeSelector
from qount.mini_trend.futures_recovery import canonical_hash, selected_um_rules
from qount.mini_trend.futures_recovery_backtest import VariantResult, run_variant
from qount.mini_trend.futures_risk_tier import risk_tier_config
from qount.mini_trend.live_pilot import LIVE_PILOT_CONTRACT
from qount.mini_trend.live_pilot import append_live_pilot_journal
from qount.mini_trend.live_pilot import verify_live_pilot_journal
from qount.models import utc_now
from qount.settings import Settings


PILOT_PAPER_RUNTIME_VERSION = "mini_trend_um_pilot_paper_runtime_v0.4"
_DAY_MS = 86_400_000


@dataclass(frozen=True)
class PilotPaperProtocol:
    strategy: str = "MiniTrend-UM-Base-v0.2"
    paper_start_date: str = "2026-07-19"
    capital_usdt: float = 300.0
    warmup_completed_bars: int = 200
    minimum_daily_funding_settlements_per_symbol: int = 3

    @property
    def contract_basis(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "live_pilot_contract_hash": LIVE_PILOT_CONTRACT.contract_hash,
            "paper_start_date": self.paper_start_date,
            "capital_usdt": self.capital_usdt,
            "warmup_completed_bars": self.warmup_completed_bars,
            "minimum_daily_funding_settlements_per_symbol": (
                self.minimum_daily_funding_settlements_per_symbol
            ),
            "market": "um",
            "interval": "1d",
            "universe": list(TOP3),
            "initial_state": "all_cash",
            "private_exchange_data": False,
            "orders_allowed": False,
            "shadow_strategies": [
                LIVE_PILOT_CONTRACT.shadow_candidate,
                LIVE_PILOT_CONTRACT.secondary_shadow_candidate,
            ],
            "shadow_strategies_control_orders": False,
        }

    @property
    def contract_hash(self) -> str:
        return canonical_hash(self.contract_basis)


PILOT_PAPER_PROTOCOL = PilotPaperProtocol()


@dataclass(frozen=True)
class PilotPaperReplay:
    report: dict[str, Any]
    journal_rows: tuple[dict[str, Any], ...]


def _data_hash(
    bars: Mapping[str, Sequence[Bar]],
    funding: Mapping[str, Sequence[Funding]],
) -> str:
    return canonical_hash(
        {
            "bars": {
                symbol: [
                    [row.ts_ms, row.open, row.high, row.low, row.close, row.volume]
                    for row in bars[symbol]
                ]
                for symbol in TOP3
            },
            "funding": {
                symbol: [[row.ts_ms, row.rate] for row in funding.get(symbol, [])]
                for symbol in TOP3
            },
        }
    )


def _gap_count(dates: Sequence[str]) -> int:
    parsed = [dt.date.fromisoformat(value) for value in dates]
    return sum(max((right - left).days - 1, 0) for left, right in zip(parsed, parsed[1:]))


def _shadow_path_summary(
    result: VariantResult,
    *,
    row_count: int,
    initial_capital: float,
) -> dict[str, Any]:
    rows = result.equity[:row_count]
    values = [initial_capital] + [float(row["equity"]) for row in rows]
    peak = initial_capital
    maximum_drawdown = 0.0
    drawdown_breached = False
    for value in values:
        peak = max(peak, value)
        drawdown = (peak - value) / peak * 100.0 if peak > 0.0 else 0.0
        maximum_drawdown = max(maximum_drawdown, drawdown)
        drawdown_breached = drawdown_breached or (
            drawdown >= LIVE_PILOT_CONTRACT.maximum_pilot_drawdown_pct
        )
    return {
        "paper_days": len(rows),
        "start_equity_usdt": initial_capital,
        "end_equity_usdt": values[-1],
        "return_pct": (values[-1] / initial_capital - 1.0) * 100.0,
        "maximum_drawdown_pct": maximum_drawdown,
        "pilot_drawdown_breached": drawdown_breached,
        "maximum_effective_gross": max(
            (float(row["gross"]) for row in rows),
            default=0.0,
        ),
        "order_intents": sum(int(row["orders"]) for row in rows),
        "controls_live_orders": False,
    }


def _empty_shadow_path_summary(initial_capital: float) -> dict[str, Any]:
    return {
        "paper_days": 0,
        "start_equity_usdt": initial_capital,
        "end_equity_usdt": initial_capital,
        "return_pct": 0.0,
        "maximum_drawdown_pct": 0.0,
        "pilot_drawdown_breached": False,
        "maximum_effective_gross": 0.0,
        "order_intents": 0,
        "controls_live_orders": False,
    }


def build_pilot_paper_replay(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    rules_artifact: Mapping[str, Any],
    *,
    protocol: PilotPaperProtocol | None = None,
) -> PilotPaperReplay:
    protocol = protocol or PILOT_PAPER_PROTOCOL
    if protocol.strategy != LIVE_PILOT_CONTRACT.strategy:
        raise ValueError("paper runtime strategy does not match the live-pilot contract")
    if not 0.0 < protocol.capital_usdt <= LIVE_PILOT_CONTRACT.maximum_capital_usdt:
        raise ValueError("paper runtime capital exceeds the live-pilot cap")

    rules, rules_hash = selected_um_rules(rules_artifact)
    bars = align_bars(bars_by_symbol, TOP3)
    common_dates = [row.date for row in bars["BTCUSDT"]]
    forward_dates = [date for date in common_dates if date >= protocol.paper_start_date]
    start_index = (
        next(
            index
            for index, date in enumerate(common_dates)
            if date >= protocol.paper_start_date
        )
        if forward_dates
        else len(common_dates)
    )
    input_prefix = complete_forward_input_prefix(
        bars,
        funding_by_symbol,
        start_index=start_index,
        minimum_settlements=protocol.minimum_daily_funding_settlements_per_symbol,
    )
    complete_pairs = int(input_prefix["complete_prefix_pair_count"])
    evaluated_dates = common_dates[start_index : start_index + complete_pairs + 1]
    report: dict[str, Any] = {
        "schema_version": PILOT_PAPER_RUNTIME_VERSION,
        "artifact_type": "mini_trend_um_pilot_paper_runtime",
        "created_at": utc_now().isoformat(),
        "meta": {
            "paper_only": True,
            "private_exchange_data": False,
            "private_api_order_attempted": False,
            "orders_allowed": False,
            "live_orders_allowed": False,
        },
        "contract": protocol.contract_basis
        | {"paper_runtime_contract_hash": protocol.contract_hash},
        "exchange_rules_hash": rules_hash,
        "data": {
            "common_bar_count": len(common_dates),
            "first_common_date": common_dates[0] if common_dates else None,
            "last_common_date": common_dates[-1] if common_dates else None,
            "paper_start_date": protocol.paper_start_date,
            "forward_input_bar_count": len(forward_dates),
            "complete_prefix_pair_count": complete_pairs,
            "evaluation_gap_count": _gap_count(evaluated_dates),
            "first_incomplete_pair": input_prefix["first_incomplete_pair"],
            "data_hash": _data_hash(bars, funding_by_symbol),
        },
        "evaluation": {
            "paper_days": 0,
            "active_bars": 0,
            "order_intents": 0,
            "start_equity_usdt": protocol.capital_usdt,
            "end_equity_usdt": protocol.capital_usdt,
            "maximum_drawdown_pct": 0.0,
            "halted": False,
            "risk_flags": [],
            "shadow_paths": {
                strategy: _empty_shadow_path_summary(protocol.capital_usdt)
                for strategy in (
                    LIVE_PILOT_CONTRACT.shadow_candidate,
                    LIVE_PILOT_CONTRACT.secondary_shadow_candidate,
                )
            },
        },
        "diagnostics": {
            "gates": {},
            "blockers": ["no_complete_paper_decision_outcome_pair"],
            "verdict": "await_paper_inputs",
            "paper_evidence_complete": False,
            "dry_or_live_allowed": False,
        },
    }
    if complete_pairs == 0:
        return PilotPaperReplay(report=report, journal_rows=())
    if start_index < protocol.warmup_completed_bars:
        report["diagnostics"]["blockers"] = ["insufficient_signal_warmup"]
        return PilotPaperReplay(report=report, journal_rows=())

    slice_start = start_index - protocol.warmup_completed_bars
    slice_end = start_index + complete_pairs + 1
    sliced_bars = {
        symbol: rows[slice_start:slice_end] for symbol, rows in bars.items()
    }
    result = run_variant(
        sliced_bars,
        funding_by_symbol,
        rules,
        recovery_enabled=False,
        daily_chandelier_atr_multiple=(
            LIVE_PILOT_CONTRACT.daily_chandelier_atr_multiple
        ),
        stop_cooldown_completed_bars=(
            LIVE_PILOT_CONTRACT.stop_cooldown_completed_bars
        ),
        capital_usdt=protocol.capital_usdt,
    )
    risk_shadow = run_variant(
        sliced_bars,
        funding_by_symbol,
        rules,
        recovery_enabled=False,
        base_config=risk_tier_config(),
        daily_chandelier_atr_multiple=(
            LIVE_PILOT_CONTRACT.daily_chandelier_atr_multiple
        ),
        stop_cooldown_completed_bars=(
            LIVE_PILOT_CONTRACT.stop_cooldown_completed_bars
        ),
        gross_cap_policy="renormalize_active_targets_with_filter_floors",
        capital_usdt=protocol.capital_usdt,
    )
    funding_selector = FundingVetoRegimeSelector(funding_by_symbol)
    funding_shadow = run_variant(
        sliced_bars,
        funding_by_symbol,
        rules,
        recovery_enabled=False,
        base_config_selector=funding_selector,
        base_config_feedback=funding_selector.observe_stops,
        daily_chandelier_atr_multiple=(
            LIVE_PILOT_CONTRACT.daily_chandelier_atr_multiple
        ),
        stop_cooldown_completed_bars=(
            LIVE_PILOT_CONTRACT.stop_cooldown_completed_bars
        ),
        gross_cap_policy="renormalize_active_targets_with_filter_floors",
        capital_usdt=protocol.capital_usdt,
    )
    shadow_results = {
        LIVE_PILOT_CONTRACT.shadow_candidate: risk_shadow,
        LIVE_PILOT_CONTRACT.secondary_shadow_candidate: funding_shadow,
    }
    if len(result.equity) != complete_pairs:
        raise ValueError("paper replay did not consume the complete input prefix")
    for strategy, shadow in shadow_results.items():
        if len(shadow.equity) != complete_pairs:
            raise ValueError(f"{strategy} shadow did not consume the complete input prefix")
        if [row["decision_date"] for row in shadow.equity] != [
            row["decision_date"] for row in result.equity
        ]:
            raise ValueError(f"{strategy} shadow decisions are not aligned with Base")
    if result.equity[0]["decision_date"] < protocol.paper_start_date:
        raise ValueError("paper replay contains a pre-start decision")

    peak = protocol.capital_usdt
    journal_rows: list[dict[str, Any]] = []
    risk_flags: list[str] = []
    shadow_peaks = {
        strategy: protocol.capital_usdt for strategy in shadow_results
    }
    for index, source in enumerate(result.equity):
        equity = float(source["equity"])
        peak = max(peak, equity)
        daily_loss_pct = max(-float(source["net_return"]) * 100.0, 0.0)
        drawdown_pct = (peak - equity) / peak * 100.0 if peak > 0.0 else 0.0
        row_flags = []
        if (
            LIVE_PILOT_CONTRACT.maximum_daily_loss_pct is not None
            and daily_loss_pct >= LIVE_PILOT_CONTRACT.maximum_daily_loss_pct
        ):
            row_flags.append("daily_loss_halt")
        if drawdown_pct >= LIVE_PILOT_CONTRACT.maximum_pilot_drawdown_pct:
            row_flags.append("pilot_drawdown_halt")
        enriched = dict(source)
        enriched["daily_loss_pct"] = daily_loss_pct
        enriched["pilot_drawdown_pct"] = drawdown_pct
        enriched["shadow_paths"] = {}
        for strategy, shadow_result in shadow_results.items():
            shadow = shadow_result.equity[index]
            shadow_equity = float(shadow["equity"])
            shadow_peaks[strategy] = max(shadow_peaks[strategy], shadow_equity)
            shadow_drawdown = (
                (shadow_peaks[strategy] - shadow_equity)
                / shadow_peaks[strategy]
                * 100.0
                if shadow_peaks[strategy] > 0.0
                else 0.0
            )
            enriched["shadow_paths"][strategy] = {
                "equity_usdt": shadow_equity,
                "gross": float(shadow["gross"]),
                "turnover": float(shadow["turnover"]),
                "orders": int(shadow["orders"]),
                "risk_stage": shadow["risk_stage"],
                "gross_price_return": float(shadow["gross_price_return"]),
                "funding_return": float(shadow["funding_return"]),
                "trading_cost_return": float(shadow["trading_cost_return"]),
                "net_return": float(shadow["net_return"]),
                "pilot_drawdown_pct": shadow_drawdown,
                "pilot_drawdown_breached": (
                    shadow_drawdown
                    >= LIVE_PILOT_CONTRACT.maximum_pilot_drawdown_pct
                ),
                "execution_state": shadow["execution_state"],
                "controls_live_orders": False,
            }
        enriched["risk_flags"] = row_flags
        enriched["halted_after_outcome"] = bool(row_flags)
        enriched["replay_row_hash"] = canonical_hash(enriched)
        journal_rows.append(enriched)
        risk_flags.extend(row_flags)
        if row_flags:
            break

    values = [protocol.capital_usdt] + [float(row["equity"]) for row in journal_rows]
    peak = values[0]
    maximum_drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0.0:
            maximum_drawdown = max(maximum_drawdown, (peak - value) / peak * 100.0)
    paper_days = len(journal_rows)
    gates = {
        "complete_price_and_funding_prefix": len(result.equity) == complete_pairs,
        "contiguous_evaluation_dates": report["data"]["evaluation_gap_count"] == 0,
        "maximum_effective_gross": all(
            float(row["gross"]) <= LIVE_PILOT_CONTRACT.maximum_effective_gross + 1e-12
            for row in journal_rows
        ),
        "no_duplicate_decisions": result.metrics["duplicate_decision_count"] == 0,
        "no_same_bar_stop_reentry": result.metrics["same_bar_stop_reentry_count"] == 0,
        "no_risk_halt": not risk_flags,
        "minimum_paper_days": paper_days >= LIVE_PILOT_CONTRACT.minimum_paper_days,
    }
    report["evaluation"] = {
        "paper_days": paper_days,
        "active_bars": sum(float(row["gross"]) > 0.0 for row in journal_rows),
        "order_intents": sum(int(row["orders"]) for row in journal_rows),
        "start_equity_usdt": protocol.capital_usdt,
        "end_equity_usdt": values[-1],
        "maximum_drawdown_pct": maximum_drawdown,
        "halted": bool(risk_flags),
        "risk_flags": sorted(set(risk_flags)),
        "shadow_paths": {
            strategy: _shadow_path_summary(
                shadow,
                row_count=paper_days,
                initial_capital=protocol.capital_usdt,
            )
            for strategy, shadow in shadow_results.items()
        },
    }
    report["diagnostics"]["gates"] = gates
    report["diagnostics"]["blockers"] = [
        name for name, passed in gates.items() if not passed
    ]
    report["diagnostics"]["paper_evidence_complete"] = all(gates.values())
    report["diagnostics"]["verdict"] = (
        "paper_risk_halted"
        if risk_flags
        else "review_dry_run_readiness"
        if all(gates.values())
        else "collect_paper_evidence"
    )
    return PilotPaperReplay(report=report, journal_rows=tuple(journal_rows))


def _load_existing_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise ValueError("paper journal contains a non-object row")
                rows.append(payload)
    return rows


def reconcile_pilot_paper_journal(
    path: str | Path,
    replay_rows: Sequence[Mapping[str, Any]],
    *,
    protocol: PilotPaperProtocol | None = None,
) -> dict[str, Any]:
    protocol = protocol or PILOT_PAPER_PROTOCOL
    target = Path(path).expanduser()
    current = verify_live_pilot_journal(target)
    expected_dates = [str(row["decision_date"]) for row in replay_rows]
    if current["decision_dates"] != expected_dates[: current["row_count"]]:
        raise ValueError("paper journal is not a prefix of the frozen replay")
    existing = _load_existing_rows(target)
    for index, row in enumerate(existing):
        expected_hash = replay_rows[index]["replay_row_hash"]
        actual_hash = row.get("execution_state", {}).get("replay_row_hash")
        if actual_hash != expected_hash:
            raise ValueError("paper journal replay hash mismatch")

    appended = 0
    previous_weights = {symbol: 0.0 for symbol in TOP3}
    for index, source in enumerate(replay_rows):
        target_weights = {
            symbol: float(source["execution_state"]["target_weights"][symbol])
            for symbol in TOP3
        }
        before_equity = (
            protocol.capital_usdt
            if index == 0
            else float(replay_rows[index - 1]["equity"])
        )
        intents = []
        for symbol in TOP3:
            delta = target_weights[symbol] - previous_weights[symbol]
            if abs(delta) <= 1e-12:
                continue
            intents.append(
                {
                    "symbol": symbol,
                    "side": "buy" if delta > 0.0 else "sell",
                    "weight_delta": delta,
                    "notional_usdt": abs(delta) * before_equity,
                }
            )
        if len(intents) != int(source["orders"]):
            raise ValueError("paper order-intent count does not match the replay")
        if index >= current["row_count"]:
            execution_state = dict(source["execution_state"])
            execution_state.update(
                {
                    "outcome_date": source["outcome_date"],
                    "replay_row_hash": source["replay_row_hash"],
                    "halted": bool(source["halted_after_outcome"]),
                    "flatten_required": bool(source["halted_after_outcome"]),
                    "shadow_paths": source["shadow_paths"],
                }
            )
            row = {
                "decision_date": source["decision_date"],
                "recorded_at": utc_now().isoformat(),
                "mode": "paper",
                "strategy": protocol.strategy,
                "capital_cap_usdt": protocol.capital_usdt,
                "wallet_balance_usdt": float(source["equity"]),
                "equity_usdt": float(source["equity"]),
                "desired_weights": target_weights,
                "actual_weights": target_weights,
                "order_intents": intents,
                "order_results": [intent | {"status": "paper_filled"} for intent in intents],
                "funding_pnl_usdt": before_equity * float(source["funding_return"]),
                "fees_usdt": before_equity * -float(source["trading_cost_return"]),
                "execution_state": execution_state,
                "risk_flags": list(source["risk_flags"]),
            }
            append_live_pilot_journal(target, row)
            appended += 1
        previous_weights = target_weights
    verified = verify_live_pilot_journal(target)
    return {
        **verified,
        "journal_path": str(target.resolve()),
        "appended_rows": appended,
    }


def write_pilot_paper_runtime_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-pilot-paper-runtime",
        path_key="artifact_path",
        default_filename="mini_trend_um_pilot_paper_runtime.json",
        explicit_path=explicit_path,
    )
