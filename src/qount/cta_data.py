"""Compatibility import for the archived CTA-R data layer."""

from importlib import import_module as _import_module

_IMPL = _import_module("qount.legacy.line_a.cta_data")


def __getattr__(name: str):
    return getattr(_IMPL, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_IMPL)))
