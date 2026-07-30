"""Compatibility import for the archived A-share ETF line."""

from importlib import import_module as _import_module

_IMPL = _import_module("qount.legacy.ashare_etf.ashare_etf_month")


def __getattr__(name: str):
    return getattr(_IMPL, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_IMPL)))
