"""Certification runner: orchestrates Plan -> Run -> Events -> Result.

Ties together the Phase A building blocks (contracts, gateway, fault
injection, replay, attribution) into an end-to-end certification run.

The runner depends on a VenueAdapter Protocol, not on any specific venue
implementation.  This keeps the pure core free of ccxt imports; the
TestnetVenueClient (which imports ccxt) is injected at runtime.

orders_authorized is always False.  Certification events are recorded
as operational certification cost, never as strategy PnL.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol, Sequence

from qount.certification.contracts import CertificationEvent
from qount.certification.contracts import CertificationPlan
from qount.certification.contracts import CertificationResult
from qount.certification.contracts import CertificationRun
from qount.certification.gateway import GatewayAckLoss
from qount.certification.gateway import GatewayCrash
from qount.certification.gateway import GatewayError
from qount.certification.gateway import GatewayTimeout
from qount.certification.replay import recover_orders
from qount.certification.replay import rest_snapshot_recovery
from qount.certification.replay import verify_no_replacement_orders
from qount.certification.replay import verify_no_unresolved_unknown
from qount.contracts.batch import ArtifactReference
from qount.contracts.hashing import canonical_hash

_ARTIFACT_SCHEMA_VERSION = 1


_STATUS_TO_STATE: dict[str, str] = {
    "NEW": "ACKNOWLEDGED",
    "FILLED": "FILLED",
    "PARTIALLY_FILLED": "PARTIALLY_FILLED",
    "CANCELLED": "CANCELLED",
    "UNKNOWN": "UNKNOWN",
}


_ARTIFACT_FILE_NAMES: dict[str, str] = {
    "authorization": "authorization.json",
    "venue_capability_snapshot": "venue_capability_snapshot.json",
    "certification_preflight": "preflight.json",
    "certification_plan": "certification_plan.json",
    "certification_order_events": "order_events.jsonl",
    "exchange_raw": "exchange_raw.json",
    "query_coverage": "query_coverage.json",
    "runtime_ledger_snapshot": "primary_ledger_snapshot.json",
    "shadow_accountant_snapshot": "shadow_accountant_snapshot.json",
    "reconciliation_diff": "reconciliation_diff.json",
    "operational_cost": "operational_cost.json",
    "zero_position_proof": "zero_position_proof.json",
}


class VenueAdapter(Protocol):
    """Unified interface for local gateway and testnet venue clients."""

    @property
    def orders_authorized(self) -> bool: ...

    @property
    def position_count(self) -> int: ...

    @property
    def order_count(self) -> int: ...

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
    ) -> dict[str, Any]: ...

    def cancel(self, *, client_order_id: str) -> dict[str, Any]: ...

    def query(self, *, client_order_id: str) -> dict[str, Any]: ...

    def snapshot(self) -> dict[str, Any]: ...

    def recover_from_crash(self) -> None: ...


def _custom_reference(
    artifact_type: str,
    payload: dict[str, Any],
    file_name: str,
) -> ArtifactReference:
    payload_hash = canonical_hash(payload)
    core = {
        "artifact_schema_version": _ARTIFACT_SCHEMA_VERSION,
        "artifact_type": artifact_type,
        "object_id": payload_hash,
        "payload": payload,
        "payload_hash": payload_hash,
    }
    artifact_hash = canonical_hash(core)
    return ArtifactReference.create(
        artifact_type=artifact_type,
        object_id=payload_hash,
        payload_hash=payload_hash,
        artifact_hash=artifact_hash,
        file_name=file_name,
    )


def _plan_payload(plan: CertificationPlan) -> dict[str, Any]:
    return {
        "schema_version": plan.schema_version,
        "plan_id": plan.plan_id,
        "certification_type": plan.certification_type,
        "venue_semantic": plan.venue_semantic,
        "symbol": plan.symbol,
        "action": plan.action,
        "max_notional": plan.max_notional,
        "max_fee": plan.max_fee,
        "max_holding_time_seconds": plan.max_holding_time_seconds,
        "owner_authorization_hash": plan.owner_authorization_hash,
        "arm_token_hash": plan.arm_token_hash,
        "expires_at": plan.expires_at,
        "preflight_snapshot_hash": plan.preflight_snapshot_hash,
        "venue_capability_snapshot_hash": plan.venue_capability_snapshot_hash,
        "zero_position_plan": plan.zero_position_plan,
        "failure_handling_path": plan.failure_handling_path,
        "certification_status": plan.certification_status,
        "batch_type": plan.batch_type,
        "pnl_attribution": plan.pnl_attribution,
        "strategy_id": plan.strategy_id,
        "portfolio_nav": plan.portfolio_nav,
        "orders_authorized": plan.orders_authorized,
        "plan_hash": plan.plan_hash,
    }


def _plan_reference(plan: CertificationPlan, file_name: str) -> ArtifactReference:
    payload = _plan_payload(plan)
    payload_hash = canonical_hash(payload)
    core = {
        "artifact_schema_version": _ARTIFACT_SCHEMA_VERSION,
        "artifact_type": "certification_plan",
        "object_id": plan.plan_id,
        "payload": payload,
        "payload_hash": payload_hash,
    }
    artifact_hash = canonical_hash(core)
    return ArtifactReference.create(
        artifact_type="certification_plan",
        object_id=plan.plan_id,
        payload_hash=payload_hash,
        artifact_hash=artifact_hash,
        file_name=file_name,
    )


class CertificationRunner:
    """Orchestrates one certification run against a VenueAdapter.

    Usage::

        gw = LocalVenueGateway()
        runner = CertificationRunner(plan, gw, source="local_gateway")
        run = runner.start()
        runner.submit_order("cert-001", "BTCUSDT", "BUY", 0.001)
        runner.cancel_order("cert-001")
        result = runner.generate_result()
        assert result.completed
    """

    def __init__(
        self,
        plan: CertificationPlan,
        venue: VenueAdapter,
        source: str,
        *,
        venue_capability_payload: dict[str, Any] | None = None,
        evidence_provenance: dict[str, Any] | None = None,
    ) -> None:
        self._plan = plan
        self._venue = venue
        self._source = source
        self._venue_capability_payload = (
            dict(venue_capability_payload)
            if venue_capability_payload is not None
            else {
                "venue": source,
                "compatibility": "pass",
                "symbol_rules": {},
            }
        )
        self._evidence_provenance = dict(evidence_provenance or {})
        if (
            plan.certification_type == "real_minimum"
            and canonical_hash(self._venue_capability_payload)
            != plan.venue_capability_snapshot_hash
        ):
            raise ValueError(
                "real_certification_venue_capability_hash_mismatch"
            )
        self._run: CertificationRun | None = None
        self._events: list[CertificationEvent] = []
        self._raw_responses: list[dict[str, Any]] = []
        self._query_log: list[dict[str, Any]] = []
        self._preflight_snapshot: dict[str, Any] = {}
        self._known_order_ids: set[str] = set()
        self._halt_errors: list[str] = []
        self._artifact_payloads: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def start(self) -> CertificationRun:
        self._preflight_snapshot = self._venue.snapshot()
        self._run = CertificationRun.create(
            plan_id=self._plan.plan_id,
            certification_type=self._plan.certification_type,
            started_at=self._now(),
        )
        return self._run

    @property
    def run(self) -> CertificationRun | None:
        return self._run

    @property
    def events(self) -> tuple[CertificationEvent, ...]:
        return tuple(self._events)

    @property
    def halt_errors(self) -> tuple[str, ...]:
        return tuple(self._halt_errors)

    @property
    def plan(self) -> CertificationPlan:
        return self._plan

    @property
    def artifact_payloads(self) -> dict[str, dict[str, Any]]:
        """Return a copy of the payloads used to build the result references."""

        return {
            name: dict(payload)
            for name, payload in self._artifact_payloads.items()
        }

    def submit_order(
        self,
        client_order_id: str,
        symbol: str,
        side: str,
        qty: float,
        *,
        order_type: str = "MARKET",
        stop_price: float | None = None,
        reduce_only: bool = False,
    ) -> dict[str, Any]:
        if client_order_id in self._known_order_ids:
            raise ValueError(
                f"duplicate_client_order_id_blocked:{client_order_id}"
            )
        self._known_order_ids.add(client_order_id)
        try:
            response = self._venue.submit(
                client_order_id=client_order_id,
                symbol=symbol,
                side=side,
                qty=qty,
                order_type=order_type,
                stop_price=stop_price,
                reduce_only=reduce_only,
            )
        except GatewayAckLoss:
            self._raw_responses.append(
                {"client_order_id": client_order_id, "error": "ack_loss"}
            )
            self._record_event(
                "submit", client_order_id, None, "UNKNOWN"
            )
            raise
        except GatewayTimeout:
            self._raw_responses.append(
                {"client_order_id": client_order_id, "error": "rest_timeout"}
            )
            self._record_event(
                "submit", client_order_id, None, "UNKNOWN"
            )
            raise
        except GatewayCrash:
            self._raw_responses.append(
                {"client_order_id": client_order_id, "error": "gateway_crash"}
            )
            self._record_event(
                "crash", client_order_id, None, "UNKNOWN"
            )
            raise
        self._raw_responses.append(dict(response))
        state = _STATUS_TO_STATE.get(
            str(response.get("status", "")), "ACKNOWLEDGED"
        )
        self._record_event(
            "submit", client_order_id, response, state
        )
        return response

    def cancel_order(self, client_order_id: str) -> dict[str, Any]:
        response = self._venue.cancel(client_order_id=client_order_id)
        self._raw_responses.append(dict(response))
        self._record_event(
            "cancel", client_order_id, response, "CANCELLED"
        )
        return response

    def query_order(self, client_order_id: str) -> dict[str, Any]:
        self._query_log.append(
            {"client_order_id": client_order_id, "timestamp": self._now()}
        )
        try:
            response = self._venue.query(client_order_id=client_order_id)
        except GatewayError:
            self._raw_responses.append(
                {"client_order_id": client_order_id, "error": "not_found"}
            )
            self._record_event(
                "query", client_order_id, None, "UNKNOWN"
            )
            raise
        self._raw_responses.append(dict(response))
        state = _STATUS_TO_STATE.get(
            str(response.get("status", "")), "ACKNOWLEDGED"
        )
        self._record_event(
            "query", client_order_id, response, state
        )
        return response

    def recover_from_crash(
        self,
        client_order_ids: list[str],
    ) -> list[dict[str, Any]]:
        states = recover_orders(self._venue, client_order_ids)
        for state in states:
            cid = str(state.get("client_order_id", ""))
            st = _STATUS_TO_STATE.get(
                str(state.get("status", "")), "UNKNOWN"
            )
            if state.get("status") == "NOT_FOUND":
                st = "UNKNOWN"
            self._raw_responses.append(dict(state))
            self._record_event("recover", cid, state, st)
        post_ids = {s.get("client_order_id") for s in states}
        replacement_errors = verify_no_replacement_orders(
            self._known_order_ids, post_ids
        )
        unknown_errors = verify_no_unresolved_unknown(states)
        all_errors = list(replacement_errors) + list(unknown_errors)
        if all_errors:
            self._halt_errors.extend(all_errors)
            self._record_event("halt", "", None, "UNKNOWN")
        return states

    def rest_snapshot_recover(self) -> dict[str, Any]:
        snap = rest_snapshot_recovery(self._venue)
        self._raw_responses.append({"snapshot_recovery": True})
        self._record_event("recover", "", snap, "FILLED")
        return snap

    def verify_zero_position(self) -> bool:
        return self._venue.position_count == 0

    def generate_result(self) -> CertificationResult:
        if self._run is None:
            raise RuntimeError("runner_not_started")

        completed_at = self._now()
        authorization_payload = {
            "owner_authorization_hash": self._plan.owner_authorization_hash,
            "arm_token_hash": self._plan.arm_token_hash,
            "expires_at": self._plan.expires_at,
            "certification_type": self._plan.certification_type,
            "venue_semantic": self._plan.venue_semantic,
            "runtime_provenance": dict(self._evidence_provenance),
        }
        preflight_payload = {
            "planned_preflight_snapshot_hash": self._plan.preflight_snapshot_hash,
            "positions": dict(self._preflight_snapshot.get("positions", {})),
            "order_count": len(
                self._preflight_snapshot.get("orders", [])
            ),
            "position_count": sum(
                1
                for v in self._preflight_snapshot.get("positions", {}).values()
                if abs(float(v)) > 1e-12
            ),
        }
        events_payload = {
            "events": [evt._core() for evt in self._events],
            "event_count": len(self._events),
        }
        exchange_raw_payload = {
            "responses": self._raw_responses,
            "response_count": len(self._raw_responses),
        }
        query_coverage_payload = {
            "queries": self._query_log,
            "query_count": len(self._query_log),
            "client_order_ids_queried": sorted(
                {q["client_order_id"] for q in self._query_log}
            ),
        }
        primary_snapshot = self._venue.snapshot()
        snapshot_trades = [
            dict(trade)
            for trade in primary_snapshot.get("trades", [])
            if isinstance(trade, dict)
        ]
        certification_trades = self._certification_trades(snapshot_trades)
        runtime_ledger_payload = {
            "orders": primary_snapshot.get("orders", []),
            "positions": dict(primary_snapshot.get("positions", {})),
            "trades": certification_trades,
            "trade_scope": "certification_order_ids",
            "snapshot_trade_count": len(snapshot_trades),
            "matched_trade_count": len(certification_trades),
        }
        shadow_positions = self._reconstruct_positions_from_trades(
            certification_trades
        )
        shadow_accountant_payload = {
            "positions": shadow_positions,
            "trade_count": len(certification_trades),
            "source": "independent_rebuild_from_trades",
        }
        reconciliation_payload = self._build_reconciliation_diff(
            dict(primary_snapshot.get("positions", {})),
            shadow_positions,
        )
        operational_cost_payload = self._build_operational_cost(
            {"trades": certification_trades}
        )
        zero_position = self.verify_zero_position()
        zero_position_payload = {
            "final_position_count": self._venue.position_count,
            "verified": zero_position,
            "halt_errors": list(self._halt_errors),
        }

        plan_ref = _plan_reference(
            self._plan, _ARTIFACT_FILE_NAMES["certification_plan"]
        )
        custom_artifacts: list[tuple[str, dict[str, Any]]] = [
            ("authorization", authorization_payload),
            ("venue_capability_snapshot", self._venue_capability_payload),
            ("certification_preflight", preflight_payload),
            ("certification_order_events", events_payload),
            ("exchange_raw", exchange_raw_payload),
            ("query_coverage", query_coverage_payload),
            ("runtime_ledger_snapshot", runtime_ledger_payload),
            ("shadow_accountant_snapshot", shadow_accountant_payload),
            ("reconciliation_diff", reconciliation_payload),
            ("operational_cost", operational_cost_payload),
            ("zero_position_proof", zero_position_payload),
        ]
        self._artifact_payloads = {
            "certification_plan": _plan_payload(self._plan),
            **{
                artifact_type: payload
                for artifact_type, payload in custom_artifacts
            },
        }
        custom_refs = [
            _custom_reference(
                atype,
                payload,
                _ARTIFACT_FILE_NAMES[atype],
            )
            for atype, payload in custom_artifacts
        ]
        all_members = [plan_ref, *custom_refs]

        zero_proof_hash = canonical_hash(zero_position_payload)
        recon_diff_hash = canonical_hash(reconciliation_payload)
        op_cost_hash = canonical_hash(operational_cost_payload)

        result = CertificationResult.create(
            run_id=self._run.run_id,
            artifact_members=all_members,
            final_zero_position_proof_hash=zero_proof_hash,
            reconciliation_diff_hash=recon_diff_hash,
            operational_cost_hash=op_cost_hash,
            final_position_is_zero=zero_position,
        )

        self._run = CertificationRun.create(
            plan_id=self._plan.plan_id,
            certification_type=self._plan.certification_type,
            started_at=self._run.started_at,
            completed_at=completed_at,
            status="completed" if result.completed else "halted",
        )
        return result

    @staticmethod
    def _build_operational_cost(
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """Rebuild observed trade fees without inventing missing income."""

        commission = 0.0
        observed_trade_count = 0
        fee_records = 0
        for trade in snapshot.get("trades", []):
            if not isinstance(trade, dict):
                continue
            observed_trade_count += 1
            fee = trade.get("fee")
            fee_value: Any = None
            if isinstance(fee, dict):
                fee_value = fee.get("cost")
            if fee_value is None:
                fee_value = trade.get("commission")
            if fee_value is None:
                info = trade.get("info")
                if isinstance(info, dict):
                    fee_value = info.get("commission")
            if fee_value is None:
                continue
            try:
                commission += abs(float(fee_value))
            except (TypeError, ValueError):
                continue
            fee_records += 1
        fees_complete = observed_trade_count > 0 and fee_records == observed_trade_count
        commission_value: Any = commission if fee_records else "unavailable"
        total_value: Any = commission if fees_complete else "unavailable"
        return {
            "commission": commission_value,
            "funding": "unavailable",
            "transfer": "unavailable",
            "total": total_value,
            "observed_trade_count": observed_trade_count,
            "fee_record_count": fee_records,
            "fees_complete": fees_complete,
            "funding_source": "not_queried_for_this_certification_run",
            "transfer_source": "not_in_certification_scope",
            "commission_source": (
                "exchange_trade_fee" if fee_records else "unavailable"
            ),
        }

    def _certification_trades(
        self,
        trades: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        exchange_ids = {
            str(response["exchange_order_id"])
            for response in self._raw_responses
            if response.get("exchange_order_id") not in (None, "")
        }
        known_ids = set(self._known_order_ids) | exchange_ids

        def identifiers(trade: dict[str, Any]) -> set[str]:
            values: set[str] = set()
            for key in (
                "client_order_id",
                "clientOrderId",
                "order",
                "order_id",
                "orderId",
            ):
                value = trade.get(key)
                if value not in (None, ""):
                    values.add(str(value))
            info = trade.get("info")
            if isinstance(info, dict):
                values.update(identifiers(info))
            return values

        return [trade for trade in trades if identifiers(trade) & known_ids]

    def _record_event(
        self,
        event_type: str,
        client_order_id: str,
        response: dict[str, Any] | None,
        observed_state: str,
    ) -> None:
        if self._run is None:
            raise RuntimeError("runner_not_started")
        raw_hash = canonical_hash(
            response if response is not None else {"empty": True}
        )
        exchange_order_id = None
        if response is not None and "exchange_order_id" in response:
            exchange_order_id = response["exchange_order_id"]
        event = CertificationEvent.create(
            run_id=self._run.run_id,
            event_type=event_type,
            client_order_id=client_order_id or "none",
            timestamp=self._now(),
            observed_state=observed_state,
            raw_response_hash=raw_hash,
            source=self._source,
            exchange_order_id=exchange_order_id,
        )
        self._events.append(event)

    @staticmethod
    def _reconstruct_positions_from_trades(
        trades: list[dict[str, Any]],
    ) -> dict[str, float]:
        positions: dict[str, float] = {}
        for trade in trades:
            symbol = str(trade.get("symbol", ""))
            side = str(trade.get("side", "")).upper()
            raw_qty = trade.get("qty", trade.get("amount", 0.0))
            if raw_qty in (None, "") and isinstance(trade.get("info"), dict):
                info = trade["info"]
                raw_qty = info.get("qty", info.get("quantity", 0.0))
            try:
                qty = float(raw_qty)
            except (TypeError, ValueError):
                continue
            if side == "BUY":
                positions[symbol] = positions.get(symbol, 0.0) + qty
            elif side == "SELL":
                positions[symbol] = positions.get(symbol, 0.0) - qty
        return {
            sym: qty for sym, qty in positions.items() if abs(qty) > 1e-12
        }

    @staticmethod
    def _build_reconciliation_diff(
        primary: dict[str, float],
        shadow: dict[str, float],
    ) -> dict[str, Any]:
        all_symbols = sorted(set(primary) | set(shadow))
        fields: list[dict[str, Any]] = []
        all_match = True
        for symbol in all_symbols:
            p = float(primary.get(symbol, 0.0))
            s = float(shadow.get(symbol, 0.0))
            diff = abs(p - s)
            match = diff < 1e-9
            if not match:
                all_match = False
            fields.append(
                {
                    "symbol": symbol,
                    "primary": p,
                    "shadow": s,
                    "diff": diff,
                    "pass": match,
                }
            )
        return {
            "all_match": all_match,
            "fields": fields,
            "field_count": len(fields),
        }
