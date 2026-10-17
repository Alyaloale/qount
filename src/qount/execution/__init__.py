"""Public compatibility exports loaded only when requested."""
from importlib import import_module

_EXPORTS = {
    'BinanceExecutionStore': ('qount.execution.binance_usdm', 'BinanceExecutionStore'),
    'BinanceUsdMExecution': ('qount.execution.binance_usdm', 'BinanceUsdMExecution'),
    'ExchangeRuleLookupError': ('qount.execution.binance_usdm', 'ExchangeRuleLookupError'),
    'ExecutionContractError': ('qount.execution.binance_usdm', 'ExecutionContractError'),
    'OrdersNotAuthorized': ('qount.execution.binance_usdm', 'OrdersNotAuthorized'),
    'SymbolRule': ('qount.execution.binance_usdm', 'SymbolRule'),
    'lookup_usdm_rule': ('qount.execution.binance_usdm', 'lookup_usdm_rule'),
    'ExchangeOrderObservation': ('qount.execution.state_machine', 'ExchangeOrderObservation'),
    'OrderRecoveryQuery': ('qount.execution.state_machine', 'OrderRecoveryQuery'),
    'OrderRecoveryReport': ('qount.execution.state_machine', 'OrderRecoveryReport'),
    'compare_legacy_dispatch_plan': ('qount.execution.parity', 'compare_legacy_dispatch_plan'),
    'build_portfolio_order_plan': ('qount.execution.planner', 'build_portfolio_order_plan'),
    'order_plan_from_legacy_dry_plan': ('qount.execution.legacy_dispatch', 'order_plan_from_legacy_dry_plan'),
    'recover_unknown_orders': ('qount.execution.recovery', 'recover_unknown_orders'),
    'validate_order_transition': ('qount.execution.state_machine', 'validate_order_transition'),
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
