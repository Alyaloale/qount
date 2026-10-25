"""Read the revised G20 cash book; preserve the old price-only curve as reference."""
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from qount.api.adapters import register_adapter
from qount.api.adapters.utils import compute_freshness, compute_sha256, observation_segments, unavailable_line
from qount.api.schemas import LineMetrics, LineSafety, LineSource, NavPoint, PaperLine, PositionItem
from qount.dual_engine.g20_cash import SYMBOLS, validate


def g20_cash_trades(config):
    data=json.loads((Path(config["root"])/"forward.json").read_text())
    validate(data)
    events=list(data["trades"])
    for a in data["income"]:
        events.append(dict(date=a["date"],symbol=a["symbol"],side=a["side"],quantity=a["quantity"],
            price=a["amount"],cost=0.,sample_kind=a["sample_kind"],recorded_at=a["recorded_at"],
            note=f"税前模型分红{a['value']:.6f} USD_EQ；除息日{a.get('ex_date',a['date'])}；"
                 f"到账日{a['pay_date'] or '未知，保留应收且不使用'}；金额来源{a['amount_source']}；"
                 f"{a['source']}；应收转现金不重复计收益；非券商真实到账"))
    return events


@register_adapter("g20_cash")
def adapt_g20_cash(line_id,name,config):
    path=Path(config["root"])/"forward.json"
    try:
        data=json.loads(path.read_text());validate(data)
        rows=data["observations"];initial=data["initial_equity"]
        if not rows:raise ValueError("g20_cash_empty")
        peak=initial;worst=0.
        for r in rows:peak=max(peak,r["equity"]);worst=min(worst,r["equity"]/peak-1)
        last=rows[-1]
        prior_year=[r for r in rows if r["date"][:4] < last["date"][:4]]
        year_initial=prior_year[-1]["equity"] if prior_year else initial
        legacy={}
        legacy_path=Path(config.get("legacy_root",str(path.parent.parent)))/"state/program.json"
        if legacy_path.exists():
            raw=json.loads(legacy_path.read_text())["portfolios"]["dual-engine-paper-g20"]["history"]
            for r in raw:
                day=dt.datetime.fromisoformat(r["data_cutoff"]).astimezone(ZoneInfo("America/New_York")).date().isoformat()
                legacy[day]=r["executable_nav"]
        return PaperLine(line_id=line_id,name=name,run_id=data["created_at"],category="equity",status="ACTIVE_PAPER",
            paper_enabled=True,sample_kind="mixed",research_status="forward",
            as_of=last["date"],freshness=compute_freshness(last["date"],config.get("reference_date")),curve_granularity="DAILY",
            adjudication="G20现金分红会计修正版：63日调整价格排名、月度20%/80%BIL不变；历史重算单列，非当时前向。基准曲线为旧G20未计分红的价格模拟。",
            metrics=LineMetrics(initial_equity=initial,observation_count=len(rows),trading_days=len(rows),
                total_return_pct=(last["equity"]/initial-1)*100,ytd_return_pct=(last["equity"]/year_initial-1)*100,
                max_drawdown_pct=-worst*100,current_drawdown_pct=(1-last["equity"]/peak)*100,
                executable_nav=last["equity"]/initial,cumulative_cost=data["layer"]["cumulative_cost"],
                trade_count=sum(t["side"] in ("BUY","SELL") for t in data["trades"]),start_date=rows[0]["date"]),
            nav_series=[NavPoint(date=r["date"],nav=r["equity"]/initial,benchmark_nav=legacy.get(r["date"])) for r in rows],
            positions=[PositionItem(**p) for p in last["positions"]],position_status="KNOWN",
            source=LineSource(path=str(path),sha256=compute_sha256(str(path)),produced_at=data["observed_at"],
                venue="us_etf",instrument_type="ETF",price_source="yahoo_public_raw+issuer_cash_distributions",
                observation_kind="continuous_paper",execution_symbols=list(SYMBOLS),segments=observation_segments(rows)),
            cost_assumptions=dict(combined_cost_per_side_bps=20.,cash_apr_pct=0.,lot_size=1,
                dividend_cash_received=data["distributions_received"],dividend_receivable=last["receivable"],
                taxes="gross_before_tax",dividend_policy=data["rules"]["dividend_policy"]),
            execution_constraints=["月末收盘决定，下一可用开盘价模拟；未知/晚到的决策不倒填成交。",
                "整数股、单边20bp综合摩擦；分红除息记应收，发行人到账日收盘转现金、下一交易日才可使用。",
                "BIL已核对发行人金额与日期；其他未核验金额沿公开行情精度，未知到账日保留应收不使用。",
                "税前模型，非券商净到账；未证明真实开盘容量、税费或实盘盈利。",
                "20%为月度资金目标，月内允许漂移，不是止损或连续风险上限。"],
            safety=LineSafety(),error=data.get("last_error"))
    except (OSError,ValueError,KeyError,TypeError) as exc:
        return unavailable_line(line_id,name,"equity",str(path),f"G20_CASH_UNAVAILABLE:{type(exc).__name__}")
