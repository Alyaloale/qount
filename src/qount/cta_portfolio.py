"""Compatibility import for the archived CTA-R portfolio layer."""

from importlib import import_module as _import_module

_IMPL = _import_module("qount.legacy.line_a.cta_portfolio")


def __getattr__(name: str):
    return getattr(_IMPL, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_IMPL)))


if __name__ == "__main__":
    raise SystemExit(_IMPL.main())
