"""Historical discovery benchmark decomposition for the UM base control."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.grid.data import Bar, Funding
from qount.mini_trend.backtest import align_bars
from qount.mini_trend.forward import TOP3
from qount.mini_trend.futures_recovery import FUTURES_RECOVERY_PROTOCOL
from qount.mini_trend.futures_recovery import canonical_hash
from qount.mini_trend.futures_recovery import selected_um_rules
from qount.models import utc_now
from qount.settings import Settings


BENCHMARK_REPORT_VERSION = "mini_trend_um_historical_benchmark_v0.1"
_DAY_MS = 86_400_000


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _max_drawdown(values: Sequence[float]) -> float:
    peak = values[0] if values else 0.0
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak:
            worst = max(worst, (peak - value) / peak * 100.0)
    return worst


def _funding_window(rows: Sequence[Funding], start_ms: int, end_ms: int) -> float:
    return sum(row.rate for row in rows if start_ms < row.ts_ms <= end_ms)


def run_buy_hold_benchmark(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    *,
    weights: Mapping[str, float],
    start_date: str,
    end_date: str,
    capital_usdt: float = 400.0,
) -> dict[str, Any]:
    bars = align_bars(bars_by_symbol, TOP3)
    dates = [bar.date for bar in bars["BTCUSDT"]]
    try:
        start_index = dates.index(start_date)
    except ValueError as exc:
        raise ValueError(f"benchmark start date missing: {start_date}") from exc
    equity = capital_usdt
    turnover = sum(abs(float(weight)) for weight in weights.values())
    cost_rate = (FUTURES_RECOVERY_PROTOCOL.taker_fee_bps + FUTURES_RECOVERY_PROTOCOL.slippage_bps) / 10_000.0
    equity *= 1.0 - turnover * cost_rate
    funding_pnl_usdt = 0.0
    rows: list[dict[str, Any]] = []
    for index in range(start_index, len(dates) - 1):
        outcome_date = dates[index + 1]
        if outcome_date > end_date:
            break
        prices = {symbol: bars[symbol][index].close for symbol in TOP3}
        next_prices = {symbol: bars[symbol][index + 1].close for symbol in TOP3}
        gross_return = sum(
            float(weights.get(symbol, 0.0)) * (next_prices[symbol] / prices[symbol] - 1.0)
            for symbol in TOP3
        )
        funding_return = 0.0
        for symbol in TOP3:
            rates = _funding_window(
                funding_by_symbol.get(symbol, []),
                bars[symbol][index].ts_ms + _DAY_MS,
                bars[symbol][index + 1].ts_ms + _DAY_MS,
            )
            funding_return -= float(weights.get(symbol, 0.0)) * rates
        before = equity
        equity *= 1.0 + gross_return + funding_return
        funding_pnl_usdt += before * funding_return
        rows.append({"date": outcome_date, "equity": round(equity, 8)})
    curve = [capital_usdt] + [float(row["equity"]) for row in rows]
    return {
        "start": start_date,
        "end": rows[-1]["date"] if rows else start_date,
        "return_pct": round((equity / capital_usdt - 1.0) * 100.0, 8),
        "max_drawdown_pct": round(_max_drawdown(curve), 8),
        "funding_pnl_usdt": round(funding_pnl_usdt, 8),
        "entry_cost_usdt": round(capital_usdt * turnover * cost_rate, 8),
        "bars": len(rows),
        "gross": round(sum(abs(float(weight)) for weight in weights.values()), 8),
    }


def _data_hash(bars: Mapping[str, Sequence[Bar]], funding: Mapping[str, Sequence[Funding]]) -> str:
    return canonical_hash(
        {
            "bars": {s: [[b.ts_ms, b.open, b.high, b.low, b.close, b.volume] for b in bars[s]] for s in TOP3},
            "funding": {s: [[f.ts_ms, f.rate] for f in funding[s]] for s in TOP3},
        }
    )


def build_benchmark_report(
    inputs: Mapping[str, Mapping[str, Any]],
    source_historical_path: str | Path,
    base_preregistration_path: str | Path,
    rules_artifact: Mapping[str, Any],
) -> dict[str, Any]:
    source = json.loads(Path(source_historical_path).expanduser().read_text(encoding="utf-8"))
    prereg = json.loads(Path(base_preregistration_path).expanduser().read_text(encoding="utf-8"))
    if source.get("artifact_type") != "mini_trend_um_recovery_historical_diagnostic":
        raise ValueError("unexpected historical source artifact")
    if prereg.get("artifact_type") != "mini_trend_um_base_forward_preregistration":
        raise ValueError("unexpected base forward preregistration")
    _, rules_hash = selected_um_rules(rules_artifact)
    protocol = FUTURES_RECOVERY_PROTOCOL
    segments = []
    for spec in protocol.historical_diagnostic_windows:
        source_segment = next(row for row in source["segments"] if row["label"] == spec["label"])
        segment_input = inputs[spec["label"]]
        bars = align_bars(segment_input["bars"], TOP3)
        funding = segment_input["funding"]
        btc = run_buy_hold_benchmark(
            bars,
            funding,
            weights={"BTCUSDT": 1.0},
            start_date=spec["start"],
            end_date=spec["end"],
        )
        top3 = run_buy_hold_benchmark(
            bars,
            funding,
            weights={symbol: 1.0 / len(TOP3) for symbol in TOP3},
            start_date=spec["start"],
            end_date=spec["end"],
        )
        control = source_segment["control"]
        segments.append(
            {
                "label": spec["label"],
                "data_hash": _data_hash(bars, funding),
                "control": control,
                "btc_1x": btc,
                "top3_equal_weight_1x": top3,
                "control_minus_btc_return_pct": round(control["return_pct"] - btc["return_pct"], 8),
                "control_minus_top3_return_pct": round(control["return_pct"] - top3["return_pct"], 8),
            }
        )
    return {
        "schema_version": BENCHMARK_REPORT_VERSION,
        "artifact_type": "mini_trend_um_historical_benchmark",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "discovery_pool",
            "existing_cache_only": True,
            "network_download_used": False,
            "strategy_results_evaluated": True,
            "promotion_allowed": False,
            "paper_or_live_allowed": False,
        },
        "base_forward_contract_hash": prereg["decision_contract"]["contract_hash"],
        "base_forward_protocol_hash": prereg["protocol"]["protocol_hash"],
        "source_historical_artifact_sha256": file_sha256(source_historical_path),
        "exchange_rules_hash": rules_hash,
        "segments": segments,
        "diagnostics": {
            "interpretation": "Historical benchmark decomposition only; no parameter or universe search.",
            "control_positive_segments": sum(row["control"]["return_pct"] > 0 for row in segments),
            "control_outperformed_btc_segments": sum(row["control_minus_btc_return_pct"] > 0 for row in segments),
            "control_outperformed_top3_segments": sum(row["control_minus_top3_return_pct"] > 0 for row in segments),
            "verdict": "discovery_only",
        },
    }


def write_benchmark_artifact(
    settings: Settings, payload: dict[str, Any], *, explicit_path: str | None = None
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-historical-benchmark",
        path_key="artifact_path",
        default_filename="mini_trend_um_historical_benchmark.json",
        explicit_path=explicit_path,
    )
