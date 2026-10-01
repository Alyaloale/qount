// Native day loop of the structural generator (generator/structural.py, design §7.1).
//
// A line-by-line port of the numpy loop in ``simulate_world`` plus the sequential helpers
// (_price_paths, _ewma_sigma, liquidity AR).  Random draws stay in numpy (worlds remain
// reproducible from the seed); this file only does the recursion.  Expression order follows
// the Python source so results agree to rounding; build with -ffp-contract=off and without
// -ffast-math (see native/__init__.py).  The numpy loop stays the reference implementation.
//
// Layouts (row-major, double unless noted):
//   econ   [NE][2]   per-economy constants, order = ECON_FIELDS in __init__.py
//   asset  [NA][n]   per-asset constants,   order = ASSET_FIELDS
//   aint   [4][n]    int: economy, kind (0 eq, 1 bond, 2 gold, 3 cmdty), fx, qdii
//   sc     [NS]      scalars,               order = SCALAR_FIELDS
//   rtab   [6][5]    regime tables: gap target, pi shift, growth vol, infl vol, eq vol, jump
//   pcum   [5][5]    cumulative transition rows
//   init   [6][2]    gap, pi, rate, tp, crisis_erp, h
//   draws  (T,2) / (T) / (T,n) as documented at each pointer
//   oecon  [5][T][2] gap, pi, rate, y10, erp

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>

using std::size_t;

namespace {

enum Econ {
  R_STAR, PI_STAR, I_FLOOR, PHI_PI, PHI_X, A_RATE, A_GAP, A_PI, A_TP, A_ERP,
  GAP_SD, PI_SD, S_GAP, S_PI, S_TP, TP_MEAN, ERP_BAR, ERP_GAP, ERP_PI, ERP_CRISIS,
  DUR_EQ, DY_BAR, LOG_INV_DY, DIV_LOAD, W10, EQ_VAR_D, G_A, G_G, G_B, PERSIST, H_CAP, THETA,
  NE
};
enum Asset { BETA, IDIO_D, DUR, CVX, WM, MAT_SCALE, LEV, STALE, NA };
enum Scalar {
  F_NOW, A_MOM, KAPPA, PSI, Q_CF, A_OBS, S_OBS, JUMP_RATE_D, JUMP_MEAN, JUMP_SD,
  REBOUND_SHARE, FTQ, JUMP_COMP, AU_VAR, GOLD_RR, GOLD_RB, GOLD_JS, CM_VAR, CM_ROLL,
  CM_IB, CM_GB, A_PR, QUOTA_PREM, PREM_SIGMA, QUOTA_DAYS, QUOTA_RATE, DROUGHT_DAYS,
  DROUGHT_RATE, CONTAGION, PAYOUT, FX_SCALE, FX_VAR, REBOUND_DAYS, STALE_SHARE, STALE_DECAY, NS
};
enum Kind { EQ = 0, BD = 1, AU = 2, CM = 3 };
constexpr int CRISIS = 4;
constexpr int NREG = 5;
constexpr double YEAR = 252.0;

struct Macro {
  double target[2], anchor[2], y10[2], real10[2], erp[2], pd_t[2];
};

inline void macro(const double* ec, const double* gap, const double* pi, const double* tp,
                  const double* crisis_erp, Macro& m) {
  for (int e = 0; e < 2; ++e) {
    auto c = [&](int f) { return ec[f * 2 + e]; };
    double t = ((c(R_STAR) + pi[e]) + c(PHI_PI) * (pi[e] - c(PI_STAR))) + c(PHI_X) * gap[e];
    m.target[e] = std::fmax(c(I_FLOOR), t);
    double pi_e = c(PI_STAR) + c(THETA) * (pi[e] - c(PI_STAR));
    m.anchor[e] = c(R_STAR) + pi_e;
    m.y10[e] = (c(W10) * m.anchor[e] + (1 - c(W10)) * m.target[e]) + tp[e];
    m.real10[e] = m.y10[e] - pi_e;
    m.erp[e] = ((c(ERP_BAR) + c(ERP_GAP) * gap[e] / c(GAP_SD)) + c(ERP_PI) * (pi[e] - c(PI_STAR)) / c(PI_SD))
               + crisis_erp[e];
    m.pd_t[e] = -c(DUR_EQ) * ((m.erp[e] - c(ERP_BAR)) + (m.real10[e] - (c(R_STAR) + c(TP_MEAN))));
  }
}

inline int regime_step(const double* pcum, int state, double u) {
  int k = 0;  // np.searchsorted(row, u, side="right") = count of entries <= u
  for (int j = 0; j < NREG; ++j) k += pcum[state * NREG + j] <= u;
  return k < NREG ? k : NREG - 1;
}

}  // namespace

extern "C" {

int qount_kernel_abi(void) { return NE * 10000 + NA * 100 + NS; }

int qount_structural_loop(
    int T, int n, const double* ec, const double* as, const int32_t* aint, const double* sc,
    const double* rtab, const double* pcum, const double* init,
    const double* u_reg, const double* u_cont, const double* zg, const double* zi, const double* z_tp,
    const double* z_eq, const double* z_id, const double* z_fx, const double* z_au, const double* z_cm,
    const double* z_pr, const double* z_obs, const double* u_jump, const double* z_jump,
    const double* u_quota, const double* u_drought,
    double* logret, double* dist, double* pe, double* pe_obs, double* bond_y, double* mu, double* var,
    uint8_t* quota_path, uint8_t* drought_path, double* fx_ret, int32_t* out_reg, double* oecon) {
  if (T < 1 || n < 1 || n > 64) return 1;
  const double nan = std::numeric_limits<double>::quiet_NaN();
  const double *RGT = rtab, *RPS = rtab + 5, *RGV = rtab + 10, *RIV = rtab + 15, *REV = rtab + 20,
               *RJ = rtab + 25;
  auto E = [&](int f, int e) { return ec[f * 2 + e]; };
  auto A = [&](int f, int i) { return as[f * n + i]; };
  const int32_t *aec = aint, *kind = aint + n, *afx = aint + 2 * n, *aq = aint + 3 * n;
  const double s_au = std::sqrt(sc[AU_VAR]), s_cm = std::sqrt(sc[CM_VAR]);

  int reg[2] = {0, 0};
  double gap[2], pi[2], rate[2], tp[2], cerp[2], h[2], eps_prev[2] = {0, 0}, rebound[2] = {0, 0};
  for (int e = 0; e < 2; ++e) {
    gap[e] = init[e]; pi[e] = init[2 + e]; rate[e] = init[4 + e];
    tp[e] = init[6 + e]; cerp[e] = init[8 + e]; h[e] = init[10 + e];
  }
  double pending[64] = {0}, pd_gap[64] = {0}, obs_noise[64] = {0}, prem[64] = {0}, stale_pending[64] = {0}, by[64], pby[64];
  bool drought[64] = {false};
  bool quota = false;
  Macro m, pm;
  macro(ec, gap, pi, tp, cerp, m);
  for (int i = 0; i < n; ++i) {
    int e = aec[i];
    by[i] = (A(WM, i) * m.anchor[e] + (1 - A(WM, i)) * m.target[e]) + tp[e] * A(MAT_SCALE, i);
  }

  for (int t = 0; t < T; ++t) {
    if (t > 0) {
      int nw[2] = {regime_step(pcum, reg[0], u_reg[t * 2]), regime_step(pcum, reg[1], u_reg[t * 2 + 1])};
      for (int e = 0; e < 2; ++e)
        if (nw[e] == CRISIS && reg[e] != CRISIS && nw[1 - e] != CRISIS && u_cont[t] < sc[CONTAGION])
          nw[1 - e] = CRISIS;
      reg[0] = nw[0]; reg[1] = nw[1];
    }
    double gv[2], iv[2], pgap[2], ppi[2], prate[2], jump_term[2], jump[2];
    pm = m;
    for (int e = 0; e < 2; ++e) {
      int r = reg[e];
      gv[e] = RGV[r]; iv[e] = RIV[r];
      pgap[e] = gap[e]; ppi[e] = pi[e]; prate[e] = rate[e];
      gap[e] = (E(A_GAP, e) * gap[e] + (1 - E(A_GAP, e)) * RGT[r] * E(GAP_SD, e)) + E(S_GAP, e) * gv[e] * zg[t * 2 + e];
      double pi_target = E(PI_STAR, e) + RPS[r] * E(PI_SD, e);
      pi[e] = (E(A_PI, e) * pi[e] + (1 - E(A_PI, e)) * pi_target) + E(S_PI, e) * iv[e] * zi[t * 2 + e];
      double lam = sc[JUMP_RATE_D] * RJ[r];
      jump[e] = u_jump[t * 2 + e] < lam ? sc[JUMP_MEAN] + sc[JUMP_SD] * z_jump[t * 2 + e] : 0.0;
      double drip = rebound[e] / sc[REBOUND_DAYS];
      rebound[e] = (rebound[e] - drip) - sc[REBOUND_SHARE] * jump[e];
      jump_term[e] = (jump[e] + drip) - sc[JUMP_COMP] * RJ[r];
      tp[e] = ((E(A_TP, e) * tp[e] + (1 - E(A_TP, e)) * E(TP_MEAN, e)) + E(S_TP, e) * iv[e] * z_tp[t * 2 + e])
              + sc[FTQ] * jump[e];
      cerp[e] = E(A_ERP, e) * cerp[e] + (1 - E(A_ERP, e)) * (r == CRISIS ? E(ERP_CRISIS, e) : 0.0);
    }
    macro(ec, gap, pi, tp, cerp, m);
    for (int e = 0; e < 2; ++e) rate[e] = E(A_RATE, e) * rate[e] + (1 - E(A_RATE, e)) * m.target[e];
    for (int i = 0; i < n; ++i) {
      int e = aec[i];
      pby[i] = by[i];
      by[i] = (A(WM, i) * m.anchor[e] + (1 - A(WM, i)) * m.target[e]) + tp[e] * A(MAT_SCALE, i);
    }

    double omega[2], eps[2], dr_news[2], cf_news[2], common[2], rf_d[2];
    for (int e = 0; e < 2; ++e) {
      double rv = REV[reg[e]];
      omega[e] = E(EQ_VAR_D, e) * (rv * rv) * (1 - E(PERSIST, e));
      double coef = E(G_A, e) + E(G_G, e) * (eps_prev[e] < 0 ? 1.0 : 0.0);
      h[e] = std::fmin((omega[e] + coef * (eps_prev[e] * eps_prev[e])) + E(G_B, e) * h[e], E(H_CAP, e));
      eps[e] = std::sqrt(h[e]) * z_eq[t * 2 + e];
      eps_prev[e] = eps[e];
      dr_news[e] = -E(DUR_EQ, e) * ((m.erp[e] - pm.erp[e]) + (m.real10[e] - pm.real10[e]));
      cf_news[e] = E(DIV_LOAD, e) * (gap[e] - pgap[e]);
      common[e] = ((dr_news[e] + cf_news[e]) + eps[e]) + jump_term[e];
      rf_d[e] = prate[e] / YEAR;
    }
    fx_ret[t] = (prate[0] - prate[1]) / YEAR + sc[FX_SCALE] * z_fx[t];

    double r[64], dy[64];
    for (int i = 0; i < n; ++i) {
      int e = aec[i];
      double beta = A(BETA, i), idio = A(IDIO_D, i), eqv = E(EQ_VAR_D, e), lev = A(LEV, i);
      double news = beta * common[e] + std::sqrt(idio * h[e] / eqv) * z_id[t * n + i];
      double drip_m = (1 - sc[A_MOM]) * pending[i];
      pending[i] = (sc[A_MOM] * pending[i] + (1 - sc[F_NOW]) * news) - drip_m;
      double eq_var = (beta * beta) * h[e] + idio * h[e] / eqv;
      double drift = ((rf_d[e] + beta * pm.erp[e] / YEAR) - lev) - sc[PSI] * sc[KAPPA] * pd_gap[i];
      double r_eq = ((drift - 0.5 * eq_var) + sc[F_NOW] * news) + drip_m;
      dy[i] = std::fmin(std::exp(-((E(LOG_INV_DY, e) + pm.pd_t[e]) + pd_gap[i])), 0.15) / YEAR;
      double g_bar = (rf_d[e] + E(ERP_BAR, e) / YEAR) - E(DY_BAR, e) / YEAR;
      double noise_news = news - beta * (dr_news[e] + cf_news[e]);
      double dd = ((((g_bar - lev) - 0.5 * eq_var) + beta * cf_news[e]) + sc[Q_CF] * noise_news)
                  + (1 - sc[PSI]) * sc[KAPPA] * pd_gap[i];
      pd_gap[i] = kind[i] == EQ
                      ? (((pd_gap[i] + r_eq) - E(DY_BAR, e) / YEAR) - dd) - (m.pd_t[e] - pm.pd_t[e])
                      : 0.0;
      double ri;
      switch (kind[i]) {
        case EQ: ri = r_eq; break;
        case BD: {
          double dby = by[i] - pby[i];
          ri = (pby[i] / YEAR - A(DUR, i) * dby) + 0.5 * A(CVX, i) * (dby * dby);
          break;
        }
        case AU:
          ri = ((((ppi[e] + sc[GOLD_RR]) / YEAR - 0.5 * sc[AU_VAR]) + sc[GOLD_RB] * (m.real10[e] - pm.real10[e]))
                - sc[GOLD_JS] * jump_term[e]) + s_au * z_au[t];
          break;
        default:
          ri = ((((rf_d[e] + sc[CM_ROLL] / YEAR) - 0.5 * sc[CM_VAR]) + sc[CM_IB] * (pi[e] - ppi[e]))
                + sc[CM_GB] * (gap[e] - pgap[e])) + s_cm * z_cm[t];
      }
      if (afx[i]) ri = ri + fx_ret[t];
      r[i] = ri;
    }

    if (t > 0) quota = quota ? u_quota[t] >= 1.0 / sc[QUOTA_DAYS] : u_quota[t] < sc[QUOTA_RATE] / YEAR;
    const double prem_target = quota ? sc[QUOTA_PREM] : 0.0;
    for (int i = 0; i < n; ++i) {
      double np_ = aq[i] ? (sc[A_PR] * prem[i] + (1 - sc[A_PR]) * prem_target) + sc[PREM_SIGMA] * z_pr[t] : 0.0;
      r[i] = r[i] + (aq[i] ? std::log1p(np_) - std::log1p(prem[i]) : 0.0);
      prem[i] = np_;
      double u = u_drought[t * n + i];

      drought[i] = drought[i] ? u >= 1.0 / sc[DROUGHT_DAYS] : u < sc[DROUGHT_RATE] / YEAR;
    }

    // CN partial-adjustment/stale mechanism: delayed absorption with geometric decay
    for (int i = 0; i < n; ++i) {
      double theta_i = A(STALE, i) * sc[STALE_SHARE];
      double drip_stale = (1 - sc[STALE_DECAY]) * stale_pending[i];
      stale_pending[i] = sc[STALE_DECAY] * stale_pending[i] + theta_i * r[i] - drip_stale;
      r[i] = (1 - theta_i) * r[i] + drip_stale;
    }

    double rf_n[2] = {rate[0] / YEAR, rate[1] / YEAR};
    const double fx_mu = (rate[0] - rate[1]) / YEAR;
    double h_next[2];
    for (int e = 0; e < 2; ++e) {
      double coef = E(G_A, e) + E(G_G, e) * (eps[e] < 0 ? 1.0 : 0.0);
      h_next[e] = std::fmin((omega[e] + coef * (eps[e] * eps[e])) + E(G_B, e) * h[e], E(H_CAP, e));
    }
    for (int i = 0; i < n; ++i) {
      const int e = aec[i], k = kind[i];
      const size_t ti = static_cast<size_t>(t) * n + i;
      if (t > 0) {
        logret[ti] = r[i];
        dist[ti] = (k == EQ && !aq[i]) ? dy[i] : (k == BD ? pby[i] / YEAR : 0.0);
      }
      double mi, vi;
      if (k == EQ) {
        double beta = A(BETA, i);
        vi = (beta * beta) * h_next[e] + A(IDIO_D, i) * h_next[e] / E(EQ_VAR_D, e);
        mi = (((rf_n[e] + beta * m.erp[e] / YEAR) - A(LEV, i)) - sc[PSI] * sc[KAPPA] * pd_gap[i])
             + (1 - sc[A_MOM]) * pending[i];
        if (aq[i]) mi = mi + (1 - sc[A_PR]) * (prem_target - prem[i]);
      } else if (k == BD) {
        double a = A(DUR, i) * E(S_TP, e) * iv[e], b = A(DUR, i) * (1 - A(WM, i)) * E(PHI_PI, e) * E(S_PI, e);
        double ms = A(MAT_SCALE, i);
        vi = (a * a) * (ms * ms) + b * b;
        mi = by[i] / YEAR - A(DUR, i) * (1 - E(A_TP, e)) * (E(TP_MEAN, e) - tp[e]) * ms;
      } else if (k == AU) {
        vi = sc[AU_VAR];
        mi = (pi[e] + sc[GOLD_RR]) / YEAR + sc[GOLD_JS] * sc[JUMP_COMP] * RJ[reg[e]];
      } else {
        vi = sc[CM_VAR];
        mi = rf_n[e] + sc[CM_ROLL] / YEAR;
      }
      if (afx[i]) { mi = mi + fx_mu; vi = vi + sc[FX_VAR]; }
      mu[ti] = mi;
      var[ti] = vi;

      obs_noise[i] = sc[A_OBS] * obs_noise[i] + sc[S_OBS] * z_obs[ti];
      double log_pd = (E(LOG_INV_DY, e) + m.pd_t[e]) + pd_gap[i];
      double p = std::exp(log_pd) * sc[PAYOUT];
      pe[ti] = k == EQ ? p : nan;
      pe_obs[ti] = k == EQ ? p * std::exp(obs_noise[i]) : nan;
      bond_y[ti] = k == BD ? by[i] : nan;
      drought_path[ti] = drought[i];
    }
    quota_path[t] = quota;
    for (int e = 0; e < 2; ++e) {
      out_reg[t * 2 + e] = reg[e];
      const size_t base = static_cast<size_t>(t) * 2 + e, TT = static_cast<size_t>(T) * 2;
      oecon[base] = gap[e];
      oecon[TT + base] = pi[e];
      oecon[2 * TT + base] = rate[e];
      oecon[3 * TT + base] = m.y10[e];
      oecon[4 * TT + base] = m.erp[e];
    }
  }
  return 0;
}

// _price_paths loop: rows 1..T-1 given close[0] = close_adj[0] already set.
int qount_price_paths(int T, int n, const double* logret, const double* dist, double tick, double lim,
                      int has_lim, double* close, double* close_adj) {
  double carry[64] = {0};
  if (n > 64) return 1;
  for (int t = 1; t < T; ++t) {
    for (int i = 0; i < n; ++i) {
      const size_t ti = static_cast<size_t>(t) * n + i, pi = ti - n;
      double prev = close[pi];
      double move = (logret[ti] - std::log1p(dist[ti])) + carry[i];
      double want = prev * std::exp(move);
      if (has_lim) {
        double up = std::fmax(std::nearbyint(prev * (1 + lim) / tick) * tick, prev + tick);
        double dn = std::fmax(std::nearbyint(prev * (1 - lim) / tick) * tick, tick);
        want = std::fmin(std::fmax(want, dn), up);
      }
      double c = std::fmax(std::nearbyint(want / tick) * tick, tick);
      carry[i] = move - std::log(c / prev);
      close[ti] = c;
      close_adj[ti] = close_adj[pi] * (c / prev) * (1 + dist[ti]);
    }
  }
  return 0;
}

// _ewma_sigma: out[t] = sqrt(v_t), v_0 = sigma0², v_t = λ v + (1-λ) r_t².
int qount_ewma_sigma(int T, int n, const double* r, const double* sigma0, double lam, double* out) {
  for (int i = 0; i < n; ++i) {
    double v = sigma0[i] * sigma0[i];
    for (int t = 0; t < T; ++t) {
      const size_t ti = static_cast<size_t>(t) * n + i;
      if (t > 0) v = lam * v + (1 - lam) * (r[ti] * r[ti]);
      out[ti] = std::sqrt(v);
    }
  }
  return 0;
}

// Liquidity AR(1): ar[0] = 0, ar[t] = a·ar[t-1] + s·z[t].
int qount_ar1(int T, int n, const double* z, double a, double s, double* out) {
  for (int i = 0; i < n; ++i) out[i] = 0.0;
  for (int t = 1; t < T; ++t)
    for (int i = 0; i < n; ++i) {
      const size_t ti = static_cast<size_t>(t) * n + i;
      out[ti] = a * out[ti - n] + s * z[ti];
    }
  return 0;
}

}  // extern "C"
