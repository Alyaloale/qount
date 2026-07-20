from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from typing import Any

from qount.artifacts import write_research_json_artifact
from qount.models import utc_now
from qount.settings import Settings

from .models import SourceRef
from .sources import SOURCE_BOOK
from .sources import sources_for_tags


KNOWLEDGE_VERSION = "alpha_agent_knowledge_v0.1"


@dataclass(frozen=True)
class SourceAssessment:
    source: SourceRef
    score: float
    verdict: str
    reasons: tuple[str, ...]
    allowed_use: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["source"] = self.source.to_dict()
        return result


BASE_SCORES = {
    "official_exchange_doc": 1.00,
    "official_exchange_data": 1.00,
    "primary_research": 0.95,
    "local_project_doc": 0.90,
    "local_infra_doc": 0.85,
    "book": 0.85,
    "security_reference": 0.80,
    "tutorial": 0.55,
    "library_doc": 0.50,
    "blog": 0.35,
    "social": 0.15,
}


def assess_source(source: SourceRef) -> SourceAssessment:
    score = BASE_SCORES.get(source.source_type, 0.30)
    reasons: list[str] = [f"base:{source.source_type}={score:.2f}"]
    allowed: list[str] = []
    url = source.url.lower()
    title = source.title.lower()

    if not source.url:
        score -= 0.30
        reasons.append("missing_url")
    if "binance" in title or "binance" in url:
        if "developers.binance.com" in url or "github.com/binance/" in url or "data.binance.vision" in url:
            reasons.append("binance_official_source")
        else:
            score -= 0.25
            reasons.append("binance_secondary_source_penalty")
    if source.source_type in {"tutorial", "blog", "social", "library_doc"}:
        reasons.append("secondary_source_needs_primary_confirmation")
    if source.source_type in {"official_exchange_doc", "official_exchange_data"}:
        allowed.extend(("data_contract", "exchange_rule", "runtime_validation"))
    elif source.source_type in {"primary_research", "book"}:
        allowed.extend(("validation_method", "metric_definition"))
    elif source.source_type == "security_reference":
        allowed.extend(("agent_security_policy", "permission_boundary"))
    elif source.source_type == "local_project_doc":
        allowed.extend(("project_fact", "prior_evidence"))
    elif source.source_type == "tutorial":
        allowed.extend(("implementation_hint", "learning_material"))
    else:
        allowed.append("background_only")

    score = max(0.0, min(1.0, score))
    if score >= 0.80:
        verdict = "accept"
    elif score >= 0.50:
        verdict = "review"
    else:
        verdict = "reject"
    return SourceAssessment(
        source=source,
        score=score,
        verdict=verdict,
        reasons=tuple(reasons),
        allowed_use=tuple(allowed),
    )


def build_knowledge_report(tags: tuple[str, ...] | None = None) -> dict[str, Any]:
    selected_tags = tags or tuple(SOURCE_BOOK)
    sources = sources_for_tags(selected_tags)
    assessments = [assess_source(source) for source in sources]
    counts = {"accept": 0, "review": 0, "reject": 0}
    for item in assessments:
        counts[item.verdict] += 1
    return {
        "schema_version": KNOWLEDGE_VERSION,
        "created_at": utc_now().isoformat(),
        "tags": list(selected_tags),
        "source_count": len(assessments),
        "verdict_counts": counts,
        "assessments": [item.to_dict() for item in assessments],
        "policy": [
            "Official exchange docs and runtime exchangeInfo define executable market rules.",
            "Primary research and project artifacts define validation gates.",
            "Tutorials are learning material only; they cannot satisfy promotion gates.",
            "Social/blog sources are background only unless confirmed by primary sources.",
            "LLM summaries cannot upgrade source trust scores.",
        ],
    }


def write_knowledge_report_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="alpha-agent-knowledge",
        path_key="artifact_path",
        default_filename="alpha_agent_knowledge.json",
        explicit_path=explicit_path,
    )
