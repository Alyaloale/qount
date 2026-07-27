"""Immutable contracts for the read-only daily intelligence plane."""

from __future__ import annotations

import datetime as dt
import math
import urllib.parse
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from qount.alpha_agents.models import AgentReport
from qount.alpha_agents.models import SourceRef
from qount.alpha_agents.official_sources import validate_official_source_url
from qount.alpha_agents.validators import validate_agent_report
from qount.contracts import canonical_hash
from qount.contracts import is_sha256
from qount.contracts import trace_id
from qount.contracts.trace import aware_datetime


DAILY_INTELLIGENCE_SCHEMA_VERSION = 2
DAILY_INTELLIGENCE_STATUSES = ("clear", "attention_required", "incomplete")
DAILY_INTELLIGENCE_PIPELINE_STATUSES = ("complete", "partial", "failed")
DAILY_INTELLIGENCE_EVIDENCE_STATUSES = ("sufficient", "limited", "insufficient")
DAILY_INTELLIGENCE_ROLES = (
    "market_analyst",
    "event_analyst",
    "execution_reviewer",
    "strategy_reviewer",
    "red_team",
    "editor",
)


class IntelligenceContractError(ValueError):
    """Raised when an intelligence artifact is malformed or tampered."""


def _timestamp(value: str, *, name: str) -> str:
    try:
        parsed = aware_datetime(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise IntelligenceContractError(f"{name}_invalid") from exc
    return parsed.astimezone(dt.timezone.utc).isoformat()


def _text(value: object, *, name: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > maximum
        or any(ord(char) < 32 and char not in "\n\t" for char in value)
    ):
        raise IntelligenceContractError(f"{name}_invalid")
    return value


def _number(value: object, *, name: str) -> float:
    if isinstance(value, bool):
        raise IntelligenceContractError(f"{name}_invalid")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise IntelligenceContractError(f"{name}_invalid") from exc
    if not math.isfinite(number):
        raise IntelligenceContractError(f"{name}_invalid")
    return number


def _json_native(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_native(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_native(item) for item in value]
    return value


@dataclass(frozen=True)
class SearchEvidence:
    query: str
    provider: str
    searched_at: str
    result_count: int
    response_hash: str
    urls: tuple[str, ...]

    def validate(self) -> None:
        _text(self.query, name="search_query", maximum=500)
        _text(self.provider, name="search_provider", maximum=64)
        _timestamp(self.searched_at, name="search_time")
        if (
            not isinstance(self.result_count, int)
            or isinstance(self.result_count, bool)
            or self.result_count < 0
            or self.result_count != len(self.urls)
            or len(self.urls) > 20
        ):
            raise IntelligenceContractError("search_result_count_invalid")
        if not is_sha256(self.response_hash):
            raise IntelligenceContractError("search_response_hash_invalid")
        if len(set(self.urls)) != len(self.urls):
            raise IntelligenceContractError("search_urls_not_unique")
        for url in self.urls:
            _text(url, name="search_url", maximum=2_000)
            if not url.startswith("https://"):
                raise IntelligenceContractError("search_url_invalid")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "query": self.query,
            "provider": self.provider,
            "searched_at": self.searched_at,
            "result_count": self.result_count,
            "response_hash": self.response_hash,
            "urls": list(self.urls),
        }


@dataclass(frozen=True)
class SourceEvidence:
    title: str
    source_url: str
    final_url: str
    observed_at: str
    content_type: str
    byte_count: int
    source_hash: str
    body_hash: str
    text_excerpt: str
    published_at: str | None
    modified_at: str | None
    parser_version: str
    content_quality: str
    extractor: str

    def validate(self) -> None:
        _text(self.title or "untitled", name="source_title", maximum=500)
        _text(self.source_url, name="source_url", maximum=2_000)
        _text(self.final_url, name="source_final_url", maximum=2_000)
        if validate_official_source_url(self.source_url) or validate_official_source_url(
            self.final_url
        ):
            raise IntelligenceContractError("source_url_invalid")
        _timestamp(self.observed_at, name="source_observed_at")
        _text(self.content_type, name="source_content_type", maximum=160)
        if (
            not isinstance(self.byte_count, int)
            or isinstance(self.byte_count, bool)
            or self.byte_count < 1
        ):
            raise IntelligenceContractError("source_byte_count_invalid")
        if not is_sha256(self.source_hash):
            raise IntelligenceContractError("source_hash_invalid")
        if self.body_hash != self.source_hash:
            raise IntelligenceContractError("source_body_hash_invalid")
        _text(self.text_excerpt, name="source_excerpt", maximum=12_000)
        for name, value in (
            ("published_at", self.published_at),
            ("modified_at", self.modified_at),
        ):
            if value is not None:
                _timestamp(value, name=f"source_{name}")
        _text(self.parser_version, name="source_parser_version", maximum=80)
        _text(self.extractor, name="source_extractor", maximum=80)
        if self.content_quality not in {"substantive", "limited", "metadata_only"}:
            raise IntelligenceContractError("source_content_quality_invalid")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "title": self.title,
            "source_url": self.source_url,
            "final_url": self.final_url,
            "observed_at": self.observed_at,
            "content_type": self.content_type,
            "byte_count": self.byte_count,
            "source_hash": self.source_hash,
            "body_hash": self.body_hash,
            "text_excerpt": self.text_excerpt,
            "published_at": self.published_at,
            "modified_at": self.modified_at,
            "parser_version": self.parser_version,
            "content_quality": self.content_quality,
            "extractor": self.extractor,
        }


@dataclass(frozen=True)
class MarketPulse:
    observed_at: str
    venue: str
    symbols: tuple[Mapping[str, Any], ...]
    source_hashes: Mapping[str, str]
    pulse_hash: str

    @classmethod
    def create(
        cls,
        *,
        observed_at: str,
        venue: str,
        symbols: Sequence[Mapping[str, Any]],
        source_hashes: Mapping[str, str],
    ) -> "MarketPulse":
        normalized_symbols = tuple(dict(row) for row in symbols)
        core = {
            "observed_at": _timestamp(observed_at, name="market_observed_at"),
            "venue": venue,
            "symbols": list(normalized_symbols),
            "source_hashes": dict(sorted(source_hashes.items())),
        }
        pulse = cls(
            observed_at=core["observed_at"],
            venue=venue,
            symbols=normalized_symbols,
            source_hashes=core["source_hashes"],
            pulse_hash=canonical_hash(core),
        )
        pulse.validate()
        return pulse

    def validate(self) -> None:
        _timestamp(self.observed_at, name="market_observed_at")
        _text(self.venue, name="market_venue", maximum=64)
        if not self.symbols or len(self.symbols) > 20:
            raise IntelligenceContractError("market_symbols_invalid")
        expected_fields = {
            "symbol",
            "last_price",
            "change_24h_pct",
            "quote_volume_24h",
            "funding_rate",
            "next_funding_time",
        }
        seen: set[str] = set()
        for row in self.symbols:
            if set(row) != expected_fields:
                raise IntelligenceContractError("market_symbol_fields_invalid")
            symbol = _text(row["symbol"], name="market_symbol", maximum=32)
            if symbol in seen:
                raise IntelligenceContractError("market_symbol_duplicate")
            seen.add(symbol)
            for name in (
                "last_price",
                "change_24h_pct",
                "quote_volume_24h",
                "funding_rate",
            ):
                _number(row[name], name=f"market_{name}")
            _timestamp(str(row["next_funding_time"]), name="market_next_funding_time")
        if not self.source_hashes or any(
            not isinstance(name, str) or not name or not is_sha256(value)
            for name, value in self.source_hashes.items()
        ):
            raise IntelligenceContractError("market_source_hashes_invalid")
        if set(self.source_hashes) != {"ticker_24h", "premium_index"}:
            raise IntelligenceContractError("market_source_names_invalid")
        core = self.as_dict()
        core.pop("pulse_hash")
        if self.pulse_hash != canonical_hash(core):
            raise IntelligenceContractError("market_pulse_hash_invalid")

    def as_dict(self) -> dict[str, Any]:
        return {
            "observed_at": self.observed_at,
            "venue": self.venue,
            "symbols": [dict(row) for row in self.symbols],
            "source_hashes": dict(self.source_hashes),
            "pulse_hash": self.pulse_hash,
        }


@dataclass(frozen=True)
class ResearchProposal:
    proposal_id: str
    hypothesis: str
    baseline_contract: str
    kill_test_contract: str
    cost_contract: tuple[str, ...]
    holdout_role: str
    source_capacity: str
    history_capacity: str
    g0_status: str
    orders_allowed: bool
    live_changes_allowed: bool
    proposal_hash: str

    @classmethod
    def create(
        cls,
        hypothesis: str,
        *,
        source_capacity: str,
        history_capacity: str,
    ) -> "ResearchProposal":
        if source_capacity not in {"sufficient", "limited", "blocked"}:
            raise IntelligenceContractError("proposal_source_capacity_invalid")
        if history_capacity not in {"sufficient", "limited", "blocked"}:
            raise IntelligenceContractError("proposal_history_capacity_invalid")
        if source_capacity == "blocked" and history_capacity == "blocked":
            g0_status = "blocked_source_and_history_capacity"
        elif source_capacity == "blocked":
            g0_status = "blocked_source_capacity"
        elif history_capacity != "sufficient":
            g0_status = "blocked_history_capacity"
        else:
            g0_status = "eligible_for_research_design"
        core = {
            "hypothesis": _text(
                hypothesis, name="proposal_hypothesis", maximum=1_000
            ),
            "baseline_contract": "simple_market_and_no_news_baselines_required",
            "kill_test_contract": "permutation_time_shift_random_label_and_event_window_deletion",
            "cost_contract": [
                "fees",
                "spread",
                "slippage",
                "funding",
                "liquidity_discount",
            ],
            "holdout_role": "discovery_design_only_until_frozen_holdout",
            "source_capacity": source_capacity,
            "history_capacity": history_capacity,
            "g0_status": g0_status,
            "orders_allowed": False,
            "live_changes_allowed": False,
        }
        proposal_hash = canonical_hash(core)
        proposal = cls(
            proposal_id=trace_id(
                "research_proposal", {"proposal_hash": proposal_hash}
            ),
            hypothesis=core["hypothesis"],
            baseline_contract=core["baseline_contract"],
            kill_test_contract=core["kill_test_contract"],
            cost_contract=tuple(core["cost_contract"]),
            holdout_role=core["holdout_role"],
            source_capacity=core["source_capacity"],
            history_capacity=core["history_capacity"],
            g0_status=core["g0_status"],
            orders_allowed=False,
            live_changes_allowed=False,
            proposal_hash=proposal_hash,
        )
        proposal.validate()
        return proposal

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ResearchProposal":
        expected = set(cls.__dataclass_fields__)
        if not isinstance(value, Mapping) or set(value) != expected:
            raise IntelligenceContractError("proposal_fields_invalid")
        proposal = cls(
            proposal_id=value["proposal_id"],
            hypothesis=value["hypothesis"],
            baseline_contract=value["baseline_contract"],
            kill_test_contract=value["kill_test_contract"],
            cost_contract=tuple(value["cost_contract"]),
            holdout_role=value["holdout_role"],
            source_capacity=value["source_capacity"],
            history_capacity=value["history_capacity"],
            g0_status=value["g0_status"],
            orders_allowed=value["orders_allowed"],
            live_changes_allowed=value["live_changes_allowed"],
            proposal_hash=value["proposal_hash"],
        )
        proposal.validate()
        return proposal

    def validate(self) -> None:
        _text(self.hypothesis, name="proposal_hypothesis", maximum=1_000)
        _text(self.baseline_contract, name="proposal_baseline", maximum=200)
        _text(self.kill_test_contract, name="proposal_kill_test", maximum=200)
        _text(self.holdout_role, name="proposal_holdout", maximum=160)
        if (
            self.source_capacity not in {"sufficient", "limited", "blocked"}
            or self.history_capacity not in {"sufficient", "limited", "blocked"}
            or self.g0_status
            not in {
                "blocked_source_and_history_capacity",
                "blocked_source_capacity",
                "blocked_history_capacity",
                "eligible_for_research_design",
            }
            or not self.cost_contract
            or any(
                not isinstance(item, str) or not item for item in self.cost_contract
            )
            or self.orders_allowed
            or self.live_changes_allowed
        ):
            raise IntelligenceContractError("proposal_contract_invalid")
        core = self.as_dict()
        proposal_id = core.pop("proposal_id")
        proposal_hash = core.pop("proposal_hash")
        if proposal_hash != canonical_hash(core) or proposal_id != trace_id(
            "research_proposal", {"proposal_hash": proposal_hash}
        ):
            raise IntelligenceContractError("proposal_hash_invalid")

    def as_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "hypothesis": self.hypothesis,
            "baseline_contract": self.baseline_contract,
            "kill_test_contract": self.kill_test_contract,
            "cost_contract": list(self.cost_contract),
            "holdout_role": self.holdout_role,
            "source_capacity": self.source_capacity,
            "history_capacity": self.history_capacity,
            "g0_status": self.g0_status,
            "orders_allowed": self.orders_allowed,
            "live_changes_allowed": self.live_changes_allowed,
            "proposal_hash": self.proposal_hash,
        }


def _research_capacities(
    sources: Sequence[SourceEvidence],
    trading_history: Mapping[str, Any],
    *,
    current_history_authoritative: bool = True,
) -> tuple[str, str]:
    substantive = [source for source in sources if source.content_quality == "substantive"]
    domains = {
        (urllib.parse.urlparse(source.final_url).hostname or "").lower()
        for source in substantive
    }
    if len(substantive) >= 2 and len(domains) >= 2:
        source_capacity = "sufficient"
    elif any(source.content_quality != "metadata_only" for source in sources):
        source_capacity = "limited"
    else:
        source_capacity = "blocked"
    execution_status = trading_history.get("execution_evidence_status")
    if (
        not current_history_authoritative
        or trading_history.get("status") != "available"
        or execution_status == "orders_expected_but_missing"
    ):
        history_capacity = "blocked"
    else:
        # A current ledger snapshot can prove an order-free or filled cycle, but it
        # is not a historical event window or an independent strategy holdout.
        history_capacity = "limited"
    return source_capacity, history_capacity


_RUNTIME_HISTORY_AUTHORITY_FIELDS = {
    "status",
    "current_history_authoritative",
    "current_ledger_reconciliation",
    "ledger_source_updated_at",
    "account_observed_at",
    "evaluated_at",
    "stale_after_seconds",
}
_RUNTIME_HISTORY_CURRENT_STATUSES = {
    "ledger_current",
    "ledger_current_after_blocked_observation",
}
_RUNTIME_HISTORY_STATUSES = _RUNTIME_HISTORY_CURRENT_STATUSES | {
    "ledger_unavailable",
    "ledger_stale",
    "ledger_future_dated",
    "ledger_freshness_unverified",
    "ledger_unavailable_with_blocked_observation",
    "ledger_superseded_by_blocked_observation",
    "ledger_stale_after_blocked_observation",
    "ledger_future_dated_after_blocked_observation",
    "ledger_freshness_unverified_after_blocked_observation",
}


def _runtime_history_authority(
    value: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Validate the persisted current-fact boundary for new v2 reports.

    Older v2 reports predate this field and remain readable, but callers must
    treat their execution evidence as non-current until a new report exists.
    """

    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != _RUNTIME_HISTORY_AUTHORITY_FIELDS:
        raise IntelligenceContractError("intelligence_runtime_history_authority_invalid")
    status = value["status"]
    current = value["current_history_authoritative"]
    reconciliation = value["current_ledger_reconciliation"]
    if (
        status not in _RUNTIME_HISTORY_STATUSES
        or not isinstance(current, bool)
        or reconciliation not in {"available", "unavailable"}
        or current is not (status in _RUNTIME_HISTORY_CURRENT_STATUSES)
        or (reconciliation == "available") is not current
        or not isinstance(value["stale_after_seconds"], int)
        or isinstance(value["stale_after_seconds"], bool)
        or not 1 <= value["stale_after_seconds"] <= 86_400
    ):
        raise IntelligenceContractError("intelligence_runtime_history_authority_invalid")
    for name in ("ledger_source_updated_at", "account_observed_at"):
        if value[name] is not None:
            _timestamp(value[name], name=f"intelligence_runtime_history_{name}")
    _timestamp(value["evaluated_at"], name="intelligence_runtime_history_evaluated_at")
    return dict(value)


@dataclass(frozen=True)
class DailyIntelligenceReport:
    schema_version: int
    report_id: str
    report_date: str
    created_at: str
    status: str
    pipeline_status: str
    evidence_status: str
    evidence_summary: Mapping[str, Any]
    market_pulse: Mapping[str, Any]
    trading_history: Mapping[str, Any]
    searches: tuple[Mapping[str, Any], ...]
    sources: tuple[Mapping[str, Any], ...]
    agent_reports: tuple[Mapping[str, Any], ...]
    executive_summary: str
    observed_impacts: tuple[str, ...]
    research_proposals: tuple[Mapping[str, Any], ...]
    risk_notes: tuple[str, ...]
    source_hashes: Mapping[str, str]
    llm: Mapping[str, Any]
    orders_allowed: bool
    live_changes_allowed: bool
    report_hash: str
    runtime_history_authority: Mapping[str, Any] | None = None

    @classmethod
    def create(
        cls,
        *,
        report_date: str,
        created_at: str,
        status: str,
        pipeline_status: str,
        evidence_status: str,
        evidence_summary: Mapping[str, Any],
        market_pulse: MarketPulse,
        trading_history: Mapping[str, Any],
        searches: Sequence[SearchEvidence],
        sources: Sequence[SourceEvidence],
        agent_reports: Sequence[AgentReport],
        executive_summary: str,
        observed_impacts: Sequence[str],
        research_proposals: Sequence[str],
        risk_notes: Sequence[str],
        source_hashes: Mapping[str, str],
        llm: Mapping[str, Any],
        current_history_authoritative: bool = True,
        runtime_history_authority: Mapping[str, Any] | None = None,
    ) -> "DailyIntelligenceReport":
        if not isinstance(current_history_authoritative, bool):
            raise IntelligenceContractError(
                "intelligence_current_history_authority_invalid"
            )
        normalized_runtime_history_authority = _runtime_history_authority(
            runtime_history_authority
        )
        if (
            normalized_runtime_history_authority is not None
            and normalized_runtime_history_authority["current_history_authoritative"]
            is not current_history_authoritative
        ):
            raise IntelligenceContractError(
                "intelligence_current_history_authority_mismatch"
            )
        source_capacity, history_capacity = _research_capacities(
            sources,
            trading_history,
            current_history_authoritative=current_history_authoritative,
        )
        structured_proposals = [
            ResearchProposal.create(
                proposal,
                source_capacity=source_capacity,
                history_capacity=history_capacity,
            ).as_dict()
            for proposal in research_proposals
        ]
        core = {
            "schema_version": DAILY_INTELLIGENCE_SCHEMA_VERSION,
            "report_date": report_date,
            "created_at": _timestamp(created_at, name="intelligence_created_at"),
            "status": status,
            "pipeline_status": pipeline_status,
            "evidence_status": evidence_status,
            "evidence_summary": dict(evidence_summary),
            "market_pulse": market_pulse.as_dict(),
            "trading_history": dict(trading_history),
            "searches": [row.as_dict() for row in searches],
            "sources": [row.as_dict() for row in sources],
            "agent_reports": [_json_native(row.to_dict()) for row in agent_reports],
            "executive_summary": executive_summary,
            "observed_impacts": list(observed_impacts),
            "research_proposals": structured_proposals,
            "risk_notes": list(risk_notes),
            "source_hashes": dict(sorted(source_hashes.items())),
            "llm": dict(llm),
            "orders_allowed": False,
            "live_changes_allowed": False,
        }
        if normalized_runtime_history_authority is not None:
            core["runtime_history_authority"] = normalized_runtime_history_authority
        report_hash = canonical_hash(core)
        report = cls(
            schema_version=core["schema_version"],
            report_date=core["report_date"],
            created_at=core["created_at"],
            status=core["status"],
            pipeline_status=core["pipeline_status"],
            evidence_status=core["evidence_status"],
            evidence_summary=dict(core["evidence_summary"]),
            market_pulse=dict(core["market_pulse"]),
            trading_history=dict(core["trading_history"]),
            searches=tuple(dict(row) for row in core["searches"]),
            sources=tuple(dict(row) for row in core["sources"]),
            agent_reports=tuple(dict(row) for row in core["agent_reports"]),
            executive_summary=core["executive_summary"],
            observed_impacts=tuple(core["observed_impacts"]),
            research_proposals=tuple(dict(row) for row in core["research_proposals"]),
            risk_notes=tuple(core["risk_notes"]),
            source_hashes=dict(core["source_hashes"]),
            llm=dict(core["llm"]),
            orders_allowed=False,
            live_changes_allowed=False,
            report_id=trace_id("daily_intelligence", {"report_hash": report_hash}),
            report_hash=report_hash,
            runtime_history_authority=normalized_runtime_history_authority,
        )
        report.validate()
        return report

    def validate(self) -> None:
        if self.schema_version != DAILY_INTELLIGENCE_SCHEMA_VERSION:
            raise IntelligenceContractError("intelligence_schema_invalid")
        try:
            report_date = dt.date.fromisoformat(self.report_date)
        except (TypeError, ValueError) as exc:
            raise IntelligenceContractError("intelligence_report_date_invalid") from exc
        _timestamp(self.created_at, name="intelligence_created_at")
        if report_date != aware_datetime(self.created_at).astimezone(
            dt.timezone.utc
        ).date():
            raise IntelligenceContractError("intelligence_report_date_mismatch")
        if self.status not in DAILY_INTELLIGENCE_STATUSES:
            raise IntelligenceContractError("intelligence_status_invalid")
        if self.pipeline_status not in DAILY_INTELLIGENCE_PIPELINE_STATUSES:
            raise IntelligenceContractError("intelligence_pipeline_status_invalid")
        if self.evidence_status not in DAILY_INTELLIGENCE_EVIDENCE_STATUSES:
            raise IntelligenceContractError("intelligence_evidence_status_invalid")
        _runtime_history_authority(self.runtime_history_authority)
        evidence_summary = self.evidence_summary
        expected_evidence_fields = {
            "status",
            "verified_source_count",
            "substantive_source_count",
            "source_domain_count",
            "trading_history_status",
            "execution_evidence_status",
            "gaps",
        }
        if (
            not isinstance(evidence_summary, Mapping)
            or set(evidence_summary) != expected_evidence_fields
            or evidence_summary["status"] != self.evidence_status
            or any(
                not isinstance(evidence_summary[name], int)
                or isinstance(evidence_summary[name], bool)
                or evidence_summary[name] < 0
                for name in (
                    "verified_source_count",
                    "substantive_source_count",
                    "source_domain_count",
                )
            )
            or evidence_summary["trading_history_status"]
            not in {"available", "unavailable"}
            or evidence_summary["execution_evidence_status"]
            not in {
                None,
                "no_order_expected",
                "orders_expected_but_missing",
                "fills_verified",
            }
            or not isinstance(evidence_summary["gaps"], list)
            or any(
                not isinstance(gap, str) or not gap
                for gap in evidence_summary["gaps"]
            )
        ):
            raise IntelligenceContractError("intelligence_evidence_summary_invalid")
        _text(self.executive_summary, name="intelligence_summary", maximum=2_000)
        for name, values in (("impacts", self.observed_impacts), ("risks", self.risk_notes)):
            if len(values) > 12:
                raise IntelligenceContractError(f"intelligence_{name}_invalid")
            for item in values:
                _text(item, name=f"intelligence_{name}_item", maximum=1_000)
        if len(self.research_proposals) > 12:
            raise IntelligenceContractError("intelligence_proposals_invalid")
        for proposal in self.research_proposals:
            ResearchProposal.from_dict(proposal)
        if self.orders_allowed or self.live_changes_allowed:
            raise IntelligenceContractError("intelligence_authority_invalid")
        if not self.source_hashes or any(
            not isinstance(name, str) or not name or not is_sha256(value)
            for name, value in self.source_hashes.items()
        ):
            raise IntelligenceContractError("intelligence_source_hashes_invalid")
        if set(self.llm) != {"enabled", "model", "provider_profile"}:
            raise IntelligenceContractError("intelligence_llm_fields_invalid")
        if not isinstance(self.llm["enabled"], bool):
            raise IntelligenceContractError("intelligence_llm_enabled_invalid")
        _text(self.llm["model"], name="intelligence_llm_model", maximum=160)
        _text(
            self.llm["provider_profile"],
            name="intelligence_llm_provider",
            maximum=160,
        )
        if len(self.agent_reports) != len(DAILY_INTELLIGENCE_ROLES):
            raise IntelligenceContractError("intelligence_agent_count_invalid")
        if tuple(row.get("role_id") for row in self.agent_reports) != DAILY_INTELLIGENCE_ROLES:
            raise IntelligenceContractError("intelligence_agent_roles_invalid")
        try:
            if set(self.market_pulse) != {
                "observed_at",
                "venue",
                "symbols",
                "source_hashes",
                "pulse_hash",
            }:
                raise IntelligenceContractError("intelligence_market_fields_invalid")
            pulse = MarketPulse(
                observed_at=self.market_pulse["observed_at"],
                venue=self.market_pulse["venue"],
                symbols=tuple(dict(row) for row in self.market_pulse["symbols"]),
                source_hashes=dict(self.market_pulse["source_hashes"]),
                pulse_hash=self.market_pulse["pulse_hash"],
            )
            pulse.validate()
            searches = tuple(
                SearchEvidence(
                    query=row["query"],
                    provider=row["provider"],
                    searched_at=row["searched_at"],
                    result_count=row["result_count"],
                    response_hash=row["response_hash"],
                    urls=tuple(row["urls"]),
                )
                for row in self.searches
                if set(row)
                == {
                    "query",
                    "provider",
                    "searched_at",
                    "result_count",
                    "response_hash",
                    "urls",
                }
            )
            if len(searches) != len(self.searches):
                raise IntelligenceContractError("intelligence_search_fields_invalid")
            for search in searches:
                search.validate()
            sources = tuple(
                SourceEvidence(
                    title=row["title"],
                    source_url=row["source_url"],
                    final_url=row["final_url"],
                    observed_at=row["observed_at"],
                    content_type=row["content_type"],
                    byte_count=row["byte_count"],
                    source_hash=row["source_hash"],
                    body_hash=row["body_hash"],
                    text_excerpt=row["text_excerpt"],
                    published_at=row["published_at"],
                    modified_at=row["modified_at"],
                    parser_version=row["parser_version"],
                    content_quality=row["content_quality"],
                    extractor=row["extractor"],
                )
                for row in self.sources
                if set(row)
                == {
                    "title",
                    "source_url",
                    "final_url",
                    "observed_at",
                    "content_type",
                    "byte_count",
                    "source_hash",
                    "body_hash",
                    "text_excerpt",
                    "published_at",
                    "modified_at",
                    "parser_version",
                    "content_quality",
                    "extractor",
                }
            )
            if len(sources) != len(self.sources):
                raise IntelligenceContractError("intelligence_source_fields_invalid")
            for source in sources:
                source.validate()
            for row in self.agent_reports:
                if set(row) != {
                    "role_id",
                    "task_id",
                    "status",
                    "summary",
                    "findings",
                    "proposals",
                    "risks",
                    "sources",
                    "raw_response",
                }:
                    raise IntelligenceContractError(
                        "intelligence_agent_report_fields_invalid"
                    )
                if any(
                    set(source) != {"title", "url", "source_type", "notes"}
                    for source in row["sources"]
                ):
                    raise IntelligenceContractError(
                        "intelligence_agent_source_fields_invalid"
                    )
                report = AgentReport(
                    role_id=row["role_id"],
                    task_id=row["task_id"],
                    status=row["status"],
                    summary=row["summary"],
                    findings=tuple(row["findings"]),
                    proposals=tuple(row["proposals"]),
                    risks=tuple(row["risks"]),
                    sources=tuple(
                        SourceRef(
                            title=source["title"],
                            url=source["url"],
                            source_type=source["source_type"],
                            notes=source["notes"],
                        )
                        for source in row["sources"]
                    ),
                    raw_response=row["raw_response"],
                )
                errors = validate_agent_report(report)
                if errors:
                    raise IntelligenceContractError(
                        f"intelligence_agent_report_invalid:{','.join(errors)}"
                    )
            from .history import validate_trading_history

            validate_trading_history(self.trading_history)
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, IntelligenceContractError):
                raise
            raise IntelligenceContractError(
                "intelligence_nested_contract_invalid"
            ) from exc
        source_domains = {
            (urllib.parse.urlparse(source.final_url).hostname or "").lower()
            for source in sources
        }
        expected_evidence_counts = {
            "verified_source_count": len(sources),
            "substantive_source_count": sum(
                source.content_quality == "substantive" for source in sources
            ),
            "source_domain_count": len(source_domains),
            "trading_history_status": self.trading_history["status"],
            "execution_evidence_status": self.trading_history[
                "execution_evidence_status"
            ],
        }
        if any(
            self.evidence_summary[name] != value
            for name, value in expected_evidence_counts.items()
        ):
            raise IntelligenceContractError("intelligence_evidence_summary_mismatch")
        expected_source_hashes = {
            "market_pulse": pulse.pulse_hash,
            "trading_history": self.trading_history["summary_hash"],
            **{
                f"search_{index:02d}": search.response_hash
                for index, search in enumerate(searches)
            },
            **{
                f"source_{index:02d}": source.source_hash
                for index, source in enumerate(sources)
            },
        }
        if dict(self.source_hashes) != expected_source_hashes:
            raise IntelligenceContractError("intelligence_source_hashes_mismatch")
        core = self.as_dict()
        core.pop("report_id")
        core.pop("report_hash")
        if self.report_hash != canonical_hash(core):
            raise IntelligenceContractError("intelligence_report_hash_invalid")
        if self.report_id != trace_id(
            "daily_intelligence", {"report_hash": self.report_hash}
        ):
            raise IntelligenceContractError("intelligence_report_id_invalid")

    def as_dict(self) -> dict[str, Any]:
        value = {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "report_date": self.report_date,
            "created_at": self.created_at,
            "status": self.status,
            "pipeline_status": self.pipeline_status,
            "evidence_status": self.evidence_status,
            "evidence_summary": dict(self.evidence_summary),
            "market_pulse": dict(self.market_pulse),
            "trading_history": dict(self.trading_history),
            "searches": [dict(row) for row in self.searches],
            "sources": [dict(row) for row in self.sources],
            "agent_reports": [dict(row) for row in self.agent_reports],
            "executive_summary": self.executive_summary,
            "observed_impacts": list(self.observed_impacts),
            "research_proposals": [dict(row) for row in self.research_proposals],
            "risk_notes": list(self.risk_notes),
            "source_hashes": dict(self.source_hashes),
            "llm": dict(self.llm),
            "orders_allowed": self.orders_allowed,
            "live_changes_allowed": self.live_changes_allowed,
            "report_hash": self.report_hash,
        }
        if self.runtime_history_authority is not None:
            value["runtime_history_authority"] = dict(self.runtime_history_authority)
        return value


def daily_intelligence_from_dict(value: Mapping[str, Any]) -> DailyIntelligenceReport:
    if not isinstance(value, Mapping):
        raise IntelligenceContractError("intelligence_report_not_object")
    expected = {
        "schema_version",
        "report_id",
        "report_date",
        "created_at",
        "status",
        "pipeline_status",
        "evidence_status",
        "evidence_summary",
        "market_pulse",
        "trading_history",
        "searches",
        "sources",
        "agent_reports",
        "executive_summary",
        "observed_impacts",
        "research_proposals",
        "risk_notes",
        "source_hashes",
        "llm",
        "orders_allowed",
        "live_changes_allowed",
        "report_hash",
    }
    optional = {"runtime_history_authority"}
    actual = set(value)
    if actual != expected and actual != expected | optional:
        raise IntelligenceContractError("intelligence_report_fields_invalid")
    report = DailyIntelligenceReport(
        schema_version=value["schema_version"],
        report_id=value["report_id"],
        report_date=value["report_date"],
        created_at=value["created_at"],
        status=value["status"],
        pipeline_status=value["pipeline_status"],
        evidence_status=value["evidence_status"],
        evidence_summary=dict(value["evidence_summary"]),
        market_pulse=dict(value["market_pulse"]),
        trading_history=dict(value["trading_history"]),
        searches=tuple(dict(row) for row in value["searches"]),
        sources=tuple(dict(row) for row in value["sources"]),
        agent_reports=tuple(dict(row) for row in value["agent_reports"]),
        executive_summary=value["executive_summary"],
        observed_impacts=tuple(value["observed_impacts"]),
        research_proposals=tuple(dict(row) for row in value["research_proposals"]),
        risk_notes=tuple(value["risk_notes"]),
        source_hashes=dict(value["source_hashes"]),
        llm=dict(value["llm"]),
        orders_allowed=value["orders_allowed"],
        live_changes_allowed=value["live_changes_allowed"],
        report_hash=value["report_hash"],
        runtime_history_authority=(
            dict(value["runtime_history_authority"])
            if "runtime_history_authority" in value
            else None
        ),
    )
    report.validate()
    return report
