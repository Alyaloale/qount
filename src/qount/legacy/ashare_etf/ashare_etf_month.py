"""Research-only one-month A-share ETF regime and portfolio study.

The module deliberately keeps market data, regime classification, portfolio evidence,
and execution guidance separate.  It never sends orders and never lets an LLM choose
weights.  Tushare is called through its documented HTTP API so the optional research
path does not add pandas/tushare to qount's production dependencies.
"""

from __future__ import annotations

import json
import math
import shutil
import statistics
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from datetime import date
from datetime import timedelta
from pathlib import Path
from typing import Any

from qount.artifacts import write_research_json_artifact
from qount.settings import Settings


TUSHARE_API_URL = "https://api.tushare.pro"
EASTMONEY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
DEFAULT_COST_PER_SIDE_BPS = 6.0
DEFAULT_HORIZON_DAYS = 20
MIN_LOOKBACK_DAYS = 120


ETF_META: dict[str, dict[str, str]] = {
    "159819.SZ": {"name": "ai_core", "role": "ai_core"},
    "512480.SH": {"name": "semiconductor", "role": "ai_hardware"},
    "515880.SH": {"name": "communications", "role": "ai_hardware"},
    "512980.SH": {"name": "media_ai_application", "role": "ai_application"},
    "516080.SH": {"name": "innovative_drug", "role": "rotation"},
    "159928.SZ": {"name": "consumer", "role": "rotation"},
    "510880.SH": {"name": "dividend", "role": "defense"},
    "510300.SH": {"name": "csi300", "role": "benchmark"},
}

AI_HARDWARE = ("512480.SH", "515880.SH")
AI_CORE = "159819.SZ"
AI_APPLICATION = "512980.SH"
BENCHMARK = "510300.SH"


# These are the four portfolios stated or directly implied by the user's two proposals.
# Keeping them fixed before the historical comparison avoids optimizing weights on the
# same data used to report their one-month distributions.
PORTFOLIOS: dict[str, dict[str, float]] = {
    "ai_heavy_legacy": {
        "159819.SZ": 0.25,
        "512480.SH": 0.20,
        "510880.SH": 0.30,
        "510300.SH": 0.15,
    },
    "technology_defensive": {
        "159819.SZ": 0.15,
        "512480.SH": 0.10,
        "510880.SH": 0.30,
        "510300.SH": 0.20,
    },
    "rotation_barbell": {
        "516080.SH": 0.15,
        "159928.SZ": 0.15,
        "512980.SH": 0.05,
        "159819.SZ": 0.10,
        "512480.SH": 0.05,
        "510880.SH": 0.25,
    },
    "ai_logic_exit": {
        "516080.SH": 0.20,
        "159928.SZ": 0.15,
        "510880.SH": 0.30,
        "510300.SH": 0.10,
    },
}

REGIME_PORTFOLIO = {
    "hardware_pullback_application_rotation": "rotation_barbell",
    "ai_logic_breakdown": "ai_logic_exit",
    "ai_trend_repair": "technology_defensive",
    "mixed_unconfirmed": "technology_defensive",
}

# Explicit price conditions supplied by the user remain hard floors.  The research
# engine may require a stricter moving-average/high breakout, but never silently loosen
# these levels when evidence is already blocked.
USER_RECLAIM_FLOORS: dict[str, tuple[float, float]] = {
    "159819.SZ": (2.05, 2.09),
    "512480.SH": (1.27, 1.32),
}
USER_BREAKOUT_FLOORS: dict[str, float] = {
    "159928.SZ": 0.670,
    "512980.SH": 0.840,
}
USER_PULLBACK_ZONES: dict[str, tuple[float, float]] = {
    "159928.SZ": (0.648, 0.655),
    "512980.SH": (0.800, 0.810),
}
USER_STOP_FLOORS: dict[str, float] = {
    "159819.SZ": 1.90,
    "512480.SH": 1.10,
    "159928.SZ": 0.630,
    "512980.SH": 0.780,
    "510880.SH": 3.00,
}


@dataclass(frozen=True)
class DailyBar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    amount: float = 0.0


def _ymd(raw: str) -> str:
    value = str(raw).strip().replace("-", "")
    if len(value) != 8 or not value.isdigit():
        raise ValueError(f"invalid trade date {raw!r}")
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def _compact_date(raw: str) -> str:
    return str(raw).strip()[:10].replace("-", "")


def _http_post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "qount-research/0.2"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed URL
        return json.loads(response.read().decode("utf-8"))


def _http_get_json(url: str) -> dict[str, Any]:
    # Eastmoney is more stable with curl's TLS fingerprint on macOS.  Use one bounded,
    # non-shell request first so urllib retries do not themselves trigger throttling.
    curl = shutil.which("curl")
    last_error: Exception | None = None
    if curl:
        completed = subprocess.run(  # noqa: S603 - fixed executable and constructed URL
            [curl, "-fsSL", "--max-time", "60", url],
            check=False,
            capture_output=True,
            text=True,
            timeout=65,
        )
        if completed.returncode == 0 and completed.stdout:
            return json.loads(completed.stdout)
        last_error = RuntimeError(
            f"curl exit={completed.returncode}: {completed.stderr.strip()[:200]}"
        )

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "Connection": "close",
            "Referer": "https://quote.eastmoney.com/",
            "User-Agent": "Mozilla/5.0 qount-research",
        },
    )
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
            last_error = error
            if attempt < 1:
                time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"public ETF data request failed after bounded retries: {last_error}")


def _tushare_rows(payload: dict[str, Any], api_name: str) -> list[dict[str, Any]]:
    if payload.get("code") != 0:
        message = payload.get("msg") or "unknown Tushare error"
        raise RuntimeError(f"Tushare {api_name} failed: {message}")
    data = payload.get("data") or {}
    fields = data.get("fields") or []
    items = data.get("items") or []
    if not fields:
        return []
    return [dict(zip(fields, item, strict=False)) for item in items]


def fetch_tushare_bars(
    symbol: str,
    *,
    token: str,
    start_date: str,
    end_date: str,
    poster: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
) -> list[DailyBar]:
    """Fetch qfq-equivalent ETF OHLCV from Tushare ``fund_daily`` + ``fund_adj``.

    The token is used only in request payloads.  It is never returned, logged, or stored.
    ``fund_adj`` is required because raw ETF prices mismeasure distributions, especially
    for dividend ETFs.
    """

    if not token.strip():
        raise ValueError("missing Tushare token")
    post = poster or _http_post_json
    params = {
        "ts_code": symbol,
        "start_date": _compact_date(start_date),
        "end_date": _compact_date(end_date),
    }
    daily_payload = post(
        TUSHARE_API_URL,
        {
            "api_name": "fund_daily",
            "token": token,
            "params": params,
            "fields": "ts_code,trade_date,open,high,low,close,vol,amount",
        },
    )
    adj_payload = post(
        TUSHARE_API_URL,
        {
            "api_name": "fund_adj",
            "token": token,
            "params": params,
            "fields": "ts_code,trade_date,adj_factor",
        },
    )
    daily_rows = _tushare_rows(daily_payload, "fund_daily")
    adj_rows = _tushare_rows(adj_payload, "fund_adj")
    factors = {
        _ymd(str(row["trade_date"])): float(row["adj_factor"])
        for row in adj_rows
        if row.get("trade_date") and row.get("adj_factor") is not None
    }
    if not daily_rows:
        raise RuntimeError(f"Tushare returned no fund_daily rows for {symbol}")
    if not factors:
        raise RuntimeError(
            f"Tushare returned no fund_adj rows for {symbol}; adjusted history is required"
        )
    latest_factor = factors[max(factors)]
    if latest_factor <= 0:
        raise RuntimeError(f"invalid latest fund_adj factor for {symbol}")

    bars: list[DailyBar] = []
    for row in daily_rows:
        date = _ymd(str(row.get("trade_date", "")))
        factor = factors.get(date)
        if factor is None or factor <= 0:
            continue
        scale = factor / latest_factor
        try:
            bar = DailyBar(
                date=date,
                open=float(row["open"]) * scale,
                high=float(row["high"]) * scale,
                low=float(row["low"]) * scale,
                close=float(row["close"]) * scale,
                volume=float(row.get("vol") or 0.0),
                amount=float(row.get("amount") or 0.0),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if min(bar.open, bar.high, bar.low, bar.close) > 0:
            bars.append(bar)
    bars.sort(key=lambda item: item.date)
    if len(bars) < 2:
        raise RuntimeError(f"Tushare returned insufficient adjusted bars for {symbol}")
    return bars


def parse_eastmoney_bars(payload: dict[str, Any], symbol: str) -> list[DailyBar]:
    data = payload.get("data") or {}
    rows = data.get("klines") or []
    bars: list[DailyBar] = []
    for raw in rows:
        fields = str(raw).split(",")
        if len(fields) < 7:
            continue
        try:
            bar = DailyBar(
                date=fields[0][:10],
                open=float(fields[1]),
                close=float(fields[2]),
                high=float(fields[3]),
                low=float(fields[4]),
                volume=float(fields[5]),
                amount=float(fields[6]),
            )
        except ValueError:
            continue
        if min(bar.open, bar.high, bar.low, bar.close) > 0:
            bars.append(bar)
    bars.sort(key=lambda item: item.date)
    if len(bars) < 2:
        raise RuntimeError(f"Eastmoney returned insufficient qfq bars for {symbol}")
    return bars


def fetch_eastmoney_bars(
    symbol: str,
    *,
    start_date: str,
    end_date: str,
    getter: Callable[[str], dict[str, Any]] | None = None,
) -> list[DailyBar]:
    """Fetch public Eastmoney qfq bars for token-free reproducibility."""

    code, _, suffix = symbol.partition(".")
    market = "1" if suffix.upper() == "SH" else "0"
    query = urllib.parse.urlencode(
        {
            "secid": f"{market}.{code}",
            "klt": "101",
            "fqt": "1",
            "lmt": "5000",
            "beg": _compact_date(start_date),
            "end": _compact_date(end_date),
            "iscca": "1",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        }
    )
    payload = (getter or _http_get_json)(f"{EASTMONEY_KLINE_URL}?{query}")
    return parse_eastmoney_bars(payload, symbol)


def parse_tencent_bars(payload: dict[str, Any], symbol: str) -> list[DailyBar]:
    code, _, suffix = symbol.partition(".")
    market_code = ("sh" if suffix.upper() == "SH" else "sz") + code
    node = (payload.get("data") or {}).get(market_code) or {}
    rows = node.get("qfqday") or node.get("day") or []
    bars: list[DailyBar] = []
    for fields in rows:
        if not isinstance(fields, list) or len(fields) < 6:
            continue
        try:
            volume = float(fields[5])
            close = float(fields[2])
            bar = DailyBar(
                date=str(fields[0])[:10],
                open=float(fields[1]),
                close=close,
                high=float(fields[3]),
                low=float(fields[4]),
                volume=volume,
                # Tencent's qfqday response has no turnover amount.  Volume is retained as
                # the within-symbol breakout activity proxy; it is never compared cross-sectionally.
                amount=volume,
            )
        except (TypeError, ValueError):
            continue
        if min(bar.open, bar.high, bar.low, bar.close) > 0:
            bars.append(bar)
    bars.sort(key=lambda item: item.date)
    return bars


def fetch_tencent_bars(
    symbol: str,
    *,
    start_date: str,
    end_date: str,
    getter: Callable[[str], dict[str, Any]] | None = None,
) -> list[DailyBar]:
    """Fetch Tencent qfq history in bounded chunks (the endpoint caps each response)."""

    code, _, suffix = symbol.partition(".")
    market_code = ("sh" if suffix.upper() == "SH" else "sz") + code
    cursor = date.fromisoformat(start_date[:10])
    final = date.fromisoformat(end_date[:10])
    by_date: dict[str, DailyBar] = {}
    get = getter or _http_get_json
    while cursor <= final:
        chunk_end = min(cursor + timedelta(days=700), final)
        query = urllib.parse.urlencode(
            {
                "param": (
                    f"{market_code},day,{cursor.isoformat()},{chunk_end.isoformat()},2000,qfq"
                )
            }
        )
        payload = get(f"{TENCENT_KLINE_URL}?{query}")
        for bar in parse_tencent_bars(payload, symbol):
            by_date[bar.date] = bar
        cursor = chunk_end + timedelta(days=1)
        if getter is None:
            time.sleep(0.15)
    bars = [by_date[value] for value in sorted(by_date)]
    if len(bars) < 2:
        raise RuntimeError(f"Tencent returned insufficient combined qfq bars for {symbol}")
    return bars


def _cache_path(cache_dir: str | Path, source: str, symbol: str) -> Path:
    return Path(cache_dir) / source / f"{symbol}.json"


def write_bars_cache(
    cache_dir: str | Path, source: str, symbol: str, bars: list[DailyBar]
) -> Path:
    path = _cache_path(cache_dir, source, symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": source,
        "symbol": symbol,
        "price_basis": "qfq_adjusted",
        "bars": [asdict(bar) for bar in bars],
    }
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return path


def read_bars_cache(cache_dir: str | Path, source: str, symbol: str) -> list[DailyBar]:
    path = _cache_path(cache_dir, source, symbol)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [DailyBar(**row) for row in payload.get("bars", [])]


def load_universe_bars(
    *,
    source: str,
    start_date: str,
    end_date: str,
    cache_dir: str | Path,
    refresh: bool = False,
    tushare_token: str | None = None,
    symbols: tuple[str, ...] | list[str] | None = None,
    tushare_poster: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    eastmoney_getter: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, list[DailyBar]]:
    if source not in {"tushare", "eastmoney", "tencent"}:
        raise ValueError(f"unsupported source {source!r}")
    selected = list(symbols or ETF_META)
    out: dict[str, list[DailyBar]] = {}
    for symbol in selected:
        bars = [] if refresh else read_bars_cache(cache_dir, source, symbol)
        cache_covers_end = bool(bars and bars[-1].date >= end_date[:10])
        if refresh or not cache_covers_end:
            if source == "tushare":
                bars = fetch_tushare_bars(
                    symbol,
                    token=tushare_token or "",
                    start_date=start_date,
                    end_date=end_date,
                    poster=tushare_poster,
                )
            elif source == "eastmoney":
                bars = fetch_eastmoney_bars(
                    symbol,
                    start_date=start_date,
                    end_date=end_date,
                    getter=eastmoney_getter,
                )
            else:
                bars = fetch_tencent_bars(
                    symbol,
                    start_date=start_date,
                    end_date=end_date,
                    getter=eastmoney_getter,
                )
            write_bars_cache(cache_dir, source, symbol, bars)
            if source in {"eastmoney", "tencent"} and eastmoney_getter is None:
                time.sleep(0.25)
        filtered = [bar for bar in bars if start_date[:10] <= bar.date <= end_date[:10]]
        if len(filtered) < MIN_LOOKBACK_DAYS + DEFAULT_HORIZON_DAYS + 2:
            raise RuntimeError(
                f"{source} history for {symbol} has only {len(filtered)} usable bars"
            )
        out[symbol] = filtered
    return out


def align_bars(
    bars_by_symbol: dict[str, list[DailyBar]],
) -> tuple[list[str], dict[str, list[DailyBar]]]:
    if set(ETF_META) - set(bars_by_symbol):
        missing = sorted(set(ETF_META) - set(bars_by_symbol))
        raise ValueError(f"missing required ETF histories: {missing}")
    maps = {symbol: {bar.date: bar for bar in bars} for symbol, bars in bars_by_symbol.items()}
    common: set[str] | None = None
    for mapping in maps.values():
        dates = set(mapping)
        common = dates if common is None else common & dates
    dates = sorted(common or set())
    if len(dates) < MIN_LOOKBACK_DAYS + DEFAULT_HORIZON_DAYS + 2:
        raise ValueError(f"only {len(dates)} common dates across ETF universe")
    return dates, {symbol: [mapping[date] for date in dates] for symbol, mapping in maps.items()}


def _mean(values: list[float] | tuple[float, ...]) -> float:
    return sum(values) / len(values) if values else 0.0


def _return(closes: list[float], index: int, lookback: int) -> float:
    return closes[index] / closes[index - lookback] - 1.0


def _moving_average(closes: list[float], index: int, lookback: int) -> float:
    return _mean(closes[index - lookback + 1 : index + 1])


def _annualized_vol(closes: list[float], index: int, lookback: int = 20) -> float:
    returns = [
        closes[pos] / closes[pos - 1] - 1.0
        for pos in range(index - lookback + 1, index + 1)
    ]
    return statistics.stdev(returns) * math.sqrt(252.0) if len(returns) > 1 else 0.0


def _atr(bars: list[DailyBar], index: int, lookback: int = 20) -> float:
    values: list[float] = []
    for pos in range(index - lookback + 1, index + 1):
        prev_close = bars[pos - 1].close
        current = bars[pos]
        values.append(
            max(
                current.high - current.low,
                abs(current.high - prev_close),
                abs(current.low - prev_close),
            )
        )
    return _mean(values)


def _median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def compute_snapshot(
    dates: list[str], panel: dict[str, list[DailyBar]], index: int
) -> dict[str, dict[str, float | str]]:
    if index < MIN_LOOKBACK_DAYS:
        raise ValueError(f"snapshot needs at least {MIN_LOOKBACK_DAYS} prior bars")
    result: dict[str, dict[str, float | str]] = {}
    for symbol, bars in panel.items():
        closes = [bar.close for bar in bars]
        current = bars[index]
        ma5 = _moving_average(closes, index, 5)
        ma10 = _moving_average(closes, index, 10)
        ma20 = _moving_average(closes, index, 20)
        ma60 = _moving_average(closes, index, 60)
        ma120 = _moving_average(closes, index, 120)
        high20 = max(closes[index - 19 : index + 1])
        high60 = max(closes[index - 59 : index + 1])
        low20 = min(closes[index - 19 : index + 1])
        prior_high20 = max(closes[index - 20 : index])
        prior_amounts = [bar.amount for bar in bars[index - 20 : index] if bar.amount > 0]
        amount_ratio = current.amount / _median(prior_amounts) if prior_amounts else 0.0
        result[symbol] = {
            "name": ETF_META[symbol]["name"],
            "role": ETF_META[symbol]["role"],
            "date": dates[index],
            "close": current.close,
            "ret_5": _return(closes, index, 5),
            "ret_20": _return(closes, index, 20),
            "ret_60": _return(closes, index, 60),
            "gap_ma_5": current.close / ma5 - 1.0,
            "gap_ma_10": current.close / ma10 - 1.0,
            "gap_ma_20": current.close / ma20 - 1.0,
            "gap_ma_60": current.close / ma60 - 1.0,
            "gap_ma_120": current.close / ma120 - 1.0,
            "ma_5": ma5,
            "ma_10": ma10,
            "ma_20": ma20,
            "ma_60": ma60,
            "ma_120": ma120,
            "drawdown_20": current.close / high20 - 1.0,
            "drawdown_60": current.close / high60 - 1.0,
            "low_20": low20,
            "prior_high_20": prior_high20,
            "atr_20": _atr(bars, index, 20),
            "annualized_vol_20": _annualized_vol(closes, index, 20),
            "amount_ratio_20_median": amount_ratio,
        }
    benchmark = result[BENCHMARK]
    for values in result.values():
        values["relative_ret_5_vs_csi300"] = float(values["ret_5"]) - float(
            benchmark["ret_5"]
        )
        values["relative_ret_20_vs_csi300"] = float(values["ret_20"]) - float(
            benchmark["ret_20"]
        )
        values["relative_ret_60_vs_csi300"] = float(values["ret_60"]) - float(
            benchmark["ret_60"]
        )
    return result


def classify_ai_regime(
    snapshot: dict[str, dict[str, float | str]],
) -> dict[str, Any]:
    hardware_gap20 = _mean([float(snapshot[s]["gap_ma_20"]) for s in AI_HARDWARE])
    hardware_rel5 = _mean(
        [float(snapshot[s]["relative_ret_5_vs_csi300"]) for s in AI_HARDWARE]
    )
    hardware_rel20 = _mean(
        [float(snapshot[s]["relative_ret_20_vs_csi300"]) for s in AI_HARDWARE]
    )
    core = snapshot[AI_CORE]
    app = snapshot[AI_APPLICATION]
    app_resilience_spread = float(app["gap_ma_20"]) - hardware_gap20

    hardware_stress = hardware_gap20 <= -0.06 and hardware_rel5 <= -0.03
    application_resilient = (
        float(app["gap_ma_20"]) >= -0.02
        and float(app["relative_ret_5_vs_csi300"]) >= 0.01
        and app_resilience_spread >= 0.05
    )
    secular_ai_intact = (
        float(core["gap_ma_120"]) >= -0.02
        or float(core["relative_ret_60_vs_csi300"]) > 0.0
    )
    broad_ai_weak = (
        float(core["gap_ma_60"]) <= -0.04
        and float(app["gap_ma_60"]) <= -0.04
        and hardware_gap20 <= -0.04
    )
    broad_relative_breakdown = (
        float(core["relative_ret_20_vs_csi300"]) <= -0.02
        and float(app["relative_ret_20_vs_csi300"]) <= -0.02
        and hardware_rel20 <= -0.02
    )
    ai_repair = (
        hardware_gap20 > 0.0
        and float(core["gap_ma_20"]) > 0.0
        and float(app["gap_ma_20"]) > 0.0
        and float(core["relative_ret_20_vs_csi300"]) > 0.0
    )

    if hardware_stress and application_resilient and secular_ai_intact:
        label = "hardware_pullback_application_rotation"
    elif broad_ai_weak and broad_relative_breakdown and not secular_ai_intact:
        label = "ai_logic_breakdown"
    elif ai_repair:
        label = "ai_trend_repair"
    else:
        label = "mixed_unconfirmed"
    return {
        "label": label,
        "tests": {
            "hardware_stress": hardware_stress,
            "application_resilient": application_resilient,
            "secular_ai_intact": secular_ai_intact,
            "broad_ai_weak": broad_ai_weak,
            "broad_relative_breakdown": broad_relative_breakdown,
            "ai_repair": ai_repair,
        },
        "measures": {
            "hardware_gap_ma20": hardware_gap20,
            "hardware_relative_ret5": hardware_rel5,
            "hardware_relative_ret20": hardware_rel20,
            "application_resilience_spread": app_resilience_spread,
            "core_gap_ma120": float(core["gap_ma_120"]),
            "core_relative_ret60": float(core["relative_ret_60_vs_csi300"]),
            "application_gap_ma60": float(app["gap_ma_60"]),
        },
    }


def _episode_result(
    panel: dict[str, list[DailyBar]],
    weights: dict[str, float],
    signal_index: int,
    horizon_days: int,
    cost_per_side_bps: float,
) -> dict[str, float]:
    invested = sum(weights.values())
    if invested > 1.0 + 1e-12 or min(weights.values(), default=0.0) < 0.0:
        raise ValueError("portfolio weights must be long-only and sum to <= 1")
    entry_index = signal_index + 1
    exit_index = signal_index + horizon_days
    cost = cost_per_side_bps / 10_000.0
    cash = 1.0 - invested
    equity_path = [1.0]
    entry_fee = invested * cost
    for pos in range(entry_index, exit_index + 1):
        equity = cash - entry_fee
        for symbol, weight in weights.items():
            equity += weight * panel[symbol][pos].close / panel[symbol][entry_index].open
        equity_path.append(equity)
    gross_final = cash + sum(
        weight * panel[symbol][exit_index].close / panel[symbol][entry_index].open
        for symbol, weight in weights.items()
    )
    net_final = gross_final - (2.0 * invested * cost)
    equity_path[-1] = net_final
    peak = equity_path[0]
    max_drawdown = 0.0
    for equity in equity_path:
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity / peak - 1.0)
    return {
        "gross_return": gross_final - 1.0,
        "net_return": net_final - 1.0,
        "max_drawdown": max_drawdown,
    }


def _quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _episode_stats(rows: list[dict[str, float]]) -> dict[str, float | int | None]:
    returns = [row["net_return"] for row in rows]
    drawdowns = [row["max_drawdown"] for row in rows]
    if not rows:
        return {
            "sample_count": 0,
            "mean_return": None,
            "median_return": None,
            "hit_rate": None,
            "p10_return": None,
            "worst_return": None,
            "median_max_drawdown": None,
            "worst_max_drawdown": None,
        }
    return {
        "sample_count": len(rows),
        "mean_return": _mean(returns),
        "median_return": _median(returns),
        "hit_rate": sum(value > 0.0 for value in returns) / len(returns),
        "p10_return": _quantile(returns, 0.10),
        "worst_return": min(returns),
        "median_max_drawdown": _median(drawdowns),
        "worst_max_drawdown": min(drawdowns),
    }


def evaluate_portfolios(
    dates: list[str],
    panel: dict[str, list[DailyBar]],
    *,
    current_regime: str,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    cost_per_side_bps: float = DEFAULT_COST_PER_SIDE_BPS,
) -> dict[str, Any]:
    last_signal_index = len(dates) - horizon_days - 1
    if last_signal_index <= MIN_LOOKBACK_DAYS:
        raise ValueError("insufficient forward history for one-month evaluation")

    regimes: dict[int, str] = {}
    for index in range(MIN_LOOKBACK_DAYS, last_signal_index + 1):
        regimes[index] = classify_ai_regime(compute_snapshot(dates, panel, index))["label"]

    unconditional = list(range(MIN_LOOKBACK_DAYS, last_signal_index + 1, horizon_days))
    matching_overlapping = [index for index, label in regimes.items() if label == current_regime]
    matching_nonoverlap: list[int] = []
    last_used = -10_000
    for index in matching_overlapping:
        if index - last_used >= horizon_days:
            matching_nonoverlap.append(index)
            last_used = index

    output: dict[str, Any] = {
        "method": {
            "signal_time": "daily_close",
            "entry_time": "next_session_open",
            "exit_time": f"signal_plus_{horizon_days}_session_close",
            "cost_per_side_bps": cost_per_side_bps,
            "cash_return_assumption": 0.0,
            "weights": "fixed_at_entry_no_daily_rebalance",
            "matching_nonoverlap": "greedy starts at least one horizon apart",
            "overlapping_samples": "diagnostic_only",
        },
        "regime_counts_daily": {
            label: list(regimes.values()).count(label) for label in sorted(set(regimes.values()))
        },
        "portfolios": {},
    }
    for name, weights in PORTFOLIOS.items():
        def rows(indices: list[int]) -> list[dict[str, float]]:
            return [
                _episode_result(panel, weights, index, horizon_days, cost_per_side_bps)
                for index in indices
            ]

        output["portfolios"][name] = {
            "weights": dict(weights),
            "cash_weight": 1.0 - sum(weights.values()),
            "all_nonoverlap": _episode_stats(rows(unconditional)),
            "matching_regime_nonoverlap": _episode_stats(rows(matching_nonoverlap)),
            "matching_regime_overlap_diagnostic": _episode_stats(rows(matching_overlapping)),
        }
    return output


def _round_level(value: float) -> float:
    return round(value, 3 if value < 100 else 2)


def build_execution_plan(
    snapshot: dict[str, dict[str, float | str]],
    portfolio_name: str,
    *,
    exposure_cap: float | None = None,
) -> dict[str, Any]:
    weights = PORTFOLIOS[portfolio_name]
    original_invested = sum(weights.values())
    capped_invested = min(original_invested, exposure_cap or original_invested)
    weight_scale = capped_invested / original_invested if original_invested else 0.0
    instructions: dict[str, Any] = {}
    for symbol, target in weights.items():
        effective_target = target * weight_scale
        row = snapshot[symbol]
        role = str(row["role"])
        close = float(row["close"])
        ma5 = float(row["ma_5"])
        ma10 = float(row["ma_10"])
        ma20 = float(row["ma_20"])
        prior_high = float(row["prior_high_20"])
        low20 = float(row["low_20"])
        amount_ratio = float(row["amount_ratio_20_median"])

        if role in {"ai_core", "ai_hardware"}:
            user_first, user_full = USER_RECLAIM_FLOORS.get(symbol, (0.0, 0.0))
            first_trigger = max(ma10, user_first, close)
            full_trigger = max(ma20, user_full, first_trigger)
            if close >= ma20 and ma5 >= ma10:
                status = "eligible_first_tranche_next_open"
            else:
                status = "wait_for_ma10_then_ma20_reclaim"
            rule = "50% target after close>=MA10; full target after close>=MA20 and MA5>=MA10"
            stop_pct = 0.06
        elif role in {"rotation", "ai_application"}:
            dynamic_support = (min(ma10, ma20) * 0.99, max(ma10, ma20) * 1.01)
            if symbol == "516080.SH":
                support_low, support_high = prior_high * 0.95, prior_high * 0.97
            else:
                support_low, support_high = USER_PULLBACK_ZONES.get(
                    symbol, dynamic_support
                )
            first_trigger = support_high
            full_trigger = max(
                prior_high * 1.005, USER_BREAKOUT_FLOORS.get(symbol, 0.0)
            )
            breakout_confirmed = amount_ratio >= 1.2 and close >= full_trigger
            support_confirmed = support_low <= close <= support_high and ma5 >= ma10
            if breakout_confirmed:
                first_trigger = close
                status = "eligible_volume_breakout_tranche_next_open"
            elif support_confirmed:
                status = "eligible_support_tranche_next_open"
            else:
                status = "wait_pullback_or_volume_breakout"
            rule = (
                "50% target on non-extended MA10/MA20 support; full target only after "
                "20d breakout with amount>=1.2x prior-20d median"
            )
            stop_pct = 0.06
        else:
            first_trigger = max(ma20, close) if close < ma20 else close
            full_trigger = prior_high
            status = (
                "eligible_first_tranche_next_open"
                if close >= ma20 and ma5 >= ma10
                else "wait_for_ma20_reclaim"
            )
            rule = "50% target after close>=MA20; full target after 20d high reclaim"
            stop_pct = 0.045

        stop_reference = min(
            first_trigger * 0.995,
            max(low20, first_trigger * (1.0 - stop_pct)),
        )
        stop_reference = max(stop_reference, USER_STOP_FLOORS.get(symbol, 0.0))
        instructions[symbol] = {
            "name": row["name"],
            "uncapped_target_weight": target,
            "target_weight": effective_target,
            "first_tranche_weight": effective_target / 2.0,
            "status": status,
            "rule": rule,
            "current_close": _round_level(close),
            "first_trigger_close": _round_level(first_trigger),
            "full_trigger_close": _round_level(full_trigger),
            "pullback_zone": [
                _round_level(
                    support_low
                    if role in {"rotation", "ai_application"}
                    else min(ma10, ma20) * 0.99
                ),
                _round_level(
                    support_high
                    if role in {"rotation", "ai_application"}
                    else max(ma10, ma20) * 1.01
                ),
            ],
            "initial_stop_close": _round_level(stop_reference),
            "amount_ratio_20_median": amount_ratio,
            "volume_breakout_confirmed": amount_ratio >= 1.2 and close >= prior_high * 1.005,
        }
    return {
        "portfolio": portfolio_name,
        "uncapped_invested_weight": original_invested,
        "effective_invested_cap": capped_invested,
        "target_cash_weight": 1.0 - capped_invested,
        "decision_frequency": "once_after_each_A_share_close",
        "instructions": instructions,
        "portfolio_rules": {
            "profit_4pct": "reduce total invested exposure by one third",
            "profit_7pct": "reduce another one third",
            "loss_4pct": "freeze all additions",
            "loss_6pct": "exit AI and offensive sleeves; reassess the whole plan",
            "time_stop": "exit or fully reassess after 20 trading sessions",
            "intraday_prices": "do not treat intraday touches as confirmed signals",
        },
    }


def _evidence_gate(stats: dict[str, float | int | None]) -> dict[str, Any]:
    tests = {
        "sample_count_gte_8": int(stats["sample_count"] or 0) >= 8,
        "median_return_positive": (stats["median_return"] or 0.0) > 0.0,
        "hit_rate_above_half": (stats["hit_rate"] or 0.0) > 0.5,
        "p10_above_minus_8pct": (stats["p10_return"] or -1.0) > -0.08,
    }
    return {"verdict": "pass" if all(tests.values()) else "block", "tests": tests}


def build_month_report(
    bars_by_symbol: dict[str, list[DailyBar]],
    *,
    data_source: str,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    cost_per_side_bps: float = DEFAULT_COST_PER_SIDE_BPS,
) -> dict[str, Any]:
    dates, panel = align_bars(bars_by_symbol)
    index = len(dates) - 1
    snapshot = compute_snapshot(dates, panel, index)
    regime = classify_ai_regime(snapshot)
    evaluation = evaluate_portfolios(
        dates,
        panel,
        current_regime=regime["label"],
        horizon_days=horizon_days,
        cost_per_side_bps=cost_per_side_bps,
    )
    portfolio_name = REGIME_PORTFOLIO[regime["label"]]
    selected_stats = evaluation["portfolios"][portfolio_name]["matching_regime_nonoverlap"]
    evidence_gate = _evidence_gate(selected_stats)
    initial_exposure_cap = (
        sum(PORTFOLIOS[portfolio_name].values())
        if evidence_gate["verdict"] == "pass"
        else min(0.50, sum(PORTFOLIOS[portfolio_name].values()) / 2.0)
    )
    return {
        "schema_version": "ashare_etf_month_v1",
        "research_status": "discovery_only_no_profit_guarantee",
        "as_of": dates[-1],
        "data": {
            "source": data_source,
            "price_basis": "qfq_adjusted",
            "common_start": dates[0],
            "common_end": dates[-1],
            "common_session_count": len(dates),
            "symbols": list(ETF_META),
        },
        "decision_contract": {
            "horizon_trading_days": horizon_days,
            "cost_per_side_bps": cost_per_side_bps,
            "regime_portfolio_mapping": dict(REGIME_PORTFOLIO),
            "weights_pre_registered_from_user_proposals": True,
            "llm_may_change_weights": False,
            "order_or_live_side_effects": False,
        },
        "ai_regime": regime,
        "snapshot": snapshot,
        "portfolio_evaluation": evaluation,
        "recommendation": {
            "portfolio": portfolio_name,
            "reason": regime["label"],
            "matching_regime_stats": selected_stats,
            "evidence_gate": evidence_gate,
            "initial_exposure_cap": initial_exposure_cap,
            "interpretation": (
                "conditional candidate; execute only the close-confirmed tranches"
                if evidence_gate["verdict"] == "pass"
                else "historical condition evidence is insufficient; keep at least 50% cash"
            ),
        },
        "execution": build_execution_plan(
            snapshot, portfolio_name, exposure_cap=initial_exposure_cap
        ),
        "limitations": [
            "This is a discovery study, not a promise of profit or promotion evidence.",
            "The application sleeve uses one media ETF proxy and cannot prove the entire AI industry cycle.",
            "Historical regime episodes overlap economically even when starts are spaced 20 sessions apart.",
            "Daily bars cannot model intraday limit orders, premium/discount, or actual broker fills.",
            "Current news and the supplied July observations are already viewed, so the current month is not holdout data.",
        ],
    }


def write_month_report_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="ashare-etf-month",
        path_key="artifact_path",
        default_filename="ashare_etf_month.json",
        explicit_path=explicit_path,
    )
