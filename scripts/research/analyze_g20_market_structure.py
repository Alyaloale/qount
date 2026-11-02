"""Market-structure analysis for the G20 small-capital leverage redesign.

Reads only cached data.  Answers the design questions the v2 strategy needs:

A. Trend structure per asset: vol, trend prevalence, return autocorrelation,
   trend continuation, drawdowns — 6 non-BTC crypto + 8 ETF proxies.
B. Correlation structure: does dual-core crypto/ETF diversification actually
   reduce risk in stress periods?
C. Funding economics: annualized funding per crypto leg, conditional on being
   in an uptrend (the regime where this strategy holds).
D. Anatomy of the 16 archived fills: what distinguished winners from losers?
E. Small-capital feasibility: min-notional grid for a 21.25U account, and
   real Binance ETF-perp fidelity vs the Yahoo proxy.

research_only=true / orders_authorized=false.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from qount.research.binance_macro_history import adjusted_bars
from qount.strategies.macro_1atr import SIGNAL_MAPPING


ETF_ROOT = Path("state/research_cache/binance_macro_etf_history_20261015")
PANEL7 = Path("state/research_cache/independent_crypto_factors_20261027/panel_seven.json")
FILLS = Path("state/research_runs/crypto_g20_daily_original_etf_20261102/curves.json")
ETF_INFO = Path("state/research_cache/binance_etf_leverage_20261015/exchange-info.json")
ETF_TICKERS = ("SPY", "QQQ")
CRYPTO = ("ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "LTCUSDT", "LINKUSDT")
DAY = 86400
YEAR_DAYS = 365.0


def load_etf_daily():
    out = {}
    for symbol, ticker in SIGNAL_MAPPING.items():
        bars = adjusted_bars(json.loads(
            (ETF_ROOT / f"yahoo-{ticker}-20160101-2026-01-01.json").read_text()))
        out[symbol] = {b.t: (b.o, b.h, b.l, b.c) for b in bars}
    return out


def load_crypto_daily():
    data = json.loads(PANEL7.read_text())["data"]
    out, funding = {}, {}
    for symbol in CRYPTO:
        rows = data[symbol + "_klines"]
        out[symbol] = {int(r[0]) // 1000: (float(r[1]), float(r[2]), float(r[3]), float(r[4]))
                       for r in rows}
        funding[symbol] = [(int(r["fundingTime"]) // 1000, float(r["fundingRate"]))
                           for r in data[symbol + "_funding"]]
    return out, funding


def daily_closes(ohlc_map, times):
    return np.array([ohlc_map[t][3] for t in times])


def annualized_vol(closes, days_year=YEAR_DAYS):
    r = np.diff(np.log(closes))
    return float(np.std(r, ddof=1) * np.sqrt(days_year)) if len(r) > 30 else None


def mdd(closes):
    nav = closes / closes[0]
    return float(np.max(1 - nav / np.maximum.accumulate(nav)))


def trend_stats(closes, times):
    n = len(closes)
    if n < 130:
        return {}
    ma120 = np.full(n, np.nan)
    for i in range(119, n):
        ma120[i] = np.mean(closes[i - 119:i + 1])
    above = closes > ma120
    valid = np.isfinite(ma120)
    r1 = np.diff(np.log(closes))
    r5 = np.log(closes[5:] / closes[:-5])
    r63 = np.log(closes[63:] / closes[:-63])
    trend_days = above[valid]
    # continuation: P(next 5d > 0 | trailing 63d > 0), aligned forward
    fwd5 = r5[63:]
    signal63 = r63[:-5] > 0
    cont = float(np.mean(fwd5[signal63] > 0)) if np.any(signal63) else None
    uncond = float(np.mean(fwd5 > 0))
    # Non-overlapping 5-day returns; overlapping windows inflate AR1 to ~0.8.
    nw5 = r5[::5]
    return dict(
        above_ma120_frac=float(np.mean(trend_days)),
        ar1_daily=float(np.corrcoef(r1[:-1], r1[1:])[0, 1]),
        ar1_weekly=float(np.corrcoef(nw5[:-1], nw5[1:])[0, 1]),
        week_pos_given_63w_up=cont, week_pos_uncond=uncond,
        best_63d=float(np.max(r63)), worst_63d=float(np.min(r63)),
    )


def window(times, closes, start, end):
    mask = [start <= t < end for t in times]
    idx = [i for i, m in enumerate(mask) if m]
    if len(idx) < 60:
        return {}
    c = closes[idx[0]:idx[-1] + 1]
    return dict(annual_vol=annualized_vol(c), mdd=mdd(c),
                total_return=float(c[-1] / c[0] - 1), days=len(idx))


def rolling_corr(closes_a, closes_b, width=60):
    ra, rb = np.diff(np.log(closes_a)), np.diff(np.log(closes_b))
    n = min(len(ra), len(rb))
    ra, rb = ra[-n:], rb[-n:]
    out = []
    for i in range(width, n + 1):
        out.append(float(np.corrcoef(ra[i - width:i], rb[i - width:i])[0, 1]))
    return np.array(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=Path("state/research_runs/g20_market_structure_20261102"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    etf = load_etf_daily()
    crypto, funding = load_crypto_daily()
    out = dict(research_only=True, orders_authorized=False,
               generated_at=datetime.now(timezone.utc).isoformat(), sections={})

    PRE = (int(datetime(2021, 6, 1, tzinfo=timezone.utc).timestamp()),
           int(datetime(2022, 6, 28, tzinfo=timezone.utc).timestamp()))
    ERA = (int(datetime(2022, 6, 28, tzinfo=timezone.utc).timestamp()),
           int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()))
    PRE_ETF = (int(datetime(2016, 6, 1, tzinfo=timezone.utc).timestamp()), PRE[1])

    # ---- A. per-asset trend structure ----
    per_asset = {}
    for symbol in CRYPTO:
        times = sorted(crypto[symbol])
        closes = daily_closes(crypto[symbol], times)
        rec = dict(kind="crypto", days=len(times),
                   annual_vol=annualized_vol(closes), full_mdd=mdd(closes))
        rec.update(trend_stats(closes, times))
        rec["pre"] = window(times, closes, *PRE)
        rec["era"] = window(times, closes, *ERA)
        per_asset[symbol] = rec
    for symbol in SIGNAL_MAPPING:
        times = sorted(etf[symbol])
        closes = daily_closes(etf[symbol], times)
        rec = dict(kind="etf", days=len(times),
                   annual_vol=annualized_vol(closes, 252), full_mdd=mdd(closes))
        rec.update(trend_stats(closes, times))
        rec["pre_long"] = window(times, closes, *PRE_ETF)
        rec["pre"] = window(times, closes, *PRE)
        rec["era"] = window(times, closes, *ERA)
        per_asset[symbol] = rec
    out["sections"]["per_asset"] = per_asset

    # ---- B. correlation structure (aligned by calendar day, not stamp) ----
    def daykey(m):
        return {t // DAY: v[3] for t, v in m.items()}

    crypto_day = {s: daykey(crypto[s]) for s in CRYPTO}
    etf_day = {s: daykey(etf[s]) for s in SIGNAL_MAPPING}
    common_crypto_days = sorted(set.intersection(*(set(crypto_day[s]) for s in CRYPTO)))
    closes_crypto = {s: np.array([crypto_day[s][d] for d in common_crypto_days]) for s in CRYPTO}
    corr_rows = []
    for i, a in enumerate(CRYPTO):
        for b in CRYPTO[i + 1:]:
            c = rolling_corr(closes_crypto[a], closes_crypto[b])
            corr_rows.append(dict(pair=f"{a}/{b}", group="crypto-crypto",
                                  mean=float(np.mean(c)), p90=float(np.percentile(c, 90))))
    all_days = sorted(set.intersection(*(set(crypto_day[s]) for s in CRYPTO),
                                       *(set(etf_day[s]) for s in SIGNAL_MAPPING)))
    closes_all = {**{s: np.array([crypto_day[s][d] for d in all_days]) for s in CRYPTO},
                  **{s: np.array([etf_day[s][d] for d in all_days]) for s in SIGNAL_MAPPING}}
    universe = list(CRYPTO) + list(SIGNAL_MAPPING)
    for i, a in enumerate(universe):
        for b in universe[i + 1:]:
            ga = "crypto" if a in CRYPTO else "etf"
            gb = "crypto" if b in CRYPTO else "etf"
            if ga == gb == "etf":
                continue
            c = rolling_corr(closes_all[a], closes_all[b], 60)
            corr_rows.append(dict(pair=f"{a}/{b}", group="crypto-etf",
                                  mean=float(np.mean(c)), p90=float(np.percentile(c, 90))))
    out["sections"]["correlation"] = dict(
        window=f"{datetime.fromtimestamp(all_days[0] * DAY, timezone.utc).date()}.."
               f"{datetime.fromtimestamp(all_days[-1] * DAY, timezone.utc).date()}",
        rows=corr_rows,
        group_means={g: float(np.mean([r["mean"] for r in corr_rows if r["group"] == g]))
                     for g in ("crypto-crypto", "crypto-etf")})

    # ---- C. funding economics ----
    fund_stats = {}
    for symbol in CRYPTO:
        rows = funding[symbol]
        rates = np.array([r for _, r in rows])
        times = sorted(crypto[symbol])
        closes = daily_closes(crypto[symbol], times)
        ma120 = np.full(len(closes), np.nan)
        for i in range(119, len(closes)):
            ma120[i] = np.mean(closes[i - 119:i + 1])
        t_of = {t: i for i, t in enumerate(times)}
        up, down = [], []
        for t, rate in rows:
            i = t_of.get(t - t % DAY)
            if i is None or not np.isfinite(ma120[i]):
                continue
            (up if closes[i] > ma120[i] else down).append(rate)
        fund_stats[symbol] = dict(
            n=len(rows), mean_annual_pct=float(np.mean(rates) * 3 * 365 * 100),
            p10_annual_pct=float(np.percentile(rates, 10) * 3 * 365 * 100),
            p90_annual_pct=float(np.percentile(rates, 90) * 3 * 365 * 100),
            mean_annual_uptrend_pct=float(np.mean(up) * 3 * 365 * 100) if up else None,
            mean_annual_downtrend_pct=float(np.mean(down) * 3 * 365 * 100) if down else None,
            up_intervals=len(up), down_intervals=len(down))
    out["sections"]["funding"] = fund_stats

    # ---- D. anatomy of the 16 archived fills ----
    curves = json.loads(FILLS.read_text())
    fills = curves["dual_2slots_2x_10bp"]["fills"]
    etf_daily = load_etf_daily()
    events = []
    for fl in fills:
        if fl["side"] != "BUY":
            continue
        symbol = fl["symbol"]
        t0 = fl["time"]
        sale = next((x for x in fills if x["side"] == "SELL"
                     and x["symbol"] == symbol and x["time"] >= t0), None)
        # trend age at entry: days since close crossed above MA120
        if symbol in crypto:
            times = sorted(crypto[symbol]); mp = crypto[symbol]
        else:
            times = sorted(etf_daily[symbol]); mp = etf_daily[symbol]
        closes = np.array([mp[t][3] for t in times])
        k = int(np.searchsorted(times, t0 - t0 % DAY))
        k = min(k, len(times) - 1)
        age = 0
        if k >= 120:
            for j in range(k, 119, -1):
                ma = np.mean(closes[j - 119:j + 1])
                if closes[j] > ma:
                    age += 1
                else:
                    break
        vol20 = annualized_vol(closes[max(0, k - 60):k + 1], 252 if symbol not in crypto else 365) if k > 40 else None
        events.append(dict(symbol=symbol, entry=fl["time"],
                           exit=sale["time"] if sale else None,
                           holding_bars=(sale.get("holding_bars") or sale.get("holding_hours")) if sale else None,
                           pnl=sale.get("quantity", 0) * (sale["price"] - fl["price"]) if sale else None,
                           trend_age_days=age, vol20=vol20))
    out["sections"]["fill_anatomy"] = events

    # ---- E. small-capital feasibility and ETF-perp fidelity ----
    info = json.loads(ETF_INFO.read_text())
    mins = {}
    for s in info.get("symbols", []):
        name = s.get("symbol", "")
        if name in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "LTCUSDT",
                    "LINKUSDT", "SPYUSDT", "QQQUSDT", "XAUUSDT", "COPPERUSDT", "CLUSDT",
                    "SMHUSDT", "IWMUSDT", "XLEUSDT"):
            f = {x["filterType"]: x for x in s.get("filters", [])}
            mins[name] = dict(min_notional=float(f.get("MIN_NOTIONAL", {}).get("notional", 0)),
                              min_qty=float(f.get("MARKET_LOT_SIZE", {}).get("minQty", 0)),
                              step=float(f.get("MARKET_LOT_SIZE", {}).get("stepSize", 0)),
                              onboard=s.get("onboardDate"))
    capital = 21.25
    grid = []
    for slots in (2, 3, 4):
        for total in (1.0, 2.0, 3.0, 4.0):
            per_slot = capital * total / slots
            grid.append(dict(slots=slots, total_gross=total, per_slot_usdt=round(per_slot, 2),
                             clears_eth20=per_slot >= 20, clears_typical20=per_slot >= 20,
                             clears_xrp5=per_slot >= 5))
    out["sections"]["min_notional"] = dict(exchange=mins, capital=capital, grid=grid)

    # ETF perp fidelity: compare Yahoo SPY/QQQ with Binance perp trade prices.
    fidelity = {}
    for ticker in ETF_TICKERS:
        trade_p = (Path("state/research_cache/binance_etf_leverage_20261015")
                   / f"{ticker}USDT-trade-1775520000-1790899200.json")
        fund_p = (Path("state/research_cache/binance_etf_leverage_20261015")
                  / f"{ticker}USDT-funding-1775520000-1790899200.json")
        if not trade_p.exists():
            continue
        trades = json.loads(trade_p.read_text())
        perp = {int(r[0]) // 1000 // DAY * DAY: float(r[4]) for r in trades}
        # Binance daily closes at 00:00 UTC; Yahoo closes 16:00 NY — compare
        # same-day returns instead of levels.
        perp_days = sorted(perp)
        perp_ret = np.diff(np.log([perp[t] for t in perp_days]))
        yh = etf[ticker + "USDT"]
        yh_days = [t for t in sorted(yh) if perp_days[0] <= t <= perp_days[-1]]
        yh_ret = np.diff(np.log([yh[t][3] for t in yh_days]))
        n = min(len(perp_ret), len(yh_ret))
        rates = []
        if fund_p.exists():
            rates = [float(r["fundingRate"]) for r in json.loads(fund_p.read_text())]
        rec = dict(
            funding_mean_annual_pct=float(np.mean(rates) * 3 * 365 * 100) if rates else None,
            funding_p10_annual_pct=float(np.percentile(rates, 10) * 3 * 365 * 100) if rates else None,
            funding_p90_annual_pct=float(np.percentile(rates, 90) * 3 * 365 * 100) if rates else None,
            funding_n=len(rates))
        if n >= 30:
            rec.update(days=n,
                       daily_return_corr=float(np.corrcoef(perp_ret[-n:], yh_ret[-n:])[0, 1]),
                       perp_total=float(np.exp(np.sum(perp_ret[-n:])) - 1),
                       yahoo_total=float(np.exp(np.sum(yh_ret[-n:])) - 1))
        else:
            rec.update(days=n, overlap_note=(
                "Yahoo proxy cache ends 2026-01-01 while Binance ETF perps start "
                "2026-04; proxy fidelity is unverifiable with current caches."))
        fidelity[ticker] = rec
    out["sections"]["etf_perp_fidelity"] = fidelity

    (args.output / "results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False, default=str) + "\n")

    # ---- console digest ----
    print("== A. per-asset (vol / above-MA120 / ar1-weekly / era-mdd)")
    for s, r in per_asset.items():
        era = r.get("era", {})
        print(f"  {s:<10} vol={r['annual_vol']:.2f}  above120={r.get('above_ma120_frac', 0):.2f}  "
              f"ar1w={r.get('ar1_weekly', 0):+.3f}  cont={r.get('week_pos_given_63w_up')}  "
              f"era_mdd={era.get('mdd', 0):.2f}  era_ret={era.get('total_return', 0):+.2f}")
    print("== B. correlation group means:", out["sections"]["correlation"]["group_means"])
    print("== C. funding annualized (all / uptrend)")
    for s, r in fund_stats.items():
        print(f"  {s:<10} {r['mean_annual_pct']:+.2f}%  up={r['mean_annual_uptrend_pct']:+.2f}%  "
              f"down={r['mean_annual_downtrend_pct']:+.2f}%")
    print("== D. fill anatomy")
    for e in events:
        print(f"  {e['symbol']:<10} hold={e['holding_bars']}  trend_age={e['trend_age_days']}  "
              f"vol20={e['vol20'] and round(e['vol20'], 2)}  pnl={e['pnl'] and round(e['pnl'], 2)}")
    print("== E. min notional:", {k: v["min_notional"] for k, v in mins.items()})
    print("    grid:"); [print("     ", g) for g in grid]
    print("    fidelity:", json.dumps(fidelity, indent=2))


if __name__ == "__main__":
    main()
