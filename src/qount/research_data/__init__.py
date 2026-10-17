"""Public compatibility exports loaded only when requested."""
from importlib import import_module

_EXPORTS = {
    'CANDIDATE_CONFIG_SCHEMA_VERSION': ('qount.research_data.candidate_config', 'CANDIDATE_CONFIG_SCHEMA_VERSION'),
    'COST_MODEL_TYPES': ('qount.research_data.cost_model', 'COST_MODEL_TYPES'),
    'CandidateConfig': ('qount.research_data.candidate_config', 'CandidateConfig'),
    'ATR': ('qount.research_data.indicators', 'ATR'),
    'Bar': ('qount.research_data.market_data', 'Bar'),
    'CostComponent': ('qount.research_data.cost_model', 'CostComponent'),
    'DataAvailability': ('qount.research_data.availability', 'DataAvailability'),
    'EXCHANGE_INFO_URLS': ('qount.research_data.lifecycle', 'EXCHANGE_INFO_URLS'),
    'FrozenCostModel': ('qount.research_data.cost_model', 'FrozenCostModel'),
    'Funding': ('qount.research_data.market_data', 'Funding'),
    'KalmanHedge': ('qount.research_data.indicators', 'KalmanHedge'),
    'NavResult': ('qount.research_data.nav', 'NavResult'),
    'VENUE_BY_MARKET': ('qount.research_data.lifecycle', 'VENUE_BY_MARKET'),
    'build_availability_manifest': ('qount.research_data.availability', 'build_availability_manifest'),
    'build_exclusion_reasons': ('qount.research_data.universe', 'build_exclusion_reasons'),
    'build_lifecycle_from_exchange_info': ('qount.research_data.lifecycle', 'build_lifecycle_from_exchange_info'),
    'build_lifecycle_from_symbol': ('qount.research_data.lifecycle', 'build_lifecycle_from_symbol'),
    'build_revision': ('qount.research_data.universe', 'build_revision'),
    'build_revision_series': ('qount.research_data.universe', 'build_revision_series'),
    'build_rules_dict': ('qount.research_data.lifecycle', 'build_rules_dict'),
    'build_rules_hash': ('qount.research_data.lifecycle', 'build_rules_hash'),
    'compute_carry_signal_nav': ('qount.research_data.nav', 'compute_carry_signal_nav'),
    'compute_carry_standalone_nav': ('qount.research_data.nav', 'compute_carry_standalone_nav'),
    'compute_max_drawdown': ('qount.research_data.nav', 'compute_max_drawdown'),
    'compute_signal_nav': ('qount.research_data.nav', 'compute_signal_nav'),
    'compute_standalone_nav': ('qount.research_data.nav', 'compute_standalone_nav'),
    'default_cxd_trend_cost_model': ('qount.research_data.cost_model', 'default_cxd_trend_cost_model'),
    'default_cxd_carry_cost_model': ('qount.research_data.cost_model', 'default_cxd_carry_cost_model'),
    'default_cta_r_etf_cost_model': ('qount.research_data.cost_model', 'default_cta_r_etf_cost_model'),
    'default_cta_r_futures_cost_model': ('qount.research_data.cost_model', 'default_cta_r_futures_cost_model'),
    'deflated_sharpe_ratio': ('qount.research_data.metrics', 'deflated_sharpe_ratio'),
    'expected_max_sharpe': ('qount.research_data.metrics', 'expected_max_sharpe'),
    'fetch_exchange_info': ('qount.research_data.lifecycle', 'fetch_exchange_info'),
    'infer_spot_listing_date': ('qount.research_data.lifecycle', 'infer_spot_listing_date'),
    'load_funding': ('qount.research_data.market_data', 'load_funding'),
    'load_klines': ('qount.research_data.market_data', 'load_klines'),
    'monthly_schedule': ('qount.research_data.universe', 'monthly_schedule'),
    'parse_lifecycle_state': ('qount.research_data.lifecycle', 'parse_lifecycle_state'),
    'parse_valid_from': ('qount.research_data.lifecycle', 'parse_valid_from'),
    'parse_valid_to': ('qount.research_data.lifecycle', 'parse_valid_to'),
    'probe_funding_month': ('qount.research_data.availability', 'probe_funding_month'),
    'probe_kline_month': ('qount.research_data.availability', 'probe_kline_month'),
    'probe_oi_month': ('qount.research_data.availability', 'probe_oi_month'),
    'pbo_cscv': ('qount.research_data.metrics', 'pbo_cscv'),
    'parse_funding_csv': ('qount.research_data.market_data', 'parse_funding_csv'),
    'parse_kline_csv': ('qount.research_data.market_data', 'parse_kline_csv'),
    'quarterly_schedule': ('qount.research_data.universe', 'quarterly_schedule'),
    'scan_funding_availability': ('qount.research_data.availability', 'scan_funding_availability'),
    'scan_kline_availability': ('qount.research_data.availability', 'scan_kline_availability'),
    'scan_oi_availability': ('qount.research_data.availability', 'scan_oi_availability'),
    'summarize_lifecycle_batch': ('qount.research_data.lifecycle', 'summarize_lifecycle_batch'),
    'summarize_revisions': ('qount.research_data.universe', 'summarize_revisions'),
    'returns_from_curve': ('qount.research_data.metrics', 'returns_from_curve'),
    'sharpe': ('qount.research_data.metrics', 'sharpe'),
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, symbol = _EXPORTS[name]
    value = getattr(import_module(module), symbol)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
