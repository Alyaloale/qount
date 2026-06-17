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
    # S7-mini signal params (§21 deployable = §19.7 validated)
    fast: int = 20
    slow: int = 100
    regime_sma: int = 200
    vol_lookback: int = 30               # inverse-vol weight window (= engine combine vol_lookback)
    gate_sym: str = "BTCUSDT"
    gate_sma: int = 200
    # --- §21.4 train+test-validated enhancements (此前未接进 live;只改善 chop/熊 regime,牛市中性) ---
    breadth_gate: float | None = 0.5     # risk-on if BTC gate OR ≥50% of universe above its regime_sma
    breadth_combine: str = "or"          # "or" (默认,§21.B) | "and" | "breadth"
    corr_penalty: bool = True            # §21.D: inverse-vol ÷ max(avg pairwise corr, corr_floor)
    corr_floor: float = 0.2


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
        return []

    raw: dict[str, float] = {}
    windows: dict[str, list[float]] = {}
    scale: dict[str, float] = {}
    need = max(cfg.regime_sma, cfg.slow, cfg.vol_lookback + 1, cfg.atr_lookback + 1)
    for s in cfg.universe:
        bars = bars_by_sym.get(s)
        if not bars:
            continue
        c = [b.close for b in bars]
        if len(c) < need:
            continue
        if c[-1] > _sma(c, cfg.regime_sma) and _sma(c, cfg.fast) > _sma(c, cfg.slow):
            rets = [c[i] / c[i - 1] - 1.0 for i in range(len(c) - cfg.vol_lookback, len(c))]
            mu = sum(rets) / len(rets)
            vol = (sum((x - mu) ** 2 for x in rets) / (len(rets) - 1)) ** 0.5
            raw[s] = (1.0 / vol) if vol > 0 else 0.0
            windows[s] = rets
            atr = ATR(cfg.atr_lookback)
            a = None
            for b in bars:
                a = atr.update(b)
            atr_pct = (a / c[-1]) if (a is not None and c[-1] > 0) else None
            scale[s] = min(cfg.max_leverage, cfg.vol_target / atr_pct) if (atr_pct and atr_pct > 0) else 0.0
    if not raw:
        return []
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
    # vol-parity sizing (mirror run_directional): absolute exposure = relative weight × per-coin scale
    return [TargetWeight(s, rel[s] * scale[s]) for s in raw]


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
    """Intraday trailing-Chandelier overlay on the daily target weights (盘中硬止损).

    For each held coin, ratchet a trailing high from the LIVE price; if the live price falls to
    ``trail_high − chandelier_mult × ATR(chandelier_lookback)`` the coin is forced flat NOW (a real
    exit on the next 10-min run, not the daily close) and **latched** so it can't re-enter until the
    daily signal itself drops the coin (mirrors :func:`run_directional`'s ``ch_latched``: re-arm on
    signal reset). Cuts both intraday-crash liquidation risk and top-giveback. ``chandelier_mult<=0``
    disables (returns targets/state unchanged). Returns (adjusted targets, new state, triggered syms)."""

    if cfg.chandelier_mult <= 0:
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
        if t.weight <= 0 or px is None:
            adjusted.append(t)
            continue
        atr = _atr_last(daily_bars.get(s, []), cfg.chandelier_lookback)
        trail_high = max(prev.get("trail_high", px), px)
        if atr is not None and px <= trail_high - cfg.chandelier_mult * atr:
            triggered.append(s)
            adjusted.append(TargetWeight(s, 0.0))   # force exit
            new_state[s] = {"latched": True}
        else:
            adjusted.append(t)
            new_state[s] = {"trail_high": trail_high}
    # coins not in `targets` (daily signal already dropped them) fall out of new_state -> latch cleared
    return adjusted, new_state, triggered


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
    """Diff target dollar allocations vs current holdings into band-gated, capped, lot-rounded orders.

    ``targets`` carry **absolute** exposure fractions of capital (vol-parity sized), so
    ``target_notional = weight × capital_usdt`` directly (NO renormalization — that would undo the
    vol-parity sizing). Total gross is clamped defensively to ``max_leverage × capital_usdt``.
    Idempotent: a leg already within ``rebalance_band`` of its target produces no order."""

    res = ReconcileResult(gate_open=bool(targets))
    tw = {t.symbol: t.weight for t in targets}
    # defensive clamp only: scale down proportionally if total gross would exceed the leverage cap
    gross = sum(tw.values())
    cap = cfg.max_leverage
    if gross > cap and gross > 0:
        tw = {s: w * cap / gross for s, w in tw.items()}
    # per-BUY deployment cap = the smaller of the configured ceiling and this account's buying power
    # (capital × leverage); the static ``max_order_usdt`` default was sized for the $415 pilot, so on a
    # smaller live capital it shrinks with the account rather than staying a stale 12×-capital backstop.
    order_cap = min(cfg.max_order_usdt, cfg.capital_usdt * max(cfg.max_leverage, 1.0))

    universe = list(dict.fromkeys(list(cfg.universe) + list(balances_base)))
    for s in universe:
        px = prices.get(s, 0.0)
        cur_usdt = balances_base.get(s, 0.0) * px
        tgt_usdt = tw.get(s, 0.0) * cfg.capital_usdt
        res.target_usdt[s] = tgt_usdt
        res.current_usdt[s] = cur_usdt
        diff = tgt_usdt - cur_usdt
        denom = max(tgt_usdt, cur_usdt, 1e-9)

        # band gate: leave small deviations alone (no churn on $415)
        if abs(diff) < cfg.rebalance_band * denom and tgt_usdt > 0:
            res.skipped.append(f"{s}: within band ({cur_usdt:.2f}->{tgt_usdt:.2f})")
            continue
        if abs(diff) < cfg.min_order_usdt:
            res.skipped.append(f"{s}: below min_order ({diff:+.2f} USDT)")
            continue
        if px <= 0 or s not in filters:
            res.skipped.append(f"{s}: no price/filter")
            continue

        f = filters[s]
        if diff > 0:   # BUY (deploy quote)
            spend = min(diff, order_cap)
            if spend < max(cfg.min_order_usdt, f.min_notional):
                res.skipped.append(f"{s}: buy {spend:.2f} below notional floor")
                continue
            est_base = _round_down_step(spend / px, f.amount_step)
            if est_base < f.min_amount or est_base <= 0:
                res.skipped.append(f"{s}: buy base {est_base} below min_amount")
                continue
            res.orders.append(Order(to_ccxt_symbol(s, cfg.quote, cfg.market_type), "buy", est_base,
                                    round(spend, 2), round(spend, 2),
                                    reason=f"deploy {cur_usdt:.0f}->{tgt_usdt:.0f}"))
        else:          # SELL (reduce base) — keep the plain cap; never throttle a risk-reducing exit
            sell_usdt = min(-diff, cfg.max_order_usdt)
            base_amt = _round_down_step(sell_usdt / px, f.amount_step)
            # don't try to sell more than we hold
            base_amt = min(base_amt, _round_down_step(balances_base.get(s, 0.0), f.amount_step))
            if base_amt < f.min_amount or base_amt * px < max(cfg.min_order_usdt, f.min_notional):
                res.skipped.append(f"{s}: sell {base_amt} below notional/min floor")
                continue
            res.orders.append(Order(to_ccxt_symbol(s, cfg.quote, cfg.market_type), "sell", base_amt,
                                    0.0, round(base_amt * px, 2),
                                    reason=f"reduce {cur_usdt:.0f}->{tgt_usdt:.0f}"))
    return res


def unreachable_coins(filters: dict[str, SymbolFilter], prices: dict[str, float],
                      cfg: LiveConfig) -> list[dict]:
    """Universe coins whose exchange MINIMUM order exceeds an equal-weight slice of buying power
    (``capital × leverage ÷ n``) — they can't be held at their vol-parity weight, so on a small
    capital the live book is a concentrated subset of the universe (honest caveat, not a bug; e.g.
    BTC perp min 0.001 ≈ whole capital at $70). Returns ``[{"symbol", "min_usdt"}]`` sorted by cost."""

    buying_power = cfg.capital_usdt * max(cfg.max_leverage, 1.0)
    slice_cap = buying_power / max(1, len(cfg.universe))
    out: list[dict] = []
    for s in cfg.universe:
        f = filters.get(s)
        px = prices.get(s, 0.0)
        if not f or px <= 0:
            continue
        floor = max(f.min_amount * px, f.min_notional, cfg.min_order_usdt)
        if floor > slice_cap:
            out.append({"symbol": s, "min_usdt": round(floor, 1)})
    return sorted(out, key=lambda d: -d["min_usdt"])


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

    Spot: BUY uses quoteOrderQty (spend $X), SELL uses base. Swap (``cfg.market_type=='swap'``):
    long-only perp — BUY uses base amount, SELL uses base amount with ``reduceOnly`` so it only
    closes the existing long (never flips short)."""

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
            params = {} if o.side == "buy" else {"reduceOnly": True}
        else:
            amount = None if o.side == "buy" else o.base_amount
            params = {"quoteOrderQty": o.quote_amount} if o.side == "buy" else {}
        print(line + "  -- SENDING")
        r = exchange.create_order(o.symbol, "market", o.side, amount, None, params)
        placed.append({"result": r, "order": o})
    return placed
