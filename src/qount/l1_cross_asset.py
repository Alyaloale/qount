"""Compatibility import for the archived L1 cross-asset line."""

from importlib import import_module as _import_module

_IMPL = _import_module("qount.legacy.l1.l1_cross_asset")


def __getattr__(name: str):
    return getattr(_IMPL, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_IMPL)))
