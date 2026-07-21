"""Immutable contracts for the read-only daily intelligence plane."""

from __future__ import annotations

import datetime as dt
import math
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


DAILY_INTELLIGENCE_SCHEMA_VERSION = 1
DAILY_INTELLIGENCE_STATUSES = ("clear", "attention_required", "incomplete")
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
    text_excerpt: str

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
        _text(self.text_excerpt, name="source_excerpt", maximum=12_000)

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
            "text_excerpt": self.text_excerpt,
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
class DailyIntelligenceReport:
    schema_version: int
    report_id: str
    report_date: str
    created_at: str
    status: str
    market_pulse: Mapping[str, Any]
    trading_history: Mapping[str, Any]
    searches: tuple[Mapping[str, Any], ...]
    sources: tuple[Mapping[str, Any], ...]
    agent_reports: tuple[Mapping[str, Any], ...]
    executive_summary: str
    observed_impacts: tuple[str, ...]
    research_proposals: tuple[str, ...]
    risk_notes: tuple[str, ...]
    source_hashes: Mapping[str, str]
    llm: Mapping[str, Any]
    orders_allowed: bool
    live_changes_allowed: bool
    report_hash: str

    @classmethod
    def create(
        cls,
        *,
        report_date: str,
        created_at: str,
        status: str,
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
    ) -> "DailyIntelligenceReport":
        core = {
            "schema_version": DAILY_INTELLIGENCE_SCHEMA_VERSION,
            "report_date": report_date,
            "created_at": _timestamp(created_at, name="intelligence_created_at"),
            "status": status,
            "market_pulse": market_pulse.as_dict(),
            "trading_history": dict(trading_history),
            "searches": [row.as_dict() for row in searches],
            "sources": [row.as_dict() for row in sources],
            "agent_reports": [_json_native(row.to_dict()) for row in agent_reports],
            "executive_summary": executive_summary,
            "observed_impacts": list(observed_impacts),
            "research_proposals": list(research_proposals),
            "risk_notes": list(risk_notes),
            "source_hashes": dict(sorted(source_hashes.items())),
            "llm": dict(llm),
            "orders_allowed": False,
            "live_changes_allowed": False,
        }
        report_hash = canonical_hash(core)
        report = cls(
            schema_version=core["schema_version"],
            report_date=core["report_date"],
            created_at=core["created_at"],
            status=core["status"],
            market_pulse=dict(core["market_pulse"]),
            trading_history=dict(core["trading_history"]),
            searches=tuple(dict(row) for row in core["searches"]),
            sources=tuple(dict(row) for row in core["sources"]),
            agent_reports=tuple(dict(row) for row in core["agent_reports"]),
            executive_summary=core["executive_summary"],
            observed_impacts=tuple(core["observed_impacts"]),
            research_proposals=tuple(core["research_proposals"]),
            risk_notes=tuple(core["risk_notes"]),
            source_hashes=dict(core["source_hashes"]),
            llm=dict(core["llm"]),
            orders_allowed=False,
            live_changes_allowed=False,
            report_id=trace_id("daily_intelligence", {"report_hash": report_hash}),
            report_hash=report_hash,
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
        _text(self.executive_summary, name="intelligence_summary", maximum=2_000)
        for name, values in (
            ("impacts", self.observed_impacts),
            ("proposals", self.research_proposals),
            ("risks", self.risk_notes),
        ):
            if len(values) > 12:
                raise IntelligenceContractError(f"intelligence_{name}_invalid")
            for item in values:
                _text(item, name=f"intelligence_{name}_item", maximum=1_000)
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
                    text_excerpt=row["text_excerpt"],
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
                    "text_excerpt",
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
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "report_date": self.report_date,
            "created_at": self.created_at,
            "status": self.status,
            "market_pulse": dict(self.market_pulse),
            "trading_history": dict(self.trading_history),
            "searches": [dict(row) for row in self.searches],
            "sources": [dict(row) for row in self.sources],
            "agent_reports": [dict(row) for row in self.agent_reports],
            "executive_summary": self.executive_summary,
            "observed_impacts": list(self.observed_impacts),
            "research_proposals": list(self.research_proposals),
            "risk_notes": list(self.risk_notes),
            "source_hashes": dict(self.source_hashes),
            "llm": dict(self.llm),
            "orders_allowed": self.orders_allowed,
            "live_changes_allowed": self.live_changes_allowed,
            "report_hash": self.report_hash,
        }


def daily_intelligence_from_dict(value: Mapping[str, Any]) -> DailyIntelligenceReport:
    if not isinstance(value, Mapping):
        raise IntelligenceContractError("intelligence_report_not_object")
    expected = {
        "schema_version",
        "report_id",
        "report_date",
        "created_at",
        "status",
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
    if set(value) != expected:
        raise IntelligenceContractError("intelligence_report_fields_invalid")
    report = DailyIntelligenceReport(
        schema_version=value["schema_version"],
        report_id=value["report_id"],
        report_date=value["report_date"],
        created_at=value["created_at"],
        status=value["status"],
        market_pulse=dict(value["market_pulse"]),
        trading_history=dict(value["trading_history"]),
        searches=tuple(dict(row) for row in value["searches"]),
        sources=tuple(dict(row) for row in value["sources"]),
        agent_reports=tuple(dict(row) for row in value["agent_reports"]),
        executive_summary=value["executive_summary"],
        observed_impacts=tuple(value["observed_impacts"]),
        research_proposals=tuple(value["research_proposals"]),
        risk_notes=tuple(value["risk_notes"]),
        source_hashes=dict(value["source_hashes"]),
        llm=dict(value["llm"]),
        orders_allowed=value["orders_allowed"],
        live_changes_allowed=value["live_changes_allowed"],
        report_hash=value["report_hash"],
    )
    report.validate()
    return report
