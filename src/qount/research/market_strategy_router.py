"""State probabilities select traditional strategies; offline research only.

This mixed-state V1 schema is retained for historical experiment reproduction.
The current pure-environment V2 research API lives in market_regimes.py.

The classifier adapter returns probabilities only. Routing and OHLC/ATR/EMA
entry rules are independent deterministic functions with no payoff ML head.
Existing positions remain under their original exit rules in the replay engine.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from qount.research.market_stages import ACTION_STATES


STATE_NAMES=ACTION_STATES+('shock','unknown')
STRATEGIES={
    'up_trend':'trend_pullback_long','down_trend':'trend_rally_short',
    'range':'range_rejection','wide_range':'wide_range_rejection',
    'up_breakout':'confirmed_breakout_long','down_breakout':'confirmed_breakout_short',
    'failed_up_breakout':'failed_breakout_short','failed_down_breakout':'failed_breakout_long',
    'compression':None,'transition':None,'shock':None,'unknown':None,
}


def state_probabilities(classifier,matrix):
    """Public model output: one {state: probability} dictionary per row.

    Unknown is omitted when it has no supervised examples. Missing known
    classes receive zero within the conditional known-state distribution.
    No strategy, expected return, entry threshold or position is returned.
    """
    values=np.asarray(classifier.predict_proba(matrix),float)
    classes=np.asarray(classifier[-1].classes_,int)
    if (values.ndim!=2 or values.shape[1]!=len(classes) or np.any(~np.isfinite(values))
            or np.any(values<0) or not np.allclose(values.sum(1),1)):
        raise ValueError('router_invalid_model_probabilities')
    if np.any(classes<0) or np.any(classes>=len(STATE_NAMES)):raise ValueError('router_unknown_class_code')
    names=STATE_NAMES if STATE_NAMES.index('unknown') in classes else STATE_NAMES[:-1]
    return [{name:float(row[np.flatnonzero(classes==STATE_NAMES.index(name))[0]])
             if STATE_NAMES.index(name) in classes else 0. for name in names} for row in values]


@dataclass(frozen=True)
class StrategyRoute:
    state: str | None
    probability: float
    strategy: str | None
    reason: str


def route_strategy(probabilities,*,threshold=.70):
    """Select one exact state; do not sum unrelated states into a trade score."""
    if not .0<=threshold<=1.:raise ValueError('router_invalid_threshold')
    if not probabilities:return StrategyRoute(None,0.,None,'no_probabilities')
    if set(probabilities)-set(STATE_NAMES):raise ValueError('router_unknown_state')
    values=list(probabilities.values())
    if any(v is None or not math.isfinite(v) or v<0 for v in values) or not math.isclose(sum(values),1.,abs_tol=1e-6):
        raise ValueError('router_invalid_probability_vector')
    ranked=sorted(probabilities.items(),key=lambda p:(-p[1],p[0]));state,p=ranked[0]
    if len(ranked)>1 and math.isclose(p,ranked[1][1],abs_tol=1e-12):return StrategyRoute(state,p,None,'ambiguous_top_state')
    if p<threshold:return StrategyRoute(state,p,None,'below_state_threshold')
    strategy=STRATEGIES[state]
    return StrategyRoute(state,p,strategy,'strategy_enabled' if strategy else 'wait_or_protect')


def traditional_entry(route,bar,features,*,allow_short=True):
    """A strategy permission still requires its own completed-bar entry setup.

    Fixed exploratory rules, no parameter search: 2 ATR trend stops, original
    breakout boundary +/-1 ATR stops, .25 ATR rejection stops; range midpoint
    and event 2R targets. At most5 bars (failed break3), no averaging down.
    """
    strategy=route.strategy
    if strategy is None or features['action_state'] in ('unknown','shock'):return None
    atr=features['atr14'];ema20=features['ema20'];ema50=features['ema50']
    low=features['previous_low20'];high=features['previous_high20'];event=features.get('event')
    side=0;stop=target=None;fraction=1.;max_bars=5
    if strategy=='trend_pullback_long':
        if bar.c>ema20>ema50 and bar.l<=ema20+.25*atr and bar.c>bar.o and bar.c-ema20<=atr:side=1
    elif strategy=='trend_rally_short':
        if bar.c<ema20<ema50 and bar.h>=ema20-.25*atr and bar.c<bar.o and ema20-bar.c<=atr:side=-1
    elif strategy in ('range_rejection','wide_range_rejection'):
        pos=(bar.c-low)/max(high-low,1e-12)
        if 0<=pos<=.2 and bar.c>bar.o:side=1;stop=low-.25*atr
        elif .8<=pos<=1 and bar.c<bar.o:side=-1;stop=high+.25*atr
        target=(low+high)/2;fraction=.5 if strategy=='wide_range_rejection' else 1.
    elif strategy in ('confirmed_breakout_long','confirmed_breakout_short'):
        side=1 if strategy.endswith('long') else -1
        if event is None or event['side']!=side or event['status']!='confirmed':return None
        boundary=event['boundary']
        if not 0<side*(bar.c-boundary)<=atr:return None
        stop=boundary-side*atr;target=bar.c+side*2*abs(bar.c-stop)
    elif strategy in ('failed_breakout_long','failed_breakout_short'):
        side=1 if strategy.endswith('long') else -1
        if event is None or event['side']!=-side or event['status']!='failed':return None
        if side*(bar.c-event['boundary'])<=0 or side*(bar.c-bar.o)<=0:return None
        stop=min(bar.l,event['boundary'])-.25*atr if side>0 else max(bar.h,event['boundary'])+.25*atr
        target=bar.c+side*2*abs(bar.c-stop);max_bars=3
    else:raise ValueError('router_unknown_strategy')
    if not side or side<0 and not allow_short:return None
    if stop is None:stop=bar.c-side*2*atr
    if stop<=0 or target is not None and target<=0:return None
    return dict(side=side,stop=stop,target=target,fraction=fraction,max_bars=max_bars,strategy=strategy)
