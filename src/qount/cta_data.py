"""DataLayer adapters for the CTA-R paper-sim (``docs/rebuild-plan.md`` §3 seam).

Turns a chosen data source into the aligned ``dict[name -> list[float]]`` price panel
that ``cta_sim.run_paper_sim`` consumes. The signal / portfolio / risk / execution code
never changes; only this layer is swapped to go from synthetic to real data.

This module is **pure-stdlib at import time**. The broker/vendor adapters (IBKR, Norgate)
lazy-import their heavy deps only when actually called, and raise a clear setup error if
the dependency or the running account/subscription is missing — so importing this module
never requires ib_insync / norgatedata / pandas / ccxt, and the offline synthetic/CSV
paths keep working on any host.

Sources:
  synthetic  -> cta_sim.generate_synthetic_panel   (offline, default)
  csv        -> cta_sim.load_prices_csv            (any wide price table)
  tiingo     -> free cross-asset ETF EOD via urllib (needs QOUNT_TIINGO_API_KEY)
  ibkr       -> IBKR continuous futures via ib_insync (needs TWS / IB Gateway running)
  norgate    -> Norgate continuous futures via norgatedata (needs NDU + subscription)
  binance    -> Binance OHLCV via ccxt (a crypto basket; the gate decides if it's an edge)
  openquant  -> A-share index/stock daily bars from the OpenQuant project's local sqlite
                (read-only; pure-stdlib sqlite3; absorbs its data, not its code)
  akshare    -> tradeable A-share ETF daily closes; local etf_data.zip seed + date,close
                cache + optional online akshare top-up (cache-first, no rate-limit)
"""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from typing import Callable

from .cta_sim import DEFAULT_UNIVERSE as SYNTHETIC_UNIVERSE
from .cta_sim import generate_synthetic_panel
from .cta_sim import load_prices_csv


DATA_SOURCES = (
    "synthetic", "csv", "tiingo", "ibkr", "norgate", "tqsdk", "binance", "openquant", "akshare",
)

TIINGO_EOD_URL_TEMPLATE = "https://api.tiingo.com/tiingo/daily/{ticker}/prices"
TIINGO_DEFAULT_START_DATE = "2010-01-01"

# A liquid cross-asset ETF panel (Tiingo free tier). This is the "real data today"
# path: it works from any host with QOUNT_TIINGO_API_KEY, no broker/subscription.
TIINGO_DEFAULT_UNIVERSE: tuple[str, ...] = (
    "SPY", "EFA", "EEM", "TLT", "IEF", "LQD", "HYG",
    "GLD", "SLV", "DBC", "USO", "UUP", "VNQ",
)

# IBKR continuous-future definitions: name -> (symbol, exchange). Uses ib_insync
# ContFuture so the back-month roll is handled by IBKR. Override via --ibkr-symbols.
IBKR_DEFAULT_FUTURES: dict[str, tuple[str, str]] = {
    "ES": ("ES", "CME"), "NQ": ("NQ", "CME"), "RTY": ("RTY", "CME"),
    "ZF": ("ZF", "CBOT"), "ZN": ("ZN", "CBOT"), "ZB": ("ZB", "CBOT"),
    "GC": ("GC", "COMEX"), "SI": ("SI", "COMEX"), "HG": ("HG", "COMEX"),
    "CL": ("CL", "NYMEX"),
    "6E": ("6E", "CME"), "6A": ("6A", "CME"), "6B": ("6B", "CME"),
}

# Norgate continuous-contract symbols (back-adjusted, calendar-weighted): "&SYM_CCB".
NORGATE_DEFAULT_FUTURES: dict[str, str] = {
    "ES": "&ES_CCB", "NQ": "&NQ_CCB", "RTY": "&RTY_CCB",
    "ZF": "&ZF_CCB", "ZN": "&ZN_CCB", "ZB": "&ZB_CCB",
    "GC": "&GC_CCB", "SI": "&SI_CCB", "HG": "&HG_CCB",
    "CL": "&CL_CCB",
    "6E": "&DX_CCB",
}

# Domestic Chinese futures (compliant, RMB) via TqSdk main-continuous symbols
# ("KQ.m@EXCHANGE.product"). A deliberately cross-sector, mostly no-threshold panel so
# effective breadth survives -- within-sector contracts (e.g. the black/ferrous complex)
# co-move heavily, so breadth comes from spanning metals / ferrous / precious / ags /
# chems. Threshold products (铁矿 i / 原油 sc / PTA TA etc. need 验资) are left out of the
# default; override with --tickers once you have the relevant 适当性 permissions.
TQSDK_DEFAULT_FUTURES: tuple[str, ...] = (
    "KQ.m@SHFE.cu", "KQ.m@SHFE.al", "KQ.m@SHFE.zn", "KQ.m@SHFE.ni",  # 有色
    "KQ.m@SHFE.rb", "KQ.m@SHFE.hc",                                    # 黑色
    "KQ.m@SHFE.au", "KQ.m@SHFE.ag",                                    # 贵金属
    "KQ.m@DCE.m", "KQ.m@DCE.c", "KQ.m@DCE.y", "KQ.m@DCE.p",            # 农产品/油脂
    "KQ.m@CZCE.SR", "KQ.m@CZCE.CF", "KQ.m@CZCE.MA", "KQ.m@CZCE.SA",    # 软商品/能化
)

# Binance spot pairs (USDT-quoted). This is deliberately a *single-sector* basket: every
# crypto here is largely beta to BTC, so effective breadth is expected to be low -- that is
# exactly the rebuild-plan §0 ceiling (eff-breadth≈1.6) the gate should re-confirm or refute
# on this real basket, NOT a curated edge. Default is daily so the verdict is apples-to-apples
# with the validated Tiingo cross-asset trend run (breadth 2.62 / Sharpe 0.77).
BINANCE_DEFAULT_UNIVERSE: tuple[str, ...] = (
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT", "ADA/USDT",
    "DOGE/USDT", "AVAX/USDT", "LINK/USDT", "LTC/USDT", "BCH/USDT", "TRX/USDT",
)

# OpenQuant local A-share sqlite (read-only). Path is the OpenQuant project's
# data/db/market_data.sqlite; on the WSL production host the Windows D: drive mounts at
# /mnt/d. Override via --openquant-db or QOUNT_OPENQUANT_DB.
OPENQUANT_DEFAULT_DB = "/mnt/d/C++/code/OpenQuant/data/db/market_data.sqlite"

# A cross-sector A-share INDEX basket the user can trade via the matching ETFs in a plain
# A-share account (RMB, compliant, no futures/short needed). Breadth here is structurally
# capped: 宽基 + 行业 are all A-share beta and co-move; the ONLY genuine non-equity
# diversifier in this dataset is 上证国债指数 (000012). There is no real gold/commodity
# price or cross-border index locally -- 000066 上证商品 is commodity-PRODUCER equities, not
# the commodity itself. So the gate is being asked an honest question, not handed an edge.
OPENQUANT_DEFAULT_UNIVERSE: tuple[str, ...] = (
    "000300", "000905", "000016", "399006",          # 宽基:沪深300/中证500/上证50/创业板
    "000012",                                          # 国债(唯一真分散器)
    "000819", "000037", "000036", "000134", "000006",  # 有色/医药/消费/银行/地产
    "399998", "399967", "399997", "399437", "399808",  # 煤炭/军工/白酒/证券/新能源
    "000066", "000015",                                # 上证商品(生产商股)/红利
)

# akshare / local ETF store. Seeded from the local etf_data.zip (Tushare-format daily +
# adj_factor), persisted as a compact date,close cache to avoid re-fetching (no rate-limit),
# with optional online incremental top-up via akshare. A *tradeable* cross-asset long-only
# basket the user can buy in a plain A-share account -- 4 real asset classes (equity / gold /
# bonds / foreign equity) so long-only breadth can escape the all-equity ceiling that trapped
# the index book at 1.71. All have deep history (3000+ bars) in the zip.
AKSHARE_DEFAULT_CACHE_DIR = "state/etf_cache"
AKSHARE_DEFAULT_UNIVERSE: tuple[str, ...] = (
    "510300.SH", "510500.SH", "159915.SZ", "510050.SH",  # 宽基:沪深300/中证500/创业板/上证50
    "518880.SH",                                          # 黄金(真分散器)
    "511010.SH",                                          # 国债 ETF(债)
    "513100.SH", "513500.SH",                             # 跨境:纳指/标普500(美元 + 不同周期)
)

# ETF -> asset class, so risk modes can reason about classes (e.g. the aggressive mode drops
# `bond` to ride pure risk assets). Unmapped symbols are treated as class None (never dropped).
ETF_ASSET_CLASS: dict[str, str] = {
    "510300.SH": "cn_equity", "510500.SH": "cn_equity", "159915.SZ": "cn_equity",
    "510050.SH": "cn_equity",
    "518880.SH": "gold",
    "511010.SH": "bond", "511260.SH": "bond",
    "513100.SH": "foreign_equity", "513500.SH": "foreign_equity", "513180.SH": "foreign_equity",
    "159985.SZ": "commodity", "159980.SZ": "commodity", "159981.SZ": "commodity",
}


def exclude_asset_classes(
    prices: dict[str, list[float]], classes: tuple[str, ...] | list[str]
) -> dict[str, list[float]]:
    """Drop symbols whose ``ETF_ASSET_CLASS`` is in ``classes`` (unmapped symbols kept)."""

    drop = set(classes)
    if not drop:
        return prices
    kept = {s: v for s, v in prices.items() if ETF_ASSET_CLASS.get(s) not in drop}
    if len(kept) < 2:
        raise ValueError(
            f"excluding classes {sorted(drop)} left {len(kept)} symbols; need >= 2 "
            "(pass a wider --tickers or a less aggressive mode)"
        )
    return kept


# --------------------------------------------------------------------------------------
# Shared alignment
# --------------------------------------------------------------------------------------


def align_on_common_dates(by_symbol: dict[str, dict[str, float]]) -> dict[str, list[float]]:
    """Align per-symbol ``{date: close}`` maps onto their common trading dates.

    Intersection (not union+ffill) so no symbol ever carries a stale/forward-filled
    price into the cross-sectional return panel. Dates are sorted ascending.
    """

    names = list(by_symbol)
    if not names:
        raise ValueError("no symbols to align")
    common: set[str] | None = None
    for name in names:
        dates = set(by_symbol[name])
        common = dates if common is None else (common & dates)
    common = common or set()
    ordered = sorted(common)
    if len(ordered) < 2:
        raise ValueError(
            f"only {len(ordered)} common dates across {len(names)} symbols; "
            "check the symbols share a calendar / history window"
        )
    return {name: [by_symbol[name][d] for d in ordered] for name in names}


# --------------------------------------------------------------------------------------
# Tiingo (free cross-asset ETF EOD)
# --------------------------------------------------------------------------------------


def _tiingo_get_json(url: str, *, attempts: int = 3) -> Any:
    request = urllib.request.Request(
        url, headers={"User-Agent": "qount-cta-r/1.0", "Content-Type": "application/json"}
    )
    last_error: Exception | None = None
    for _attempt in range(max(1, attempts)):
        try:
            with urllib.request.build_opener().open(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last_error = error
    raise last_error if last_error is not None else RuntimeError("tiingo fetch failed")


def fetch_tiingo_panel(
    tickers: list[str] | tuple[str, ...] | None = None,
    *,
    api_key: str | None,
    start_date: str = TIINGO_DEFAULT_START_DATE,
    field: str = "adjClose",
    fetcher: Callable[[str], Any] | None = None,
) -> dict[str, list[float]]:
    """Fetch a cross-asset ETF EOD panel from Tiingo and align it on common dates.

    ``fetcher`` lets tests inject payloads without the network or a key.
    """

    if not api_key:
        raise ValueError(
            "missing Tiingo API key: set QOUNT_TIINGO_API_KEY in .env (free at tiingo.com) "
            "or pass --tiingo-api-key"
        )
    tickers = list(tickers) if tickers else list(TIINGO_DEFAULT_UNIVERSE)
    by_symbol: dict[str, dict[str, float]] = {}
    for ticker in tickers:
        base = TIINGO_EOD_URL_TEMPLATE.format(ticker=ticker.lower())
        url = f"{base}?startDate={start_date}&format=json&token={api_key}"
        rows = fetcher(url) if fetcher is not None else _tiingo_get_json(url)
        closes: dict[str, float] = {}
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                date = row.get("date")
                value = row.get(field)
                if isinstance(date, str) and isinstance(value, (int, float)) and value > 0:
                    closes[date[:10]] = float(value)
        if not closes:
            raise ValueError(f"Tiingo returned no usable rows for {ticker!r}")
        by_symbol[ticker] = closes
    return align_on_common_dates(by_symbol)


# --------------------------------------------------------------------------------------
# IBKR paper/live (continuous futures via ib_insync)
# --------------------------------------------------------------------------------------


def fetch_ibkr_panel(
    symbols: dict[str, tuple[str, str]] | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 7497,
    client_id: int = 17,
    duration: str = "10 Y",
    bar_size: str = "1 day",
    what_to_show: str = "TRADES",
    use_rth: bool = True,
) -> dict[str, list[float]]:
    """Pull daily continuous-future bars from a running IBKR TWS / IB Gateway.

    Requires ``ib_insync`` installed and TWS/Gateway logged in with the API enabled.
    Default port 7497 = paper TWS (paper IB Gateway = 4002). Needs the relevant market
    -data subscriptions for the futures requested.
    """

    try:
        from ib_insync import ContFuture  # type: ignore
        from ib_insync import IB  # type: ignore
    except ImportError as error:  # pragma: no cover - env without ib_insync
        raise RuntimeError(
            "IBKR data source needs ib_insync: pip install ib_insync, and run TWS or "
            "IB Gateway logged in with the API enabled (paper TWS port 7497)."
        ) from error

    symbols = symbols or IBKR_DEFAULT_FUTURES
    ib = IB()
    try:
        ib.connect(host, port, clientId=client_id, timeout=15)
    except Exception as error:  # pragma: no cover - needs a live gateway
        raise RuntimeError(
            f"could not connect to IBKR at {host}:{port} (clientId={client_id}). "
            "Is TWS / IB Gateway running and logged in with the API port enabled?"
        ) from error
    try:
        by_symbol: dict[str, dict[str, float]] = {}
        for name, (symbol, exchange) in symbols.items():
            contract = ContFuture(symbol, exchange)
            ib.qualifyContracts(contract)
            bars = ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow=what_to_show,
                useRTH=use_rth,
                formatDate=1,
            )
            closes: dict[str, float] = {}
            for bar in bars:
                close = float(getattr(bar, "close", 0.0) or 0.0)
                if close > 0:
                    closes[str(getattr(bar, "date", ""))[:10]] = close
            if not closes:
                raise RuntimeError(f"IBKR returned no bars for {name} ({symbol}@{exchange})")
            by_symbol[name] = closes
    finally:  # pragma: no cover - needs a live gateway
        ib.disconnect()
    return align_on_common_dates(by_symbol)


# --------------------------------------------------------------------------------------
# Norgate (continuous futures via norgatedata)
# --------------------------------------------------------------------------------------


def fetch_norgate_panel(
    symbols: dict[str, str] | None = None,
    *,
    start_date: str = TIINGO_DEFAULT_START_DATE,
) -> dict[str, list[float]]:
    """Pull daily continuous-future closes from Norgate (needs NDU + a subscription).

    Requires the ``norgatedata`` package (and ``pandas``) with Norgate Data Updater
    running locally. Uses back-adjusted continuous contracts (``&SYM_CCB``).
    """

    try:
        import norgatedata  # type: ignore
    except ImportError as error:  # pragma: no cover - env without norgatedata
        raise RuntimeError(
            "Norgate data source needs norgatedata: pip install norgatedata, plus a Norgate "
            "subscription with Norgate Data Updater (NDU) running locally."
        ) from error

    symbols = symbols or NORGATE_DEFAULT_FUTURES
    by_symbol: dict[str, dict[str, float]] = {}
    for name, norgate_symbol in symbols.items():
        frame = norgatedata.price_timeseries(
            norgate_symbol,
            start_date=start_date,
            timeseriesformat="pandas-dataframe",
        )
        closes: dict[str, float] = {}
        for index, value in frame["Close"].items():  # pragma: no cover - needs Norgate
            close = float(value)
            if close > 0:
                closes[str(index)[:10]] = close
        if not closes:
            raise RuntimeError(f"Norgate returned no rows for {name} ({norgate_symbol})")
        by_symbol[name] = closes
    return align_on_common_dates(by_symbol)


# --------------------------------------------------------------------------------------
# TqSdk (domestic Chinese futures -- compliant RMB path, free data + sim)
# --------------------------------------------------------------------------------------


def fetch_tqsdk_panel(
    symbols: tuple[str, ...] | list[str] | None = None,
    *,
    user: str | None,
    password: str | None,
    bars: int = 2000,
) -> dict[str, list[float]]:
    """Pull daily main-continuous closes for domestic Chinese futures via TqSdk.

    Needs the ``tqsdk`` package and a free 天勤 account (register at shinnytech.com); pass
    credentials via --tqsdk-user/--tqsdk-pass or env QOUNT_TQSDK_USER / QOUNT_TQSDK_PASS.
    Uses main-continuous symbols ("KQ.m@EXCHANGE.product") so the back-month roll is
    handled by TqSdk. Compliant for mainland residents -- no FX/overseas funding.
    """

    if not user or not password:
        raise ValueError(
            "missing TqSdk credentials: register a free 天勤 account at shinnytech.com and set "
            "QOUNT_TQSDK_USER / QOUNT_TQSDK_PASS (or pass --tqsdk-user / --tqsdk-pass)"
        )
    try:
        from tqsdk import TqApi  # type: ignore
        from tqsdk import TqAuth  # type: ignore
    except ImportError as error:  # pragma: no cover - env without tqsdk
        raise RuntimeError(
            "domestic futures source needs tqsdk: pip install tqsdk (free 天勤 account required)."
        ) from error

    symbols = list(symbols) if symbols else list(TQSDK_DEFAULT_FUTURES)
    api = TqApi(auth=TqAuth(user, password))  # pragma: no cover - needs account + network
    try:  # pragma: no cover - needs account + network
        import datetime as _dt

        by_symbol: dict[str, dict[str, float]] = {}
        for symbol in symbols:
            frame = api.get_kline_serial(symbol, duration_seconds=24 * 60 * 60, data_length=bars)
            closes: dict[str, float] = {}
            for ns, close in zip(frame["datetime"], frame["close"]):
                close = float(close)
                if close > 0 and not math.isnan(close):
                    date = _dt.datetime.utcfromtimestamp(int(ns) / 1e9).strftime("%Y-%m-%d")
                    closes[date] = close
            if not closes:
                raise RuntimeError(f"TqSdk returned no usable bars for {symbol}")
            by_symbol[symbol] = closes
    finally:  # pragma: no cover - needs account + network
        api.close()
    return align_on_common_dates(by_symbol)


# --------------------------------------------------------------------------------------
# Futures term-structure carry (roll yield) -- pure builder + tqsdk adapter
# --------------------------------------------------------------------------------------


def _days_between(date_iso: str, expire_iso: str) -> int | None:
    """Calendar days from ``date_iso`` to ``expire_iso`` (both YYYY-MM-DD); None if unparseable."""

    import datetime as _dt

    try:
        d0 = _dt.date.fromisoformat(date_iso[:10])
        d1 = _dt.date.fromisoformat(expire_iso[:10])
    except (ValueError, TypeError):
        return None
    return (d1 - d0).days


def annualized_roll_yield(
    near_close: float, far_close: float, near_dte: int, far_dte: int
) -> float | None:
    """Annualized roll yield between the near and the deferred contract.

    ``(near/far - 1) * 365 / (far_dte - near_dte)``. Positive = backwardation (near richer
    than far -> long earns roll as the far converges up); negative = contango (short).
    Returns None if the tenor gap or a price is non-positive.
    """

    gap = far_dte - near_dte
    if gap <= 0 or far_close <= 0.0 or near_close <= 0.0:
        return None
    return (near_close / far_close - 1.0) * 365.0 / gap


def build_term_structure_carry(
    contracts: dict[str, dict[str, Any]],
    dates: list[str],
    *,
    min_dte_days: int = 10,
) -> dict[str, float]:
    """Daily annualized carry from the two nearest non-expiring contracts of one product.

    ``contracts``: ``{symbol: {"expire": "YYYY-MM-DD", "closes": {date: close}}}``. Per date,
    take the contracts that traded that date with at least ``min_dte_days`` to expiry (drops
    the about-to-deliver, illiquid front), sort by days-to-expiry, and roll-yield the nearest
    two. Returns ``{date: annualized_carry}`` (only dates with >= 2 usable contracts).
    """

    out: dict[str, float] = {}
    for date in dates:
        usable: list[tuple[int, float]] = []
        for contract in contracts.values():
            close = contract.get("closes", {}).get(date)
            if not isinstance(close, (int, float)) or close <= 0.0:
                continue
            dte = _days_between(date, contract.get("expire", ""))
            if dte is None or dte < min_dte_days:
                continue
            usable.append((dte, float(close)))
        if len(usable) < 2:
            continue
        usable.sort(key=lambda item: item[0])
        (near_dte, near_px), (far_dte, far_px) = usable[0], usable[1]
        carry = annualized_roll_yield(near_px, far_px, near_dte, far_dte)
        if carry is not None:
            out[date] = carry
    return out


def align_prices_and_carry(
    price_by_symbol: dict[str, dict[str, float]],
    carry_by_symbol: dict[str, dict[str, float]],
) -> tuple[dict[str, list[float]], dict[str, list[float | None]]]:
    """Align price + carry onto the symbols' common PRICE dates (carry None where missing).

    Prices drive the date axis (intersection across symbols, like ``align_on_common_dates``);
    the carry panel is laid on the same axis with ``None`` wherever a date has no carry, which
    the carry sleeve skips at decision time. Returns ``(prices, carry)`` ready for the sim.
    """

    names = list(price_by_symbol)
    if len(names) < 2:
        raise ValueError("need >= 2 symbols for a carry panel")
    common: set[str] | None = None
    for name in names:
        dates = set(price_by_symbol[name])
        common = dates if common is None else (common & dates)
    ordered = sorted(common or set())
    if len(ordered) < 2:
        raise ValueError(f"only {len(ordered)} common price dates across {len(names)} symbols")
    prices = {n: [price_by_symbol[n][d] for d in ordered] for n in names}
    carry = {
        n: [carry_by_symbol.get(n, {}).get(d) for d in ordered] for n in names
    }
    return prices, carry


def fetch_tqsdk_carry_panel(
    symbols: tuple[str, ...] | list[str] | None = None,
    *,
    user: str | None,
    password: str | None,
    bars: int = 2000,
    min_dte_days: int = 10,
    start_date: str | None = None,
    end_date: str | None = None,
    cache_dir: str = "state/tqsdk_carry_cache",
) -> tuple[dict[str, list[float]], dict[str, list[float | None]]]:
    """Build ``(prices, carry)`` panels for domestic futures via TqSdk term structure.

    For each ``KQ.m@EX.product`` symbol: the main-continuous daily closes are the price axis,
    and the carry series is the roll yield of the two nearest live/expired contracts at each
    date (``build_term_structure_carry``). Per-contract daily klines are cached under
    ``cache_dir`` so re-runs are cheap. Needs a free 天勤 account; **route direct, not via the
    Binance proxy** (unset HTTP(S)_PROXY first). Returns panels aligned on common price dates.
    """

    if not user or not password:
        raise ValueError(
            "missing TqSdk credentials: set QOUNT_TQSDK_USER / QOUNT_TQSDK_PASS (free 天勤 "
            "account at shinnytech.com)"
        )
    try:
        from tqsdk import TqApi  # type: ignore
        from tqsdk import TqAuth  # type: ignore
    except ImportError as error:  # pragma: no cover - env without tqsdk
        raise RuntimeError(
            "domestic futures carry source needs tqsdk: pip install tqsdk"
        ) from error

    import datetime as _dt
    import json as _json

    symbols = list(symbols) if symbols else list(TQSDK_DEFAULT_FUTURES)
    cutoff = (start_date or "")[:10]
    end_cut = (end_date or "")[:10]
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)

    def _to_date(ns_or_ts: float, *, ns: bool) -> str:  # pragma: no cover - needs network
        seconds = (ns_or_ts / 1e9) if ns else float(ns_or_ts)
        return _dt.datetime.fromtimestamp(seconds).strftime("%Y-%m-%d")

    api = TqApi(auth=TqAuth(user, password))  # pragma: no cover - needs account + network
    price_by_symbol: dict[str, dict[str, float]] = {}
    carry_by_symbol: dict[str, dict[str, float]] = {}
    try:  # pragma: no cover - needs account + network
        for symbol in symbols:
            _, _, ex_product = symbol.partition("@")
            exchange, _, product = ex_product.partition(".")
            # main-continuous price axis
            mk = api.get_kline_serial(symbol, 24 * 60 * 60, bars)
            closes: dict[str, float] = {}
            for ns, close in zip(mk["datetime"], mk["close"]):
                if close == close and float(close) > 0:  # not NaN
                    closes[_to_date(int(ns), ns=True)] = float(close)
            if cutoff or end_cut:
                closes = {
                    d: c for d, c in closes.items()
                    if (not cutoff or d >= cutoff) and (not end_cut or d <= end_cut)
                }
            price_by_symbol[symbol] = closes
            min_price_date = min(closes) if closes else "2000-01-01"
            # per-contract klines (cached) -> term-structure carry
            contracts: dict[str, dict[str, Any]] = {}
            live = api.query_quotes(ins_class="FUTURE", product_id=product, expired=False) or []
            expired = api.query_quotes(ins_class="FUTURE", product_id=product, expired=True) or []
            for csym in sorted(set(live) | set(expired)):
                cpath = cache / f"{csym}.json"
                if cpath.exists():
                    contracts[csym] = _json.loads(cpath.read_text(encoding="utf-8"))
                    continue
                quote = api.get_quote(csym)
                exp = quote.expire_datetime
                if not exp:
                    continue
                exp_date = _to_date(float(exp), ns=False)
                if exp_date < min_price_date:  # contract delivered before our window starts
                    continue
                ck = api.get_kline_serial(csym, 24 * 60 * 60, bars)
                ccloses: dict[str, float] = {}
                for ns, close in zip(ck["datetime"], ck["close"]):
                    if close == close and float(close) > 0:
                        ccloses[_to_date(int(ns), ns=True)] = float(close)
                rec = {"expire": exp_date, "closes": ccloses}
                cpath.write_text(_json.dumps(rec, ensure_ascii=False), encoding="utf-8")
                contracts[csym] = rec
            carry_by_symbol[symbol] = build_term_structure_carry(
                contracts, sorted(closes), min_dte_days=min_dte_days
            )
    finally:  # pragma: no cover - needs account + network
        api.close()
    return align_prices_and_carry(price_by_symbol, carry_by_symbol)


# --------------------------------------------------------------------------------------
# Binance (crypto OHLCV via ccxt)
# --------------------------------------------------------------------------------------


def fetch_binance_panel(
    symbols: tuple[str, ...] | list[str] | None = None,
    *,
    timeframe: str = "1d",
    limit: int = 1000,
    market_type: str = "spot",
    fetcher: Callable[[str], Any] | None = None,
) -> dict[str, list[float]]:
    """Fetch a Binance OHLCV close panel via ccxt and align it on common timestamps.

    Default ``timeframe='1d'`` keeps the verdict apples-to-apples with the validated
    cross-asset trend run; intraday timeframes (e.g. ``4h`` / ``1h``) are supported and
    keyed at minute resolution so same-day bars are not collapsed. ``market_type`` is
    ``'spot'`` or ``'future'`` (USDT-margined perpetuals -- use ``BTC/USDT:USDT`` style
    symbols there). ``fetcher`` lets tests inject OHLCV rows without ccxt or the network.
    """

    import datetime as _dt
    import os as _os

    symbols = list(symbols) if symbols else list(BINANCE_DEFAULT_UNIVERSE)
    if fetcher is None:
        try:
            import ccxt  # type: ignore
        except ImportError as error:  # pragma: no cover - env without ccxt
            raise RuntimeError(
                "Binance data source needs ccxt: pip install ccxt."
            ) from error
        # Binance's global API is geo-blocked on the production host; route through the
        # same proxy the live executor uses (read from env to keep this module decoupled
        # from settings.py and pure-stdlib at import time).
        # Restrict market loading to the one type we need: otherwise ccxt's load_markets
        # also hits the inverse (dapi) / options (eapi) endpoints, which fail here and are
        # irrelevant. Mirrors exchange_utils.build_exchange.
        is_future = market_type == "future"
        exchange_options: dict[str, Any] = {
            "defaultType": market_type,
            "fetchMarkets": {"types": ["linear"] if is_future else ["spot"]},
        }
        if is_future:
            exchange_options["defaultSubType"] = "linear"
        options: dict[str, Any] = {
            "enableRateLimit": True,
            "options": exchange_options,
        }
        https_proxy = _os.environ.get("QOUNT_HTTPS_PROXY") or _os.environ.get("HTTPS_PROXY")
        http_proxy = _os.environ.get("QOUNT_HTTP_PROXY") or _os.environ.get("HTTP_PROXY")
        if https_proxy:
            options["httpsProxy"] = https_proxy
        elif http_proxy:
            options["httpProxy"] = http_proxy
        exchange = ccxt.binance(options)

        def fetcher(symbol: str) -> Any:  # pragma: no cover - needs network
            return exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    intraday = not (timeframe.endswith("d") or timeframe.endswith("w") or timeframe.endswith("M"))
    fmt = "%Y-%m-%dT%H:%M" if intraday else "%Y-%m-%d"
    by_symbol: dict[str, dict[str, float]] = {}
    for symbol in symbols:
        rows = fetcher(symbol)
        closes: dict[str, float] = {}
        for row in rows or []:
            # ccxt OHLCV row: [timestamp_ms, open, high, low, close, volume]
            if not isinstance(row, (list, tuple)) or len(row) < 5:
                continue
            ts_ms, close = row[0], row[4]
            if isinstance(close, (int, float)) and close > 0 and not math.isnan(float(close)):
                stamp = _dt.datetime.utcfromtimestamp(int(ts_ms) / 1000).strftime(fmt)
                closes[stamp] = float(close)
        if not closes:
            raise RuntimeError(f"Binance returned no usable bars for {symbol!r}")
        by_symbol[symbol] = closes
    return align_on_common_dates(by_symbol)


# --------------------------------------------------------------------------------------
# OpenQuant (local A-share sqlite -- absorbed read-only as a DataLayer adapter)
# --------------------------------------------------------------------------------------


def _openquant_align(
    symbols: list[str], fetcher: Callable[[str], Any]
) -> dict[str, list[float]]:
    """Turn ``fetcher(symbol) -> [(date, close), ...]`` rows into an aligned panel."""

    by_symbol: dict[str, dict[str, float]] = {}
    for symbol in symbols:
        rows = fetcher(symbol)
        closes: dict[str, float] = {}
        for row in rows or []:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            date, close = row[0], row[1]
            if (
                isinstance(date, str)
                and isinstance(close, (int, float))
                and close > 0
                and not math.isnan(float(close))
            ):
                closes[date[:10]] = float(close)
        if not closes:
            raise RuntimeError(
                f"OpenQuant DB returned no usable bars for {symbol!r} (check symbol/table)"
            )
        by_symbol[symbol] = closes
    return align_on_common_dates(by_symbol)


def fetch_openquant_panel(
    symbols: tuple[str, ...] | list[str] | None = None,
    *,
    db_path: str | None = None,
    table: str = "index_bars",
    period: str = "daily",
    adjust: str = "qfq",
    fetcher: Callable[[str], Any] | None = None,
) -> dict[str, list[float]]:
    """Read a daily-close panel from the OpenQuant project's local ``market_data.sqlite``.

    Read-only (``mode=ro``) and pure-stdlib ``sqlite3`` -- we absorb the data, never the
    code, and never write to its DB. ``table='index_bars'`` pulls index daily closes;
    ``table='price_bars'`` pulls per-stock bars filtered by ``period``/``adjust`` (qfq =
    前复权). ``fetcher`` lets tests inject ``(date, close)`` rows without a real DB.
    """

    import os as _os

    symbols = list(symbols) if symbols else list(OPENQUANT_DEFAULT_UNIVERSE)
    if table not in ("index_bars", "price_bars"):
        raise ValueError(f"openquant table must be index_bars or price_bars, got {table!r}")
    if fetcher is not None:
        return _openquant_align(symbols, fetcher)

    import sqlite3

    db = db_path or _os.environ.get("QOUNT_OPENQUANT_DB") or OPENQUANT_DEFAULT_DB
    if not Path(db).exists():
        raise RuntimeError(
            f"OpenQuant market_data.sqlite not found at {db!r}; pass --openquant-db or set "
            "QOUNT_OPENQUANT_DB (the OpenQuant project's data/db/market_data.sqlite). On the "
            "WSL host the Windows D: drive mounts at /mnt/d."
        )
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        def db_fetcher(symbol: str) -> Any:
            cur = con.cursor()
            if table == "price_bars":
                return cur.execute(
                    "SELECT date, close FROM price_bars "
                    "WHERE symbol=? AND period=? AND adjust=? ORDER BY date",
                    (symbol, period, adjust),
                ).fetchall()
            return cur.execute(
                "SELECT date, close FROM index_bars WHERE symbol=? ORDER BY date",
                (symbol,),
            ).fetchall()

        return _openquant_align(symbols, db_fetcher)
    finally:
        con.close()


# --------------------------------------------------------------------------------------
# akshare / local ETF store (zip seed -> date,close cache -> optional online top-up)
# --------------------------------------------------------------------------------------


def _ymd(raw: str) -> str:
    """Normalise a Tushare ``YYYYMMDD`` (or already-ISO) date to ``YYYY-MM-DD``."""

    raw = raw.strip()
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return raw[:10]


def read_etf_adjusted_close_from_zip(zip_path: str, symbol: str) -> dict[str, float]:
    """Adjusted daily close for ``symbol`` from the local etf_data.zip (or ``{}`` if absent).

    Reads ``etf_data/daily/{symbol}.csv`` (raw OHLCV) and multiplies by the matching
    ``etf_data/adj/{symbol}.csv`` ``adj_factor`` (Tushare back-adjust; identical *returns* to
    qfq, which is all the trend/vol signal uses). Missing adj file -> raw close (factor 1).
    """

    import csv
    import io
    import zipfile

    closes: dict[str, float] = {}
    factors: dict[str, float] = {}
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        daily_name = f"etf_data/daily/{symbol}.csv"
        if daily_name not in names:
            return {}
        with zf.open(daily_name) as raw:
            for row in csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8")):
                date, close = row.get("trade_date"), row.get("close")
                if date and close:
                    try:
                        value = float(close)
                    except ValueError:
                        continue
                    if value > 0:
                        closes[_ymd(date)] = value
        adj_name = f"etf_data/adj/{symbol}.csv"
        if adj_name in names:
            with zf.open(adj_name) as raw:
                for row in csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8")):
                    date, factor = row.get("trade_date"), row.get("adj_factor")
                    if date and factor:
                        try:
                            factors[_ymd(date)] = float(factor)
                        except ValueError:
                            continue
    return {date: close * factors.get(date, 1.0) for date, close in closes.items()}


def load_etf_cache(cache_dir: str, symbol: str) -> dict[str, float]:
    """Load a persisted ``date,close`` cache for ``symbol`` (``{}`` if none)."""

    import csv

    path = Path(cache_dir) / f"{symbol}.csv"
    if not path.exists():
        return {}
    out: dict[str, float] = {}
    with path.open(encoding="utf-8") as fh:
        reader = csv.reader(fh)
        next(reader, None)  # header
        for row in reader:
            if len(row) >= 2:
                try:
                    out[row[0]] = float(row[1])
                except ValueError:
                    continue
    return out


def save_etf_cache(cache_dir: str, symbol: str, series: dict[str, float]) -> None:
    """Persist ``series`` as a compact ``date,close`` cache (sorted ascending)."""

    import csv

    directory = Path(cache_dir)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f"{symbol}.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["date", "close"])
        for date in sorted(series):
            writer.writerow([date, series[date]])


def fetch_etf_online_akshare(symbol: str, *, start_date: str | None = None) -> dict[str, float]:
    """Online incremental fetch of qfq daily close for one ETF via akshare (lazy import).

    Used only to top up the cache tail; the local zip is the bulk, so this stays small and
    avoids rate limits. Seam caveat: akshare qfq base may differ slightly from the zip's
    back-adjust for symbols with distributions, but the local data is already near-current.
    """

    try:
        import akshare as ak  # type: ignore
    except ImportError as error:  # pragma: no cover - env without akshare
        raise RuntimeError(
            "akshare online top-up needs akshare: pip install akshare (data is domestic, "
            "no proxy needed). Or run offline from the local zip cache (--akshare-online off)."
        ) from error

    import datetime as _dt

    code = symbol.split(".")[0]
    start = (start_date or "2010-01-01").replace("-", "")
    end = _dt.datetime.now().strftime("%Y%m%d")
    frame = ak.fund_etf_hist_em(  # pragma: no cover - needs network
        symbol=code, period="daily", start_date=start, end_date=end, adjust="qfq"
    )
    out: dict[str, float] = {}
    for _, row in frame.iterrows():  # pragma: no cover - needs network
        date, close = str(row.get("日期")), row.get("收盘")
        if isinstance(close, (int, float)) and close > 0:
            out[_ymd(date)] = float(close)
    return out


def fetch_akshare_panel(
    symbols: tuple[str, ...] | list[str] | None = None,
    *,
    cache_dir: str = AKSHARE_DEFAULT_CACHE_DIR,
    zip_path: str | None = None,
    online: bool = False,
    start_date: str | None = None,
    fetcher: Callable[[str], dict[str, float]] | None = None,
) -> dict[str, list[float]]:
    """Build an aligned ETF close panel: cache-first, seed-from-zip, optional online top-up.

    Per symbol: (1) load the persisted date,close cache; (2) if empty and a ``zip_path`` is
    given, seed it from the local etf_data.zip and persist; (3) if ``online`` (or an injected
    ``fetcher``), append only dates newer than the cache tail and persist. This is the
    "local store + online completion, no rate-limit" design. ``fetcher`` lets tests inject an
    online tail (``symbol -> {date: close}``) without akshare/network.
    """

    symbols = list(symbols) if symbols else list(AKSHARE_DEFAULT_UNIVERSE)
    by_symbol: dict[str, dict[str, float]] = {}
    for symbol in symbols:
        series = load_etf_cache(cache_dir, symbol)
        if not series and zip_path:
            series = read_etf_adjusted_close_from_zip(zip_path, symbol)
            if series:
                save_etf_cache(cache_dir, symbol, series)
        if online or fetcher is not None:
            last = max(series) if series else None
            tail = (
                fetcher(symbol)
                if fetcher is not None
                else fetch_etf_online_akshare(symbol, start_date=start_date)
            )
            new = {d: c for d, c in (tail or {}).items() if last is None or d > last}
            if new:
                series.update(new)
                save_etf_cache(cache_dir, symbol, series)
        if not series:
            raise RuntimeError(
                f"akshare: no data for {symbol!r} (cache empty, no zip, online off). Pass "
                "--akshare-zip <etf_data.zip> to seed the local store, or --akshare-online."
            )
        if start_date:
            cutoff = start_date[:10]
            series = {d: c for d, c in series.items() if d >= cutoff}
        by_symbol[symbol] = series
    return align_on_common_dates(by_symbol)


# --------------------------------------------------------------------------------------
# Dispatcher
# --------------------------------------------------------------------------------------


def load_panel(data_source: str, **kwargs: Any) -> tuple[dict[str, list[float]], str]:
    """Return ``(prices, description)`` for the chosen data source.

    Recognized kwargs per source:
      synthetic: days, seed
      csv:       prices_csv
      tiingo:    tickers, api_key, start_date
      ibkr:      symbols, host, port, client_id, duration, bar_size
      norgate:   symbols, start_date
      binance:   tickers, binance_timeframe, binance_limit, binance_market
      openquant: tickers, openquant_db, openquant_table, openquant_period, openquant_adjust
      akshare:   tickers, akshare_cache_dir, akshare_zip, akshare_online, start_date
    """

    if data_source == "synthetic":
        days = int(kwargs.get("days", 1500))
        seed = int(kwargs.get("seed", 7))
        prices = generate_synthetic_panel(SYNTHETIC_UNIVERSE, n_days=days, seed=seed)
        return prices, f"synthetic(seed={seed},days={days})"
    if data_source == "csv":
        path = kwargs.get("prices_csv")
        if not path:
            raise ValueError("csv data source needs prices_csv")
        return load_prices_csv(path), f"csv:{path}"
    if data_source == "tiingo":
        prices = fetch_tiingo_panel(
            kwargs.get("tickers"),
            api_key=kwargs.get("api_key"),
            start_date=kwargs.get("start_date", TIINGO_DEFAULT_START_DATE),
        )
        return prices, f"tiingo({len(prices)} ETFs)"
    if data_source == "ibkr":
        prices = fetch_ibkr_panel(
            kwargs.get("symbols"),
            host=kwargs.get("host", "127.0.0.1"),
            port=int(kwargs.get("port", 7497)),
            client_id=int(kwargs.get("client_id", 17)),
            duration=kwargs.get("duration", "10 Y"),
            bar_size=kwargs.get("bar_size", "1 day"),
        )
        return prices, f"ibkr({len(prices)} futures)"
    if data_source == "norgate":
        prices = fetch_norgate_panel(
            kwargs.get("symbols"),
            start_date=kwargs.get("start_date", TIINGO_DEFAULT_START_DATE),
        )
        return prices, f"norgate({len(prices)} futures)"
    if data_source == "tqsdk":
        prices = fetch_tqsdk_panel(
            kwargs.get("tickers"),
            user=kwargs.get("tqsdk_user"),
            password=kwargs.get("tqsdk_password"),
            bars=int(kwargs.get("tqsdk_bars", 2000)),
        )
        return prices, f"tqsdk({len(prices)} domestic futures)"
    if data_source == "binance":
        timeframe = kwargs.get("binance_timeframe", "1d")
        prices = fetch_binance_panel(
            kwargs.get("tickers"),
            timeframe=timeframe,
            limit=int(kwargs.get("binance_limit", 1000)),
            market_type=kwargs.get("binance_market", "spot"),
            fetcher=kwargs.get("fetcher"),
        )
        return prices, f"binance({len(prices)} pairs,{timeframe})"
    if data_source == "openquant":
        table = kwargs.get("openquant_table", "index_bars")
        prices = fetch_openquant_panel(
            kwargs.get("tickers"),
            db_path=kwargs.get("openquant_db"),
            table=table,
            period=kwargs.get("openquant_period", "daily"),
            adjust=kwargs.get("openquant_adjust", "qfq"),
            fetcher=kwargs.get("fetcher"),
        )
        return prices, f"openquant({len(prices)} {table})"
    if data_source == "akshare":
        online = bool(kwargs.get("akshare_online", False))
        prices = fetch_akshare_panel(
            kwargs.get("tickers"),
            cache_dir=kwargs.get("akshare_cache_dir") or AKSHARE_DEFAULT_CACHE_DIR,
            zip_path=kwargs.get("akshare_zip"),
            online=online,
            start_date=kwargs.get("start_date"),
            fetcher=kwargs.get("fetcher"),
        )
        return prices, f"akshare({len(prices)} ETFs{',online' if online else ''})"
    raise ValueError(f"unknown data_source {data_source!r}; choose from {DATA_SOURCES}")
