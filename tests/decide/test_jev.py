"""Tests for Jev as the Decider, answered without the network."""

import io
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from PIL import Image

from bi2.core.asking import Ask, Choice, Levels, Locate, YesNo
from bi2.core.errors import ModelUnavailable
from bi2.decide.jev import Jev, fit_image
from bi2.llm.limits import FreeTier
from tests.resolvers.images import picture

ASK = Ask(
    task="test",
    version="1",
    state="Bellwoods Brewery, a taproom in Toronto",
    questions={
        "mcc": Choice(instructions="Which code?", options={"5813": "Bars", "5812": "Restaurants"}),
        "own": YesNo(instructions="Its own site?", yes="its own", no="a profile"),
        "trust": Levels(instructions="How sure?", levels=("low", "high")),
    },
)
ANSWERS = {
    "model": "jev-1.13.0",
    "answers": {
        "mcc": {
            "type": "choice",
            "choice": "5813",
            "confidence": 0.68,
            "probabilities": {"5813": 0.9, "5812": 0.1},
        },
        "own": {"type": "noul", "noul": 0.8},
        "trust": {
            "type": "score",
            "score": 0.7,
            "confidence": 0.4,
            "probabilities": {"0": 0.3, "1": 0.7},
        },
    },
    "usage": {"input_tokens": 400, "output_tokens": 50},
}


def _jev(answer: Callable[[httpx.Request], httpx.Response]) -> Jev:
    return Jev("key", limits=FreeTier(), transport=httpx.MockTransport(answer))


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_wait(seconds: float) -> None:
        return None

    monkeypatch.setattr("bi2.decide.jev.asyncio.sleep", no_wait)


async def test_every_question_is_asked_in_one_call() -> None:
    seen: list[dict[str, Any]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer key"
        assert "typesafe-danger-zone-images" not in request.headers
        return httpx.Response(200, json=ANSWERS)

    async with _jev(answer) as jev:
        decision = await jev.decide(ASK)
    questions = seen[0]["questions"]
    assert questions["own"] == {
        "type": "noul",
        "instructions": "Its own site?",
        "criteria": {"true": "its own", "false": "a profile"},
    }
    assert questions["trust"]["criteria"] == ["low", "high"]
    assert decision.picked("mcc").choice == "5813"
    assert decision.picked("mcc").probability("5812") == 0.1
    assert decision.agreed("own").probability == 0.8
    assert decision.model == "jev-1.13.0"
    assert decision.cost.input_tokens == 400


async def test_images_are_sent_as_named_parts_of_the_state() -> None:
    seen: list[dict[str, Any]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        assert request.headers["typesafe-danger-zone-images"] == "true"
        box = {"top": 0.1, "left": 0.2, "bottom": 0.3, "right": 0.4}
        logo = {"type": "box", "box": box, "confidence": None}
        return httpx.Response(200, json={"model": "jev", "answers": {"logo": logo}})

    ask = Ask(
        task="t",
        version="1",
        state="The page",
        images={"screenshot": picture(40, 30)},
        questions={"logo": Locate(instructions="Where is the logo in `screenshot`?")},
    )
    async with _jev(answer) as jev:
        found = (await jev.decide(ask)).found("logo")
    body = seen[0]
    reference = body["state"]["screenshot"]
    assert body["state"]["evidence"] == "The page"
    assert body["assets"][reference]["format"] == "png"
    assert (found.top, found.right) == (0.1, 0.4)


async def test_a_busy_jev_is_asked_again_and_a_refusal_is_unavailable() -> None:
    answers = iter([httpx.Response(529), httpx.Response(200, json=ANSWERS)])
    async with _jev(lambda request: next(answers)) as jev:
        assert (await jev.decide(ASK)).picked("mcc").choice == "5813"
    async with _jev(lambda request: httpx.Response(422, text="bad")) as jev:
        with pytest.raises(ModelUnavailable, match="422"):
            await jev.decide(ASK)


def test_images_are_fitted_to_jevs_limits() -> None:
    with Image.open(io.BytesIO(fit_image(picture(100, 50)))) as small:
        assert small.size == (280, 280)
    with Image.open(io.BytesIO(fit_image(picture(3000, 1000, "JPEG")))) as large:
        assert large.size == (1568, 523)
    with pytest.raises(ValueError, match="not an image"):
        fit_image(b"nope")
