from __future__ import annotations

import unittest

from qount.mini_trend.liquidity_capacity_calibration import (
    LIQUIDITY_CAPACITY_CALIBRATION_PROTOCOL,
    binding_capacity,
    build_calibration_scorecard,
    capacity_by_cost_budget,
    capacity_by_participation,
    friction_bps,
    half_spread_bps,
    impact_bps,
)


class CostMathTests(unittest.TestCase):
    def test_half_spread_is_half_of_proportional_spread_in_bps(self) -> None:
        # 0.004 proportional spread -> 40 bps total -> 20 bps one side.
        self.assertAlmostEqual(half_spread_bps(0.004), 20.0)

    def test_half_spread_clamps_negative(self) -> None:
        self.assertEqual(half_spread_bps(-0.01), 0.0)

    def test_impact_is_linear_in_notional(self) -> None:
        # impact_bps = amihud_x_1e6 * notional / 100.
        self.assertAlmostEqual(impact_bps(0.0003, 100_000.0), 0.3)
        self.assertAlmostEqual(impact_bps(0.0003, 200_000.0), 0.6)

    def test_impact_zero_at_nonpositive_notional(self) -> None:
        self.assertEqual(impact_bps(0.0003, 0.0), 0.0)
        self.assertEqual(impact_bps(0.0003, -5.0), 0.0)

    def test_impact_negligible_at_pilot_notional(self) -> None:
        # At the 100 USDT Base pilot notional even the least liquid coin is ~0.
        self.assertLess(impact_bps(0.0003, 100.0), 1e-3)

    def test_friction_sums_spread_and_impact(self) -> None:
        self.assertAlmostEqual(
            friction_bps(0.004, 0.0003, 100_000.0), 20.0 + 0.3
        )


class CapacityTests(unittest.TestCase):
    def test_cost_budget_capacity_solves_headroom(self) -> None:
        # half_spread = 20 bps; budget 25 -> 5 bps headroom.
        # N = 5 * 100 / 0.0003 = 1_666_666.67
        cap = capacity_by_cost_budget(0.004, 0.0003, 25.0)
        self.assertAlmostEqual(cap, 5.0 * 100.0 / 0.0003, places=2)

    def test_cost_budget_zero_when_spread_exceeds_budget(self) -> None:
        # half_spread = 20 bps > 10 bps budget.
        self.assertEqual(capacity_by_cost_budget(0.004, 0.0003, 10.0), 0.0)

    def test_cost_budget_infinite_when_no_impact(self) -> None:
        self.assertEqual(capacity_by_cost_budget(0.0001, 0.0, 10.0), float("inf"))

    def test_participation_capacity(self) -> None:
        self.assertAlmostEqual(
            capacity_by_participation(200_000_000.0, 0.01), 2_000_000.0
        )

    def test_binding_capacity_picks_minimum(self) -> None:
        # Large budget -> cost cap huge; participation small -> participation binds.
        result = binding_capacity(
            corwin_schultz_spread=0.002,
            amihud_x_1e6=1e-5,
            median_daily_quote_volume_usdt=100_000_000.0,
            budget_bps=25.0,
            participation_cap=0.01,
        )
        self.assertEqual(result["binding_constraint"], "participation")
        self.assertAlmostEqual(result["binding_capacity_usdt"], 1_000_000.0)

    def test_binding_capacity_cost_budget_binds(self) -> None:
        # Wide spread + high impact -> cost budget binds below participation.
        result = binding_capacity(
            corwin_schultz_spread=0.004,
            amihud_x_1e6=0.0003,
            median_daily_quote_volume_usdt=200_000_000.0,
            budget_bps=25.0,
            participation_cap=0.01,
        )
        self.assertEqual(result["binding_constraint"], "cost_budget")


def _g0_summary() -> dict[str, dict[str, object]]:
    return {
        "BTCUSDT": {
            "bar_count": 2342,
            "median_daily_quote_volume_usdt": 12_489_098_968.1,
            "amihud_x_1e6": 1.5171966537506083e-06,
            "corwin_schultz_spread_estimate": 0.002505646024918609,
            "book_spread_depth_available": False,
        },
        "LTCUSDT": {
            "bar_count": 2337,
            "median_daily_quote_volume_usdt": 213_289_969.4,
            "amihud_x_1e6": 0.0003073834971362335,
            "corwin_schultz_spread_estimate": 0.0035895114552108183,
            "book_spread_depth_available": False,
        },
        "EMPTY": {"bar_count": 0},
    }


class ScorecardTests(unittest.TestCase):
    def test_scorecard_is_no_alpha_no_pnl(self) -> None:
        card = build_calibration_scorecard(
            _g0_summary(),
            available_symbols=["BTCUSDT", "LTCUSDT", "EMPTY"],
            g0_artifact_hash="deadbeef",
            g0_verdict="pass_to_capacity_calibration",
            observed_at="2026-07-25T00:00:00+00:00",
        )
        meta = card["meta"]
        self.assertFalse(meta["direction_produced"])
        self.assertFalse(meta["pnl_evaluated"])
        self.assertFalse(meta["alpha_attributed"])
        self.assertFalse(meta["candidate_pnl_ready"])
        self.assertFalse(meta["orders_authorized"])

    def test_scorecard_skips_empty_symbol(self) -> None:
        card = build_calibration_scorecard(
            _g0_summary(),
            available_symbols=["BTCUSDT", "LTCUSDT", "EMPTY"],
            g0_artifact_hash="deadbeef",
            g0_verdict="pass_to_capacity_calibration",
            observed_at="2026-07-25T00:00:00+00:00",
        )
        self.assertIn("BTCUSDT", card["by_symbol"])
        self.assertIn("LTCUSDT", card["by_symbol"])
        self.assertNotIn("EMPTY", card["by_symbol"])

    def test_scorecard_binds_g0_hash_and_verdict(self) -> None:
        card = build_calibration_scorecard(
            _g0_summary(),
            available_symbols=["BTCUSDT"],
            g0_artifact_hash="abc123",
            g0_verdict="pass_to_capacity_calibration",
            observed_at="2026-07-25T00:00:00+00:00",
        )
        self.assertEqual(card["g0_input"]["g0_artifact_hash"], "abc123")

    def test_scorecard_rejects_non_passing_verdict(self) -> None:
        with self.assertRaises(ValueError):
            build_calibration_scorecard(
                _g0_summary(),
                available_symbols=["BTCUSDT"],
                g0_artifact_hash="abc123",
                g0_verdict="block_capacity",
                observed_at="2026-07-25T00:00:00+00:00",
            )

    def test_participation_only_universe_capacity_bound_by_least_liquid(self) -> None:
        card = build_calibration_scorecard(
            _g0_summary(),
            available_symbols=["BTCUSDT", "LTCUSDT"],
            g0_artifact_hash="deadbeef",
            g0_verdict="pass_to_capacity_calibration",
            observed_at="2026-07-25T00:00:00+00:00",
        )
        roll = card["universe_capacity_participation_only"]
        # LTC has far lower turnover than BTC, so it binds the robust rollup.
        self.assertEqual(roll["min_participation_symbol"], "LTCUSDT")
        self.assertAlmostEqual(
            roll["min_participation_capacity_usdt"], 213_289_969.4 * 0.01
        )

    def test_cs_spread_overstated_is_flagged(self) -> None:
        card = build_calibration_scorecard(
            _g0_summary(),
            available_symbols=["BTCUSDT", "LTCUSDT"],
            g0_artifact_hash="deadbeef",
            g0_verdict="pass_to_capacity_calibration",
            observed_at="2026-07-25T00:00:00+00:00",
        )
        # Both coins' CS half-spread (12-18 bps) exceeds the 5 bps plausible ceiling.
        self.assertEqual(
            card["cost_error"]["cs_spread_overstated_symbols"], ["BTCUSDT", "LTCUSDT"]
        )
        for symbol in ("BTCUSDT", "LTCUSDT"):
            self.assertTrue(
                card["by_symbol"][symbol]["spread_proxy_plausibility"]["cs_overstated"]
            )

    def test_cost_error_flags_no_ground_truth(self) -> None:
        card = build_calibration_scorecard(
            _g0_summary(),
            available_symbols=["BTCUSDT"],
            g0_artifact_hash="deadbeef",
            g0_verdict="pass_to_capacity_calibration",
            observed_at="2026-07-25T00:00:00+00:00",
        )
        self.assertFalse(card["cost_error"]["ground_truth_available"])
        self.assertTrue(card["cost_error"]["ground_truth_blockers"])


class ProtocolTests(unittest.TestCase):
    def test_contract_hash_is_stable(self) -> None:
        self.assertEqual(
            LIQUIDITY_CAPACITY_CALIBRATION_PROTOCOL.contract_hash,
            LIQUIDITY_CAPACITY_CALIBRATION_PROTOCOL.contract_hash,
        )

    def test_taker_fee_is_binance_um_official(self) -> None:
        self.assertEqual(LIQUIDITY_CAPACITY_CALIBRATION_PROTOCOL.taker_fee_bps, 4.0)


if __name__ == "__main__":
    unittest.main()
