"""Actual forward snapshots, separate from preserved historical studies."""
import json
from pathlib import Path

from qount.api.adapters import register_adapter
from qount.api.adapters.utils import compute_freshness, compute_sha256, unavailable_line, observation_segments
from qount.api.schemas import LineMetrics, LineSafety, LineSource, NavPoint, PaperLine, PositionItem


@register_adapter("research_paper")
def adapt_research_paper(line_id,name,config):
    path=Path(config["root"])/"forward.json"
    try:
        data=json.loads(path.read_text())
        if data["research_only"] is not True or data["orders_authorized"] is not False:
            raise ValueError("paper_order_guard_invalid")
        observations=data["observations"];initial=data["initial_equity"]
        if not observations or initial<=0:raise ValueError("paper_observations_missing")
        peak=initial;worst=0.
        for row in observations:
            peak=max(peak,row["equity"]);worst=min(worst,row["equity"]/peak-1)
        last=observations[-1];reconstructed=sum(r.get("sample_kind")=="reconstructed" for r in observations)
        etf=data["kind"]=="etf"
        return PaperLine(line_id=line_id,run_id=data["created_at"],name=name,
            category="equity" if etf else "macro",as_of=last["date"],status="ACTIVE_PAPER",
            freshness=compute_freshness(last["date"]),curve_granularity="DAILY",
            adjudication=(f"沿用原模拟的资金、持仓和规则续接；含历史补算{reconstructed}条，非当时运行。小数模型份额，假定现金年收益2%，非实际到账。" if data.get("continuous") else
                f"从实际启动观测起算；历史仅作预热。补算{reconstructed}条单列，非当时运行。日线OHLC撮合模型，无真实订单。"),
            nav_series=[NavPoint(date=r["date"],nav=r["equity"]/initial,benchmark_nav=r.get("benchmark_nav")) for r in observations],
            metrics=LineMetrics(initial_equity=initial,total_return_pct=(last["equity"]/initial-1)*100,
                max_drawdown_pct=-worst*100,current_drawdown_pct=(1-last["equity"]/peak)*100,
                observation_count=len(observations),trading_days=max(0,len(observations)-1),
                trade_count=sum(t["side"] in ("BUY","SELL") for t in data["trades"]),
                corporate_action_count=sum(t["side"] in ("SPLIT","CORPORATE_ACTION_SPLIT") for t in data["trades"]),start_date=observations[0]["date"],
                executable_nav=last["equity"]/initial),
            positions=[PositionItem(**p) for p in last["positions"]],position_status="KNOWN",
            source=LineSource(path=str(path),sha256=compute_sha256(str(path)),produced_at=data["observed_at"],
                venue="sse_szse" if etf else "us_etf",instrument_type="ETF",price_source=data["source"],
                observation_kind="continuous_paper" if data.get("continuous") else "forward_paper",
                segments=observation_segments(observations),execution_symbols=["513100.SH"] if etf else
                    ["SPY","SMH","IWM","XLI","XLB","GLD","CPER","XLU","TLT","UUP"]),
            cost_assumptions=dict(data["rules"],cash_apr_pct=data["rules"].get("cash_apr",0)*100) if etf else dict(commission_bps=3,slippage_bps=5,gap_stress_pct=1.5,cash_apr=0),
            execution_constraints=["日线模拟按前一日计划撮合，OHLC无法确认真实成交、盘中路径或盘口容量。",
                ("ETF历史模型：小数份额，现金假定2%年收益；不是个人账户整手成交或已实现利息。" if data.get("continuous") else
                 "ETF择时为100份整数手与现金0收益；通用状态为1X模型，关闭后续版本优化和假定现金生息。"),
                "历史、补算和实际观测分段解释；补算与已消费历史不属于独立前向验证。"],
            safety=LineSafety(),error=data.get("last_error"))
    except (OSError,ValueError,KeyError,TypeError) as exc:
        return unavailable_line(line_id,name,"equity",str(path),f"SOURCE_UNAVAILABLE:{type(exc).__name__}")


def research_paper_trades(config):
    data=json.loads((Path(config["root"])/"forward.json").read_text())
    return data["trades"]
