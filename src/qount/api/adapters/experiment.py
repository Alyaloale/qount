"""Read explicitly selected, isolated offline runs; no strategy imports."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path

from qount.api.adapters import register_adapter
from qount.api.adapters.utils import unavailable_line
from qount.api.schemas import PaperLine, LineSource, LineMetrics, NavPoint
from qount.research.engine.runs import cached_run


def stamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def read_experiment(line_id, config, run_id=None):
    root = Path(config["root"])
    selected = run_id or config.get("run_id")
    if not selected or not re.fullmatch(r"[a-f0-9]{20,64}", selected):
        raise ValueError("experiment_selection_required")
    path = root / selected
    if not path.exists() and len(selected) == 64:
        path = root / selected[:20]
    summary = json.loads((path / "summary.json").read_text())
    if (summary["line_id"] != line_id or not summary["run_id"].startswith(selected)
            or summary.get("research_only") is not True or summary.get("orders_authorized") is not False):
        raise ValueError("experiment_identity_invalid")
    cached_run(path, summary["run_id"])
    return path, summary, json.loads((path / "nav.json").read_text()), json.loads((path / "trades.json").read_text())


def experiment_trade_events(line_id, config, run_id=None):
    _, _, _, trades = read_experiment(line_id, config, run_id)
    events = []
    for trade in trades:
        short = trade.get("direction", 1) in (-1, "short")
        for leg, side in (("entry", "SELL" if short else "BUY"), ("exit", "BUY" if short else "SELL")):
            if trade.get(leg+"_time") is None or trade.get(leg+"_price") is None:
                continue
            events.append(dict(date=stamp(trade[leg+"_time"]), symbol=trade["symbol"],
                side=side, quantity=trade["quantity"], price=trade[leg+"_price"],
                cost=trade.get(leg+"_fee"),
                note=("历史回测；样本末尾估值，非真实成交" if leg == "exit" and trade.get("exit_reason") == "end_of_sample"
                      else "历史回测；" + str(trade.get("exit_reason", "入场") if leg == "exit" else "入场"))))
    return events


@register_adapter("experiment")
def adapt_experiment(line_id, name, config):
    try:
        path, summary, nav, _ = read_experiment(line_id, config)
        raw = (path / "summary.json").read_bytes()
        return PaperLine(line_id=line_id, run_id=summary["run_id"], name=name, category=config.get("category", "macro"),
            as_of=stamp(nav[-1]["t"]), freshness="HISTORICAL", paper_enabled=False,
            adjudication=summary.get("conclusion", "已消费历史探索；执行近似及限制以本次实验说明为准。"),
            nav_series=[NavPoint(date=stamp(p["t"]), nav=p["nav"], benchmark_nav=p.get("benchmark_nav")) for p in nav],
            metrics=LineMetrics(total_return_pct=summary["total_return_pct"], max_drawdown_pct=summary["max_drawdown_pct"],
                current_drawdown_pct=summary.get("current_drawdown_pct"),
                initial_equity=summary.get("initial_capital"),
                cagr_pct=summary["cagr_pct"], calmar=summary["calmar"], trade_count=summary["trade_count"],
                start_date=stamp(nav[0]["t"]), days=int(summary["days"])),
            position_status="NOT_APPLICABLE",
            source=LineSource(path=str(path / "summary.json"), sha256=hashlib.sha256(raw).hexdigest(),
                observation_kind="historical_backtest"),
            cost_assumptions={"commission_bps":summary["parameters"]["fee"]*10000,
                              "slippage_bps":summary["parameters"]["slip"]*10000},
            execution_constraints=summary.get("limitations", []))
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return unavailable_line(line_id, name, config.get("category", "macro"), str(config.get("root", "")),
                                "SOURCE_UNREADABLE", "请选择完整的离线实验；曲线与成交须来自同一次运行。")
