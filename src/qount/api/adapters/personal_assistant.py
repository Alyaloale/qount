"""Adapter for the ETF moving-average timing research line (legacy ID preserved)."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from qount.api.adapters import register_adapter
from qount.api.adapters.utils import (
    compute_freshness,
    compute_sha256,
    format_date_str,
    unavailable_line,
)
from qount.api.schemas import (
    LineMetrics,
    LineSafety,
    LineSource,
    NavPoint,
    PaperLine,
    PositionItem,
)

from qount.api.ledger import parse_personal_assistant_position_ledger

_ADJUDICATION = (
    "普通 ETF 研究线，研究 MA120 与 1.5% 带宽的择时效果。"
    "历史回放已调和，同标的收益与回撤对照见下方；择时机制的增量价值尚待验证。"
    "确定性日报已完成，前向记录待积累；账户资格尚未认证，无实盘下单授权。"
)


def load_personal_assistant_trade_events(config: Dict[str, Any]) -> list[dict[str, object]]:
    """Load source ledger events without combining split actions with BUY/SELL trades."""
    run_dir = config.get("run", "state/research_runs/personal_assistant_reconciled_20261012")
    trades_path = os.path.join(run_dir, "trades.json")
    with open(trades_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    trades = data["513100.SH"]["MA120_Band1.5pct"]
    return [
        {
            "date": row.get("date"),
            "symbol": "513100.SH",
            "side": row.get("action"),
            "quantity": row.get("shares"),
            "price": row.get("price"),
            "cost": row.get("commission"),
            "note": ((f"split_ratio={row['split_ratio']}; " if row.get("split_ratio") else "") + (row.get("note") or "")),
            "split_ratio": row.get("split_ratio"),
        }
        for row in trades
    ]


@register_adapter("personal_assistant")
def adapt_personal_assistant(line_id: str, name: str, config: Dict[str, Any]) -> PaperLine:
    run_dir = config.get("run", "state/research_runs/personal_assistant_reconciled_20261012")
    summary_path = os.path.join(run_dir, "summary.json")
    replay_path = os.path.join(run_dir, "baseline-replay.json")
    trades_path = os.path.join(run_dir, "trades.json")

    if not os.path.isfile(summary_path):
        return unavailable_line(
            line_id,
            name,
            "equity",
            summary_path,
            "SOURCE_NOT_FOUND: personal assistant summary.json is absent; no performance figures are reported.",
            _ADJUDICATION,
        )
    if not os.path.isfile(replay_path):
        return unavailable_line(
            line_id,
            name,
            "equity",
            replay_path,
            "SOURCE_NOT_FOUND: personal assistant baseline-replay.json is absent; no performance figures are reported.",
            _ADJUDICATION,
        )

    try:
        with open(summary_path, "r", encoding="utf-8") as handle:
            summary_data = json.load(handle)
        with open(replay_path, "r", encoding="utf-8") as handle:
            replay_data = json.load(handle)

        asset = summary_data["assets"]["513100.SH"]
        baseline = next(
            row for row in asset["baselines"] if row.get("model_name") == "MA120_Band1.5pct"
        )
        replay = replay_data["513100.SH"]["MA120_Band1.5pct"]
        # Compare against buy-and-hold of the same ETF on the same date window.
        benchmark_replay = replay_data.get("513100.SH", {}).get("Buy_and_Hold", {})
        nav_rows = replay["nav"]
        if not isinstance(nav_rows, list) or not nav_rows:
            raise ValueError("baseline replay contains no NAV observations")

        benchmark_rows = benchmark_replay.get("nav", [])
        benchmark_map = {
            row[0]: float(row[1])
            for row in benchmark_rows
            if isinstance(row, (list, tuple)) and len(row) >= 2
        }
        sampled_rows = nav_rows

        normalized_rows = [(format_date_str(str(row[0])), float(row[1])) for row in sampled_rows]
        initial_equity = float(replay.get("metrics", {}).get("initial_equity", 0.0))
        benchmark_initial_equity = float(
            benchmark_replay.get("metrics", {}).get("initial_equity", initial_equity)
        )
        if initial_equity <= 0.0 or benchmark_initial_equity <= 0.0:
            raise ValueError("baseline replay has no valid initial equity")
        nav_series = []
        for (date, raw_nav), source_row in zip(normalized_rows, sampled_rows):
            raw_benchmark = benchmark_map.get(source_row[0])
            benchmark_nav: Optional[float] = None
            if raw_benchmark is not None:
                benchmark_nav = round(float(raw_benchmark) / benchmark_initial_equity, 8)
            nav_series.append(
                NavPoint(
                    date=date,
                    nav=round(raw_nav / initial_equity, 8),
                    benchmark_nav=benchmark_nav,
                )
            )

        as_of = format_date_str(str(baseline["end_date"]))
        benchmark_metrics = benchmark_replay.get("metrics", {})
        source_trades = load_personal_assistant_trade_events(config) if os.path.isfile(trades_path) else None
        metrics = LineMetrics(
            current_drawdown_pct=round((nav_series[-1].nav / max(pt.nav for pt in nav_series) - 1.0) * 100.0, 4),
            total_return_pct=baseline.get("total_return_pct"),
            cagr_basis="252 trading days",
            benchmark_cagr_pct=benchmark_metrics.get("cagr_252_pct", benchmark_metrics.get("cagr_pct")),
            benchmark_max_drawdown_pct=benchmark_metrics.get("max_drawdown_pct"),
            exposure_pct=baseline.get("exposure_pct"),
            initial_equity=initial_equity,
            observation_count=len(nav_series),
            trading_days=int(baseline["trading_days"]),
            corporate_action_count=sum(row["side"] in ("SPLIT", "CORPORATE_ACTION_SPLIT") for row in source_trades) if source_trades is not None else None,
            cagr_pct=round(float(baseline["cagr_pct"]), 2),
            max_drawdown_pct=round(float(baseline["max_drawdown_pct"]), 2),
            calmar=round(float(baseline["calmar_ratio"]), 2),
            trade_count=sum(row["side"] in ("BUY", "SELL") for row in source_trades) if source_trades is not None else None,
            start_date=format_date_str(str(baseline["start_date"])),
            days=int(baseline["trading_days"]),
            ytd_return_pct=None,
            executable_nav=round(float(baseline["terminal_equity"]) / initial_equity, 8),
        )

        open_shares = 0.0
        entry_date = None
        position_error = None
        position_known = False
        trade_count = int(baseline["trade_count"])
        corporate_action_count = 0
        if os.path.isfile(trades_path):
            with open(trades_path, "r", encoding="utf-8") as handle:
                trades_data = json.load(handle)
            ledger = trades_data.get("513100.SH", {}).get("MA120_Band1.5pct")
            if isinstance(ledger, list):
                trade_count = sum(str(row.get("action", "")).upper() in {"BUY", "SELL"} for row in ledger if isinstance(row, dict))
                corporate_action_count = sum(str(row.get("action", "")).upper().startswith("CORPORATE_ACTION_") for row in ledger if isinstance(row, dict))
            try:
                open_shares, entry_date = parse_personal_assistant_position_ledger(ledger, as_of=as_of)
                position_known = True
            except (TypeError, ValueError) as exc:
                position_error = f"POSITION_LEDGER_INVALID: {type(exc).__name__}"

    except (OSError, json.JSONDecodeError, KeyError, StopIteration, TypeError, ValueError, IndexError) as exc:
        code = "SOURCE_UNREADABLE" if isinstance(exc, (OSError, json.JSONDecodeError)) else "SUMMARY_EMPTY"
        return unavailable_line(
            line_id,
            name,
            "equity",
            summary_path,
            f"{code}: personal assistant source package could not provide a complete baseline ({type(exc).__name__}).",
            _ADJUDICATION,
        )

    return PaperLine(
        line_id=line_id,
        name=name,
        category="equity",
        status="ACTIVE_PAPER",
        adjudication=_ADJUDICATION,
        as_of=as_of,
        freshness=compute_freshness(as_of),
        curve_granularity="DAILY",
        nav_series=nav_series,
        metrics=metrics,
        positions=(
            [PositionItem(symbol="513100.SH", weight=None, quantity=round(open_shares, 6), entry_date=entry_date)]
            if open_shares > 1e-9 else []
        ),
        position_status="KNOWN" if position_known else "UNKNOWN",
        position_error=position_error,
        cost_assumptions={
            key: asset.get("metadata", {}).get(key)
            for key in ("commission_bps", "slippage_bps")
            if asset.get("metadata", {}).get(key) is not None
        },
        execution_constraints=summary_data.get("unknowns_and_limitations", []) + [
            "本历史回放采用小数模型份额；个人账户整手（100股）和最低5元佣金门槛未纳入。",
            "513100.SH现金分红与到账日资格仍待核；其他成本缺项不能据历史回放推定为已覆盖。",
        ],
        source=LineSource(
            path=summary_path,
            sha256=compute_sha256(summary_path),
            produced_at=summary_data.get("generated_at"),
        ),
        safety=LineSafety(research_only=True, orders_authorized=False),
    )
