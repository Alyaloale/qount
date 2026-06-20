"""X4 small-cap LIVE execution (线 D §21) — reconciliation-based, idempotent; spot OR leveraged perp.

Owner authorized a ~$415 (3000 RMB) live pilot of the small-cap S7-mini trend portfolio (7 liquid
coins — §21). v2 (博收益): switches to **USDⓈ-M perpetual at ``target_leverage`` (default 2x)** and
wires the §21.4 train+test-validated breadth-OR gate + correlation penalty into the live weights.

ISOLATION (守线 A 纪律):
  * REUSES only the generic ccxt client builder ``exchange_utils.build_exchange`` — it does NOT route
    through line A's ``Executor`` (frozen, ``QOUNT_LIVE_ENABLE=false`` invariant intact).
  * Own switch ``QOUNT_X4_LIVE_ENABLE`` (default off). Even when on, ``mode="dry"`` places no orders.

⚠️ LEVERAGE RISK (v2,真钱):
  * ``market_type="swap"`` + ``target_leverage=2.0`` → deployed NOTIONAL = capital × leverage, and the
    position **CAN be liquidated** (the old spot "cannot go negative" guarantee no longer holds).
    Doc §23: a leverage *cap* alone is inert (vol_target binds first), so the return only scales because
    deployment actually exceeds 100% — which also ~doubles the tail (in-sample maxDD −21% → ~−42%).
  * Hard caps still enforced: ``capital_usdt`` is the MARGIN ceiling; per-order ``max_order_usdt``.
    Long-only (trend), isolated margin (one coin's liquidation does not cascade).
  * Requires a Binance **Futures** API key (the spot-only pilot key cannot trade swap).

The pure functions (:func:`target_weights`, :func:`compute_orders`) are network-free and unit-tested;
the thin ccxt wrappers are mocked in tests. The forward-s7 paper track remains the performance
source-of-truth; this module only *tracks* the engine's target weights into real fills.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

from qount.x4.indicators import ATR  # vol-parity sizing: ATR(14) per coin (mirror run_directional)
from qount.x4.portfolio import correlation  # §21.4 D correlation penalty (reuse engine's helper)

# ---- a priori liquidity-tiered 7-coin small-cap universe (§21; data symbols, not ccxt) ----
SMALLCAP_UNIVERSE = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT")


def to_ccxt_symbol(data_sym: str, quote: str = "USDT", market_type: str = "spot") -> str:
    """``"BTCUSDT"`` -> ``"BTC/USDT"`` (spot) or ``"BTC/USDT:USDT"`` (USDⓈ-M swap). ccxt unified."""
    if not data_sym.endswith(quote):
        raise ValueError(f"{data_sym!r} does not end with quote {quote!r}")
    sym = f"{data_sym[: -len(quote)]}/{quote}"
    return f"{sym}:{quote}" if market_type == "swap" else sym


@dataclass(frozen=True)
class LiveConfig:
    """Small-cap live config. ``capital_usdt`` is a HARD total ceiling enforced in code."""

    universe: tuple[str, ...] = SMALLCAP_UNIVERSE
    capital_usdt: float = 415.0          # MARGIN ceiling (3000 RMB ≈ $415); notional = this × leverage
    quote: str = "USDT"
    rebalance_band: float = 0.25         # skip a leg if |target-current| < band×max(target,current)
    min_order_usdt: float = 6.0          # skip dust below ~Binance MIN_NOTIONAL ($5) + margin
    max_order_usdt: float = 830.0        # per-order safety cap (= capital × default 2x)
    # --- v2 博收益: vol-parity sized USDⓈ-M perp (FAITHFUL to the validated engine; ⚠️ liquidation) ---
    market_type: str = "swap"            # "spot" = cash 1x (旧,不可强平) | "swap" = USDⓈ-M 永续
    vol_target: float = 0.03             # §23 博收益档 (vt3 = validated +135%/−30%); per-coin risk target
    max_leverage: float = 2.0            # CAP on per-coin scale = min(max_lev, vol_target/atr_pct)
    atr_lookback: int = 14               # ATR window for vol-parity (= run_directional default)
    margin_mode: str = "isolated"        # 逐仓:单币强平不连坐其余腿
    # 盘中硬止损 (intraday Chandelier): trailing stop on the 10-min LIVE price. Backtest (TOP7
    # 2021-26) showed a TIGHT stop (3×ATR) costs ~44pp return by whipsawing trends with no stable
    # optimum -- so this is set WIDE (8×ATR ≈ −28% from the peak) = a DISASTER/liquidation safeguard
    # only (well inside the 2x −50% liq), ≈neutral on return (+165%/0.99) but pre-empts an intraday
    # crash before the daily-close exit. NOT a return optimizer. 0 disables.
    chandelier_mult: float = 8.0         # stop = trailing_high − mult × ATR(chandelier_lookback)
    chandelier_lookback: int = 22
    # S7-mini signal params (§21 deployable; slow 100->60 per §24 train/test re-optimization:
    # the slow MA was the one un-swept core factor — faster slow MA enters crypto trends earlier,
    # a broad robust plateau (slow 40-70 beats baseline both train+test), total +142->+173%,
    # Sharpe 0.91->1.07, maxDD -28->-26%, train 0.78->1.00. fast=20 already optimal.)
    fast: int = 20
    slow: int = 60
    regime_sma: int = 200
    vol_lookback: int = 30               # inverse-vol weight window (= engine combine vol_lookback)
    gate_sym: str = "BTCUSDT"
    gate_sma: int = 200
    # --- §24 做空闸 (short gate): when the master gate is SHUT (real bear), instead of 100% cash,
    # open a mirror SHORT book on coins in a confirmed downtrend (close < SMA``short_regime_sma`` AND
    # SMA``fast`` < SMA``slow``), inverse-vol sized. Risk-off short is FREE additive return (the long is
    # in cash then). Validated OOS-robust (§24): short risk-off compound +20%/train +18%/test across a
    # plateau; total +142->+246%. ⚠️ NOT a tail hedge (maxDD ~2pp deeper); it's a return knob. Default
    # OFF — flipping to True is owner's deliberate arm step (after paper). short_regime_sma=100 (NOT the
    # long's 200): a short must engage the downtrend earlier. Smaller size + tighter stop (squeeze tail).
    short_gate: bool = False
    short_regime_sma: int = 100
    short_vol_target: float = 0.03       # owner 2026-06-19: 0.02->0.03 抬空书 gross ~0.40->~0.60 (上限给到
                                         # 0.6). vt 是 binding 旋钮 (short_max_leverage cap 1.5 inert,不 bind).
                                         # 回测:拼账 +246->+312%/Sharpe 1.17->1.23/train+test 双升/maxDD ~1pp 深.
    short_max_leverage: float = 1.5      # per-coin scale cap; inert at vt0.03 (无币 scale 触顶 -> 不动)
    short_chandelier_mult: float = 3.0
    # --- §21.4 train+test-validated enhancements (此前未接进 live;只改善 chop/熊 regime,牛市中性) ---
    breadth_gate: float | None = 0.5     # risk-on if BTC gate OR ≥50% of universe above its regime_sma
    breadth_combine: str = "or"          # "or" (默认,§21.B) | "and" | "breadth"
    corr_penalty: bool = True            # §21.D: inverse-vol ÷ max(avg pairwise corr, corr_floor)
    corr_floor: float = 0.2
    # --- T2-2 交易所原生兜底止损: a resting reduce-only STOP_MARKET parked on the exchange at the
    # Chandelier level, so an intraday crash that gaps through it BETWEEN the 10-min cron runs is
    # closed by the exchange (not only on the next poll). Tracks the trail up via cancel+replace,
    # debounced by ``stop_amend_band``. Swap only (perp). ``exchange_stops=False`` tears them down. ---
    exchange_stops: bool = True
    stop_amend_band: float = 0.01        # only move the resting stop if the trigger shifts >1% (no churn)
    # --- §10 partial scale-out (分批止盈 / 锁利): as an OPEN position runs into profit, ratchet DOWN its
    # target weight by ``scale_out_frac`` every ``scale_out_step`` of open profit (fraction of entry),
    # flooring at ``scale_out_residual`` of full size; the residual rides the Chandelier. Ratcheted (a
    # retrace never re-adds) -> books partial profit on a winner so a +100% trend doesn't give back 28%
    # before the wide stop. Validated LONG-side (§10, x4_profit_taking.py): Sharpe 0.91->1.00, maxDD
    # -28%->-22%, train/test both hold, at the cost of ~18pp total return = a giveback / risk-adjusted
    # knob (NOT pure alpha). Symmetric -> also applies to a held SHORT leg (mechanism direction-agnostic,
    # though the short side wasn't separately validated). Default OFF (byte-identical) -- arming via
    # QOUNT_X4_SCALE_OUT is owner's deliberate step. Recommended armed档: step0.20/frac0.50/residual0.34.
    scale_out_step: float = 0.0          # open-profit fraction between successive partial scale-outs (0=off)
    scale_out_frac: float = 0.0          # fraction of full size trimmed at each step
    scale_out_residual: float = 0.0      # floor fraction always kept (residual rides the stop)


@dataclass(frozen=True)
class TargetWeight:
    symbol: str   # data symbol e.g. "BTCUSDT"
    weight: float


@dataclass(frozen=True)
class SymbolFilter:
    """Per-symbol exchange constraints (from ccxt ``market``)."""

    amount_step: float       # LOT_SIZE stepSize (base precision increment)
    min_amount: float        # LOT_SIZE minQty
    min_notional: float      # MIN_NOTIONAL (quote)


@dataclass(frozen=True)
class Order:
    symbol: str              # ccxt symbol e.g. "BTC/USDT"
    side: str                # "buy" | "sell"
    base_amount: float       # rounded base qty (used for SELL and for est)
    quote_amount: float      # USDT to spend (used for market BUY via quoteOrderQty)
    est_usdt: float
    reason: str = ""
    reduce_only: bool = False   # swap: True iff this order REDUCES |position| (close long / cover short)
                                # -> reduceOnly param; opening/increasing a short is a non-reduceOnly SELL


@dataclass
class ReconcileResult:
    orders: list[Order] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    target_usdt: dict[str, float] = field(default_factory=dict)
    current_usdt: dict[str, float] = field(default_factory=dict)
    gate_open: bool = True


# ----------------------------- pure target-weight derivation -----------------------------

def _sma(xs: list[float], n: int) -> float:
    return sum(xs[-n:]) / n


def gate_is_open(closes: list[float], gate_sma: int) -> bool:
    """BTC master gate: last close above its ``gate_sma`` SMA (warm-up -> shut)."""
    if len(closes) < gate_sma:
        return False
    return closes[-1] > _sma(closes, gate_sma)


def usdt_wallet_balance(bal: dict) -> float | None:
    """USDⓈ-M **walletBalance** (cash incl. realized PnL/funding/fees, EXCLUDING open-position
    unrealized MTM) from a ccxt ``fetch_balance`` result — the correct sizing/equity base.

    ⚠️ ccxt ``balance['USDT']['total']`` on USDⓈ-M is the **marginBalance** (= walletBalance +
    unrealized): using it as ``capital`` and then adding unrealized again DOUBLE-counts the open
    profit (inflates equity & total PnL ≈ 2× when unrealized is large). So prefer Binance
    ``info.totalWalletBalance``; fall back to ``total − totalUnrealizedProfit``, else ``total``.
    None if unreadable (caller refuses to trade against an unknown balance)."""

    info = bal.get("info") or {}
    # Binance USDⓈ-M: marginBalance = walletBalance + unrealized. 最可靠的做法是
    # 用 USDT.total(=marginBalance) − totalUnrealizedProfit 得到真正的 walletBalance;
    # 这比直接用 totalWalletBalance 更稳(某些账户/模式下 totalWalletBalance 会混进未实现)。
    u = bal.get("USDT") or {}
    t = u.get("total")
    upnl = info.get("totalUnrealizedProfit")
    if t not in (None, "") and upnl not in (None, ""):
        try:
            return float(t) - float(upnl)
        except (TypeError, ValueError):
            pass
    w = info.get("totalWalletBalance")
    if w not in (None, ""):
        try:
            return float(w)
        except (TypeError, ValueError):
            pass
    if t in (None, ""):
        return None
    try:
        return float(t)
    except (TypeError, ValueError):
        return None


def portfolio_gate_open(bars_by_sym: dict[str, list], cfg: LiveConfig) -> bool:
    """Risk-on/off gate: BTC master gate, optionally OR'd with a breadth gate (§21.4 B, validated).

    ``breadth`` = fraction of the universe trading above its own ``regime_sma`` SMA. With
    ``breadth_combine='or'`` (default) the book is risk-on if **BTC is above its 200d SMA OR breadth
    is broad** — so a sideways BTC no longer dictates 100% cash while the alt-universe trends
    (lifts the chop/bear regime in train+test, bull-neutral). 'and'/'breadth' also supported."""

    gate_bars = bars_by_sym.get(cfg.gate_sym)
    if gate_bars is None:
        return False
    btc_on = gate_is_open([b.close for b in gate_bars], cfg.gate_sma)
    if cfg.breadth_gate is None:
        return btc_on
    masks = []
    for s in cfg.universe:
        bars = bars_by_sym.get(s)
        if not bars:
            continue
        c = [b.close for b in bars]
        if len(c) >= cfg.regime_sma:
            masks.append(c[-1] > _sma(c, cfg.regime_sma))
    breadth_on = bool(masks) and (sum(masks) / len(masks)) >= cfg.breadth_gate
    if cfg.breadth_combine == "breadth":
        return breadth_on
    if cfg.breadth_combine == "and":
        return btc_on and breadth_on
    return btc_on or breadth_on  # "or" (default)


def _coin_windows_scales(bars_by_sym: dict[str, list], cfg: LiveConfig, trend_filter: bool,
                         short: bool = False
                         ) -> tuple[dict[str, list[float]], dict[str, float]]:
    """Per-coin return window (last ``vol_lookback`` daily rets) + vol-parity ``scale`` =
    ``min(max_leverage, vol_target / atr_pct)``. ``trend_filter`` keeps only coins held by the signal;
    False keeps the whole universe.

    ``short=False`` (long, §21): held iff close > SMA``regime_sma`` AND SMA``fast`` > SMA``slow``; scale
    uses ``vol_target``/``max_leverage``. ``short=True`` (§24 做空闸 mirror): held iff close <
    SMA``short_regime_sma`` AND SMA``fast`` < SMA``slow`` (confirmed downtrend, earlier regime window);
    scale uses the smaller ``short_vol_target``/``short_max_leverage``."""

    regime_sma = cfg.short_regime_sma if short else cfg.regime_sma
    vol_target = cfg.short_vol_target if short else cfg.vol_target
    max_leverage = cfg.short_max_leverage if short else cfg.max_leverage
    windows: dict[str, list[float]] = {}
    scale: dict[str, float] = {}
    need = max(regime_sma, cfg.slow, cfg.vol_lookback + 1, cfg.atr_lookback + 1)
    for s in cfg.universe:
        bars = bars_by_sym.get(s)
        if not bars:
            continue
        c = [b.close for b in bars]
        if len(c) < need:
            continue
        if trend_filter:
            up = c[-1] > _sma(c, regime_sma) and _sma(c, cfg.fast) > _sma(c, cfg.slow)
            down = c[-1] < _sma(c, regime_sma) and _sma(c, cfg.fast) < _sma(c, cfg.slow)
            if not (down if short else up):
                continue
        windows[s] = [c[i] / c[i - 1] - 1.0 for i in range(len(c) - cfg.vol_lookback, len(c))]
        atr = ATR(cfg.atr_lookback)
        a = None
        for b in bars:
            a = atr.update(b)
        atr_pct = (a / c[-1]) if (a is not None and c[-1] > 0) else None
        scale[s] = min(max_leverage, vol_target / atr_pct) if (atr_pct and atr_pct > 0) else 0.0
    return windows, scale


def _inverse_vol_parity(windows: dict[str, list[float]], scale: dict[str, float],
                        cfg: LiveConfig) -> dict[str, float]:
    """Inverse-volatility *relative* weights over ``windows`` (1/σ, + §21.4 D correlation penalty,
    normalized to sum 1) each × its vol-parity ``scale`` -> **absolute** exposure weights (sum = gross,
    NOT 1). Shared by the live target book and the small-capital reachability estimate so both use the
    identical (non-equal) weighting."""

    raw: dict[str, float] = {}
    for s, rets in windows.items():
        mu = sum(rets) / len(rets)
        vol = (sum((x - mu) ** 2 for x in rets) / (len(rets) - 1)) ** 0.5 if len(rets) > 1 else 0.0
        raw[s] = (1.0 / vol) if vol > 0 else 0.0
    if not raw:
        return {}
    # §21.4 D correlation penalty: down-weight coins correlated with the rest (floored, no blow-up)
    if cfg.corr_penalty and len(raw) > 1:
        names = list(raw)
        penalized = {}
        for n in names:
            cs = [correlation(windows[n], windows[m]) for m in names if m != n]
            avg_corr = sum(cs) / len(cs) if cs else 0.0
            penalized[n] = raw[n] / max(avg_corr, cfg.corr_floor)
        raw = penalized
    tot = sum(raw.values())
    rel = {s: (raw[s] / tot if tot > 0 else 1.0 / len(raw)) for s in raw}  # inverse-vol weight, Σ=1
    return {s: rel[s] * scale[s] for s in raw}   # absolute exposure = rel × per-coin scale


def target_weights(bars_by_sym: dict[str, list], cfg: LiveConfig) -> list[TargetWeight]:
    """Today's S7-mini target weights — mirrors ``x4_paper._held_coins`` / the §19 engine + §21.4 D.

    Risk-on per :func:`portfolio_gate_open`. Then per coin held iff (close > SMA``regime_sma``) AND
    (SMA``fast`` > SMA``slow``). Held coins get an inverse-volatility parity *relative* weight (1/σ of
    the last ``vol_lookback`` daily returns; optional §21.4 D correlation penalty), normalized to sum 1.

    Each relative weight is then multiplied by the coin's **vol-parity scale**
    ``min(max_leverage, vol_target / atr_pct)`` (ATR``atr_lookback`` as a fraction of price) — IDENTICAL
    to the engine's :func:`run_directional` sizing, so the live deployed exposure matches the validated
    backtest (≈0.5x gross in normal crypto vol, capped at ``max_leverage``) instead of a naive full
    notional. The returned ``weight`` is the coin's **absolute exposure fraction of capital** (the list
    no longer sums to 1). Empty -> 100% cash; a coin in ATR warm-up gets scale 0 (flat, no look-ahead)."""

    if not portfolio_gate_open(bars_by_sym, cfg):
        if not cfg.short_gate:
            return []                       # §21 default: risk-off -> 100% cash
        # §24 做空闸: risk-off -> mirror SHORT book on coins in a confirmed downtrend (NEGATIVE weights)
        windows, scale = _coin_windows_scales(bars_by_sym, cfg, trend_filter=True, short=True)
        return [TargetWeight(s, -w) for s, w in _inverse_vol_parity(windows, scale, cfg).items()]
    windows, scale = _coin_windows_scales(bars_by_sym, cfg, trend_filter=True)
    return [TargetWeight(s, w) for s, w in _inverse_vol_parity(windows, scale, cfg).items()]


def natural_weights(bars_by_sym: dict[str, list], cfg: LiveConfig) -> dict[str, float]:
    """Each coin's inverse-vol × vol-parity **absolute** weight assuming the WHOLE universe is held
    (ignores the trend/gate membership filter) — the coin's *typical* allocation when in the book, and
    the max-dilution (most conservative) case. Used by :func:`unreachable_coins` to judge small-capital
    reachability with the REAL (non-equal) weighting rather than a 1/n proxy."""

    windows, scale = _coin_windows_scales(bars_by_sym, cfg, trend_filter=False)
    return _inverse_vol_parity(windows, scale, cfg)


def _atr_last(bars: list, lookback: int) -> float | None:
    """Trailing ATR(lookback) at the last bar (absolute price units), or None until warm."""
    if len(bars) <= lookback:
        return None
    atr = ATR(lookback)
    a = None
    for b in bars:
        a = atr.update(b)
    return a


def apply_chandelier_stops(
    targets: list[TargetWeight],
    live_prices: dict[str, float],       # data_sym -> current LIVE price (intraday)
    daily_bars: dict[str, list],         # data_sym -> daily bars (for ATR)
    stop_state: dict[str, dict],         # persisted {sym: {"trail_high": float} | {"latched": True}}
    cfg: LiveConfig,
) -> tuple[list[TargetWeight], dict[str, dict], list[str]]:
    """Intraday trailing-Chandelier overlay on the daily target weights (盘中硬止损), **side-aware**.

    LONG leg (weight>0): ratchet a trailing high from the LIVE price; if it falls to
    ``trail_high − chandelier_mult × ATR`` force flat + **latch**. SHORT leg (weight<0, §24 做空闸): the
    mirror — ratchet a trailing low; if the price RISES to ``trail_low + short_chandelier_mult × ATR``
    (a squeeze) force flat + latch. Latched until the daily signal drops the coin (mirrors
    :func:`run_directional`'s ``ch_latched``). The short uses the tighter ``short_chandelier_mult`` (the
    squeeze right-tail is sharper). A side whose mult≤0 is left unmanaged. Returns (adjusted targets,
    new state, triggered syms)."""

    if cfg.chandelier_mult <= 0 and cfg.short_chandelier_mult <= 0:
        return targets, stop_state, []
    new_state: dict[str, dict] = {}
    triggered: list[str] = []
    adjusted: list[TargetWeight] = []
    for t in targets:
        s, px = t.symbol, live_prices.get(t.symbol)
        prev = stop_state.get(s, {})
        if prev.get("latched"):           # already stopped this trend -> stay flat until signal resets
            adjusted.append(TargetWeight(s, 0.0))
            new_state[s] = {"latched": True}
            continue
        if t.weight == 0 or px is None:
            adjusted.append(t)
            continue
        atr = _atr_last(daily_bars.get(s, []), cfg.chandelier_lookback)
        if t.weight > 0:                  # LONG: trail high, stop on a fall
            if cfg.chandelier_mult <= 0:
                adjusted.append(t)
                continue
            trail_high = max(prev.get("trail_high", px), px)
            if atr is not None and px <= trail_high - cfg.chandelier_mult * atr:
                triggered.append(s)
                adjusted.append(TargetWeight(s, 0.0))
                new_state[s] = {"latched": True}
            else:
                adjusted.append(t)
                new_state[s] = {"trail_high": trail_high}
        else:                             # SHORT: trail low, stop on a squeeze (rise)
            if cfg.short_chandelier_mult <= 0:
                adjusted.append(t)
                continue
            trail_low = min(prev.get("trail_low", px), px)
            if atr is not None and px >= trail_low + cfg.short_chandelier_mult * atr:
                triggered.append(s)
                adjusted.append(TargetWeight(s, 0.0))
                new_state[s] = {"latched": True}
            else:
                adjusted.append(t)
                new_state[s] = {"trail_low": trail_low}
    # coins not in `targets` (daily signal already dropped them) fall out of new_state -> latch cleared
    return adjusted, new_state, triggered


def apply_scale_out(
    targets: list[TargetWeight],
    live_prices: dict[str, float],          # data_sym -> current LIVE price (intraday)
    entry_prices: dict[str, float | None],  # data_sym -> avg entry of the current position (None if flat)
    positions_base: dict[str, float],       # data_sym -> SIGNED current position (+long / −short, base units)
    so_state: dict[str, dict],              # persisted {sym: {"steps": int}}
    cfg: LiveConfig,
) -> tuple[list[TargetWeight], dict[str, dict], list[str]]:
    """§10 partial scale-out (分批止盈): cap each target weight by a **ratcheted** partial profit-take.

    For an OPEN position held in the SAME direction as today's target, measure open profit as a fraction
    of the average entry; every ``scale_out_step`` of profit permanently trims ``scale_out_frac`` of full
    size, flooring at ``scale_out_residual`` (the residual keeps riding the Chandelier). Ratcheted: steps
    only go UP, so a retrace never re-adds (state persisted across the 10-min cron in ``scale_out.json``).
    A flat / freshly-entered / opposite-side leg gets its full target and its state reset (it falls out of
    the returned state). Mirrors :func:`run_directional`'s scale-out; OFF when either knob is 0
    (byte-identical). Returns (adjusted targets, new state, syms that took a new scale-out step)."""

    if cfg.scale_out_step <= 0 or cfg.scale_out_frac <= 0:
        return targets, so_state, []
    new_state: dict[str, dict] = {}
    scaled: list[str] = []
    adjusted: list[TargetWeight] = []
    for t in targets:
        s = t.symbol
        px = live_prices.get(s)
        entry = entry_prices.get(s)
        pos = positions_base.get(s, 0.0)
        same_side = abs(pos) > 0 and (pos > 0) == (t.weight > 0)
        if not (t.weight != 0.0 and px and entry and entry > 0 and same_side):
            adjusted.append(t)                 # flat / fresh / opposite / unknown entry -> full, reset
            continue
        prof = ((px - entry) if t.weight > 0 else (entry - px)) / entry
        prev = int(so_state.get(s, {}).get("steps", 0))
        steps = max(prev, int(prof // cfg.scale_out_step)) if prof > 0 else prev
        if steps > prev:
            scaled.append(s)
        new_state[s] = {"steps": steps}
        cap = max(cfg.scale_out_residual, 1.0 - steps * cfg.scale_out_frac)
        adjusted.append(TargetWeight(s, t.weight * cap))
    return adjusted, new_state, scaled


# ------------------- T2-2: exchange-native resting STOP_MARKET backstop -------------------

@dataclass(frozen=True)
class StopOrder:
    symbol: str          # ccxt symbol e.g. "BTC/USDT:USDT"
    stop_price: float    # trigger price
    reason: str = ""
    side: str = "sell"   # "sell" closes a long / "buy" covers a short (closePosition=True)


@dataclass(frozen=True)
class StopCancel:
    order_id: str
    symbol: str          # ccxt symbol (binance cancel_order needs it)


@dataclass
class StopOrderPlan:
    to_place: list[StopOrder] = field(default_factory=list)
    to_cancel: list[StopCancel] = field(default_factory=list)


def chandelier_stop_prices(targets: list[TargetWeight], daily_bars: dict[str, list],
                           stop_state: dict[str, dict], cfg: LiveConfig) -> dict[str, float]:
    """The intraday Chandelier stop trigger price per held coin, using the trail
    :func:`apply_chandelier_stops` just persisted (call AFTER it, with the adjusted targets + state).
    LONG (weight>0): ``trail_high − chandelier_mult × ATR`` (a fall). SHORT (weight<0, §24):
    ``trail_low + short_chandelier_mult × ATR`` (a squeeze). Latched / flat / ATR-warm-up / disabled-side
    coins yield no price. Feeds the exchange-native resting STOP_MARKET (the local stop fires only on the
    next 10-min run)."""

    out: dict[str, float] = {}
    for t in targets:
        atr = _atr_last(daily_bars.get(t.symbol, []), cfg.chandelier_lookback)
        if atr is None:
            continue
        st = stop_state.get(t.symbol) or {}
        if t.weight > 0 and cfg.chandelier_mult > 0:
            trail_high = st.get("trail_high")
            if trail_high is not None:
                out[t.symbol] = trail_high - cfg.chandelier_mult * atr
        elif t.weight < 0 and cfg.short_chandelier_mult > 0:
            trail_low = st.get("trail_low")
            if trail_low is not None:
                out[t.symbol] = trail_low + cfg.short_chandelier_mult * atr
    return out


def plan_stop_orders(stop_prices: dict[str, float], positions_base: dict[str, float],
                     existing: dict[str, dict], cfg: LiveConfig) -> StopOrderPlan:
    """Idempotent diff of the DESIRED resting stops vs the ones already on the exchange.

    ``stop_prices``: {data_sym: trigger px} from :func:`chandelier_stop_prices`. ``positions_base``:
    {data_sym: SIGNED base held} — only coins we ACTUALLY hold get a protective stop; a long (>0) gets a
    SELL stop, a short (<0) a BUY stop (§24). ``existing``: {data_sym: {"id","symbol","stopPrice"}} from
    :func:`fetch_open_stops`. A stop is (re)placed only when there is none yet OR the trigger moved more
    than ``stop_amend_band`` (the trail ratchets, so the resting stop must follow) — within band is left
    untouched (no churn). Coins no longer held / latched / gate-shut (absent from desired) have their
    stale stop cancelled. Swap only; ``exchange_stops=False`` desires nothing (existing stops torn down)."""

    plan = StopOrderPlan()
    if cfg.market_type != "swap":
        return plan
    use = stop_prices if cfg.exchange_stops else {}
    desired = {s: px for s, px in use.items() if positions_base.get(s, 0.0) != 0 and px > 0}
    for s, px in desired.items():
        sym = to_ccxt_symbol(s, cfg.quote, cfg.market_type)
        side = "sell" if positions_base.get(s, 0.0) > 0 else "buy"   # close long / cover short
        ex = existing.get(s)
        if ex is None:
            plan.to_place.append(StopOrder(sym, px, reason="arm stop", side=side))
            continue
        old = ex.get("stopPrice")
        if old is None or abs(px - old) > cfg.stop_amend_band * max(abs(old), 1e-9):
            plan.to_cancel.append(StopCancel(ex["id"], ex.get("symbol", sym)))
            plan.to_place.append(StopOrder(sym, px, reason=f"trail {old}->{px:.6g}", side=side))
    for s, ex in existing.items():
        if s not in desired:
            sym = to_ccxt_symbol(s, cfg.quote, cfg.market_type)
            plan.to_cancel.append(StopCancel(ex["id"], ex.get("symbol", sym)))
    return plan


# ----------------------------- pure order reconciliation -----------------------------

def _round_down_step(amount: float, step: float) -> float:
    if step <= 0:
        return amount
    return math.floor(amount / step + 1e-9) * step


def compute_orders(
    targets: list[TargetWeight],
    balances_base: dict[str, float],   # data_sym -> base units currently held
    prices: dict[str, float],          # data_sym -> last price (quote per base)
    filters: dict[str, SymbolFilter],  # data_sym -> exchange filter
    cfg: LiveConfig,
) -> ReconcileResult:
    """Diff **signed** target dollar allocations vs current holdings into band-gated, capped, lot-rounded
    orders. ``balances_base`` is signed (``+`` long / ``−`` short on swap).

    ``targets`` carry **absolute** exposure fractions of capital (vol-parity sized; negative = §24 short
    book), so ``target_notional = weight × capital_usdt`` directly (NO renormalization). Gross is the sum
    of |exposure|, clamped defensively to ``max_leverage × capital_usdt``. Each leg trades toward its
    signed target: ``diff>0``→BUY (cover short / open-or-add long), ``diff<0``→SELL (reduce long /
    open-or-add short). ``reduce_only`` is set when the order moves |position| toward zero WITHOUT
    crossing — opening/increasing a short is a non-reduceOnly SELL, covering is a reduceOnly BUY. Shorting
    is swap-only: on spot a SELL is clamped to holdings (no naked short). Idempotent within
    ``rebalance_band``."""

    res = ReconcileResult(gate_open=bool(targets))
    tw = {t.symbol: t.weight for t in targets}
    swap = cfg.market_type == "swap"
    # defensive clamp only: scale down proportionally if total GROSS (|long|+|short|) exceeds the cap
    gross = sum(abs(w) for w in tw.values())
    cap = cfg.max_leverage
    if gross > cap and gross > 0:
        tw = {s: w * cap / gross for s, w in tw.items()}
    # per-order deployment cap = the smaller of the configured ceiling and this account's buying power
    # (capital × leverage); shrinks with a smaller live capital rather than staying a stale backstop.
    order_cap = min(cfg.max_order_usdt, cfg.capital_usdt * max(cfg.max_leverage, 1.0))

    universe = list(dict.fromkeys(list(cfg.universe) + list(balances_base)))
    for s in universe:
        px = prices.get(s, 0.0)
        cur_usdt = balances_base.get(s, 0.0) * px           # signed
        tgt_usdt = tw.get(s, 0.0) * cfg.capital_usdt        # signed
        res.target_usdt[s] = tgt_usdt
        res.current_usdt[s] = cur_usdt
        diff = tgt_usdt - cur_usdt
        denom = max(abs(tgt_usdt), abs(cur_usdt), 1e-9)

        # band gate: leave small deviations alone (no churn) — but never skip a full exit (tgt=0)
        if abs(diff) < cfg.rebalance_band * denom and tgt_usdt != 0:
            res.skipped.append(f"{s}: within band ({cur_usdt:.2f}->{tgt_usdt:.2f})")
            continue
        if abs(diff) < cfg.min_order_usdt:
            res.skipped.append(f"{s}: below min_order ({diff:+.2f} USDT)")
            continue
        if px <= 0 or s not in filters:
            res.skipped.append(f"{s}: no price/filter")
            continue

        f = filters[s]
        if diff > 0:   # BUY: cover short and/or open-or-add long
            spend = min(diff, order_cap)
            if spend < max(cfg.min_order_usdt, f.min_notional):
                res.skipped.append(f"{s}: buy {spend:.2f} below notional floor")
                continue
            est_base = _round_down_step(spend / px, f.amount_step)
            if est_base < f.min_amount or est_base <= 0:
                res.skipped.append(f"{s}: buy base {est_base} below min_amount")
                continue
            # reduceOnly iff purely covering a short without crossing into a long
            reduce_only = swap and cur_usdt < 0 and (cur_usdt + spend) <= 1e-9
            res.orders.append(Order(to_ccxt_symbol(s, cfg.quote, cfg.market_type), "buy", est_base,
                                    round(spend, 2), round(spend, 2),
                                    reason=f"{'cover' if cur_usdt < 0 else 'deploy'} {cur_usdt:.0f}->{tgt_usdt:.0f}",
                                    reduce_only=reduce_only))
        else:          # SELL: reduce long and/or open-or-add short (swap)
            sell_usdt = min(-diff, order_cap)
            base_amt = _round_down_step(sell_usdt / px, f.amount_step)
            if not swap:   # spot: no naked short — never sell more than held
                base_amt = min(base_amt, _round_down_step(max(balances_base.get(s, 0.0), 0.0), f.amount_step))
            if base_amt < f.min_amount or base_amt * px < max(cfg.min_order_usdt, f.min_notional):
                res.skipped.append(f"{s}: sell {base_amt} below notional/min floor")
                continue
            # reduceOnly iff purely reducing a long without crossing into a short
            reduce_only = swap and cur_usdt > 0 and (cur_usdt - base_amt * px) >= -1e-9
            opening_short = tgt_usdt < cur_usdt <= 0 or tgt_usdt < 0 <= cur_usdt
            res.orders.append(Order(to_ccxt_symbol(s, cfg.quote, cfg.market_type), "sell", base_amt,
                                    0.0, round(base_amt * px, 2),
                                    reason=f"{'short' if opening_short else 'reduce'} {cur_usdt:.0f}->{tgt_usdt:.0f}",
                                    reduce_only=reduce_only))
    return res


def unreachable_coins(bars_by_sym: dict[str, list], prices: dict[str, float],
                      filters: dict[str, SymbolFilter], cfg: LiveConfig,
                      held: set[str] | None = None) -> list[dict]:
    """Universe coins whose **real** inverse-vol × vol-parity target notional (when held alongside the
    full universe, :func:`natural_weights`) falls below the exchange MIN order — they'd be skipped as
    dust, so on a small capital the live book is a concentrated subset (honest caveat, not a bug).

    NOT equal-weight: it uses the actual (non-uniform) inverse-vol weighting, so e.g. at $115 BTC's
    larger inverse-vol share still only targets ~$18 < its ~$65 min, and ETH/LINK/ADA also fall short
    — only BNB/SOL/XRP clear their floors. Returns ``[{"symbol","min_usdt","target_usdt"}]`` sorted by
    shortfall (worst first).

    ``held`` (symbols with a current non-zero position) are EXCLUDED: a coin already in the book isn't
    "skipped/missing" — it sits at one min-lot, just slightly above its sub-floor target (granularity
    overshoot, e.g. BTC held at $63 lot vs a $59 target). Flagging it made the dashboard claim a "非完整
    7 币" subset while all 7 were in fact held."""

    nat = natural_weights(bars_by_sym, cfg)
    held = held or set()
    out: list[dict] = []
    for s in cfg.universe:
        f = filters.get(s)
        px = prices.get(s, 0.0)
        if not f or px <= 0 or s not in nat or s in held:
            continue
        floor = max(f.min_amount * px, f.min_notional, cfg.min_order_usdt)
        tgt = nat[s] * cfg.capital_usdt
        if tgt < floor:
            out.append({"symbol": s, "min_usdt": round(floor, 1), "target_usdt": round(tgt, 1)})
    return sorted(out, key=lambda d: d["target_usdt"] - d["min_usdt"])


def x4_live_enabled() -> bool:
    """Line-D-only live switch (independent of line A's ``QOUNT_LIVE_ENABLE``)."""
    return os.environ.get("QOUNT_X4_LIVE_ENABLE", "").lower() in ("1", "true", "yes")


# ----------------------------- thin ccxt layer (mocked in tests) -----------------------------

def fetch_filters(exchange, data_syms: list[str], quote: str = "USDT",
                  market_type: str = "spot") -> dict[str, SymbolFilter]:
    """Pull LOT_SIZE / MIN_NOTIONAL from loaded ccxt markets (spot or swap)."""
    if not getattr(exchange, "markets", None):
        exchange.load_markets()
    out: dict[str, SymbolFilter] = {}
    for s in data_syms:
        m = exchange.markets.get(to_ccxt_symbol(s, quote, market_type))
        if not m:
            continue
        limits = m.get("limits", {})
        prec = m.get("precision", {})
        amt = prec.get("amount")
        step = (10 ** -amt) if isinstance(amt, int) else float(amt or 0.0) or 1e-8
        out[s] = SymbolFilter(
            amount_step=step,
            min_amount=float((limits.get("amount") or {}).get("min") or 0.0),
            min_notional=float((limits.get("cost") or {}).get("min") or 0.0),
        )
    return out


def prepare_swap(exchange, data_syms: list[str], cfg: LiveConfig) -> set[str]:
    """Set isolated margin + ``max_leverage`` per swap symbol, then VERIFY by reading back the live
    leverage. Returns the set of data symbols whose leverage could **not be confirmed** at
    ``max_leverage`` — the caller MUST refuse to trade those.

    Why verify (真钱关键): ``set_leverage`` can fail silently (API hiccup, an already-open position,
    a re-set error) and Binance defaults a fresh symbol to **20x** — so a "2x" strategy that trusts the
    set call could open at 20x, where isolated liquidation is ~−5% (a single normal candle wipes the
    leg). Reading the effective leverage back is the only safe check. Empty set for spot."""
    if cfg.market_type != "swap":
        return set()
    target = int(cfg.max_leverage)
    syms = [to_ccxt_symbol(s, cfg.quote, cfg.market_type) for s in data_syms]
    # PRIMARY confirmation = the leverage Binance echoes back in the set_leverage response. This is
    # authoritative (it is the now-effective leverage, not a blind ack) AND it works on a FLAT
    # account — critical, because Binance's positionRisk read-back returns NO rows when flat, so a
    # read-back-only check could never confirm leverage before the first fill (chicken-and-egg: can't
    # open without confirming, can't confirm without an open position) -> the bot would never trade.
    set_lev: dict[str, object] = {}
    for sym in syms:
        try:
            exchange.set_margin_mode(cfg.margin_mode, sym)
        except Exception:
            pass  # re-setting an unchanged margin mode throws a benign error
        try:
            r = exchange.set_leverage(target, sym)
            L = None
            if isinstance(r, dict):
                L = r.get("leverage")
                if L is None and isinstance(r.get("info"), dict):
                    L = r["info"].get("leverage")
            set_lev[sym] = L
        except Exception:
            set_lev[sym] = None  # set failed -> fall back to the read-back, else unsafe
    # SECONDARY confirmation: effective leverage off any OPEN position (belt-and-suspenders; binance
    # only returns non-flat rows, so this just corroborates once a leg exists).
    read_lev: dict[str, object] = {}
    try:
        for p in exchange.fetch_positions(syms):
            read_lev[p.get("symbol")] = p.get("leverage")
    except Exception:
        read_lev = {}
    unsafe = set()
    for s, sym in zip(data_syms, syms):
        ok = False
        for L in (set_lev.get(sym), read_lev.get(sym)):
            try:
                if L is not None and int(float(L)) == target:
                    ok = True
                    break
            except (TypeError, ValueError):
                pass
        if not ok:
            unsafe.add(s)
    return unsafe


def place_orders(exchange, orders: list[Order], *, mode: str = "dry",
                 cfg: LiveConfig | None = None) -> list[dict]:
    """``mode='dry'`` prints intended orders (no API write). ``mode='live'`` places market orders —
    only proceeds when :func:`x4_live_enabled`.

    Spot: BUY uses quoteOrderQty (spend $X), SELL uses base. Swap (``cfg.market_type=='swap'``): BUY/SELL
    use base amount; ``reduceOnly`` is set per-order (``Order.reduce_only``) — True only when the order
    moves |position| toward zero without crossing (close long / cover short), so an open-or-add SELL
    short (§24 做空闸) or a regime-flip cross-zero order is NOT reduceOnly (would otherwise be rejected/
    capped)."""

    swap = bool(cfg and cfg.market_type == "swap")
    placed: list[dict] = []
    for o in orders:
        line = f"  [{mode}] {o.side.upper():4} {o.symbol:10} ~${o.est_usdt:.2f}  ({o.reason})"
        if mode != "live":
            print(line + "  -- DRY, no order sent")
            placed.append({"dry": True, "order": o})
            continue
        if not x4_live_enabled():
            print(line + "  -- BLOCKED: QOUNT_X4_LIVE_ENABLE not set")
            placed.append({"blocked": True, "order": o})
            continue
        if swap:
            amount = o.base_amount
            params = {"reduceOnly": True} if o.reduce_only else {}
        else:
            amount = None if o.side == "buy" else o.base_amount
            params = {"quoteOrderQty": o.quote_amount} if o.side == "buy" else {}
        print(line + "  -- SENDING")
        r = exchange.create_order(o.symbol, "market", o.side, amount, None, params)
        placed.append({"result": r, "order": o})
    return placed


def fetch_open_stops(exchange, data_syms: list[str], cfg: LiveConfig) -> dict[str, dict]:
    """The resting reduce-only / closePosition STOP_MARKET orders currently on the exchange, keyed by
    data symbol: ``{data_sym: {"id","symbol","stopPrice"}}``. Swap only; a per-symbol read failure is
    skipped (best-effort — a missed read just means we may re-place, which the band debounces).

    ⚠️ Binance USDⓈ-M conditional / ``closePosition`` STOP_MARKET orders are NOT returned by a plain
    ``fetch_open_orders`` — they live in a separate "stop" order book and only surface with
    ``params={"stop": True}``. Without it this returned ``{}`` every run → plan re-placed the stop that
    was already resting → Binance ``-4130`` ("a closePosition order in the direction is existing") →
    the whole live run crashed each cron tick. (Found the first time stops were actually placed live.)"""

    if cfg.market_type != "swap":
        return {}
    out: dict[str, dict] = {}
    for s in data_syms:
        sym = to_ccxt_symbol(s, cfg.quote, cfg.market_type)
        try:
            orders = exchange.fetch_open_orders(sym, params={"stop": True})
        except Exception:
            continue
        for o in orders:
            info = o.get("info") or {}
            otype = str(o.get("type") or info.get("type") or info.get("origType") or "").upper()
            sp = o.get("stopPrice") or o.get("triggerPrice") or info.get("stopPrice")
            # ccxt normalizes a Binance conditional order's unified ``type`` to "market" — the STOP-ness
            # lives in origType / the presence of a trigger price. Since we query the stop book
            # (params stop=True) any returned order with a trigger price IS a resting stop.
            is_stop = "STOP" in otype or sp not in (None, "", 0)
            is_reduce = bool(o.get("reduceOnly") or str(info.get("reduceOnly")).lower() == "true"
                             or o.get("closePosition") or str(info.get("closePosition")).lower() == "true")
            if is_stop and is_reduce:
                out[s] = {"id": o.get("id"), "symbol": sym,
                          "stopPrice": float(sp) if sp not in (None, "") else None}
                break
    return out


def sync_stop_orders(exchange, plan: StopOrderPlan, *, mode: str = "dry",
                     cfg: LiveConfig | None = None) -> list[dict]:
    """Cancel stale resting stops, THEN place the new ones (cancel-first so an amended/closePosition
    stop is not rejected as a duplicate). Same dry/live + :func:`x4_live_enabled` gating as
    :func:`place_orders`. Each placed order is a ``STOP_MARKET`` with ``closePosition=True`` — it closes
    the whole leg on trigger and auto-cancels once the position is flat (so the daily-close exit cleans
    it up), the exchange-side disaster backstop for the 10-min cron gap."""

    acted: list[dict] = []
    live = (mode == "live") and x4_live_enabled()
    for c in plan.to_cancel:
        tag = f"  [{mode}] CANCEL stop {c.symbol} #{c.order_id}"
        if not live:
            print(tag + ("  -- BLOCKED: switch off" if mode == "live" else "  -- DRY"))
            acted.append({"cancel": c, "sent": False})
            continue
        try:
            # ⚠️ closePosition STOP_MARKET orders are Binance **CONDITIONAL/algo** orders (algoType
            # CONDITIONAL, keyed by algoId, actualOrderId empty until triggered) — NOT regular orders.
            # cancel_order WITHOUT params={"stop": True} hits the regular-order endpoint -> the algoId
            # isn't found there -> OrderNotFound, the algo stop survives, and the re-place then hits
            # -4130 ("already existing") => every-run churn. The stop param routes to the algo cancel
            # endpoint (mirror of fetch_open_stops, which already needs it). Verified live 2026-06-19.
            exchange.cancel_order(c.order_id, c.symbol, params={"stop": True})
            acted.append({"cancel": c, "sent": True})
        except Exception as exc:   # a stale id (already filled/cancelled) is benign — log, continue
            print(tag + f"  -- cancel failed: {type(exc).__name__}")
            acted.append({"cancel": c, "error": str(exc)})
    for o in plan.to_place:
        tag = f"  [{mode}] STOP {o.symbol} @ {o.stop_price:.6g}  ({o.reason})"
        if not live:
            print(tag + ("  -- BLOCKED: switch off" if mode == "live" else "  -- DRY"))
            acted.append({"place": o, "sent": False})
            continue
        print(tag + "  -- SENDING")
        try:
            r = exchange.create_order(o.symbol, "STOP_MARKET", o.side, None, None,
                                      {"stopPrice": o.stop_price, "closePosition": True})
            acted.append({"place": o, "result": r})
        except Exception as exc:   # a stop is a best-effort disaster backstop — never crash the whole
            # run on a placement error. -4130 (a closePosition stop already rests in this direction) is
            # benign (the protective stop IS there); any other error is logged but also non-fatal so the
            # daily reconcile + local intraday stop still run.
            print(tag + f"  -- place failed (non-fatal): {type(exc).__name__}: {str(exc)[:120]}")
            acted.append({"place": o, "error": str(exc)})
    return acted
