"""Tests for OpenAI-compatible providers as the LanguageModel, answered without the network."""

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx
import pytest

from bi2.core.asking import Prompt
from bi2.core.errors import BudgetUsedUp, ModelUnavailable
from bi2.core.providers import ModelRef, providers
from bi2.llm.limits import FreeTier
from bi2.llm.openai_compatible import OpenAICompatible
from bi2.llm.registry import model_info
from tests.resolvers.images import picture

SCHEMA = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
PROMPT = Prompt(
    task="test", version="1", instructions="Answer.", evidence="Example Cafe", answer_schema=SCHEMA
)


def _ok(answer: dict[str, Any], **extra: Any) -> httpx.Response:
    choice = {"message": {"content": json.dumps(answer)}, "finish_reason": "stop"}
    usage = {"prompt_tokens": 1000, "completion_tokens": 20}
    return httpx.Response(200, json={"choices": [choice], "usage": usage, **extra})


def _model(
    answer: Callable[[httpx.Request], httpx.Response],
    *,
    provider: str = "openai",
    model: str = "gpt-5.4-mini",
    key: str | None = "sk-test",
) -> OpenAICompatible:
    settings = providers()[provider]
    return OpenAICompatible(
        key,
        name=provider,
        provider=settings,
        info=model_info(ModelRef(provider, model)),
        limits=FreeTier(),
        transport=httpx.MockTransport(answer),
    )


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_wait(seconds: float) -> None:
        return None

    monkeypatch.setattr("bi2.llm.openai_compatible.asyncio.sleep", no_wait)


async def test_the_schema_goes_in_the_request_and_the_answer_comes_back_with_its_cost() -> None:
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok({"name": "Example Cafe"}, model="gpt-5.4-mini-2026-08-01")

    async with _model(answer) as model:
        generated = await model.generate(PROMPT)
    assert generated.data == {"name": "Example Cafe"}
    assert generated.model == "gpt-5.4-mini-2026-08-01"
    assert generated.cost.usd == Decimal("0.00084")  # 1,000 in at $0.75, 20 out at $4.50
    request = seen[0]
    assert str(request.url) == "https://api.openai.com/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer sk-test"
    body = json.loads(request.content)
    assert body["model"] == "gpt-5.4-mini"
    assert body["messages"][0] == {"role": "system", "content": "Answer."}
    assert body["messages"][1] == {"role": "user", "content": "Example Cafe"}
    assert body["response_format"]["json_schema"]["schema"] == SCHEMA
    assert body["max_completion_tokens"] >= 1024  # OpenAI's name for the output limit
    assert body["reasoning_effort"] == "minimal"  # from data/models.toml


async def test_images_go_as_data_urls_beside_the_text() -> None:
    bodies: list[dict[str, Any]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return _ok({"name": "x"})

    prompt = PROMPT.model_copy(update={"images": (picture(10, 10),)})
    async with _model(answer) as model:
        await model.generate(prompt)
    content = bodies[0]["messages"][1]["content"]
    assert content[0] == {"type": "text", "text": "Example Cafe"}
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


async def test_a_provider_that_refuses_the_schema_is_asked_more_loosely_and_remembered() -> None:
    bodies: list[dict[str, Any]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if body.get("response_format", {}).get("type") == "json_schema":
            return httpx.Response(
                400, json={"error": {"message": "response_format json_schema is not supported"}}
            )
        return _ok({"name": "Example Cafe"})

    async with _model(answer, provider="mistral", model="mistral-small-latest") as model:
        assert (await model.generate(PROMPT)).data == {"name": "Example Cafe"}
        await model.generate(PROMPT)
    assert [b.get("response_format", {}).get("type") for b in bodies] == [
        "json_schema",
        "json_object",
        "json_object",
    ]
    assert "JSON object matching this schema" in bodies[1]["messages"][0]["content"]
    assert bodies[1]["max_tokens"] >= 1024  # the usual name for the output limit


async def test_a_field_the_model_refuses_is_dropped() -> None:
    bodies: list[dict[str, Any]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "temperature" in body:
            message = "Unsupported value: 'temperature' does not support 0 with this model."
            return httpx.Response(400, json={"error": {"message": message}})
        return _ok({"name": "x"})

    async with _model(answer) as model:
        await model.generate(PROMPT)
    assert "temperature" in bodies[0]
    assert "temperature" not in bodies[1]


async def test_a_used_up_quota_is_a_budget_and_a_busy_minute_is_waited_out() -> None:
    def used_up(request: httpx.Request) -> httpx.Response:
        error = {"message": "You exceeded your current quota", "type": "insufficient_quota"}
        return httpx.Response(429, json={"error": error})

    async with _model(used_up) as model:
        with pytest.raises(BudgetUsedUp):
            await model.generate(PROMPT)

    calls = 0

    def busy_once(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429, headers={"retry-after": "2"}, json={"error": {"message": "rate limit"}}
            )
        return _ok({"name": "x"})

    async with _model(busy_once) as model:
        assert (await model.generate(PROMPT)).data == {"name": "x"}
    assert calls == 2


async def test_failures_say_what_went_wrong() -> None:
    async with _model(
        lambda request: httpx.Response(500, json={"error": {"message": "boom"}})
    ) as model:
        with pytest.raises(ModelUnavailable, match="500"):
            await model.generate(PROMPT)
    async with _model(
        lambda request: httpx.Response(401, json={"error": {"message": "bad key"}})
    ) as model:
        with pytest.raises(ModelUnavailable, match="refused the key"):
            await model.generate(PROMPT)

    def cut_off(request: httpx.Request) -> httpx.Response:
        choice = {"message": {"content": ""}, "finish_reason": "length"}
        return httpx.Response(200, json={"choices": [choice]})

    async with _model(cut_off) as model:
        with pytest.raises(ModelUnavailable, match="ran out of output tokens"):
            await model.generate(PROMPT)
    async with _model(lambda request: _ok({"name": "x"})) as model:
        with pytest.raises(ModelUnavailable, match="needs a Gemini model"):
            await model.generate(PROMPT.model_copy(update={"search": True}))


async def test_a_local_server_takes_no_key_and_lists_its_models() -> None:
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "qwen2.5"}, {"id": "llama3.1:8b"}]})
        return _ok({"name": "x"})

    async with _model(answer, provider="ollama", model="llama3.1:8b", key=None) as model:
        assert await model.models() == ["llama3.1:8b", "qwen2.5"]
        generated = await model.generate(PROMPT)
    assert "Authorization" not in seen[-1].headers
    assert str(seen[-1].url) == "http://localhost:11434/v1/chat/completions"
    assert generated.cost.usd == 0  # an unlisted model's price isn't known
