"""Fail-closed readiness contract for a one-month MiniTrend UM live pilot."""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
from dataclasses import asdict, dataclass
from typing import Any

from qount.artifacts import write_research_json_artifact
from qount.mini_trend.forward import TOP3
from qount.mini_trend.futures_recovery import canonical_hash
from qount.models import utc_now
from qount.settings import Settings


LIVE_PILOT_READINESS_VERSION = "mini_trend_um_live_pilot_readiness_v0.6"
LIVE_PILOT_JOURNAL_VERSION = "mini_trend_um_live_pilot_journal_v0.1"


@dataclass(frozen=True)
class OneMonthLivePilotContract:
    strategy: str = "MiniTrend-UM-Base-v0.2"
    shadow_candidate: str = "MiniTrend-UM-RiskTier-v0.2"
    secondary_shadow_candidate: str = "MiniTrend-UM-FundingVeto-v0.1"
    market: str = "um"
    interval: str = "1d"
    universe: tuple[str, ...] = TOP3
    direction: str = "long_cash"
    duration_days: int = 30
    minimum_capital_usdt: float = 100.0
    maximum_capital_usdt: float = 1000.0
    maximum_effective_gross: float = 1.0
    exchange_leverage: int = 1
    margin_mode: str = "isolated"
    position_mode: str = "oneway"
    daily_chandelier_atr_multiple: float = 3.0
    stop_cooldown_completed_bars: int = 3
    rebalance_deadband: float = 0.35
    maximum_daily_loss_pct: float | None = None
    maximum_pilot_drawdown_pct: float = 10.0
    minimum_forward_pairs: int = 60
    minimum_forward_active_bars: int = 10
    minimum_paper_days: int = 30
    minimum_dry_run_days: int = 7

    @property
    def contract_basis(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "execution": {
                "capital_selection": "audited_usd_m_available_balance_at_runtime",
                "capital_frozen_at_manual_arm": True,
                "maximum_decision_batches_per_completed_day": 1,
                "market_orders_only": True,
                "private_api_key_reading_permission_required": True,
                "private_api_key_spot_margin_permission_allowed": True,
                "private_api_key_withdrawal_permission_allowed": False,
                "shorting_allowed": False,
                "carry_allowed": False,
                "leverage_boost_allowed": False,
                "funding_veto_controls_live_orders": False,
                "risk_tier_controls_live_orders": False,
                "legacy_x4_or_cxd_runtime_reused": False,
                "journal_schema": LIVE_PILOT_JOURNAL_VERSION,
                "append_only_row_and_chain_hashes": True,
                "independent_runtime_required": True,
            },
            "safety": {
                "unknown_balance_or_positions": "halt",
                "unexpected_short_or_non_top3_position": "halt",
                "wrong_leverage_margin_or_position_mode": "halt",
                "missing_completed_price_or_funding_journal": "halt",
                "duplicate_decision_or_order_intent": "halt",
                "account_daily_loss_limit": None,
                "pilot_drawdown_limit": "flatten_then_halt",
                "manual_final_arm_required": True,
            },
        }

    @property
    def contract_hash(self) -> str:
        return canonical_hash(self.contract_basis)


LIVE_PILOT_CONTRACT = OneMonthLivePilotContract()


@dataclass(frozen=True)
class LivePilotRequest:
    owner_requested_one_month_live: bool = False
    capital_usdt: float | None = None
    start_date: str | None = None
    duration_days: int = 30


@dataclass(frozen=True)
class LivePilotEvidence:
    forward_pairs: int = 0
    forward_active_bars: int = 0
    paper_days: int = 0
    paper_schema_error_count: int = 0
    dry_run_days: int = 0
    dry_run_schema_error_count: int = 0
    independent_runtime_verified: bool = False
    complete_funding_journal: bool = False
    configured_exchange_route_ok: bool = False
    public_api_ok: bool = False
    credentials_ok: bool = False
    api_key_reading_enabled: bool = False
    api_key_spot_margin_disabled: bool = False
    api_key_withdrawal_disabled: bool = False
    api_key_futures_enabled: bool = False
    api_key_ip_restricted: bool = False
    account_balance_audit_complete: bool = False
    available_balance_usdt: float | None = None
    position_mode_oneway: bool = False
    position_audit_complete: bool = False
    unmanaged_position_count: int | None = None
    account_flat: bool = False
    open_order_audit_complete: bool = False
    open_order_count: int | None = None
    isolated_one_x_verified: bool = False
    legacy_production_cron_disabled: bool = False
    legacy_live_guard_disarmed: bool = False
    rollback_documented: bool = False


def _pilot_window(request: LivePilotRequest) -> tuple[str | None, str | None, bool]:
    if request.start_date is None:
        return None, None, False
    try:
        start = dt.date.fromisoformat(request.start_date)
    except ValueError:
        return request.start_date, None, False
    end_exclusive = start + dt.timedelta(days=request.duration_days)
    return start.isoformat(), end_exclusive.isoformat(), request.duration_days == 30


def build_live_pilot_readiness(
    request: LivePilotRequest,
    evidence: LivePilotEvidence,
    *,
    contract: OneMonthLivePilotContract | None = None,
) -> dict[str, Any]:
    contract = contract or LIVE_PILOT_CONTRACT
    start_date, end_date_exclusive, exact_window = _pilot_window(request)
    exact_capital = (
        request.capital_usdt is not None
        and contract.minimum_capital_usdt
        <= request.capital_usdt
        <= contract.maximum_capital_usdt
    )
    no_unmanaged_positions = (
        evidence.position_audit_complete and evidence.unmanaged_position_count == 0
    )
    capital_available = (
        exact_capital
        and evidence.account_balance_audit_complete
        and evidence.available_balance_usdt is not None
        and evidence.available_balance_usdt + 1e-12 >= float(request.capital_usdt)
    )
    no_open_orders = (
        evidence.open_order_audit_complete and evidence.open_order_count == 0
    )
    gates = {
        "owner_requested_one_month_live": request.owner_requested_one_month_live,
        "exact_capital_within_pilot_cap": exact_capital,
        "exact_thirty_day_window": exact_window,
        "minimum_forward_pairs": evidence.forward_pairs >= contract.minimum_forward_pairs,
        "minimum_forward_active_bars": (
            evidence.forward_active_bars >= contract.minimum_forward_active_bars
        ),
        "minimum_paper_days": evidence.paper_days >= contract.minimum_paper_days,
        "paper_state_schema_clean": evidence.paper_schema_error_count == 0,
        "minimum_dry_run_days": evidence.dry_run_days >= contract.minimum_dry_run_days,
        "dry_run_state_schema_clean": evidence.dry_run_schema_error_count == 0,
        "independent_runtime_verified": evidence.independent_runtime_verified,
        "complete_funding_journal": evidence.complete_funding_journal,
        "configured_exchange_route": evidence.configured_exchange_route_ok,
        "public_exchange_api": evidence.public_api_ok,
        "private_credentials": evidence.credentials_ok,
        "api_key_reading_enabled": evidence.api_key_reading_enabled,
        "api_key_withdrawal_disabled": evidence.api_key_withdrawal_disabled,
        "api_key_futures_enabled": evidence.api_key_futures_enabled,
        "api_key_ip_restricted": evidence.api_key_ip_restricted,
        "account_balance_audit_complete": evidence.account_balance_audit_complete,
        "pilot_capital_available": capital_available,
        "position_mode_oneway": evidence.position_mode_oneway,
        "position_audit_complete": evidence.position_audit_complete,
        "no_unmanaged_positions": no_unmanaged_positions,
        "account_flat": evidence.position_audit_complete and evidence.account_flat,
        "open_order_audit_complete": evidence.open_order_audit_complete,
        "no_open_orders": no_open_orders,
        "isolated_one_x_verified": evidence.isolated_one_x_verified,
        "legacy_production_cron_disabled": evidence.legacy_production_cron_disabled,
        "legacy_live_guard_disarmed": evidence.legacy_live_guard_disarmed,
        "rollback_documented": evidence.rollback_documented,
    }
    readiness_passed = all(gates.values())
    return {
        "schema_version": LIVE_PILOT_READINESS_VERSION,
        "artifact_type": "mini_trend_um_live_pilot_readiness",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "private_api_order_attempted": False,
            "live_orders_allowed": False,
            "manual_final_arm_required": True,
        },
        "contract": contract.contract_basis | {"contract_hash": contract.contract_hash},
        "request": {
            **asdict(request),
            "start_date": start_date,
            "end_date_exclusive": end_date_exclusive,
        },
        "evidence": asdict(evidence),
        "gates": gates,
        "diagnostics": {
            "readiness_passed": readiness_passed,
            "blockers": [name for name, passed in gates.items() if not passed],
            "verdict": (
                "ready_for_manual_final_arm"
                if readiness_passed
                else "blocked_live_pilot_readiness"
            ),
            "selected_live_strategy": contract.strategy,
            "profit_candidate_role": "shadow_only",
            "secondary_funding_veto_role": "shadow_only",
            "live_orders_allowed": False,
        },
        "readiness_hash": canonical_hash(
            {
                "contract_hash": contract.contract_hash,
                "request": asdict(request),
                "evidence": asdict(evidence),
                "gates": gates,
            }
        ),
    }


def write_live_pilot_readiness_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-live-pilot-readiness",
        path_key="artifact_path",
        default_filename="mini_trend_um_live_pilot_readiness.json",
        explicit_path=explicit_path,
    )


_JOURNAL_REQUIRED_FIELDS = {
    "decision_date",
    "recorded_at",
    "mode",
    "strategy",
    "capital_cap_usdt",
    "wallet_balance_usdt",
    "equity_usdt",
    "desired_weights",
    "actual_weights",
    "order_intents",
    "order_results",
    "funding_pnl_usdt",
    "fees_usdt",
    "execution_state",
    "risk_flags",
}


def _journal_core(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in {"row_hash", "chain_hash"}}


def _validate_journal_core(row: dict[str, Any]) -> None:
    missing = sorted(_JOURNAL_REQUIRED_FIELDS - set(row))
    if missing:
        raise ValueError(f"pilot journal row missing fields: {','.join(missing)}")
    dt.date.fromisoformat(str(row["decision_date"]))
    dt.datetime.fromisoformat(str(row["recorded_at"]))
    if row["mode"] not in {"paper", "live"}:
        raise ValueError("pilot journal mode must be paper or live")
    if row["strategy"] != LIVE_PILOT_CONTRACT.strategy:
        raise ValueError("pilot journal strategy mismatch")
    capital = float(row["capital_cap_usdt"])
    if not 0.0 < capital <= LIVE_PILOT_CONTRACT.maximum_capital_usdt:
        raise ValueError("pilot journal capital exceeds the live-pilot cap")
    for key in ("wallet_balance_usdt", "equity_usdt"):
        if float(row[key]) < 0.0:
            raise ValueError(f"pilot journal {key} must be non-negative")
    for key in ("desired_weights", "actual_weights"):
        weights = row[key]
        if not isinstance(weights, dict) or set(weights) != set(TOP3):
            raise ValueError(f"pilot journal {key} must contain exactly TOP3")
        if any(float(value) < 0.0 for value in weights.values()):
            raise ValueError(f"pilot journal {key} cannot contain short exposure")
        if sum(float(value) for value in weights.values()) > 1.0 + 1e-12:
            raise ValueError(f"pilot journal {key} exceeds gross one")
    if not isinstance(row["order_intents"], list) or not isinstance(row["order_results"], list):
        raise ValueError("pilot journal orders must be lists")
    if not isinstance(row["execution_state"], dict) or not isinstance(row["risk_flags"], list):
        raise ValueError("pilot journal execution_state/risk_flags schema mismatch")


def verify_live_pilot_journal(path: str | os.PathLike[str]) -> dict[str, Any]:
    source = os.fspath(path)
    if not os.path.exists(source):
        return {"row_count": 0, "final_chain_hash": "0" * 64, "decision_dates": []}
    rows = []
    previous_chain_hash = "0" * 64
    decision_dates: list[str] = []
    with open(source, encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"pilot journal row {line_number} is not an object")
            core = _journal_core(row)
            _validate_journal_core(core)
            row_hash = canonical_hash(core)
            chain_hash = canonical_hash(
                {"previous_chain_hash": previous_chain_hash, "row_hash": row_hash}
            )
            if row.get("row_hash") != row_hash or row.get("chain_hash") != chain_hash:
                raise ValueError(f"pilot journal hash mismatch at row {line_number}")
            decision_date = str(core["decision_date"])
            if decision_date in decision_dates:
                raise ValueError(f"duplicate pilot journal decision date: {decision_date}")
            decision_dates.append(decision_date)
            previous_chain_hash = chain_hash
            rows.append(row)
    return {
        "schema_version": LIVE_PILOT_JOURNAL_VERSION,
        "row_count": len(rows),
        "final_chain_hash": previous_chain_hash,
        "decision_dates": decision_dates,
    }


def append_live_pilot_journal(
    path: str | os.PathLike[str], row: dict[str, Any]
) -> dict[str, Any]:
    target = os.fspath(path)
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    core = _journal_core(dict(row))
    _validate_journal_core(core)
    with open(target, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.seek(0)
            existing_lines = [line for line in handle if line.strip()]
            if existing_lines:
                current = verify_live_pilot_journal(target)
            else:
                current = {
                    "row_count": 0,
                    "final_chain_hash": "0" * 64,
                    "decision_dates": [],
                }
            decision_date = str(core["decision_date"])
            if decision_date in current["decision_dates"]:
                raise ValueError(f"duplicate pilot journal decision date: {decision_date}")
            row_hash = canonical_hash(core)
            chain_hash = canonical_hash(
                {
                    "previous_chain_hash": current["final_chain_hash"],
                    "row_hash": row_hash,
                }
            )
            payload = core | {"row_hash": row_hash, "chain_hash": chain_hash}
            handle.seek(0, os.SEEK_END)
            handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return payload
