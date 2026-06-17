"""X4 single-asset directional backtest driver + §4 metrics (线 D). Plan: §3/§4.

Feeds one bar stream to a :class:`~qount.x4.strategies.Strategy`, sizes its signed target weight
**equity-normalized** (``target_base = weight × equity / close``), trades the unified
:class:`~qount.x4.account.X4Account`, optionally settles funding, and snapshots equity each bar.
Fill is at the bar close (no look-ahead: the decision uses only closes up to and including the
current bar). Reports the bake-off §4 metrics, reusing ``rv.stats`` for Sharpe.

This driver handles the single-asset directional contestants (S3-CTA, S4-MOM). The grid (S1) and
pair (S2) drivers are separate (different position shapes) and land in the next B0 increment.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Callable
from typing import Sequence

from qount.grid.data import Bar
from qount.grid.engine import GridLadder
from qount.grid.engine import build_grid
from qount.grid.trend import TrendState
from qount.grid.trend import trend_states
from qount.rv import stats as _stats
from qount.x4.account import X4Account
from qount.x4.indicators import ATR
from qount.x4.strategies import GridStrategy
from qount.x4.strategies import PairStrategy
from qount.x4.strategies import Strategy


@dataclass
class X4Result:
    """One contestant's run: equity curve + the §4 comparison metrics.

    ``extra`` carries strategy-specific diagnostics (grid fill counts, pair positions) without
    polluting the shared metric fields; directional runs leave it empty.
    """

    name: str
    equity_curve: list[float]
    total_return: float
    sharpe: float
    max_drawdown: float
    trade_count: int
    fees_paid: float
    funding_pnl: float
    extra: dict = field(default_factory=dict)


def _should_rebalance(current: float, target: float, band: float) -> bool:
    """Whether to trade ``current`` -> ``target``: always on open/close/flip; else only past a
    drift ``band`` (fraction of current notional). Suppresses the fee-induced micro-churn that
    every-bar equity-normalized resizing would otherwise generate."""

    eps = 1e-12
    if abs(current) < eps:
        return abs(target) > eps          # open only if a position is wanted
    if abs(target) < eps:
        return True                       # close to flat
    if (current > 0) != (target > 0):
        return True                       # flip
    return abs(target - current) > band * abs(current)


def max_drawdown(curve: Sequence[float]) -> float:
    """Largest peak-to-trough fractional drawdown of an equity curve (<= 0; 0 if monotone)."""

    peak = float("-inf")
    mdd = 0.0
    for v in curve:
        if v > peak:
            peak = v
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return mdd


def run_directional(
    bars: Sequence[Bar],
    strategy: Strategy,
    *,
    initial_capital: float = 100_000.0,
    taker_fee: float = 0.0005,
    slippage: float = 0.0002,
    funding: Callable[[Bar], float] | None = None,
    rebalance_band: float = 0.0,
    vol_target: float = 0.0,
    vol_lookback: int = 14,
    max_leverage: float = 1.0,
    chandelier_mult: float = 0.0,
    chandelier_lookback: int = 22,
    periods_per_year: float | None = None,
) -> X4Result:
    """Run one single-asset directional strategy and return its :class:`X4Result`.

    ``funding`` (optional) maps a bar to its funding rate for the period, settled on the signed
    notional after the bar's trade. ``rebalance_band`` is the equity-drift deadband (fraction of
    current notional) below which the position is left alone — it suppresses fee-induced micro-churn
    while always trading on a genuine signal change.

    ``vol_target`` > 0 turns on **volatility-parity sizing** (risk parity): the position is scaled to
    ``min(max_leverage, vol_target / atr_pct)`` where ``atr_pct`` is the ``vol_lookback``-bar ATR as a
    fraction of price — small in high vol, large (capped) in low vol, so each trade carries a roughly
    constant risk exposure (flattens the equity curve, caps drawdown). 0 = off (always 1x). Sizing is
    flat during ATR warm-up (no look-ahead). ``periods_per_year`` annualizes the Sharpe if given.

    ``chandelier_mult`` > 0 adds an **asymmetric Chandelier exit** (long-only): while long, trail a
    stop at ``highest_high_since_entry − chandelier_mult × ATR(chandelier_lookback)`` (ratchets up,
    never down); if a bar's low pierces it, flatten and latch out until the strategy signal resets to
    flat/short (then a fresh signal re-enters). Slow entry, fast exit — cuts the trend giveback at a
    blow-off top. 0 = off.
    """

    acct = X4Account(initial_capital=initial_capital, taker_fee=taker_fee, slippage=slippage)
    atr = ATR(vol_lookback) if vol_target > 0 else None
    atr_ch = ATR(chandelier_lookback) if chandelier_mult > 0 else None
    hh_since_entry: float | None = None
    ch_latched = False
    chandelier_exits = 0
    curve: list[float] = []
    for bar in bars:
        raw = strategy.on_bar(bar)
        scale = 1.0
        if atr is not None:
            a = atr.update(bar)
            atr_pct = a / bar.close if (a is not None and bar.close > 0) else None
            scale = min(max_leverage, vol_target / atr_pct) if atr_pct and atr_pct > 0 else 0.0
        weight = raw
        if atr_ch is not None:
            a_ch = atr_ch.update(bar)
            was_long = acct.position_base > 1e-12
            if ch_latched and raw <= 0.0:
                ch_latched = False          # signal reset -> re-arm
            if ch_latched:
                weight = 0.0
            elif was_long and a_ch is not None:
                hh_since_entry = bar.high if hh_since_entry is None else max(hh_since_entry, bar.high)
                stop = hh_since_entry - chandelier_mult * a_ch
                if bar.low <= stop:          # trailing stop pierced -> flatten + latch
                    weight = 0.0
                    ch_latched = True
                    hh_since_entry = None
                    chandelier_exits += 1
            if not was_long and weight > 0.0:
                hh_since_entry = bar.high     # newly entering long -> start the trail
        eq = acct.equity(bar.close)
        target_base = weight * scale * eq / bar.close
        if _should_rebalance(acct.position_base, target_base, rebalance_band):
            acct.trade(target_base, bar.close)
        if funding is not None:
            acct.accrue_funding(funding(bar), bar.close)
        curve.append(acct.equity(bar.close))

    last_w = acct.weight(bars[-1].close) if bars else 0.0
    return _result(strategy.name if hasattr(strategy, "name") else strategy.__class__.__name__,
                   curve, initial_capital, acct.trade_count, acct.fees_paid, acct.funding_pnl,
                   periods_per_year,
                   {"chandelier_exits": chandelier_exits, "final_weight": last_w,
                    "final_position_base": acct.position_base})


def _result(name, curve, initial_capital, trades, fees, funding, periods_per_year, extra=None):
    rets = _stats.returns_from_curve(curve)
    sharpe = _stats.sharpe(rets, periods_per_year=periods_per_year) if len(rets) >= 2 else 0.0
    final = curve[-1] if curve else initial_capital
    return X4Result(
        name=name,
        equity_curve=curve,
        total_return=final / initial_capital - 1.0,
        sharpe=sharpe,
        max_drawdown=max_drawdown(curve),
        trade_count=trades,
        fees_paid=fees,
        funding_pnl=funding,
        extra=extra or {},
    )


def run_grid(
    bars: Sequence[Bar],
    cfg: GridStrategy | None = None,
    *,
    initial_capital: float = 100_000.0,
    taker_fee: float = 0.0005,
    slippage: float = 0.0002,
    gate_override: Sequence[TrendState] | None = None,
    atr_lookback: int = 14,
    atr_mult: float = 0.0,
    funding: Callable[[Bar], float] | None = None,
    periods_per_year: float | None = None,
) -> X4Result:
    """Run S1-GRID: a long-only geometric grid under the SMA200 trend gate (plan §2 S1).

    The gate (per bar) decides behaviour: ACTIVE = full grid (seed if not armed; buy on dips to
    grid lines, sell held cells on rallies); DERISK = sell-only (de-risk, no new buys); PAUSED =
    liquidate all inventory to cash at the close and disarm (re-seeds on the next ACTIVE). Pass
    ``gate_override`` to supply the gate directly (testing / a shared bake-off gate); otherwise it
    is computed from closes via ``grid.trend.trend_states``.

    ``atr_mult`` > 0 makes the grid **ATR-dynamic**: at each (re)seed the half-width is
    ``clamp(atr_mult × atr_pct, 5%, 40%)`` from the ``atr_lookback``-bar ATR — it widens in high vol
    (don't get broken through) and tightens in low vol (more turnover). 0 = fixed ``cfg.half_width``.
    ``funding`` (optional) accrues perp funding on the held long inventory each bar: a long **pays**
    when the rate is positive (honest -- to *earn* funding you must short the perp = the delta-neutral
    carry of 线 C, not a long-only grid). Equity = ``initial_capital + booked + live ladder equity +
    funding``.
    """

    cfg = cfg or GridStrategy()
    atr = ATR(atr_lookback) if atr_mult > 0 else None
    grid_funding = 0.0
    if gate_override is not None:
        gates = list(gate_override)
        if len(gates) != len(bars):
            raise ValueError("gate_override length must match bars")
    else:
        gates = trend_states([b.close for b in bars], window=cfg.sma_window,
                             confirm_bars=cfg.confirm_bars)

    booked = 0.0
    total_fees = 0.0
    ladder: GridLadder | None = None
    ref = 0.0
    curve: list[float] = []
    buy_fills = sell_fills = liquidations = seed_count = 0

    def eq(mark: float) -> float:
        return initial_capital + booked + grid_funding + (ladder.equity(mark) if ladder is not None else 0.0)

    for bar, state in zip(bars, gates):
        atr_pct = None
        if atr is not None:
            a = atr.update(bar)
            atr_pct = a / bar.close if (a is not None and bar.close > 0) else None
        if state == TrendState.ACTIVE:
            if ladder is None:
                half_width = cfg.half_width if atr_pct is None else max(0.05, min(0.40, atr_mult * atr_pct))
                spec = build_grid(
                    lower=bar.close * (1.0 - half_width),
                    upper=bar.close * (1.0 + half_width),
                    grid_capital=eq(bar.close),
                    n=cfg.n,
                    maker_fee=taker_fee,
                    slippage=slippage,
                )
                ladder = GridLadder(spec=spec, maker_fee=taker_fee)
                ref = bar.close
                seed_count += 1
            held = [c.holding for c in ladder.cells]
            for k in range(ladder.spec.n):  # sells first: cells held at bar start, rallied to top
                if held[k] and bar.high >= ladder.spec.prices[k + 1]:
                    ladder.apply_sell_fill(k)
                    sell_fills += 1
            for k in range(ladder.spec.n):  # buys: armed line (<= ref) reached on the dip
                if not ladder.cells[k].holding and ladder.spec.prices[k] <= ref and bar.low <= ladder.spec.prices[k]:
                    ladder.apply_buy_fill(k)
                    buy_fills += 1
            ref = bar.close
        elif state == TrendState.DERISK:
            if ladder is not None:
                held = [c.holding for c in ladder.cells]
                for k in range(ladder.spec.n):
                    if held[k] and bar.high >= ladder.spec.prices[k + 1]:
                        ladder.apply_sell_fill(k)
                        sell_fills += 1
                ref = bar.close
        else:  # PAUSED: liquidate to cash
            if ladder is not None:
                total_fees += ladder.fees_paid
                if ladder.inventory_base > 1e-12:
                    liq_fee = ladder.inventory_base * bar.close * taker_fee
                    booked += ladder.equity(bar.close) - liq_fee
                    total_fees += liq_fee
                    liquidations += 1
                else:
                    booked += ladder.equity(bar.close)  # carry realized grid profit, no inventory
                ladder = None
        if funding is not None and ladder is not None and ladder.inventory_base > 1e-12:
            grid_funding += -funding(bar) * ladder.inventory_base * bar.close  # long pays positive
        curve.append(eq(bar.close))

    if ladder is not None:
        total_fees += ladder.fees_paid
    extra = {
        "buy_fills": buy_fills,
        "sell_fills": sell_fills,
        "liquidations": liquidations,
        "seed_count": seed_count,
        "final_inventory_base": ladder.inventory_base if ladder is not None else 0.0,
    }
    return _result(cfg.name, curve, initial_capital, buy_fills + sell_fills + liquidations,
                   total_fees, grid_funding, periods_per_year, extra)


def run_pair(
    btc_bars: Sequence[Bar],
    eth_bars: Sequence[Bar],
    cfg: PairStrategy | None = None,
    *,
    initial_capital: float = 100_000.0,
    taker_fee: float = 0.0005,
    slippage: float = 0.0002,
    periods_per_year: float | None = None,
) -> X4Result:
    """Run S2-PAIR: a BTC-ETH ratio z-score statistical-arbitrage pair (plan §2 S2).

    Signal = z-score of the ETH/BTC close ratio over a trailing ``window``. ``z > +entry_z`` (ETH
    rich) => long BTC / short ETH; ``z < -entry_z`` => the reverse; ``|z| < exit_z`` => flat
    (hysteresis: hold otherwise). Each leg is its own pure ledger (``X4Account``) sharing the one
    $100k capital; each is sized ``leg_leverage × equity`` for a dollar-neutral spread. Both legs
    charge the same ``taker_fee``/``slippage`` as the other contestants.
    """

    cfg = cfg or PairStrategy()
    if len(btc_bars) != len(eth_bars):
        raise ValueError("btc_bars and eth_bars must be aligned (same length)")

    btc = X4Account(initial_capital=0.0, taker_fee=taker_fee, slippage=slippage)
    eth = X4Account(initial_capital=0.0, taker_fee=taker_fee, slippage=slippage)
    ratios: list[float] = []
    pos = 0       # +1 long-BTC/short-ETH, -1 reverse, 0 flat
    prev_pos = 0
    stopped = False  # latched flat after a stop_z break; re-arms once |z| normalizes
    curve: list[float] = []

    def eq(b_close: float, e_close: float) -> float:
        return initial_capital + btc.equity(b_close) + eth.equity(e_close)

    for b, e in zip(btc_bars, eth_bars):
        ratios.append(e.close / b.close)
        if len(ratios) >= cfg.window:
            win = ratios[-cfg.window:]
            mean = sum(win) / len(win)
            var = sum((x - mean) ** 2 for x in win) / (len(win) - 1)
            std = var ** 0.5
            z = (ratios[-1] - mean) / std if std > 0 else 0.0
            if pos == 0:
                if stopped:
                    if abs(z) < cfg.exit_z:
                        stopped = False  # spread normalized -> allow new entries again
                elif z > cfg.entry_z:
                    pos = 1
                elif z < -cfg.entry_z:
                    pos = -1
            elif cfg.stop_z > 0 and abs(z) > cfg.stop_z:
                pos = 0           # cointegration break: cut the runaway spread, latch flat
                stopped = True
            elif abs(z) < cfg.exit_z:
                pos = 0
        # B1-b: only trade on a position change (entry/exit/flip), not every bar — leaving a held
        # spread alone is the standard stat-arb implementation and kills the resize churn artifact.
        if pos != prev_pos:
            leg_notional = cfg.leg_leverage * eq(b.close, e.close)
            btc.trade(pos * leg_notional / b.close, b.close)
            eth.trade(-pos * leg_notional / e.close, e.close)
            prev_pos = pos
        curve.append(eq(b.close, e.close))

    extra = {"final_pos": pos, "btc_base": btc.position_base, "eth_base": eth.position_base}
    return _result(cfg.name, curve, initial_capital, btc.trade_count + eth.trade_count,
                   btc.fees_paid + eth.fees_paid, btc.funding_pnl + eth.funding_pnl,
                   periods_per_year, extra)


def run_kalman_pair(
    btc_bars: Sequence[Bar],
    eth_bars: Sequence[Bar],
    cfg: "KalmanPair | None" = None,
    *,
    initial_capital: float = 100_000.0,
    taker_fee: float = 0.0005,
    slippage: float = 0.0002,
    periods_per_year: float | None = None,
) -> X4Result:
    """Run S2-K: the BTC-ETH pair on a Kalman dynamic hedge ratio (§12 optimization of S2-PAIR).

    Mirrors :func:`run_pair` (dollar-neutral legs, trade only on position change, optional ``stop_z``
    latch) but the z-signal comes from :class:`~qount.x4.indicators.KalmanHedge` — β adapts online so
    a structural drift in ETH/BTC is tracked instead of triggering the static z's forced stop.
    """

    from qount.x4.indicators import KalmanHedge
    from qount.x4.strategies import KalmanPair

    cfg = cfg or KalmanPair()
    if len(btc_bars) != len(eth_bars):
        raise ValueError("btc_bars and eth_bars must be aligned (same length)")

    kf = KalmanHedge(delta=cfg.delta, r=cfg.r)
    btc = X4Account(initial_capital=0.0, taker_fee=taker_fee, slippage=slippage)
    eth = X4Account(initial_capital=0.0, taker_fee=taker_fee, slippage=slippage)
    pos = 0
    prev_pos = 0
    stopped = False
    curve: list[float] = []

    def eq(b_close: float, e_close: float) -> float:
        return initial_capital + btc.equity(b_close) + eth.equity(e_close)

    for i, (b, e) in enumerate(zip(btc_bars, eth_bars)):
        _beta, _e, z = kf.update(b.close, e.close)
        if i >= cfg.warmup:
            if pos == 0:
                if stopped:
                    if abs(z) < cfg.exit_z:
                        stopped = False
                elif z > cfg.entry_z:       # ETH rich vs its dynamic fair value -> short ETH/long BTC
                    pos = 1
                elif z < -cfg.entry_z:
                    pos = -1
            elif cfg.stop_z > 0 and abs(z) > cfg.stop_z:
                pos = 0
                stopped = True
            elif abs(z) < cfg.exit_z:
                pos = 0
        if pos != prev_pos:
            leg_notional = cfg.leg_leverage * eq(b.close, e.close)
            btc.trade(pos * leg_notional / b.close, b.close)
            eth.trade(-pos * leg_notional / e.close, e.close)
            prev_pos = pos
        curve.append(eq(b.close, e.close))

    extra = {"final_pos": pos, "final_beta": kf.beta,
             "btc_base": btc.position_base, "eth_base": eth.position_base}
    return _result(cfg.name, curve, initial_capital, btc.trade_count + eth.trade_count,
                   btc.fees_paid + eth.fees_paid, 0.0, periods_per_year, extra)


def run_cross_sectional(
    bars_by_sym: dict[str, list[Bar]],
    *,
    lookback: int = 30,
    top_k: int = 3,
    regime_sma: int = 200,
    rebalance_days: int = 7,
    initial_capital: float = 100_000.0,
    taker_fee: float = 0.0005,
    slippage: float = 0.0002,
    periods_per_year: float | None = None,
) -> X4Result:
    """Run S6-XMOM: cross-sectional momentum rotation across an altcoin universe (§16).

    Every ``rebalance_days`` bars, rank the universe by vol-adjusted momentum (only symbols above
    their own ``regime_sma`` SMA) and hold equal weight in the ``top_k`` strongest, long-only; sit in
    cash when none qualify. Between rebalances the held basket rides. All curves must be aligned (same
    length, same timestamps). Turnover at each rebalance is charged ``taker_fee + slippage``.

    Captures the bull-market capital rotation (the user's point: 2024-style alt leadership) that a
    single-asset trend can't. Honest prior: alt tails are violent (line C breadth panel) and the edge
    concentrates in bull years -- the kill comparison is vs simply holding BTC's trend (S3).
    """

    from qount.x4.strategies import cross_sectional_rank

    syms = list(bars_by_sym)
    if not syms:
        raise ValueError("need >= 1 symbol")
    length = len(bars_by_sym[syms[0]])
    if any(len(bars_by_sym[s]) != length for s in syms):
        raise ValueError("all symbol bar lists must be aligned (same length)")
    closes = {s: [b.close for b in bars_by_sym[s]] for s in syms}

    held: dict[str, float] = {}
    cap = initial_capital
    fees_paid = 0.0
    rebalances = 0
    curve = [initial_capital]

    for t in range(1, length):
        if held:
            r = sum(w * (closes[s][t] / closes[s][t - 1] - 1.0)
                    for s, w in held.items() if closes[s][t - 1] > 0)
            cap *= 1.0 + r
        if t % rebalance_days == 0:
            top = cross_sectional_rank(closes, t, lookback=lookback, regime_sma=regime_sma, top_k=top_k)
            new = {s: 1.0 / len(top) for s in top} if top else {}
            turnover = sum(abs(new.get(s, 0.0) - held.get(s, 0.0)) for s in set(new) | set(held))
            cost = turnover * (taker_fee + slippage)
            fees_paid += cap * cost
            cap *= 1.0 - cost
            held = new
            rebalances += 1
        curve.append(cap)

    extra = {"rebalances": rebalances, "final_holdings": list(held)}
    return _result("S6-XMOM", curve, initial_capital, rebalances, fees_paid, 0.0,
                   periods_per_year, extra)


def run_trend_portfolio(
    bars_by_sym: dict[str, list[Bar]],
    *,
    fast: int = 20,
    slow: int = 100,
    regime_sma: int = 200,
    adx_min: float = 0.0,
    adx_period: int = 14,
    weighting: str = "inverse_vol",
    vol_lookback: int = 30,
    master_gate_sym: str | None = "BTCUSDT",
    master_gate_sma: int = 200,
    master_gate_slope: int = 0,
    breadth_gate: float | None = None,
    breadth_combine: str = "or",
    initial_capital: float = 100_000.0,
    taker_fee: float = 0.0005,
    slippage: float = 0.0002,
    vol_target: float = 0.03,
    max_leverage: float = 2.0,
    rebalance_band: float = 0.25,
    chandelier_mult: float = 0.0,
    chandelier_lookback: int = 22,
    dd_derisk_threshold: float = 0.0,
    dd_derisk_vol_target: float = 0.0,
    funding_by_sym: dict[str, Callable[[Bar], float]] | None = None,
    periods_per_year: float | None = None,
) -> X4Result:
    """S7-TREND-PORT: the §17 trend signal (S3) run per-symbol, risk-combined (§19).

    Not cross-sectional *selection* (§16.1 XMOM = falsified) but *diversification* of the one
    walk-forward-validated edge: each symbol gets its own long-only :class:`TrendFollow` sleeve (with a
    per-symbol ``regime_sma`` gate -> a coin in a downtrend sits flat), vol-parity sized. Sleeves are
    combined by ``weighting`` (default inverse-vol risk parity, computed on the *true* sleeve returns
    -- no look-ahead). An optional **master gate** (``master_gate_sym`` below its ``master_gate_sma``
    SMA) flattens the whole portfolio to cash that bar (BTC risk-off overlay). All bar lists must be
    aligned (same length). ``extra`` exposes per-sleeve curves + diagnostics.
    """

    from qount.x4.portfolio import combine
    from qount.x4.strategies import TrendFollow, sma_regime_mask, sma_slope_up_mask

    syms = list(bars_by_sym)
    if not syms:
        raise ValueError("need >= 1 symbol")
    length = len(bars_by_sym[syms[0]])
    if any(len(bars_by_sym[s]) != length for s in syms):
        raise ValueError("all symbol bar lists must be aligned (same length)")
    if master_gate_sym is not None and master_gate_sym not in bars_by_sym:
        raise ValueError(f"master_gate_sym {master_gate_sym!r} not in universe")

    sleeves: dict[str, list[float]] = {}
    fees_paid = 0.0
    trades = 0
    for s in syms:
        res = run_directional(
            bars_by_sym[s],
            TrendFollow(fast=fast, slow=slow, allow_short=False, regime_sma=regime_sma,
                        adx_min=adx_min, adx_period=adx_period),
            initial_capital=initial_capital, taker_fee=taker_fee, slippage=slippage,
            rebalance_band=rebalance_band, vol_target=vol_target, max_leverage=max_leverage,
            chandelier_mult=chandelier_mult, chandelier_lookback=chandelier_lookback,
            funding=(funding_by_sym.get(s) if funding_by_sym else None),
            periods_per_year=periods_per_year,
        )
        sleeves[s] = res.equity_curve
        fees_paid += res.fees_paid
        trades += res.trade_count

    port = combine(sleeves, scheme=weighting, vol_lookback=vol_lookback,
                   initial_capital=initial_capital)

    gate_active_frac = 1.0
    if master_gate_sym is not None or breadth_gate is not None:
        n = len(port)
        # BTC leader mask (all-on when no master gate)
        if master_gate_sym is not None:
            mc = [b.close for b in bars_by_sym[master_gate_sym]]
            btc_mask = sma_regime_mask(mc, master_gate_sma)
            if master_gate_slope > 0:  # T3-4: also require the SMA itself to be rising (slope confirm)
                slope_mask = sma_slope_up_mask(mc, master_gate_sma, master_gate_slope)
                btc_mask = [a and b for a, b in zip(btc_mask, slope_mask)]
        else:
            btc_mask = [True] * n
        # breadth mask: fraction of the universe above its own regime SMA >= threshold (§21.B)
        if breadth_gate is not None:
            per_coin = [sma_regime_mask([b.close for b in bars_by_sym[s]], regime_sma) for s in syms]
            breadth_mask = []
            for t in range(n):
                frac = sum(1 for m in per_coin if m[t]) / len(per_coin)
                breadth_mask.append(frac >= breadth_gate)
        else:
            breadth_mask = [True] * n

        if breadth_gate is None:
            mask = btc_mask
        elif master_gate_sym is None or breadth_combine == "breadth":
            mask = breadth_mask
        elif breadth_combine == "and":
            mask = [a and b for a, b in zip(btc_mask, breadth_mask)]
        else:  # "or" (default): risk-on if BTC up OR breadth broad -> avoids BTC dictatorship
            mask = [a or b for a, b in zip(btc_mask, breadth_mask)]

        gated = [initial_capital]
        active = 0
        for t in range(len(port) - 1):
            r = (port[t + 1] / port[t] - 1.0) if port[t] > 0 else 0.0
            if mask[t]:
                active += 1
            else:
                r = 0.0          # gate shut at bar t -> cash for the t -> t+1 step
            gated.append(gated[-1] * (1.0 + r))
        port = gated
        gate_active_frac = active / max(1, len(port) - 1)

    # T3-8 动态 vol_target: a portfolio-level exposure haircut while in drawdown. When the running
    # drawdown of the ridden curve exceeds ``dd_derisk_threshold``, scale the book's exposure by
    # ``dd_derisk_vol_target / vol_target`` (= cutting the vol target, e.g. 3%->2%) for the next step,
    # restoring full size once recovered. Causal (DD measured through bar t sets exposure for t->t+1).
    # Exposure ~0.5x sits below the max_leverage cap so a per-sleeve vt cut is ~linear -> this
    # portfolio-level multiplier faithfully approximates re-vol-targeting each sleeve (and is exactly
    # how you'd run it live: scale total deployment by a drawdown-based risk budget). 0 = off.
    derisk_active_frac = 0.0
    if dd_derisk_threshold > 0 and dd_derisk_vol_target > 0 and vol_target > 0:
        mult = min(1.0, dd_derisk_vol_target / vol_target)
        de = [port[0]]
        peak = port[0]
        derisked = 0
        for t in range(len(port) - 1):
            peak = max(peak, de[-1])
            dd = (de[-1] / peak - 1.0) if peak > 0 else 0.0
            r = (port[t + 1] / port[t] - 1.0) if port[t] > 0 else 0.0
            m = mult if -dd > dd_derisk_threshold else 1.0
            if m < 1.0:
                derisked += 1
            de.append(de[-1] * (1.0 + m * r))
        port = de
        derisk_active_frac = derisked / max(1, len(port) - 1)

    extra = {
        "sleeves": sleeves,
        "n_syms": len(syms),
        "weighting": weighting,
        "master_gate_sym": master_gate_sym,
        "gate_active_frac": gate_active_frac,
        "derisk_active_frac": derisk_active_frac,
    }
    return _result("S7-TREND-PORT", port, initial_capital, trades, fees_paid, 0.0,
                   periods_per_year, extra)


def run_scalper(
    bars: Sequence[Bar],
    strategy,
    *,
    initial_capital: float = 100_000.0,
    taker_fee: float = 0.0005,
    slippage: float = 0.0002,
    tp: float = 0.004,
    sl: float = 0.002,
    max_hold: int = 0,
    periods_per_year: float | None = None,
) -> X4Result:
    """Run a long-only impulse scalper with intrabar take-profit / stop ("见好就收"). Plan §11.

    ``strategy.on_bar(bar)`` emits an entry signal (``1.0`` = open long now, else ``0.0``). While flat,
    a signal opens a 1x long at the close. While in a position the driver checks **this bar's OHLC**:
    exit at the stop ``entry×(1−sl)`` if ``low`` touches it (checked first, pessimistic), else at the
    take-profit ``entry×(1+tp)`` if ``high`` touches it, else flat at the close after ``max_hold`` bars
    (0 = no timeout). Every fill pays ``taker_fee`` + adverse ``slippage`` — the whole point is to see
    if the burst clears the round-trip cost. ``extra`` reports trade count, wins, and win rate.
    """

    acct = X4Account(initial_capital=initial_capital, taker_fee=taker_fee, slippage=slippage)
    curve: list[float] = []
    in_pos = False
    entry_price = 0.0
    hold = 0
    wins = 0
    round_trips = 0

    for bar in bars:
        signal = strategy.on_bar(bar)
        if in_pos:
            hold += 1
            stop_px = entry_price * (1.0 - sl)
            tp_px = entry_price * (1.0 + tp)
            exit_px = None
            if bar.low <= stop_px:
                exit_px = stop_px          # pessimistic: a bar spanning both is assumed to stop first
            elif bar.high >= tp_px:
                exit_px = tp_px
            elif max_hold and hold >= max_hold:
                exit_px = bar.close
            if exit_px is not None:
                acct.trade(0.0, exit_px)   # close long
                round_trips += 1
                if exit_px > entry_price:
                    wins += 1
                in_pos = False
        elif signal > 0.0:
            acct.trade(acct.equity(bar.close) / bar.close, bar.close)  # 1x long at close
            in_pos = True
            entry_price = bar.close
            hold = 0
        curve.append(acct.equity(bar.close))

    extra = {"round_trips": round_trips, "wins": wins,
             "win_rate": wins / round_trips if round_trips else 0.0}
    return _result(getattr(strategy, "name", "scalper"), curve, initial_capital, acct.trade_count,
                   acct.fees_paid, acct.funding_pnl, periods_per_year, extra)
