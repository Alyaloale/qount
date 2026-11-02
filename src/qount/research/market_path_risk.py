"""Decision-aligned path labels with honest uncertainty at coarse-bar edges."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
import zipfile

import numpy as np
from scipy.special import ndtr


HOUR_MS=3600000
MINUTE_MS=60000
ASSETS=('BTCUSDT','ETHUSDT','SOLUSDT')


def validate_candle(row,interval):
    row=np.asarray(row,float)
    if row.ndim!=1 or len(row)<7 or not np.all(np.isfinite(row[:7])):raise ValueError('path_invalid_candle')
    if row[0]%interval or row[6]!=row[0]+interval-1:raise ValueError('path_candle_clock')
    o,h,l,c=row[1:5]
    if not 0<l<=min(o,c)<=max(o,c)<=h or row[5]<0:raise ValueError('path_candle_prices')
    return row


def load_path_sources(hour_root,minute_root):
    hours={a:{} for a in ASSETS};minutes={a:{} for a in ASSETS};sources=[]
    for path in sorted(Path(hour_root).glob('hourly*.json')):
        raw=json.loads(path.read_text())['data']
        for asset in ASSETS:
            for value in raw[asset+'_futures']:
                row=validate_candle(value,HOUR_MS);stamp=int(row[0])
                if stamp in hours[asset] and not np.array_equal(row,hours[asset][stamp]):raise ValueError('path_hour_conflict')
                hours[asset][stamp]=row
        sources.append(dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    # Only00:00--01:00 UTC is needed to refine the fixed daily decision edges.
    for asset in ASSETS:
        for path in sorted(Path(minute_root).glob(f'klines-{asset}-1m-*.zip')):
            with zipfile.ZipFile(path) as archive:
                with archive.open(archive.namelist()[0]) as stream:
                    for value in csv.reader(io.TextIOWrapper(stream)):
                        if not value or value[0]=='open_time':continue
                        stamp=int(value[0])
                        if stamp%86400000>=HOUR_MS:continue
                        row=validate_candle(value,MINUTE_MS)
                        if stamp in minutes[asset] and not np.array_equal(row,minutes[asset][stamp]):raise ValueError('path_minute_conflict')
                        minutes[asset][stamp]=row
            sources.append(dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    return hours,minutes,sources


def aligned_path_label(hours,start_ms,end_ms,lower,upper,*,minutes=None):
    """All prices in closed price interval [lower,upper] on [start,end).

    Boundary touches count as inside, so this is not a stop-touch label.

    A complete hourly high/low breach is certain. At a partial edge, only
    endpoints inside the requested interval or fully covering minute bars can
    locate a breach. Otherwise return -1 rather than backdating an extreme.
    Missing future coverage is rejected before inspecting outcomes. Availability
    conservatively waits for every requested coarse hour +60s publication lag.
    """
    start_ms=int(start_ms);end_ms=int(end_ms)
    if start_ms<0 or end_ms<=start_ms or not 0<lower<upper:raise ValueError('path_invalid_window')
    first=start_ms//HOUR_MS*HOUR_MS
    clocks=list(range(first,((end_ms-1)//HOUR_MS+1)*HOUR_MS,HOUR_MS))
    if any(t not in hours for t in clocks):
        return dict(complete=False,label=-1,reason='missing_hours',available_at=0,refined_cells=0)
    ambiguous=False;breach=False;refined=0
    for clock in clocks:
        row=hours[clock];left=max(start_ms,clock);right=min(end_ms,clock+HOUR_MS)
        full=left==clock and right==clock+HOUR_MS
        cells=None
        if not full and minutes is not None and left%MINUTE_MS==0 and right%MINUTE_MS==0:
            needed=list(range(left,right,MINUTE_MS))
            if all(t in minutes for t in needed):cells=[minutes[t] for t in needed];refined+=1
        if cells is not None:
            breach|=any(r[3]<lower or r[2]>upper for r in cells)
        elif full:
            breach|=row[3]<lower or row[2]>upper
        else:
            if left<=row[0]<right:breach|=not lower<=row[1]<=upper
            if left<=row[6]<right:breach|=not lower<=row[4]<=upper
            ambiguous|=row[3]<lower or row[2]>upper
    label=0 if breach else -1 if ambiguous else 1
    return dict(complete=True,label=label,reason='observed_breach' if breach else 'edge_uncertain' if ambiguous else 'inside',
                available_at=(clocks[-1]+HOUR_MS)//1000+60,refined_cells=refined)


def _absorbing_survival(lower,upper,horizon):
    """Standard Brownian survival in (-lower,upper), via absorbing heat kernel."""
    if lower<=0 or upper<=0:return 0.
    width=lower+upper;scale=np.sqrt(horizon)
    if min(lower,upper)>8*scale:return 1.
    if width>100*scale:return float(2*ndtr(min(lower,upper)/scale)-1)
    maximum=max(65,int(np.ceil(width/scale*np.sqrt(2*np.log(1e15))/np.pi))+1)
    odd=np.arange(1,maximum+1,2,dtype=float)
    value=4/np.pi*np.sum(np.sin(odd*np.pi*lower/width)/odd*np.exp(-.5*(odd*np.pi/width)**2*horizon))
    return float(np.clip(value,0,1))


def continuous_range_probability(lower,upper,*,horizon=5.,wait_days=0.):
    """Zero-drift continuous path baseline, not an assertion of true price law.

    Distances use the last known close and sigma20. Optional Gaussian waiting
    integrates uncertainty before the target window starts; the path during
    this wait is unrestricted. Horizon/wait are calendar days for crypto.
    """
    if not np.all(np.isfinite([lower,upper,horizon,wait_days])) or lower+upper<=0 or horizon<=0 or wait_days<0:
        raise ValueError('path_invalid_geometry')
    if wait_days==0:value=_absorbing_survival(lower,upper,horizon)
    else:
        nodes,weights=np.polynomial.hermite.hermgauss(48)
        shift=np.sqrt(2*wait_days)*nodes
        value=float(np.dot(weights,[_absorbing_survival(lower+x,upper-x,horizon) for x in shift])/np.sqrt(np.pi))
    return float(np.clip(value,.001,.999))
