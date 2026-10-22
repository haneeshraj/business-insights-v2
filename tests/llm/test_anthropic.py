"""Tests for Claude as the LanguageModel, answered without the network."""

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx
import pytest

from bi2.core.asking import Prompt
from bi2.core.errors import BudgetUsedUp, ModelUnavailable
from bi2.core.providers import ModelRef, providers
from bi2.llm.anthropic import Anthropic
from bi2.llm.limits import FreeTier
from bi2.llm.registry import model_info
from tests.resolvers.images import picture

SCHEMA = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
PROMPT = Prompt(
    task="test",
    version="1",
    instructions="Answer.",
    evidence="Example Cafe",
    answer_schema=SCHEMA,
    images=(picture(10, 10),),
)


def _ok(answer: dict[str, Any]) -> httpx.Response:
    content = [{"type": "tool_use", "id": "t1", "name": "answer", "input": answer}]
    usage = {"input_tokens": 1000, "output_tokens": 20, "cache_read_input_tokens": 0}
    body = {
        "content": content,
        "usage": usage,
        "model": "claude-haiku-5-5",
        "stop_reason": "tool_use",
    }
    return httpx.Response(200, json=body)


def _claude(answer: Callable[[httpx.Request], httpx.Response]) -> Anthropic:
    return Anthropic(
        "sk-ant",
        provider=providers()["anthropic"],
        info=model_info(ModelRef("anthropic", "claude-haiku-5-5")),
        limits=FreeTier(),
        transport=httpx.MockTransport(answer),
    )


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_wait(seconds: float) -> None:
        return None

    monkeypatch.setattr("bi2.llm.anthropic.asyncio.sleep", no_wait)


async def test_the_answer_is_the_input_of_the_one_tool_claude_must_call() -> None:
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok({"name": "Example Cafe"})

    async with _claude(answer) as claude:
        generated = await claude.generate(PROMPT)
    assert generated.data == {"name": "Example Cafe"}
    assert generated.cost.usd == Decimal("0.00011")  # 1,000 in at $0.10, 20 out at $0.50
    request = seen[0]
    assert str(request.url) == "https://api.anthropic.com/v1/messages"
    assert request.headers["x-api-key"] == "sk-ant"
    assert request.headers["anthropic-version"] == "2023-06-01"
    body = json.loads(request.content)
    assert body["system"] == "Answer."
    assert body["tools"][0]["input_schema"] == SCHEMA
    assert body["tool_choice"] == {"type": "tool", "name": "answer"}
    content = body["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "Example Cafe"}
    assert content[1]["source"]["media_type"] == "image/png"


async def test_an_overloaded_api_is_asked_again_and_used_up_credit_is_a_budget() -> None:
    calls = 0

    def overloaded_once(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                529, json={"error": {"type": "overloaded_error", "message": "Overloaded"}}
            )
        return _ok({"name": "x"})

    async with _claude(overloaded_once) as claude:
        assert (await claude.generate(PROMPT)).data == {"name": "x"}
    assert calls == 2

    def no_credit(request: httpx.Request) -> httpx.Response:
        message = "Your credit balance is too low to access the Anthropic API."
        return httpx.Response(
            400, json={"error": {"type": "invalid_request_error", "message": message}}
        )

    async with _claude(no_credit) as claude:
        with pytest.raises(BudgetUsedUp):
            await claude.generate(PROMPT)


async def test_an_answer_cut_off_before_the_tool_call_fails() -> None:
    def cut_off(request: httpx.Request) -> httpx.Response:
        body = {
            "content": [{"type": "text", "text": "Let me"}],
            "stop_reason": "max_tokens",
            "usage": {},
        }
        return httpx.Response(200, json=body)

    async with _claude(cut_off) as claude:
        with pytest.raises(ModelUnavailable, match="ran out of output tokens"):
            await claude.generate(PROMPT)


async def test_the_models_a_key_can_use_are_listed() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(
            200, json={"data": [{"id": "claude-haiku-5-5"}, {"id": "claude-opus-5-5"}]}
        )

    async with _claude(answer) as claude:
        assert await claude.models() == ["claude-haiku-5-5", "claude-opus-5-5"]
