"""Read-only USD-M fills and income; immutable records, no order authority."""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from qount.binance_assets import load_binance_assets

SYMBOLS = tuple(
    asset.execution_symbol
    for asset in load_binance_assets()
    if asset.status == "active"
)


def _number(value):
    if isinstance(value,bool):raise ValueError("invalid_amount")
    value=float(value)
    if not math.isfinite(value):raise ValueError("invalid_amount")
    return value


def _id(value):
    if isinstance(value,bool) or not re.fullmatch(r"\d+",str(value)):raise ValueError("invalid_record_id")
    return str(value)


def _fill(row,symbol):
    if row["symbol"]!=symbol or not re.fullmatch(r"[A-Z0-9_]+",symbol) or row["side"] not in ("BUY","SELL") or row["positionSide"] not in ("BOTH","LONG","SHORT"):
        raise ValueError("invalid_fill_identity")
    price,quantity=_number(row["price"]),_number(row["qty"])
    if min(price,quantity)<=0:raise ValueError("invalid_fill_size")
    trade_id = _id(row["id"])
    return dict(account_record_id=f"fill:{symbol}:{trade_id}", symbol=symbol,trade_id=trade_id,order_id=_id(row["orderId"]),
                time=int(_id(row["time"])),side=row["side"],position_side=row["positionSide"],
                price=price,quantity=quantity,realized_pnl=_number(row["realizedPnl"]),
                commission=_number(row["commission"]),commission_asset=str(row["commissionAsset"]),
                pnl_asset="USDT" if symbol.endswith("USDT") else "USDC" if symbol.endswith("USDC") else None,
                strategy_id=None,signal_id=None,order_intent_id=None,attribution="unassigned_account_fill")


def _income(row):
    kind=str(row["incomeType"]);symbol=str(row.get("symbol") or "")
    if not re.fullmatch(r"[A-Z0-9_]+",kind) or (symbol and not re.fullmatch(r"[A-Z0-9_]+",symbol)):
        raise ValueError("invalid_income_identity")
    transaction_id = _id(row["tranId"])
    return dict(account_record_id=f"income:{kind}:{transaction_id}", symbol=symbol,income_type=kind,transaction_id=transaction_id,
                time=int(_id(row["time"])),amount=_number(row["income"]),asset=str(row["asset"]),
                strategy_id=None,signal_id=None,order_intent_id=None,attribution="unassigned_account_income")


def collect_trade_records(exchange, *, now_ms=None, symbols=SYMBOLS, limit=1000, max_calls=32):
    """Only GET userTrades/income. Split saturated time intervals without gaps.

    No fromId+time combination, no timestamp+1 skip of tied records. A saturated
    millisecond or exhausted request budget is explicit incomplete coverage.
    First window is7days; durable storage retains earlier collected records.
    """
    now_ms=int(datetime.now(timezone.utc).timestamp()*1000) if now_ms is None else now_ms
    start=now_ms-7*86400000+1
    calls=0
    errors={};fills=[];income=[];completed=[]
    def window(method,params,left,right):
        nonlocal calls
        if calls>=max_calls:raise ValueError("history_request_budget_exhausted")
        calls+=1
        rows=method({**params,"startTime":left,"endTime":right,"limit":limit})
        if not isinstance(rows,list) or len(rows)>limit:raise ValueError("invalid_history_response")
        if any(not left<=int(_id(r["time"]))<=right for r in rows):raise ValueError("history_outside_requested_window")
        if len(rows)<limit:return rows
        if left==right:raise ValueError("history_saturated_millisecond")
        # Split near observed activity rather than spending the request budget
        # halving days of empty history around a dense recent burst.
        mid=min(right-1,max(left,sorted(int(r["time"]) for r in rows)[len(rows)//2]))
        return window(method,params,left,mid)+window(method,params,mid+1,right)
    try:
        income=[_income(r) for r in window(exchange.fapiPrivateGetIncome,{},start,now_ms)]
    except Exception as exc:
        errors["income"]=type(exc).__name__
    requested=sorted(set(symbols)|{r["symbol"] for r in income if r["symbol"]})
    for symbol in requested:
        if not re.fullmatch(r"[A-Z0-9_]+",symbol):
            raise ValueError("invalid_account_symbol")
        try:
            rows=[_fill(r,symbol) for r in window(exchange.fapiPrivateGetUserTrades,{"symbol":symbol},start,now_ms)]
            fills+=rows;completed.append(symbol)
        except Exception as exc:
            # Never retain signed URLs, account credentials or exception text.
            errors[symbol]=type(exc).__name__
    return dict(schema_version=1,observed_at=datetime.fromtimestamp(now_ms/1000,timezone.utc).isoformat(),
                window_start_ms=start,window_end_ms=now_ms,status="AVAILABLE" if not errors else "PARTIAL" if completed or income else "ERROR",
                requested_symbols=requested,completed_symbols=completed,errors=errors,request_count=calls,
                fills=fills,income=income,read_only=True,orders_authorized=False,
                scope="Binance USD-M: requested symbols plus symbols discovered in 7-day account income; not all lifetime fills",
                attribution="Account records; no strategy ownership inferred from ticker or time")


def persist_trade_records(path: Path, snapshot):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink():raise ValueError("unsafe_trade_history_path")
    encode=lambda x:json.dumps(x,sort_keys=True,separators=(",",":"),allow_nan=False)
    with sqlite3.connect(path,timeout=10) as conn:
        os.chmod(path,0o600)
        conn.execute("CREATE TABLE IF NOT EXISTS account_records(kind TEXT, record_key TEXT, time_ms INTEGER, symbol TEXT, payload TEXT, PRIMARY KEY(kind,record_key))")
        conn.execute("CREATE TABLE IF NOT EXISTS account_collection(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS account_collection_history(observed_at TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        for kind,rows in (("fill",snapshot["fills"]),("income",snapshot["income"])):
            for row in rows:
                key=encode([row["symbol"],row["trade_id"]] if kind=="fill" else [row["income_type"],row["transaction_id"]])
                encoded=encode(row)
                old=conn.execute("SELECT payload FROM account_records WHERE kind=? AND record_key=?",(kind,key)).fetchone()
                if old and old[0]!=encoded:
                    previous = json.loads(old[0])
                    # record_id is derived metadata added after the first
                    # production collection. Keep the original payload intact;
                    # missing metadata must not reject unchanged exchange facts.
                    if previous.get("account_record_id") is None and "account_record_id" in row:
                        previous["account_record_id"] = row.get("account_record_id")
                    for field in ("signal_id", "order_intent_id"):
                        if field not in previous and field in row and row[field] is None:
                            previous[field] = None
                    if previous != row:
                        raise ValueError("immutable_account_record_conflict")
                conn.execute("INSERT OR IGNORE INTO account_records VALUES(?,?,?,?,?)",(kind,key,row["time"],row["symbol"],encoded))
        meta={k:v for k,v in snapshot.items() if k not in ("fills","income")}
        conn.execute("INSERT INTO account_collection VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",(encode(meta),))
        conn.execute("INSERT OR IGNORE INTO account_collection_history VALUES(?,?)", (meta["observed_at"], encode(meta)))


def execution_links(path: Path) -> dict[tuple[str, str], dict]:
    """Exact exchange-order identities only; never infer ownership from time/ticker."""
    if not path.is_file():
        return {}
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=5) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT symbol,exchange_order_id,client_order_id,strategy_id,signal_id,order_intent_id FROM orders WHERE exchange_order_id IS NOT NULL").fetchall()
    links = {}
    for row in rows:
        key = (row["symbol"], str(row["exchange_order_id"]))
        link = {k: row[k] for k in ("client_order_id", "strategy_id", "signal_id", "order_intent_id")}
        if key in links and links[key] != link:
            raise ValueError("conflicting_execution_ownership")
        links[key] = link
    return links


def attribute_fills(fills: list[dict], links: dict) -> list[dict]:
    return [dict(row, **links[(row["symbol"], str(row["order_id"]))], attribution="exact_exchange_order")
            if (row["symbol"], str(row["order_id"])) in links else dict(row) for row in fills]


def strategy_accounting(path: Path, execution_path: Path, strategy_id: str) -> dict:
    """Partial realized economics, with unknown funding/coverage kept explicit."""
    result = dict(strategy_id=strategy_id, status="MISSING", assigned_fill_count=0,
                  realized_pnl_usdt=None, commission_by_asset={}, net_pnl_usdt=None,
                  funding_complete=False, note="成交归属、资金费与历史覆盖尚未完整，暂不计算净收益。")
    if not path.is_file() or not execution_path.is_file():
        return result
    try:
        links = execution_links(execution_path)
        with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=5) as conn:
            all_rows = [json.loads(row[0]) for row in conn.execute("SELECT payload FROM account_records WHERE kind='fill'")]
        all_rows = attribute_fills(all_rows, links)
        rows = sorted([r for r in all_rows if r.get("strategy_id") == strategy_id], key=lambda r:r["time"])
        if not rows:
            return result | {"note": "尚无本策略归属成交；账户曲线包含手动和旧策略交易，不能替代本策略收益。"}
        fees = {}
        for r in rows:
            asset = r["commission_asset"]
            fees[asset] = fees.get(asset, 0.0) + r["commission"]
        result.update(status="PARTIAL", assigned_fill_count=len(rows), commission_by_asset=fees,
                      realized_pnl_usdt=sum(r["realized_pnl"] for r in rows) if all(r.get("pnl_asset") == "USDT" for r in rows) else None)
        # Certify only fully closed long round trips with complete fill/income
        # windows and no competing ownership. Open positions remain partial.
        from qount.operations.account_performance import income_history, covered
        income, coverage = income_history(path)
        first, last = rows[0]["time"], rows[-1]["time"]
        complete = covered(coverage, first, last) and result["realized_pnl_usdt"] is not None and set(fees) <= {"USDT"}
        funding = 0.0
        for symbol in {r["symbol"] for r in rows}:
            _, fills_coverage = income_history(path, symbol=symbol)
            complete = complete and covered(fills_coverage, first, last)
            events = [(r["time"], 0, r) for r in all_rows if r["symbol"] == symbol and first <= r["time"] <= last]
            events += [(r["time"], 1, r) for r in income if r["symbol"] == symbol and first <= r["time"] <= last]
            position = 0.0
            for _, kind, r in sorted(events, key=lambda e:(e[0],e[1])):
                if kind == 0:
                    if r.get("strategy_id") != strategy_id or r["position_side"] != "BOTH":
                        complete = False
                    position += r["quantity"]*(1 if r["side"] == "BUY" else -1)
                    complete = complete and position >= -1e-9
                elif r["income_type"] == "FUNDING_FEE":
                    # Same-millisecond fills and funding have unknown ordering.
                    ambiguous = any(f["time"] == r["time"] for f in rows if f["symbol"] == symbol)
                    if ambiguous or r["asset"] != "USDT":
                        complete = False
                    elif position > 1e-9:
                        funding += r["amount"]
                elif r["income_type"] not in {"REALIZED_PNL", "COMMISSION"}:
                    complete = False
            complete = complete and abs(position) <= 1e-9
        with sqlite3.connect(f"file:{execution_path.resolve()}?mode=ro", uri=True) as conn:
            expected = conn.execute("SELECT symbol,exchange_order_id,executed_quantity FROM orders WHERE strategy_id=? AND executed_quantity>0", (strategy_id,)).fetchall()
        for symbol, order_id, quantity in expected:
            complete = complete and math.isclose(sum(r["quantity"] for r in rows
                if r["symbol"] == symbol and str(r["order_id"]) == str(order_id)), quantity, abs_tol=1e-9)
        if complete:
            result.update(status="AVAILABLE", funding_complete=True, funding_usdt=funding,
                          net_pnl_usdt=result["realized_pnl_usdt"]-fees.get("USDT", 0.0)+funding,
                          note="已闭合成交按订单精确归属，已扣手续费并计入可确认资金费；未计算本金收益率。")
        return result
    except (sqlite3.Error, ValueError, KeyError, TypeError):
        return result | {"status": "ERROR", "note": "策略归属记录不可用，已有账户记录仍独立保留。"}


def read_trade_records(path: Path, *, limit=100, execution_path: Path | None = None):
    empty=dict(status="MISSING",observed_at=None,fills=[],income=[],fill_count=None,income_count=None,
               read_only=True,orders_authorized=False,error="ACCOUNT_HISTORY_NOT_COLLECTED")
    if not path.is_file():return empty
    try:
        with sqlite3.connect(f"file:{path.resolve()}?mode=ro",uri=True,timeout=5) as conn:
            row=conn.execute("SELECT payload FROM account_collection WHERE id=1").fetchone()
            if not row:return empty
            meta=json.loads(row[0])
            if meta.get("read_only") is not True or meta.get("orders_authorized") is not False:raise ValueError("invalid_history_identity")
            result={**meta,"fills":[],"income":[],"error":None}
            for kind,key in (("fill","fills"),("income","income")):
                rows=conn.execute("SELECT payload FROM account_records WHERE kind=? ORDER BY time_ms DESC,record_key DESC LIMIT ?",(kind,limit)).fetchall()
                result[key]=[json.loads(r[0]) for r in rows]
                for record in result[key]:
                    if not record.get("account_record_id"):
                        record["account_record_id"] = (f"fill:{record['symbol']}:{record['trade_id']}" if kind == "fill"
                            else f"income:{record['income_type']}:{record['transaction_id']}")
                result["fill_count" if kind=="fill" else "income_count"]=conn.execute("SELECT count(*) FROM account_records WHERE kind=?",(kind,)).fetchone()[0]
            if execution_path is not None:
                try:
                    result["fills"] = attribute_fills(result["fills"], execution_links(execution_path))
                except (sqlite3.Error, ValueError):
                    result["attribution_error"] = "execution_links_unavailable"
            return result
    except (OSError,sqlite3.Error,ValueError,TypeError,KeyError):
        return empty|dict(status="ERROR",error="ACCOUNT_HISTORY_UNREADABLE")
