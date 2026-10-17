"""Public compatibility exports loaded only when requested."""
from importlib import import_module

_EXPORTS = {
    'BASE_STRATEGY_VERSION': ('qount.strategies.base', 'BASE_STRATEGY_VERSION'),
    'base_intent_from_projection': ('qount.strategies.base', 'base_intent_from_projection'),
    'base_snapshot_from_projection': ('qount.strategies.base', 'base_snapshot_from_projection'),
    'base_strategy_registration': ('qount.strategies.base', 'base_strategy_registration'),
    'passive_allocation_strategy_registration': ('qount.strategies.passive_allocation', 'passive_allocation_strategy_registration'),
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
