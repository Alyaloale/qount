"""Independent shadow accountant.

Implements Workstream B of the trading-system-evolution-plan section 4.
Rebuilds positions, cost basis, and NAV from raw exchange responses
independently of the primary ledger, then diffs against it.

Import boundary: this package must NOT import qount.execution,
qount.mini_trend.pilot_dispatcher, or qount.ledger position aggregation.
"""

from qount.shadow_accounting.archive import archive_json
from qount.shadow_accounting.archive import archive_raw_responses
from qount.shadow_accounting.archive import archive_shadow_run
from qount.shadow_accounting.archive import verify_archive
from qount.shadow_accounting.contracts import BLOCKING_LEVELS
from qount.shadow_accounting.contracts import CASH_EVENT_TYPES
from qount.shadow_accounting.contracts import FetchResult
from qount.shadow_accounting.contracts import QueryMetadata
from qount.shadow_accounting.contracts import ShadowCashEvent
from qount.shadow_accounting.contracts import ShadowCoverageWindow
from qount.shadow_accounting.contracts import ShadowNavMark
from qount.shadow_accounting.contracts import ShadowPosition
from qount.shadow_accounting.contracts import ShadowReconciliationDiff
from qount.shadow_accounting.contracts import ShadowRun
from qount.shadow_accounting.contracts import WatermarkContract
from qount.shadow_accounting.diff import diff_nav
from qount.shadow_accounting.diff import diff_positions
from qount.shadow_accounting.diff import has_blocking_diff
from qount.shadow_accounting.fetch import ReadOnlyExchange
from qount.shadow_accounting.fetch import fetch_income_history
from qount.shadow_accounting.fetch import fetch_open_orders
from qount.shadow_accounting.fetch import fetch_private_trades
from qount.shadow_accounting.orchestrator import run_shadow_accountant
from qount.shadow_accounting.progress import PHASE_B_PROGRESS_SCHEMA_VERSION
from qount.shadow_accounting.progress import PHASE_B_REQUIRED_VALID_STREAK
from qount.shadow_accounting.progress import PhaseBProgressError
from qount.shadow_accounting.progress import initialize_phase_b_baseline
from qount.shadow_accounting.progress import record_phase_b_cycle
from qount.shadow_accounting.rebuild import apply_mark_prices
from qount.shadow_accounting.rebuild import detect_unknown_income_halt_candidates
from qount.shadow_accounting.rebuild import rebuild_cash_events
from qount.shadow_accounting.rebuild import rebuild_nav
from qount.shadow_accounting.rebuild import rebuild_positions
from qount.shadow_accounting.rebuild import verify_coverage_window

__all__ = [
    "BLOCKING_LEVELS",
    "CASH_EVENT_TYPES",
    "FetchResult",
    "PHASE_B_PROGRESS_SCHEMA_VERSION",
    "PHASE_B_REQUIRED_VALID_STREAK",
    "PhaseBProgressError",
    "QueryMetadata",
    "ReadOnlyExchange",
    "ShadowCashEvent",
    "ShadowCoverageWindow",
    "ShadowNavMark",
    "ShadowPosition",
    "ShadowReconciliationDiff",
    "ShadowRun",
    "WatermarkContract",
    "archive_json",
    "archive_raw_responses",
    "archive_shadow_run",
    "apply_mark_prices",
    "detect_unknown_income_halt_candidates",
    "diff_nav",
    "diff_positions",
    "fetch_income_history",
    "fetch_open_orders",
    "fetch_private_trades",
    "has_blocking_diff",
    "initialize_phase_b_baseline",
    "rebuild_cash_events",
    "rebuild_nav",
    "rebuild_positions",
    "record_phase_b_cycle",
    "run_shadow_accountant",
    "verify_archive",
    "verify_coverage_window",
]
