"""Append-only forward collection schema contracts for Wave 3 derivative families.

Defines the frozen data contracts for OI/flow, basis curve, liquidation cascade
and cross-venue price discovery. These families can only collect from the current
point forward; official Binance history is limited to 1 month (OI) or 30 days
(basis/taker/long-short ratios), and liquidation has no official archive.

Each contract specifies: raw source, aggregation, clock, dedup/gap rules, the
pre-registered independent window, and the hard constraint that results are not
read until the window is reached. No PnL, no direction, no strategy signal.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from qount.contracts import canonical_hash


FORWARD_SCHEMA_VERSION = "forward_collection_schema_v0.1"


@dataclass(frozen=True)
class ForwardCollectionContract:
    family: str
    candidate_id: str
    trial_number_within_family: int
    family_trial_budget: int
    raw_sources: tuple[str, ...]
    aggregation: str
    clock: str
    dedup_rule: str
    gap_rule: str
    official_history_limit: str
    independent_window_days: int
    venues: tuple[str, ...]
    fields: tuple[str, ...]
    read_results_before_window: bool
    output_role: str

    @property
    def contract_basis(self) -> dict[str, Any]:
        return {
            "schema_version": FORWARD_SCHEMA_VERSION,
            "family": self.family,
            "candidate_id": self.candidate_id,
            "trial_number_within_family": self.trial_number_within_family,
            "family_trial_budget": self.family_trial_budget,
            "raw_sources": list(self.raw_sources),
            "aggregation": self.aggregation,
            "clock": self.clock,
            "dedup_rule": self.dedup_rule,
            "gap_rule": self.gap_rule,
            "official_history_limit": self.official_history_limit,
            "independent_window_days": self.independent_window_days,
            "venues": list(self.venues),
            "fields": list(self.fields),
            "read_results_before_window": self.read_results_before_window,
            "output_role": self.output_role,
            "candidate_pnl_ready": False,
            "promotion_evidence": False,
            "orders_authorized": False,
        }

    @property
    def contract_hash(self) -> str:
        return canonical_hash(self.contract_basis)


OI_FLOW_FORWARD = ForwardCollectionContract(
    family="oi_flow_forward_v1",
    candidate_id="oi_flow_state_v0",
    trial_number_within_family=0,
    family_trial_budget=2,
    raw_sources=(
        "binance_futures_data_openInterestHist",
        "binance_futures_data_takerlongshortRatio",
        "binance_um_klines_taker_buy_volume",
        "binance_um_fundingRate",
    ),
    aggregation="5m/1h raw -> 4h/1d aggregate",
    clock="exchange_settlement_timestamp_not_retrieved_at",
    dedup_rule="hash_of(symbol_interval_timestamp_value); keep first occurrence",
    gap_rule="missing_interval_marked_null_never_forward_filled",
    official_history_limit="OI 1 month; taker/long-short ratios 30 days",
    independent_window_days=90,
    venues=("binance",),
    fields=("open_interest", "taker_buy_volume", "taker_sell_volume", "funding_rate", "close_price"),
    read_results_before_window=False,
    output_role="positioning_state_no_direction_no_pnl",
)

BASIS_CURVE_FORWARD = ForwardCollectionContract(
    family="basis_curve_dislocation_v1",
    candidate_id="basis_curve_state_v0",
    trial_number_within_family=0,
    family_trial_budget=2,
    raw_sources=(
        "binance_futures_data_basis",
        "binance_fapi_premiumIndex",
        "binance_um_fundingRate",
    ),
    aggregation="daily settlement snapshot",
    clock="settlement_timestamp_not_retrieved_at",
    dedup_rule="hash_of(symbol_date_basis_type); keep first occurrence",
    gap_rule="missing_settlement_marked_null_never_interpolated",
    official_history_limit="basis statistics 30 days; premiumIndex current only",
    independent_window_days=90,
    venues=("binance",),
    fields=("perp_premium", "dated_basis", "curve_slope", "funding_rate", "index_price", "mark_price"),
    read_results_before_window=False,
    output_role="crowding_tail_state_no_carry_no_pnl",
)

LIQUIDATION_CASCADE_FORWARD = ForwardCollectionContract(
    family="liquidation_cascade_forward_v1",
    candidate_id="liquidation_cascade_state_v0",
    trial_number_within_family=0,
    family_trial_budget=2,
    raw_sources=(
        "binance_ws_forceOrder_stream",
        "binance_futures_data_openInterestHist",
        "binance_um_depth_snapshot",
        "binance_um_klines",
    ),
    aggregation="event_triggered -> intensity/OI/direction/concentration/recovery",
    clock="exchange_event_timestamp_not_retrieved_at",
    dedup_rule="trade_id_dedup; cross-reconnect gap marked",
    gap_rule="disconnect_interval_marked_with_start_end_gap_flag",
    official_history_limit="no official historical archive; realtime stream only",
    independent_window_days=180,
    venues=("binance",),
    fields=("liquidation_price", "liquidation_qty", "side", "oi_at_event", "depth_at_event", "price_at_event"),
    read_results_before_window=False,
    output_role="cascade_risk_state_no_direction_no_pnl",
)

CROSS_VENUE_FORWARD = ForwardCollectionContract(
    family="cross_venue_price_discovery_v1",
    candidate_id="cross_venue_state_v0",
    trial_number_within_family=0,
    family_trial_budget=2,
    raw_sources=(
        "binance_um_aggTrades",
        "binance_um_bookTicker",
        "bybit_v5_public_trade",
        "bybit_v5_public_ticker",
        "okx_public_trade",
        "okx_public_ticker",
    ),
    aggregation="5m/1h synced trade/quote -> laggard residual",
    clock="exchange_event_timestamp_normalized_to_utc_not_retrieved_at",
    dedup_rule="venue_trade_id_dedup; clock_skew_flagged_not_corrected",
    gap_rule="venue_outage_marked_with_start_end; transfer_borrow_fee_recorded",
    official_history_limit="no cross-venue historical; append-only from now",
    independent_window_days=90,
    venues=("binance", "bybit", "okx"),
    fields=("venue_trade_price", "venue_quote_bid", "venue_quote_ask", "mark_price", "index_price", "fee_tier", "transfer_cost_estimate"),
    read_results_before_window=False,
    output_role="laggard_residual_forecast_no_arb_no_pnl_until_window",
)

ALL_FORWARD_CONTRACTS = (
    OI_FLOW_FORWARD,
    BASIS_CURVE_FORWARD,
    LIQUIDATION_CASCADE_FORWARD,
    CROSS_VENUE_FORWARD,
)


def build_forward_schema_report(observed_at: str) -> dict[str, Any]:
    contracts = []
    for contract in ALL_FORWARD_CONTRACTS:
        entry = {**contract.contract_basis, "contract_hash": contract.contract_hash}
        entry["remaining_blockers"] = [
            "append_only_collection_not_started",
            "independent_window_not_reached",
            "results_not_read",
        ]
        entry["verdict"] = "continue_collection"
        contracts.append(entry)
    return {
        "schema_version": FORWARD_SCHEMA_VERSION,
        "artifact_type": "forward_collection_schema",
        "observed_at": observed_at,
        "meta": {
            "research_only": True,
            "direction_produced": False,
            "pnl_evaluated": False,
            "candidate_pnl_ready": False,
            "promotion_evidence": False,
            "orders_authorized": False,
        },
        "contracts": contracts,
        "hard_constraints": [
            "official_short_history_must_not_be_sliced_into_multiple_folds",
            "results_not_read_until_independent_window_reached",
            "raw_response_and_source_commit_hash_must_be_preserved",
            "gap_and_disconnect_must_be_marked_never_forward_filled",
            "cross_venue_clock_skew_flagged_not_corrected",
        ],
    }
