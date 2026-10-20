"""Tests for sending a site's questions for Jev together."""

import asyncio

import pytest

from bi2.core.asking import Agreed, Answer, Ask, Choice, Decision, Picked, YesNo
from bi2.core.errors import ModelUnavailable
from bi2.core.models import Cost
from bi2.resolvers.fanout import FanOut, combine


def _ask(task: str, question: str) -> Ask:
    return Ask(
        task=task,
        version="1",
        state=f"{task} evidence; see `screenshot`",
        questions={question: YesNo(instructions=f"Is it {task}?")},
        images={"screenshot": b"png"},
    )


class Recording:
    name = "jev"

    def __init__(self, *, down: bool = False) -> None:
        self.asked: list[Ask] = []
        self.down = down

    async def decide(self, ask: Ask) -> Decision:
        self.asked.append(ask)
        if self.down:
            raise ModelUnavailable("down")
        answers: dict[str, Answer] = {name: Agreed(probability=0.9) for name in ask.questions}
        return Decision(answers=answers, model="jev-1", cost=Cost(input_tokens=100, model_calls=1))


def test_asks_combine_into_labeled_sections_with_their_own_images() -> None:
    combined = combine([_ask("name_pick", "name"), _ask("phone_pick", "phone")])
    assert set(combined.questions) == {"0_name_pick__name", "1_phone_pick__phone"}
    assert "[0_name_pick]" in combined.state
    assert "`0_name_pick_screenshot`" in combined.state
    assert set(combined.images) == {"0_name_pick_screenshot", "1_phone_pick_screenshot"}
    question = combined.questions["1_phone_pick__phone"]
    assert question.instructions.startswith("Answer from the [1_phone_pick] section only.")


async def test_questions_asked_together_go_in_one_call() -> None:
    jev = Recording()
    fan_out = FanOut(jev, running=3)

    async def resolver(task: str) -> float:
        try:
            decision = await fan_out.decide(_ask(task, "q"))
            return decision.agreed("q").probability
        finally:
            fan_out.finished()

    async def no_question() -> None:
        fan_out.finished()

    answers = await asyncio.gather(resolver("a"), resolver("b"), no_question())
    assert list(answers[:2]) == [0.9, 0.9]
    assert len(jev.asked) == 1  # the two questions went together
    assert jev.asked[0].task == "fanout"


async def test_a_lone_question_goes_as_it_is_and_failures_reach_every_asker() -> None:
    jev = Recording()
    fan_out = FanOut(jev, running=1)
    await fan_out.decide(_ask("mcc_round_1", "q"))
    assert jev.asked[0].task == "mcc_round_1"
    down = FanOut(Recording(down=True), running=2)
    results = await asyncio.gather(
        down.decide(_ask("a", "q")), down.decide(_ask("b", "q")), return_exceptions=True
    )
    assert all(isinstance(result, ModelUnavailable) for result in results)


def test_choice_options_survive_combining() -> None:
    ask = Ask(
        task="logo_pick",
        version="1",
        state="s",
        questions={"logo": Choice(instructions="Which?", options={"1": "box 1", "none": "none"})},
    )
    combined = combine([ask, _ask("name_pick", "name")])
    question = combined.questions["0_logo_pick__logo"]
    assert isinstance(question, Choice)
    assert list(question.options) == ["1", "none"]
    with pytest.raises(KeyError):
        Decision(answers={"x": Picked(choice="1", confidence=1)}, model="m").agreed(
            "0_logo_pick__logo"
        )
