"""Read-only USD-M USDT performance from real observations and income.

Chain Modified Dietz over observed intervals; not exact intraday TWR. Missing
income coverage or an unreconciled wallet change starts a separate segment.
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ECONOMIC_INCOME = {"REALIZED_PNL", "COMMISSION", "FUNDING_FEE", "INSURANCE_CLEAR",
                   "COMMISSION_REBATE", "REFERRAL_KICKBACK"}
CASH_FLOW_INCOME = {"TRANSFER"}


def millis(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone_required")
    return parsed.timestamp() * 1000


def number(value):
    if value is None or isinstance(value, bool):
        raise ValueError("amount_required")
    amount = float(value)
    if not math.isfinite(amount):
        raise ValueError("finite_amount_required")
    return amount


def income_history(path, symbol=None):
    """All retained income and successfully persisted collection windows."""
    path = Path(path)
    if not path.is_file():
        return [], []
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=5) as conn:
        rows = [json.loads(r[0]) for r in conn.execute("SELECT payload FROM account_records WHERE kind='income' ORDER BY time_ms")]
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        metadata = [json.loads(r[0]) for r in conn.execute("SELECT payload FROM account_collection WHERE id=1")]
        if "account_collection_history" in tables:
            metadata += [json.loads(r[0]) for r in conn.execute("SELECT payload FROM account_collection_history")]
    intervals = []
    for meta in metadata:
        errors = meta.get("errors", {})
        if (meta.get("read_only") is True and meta.get("orders_authorized") is False
                and not any(k in errors for k in ("income", "persistence"))
                and (symbol is None or symbol in meta.get("completed_symbols", []) and symbol not in errors)):
            left, right = meta.get("window_start_ms"), meta.get("window_end_ms")
            if left is not None and right is not None and left <= right:
                intervals.append((left, right))
    merged = []
    for left, right in sorted(intervals):
        if merged and left <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
        else:
            merged.append((left, right))
    return rows, merged


def covered(intervals, left, right):
    return any(a <= left and b >= right for a, b in intervals)


def _observation(stamp, row):
    if row.get("read_only") is not True or row.get("status") not in {"AVAILABLE", "PARTIAL"} or "usdm" in row.get("errors", {}):
        raise ValueError("usdm_observation_unavailable")
    equity = number(row.get("usdm_margin_balance_usdt"))
    wallet = number(row.get("usdm_wallet_balance_usdt"))
    time = millis(stamp)
    started = millis(row.get("started_at", stamp))
    if started > time or time - started > 60_000 or time > datetime.now(timezone.utc).timestamp()*1000+60_000:
        raise ValueError("observation_clock_invalid")
    return dict(observed_at=stamp, time=time, started=started, equity_usdt=equity,
                wallet_usdt=wallet, unrealized_pnl_usdt=equity-wallet)


def build_performance(observations, income, coverage, *, max_gap_ms=900_000):
    points, gaps = [], []
    previous = None
    segment = -1
    start_equity = flows = pnl = 0.0
    nav = peak = 1.0
    drawdown = 0.0
    anchor_needed = True
    for stamp, row in observations:
        try:
            current = _observation(stamp, row)
        except (TypeError, ValueError, KeyError):
            gaps.append(dict(observed_at=stamp, reason="usdm_observation_unavailable"))
            previous, anchor_needed = None, True
            continue
        if previous is None:
            previous = current
            continue
        left, right = previous["time"], current["time"]
        rows = [r for r in income if left < r["time"] <= right and r["asset"] == "USDT"]
        reason = None
        if not 0 < right-left <= max_gap_ms:
            reason = "observation_gap"
        # Exchange income has integer-millisecond timestamps. The last
        # possible event <= a microsecond snapshot is floor(right), not ceil.
        elif not covered(coverage, math.floor(left)+1, math.floor(right)):
            reason = "income_coverage_missing"
        elif any(r["income_type"] not in ECONOMIC_INCOME | CASH_FLOW_INCOME for r in rows):
            reason = "unsupported_income_type"
        elif any(a["started"] <= r["time"] <= a["time"] for a in (previous, current)
                 for r in income if r["asset"] == "USDT"):
            reason = "income_during_observation"
        elif not math.isclose(current["wallet_usdt"]-previous["wallet_usdt"],
                              sum(number(r["amount"]) for r in rows), rel_tol=1e-9, abs_tol=1e-6):
            reason = "wallet_income_mismatch"
        external = [r for r in rows if r["income_type"] in CASH_FLOW_INCOME]
        flow = sum(number(r["amount"]) for r in external)
        denominator = previous["equity_usdt"] + sum(
            number(r["amount"]) * (right-r["time"])/(right-left) for r in external) if right > left else 0
        delta = current["equity_usdt"]-previous["equity_usdt"]-flow
        if reason is None and (previous["equity_usdt"] <= 0 or denominator <= 0 or 1+delta/denominator < 0):
            reason = "return_capital_unavailable"
        if reason:
            gaps.append(dict(observed_at=stamp, reason=reason))
            previous, anchor_needed = current, True
            continue
        if anchor_needed:
            segment += 1
            start_equity, flows, pnl, nav, peak, drawdown = previous["equity_usdt"], 0.0, 0.0, 1.0, 1.0, 0.0
            points.append(dict(previous, segment_id=segment, nav=1.0, return_pct=0.0,
                               net_pnl_usdt=0.0, net_external_flow_usdt=0.0, drawdown_pct=0.0))
            anchor_needed = False
        flows += flow
        pnl = current["equity_usdt"]-start_equity-flows
        nav *= 1+delta/denominator
        peak = max(peak, nav)
        drawdown = max(drawdown, 1-nav/peak)
        points.append(dict(current, segment_id=segment, nav=nav, return_pct=(nav-1)*100,
                           net_pnl_usdt=pnl, net_external_flow_usdt=flows,
                           drawdown_pct=(1-nav/peak)*100, max_drawdown_pct=drawdown*100))
        previous = current
    latest = [p for p in points if p["segment_id"] == segment]
    summary = None
    if latest:
        summary = {k:latest[-1].get(k) for k in ("return_pct", "net_pnl_usdt", "net_external_flow_usdt", "max_drawdown_pct")}
        summary.update(start=latest[0]["observed_at"], end=latest[-1]["observed_at"],
                       observation_count=len(latest), segment_id=segment,
                       includes_latest_observation=bool(observations and latest[-1]["observed_at"] == observations[-1][0]))
    return dict(status="PARTIAL" if gaps and points else "AVAILABLE" if points else "MISSING",
                points=points, gaps=gaps, summary=summary, segment_count=segment+1,
                observation_count=len(observations))


def read_account_performance(history_path, trades_path, days=30):
    result = dict(status="MISSING", scope="Binance USD-M USDT account; includes manual and legacy trades",
                  currency="USDT", read_only=True, orders_authorized=False,
                  method="chained_modified_dietz", points=[], gaps=[], summary=None, segment_count=0,
                  note="基于真实USDT合约权益与资金流水；含手动及旧策略成交，不代表当前策略独立收益。",
                  limitations=["快照区间链式Modified Dietz近似，不是精确逐笔时间加权收益",
                               "收益已包含手续费、资金费及未实现盈亏；不重复扣费",
                               "缺失覆盖、观测中交易或钱包核对不符处断线，各段独立起算；不年化",
                               "不包含其他钱包、其他保证金币种或观测起点之前的收益"])
    if not Path(history_path).is_file():
        return result
    try:
        cutoff = (datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
        with sqlite3.connect(f"file:{Path(history_path).resolve()}?mode=ro", uri=True, timeout=5) as conn:
            observations = [(t, json.loads(raw)) for t, raw in conn.execute(
                "SELECT observed_at,payload FROM asset_observations WHERE observed_at>=? ORDER BY observed_at", (cutoff,))]
        income, coverage = income_history(trades_path)
        result.update(build_performance(observations, income, coverage))
        result["observed_at"] = observations[-1][0] if observations else None
        result["stale"] = bool(observations and datetime.now(timezone.utc).timestamp()*1000-millis(observations[-1][0]) > 900_000)
        result["income_coverage"] = [dict(start_ms=a, end_ms=b) for a,b in coverage]
        return result
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        return result | dict(status="ERROR", error="ACCOUNT_PERFORMANCE_UNREADABLE")
