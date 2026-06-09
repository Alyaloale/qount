"""CTA-R portfolio tracker + rebalance alert (research-only; no broker, no orders).

Human-in-the-loop semi-automation for the monthly cross-asset ETF basket:

- **manual position sync**: you record what you actually hold in a local JSON
  (edit it after each fill);
- **auto P&L**: it values the book from the latest cached/refreshed ETF prices;
- **rebalance alert**: it flags when a rebalance is due (cadence elapsed OR the
  trend book drifted past a threshold) and prints the exact buy/sell lot orders
  to reach the engine's target weights — which you then place manually.

No broker API, no order placement, no live trading. Pure stdlib; price refresh
is an optional best-effort akshare top-up. The target book reuses the validated
``cta_sim`` engine (``_target_weights`` + ``MODE_PRESETS``, fixed lookbacks).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cta_data import ETF_ASSET_CLASS, exclude_asset_classes, load_etf_cache
from .cta_sim import MODE_PRESETS, SimConfig, _target_weights

CTA_PORTFOLIO_VERSION = "cta_portfolio_v1"
LOT = 100  # A-share ETF lot = 100 shares
FIXED_LOOKBACKS = (63, 126, 252)
FIXED_VOL_LB = 63
REBALANCE_DAYS = 21  # trading-day cadence (matches the engine)
DRIFT_THRESHOLD = 0.05  # |target - current| weight gap that forces an off-cadence rebalance

ETF_NAMES = {
    "510300.SH": "沪深300ETF", "510500.SH": "中证500ETF", "159915.SZ": "创业板ETF",
    "510050.SH": "上证50ETF", "518880.SH": "黄金ETF", "511010.SH": "国债ETF",
    "513100.SH": "纳指ETF", "513500.SH": "标普500ETF",
}
QDII = {"513100.SH", "513500.SH"}


# ---------------------------------------------------------------------------
# Pure logic (unit-tested): valuation, target book, rebalance orders, due-check.
# ---------------------------------------------------------------------------
def value_holdings(
    holdings: dict[str, dict[str, float]], cash: float, latest_px: dict[str, float]
) -> dict[str, Any]:
    """Mark the book to ``latest_px``; per-position + portfolio P&L. No network."""
    rows: list[dict[str, Any]] = []
    total_mv = 0.0
    total_cost = 0.0
    for sym, pos in holdings.items():
        shares = float(pos.get("shares", 0.0))
        avg_cost = float(pos.get("avg_cost", 0.0))
        px = latest_px.get(sym, 0.0)
        mv = shares * px
        cost = shares * avg_cost
        total_mv += mv
        total_cost += cost
        rows.append({
            "symbol": sym, "shares": shares, "avg_cost": avg_cost, "last_px": px,
            "market_value": mv, "cost_basis": cost,
            "pnl": mv - cost, "pnl_pct": (mv / cost - 1.0) if cost > 0 else None,
        })
    equity = total_mv + cash
    for r in rows:
        r["weight"] = (r["market_value"] / equity) if equity > 0 else 0.0
    return {
        "rows": rows, "cash": cash, "total_market_value": total_mv,
        "total_cost_basis": total_cost, "equity": equity,
        "total_pnl": total_mv - total_cost,
        "total_pnl_pct": (total_mv / total_cost - 1.0) if total_cost > 0 else None,
    }


def target_book(prices: dict[str, list[float]], mode: str) -> dict[str, float]:
    """Current target weights from the validated engine (final rebalance weights)."""
    preset = MODE_PRESETS[mode]
    panel = exclude_asset_classes(prices, preset["exclude_classes"]) if preset["exclude_classes"] else prices
    config = SimConfig(
        lookback_days=FIXED_LOOKBACKS, vol_lookback_days=FIXED_VOL_LB, rebalance_days=REBALANCE_DAYS,
        target_vol=preset["target_vol"], max_leverage=preset["max_leverage"],
        long_only=preset["long_only"], max_weight=preset["max_weight"],
    )
    names = list(panel)
    length = len(panel[names[0]])
    rets: dict[str, list[float | None]] = {}
    for n in names:
        s: list[float | None] = [None]
        for t in range(1, length):
            prev = panel[n][t - 1]
            s.append(panel[n][t] / prev - 1.0 if prev > 0 else None)
        rets[n] = s
    warmup = max(max(FIXED_LOOKBACKS), FIXED_VOL_LB) + 1
    equity, peak, weights = 1.0, 1.0, {}
    for t in range(1, length):
        port = sum(w * rets[n][t] for n, w in weights.items() if rets[n][t] is not None)
        equity *= 1.0 + port
        peak = max(peak, equity)
        if t >= warmup and t % REBALANCE_DAYS == 0:
            weights = _target_weights(panel, rets, t, config, equity, peak)
            peak = max(peak, equity)
    return weights


def rebalance_orders(
    holdings: dict[str, dict[str, float]], target_w: dict[str, float],
    latest_px: dict[str, float], equity: float,
) -> list[dict[str, Any]]:
    """Buy/sell lot orders to move current shares to the target book. No network."""
    universe = set(holdings) | set(target_w)
    orders: list[dict[str, Any]] = []
    for sym in sorted(universe):
        px = latest_px.get(sym, 0.0)
        if px <= 0:
            continue
        cur_shares = float(holdings.get(sym, {}).get("shares", 0.0))
        tgt_shares = int(equity * target_w.get(sym, 0.0) / px / LOT) * LOT
        delta = tgt_shares - cur_shares
        lots = int(round(delta / LOT))
        if lots == 0:
            continue
        orders.append({
            "symbol": sym, "side": "BUY" if lots > 0 else "SELL",
            "lots": abs(lots), "shares": abs(lots) * LOT, "limit_ref": px,
            "amount": abs(lots) * LOT * px,
        })
    return orders


def apply_fill(positions: dict[str, Any], symbol: str, side: str, shares: float, price: float) -> dict[str, Any]:
    """Apply a manual fill to the positions dict (updates shares/avg_cost/cash).

    Buy: blends avg_cost, debits cash. Sell: frees cash, keeps avg_cost on the
    remainder (realized P&L not separately tracked). Commission ignored — adjust
    cash by hand if you want it exact. Mutates and returns ``positions``.
    """
    holdings: dict[str, dict[str, float]] = positions.setdefault("holdings", {})
    cur = holdings.get(symbol, {"shares": 0.0, "avg_cost": 0.0})
    cs, ca = float(cur["shares"]), float(cur["avg_cost"])
    if side == "buy":
        new_shares = cs + shares
        new_cost = (cs * ca + shares * price) / new_shares if new_shares > 0 else 0.0
        positions["cash"] = float(positions.get("cash", 0.0)) - shares * price
    elif side == "sell":
        new_shares = cs - shares
        new_cost = ca
        positions["cash"] = float(positions.get("cash", 0.0)) + shares * price
    else:
        raise ValueError(f"side must be buy/sell, got {side!r}")
    if new_shares <= 0:
        holdings.pop(symbol, None)
    else:
        holdings[symbol] = {"shares": new_shares, "avg_cost": new_cost}
    return positions


def _sina_secid(symbol: str) -> str:
    code, ex = symbol.split(".")
    return ("sh" if ex.upper() == "SH" else "sz") + code


def parse_sina_quote(line: str) -> tuple[str, float, float] | None:
    """Parse one Sina ``var hq_str_sh510300="名称,开,昨收,现价,...";`` line.

    Returns ``(secid, current_price, prev_close)`` or ``None``. Pure (no network);
    ETF intraday valuation uses the RAW (unadjusted) traded price — distinct from
    the qfq-adjusted cache series used only for signals/target weights.
    """
    if "=\"" not in line:
        return None
    secid = line.split("hq_str_")[1].split("=")[0]
    body = line.split('="', 1)[1].rstrip('";\n')
    parts = body.split(",")
    if len(parts) < 4:
        return None
    try:
        prev_close = float(parts[2])
        current = float(parts[3])
    except ValueError:
        return None
    price = current if current > 0 else prev_close  # pre-open -> prev close
    return secid, price, prev_close


def fetch_spot_sina(symbols: list[str], timeout: float = 8.0) -> dict[str, dict[str, float]]:
    """Best-effort live raw quotes from Sina (domestic, stdlib, no proxy/dep).

    ``{symbol: {"price": .., "prev_close": ..}}``; empty on failure. The caller
    falls back to the cache close (a different, adjusted level) with a warning.
    """
    import urllib.request

    secids = {_sina_secid(s): s for s in symbols}
    url = "https://hq.sinajs.cn/list=" + ",".join(secids)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn",
    })
    out: dict[str, dict[str, float]] = {}
    raw = urllib.request.urlopen(req, timeout=timeout).read().decode("gbk", "ignore")
    for line in raw.splitlines():
        parsed = parse_sina_quote(line)
        if parsed:
            secid, price, prev = parsed
            sym = secids.get(secid)
            if sym and price > 0:
                out[sym] = {"price": price, "prev_close": prev}
    return out


def paper_execute(positions: dict[str, Any], orders: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply a list of rebalance orders to ``positions`` at each order's ``limit_ref``.

    SIMULATION ONLY: fills at the live reference price with no slippage/commission —
    the optimistic paper baseline. Real fills differ (spread/impact/QDII premium);
    that gap is exactly what a later small-size live test measures. Mutates positions.
    """
    for o in orders:
        apply_fill(positions, o["symbol"], o["side"].lower(), float(o["shares"]), float(o["limit_ref"]))
    return positions


def equity_curve_stats(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Summarize a daily equity log (list of ``{date, equity}``) for review. Pure."""
    pts = sorted(
        (str(r["date"]), float(r["equity"])) for r in rows
        if r.get("equity") not in (None, "")
    )
    if not pts:
        return None
    eq = [v for _d, v in pts]
    peak, maxdd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        if peak > 0:
            maxdd = min(maxdd, v / peak - 1.0)
    return {
        "n_days": len(eq), "first_date": pts[0][0], "last_date": pts[-1][0],
        "start_equity": eq[0], "current_equity": eq[-1],
        "total_return_pct": (eq[-1] / eq[0] - 1.0) if eq[0] > 0 else None,
        "peak_equity": max(eq), "trough_equity": min(eq), "max_drawdown": maxdd,
    }


def splice_daily(cache: dict[str, float], raw: dict[str, float]) -> tuple[dict[str, float], int]:
    """Extend an adjusted ``cache`` with new ``raw`` daily closes, seam-free. Pure.

    Anchors on the latest date present in BOTH series and carries the cache's
    adjusted level forward by the RAW return ratio — so the spliced level is
    continuous at the anchor regardless of the cache's adjustment base. Returns
    ``(updated_cache, n_appended)``. (A distribution after the anchor would inject
    a small spurious gap; rare for these ETFs over a 1-2 month window.)
    """
    if not cache or not raw:
        return dict(cache), 0
    overlap = [d for d in raw if d in cache]
    if not overlap:
        return dict(cache), 0
    anchor = max(overlap)
    raw_anchor = raw[anchor]
    if raw_anchor <= 0:
        return dict(cache), 0
    last = max(cache)
    out = dict(cache)
    n = 0
    for d in sorted(raw):
        if d > last and raw[d] > 0:
            out[d] = round(cache[anchor] * raw[d] / raw_anchor, 6)
            n += 1
    return out, n


def fetch_daily_sina(symbol: str, datalen: int = 60, timeout: float = 12.0) -> dict[str, float]:
    """Raw daily closes from Sina kline (stdlib, domestic, no dep). ``{date: close}``."""
    import urllib.request

    url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           f"CN_MarketData.getKLineData?symbol={_sina_secid(symbol)}&scale=240&ma=no&datalen={datalen}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore"))
    out: dict[str, float] = {}
    for row in data:
        day, close = row.get("day"), row.get("close")
        if day and close:
            try:
                out[day] = float(close)
            except ValueError:
                continue
    return out


def trading_days_since(dates: list[str], since_date: str) -> int:
    """Count panel trading dates strictly after ``since_date``."""
    return sum(1 for d in dates if d > since_date)


def rebalance_due(
    dates: list[str], last_rebalance_date: str,
    current_w: dict[str, float], target_w: dict[str, float],
    *, cadence: int = REBALANCE_DAYS, drift: float = DRIFT_THRESHOLD,
) -> dict[str, Any]:
    """Due if the trading-day cadence elapsed OR weights drifted past threshold."""
    elapsed = trading_days_since(dates, last_rebalance_date)
    syms = set(current_w) | set(target_w)
    max_drift = max((abs(target_w.get(s, 0.0) - current_w.get(s, 0.0)) for s in syms), default=0.0)
    reasons = []
    if elapsed >= cadence:
        reasons.append(f"cadence {elapsed}≥{cadence} 交易日")
    if max_drift >= drift:
        reasons.append(f"权重漂移 {max_drift*100:.1f}%≥{drift*100:.0f}%")
    return {"due": bool(reasons), "trading_days_elapsed": elapsed,
            "max_weight_drift": max_drift, "reasons": reasons}


# ---------------------------------------------------------------------------
# Persistence + CLI plumbing (not unit-tested: I/O only).
# ---------------------------------------------------------------------------
def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _positions_path() -> Path:
    return _repo_root() / "state" / "cta_portfolio" / "positions.json"


def _cache_dir() -> Path:
    return _repo_root() / "state" / "etf_cache"


def _trades_path() -> Path:
    return _repo_root() / "state" / "cta_portfolio" / "trades.jsonl"


def _equity_path() -> Path:
    return _repo_root() / "state" / "cta_portfolio" / "equity.csv"


def _append_trade(rec: dict[str, Any]) -> None:
    """Append one fill to the trade log (jsonl) for review."""
    p = _trades_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


_EQUITY_COLS = ["date", "equity", "market_value", "cash", "total_pnl",
                "total_pnl_pct", "day_pnl", "price_source"]


def _upsert_equity(row: dict[str, Any]) -> None:
    """Write one row per date (latest intraday value overwrites the same date)."""
    import csv
    p = _equity_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    by_date: dict[str, dict[str, Any]] = {}
    if p.exists():
        with p.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                by_date[r["date"]] = r
    by_date[row["date"]] = {k: row.get(k, "") for k in _EQUITY_COLS}
    with p.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=_EQUITY_COLS)
        w.writeheader()
        for d in sorted(by_date):
            w.writerow(by_date[d])


def _load_equity_rows() -> list[dict[str, Any]]:
    import csv
    p = _equity_path()
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _log_equity(res: dict[str, Any]) -> None:
    """Upsert today's equity snapshot from a status payload (one row per date)."""
    import datetime as _dt
    _upsert_equity({
        "date": _dt.date.today().isoformat(), "equity": round(res["equity"], 2),
        "market_value": round(res["total_market_value"], 2), "cash": round(res["cash"], 2),
        "total_pnl": round(res["total_pnl"], 2),
        "total_pnl_pct": round(res["total_pnl_pct"], 6) if res["total_pnl_pct"] is not None else "",
        "day_pnl": round(res["day_pnl"], 2), "price_source": res["price_source"],
    })


def load_positions(path: Path | None = None) -> dict[str, Any]:
    p = path or _positions_path()
    return json.loads(p.read_text(encoding="utf-8"))


def save_positions(data: dict[str, Any], path: Path | None = None) -> None:
    p = path or _positions_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_panel() -> tuple[list[str], dict[str, list[float]]]:
    cache = _cache_dir()
    symbols = sorted(p.stem for p in cache.glob("*.csv"))
    by = {s: load_etf_cache(str(cache), s) for s in symbols}
    common: set[str] | None = None
    for s in symbols:
        d = set(by[s])
        common = d if common is None else (common & d)
    dates = sorted(common or [])
    return dates, {s: [by[s][dt] for dt in dates] for s in symbols}


def _refresh_prices() -> None:
    """Advance the qfq daily cache with new Sina daily bars (stdlib, seam-free)."""
    from .cta_data import save_etf_cache
    cache_dir = _cache_dir()
    total = 0
    for sym in sorted(p.stem for p in cache_dir.glob("*.csv")):
        try:
            cache = load_etf_cache(str(cache_dir), sym)
            raw = fetch_daily_sina(sym)
            updated, n = splice_daily(cache, raw)
            if n:
                save_etf_cache(str(cache_dir), sym, updated)
                total += n
        except Exception as exc:  # noqa: BLE001 - best effort
            print(f"  [warn] 日线补尾 {sym} 失败: {str(exc)[:60]}")
    if total:
        print(f"  日线缓存已补 {total} 个(股×日),源=新浪。")


def _fmt_money(x: float) -> str:
    return f"{x:,.0f}"


def _build_status(pos: dict[str, Any]) -> dict[str, Any]:
    """Assemble the full status payload (live valuation + target + due + orders)."""
    dates, prices = _load_panel()
    mode = pos.get("mode", "aggressive")
    holdings = pos.get("holdings", {})
    syms = sorted(set(holdings) | set(prices))
    spot = {}
    try:
        spot = fetch_spot_sina(syms)
    except Exception:  # noqa: BLE001 - best effort; fall back to cache
        spot = {}
    # valuation price = live raw (Sina); fall back to cache close (adjusted level)
    latest_px = {s: (spot[s]["price"] if s in spot else prices[s][-1]) for s in prices}
    st = value_holdings(holdings, float(pos.get("cash", 0.0)), latest_px)
    # intraday day-change from spot prev_close
    day_pnl = sum(
        float(holdings[s]["shares"]) * (spot[s]["price"] - spot[s]["prev_close"])
        for s in holdings if s in spot
    )
    tgt = target_book(prices, mode)
    cur_w = {r["symbol"]: r["weight"] for r in st["rows"]}
    due = rebalance_due(dates, pos.get("last_rebalance_date", dates[0]), cur_w, tgt)
    orders = rebalance_orders(holdings, tgt, latest_px, st["equity"]) if due["due"] else []
    return {
        "version": CTA_PORTFOLIO_VERSION, "mode": mode, "data_date": dates[-1],
        "last_rebalance_date": pos.get("last_rebalance_date", "?"),
        "price_source": "sina_live" if spot else "cache_close_adjusted",
        "equity": st["equity"], "cash": st["cash"], "total_market_value": st["total_market_value"],
        "total_pnl": st["total_pnl"], "total_pnl_pct": st["total_pnl_pct"], "day_pnl": day_pnl,
        "positions": [
            {**r, "target_weight": tgt.get(r["symbol"], 0.0), "name": ETF_NAMES.get(r["symbol"], "?")}
            for r in st["rows"]
        ],
        "due": due["due"], "due_reasons": due["reasons"],
        "trading_days_elapsed": due["trading_days_elapsed"], "max_weight_drift": due["max_weight_drift"],
        "orders": [{**o, "name": ETF_NAMES.get(o["symbol"], "?"), "qdii": o["symbol"] in QDII} for o in orders],
    }


def cmd_status(args: Any) -> None:
    if args.refresh:
        _refresh_prices()
    pos = load_positions()
    res = _build_status(pos)
    _log_equity(res)
    if getattr(args, "json", False):
        import json as _json
        curve = [{"date": r["date"], "equity": float(r["equity"])}
                 for r in _load_equity_rows() if r.get("equity") not in (None, "")]
        res["equity_curve"] = curve[-90:]
        res["paper"] = pos.get("paper", True)
        print(_json.dumps(res, ensure_ascii=False))
        return
    st = {"rows": res["positions"], "cash": res["cash"], "total_market_value": res["total_market_value"],
          "equity": res["equity"], "total_pnl": res["total_pnl"], "total_pnl_pct": res["total_pnl_pct"]}
    tgt = {p["symbol"]: p["target_weight"] for p in res["positions"]}
    due = {"due": res["due"], "reasons": res["due_reasons"],
           "trading_days_elapsed": res["trading_days_elapsed"], "max_weight_drift": res["max_weight_drift"]}
    latest_px = {p["symbol"]: p["last_px"] for p in res["positions"]}
    mode, dates_last = res["mode"], res["data_date"]
    src = "新浪实时" if res["price_source"] == "sina_live" else "缓存收盘(复权,非实时)"
    print(f"\nCTA-R 组合状态  mode={mode}  价格={src}  数据 {dates_last}  上次调仓 {res['last_rebalance_date']}")
    print(f"{'ETF':<11}{'名称':<12}{'持仓股':>9}{'成本':>8}{'现价':>8}{'市值¥':>11}{'盈亏¥':>11}{'盈亏%':>8}{'当前w':>7}{'目标w':>7}")
    for r in sorted(st["rows"], key=lambda x: -x["market_value"]):
        s = r["symbol"]
        pnl_pct = f"{r['pnl_pct']*100:+.1f}%" if r["pnl_pct"] is not None else "  -"
        print(f"{s:<11}{ETF_NAMES.get(s,'?'):<11}{r['shares']:>9.0f}{r['avg_cost']:>8.3f}{r['last_px']:>8.3f}"
              f"{_fmt_money(r['market_value']):>11}{r['pnl']:>+11,.0f}{pnl_pct:>8}"
              f"{r['weight']*100:>6.1f}%{tgt.get(s,0.0)*100:>6.1f}%")
    print(f"\n现金 ¥{_fmt_money(st['cash'])}   总市值 ¥{_fmt_money(st['total_market_value'])}   "
          f"总资产 ¥{_fmt_money(st['equity'])}")
    tp = st["total_pnl_pct"]
    print(f"总盈亏 ¥{st['total_pnl']:+,.0f}" + (f"  ({tp*100:+.1f}%)" if tp is not None else "")
          + f"   今日 ¥{res['day_pnl']:+,.0f}")

    print()
    if due["due"]:
        print(f"🔔 调仓提醒:需要调仓 —— {' + '.join(due['reasons'])}")
        orders = rebalance_orders(pos.get("holdings", {}), tgt, latest_px, st["equity"])
        if orders:
            print(f"{'操作':<6}{'ETF':<11}{'名称':<12}{'手数':>6}{'股数':>8}{'参考价':>8}{'金额¥':>11}")
            for o in orders:
                tag = " *QDII" if o["symbol"] in QDII else ""
                print(f"{o['side']:<6}{o['symbol']:<11}{ETF_NAMES.get(o['symbol'],'?')+tag:<12}"
                      f"{o['lots']:>6}{o['shares']:>8}{o['limit_ref']:>8.3f}{_fmt_money(o['amount']):>11}")
            print("→ 限价单挂上述目标;每笔成交后跑 `record-fill --symbol .. --side buy/sell --shares N --price P`,")
            print("  全部调完后跑 `mark-rebalanced` 盖时间戳。*QDII 注意溢价。")
        else:
            print("(目标与当前一致,无需下单)")
    else:
        print(f"✅ 暂不需要调仓(已过 {due['trading_days_elapsed']}/{REBALANCE_DAYS} 交易日,"
              f"最大权重漂移 {due['max_weight_drift']*100:.1f}%<{DRIFT_THRESHOLD*100:.0f}%)")


def cmd_init(args: Any) -> None:
    """Scaffold an empty positions file (all cash) for ``--capital``/``--mode``."""
    path = _positions_path()
    if path.exists() and not args.force:
        print(f"已存在 {path};加 --force 覆盖。")
        return
    dates, _ = _load_panel()
    save_positions({
        "version": CTA_PORTFOLIO_VERSION, "mode": args.mode, "capital": args.capital,
        "cash": args.capital, "last_rebalance_date": dates[-1] if dates else "",
        "paper": not args.live, "holdings": {},
        "_note": "paper=true 模拟盘(daily 自动调仓);go-live 切实盘后需手动 record-fill 填成本/数量。",
    })
    kind = "实盘(手动调仓)" if args.live else "模拟盘(自动调仓)"
    print(f"已创建 {path}(全现金 ¥{_fmt_money(args.capital)} / mode={args.mode} / {kind})。")


def cmd_go_live(args: Any) -> None:
    """Switch the book from paper to live: rebalances become MANUAL (record-fill)."""
    pos = load_positions()
    pos["paper"] = False
    save_positions(pos)
    print("⚠️ 已切换为【实盘】:此后 daily 不再自动成交;调仓提醒触发后,你下真实单、")
    print("   再用 `record-fill --symbol .. --side buy/sell --shares N --price P` 逐笔填实际成本/数量。")


def cmd_record_fill(args: Any) -> None:
    import datetime as _dt
    pos = load_positions()
    apply_fill(pos, args.symbol, args.side, args.shares, args.price)
    save_positions(pos)
    _append_trade({"ts": _dt.datetime.now().isoformat(timespec="seconds"), "kind": "live",
                   "symbol": args.symbol, "side": args.side, "shares": args.shares,
                   "price": args.price, "amount": args.shares * args.price})
    h = pos["holdings"].get(args.symbol, {"shares": 0.0, "avg_cost": 0.0})
    print(f"已记 {args.side} {args.symbol} {args.shares:.0f}@{args.price} → "
          f"现持 {h['shares']:.0f} 股 / 成本 {h['avg_cost']:.4f} / 现金 ¥{_fmt_money(pos['cash'])}")


def cmd_mark_rebalanced(args: Any) -> None:
    pos = load_positions()
    dates, _ = _load_panel()
    pos["last_rebalance_date"] = dates[-1] if dates else pos.get("last_rebalance_date", "")
    save_positions(pos)
    print(f"已盖调仓时间戳 last_rebalance_date={pos['last_rebalance_date']}。")


def cmd_daily(args: Any) -> None:
    """Scheduled daily job: refresh + log equity + auto-rebalance (paper) / alert (live)."""
    import datetime as _dt
    if not args.no_refresh:
        _refresh_prices()
    pos = load_positions()
    res = _build_status(pos)
    _log_equity(res)
    paper = pos.get("paper", True)
    stamp = _dt.datetime.now().isoformat(timespec="seconds")
    head = f"[daily {stamp}] equity ¥{_fmt_money(res['equity'])} pnl {res['total_pnl']:+,.0f} " \
           f"({'paper' if paper else 'LIVE'})"
    if not (res["due"] and res["orders"]):
        print(head + " · 无需调仓")
        return
    reasons = " + ".join(res["due_reasons"])
    if paper:
        paper_execute(pos, res["orders"])
        for o in res["orders"]:
            _append_trade({"ts": stamp, "kind": "paper", "symbol": o["symbol"], "side": o["side"].lower(),
                           "shares": o["shares"], "price": o["limit_ref"], "amount": o["amount"]})
        dates, _ = _load_panel()
        pos["last_rebalance_date"] = dates[-1] if dates else pos.get("last_rebalance_date", "")
        save_positions(pos)
        print(head + f" · 📝 模拟自动调仓 {len(res['orders'])} 笔({reasons})")
    else:
        print(head + f" · 🔔 实盘需手动调仓({reasons}):")
        for o in res["orders"]:
            print(f"    {o['side']} {o.get('name','')} {o['lots']}手 @{o['limit_ref']:.3f} ¥{_fmt_money(o['amount'])}")
        print("    下真实单后:record-fill --symbol .. --side buy/sell --shares N --price P")


def cmd_review(args: Any) -> None:
    """复盘:净值曲线统计 + 成交流水。"""
    rows = _load_equity_rows()
    stats = equity_curve_stats(rows)
    print(f"\n=== 净值复盘({_equity_path()})===")
    if stats:
        tr = stats["total_return_pct"]
        print(f"区间 {stats['first_date']} → {stats['last_date']}  ({stats['n_days']} 个记录日)")
        print(f"起始 ¥{_fmt_money(stats['start_equity'])} → 当前 ¥{_fmt_money(stats['current_equity'])}  "
              f"({tr*100:+.2f}%)" if tr is not None else "")
        print(f"峰值 ¥{_fmt_money(stats['peak_equity'])}  谷值 ¥{_fmt_money(stats['trough_equity'])}  "
              f"最大回撤 {stats['max_drawdown']*100:.2f}%")
        if args.curve:
            print("\n日期        净值¥          当日盈亏     来源")
            for r in rows[-args.curve:]:
                dp = r.get("day_pnl", "")
                print(f"{r['date']:<11} {float(r['equity']):>12,.0f}   {dp:>10}   {r.get('price_source','')}")
    else:
        print("(暂无净值记录;跑 status/面板刷新后会逐日累积)")
    trades = []
    if _trades_path().exists():
        with _trades_path().open(encoding="utf-8") as fh:
            trades = [json.loads(line) for line in fh if line.strip()]
    print(f"\n=== 成交流水({len(trades)} 笔,{_trades_path()})===")
    for t in trades[-args.trades:]:
        flag = "模拟" if t.get("kind") == "paper" else "实盘"
        print(f"{t['ts']:<20} {flag} {t['side'].upper():<4} {t['symbol']:<11} "
              f"{t['shares']:>8.0f}@{t['price']:<8.3f} ¥{_fmt_money(t['amount'])}")


def cmd_paper_rebalance(args: Any) -> None:
    """SIMULATION: execute the current target at live prices + stamp rebalanced."""
    pos = load_positions()
    res = _build_status(pos)
    orders = res["orders"]
    if not res["due"]:
        print("当前不需要调仓(未到 cadence 且漂移<阈值),未模拟成交。")
        return
    if not orders:
        print("目标与当前一致,无需成交。")
        return
    import datetime as _dt
    paper_execute(pos, orders)
    dates, _ = _load_panel()
    pos["last_rebalance_date"] = dates[-1] if dates else pos.get("last_rebalance_date", "")
    save_positions(pos)
    now = _dt.datetime.now().isoformat(timespec="seconds")
    for o in orders:
        _append_trade({"ts": now, "kind": "paper", "symbol": o["symbol"], "side": o["side"].lower(),
                       "shares": o["shares"], "price": o["limit_ref"], "amount": o["amount"]})
    print(f"📝 模拟盘已按实时价成交 {len(orders)} 笔(无滑点/佣金的乐观基准):")
    for o in orders:
        print(f"   {o['side']} {o.get('name','')} {o['lots']}手 @{o['limit_ref']:.3f}  ¥{_fmt_money(o['amount'])}")
    print("→ 面板从现在起跟踪盈亏;真实滑点/QDII溢价留待后续小额实盘验证。")


def main(argv: list[str] | None = None) -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="qount.cta_portfolio", description="CTA-R 半自动组合跟踪 + 调仓提醒(不下单)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status", help="估值/盈亏 + 目标权重 + 调仓提醒")
    s.add_argument("--refresh", action="store_true", help="先在线补尾日线缓存(akshare,域内)")
    s.add_argument("--json", action="store_true", help="机器可读输出(供 Mac 面板解析)")
    s.set_defaults(func=cmd_status)
    i = sub.add_parser("init", help="初始化本地持仓文件(全现金)")
    i.add_argument("--capital", type=float, default=1_000_000.0)
    i.add_argument("--mode", choices=list(MODE_PRESETS), default="aggressive")
    i.add_argument("--live", action="store_true", help="实盘(手动调仓);默认模拟盘(自动调仓)")
    i.add_argument("--force", action="store_true")
    i.set_defaults(func=cmd_init)
    gl = sub.add_parser("go-live", help="模拟盘→实盘:调仓改为手动 record-fill")
    gl.set_defaults(func=cmd_go_live)
    dl = sub.add_parser("daily", help="定时任务:刷新+记净值+模拟自动调仓/实盘提醒")
    dl.add_argument("--no-refresh", action="store_true", help="不在线补尾日线缓存")
    dl.set_defaults(func=cmd_daily)
    rf = sub.add_parser("record-fill", help="记一笔成交(手动同步本地持仓)")
    rf.add_argument("--symbol", required=True)
    rf.add_argument("--side", required=True, choices=["buy", "sell"])
    rf.add_argument("--shares", type=float, required=True)
    rf.add_argument("--price", type=float, required=True)
    rf.set_defaults(func=cmd_record_fill)
    mr = sub.add_parser("mark-rebalanced", help="调仓完成后盖时间戳")
    mr.set_defaults(func=cmd_mark_rebalanced)
    pr = sub.add_parser("paper-rebalance", help="模拟盘:按实时价一键成交当前目标(无滑点基准)")
    pr.set_defaults(func=cmd_paper_rebalance)
    rv = sub.add_parser("review", help="复盘:净值曲线统计 + 成交流水")
    rv.add_argument("--curve", type=int, default=10, help="末尾 N 日净值明细;默认 10")
    rv.add_argument("--trades", type=int, default=20, help="末尾 N 笔成交;默认 20")
    rv.set_defaults(func=cmd_review)
    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
