"""RV-C dated-basis cash-and-carry backtest: ``run_basis_carry`` (线 C).

Mirrors line B's ``grid.backtest.run_h3_carry`` (equity-normalized sizing + the physical
liquidation tail门 from H3 §8.6) but swaps the short leg from a perpetual to a **dated
quarterly future** and the carry source from funding to **basis convergence**:

* No funding term -- a dated future has none. The carry is realized *through* the directional
  residual: while we hold the short, F drifts toward S (basis shrinks), and ``−short_base·dF``
  banks it. The spot long cancels the index move, leaving the basis. At expiry F≡S, so the
  full entry basis is captured -- the **hard anchor** H3's perpetual lacked.
* **Roll** every quarter (``is_roll`` from :func:`qount.rv.basis.build_active_series`): the
  expiring future is closed and the next opened. The price gap across contracts is *never*
  booked as PnL; only the two-leg roll fee is. Roll cost is tracked separately from rebalance
  fees for an honest decomposition.
* **Liquidation tail (H3 教训)**: the short can be force-closed by an intrabar pump past
  ``1/liq_leverage − mm_rate`` above the last rebalance/roll reference, costing
  ``notional × (liq_penalty + gap)``. Replicated here (not imported) to honour the line-B
  isolation boundary -- ``rv`` must not modify ``grid`` -- with the formula credited to
  ``run_h3_carry``.

Honest simplification (written in the open, per §3 priors): the COIN-M quarterly is an
*inverse* contract; this first cut treats the short leg linearly on its USD price (as H3
did), ignoring inverse convexity. The kill question is whether the thin basis survives
two-leg retail fees + the liquidation tail -- a cleaner question than grid/funding, and the
linear approximation does not flatter the edge.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from dataclasses import field
from typing import Sequence

from qount.rv.basis import ActiveBar


def _year_of(ts_ms: int) -> int:
    return _dt.datetime.fromtimestamp(ts_ms / 1000, _dt.UTC).year


def _max_drawdown(curve: Sequence[float]) -> float:
    peak = float("-inf")
    mdd = 0.0
    for v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return mdd


@dataclass
class BasisYearAttribution:
    year: int
    net_return: float


@dataclass
class BasisResult:
    """Decomposition of a dated-basis cash-and-carry run; components sum to ``net_return``.

    ``carry_pnl`` is the delta-neutral directional residual = captured basis convergence
    (the edge). ``roll_cost`` / ``fee_cost`` / ``liq_cost`` are the three frictions the
    pre-registered criteria (``docs/rv-c-plan.md`` §3) must survive.
    """

    n_bars: int
    net_return: float
    carry_pnl: float          # delta-neutral residual = basis convergence captured (over capital)
    roll_cost: float          # quarterly roll fees: close expiring + open next (>= 0)
    fee_cost: float           # open + rebalance + liq-reopen taker fees (>= 0)
    liq_cost: float           # physical liquidation tail: penalty + intrabar gap (>= 0)
    liq_events: int
    roll_count: int
    rebalance_count: int
    worst_basis: float        # max |F−S|/S seen (raw, for liq-risk sense)
    entry_basis_ann: float    # annualized basis at first bar (the edge we sold)
    max_drawdown: float
    deployed_fraction: float = 1.0   # A1: fraction of bars actually holding the position
    final_equity: float = 0.0
    per_year: list[BasisYearAttribution] = field(default_factory=list)
    curve: list[float] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        # No annualization here: it depends on the bar interval (daily vs hourly), which the
        # result doesn't carry. The caller annualizes with the right bars-per-year.
        won = sum(1 for y in self.per_year if y.net_return > 0)
        n = len(self.per_year)
        return (
            f"basis-carry net {self.net_return:+.2%}; "
            f"won {won}/{n}y; carry {self.carry_pnl:+.2%} / fees {self.fee_cost:.2%} / "
            f"roll {self.roll_cost:.2%} / liq {self.liq_cost:.2%} ({self.liq_events}x); "
            f"rolls {self.roll_count}, worst_basis {self.worst_basis:.1%}"
        )


def run_basis_carry(
    active: Sequence[ActiveBar],
    *,
    capital: float = 1.0,
    k_gross: float = 1.0,
    liq_leverage: float | None = 3.0,
    mm_rate: float = 0.005,
    liq_penalty: float = 0.015,
    rebalance_bars: int = 1,
    spot_taker: float = 0.0010,
    dated_taker: float = 0.0005,
    spot_maker: float = 0.0010,
    dated_maker: float = 0.0005,
    maker_open: bool = False,
    maker_roll: bool = False,
    maker_rebalance: bool = False,
    inverse: bool = False,
    min_ann_basis: float | None = None,
) -> BasisResult:
    """Equity-normalized dated-basis cash-and-carry: long spot + short the active quarterly.

    Notional is rebalanced to ``k_gross × equity`` every ``rebalance_bars`` (daily by default,
    which is also the liquidation margin-reference cadence). Each contract change in ``active``
    triggers a roll (close expiring future, open next; gap never booked, two-leg fee charged).
    The :class:`BasisResult` decomposition (``carry − roll − fee − liq``) sums to ``net_return``.

    ``inverse=True`` hardens the COIN-M reality (RV-C #1 hole): the dated short is a coin-margined
    *inverse* contract. Under daily rebalancing the short's **USD directional PnL is first-order
    identical** to the linear treatment -- short USD PnL ≈ −notional·return either way, and the
    notional is reset each bar -- so ``carry``/``fees`` are unchanged. The one material difference
    is the **liquidation trigger**: coin collateral appreciates during a pump, so an inverse short
    liquidates *later*, at ``P_liq/ref = (1 − mm) / (1 − 1/L)`` (L=3 → +49.3%) versus the linear
    ``1/L − mm`` (+32.8%). Inverse is thus *more* pump-robust; the linear path is conservative.

    **S2 fee model** (``maker_*`` flags, default off = all-taker): the open, the quarterly roll
    (5-day buffer = patient), and the daily rebalance (small, non-urgent delta) are all postable
    as **maker** limit orders, charged ``spot_maker``/``dated_maker`` when their flag is set. The
    liquidation re-open stays **taker** (forced/urgent). This is a *best-case* maker scenario --
    it assumes the resting orders fill; fill probability / adverse selection is the next study --
    so a pass under maker that fails under taker is a fee-relief *upper bound*, not a new verdict.

    **A1 basis-conditional deployment** (``min_ann_basis``, default ``None`` = always deployed):
    when set, the position is held only while the **annualized basis is fat** -- we deploy when it
    is ``>= min_ann_basis`` and stand flat in cash (earning 0, conservative) otherwise, skipping the
    thin / backwardation drag. The decision uses the *previous* bar's observed basis and transitions
    execute at the close (no look-ahead); each in/out pays a two-leg fee. Raises return-on-deployed-
    capital at the cost of idle time -- and adds a threshold parameter, so it MUST be re-validated by
    the S3 DSR/PBO harness (the LINK/LTC lesson: passing a gate ≠ surviving multiple testing).
    """

    if not active:
        raise ValueError("need at least one ActiveBar")

    so_fee = spot_maker if maker_open else spot_taker
    do_fee = dated_maker if maker_open else dated_taker
    roll_fee_rate = dated_maker if maker_roll else dated_taker
    reb_s_fee = spot_maker if maker_rebalance else spot_taker
    reb_d_fee = dated_maker if maker_rebalance else dated_taker

    if not liq_leverage:
        buffer = None
    elif inverse:
        # inverse short liq price ratio (coin-margined): P_liq/ref = (1 − mm)/(1 − 1/L)
        buffer = (1.0 - mm_rate) / (1.0 - 1.0 / liq_leverage) - 1.0
    else:
        buffer = 1.0 / liq_leverage - mm_rate

    ab0 = active[0]
    equity = capital
    gated = min_ann_basis is not None
    deployed = not gated                            # ungated: open at bar 0 as before
    n = len(active)
    fees = 0.0
    spot_base = short_base = 0.0
    prev_s = prev_d = ref_d = 0.0
    if deployed:
        notional = k_gross * equity
        spot_base = notional / ab0.spot.open
        short_base = notional / ab0.dated.open
        fees = notional * (so_fee + do_fee)         # open spot long + dated short
        equity -= fees
        prev_s, prev_d = ab0.spot.open, ab0.dated.open
        ref_d = ab0.dated.open                       # liquidation reference (set at rebalance/roll)

    carry_total = 0.0
    roll_cost = 0.0
    liq_total = 0.0
    liq_events = 0
    roll_count = 0
    rebalances = 0
    bars_deployed = 0
    worst_basis = abs(ab0.dated.close - ab0.spot.close) / ab0.spot.close
    curve: list[float] = []
    yr_first: dict[int, float] = {}
    yr_last: dict[int, float] = {}

    for i, ab in enumerate(active):
        s_close, d_close = ab.spot.close, ab.dated.close

        if deployed:
            bars_deployed += 1

            # quarterly roll: close the expiring future, open the next on its own price. The price
            # gap between contracts is NOT directional PnL -- only the two-leg roll fee is.
            if i > 0 and ab.is_roll and short_base > 0.0:
                d_open_new = ab.dated.open
                new_short_base = (spot_base * prev_s) / d_open_new   # match spot notional, Δ-neutral
                fee = short_base * prev_d * roll_fee_rate + new_short_base * d_open_new * roll_fee_rate
                equity -= fee
                roll_cost += fee
                roll_count += 1
                short_base = new_short_base
                prev_d = d_open_new
                ref_d = d_open_new

            # directional (basis) pnl this bar on held bases; spot move cancels, basis remains
            dpnl = spot_base * (s_close - prev_s) - short_base * (d_close - prev_d)
            equity += dpnl
            carry_total += dpnl

            # liquidation: intrabar pump past the liq price set at the last rebalance/roll (H3 §8.6).
            # Short force-closed (margin lost = penalty + gap, bounded by notional), carry re-opened
            # on remaining equity at the current price -- as a real account would after liquidation.
            if buffer is not None and buffer > 0.0 and short_base > 0.0:
                if ab.dated.high / ref_d - 1.0 > buffer:
                    liq_price = ref_d * (1.0 + buffer)
                    gap = max(0.0, ab.dated.high / liq_price - 1.0)
                    cost = short_base * liq_price * (liq_penalty + gap)
                    equity -= cost
                    liq_total += cost
                    liq_events += 1
                    if equity > 0.0:
                        notional = k_gross * equity
                        reopen_fee = notional * (spot_taker + dated_taker)  # forced/urgent: taker
                        equity -= reopen_fee
                        fees += reopen_fee
                        spot_base = notional / s_close
                        short_base = notional / d_close
                        ref_d = d_close
                    else:
                        spot_base = short_base = 0.0

            prev_s, prev_d = s_close, d_close

        # A1 transition + (when staying deployed) the periodic rebalance, decided at this close.
        if gated and i + 1 < n:
            want = ab.annualized_basis >= min_ann_basis
            if want and not deployed and equity > 0.0:            # ENTER at this close
                notional = k_gross * equity
                spot_base = notional / s_close
                short_base = notional / d_close
                fee = notional * (so_fee + do_fee)
                equity -= fee
                fees += fee
                prev_s, prev_d = s_close, d_close
                ref_d = d_close
                deployed = True
            elif not want and deployed:                          # EXIT to cash at this close
                fee = spot_base * s_close * so_fee + short_base * d_close * do_fee
                equity -= fee
                fees += fee
                spot_base = short_base = 0.0
                deployed = False
            elif deployed:                                       # staying in: normal rebalance
                _rebalance = (i + 1) % rebalance_bars == 0
                if _rebalance and equity > 0.0 and short_base > 0.0:
                    notional = k_gross * equity
                    new_spot_base = notional / s_close
                    new_short_base = notional / d_close
                    fee = (abs(new_spot_base - spot_base) * s_close * reb_s_fee
                           + abs(new_short_base - short_base) * d_close * reb_d_fee)
                    equity -= fee
                    fees += fee
                    spot_base, short_base = new_spot_base, new_short_base
                    ref_d = d_close
                    rebalances += 1
        elif deployed and (i + 1) % rebalance_bars == 0 and equity > 0.0 and short_base > 0.0:
            # ungated path (or last bar): periodic rebalance to k_gross × equity
            notional = k_gross * equity
            new_spot_base = notional / s_close
            new_short_base = notional / d_close
            fee = (abs(new_spot_base - spot_base) * s_close * reb_s_fee
                   + abs(new_short_base - short_base) * d_close * reb_d_fee)
            equity -= fee
            fees += fee
            spot_base, short_base = new_spot_base, new_short_base
            ref_d = d_close
            rebalances += 1

        worst_basis = max(worst_basis, abs(d_close - s_close) / s_close)
        curve.append(equity)
        y = _year_of(ab.spot.ts_ms)
        if y not in yr_first:
            yr_first[y] = equity
        yr_last[y] = equity

    per_year = [
        BasisYearAttribution(
            year=y, net_return=yr_last[y] / yr_first[y] - 1.0 if yr_first[y] else 0.0
        )
        for y in sorted(yr_first)
    ]
    return BasisResult(
        n_bars=len(active),
        net_return=equity / capital - 1.0,
        carry_pnl=carry_total / capital,
        roll_cost=roll_cost / capital,
        fee_cost=fees / capital,
        liq_cost=liq_total / capital,
        liq_events=liq_events,
        roll_count=roll_count,
        rebalance_count=rebalances,
        worst_basis=worst_basis,
        entry_basis_ann=ab0.annualized_basis,
        max_drawdown=_max_drawdown(curve),
        deployed_fraction=bars_deployed / n if n else 0.0,
        final_equity=equity,
        per_year=per_year,
        curve=curve,
    )
