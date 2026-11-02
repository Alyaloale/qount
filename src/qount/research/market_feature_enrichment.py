"""Source-led feature enrichment; no target fitting, downloads or live access."""
from __future__ import annotations

from collections import defaultdict
import csv
import datetime as dt
import io
import json
import math
from pathlib import Path
import zipfile
from zoneinfo import ZoneInfo

import numpy as np

from qount.research.binance_macro_history import adjusted_bars
from qount.research_data.regime import compute_ema


# Each tuple is name, source family, exact meaning, unit, past window.
FIELDS=(
    ("candle_body_fraction","price_path","(close-open)/(high-low); missing for zero range","ratio","1 bar"),
    ("candle_close_location","price_path","(close-low)/(high-low); missing for zero range","fraction","1 bar"),
    ("range_expansion20","price_path","log(current high-low / median strictly prior20 high-low)","log ratio","20 prior bars"),
    ("signed_gap_sigma20","price_path","log(open/previous close)/known sigma20; adjusted signal gap for ETF","sigma units","1 bar"),
    ("downside_variance_share20","price_path","sum(min(return,0)^2)/sum(return^2)","fraction","20 bars"),
    ("return_skew20","price_path","mean(((return-mean20)/std20)^3)","dimensionless","20 bars"),
    ("fast_volatility5_20","price_path","log(std5 log returns / std20 log returns)","log ratio","5/20 bars"),
    ("efficiency5","price_path","abs(close-close_lag5)/sum5 absolute close changes","fraction","5 bars"),
    ("momentum63_sigma","price_path","log(close/close_lag63)/(sigma20*sqrt(63))","sigma units","63 bars"),
    ("prior_high_age20","price_path","number of bars since latest maximum high within strictly prior20 /20","fraction","20 prior bars"),
    ("prior_low_age20","price_path","number of bars since latest minimum low within strictly prior20 /20","fraction","20 prior bars"),
    ("maximum_drawdown126","price_path","maximum peak-to-trough close drawdown within last126, unlike current drawdown126","fraction","126 bars"),
    ("peer_above_ema50_fraction","peer_context","fraction above own EMA50 in fixed seven-coin/five-equity panel","fraction","current completed panel"),
    ("peer_momentum20_dispersion","peer_context","cross-sectional std of20-period log returns; fixed representative panel","log return","20 bars"),
    ("own_momentum20_percentile","peer_context","midrank20-period log momentum within same fixed panel; commodities use three-commodity peers","fraction","20 bars"),
    ("trade_count_log20","crypto_activity","log1p(mean20 reported Kline number of trades)","log count","20 UTC days"),
    ("average_trade_size_relative20","crypto_activity","log(current quote turnover/trades / median strictly prior20 quote turnover/trades)","log ratio","20 prior UTC days"),
    ("last_settled_funding_rate","crypto_activity","last funding rate settled strictly before next UTC day; no future announced estimate","rate fraction","current UTC day"),
    ("funding_rate_std21","crypto_activity","std of daily summed settled funding rates","rate fraction","21 UTC days"),
    ("negative_funding_fraction21","crypto_activity","fraction of daily summed settled funding rates below zero","fraction","21 UTC days"),
    ("funding_settlement_count1d","crypto_activity","actual settlement count during completed UTC day; no fixed8h assumption","count","1 UTC day"),
    ("dollar_proxy_momentum20_sigma","macro_context","UUP log-return20 / its sigma20 /sqrt20; dollar ETF proxy, not DXY spot","sigma units","20 cash sessions"),
    ("long_bond_proxy_momentum20_sigma","macro_context","TLT log-return20 / its sigma20 /sqrt20; bond price, not yield or real rate","sigma units","20 cash sessions"),
    ("equity_proxy_breadth50","macro_context","fraction above EMA50 among SPY/QQQ/SMH/IWM/XLE/XLI/XLB","fraction","50 cash sessions"),
    ("cyclical_defensive_relative20","macro_context","mean20 log return of XLI/XLB/IWM/SMH minus mean of XLU/TLT","log return","20 cash sessions"),
    ("commodity_equity_relative20","macro_context","mean20 log return of GLD/CPER/USO minus SPY","log return","20 cash sessions"),
    ("equity_proxy_momentum_dispersion20","macro_context","std20-session log momentum across the seven equity proxies","log return","20 cash sessions"),
    ("macro_oldest_input_age_hours","macro_context","age of oldest required observable macro bar; freshness capped at96h","hours","asof"),
    ("em_equity_proxy_momentum20_sigma","global_context","EEM adjusted log-return20 / its sigma20 /sqrt20; emerging-equity ETF proxy","sigma units","20 cash sessions"),
    ("developed_ex_us_proxy_momentum20_sigma","global_context","EFA adjusted log-return20 / its sigma20 /sqrt20; developed ex-US equity proxy","sigma units","20 cash sessions"),
    ("broad_commodity_proxy_momentum20_sigma","global_context","DBC adjusted log-return20 / its sigma20 /sqrt20; commodity-futures ETF proxy","sigma units","20 cash sessions"),
    ("long_intermediate_bond_relative20","global_context","TLT20-session log return minus IEF20-session log return; duration-relative price, not yield spread","log return difference","20 cash sessions"),
    ("cash_proxy_total_return20","global_context","BIL20-session adjusted log return; cash-ETF total-return proxy, not risk-free rate","log return","20 cash sessions"),
    ("oi_quantity_growth_intraday","metrics_intraday","log(last/first reported OI quantity), not identifiable capital inflow","log ratio","completed UTC day"),
    ("oi_path_volatility_intraday","metrics_intraday","std of5m log reported OI quantity changes times sqrt(number of changes)","log ratio","completed UTC day"),
    ("reported_top_position_log_level","metrics_intraday","log(raw sum_toptrader_long_short_ratio); archive mapping not independently certified","log reported ratio","asof daily tail"),
    ("reported_crowd_ratio_log_level","metrics_intraday","log(raw count_long_short_ratio); do not infer identifiable profitable traders","log reported ratio","asof daily tail"),
    ("reported_top_position_change_intraday","metrics_intraday","log(last/first raw sum_toptrader_long_short_ratio)","log reported ratio","completed UTC day"),
    ("reported_crowd_change_intraday","metrics_intraday","log(last/first raw count_long_short_ratio)","log reported ratio","completed UTC day"),
    ("reported_taker_ratio_log_mean_intraday","metrics_intraday","mean log raw sum_taker_long_short_vol_ratio; not treated as Kline taker imbalance","log reported ratio","completed UTC day"),
    ("metrics_valid_fraction_intraday","metrics_intraday","valid OI record count /288; source-quality metadata","fraction","completed UTC day"),
    ("metrics_record_age_hours","metrics_intraday","decision time minus last underlying metric observation","hours","asof"),
    ("perpetual_spot_premium_close","spot_perpetual","futures close / spot close -1 at same final hourly close; not annualized basis","fraction","24 complete hours"),
    ("perpetual_spot_premium_mean24","spot_perpetual","mean of24 contemporaneous hourly futures/spot close -1","fraction","24 complete hours"),
    ("spot_taker_imbalance24","spot_perpetual","2*spot taker-buy quote / spot total quote -1","fraction","24 complete hours"),
    ("spot_minus_perpetual_flow24","spot_perpetual","spot quote taker imbalance minus futures quote taker imbalance","fraction difference","24 complete hours"),
    ("hourly_realized_vol_daily_sigma","spot_perpetual","sqrt(sum24 hourly futures log(close/open)^2) / known daily sigma20","ratio","24 complete hours"),
    ("hourly_downside_variance_share24","spot_perpetual","negative hourly futures return squared / total hourly return squared","fraction","24 complete hours"),
    ("hourly_efficiency24","spot_perpetual","abs(sum hourly log returns)/sum absolute hourly log returns","fraction","24 complete hours"),
    ("late_session_return_rv24","spot_perpetual","sum last6 hourly log returns /sqrt(sum24 hourly return squared)","realized-vol units","24 complete hours"),
    ("bar_weekday_sin","calendar","sin(2*pi*bar weekday/7), bar's own UTC or NY calendar","dimensionless","known calendar"),
    ("bar_weekday_cos","calendar","cos(2*pi*bar weekday/7), bar's own UTC or NY calendar","dimensionless","known calendar"),
    ("bar_is_weekend","calendar","Saturday/Sunday indicator for underlying bar date","indicator","known calendar"),
)
NEW_NAMES=tuple(r[0] for r in FIELDS)
UNVERIFIED={r[0] for r in FIELDS if r[0].startswith("reported_")}
QUALITY={"macro_oldest_input_age_hours","metrics_valid_fraction_intraday","metrics_record_age_hours"}
MACRO_TICKERS=("SPY","QQQ","SMH","IWM","XLE","XLI","XLB","XLU","TLT","UUP","GLD","CPER","USO")
GLOBAL_TICKERS=("EEM","EFA","DBC","IEF","BIL")


def price_path_features(bars,states,i):
    closes=np.array([b.c for b in bars[max(0,i-125):i+1]])
    all_close=np.array([b.c for b in bars[i-63:i+1]])
    returns=np.diff(np.log(all_close))
    r=returns[-20:]
    sigma=max(states[bars[i].t]["volatility20"],1e-12)
    b=bars[i]
    width=b.h-b.l
    prior=bars[i-20:i]
    typical=float(np.median([x.h-x.l for x in prior]))
    variance=float(np.sum(r*r))
    std=float(np.std(r,ddof=1))
    change=np.diff([x.c for x in bars[i-5:i+1]])
    high=max(x.h for x in prior)
    low=min(x.l for x in prior)
    high_age=next(i-(i-20+j) for j in range(19,-1,-1) if prior[j].h==high)
    low_age=next(i-(i-20+j) for j in range(19,-1,-1) if prior[j].l==low)
    return np.array([
        (b.c-b.o)/width if width>0 else np.nan,(b.c-b.l)/width if width>0 else np.nan,
        math.log(width/typical) if width>0 and typical>0 else np.nan,
        math.log(b.o/bars[i-1].c)/sigma,
        np.sum(np.minimum(r,0)**2)/variance if variance>0 else np.nan,
        np.mean(((r-r.mean())/std)**3) if std>0 else np.nan,
        math.log(max(np.std(r[-5:],ddof=1),1e-12)/sigma),
        abs(b.c-bars[i-5].c)/np.sum(abs(change)) if np.sum(abs(change))>0 else 0.,
        math.log(b.c/bars[i-63].c)/(sigma*math.sqrt(63)),high_age/20,low_age/20,
        np.max(1-closes/np.maximum.accumulate(closes)),
    ],float)


def proxy_records(old_root,tail_root):
    """Compute snapshots separately; append derived values, never splice prices."""
    result,sources={},[]
    for ticker in MACRO_TICKERS:
        records={}
        last_old=-1
        for root,suffix in ((Path(old_root),"20160101-2026-01-01"),(Path(tail_root),"20250101-2026-10-26")):
            path=root/f"yahoo-{ticker}-{suffix}.json"
            if not path.exists():continue
            bars=adjusted_bars(json.loads(path.read_text()))
            closes=[b.c for b in bars]
            ema=compute_ema(closes,50)
            for i in range(50,len(bars)):
                b=bars[i]
                if root==Path(tail_root) and b.t<=last_old:continue
                r=np.diff(np.log(closes[i-20:i+1]))
                records[b.t+60]=(math.log(b.c/closes[i-20]),float(np.std(r,ddof=1)),float(b.c>ema[i]))
            if root==Path(old_root):last_old=bars[-1].t
            sources.append(str(path))
        clocks=sorted(records)
        result[ticker]=(np.array(clocks,np.int64),np.array([records[t] for t in clocks],float))
    return result,sources


def csv_proxy_records(root):
    """Additional existing ETF closes; no manufactured OHLC or cash yield."""
    result,sources={},[]
    for ticker in GLOBAL_TICKERS:
        path=Path(root)/f"{ticker}_daily.csv"
        if not path.exists():continue
        with path.open() as stream:rows=list(csv.DictReader(stream))
        days=[dt.date.fromisoformat(row['Date']) for row in rows]
        if days!=sorted(set(days)):raise ValueError('global_proxy_calendar_order')
        closes=np.array([float(row['Adj Close']) for row in rows])
        if np.any(~np.isfinite(closes)) or np.any(closes<=0):raise ValueError('invalid_global_proxy_close')
        ema=compute_ema(closes.tolist(),50)
        clocks=[];values=[]
        for i in range(50,len(rows)):
            clocks.append(int(dt.datetime.combine(days[i],dt.time(16),ZoneInfo('America/New_York')).timestamp())+60)
            values.append([math.log(closes[i]/closes[i-20]),np.std(np.diff(np.log(closes[i-20:i+1])),ddof=1),float(closes[i]>ema[i])])
        result[ticker]=(np.array(clocks,np.int64),np.array(values,float))
        sources.append(str(path))
    return result,sources


def available_proxies(records,known,max_age):
    values,available,ages={},{},{}
    for ticker,(clocks,rows) in records.items():
        index=np.searchsorted(clocks,known,side="right")-1
        if index>=0 and known-clocks[index]<=max_age:
            values[ticker]=rows[index]
            available[ticker]=int(clocks[index])
            ages[ticker]=known-int(clocks[index])
    return values,available,ages


def macro_features(records,known,max_age=96*3600):
    values,available,ages=available_proxies(records,known,max_age)
    equity=("SPY","QQQ","SMH","IWM","XLE","XLI","XLB")
    definitions=[("UUP",),("TLT",),equity,("XLI","XLB","IWM","SMH","XLU","TLT"),
                 ("GLD","CPER","USO","SPY"),equity,MACRO_TICKERS]
    out=np.full(7,np.nan);times=np.zeros(7,np.int64)
    for j,required in enumerate(definitions):
        if not all(t in values for t in required):continue
        times[j]=max(available[t] for t in required)
        if j<2:
            v=values[required[0]];out[j]=v[0]/max(v[1],1e-12)/math.sqrt(20)
        elif j==2:out[j]=np.mean([values[t][2] for t in equity])
        elif j==3:out[j]=np.mean([values[t][0] for t in required[:4]])-np.mean([values[t][0] for t in required[4:]])
        elif j==4:out[j]=np.mean([values[t][0] for t in required[:3]])-values["SPY"][0]
        elif j==5:out[j]=np.std([values[t][0] for t in equity])
        else:out[j]=max(ages[t] for t in required)/3600;times[j]=known
    return out,times


def global_features(records,known,max_age=96*3600):
    values,available,_=available_proxies(records,known,max_age)
    out=np.full(5,np.nan);times=np.zeros(5,np.int64)
    for j,required in enumerate((('EEM',),('EFA',),('DBC',),('TLT','IEF'),('BIL',))):
        if not all(t in values for t in required):continue
        times[j]=max(available[t] for t in required)
        v=values[required[0]]
        out[j]=v[0]/max(v[1],1e-12)/math.sqrt(20) if j<3 else v[0]-values['IEF'][0] if j==3 else v[0]
    return out,times


def hourly_snapshots(root):
    combined=defaultdict(dict)
    sources=[]
    for path in sorted(Path(root).glob("hourly*.json")):
        raw=json.loads(path.read_text())["data"]
        for key,rows in raw.items():
            if not key.endswith(("_spot","_futures")):continue
            for row in rows:
                stamp=int(row[0])//1000
                numeric=np.array(row,float)
                if len(numeric)!=12 or not np.all(np.isfinite(numeric)):raise ValueError("invalid_hourly_source")
                if stamp in combined[key] and not np.array_equal(combined[key][stamp],numeric):
                    raise ValueError("conflicting_hourly_overlap")
                combined[key][stamp]=numeric
        sources.append(str(path))
    daily={}
    for asset in ("BTCUSDT","ETHUSDT","SOLUSDT"):
        spot,futures=combined[asset+"_spot"],combined[asset+"_futures"]
        days=sorted({t//86400*86400 for t in futures})
        for start in days:
            clocks=list(range(start,start+86400,3600))
            if not all(t in spot and t in futures for t in clocks):continue
            s=np.array([spot[t] for t in clocks]);f=np.array([futures[t] for t in clocks])
            if np.any(s[:,1:6]<=0) or np.any(f[:,1:6]<=0):raise ValueError("invalid_hourly_prices")
            expected_close=np.array(clocks)*1000+3599999
            for rows in (s,f):
                if np.any(rows[:,6]!=expected_close):raise ValueError("incomplete_hourly_interval")
                if np.any(rows[:,2]<np.maximum(rows[:,1],rows[:,4])) or np.any(rows[:,3]>np.minimum(rows[:,1],rows[:,4])):
                    raise ValueError("invalid_hourly_ohlc")
                if np.any(rows[:,10]<0) or np.any(rows[:,10]>rows[:,7]):raise ValueError("invalid_hourly_taker_flow")
            r=np.log(f[:,4]/f[:,1]);rv=float(np.sqrt(np.sum(r*r)))
            if min(np.sum(s[:,7]),np.sum(f[:,7]))<=0:continue
            sf=2*np.sum(s[:,10])/np.sum(s[:,7])-1
            ff=2*np.sum(f[:,10])/np.sum(f[:,7])-1
            values=np.array([f[-1,4]/s[-1,4]-1,np.mean(f[:,4]/s[:,4]-1),sf,sf-ff,rv,
                np.sum(np.minimum(r,0)**2)/rv**2 if rv>0 else np.nan,
                abs(np.sum(r))/np.sum(abs(r)) if np.sum(abs(r))>0 else 0.,
                np.sum(r[-6:])/rv if rv>0 else np.nan])
            daily[asset,start]=(start+86400+60,values)
    return daily,sources


def intraday_metric_snapshots(root):
    fields=("sum_open_interest","sum_toptrader_long_short_ratio","count_long_short_ratio","sum_taker_long_short_vol_ratio")
    result={};sources=[];rejected=0
    for path in sorted(Path(root).glob("*-metrics-*.zip")):
        asset,day=path.stem.split("-metrics-")
        if asset not in ("BTCUSDT","ETHUSDT","SOLUSDT"):continue
        start=int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.timezone.utc).timestamp())
        decision=start+86400+60
        selected={}
        with zipfile.ZipFile(path) as archive:
            with archive.open(archive.namelist()[0]) as stream:
                for row in csv.DictReader(io.TextIOWrapper(stream)):
                    if row["symbol"]!=asset:raise ValueError("metric_asset_mismatch")
                    stamp=int(dt.datetime.fromisoformat(row["create_time"]).replace(tzinfo=dt.timezone.utc).timestamp())
                    if not start<=stamp<start+86400 or stamp+300>decision:continue
                    if (stamp-start)%300:raise ValueError("off_grid_metric_observation")
                    vals=[]
                    for field in fields:
                        try:v=float(row[field])
                        except (TypeError,ValueError,KeyError):v=np.nan
                        vals.append(v if np.isfinite(v) and v>0 else np.nan)
                    if not np.isfinite(vals[0]):continue
                    numeric=np.array(vals)
                    if stamp in selected and not np.array_equal(selected[stamp],numeric,equal_nan=True):
                        raise ValueError("conflicting_metric_timestamp")
                    selected[stamp]=numeric
        sources.append(str(path))
        times=sorted(selected)
        complete=len(times)>=260 and times[0]<=start+900 and start+86400-times[-1]<=1200
        if not complete or max(np.diff(times),default=0)>900:
            rejected+=1;continue
        values=np.array([selected[t] for t in times])
        oi=np.log(values[:,0]);changes=np.diff(oi)
        def endpoints(j):
            return math.log(values[-1,j]/values[0,j]) if np.isfinite(values[0,j]) and np.isfinite(values[-1,j]) else np.nan
        def level(j):return math.log(values[-1,j]) if np.isfinite(values[-1,j]) else np.nan
        ratio=np.log(values[:,3])
        valid=np.isfinite(ratio)
        out=np.array([oi[-1]-oi[0],np.std(changes,ddof=1)*math.sqrt(len(changes)),level(1),level(2),
            endpoints(1),endpoints(2),np.mean(ratio[valid]) if valid.sum()>=260 else np.nan,
            len(times)/288,(decision-times[-1])/3600])
        result[asset,start]=(times[-1]+300,out)
    return result,sources,rejected


def activity_tables(raw):
    result={}
    for key,source in raw["data"].items():
        if not key.endswith("_klines"):continue
        asset=key.removesuffix("_klines")
        rows=np.array(source,float)
        if rows.ndim!=2 or rows.shape[1]!=12 or not np.all(np.isfinite(rows)):
            raise ValueError("invalid_daily_activity_source")
        if np.any(np.diff(rows[:,0])!=86400000) or rows[0,0]%86400000:
            raise ValueError("noncontiguous_daily_activity_source")
        daily=np.zeros(len(rows));counts=np.zeros(len(rows));last=np.full(len(rows),np.nan)
        funding=sorted(raw["data"][asset+"_funding"],key=lambda r:int(r["fundingTime"]))
        seen=set()
        for row in funding:
            stamp=int(row["fundingTime"])
            if stamp in seen:raise ValueError("duplicate_funding_settlement")
            seen.add(stamp)
            day=(int(row["fundingTime"])-int(rows[0,0]))//86400000
            if 0<=day<len(rows):
                rate=float(row["fundingRate"])
                if not np.isfinite(rate):raise ValueError("invalid_funding_settlement")
                daily[day]+=rate;counts[day]+=1;last[day]=rate
        result[asset]=dict(rows=rows,daily=daily,counts=counts,last=last)
    return result


def activity_features(source,asset,i):
    table=source[asset];rows=table["rows"]
    n=rows[:,8];q=rows[:,7]
    valid=(n[i-20:i]>0)&(q[i-20:i]>0)
    mean_size=np.median(q[i-20:i][valid]/n[i-20:i][valid]) if valid.any() else np.nan
    daily=table["daily"][i-20:i+1]
    return np.array([math.log1p(np.mean(n[i-19:i+1])),
        math.log((q[i]/n[i])/mean_size) if n[i]>0 and np.isfinite(mean_size) and mean_size>0 else np.nan,
        table["last"][i],np.std(daily,ddof=1),np.mean(daily<0),table["counts"][i]])


def enrich(data,markets,states,raw,panel,proxies,hourly,metrics):
    """Append information while preserving every old input, target and row."""
    n=len(data["X"])
    extra=np.full((n,len(FIELDS)),np.nan)
    times=np.zeros((n,len(FIELDS)),np.int64)
    at={name:j for j,name in enumerate(NEW_NAMES)}
    macro_cache={};global_cache={}
    activities=activity_tables(raw)
    for group,book in markets.items():
        reference=[b.t for b in next(iter(book.values()))]
        if any([b.t for b in bars]!=reference for bars in book.values()):
            raise ValueError("enrichment_peer_calendar_mismatch")
    for j,asset in enumerate(markets["crypto"]):
        source=activities[asset]
        if not np.allclose(source["daily"],panel["daily_rate"][:,j],rtol=0,atol=1e-12):
            raise ValueError("funding_panel_source_mismatch")
    for k in range(n):
        asset=str(data["asset"][k]);group=str(data["group"][k]);i=int(data["bar_index"][k])
        bars=markets[group][asset];row=states[group][asset][bars[i].t];known=int(data["known_at"][k])
        expected_close=bars[i].t+int(group=="crypto")
        if data["bar_close_time"][k]!=expected_close or known!=expected_close+60:
            raise ValueError("parent_row_source_clock_mismatch")
        if group=="crypto" and int(activities[asset]["rows"][i,6])//1000!=bars[i].t:
            raise ValueError("activity_source_clock_mismatch")
        start=bars[i].t//86400*86400
        def put(first,values,available):
            j=at[first];extra[k,j:j+len(values)]=values
            times[k,j:j+len(values)]=np.where(np.isfinite(values),available,0)
        put("candle_body_fraction",price_path_features(bars,states[group][asset],i),known)
        peers=list(markets[group]) if group=="crypto" else ["SPYUSDT","QQQUSDT","SMHUSDT","IWMUSDT","XLEUSDT"]
        momentum=np.array([math.log(markets[group][s][i].c/markets[group][s][i-20].c) for s in peers])
        breadth=np.mean([markets[group][s][i].c>states[group][s][bars[i].t]["ema50"] for s in peers])
        ranking=peers if asset in peers else ["XAUUSDT","COPPERUSDT","CLUSDT"]
        own=math.log(bars[i].c/bars[i-20].c)
        rank=np.array([math.log(markets[group][s][i].c/markets[group][s][i-20].c) for s in ranking])
        percentile=(np.sum(rank<own)+.5*np.sum(rank==own))/len(rank)
        put("peer_above_ema50_fraction",[breadth,np.std(momentum),percentile],known)
        if group=="crypto":put("trade_count_log20",activity_features(activities,asset,i),known)
        if known not in macro_cache:macro_cache[known]=macro_features(proxies,known)
        values,available=macro_cache[known]
        j=at["dollar_proxy_momentum20_sigma"];extra[k,j:j+7]=values;times[k,j:j+7]=available
        if known not in global_cache:global_cache[known]=global_features(proxies,known)
        values,available=global_cache[known]
        j=at['em_equity_proxy_momentum20_sigma'];extra[k,j:j+5]=values;times[k,j:j+5]=available
        observed=metrics.get((asset,start))
        if observed:
            available,values=observed
            put("oi_quantity_growth_intraday",values,available)
            times[k,at["metrics_record_age_hours"]]=known
        observed=hourly.get((asset,start))
        if observed:
            available,values=observed;values=values.copy()
            values[4]/=max(row["volatility20"],1e-12)
            put("perpetual_spot_premium_close",values,available)
        local=dt.datetime.fromtimestamp(bars[i].t,dt.timezone.utc if group=="crypto" else ZoneInfo("America/New_York"))
        put("bar_weekday_sin",[math.sin(2*math.pi*local.weekday()/7),math.cos(2*math.pi*local.weekday()/7),float(local.weekday()>=5)],known)
    out={k:v.copy() for k,v in data.items()}
    out["X"]=np.c_[data["X"],extra].astype(np.float32)
    out["missing"]=~np.isfinite(out["X"])
    out["feature_names"]=np.r_[data["feature_names"],np.array(NEW_NAMES)]
    old_times=np.where(np.isfinite(data["X"]),data["known_at"][:,None],0)
    out["feature_available_at"]=np.c_[old_times,times]
    out["default_feature_mask"]=np.array([name!="top_position_account_log_ratio" for name in data["feature_names"]]+
        [name not in UNVERIFIED|QUALITY for name in NEW_NAMES],bool)
    if np.any(np.isfinite(out["X"])&(out["feature_available_at"]>out["known_at"][:,None])):
        raise ValueError("enriched_feature_lookahead")
    if np.any(np.isinf(out["X"])):raise ValueError("infinite_enriched_feature")
    return out
