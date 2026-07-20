from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from typing import Any


ALPHA_AGENT_VERSION = "alpha_agents_v0.1"


@dataclass(frozen=True)
class SourceRef:
    title: str
    url: str
    source_type: str
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentRole:
    role_id: str
    name: str
    kind: str
    mission: str
    allowed_outputs: tuple[str, ...]
    forbidden_outputs: tuple[str, ...]
    required_checks: tuple[str, ...] = ()
    llm_allowed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResearchTask:
    task_id: str
    title: str
    objective: str
    role_ids: tuple[str, ...]
    required_outputs: tuple[str, ...]
    source_tags: tuple[str, ...] = ()
    holdout_role: str = "discovery"
    priority: int = 100

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentReport:
    role_id: str
    task_id: str
    status: str
    summary: str
    findings: tuple[str, ...] = ()
    proposals: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    sources: tuple[SourceRef, ...] = ()
    raw_response: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["sources"] = [source.to_dict() for source in self.sources]
        return result
