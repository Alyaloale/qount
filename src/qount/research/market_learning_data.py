"""Small, causal daily feature/label panel for market-model experiments.

Economic identity, dynamic behavior and future targets are kept separate.
Missing microstructure is NaN with a mask, never a fabricated observation.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import math
from pathlib import Path
import zipfile

import numpy as np

from qount.research.market_state_profiles import FEATURE_NAMES, profile_samples
from qount.research.binance_macro_attack import CONTRACT_SIGNALS
from qount.research_data.regime import compute_kaufman_er


EXTRA_NAMES = (
    "volatility126_annual", "efficiency20_median126", "benchmark_beta126", "benchmark_corr126",
    "return_autocorr126", "absolute_return_autocorr126", "negative_return_fraction126",
    "left_tail_frequency126", "drawdown126", "gap_share20", "turnover_log20",
    "turnover_relative20_126", "illiquidity_proxy20", "intraday_range_atr",
    "funding_rate7d", "funding_rate21d", "funding_change7d", "taker_imbalance3d", "taker_imbalance20d",
    "oi_contract_change1d", "oi_contract_change7d", "oi_price_divergence7d",
    "top_position_account_log_ratio", "oi_notional_turnover20",
    "lower_boundary_distance_sigma20", "upper_boundary_distance_sigma20",
)
ALL_FEATURES=FEATURE_NAMES+EXTRA_NAMES
STYLE_NAMES=("volatility126_annual","efficiency20_median126","benchmark_beta126","benchmark_corr126",
             "return_autocorr126","left_tail_frequency126","drawdown126","gap_share20")
STYLE_COLUMNS=tuple(ALL_FEATURES.index(k) for k in STYLE_NAMES)
TARGET_NAMES=("direction5","direction20","range5","break_survival3")
FEATURE_DESCRIPTIONS={
    "ema20_distance_atr":"(close-EMA20)/ATR14",
    "ema50_distance_atr":"(close-EMA50)/ATR14",
    "ema200_distance_atr":"(close-EMA200)/ATR14",
    "momentum5_sigma":"log(close/close_lag5)/(sigma20*sqrt(5))",
    "momentum20_sigma":"log(close/close_lag20)/(sigma20*sqrt(20))",
    "efficiency20":"abs(20-period net price change)/sum(abs(one-period price changes))",
    "signed_efficiency20":"ER20*sign(20-period log return)",
    "relative_volatility":"log(sigma20/median of up to 252 strictly prior sigma20 values)",
    "volatility_change5":"log(sigma20/sigma20_lag5)",
    "ema50_slope5_atr":"(EMA50-EMA50_lag5)/ATR14",
    "range_position":"(close-prior20_low)/(prior20_high-prior20_low)",
    "action_age":"log1p(consecutive observations with same action state including event status)",
    "direction_age":"log1p(consecutive matching raw directions)",
    "event_age":"break-event age in observations / 3; zero if no event",
    "event_distance_atr":"event_side*(close-fixed_event_boundary)/ATR14; zero without event",
    "return1_sigma":"one-period log return / strictly previous sigma20",
    "benchmark_direction":"-1/0/+1 direction of BTC for crypto, SPY for ETF/proxy",
    "benchmark_efficiency":"benchmark ER20 at same completed observation",
    "relative_momentum20_sigma":"(own_log_return20-benchmark_log_return20)/(own_sigma20*sqrt(20))",
    "volatility126_annual":"std(last126 log returns,ddof=1)*sqrt(365.25 crypto / 252 ETF)",
    "efficiency20_median126":"median of last126 completed ER20 values",
    "benchmark_beta126":"cov(own,benchmark last126 returns)/var(benchmark last126 returns)",
    "benchmark_corr126":"Pearson correlation of own and benchmark last126 returns",
    "return_autocorr126":"lag1 Pearson correlation within last126 log returns",
    "absolute_return_autocorr126":"lag1 Pearson correlation within absolute last126 log returns",
    "negative_return_fraction126":"fraction of last126 log returns below zero",
    "left_tail_frequency126":"fraction of last126 returns below minus2 times their std",
    "drawdown126":"1-current_close/max(last126 closes); current distance, not maximum historical MDD",
    "gap_share20":"mean(abs(log(open/previous_close)),20)/mean(abs(log_return),20)",
    "turnover_log20":"log1p(mean20 quote turnover); ETF uses raw close*volume proxy",
    "turnover_relative20_126":"log(mean20 turnover/mean126 turnover)",
    "illiquidity_proxy20":"median20(abs(log return)/quote turnover)*1e6; not bid/ask spread",
    "intraday_range_atr":"(high-low)/ATR14",
    "funding_rate7d":"sum of funding rates settled during last7 complete UTC days",
    "funding_rate21d":"sum of funding rates settled during last21 complete UTC days",
    "funding_change7d":"last7-day funding-rate sum minus preceding7-day sum",
    "taker_imbalance3d":"2*sum3 taker-buy quote turnover/sum3 total quote turnover-1",
    "taker_imbalance20d":"2*sum20 taker-buy quote turnover/sum20 total quote turnover-1",
    "oi_contract_change1d":"log(current OI contracts / asof OI contracts exactly one calendar day ago)",
    "oi_contract_change7d":"log(current OI contracts / asof OI contracts exactly seven days ago)",
    "oi_price_divergence7d":"7-day log OI-contract change minus 7-day log price change",
    "top_position_account_log_ratio":"log(top-position long/short ratio / top-account long/short ratio)",
    "oi_notional_turnover20":"asof OI quote value / mean20 daily quote turnover",
    "lower_boundary_distance_sigma20":"log(close/prior20_low)/known sigma20",
    "upper_boundary_distance_sigma20":"log(prior20_high/close)/known sigma20",
}


def metric_snapshots(cache):
    """Use only existing archive tails with a five-minute assumed release lag.

    Daily archives may be partial. A tail older than twenty minutes at the daily
    close is missing. No archive download, interpolation or stale carry-forward.
    """
    values={}
    sources=[]
    fields=("sum_open_interest","sum_open_interest_value",
            "count_toptrader_long_short_ratio","sum_toptrader_long_short_ratio")
    for path in sorted(Path(cache).glob("*-metrics-*.zip")):
        asset=path.name.split("-metrics-")[0]
        if asset not in ("BTCUSDT","ETHUSDT","SOLUSDT"):continue
        day=path.stem.rsplit("-metrics-",1)[1]
        end=int(dt.datetime.combine(dt.date.fromisoformat(day),dt.time(23,59,59),dt.timezone.utc).timestamp())
        best=None
        with zipfile.ZipFile(path) as archive:
            with archive.open(archive.namelist()[0]) as stream:
                for row in csv.DictReader(io.TextIOWrapper(stream)):
                    if row["symbol"]!=asset:raise ValueError("metrics_symbol_mismatch")
                    stamp=int(dt.datetime.fromisoformat(row["create_time"]).replace(tzinfo=dt.timezone.utc).timestamp())
                    if not stamp+300<=end or end-stamp>1200:continue
                    try:v=[float(row[k]) for k in fields]
                    except (TypeError,ValueError):continue
                    if not all(np.isfinite(v)) or min(v)<=0:continue
                    if best is None or stamp>best[0]:best=(stamp,v)
        if best is not None:values[asset,day]=(best[0]+300,np.array(best[1]))
        sources.append(str(path))
    return values,sources


def corr(a,b):
    if np.std(a)<1e-12 or np.std(b)<1e-12:return 0.
    return float(np.corrcoef(a,b)[0,1])


def additional_features(bars, states, benchmark, turnover, rates=None, taker=None, metrics=None, asset=""):
    """Completed-window values only; absent sources remain absent."""
    closes=np.array([b.c for b in bars])
    returns=np.r_[0.,np.diff(np.log(closes))]
    market=np.r_[0.,np.diff(np.log([b.c for b in benchmark]))]
    efficiencies=compute_kaufman_er(closes.tolist(),20)
    gaps=np.r_[0.,np.abs(np.log([b.o for b in bars[1:]]/closes[:-1]))]
    output={}
    for i in range(205,len(bars)):
        bar=bars[i]
        r=returns[i-125:i+1]
        m=market[i-125:i+1]
        sigma=max(float(np.std(r,ddof=1)),1e-12)
        beta=float(np.cov(r,m,ddof=1)[0,1]/max(np.var(m,ddof=1),1e-12))
        er=efficiencies[i-125:i+1]
        tail=closes[i-125:i+1]
        q20=turnover[i-19:i+1]
        q126=turnover[i-125:i+1]
        valid_q=np.all(np.isfinite(q126)) and np.all(q126>0)
        mean_q20=float(np.mean(q20)) if np.all(np.isfinite(q20)) and np.all(q20>0) else np.nan
        vals=[sigma*math.sqrt(365.25 if rates is not None else 252),float(np.median(er)),beta,corr(r,m),
            corr(r[1:],r[:-1]),corr(abs(r[1:]),abs(r[:-1])),float(np.mean(r<0)),
            float(np.mean(r < -2*sigma)),float(1-bar.c/max(tail)),
            float(np.mean(gaps[i-19:i+1])/max(np.mean(abs(returns[i-19:i+1])),1e-12)),
            math.log1p(mean_q20) if np.isfinite(mean_q20) else np.nan,
            math.log(mean_q20/np.mean(q126)) if valid_q else np.nan,
            float(np.median(abs(returns[i-19:i+1])/q20)*1e6) if np.isfinite(mean_q20) else np.nan,
            (bar.h-bar.l)/max(states[bar.t]["atr14"],1e-12)]
        if rates is None:
            vals += [np.nan]*5
        else:
            vals += [float(np.sum(rates[i-6:i+1])),float(np.sum(rates[i-20:i+1])),
                float(np.sum(rates[i-6:i+1])-np.sum(rates[i-13:i-6])),
                float(2*np.sum(taker[i-2:i+1])/np.sum(turnover[i-2:i+1])-1),
                float(2*np.sum(taker[i-19:i+1])/np.sum(q20)-1)]
        day=dt.datetime.fromtimestamp(bar.t,dt.timezone.utc).date()
        current=(metrics or {}).get((asset,day.isoformat()))
        lag1=(metrics or {}).get((asset,(day-dt.timedelta(days=1)).isoformat()))
        lag7=(metrics or {}).get((asset,(day-dt.timedelta(days=7)).isoformat()))
        if current is None:
            vals += [np.nan]*5
            available=0
        else:
            available,now=current
            if available>bar.t:raise ValueError("future_metrics_feature")
            one=math.log(now[0]/lag1[1][0]) if lag1 else np.nan
            seven=math.log(now[0]/lag7[1][0]) if lag7 else np.nan
            vals += [one,seven,seven-math.log(bar.c/closes[i-7]),math.log(now[3]/now[2]),
                     now[1]/mean_q20 if np.isfinite(mean_q20) else np.nan]
        known_sigma=max(states[bar.t]["volatility20"],1e-10)
        vals += [math.log(bar.c/states[bar.t]["previous_low20"])/known_sigma,
                 math.log(states[bar.t]["previous_high20"]/bar.c)/known_sigma]
        output[bar.t]=(np.array(vals,float),available)
    return output


def build_dataset(markets, states, panel, metrics, *, etf_cache):
    """Daily rows include unlabeled tails. Targets/maturity never enter X."""
    rows=[]
    for group,book in markets.items():
        benchmark=book["BTCUSDT" if group=="crypto" else "SPYUSDT"]
        for asset,bars in book.items():
            if group=="crypto":
                j=list(markets["crypto"]).index(asset)
                turnover=panel["quote"][:,j]
                rates=panel["daily_rate"][:,j]
                taker=panel["taker"][:,j]
            else:
                path=Path(etf_cache)/f"yahoo-{CONTRACT_SIGNALS[asset]}-20160101-2026-01-01.json"
                raw=json.loads(path.read_text())["chart"]["result"][0]["indicators"]["quote"][0]
                turnover=np.array(raw["close"],float)*np.array(raw["volume"],float)
                assert len(turnover)==len(bars)
                rates=taker=None
            extra=additional_features(bars,states[group][asset],benchmark,turnover,rates,taker,metrics,asset)
            # Reuse the exact retained 19-feature calculation, now at daily stride.
            own={asset:bars}
            own_states={asset:states[group][asset]}
            anchor="BTCUSDT" if group=="crypto" else "SPYUSDT"
            own[anchor]=book[anchor]
            own_states[anchor]=states[group][anchor]
            samples=profile_samples(own,own_states,group,5,origin_stride=1,include_tail=True)
            for sample in samples:
                if sample["asset"]!=asset:continue
                i=sample["bar_index"]
                row=states[group][asset][bars[i].t]
                y=np.full(4,-1,int)
                maturity=np.zeros(4,np.int64)
                for col,horizon in ((0,5),(1,20)):
                    if i+horizon<len(bars):
                        displacement=math.log(bars[i+horizon].c/bars[i].c)
                        boundary=.5*row["volatility20"]*math.sqrt(horizon)
                        y[col]=2 if displacement>boundary else 0 if displacement < -boundary else 1
                        maturity[col]=bars[i+horizon].t
                if i+5<len(bars) and row["action_state"] in ("compression","range","wide_range"):
                    y[2]=int(all(row["previous_low20"]<=b.c<=row["previous_high20"] for b in bars[i+1:i+6]))
                    maturity[2]=bars[i+5].t
                event=row.get("event")
                if i+3<len(bars) and event and event["status"] in ("pending","confirmed"):
                    y[3]=int(all(event["side"]*(b.c-event["boundary"])>0 for b in bars[i+1:i+4]))
                    maturity[3]=bars[i+3].t
                values,available=extra[sample["known_at"]]
                rows.append(dict(sample,group=group,X=np.r_[sample["features"],values],y=y,
                    maturity=maturity,auxiliary_available=available))
    rows.sort(key=lambda r:(r["asset"],r["known_at"]))
    X=np.vstack([r["X"] for r in rows]).astype(np.float32)
    previous=np.full(len(rows),-1,np.int64)
    following=np.full(len(rows),-1,np.int64)
    for i in range(1,len(rows)):
        if rows[i]["asset"]==rows[i-1]["asset"]:
            previous[i]=i-1
            following[i-1]=i
    dataset=dict(X=X,missing=~np.isfinite(X),y=np.stack([r["y"] for r in rows]),
        maturity=np.stack([r["maturity"] for r in rows]),known_at=np.array([r["known_at"] for r in rows],np.int64),
        asset=np.array([r["asset"] for r in rows]),group=np.array([r["group"] for r in rows]),
        economic_category=np.array([r["category"] for r in rows]),state=np.array([r["key"] for r in rows]),
        bar_index=np.array([r["bar_index"] for r in rows]),previous_row=previous,next_row=following,
        auxiliary_available=np.array([r["auxiliary_available"] for r in rows],np.int64),
        route_class=np.array([r["route_class"] if r["route_class"] is not None else -1 for r in rows],int),
        feature_names=np.array(ALL_FEATURES),target_names=np.array(TARGET_NAMES))
    # Candle timestamps were retained at seconds precision in the old studies.
    # Crypto candles really complete at the next UTC second; add a further
    # fixed minute of publication buffer for BOTH markets in this new dataset.
    offset=np.where(dataset["group"]=="crypto",61,60).astype(np.int64)
    dataset["bar_close_time"]=dataset["known_at"]+np.where(dataset["group"]=="crypto",1,0)
    dataset["known_at"]+=offset
    dataset["maturity"]=np.where(dataset["maturity"]>0,dataset["maturity"]+offset[:,None],0)
    if np.any((dataset["y"]<0)!=(dataset["maturity"]==0)):
        raise ValueError("target_censor_mismatch")
    if np.any((dataset["maturity"]>0)&(dataset["maturity"]<=dataset["known_at"][:,None])):
        raise ValueError("target_not_future")
    if np.any(dataset["auxiliary_available"]>dataset["known_at"]):raise ValueError("auxiliary_lookahead")
    return dataset
