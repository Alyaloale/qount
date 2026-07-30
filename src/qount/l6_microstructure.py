"""Compatibility import for the archived L6 microstructure line."""

from importlib import import_module as _import_module

_IMPL = _import_module("qount.legacy.l6.l6_microstructure")


def __getattr__(name: str):
    return getattr(_IMPL, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_IMPL)))
