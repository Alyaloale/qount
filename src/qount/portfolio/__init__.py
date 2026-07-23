"""Portfolio aggregation and virtual-account contracts."""

from qount.portfolio.allocator import allocate_strategy_intents
from qount.portfolio.allocator import portfolio_target_from_allocation
from qount.portfolio.models import PORTFOLIO_ACCOUNT_NAV
from qount.portfolio.models import PROMOTION_NAV
from qount.portfolio.models import NavAttribution
from qount.portfolio.models import SleeveRiskBudget
from qount.portfolio.models import scale_standalone_weights

__all__ = [
    "PORTFOLIO_ACCOUNT_NAV",
    "PROMOTION_NAV",
    "NavAttribution",
    "SleeveRiskBudget",
    "MultiSleeveVirtualArtifactError",
    "MultiSleeveVirtualArtifactIncompleteError",
    "MultiSleeveVirtualRuntimeError",
    "VerifiedMultiSleeveVirtualArtifact",
    "VirtualExecutionCostModel",
    "allocate_strategy_intents",
    "portfolio_target_from_allocation",
    "read_multi_sleeve_virtual_artifact",
    "run_multi_sleeve_virtual_runtime",
    "scale_standalone_weights",
]


_VIRTUAL_RUNTIME_EXPORTS = {
    "MultiSleeveVirtualArtifactError",
    "MultiSleeveVirtualArtifactIncompleteError",
    "MultiSleeveVirtualRuntimeError",
    "VerifiedMultiSleeveVirtualArtifact",
    "VirtualExecutionCostModel",
    "read_multi_sleeve_virtual_artifact",
    "run_multi_sleeve_virtual_runtime",
}


def __getattr__(name: str) -> object:
    """Load the ledger-backed virtual runtime without creating import cycles."""

    if name in _VIRTUAL_RUNTIME_EXPORTS:
        from qount.portfolio import virtual_runtime

        return getattr(virtual_runtime, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
