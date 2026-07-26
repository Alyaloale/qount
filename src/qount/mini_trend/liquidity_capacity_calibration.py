"""Capacity calibration for ``liquidity_capacity_meta_v1``.

The liquidity G0 (``liquidity_capacity_g0``) already passed
``pass_to_capacity_calibration`` for the 10-symbol LiquidTrend universe: PIT
rules coverage 1.0, median quote volume and Amihud illiquidity within budget.
This module turns those *frozen* per-symbol liquidity proxies into an execution
cost / capacity scorecard that other research lines can reuse as a common cost
convention. It produces **no direction, no alpha and no PnL**.

Inputs are the per-symbol summary already recorded in a frozen G0 artifact:

* ``median_daily_quote_volume_usdt`` -- turnover, drives participation capacity;
* ``amihud_x_1e6`` -- ``mean(|daily_return| / daily_quote_volume_usdt) * 1e6``,
  a coarse *linear* price-impact proxy (Kyle-lambda-like, 1/USDT units);
* ``corwin_schultz_spread_estimate`` -- proportional bid/ask spread proxy.

Cost model (per single execution, one side):

    half_spread_bps = (corwin_schultz_spread / 2) * 1e4
    impact_bps(N)   = amihud_x_1e6 * N / 100          # linear in notional N (USDT)
    friction_bps(N) = half_spread_bps + impact_bps(N)
    total_bps(N)    = friction_bps(N) + taker_fee_bps  # exchange fee added explicitly

Impact derivation: Amihud lambda = amihud_x_1e6 * 1e-6 has units of return per
USDT, so trading ``N`` USDT moves price by ``lambda * N`` in return space; in bps
that is ``lambda * N * 1e4 = amihud_x_1e6 * N / 100``. Linear Amihud impact is a
conservative *upper* proxy at large size (true impact is concave / ~sqrt), which
is the safe direction for a capacity ceiling.

Two capacity notions are reported and the binding one is the minimum:

* cost-budget capacity: largest N with ``friction_bps(N) <= budget`` (market
  friction only, exchange fee excluded because fee is size-independent);
* participation capacity: ``participation_cap * median_daily_quote_volume``.

**Cost-error honesty**: there are no real fills and no order-book depth on this
machine, so ground-truth execution cost is *unavailable*. The scorecard marks
``ground_truth_available=False`` and reports a proxy cross-check (Amihud impact
at participation capacity vs. the Corwin-Schultz half-spread) as the only
uncertainty signal, plus the still-open blockers (real fills, book depth,
segment stability on the full per-day series -- WSL follow-up).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from qount.contracts import canonical_hash


LIQUIDITY_CAPACITY_CALIBRATION_VERSION = "liquidity_capacity_meta_calibration_v0.1"
LIQUIDITY_CAPACITY_FAMILY = "liquidity_capacity_meta_v1"

# Binance USD-M standard taker fee (0.04% = 4 bps). Kept explicit and separate
# from market friction because the exchange fee is size-independent and is not a
# liquidity property. Official rate; not derived from the klines.
BINANCE_UM_TAKER_FEE_BPS = 4.0


@dataclass(frozen=True)
class LiquidityCapacityCalibrationProtocol:
    hypothesis_family: str = LIQUIDITY_CAPACITY_FAMILY
    candidate_id: str = "liquidity_capacity_state_v0"
    # Reference notionals (USDT) at which cost is tabulated. 100 is the Base
    # pilot notional; the ladder spans research/production-scale sizes.
    reference_notionals_usdt: tuple[float, ...] = (
        100.0,
        1_000.0,
        10_000.0,
        100_000.0,
        1_000_000.0,
    )
    # Market-friction budgets (bps, one side) used to solve for capacity.
    cost_budgets_bps: tuple[float, ...] = (5.0, 10.0, 25.0)
    # Fraction of median daily quote volume treated as the participation ceiling.
    participation_cap: float = 0.01
    taker_fee_bps: float = BINANCE_UM_TAKER_FEE_BPS
    # Corwin-Schultz on daily high/low is a known-noisy, upward-biased spread
    # estimator. For liquid USD-M perps a plausible one-side spread is well
    # under this ceiling; a half-spread above it flags the proxy as overstated
    # so cost-budget capacity below it is proxy-limited, not liquidity-limited.
    plausible_half_spread_bps_ceiling: float = 5.0
    output_role: str = "eligibility_cost_capacity_no_alpha"

    @property
    def contract_basis(self) -> dict[str, Any]:
        return {
            "hypothesis_family": self.hypothesis_family,
            "candidate_id": self.candidate_id,
            "reference_notionals_usdt": list(self.reference_notionals_usdt),
            "cost_budgets_bps": list(self.cost_budgets_bps),
            "participation_cap": self.participation_cap,
            "taker_fee_bps": self.taker_fee_bps,
            "plausible_half_spread_bps_ceiling": self.plausible_half_spread_bps_ceiling,
            "cost_model": {
                "half_spread_bps": "corwin_schultz_spread / 2 * 1e4",
                "impact_bps": "amihud_x_1e6 * notional_usdt / 100 (linear Amihud proxy)",
                "friction_bps": "half_spread_bps + impact_bps (one side, fee excluded)",
                "total_bps": "friction_bps + taker_fee_bps",
                "impact_is_upper_proxy": True,
            },
            "output_role": self.output_role,
            "candidate_pnl_ready": False,
            "promotion_evidence": False,
            "orders_authorized": False,
        }

    @property
    def contract_hash(self) -> str:
        return canonical_hash(self.contract_basis)


LIQUIDITY_CAPACITY_CALIBRATION_PROTOCOL = LiquidityCapacityCalibrationProtocol()


def half_spread_bps(corwin_schultz_spread: float) -> float:
    """One-side spread cost in bps from the proportional-spread proxy."""

    return max(0.0, corwin_schultz_spread) / 2.0 * 1e4


def impact_bps(amihud_x_1e6: float, notional_usdt: float) -> float:
    """Linear Amihud price-impact estimate (bps) for a single execution.

    ``impact_bps = amihud_x_1e6 * notional / 100`` (see module docstring).
    """

    if notional_usdt <= 0.0:
        return 0.0
    return max(0.0, amihud_x_1e6) * notional_usdt / 100.0


def friction_bps(
    corwin_schultz_spread: float, amihud_x_1e6: float, notional_usdt: float
) -> float:
    """One-side market friction: half-spread + linear impact (fee excluded)."""

    return half_spread_bps(corwin_schultz_spread) + impact_bps(
        amihud_x_1e6, notional_usdt
    )


def capacity_by_cost_budget(
    corwin_schultz_spread: float, amihud_x_1e6: float, budget_bps: float
) -> float:
    """Largest notional (USDT) whose one-side friction stays within ``budget_bps``.

    Solves ``half_spread + amihud_x_1e6 * N / 100 = budget`` for ``N``. If the
    half-spread alone already exceeds the budget, capacity is 0. If impact is
    zero (amihud <= 0), capacity is unbounded by this constraint -> ``inf``.
    """

    headroom = budget_bps - half_spread_bps(corwin_schultz_spread)
    if headroom <= 0.0:
        return 0.0
    if amihud_x_1e6 <= 0.0:
        return float("inf")
    return headroom * 100.0 / amihud_x_1e6


def capacity_by_participation(
    median_daily_quote_volume_usdt: float, participation_cap: float
) -> float:
    """Participation ceiling: ``cap * median daily quote volume`` (USDT)."""

    return max(0.0, median_daily_quote_volume_usdt) * max(0.0, participation_cap)


def binding_capacity(
    *,
    corwin_schultz_spread: float,
    amihud_x_1e6: float,
    median_daily_quote_volume_usdt: float,
    budget_bps: float,
    participation_cap: float,
) -> dict[str, Any]:
    """Combine cost-budget and participation capacity; the binding one wins."""

    cost_cap = capacity_by_cost_budget(corwin_schultz_spread, amihud_x_1e6, budget_bps)
    part_cap = capacity_by_participation(
        median_daily_quote_volume_usdt, participation_cap
    )
    if cost_cap <= part_cap:
        binding, notional = "cost_budget", cost_cap
    else:
        binding, notional = "participation", part_cap
    return {
        "budget_bps": budget_bps,
        "cost_budget_capacity_usdt": None if cost_cap == float("inf") else cost_cap,
        "participation_capacity_usdt": part_cap,
        "binding_constraint": binding,
        "binding_capacity_usdt": None if notional == float("inf") else notional,
    }


def _symbol_calibration(
    row: Mapping[str, Any], protocol: LiquidityCapacityCalibrationProtocol
) -> dict[str, Any] | None:
    if int(row.get("bar_count", 0) or 0) <= 0:
        return None
    cs = row.get("corwin_schultz_spread_estimate")
    amihud = row.get("amihud_x_1e6")
    median_vol = float(row.get("median_daily_quote_volume_usdt", 0.0) or 0.0)
    if cs is None or amihud is None:
        return None
    cs = float(cs)
    amihud = float(amihud)

    hs = half_spread_bps(cs)
    cost_ladder = {}
    for notional in protocol.reference_notionals_usdt:
        imp = impact_bps(amihud, notional)
        fr = hs + imp
        cost_ladder[f"{int(notional)}"] = {
            "notional_usdt": notional,
            "half_spread_bps": hs,
            "impact_bps": imp,
            "friction_bps": fr,
            "total_bps_incl_taker_fee": fr + protocol.taker_fee_bps,
        }

    capacities = {
        f"{int(budget)}bps": binding_capacity(
            corwin_schultz_spread=cs,
            amihud_x_1e6=amihud,
            median_daily_quote_volume_usdt=median_vol,
            budget_bps=budget,
            participation_cap=protocol.participation_cap,
        )
        for budget in protocol.cost_budgets_bps
    }

    # Proxy cross-check: linear Amihud impact evaluated at the participation
    # ceiling vs. the Corwin-Schultz half-spread. A large ratio in either
    # direction means the two independent friction proxies disagree, which is
    # the only uncertainty signal available without real fills / book depth.
    part_cap = capacity_by_participation(median_vol, protocol.participation_cap)
    impact_at_participation = impact_bps(amihud, part_cap)
    if hs > 0.0:
        proxy_ratio = impact_at_participation / hs
    else:
        proxy_ratio = None

    return {
        "bar_count": int(row.get("bar_count", 0) or 0),
        "median_daily_quote_volume_usdt": median_vol,
        "amihud_x_1e6": amihud,
        "corwin_schultz_spread_estimate": cs,
        "half_spread_bps": hs,
        "cost_ladder": cost_ladder,
        "capacity": capacities,
        "proxy_cross_check": {
            "participation_capacity_usdt": part_cap,
            "impact_bps_at_participation": impact_at_participation,
            "half_spread_bps": hs,
            "impact_over_half_spread_ratio": proxy_ratio,
        },
        "spread_proxy_plausibility": {
            "half_spread_bps": hs,
            "plausible_ceiling_bps": protocol.plausible_half_spread_bps_ceiling,
            "cs_overstated": hs > protocol.plausible_half_spread_bps_ceiling,
        },
        "book_spread_depth_available": bool(row.get("book_spread_depth_available", False)),
    }


def build_calibration_scorecard(
    g0_liquidity_summary: Mapping[str, Mapping[str, Any]],
    *,
    available_symbols: Sequence[str],
    g0_artifact_hash: str,
    g0_verdict: str,
    observed_at: str,
    protocol: LiquidityCapacityCalibrationProtocol | None = None,
) -> dict[str, Any]:
    """Assemble the per-symbol + universe capacity/cost scorecard.

    ``g0_liquidity_summary`` is the frozen ``liquidity`` map from a passing G0
    artifact; ``g0_artifact_hash`` binds this calibration to that input.
    """

    protocol = protocol or LIQUIDITY_CAPACITY_CALIBRATION_PROTOCOL
    if g0_verdict != "pass_to_capacity_calibration":
        raise ValueError(
            f"calibration requires a passing G0 verdict, got {g0_verdict!r}"
        )

    by_symbol: dict[str, Any] = {}
    for symbol in available_symbols:
        row = g0_liquidity_summary.get(symbol)
        if not isinstance(row, Mapping):
            continue
        cal = _symbol_calibration(row, protocol)
        if cal is not None:
            by_symbol[symbol] = cal

    # Universe roll-up: worst-case (min) binding capacity per budget defines the
    # notional at which the *whole* equal-weight universe stays within budget.
    universe_capacity: dict[str, Any] = {}
    for budget in protocol.cost_budgets_bps:
        key = f"{int(budget)}bps"
        binding_values = [
            cal["capacity"][key]["binding_capacity_usdt"]
            for cal in by_symbol.values()
            if cal["capacity"][key]["binding_capacity_usdt"] is not None
        ]
        if binding_values:
            min_symbol = min(
                by_symbol,
                key=lambda s: (
                    by_symbol[s]["capacity"][key]["binding_capacity_usdt"]
                    if by_symbol[s]["capacity"][key]["binding_capacity_usdt"] is not None
                    else float("inf")
                ),
            )
            universe_capacity[key] = {
                "min_binding_capacity_usdt": min(binding_values),
                "min_capacity_symbol": min_symbol,
                "equal_weight_universe_capacity_usdt": min(binding_values)
                * len(by_symbol),
            }
        else:
            universe_capacity[key] = {
                "min_binding_capacity_usdt": None,
                "min_capacity_symbol": None,
                "equal_weight_universe_capacity_usdt": None,
            }

    # Participation-only universe capacity is budget-independent and robust to
    # the noisy CS spread proxy: the equal-weight universe is limited by its
    # least-liquid member's participation ceiling.
    participation_caps = {
        symbol: capacity_by_participation(
            cal["median_daily_quote_volume_usdt"], protocol.participation_cap
        )
        for symbol, cal in by_symbol.items()
    }
    if participation_caps:
        min_part_symbol = min(participation_caps, key=participation_caps.get)
        min_part = participation_caps[min_part_symbol]
        participation_only = {
            "min_participation_capacity_usdt": min_part,
            "min_participation_symbol": min_part_symbol,
            "equal_weight_universe_capacity_usdt": min_part * len(by_symbol),
        }
    else:
        participation_only = {
            "min_participation_capacity_usdt": None,
            "min_participation_symbol": None,
            "equal_weight_universe_capacity_usdt": None,
        }

    cs_overstated_symbols = sorted(
        s for s, cal in by_symbol.items() if cal["spread_proxy_plausibility"]["cs_overstated"]
    )

    return {
        "schema_version": LIQUIDITY_CAPACITY_CALIBRATION_VERSION,
        "artifact_type": "liquidity_capacity_meta_calibration",
        "observed_at": observed_at,
        "contract_hash": protocol.contract_hash,
        "g0_input": {
            "g0_artifact_hash": g0_artifact_hash,
            "g0_verdict": g0_verdict,
            "symbols_calibrated": sorted(by_symbol),
        },
        "meta": {
            "research_only": True,
            "output_role": protocol.output_role,
            "direction_produced": False,
            "pnl_evaluated": False,
            "alpha_attributed": False,
            "candidate_pnl_ready": False,
            "promotion_evidence": False,
            "orders_authorized": False,
        },
        "cost_model": {
            "taker_fee_bps": protocol.taker_fee_bps,
            "taker_fee_source": "binance_um_official_0.04pct",
            "participation_cap": protocol.participation_cap,
            "impact_model": "linear_amihud_upper_proxy",
            "friction_excludes_fee": True,
        },
        "by_symbol": by_symbol,
        "universe_capacity": universe_capacity,
        "universe_capacity_participation_only": participation_only,
        "cost_error": {
            "ground_truth_available": False,
            "ground_truth_blockers": [
                "no_real_fills_on_this_machine",
                "no_order_book_depth_snapshot",
                "corwin_schultz_is_daily_high_low_proxy_known_noisy",
                "linear_amihud_ignores_concavity_and_intraday_timing",
            ],
            "cs_spread_overstated_symbols": cs_overstated_symbols,
            "cs_spread_finding": (
                "corwin_schultz half-spread exceeds the plausible perp ceiling for "
                "these symbols; cost-budget capacity below that half-spread is "
                "proxy-limited, not liquidity-limited -- use participation-only "
                "universe capacity as the robust number until book depth is collected"
            ),
            "uncertainty_signal": "impact_over_half_spread_ratio_per_symbol",
            "deferred_to_wsl_full_series": [
                "rolling_time_varying_capacity",
                "segment_stability_2020_21_2022_23_2024_26",
                "amihud_and_cs_confidence_intervals",
            ],
        },
    }
