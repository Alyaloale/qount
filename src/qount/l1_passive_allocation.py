"""Compatibility import for the active Sleeve 1 passive research contract."""

from importlib import import_module as _import_module

_IMPL = _import_module("qount.research.sleeves.l1_passive_allocation")


def __getattr__(name: str):
    return getattr(_IMPL, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_IMPL)))
