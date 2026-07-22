"""Crash recovery replay for the local venue gateway.

After a crash, the gateway enters a crashed state.  Recovery:
1. Clear the crashed flag
2. Query each persisted order by client_order_id (read-only)
3. UNKNOWN orders are NOT replaced -- no substitute orders
4. REST snapshot covers any WS gaps

This module is pure: it takes a gateway and a list of known
client_order_ids, queries each, and returns the recovered states.
"""

from __future__ import annotations

from typing import Any

from qount.certification.gateway import GatewayCrash
from qount.certification.gateway import GatewayError
from qount.certification.gateway import LocalVenueGateway


def recover_orders(
    gateway: LocalVenueGateway,
    client_order_ids: list[str],
) -> list[dict[str, Any]]:
    """Query each order after a crash.  Does NOT create replacement orders.

    Returns a list of query results.  Orders that are not found
    or remain UNKNOWN are reported as-is.
    """
    if gateway._crashed:
        gateway.recover_from_crash()
    results: list[dict[str, Any]] = []
    for client_order_id in client_order_ids:
        try:
            state = gateway.query(client_order_id=client_order_id)
            results.append(state)
        except GatewayError:
            results.append(
                {
                    "client_order_id": client_order_id,
                    "status": "NOT_FOUND",
                }
            )
    return results


def rest_snapshot_recovery(
    gateway: LocalVenueGateway,
) -> dict[str, Any]:
    """Use REST full snapshot to cover WS gaps after recovery.

    Returns the complete state of all orders, positions, and trades.
    This is the authoritative state after any WS disconnection.
    """
    return gateway.snapshot()


def verify_no_replacement_orders(
    pre_crash_order_ids: set[str],
    post_recovery_order_ids: set[str],
) -> tuple[str, ...]:
    """Verify that no replacement orders were created during recovery.

    Returns error strings; empty means recovery is clean.
    """
    errors: list[str] = []
    new_orders = post_recovery_order_ids - pre_crash_order_ids
    if new_orders:
        errors.append(
            f"replacement_orders_created:{','.join(sorted(new_orders))}"
        )
    return tuple(errors)


def verify_no_unresolved_unknown(
    recovered_states: list[dict[str, Any]],
) -> tuple[str, ...]:
    """Verify that no orders remain in UNKNOWN state after recovery.

    Returns error strings; empty means all orders are resolved.
    """
    errors: list[str] = []
    for state in recovered_states:
        if state.get("status") == "UNKNOWN":
            errors.append(
                f"unresolved_unknown:{state.get('client_order_id', '?')}"
            )
    return tuple(errors)
