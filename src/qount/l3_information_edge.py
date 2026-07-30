"""Compatibility import for the archived L3 information-edge line."""

from importlib import import_module as _import_module

_IMPL = _import_module("qount.legacy.l3.l3_information_edge")


def __getattr__(name: str):
    return getattr(_IMPL, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_IMPL)))
