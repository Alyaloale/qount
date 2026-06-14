"""X4 small-cap LIVE spot execution (线 D §21) — reconciliation-based, idempotent, spot-only.

Owner authorized a ~$415 (3000 RMB) live pilot of the small-cap S7-mini trend portfolio
(7 liquid coins, spot-only, no carry yet — §21). This module turns today's target weights into
real Binance spot orders.

ISOLATION (守线 A 纪律):
  * REUSES only the generic ccxt client builder ``exchange_utils.build_exchange`` — it does NOT route
    through line A's ``Executor`` (frozen, ``QOUNT_LIVE_ENABLE=false`` invariant intact).
  * Own switch ``QOUNT_X4_LIVE_ENABLE`` (default off). Even when on, ``mode="dry"`` places no orders.

SAFETY (真钱第一次):
  * Spot-only → no margin/futures → cannot be liquidated, cannot go negative.
  * Hard caps: ``capital_usdt`` total ceiling + ``max_order_usdt`` per order. Code refuses to exceed.
  * Reconciliation diff is band-gated → reruns are idempotent (no churn, no double-fills).
  * Market BUY uses ``quoteOrderQty`` (spend exactly $X); SELL uses base amount rounded to lot step.

The pure functions (:func:`target_weights`, :func:`compute_orders`) are network-free and unit-tested;
the thin ccxt wrappers are mocked in tests. The forward-s7 paper track remains the performance
source-of-truth; this module only *tracks* the engine's target weights into real fills.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

# ---- a priori liquidity-tiered 7-coin small-cap universe (§21; data symbols, not ccxt) ----
SMALLCAP_UNIVERSE = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT")


def to_ccxt_symbol(data_sym: str, quote: str = "USDT") -> str:
    """``"BTCUSDT"`` -> ``"BTC/USDT"`` (ccxt unified). Assumes the quote is the suffix."""
    if not data_sym.endswith(quote):
        raise ValueError(f"{data_sym!r} does not end with quote {quote!r}")
    return f"{data_sym[: -len(quote)]}/{quote}"


@dataclass(frozen=True)
class LiveConfig:
    """Small-cap live config. ``capital_usdt`` is a HARD total ceiling enforced in code."""

    universe: tuple[str, ...] = SMALLCAP_UNIVERSE
    capital_usdt: float = 415.0          # total deployable ceiling (3000 RMB ≈ $415)
    quote: str = "USDT"
    rebalance_band: float = 0.25         # skip a leg if |target-current| < band×max(target,current)
    min_order_usdt: float = 6.0          # skip dust below ~Binance MIN_NOTIONAL ($5) + margin
    max_order_usdt: float = 415.0        # per-order safety cap
    # S7-mini signal params (§21 deployable = §19.7 validated)
    fast: int = 20
    slow: int = 100
    regime_sma: int = 200
    vol_lookback: int = 30
    gate_sym: str = "BTCUSDT"
    gate_sma: int = 200


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


def target_weights(bars_by_sym: dict[str, list], cfg: LiveConfig) -> list[TargetWeight]:
    """Today's S7-mini target weights — mirrors ``x4_paper._held_coins`` / the §19 engine.

    Per coin held iff (close > SMA``regime_sma``) AND (SMA``fast`` > SMA``slow``); held coins get
    inverse-volatility parity weight (1/σ of the last ``vol_lookback`` daily returns), normalized.
    Empty list when the BTC master gate is shut or no coin is in an uptrend (-> 100% cash)."""

    gate_bars = bars_by_sym.get(cfg.gate_sym)
    if gate_bars is None:
        return []
    if not gate_is_open([b.close for b in gate_bars], cfg.gate_sma):
        return []

    raw: dict[str, float] = {}
    for s, bars in bars_by_sym.items():
        c = [b.close for b in bars]
        if len(c) < max(cfg.regime_sma, cfg.slow, cfg.vol_lookback + 1):
            continue
        if c[-1] > _sma(c, cfg.regime_sma) and _sma(c, cfg.fast) > _sma(c, cfg.slow):
            rets = [c[i] / c[i - 1] - 1.0 for i in range(len(c) - cfg.vol_lookback, len(c))]
            mu = sum(rets) / len(rets)
            vol = (sum((x - mu) ** 2 for x in rets) / (len(rets) - 1)) ** 0.5
            raw[s] = (1.0 / vol) if vol > 0 else 0.0
    tot = sum(raw.values())
    if not raw:
        return []
    if tot <= 0:
        return [TargetWeight(s, 1.0 / len(raw)) for s in raw]
    return [TargetWeight(s, w / tot) for s, w in raw.items()]


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

    Idempotent: a leg already within ``rebalance_band`` of its target produces no order, so re-running
    on an unchanged book is a no-op. Total target deployment is clamped to ``capital_usdt``."""

    res = ReconcileResult(gate_open=bool(targets))
    tw = {t.symbol: t.weight for t in targets}
    # normalize (defensive) and clamp total deployment to the hard capital ceiling
    wsum = sum(tw.values())
    if wsum > 0:
        tw = {s: w / wsum for s, w in tw.items()}

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
            spend = min(diff, cfg.max_order_usdt)
            if spend < max(cfg.min_order_usdt, f.min_notional):
                res.skipped.append(f"{s}: buy {spend:.2f} below notional floor")
                continue
            est_base = _round_down_step(spend / px, f.amount_step)
            if est_base < f.min_amount or est_base <= 0:
                res.skipped.append(f"{s}: buy base {est_base} below min_amount")
                continue
            res.orders.append(Order(to_ccxt_symbol(s, cfg.quote), "buy", est_base, round(spend, 2),
                                    round(spend, 2), reason=f"deploy {cur_usdt:.0f}->{tgt_usdt:.0f}"))
        else:          # SELL (reduce base)
            sell_usdt = min(-diff, cfg.max_order_usdt)
            base_amt = _round_down_step(sell_usdt / px, f.amount_step)
            # don't try to sell more than we hold
            base_amt = min(base_amt, _round_down_step(balances_base.get(s, 0.0), f.amount_step))
            if base_amt < f.min_amount or base_amt * px < max(cfg.min_order_usdt, f.min_notional):
                res.skipped.append(f"{s}: sell {base_amt} below notional/min floor")
                continue
            res.orders.append(Order(to_ccxt_symbol(s, cfg.quote), "sell", base_amt, 0.0,
                                    round(base_amt * px, 2), reason=f"reduce {cur_usdt:.0f}->{tgt_usdt:.0f}"))
    return res


def x4_live_enabled() -> bool:
    """Line-D-only live switch (independent of line A's ``QOUNT_LIVE_ENABLE``)."""
    return os.environ.get("QOUNT_X4_LIVE_ENABLE", "").lower() in ("1", "true", "yes")


# ----------------------------- thin ccxt layer (mocked in tests) -----------------------------

def fetch_filters(exchange, data_syms: list[str], quote: str = "USDT") -> dict[str, SymbolFilter]:
    """Pull LOT_SIZE / MIN_NOTIONAL from loaded ccxt markets."""
    if not getattr(exchange, "markets", None):
        exchange.load_markets()
    out: dict[str, SymbolFilter] = {}
    for s in data_syms:
        m = exchange.markets.get(to_ccxt_symbol(s, quote))
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


def place_orders(exchange, orders: list[Order], *, mode: str = "dry") -> list[dict]:
    """``mode='dry'`` prints intended orders (no API write). ``mode='live'`` places market orders —
    only proceeds when :func:`x4_live_enabled`. BUY uses quoteOrderQty (spend $X), SELL uses base."""

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
        params = {"quoteOrderQty": o.quote_amount} if o.side == "buy" else {}
        amount = None if o.side == "buy" else o.base_amount
        print(line + "  -- SENDING")
        r = exchange.create_order(o.symbol, "market", o.side, amount, None, params)
        placed.append({"result": r, "order": o})
    return placed
