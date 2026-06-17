"""RV-C cash-and-carry LIVE execution (线 C 实盘腿) — reconciliation-based, idempotent.

The validated edge (``docs/rv-c-plan.md`` §7): **long spot + short the active dated quarterly
COIN-M future**, delta-neutral, always-on (A1 basis-timing was falsified). The dated future's
contractual expiry convergence (F→S) is the hard anchor H3's perpetual lacked. This module turns
that into real two-leg orders + the quarterly **roll** (close the expiring short, open the next),
sized so each pair's capital funds the long spot + the short's isolated margin.

Built to be the carry sleeve of the C×D combo (线 D trend rides bulls, this earns the contango +
collects funding the trend leg pays). Isolated from line A's frozen ``Executor``; own switch
``QOUNT_RV_LIVE_ENABLE`` (default off); ``mode="dry"`` places nothing.

ECONOMICS / sizing (per pair, capital ``C``, short leverage ``L``):
  spot long notional ``N = C·L/(L+1)``; short dated notional ``= N`` (delta-neutral); short isolated
  margin ``N/L`` -> spot + margin ``= C``. Δ≈0 by construction; the carry is the basis F→S, not price.

The pure functions (:func:`active_dated`, :func:`target_legs`, :func:`compute_carry_orders`) are
network-free and unit-tested; the thin ccxt wrappers are mocked in tests. Reuses the PIT-clean roll
calendar (:func:`qount.rv.basis.active_expiry`, :func:`qount.rv.data.quarterly_contracts`).
"""
from __future__ import annotations

import datetime as dt
import math
import os
from dataclasses import dataclass, field

from qount.rv.basis import active_expiry
from qount.rv.data import dated_symbol, expiry_ms as _expiry_ms, quarterly_contracts

_DAY_MS = 86_400_000


# a-priori BTC/ETH only (§7.8: breadth falsified, LINK/LTC don't survive de-multiple-testing)
CARRY_PAIRS = (("BTCUSDT", "BTCUSD"), ("ETHUSDT", "ETHUSD"))  # (spot data sym, COIN-M base)


@dataclass(frozen=True)
class CarryConfig:
    """Cash-and-carry live config. ``capital_usdt`` is the HARD total ceiling (spot + short margin)."""

    pairs: tuple[tuple[str, str], ...] = CARRY_PAIRS
    capital_usdt: float = 1_000.0     # total deployable (per-pair = this / n_pairs)
    quote: str = "USDT"
    roll_buffer_days: float = 5.0     # roll out of a contract this many days before expiry (thin/pinned)
    liq_leverage: float = 3.0         # leverage on the dated short (§7 认证档 L=3)
    rebalance_band: float = 0.10      # carry wants Δ tight -> narrower band than the trend leg
    min_order_usdt: float = 10.0
    margin_mode: str = "isolated"


@dataclass(frozen=True)
class CarryLeg:
    """A target leg: ``kind`` in {"spot","dated"}, signed ``notional_usdt`` (+long / −short)."""

    kind: str
    symbol: str          # spot data sym (e.g. "BTCUSDT") or dated COIN-M sym (e.g. "BTCUSD_260626")
    notional_usdt: float
    base: str = ""       # COIN-M base for the dated leg (e.g. "BTCUSD")


@dataclass(frozen=True)
class CarryOrder:
    symbol: str
    side: str            # "buy" | "sell"
    notional_usdt: float
    reason: str = ""
    is_roll: bool = False


@dataclass
class CarryReconcile:
    orders: list[CarryOrder] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    target_usdt: dict[str, float] = field(default_factory=dict)
    current_usdt: dict[str, float] = field(default_factory=dict)
    rolled: list[str] = field(default_factory=list)


# ----------------------------- pure target derivation -----------------------------

def active_dated(base: str, now_ms: int, cfg: CarryConfig) -> tuple[str, int] | None:
    """The dated COIN-M contract to be short *now* — nearest quarterly > ``roll_buffer_days`` away.

    PIT by construction: depends only on the fixed quarterly expiry calendar (known years ahead) +
    the roll buffer, never on price. Returns ``(symbol, expiry_ms)`` or ``None`` if the calendar
    window yields nothing. Scans this quarter through ~4 quarters ahead so a near roll always has a
    successor."""

    now = dt.datetime.fromtimestamp(now_ms / 1000, dt.UTC)
    start = (now.year, now.month)
    end_dt = now + dt.timedelta(days=400)
    quarters = quarterly_contracts(start, (end_dt.year, end_dt.month), base=base)
    if not quarters:
        return None
    exp_to_sym = {e: s for s, e in quarters}
    e = active_expiry(now_ms, list(exp_to_sym), cfg.roll_buffer_days)
    return (exp_to_sym[e], e) if e is not None else None


def _per_pair_spot_notional(cfg: CarryConfig) -> float:
    """Spot long notional per pair so spot + short-margin == per-pair capital (delta-neutral)."""
    per_pair = cfg.capital_usdt / max(1, len(cfg.pairs))
    L = cfg.liq_leverage
    return per_pair * (L / (L + 1.0)) if L and L > 0 else per_pair


def target_legs(now_ms: int, cfg: CarryConfig) -> list[CarryLeg]:
    """Today's target legs: per pair a +N spot long and a −N short on the active dated contract.

    ``N`` is the delta-neutral notional (:func:`_per_pair_spot_notional`). Empty for a pair whose
    dated calendar yields no tradeable contract (skipped, not guessed)."""

    n = _per_pair_spot_notional(cfg)
    legs: list[CarryLeg] = []
    for spot_sym, base in cfg.pairs:
        ad = active_dated(base, now_ms, cfg)
        if ad is None:
            continue
        dated_sym, _exp = ad
        legs.append(CarryLeg("spot", spot_sym, +n))
        legs.append(CarryLeg("dated", dated_sym, -n, base=base))
    return legs


# ----------------------------- pure reconciliation (with roll) -----------------------------

def compute_carry_orders(
    targets: list[CarryLeg],
    current_usdt: dict[str, float],   # symbol -> signed current notional (+long spot / −short dated)
    cfg: CarryConfig,
) -> CarryReconcile:
    """Diff target legs vs current signed notionals into band-gated orders, handling the ROLL.

    A dated contract held but NOT in ``targets`` (the expiring quarterly) gets a target of 0 — i.e.
    bought back to cover (the roll-out) — while the new active dated is opened short. Spot is nudged
    to its target long. Idempotent: a leg within ``rebalance_band`` of target produces no order."""

    res = CarryReconcile()
    tgt = {leg.symbol: leg.notional_usdt for leg in targets}
    res.target_usdt = dict(tgt)
    res.current_usdt = dict(current_usdt)
    active_dated_syms = {leg.symbol for leg in targets if leg.kind == "dated"}

    for sym in dict.fromkeys(list(tgt) + list(current_usdt)):
        t = tgt.get(sym, 0.0)
        c = current_usdt.get(sym, 0.0)
        diff = t - c
        denom = max(abs(t), abs(c), 1e-9)
        # a held dated contract that is no longer the active target == an expiring leg -> roll it out
        is_roll = sym not in active_dated_syms and sym not in tgt and abs(c) > 1e-9 and "_" in sym
        if abs(diff) < cfg.rebalance_band * denom and abs(t) > 1e-9:
            res.skipped.append(f"{sym}: within band ({c:.0f}->{t:.0f})")
            continue
        if abs(diff) < cfg.min_order_usdt:
            res.skipped.append(f"{sym}: below min_order ({diff:+.0f})")
            continue
        side = "buy" if diff > 0 else "sell"   # buy raises signed notional (more long / cover short)
        if is_roll:
            res.rolled.append(sym)
        res.orders.append(CarryOrder(sym, side, abs(diff),
                                     reason=("roll-out" if is_roll else f"{c:.0f}->{t:.0f}"),
                                     is_roll=is_roll))
    return res


def rv_live_enabled() -> bool:
    """Line-C-only live switch (independent of line A's ``QOUNT_LIVE_ENABLE`` and line D's switch)."""
    return os.environ.get("QOUNT_RV_LIVE_ENABLE", "").lower() in ("1", "true", "yes")


# ----------------------------- thin ccxt layer (mocked in tests) -----------------------------

def to_ccxt_spot(data_sym: str, quote: str = "USDT") -> str:
    if not data_sym.endswith(quote):
        raise ValueError(f"{data_sym!r} does not end with quote {quote!r}")
    return f"{data_sym[: -len(quote)]}/{quote}"


def to_ccxt_dated(dated_sym: str) -> str:
    """``"BTCUSD_260626"`` -> ccxt COIN-M dated ``"BTC/USD:BTC-260626"``."""
    base_quote, _, yymmdd = dated_sym.partition("_")
    coin = base_quote[:-3]      # "BTCUSD" -> "BTC"
    return f"{coin}/USD:{coin}-{yymmdd}"


def place_carry_orders(exchange_spot, exchange_cm, orders: list[CarryOrder], *,
                       mode: str = "dry", cfg: CarryConfig | None = None) -> list[dict]:
    """``mode='dry'`` prints intended two-venue orders (no API write); ``mode='live'`` places market
    orders only when :func:`rv_live_enabled`. Spot legs route to ``exchange_spot``, dated COIN-M legs
    to ``exchange_cm`` (short open / roll-cover). Mocked in tests."""

    placed: list[dict] = []
    for o in orders:
        dated = "_" in o.symbol
        venue = "COIN-M" if dated else "spot"
        line = f"  [{mode}] {o.side.upper():4} {venue:6} {o.symbol:14} ~${o.notional_usdt:.0f}  ({o.reason})"
        if mode != "live":
            print(line + "  -- DRY")
            placed.append({"dry": True, "order": o})
            continue
        if not rv_live_enabled():
            print(line + "  -- BLOCKED: QOUNT_RV_LIVE_ENABLE not set")
            placed.append({"blocked": True, "order": o})
            continue
        ex = exchange_cm if dated else exchange_spot
        sym = to_ccxt_dated(o.symbol) if dated else to_ccxt_spot(o.symbol, cfg.quote if cfg else "USDT")
        print(line + "  -- SENDING")
        r = ex.create_order(sym, "market", o.side, None, None,
                            {} if dated else {"quoteOrderQty": round(o.notional_usdt, 2)})
        placed.append({"result": r, "order": o})
    return placed
