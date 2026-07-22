"""Fault injection scenarios for the local venue gateway.

Each scenario describes one injected fault (ACK loss, timeout, partial
fill, crash at a specific state, etc.).  The gateway checks the injector
before responding to each operation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


FAULT_TYPES = (
    "ack_loss",
    "rest_timeout",
    "ws_reorder",
    "ws_duplicate",
    "ws_disconnect",
    "partial_fill",
    "crash_at_submitting",
    "crash_at_acknowledged",
    "crash_at_partial",
    "duplicate_client_id",
)


@dataclass(frozen=True)
class FaultScenario:
    """One scheduled fault for the local venue gateway."""

    scenario_id: str
    trigger_client_order_id: str
    fault_type: str
    parameters: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.scenario_id:
            errors.append("fault_scenario_id_empty")
        if not self.trigger_client_order_id:
            errors.append("fault_scenario_trigger_empty")
        if self.fault_type not in FAULT_TYPES:
            errors.append("fault_scenario_type_invalid")
        return tuple(errors)


class FaultInjector:
    """Schedule and check fault scenarios by client_order_id."""

    def __init__(self) -> None:
        self._scenarios: dict[str, FaultScenario] = {}
        self._fired: set[str] = set()

    def register(self, scenario: FaultScenario) -> None:
        errors = scenario.validate()
        if errors:
            raise ValueError(
                f"fault_scenario_invalid:{','.join(errors)}"
            )
        self._scenarios[scenario.trigger_client_order_id] = scenario

    def check(
        self,
        client_order_id: str,
        operation: str,
    ) -> FaultScenario | None:
        """Return the matching scenario if it should fire, else None.

        Each scenario fires at most once.
        """
        scenario = self._scenarios.get(client_order_id)
        if scenario is None:
            return None
        if client_order_id in self._fired:
            return None
        self._fired.add(client_order_id)
        return scenario

    @property
    def fired_count(self) -> int:
        return len(self._fired)
