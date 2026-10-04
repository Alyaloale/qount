"""Batched torch env: :func:`env.simulate` for B worlds at once (design §4, §5, §6, §10).

Same accounting (shares, unadjusted prices, distributions credited to cash, decide at close
t, fill at the t+1 open), same §5 constraint order and §6 cost model as the numpy env.

- ``exact=True``: lot rounding as in numpy; :mod:`tests.test_etf_trader_torch` checks
  day-by-day parity with ``env.simulate`` (float64).
- ``exact=False`` (training): fractional shares so a step is differentiable end to end
  (Deep Hedging, §4).  Market-rule masks, reduce-only flags and the de-risk state machine
  carry no gradient; the turnover-budget ledger does (spending budget early leaves less later).

Every divide uses a guarded denominator so the unused branch of ``where`` cannot produce
NaN gradients; impact is written as ``k·σ·|N|^1.5/√ADV`` (finite gradient at 0).
Torch is imported here only: install it on the research GPU host, never in production.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch

from . import constraints as C
from .costs import CostParams
from .env import MarketData
from .universe import Account

EPS = C.EPS


def _t(x, dtype, device):
    return torch.as_tensor(np.asarray(x), dtype=dtype, device=device)


def fill_cost(notional, price, adv, sigma, series, p, half_static, spread_mult, k_impact, mult):
    """Stateless tensor cost calculation; shared by eager and fused training kernels."""
    size = notional.abs()
    traded = size > 0
    commission = torch.where(traded, torch.clamp_min(p.commission_rate * size, p.min_fee), torch.zeros_like(size))
    shares = size / price
    fees = torch.where(notional < 0, p.sec_fee_rate * size + torch.clamp_max(p.taf_per_share * shares, p.taf_max),
                       torch.zeros_like(size))
    base = half_static if series is None else spread_mult * series
    half = torch.maximum(base.expand_as(price), 0.5 * p.tick / price)
    spread = half * size
    safe_adv = torch.where(adv > 0, adv, torch.ones_like(adv))
    impact = torch.where(adv > 0, k_impact * sigma * size.pow(1.5) / safe_adv.sqrt(), torch.zeros_like(size))
    return mult * (commission + fees + spread + impact)


@dataclass
class Batch:
    """(B, T, n) market panels (cash_return (B, T)); rows are the episode's trading rows."""

    close_adj: torch.Tensor
    close: torch.Tensor
    open: torch.Tensor
    adv: torch.Tensor
    sigma: torch.Tensor
    cash_return: torch.Tensor
    spread: torch.Tensor | None
    reduce_only: torch.Tensor  # bool
    buy_blocked: torch.Tensor  # bool
    suspended: torch.Tensor  # bool

    @property
    def shape(self) -> tuple[int, int, int]:
        return tuple(self.close.shape)  # type: ignore[return-value]

    @staticmethod
    def from_market(datas: list[MarketData], reduce_only: list[np.ndarray], *, start: int = 0, stop: int | None = None,
                    dtype=torch.float64, device="cpu") -> "Batch":
        s = slice(start, stop)

        def stack(name):
            return _t(np.stack([getattr(d, name)[s] for d in datas]), dtype, device)

        def stack_bool(arrs):
            return torch.as_tensor(np.stack([np.asarray(a, bool)[s] for a in arrs]), device=device)

        T, n = datas[0].close[s].shape
        zeros = [np.zeros((datas[0].T, n), bool)] * len(datas)
        spread = stack("spread") if all(d.spread is not None for d in datas) else None
        return Batch(
            close_adj=stack("close_adj"), close=stack("close"), open=stack("open"), adv=stack("adv"),
            sigma=stack("sigma"), cash_return=_t(np.stack([d.cash_return[s] for d in datas]), dtype, device),
            spread=spread, reduce_only=stack_bool(reduce_only),
            buy_blocked=stack_bool([d.buy_blocked if d.buy_blocked is not None else z for d, z in zip(datas, zeros)]),
            suspended=stack_bool([d.suspended if d.suspended is not None else z for d, z in zip(datas, zeros)]),
        )


@dataclass
class Obs:
    t: int
    weights: torch.Tensor  # (B, n) close weights
    equity: torch.Tensor  # (B,)
    gross_cap: torch.Tensor  # (B,)
    drawdown: torch.Tensor  # (B,)
    derisked: torch.Tensor  # (B,) bool
    used_voluntary: torch.Tensor  # (B,)
    budget: float


class TorchEnv:
    def __init__(
        self,
        batch: Batch,
        account: Account,
        costs: CostParams,
        *,
        exact: bool = False,
        initial_equity: float = 1_000_000.0,
        cost_multiplier: float = 1.0,
        spread_mult: torch.Tensor | None = None,  # (B,) per-world randomization (§6)
        impact_mult: torch.Tensor | None = None,
        derisk: C.DeRisk | None = None,
        budget: float | None = None,
    ):
        self.b = batch
        self.acct = account
        self.exact = exact
        B, T, n = batch.shape
        self.B, self.T, self.n = B, T, n
        dt, dev = batch.close.dtype, batch.close.device
        self.dtype, self.device = dt, dev
        ones = torch.ones(B, dtype=dt, device=dev)
        sm = ones if spread_mult is None else spread_mult.to(dt)
        im = ones if impact_mult is None else impact_mult.to(dt)
        self.spread_mult = (costs.spread_mult * sm)[:, None]
        self.half_static = _t(costs.half_spread, dt, dev)[None, :] * sm[:, None]
        self.k_impact = (costs.k_impact * im)[:, None]
        self.costs = costs
        self.cost_fn = fill_cost
        self.mult = float(cost_multiplier)
        dr = derisk or C.DeRisk()
        self.d1, self.d2, self.cap1, self.cap2 = dr.d1, dr.d2, dr.cap1, dr.cap2
        self.min_days, self.lookback = dr.min_days, dr.lookback
        self.U = float(account.turnover_budget if budget is None else budget)
        self.window = C.TURNOVER_WINDOW
        self.groups = [list(g) for g in account.group_indices()]
        self.reset(initial_equity)

    # ------------------------------------------------------------------ state
    def reset(self, initial_equity: float = 1_000_000.0) -> None:
        B, n, dt, dev = self.B, self.n, self.dtype, self.device
        self.t = 0
        self.shares = torch.zeros(B, n, dtype=dt, device=dev)
        self.cash = torch.full((B,), float(initial_equity), dtype=dt, device=dev)
        self.equity = self.cash.clone()
        self.peak = torch.full((B,), float("nan"), dtype=dt, device=dev)
        self.cap = torch.ones(B, dtype=dt, device=dev)
        self.days_capped = torch.zeros(B, dtype=torch.long, device=dev)
        self.hist = torch.zeros(B, self.lookback + 1, dtype=dt, device=dev)
        self.n_hist = 0
        self.vol_ring = torch.zeros(B, self.window - 1, dtype=dt, device=dev)
        self.frc_ring = torch.zeros(B, self.window - 1, dtype=dt, device=dev)
        self.n_ring = 0

    def detach_(self) -> None:
        """Truncated BPTT boundary: keep values, drop the graph."""
        for name in ("shares", "cash", "equity", "vol_ring", "frc_ring"):
            setattr(self, name, getattr(self, name).detach())

    @property
    def used_voluntary(self) -> torch.Tensor:
        return self.vol_ring.sum(dim=1)

    @property
    def used_forced(self) -> torch.Tensor:
        return self.frc_ring.sum(dim=1)

    # ------------------------------------------------------------------ §5.2 de-risk (no gradient)
    @torch.no_grad()
    def _derisk(self, eq: torch.Tensor) -> torch.Tensor:
        L1 = self.lookback + 1
        k = self.n_hist
        self.hist[:, k % L1] = eq
        self.n_hist += 1
        self.peak = torch.where(torch.isnan(self.peak), eq, torch.maximum(self.peak, eq))
        dd = 1.0 - eq / self.peak
        capped = self.cap < 1.0
        self.days_capped = torch.where(capped, self.days_capped + 1, self.days_capped)
        full = self.n_hist > self.lookback
        oldest = self.hist[:, self.n_hist % L1] if full else eq
        trailing = torch.full_like(capped, full) & (eq / oldest - 1.0 > 0)
        rel1 = capped & (dd <= self.d1 / 2)
        rel2 = capped & ~rel1 & (self.days_capped >= self.min_days) & trailing
        rel = rel1 | rel2
        self.cap = torch.where(rel, torch.ones_like(self.cap), self.cap)
        self.days_capped = torch.where(rel, torch.zeros_like(self.days_capped), self.days_capped)
        self.peak = torch.where(rel2, eq, self.peak)
        new = torch.where(dd > self.d2, torch.full_like(dd, self.cap2),
                          torch.where(dd > self.d1, torch.full_like(dd, self.cap1), torch.ones_like(dd)))
        eng = ~rel2 & (new < self.cap)
        self.days_capped = torch.where(eng & (self.cap == 1.0), torch.zeros_like(self.days_capped), self.days_capped)
        self.cap = torch.where(eng, new, self.cap)
        return self.cap.clone()

    # ------------------------------------------------------------------ day loop
    def observe(self) -> Obs:
        """Close t: mark weights, update the de-risk state (call once per day, then :meth:`step`)."""
        t = self.t
        if t >= self.T - 1:
            raise IndexError("episode finished")
        w = self.shares * self.b.close[:, t] / self.equity[:, None]
        cap = self._derisk(self.equity.detach())
        dd = 1.0 - self.equity.detach() / self.peak
        return Obs(t=t, weights=w, equity=self.equity, gross_cap=cap, drawdown=dd, derisked=cap < 1.0,
                   used_voluntary=self.used_voluntary, budget=self.U)

    @staticmethod
    def _scale_to_gross(w: torch.Tensor, cap: torch.Tensor) -> torch.Tensor:
        g = w.sum(dim=1)
        scale = torch.where(g > cap + EPS, cap / g.clamp_min(EPS), torch.ones_like(g))
        return w * scale[:, None]

    def step(self, target: torch.Tensor, band: torch.Tensor | float = 0.0, kappa: torch.Tensor | float = 1.0,
             hold: torch.Tensor | None = None) -> dict[str, torch.Tensor]:
        """Fill at the t+1 open and mark the t+1 close. Returns per-world day outputs."""
        b, t, u, acct = self.b, self.t, self.t + 1, self.acct
        B, n, dt, dev = self.B, self.n, self.dtype, self.device
        band = torch.as_tensor(band, dtype=dt, device=dev).expand(B)
        kappa = torch.as_tensor(kappa, dtype=dt, device=dev).expand(B)
        cap = self.cap
        opn = b.open[:, u]
        valid_open = torch.isfinite(opn) & (opn > 0)
        mark = torch.where(valid_open, opn, b.close[:, t])
        eq_open = self.cash + (self.shares * mark).sum(dim=1)
        current = self.shares * mark / eq_open[:, None]
        if hold is not None:
            hold_w = self._scale_to_gross(current.clamp_min(0.0), torch.ones_like(cap))
            target = torch.where(hold[:, None], hold_w, target)
            band = torch.where(hold, torch.zeros_like(band), band)
            kappa = torch.where(hold, torch.ones_like(kappa), kappa)

        # 1. liquidity: reduce-only and the 3-day capacity cap
        adv = torch.nan_to_num(b.adv[:, t], nan=0.0).clamp_min(0.0)
        capacity = torch.minimum(torch.full_like(adv, acct.single_cap),
                                 C.CAPACITY_DAYS * C.MAX_ADV_FRACTION * adv / eq_open[:, None])
        tgt = torch.where(b.reduce_only[:, t], torch.minimum(target, current), target)
        tgt = torch.minimum(tgt, capacity)
        # 2. de-risk: forced sells bring the book to the cap
        tgt = self._scale_to_gross(tgt, cap)
        base = self._scale_to_gross(current, cap)
        forced = base - current
        # 3. soft band, then keep gross within the cap (buys only)
        d = tgt - base
        vol = kappa[:, None] * torch.sign(d) * torch.relu(d.abs() - band[:, None])
        buys = vol.clamp_min(0.0)
        excess = base.sum(dim=1) + vol.sum(dim=1) - cap
        total_buy = buys.sum(dim=1)
        keep = (1.0 - excess / total_buy.clamp_min(EPS)).clamp_min(0.0)
        do = (excess > EPS) & (total_buy > EPS)
        vol = torch.where(do[:, None] & (vol > 0), vol * keep[:, None], vol)
        # 4. turnover budget (voluntary only)
        need = 0.5 * vol.abs().sum(dim=1)
        need_f = 0.5 * forced.abs().sum(dim=1)
        used_v, used_f = self.used_voluntary, self.used_forced
        room_v = self.U - used_v
        room_total = C.FORCED_TOTAL_MULTIPLE * self.U - used_v - used_f - need_f
        room = torch.minimum(room_v, room_total).clamp_min(0.0)
        scale = torch.where(need <= room + EPS, torch.ones_like(need), room / need.clamp_min(EPS))
        vol = vol * scale[:, None]
        breach = room_total < -EPS
        # 5. market rules
        delta = forced + vol
        ok = ~b.suspended[:, u] & valid_open
        can_buy, can_sell = ok.clone(), ok.clone()
        if acct.price_limit is not None:
            prev = b.close[:, t]
            tick = acct.tick
            up = torch.round(prev * (1 + acct.price_limit) / tick) * tick
            down = torch.round(prev * (1 - acct.price_limit) / tick) * tick
            can_buy = can_buy & (opn < up - 0.5 * tick)
            can_sell = can_sell & (opn > down + 0.5 * tick)
        can_buy = can_buy & ~b.buy_blocked[:, u]
        voided = ((delta > EPS) & ~can_buy) | ((delta < -EPS) & ~can_sell)
        delta = torch.where(voided, torch.zeros_like(delta), delta)
        notional = delta * eq_open[:, None]
        limit = C.MAX_ADV_FRACTION * adv
        executed_notional = torch.minimum(torch.maximum(notional, -limit), limit)
        price = torch.where(valid_open, opn, torch.ones_like(opn))
        desired = executed_notional / price
        sellable = self.shares.clamp_min(0.0)
        desired = torch.maximum(desired, -sellable)
        if self.exact and not acct.fractional_shares:
            lot = float(acct.lot_size)
            lots = torch.trunc(desired / lot) * lot
            full_exit = (desired < 0) & torch.isclose(-desired, sellable)
            sh = torch.where(full_exit, -sellable, lots)
        else:
            sh = desired
        sh = torch.where(voided, torch.zeros_like(sh), sh)
        executed = sh * price / eq_open[:, None]
        same = torch.sign(executed) == torch.sign(forced)
        forced_exec = torch.where(same, torch.minimum(executed.abs(), forced.abs()), torch.zeros_like(executed))
        ft = 0.5 * forced_exec.sum(dim=1)
        vt = 0.5 * executed.abs().sum(dim=1) - ft
        k = self.n_ring % (self.window - 1)
        self.vol_ring = self.vol_ring.clone()
        self.frc_ring = self.frc_ring.clone()
        self.vol_ring[:, k] = vt
        self.frc_ring[:, k] = ft
        self.n_ring += 1

        # §6 costs on the fill notional at the mark
        fill = sh * mark
        fee = self._cost(fill, mark, adv, b.sigma[:, t], None if b.spread is None else b.spread[:, t]).sum(dim=1)
        shares = self.shares + sh
        cash = self.cash - fill.sum(dim=1) - fee
        # close t+1: cash carry, distributions, mark
        cash = cash * (1.0 + b.cash_return[:, u])
        adj_ret = b.close_adj[:, u] / b.close_adj[:, t] - 1.0
        px_ret = b.close[:, u] / b.close[:, t] - 1.0
        dist = torch.nan_to_num(shares * b.close[:, t] * (adj_ret - px_ret))
        cash = cash + dist.sum(dim=1)
        equity = cash + torch.nan_to_num(shares * b.close[:, u]).sum(dim=1)
        ret = equity / self.equity - 1.0
        self.shares, self.cash, self.equity = shares, cash, equity
        self.t = u
        return {"ret": ret, "equity": equity, "cost": fee, "voluntary_turnover": vt, "forced_turnover": ft,
                "voided": voided, "forced_breach": breach, "budget_scale": scale, "gross_cap": cap}

    def _cost(self, notional, price, adv, sigma, series):
        return self.cost_fn(notional, price, adv, sigma, series, self.costs,
                            self.half_static, self.spread_mult, self.k_impact, self.mult)
