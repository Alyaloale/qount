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


class _FakeCompletions:
    def __init__(self, raw: str, calls: list[dict]) -> None:
        self.raw = raw
        self.calls = calls

    def create(self, **kwargs):
        self.calls.append(kwargs)
        message = types.SimpleNamespace(content=self.raw)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


def _fake_openai_module(raw: str, calls: list[dict], clients: list[dict]):
    class FakeHttpClient:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class FakeOpenAI:
        def __init__(self, **kwargs) -> None:
            clients.append(kwargs)
            self.chat = types.SimpleNamespace(
                completions=_FakeCompletions(raw, calls)
            )

        def close(self) -> None:
            return None

    return types.SimpleNamespace(
        DefaultHttpxClient=FakeHttpClient,
        OpenAI=FakeOpenAI,
    )


class RelayStationLLMTests(unittest.TestCase):
    def test_env_defaults_to_relay_station_chatgpt_with_single_request(self) -> None:
        with patch("qount.alpha_agents.llm._load_local_alpha_env"), patch.dict(
            os.environ, {}, clear=True
        ):
            config = AlphaLLMConfig.from_env()
        self.assertEqual(config.base_url, RELAY_STATION_BASE_URL)
        self.assertEqual(config.model, RELAY_STATION_DEFAULT_MODEL)
        self.assertEqual(config.model, "gpt-5.6-terra")
        self.assertEqual(config.max_concurrency, 1)
        self.assertEqual(config.max_retries, 0)
        self.assertEqual(config.validate(), ())

    def test_valid_fixture_uses_strict_json_without_tools(self) -> None:
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
        self.assertEqual(calls[0]["response_format"], {"type": "json_object"})
        self.assertEqual(clients[0]["max_retries"], 0)
        self.assertFalse(clients[0]["http_client"].kwargs["trust_env"])

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
            )
        self.assertEqual(report.status, "blocked")
        self.assertIn("llm_payload_keys_not_exact", report.risks)

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
