"""Compatibility import for the active Sleeve 1 breadth research helper."""

from importlib import import_module as _import_module

_IMPL = _import_module("qount.research.sleeves.spdr_sector_breadth")


def __getattr__(name: str):
    return getattr(_IMPL, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_IMPL)))
