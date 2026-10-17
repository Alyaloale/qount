"""Adapter for the universal regime v1.3 forward paper recording line."""

from __future__ import annotations

import json
import os
from typing import Any, Dict

from qount.api.adapters import register_adapter
from qount.api.adapters.utils import compute_freshness, compute_sha256, unavailable_line
from qount.api.schemas import LineMetrics, LineSafety, LineSource, NavPoint, PaperLine, PositionItem


_ADJUDICATION = (
    "通用状态期望 v1.3 冻结参数前向记录；参数已冻结不再迭代，"
    "保留独立观测；历史 Calmar 1.02 实为累计收益/回撤，不能当作标准 Calmar。"
    "短样本期间不报告年化或 Sharpe。"
)


def _forward_dir(config: Dict[str, Any]) -> str:
    return os.environ.get(
        "QOUNT_UNIVERSAL_REGIME_FORWARD_ROOT"
    ) or config.get("root", "state/research_runs/universal_regime_v1.3_forward")


@register_adapter("universal_regime_forward")
def adapt_universal_regime(line_id: str, name: str, config: Dict[str, Any]) -> PaperLine:
    root = _forward_dir(config)
    nav_path = os.path.join(root, "forward_nav.json")

    if not os.path.isfile(nav_path):
        return unavailable_line(
            line_id,
            name,
            "macro",
            nav_path,
            "SOURCE_NOT_FOUND: universal regime v1.3 forward recording has not yet produced data. "
            "Parameters frozen; awaiting daily accumulation.",
            _ADJUDICATION,
        )

    try:
        with open(nav_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        observations = data.get("observations", [])
        if not observations:
            return unavailable_line(
                line_id,
                name,
                "macro",
                nav_path,
                "SOURCE_EMPTY: universal regime forward recording exists but has no observations yet.",
                _ADJUDICATION,
            )

        initial_equity = float(data.get("initial_equity", 1000.0))
        nav_series = []
        peak = initial_equity
        worst_dd = 0.0
        current_equity = initial_equity
        for obs in observations:
            eq = float(obs["equity"])
            current_equity = eq
            peak = max(peak, eq)
            dd = eq / peak - 1.0
            worst_dd = min(worst_dd, dd)
            nav_series.append(NavPoint(
                date=str(obs["date"]),
                nav=round(eq / initial_equity, 8),
                benchmark_nav=round(float(obs["benchmark_nav"]), 8) if obs.get("benchmark_nav") is not None else None,
            ))

        as_of = str(observations[-1]["date"])
        positions_data = data.get("current_positions", [])
        positions = [
            PositionItem(
                symbol=str(p["symbol"]),
                weight=float(p.get("weight", 0)) or None,
                quantity=float(p.get("quantity", 0)) or None,
            )
            for p in positions_data
        ]
        current_dd = current_equity / peak - 1.0

    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, IndexError) as exc:
        return unavailable_line(
            line_id,
            name,
            "macro",
            nav_path,
            f"SOURCE_UNREADABLE: universal regime forward data could not be parsed ({type(exc).__name__}).",
            _ADJUDICATION,
        )

    return PaperLine(
        line_id=line_id,
        name=name,
        category="macro",
        status="ACTIVE_PAPER",
        adjudication=_ADJUDICATION,
        as_of=as_of,
        freshness=compute_freshness(as_of),
        curve_granularity="DAILY",
        nav_series=nav_series,
        metrics=LineMetrics(
            initial_equity=initial_equity,
            observation_count=len(nav_series),
            trading_days=len(observations),
            max_drawdown_pct=round(worst_dd * 100.0, 4),
            current_drawdown_pct=round(current_dd * 100.0, 4),
            executable_nav=round(current_equity / initial_equity, 8),
            start_date=str(observations[0]["date"]),
            days=len(observations),
        ),
        positions=positions,
        position_status="KNOWN" if positions_data else "UNKNOWN",
        cost_assumptions={
            "commission_bps": 5.0,
            "slippage_bps": 5.0,
            "gap_stress_pct": 0.015,
        },
        execution_constraints=[
            "v1.3 参数已冻结，不再迭代；前向记录用于验证可信基准。",
            "1X 现货模式，RIGOROUS 因果律（止损优先于止盈）。",
            "历史跳空压力结果使用旧收益/回撤口径，不作为标准 Calmar 或实盘资格。",
            "2020-2022 连续三年亏损约 -26.5%，全部正收益来自 2023-2026 商品牛市。",
        ],
        source=LineSource(
            path=nav_path,
            sha256=compute_sha256(nav_path),
        ),
        safety=LineSafety(research_only=True, orders_authorized=False),
    )
