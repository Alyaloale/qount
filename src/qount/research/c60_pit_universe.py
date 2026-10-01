"""Survivorship check for Trial 150: replay C60 v2 on a point-in-time Binance spot universe.

Preregistration: docs/c60-pit-universe-survivorship-2026-09.md
research_only=true / orders_authorized=false. Public archive klines only (including delisted pairs);
not a new trial. Gate / vol-cap math is the frozen C60 code; only the universe is time-varying.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import math
import re
import zipfile
from dataclasses import dataclass
from statistics import fmean
from typing import Callable, Iterable, Mapping, Sequence

from qount.dual_engine.contracts import C60_SYMBOLS, DualEnginePaperContract
from qount.dual_engine.strategy import _portfolio_volatility
from qount.research.c60_cost_study import WARMUP_BARS, _rank_candidates
from qount.research_data.metrics import _moments

ARCHIVE = "https://data.binance.vision/data/spot/monthly/klines/{symbol}/1d/{symbol}-1d-{month}.zip"
S3_LIST = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
FIRST_MONTH = "2020-01"
LAST_MONTH = "2026-08"
FIRST_DECISION = "2020-12-05"
EVAL_END = "2026-08-31"
TOP_N = 8
VOLUME_DAYS = 30
COST_BPS = 25.0
EXCLUDED_YEAR = "2021"
ANCHORS = ("BTCUSDT", "PAXGUSDT")
STABLE_OR_FIAT = frozenset({
    "USDC", "BUSD", "TUSD", "USDP", "PAX", "FDUSD", "DAI", "UST", "USTC", "SUSD", "USDS", "AEUR", "EURI", "EUR",
    "GBP", "AUD", "BRL", "TRY", "RUB", "BIDR", "IDRT", "NGN", "UAH", "ZAR", "BKRW", "BVND", "XUSD", "USD1", "RLUSD",
})
LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")
GUARDS = {"research_only": True, "orders_authorized": False, "trial": False, "global_trial_count": 151}

Getter = Callable[[str], bytes]


class C60PitError(ValueError):
    pass


# ---------------------------------------------------------------- data

def eligible_symbol(symbol: str, all_symbols: Iterable[str]) -> bool:
    if not symbol.endswith("USDT") or len(symbol) <= 4:
        return False
    base = symbol[:-4]
    if base in STABLE_OR_FIAT:
        return False
    names = set(all_symbols)
    for suffix in LEVERAGED_SUFFIXES:
        if base.endswith(suffix) and len(base) > len(suffix) and f"{base[:-len(suffix)]}USDT" in names:
            return False
    return True


def _s3_prefixes(prefix: str, getter: Getter, tag: str) -> list[str]:
    out, marker = [], ""
    for _ in range(100):
        url = f"{S3_LIST}?delimiter=/&prefix={prefix}" + (f"&marker={marker}" if marker else "")
        body = getter(url).decode("utf-8")
        out += re.findall(rf"<{tag}>{re.escape(prefix)}([^<]*)</{tag}>", body)
        if "<IsTruncated>true" not in body:
            return out
        found = re.search(r"<NextMarker>([^<]*)</NextMarker>", body)
        marker = found.group(1) if found else prefix + out[-1]
    raise C60PitError("s3_listing_unbounded")


def list_spot_symbols(getter: Getter) -> list[str]:
    return sorted(p.rstrip("/") for p in _s3_prefixes("data/spot/monthly/klines/", getter, "Prefix"))


def list_months(symbol: str, getter: Getter) -> list[str]:
    keys = _s3_prefixes(f"data/spot/monthly/klines/{symbol}/1d/", getter, "Key")
    months = [k[-11:-4] for k in keys if k.endswith(".zip")]
    return sorted(m for m in months if FIRST_MONTH <= m <= LAST_MONTH)


def parse_kline_csv(text: str) -> dict[str, tuple[float, float]]:
    """date -> (close, quote volume); header rows skipped; microsecond timestamps normalised."""

    out: dict[str, tuple[float, float]] = {}
    for line in text.splitlines():
        cols = line.split(",")
        if len(cols) < 8 or not cols[0].strip().isdigit():
            continue
        stamp = int(cols[0])
        if stamp > 10**14:
            stamp //= 1000
        day = dt.datetime.fromtimestamp(stamp / 1000, dt.timezone.utc).date().isoformat()
        close, quote = float(cols[4]), float(cols[7])
        if close > 0.0 and math.isfinite(close) and math.isfinite(quote):
            out[day] = (close, max(0.0, quote))
    return out


def fetch_symbol(symbol: str, getter: Getter) -> dict[str, object]:
    rows: dict[str, tuple[float, float]] = {}
    files = {}
    for month in list_months(symbol, getter):
        raw = getter(ARCHIVE.format(symbol=symbol, month=month))
        files[month] = hashlib.sha256(raw).hexdigest()
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            for name in archive.namelist():
                rows.update(parse_kline_csv(archive.read(name).decode("utf-8")))
    return {"rows": {d: list(v) for d, v in sorted(rows.items())}, "files": files}


# ---------------------------------------------------------------- assets

@dataclass(frozen=True)
class Asset:
    asset_id: str
    symbol: str
    start: int  # index on the master calendar axis
    closes: tuple[float, ...]
    quote: tuple[float, ...]

    @property
    def end(self) -> int:
        return self.start + len(self.closes) - 1

    def has(self, index: int) -> bool:
        return self.start <= index <= self.end

    def close(self, index: int) -> float:
        return self.closes[index - self.start]

    def window(self, index: int, length: int = WARMUP_BARS) -> tuple[float, ...] | None:
        if index - length + 1 < self.start or index > self.end:
            return None
        return self.closes[index - length + 1 - self.start:index + 1 - self.start]

    def volume(self, index: int, days: int = VOLUME_DAYS) -> float:
        lo = max(self.start, index - days + 1)
        return sum(self.quote[lo - self.start:index + 1 - self.start])


@dataclass(frozen=True)
class Axis:
    dates: tuple[str, ...]

    def index(self, day: str) -> int:
        return (dt.date.fromisoformat(day) - dt.date.fromisoformat(self.dates[0])).days


def build_assets(raw: Mapping[str, Mapping[str, Sequence[float]]]) -> tuple[Axis, dict[str, Asset]]:
    """Split each symbol at any missing day; each continuous run is a distinct asset."""

    if "BTCUSDT" not in raw:
        raise C60PitError("btc_missing")
    first = min(dt.date.fromisoformat(min(rows)) for rows in raw.values() if rows)
    last = dt.date.fromisoformat(EVAL_END)
    axis = Axis(tuple((first + dt.timedelta(days=i)).isoformat() for i in range((last - first).days + 1)))
    assets: dict[str, Asset] = {}
    for symbol, rows in sorted(raw.items()):
        days = sorted(d for d in rows if d <= EVAL_END)
        runs: list[list[str]] = []
        for day in days:
            if runs and (dt.date.fromisoformat(day) - dt.date.fromisoformat(runs[-1][-1])).days == 1:
                runs[-1].append(day)
            else:
                runs.append([day])
        for run in runs:
            asset_id = symbol if len(runs) == 1 else f"{symbol}@{run[0]}"
            assets[asset_id] = Asset(asset_id, symbol, axis.index(run[0]),
                                     tuple(float(rows[d][0]) for d in run), tuple(float(rows[d][1]) for d in run))
    btc = [a for a in assets.values() if a.symbol == "BTCUSDT"]
    first_decision = axis.index(FIRST_DECISION)
    if len(btc) != 1 or btc[0].window(first_decision) is None or btc[0].end != len(axis.dates) - 1:
        raise C60PitError("btc_not_continuous_over_window")
    return axis, assets


# ---------------------------------------------------------------- rule

def _month_end(axis: Axis, index: int) -> bool:
    return index + 1 >= len(axis.dates) or axis.dates[index + 1][:7] != axis.dates[index][:7]


def pit_universe(assets: Mapping[str, Asset], index: int) -> list[str]:
    anchors = [a.asset_id for a in assets.values() if a.symbol in ANCHORS and a.window(index) is not None]
    pool = [a for a in assets.values() if a.symbol not in ANCHORS and a.window(index) is not None]
    pool.sort(key=lambda a: (-a.volume(index), a.asset_id))
    return sorted(anchors + [a.asset_id for a in pool[:TOP_N]])


def survivor_universe(assets: Mapping[str, Asset], index: int) -> list[str]:
    return sorted(a.asset_id for a in assets.values() if a.symbol in C60_SYMBOLS and a.window(index) is not None)


def target(windows: Mapping[str, tuple[float, ...]], held: Sequence[str], tradable: Sequence[str],
           btc_id: str, paxg_ids: frozenset[str], contract: DualEnginePaperContract) -> dict[str, float]:
    """Frozen C60 gates + vol cap; base = 1/len(held); held names not tradable stay in cash."""

    btc = windows[btc_id]
    btc_gate = btc[-1] > fmean(btc[-50:])
    base = 0.0 if not held else 1.0 / len(held)
    pre: dict[str, float] = {}
    for asset_id in held:
        if asset_id not in tradable:
            continue
        w = windows[asset_id]
        if w[-1] > fmean(w[-20:]) and (btc_gate or asset_id in paxg_ids):
            pre[asset_id] = base
    if not pre:
        return {}
    vol = _portfolio_volatility({k: windows[k] for k in pre}, pre, window=contract.c60_volatility_window)
    scalar = 1.0 if vol == 0.0 else min(1.0, contract.c60_volatility_target / vol)
    return {k: v * scalar for k, v in pre.items() if v * scalar > 0.0}


def target_path(axis: Axis, assets: Mapping[str, Asset], universe: Callable[[Mapping[str, Asset], int], list[str]],
                ) -> tuple[dict[int, dict[str, float]], dict[int, list[str]]]:
    contract = DualEnginePaperContract.frozen_v1()
    btc_id = next(a.asset_id for a in assets.values() if a.symbol == "BTCUSDT")
    paxg_ids = frozenset(a.asset_id for a in assets.values() if a.symbol == "PAXGUSDT")
    first, last = axis.index(FIRST_DECISION), len(axis.dates) - 2
    held: tuple[str, ...] = ()
    targets: dict[int, dict[str, float]] = {}
    universes: dict[int, list[str]] = {}
    for t in range(first, last + 1):
        if _month_end(axis, t):
            members = universe(assets, t)
            universes[t] = members
            held = _rank_candidates({k: assets[k].window(t) for k in members})
        windows = {btc_id: assets[btc_id].window(t)}
        tradable = []
        for k in held:
            w = assets[k].window(t)
            if w is not None and assets[k].has(t + 1):  # forced exit on the last listed close
                windows[k] = w
                tradable.append(k)
        targets[t] = target(windows, held, tradable, btc_id, paxg_ids, contract)
    return targets, universes


def btc_only_gate(axis: Axis, assets: Mapping[str, Asset]) -> dict[int, dict[str, float]]:
    contract = DualEnginePaperContract.frozen_v1()
    btc = next(a for a in assets.values() if a.symbol == "BTCUSDT")
    out = {}
    for t in range(axis.index(FIRST_DECISION), len(axis.dates) - 1):
        w = btc.window(t)
        held = (btc.asset_id,) if w[-1] / w[-91] - 1.0 > 0.0 else ()
        out[t] = target({btc.asset_id: w}, held, held, btc.asset_id, frozenset(), contract)
    return out


# ---------------------------------------------------------------- accounting

def simulate(axis: Axis, assets: Mapping[str, Asset], targets: Mapping[int, Mapping[str, float]],
             *, cost_bps: float = COST_BPS) -> dict[str, object]:
    rate = cost_bps / 10_000.0
    weights: dict[str, float] = {}
    dates, returns = [], []
    contribution: dict[str, float] = {}
    held_days: dict[str, int] = {}
    turnover = gross_sum = 0.0
    for t in sorted(targets):
        tgt = targets[t]
        traded = sum(abs(tgt.get(k, 0.0) - weights.get(k, 0.0)) for k in set(tgt) | set(weights))
        cost = traded * rate
        turnover += traded
        asset_r = {k: assets[k].close(t + 1) / assets[k].close(t) - 1.0 for k in tgt}
        for k, w in tgt.items():
            contribution[k] = contribution.get(k, 0.0) + w * asset_r[k]
            held_days[k] = held_days.get(k, 0) + 1
        gross_sum += sum(tgt.values())
        day = (1.0 - cost) * (1.0 + sum(w * asset_r[k] for k, w in tgt.items())) - 1.0
        total = 1.0 + day
        weights = {k: w * (1.0 + asset_r[k]) * (1.0 - cost) / total for k, w in tgt.items()} if total > 0.0 else {}
        dates.append(axis.dates[t + 1])
        returns.append(day)
    return {"dates": dates, "returns": returns, "turnover": turnover, "average_gross": gross_sum / len(returns),
            "contribution": contribution, "held_days": held_days}


def _cagr(r: Sequence[float]) -> float:
    nav = math.prod(1.0 + x for x in r)
    return nav ** (365.0 / len(r)) - 1.0 if nav > 0.0 else -1.0


def _sharpe(r: Sequence[float]) -> float:
    mean, std, _, _ = _moments(list(r))
    return 0.0 if std == 0.0 else mean / std * math.sqrt(365.0)


def _mdd(r: Sequence[float]) -> float:
    nav = peak = 1.0
    worst = 0.0
    for x in r:
        nav *= 1.0 + x
        peak = max(peak, nav)
        worst = min(worst, nav / peak - 1.0)
    return worst


def summarize(sim: Mapping[str, object]) -> dict[str, object]:
    dates, r = sim["dates"], sim["returns"]
    kept = [x for d, x in zip(dates, r) if d[:4] != EXCLUDED_YEAR]
    years: dict[str, float] = {}
    for d, x in zip(dates, r):
        years[d[:4]] = years.get(d[:4], 1.0) * (1.0 + x)
    return {"first": dates[0], "last": dates[-1], "bars": len(r), "cagr": round(_cagr(r), 4),
            "sharpe": round(_sharpe(r), 4), "max_drawdown": round(_mdd(r), 4),
            "annual_vol": round(_moments(list(r))[1] * math.sqrt(365.0), 4),
            "average_gross": round(sim["average_gross"], 4),
            "annual_turnover": round(sim["turnover"] / (len(r) / 365.0), 3),
            "ex_2021_cagr": round(_cagr(kept), 4), "ex_2021_sharpe": round(_sharpe(kept), 4),
            "yearly": {y: round(v - 1.0, 4) for y, v in sorted(years.items())}}


def run(raw: Mapping[str, Mapping[str, Sequence[float]]]) -> dict[str, object]:
    axis, assets = build_assets(raw)
    pit_targets, pit_members = target_path(axis, assets, pit_universe)
    surv_targets, _ = target_path(axis, assets, survivor_universe)
    pit = simulate(axis, assets, pit_targets)
    surv = simulate(axis, assets, surv_targets)
    btc = next(a for a in assets.values() if a.symbol == "BTCUSDT")
    first = axis.index(FIRST_DECISION)
    btc_r = [btc.close(t + 1) / btc.close(t) - 1.0 for t in range(first, len(axis.dates) - 1)]
    k = _moments(list(pit["returns"]))[1] / _moments(btc_r)[1]
    static = simulate(axis, assets, {t: {btc.asset_id: k} for t in range(first, len(axis.dates) - 1)})
    gate = simulate(axis, assets, btc_only_gate(axis, assets))
    for name, sim in (("survivor", surv), ("static", static), ("gate", gate)):
        if sim["dates"] != pit["dates"]:
            raise C60PitError(f"window_mismatch:{name}")

    ended = {a.asset_id for a in assets.values() if a.end < len(axis.dates) - 1}
    ever = sorted({k for members in pit_members.values() for k in members})
    contrib = sorted(pit["contribution"].items(), key=lambda kv: kv[1])
    pit_s, surv_s = summarize(pit), summarize(surv)
    bench = max(summarize(static)["ex_2021_sharpe"], summarize(gate)["ex_2021_sharpe"])
    return {
        "guards": GUARDS,
        "assets_total": len(assets),
        "split_symbols": sorted({a.symbol for a in assets.values() if "@" in a.asset_id}),
        "universe_members_ever": len(ever),
        "universe_members_later_ended": sorted(k for k in ever if k in ended),
        "held_later_ended": {k: {"held_days": pit["held_days"][k], "contribution": round(pit["contribution"][k], 4),
                                 "last_date": axis.dates[assets[k].end]}
                             for k in sorted(pit["held_days"]) if k in ended},
        "universe_by_year_end": {axis.dates[t][:4]: m for t, m in sorted(pit_members.items())
                                 if axis.dates[t][5:7] == "12" or t == max(pit_members)},
        "static_k": round(k, 6),
        "variants": {"pit_c60_v2": pit_s, "survivor_c60_v2": surv_s,
                     "btc_static_vol_matched": summarize(static), "btc_only_c60_gate": summarize(gate)},
        "bias": {"cagr": round(surv_s["cagr"] - pit_s["cagr"], 4), "sharpe": round(surv_s["sharpe"] - pit_s["sharpe"], 4),
                 "ex_2021_sharpe": round(surv_s["ex_2021_sharpe"] - pit_s["ex_2021_sharpe"], 4)},
        "pit_contribution_bottom10": {k: round(v, 4) for k, v in contrib[:10]},
        "pit_contribution_top10": {k: round(v, 4) for k, v in reversed(contrib[-10:])},
        "decision": {"benchmark_ex_2021_sharpe": bench,
                     "selection_edge_survives_pit": pit_s["ex_2021_sharpe"] > bench},
    }
