"""Daily market, execution and strategy-review multi-agent workflow."""

from __future__ import annotations

import datetime as dt
import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from qount.alpha_agents.llm import AlphaLLMConfig
from qount.alpha_agents.llm import request_agent_report
from qount.alpha_agents.models import AgentReport
from qount.alpha_agents.models import AgentRole
from qount.alpha_agents.models import ResearchTask
from qount.alpha_agents.models import SourceRef
from qount.alpha_agents.official_sources import OfficialSourceDocument
from qount.alpha_agents.official_sources import fetch_official_source_document
from qount.alpha_agents.official_sources import validate_official_source_url
from qount.contracts import canonical_hash

from .archive import IntelligenceArchiveRecord
from .archive import archive_daily_intelligence
from .contracts import DAILY_INTELLIGENCE_ROLES
from .contracts import DailyIntelligenceReport
from .contracts import MarketPulse
from .contracts import SearchEvidence
from .contracts import SourceEvidence
from .history import RUNTIME_LEDGER_CURRENT_MAX_AGE_SECONDS
from .history import summarize_runtime_fact_boundary
from .history import summarize_trading_history
from .search import SearchProvider


DEFAULT_DAILY_SEARCH_QUERIES = (
    "site:binance.com latest crypto market announcement BTC ETH BNB",
    "site:federalreserve.gov latest monetary policy financial conditions",
    "site:sec.gov latest crypto digital asset enforcement filing",
)

DAILY_LLM_SOURCE_EXCERPT_CHARS = 1_800
DAILY_LLM_COMPACT_SOURCE_EXCERPT_CHARS = 600
DAILY_LLM_PRIOR_SUMMARY_CHARS = 700
DAILY_LLM_PRIOR_ITEM_CHARS = 240


DAILY_ROLES = tuple(
    AgentRole(
        role_id=role_id,
        name=name,
        kind="llm_review",
        mission=mission,
        allowed_outputs=("report", "critique", "research_proposal"),
        forbidden_outputs=("order", "target_weight", "live_config_change", "risk_override"),
        required_checks=checks,
        llm_allowed=True,
    )
    for role_id, name, mission, checks in (
        (
            "market_analyst",
            "市场分析员",
            "用简体中文解释给定的当前行情，不得虚构上下文未提供的市场事实。",
            ("timestamp", "price_change", "funding", "source_hash"),
        ),
        (
            "event_analyst",
            "事件分析员",
            "用简体中文分析带时点的一手来源，并严格区分已观测事实与假设。",
            ("published_or_observed_time", "primary_source", "causal_uncertainty"),
        ),
        (
            "execution_reviewer",
            "执行复核员",
            "用简体中文复核给定账本中的交易历史、成交证据、费用、资金费和对账。",
            ("ledger_only", "fills_not_plans", "reconciliation"),
        ),
        (
            "strategy_reviewer",
            "策略复核员",
            "用简体中文把证据转化为可证伪研究建议，不得直接提出实盘参数修改。",
            ("baseline", "kill_test", "costs", "holdout_role"),
        ),
        (
            "red_team",
            "红队审查员",
            "用简体中文质疑市场和策略解释中的后见偏差、Beta、成本与来源缺口。",
            ("counterexample", "missing_evidence", "simpler_baseline"),
        ),
        (
            "editor",
            "总编",
            "用简体中文把给定报告整理为简洁的所有者简报，并明确写出不确定性。",
            ("source_bound", "separate_fact_and_hypothesis", "no_trading_authority"),
        ),
    )
)


@dataclass(frozen=True)
class DailyIntelligenceRun:
    report: DailyIntelligenceReport
    archive: IntelligenceArchiveRecord


def _date(value: str) -> str:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("intelligence_run_time_must_be_aware")
    return parsed.astimezone(dt.timezone.utc).date().isoformat()


def _source_evidence(document: OfficialSourceDocument, title: str) -> SourceEvidence:
    return SourceEvidence(
        title=(document.title or title or "Official source")[:500],
        source_url=document.source_url,
        final_url=document.final_url,
        observed_at=document.observed_at,
        content_type=document.content_type,
        byte_count=document.byte_count,
        source_hash=document.source_hash,
        body_hash=document.body_hash,
        text_excerpt=document.text_excerpt,
        published_at=document.published_at,
        modified_at=document.modified_at,
        parser_version=document.parser_version,
        content_quality=document.content_quality,
        extractor=document.extractor,
    )


def _source_context(
    source: SourceEvidence,
    *,
    excerpt_chars: int = 0,
) -> dict[str, Any]:
    value = {
        "title": source.title,
        "source_url": source.source_url,
        "final_url": source.final_url,
        "observed_at": source.observed_at,
        "content_type": source.content_type,
        "byte_count": source.byte_count,
        "source_hash": source.source_hash,
        "body_hash": source.body_hash,
        "published_at": source.published_at,
        "modified_at": source.modified_at,
        "parser_version": source.parser_version,
        "content_quality": source.content_quality,
        "extractor": source.extractor,
    }
    if excerpt_chars > 0:
        value["text_excerpt"] = source.text_excerpt[:excerpt_chars]
    return value


def _evidence_summary(
    sources: Sequence[SourceEvidence],
    trading_history: Mapping[str, Any],
    runtime_fact_boundary: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    substantive_count = sum(
        source.content_quality == "substantive" for source in sources
    )
    source_domains = {
        (urllib.parse.urlparse(source.final_url).hostname or "").lower()
        for source in sources
    }
    execution_status = trading_history.get("execution_evidence_status")
    history_sufficient = bool(trading_history.get("execution_evidence_sufficient"))
    gaps: list[str] = []
    if not sources:
        gaps.append("no_verified_relevant_sources")
    elif substantive_count < 2:
        gaps.append("fewer_than_two_substantive_sources")
    if len(source_domains) < 2:
        gaps.append("fewer_than_two_source_domains")
    if trading_history.get("status") != "available":
        gaps.append("runtime_ledger_history_unavailable")
    elif execution_status == "orders_expected_but_missing":
        gaps.append("orders_expected_but_missing")
    current_reconciliation_available = (
        runtime_fact_boundary.get("current_ledger_reconciliation") == "available"
    )
    if not current_reconciliation_available:
        if runtime_fact_boundary.get("blocked_runtime_observation") is not None:
            gaps.append("runtime_ledger_superseded_by_blocked_runtime_observation")
        else:
            gaps.append("runtime_ledger_history_not_current")
        gaps.append("current_ledger_reconciliation_unavailable")
    if (
        substantive_count >= 2
        and len(source_domains) >= 2
        and history_sufficient
        and current_reconciliation_available
    ):
        status = "sufficient"
    elif (
        any(source.content_quality != "metadata_only" for source in sources)
        and trading_history.get("status") == "available"
    ):
        status = "limited"
    else:
        status = "insufficient"
    return status, {
        "status": status,
        "verified_source_count": len(sources),
        "substantive_source_count": substantive_count,
        "source_domain_count": len(source_domains),
        "trading_history_status": trading_history.get("status"),
        "execution_evidence_status": execution_status,
        "gaps": gaps,
    }


def _compact_agent_report(report: AgentReport) -> dict[str, Any]:
    return {
        "role_id": report.role_id,
        "status": report.status,
        "summary": report.summary[:DAILY_LLM_PRIOR_SUMMARY_CHARS],
        "findings": [item[:DAILY_LLM_PRIOR_ITEM_CHARS] for item in report.findings[:3]],
        "proposals": [item[:DAILY_LLM_PRIOR_ITEM_CHARS] for item in report.proposals[:3]],
        "risks": [item[:DAILY_LLM_PRIOR_ITEM_CHARS] for item in report.risks[:3]],
    }


def _role_context(
    *,
    role_id: str,
    created_at: str,
    market_pulse: MarketPulse,
    trading_history: Mapping[str, Any],
    runtime_fact_boundary: Mapping[str, Any],
    sources: Sequence[SourceEvidence],
    source_failures: Sequence[str],
    reports: Sequence[AgentReport],
) -> dict[str, Any]:
    source_catalog = [
        _source_context(source)
        for source in sources
    ]
    context: dict[str, Any] = {
        "as_of": created_at,
        "mode": "research_sandbox_read_only",
        "report_language": "zh-CN",
        "source_catalog": source_catalog,
        "source_failures": list(source_failures),
        "source_quality": {
            "verified_count": len(sources),
            "substantive_count": sum(
                source.content_quality == "substantive" for source in sources
            ),
            "metadata_only_count": sum(
                source.content_quality == "metadata_only" for source in sources
            ),
        },
        "guardrails": [
            "不得输出订单、目标权重、实盘配置修改或风险豁免。",
            "优化想法必须是带基线和否决测试的可证伪研究建议。",
            "只有给定来源原文和账本事实可以表述为已观测事实。",
            "所有面向用户的自然语言报告必须使用简体中文。",
            "历史 ledger reconciliation 只适用于 source_updated_at，不得表述为当前账户对账。",
            "交易所只读账户观察不得用于补造成本、成交、手续费、盈亏、NAV 或订单沿袭。",
        ],
    }
    if role_id in {"market_analyst", "event_analyst", "strategy_reviewer", "red_team", "editor"}:
        context["market_pulse"] = market_pulse.as_dict()
    if role_id in {"execution_reviewer", "strategy_reviewer", "red_team", "editor"}:
        context["trading_history"] = trading_history
        context["runtime_fact_boundary"] = runtime_fact_boundary
    if role_id == "event_analyst":
        context["verified_sources"] = [
            _source_context(source, excerpt_chars=DAILY_LLM_SOURCE_EXCERPT_CHARS)
            for source in sources
        ]
    elif role_id in {"strategy_reviewer", "red_team", "editor"}:
        context["verified_sources"] = [
            _source_context(source, excerpt_chars=DAILY_LLM_COMPACT_SOURCE_EXCERPT_CHARS)
            for source in sources
        ]
    if role_id in {"red_team", "editor"}:
        context["prior_agent_reports"] = [
            _compact_agent_report(report) for report in reports
        ]
    return context


def _run_agent(
    *,
    config: AlphaLLMConfig,
    role: AgentRole,
    context: Mapping[str, Any],
    sources: tuple[SourceRef, ...],
) -> AgentReport:
    task = ResearchTask(
        task_id=f"daily_intelligence_{role.role_id}_v1",
        title=f"每日情报复盘：{role.name}",
        objective=role.mission,
        role_ids=(role.role_id,),
        required_outputs=role.allowed_outputs,
        source_tags=("daily_intelligence",),
        holdout_role="discovery",
        priority=10,
    )
    return request_agent_report(
        config=config,
        role=role,
        task=task,
        sources=sources,
        context=dict(context),
        output_language="zh-CN",
    )


def _circuit_blocked_agent(
    *,
    role: AgentRole,
    sources: tuple[SourceRef, ...],
    failed_role_id: str,
) -> AgentReport:
    return AgentReport(
        role_id=role.role_id,
        task_id=f"daily_intelligence_{role.role_id}_v1",
        status="blocked",
        summary="LLM 上游熔断已开启，本角色未发送网络请求。",
        findings=(f"前序角色 {failed_role_id} 已耗尽有限重试。",),
        proposals=(),
        risks=("llm_batch_circuit_open",),
        sources=sources,
    )


def _runtime_boundary_is_conflicted(value: Mapping[str, Any]) -> bool:
    return value.get("current_ledger_reconciliation") != "available"


def _runtime_history_authority(value: Mapping[str, Any]) -> dict[str, Any]:
    ledger = value["ledger"]
    account = value.get("account_observation")
    return {
        "status": value["status"],
        "current_history_authoritative": not _runtime_boundary_is_conflicted(value),
        "current_ledger_reconciliation": value["current_ledger_reconciliation"],
        "ledger_source_updated_at": ledger["source_updated_at"],
        "account_observed_at": (
            account["observed_at"] if isinstance(account, Mapping) else None
        ),
        "evaluated_at": value["evaluated_at"],
        "stale_after_seconds": value["stale_after_seconds"],
    }


def _market_facts_summary(market_pulse: MarketPulse) -> str:
    rows = ", ".join(
        f"{row['symbol']} {float(row['change_24h_pct']):+.2f}%"
        for row in market_pulse.symbols
    )
    return f"行情观察：{rows}。"


def _runtime_boundary_notice(value: Mapping[str, Any]) -> str | None:
    if not _runtime_boundary_is_conflicted(value):
        return None
    ledger = value["ledger"]
    if ledger["status"] == "available":
        position_count = int(ledger["position_count"])
        reconciliation = (
            "对账通过" if ledger["reconciliation_passed"] else "对账未通过"
        )
        ledger_state = (
            f"空仓且{reconciliation}"
            if position_count == 0
            else f"有 {position_count} 个账本持仓且{reconciliation}"
        )
        ledger_text = (
            f"Qount 权威 ledger 截至 {ledger['source_updated_at']}，"
            f"仅证明该时点{ledger_state}"
        )
    else:
        ledger_text = "当前没有可用的 Qount 权威 ledger"
    blocked = value.get("blocked_runtime_observation")
    if not isinstance(blocked, Mapping):
        return (
            f"运行事实边界：{ledger_text}，但截至 {value['evaluated_at']} "
            "未取得当前权威 ledger reconciliation。"
            "当前成本、手续费、订单沿袭、NAV 与 ledger reconciliation 均不可用；"
            "live_orders_allowed=false。"
        )
    account = value.get("account_observation")
    if isinstance(account, Mapping):
        side_names = {"long": "多头", "short": "空头"}
        position_rows = account["positions"]
        positions = ", ".join(
            f"{row['symbol']} {side_names[row['side']]} "
            f"{float(row['quantity']):g}（名义价值 "
            f"{float(row['notional']):.2f} {account['quote_asset']}）"
            for row in position_rows[:3]
        )
        if len(position_rows) > 3:
            positions = f"{positions} 等 {len(position_rows)} 个持仓"
        account_state = positions or "账户无非零持仓"
        observation_text = (
            f"交易所只读观察截至 {account['observed_at']}，"
            f"记录到{account_state}"
        )
    else:
        observation_text = (
            f"阻断运行观察截至 {blocked['observed_at']}，"
            "但没有可用的账户持仓明细"
        )
    return (
        f"运行事实边界：{ledger_text}；{observation_text}。"
        "该观察未进入 Qount ledger，当前成本、手续费、订单沿袭、NAV 与 "
        "ledger reconciliation 均不可用；live_orders_allowed=false。"
        f"观察哈希 {blocked['observation_hash']}。"
    )


def _executive_summary(
    editor_summary: str,
    runtime_fact_boundary: Mapping[str, Any],
    market_pulse: MarketPulse,
) -> str:
    notice = _runtime_boundary_notice(runtime_fact_boundary)
    if notice is None:
        return editor_summary
    # Execution and reconciliation claims from an LLM cannot survive a
    # deterministic current-fact conflict. Retain only the supplied market facts.
    return f"{notice} {_market_facts_summary(market_pulse)}"[:2_000].rstrip()


def run_daily_intelligence(
    *,
    created_at: str,
    market_pulse: MarketPulse,
    market_bodies: Mapping[str, bytes],
    runtime_ledger_snapshot: Any | None,
    blocked_runtime_observation: Mapping[str, Any] | None = None,
    search_provider: SearchProvider,
    archive_root: str,
    llm_config: AlphaLLMConfig | None = None,
    search_queries: Sequence[str] = DEFAULT_DAILY_SEARCH_QUERIES,
    source_fetcher: Callable[..., OfficialSourceDocument] = fetch_official_source_document,
    maximum_sources: int = 8,
) -> DailyIntelligenceRun:
    if maximum_sources < 1 or maximum_sources > 20:
        raise ValueError("intelligence_maximum_sources_invalid")
    market_pulse.validate()
    config = llm_config or AlphaLLMConfig.from_env()
    trading_history = summarize_trading_history(runtime_ledger_snapshot)
    runtime_fact_boundary = summarize_runtime_fact_boundary(
        runtime_ledger_snapshot,
        blocked_runtime_observation,
        evaluated_at=created_at,
        stale_after_seconds=RUNTIME_LEDGER_CURRENT_MAX_AGE_SECONDS,
    )

    searches: list[SearchEvidence] = []
    search_bodies: list[bytes] = []
    candidates: list[tuple[str, str]] = []
    for query in search_queries:
        response = search_provider.search(query, searched_at=created_at)
        searches.append(response.evidence)
        search_bodies.append(response.raw_body)
        candidates.extend(zip(response.titles, response.evidence.urls, strict=False))

    sources: list[SourceEvidence] = []
    source_bodies: dict[str, bytes] = {}
    seen_urls: set[str] = set()
    source_failures: list[str] = []
    for title, url in candidates:
        if url in seen_urls or validate_official_source_url(url):
            continue
        seen_urls.add(url)
        try:
            document = source_fetcher(url, observed_at=created_at)
        except (OSError, ValueError) as exc:
            source_failures.append(f"{url}:{type(exc).__name__}")
            continue
        sources.append(_source_evidence(document, title))
        source_bodies[document.source_hash] = document.body
        if len(sources) >= maximum_sources:
            break

    source_refs = tuple(
        SourceRef(
            title=source.title,
            url=source.final_url,
            source_type="verified_primary_source",
            notes=(
                f"sha256={source.source_hash}; observed_at={source.observed_at}; "
                f"published_at={source.published_at}; quality={source.content_quality}; "
                f"parser={source.parser_version}"
            ),
        )
        for source in sources
    )
    reports: list[AgentReport] = []
    failed_infrastructure_role: str | None = None
    for role in DAILY_ROLES:
        if failed_infrastructure_role is not None:
            reports.append(
                _circuit_blocked_agent(
                    role=role,
                    sources=source_refs,
                    failed_role_id=failed_infrastructure_role,
                )
            )
            continue
        context = _role_context(
            role_id=role.role_id,
            created_at=created_at,
            market_pulse=market_pulse,
            trading_history=trading_history,
            runtime_fact_boundary=runtime_fact_boundary,
            sources=sources,
            source_failures=source_failures,
            reports=reports,
        )
        report = _run_agent(
            config=config,
            role=role,
            context=context,
            sources=source_refs,
        )
        reports.append(report)
        if any(risk.startswith("llm_request_error:") for risk in report.risks):
            failed_infrastructure_role = role.role_id

    editor = reports[-1]
    observed_impacts = tuple(
        dict.fromkeys(
            item
            for report in reports[:2]
            for item in report.findings
        )
    )[:12]
    proposals = tuple(dict.fromkeys(reports[3].proposals))[:12]
    boundary_notice = _runtime_boundary_notice(runtime_fact_boundary)
    risks = tuple(
        dict.fromkeys(
            ([boundary_notice] if boundary_notice is not None else [])
            + [item for report in reports for item in report.risks]
        )
    )[:12]
    pipeline_status = (
        "partial"
        if source_failures
        or failed_infrastructure_role is not None
        or any(report.status == "blocked" for report in reports)
        else "complete"
    )
    evidence_status, evidence_summary = _evidence_summary(
        sources,
        trading_history,
        runtime_fact_boundary,
    )
    status = (
        "incomplete"
        if pipeline_status != "complete" or evidence_status != "sufficient"
        else "attention_required"
        if risks
        else "clear"
    )
    source_hashes = {
        "market_pulse": market_pulse.pulse_hash,
        "trading_history": trading_history["summary_hash"],
        **{f"source_{index:02d}": source.source_hash for index, source in enumerate(sources)},
        **{
            f"search_{index:02d}": search.response_hash
            for index, search in enumerate(searches)
        },
    }
    report = DailyIntelligenceReport.create(
        report_date=_date(created_at),
        created_at=created_at,
        status=status,
        pipeline_status=pipeline_status,
        evidence_status=evidence_status,
        evidence_summary=evidence_summary,
        market_pulse=market_pulse,
        trading_history=trading_history,
        searches=searches,
        sources=sources,
        agent_reports=reports,
        executive_summary=_executive_summary(
            editor.summary,
            runtime_fact_boundary,
            market_pulse,
        ),
        observed_impacts=observed_impacts,
        research_proposals=proposals,
        risk_notes=risks,
        source_hashes=source_hashes,
        llm={
            "enabled": config.enabled,
            "model": config.model,
            "provider_profile": config.provider_profile,
        },
        current_history_authoritative=not _runtime_boundary_is_conflicted(
            runtime_fact_boundary
        ),
        runtime_history_authority=_runtime_history_authority(runtime_fact_boundary),
    )
    archive = archive_daily_intelligence(
        archive_root,
        report,
        source_bodies=source_bodies,
        search_bodies=search_bodies,
        market_bodies=market_bodies,
    )
    return DailyIntelligenceRun(report=report, archive=archive)


__all__ = [
    "DAILY_ROLES",
    "DEFAULT_DAILY_SEARCH_QUERIES",
    "DailyIntelligenceRun",
    "run_daily_intelligence",
]
