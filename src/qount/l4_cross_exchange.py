"""Compatibility import for the archived L4 cross-exchange line."""

from importlib import import_module as _import_module

_IMPL = _import_module("qount.legacy.l4.l4_cross_exchange")


def __getattr__(name: str):
    return getattr(_IMPL, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_IMPL)))
