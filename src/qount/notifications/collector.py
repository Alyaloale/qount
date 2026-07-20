"""Deterministic adapter for the four explicit runtime health probes.

The collector deliberately accepts already-measured values.  Platform-specific
code (systemd, filesystem, clock and backup probes) stays outside the contract
layer and must provide a source id/hash for every measurement.
"""

from __future__ import annotations

from typing import Any, Mapping

from qount.notifications.health import SYSTEM_COMPONENTS
from qount.notifications.health import SystemComponentObservation
from qount.notifications.health import SystemHealthContractError
from qount.notifications.health import SystemHealthSnapshot


class SystemHealthCollectorError(ValueError):
    """Raised when a health probe set is incomplete or has extra fields."""


_MEASUREMENT_FIELDS = {
    "status",
    "detail_codes",
    "metrics",
    "source_id",
    "source_hash",
}


def collect_system_health(
    measurements: Mapping[str, Mapping[str, Any]],
    *,
    observed_at: str,
    captured_at: str,
) -> SystemHealthSnapshot:
    """Build a verified snapshot from one atomic set of four probe readings.

    ``measurements`` must contain exactly ``clock``, ``disk``, ``service`` and
    ``backup``.  Each probe supplies its own source identity and metrics; this
    function never queries the operating system, network, exchange or clock.
    """

    if not isinstance(measurements, Mapping) or set(measurements) != set(
        SYSTEM_COMPONENTS
    ):
        raise SystemHealthCollectorError("system_health_measurements_incomplete")

    observations: list[SystemComponentObservation] = []
    for component in SYSTEM_COMPONENTS:
        raw = measurements[component]
        if not isinstance(raw, Mapping) or set(raw) != _MEASUREMENT_FIELDS:
            raise SystemHealthCollectorError(
                f"system_health_measurement_fields_invalid:{component}"
            )
        try:
            observation = SystemComponentObservation.create(
                component=component,
                status=raw["status"],
                observed_at=observed_at,
                detail_codes=raw["detail_codes"],
                metrics=raw["metrics"],
                source_id=raw["source_id"],
                source_hash=raw["source_hash"],
            )
        except (SystemHealthContractError, TypeError, ValueError) as exc:
            raise SystemHealthCollectorError(
                f"system_health_measurement_invalid:{component}"
            ) from exc
        observations.append(observation)

    try:
        return SystemHealthSnapshot.create(
            observations,
            captured_at=captured_at,
        )
    except (SystemHealthContractError, TypeError, ValueError) as exc:
        raise SystemHealthCollectorError("system_health_snapshot_invalid") from exc


__all__ = ["SystemHealthCollectorError", "collect_system_health"]
