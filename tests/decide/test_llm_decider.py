"""Tests for an LLM standing in for Jev, and for a Decider with a backup."""

from typing import Any

import pytest

from bi2.core.asking import Ask, Choice, Decision, Generated, Locate, Picked, Prompt, YesNo
from bi2.core.errors import ModelUnavailable
from bi2.decide.llm import LlmDecider, WithBackup

ASK = Ask(
    task="t",
    version="1",
    state="Bellwoods Brewery",
    images={"screenshot": b"\x89PNG\r\n\x1a\n"},
    questions={
        "mcc": Choice(
            instructions="Which code?",
            options={"5813": "Bars", "5812": "Restaurants", "5921": "Stores"},
        ),
        "own": YesNo(instructions="Its own site?"),
        "logo": Locate(instructions="Where's the logo?"),
    },
)


class FakeModel:
    name = "gemini"

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.prompts: list[Prompt] = []

    async def generate(self, prompt: Prompt) -> Generated:
        self.prompts.append(prompt)
        return Generated(data=self.data, model="gemini-test")


async def test_the_llms_answers_are_read_as_typed_answers() -> None:
    model = FakeModel(
        {
            "mcc": {"answer": "5813", "confidence": 0.8},
            "own": {"answer": False, "confidence": 0.9},
            "logo": {"answer": [100, 200, 300, 400], "confidence": 0.7},
        }
    )
    decision = await LlmDecider(model).decide(ASK)
    picked = decision.picked("mcc")
    assert picked.choice == "5813"
    assert picked.probability("5812") == pytest.approx(0.1)
    assert decision.agreed("own").probability == pytest.approx(0.1)
    found = decision.found("logo")
    assert (found.top, found.left, found.bottom, found.right) == (0.1, 0.2, 0.3, 0.4)
    prompt = model.prompts[0]
    mcc = prompt.answer_schema["properties"]["mcc"]["properties"]["answer"]
    assert mcc["enum"] == ["5813", "5812", "5921"]
    assert "Image `screenshot` is attached." in prompt.evidence
    assert len(prompt.images) == 1


async def test_an_answer_outside_the_options_is_unavailable() -> None:
    model = FakeModel(
        {
            "mcc": {"answer": "9999", "confidence": 1},
            "own": {"answer": True, "confidence": 1},
            "logo": {"answer": [0, 0, 1, 1], "confidence": 1},
        }
    )
    with pytest.raises(ModelUnavailable, match="isn't one of the options"):
        await LlmDecider(model).decide(ASK)


class Down:
    name = "jev"

    async def decide(self, ask: Ask) -> Decision:
        raise ModelUnavailable("down")


class Up:
    name = "gemini"

    async def decide(self, ask: Ask) -> Decision:
        return Decision(answers={"mcc": Picked(choice="5813", confidence=0.5)}, model="backup")


async def test_the_backup_answers_when_the_first_cant() -> None:
    assert (await WithBackup(Down(), Up()).decide(ASK)).model == "backup"
