"""Adapter for the separately authorized CTA-R append-only forward ledger."""

from __future__ import annotations

import os
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from qount.api.adapters import register_adapter
from qount.api.adapters.utils import compute_freshness, compute_sha256, unavailable_line, observation_segments
from qount.api.schemas import LineMetrics, LineSafety, LineSource, NavPoint, PaperLine, PositionItem
from qount.research.cta_r_forward import CONTRACT, read_ledger


_ADJUDICATION = (
    "CTA-R 独立公共数据前瞻账本；只读展示研究模拟，不恢复冻结策略、不产生订单，"
    "前瞻结果不构成晋级证据。"
)


def _ledger_path(config: Dict[str, Any]) -> Path:
    root = Path(
        os.environ.get("QOUNT_CTA_R_STATE_ROOT")
        or config.get("root")
        or "state/cta_r"
    ).expanduser()
    explicit = os.environ.get("QOUNT_CTA_R_FORWARD_LEDGER") or config.get("ledger")
    return Path(explicit).expanduser() if explicit else root / "forward-ledger.jsonl"


@register_adapter("cta_r_forward")
def adapt_cta_r_forward(line_id: str, name: str, config: Dict[str, Any]) -> PaperLine:
    ledger_path = _ledger_path(config)
    if not ledger_path.is_file() or ledger_path.is_symlink():
        return unavailable_line(
            line_id,
            name,
            "equity",
            str(ledger_path),
            "SOURCE_NOT_FOUND: CTA-R forward ledger is absent; no performance figures are reported.",
            _ADJUDICATION,
        )

    try:
        ledger = read_ledger(ledger_path)
        forward_start=config.get("forward_start")
        if forward_start:
            # Rebase on a recorded restart boundary; old catchup stays in the
            # original ledger and historical research line, not new performance.
            ledger=[entry for entry in ledger if entry["date"]>=forward_start]
        if not ledger or (not forward_start and ledger[0].get("kind") != "genesis"):
            raise ValueError("forward_ledger_genesis_missing")
        if any(entry.get("orders_authorized") is True for entry in ledger):
            raise ValueError("forward_ledger_order_guard_invalid")
        bars = [entry for entry in ledger[1:] if entry.get("kind") == "bar"] if forward_start else [entry for entry in ledger if entry.get("kind") == "bar"]
        if not bars and not forward_start:
            return unavailable_line(
                line_id,
                name,
                "equity",
                str(ledger_path),
                "SOURCE_EMPTY: CTA-R ledger has no post-genesis forward bars yet.",
                _ADJUDICATION,
            )

        initial = float(ledger[0]["equity"] if forward_start else CONTRACT["initial_equity"])
        if not initial > 0.0:
            raise ValueError("forward_ledger_initial_equity_invalid")
        equity = initial
        signal_equity = initial
        cumulative_cost = 0.0
        peak_equity = initial
        worst_drawdown = 0.0
        nav_series = [
            NavPoint(
                date=str(ledger[0]["date"]),
                nav=1.0,
                signal_nav=1.0,
            )
        ]
        for entry in bars:
            gross_return = float(entry["gross_return"])
            prior_equity = equity
            signal_equity *= 1.0 + gross_return
            equity = float(entry["equity"])
            pre_cost_equity = prior_equity * (1.0 + gross_return)
            cumulative_cost += max(0.0, pre_cost_equity - equity)
            peak_equity = max(peak_equity, equity)
            worst_drawdown = min(worst_drawdown, equity / peak_equity - 1.0)
            nav_series.append(
                NavPoint(
                    date=str(entry["date"]),
                    nav=equity / initial,
                    signal_nav=signal_equity / initial,
                )
            )

        last = ledger[-1]
        final_equity = float(last["equity"])
        current_drawdown = final_equity / peak_equity - 1.0
        as_of = str(last["date"])
        stat = ledger_path.stat()
        produced_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        positions = [
            PositionItem(symbol=str(symbol), weight=float(weight))
            for symbol, weight in sorted((last.get("weights_after_close") or {}).items())
            if float(weight) > 0.0
        ]
        latest_error=None
        if config.get("status_path"):
            attempt=json.loads(Path(config["status_path"]).read_text())
            if attempt.get("status")!="valid":
                latest_error="LATEST_CTA_INPUT_REFRESH_FAILED"
    except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
        return unavailable_line(
            line_id,
            name,
            "equity",
            str(ledger_path),
            f"SOURCE_UNREADABLE: CTA-R forward ledger could not be verified ({type(exc).__name__}).",
            _ADJUDICATION,
        )

    return PaperLine(
        line_id=line_id,
        name=name,
        category="equity",
        status="ACTIVE_PAPER",
        adjudication=("原账本连续展示，含停跑历史补算；补算有真实记录时间，非当时前向运行。收盘权重收益代理，不等于次日开盘现金成交净值。" if config.get("continuous") else
            "按原冻结合同记录收盘权重收益代理；不等于下一开盘现金成交净值。恢复边界以前及补算不计入本段收益。" if forward_start else _ADJUDICATION),
        as_of=as_of,
        freshness=compute_freshness(as_of, config.get("reference_date")),
        curve_granularity="DAILY",
        nav_series=nav_series,
        metrics=LineMetrics(
            initial_equity=initial,
            observation_count=len(nav_series),
            trading_days=len(bars),
            max_drawdown_pct=round(worst_drawdown * 100.0, 4),
            current_drawdown_pct=round(current_drawdown * 100.0, 4),
            signal_nav=round(signal_equity / initial, 8),
            executable_nav=round(final_equity / initial, 8),
            cumulative_cost=round(cumulative_cost, 6),
            start_date=str(ledger[0]["date"]),
            days=len(nav_series),
        ),
        positions=positions,
        position_status="KNOWN" if isinstance(last.get("weights_after_close"), dict) else "UNKNOWN",
        cost_assumptions={"combined_cost_per_side_bps": float(CONTRACT["cost_per_side"]) * 10000.0},
        execution_constraints=[
            "成本采用合同的单边综合费率近似，不能拆成已核验佣金、滑点或价差。",
            "合同按收盘决策并在调仓之间维持权重；未确认真实成交能力与个人账户交易单位。",
        ],
        source=LineSource(
            path=str(ledger_path),
            sha256=compute_sha256(str(ledger_path)),
            produced_at=produced_at,
            venue="sse_szse" if forward_start or config.get("continuous") else None,
            instrument_type="ETF_ADJUSTED_PROXY" if forward_start or config.get("continuous") else None,
            price_source="tencent_public_qfq" if forward_start or config.get("continuous") else None,
            observation_kind="continuous_paper" if config.get("continuous") else "forward_paper" if forward_start else None,
            segments=observation_segments(ledger) if config.get("continuous") else [],
            execution_symbols=list(CONTRACT["universe"]) if forward_start or config.get("continuous") else [],
        ),
        safety=LineSafety(research_only=True, orders_authorized=False),
        error=latest_error,
    )
