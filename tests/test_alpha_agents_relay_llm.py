from __future__ import annotations

import json
import os
import sys
import types
import unittest
from unittest.mock import patch

from qount.alpha_agents.llm import AlphaLLMConfig
from qount.alpha_agents.llm import RELAY_STATION_BASE_URL
from qount.alpha_agents.llm import RELAY_STATION_DEFAULT_MODEL
from qount.alpha_agents.llm import VOLC_CODING_PLAN_BASE_URL
from qount.alpha_agents.llm import VOLC_CODING_PLAN_PROFILE
from qount.alpha_agents.llm import request_agent_report
from qount.alpha_agents.models import AgentRole
from qount.alpha_agents.models import ResearchTask
from qount.alpha_agents.models import SourceRef


def _role() -> AgentRole:
    return AgentRole(
        role_id="information_researcher",
        name="InformationResearcher",
        kind="llm_research",
        mission="Extract research facts from supplied official sources.",
        allowed_outputs=("research_report",),
        forbidden_outputs=("order", "target_weight"),
        llm_allowed=True,
    )


def _task() -> ResearchTask:
    return ResearchTask(
        task_id="fixture",
        title="Fixture extraction",
        objective="Describe supplied point-in-time facts.",
        role_ids=("information_researcher",),
        required_outputs=("research_report",),
    )


def _source() -> tuple[SourceRef, ...]:
    return (
        SourceRef(
            title="Official filing",
            url="https://www.sec.gov/Archives/fixture",
            source_type="official",
        ),
    )


class _FakeProviderError(Exception):
    def __init__(
        self,
        status_code: int,
        *,
        retry_after: str | None = None,
        owner_action_required: bool = False,
        retryable: bool = False,
        body_retry_after: int | None = None,
    ) -> None:
        super().__init__(f"http_{status_code}")
        self.status_code = status_code
        headers = {} if retry_after is None else {"retry-after": retry_after}
        self.response = types.SimpleNamespace(headers=headers)
        self.body = {
            "owner_action_required": owner_action_required,
            "retryable": retryable,
        }
        if body_retry_after is not None:
            self.body["retry_after"] = body_retry_after


class _FakeResponses:
    def __init__(
        self,
        raw: str,
        calls: list[dict],
        status: str,
        failures: list[Exception],
    ) -> None:
        self.raw = raw
        self.calls = calls
        self.status = status
        self.failures = failures

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.failures:
            raise self.failures.pop(0)
        return types.SimpleNamespace(output_text=self.raw, status=self.status)


class _FakeChatCompletions:
    def __init__(
        self,
        raw: str,
        calls: list[dict],
        finish_reason: str | None,
        failures: list[Exception],
    ) -> None:
        self.raw = raw
        self.calls = calls
        self.finish_reason = finish_reason
        self.failures = failures

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.failures:
            raise self.failures.pop(0)
        return types.SimpleNamespace(
            choices=(
                types.SimpleNamespace(
                    finish_reason=self.finish_reason,
                    message=types.SimpleNamespace(content=self.raw),
                ),
            )
        )


def _fake_openai_module(
    raw: str,
    calls: list[dict],
    clients: list[dict],
    *,
    status: str = "completed",
    chat_finish_reason: str | None = "stop",
    failures: list[Exception] | None = None,
):
    class FakeHttpClient:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class FakeOpenAI:
        def __init__(self, **kwargs) -> None:
            clients.append(kwargs)
            provider_failures = failures or []
            self.responses = _FakeResponses(raw, calls, status, provider_failures)
            self.chat = types.SimpleNamespace(
                completions=_FakeChatCompletions(
                    raw,
                    calls,
                    chat_finish_reason,
                    provider_failures,
                )
            )

        def close(self) -> None:
            return None

    return types.SimpleNamespace(
        DefaultHttpxClient=FakeHttpClient,
        OpenAI=FakeOpenAI,
    )


class RelayStationLLMTests(unittest.TestCase):
    def test_env_defaults_to_relay_station_chatgpt_with_bounded_retry(self) -> None:
        with patch("qount.alpha_agents.llm._load_local_alpha_env"), patch.dict(
            os.environ, {}, clear=True
        ):
            config = AlphaLLMConfig.from_env()
        self.assertEqual(config.base_url, RELAY_STATION_BASE_URL)
        self.assertEqual(config.model, RELAY_STATION_DEFAULT_MODEL)
        self.assertEqual(config.model, "gpt-5.6-terra")
        self.assertEqual(config.max_concurrency, 1)
        self.assertEqual(config.max_retries, 1)
        self.assertEqual(config.retry_base_seconds, 10)
        self.assertEqual(config.max_retry_delay_seconds, 60)
        self.assertEqual(config.validate(), ())

    def test_retry_count_above_two_is_rejected(self) -> None:
        config = AlphaLLMConfig(
            enabled=True,
            base_url=RELAY_STATION_BASE_URL,
            api_key="fixture-secret",
            model=RELAY_STATION_DEFAULT_MODEL,
            max_retries=3,
        )
        self.assertIn(
            "research_llm_retries_must_not_exceed_two", config.validate()
        )

    def test_production_config_can_skip_implicit_local_file(self) -> None:
        with patch("qount.alpha_agents.llm._load_local_alpha_env") as loader, patch.dict(
            os.environ, {}, clear=True
        ):
            config = AlphaLLMConfig.from_env(load_local_file=False)
        loader.assert_not_called()
        self.assertEqual(config.base_url, RELAY_STATION_BASE_URL)
        self.assertEqual(config.model, RELAY_STATION_DEFAULT_MODEL)

    def test_valid_fixture_uses_responses_strict_json_without_tools(self) -> None:
        raw = json.dumps(
            {
                "status": "ok",
                "summary": "The supplied filing contains a research fact.",
                "findings": ["The source is an official filing."],
                "proposals": ["Validate the timestamp deterministically."],
                "risks": ["The fixture does not establish alpha."],
            }
        )
        calls: list[dict] = []
        clients: list[dict] = []
        config = AlphaLLMConfig(
            enabled=True,
            base_url=RELAY_STATION_BASE_URL,
            api_key="fixture-secret",
            model=RELAY_STATION_DEFAULT_MODEL,
        )
        with patch.dict(
            sys.modules,
            {"openai": _fake_openai_module(raw, calls, clients)},
        ):
            report = request_agent_report(
                config=config,
                role=_role(),
                task=_task(),
                sources=_source(),
                context={"fixture": True},
            )
        self.assertEqual(report.status, "ok")
        self.assertEqual(len(calls), 1)
        self.assertNotIn("tools", calls[0])
        self.assertEqual(calls[0]["model"], RELAY_STATION_DEFAULT_MODEL)
        self.assertEqual(calls[0]["max_output_tokens"], 2000)
        self.assertFalse(calls[0]["store"])
        self.assertEqual(calls[0]["input"][0]["role"], "system")
        response_format = calls[0]["text"]["format"]
        self.assertEqual(response_format["type"], "json_schema")
        self.assertEqual(response_format["name"], "qount_agent_report")
        self.assertTrue(response_format["strict"])
        self.assertFalse(response_format["schema"]["additionalProperties"])
        self.assertEqual(
            set(response_format["schema"]["required"]),
            {"status", "summary", "findings", "proposals", "risks"},
        )
        self.assertEqual(clients[0]["max_retries"], 0)
        self.assertFalse(clients[0]["http_client"].kwargs["trust_env"])

    def test_volc_coding_plan_uses_chat_json_object_and_local_validation(self) -> None:
        raw = json.dumps(
            {
                "status": "ok",
                "summary": "The supplied filing contains a research fact.",
                "findings": ["The source is an official filing."],
                "proposals": ["Validate the timestamp deterministically."],
                "risks": ["The fixture does not establish alpha."],
            }
        )
        calls: list[dict] = []
        config = AlphaLLMConfig(
            enabled=True,
            base_url=VOLC_CODING_PLAN_BASE_URL,
            api_key="fixture-secret",
            model="glm-5-2-260617",
            max_tokens=8000,
            provider_profile=VOLC_CODING_PLAN_PROFILE,
        )
        with patch.dict(
            sys.modules,
            {"openai": _fake_openai_module(raw, calls, [])},
        ):
            report = request_agent_report(
                config=config,
                role=_role(),
                task=_task(),
                sources=_source(),
                context={"fixture": True},
            )
        self.assertEqual(report.status, "ok")
        self.assertEqual(calls[0]["model"], "glm-5-2-260617")
        self.assertEqual(calls[0]["max_tokens"], 8000)
        self.assertEqual(calls[0]["response_format"], {"type": "json_object"})
        self.assertEqual(calls[0]["messages"][0]["role"], "system")
        self.assertNotIn("store", calls[0])
        self.assertNotIn("tools", calls[0])

    def test_volc_coding_plan_length_finish_is_blocked(self) -> None:
        config = AlphaLLMConfig(
            enabled=True,
            base_url=VOLC_CODING_PLAN_BASE_URL,
            api_key="fixture-secret",
            model="glm-5-2-260617",
            max_tokens=8000,
            provider_profile=VOLC_CODING_PLAN_PROFILE,
        )
        with patch.dict(
            sys.modules,
            {
                "openai": _fake_openai_module(
                    "{}", [], [], chat_finish_reason="length"
                )
            },
        ):
            report = request_agent_report(
                config=config,
                role=_role(),
                task=_task(),
                sources=_source(),
                context={"fixture": True},
            )
        self.assertEqual(report.status, "blocked")
        self.assertIn("llm_response_status_invalid:length", report.risks)

    def test_volc_coding_plan_accepts_one_json_fence_only(self) -> None:
        payload = {
            "status": "ok",
            "summary": "The supplied filing contains a research fact.",
            "findings": ["The source is an official filing."],
            "proposals": ["Validate the timestamp deterministically."],
            "risks": ["The fixture does not establish alpha."],
        }
        config = AlphaLLMConfig(
            enabled=True,
            base_url=VOLC_CODING_PLAN_BASE_URL,
            api_key="fixture-secret",
            model="glm-5-2-260617",
            max_tokens=8000,
            provider_profile=VOLC_CODING_PLAN_PROFILE,
        )
        with patch.dict(
            sys.modules,
            {
                "openai": _fake_openai_module(
                    f"```json\n{json.dumps(payload)}\n```", [], []
                )
            },
        ):
            report = request_agent_report(
                config=config,
                role=_role(),
                task=_task(),
                sources=_source(),
                context={"fixture": True},
            )
        self.assertEqual(report.status, "ok")

    def test_volc_coding_plan_rejects_text_around_json_fence(self) -> None:
        config = AlphaLLMConfig(
            enabled=True,
            base_url=VOLC_CODING_PLAN_BASE_URL,
            api_key="fixture-secret",
            model="glm-5-2-260617",
            max_tokens=8000,
            provider_profile=VOLC_CODING_PLAN_PROFILE,
        )
        with patch.dict(
            sys.modules,
            {
                "openai": _fake_openai_module(
                    "Result:\n```json\n{}\n```", [], []
                )
            },
        ):
            report = request_agent_report(
                config=config,
                role=_role(),
                task=_task(),
                sources=_source(),
                context={"fixture": True},
            )
        self.assertEqual(report.status, "blocked")
        self.assertIn("llm_parse_error:JSONDecodeError", report.risks)

    def test_volc_coding_plan_rejects_other_base_urls(self) -> None:
        config = AlphaLLMConfig(
            enabled=True,
            base_url="https://example.com/api/coding/v3",
            api_key="fixture-secret",
            model="glm-5-2-260617",
            provider_profile=VOLC_CODING_PLAN_PROFILE,
        )
        self.assertIn(
            "volc_coding_plan_base_url_not_allowlisted", config.validate()
        )

    def test_unknown_provider_profile_is_rejected(self) -> None:
        config = AlphaLLMConfig(
            enabled=True,
            base_url="https://example.com/v1",
            api_key="fixture-secret",
            model="fixture-model",
            provider_profile="unknown",
        )
        self.assertIn("llm_provider_profile_unsupported", config.validate())

    def test_transient_provider_error_retries_once_and_honors_retry_after(self) -> None:
        raw = json.dumps(
            {
                "status": "ok",
                "summary": "Recovered.",
                "findings": [],
                "proposals": [],
                "risks": [],
            }
        )
        calls: list[dict] = []
        config = AlphaLLMConfig(
            enabled=True,
            base_url=RELAY_STATION_BASE_URL,
            api_key="fixture-secret",
            model=RELAY_STATION_DEFAULT_MODEL,
            max_retries=1,
        )
        with patch.dict(
            sys.modules,
            {
                "openai": _fake_openai_module(
                    raw,
                    calls,
                    [],
                    failures=[_FakeProviderError(503, retry_after="7")],
                )
            },
        ), patch("qount.alpha_agents.llm.time.sleep") as sleeper:
            report = request_agent_report(
                config=config,
                role=_role(),
                task=_task(),
                sources=_source(),
                context={},
            )
        self.assertEqual(report.status, "ok")
        self.assertEqual(len(calls), 2)
        sleeper.assert_called_once_with(7.0)

    def test_owner_action_required_opens_without_retry(self) -> None:
        calls: list[dict] = []
        config = AlphaLLMConfig(
            enabled=True,
            base_url=RELAY_STATION_BASE_URL,
            api_key="fixture-secret",
            model=RELAY_STATION_DEFAULT_MODEL,
            max_retries=2,
        )
        with patch.dict(
            sys.modules,
            {
                "openai": _fake_openai_module(
                    "{}",
                    calls,
                    [],
                    failures=[
                        _FakeProviderError(502, owner_action_required=True)
                    ],
                )
            },
        ), patch("qount.alpha_agents.llm.time.sleep") as sleeper:
            report = request_agent_report(
                config=config,
                role=_role(),
                task=_task(),
                sources=_source(),
                context={},
            )
        self.assertEqual(report.status, "blocked")
        self.assertEqual(len(calls), 1)
        self.assertIn("http_502:attempts_1", report.risks[0])
        sleeper.assert_not_called()

    def test_retryable_cloudflare_owner_error_uses_body_delay(self) -> None:
        raw = json.dumps(
            {
                "status": "ok",
                "summary": "Recovered.",
                "findings": [],
                "proposals": [],
                "risks": [],
            }
        )
        calls: list[dict] = []
        config = AlphaLLMConfig(
            enabled=True,
            base_url=RELAY_STATION_BASE_URL,
            api_key="fixture-secret",
            model=RELAY_STATION_DEFAULT_MODEL,
            max_retries=1,
        )
        with patch.dict(
            sys.modules,
            {
                "openai": _fake_openai_module(
                    raw,
                    calls,
                    [],
                    failures=[
                        _FakeProviderError(
                            524,
                            owner_action_required=True,
                            retryable=True,
                            body_retry_after=60,
                        )
                    ],
                )
            },
        ), patch("qount.alpha_agents.llm.time.sleep") as sleeper:
            report = request_agent_report(
                config=config,
                role=_role(),
                task=_task(),
                sources=_source(),
                context={},
            )
        self.assertEqual(report.status, "ok")
        self.assertEqual(len(calls), 2)
        sleeper.assert_called_once_with(60.0)

    def test_incomplete_responses_result_is_blocked(self) -> None:
        raw = json.dumps(
            {
                "status": "ok",
                "summary": "Fixture.",
                "findings": [],
                "proposals": [],
                "risks": [],
            }
        )
        config = AlphaLLMConfig(
            enabled=True,
            base_url=RELAY_STATION_BASE_URL,
            api_key="fixture-secret",
            model=RELAY_STATION_DEFAULT_MODEL,
        )
        with patch.dict(
            sys.modules,
            {
                "openai": _fake_openai_module(
                    raw, [], [], status="incomplete"
                )
            },
        ):
            report = request_agent_report(
                config=config,
                role=_role(),
                task=_task(),
                sources=_source(),
                context={},
            )
        self.assertEqual(report.status, "blocked")
        self.assertIn("llm_response_status_invalid:incomplete", report.risks)

    def test_extra_output_key_is_blocked(self) -> None:
        raw = json.dumps(
            {
                "status": "ok",
                "summary": "Fixture.",
                "findings": [],
                "proposals": [],
                "risks": [],
                "target_weights": {"BTCUSDT": 1.0},
            }
        )
        config = AlphaLLMConfig(
            enabled=True,
            base_url=RELAY_STATION_BASE_URL,
            api_key="fixture-secret",
            model=RELAY_STATION_DEFAULT_MODEL,
        )
        calls: list[dict] = []
        with patch.dict(
            sys.modules,
            {"openai": _fake_openai_module(raw, calls, [])},
        ):
            report = request_agent_report(
                config=config,
                role=_role(),
                task=_task(),
                sources=_source(),
                context={},
            )
        self.assertEqual(report.status, "blocked")
        self.assertIn("llm_payload_keys_not_exact", report.risks)
        self.assertEqual(len(calls), 1)

    def test_zh_cn_contract_rejects_english_narrative(self) -> None:
        raw = json.dumps(
            {
                "status": "ok",
                "summary": "English summary.",
                "findings": ["English finding."],
                "proposals": [],
                "risks": [],
            }
        )
        calls: list[dict] = []
        config = AlphaLLMConfig(
            enabled=True,
            base_url=RELAY_STATION_BASE_URL,
            api_key="fixture-secret",
            model=RELAY_STATION_DEFAULT_MODEL,
        )
        with patch.dict(
            sys.modules,
            {"openai": _fake_openai_module(raw, calls, [])},
        ):
            report = request_agent_report(
                config=config,
                role=_role(),
                task=_task(),
                sources=_source(),
                context={},
                output_language="zh-CN",
            )
        self.assertEqual(report.status, "blocked")
        self.assertIn("llm_payload_language_invalid", report.risks)
        self.assertIn("简体中文", calls[0]["input"][0]["content"])

    def test_zh_cn_contract_accepts_chinese_narrative(self) -> None:
        raw = json.dumps(
            {
                "status": "ok",
                "summary": "已完成一手来源复核。",
                "findings": ["该来源包含明确时间戳。"],
                "proposals": ["使用确定性程序复核时间戳。"],
                "risks": ["当前样本不能证明存在超额收益。"],
            },
            ensure_ascii=False,
        )
        config = AlphaLLMConfig(
            enabled=True,
            base_url=RELAY_STATION_BASE_URL,
            api_key="fixture-secret",
            model=RELAY_STATION_DEFAULT_MODEL,
        )
        with patch.dict(
            sys.modules,
            {"openai": _fake_openai_module(raw, [], [])},
        ):
            report = request_agent_report(
                config=config,
                role=_role(),
                task=_task(),
                sources=_source(),
                context={},
                output_language="zh-CN",
            )
        self.assertEqual(report.status, "ok")
        self.assertIn("来源复核", report.summary)

    def test_oversized_context_is_blocked_before_network_call(self) -> None:
        config = AlphaLLMConfig(
            enabled=True,
            base_url=RELAY_STATION_BASE_URL,
            api_key="fixture-secret",
            model=RELAY_STATION_DEFAULT_MODEL,
            max_input_chars=500,
        )
        calls: list[dict] = []
        with patch.dict(
            sys.modules,
            {"openai": _fake_openai_module("{}", calls, [])},
        ):
            report = request_agent_report(
                config=config,
                role=_role(),
                task=_task(),
                sources=_source(),
                context={"text": "x" * 10_000},
            )
        self.assertEqual(report.status, "blocked")
        self.assertIn("llm_input_too_large", report.risks)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
