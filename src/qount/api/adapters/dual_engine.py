"""Adapter for the Dual-Engine paper accounts (G20 / C60 / GC5 / D15).

Reads the authoritative paper snapshot written by ``qount.dual_engine.paper`` and normalizes one
portfolio into a :class:`PaperLine`. The snapshot is the single source of truth for these accounts:
this module must never invent a NAV, a drawdown, or a holding. When the snapshot is absent or does
not carry the requested portfolio, it returns an explicitly unavailable line (``error`` set, empty
``nav_series``, ``metrics=None``) so the UI shows "data unavailable" rather than a plausible-looking
number that is indistinguishable from a real one.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from qount.api.adapters import register_adapter
from qount.api.adapters.utils import compute_freshness, compute_sha256, format_date_str
from qount.api.schemas import (
    LineMetrics,
    LineSafety,
    LineSource,
    NavPoint,
    PaperLine,
    PositionItem,
)

# Portfolio ids as declared by the frozen contract (qount.dual_engine.contracts).
_ACCOUNT_TO_PORTFOLIO = {
    "g20": "dual-engine-paper-g20",
    "c60": "dual-engine-paper-c60",
    "gc5": "dual-engine-paper-gc5",
    "d15": "dual-engine-paper-d15",
}

_ACCOUNT_CATEGORY = {
    "g20": "equity",
    "c60": "crypto",
    "gc5": "mixed",
    "d15": "mixed",
}

# Snapshot path candidates, most specific first. The canonical location is
# ``<state_root>/current/paper_program_snapshot.json``.
_SNAPSHOT_RELATIVE_CANDIDATES = (
    os.path.join("current", "paper_program_snapshot.json"),
    "paper_program_snapshot.json",
)

_ADJUDICATION = (
    "四账户公共数据无订单模拟；YTD 含部署时历史回放，不是实盘收益。"
    "YTD 收益与同期最大回撤必须并排读取：示范区间内回撤曾达两位数百分比。"
)


def _resolve_snapshot_path(config: Dict[str, Any]) -> str:
    """Locate the snapshot for this line, or return the canonical expected path.

    ``QOUNT_PAPER_STATE_ROOT`` overrides the configured root so one registry entry works on
    every host: the Mac has no snapshot, while the VPS keeps the authoritative one under
    /var/lib/qount. Without the override the registry would have to carry a host-specific
    absolute path and drift between machines.
    """
    root = str(
        os.environ.get("QOUNT_PAPER_STATE_ROOT")
        or config.get("root")
        or "state/dual_engine"
    )
    explicit = config.get("snapshot")
    if explicit:
        return str(explicit)
    for relative in _SNAPSHOT_RELATIVE_CANDIDATES:
        candidate = os.path.join(root, relative)
        if os.path.exists(candidate):
            return candidate
    # Nothing found: report the canonical path so the UI can show where it looked.
    return os.path.join(root, _SNAPSHOT_RELATIVE_CANDIDATES[0])


def _unavailable(
    line_id: str,
    name: str,
    account: str,
    snapshot_path: str,
    as_of: str,
    error: str,
) -> PaperLine:
    """Build a line that carries no performance figures, only the reason there are none."""
    return PaperLine(
        line_id=line_id,
        name=name,
        category=_ACCOUNT_CATEGORY.get(account, "equity"),
        status="MISSING",
        adjudication=_ADJUDICATION,
        as_of=as_of,
        freshness="MISSING",
        nav_series=[],
        metrics=None,
        positions=[],
        source=LineSource(
            path=snapshot_path,
            sha256=compute_sha256(snapshot_path),
            produced_at=None,
        ),
        safety=LineSafety(research_only=True, orders_authorized=False),
        error=error,
    )


def _find_portfolio(snapshot: Dict[str, Any], portfolio_id: str) -> Optional[Dict[str, Any]]:
    portfolios = snapshot.get("portfolios") or []
    if not isinstance(portfolios, list):
        return None
    for row in portfolios:
        if isinstance(row, dict) and row.get("portfolio_id") == portfolio_id:
            return row
    return None


def _find_benchmark_series(snapshot: Dict[str, Any]) -> Dict[str, float]:
    """Return {date: nav} for the SPY benchmark, or {} when unavailable.

    The benchmark is optional by design: a missing SPY history must leave the benchmark line
    absent rather than spliced or fabricated.
    """
    benchmarks = snapshot.get("benchmarks") or []
    series: Dict[str, float] = {}
    if not isinstance(benchmarks, list):
        return series
    for row in benchmarks:
        if not isinstance(row, dict):
            continue
        nav_block = row.get("nav") or {}
        points = nav_block.get("points") or []
        if not isinstance(points, list) or not points:
            continue
        initial = float(row.get("initial_capital") or 1.0)
        if initial <= 0:
            continue
        for point in points:
            if not isinstance(point, dict):
                continue
            marked_at = point.get("marked_at")
            value = point.get("value")
            if marked_at is None or value is None:
                continue
            try:
                series[format_date_str(str(marked_at))] = float(value) / initial
            except (TypeError, ValueError):
                continue
        break
    return series


def _format_nav_point_time(marked_at: Any) -> str:
    """Preserve intraday identity while keeping date-only legacy snapshots compatible.

    Several authoritative paper snapshots contain distinct marks on the same calendar day.
    Returning only the date would make SQLite's ``(line_id, date)`` key overwrite those rows.
    """
    raw = str(marked_at).strip()
    if len(raw) > 10 and raw[10] in {"T", " "}:
        return raw
    return format_date_str(raw)


def _build_nav_series(
    portfolio: Dict[str, Any],
    benchmark_series: Dict[str, float],
) -> list[NavPoint]:
    nav_block = portfolio.get("nav") or {}
    points = nav_block.get("points") or []
    initial = float(portfolio.get("initial_capital") or 1.0)
    if initial <= 0 or not isinstance(points, list):
        return []

    out: list[NavPoint] = []
    for point in points:
        if not isinstance(point, dict):
            continue
        marked_at = point.get("marked_at")
        # The snapshot names these "executable" and "signal"; older captures used the
        # suffixed spellings, so both are accepted.
        executable = point.get("executable", point.get("executable_nav"))
        if marked_at is None or executable is None:
            continue
        date = _format_nav_point_time(marked_at)
        benchmark_date = format_date_str(str(marked_at))
        try:
            nav_value = float(executable)
        except (TypeError, ValueError):
            continue
        signal_raw = point.get("signal", point.get("signal_nav"))
        try:
            signal_value = float(signal_raw) if signal_raw is not None else nav_value
        except (TypeError, ValueError):
            signal_value = nav_value
        out.append(
            NavPoint(
                date=date,
                nav=nav_value,
                benchmark_nav=benchmark_series.get(benchmark_date, 1.0),
                signal_nav=signal_value,
            )
        )
    return out


def _build_metrics(portfolio: Dict[str, Any], nav_series: list[NavPoint]) -> LineMetrics:
    nav_block = portfolio.get("nav") or {}

    def _pct(key: str) -> Optional[float]:
        value = nav_block.get(key)
        if value is None:
            return None
        try:
            return round(float(value) * 100.0, 2)
        except (TypeError, ValueError):
            return None

    days = len(nav_series)
    return LineMetrics(
        ytd_return_pct=_pct("since_start_return_fraction"),
        max_drawdown_pct=_pct("max_drawdown_fraction"),
        current_drawdown_pct=_pct("current_drawdown_fraction"),
        signal_nav=nav_block.get("signal"),
        executable_nav=nav_block.get("executable"),
        cumulative_cost=nav_block.get("cumulative_cost"),
        start_date=format_date_str(nav_series[0].date) if nav_series else None,
        days=days or None,
        trade_count=None,
    )

def _build_positions(portfolio: Dict[str, Any]) -> list[PositionItem]:
    out: list[PositionItem] = []
    for holding in portfolio.get("holdings") or []:
        if not isinstance(holding, dict):
            continue
        symbol = holding.get("symbol")
        if not symbol:
            continue
        try:
            weight = float(holding.get("actual_weight") or 0.0)
        except (TypeError, ValueError):
            weight = 0.0
        out.append(
            PositionItem(
                symbol=str(symbol),
                weight=weight,
                quantity=holding.get("quantity"),
                market_value=holding.get("market_value"),
            )
        )
    out.sort(key=lambda item: item.weight, reverse=True)
    return out


@register_adapter("dual_engine")
def adapt_dual_engine(line_id: str, name: str, config: Dict[str, Any]) -> PaperLine:
    account = str(config.get("account") or "").lower()
    portfolio_id = _ACCOUNT_TO_PORTFOLIO.get(account)

    snapshot_path = _resolve_snapshot_path(config)
    today = format_date_str(config.get("reference_date") or "2026-10-12")

    if portfolio_id is None:
        return _unavailable(
            line_id, name, account, snapshot_path, today,
            error=f"UNKNOWN_ACCOUNT: '{account}' is not one of {sorted(_ACCOUNT_TO_PORTFOLIO)}",
        )

    if not os.path.exists(snapshot_path):
        return _unavailable(
            line_id, name, account, snapshot_path, today,
            error=(
                "SNAPSHOT_NOT_FOUND: the Dual-Engine paper snapshot is produced on the host that "
                "runs the paper cycle and is not present locally. No performance figures are "
                "shown because none can be sourced."
            ),
        )

    try:
        with open(snapshot_path, "r", encoding="utf-8") as handle:
            snapshot = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        return _unavailable(
            line_id, name, account, snapshot_path, today,
            error=f"SNAPSHOT_UNREADABLE: {type(exc).__name__}",
        )

    portfolio = _find_portfolio(snapshot, portfolio_id)
    if portfolio is None:
        return _unavailable(
            line_id, name, account, snapshot_path, today,
            error=f"PORTFOLIO_ABSENT: snapshot carries no row for '{portfolio_id}'",
        )

    nav_series = _build_nav_series(portfolio, _find_benchmark_series(snapshot))
    if not nav_series:
        return _unavailable(
            line_id, name, account, snapshot_path, today,
            error="NAV_SERIES_EMPTY: snapshot row carries no usable NAV points",
        )

    data_cutoff = snapshot.get("data_cutoff") or nav_series[-1].date
    as_of = format_date_str(str(data_cutoff))

    return PaperLine(
        line_id=line_id,
        name=name,
        category=_ACCOUNT_CATEGORY.get(account, "equity"),
        status="ACTIVE_PAPER",
        adjudication=_ADJUDICATION,
        as_of=as_of,
        freshness=compute_freshness(as_of, config.get("reference_date") or "2026-10-12"),
        nav_series=nav_series,
        metrics=_build_metrics(portfolio, nav_series),
        positions=_build_positions(portfolio),
        source=LineSource(
            path=snapshot_path,
            sha256=compute_sha256(snapshot_path),
            produced_at=snapshot.get("generated_at"),
        ),
        safety=LineSafety(research_only=True, orders_authorized=False),
        error=None,
    )
