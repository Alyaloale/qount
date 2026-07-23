"""Real Binance USD-M venue client for Phase D certification.

Implements the VenueAdapter Protocol against the real Binance USD-M
production endpoint.  Unlike TestnetVenueClient, real order submission
is gated by an independent CertificationArm (section 3.1): ``submit``
fails closed when the arm is missing, expired, or already used.

``query`` and ``cancel`` are intentionally NOT arm-gated: they only
reduce risk (resolve UNKNOWN, zero out a position) and must remain
usable after an arm expires mid-run (section 5.3 recovery).

This module imports ccxt (transitively via TestnetVenueClient's exchange
injection) and is intentionally NOT in the CERTIFICATION_GATEWAY_MODULES
boundary group.  The pure core (runner.py, contracts.py, arm.py) never
imports this module; it is injected at runtime via the VenueAdapter
Protocol.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from qount.certification.arm import CertificationArm
from qount.certification.testnet_client import TestnetVenueClient


class CertificationArmNotAuthorized(RuntimeError):
    """Raised when a real order is attempted without a valid arm."""


class RealVenueClient(TestnetVenueClient):
    """Real Binance USD-M venue client gated by a CertificationArm."""

    def __init__(
        self,
        exchange: Any,
        arm: CertificationArm,
        *,
        now_provider: Callable[[], str] | None = None,
    ) -> None:
        super().__init__(exchange)
        self._arm = arm
        self._now_provider = now_provider

    def _now(self) -> str:
        if self._now_provider is not None:
            return self._now_provider()
        return datetime.now(timezone.utc).isoformat()

    @property
    def arm(self) -> CertificationArm:
        return self._arm

    @property
    def orders_authorized(self) -> bool:
        return self._arm.is_valid_at(self._now())

    def submit(
        self,
        *,
        client_order_id: str,
        symbol: str,
        side: str,
        qty: float,
        order_type: str = "MARKET",
        stop_price: float | None = None,
        reduce_only: bool = False,
    ) -> dict[str, Any]:
        if not self.orders_authorized:
            raise CertificationArmNotAuthorized(
                "certification_arm_not_authorized_or_expired"
            )
        return super().submit(
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            qty=qty,
            order_type=order_type,
            stop_price=stop_price,
            reduce_only=reduce_only,
        )
