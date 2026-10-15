"""Adapters package for normalizing research lines into PaperLine."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional
from qount.api.schemas import PaperLine

_ADAPTER_REGISTRY: Dict[str, Callable[[str, str, Dict[str, Any]], PaperLine]] = {}


def register_adapter(name: str):
    def decorator(fn: Callable[[str, str, Dict[str, Any]], PaperLine]):
        _ADAPTER_REGISTRY[name] = fn
        return fn
    return decorator


def get_adapter(name: str) -> Optional[Callable[[str, str, Dict[str, Any]], PaperLine]]:
    # Trigger lazy import of built-in adapters
    _ensure_loaded()
    return _ADAPTER_REGISTRY.get(name)


def list_adapters() -> list[str]:
    _ensure_loaded()
    return sorted(list(_ADAPTER_REGISTRY.keys()))


_loaded = False


def _ensure_loaded() -> None:
    global _loaded
    if not _loaded:
        import qount.api.adapters.personal_assistant
        import qount.api.adapters.binance_macro
        import qount.api.adapters.ashare_master
        import qount.api.adapters.dual_engine
        import qount.api.adapters.cta_r_forward
        import qount.api.adapters.universal_regime
        _loaded = True
