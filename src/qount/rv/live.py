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

# COIN-M dated contracts are FIXED-USD-value (inverse): the short leg can only be opened in whole
# contracts. Below 1 contract the pair is not tradeable -> skip it (small-capital safety, e.g. $100
# total can't fund a $100 BTCUSD short, so it runs ETH-only). Standard Binance multipliers.
CONTRACT_USD: dict[str, float] = {"BTCUSD": 100.0, "ETHUSD": 10.0}


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
    # --- auto-funding (owner 2026-06-19「用合约账户闲置资金」): pull idle USDⓈ-M USDT to fund the carry
    # wallets instead of manual pre-funding. Per pair: spot long needs N USDT; COIN-M short needs N/L of
    # the BASE COIN as margin (inverse) -> the plan transfers USDT UMFUTURE->SPOT, buys the margin-coin
    # shortfall on spot, and transfers it SPOT->COIN-M. ``um_buffer_usdt`` is left in UMFUTURE untouched
    # (the trend leg's liquidation buffer — never drained). Default OFF (byte-identical); needs the API
    # key's **Permits Universal Transfer** permission to actually move funds. ---
    autofund: bool = False
    um_buffer_usdt: float = 200.0     # keep ≥ this much in UMFUTURE for the trend leg (never transfer out)


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


def _fundable_pairs(cfg: CarryConfig) -> tuple[list[tuple[str, str]], float]:
    """Resolve which pairs are fundable and the per-pair SHORT notional ``N = slice × L/(L+1)``,
    dividing the carry capital ONLY among fundable pairs.

    A pair whose equal share can't open one whole COIN-M contract (e.g. BTCUSD=$100 at a small slice)
    is DROPPED and its capital REALLOCATED to the survivors instead of stranding it idle — so the carry
    deploys its full slice. (2026-06-19: previously divided by ``len(pairs)`` unconditionally, so when
    BTC was un-fundable its half of the slice sat idle forever and the carry stuck at ~½ of its 40%
    target. Now ETH absorbs the freed BTC half → the slice is actually deployed.)

    Iterative because dropping a pair raises the survivors' share, which can itself make a leg fundable:
    drop the largest-contract un-fundable pair, recompute ``N``, repeat to a fixed point. Returns
    ``([], 0.0)`` when even the single best pair can't fund one contract."""
    L = cfg.liq_leverage if (cfg.liq_leverage and cfg.liq_leverage > 0) else 1.0
    pairs = list(cfg.pairs)
    while pairs:
        per_pair = cfg.capital_usdt / len(pairs)
        sh = per_pair * (L / (L + 1.0)) if L and L > 0 else per_pair
        unfundable = [(s, b) for s, b in pairs
                      if CONTRACT_USD.get(b, 0.0) and sh < CONTRACT_USD[b]]
        if not unfundable:
            return pairs, sh
        drop = max(unfundable, key=lambda sb: CONTRACT_USD.get(sb[1], 0.0))  # hardest to fund first
        pairs = [p for p in pairs if p != drop]
    return [], 0.0


def target_legs(now_ms: int, cfg: CarryConfig) -> list[CarryLeg]:
    """Today's target legs: per FUNDABLE pair a SHORT of notional ``N`` on the active dated, and a spot
    long of ``N·(L−1)/L``. Capital is split across only the fundable pairs (:func:`_fundable_pairs`).

    **Net Δ ≈ 0**: the spot long (``N·(L−1)/L``) PLUS the short's COIN-M margin coin (``N/L``, which is
    real coin held = long exposure) == ``N`` total long == the short ``N``. The margin coin is part of
    the hedge, not extra exposure — this matches the backtest's delta-neutral N-vs-N model. (Before
    2026-06-19 the spot was the FULL ``N``, so spot+margin left a ``+N/L`` long tilt; fixed here.) The
    un-leveraged remainder ``N/L`` of per-pair capital stays idle. A pair is SKIPPED when its dated
    calendar is empty OR (via :func:`_fundable_pairs`) its share can't fund one whole COIN-M contract."""

    fundable, sh = _fundable_pairs(cfg)
    if not fundable:
        return []
    L = cfg.liq_leverage if (cfg.liq_leverage and cfg.liq_leverage > 0) else 1.0
    spot_long = sh * (L - 1.0) / L          # spot + COIN-M margin (N/L) == N total long => Δ≈0
    legs: list[CarryLeg] = []
    for spot_sym, base in fundable:
        ad = active_dated(base, now_ms, cfg)
        if ad is None:
            continue
        dated_sym, _exp = ad
        legs.append(CarryLeg("spot", spot_sym, +spot_long))
        legs.append(CarryLeg("dated", dated_sym, -sh, base=base))
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


# ----------------------------- pure auto-funding planner -----------------------------

@dataclass(frozen=True)
class FundingAction:
    """One wallet move to provision the carry: ``kind`` in
    {"transfer_usdt_to_spot","buy_margin_coin","transfer_coin_to_cm"}."""

    kind: str
    asset: str            # "USDT" for the transfer; the BASE coin (e.g. "BTC") for buy/coin-transfer
    amount: float         # USDT for transfer/buy; COIN units for the coin transfer
    spot_sym: str = ""    # buy_margin_coin: the spot symbol to market-buy (e.g. "BTCUSDT")
    reason: str = ""


@dataclass
class FundingPlan:
    actions: list[FundingAction] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    um_draw_usdt: float = 0.0   # total USDT pulled from UMFUTURE this run


def plan_funding(
    legs: list[CarryLeg],
    spot_usdt: float,                  # USDT currently in the SPOT wallet
    cm_coin_usdt: dict[str, float],    # spot_sym -> USD value of the BASE coin already in the COIN-M wallet
    prices: dict[str, float],          # spot_sym -> price (for coin amount estimate)
    um_available_usdt: float,          # free (idle) USDT in the USDⓈ-M wallet
    cfg: CarryConfig,
    cur_spot_usdt: dict[str, float] | None = None,  # spot_sym -> USD value of the spot BASE already held
) -> FundingPlan:
    """Plan the moves to fund the target carry legs from idle UMFUTURE USDT (cfg.autofund).

    Per active pair: the spot long needs to be BUILT UP to its full notional ``N`` — but only the
    SHORTFALL vs the spot already held (``cur_spot_usdt``) costs USDT; the COIN-M short needs ``N/L``
    of the base coin as margin (again only the shortfall). So spot must hold ``Σ (N − held) + Σ (margin
    shortfall)`` USDT; the deficit vs ``spot_usdt`` is transferred UMFUTURE->SPOT, **capped so UMFUTURE
    keeps ``um_buffer_usdt``** (never drains the trend leg). Then each pair's margin-coin shortfall is
    market-bought on spot and transferred SPOT->COIN-M. OFF -> empty plan.

    (2026-06-19: ``cur_spot_usdt`` added — previously the need was the FULL ``N`` ignoring the spot ETH
    already held, so every run topped spot USDT toward ``N`` and slowly bled the trend wallet into idle
    spot cash even when the legs were already at target. Now an at-target carry funds $0.)"""

    plan = FundingPlan()
    if not cfg.autofund:
        return plan
    L = cfg.liq_leverage if cfg.liq_leverage and cfg.liq_leverage > 0 else 1.0
    held = cur_spot_usdt or {}
    # margin is N/L of the SHORT notional (dated leg), NOT of the (smaller) spot long -> map per pair
    base_to_spot = {b: s for s, b in cfg.pairs}
    short_by_spot: dict[str, float] = {}
    for leg in legs:
        if leg.kind == "dated":
            sp = base_to_spot.get(leg.base)
            if sp:
                short_by_spot[sp] = abs(leg.notional_usdt)
    usdt_need = 0.0
    margin_shortfalls: list[tuple[str, float]] = []   # (spot_sym, USD margin coin to BUY)
    for leg in legs:
        if leg.kind != "spot":
            continue
        spot_long = abs(leg.notional_usdt)
        spot_buy = max(0.0, spot_long - held.get(leg.symbol, 0.0))  # only the INCREMENTAL spot to acquire
        sh = short_by_spot.get(leg.symbol, spot_long)
        margin_usd = sh / L
        have = cm_coin_usdt.get(leg.symbol, 0.0)
        short = max(0.0, margin_usd - have)          # margin coin still to acquire
        usdt_need += spot_buy + short                # USDT for the incremental spot buy + the margin-coin buy
        if short > 0:
            margin_shortfalls.append((leg.symbol, short))
    transfer = max(0.0, usdt_need - spot_usdt)
    cap = max(0.0, um_available_usdt - cfg.um_buffer_usdt)
    if transfer > cap + 1e-9:
        plan.skipped.append(
            f"自动供资跳过:需从 UMFUTURE 转 ${transfer:.0f},但可用 ${um_available_usdt:.0f} − 缓冲 "
            f"${cfg.um_buffer_usdt:.0f} = ${cap:.0f} 不够(不抽干趋势腿保证金)")
        return plan
    if transfer >= cfg.min_order_usdt:
        plan.actions.append(FundingAction("transfer_usdt_to_spot", "USDT", transfer,
                                          reason="fund carry (UMFUTURE->SPOT)"))
        plan.um_draw_usdt = transfer
    for spot_sym, short_usd in margin_shortfalls:
        if short_usd < cfg.min_order_usdt:
            plan.skipped.append(f"{spot_sym}: 保证金缺口 ${short_usd:.0f} < min_order,跳过")
            continue
        coin = spot_sym[: -len(cfg.quote)]
        px = prices.get(spot_sym, 0.0)
        plan.actions.append(FundingAction("buy_margin_coin", coin, short_usd, spot_sym=spot_sym,
                                          reason="COIN-M margin"))
        if px > 0:
            plan.actions.append(FundingAction("transfer_coin_to_cm", coin, short_usd / px,
                                              reason="margin SPOT->COIN-M"))
    return plan


def execute_funding(spot_ex, orders_plan: FundingPlan, *, mode: str = "dry",
                    cfg: CarryConfig | None = None) -> list[dict]:
    """Run a :func:`plan_funding` plan. ``dry`` prints, sends nothing. ``live`` (and
    :func:`rv_live_enabled`) does the ccxt moves on ``spot_ex`` (transfers are account-level sapi calls;
    the margin coin is market-bought on spot then transferred SPOT->COIN-M). Needs the key's
    **Permits Universal Transfer** permission — without it the transfer raises (caught, non-fatal)."""

    quote = cfg.quote if cfg else "USDT"
    done: list[dict] = []
    for a in orders_plan.actions:
        if a.kind == "transfer_usdt_to_spot":
            line = f"  [{mode}] TRANSFER {a.amount:.2f} USDT  UMFUTURE->SPOT  ({a.reason})"
        elif a.kind == "buy_margin_coin":
            line = f"  [{mode}] BUY spot {a.spot_sym} ~${a.amount:.0f}  ({a.reason})"
        else:
            line = f"  [{mode}] TRANSFER {a.amount:.6g} {a.asset}  SPOT->COIN-M  ({a.reason})"
        if mode != "live":
            print(line + "  -- DRY"); done.append({"dry": True, "action": a}); continue
        if not rv_live_enabled():
            print(line + "  -- BLOCKED: QOUNT_RV_LIVE_ENABLE not set"); done.append({"blocked": True, "action": a}); continue
        print(line + "  -- SENDING")
        try:
            if a.kind == "transfer_usdt_to_spot":
                r = spot_ex.transfer("USDT", a.amount, "future", "spot")
            elif a.kind == "buy_margin_coin":
                r = spot_ex.create_order(to_ccxt_spot(a.spot_sym, quote), "market", "buy", None, None,
                                         {"quoteOrderQty": round(a.amount, 2)})
            else:
                # transfer_coin_to_cm: the plan amount is a PRE-fee estimate; a market buy fills slightly
                # LESS after fees, so transferring the estimate -> "insufficient balance" (the 2026-06-19
                # incident: coin stayed in spot, COIN-M empty, short unmargined). Use the ACTUAL free
                # coin, lightly haircut for dust/precision.
                free = float((spot_ex.fetch_balance().get("free") or {}).get(a.asset, 0.0) or 0.0)
                amt = min(a.amount, free) * 0.999
                if amt <= 0:
                    raise RuntimeError(f"no free {a.asset} to transfer to COIN-M (have {free})")
                r = spot_ex.transfer(a.asset, amt, "spot", "delivery")
            done.append({"result": r, "action": a})
        except Exception as exc:   # non-fatal: a missing transfer permission / dust must not crash the run
            print(line + f"  -- failed (non-fatal): {type(exc).__name__}: {str(exc)[:120]}")
            done.append({"error": str(exc), "action": a})
    return done


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


def from_ccxt_dated(ccxt_sym: str) -> str:
    """``"BTC/USD:BTC-260626"`` -> internal ``"BTCUSD_260626"`` (reverse of :func:`to_ccxt_dated`)."""
    _, _, settle_exp = ccxt_sym.partition(":")
    coin, _, yymmdd = settle_exp.partition("-")
    return f"{coin}USD_{yymmdd}"


def place_carry_orders(exchange_spot, exchange_cm, orders: list[CarryOrder], *,
                       mode: str = "dry", cfg: CarryConfig | None = None) -> list[dict]:
    """``mode='dry'`` prints intended two-venue orders (no API write); ``mode='live'`` places market
    orders only when :func:`rv_live_enabled`. Spot legs route to ``exchange_spot``, dated COIN-M legs
    to ``exchange_cm`` (short open / roll-cover). Mocked in tests."""

    quote = cfg.quote if cfg else "USDT"
    placed: list[dict] = []
    # SPOT-FIRST ordering (safer partial-failure residual): if a leg fails mid-sequence the leftover is a
    # SPOT LONG (bounded, no leverage, no liquidation) — never a naked leveraged SHORT. The 2026-06-19
    # incident left a naked long ONLY because the short ALWAYS -1102'd (contract-qty bug, now fixed); the
    # fix is a correct short, not hedge-first (which would risk a naked short). A short failure after the
    # spot fills -> loud ALERT; the leftover long is safe and re-hedged on the next reconcile.
    spot_orders = [o for o in orders if "_" not in o.symbol]
    dated_orders = [o for o in orders if "_" in o.symbol]
    for o in spot_orders + dated_orders:
        dated = "_" in o.symbol
        venue = "COIN-M" if dated else "spot"
        line = f"  [{mode}] {o.side.upper():4} {venue:6} {o.symbol:14} ~${o.notional_usdt:.0f}  ({o.reason})"
        qty = 0
        if dated:
            base = o.symbol.split("_")[0]               # "ETHUSD"
            contract = CONTRACT_USD.get(base, 0.0)
            qty = int(o.notional_usdt / contract) if contract else 0   # COIN-M = whole contracts, FLOOR
            # (floor not round: short <= target N <= long, and margin N/L always covers floor(N)/L; a
            #  round-up over-sized the short past the provisioned margin -> 2026-06-19 -2019 incident)
            if qty < 1:
                print(line + "  -- SKIP: below 1 whole COIN-M contract")
                placed.append({"skip": "below 1 contract", "order": o})
                continue
        if mode != "live":
            print(line + (f"  x{qty}c" if dated else "") + "  -- DRY")
            placed.append({"dry": True, "order": o})
            continue
        if not rv_live_enabled():
            print(line + "  -- BLOCKED: QOUNT_RV_LIVE_ENABLE not set")
            placed.append({"blocked": True, "order": o})
            continue
        ex = exchange_cm if dated else exchange_spot
        sym = to_ccxt_dated(o.symbol) if dated else to_ccxt_spot(o.symbol, quote)
        print(line + (f"  x{qty}c" if dated else "") + "  -- SENDING")
        try:
            # COIN-M inverse dated: sized in WHOLE CONTRACTS (fixed-USD each), NOT quoteOrderQty.
            r = (ex.create_order(sym, "market", o.side, qty, None, {}) if dated else
                 ex.create_order(sym, "market", o.side, None, None, {"quoteOrderQty": round(o.notional_usdt, 2)}))
            placed.append({"result": r, "order": o})
        except Exception as exc:   # one leg failing must not crash the run
            tag = "[ALERT] SHORT 腿失败 -> 现货多腿可能裸露(安全:无杠杆/无清算),下轮自动重对冲" if (
                dated and o.side == "sell") else f"failed (non-fatal): {type(exc).__name__}"
            print(line + f"  -- {tag}: {str(exc)[:120]}")
            placed.append({"error": str(exc), "order": o})
    return placed
