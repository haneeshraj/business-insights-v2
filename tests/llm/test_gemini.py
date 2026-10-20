"""Tests for Gemini as the LanguageModel, answered without the network."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from bi2.core.asking import Prompt
from bi2.core.errors import BudgetUsedUp, ModelUnavailable
from bi2.llm.gemini import Gemini, media_type
from bi2.llm.limits import FreeTier
from tests.resolvers.images import picture

PROMPT = Prompt(
    task="test",
    version="1",
    instructions="Answer.",
    evidence="Example Cafe",
    answer_schema={"type": "object"},
    images=(picture(10, 10),),
)


def _ok(answer: dict[str, Any], model: str = "gemini-3.6-flash") -> httpx.Response:
    candidate = {"content": {"parts": [{"text": json.dumps(answer)}]}, "finishReason": "STOP"}
    usage = {"promptTokenCount": 1000, "candidatesTokenCount": 10, "thoughtsTokenCount": 5}
    return httpx.Response(
        200, json={"candidates": [candidate], "usageMetadata": usage, "modelVersion": model}
    )


def _quota(*, per_day: bool) -> httpx.Response:
    quota = "GenerateRequestsPerDayPerProjectPerModel-FreeTier" if per_day else "PerMinute"
    details = [{"violations": [{"quotaId": quota}]}, {"retryDelay": "1s"}]
    return httpx.Response(429, json={"error": {"message": "quota", "details": details}})


def _gemini(answer: Callable[[httpx.Request], httpx.Response], **kwargs: Any) -> Gemini:
    return Gemini("key", limits=FreeTier(), transport=httpx.MockTransport(answer), **kwargs)


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_wait(seconds: float) -> None:
        return None

    monkeypatch.setattr("bi2.llm.gemini.asyncio.sleep", no_wait)


async def test_an_answer_is_json_with_its_cost() -> None:
    seen: list[dict[str, Any]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        assert request.headers["x-goog-api-key"] == "key"
        return _ok({"name": "Example Cafe"})

    async with _gemini(answer) as gemini:
        generated = await gemini.generate(PROMPT)
    assert generated.data == {"name": "Example Cafe"}
    assert generated.model == "gemini-3.6-flash"
    assert (generated.cost.input_tokens, generated.cost.output_tokens) == (1000, 15)
    assert generated.cost.usd > 0
    config = seen[0]["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["thinkingConfig"] == {"thinkingLevel": "minimal"}
    assert seen[0]["contents"][0]["parts"][1]["inline_data"]["mime_type"] == "image/png"


async def test_a_used_up_day_moves_to_the_backup_model() -> None:
    asked: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path)
        return _quota(per_day=True) if "3.5-flash:" in request.url.path else _ok({"a": 1})

    async with _gemini(answer) as gemini:
        assert (await gemini.generate(PROMPT)).data == {"a": 1}
        await gemini.generate(PROMPT)  # the used-up model isn't asked again today
    assert sum("3.5-flash:" in path for path in asked) == 1


async def test_every_model_used_up_is_a_used_up_budget() -> None:
    async with _gemini(lambda request: _quota(per_day=True)) as gemini:
        with pytest.raises(BudgetUsedUp):
            await gemini.generate(PROMPT)


async def test_a_busy_model_is_asked_again() -> None:
    answers = iter([httpx.Response(503), _quota(per_day=False), _ok({"a": 1})])
    async with _gemini(lambda request: next(answers), backup=None) as gemini:
        assert (await gemini.generate(PROMPT)).data == {"a": 1}


async def test_an_answer_cut_off_or_refused_is_unavailable() -> None:
    candidate = {"content": {"parts": [{"text": "{"}]}, "finishReason": "MAX_TOKENS"}
    cut = httpx.Response(200, json={"candidates": [candidate]})
    async with _gemini(lambda request: cut, backup=None) as gemini:
        with pytest.raises(ModelUnavailable, match="MAX_TOKENS"):
            await gemini.generate(PROMPT)
    refused = httpx.Response(400, json={"error": {"message": "bad"}})
    async with _gemini(lambda request: refused, backup=None) as gemini:
        with pytest.raises(ModelUnavailable, match="400: bad"):
            await gemini.generate(PROMPT)


def test_only_png_and_jpeg_go_to_a_model() -> None:
    assert media_type(picture(4, 4, "JPEG")) == "image/jpeg"
    with pytest.raises(ValueError, match="PNG and JPEG"):
        media_type(b"GIF89a")
