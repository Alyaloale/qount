"""Four-layer structural market generator (design §7.1).

Layer 1 macro: output gap and inflation AR(1) toward regime targets, smoothed Taylor-rule
policy rate, a 5-state regime chain per economy with crisis contagion.
Layer 2 fundamentals: yields blend the Taylor target and a long-run anchor plus a term
premium; bond ETF return = carry − D·Δy + ½·C·Δy².  Equity log P/D = macro target (falls
when ERP or the real 10y rise) + mispricing gap; dividends are the identity residual.
Gold follows real rates and crisis flight, commodities inflation and growth, FX follows UIP.
Layer 3 mechanisms (``FactorParams``): delayed news absorption (momentum), P/D gap reversion
partly through prices (value), leverage-constraint ERP haircut on high β (low risk).  The
liquidity premium is zero by construction.
Layer 4 microstructure: GJR-GARCH + Student-t noise, compensated crisis jumps with partial
rebound, traded value rising with vol and |r|, spreads rising with vol and falling with
volume, liquidity droughts, CN ±10% limits on unadjusted prices with carry-over, long
holiday closures, QDII premium and quota.

Numpy, one world at a time; a batched/torch version for training must match it (§10).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..env import MarketData
from .params import YEAR, WorldParams
from .specs import (
    BOND,
    COMMODITY,
    CRISIS,
    EQUITY,
    GOLD,
    REGIME_EQ_VOL,
    REGIME_GAP_TARGET,
    REGIME_GROWTH_VOL,
    REGIME_INFL_VOL,
    REGIME_JUMP,
    REGIME_PI_SHIFT,
    AccountSpec,
    ten_year_weight,
    transition_matrix,
)
from .stylized import WorldSample

EWMA_LAMBDA = 0.94
ADV_WINDOW = 20
REBOUND_DAYS = 21.0
GARCH_VOL_CAP = 6.0  # conditional daily σ ≤ 6 × the regime-free base σ (fat tails can explode GJR)
HOLIDAY_ROWS = (25, 190)  # trading-day offsets in each year after which CN closes


def ar_coef(halflife_days: float) -> float:
    return float(0.5 ** (1.0 / max(halflife_days, 1e-9)))


@dataclass(frozen=True)
class Truth:
    """Latent state for oracle / evaluation. Never an input to the trader."""

    regime: np.ndarray  # (T, 2) home, foreign
    gap: np.ndarray  # (T, 2)
    pi: np.ndarray  # (T, 2)
    rate: np.ndarray  # (T, 2) policy short rate
    y10: np.ndarray  # (T, 2)
    erp: np.ndarray  # (T, 2)
    pe: np.ndarray  # (T, n) true PE (no observation noise), NaN for non-equity
    mu: np.ndarray  # (T, n) expected next-day arithmetic return (local-to-home, account ccy)
    var: np.ndarray  # (T, n) conditional next-day variance
    quota: np.ndarray  # (T,) bool
    drought: np.ndarray  # (T, n) bool
    fx_log: np.ndarray  # (T,) log change of home per foreign currency


@dataclass(frozen=True)
class World:
    spec: AccountSpec
    params: WorldParams
    data: MarketData
    valuation: np.ndarray  # (T, n) observed PE for equities, yield for bonds, NaN otherwise
    traded_value: np.ndarray  # (T, n) daily traded value
    truth: Truth
    start: int  # first trading row (after warmup)

    def sample(self, from_row: int | None = None) -> WorldSample:
        s = self.start if from_row is None else from_row
        adj = self.data.close_adj[s:]
        log_r = np.diff(np.log(adj), axis=0)
        eq = np.array([a.kind == EQUITY for a in self.spec.assets])
        dy = np.log(self.params.payout_ratio / self.truth.pe[s + 1 :, eq])
        return WorldSample(log_r, eq, self.traded_value[s + 1 :], dy)


def _regime_step(state: int, P_cum: np.ndarray, u: float) -> int:
    return int(np.searchsorted(P_cum[state], u, side="right"))


def simulate_world(
    spec: AccountSpec, params: WorldParams, years: float, warmup_years: float = 10.0, *, backend: str = "auto",
) -> World:
    """Simulate ``warmup_years + years`` of daily data; ``World.start`` marks the first trading row.

    ``backend``: ``"numpy"`` (reference loop), ``"native"`` (C++ kernel, error if it cannot
    build) or ``"auto"`` (native when a compiler is available).  Both consume the same numpy
    draws, so a seed gives the same world up to floating-point rounding.
    """
    T = int(round((warmup_years + years) * YEAR)) + 1
    start = int(round(warmup_years * YEAR))
    rng = np.random.default_rng(params.seed)
    econ = (params.home, params.foreign)
    fp, ap, mp = params.factors, params.assets, params.micro
    n = spec.n
    E = 2  # 0 home, 1 foreign

    def arr(name: str) -> np.ndarray:
        return np.array([getattr(e, name) for e in econ], dtype=float)

    r_star, pi_star, i_floor = arr("r_star"), arr("pi_star"), arr("i_floor")
    phi_pi, phi_x = arr("phi_pi"), arr("phi_x")
    a_rate = np.array([ar_coef(e.rate_smooth_hl) for e in econ])
    a_gap = np.array([ar_coef(e.gap_hl) for e in econ])
    a_pi = np.array([ar_coef(e.pi_hl) for e in econ])
    a_tp = np.array([ar_coef(e.tp_hl) for e in econ])
    a_erp = np.array([ar_coef(e.erp_hl) for e in econ])
    gap_sd, pi_sd, tp_sd = arr("gap_sigma"), arr("pi_sigma"), arr("tp_sigma")
    s_gap, s_pi, s_tp = gap_sd * np.sqrt(1 - a_gap**2), pi_sd * np.sqrt(1 - a_pi**2), tp_sd * np.sqrt(1 - a_tp**2)
    tp_mean, erp_bar = arr("tp_mean"), arr("erp")
    erp_gap, erp_pi, erp_crisis = arr("erp_gap"), arr("erp_pi"), arr("erp_crisis")
    dur_eq, dy_bar = arr("equity_duration"), arr("dy_bar")
    div_load = arr("div_gap_load")
    w10 = np.array([ten_year_weight(10.0, e.curve_hl_years) for e in econ])
    eq_var_d = arr("eq_vol") ** 2 / YEAR
    g_a, g_g, g_b = arr("garch_alpha"), arr("garch_gamma"), arr("garch_beta")
    t_df = arr("t_df")
    rho_gi = arr("rho_growth_infl")
    theta = arr("infl_passthrough")

    kind = np.array([a.kind for a in spec.assets])
    ec = np.array([0 if a.economy == "home" else 1 for a in spec.assets])
    fx = np.array([a.fx for a in spec.assets])
    qdii = np.array([a.qdii for a in spec.assets])
    beta = np.array([a.beta for a in spec.assets])
    idio_d = (params.idio_scale * np.array([a.idio_vol for a in spec.assets])) ** 2 / YEAR
    dur = np.array([a.duration for a in spec.assets])
    cvx = np.array([a.convexity for a in spec.assets])
    wm = np.array([ten_year_weight(a.maturity, econ[e].curve_hl_years) if a.kind == BOND else 0.0
                   for a, e in zip(spec.assets, ec)])
    mat_scale = np.array([min(a.maturity / 10.0, 1.3) if a.kind == BOND else 0.0 for a in spec.assets])
    is_eq, is_bd, is_au, is_cm = kind == EQUITY, kind == BOND, kind == GOLD, kind == COMMODITY
    lev = fp.leverage_cost / YEAR * (beta - 1.0)  # daily ERP haircut, high β earns less
    f_now = 1.0 - fp.momentum_share
    a_mom = np.exp(-1.0 / fp.momentum_lag_days)
    kappa = 1.0 - ar_coef(fp.value_reversion_hl)
    psi, q_cf = fp.value_return_share, fp.cashflow_share
    a_obs = ar_coef(fp.value_obs_hl)
    s_obs = fp.value_obs_noise * np.sqrt(1 - a_obs**2)

    # --- random draws (fixed order keeps worlds reproducible from the seed)
    P_cum = np.cumsum(transition_matrix(params.regime_duration_scale), axis=1)
    u_reg = rng.random((T, E))
    u_cont = rng.random(T)
    zg = rng.standard_normal((T, E))
    zi = rho_gi * zg + np.sqrt(1 - rho_gi**2) * rng.standard_normal((T, E))
    zg[:, 1] = params.rho_global * zg[:, 0] + np.sqrt(1 - params.rho_global**2) * zg[:, 1]
    z_tp = rng.standard_normal((T, E))
    z_eq = rng.standard_t(t_df, size=(T, E)) / np.sqrt(t_df / (t_df - 2))
    z_id = rng.standard_t(5.0, size=(T, n)) / np.sqrt(5.0 / 3.0)
    z_fx = rng.standard_normal(T)
    z_au = rng.standard_normal(T)
    z_cm = rng.standard_normal(T)
    z_pr = rng.standard_normal(T)
    z_obs = rng.standard_normal((T, n))
    u_jump = rng.random((T, E))
    z_jump = rng.standard_normal((T, E))
    u_quota = rng.random(T)
    u_drought = rng.random((T, n))
    z_on = rng.standard_normal((T, n))
    z_tv = rng.standard_normal((T, n))

    reopen = np.zeros(T)
    if spec.cn_calendar:
        for off, gap_days in zip(HOLIDAY_ROWS, params.micro.holiday_gap_days):
            rows = np.arange(off + 1, T, int(YEAR))
            reopen[rows] = gap_days * 5.0 / 7.0  # missed trading days of news
    news_mult = np.sqrt(1.0 + reopen)
    z_eq *= news_mult[:, None]
    z_id *= news_mult[:, None]
    z_fx *= news_mult
    z_au *= news_mult

    jump_comp = ap.crisis_jump_rate / YEAR * (np.exp(ap.crisis_jump_mean + 0.5 * ap.crisis_jump_sd**2) - 1.0)
    a_pr = ar_coef(mp.premium_hl)
    if _use_native(backend):
        from . import native

        econ_c = dict(
            R_STAR=r_star, PI_STAR=pi_star, I_FLOOR=i_floor, PHI_PI=phi_pi, PHI_X=phi_x, A_RATE=a_rate, A_GAP=a_gap,
            A_PI=a_pi, A_TP=a_tp, A_ERP=a_erp, GAP_SD=gap_sd, PI_SD=pi_sd, S_GAP=s_gap, S_PI=s_pi, S_TP=s_tp,
            TP_MEAN=tp_mean, ERP_BAR=erp_bar, ERP_GAP=erp_gap, ERP_PI=erp_pi, ERP_CRISIS=erp_crisis, DUR_EQ=dur_eq,
            DY_BAR=dy_bar, LOG_INV_DY=np.log(1 / dy_bar), DIV_LOAD=div_load, W10=w10, EQ_VAR_D=eq_var_d,
            G_A=g_a, G_G=g_g, G_B=g_b, PERSIST=g_a + g_g / 2 + g_b, H_CAP=GARCH_VOL_CAP**2 * eq_var_d, THETA=theta,
        )
        stale_i = np.array([a.stale for a in spec.assets])
        asset_c = dict(BETA=beta, IDIO_D=idio_d, DUR=dur, CVX=cvx, WM=wm, MAT_SCALE=mat_scale, LEV=lev, STALE=stale_i)
        kind_code = np.select([is_eq, is_bd, is_au, is_cm], [0, 1, 2, 3])
        aint = np.stack([ec, kind_code, fx.astype(int), qdii.astype(int)])
        scal = dict(
            F_NOW=f_now, A_MOM=a_mom, KAPPA=kappa, PSI=psi, Q_CF=q_cf, A_OBS=a_obs, S_OBS=s_obs,
            JUMP_RATE_D=ap.crisis_jump_rate / YEAR, JUMP_MEAN=ap.crisis_jump_mean, JUMP_SD=ap.crisis_jump_sd,
            REBOUND_SHARE=ap.rebound_share, FTQ=ap.flight_to_quality, JUMP_COMP=jump_comp,
            AU_VAR=ap.gold_vol**2 / YEAR, GOLD_RR=ap.gold_real_return, GOLD_RB=ap.gold_real_beta,
            GOLD_JS=ap.gold_jump_share, CM_VAR=ap.cmdty_vol**2 / YEAR, CM_ROLL=ap.cmdty_roll,
            CM_IB=ap.cmdty_infl_beta, CM_GB=ap.cmdty_gap_beta, A_PR=a_pr, QUOTA_PREM=mp.quota_premium,
            PREM_SIGMA=mp.premium_sigma, QUOTA_DAYS=mp.quota_days, QUOTA_RATE=mp.quota_rate,
            DROUGHT_DAYS=mp.drought_days, DROUGHT_RATE=mp.drought_rate, CONTAGION=params.contagion,
            PAYOUT=params.payout_ratio, FX_SCALE=econ[1].fx_vol / np.sqrt(YEAR), FX_VAR=econ[1].fx_vol ** 2 / YEAR,
            REBOUND_DAYS=REBOUND_DAYS, STALE_SHARE=params.stale_share, STALE_DECAY=params.stale_decay,
        )
        rtab = np.stack([REGIME_GAP_TARGET, REGIME_PI_SHIFT, REGIME_GROWTH_VOL, REGIME_INFL_VOL, REGIME_EQ_VOL,
                         REGIME_JUMP])
        init = np.stack([np.zeros(E), pi_star, np.maximum(i_floor, r_star + pi_star), tp_mean, np.zeros(E), eq_var_d])
        draws = dict(u_reg=u_reg, u_cont=u_cont, zg=zg, zi=zi, z_tp=z_tp, z_eq=z_eq, z_id=z_id, z_fx=z_fx, z_au=z_au,
                     z_cm=z_cm, z_pr=z_pr, z_obs=z_obs, u_jump=u_jump, z_jump=z_jump, u_quota=u_quota,
                     u_drought=u_drought)
        o = native.structural_loop(T, n, econ_c, asset_c, aint, scal, rtab, P_cum, init, draws)
        econ_out = dict(zip(("gap", "pi", "rate", "y10", "erp"), o["econ"]))
        return _finish(spec, params, start, is_eq, qdii, reopen, z_on, z_tv, o["logret"], o["dist"], o["var"],
                       o["quota"].astype(bool), o["drought"].astype(bool), o["pe"], o["pe_obs"], o["bond_y"],
                       o["mu"], o["fx_ret"], o["reg"].astype(int), econ_out, native=True)

    # --- state (numpy reference loop; the native kernel above is a line-by-line port)
    reg = np.zeros(E, dtype=int)
    gap = np.zeros(E)
    pi = pi_star.copy()
    rate = np.maximum(i_floor, r_star + pi_star)
    tp = tp_mean.copy()
    crisis_erp = np.zeros(E)
    h = eq_var_d.copy()  # GARCH conditional variance of the equity noise component
    eps_prev = np.zeros(E)
    persist = g_a + g_g / 2 + g_b
    rebound = np.zeros(E)
    pending = np.zeros(n)
    pd_gap = np.zeros(n)
    obs_noise = np.zeros(n)
    prem = np.zeros(n)
    stale_i = np.array([a.stale for a in spec.assets])
    stale_pending = np.zeros(n)  # delayed absorption buffer per asset
    a_stale = params.stale_decay
    quota = False
    drought = np.zeros(n, dtype=bool)

    def macro(gap, pi, tp, crisis_erp):
        target = np.maximum(i_floor, r_star + pi + phi_pi * (pi - pi_star) + phi_x * gap)
        pi_e = pi_star + theta * (pi - pi_star)  # anchored long-run inflation expectation
        anchor = r_star + pi_e
        y10 = w10 * anchor + (1 - w10) * target + tp
        real10 = y10 - pi_e
        erp = erp_bar + erp_gap * gap / gap_sd + erp_pi * (pi - pi_star) / pi_sd + crisis_erp
        pd_t = -dur_eq * ((erp - erp_bar) + (real10 - (r_star + tp_mean)))
        return target, anchor, y10, real10, erp, pd_t

    target, anchor, y10, real10, erp, pd_t = macro(gap, pi, tp, crisis_erp)
    out_reg = np.zeros((T, E), dtype=int)
    out = {k: np.zeros((T, E)) for k in ("gap", "pi", "rate", "y10", "erp")}
    logret = np.zeros((T, n))
    dist = np.zeros((T, n))
    pe = np.full((T, n), np.nan)
    pe_obs = np.full((T, n), np.nan)
    bond_y = np.full((T, n), np.nan)
    mu = np.zeros((T, n))
    var = np.zeros((T, n))
    quota_path = np.zeros(T, dtype=bool)
    drought_path = np.zeros((T, n), dtype=bool)
    fx_ret = np.zeros(T)

    def bond_yield(anchor, target, tp):
        return (wm * anchor[ec] + (1 - wm) * target[ec] + tp[ec] * mat_scale)

    by = bond_yield(anchor, target, tp)

    for t in range(T):
        # Layer 1: regime chain with symmetric crisis contagion
        if t > 0:
            new = np.array([_regime_step(reg[e], P_cum, u_reg[t, e]) for e in range(E)])
            for e in range(E):
                if new[e] == CRISIS and reg[e] != CRISIS and new[1 - e] != CRISIS and u_cont[t] < params.contagion:
                    new[1 - e] = CRISIS
            reg = new
        gv, iv = REGIME_GROWTH_VOL[reg], REGIME_INFL_VOL[reg]
        prev = dict(gap=gap, pi=pi, tp=tp, y10=y10, real10=real10, erp=erp, pd_t=pd_t, by=by, rate=rate)
        gap = a_gap * gap + (1 - a_gap) * REGIME_GAP_TARGET[reg] * gap_sd + s_gap * gv * zg[t]
        pi_target = pi_star + REGIME_PI_SHIFT[reg] * pi_sd
        pi = a_pi * pi + (1 - a_pi) * pi_target + s_pi * iv * zi[t]
        # Crisis jumps (compensated; part of each jump rebounds over ~a month)
        lam = ap.crisis_jump_rate / YEAR * REGIME_JUMP[reg]
        jump = np.where(u_jump[t] < lam, ap.crisis_jump_mean + ap.crisis_jump_sd * z_jump[t], 0.0)
        drip = rebound / REBOUND_DAYS
        rebound = rebound - drip - ap.rebound_share * jump
        jump_term = jump + drip - jump_comp * REGIME_JUMP[reg]
        tp = a_tp * tp + (1 - a_tp) * tp_mean + s_tp * iv * z_tp[t] + ap.flight_to_quality * jump
        crisis_erp = a_erp * crisis_erp + (1 - a_erp) * np.where(reg == CRISIS, erp_crisis, 0.0)
        target, anchor, y10, real10, erp, pd_t = macro(gap, pi, tp, crisis_erp)
        rate = a_rate * rate + (1 - a_rate) * target
        by = bond_yield(anchor, target, tp)

        # Layer 4 noise: GJR-GARCH on the equity noise component, long-run level by regime
        omega = eq_var_d * REGIME_EQ_VOL[reg] ** 2 * (1 - persist)
        h = np.minimum(omega + (g_a + g_g * (eps_prev < 0)) * eps_prev**2 + g_b * h, GARCH_VOL_CAP**2 * eq_var_d)
        eps = np.sqrt(h) * z_eq[t]
        eps_prev = eps
        dr_news = -dur_eq * ((erp - prev["erp"]) + (real10 - prev["real10"]))
        cf_news = div_load * (gap - prev["gap"])  # growth revises expected dividends
        common = dr_news + cf_news + eps + jump_term  # (E,)

        # Layer 2/3: equities (local currency)
        rf_d = prev["rate"] / YEAR
        news = beta * common[ec] + np.sqrt(idio_d * h[ec] / eq_var_d[ec]) * z_id[t]
        drip_m = (1 - a_mom) * pending
        pending = a_mom * pending + (1 - f_now) * news - drip_m
        eq_var = beta**2 * h[ec] + idio_d * h[ec] / eq_var_d[ec]
        drift = rf_d[ec] + beta * prev["erp"][ec] / YEAR - lev - psi * kappa * pd_gap
        r_eq = drift - 0.5 * eq_var + f_now * news + drip_m
        # Paid yield follows the actual P/D (capped); the P/D identity uses the Campbell–Shiller
        # linearization (constant dy_bar) so a cheap price does not feed back into itself.
        dy = np.minimum(np.exp(-(np.log(1 / dy_bar[ec]) + prev["pd_t"][ec] + pd_gap)), 0.15) / YEAR
        g_bar = rf_d[ec] + erp_bar[ec] / YEAR - dy_bar[ec] / YEAR
        # identity: gap_t = gap + r − dy − Δd − Δpd_target; Δd carries cash-flow news and
        # the non-price share of the reversion
        # macro cash-flow news is fully cash flow; the noise part splits by q
        noise_news = news - beta * (dr_news[ec] + cf_news[ec])
        dd = g_bar - lev - 0.5 * eq_var + beta * cf_news[ec] + q_cf * noise_news + (1 - psi) * kappa * pd_gap
        pd_gap = np.where(is_eq, pd_gap + r_eq - dy_bar[ec] / YEAR - dd - (pd_t[ec] - prev["pd_t"][ec]), 0.0)

        # FX: home per foreign, UIP drift
        fx_ret[t] = (prev["rate"][0] - prev["rate"][1]) / YEAR + econ[1].fx_vol / np.sqrt(YEAR) * z_fx[t]

        # Bonds, gold, commodity (local)
        dby = by - prev["by"]
        r_bd = prev["by"] / YEAR - dur * dby + 0.5 * cvx * dby**2
        au_var = ap.gold_vol**2 / YEAR
        r_au = (prev["pi"][ec] + ap.gold_real_return) / YEAR - 0.5 * au_var \
            + ap.gold_real_beta * (real10[ec] - prev["real10"][ec]) \
            - ap.gold_jump_share * jump_term[ec] + np.sqrt(au_var) * z_au[t]
        cm_var = ap.cmdty_vol**2 / YEAR
        r_cm = rf_d[ec] + ap.cmdty_roll / YEAR - 0.5 * cm_var \
            + ap.cmdty_infl_beta * (pi[ec] - prev["pi"][ec]) + ap.cmdty_gap_beta * (gap[ec] - prev["gap"][ec]) \
            + np.sqrt(cm_var) * z_cm[t]
        r = np.select([is_eq, is_bd, is_au, is_cm], [r_eq, r_bd, r_au, r_cm])
        r = r + np.where(fx, fx_ret[t], 0.0)

        # QDII premium and quota (shared across QDII columns)
        if t > 0:
            if quota:
                quota = u_quota[t] >= 1.0 / mp.quota_days
            else:
                quota = u_quota[t] < mp.quota_rate / YEAR
        prem_target = mp.quota_premium if quota else 0.0
        new_prem = np.where(qdii, a_pr * prem + (1 - a_pr) * prem_target + mp.premium_sigma * z_pr[t], 0.0)
        r = r + np.where(qdii, np.log1p(new_prem) - np.log1p(prem), 0.0)
        prem = new_prem

        # CN partial-adjustment/stale mechanism: delayed absorption with geometric decay
        theta_i = stale_i * params.stale_share  # asset-level delay share
        drip_stale = (1 - a_stale) * stale_pending
        stale_pending = a_stale * stale_pending + theta_i * r - drip_stale
        r = (1 - theta_i) * r + drip_stale

        drought = np.where(drought, u_drought[t] >= 1.0 / mp.drought_days, u_drought[t] < mp.drought_rate / YEAR)

        if t > 0:
            logret[t] = r
            dist[t] = np.select([is_eq & ~qdii, is_bd], [dy, prev["by"] / YEAR], 0.0)

        # Oracle view of tomorrow (arithmetic, account currency); tomorrow's regime ≈ today's
        rf_n = rate / YEAR
        fx_mu = (rate[0] - rate[1]) / YEAR
        fx_var = econ[1].fx_vol ** 2 / YEAR
        h_next = np.minimum(omega + (g_a + g_g * (eps < 0)) * eps**2 + g_b * h, GARCH_VOL_CAP**2 * eq_var_d)
        v_eq = beta**2 * h_next[ec] + idio_d * h_next[ec] / eq_var_d[ec]
        m_eq = rf_n[ec] + beta * erp[ec] / YEAR - lev - psi * kappa * pd_gap + (1 - a_mom) * pending
        m_eq = m_eq + np.where(qdii, (1 - a_pr) * (prem_target - prem), 0.0)
        v_bd = (dur * s_tp[ec] * iv[ec]) ** 2 * mat_scale**2 + (dur * (1 - wm) * phi_pi[ec] * s_pi[ec]) ** 2
        m_bd = by / YEAR - dur * (1 - a_tp[ec]) * (tp_mean[ec] - tp[ec]) * mat_scale
        m_au = (pi[ec] + ap.gold_real_return) / YEAR + ap.gold_jump_share * jump_comp * REGIME_JUMP[reg][ec]
        m_cm = rf_n[ec] + ap.cmdty_roll / YEAR
        mu[t] = np.select([is_eq, is_bd, is_au, is_cm], [m_eq, m_bd, m_au, m_cm]) + np.where(fx, fx_mu, 0.0)
        var[t] = np.select([is_eq, is_bd, is_au, is_cm], [v_eq, v_bd, np.full(n, au_var), np.full(n, cm_var)]) \
            + np.where(fx, fx_var, 0.0)

        obs_noise = a_obs * obs_noise + s_obs * z_obs[t]
        log_pd = np.log(1 / dy_bar[ec]) + pd_t[ec] + pd_gap
        pe[t] = np.where(is_eq, np.exp(log_pd) * params.payout_ratio, np.nan)
        pe_obs[t] = np.where(is_eq, pe[t] * np.exp(obs_noise), np.nan)
        bond_y[t] = np.where(is_bd, by, np.nan)
        out_reg[t] = reg
        for key, val in (("gap", gap), ("pi", pi), ("rate", rate), ("y10", y10), ("erp", erp)):
            out[key][t] = val
        quota_path[t] = quota
        drought_path[t] = drought

    return _finish(spec, params, start, is_eq, qdii, reopen, z_on, z_tv, logret, dist, var, quota_path,
                   drought_path, pe, pe_obs, bond_y, mu, fx_ret, out_reg, out, native=False)


def _use_native(backend: str) -> bool:
    if backend == "numpy":
        return False
    if backend not in ("auto", "native"):
        raise ValueError(f"unknown backend {backend!r}")
    from . import native

    if backend == "native":
        native.load()  # raises NativeUnavailable
        return True
    return native.available()


def _finish(spec, params, start, is_eq, qdii, reopen, z_on, z_tv, logret, dist, var, quota_path, drought_path,
            pe, pe_obs, bond_y, mu, fx_ret, out_reg, out, *, native: bool) -> "World":
    """Prices, liquidity and packaging shared by the numpy and native loops."""
    mp = params.micro
    close, close_adj = _price_paths(spec, logret, dist, start, native=native)
    realized = np.diff(np.log(close_adj), axis=0, prepend=np.log(close_adj[:1]))
    sigma0 = np.sqrt(np.maximum(var[0], 1e-8))
    # floor avoids 0 ** negative in the spread model
    sigma = np.maximum(_ewma_sigma(realized, sigma0, native=native), 1e-5)
    opn = _open_prices(spec, close, sigma, reopen, mp, z_on)
    tv, adv, spread = _liquidity(spec, mp, sigma, sigma0, realized, close, drought_path, z_tv, native=native)
    blocked = np.where(qdii[None, :], quota_path[:, None], False)

    data = MarketData(
        close_adj=close_adj,
        close=close,
        open=opn,
        adv=adv,
        sigma=sigma,
        cash_return=np.concatenate([[0.0], out["rate"][:-1, 0] / YEAR]),
        spread=spread,
        buy_blocked=blocked,
    )
    truth = Truth(
        regime=out_reg, gap=out["gap"], pi=out["pi"], rate=out["rate"], y10=out["y10"], erp=out["erp"],
        pe=pe, mu=mu, var=var, quota=quota_path, drought=drought_path, fx_log=fx_ret,
    )
    valuation = np.where(is_eq[None, :], pe_obs, bond_y)
    return World(spec=spec, params=params, data=data, valuation=valuation, traded_value=tv, truth=truth, start=start)


def _price_paths(spec: AccountSpec, logret, dist, start: int, *, native: bool = False):
    """Unadjusted close on the tick grid with CN limits (excess carried to later days).

    The level is chosen so the unrounded path is at ``price0`` on the first trading row,
    keeping tick size and lot value realistic when trading starts.
    """
    T, n = logret.shape
    tick, lim = spec.tick, spec.price_limit
    drift = np.cumsum(logret - np.log1p(dist), axis=0)[start]
    p0 = np.array([a.price0 for a in spec.assets]) * np.exp(-drift)
    close0 = np.maximum(np.round(p0 / tick) * tick, 100 * tick)
    if native:
        from . import native as _nat

        return _nat.price_paths(logret, dist, close0, tick, lim)
    close = np.empty((T, n))
    close_adj = np.empty((T, n))
    close[0] = close0
    close_adj[0] = close[0]
    carry = np.zeros(n)
    for t in range(1, T):
        # Price return excludes the distribution paid out that day (adjusted = price + dist).
        move = logret[t] - np.log1p(dist[t]) + carry
        want = close[t - 1] * np.exp(move)
        if lim is not None:
            up = np.maximum(np.round(close[t - 1] * (1 + lim) / tick) * tick, close[t - 1] + tick)
            dn = np.maximum(np.round(close[t - 1] * (1 - lim) / tick) * tick, tick)
            want = np.clip(want, dn, up)
        c = np.maximum(np.round(want / tick) * tick, tick)
        carry = move - np.log(c / close[t - 1])
        close[t] = c
        close_adj[t] = close_adj[t - 1] * (c / close[t - 1]) * (1 + dist[t])
    return close, close_adj


def _open_prices(spec: AccountSpec, close, sigma, reopen, mp, z_on):
    """Open = previous close × overnight share of the day's move + noise (lagged σ)."""
    tick, lim = spec.tick, spec.price_limit
    day = np.diff(np.log(close), axis=0, prepend=np.log(close[:1]))
    share = np.minimum(mp.overnight_share * (1 + reopen), 0.9)[:, None]
    lag_sigma = np.vstack([sigma[:1], sigma[:-1]])
    on = share * day + mp.overnight_noise * lag_sigma * z_on
    prev = np.vstack([close[:1], close[:-1]])
    opn = prev * np.exp(on)
    if lim is not None:
        opn = np.clip(opn, np.round(prev * (1 - lim) / tick) * tick, np.round(prev * (1 + lim) / tick) * tick)
    return np.maximum(np.round(opn / tick) * tick, tick)


def _ewma_sigma(r: np.ndarray, sigma0: np.ndarray, *, native: bool = False) -> np.ndarray:
    """PIT EWMA daily vol known at each close (includes that day's return)."""
    if native:
        from . import native as _nat

        return _nat.ewma_sigma(r, sigma0, EWMA_LAMBDA)
    out = np.empty_like(r)
    v = sigma0**2
    for t in range(r.shape[0]):
        if t > 0:
            v = EWMA_LAMBDA * v + (1 - EWMA_LAMBDA) * r[t] ** 2
        out[t] = np.sqrt(v)
    return out


def _liquidity(spec: AccountSpec, mp, sigma, sigma0, realized, close, drought, z_tv, *, native: bool = False):
    """Traded value, 20-day ADV and half spread; scales are the starting σ and adv0 (PIT)."""
    T, n = sigma.shape
    adv0 = np.array([a_.adv0 for a_ in spec.assets])
    a = ar_coef(mp.tv_hl)
    s = mp.tv_sigma * np.sqrt(1 - a**2)
    if native:
        from . import native as _nat

        ar = _nat.ar1(z_tv, a, s)
    else:
        ar = np.zeros((T, n))
        for t in range(1, T):
            ar[t] = a * ar[t - 1] + s * z_tv[t]
    ar = np.clip(ar, -50, 50)
    sig_bar = sigma0
    shock = np.abs(realized) / np.maximum(np.vstack([sigma[:1], sigma[:-1]]), 1e-8)
    shock = np.clip(shock, 0.0, 10.0)
    years = np.arange(T)[:, None] / YEAR
    log_tv = (
        np.log(adv0)[None, :]
        + ar
        + mp.tv_vol_beta * np.log(np.maximum(sigma / sig_bar, 1e-8))
        + mp.tv_abs_beta * (shock - np.sqrt(2 / np.pi))
        + mp.tv_trend * years
        + np.where(drought, np.log(mp.drought_tv_mult), 0.0)
    )
    log_tv = np.where(np.isfinite(log_tv), log_tv, 0.0)
    tv = np.exp(np.clip(log_tv, -100, 100))
    cs = np.vstack([np.zeros((1, n)), np.cumsum(tv, axis=0)])
    idx = np.arange(1, T + 1)
    lo = np.maximum(idx - ADV_WINDOW, 0)
    adv = (cs[idx] - cs[lo]) / (idx - lo)[:, None]
    base = np.maximum(np.array([a_.half_spread_bp for a_ in spec.assets]) * 1e-4, 0.5 * spec.tick / close)
    spread = base * np.maximum(sigma / sig_bar, 1e-8) ** mp.spread_vol_beta * np.maximum(adv / adv0, 1e-8) ** mp.spread_tv_beta
    spread = spread * np.where(drought, mp.drought_spread_mult, 1.0)
    return tv, adv, spread
