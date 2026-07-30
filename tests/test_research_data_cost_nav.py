"""Unit tests for R0-COST/NAV frozen cost model and NAV generators."""

from __future__ import annotations

import math
import unittest

from qount.research_data.market_data import Bar
from qount.research_data.market_data import Funding
from qount.research_data.cost_model import COST_MODEL_TYPES
from qount.research_data.cost_model import CostComponent
from qount.research_data.cost_model import FrozenCostModel
from qount.research_data.cost_model import default_cxd_trend_cost_model
from qount.research_data.cost_model import default_cxd_carry_cost_model
from qount.research_data.cost_model import default_cta_r_etf_cost_model
from qount.research_data.cost_model import default_cta_r_futures_cost_model
from qount.research_data.nav import NavResult
from qount.research_data.nav import compute_carry_signal_nav
from qount.research_data.nav import compute_carry_standalone_nav
from qount.research_data.nav import compute_signal_nav
from qount.research_data.nav import compute_standalone_nav


# --- CostComponent tests ----------------------------------------------------


class TestCostComponent(unittest.TestCase):
    def test_valid_component(self) -> None:
        c = CostComponent("taker_fee", 0.0004, "official_rate", "UM 0.04%")
        self.assertEqual(c.validate(), ())

    def test_negative_rate_invalid(self) -> None:
        c = CostComponent("fee", -0.001, "official_rate", "")
        self.assertIn("cost_component_rate_invalid:fee", c.validate())

    def test_invalid_source(self) -> None:
        c = CostComponent("fee", 0.001, "guessed", "")
        self.assertIn("cost_component_source_invalid:fee", c.validate())

    def test_empty_name_invalid(self) -> None:
        c = CostComponent("", 0.001, "official_rate", "")
        self.assertIn("cost_component_name_empty", c.validate())


# --- FrozenCostModel tests --------------------------------------------------


class TestFrozenCostModel(unittest.TestCase):
    def test_default_trend_model(self) -> None:
        model = default_cxd_trend_cost_model(frozen_at="2026-07-23T00:00:00+00:00")
        errors = model.validate()
        self.assertEqual(errors, ())
        self.assertEqual(model.model_type, "cxd_trend_leg")
        self.assertEqual(model.venue, "binance_um")
        self.assertEqual(len(model.components), 3)
        self.assertFalse(model.has_unavailable)

    def test_default_carry_model(self) -> None:
        model = default_cxd_carry_cost_model(frozen_at="2026-07-23T00:00:00+00:00")
        errors = model.validate()
        self.assertEqual(errors, ())
        self.assertEqual(model.model_type, "cxd_carry_leg")
        self.assertEqual(len(model.components), 8)

    def test_default_cta_r_etf_model(self) -> None:
        model = default_cta_r_etf_cost_model(frozen_at="2026-07-23T00:00:00+00:00")
        errors = model.validate()
        self.assertEqual(errors, ())
        self.assertEqual(model.model_type, "cta_r_etf")
        self.assertEqual(model.venue, "cn_etf_brokerage")

    def test_default_cta_r_futures_model(self) -> None:
        model = default_cta_r_futures_cost_model(frozen_at="2026-07-23T00:00:00+00:00")
        errors = model.validate()
        self.assertEqual(errors, ())
        self.assertEqual(model.model_type, "cta_r_futures")

    def test_hash_stable(self) -> None:
        m1 = default_cxd_trend_cost_model(frozen_at="2026-07-23T00:00:00+00:00")
        m2 = default_cxd_trend_cost_model(frozen_at="2026-07-23T00:00:00+00:00")
        self.assertEqual(m1.model_hash, m2.model_hash)

    def test_hash_changes_with_rate(self) -> None:
        m1 = default_cxd_trend_cost_model(taker_fee=0.0004, frozen_at="2026-07-23T00:00:00+00:00")
        m2 = default_cxd_trend_cost_model(taker_fee=0.0005, frozen_at="2026-07-23T00:00:00+00:00")
        self.assertNotEqual(m1.model_hash, m2.model_hash)

    def test_has_unavailable(self) -> None:
        model = FrozenCostModel.create(
            model_type="cxd_trend_leg",
            model_version="test",
            venue="binance_um",
            components=[
                CostComponent("taker_fee", 0.0004, "official_rate", ""),
                CostComponent("slippage", 0.0, "unavailable", "no data"),
            ],
            frozen_at="2026-07-23T00:00:00+00:00",
        )
        self.assertTrue(model.has_unavailable)

    def test_total_round_trip_rate(self) -> None:
        model = default_cxd_trend_cost_model(taker_fee=0.0004, slippage_bps=2.0, frozen_at="2026-07-23T00:00:00+00:00")
        # round-trip = (taker 0.0004 + slippage 0.0002) * 2 = 0.0012
        # funding is not a turnover cost
        self.assertAlmostEqual(model.total_round_trip_rate, 0.0012, places=6)

    def test_invalid_model_type_raises(self) -> None:
        with self.assertRaises(ValueError):
            FrozenCostModel.create(
                model_type="invalid",
                model_version="test",
                venue="test",
                components=[CostComponent("fee", 0.001, "official_rate", "")],
                frozen_at="2026-07-23T00:00:00+00:00",
            )

    def test_cost_model_types(self) -> None:
        self.assertIn("cxd_trend_leg", COST_MODEL_TYPES)
        self.assertIn("cxd_carry_leg", COST_MODEL_TYPES)
        self.assertIn("cta_r_etf", COST_MODEL_TYPES)
        self.assertIn("cta_r_futures", COST_MODEL_TYPES)

    def test_get_component(self) -> None:
        model = default_cxd_trend_cost_model(frozen_at="2026-07-23T00:00:00+00:00")
        comp = model.get("taker_fee")
        self.assertIsNotNone(comp)
        assert comp is not None
        self.assertEqual(comp.rate, 0.0004)
        self.assertIsNone(model.get("nonexistent"))


# --- Signal NAV tests -------------------------------------------------------


class TestSignalNav(unittest.TestCase):
    def test_long_upward_trend(self) -> None:
        closes = [100, 110, 120]
        positions = [1.0, 1.0, 1.0]
        result = compute_signal_nav(closes, positions)
        self.assertAlmostEqual(result.nav_series[-1], 1.20, places=6)
        self.assertAlmostEqual(result.total_return, 0.20, places=6)
        self.assertEqual(result.total_cost, 0.0)
        self.assertEqual(len(result.nav_series), 3)

    def test_short_downward_trend(self) -> None:
        closes = [120, 110, 100]
        positions = [-1.0, -1.0, -1.0]
        result = compute_signal_nav(closes, positions)
        # Short profit when price falls: pos=-1, return=-(price_drop)
        expected = (1 + (-1) * (110/120 - 1)) * (1 + (-1) * (100/110 - 1))
        self.assertAlmostEqual(result.nav_series[-1], expected, places=6)

    def test_flat_position(self) -> None:
        closes = [100, 110, 120]
        positions = [0.0, 0.0, 0.0]
        result = compute_signal_nav(closes, positions)
        self.assertAlmostEqual(result.nav_series[-1], 1.0, places=6)
        self.assertAlmostEqual(result.total_return, 0.0, places=6)

    def test_turnover_computed(self) -> None:
        closes = [100, 110, 120]
        positions = [0.0, 1.0, 0.0]
        result = compute_signal_nav(closes, positions)
        self.assertAlmostEqual(result.turnover, 2.0, places=6)

    def test_length_mismatch_raises(self) -> None:
        with self.assertRaises(ValueError):
            compute_signal_nav([100, 110], [1.0])

    def test_too_few_bars_raises(self) -> None:
        with self.assertRaises(ValueError):
            compute_signal_nav([100], [1.0])

    def test_to_dict(self) -> None:
        result = compute_signal_nav([100, 110], [1.0, 1.0])
        d = result.to_dict()
        self.assertIn("nav_series", d)
        self.assertIn("total_return", d)
        self.assertIn("final_nav", d)


# --- Standalone NAV tests ---------------------------------------------------


class TestStandaloneNav(unittest.TestCase):
    def test_standalone_less_than_signal(self) -> None:
        closes = [100, 110, 120]
        positions = [0.0, 1.0, 1.0]
        cost_model = default_cxd_trend_cost_model(frozen_at="2026-07-23T00:00:00+00:00")
        signal = compute_signal_nav(closes, positions)
        standalone = compute_standalone_nav(closes, positions, cost_model)
        self.assertLess(standalone.nav_series[-1], signal.nav_series[-1])
        self.assertGreater(standalone.total_cost, 0.0)

    def test_flat_position_no_turnover_cost(self) -> None:
        closes = [100, 110, 120]
        positions = [0.0, 0.0, 0.0]
        cost_model = default_cxd_trend_cost_model(frozen_at="2026-07-23T00:00:00+00:00")
        result = compute_standalone_nav(closes, positions, cost_model)
        self.assertAlmostEqual(result.total_cost, 0.0, places=8)
        self.assertAlmostEqual(result.nav_series[-1], 1.0, places=6)

    def test_cost_breakdown_has_components(self) -> None:
        closes = [100, 110, 120]
        positions = [0.0, 1.0, 1.0]
        cost_model = default_cxd_trend_cost_model(frozen_at="2026-07-23T00:00:00+00:00")
        result = compute_standalone_nav(closes, positions, cost_model)
        self.assertIn("taker_fee", result.cost_breakdown)
        self.assertIn("slippage", result.cost_breakdown)
        self.assertGreater(result.cost_breakdown["taker_fee"], 0.0)

    def test_funding_with_rates(self) -> None:
        closes = [100, 110, 120]
        positions = [1.0, 1.0, 1.0]
        funding = [0.0001, 0.0001, 0.0001]
        cost_model = default_cxd_trend_cost_model(frozen_at="2026-07-23T00:00:00+00:00")
        result = compute_standalone_nav(closes, positions, cost_model, funding_rates=funding)
        self.assertIn("funding", result.cost_breakdown)
        self.assertGreater(result.cost_breakdown["funding"], 0.0)
        self.assertFalse(result.cost_incomplete)

    def test_funding_without_rates_flagged_incomplete(self) -> None:
        closes = [100, 110, 120]
        positions = [1.0, 1.0, 1.0]
        cost_model = default_cxd_trend_cost_model(frozen_at="2026-07-23T00:00:00+00:00")
        result = compute_standalone_nav(closes, positions, cost_model, funding_rates=None)
        self.assertTrue(result.cost_incomplete)

    def test_cost_model_hash_in_result(self) -> None:
        closes = [100, 110]
        positions = [1.0, 1.0]
        cost_model = default_cxd_trend_cost_model(frozen_at="2026-07-23T00:00:00+00:00")
        result = compute_standalone_nav(closes, positions, cost_model)
        self.assertEqual(result.cost_model_hash, cost_model.model_hash)

    def test_invalid_cost_model_raises(self) -> None:
        closes = [100, 110]
        positions = [1.0, 1.0]
        model = FrozenCostModel(
            model_type="cxd_trend_leg", model_version="", venue="binance_um",
            components=(CostComponent("fee", 0.001, "official_rate", ""),),
            frozen_at="2026-07-23T00:00:00+00:00", model_hash="invalid",
        )
        with self.assertRaises(ValueError):
            compute_standalone_nav(closes, positions, model)

    def test_funding_rates_length_mismatch_raises(self) -> None:
        closes = [100, 110, 120]
        positions = [1.0, 1.0, 1.0]
        funding = [0.0001, 0.0001]
        cost_model = default_cxd_trend_cost_model(frozen_at="2026-07-23T00:00:00+00:00")
        with self.assertRaises(ValueError):
            compute_standalone_nav(closes, positions, cost_model, funding_rates=funding)

    def test_double_cost_still_positive_nav(self) -> None:
        closes = [100, 200]
        positions = [1.0, 1.0]
        cost_model = default_cxd_trend_cost_model(
            taker_fee=0.002, slippage_bps=10.0, frozen_at="2026-07-23T00:00:00+00:00",
        )
        result = compute_standalone_nav(closes, positions, cost_model)
        # Even with doubled costs, 100% return should be positive
        self.assertGreater(result.nav_series[-1], 1.0)


# --- Carry NAV tests --------------------------------------------------------


class TestCarryNav(unittest.TestCase):
    def test_carry_signal_nav_basis_convergence(self) -> None:
        # Spot goes up, perp goes up less -> basis narrows -> carry profits
        spot = [100, 105, 110]
        perp = [101, 105, 110]
        result = compute_carry_signal_nav(spot, perp, basis_at_entry=0.01)
        # basis_0 = 0.01, basis_1 = 0.0, basis_2 = 0.0
        # signal_return bar 1: 0.01 - 0.0 = 0.01 (basis narrowed)
        # signal_return bar 2: 0.0 - 0.0 = 0.0
        self.assertGreater(result.nav_series[-1], 1.0)
        self.assertEqual(len(result.nav_series), 3)

    def test_carry_signal_nav_basis_widening(self) -> None:
        # Spot goes down, perp goes up -> basis widens -> carry loses
        spot = [100, 95, 90]
        perp = [101, 102, 103]
        result = compute_carry_signal_nav(spot, perp, basis_at_entry=0.01)
        self.assertLess(result.nav_series[-1], 1.0)

    def test_carry_signal_nav_auto_computes_basis_at_entry(self) -> None:
        spot = [100, 105]
        perp = [102, 105]
        result = compute_carry_signal_nav(spot, perp)
        # basis_0 = (102-100)/100 = 0.02, basis_1 = (105-105)/105 = 0.0
        # signal_return = 0.02 - 0.0 = 0.02
        self.assertAlmostEqual(result.nav_series[-1], 1.02, places=6)

    def test_carry_signal_nav_tracks_basis_not_delta_pnl(self) -> None:
        # Verify signal NAV tracks basis convergence, not delta-neutral PnL
        # spot=[100, 110], perp=[101, 108]
        # delta-neutral PnL = 10/100 - 7/101 = 0.10 - 0.0693 = 0.0307
        # basis_0 = 0.01, basis_1 = (108-110)/110 = -0.01818
        # signal_return = 0.01 - (-0.01818) = 0.02818
        spot = [100, 110]
        perp = [101, 108]
        result = compute_carry_signal_nav(spot, perp)
        expected = 1.0 + (0.01 - (-2.0 / 110.0))
        self.assertAlmostEqual(result.nav_series[-1], expected, places=6)

    def test_carry_standalone_has_costs(self) -> None:
        spot = [100, 105, 110]
        perp = [101, 105, 110]
        cost_model = default_cxd_carry_cost_model(frozen_at="2026-07-23T00:00:00+00:00")
        result = compute_carry_standalone_nav(spot, perp, cost_model)
        self.assertGreater(result.total_cost, 0.0)

    def test_carry_standalone_gross_leq_one(self) -> None:
        # weight=0.5 per leg -> turnover = 4 * 0.5 = 2.0 (not 4.0)
        spot = [100, 105]
        perp = [101, 105]
        cost_model = default_cxd_carry_cost_model(frozen_at="2026-07-23T00:00:00+00:00")
        result = compute_carry_standalone_nav(spot, perp, cost_model)
        self.assertAlmostEqual(result.turnover, 2.0, places=6)

    def test_carry_standalone_additive_not_compound(self) -> None:
        # With flat prices (no market PnL) and no funding, NAV should stay
        # constant during holding period (additive, not multiplicative).
        # Exit cost is applied only to the final bar.
        spot = [100, 100, 100]
        perp = [100, 100, 100]
        cost_model = default_cxd_carry_cost_model(frozen_at="2026-07-23T00:00:00+00:00")
        result = compute_carry_standalone_nav(spot, perp, cost_model)
        # Entry + exit costs are deducted; no market PnL; no funding
        self.assertLess(result.nav_series[-1], 1.0)
        # During holding (bars 0->1), NAV should not change (additive, flat)
        self.assertAlmostEqual(result.nav_series[0], result.nav_series[1], places=8)
        # Exit cost is applied to the last bar, so nav[2] < nav[1]
        self.assertLess(result.nav_series[2], result.nav_series[1])

    def test_carry_standalone_has_legging_and_taker_fee(self) -> None:
        spot = [100, 105, 110]
        perp = [101, 105, 110]
        cost_model = default_cxd_carry_cost_model(frozen_at="2026-07-23T00:00:00+00:00")
        result = compute_carry_standalone_nav(spot, perp, cost_model)
        self.assertIn("legging_cost", result.cost_breakdown)
        self.assertIn("taker_fee", result.cost_breakdown)

    def test_carry_standalone_cost_incomplete_due_to_unavailable(self) -> None:
        # collateral_cost and tail_cost are "unavailable" -> cost_incomplete=True
        spot = [100, 105, 110]
        perp = [101, 105, 110]
        cost_model = default_cxd_carry_cost_model(frozen_at="2026-07-23T00:00:00+00:00")
        result = compute_carry_standalone_nav(spot, perp, cost_model)
        self.assertTrue(result.cost_incomplete)

    def test_carry_with_funding(self) -> None:
        spot = [100, 105, 110]
        perp = [101, 105, 110]
        funding = [0.0001, 0.0001, 0.0001]
        cost_model = default_cxd_carry_cost_model(frozen_at="2026-07-23T00:00:00+00:00")
        result = compute_carry_standalone_nav(spot, perp, cost_model, funding_rates=funding)
        self.assertIn("funding", result.cost_breakdown)
        # cost_incomplete is True because collateral/tail are "unavailable"
        self.assertTrue(result.cost_incomplete)

    def test_carry_length_mismatch_raises(self) -> None:
        with self.assertRaises(ValueError):
            compute_carry_signal_nav([100, 110], [101], basis_at_entry=0.01)


# --- P0 regression: funding sign, rolling drawdown, causal vol-target -------


class TestFundingSignRegression(unittest.TestCase):
    """P0: short perp with positive funding should RECEIVE income, not pay cost."""

    def test_long_positive_funding_is_cost(self) -> None:
        """Long position, positive funding -> cost (positive)."""
        from qount.research_data.nav import _compute_holding_costs
        model = default_cxd_trend_cost_model(frozen_at="2026-07-23T00:00:00+00:00")
        costs = _compute_holding_costs(1.0, 0.0001, model)
        self.assertGreater(costs["funding"], 0.0)  # longs pay

    def test_short_positive_funding_is_income(self) -> None:
        """Short position, positive funding -> income (negative cost)."""
        from qount.research_data.nav import _compute_holding_costs
        model = default_cxd_carry_cost_model(frozen_at="2026-07-23T00:00:00+00:00")
        costs = _compute_holding_costs(-1.0, 0.0001, model)
        self.assertLess(costs["funding"], 0.0)  # shorts receive

    def test_short_negative_funding_is_cost(self) -> None:
        """Short position, negative funding -> cost (positive)."""
        from qount.research_data.nav import _compute_holding_costs
        model = default_cxd_carry_cost_model(frozen_at="2026-07-23T00:00:00+00:00")
        costs = _compute_holding_costs(-1.0, -0.0001, model)
        self.assertGreater(costs["funding"], 0.0)  # shorts pay when funding negative

    def test_carry_funding_income_improves_nav(self) -> None:
        """Carry leg with positive funding should have HIGHER NAV than without funding."""
        spot = [100, 100, 100]  # flat spot
        perp = [100, 100, 100]  # flat perp (no basis change)
        cost_model = default_cxd_carry_cost_model(frozen_at="2026-07-23T00:00:00+00:00")
        # With positive funding, short perp receives income
        result_with_funding = compute_carry_standalone_nav(
            spot, perp, cost_model, funding_rates=[0.001, 0.001, 0.001],
        )
        result_no_funding = compute_carry_standalone_nav(
            spot, perp, cost_model, funding_rates=None,
        )
        # With funding income, NAV should be higher (or cost lower)
        self.assertGreater(result_with_funding.nav_series[-1], result_no_funding.nav_series[-1])


class TestRollingDrawdownRegression(unittest.TestCase):
    """P0: max drawdown must use rolling peak, not global peak."""

    def test_drawdown_before_peak_not_counted(self) -> None:
        """Series [1, 0.5, 3, 2] -> maxDD = -50% (from 1.0 to 0.5), not -83% (from 3.0 to 0.5)."""
        from qount.research_data.nav import compute_max_drawdown
        series = [1.0, 0.5, 3.0, 2.0]
        dd = compute_max_drawdown(series)
        # Rolling peak: t0=1.0, t1=0.5 (dd=-50%), t2=3.0 (dd=0), t3=2.0 (dd=-33%)
        # Max = -50% from the 1.0->0.5 drop (a real drawdown)
        self.assertAlmostEqual(dd, -0.5, places=6)

    def test_monotonic_increase_has_zero_drawdown(self) -> None:
        from qount.research_data.nav import compute_max_drawdown
        series = [1.0, 2.0, 3.0, 4.0]
        self.assertEqual(compute_max_drawdown(series), 0.0)

    def test_single_drawdown(self) -> None:
        from qount.research_data.nav import compute_max_drawdown
        series = [1.0, 2.0, 1.0, 3.0]
        dd = compute_max_drawdown(series)
        self.assertAlmostEqual(dd, -0.5, places=6)  # from peak 2.0 to 1.0

    def test_empty_series(self) -> None:
        from qount.research_data.nav import compute_max_drawdown
        self.assertEqual(compute_max_drawdown([]), 0.0)

    def test_drawdown_not_inflated_by_global_peak(self) -> None:
        """Series starting low and ending high must not report the starting point as drawdown."""
        from qount.research_data.nav import compute_max_drawdown
        series = [1.0, 1.5, 10.0]
        dd = compute_max_drawdown(series)
        self.assertEqual(dd, 0.0)  # monotonically increasing


class TestCausalVolTargetRegression(unittest.TestCase):
    """P0: vol-target must not use current bar's return (no future function)."""

    def test_vol_target_does_not_use_current_bar(self) -> None:
        """Position at bar i should be scaled by vol from lookback completed returns ending at i-1."""
        import math
        # Construct a series where bar 25 doubles
        closes = [100.0] * 25 + [200.0]  # bar 25 doubles
        positions = [1.0] * 26
        # With lookback=20 (20 completed returns), loop starts at i=21:
        # At i=21: uses returns j=1..20, all 100 -> vol=0 -> scale=1.0
        # At i=25: uses returns j=5..24, all 100 -> vol=0 -> scale=1.0
        # (bar 25's spike is the current bar, not included)
        from scripts.research.governance.run_r0_advancement import vol_target_positions
        scaled = vol_target_positions(closes, positions, target_vol=0.02, lookback=20)
        # At bar 20, loop hasn't started (starts at 21), so position unchanged
        self.assertEqual(scaled[20], 1.0)
        # At bar 21, causal vol from returns 1..20 is 0, so scale should be 1.0
        self.assertEqual(scaled[21], 1.0)
        # At bar 25, causal vol from returns 5..24 includes no spike yet
        # (all 100s), so scale should also be 1.0
        self.assertEqual(scaled[25], 1.0)

    def test_vol_target_reduces_position_in_high_vol(self) -> None:
        """When realized vol is high, position should be scaled down."""
        import math
        # Alternating up/down creates high vol
        closes = [100.0, 110.0, 90.0, 110.0, 90.0, 110.0, 90.0, 110.0,
                  90.0, 110.0, 90.0, 110.0, 90.0, 110.0, 90.0, 110.0,
                  90.0, 110.0, 90.0, 110.0, 90.0, 110.0, 90.0, 110.0, 90.0]
        positions = [1.0] * len(closes)
        from scripts.research.governance.run_r0_advancement import vol_target_positions
        scaled = vol_target_positions(closes, positions, target_vol=0.02, lookback=20)
        # At bar 21+ (loop starts at lookback+1=21), realized vol should be very high
        self.assertLess(scaled[21], 1.0)
        self.assertGreater(scaled[21], 0.0)


# --- Funding aggregation tests (P0.5) ---------------------------------------


_DAY = 86_400_000
_8H = 28_800_000
_16H = 57_600_000


def _bar(day: int, close: float = 100.0) -> Bar:
    """Create a daily bar at midnight UTC of *day* (day 0 = 2020-01-01)."""
    return Bar(ts_ms=day * _DAY, open=close, high=close, low=close, close=close, volume=0.0)


def _bars(n: int, close: float = 100.0) -> list[Bar]:
    return [_bar(i, close) for i in range(n)]


def _funding_3x(day: int, rate: float = 0.0001) -> list[Funding]:
    """3 settlements per day at 00:00, 08:00, 16:00 UTC."""
    base = day * _DAY
    return [
        Funding(ts_ms=base, rate=rate),
        Funding(ts_ms=base + _8H, rate=rate),
        Funding(ts_ms=base + _16H, rate=rate),
    ]


class TestFundingAggregation(unittest.TestCase):
    """P0.5: funding settlements must be summed per holding interval, not pick-one."""

    def test_3_settlements_per_day_summed(self) -> None:
        """Each day has 3 settlements; aggregated rate = 3 × rate."""
        bars = _bars(5)
        funding: list[Funding] = []
        for d in range(5):
            funding.extend(_funding_3x(d, rate=0.0001))
        from scripts.research.governance.run_r0_runtime import aggregate_funding_to_bars
        result = aggregate_funding_to_bars(bars, funding)
        # Days 0-4 each have 3 settlements summed to 0.0003
        for i in range(5):
            self.assertAlmostEqual(result.rates[i], 0.0003, places=10,
                                   msg=f"bar {i} rate should be 3x0.0001")
            self.assertEqual(result.settlement_counts[i], 3)
        self.assertFalse(result.incomplete)

    def test_1_settlement_per_day(self) -> None:
        """Only 1 settlement per day; aggregated rate = 1 × rate."""
        bars = _bars(4)
        funding = [Funding(ts_ms=d * _DAY, rate=0.0002) for d in range(4)]
        from scripts.research.governance.run_r0_runtime import aggregate_funding_to_bars
        result = aggregate_funding_to_bars(bars, funding)
        for i in range(4):
            self.assertAlmostEqual(result.rates[i], 0.0002, places=10)
            self.assertEqual(result.settlement_counts[i], 1)
        self.assertFalse(result.incomplete)

    def test_0_settlements_marks_incomplete(self) -> None:
        """A gap (0 settlements) after prior settlements -> incomplete=True."""
        bars = _bars(5)
        funding: list[Funding] = []
        # Days 0-1 have funding, day 2 is a gap, days 3-4 have funding
        funding.extend(_funding_3x(0))
        funding.extend(_funding_3x(1))
        # day 2: no funding (the gap)
        funding.extend(_funding_3x(3))
        funding.extend(_funding_3x(4))
        from scripts.research.governance.run_r0_runtime import aggregate_funding_to_bars
        result = aggregate_funding_to_bars(bars, funding)
        self.assertTrue(result.incomplete)
        self.assertEqual(len(result.missing_intervals), 1)
        self.assertEqual(result.missing_intervals[0]["bar_index"], 2)
        self.assertEqual(result.settlement_counts[2], 0)

    def test_0_settlements_at_start_not_incomplete(self) -> None:
        """Bars before the first settlement are not flagged as incomplete."""
        bars = _bars(5)
        funding: list[Funding] = []
        # No funding for days 0-1, funding starts at day 2
        funding.extend(_funding_3x(2))
        funding.extend(_funding_3x(3))
        funding.extend(_funding_3x(4))
        from scripts.research.governance.run_r0_runtime import aggregate_funding_to_bars
        result = aggregate_funding_to_bars(bars, funding)
        # Days 0-1 have 0 settlements but no prior data, so not incomplete
        self.assertFalse(result.incomplete)
        self.assertEqual(len(result.missing_intervals), 0)
        self.assertEqual(result.settlement_counts[0], 0)
        self.assertEqual(result.settlement_counts[1], 0)

    def test_cross_day_boundary(self) -> None:
        """Settlement at exactly next day's 00:00 goes to next day's interval."""
        bars = _bars(3)
        funding = [
            Funding(ts_ms=0, rate=0.0001),         # day 0, 00:00
            Funding(ts_ms=_8H, rate=0.0001),       # day 0, 08:00
            Funding(ts_ms=_16H, rate=0.0001),      # day 0, 16:00
            Funding(ts_ms=_DAY, rate=0.0002),      # day 1, 00:00 -> day 1 interval
            Funding(ts_ms=_DAY + _8H, rate=0.0002),
            Funding(ts_ms=_DAY + _16H, rate=0.0002),
            Funding(ts_ms=2 * _DAY, rate=0.0001),      # day 2
            Funding(ts_ms=2 * _DAY + _8H, rate=0.0001),
            Funding(ts_ms=2 * _DAY + _16H, rate=0.0001),
        ]
        from scripts.research.governance.run_r0_runtime import aggregate_funding_to_bars
        result = aggregate_funding_to_bars(bars, funding)
        self.assertAlmostEqual(result.rates[0], 0.0003, places=10)
        self.assertAlmostEqual(result.rates[1], 0.0006, places=10)
        self.assertEqual(result.settlement_counts[0], 3)
        self.assertEqual(result.settlement_counts[1], 3)
        self.assertFalse(result.incomplete)

    def test_2ms_timestamp_offset(self) -> None:
        """Bar open differs from settlement by 2ms; interval range still matches."""
        bars = [_bar(0), _bar(1), _bar(2)]
        # Settlements at +2ms offset from exact 0h/8h/16h
        funding = [
            Funding(ts_ms=2, rate=0.0001),
            Funding(ts_ms=_8H + 2, rate=0.0001),
            Funding(ts_ms=_16H + 2, rate=0.0001),
            Funding(ts_ms=_DAY + 2, rate=0.0001),
            Funding(ts_ms=_DAY + _8H + 2, rate=0.0001),
            Funding(ts_ms=_DAY + _16H + 2, rate=0.0001),
            Funding(ts_ms=2 * _DAY + 2, rate=0.0001),
            Funding(ts_ms=2 * _DAY + _8H + 2, rate=0.0001),
            Funding(ts_ms=2 * _DAY + _16H + 2, rate=0.0001),
        ]
        from scripts.research.governance.run_r0_runtime import aggregate_funding_to_bars
        result = aggregate_funding_to_bars(bars, funding)
        self.assertAlmostEqual(result.rates[0], 0.0003, places=10)
        self.assertAlmostEqual(result.rates[1], 0.0003, places=10)
        self.assertEqual(result.settlement_counts[0], 3)
        self.assertEqual(result.settlement_counts[1], 3)
        self.assertFalse(result.incomplete)

    def test_5ms_timestamp_offset(self) -> None:
        """Bar open differs from settlement by 5ms; interval range still matches."""
        bars = [_bar(0), _bar(1)]
        funding = [
            Funding(ts_ms=5, rate=0.0001),
            Funding(ts_ms=_8H + 5, rate=0.0001),
            Funding(ts_ms=_16H + 5, rate=0.0001),
            Funding(ts_ms=_DAY + 5, rate=0.0001),
            Funding(ts_ms=_DAY + _8H + 5, rate=0.0001),
            Funding(ts_ms=_DAY + _16H + 5, rate=0.0001),
        ]
        from scripts.research.governance.run_r0_runtime import aggregate_funding_to_bars
        result = aggregate_funding_to_bars(bars, funding)
        self.assertAlmostEqual(result.rates[0], 0.0003, places=10)
        self.assertEqual(result.settlement_counts[0], 3)
        self.assertFalse(result.incomplete)

    def test_trailing_incomplete_interval(self) -> None:
        """Last bar with 0 settlements after prior data -> incomplete."""
        bars = _bars(4)
        funding: list[Funding] = []
        funding.extend(_funding_3x(0))
        funding.extend(_funding_3x(1))
        funding.extend(_funding_3x(2))
        # Day 3 (last bar) has no funding
        from scripts.research.governance.run_r0_runtime import aggregate_funding_to_bars
        result = aggregate_funding_to_bars(bars, funding)
        self.assertTrue(result.incomplete)
        self.assertEqual(result.missing_intervals[-1]["bar_index"], 3)

    def test_empty_funding_not_incomplete(self) -> None:
        """No funding data at all -> incomplete=False (no prior settlements)."""
        bars = _bars(5)
        from scripts.research.governance.run_r0_runtime import aggregate_funding_to_bars
        result = aggregate_funding_to_bars(bars, [])
        self.assertFalse(result.incomplete)
        self.assertEqual(len(result.missing_intervals), 0)
        for r in result.rates:
            self.assertEqual(r, 0.0)

    def test_funding_sum_matches_raw(self) -> None:
        """Known fixture: 3 settlements × 0.0001 = 0.0003 per bar."""
        bars = _bars(3)
        funding = _funding_3x(0, 0.0001) + _funding_3x(1, 0.0001) + _funding_3x(2, 0.0001)
        from scripts.research.governance.run_r0_runtime import aggregate_funding_to_bars
        result = aggregate_funding_to_bars(bars, funding)
        self.assertAlmostEqual(result.rates[0], 0.0003, places=10)
        self.assertAlmostEqual(result.rates[1], 0.0003, places=10)
        self.assertAlmostEqual(result.rates[2], 0.0003, places=10)


class TestFundingCompletenessPropagation(unittest.TestCase):
    """P0.5: funding_incomplete must propagate to NavResult.cost_incomplete."""

    def test_incomplete_funding_sets_cost_incomplete(self) -> None:
        """compute_standalone_nav with funding_incomplete=True -> cost_incomplete=True."""
        closes = [100.0, 101.0, 102.0, 103.0]
        positions = [1.0, 1.0, 1.0, 1.0]
        model = default_cxd_trend_cost_model(frozen_at="2026-07-24T00:00:00+00:00")
        result = compute_standalone_nav(
            closes, positions, model,
            funding_rates=[0.0001, 0.0001, 0.0001, 0.0001],
            funding_incomplete=True,
        )
        self.assertTrue(result.cost_incomplete)

    def test_complete_funding_keeps_cost_complete(self) -> None:
        """compute_standalone_nav with funding_incomplete=False -> cost_incomplete=False."""
        closes = [100.0, 101.0, 102.0, 103.0]
        positions = [1.0, 1.0, 1.0, 1.0]
        model = default_cxd_trend_cost_model(frozen_at="2026-07-24T00:00:00+00:00")
        result = compute_standalone_nav(
            closes, positions, model,
            funding_rates=[0.0003, 0.0003, 0.0003, 0.0003],
            funding_incomplete=False,
        )
        self.assertFalse(result.cost_incomplete)

    def test_summed_funding_3x_cost_vs_single(self) -> None:
        """NAV with 3x summed funding should have ~3x funding cost vs single rate."""
        closes = [100.0, 101.0, 102.0, 103.0]
        positions = [1.0, 1.0, 1.0, 1.0]
        model = default_cxd_trend_cost_model(frozen_at="2026-07-24T00:00:00+00:00")
        # Single rate (old buggy behavior)
        nav_single = compute_standalone_nav(
            closes, positions, model,
            funding_rates=[0.0001, 0.0001, 0.0001, 0.0001],
        )
        # Summed rate (3 settlements per day)
        nav_summed = compute_standalone_nav(
            closes, positions, model,
            funding_rates=[0.0003, 0.0003, 0.0003, 0.0003],
        )
        # Summed funding cost should be ~3x single
        self.assertAlmostEqual(
            nav_summed.cost_breakdown["funding"],
            nav_single.cost_breakdown["funding"] * 3,
            places=6,
        )

    def test_carry_nav_with_funding_incomplete(self) -> None:
        """compute_carry_standalone_nav with funding_incomplete -> cost_incomplete."""
        spot = [100.0, 101.0, 102.0, 103.0]
        perp = [100.0, 101.0, 102.0, 103.0]
        model = default_cxd_carry_cost_model(frozen_at="2026-07-24T00:00:00+00:00")
        result = compute_carry_standalone_nav(
            spot, perp, model,
            funding_rates=[0.0001, 0.0001, 0.0001, 0.0001],
            funding_incomplete=True,
        )
        self.assertTrue(result.cost_incomplete)

    def test_deprecated_align_returns_rates_only(self) -> None:
        """align_funding_to_bars (deprecated) still returns a list of floats."""
        bars = _bars(3)
        funding = _funding_3x(0, 0.0001) + _funding_3x(1, 0.0001)
        from scripts.research.governance.run_r0_runtime import align_funding_to_bars
        rates = align_funding_to_bars(bars, funding)
        self.assertIsInstance(rates, list)
        self.assertAlmostEqual(rates[0], 0.0003, places=10)


if __name__ == "__main__":
    unittest.main()
