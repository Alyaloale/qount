from __future__ import annotations

import json
import os
import time
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
VOLC_CODING_PLAN_PROFILE = "volc_coding_plan"
VOLC_CODING_PLAN_BASE_URL = "https://ark.cn-beijing.volces.com/api/coding/v3"
VOLC_CODING_PLAN_DEFAULT_MODEL = "glm-5-2-260617"
VOLC_CODING_PLAN_DEFAULT_MAX_TOKENS = 8_000
_REPORT_KEYS = frozenset({"status", "summary", "findings", "proposals", "risks"})
_TRANSIENT_HTTP_STATUSES = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 524})
_REPORT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["ok", "blocked", "needs_research"]},
        "summary": {"type": "string", "minLength": 1},
        "findings": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "maxItems": 6,
        },
        "proposals": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "maxItems": 6,
        },
        "risks": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "maxItems": 6,
        },
    },
    "required": ["status", "summary", "findings", "proposals", "risks"],
    "additionalProperties": False,
}


def _is_zh_cn(output_language: str | None) -> bool:
    return output_language == "zh-CN"


def _localized(output_language: str | None, *, zh: str, en: str) -> str:
    return zh if _is_zh_cn(output_language) else en


def _contains_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _payload_matches_language(
    payload: dict[str, Any], output_language: str | None
) -> bool:
    if not _is_zh_cn(output_language):
        return True
    narratives = [payload["summary"]]
    for name in ("findings", "proposals", "risks"):
        narratives.extend(payload[name])
    return all(_contains_cjk(value) for value in narratives)


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
    max_retries: int = 1
    retry_base_seconds: int = 10
    max_retry_delay_seconds: int = 60
    provider_profile: str = RELAY_STATION_CHATGPT_PROFILE
    max_input_chars: int = 50_000
    max_response_chars: int = 20_000

    @classmethod
    def from_env(
        cls,
        *,
        enabled_override: bool | None = None,
        load_local_file: bool = True,
    ) -> "AlphaLLMConfig":
        if load_local_file:
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
            max_retries=max(0, int(os.getenv("QOUNT_ALPHA_AGENT_MAX_RETRIES", "1"))),
            retry_base_seconds=max(
                1, int(os.getenv("QOUNT_ALPHA_AGENT_RETRY_BASE_SECONDS", "10"))
            ),
            max_retry_delay_seconds=max(
                1,
                int(os.getenv("QOUNT_ALPHA_AGENT_MAX_RETRY_DELAY_SECONDS", "60")),
            ),
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
        elif self.provider_profile == VOLC_CODING_PLAN_PROFILE:
            if self.base_url.rstrip("/") != VOLC_CODING_PLAN_BASE_URL:
                errors.append("volc_coding_plan_base_url_not_allowlisted")
            if not self.model.strip():
                errors.append("volc_coding_plan_model_required")
        else:
            errors.append("llm_provider_profile_unsupported")
        if self.timeout_seconds <= 0:
            errors.append("llm_timeout_invalid")
        if self.max_tokens <= 0:
            errors.append("llm_max_tokens_invalid")
        if self.max_concurrency != 1:
            errors.append("research_llm_concurrency_must_equal_one")
        if self.max_retries > 2:
            errors.append("research_llm_retries_must_not_exceed_two")
        if self.retry_base_seconds <= 0 or self.max_retry_delay_seconds <= 0:
            errors.append("research_llm_retry_delay_invalid")
        if self.max_input_chars <= 0 or self.max_response_chars <= 0:
            errors.append("llm_payload_limit_invalid")
        return tuple(errors)


def offline_report(
    role: AgentRole,
    task: ResearchTask,
    sources: tuple[SourceRef, ...],
    reason: str,
    *,
    output_language: str | None = None,
) -> AgentReport:
    if _is_zh_cn(output_language):
        findings = (
            f"角色 {role.role_id} 已注册，但本次未调用 LLM：{reason}",
            "本报告只是任务骨架，不构成研究证据或交易信号。",
            "边界：仅限研究，不得分配组合风险或修改实盘运行状态。",
        )
        risks = (
            "在确定性量化产物形成前，不得提出策略晋级结论。",
            "LLM 输出只能用于描述和复核，不得分配风险或修改运行控制。",
        )
        summary = f"已为{role.name}创建“{task.title}”任务骨架。"
    else:
        findings = (
            f"role={role.role_id} registered; runtime LLM call skipped: {reason}",
            "This report is a task scaffold, not research evidence or a trading signal.",
            "Guardrail: research-only; portfolio allocation and live runtime changes are out of scope.",
        )
        risks = (
            "No promotion claim is allowed until a deterministic quant artifact exists.",
            "LLM output must stay descriptive and cannot allocate portfolio risk or alter runtime controls.",
        )
        summary = f"{role.name} task scaffold created for {task.title}."
    report = AgentReport(
        role_id=role.role_id,
        task_id=task.task_id,
        status="needs_research",
        summary=summary,
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
            summary=_localized(
                output_language,
                zh="离线报告未通过 Alpha Agent 合同校验。",
                en="Offline report failed alpha-agent validation.",
            ),
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


def _parse_report_json(raw: str, provider_profile: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        if provider_profile != VOLC_CODING_PLAN_PROFILE:
            raise
        lines = raw.strip().splitlines()
        if (
            len(lines) < 3
            or lines[0].strip().casefold() != "```json"
            or lines[-1].strip() != "```"
        ):
            raise
        return json.loads("\n".join(lines[1:-1]))


def _exception_status(exc: Exception) -> int | None:
    value = getattr(exc, "status_code", None)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _owner_action_required(exc: Exception) -> bool:
    body = getattr(exc, "body", None)
    if not isinstance(body, dict):
        return False
    if body.get("owner_action_required") is True:
        return True
    error = body.get("error")
    return isinstance(error, dict) and error.get("owner_action_required") is True


def _body_value(exc: Exception, name: str) -> Any:
    body = getattr(exc, "body", None)
    if not isinstance(body, dict):
        return None
    if name in body:
        return body[name]
    error = body.get("error")
    return error.get(name) if isinstance(error, dict) else None


def _retry_delay(config: AlphaLLMConfig, exc: Exception, attempt: int) -> float:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    retry_after = headers.get("retry-after") if headers is not None else None
    if retry_after is None:
        retry_after = _body_value(exc, "retry_after")
    if retry_after is not None:
        try:
            seconds = float(retry_after)
        except (TypeError, ValueError):
            seconds = 0.0
        if seconds > 0:
            return min(float(config.max_retry_delay_seconds), seconds)
    delay = config.retry_base_seconds * (2**attempt)
    return float(min(config.max_retry_delay_seconds, delay))


def _is_transient_request_error(exc: Exception) -> bool:
    status = _exception_status(exc)
    explicitly_retryable = _body_value(exc, "retryable") is True
    if _owner_action_required(exc) and not explicitly_retryable:
        return False
    if status is not None:
        return status in _TRANSIENT_HTTP_STATUSES
    return type(exc).__name__ in {
        "APIConnectionError",
        "APITimeoutError",
        "ConnectError",
        "ConnectTimeout",
        "ReadError",
        "ReadTimeout",
        "TimeoutException",
    }


def _request_error_reason(exc: Exception, attempts: int) -> str:
    status = _exception_status(exc)
    status_part = f":http_{status}" if status is not None else ""
    return f"llm_request_error:{type(exc).__name__}{status_part}:attempts_{attempts}"


def request_agent_report(
    *,
    config: AlphaLLMConfig,
    role: AgentRole,
    task: ResearchTask,
    sources: tuple[SourceRef, ...],
    context: dict[str, Any],
    output_language: str | None = None,
) -> AgentReport:
    if not config.enabled:
        return offline_report(
            role,
            task,
            sources,
            "QOUNT_ALPHA_AGENT_LLM_ENABLE is not true",
            output_language=output_language,
        )
    if not role.llm_allowed:
        return offline_report(
            role,
            task,
            sources,
            "role is deterministic-only",
            output_language=output_language,
        )
    if not config.api_key:
        return offline_report(
            role,
            task,
            sources,
            "QOUNT_ALPHA_AGENT_API_KEY is not set",
            output_language=output_language,
        )
    config_errors = config.validate()
    if config_errors:
        return AgentReport(
            role_id=role.role_id,
            task_id=task.task_id,
            status="blocked",
            summary=_localized(
                output_language,
                zh="LLM 配置未通过研究边界校验。",
                en="LLM configuration failed the research boundary.",
            ),
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
            "language": output_language or "unspecified",
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
    if _is_zh_cn(output_language):
        messages[0]["content"] += (
            " summary、findings、proposals 和 risks 中的所有自然语言必须使用简体中文；"
            "市场代码、哈希、URL 和专有名词可以保留原文。"
        )
    serialized_payload = messages[1]["content"]
    if len(serialized_payload) > config.max_input_chars:
        return AgentReport(
            role_id=role.role_id,
            task_id=task.task_id,
            status="blocked",
            summary=_localized(
                output_language,
                zh="LLM 输入超过冻结的研究载荷上限。",
                en="LLM input exceeded the frozen research payload limit.",
            ),
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
    for attempt in range(config.max_retries + 1):
        try:
            if config.provider_profile == VOLC_CODING_PLAN_PROFILE:
                response = client.chat.completions.create(
                    model=config.model,
                    messages=messages,
                    temperature=config.temperature,
                    max_tokens=config.max_tokens,
                    response_format={"type": "json_object"},
                )
            else:
                response = client.responses.create(
                    model=config.model,
                    input=messages,
                    temperature=config.temperature,
                    max_output_tokens=config.max_tokens,
                    store=False,
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "qount_agent_report",
                            "strict": True,
                            "schema": _REPORT_JSON_SCHEMA,
                        }
                    },
                )
        except Exception as exc:
            if attempt < config.max_retries and _is_transient_request_error(exc):
                time.sleep(_retry_delay(config, exc, attempt))
                continue
            client.close()
            return AgentReport(
                role_id=role.role_id,
                task_id=task.task_id,
                status="blocked",
                summary=_localized(
                    output_language,
                    zh="LLM 请求失败；该角色报告已阻断，但日报批次可继续归档。",
                    en="LLM request failed; agent report was blocked and the batch may continue.",
                ),
                findings=(),
                risks=(_request_error_reason(exc, attempt + 1),),
                sources=sources,
            )
        if config.provider_profile == VOLC_CODING_PLAN_PROFILE:
            choices = getattr(response, "choices", ())
            if len(choices) != 1:
                last_reason = "llm_chat_choices_invalid"
                break
            choice = choices[0]
            finish_reason = getattr(choice, "finish_reason", None)
            if finish_reason != "stop":
                last_reason = f"llm_response_status_invalid:{finish_reason}"
                break
            message = getattr(choice, "message", None)
            raw = getattr(message, "content", "") or "{}"
        else:
            response_status = getattr(response, "status", "completed")
            if response_status != "completed":
                last_reason = f"llm_response_status_invalid:{response_status}"
                break
            raw = getattr(response, "output_text", "") or "{}"
        if not isinstance(raw, str):
            last_reason = "llm_response_text_invalid"
            break
        last_raw = raw
        if len(raw) > config.max_response_chars:
            last_reason = "llm_response_too_large"
            break
        try:
            parsed = _parse_report_json(raw, config.provider_profile)
        except json.JSONDecodeError as exc:
            last_reason = f"llm_parse_error:{exc.__class__.__name__}"
            break
        strict_payload, payload_error = _validate_report_payload(parsed)
        if payload_error is not None or strict_payload is None:
            last_reason = payload_error or "llm_payload_invalid"
            break
        if not _payload_matches_language(strict_payload, output_language):
            last_reason = "llm_payload_language_invalid"
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
        break
    client.close()
    return AgentReport(
        role_id=role.role_id,
        task_id=task.task_id,
        status="blocked",
        summary=_localized(
            output_language,
            zh="LLM 响应未通过 Alpha Agent 合同校验。",
            en="LLM response failed alpha-agent validation.",
        ),
        findings=(),
        risks=(last_reason,),
        sources=sources,
        raw_response=last_raw,
    )
