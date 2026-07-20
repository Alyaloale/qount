from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .models import AgentReport
from .models import AgentRole
from .models import ResearchTask
from .models import SourceRef
from .validators import find_forbidden_output
from .validators import validate_agent_report


RELAY_STATION_CHATGPT_PROFILE = "relay_station_chatgpt"
RELAY_STATION_BASE_URL = "https://llm.alyaloale.com/v1"
RELAY_STATION_DEFAULT_MODEL = "gpt-5.6-terra"
_REPORT_KEYS = frozenset({"status", "summary", "findings", "proposals", "risks"})


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _load_local_alpha_env() -> None:
    path = Path.home() / ".qount" / "alpha-agent.env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class AlphaLLMConfig:
    enabled: bool
    base_url: str
    api_key: str
    model: str
    timeout_seconds: int = 90
    temperature: float = 0.0
    max_tokens: int = 2000
    max_concurrency: int = 1
    max_retries: int = 0
    provider_profile: str = RELAY_STATION_CHATGPT_PROFILE
    max_input_chars: int = 50_000
    max_response_chars: int = 20_000

    @classmethod
    def from_env(cls, *, enabled_override: bool | None = None) -> "AlphaLLMConfig":
        _load_local_alpha_env()
        enabled = _env_bool("QOUNT_ALPHA_AGENT_LLM_ENABLE", False)
        if enabled_override is not None:
            enabled = enabled_override
        return cls(
            enabled=enabled,
            base_url=os.getenv("QOUNT_ALPHA_AGENT_BASE_URL", RELAY_STATION_BASE_URL),
            api_key=os.getenv("QOUNT_ALPHA_AGENT_API_KEY", ""),
            model=os.getenv("QOUNT_ALPHA_AGENT_MODEL", RELAY_STATION_DEFAULT_MODEL),
            timeout_seconds=int(os.getenv("QOUNT_ALPHA_AGENT_TIMEOUT_SECONDS", "90")),
            temperature=float(os.getenv("QOUNT_ALPHA_AGENT_TEMPERATURE", "0")),
            max_tokens=int(os.getenv("QOUNT_ALPHA_AGENT_MAX_TOKENS", "2000")),
            max_concurrency=max(1, int(os.getenv("QOUNT_ALPHA_AGENT_MAX_CONCURRENCY", "1"))),
            max_retries=max(0, int(os.getenv("QOUNT_ALPHA_AGENT_MAX_RETRIES", "0"))),
            provider_profile=os.getenv(
                "QOUNT_ALPHA_AGENT_PROVIDER_PROFILE", RELAY_STATION_CHATGPT_PROFILE
            ),
            max_input_chars=max(
                1, int(os.getenv("QOUNT_ALPHA_AGENT_MAX_INPUT_CHARS", "50000"))
            ),
            max_response_chars=max(
                1, int(os.getenv("QOUNT_ALPHA_AGENT_MAX_RESPONSE_CHARS", "20000"))
            ),
        )

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        parsed = urlparse(self.base_url)
        if self.provider_profile == RELAY_STATION_CHATGPT_PROFILE:
            if parsed.scheme != "https" or parsed.hostname != "llm.alyaloale.com":
                errors.append("relay_station_base_url_not_allowlisted")
            if parsed.path.rstrip("/") != "/v1":
                errors.append("relay_station_base_path_must_be_v1")
            if not self.model.startswith("gpt-") and self.model != "codex-auto-review":
                errors.append("relay_station_chatgpt_model_required")
        if self.timeout_seconds <= 0:
            errors.append("llm_timeout_invalid")
        if self.max_tokens <= 0:
            errors.append("llm_max_tokens_invalid")
        if self.max_concurrency != 1:
            errors.append("research_llm_concurrency_must_equal_one")
        if self.max_retries != 0:
            errors.append("research_llm_retries_must_equal_zero")
        if self.max_input_chars <= 0 or self.max_response_chars <= 0:
            errors.append("llm_payload_limit_invalid")
        return tuple(errors)


def offline_report(role: AgentRole, task: ResearchTask, sources: tuple[SourceRef, ...], reason: str) -> AgentReport:
    findings = (
        f"role={role.role_id} registered; runtime LLM call skipped: {reason}",
        "This report is a task scaffold, not research evidence or a trading signal.",
        "Guardrail: research-only; portfolio allocation and live runtime changes are out of scope.",
    )
    risks = (
        "No promotion claim is allowed until a deterministic quant artifact exists.",
        "LLM output must stay descriptive and cannot allocate portfolio risk or alter runtime controls.",
    )
    report = AgentReport(
        role_id=role.role_id,
        task_id=task.task_id,
        status="needs_research",
        summary=f"{role.name} task scaffold created for {task.title}.",
        findings=findings,
        risks=risks,
        sources=sources,
    )
    errors = validate_agent_report(report)
    if errors:
        return AgentReport(
            role_id=role.role_id,
            task_id=task.task_id,
            status="blocked",
            summary="Offline report failed alpha-agent validation.",
            risks=errors,
            sources=sources,
        )
    return report


def _validate_report_payload(parsed: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(parsed, dict):
        return None, "llm_payload_not_object"
    if set(parsed) != _REPORT_KEYS:
        return None, "llm_payload_keys_not_exact"
    if parsed["status"] not in {"ok", "blocked", "needs_research"}:
        return None, "llm_payload_status_invalid"
    if not isinstance(parsed["summary"], str) or not parsed["summary"].strip():
        return None, "llm_payload_summary_invalid"
    for name in ("findings", "proposals", "risks"):
        value = parsed[name]
        if not isinstance(value, list) or len(value) > 6:
            return None, f"llm_payload_{name}_invalid"
        if any(not isinstance(item, str) or not item.strip() for item in value):
            return None, f"llm_payload_{name}_items_invalid"
    return parsed, None


def _strict_json_retry_message(reason: str) -> dict[str, str]:
    return {
        "role": "user",
        "content": (
            "Your previous response failed validation: "
            f"{reason}. Return ONLY one valid JSON object with exactly these keys: "
            "status, summary, findings, proposals, risks. "
            "status must be ok, blocked, or needs_research. "
            "summary must be one sentence. findings/proposals/risks must be arrays of strings only. "
            "No nested objects, no markdown, no comments, no extra keys."
        ),
    }


def request_agent_report(
    *,
    config: AlphaLLMConfig,
    role: AgentRole,
    task: ResearchTask,
    sources: tuple[SourceRef, ...],
    context: dict[str, Any],
) -> AgentReport:
    if not config.enabled:
        return offline_report(role, task, sources, "QOUNT_ALPHA_AGENT_LLM_ENABLE is not true")
    if not role.llm_allowed:
        return offline_report(role, task, sources, "role is deterministic-only")
    if not config.api_key:
        return offline_report(role, task, sources, "QOUNT_ALPHA_AGENT_API_KEY is not set")
    config_errors = config.validate()
    if config_errors:
        return AgentReport(
            role_id=role.role_id,
            task_id=task.task_id,
            status="blocked",
            summary="LLM configuration failed the relay-station research boundary.",
            risks=config_errors,
            sources=sources,
        )

    try:
        from openai import DefaultHttpxClient, OpenAI
    except ImportError as exc:
        raise RuntimeError("openai package is required for alpha-agent LLM calls") from exc

    payload = {
        "role": {
            "role_id": role.role_id,
            "mission": role.mission,
            "required_checks": role.required_checks,
            "forbidden_outputs": role.forbidden_outputs,
        },
        "task": {
            "task_id": task.task_id,
            "objective": task.objective,
            "required_outputs": task.required_outputs,
        },
        "sources": [
            {
                "title": source.title,
                "url": source.url,
                "source_type": source.source_type,
                "notes": source.notes,
            }
            for source in sources[:8]
        ],
        "context": context,
        "output_contract": {
            "required_top_level_keys": ["status", "summary", "findings", "proposals", "risks"],
            "status": "ok | blocked | needs_research",
            "summary": "one sentence string",
            "findings": ["array of strings only, max 6"],
            "proposals": ["array of strings only, max 6"],
            "risks": ["array of strings only, max 6"],
            "forbidden": "nested objects, markdown, comments, extra keys",
        },
    }
    messages = [
        {
            "role": "system",
            "content": (
                "You are a research-only trading-system agent. Output JSON only. "
                "The JSON object must have exactly five top-level keys: status, summary, findings, proposals, risks. "
                "findings, proposals, and risks must be arrays of strings only; no nested objects. "
                "Never propose direct orders, target weights, live config changes, or risk overrides. "
                "Be concise. Every claim must be tied to supplied sources or marked as a hypothesis."
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]
    serialized_payload = messages[1]["content"]
    if len(serialized_payload) > config.max_input_chars:
        return AgentReport(
            role_id=role.role_id,
            task_id=task.task_id,
            status="blocked",
            summary="LLM input exceeded the frozen research payload limit.",
            risks=("llm_input_too_large",),
            sources=sources,
        )
    client = OpenAI(
        base_url=config.base_url,
        api_key=config.api_key,
        timeout=config.timeout_seconds,
        max_retries=0,
        http_client=DefaultHttpxClient(trust_env=False),
    )
    last_raw = ""
    last_reason = "unknown_error"
    current_messages = list(messages)
    for attempt in range(config.max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=config.model,
                messages=current_messages,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            client.close()
            return AgentReport(
                role_id=role.role_id,
                task_id=task.task_id,
                status="blocked",
                summary="LLM request failed; agent report was blocked and the batch may continue.",
                findings=(),
                risks=(f"llm_request_error:{type(exc).__name__}",),
                sources=sources,
            )
        raw = response.choices[0].message.content or "{}"
        last_raw = raw
        if len(raw) > config.max_response_chars:
            last_reason = "llm_response_too_large"
            break
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            last_reason = f"llm_parse_error:{exc.__class__.__name__}"
            if attempt < config.max_retries:
                current_messages.append({"role": "assistant", "content": raw[:2000]})
                current_messages.append(_strict_json_retry_message(last_reason))
                continue
            break
        strict_payload, payload_error = _validate_report_payload(parsed)
        if payload_error is not None or strict_payload is None:
            last_reason = payload_error or "llm_payload_invalid"
            if attempt < config.max_retries:
                current_messages.append({"role": "assistant", "content": raw[:2000]})
                current_messages.append(_strict_json_retry_message(last_reason))
                continue
            break
        candidate = AgentReport(
            role_id=role.role_id,
            task_id=task.task_id,
            status=strict_payload["status"],
            summary=strict_payload["summary"],
            findings=tuple(strict_payload["findings"]),
            proposals=tuple(strict_payload["proposals"]),
            risks=tuple(strict_payload["risks"]),
            sources=sources,
            raw_response=raw,
        )
        validation_errors = validate_agent_report(candidate)
        if not validation_errors:
            client.close()
            return candidate
        last_reason = ",".join(validation_errors)
        if attempt < config.max_retries:
            current_messages.append({"role": "assistant", "content": raw[:2000]})
            current_messages.append(_strict_json_retry_message(last_reason))
            continue
    client.close()
    return AgentReport(
        role_id=role.role_id,
        task_id=task.task_id,
        status="blocked",
        summary="LLM response failed alpha-agent validation.",
        findings=(),
        risks=(last_reason,),
        sources=sources,
        raw_response=last_raw,
    )
