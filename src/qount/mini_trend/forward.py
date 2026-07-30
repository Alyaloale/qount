"""Frozen low-frequency MiniTrend TOP3 forward research protocol."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.research_data.market_data import Bar
from qount.mini_trend.backtest import align_bars, research_filters, run_backtest
from qount.mini_trend.config import MiniTrendConfig
from qount.mini_trend.models import SymbolFilter
from qount.mini_trend.scorecard import max_drawdown_pct
from qount.mini_trend.signals import target_weights
from qount.models import utc_now
from qount.settings import Settings


MINI_TREND_FORWARD_PREREG_VERSION = "mini_trend_top3_forward_preregistration_v0.1"
MINI_TREND_FORWARD_VERSION = "mini_trend_top3_forward_v0.1"
TOP3 = ("BTCUSDT", "ETHUSDT", "BNBUSDT")


def _canonical_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def frozen_top3_config() -> MiniTrendConfig:
    return MiniTrendConfig(universe=TOP3, gate_symbol="BTCUSDT")


@dataclass(frozen=True)
class FrozenTop3ForwardProtocol:
    warmup_start_month: str = "2025-01"
    anchor_end_date: str = "2026-06-30"
    evaluation_start_date: str = "2026-07-01"
    minimum_forward_bars: int = 60
    minimum_active_bars: int = 10
    maximum_forward_drawdown_pct: float = 15.0
    maximum_fee_to_notional_pct: float = 0.12
    taker_fee_bps: float = 10.0
    slippage_bps: float = 2.0
    interval: str = "1d"
    market: str = "spot"
    benchmark: str = "BTC buy-and-hold plus TOP3 equal-weight buy-and-hold"
    holdout_role: str = "forward_monitoring"

    @property
    def contract_basis(self) -> dict[str, Any]:
        return {
            "strategy_config": asdict(frozen_top3_config()),
            "data": {
                "source": "https://data.binance.vision",
                "market": self.market,
                "interval": self.interval,
                "warmup_start_month": self.warmup_start_month,
                "anchor_end_date": self.anchor_end_date,
                "evaluation_start_date": self.evaluation_start_date,
                "completed_daily_bars_only": True,
            },
            "costs": {
                "taker_fee_bps": self.taker_fee_bps,
                "slippage_bps": self.slippage_bps,
            },
            "benchmark": self.benchmark,
        }

    @property
    def contract_hash(self) -> str:
        return _canonical_hash(self.contract_basis)

    @property
    def protocol_basis(self) -> dict[str, Any]:
        return {
            "contract_hash": self.contract_hash,
            "holdout_role": self.holdout_role,
            "minimum_forward_bars": self.minimum_forward_bars,
            "minimum_active_bars": self.minimum_active_bars,
            "maximum_forward_drawdown_pct": self.maximum_forward_drawdown_pct,
            "maximum_fee_to_notional_pct": self.maximum_fee_to_notional_pct,
            "required_min_notional_coverage": 1.0,
            "required_blocked_symbol_count": 0,
            "trial_count": 1,
            "parameter_search_allowed": False,
            "universe_search_allowed": False,
            "high_frequency_data_allowed": False,
            "shorting_allowed": False,
            "leverage_allowed": False,
            "paper_or_live_allowed": False,
            "interpretation": (
                "This protocol tests low-beta trend participation and execution readiness; "
                "it does not claim directional alpha from a short forward window."
            ),
        }

    @property
    def protocol_hash(self) -> str:
        return _canonical_hash(self.protocol_basis)


FROZEN_TOP3_FORWARD_PROTOCOL = FrozenTop3ForwardProtocol()


def _selected_rules(rules_artifact: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], str]:
    if rules_artifact.get("market") != "spot":
        raise ValueError("MiniTrend forward requires spot exchange rules")
    if rules_artifact.get("source_type") != "runtime_exchange_info":
        raise ValueError("MiniTrend forward requires runtime exchangeInfo rules")
    rows = {
        str(row.get("symbol", "")).upper(): dict(row)
        for row in rules_artifact.get("rules", [])
        if isinstance(row, Mapping) and row.get("symbol")
    }
    missing = sorted(set(TOP3) - set(rows))
    if missing:
        raise ValueError(f"exchange rules missing TOP3 symbols: {','.join(missing)}")
    selected = {symbol: rows[symbol] for symbol in TOP3}
    non_trading = [symbol for symbol, row in selected.items() if row.get("status") != "TRADING"]
    if non_trading:
        raise ValueError(f"TOP3 symbols not trading: {','.join(non_trading)}")
    return selected, _canonical_hash(selected)


def _mini_trend_filters(rules_artifact: Mapping[str, Any]) -> dict[str, SymbolFilter]:
    selected, _ = _selected_rules(rules_artifact)
    filters: dict[str, SymbolFilter] = {}
    for symbol, row in selected.items():
        step = float(row.get("market_step_size") or 0.0) or float(row.get("step_size") or 0.0)
        filters[symbol] = SymbolFilter(
            amount_step=step,
            min_amount=float(row.get("min_qty") or 0.0),
            min_notional=float(row.get("min_notional") or 0.0),
        )
    return filters


def load_anchor_evidence(anchor_dir: str | Path) -> dict[str, Any]:
    root = Path(anchor_dir).expanduser()
    paths = {
        "config": root / "config.json",
        "summary": root / "summary.json",
        "equity": root / "equity.jsonl",
    }
    missing = [name for name, path in paths.items() if not path.exists()]
    if missing:
        raise ValueError(f"anchor artifact missing files: {','.join(missing)}")
    config = json.loads(paths["config"].read_text(encoding="utf-8"))
    summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
    normalized_frozen_config = json.loads(json.dumps(asdict(frozen_top3_config())))
    if config != normalized_frozen_config:
        raise ValueError("anchor config does not match frozen TOP3 config")
    if summary.get("end") != FROZEN_TOP3_FORWARD_PROTOCOL.anchor_end_date:
        raise ValueError("anchor end date does not match frozen protocol")
    return {
        "artifact_dir": str(root),
        "config_sha256": _file_sha256(paths["config"]),
        "summary_sha256": _file_sha256(paths["summary"]),
        "equity_sha256": _file_sha256(paths["equity"]),
        "start": summary.get("start"),
        "end": summary.get("end"),
        "final_equity": float(summary["final_equity"]),
        "total_return_pct": float(summary["total_return_pct"]),
        "scorecard_verdict": summary.get("scorecard_verdict"),
    }


def build_forward_preregistration(
    rules_artifact: Mapping[str, Any],
    anchor_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    protocol = FROZEN_TOP3_FORWARD_PROTOCOL
    selected_rules, rules_hash = _selected_rules(rules_artifact)
    return {
        "schema_version": MINI_TREND_FORWARD_PREREG_VERSION,
        "artifact_type": "mini_trend_top3_forward_preregistration",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "low_frequency_only": True,
            "strategy_results_evaluated": False,
            "private_exchange_data": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "decision_contract": {
            **protocol.contract_basis,
            "contract_hash": protocol.contract_hash,
        },
        "protocol": {
            **protocol.protocol_basis,
            "protocol_hash": protocol.protocol_hash,
        },
        "exchange_rules": {
            "selected_rules_hash": rules_hash,
            "raw_exchange_info_hash": rules_artifact.get("raw_exchange_info_hash"),
            "rules": [selected_rules[symbol] for symbol in TOP3],
        },
        "anchor": dict(anchor_evidence),
    }


def _validate_registration(
    preregistration: Mapping[str, Any],
    rules_artifact: Mapping[str, Any],
    anchor_evidence: Mapping[str, Any],
) -> str:
    protocol = FROZEN_TOP3_FORWARD_PROTOCOL
    _, rules_hash = _selected_rules(rules_artifact)
    if preregistration.get("schema_version") != MINI_TREND_FORWARD_PREREG_VERSION:
        raise ValueError("unexpected MiniTrend forward preregistration schema")
    if preregistration.get("decision_contract", {}).get("contract_hash") != protocol.contract_hash:
        raise ValueError("MiniTrend forward contract hash mismatch")
    if preregistration.get("protocol", {}).get("protocol_hash") != protocol.protocol_hash:
        raise ValueError("MiniTrend forward protocol hash mismatch")
    if preregistration.get("exchange_rules", {}).get("selected_rules_hash") != rules_hash:
        raise ValueError("MiniTrend forward exchange-rules hash mismatch")
    expected_anchor = preregistration.get("anchor", {})
    for key in ("config_sha256", "summary_sha256", "equity_sha256"):
        if expected_anchor.get(key) != anchor_evidence.get(key):
            raise ValueError(f"MiniTrend forward anchor {key} mismatch")
    return rules_hash


def _bars_hash(aligned: Mapping[str, Sequence[Bar]]) -> str:
    basis = {
        symbol: [
            [bar.ts_ms, bar.open, bar.high, bar.low, bar.close, bar.volume]
            for bar in rows
        ]
        for symbol, rows in sorted(aligned.items())
    }
    return _canonical_hash(basis)


def _date(raw: str) -> dt.date:
    return dt.date.fromisoformat(raw)


def _returns(values: Sequence[float]) -> list[float]:
    return [values[i] / values[i - 1] - 1.0 for i in range(1, len(values)) if values[i - 1] != 0]


def _beta(strategy_values: Sequence[float], benchmark_values: Sequence[float]) -> float:
    strategy_returns = _returns(strategy_values)
    benchmark_returns = _returns(benchmark_values)
    n = min(len(strategy_returns), len(benchmark_returns))
    if n < 2:
        return 0.0
    xs = benchmark_returns[-n:]
    ys = strategy_returns[-n:]
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    variance = sum((value - x_mean) ** 2 for value in xs)
    if variance <= 0:
        return 0.0
    return sum((xs[i] - x_mean) * (ys[i] - y_mean) for i in range(n)) / variance


def build_forward_report(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    rules_artifact: Mapping[str, Any],
    preregistration: Mapping[str, Any],
    anchor_evidence: Mapping[str, Any],
    *,
    expected_end_date: str | None = None,
) -> dict[str, Any]:
    protocol = FROZEN_TOP3_FORWARD_PROTOCOL
    rules_hash = _validate_registration(preregistration, rules_artifact, anchor_evidence)
    cfg = frozen_top3_config()
    aligned = align_bars(bars_by_symbol, cfg.universe)
    anchor_result = run_backtest(
        aligned,
        cfg,
        filters=research_filters(TOP3, min_notional=10.0),
        taker_fee=protocol.taker_fee_bps / 10_000.0,
        slippage=protocol.slippage_bps / 10_000.0,
    )
    result = run_backtest(
        aligned,
        cfg,
        filters=_mini_trend_filters(rules_artifact),
        taker_fee=protocol.taker_fee_bps / 10_000.0,
        slippage=protocol.slippage_bps / 10_000.0,
    )
    evaluation_start = _date(protocol.evaluation_start_date)
    anchor_end = _date(protocol.anchor_end_date)
    anchor_equity_before = [
        row for row in anchor_result.equity if _date(row["date"]) <= anchor_end
    ]
    equity_before = [row for row in result.equity if _date(row["date"]) <= anchor_end]
    evaluation_equity = [row for row in result.equity if _date(row["date"]) >= evaluation_start]
    if not anchor_equity_before or not equity_before or not evaluation_equity:
        raise ValueError("forward report requires anchor and evaluation equity rows")
    reproduced_anchor_equity = float(anchor_equity_before[-1]["equity"])
    runtime_rules_anchor_equity = float(equity_before[-1]["equity"])
    anchor_parity_error = abs(
        reproduced_anchor_equity - float(anchor_evidence["final_equity"])
    )
    anchor_parity_pass = anchor_parity_error <= 1e-6
    if not anchor_parity_pass:
        raise ValueError("frozen TOP3 rerun does not reproduce anchor equity")

    evaluation_dates = [row["date"] for row in evaluation_equity]
    last_date = _date(evaluation_dates[-1])
    expected_end = _date(expected_end_date) if expected_end_date else last_date
    if last_date > expected_end:
        raise ValueError("forward data extends past the expected completed-bar date")
    expected_bars = (expected_end - evaluation_start).days + 1
    gap_count = expected_bars - len(evaluation_equity)
    strategy_curve = [runtime_rules_anchor_equity] + [
        float(row["equity"]) for row in evaluation_equity
    ]
    strategy_return = (strategy_curve[-1] / strategy_curve[0] - 1.0) * 100.0

    date_maps = {symbol: {bar.date: bar for bar in rows} for symbol, rows in aligned.items()}
    benchmark_dates = [protocol.anchor_end_date] + evaluation_dates
    benchmark_curves: dict[str, list[float]] = {}
    for symbol in TOP3:
        start_close = date_maps[symbol][protocol.anchor_end_date].close
        benchmark_curves[symbol] = [date_maps[symbol][date].close / start_close for date in benchmark_dates]
    top3_curve = [
        sum(benchmark_curves[symbol][i] for symbol in TOP3) / len(TOP3)
        for i in range(len(benchmark_dates))
    ]
    btc_curve = benchmark_curves["BTCUSDT"]
    top3_return = (top3_curve[-1] - 1.0) * 100.0
    btc_return = (btc_curve[-1] - 1.0) * 100.0
    beta_to_top3 = _beta(strategy_curve, top3_curve)

    evaluation_orders = [row for row in result.orders if _date(row["date"]) >= evaluation_start]
    evaluation_blocked = [row for row in result.blocked_symbols if _date(row["date"]) >= evaluation_start]
    notional = sum(float(row.get("notional_usdt", 0.0)) for row in evaluation_orders)
    fees = sum(float(row.get("fee_usdt", 0.0)) for row in evaluation_orders)
    fee_to_notional = fees / notional * 100.0 if notional > 0 else 0.0
    active_bars = sum(1 for row in evaluation_equity if float(row["gross_target"]) > 0.0)
    latest_signal = target_weights({symbol: list(rows) for symbol, rows in aligned.items()}, cfg)

    gates = {
        "data_complete": gap_count == 0 and last_date == expected_end,
        "anchor_parity": anchor_parity_pass,
        "minimum_forward_bars": len(evaluation_equity) >= protocol.minimum_forward_bars,
        "minimum_active_bars": active_bars >= protocol.minimum_active_bars,
        "maximum_forward_drawdown": max_drawdown_pct(strategy_curve)
        <= protocol.maximum_forward_drawdown_pct,
        "maximum_fee_to_notional": fee_to_notional <= protocol.maximum_fee_to_notional_pct,
        "min_notional_coverage": len(evaluation_blocked) == 0,
        "no_blocked_symbols": len(evaluation_blocked) == 0,
        "no_schema_or_position_errors": (
            result.scorecard.metrics.get("schema_error_count", 0) == 0
            and result.scorecard.metrics.get("unmanaged_position_count", 0) == 0
        ),
    }
    enough_horizon = gates["minimum_forward_bars"] and gates["minimum_active_bars"]
    paper_review_allowed = enough_horizon and all(gates.values())
    verdict = (
        "eligible_for_paper_review"
        if paper_review_allowed
        else "block_forward"
        if enough_horizon
        else "collect_forward"
    )
    blockers = [name for name, passed in gates.items() if not passed]

    return {
        "schema_version": MINI_TREND_FORWARD_VERSION,
        "artifact_type": "mini_trend_top3_forward_report",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "low_frequency_only": True,
            "private_exchange_data": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
            "strategy_results_evaluated": True,
            "contract_hash": protocol.contract_hash,
            "protocol_hash": protocol.protocol_hash,
            "data_hash": _bars_hash(aligned),
            "selected_rules_hash": rules_hash,
        },
        "protocol": {
            **protocol.protocol_basis,
            "protocol_hash": protocol.protocol_hash,
        },
        "data": {
            "source": "https://data.binance.vision",
            "market": protocol.market,
            "interval": protocol.interval,
            "first_common_date": next(iter(aligned.values()))[0].date,
            "last_common_date": next(iter(aligned.values()))[-1].date,
            "aligned_bar_count": len(next(iter(aligned.values()))),
            "evaluation_bar_count": len(evaluation_equity),
            "evaluation_expected_bar_count": expected_bars,
            "evaluation_expected_end_date": expected_end.isoformat(),
            "evaluation_gap_count": gap_count,
            "per_symbol_bar_count": {symbol: len(rows) for symbol, rows in aligned.items()},
        },
        "anchor": {
            **dict(anchor_evidence),
            "rerun_equity": reproduced_anchor_equity,
            "runtime_rules_anchor_equity": runtime_rules_anchor_equity,
            "runtime_rules_equity_drift": (
                runtime_rules_anchor_equity - reproduced_anchor_equity
            ),
            "parity_error": anchor_parity_error,
            "parity_pass": anchor_parity_pass,
        },
        "evaluation": {
            "start": protocol.evaluation_start_date,
            "end": evaluation_dates[-1],
            "strategy_return_pct": strategy_return,
            "strategy_max_drawdown_pct": max_drawdown_pct(strategy_curve),
            "btc_buy_hold_return_pct": btc_return,
            "top3_equal_weight_return_pct": top3_return,
            "excess_vs_top3_equal_weight_pct": strategy_return - top3_return,
            "beta_to_top3_equal_weight": beta_to_top3,
            "beta_residual_return_pct": strategy_return - beta_to_top3 * top3_return,
            "active_bar_count": active_bars,
            "cash_bar_count": len(evaluation_equity) - active_bars,
            "order_count": len(evaluation_orders),
            "fee_usdt": fees,
            "notional_usdt": notional,
            "fee_to_notional_pct": fee_to_notional,
            "blocked_symbol_count": len(evaluation_blocked),
        },
        "latest_signal": {
            "bar": latest_signal.bar,
            "gate": asdict(latest_signal.gate),
            "targets": latest_signal.targets,
            "gross_target": sum(latest_signal.targets.values()),
        },
        "diagnostics": {
            "verdict": verdict,
            "blockers": blockers,
            "gates": gates,
            "paper_review_allowed": paper_review_allowed,
            "high_frequency_used": False,
            "parameter_search_performed": False,
            "next_action": (
                "continue collecting completed daily bars under the frozen protocol"
                if verdict == "collect_forward"
                else "review forward blockers without tuning the frozen contract"
                if verdict == "block_forward"
                else "perform a separate paper-readiness review; do not auto-start paper or live"
            ),
        },
    }


def write_forward_preregistration_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-top3-forward-preregistration",
        path_key="artifact_path",
        default_filename="mini_trend_top3_forward_preregistration.json",
        explicit_path=explicit_path,
    )


def write_forward_report_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-top3-forward",
        path_key="artifact_path",
        default_filename="mini_trend_top3_forward.json",
        explicit_path=explicit_path,
    )
