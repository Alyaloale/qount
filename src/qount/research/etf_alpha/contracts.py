"""Frozen M1 research defaults, distinct from an Alpha or production result."""
from __future__ import annotations

from dataclasses import asdict

from qount.research.etf_trader.costs import cost_params_for
from qount.research.etf_trader.universe import US_ACCOUNT

from .artifacts import GUARDS


def protocol_contract() -> dict:
    return GUARDS | {"line_id": "etf_alpha_p3", "protocol_id": "p3-alpha-v0.1",
        "scope": "M0 preservation and M1 data/labels/splits/accounting/baseline diagnostics",
        "prediction_training_status": "not_run", "alpha_result_status": "not_run",
        "account": asdict(US_ACCOUNT) | {"t_plus_one": sorted(US_ACCOUNT.t_plus_one)},
        "initial_equity": 1_000_000.0, "gross_cap": 1.0, "dd_thresholds": [0.10, 0.15],
        "cost_multipliers": [1.0, 2.0, 3.0], "main_horizon": 20,
        "feature_value": "excluded", "stage1_data": "real training partitions only",
        "cash_forecast": "trailing BIL total-return 20-day extrapolated to matching horizon",
        "seed_contract": {"screening": list(range(1000, 1005)), "final": list(range(1000, 1010)),
                          "ensemble": list(range(1000, 1005)), "test_seed_selection": False},
        "selection_contract": {"train_validation_only": True, "test_is_not_a_selector": True,
                              "robustness_score": "unavailable until train/validation reference scales exist",
                              "initial_formal_hypotheses": ["E3", "E4", "E5"],
                              "third_trial_review_required": True, "new_alpha_trials": 0}}


def label_contract() -> dict:
    return GUARDS | {"schema": "etf-p3-labels-v1", "horizons": [5, 20, 60],
        "decision": "close[t]", "entry": "open[t+1]", "exit": "open[t+h+1]",
        "label_formula": "TR_open[t+h+1]/TR_open[t+1]-1",
        "TR_open": "raw opening price plus split-adjusted prior-share entitlement, reinvested at ex-date open",
        "entry_ex_date_distribution": "excluded", "exit_ex_date_distribution": "included",
        "mu": "cumulative simple total return", "sigma20": "sample sd of the 20 matching open-to-open returns * sqrt(252)",
        "p_up": "1[y20>0]", "q10_training_target": "y20 under pinball_0.10; not a realised sample quantile",
        "cash_excess": "matching BIL opening total-return interval, labels/evaluation only",
        "residual": "asset excess_h - beta_t * SPY excess_h, beta from trailing 252 close excess returns",
        "missing": "head-specific mask; execution days are retained",
        "zero_cost_label_convention": "fractional reinvestment; constrained execution retains cash and charges costs"}


def metric_contract() -> dict:
    return GUARDS | {"schema": "etf-p3-metrics-v1", "annualization_sessions": 252,
        "cagr": "(last_NAV/first_NAV)^(252/number_of_realised_daily_returns)-1",
        "excess_sharpe": "sqrt(252)*mean(net_daily-BIL_daily)/sample_sd(net_daily-BIL_daily)",
        "mdd": "positive loss from continuous cost-after NAV running peak",
        "cvar95": "mean of daily net returns <= empirical 5% quantile, also report positive loss",
        "annual_table": "realised cumulative return and days; current partial year is never a full-year result",
        "IC": "per-date cross-sectional and per-asset time-series; masks and sample counts required",
        "paired_intervals": {"method": "synchronized date blocks by fold", "block": 60, "sensitivity": [40, 120]},
        "DSR": "not_run until complete reconciled trial ledger", "PBO": "not_identifiable without configuration matrix"}


def regime_contract() -> dict:
    return GUARDS | {"schema": "etf-p3-regimes-v1", "thresholds_frozen_before_alpha_test": True,
        "historical_events": [{"id": "covid2020", "start": "2020-02-20", "end": "2020-04-30"},
                              {"id": "inflation_stock_bond2022", "start": "2022-01-01", "end": "2022-12-31"},
                              {"id": "advance2023", "start": "2023-01-01", "end": "2023-12-31"}],
        "past_only_states": {"risk_off": "SPY trailing252<=0 and annual RV20>=0.20",
                             "sideways": "abs(SPY trailing60)<=0.03 and annual RV20<0.20",
                             "rate_sensitive_proxy": "TLT trailing60<=-0.05"},
        "minimum_sessions": 60, "short_state_cagr": "not_reported",
        "rate_sensitive_is_rate_cut_cycle": False,
        "held_out_rule": "train only history preceding event; future-trained LOO is diagnostic only"}


def cost_contract() -> dict:
    return GUARDS | {"schema": "etf-p3-costs-v1", "params": asdict(cost_params_for(US_ACCOUNT)),
        "units": "USD nominal fill price, signed buy/sell notional, trailing20 dollar ADV",
        "multipliers": [1.0, 2.0, 3.0], "tax_basis": "pre-tax",
        "historical_fee_schedule_verified": False, "spread_observed": False,
        "source": "frozen repository P2 static estimates; not a historical quote/fee audit",
        "capacity": "5% trailing ADV per day, 3-day capacity position cap"}
