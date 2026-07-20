from __future__ import annotations

import dataclasses
import copy
import json
import unittest
from pathlib import Path

from qount.mini_trend.equity_mapping import CashSessionState
from qount.mini_trend.equity_mapping import CorporateActionState
from qount.mini_trend.equity_mapping import EquityMappingEventContext
from qount.mini_trend.equity_mapping import EquityMappingG0Config
from qount.mini_trend.equity_mapping import ExecutableQuote
from qount.mini_trend.equity_mapping import MappedEquityInstrument
from qount.mini_trend.equity_mapping import EquityMappingStressScenario
from qount.mini_trend.equity_mapping import build_equity_mapping_g0_event
from qount.mini_trend.equity_mapping import build_equity_mapping_g0_dataset
from qount.mini_trend.equity_mapping import build_equity_mapping_g0_report
from qount.mini_trend.equity_mapping_collection import (
    EQUITY_MAPPING_COLLECTION_VERSION,
)
from qount.mini_trend.futures_recovery import canonical_hash


_HASH = "a" * 64


def _instrument() -> MappedEquityInstrument:
    return MappedEquityInstrument(
        venue="binance",
        venue_symbol="NVDAUSDT",
        venue_base_currency="NVDA",
        cash_quote_venue="nasdaq",
        stablecoin_quote_venue="reference",
        cash_symbol="NVDA",
        product_kind="equity_perpetual",
        claim_kind="synthetic_derivative",
        quote_currency="USDT",
        price_multiplier=1.0,
        price_multiplier_scope="mapped_quote_to_one_cash_share",
        mapping_available_at="2026-07-19T12:00:00+00:00",
        mapping_source_hash=_HASH,
    )


def _quote(
    symbol: str,
    bid: float,
    ask: float,
    *,
    product_kind: str,
    quote_currency: str,
    venue: str,
    session: str,
    base_currency: str | None = None,
    quote_at: str = "2026-07-20T13:24:55+00:00",
) -> ExecutableQuote:
    return ExecutableQuote(
        venue=venue,
        symbol=symbol,
        product_kind=product_kind,
        base_currency=base_currency or symbol.removesuffix(quote_currency),
        bid=bid,
        ask=ask,
        quote_currency=quote_currency,
        quote_at=quote_at,
        available_at=quote_at,
        source_hash=_HASH,
        session=session,
    )


def _session(
    *,
    cash_trading_date: str = "2026-07-20",
    session_type: str = "regular",
) -> CashSessionState:
    return CashSessionState(
        cash_trading_date=cash_trading_date,
        is_trading_day=True,
        session_type=session_type,
        suspended=False,
        regular_open_time_local="09:30:00",
        regular_close_time_local=(
            "13:00:00" if session_type == "half_day" else "16:00:00"
        ),
        calendar_available_at="2026-07-19T12:00:00+00:00",
        calendar_source_hash=_HASH,
    )


def _action(
    status: str = "none",
    *,
    cash_trading_date: str = "2026-07-20",
    adjustment_factor: float | None = None,
) -> CorporateActionState:
    if adjustment_factor is None and status == "point_in_time_adjusted":
        adjustment_factor = 1.0
    return CorporateActionState(
        cash_symbol="NVDA",
        cash_trading_date=cash_trading_date,
        status=status,
        action_kind={
            "none": "none",
            "point_in_time_adjusted": "split",
            "unknown": "unknown",
        }[status],
        adjustment_factor=adjustment_factor,
        adjustment_scope={
            "none": "none",
            "point_in_time_adjusted": "multiply_cash_quote_to_instrument_basis",
            "unknown": "unknown",
        }[status],
        effective_at=(
            "2026-07-19T11:00:00+00:00"
            if status == "point_in_time_adjusted"
            else None
        ),
        available_at="2026-07-19T12:00:00+00:00",
        source_hash=_HASH,
    )


def _context(
    closure_kind: str = "ordinary_overnight",
    *,
    is_earnings: bool = False,
    available_at: str = "2026-07-19T12:00:00+00:00",
) -> EquityMappingEventContext:
    return EquityMappingEventContext(
        closure_kind=closure_kind,
        is_earnings=is_earnings,
        available_at=available_at,
        source_hash=_HASH,
    )


def _stress(
    *,
    observation_end_at: str = "2026-07-18T00:00:00+00:00",
    available_at: str = "2026-07-19T12:00:00+00:00",
) -> EquityMappingStressScenario:
    return EquityMappingStressScenario(
        scenario_id="fixture-gap-spread-stress-v1",
        stress_loss_fraction=0.10,
        method="historical_gap_spread_haircut",
        included_components=(
            "mapped_spread",
            "stablecoin_conversion_spread",
            "fees",
            "slippage",
            "gap_tail",
            "market_impact",
        ),
        observation_end_at=observation_end_at,
        available_at=available_at,
        source_hash=_HASH,
    )


def _event(**overrides):
    inputs = {
        "instrument": _instrument(),
        "mapped_quote": _quote(
            "NVDAUSDT", 94.9, 95.1,
            product_kind="equity_perpetual", quote_currency="USDT",
            venue="binance", session="continuous",
        ),
        "cash_premarket_quote": _quote(
            "NVDA", 99.9, 100.1,
            product_kind="cash_equity", quote_currency="USD",
            venue="nasdaq", session="premarket",
            quote_at="2026-07-20T13:24:56+00:00",
        ),
        "usdt_usd_quote": _quote(
            "USDTUSD", 0.999, 1.001,
            product_kind="fx_spot", quote_currency="USD",
            venue="reference", session="continuous",
            quote_at="2026-07-20T13:24:57+00:00",
        ),
        "cash_session": _session(),
        "corporate_action": _action(),
        "event_context": _context(),
        "stress_scenario": _stress(),
        "account_equity_usdt": 1_000.0,
        "minimum_notional_usdt": 5.0,
    }
    inputs.update(overrides)
    return build_equity_mapping_g0_event(**inputs)


class EquityMappingG0Tests(unittest.TestCase):
    def test_structured_fixture_is_contract_evidence_not_market_evidence(self) -> None:
        fixture_path = (
            Path(__file__).parent / "fixtures" / "equity_mapping_g0_input.json"
        )
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        report = build_equity_mapping_g0_dataset(payload)
        self.assertTrue(report["input"]["synthetic_fixture"])
        self.assertFalse(report["input"]["market_evidence_claimed"])
        self.assertEqual(report["event_count"], 2)
        self.assertEqual(report["independence"]["independent_cash_trading_dates"], 1)
        self.assertEqual(report["verdict"], "collect_equity_mapping_independent_dates")
        self.assertFalse(report["meta"]["pnl_evaluated"])
        self.assertTrue(report["gates"]["raw_collection_lineage_complete"])

    def test_point_in_time_input_requires_verified_raw_lineage(self) -> None:
        fixture_path = (
            Path(__file__).parent / "fixtures" / "equity_mapping_g0_input.json"
        )
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        payload["dataset_role"] = "point_in_time_collection"
        report = build_equity_mapping_g0_dataset(payload)
        self.assertFalse(report["gates"]["raw_collection_lineage_complete"])
        self.assertFalse(report["input"]["market_evidence_claimed"])
        self.assertEqual(report["verdict"], "block_equity_mapping_g0_raw_lineage")

    def test_point_in_time_input_accepts_same_date_verified_source_hashes(self) -> None:
        fixture_path = (
            Path(__file__).parent / "fixtures" / "equity_mapping_g0_input.json"
        )
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        payload["dataset_role"] = "point_in_time_collection"
        payload["events"] = [copy.deepcopy(payload["events"][0])]
        event = payload["events"][0]
        source_hashes = [
            event["instrument"]["mapping_source_hash"],
            event["mapped_quote"]["source_hash"],
            event["cash_premarket_quote"]["source_hash"],
            event["usdt_usd_quote"]["source_hash"],
            event["cash_session"]["calendar_source_hash"],
            event["corporate_action"]["source_hash"],
            event["event_context"]["source_hash"],
            event["stress_scenario"]["source_hash"],
        ]
        batch = {
            "schema_version": EQUITY_MAPPING_COLLECTION_VERSION,
            "dataset_role": "point_in_time_forward_collection",
            "synthetic_fixture": False,
            "cash_trading_date": "2026-07-20",
            "captures": [{"sha256": value} for value in source_hashes],
        }
        raw_manifests = [
            {
                "batch": batch,
                "batch_hash": canonical_hash(batch),
                "verdict": "sealed_raw_collection",
                "verification": {"raw_readback_verified": True},
            }
        ]
        report = build_equity_mapping_g0_dataset(
            payload,
            verified_raw_collection_manifests=raw_manifests,
        )
        self.assertTrue(report["gates"]["raw_collection_lineage_complete"])
        self.assertTrue(report["input"]["market_evidence_claimed"])
        self.assertEqual(report["verdict"], "collect_equity_mapping_independent_dates")

    def test_point_in_time_input_cannot_self_assert_verified_raw_manifests(self) -> None:
        fixture_path = (
            Path(__file__).parent / "fixtures" / "equity_mapping_g0_input.json"
        )
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        payload["raw_collection_manifests"] = []
        with self.assertRaisesRegex(ValueError, "embedded_raw_manifests_forbidden"):
            build_equity_mapping_g0_dataset(payload)

    def test_valid_negative_true_gap_is_stress_sized_without_pnl(self) -> None:
        event = _event()
        self.assertTrue(event["data_contract_valid"])
        self.assertTrue(event["long_negative_gap_candidate"])
        self.assertAlmostEqual(event["true_gap"], -0.05)
        self.assertEqual(event["stress_sized_notional_usdt"], 25.0)
        self.assertTrue(event["stress_capacity_eligible"])
        self.assertTrue(event["research_candidate_eligible"])
        self.assertFalse(event["minimal_live_trial_eligible"])
        self.assertFalse(event["pnl_evaluated"])
        self.assertFalse(event["orders_allowed"])
        self.assertFalse(event["execution_evidence_present"])

    def test_positive_gap_is_valid_research_data_but_never_a_short(self) -> None:
        event = _event(
            mapped_quote=_quote(
                "NVDAUSDT", 104.9, 105.1,
                product_kind="equity_perpetual", quote_currency="USDT",
                venue="binance", session="continuous",
            )
        )
        self.assertTrue(event["data_contract_valid"])
        self.assertFalse(event["long_negative_gap_candidate"])
        self.assertFalse(event["minimal_live_trial_eligible"])
        self.assertIn("not_a_negative_gap_long_event", event["reasons"])

    def test_negative_midpoint_gap_must_survive_full_quote_uncertainty(self) -> None:
        event = _event(
            mapped_quote=_quote(
                "NVDAUSDT", 94.0, 100.0,
                product_kind="equity_perpetual", quote_currency="USDT",
                venue="binance", session="continuous",
            )
        )
        self.assertTrue(event["data_contract_valid"])
        self.assertTrue(event["mid_negative_gap_observation"])
        self.assertGreaterEqual(event["gap_upper_bound"], 0.0)
        self.assertFalse(event["long_negative_gap_candidate"])
        self.assertFalse(event["research_candidate_eligible"])

    def test_stablecoin_conversion_is_part_of_true_gap(self) -> None:
        event = _event(
            usdt_usd_quote=_quote(
                "USDTUSD", 0.979, 0.981,
                product_kind="fx_spot", quote_currency="USD",
                venue="reference", session="continuous",
                quote_at="2026-07-20T13:24:57+00:00",
            )
        )
        self.assertAlmostEqual(event["mapped_mid_usd"], 93.1)
        self.assertAlmostEqual(event["true_gap"], -0.069)

    def test_corporate_action_factor_normalizes_cash_reference_units(self) -> None:
        baseline = _event()
        adjusted = _event(
            cash_premarket_quote=_quote(
                "NVDA", 199.8, 200.2,
                product_kind="cash_equity", quote_currency="USD",
                venue="nasdaq", session="premarket",
                quote_at="2026-07-20T13:24:56+00:00",
            ),
            corporate_action=_action(
                "point_in_time_adjusted", adjustment_factor=0.5
            ),
        )
        self.assertTrue(adjusted["data_contract_valid"])
        self.assertAlmostEqual(adjusted["cash_reference_mid_usd"], 100.0)
        self.assertAlmostEqual(adjusted["true_gap"], baseline["true_gap"])

    def test_invalid_quote_is_a_blocked_record_not_an_arithmetic_crash(self) -> None:
        event = _event(
            mapped_quote=_quote(
                "NVDAUSDT", float("nan"), 95.1,
                product_kind="equity_perpetual", quote_currency="USDT",
                venue="binance", session="continuous",
            )
        )
        self.assertFalse(event["data_contract_valid"])
        self.assertIsNone(event["true_gap"])
        self.assertIn("mapped:quote_price_non_finite", event["reasons"])
        self.assertIn(
            "capacity_not_evaluated_invalid_comparable_prices", event["reasons"]
        )

    def test_quote_after_decision_or_cross_market_skew_blocks_contract(self) -> None:
        event = _event(
            cash_premarket_quote=_quote(
                "NVDA", 99.9, 100.1,
                product_kind="cash_equity", quote_currency="USD",
                venue="nasdaq", session="premarket",
                quote_at="2026-07-20T13:25:01+00:00",
            )
        )
        self.assertFalse(event["data_contract_valid"])
        self.assertIn("cash:quote_outside_reference_window", event["reasons"])
        self.assertIn("cash:quote_not_available_at_decision", event["reasons"])
        self.assertIn("cross_market_quote_skew_exceeded", event["reasons"])
        self.assertTrue(event["stress_capacity_computed"])
        self.assertFalse(event["stress_capacity_eligible"])

    def test_unknown_company_action_and_suspension_block_event(self) -> None:
        event = _event(
            corporate_action=_action("unknown"),
            cash_session=dataclasses.replace(_session(), suspended=True),
        )
        self.assertFalse(event["data_contract_valid"])
        self.assertIn("corporate_action_not_point_in_time_reconstructable", event["reasons"])
        self.assertIn("cash_symbol_suspended", event["reasons"])

    def test_product_claim_types_cannot_be_mixed(self) -> None:
        instrument = dataclasses.replace(
            _instrument(), product_kind="tokenized_spot"
        )
        self.assertIn("instrument_claim_kind_mismatch", instrument.validate())

    def test_quote_venues_are_bound_by_instrument_mapping(self) -> None:
        event = _event(
            cash_premarket_quote=_quote(
                "NVDA", 99.9, 100.1,
                product_kind="cash_equity", quote_currency="USD",
                venue="unapproved-cash", session="premarket",
                quote_at="2026-07-20T13:24:56+00:00",
            )
        )
        self.assertFalse(event["data_contract_valid"])
        self.assertIn("cash_quote_venue_mismatch", event["reasons"])

    def test_new_york_dst_and_half_day_use_point_in_time_session_hours(self) -> None:
        winter_date = "2026-11-27"
        winter = _event(
            mapped_quote=_quote(
                "NVDAUSDT", 94.9, 95.1,
                product_kind="equity_perpetual", quote_currency="USDT",
                venue="binance", session="continuous",
                quote_at="2026-11-27T14:24:55+00:00",
            ),
            cash_premarket_quote=_quote(
                "NVDA", 99.9, 100.1,
                product_kind="cash_equity", quote_currency="USD",
                venue="nasdaq", session="premarket",
                quote_at="2026-11-27T14:24:56+00:00",
            ),
            usdt_usd_quote=_quote(
                "USDTUSD", 0.999, 1.001,
                product_kind="fx_spot", quote_currency="USD",
                venue="reference", session="continuous",
                quote_at="2026-11-27T14:24:57+00:00",
            ),
            cash_session=_session(
                cash_trading_date=winter_date, session_type="half_day"
            ),
            corporate_action=_action(cash_trading_date=winter_date),
        )
        self.assertTrue(winter["data_contract_valid"])
        self.assertEqual(winter["decision_time"], "2026-11-27T14:25:00+00:00")

    def test_event_context_available_after_decision_blocks_contract(self) -> None:
        event = _event(
            event_context=_context(
                "ordinary_weekend",
                is_earnings=True,
                available_at="2026-07-20T13:25:01+00:00",
            )
        )
        self.assertFalse(event["data_contract_valid"])
        self.assertIn("event_context_not_available_at_decision", event["reasons"])

    def test_stress_scenario_future_observations_block_capacity_evidence(self) -> None:
        event = _event(
            stress_scenario=_stress(
                observation_end_at="2026-07-20T13:25:01+00:00",
                available_at="2026-07-20T13:25:02+00:00",
            )
        )
        self.assertFalse(event["data_contract_valid"])
        self.assertIn("stress_scenario_uses_future_observations", event["reasons"])
        self.assertIn("stress_scenario_not_available_at_decision", event["reasons"])

    def test_report_counts_independent_cash_dates_not_asset_rows(self) -> None:
        first = _event()
        second = _event(
            instrument=dataclasses.replace(
                _instrument(),
                venue_symbol="TSLAUSDT",
                venue_base_currency="TSLA",
                cash_symbol="TSLA",
            ),
            mapped_quote=_quote(
                "TSLAUSDT", 299.4, 299.6,
                product_kind="equity_perpetual", quote_currency="USDT",
                venue="binance", session="continuous",
            ),
            cash_premarket_quote=_quote(
                "TSLA", 304.9, 305.1,
                product_kind="cash_equity", quote_currency="USD",
                venue="nasdaq", session="premarket",
                quote_at="2026-07-20T13:24:56+00:00",
            ),
            corporate_action=dataclasses.replace(
                _action(), cash_symbol="TSLA"
            ),
        )
        report = build_equity_mapping_g0_report((first, second))
        self.assertEqual(report["event_count"], 2)
        self.assertEqual(report["independence"]["independent_cash_trading_dates"], 1)
        self.assertEqual(report["verdict"], "collect_equity_mapping_independent_dates")
        self.assertFalse(report["meta"]["pnl_evaluated"])

    def test_duplicate_event_ids_block_report_without_inflating_counts(self) -> None:
        event = _event()
        report = build_equity_mapping_g0_report((event, dict(event)))
        self.assertEqual(report["event_count"], 2)
        self.assertEqual(report["unique_event_count"], 1)
        self.assertEqual(report["duplicate_event_count"], 1)
        self.assertEqual(report["independence"]["asset_event_count"], 1)
        self.assertFalse(report["gates"]["duplicate_event_ids_absent"])
        self.assertEqual(report["verdict"], "block_equity_mapping_g0_data_contract")

    def test_quote_recollection_is_same_event_but_distinct_evidence_revision(self) -> None:
        first = _event()
        revised = _event(
            mapped_quote=_quote(
                "NVDAUSDT", 94.8, 95.0,
                product_kind="equity_perpetual", quote_currency="USDT",
                venue="binance", session="continuous",
            )
        )
        self.assertEqual(first["event_id"], revised["event_id"])
        self.assertNotEqual(
            first["evidence_revision_id"], revised["evidence_revision_id"]
        )
        report = build_equity_mapping_g0_report((first, revised))
        self.assertEqual(report["unique_event_count"], 1)
        self.assertEqual(report["duplicate_event_count"], 1)
        self.assertEqual(report["independence"]["asset_event_count"], 1)

    def test_report_recomputes_and_rejects_forged_economic_event_id(self) -> None:
        first = dict(_event()) | {"event_id": "b" * 64}
        second = dict(_event()) | {"event_id": "c" * 64}
        report = build_equity_mapping_g0_report((first, second))
        self.assertFalse(report["gates"]["all_event_ids_valid"])
        self.assertEqual(report["invalid_event_id_count"], 2)
        self.assertEqual(report["valid_event_count"], 0)
        self.assertEqual(report["verdict"], "block_equity_mapping_g0_data_contract")

    def test_report_rejects_events_built_under_a_different_contract_hash(self) -> None:
        report = build_equity_mapping_g0_report(
            (_event(),),
            config=EquityMappingG0Config(minimum_independent_cash_dates=2),
        )
        self.assertFalse(report["gates"]["all_event_contract_hashes_match"])
        self.assertEqual(report["contract_mismatch_event_count"], 1)
        self.assertEqual(report["verdict"], "block_equity_mapping_g0_data_contract")

    def test_invalid_account_equity_is_a_dataset_configuration_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "equity_mapping_account_equity_invalid"):
            _event(account_equity_usdt=0.0)


if __name__ == "__main__":
    unittest.main()
