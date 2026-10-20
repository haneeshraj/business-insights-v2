"""Tests for keeping model answers, and for the call log."""

import json
from pathlib import Path

from bi2.adapters.local.answers import CallLog, KeptDecisions, KeptGenerations, LoggedDecider
from bi2.core.asking import Ask, Choice, Decision, Generated, Picked, Prompt
from bi2.core.models import Cost

ASK = Ask(
    task="t", version="1", state="s", questions={"q": Choice(instructions="i", options={"a": "A"})}
)
PROMPT = Prompt(task="t", version="1", instructions="i", evidence="e", answer_schema={})


class CountingDecider:
    name = "jev"

    def __init__(self) -> None:
        self.calls = 0

    async def decide(self, ask: Ask) -> Decision:
        self.calls += 1
        return Decision(
            answers={"q": Picked(choice="a", confidence=1)},
            model="jev-1",
            cost=Cost(input_tokens=5, model_calls=1),
        )


class CountingModel:
    name = "gemini"

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, prompt: Prompt) -> Generated:
        self.calls += 1
        return Generated(data={"x": 1}, model="g")


async def test_the_same_question_is_answered_from_the_kept_copy(tmp_path: Path) -> None:
    decider = CountingDecider()
    kept = KeptDecisions(decider, tmp_path, model="jev-latest")
    first, again = await kept.decide(ASK), await kept.decide(ASK)
    assert decider.calls == 1
    assert (first.cached, again.cached) == (False, True)
    assert again.cost == first.cost  # a kept answer still says what it cost when asked
    await kept.decide(ASK.model_copy(update={"version": "2"}))  # a new prompt is a new question
    assert decider.calls == 2


async def test_generations_are_kept_too(tmp_path: Path) -> None:
    model = CountingModel()
    kept = KeptGenerations(model, tmp_path)
    await kept.generate(PROMPT)
    assert (await kept.generate(PROMPT)).cached
    assert model.calls == 1


async def test_every_call_is_logged_and_only_new_ones_count_as_spent(tmp_path: Path) -> None:
    log = CallLog(tmp_path / "calls.jsonl")
    decider = LoggedDecider(KeptDecisions(CountingDecider(), tmp_path / "kept"), log)
    await decider.decide(ASK)
    await decider.decide(ASK)
    lines = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]
    assert [line["cached"] for line in lines] == [False, True]
    assert (log.calls, log.kept, log.spent.input_tokens) == (2, 1, 5)
