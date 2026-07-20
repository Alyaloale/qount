"""Compatibility exports for the former combined portfolio-governance module.

New code should import from :mod:`qount.contracts`, :mod:`qount.governance`,
or :mod:`qount.portfolio`. This path remains stable during gradual migration.
"""

from qount.contracts import StrategyIntent
from qount.governance import MAX_FORMAL_TRIALS_PER_FAMILY
from qount.governance import SMALL_ACCOUNT_THRESHOLD_USDT
from qount.governance import EquityMappingExecutionContract
from qount.governance import FormalTrial
from qount.governance import ForwardPeriod
from qount.governance import SleeveRuntimeEligibility
from qount.governance import base_operational_evidence
from qount.governance import equity_mapping_event_capacity
from qount.governance import equity_mapping_independence
from qount.governance import funding_episode_independence
from qount.governance import liquid_trend_independence
from qount.governance import record_forward_review
from qount.governance import register_formal_trial
from qount.governance import validate_runtime_eligibility
from qount.portfolio import PORTFOLIO_ACCOUNT_NAV
from qount.portfolio import PROMOTION_NAV
from qount.portfolio import NavAttribution
from qount.portfolio import SleeveRiskBudget
from qount.portfolio import allocate_strategy_intents
from qount.portfolio import scale_standalone_weights

__all__ = [
    "MAX_FORMAL_TRIALS_PER_FAMILY",
    "PORTFOLIO_ACCOUNT_NAV",
    "PROMOTION_NAV",
    "SMALL_ACCOUNT_THRESHOLD_USDT",
    "EquityMappingExecutionContract",
    "FormalTrial",
    "ForwardPeriod",
    "NavAttribution",
    "SleeveRiskBudget",
    "SleeveRuntimeEligibility",
    "StrategyIntent",
    "allocate_strategy_intents",
    "base_operational_evidence",
    "equity_mapping_event_capacity",
    "equity_mapping_independence",
    "funding_episode_independence",
    "liquid_trend_independence",
    "record_forward_review",
    "register_formal_trial",
    "scale_standalone_weights",
    "validate_runtime_eligibility",
]
