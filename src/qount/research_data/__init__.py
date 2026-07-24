"""R0-DATA point-in-time data collection infrastructure.

Builds symbol lifecycle records, data-availability manifests, and frozen
universe revisions from Binance public data.  Feeds the R0-DATA step of the
research advancement roadmap.

All modules use injectable fetchers so tests never touch the network.
"""

from qount.research_data.availability import DataAvailability
from qount.research_data.availability import build_availability_manifest
from qount.research_data.availability import probe_funding_month
from qount.research_data.availability import probe_kline_month
from qount.research_data.availability import probe_oi_month
from qount.research_data.availability import scan_funding_availability
from qount.research_data.availability import scan_kline_availability
from qount.research_data.availability import scan_oi_availability
from qount.research_data.lifecycle import EXCHANGE_INFO_URLS
from qount.research_data.lifecycle import VENUE_BY_MARKET
from qount.research_data.lifecycle import build_lifecycle_from_exchange_info
from qount.research_data.lifecycle import build_lifecycle_from_symbol
from qount.research_data.lifecycle import build_rules_dict
from qount.research_data.lifecycle import build_rules_hash
from qount.research_data.lifecycle import fetch_exchange_info
from qount.research_data.lifecycle import infer_spot_listing_date
from qount.research_data.lifecycle import parse_lifecycle_state
from qount.research_data.lifecycle import parse_valid_from
from qount.research_data.lifecycle import parse_valid_to
from qount.research_data.lifecycle import summarize_lifecycle_batch
from qount.research_data.candidate_config import CANDIDATE_CONFIG_SCHEMA_VERSION
from qount.research_data.candidate_config import CandidateConfig
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
from qount.research_data.nav import compute_max_drawdown
from qount.research_data.nav import compute_signal_nav
from qount.research_data.nav import compute_standalone_nav
from qount.research_data.universe import build_revision
from qount.research_data.universe import build_revision_series
from qount.research_data.universe import build_exclusion_reasons
from qount.research_data.universe import monthly_schedule
from qount.research_data.universe import quarterly_schedule
from qount.research_data.universe import summarize_revisions

__all__ = [
    "CANDIDATE_CONFIG_SCHEMA_VERSION",
    "COST_MODEL_TYPES",
    "CandidateConfig",
    "CostComponent",
    "DataAvailability",
    "EXCHANGE_INFO_URLS",
    "FrozenCostModel",
    "NavResult",
    "VENUE_BY_MARKET",
    "build_availability_manifest",
    "build_exclusion_reasons",
    "build_lifecycle_from_exchange_info",
    "build_lifecycle_from_symbol",
    "build_revision",
    "build_revision_series",
    "build_rules_dict",
    "build_rules_hash",
    "compute_carry_signal_nav",
    "compute_carry_standalone_nav",
    "compute_max_drawdown",
    "compute_signal_nav",
    "compute_standalone_nav",
    "default_cxd_trend_cost_model",
    "default_cxd_carry_cost_model",
    "default_cta_r_etf_cost_model",
    "default_cta_r_futures_cost_model",
    "fetch_exchange_info",
    "infer_spot_listing_date",
    "monthly_schedule",
    "parse_lifecycle_state",
    "parse_valid_from",
    "parse_valid_to",
    "probe_funding_month",
    "probe_kline_month",
    "probe_oi_month",
    "quarterly_schedule",
    "scan_funding_availability",
    "scan_kline_availability",
    "scan_oi_availability",
    "summarize_lifecycle_batch",
    "summarize_revisions",
]
