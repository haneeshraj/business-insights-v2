"""Tests for the steps that ask a model about the answers the rules aren't sure of."""

import io
from dataclasses import replace
from typing import Any

import pytest
from PIL import Image

from bi2.core.asking import Agreed, Ask, Choice, Decision, Generated, Picked, Prompt, YesNo
from bi2.core.errors import ModelUnavailable
from bi2.core.models import (
    Box,
    ContactPage,
    Contacts,
    Evidence,
    LogoCandidate,
    PageInfo,
    PageKind,
    PageMeta,
    StructuredData,
)
from bi2.resolvers.asking import NO_MODEL, NONE
from bi2.resolvers.cascade import Resolved
from bi2.resolvers.email import email_by_decider
from bi2.resolvers.images import number_boxes
from bi2.resolvers.logo import logo_by_decider, resolve_logo
from bi2.resolvers.name import name_by_decider, name_by_llm
from bi2.resolvers.phone import phone_by_decider
from tests.fakes import MemoryFiles, fake_context
from tests.resolvers.images import picture, screenshot_with_logo

URL = "https://example-cafe.ca/"


class FakeDecider:
    """Answers each question with the answer it's given, and keeps what it was asked."""

    name = "fake"

    def __init__(self, **answers: Any) -> None:
        self.answers = answers
        self.asked: list[Ask] = []

    async def decide(self, ask: Ask) -> Decision:
        self.asked.append(ask)
        return Decision(answers=self.answers, model="fake-1")


class FakeLlm:
    name = "fake-llm"

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    async def generate(self, prompt: Prompt) -> Generated:
        return Generated(data=self.data, model="fake-llm-1")


def _pick(choice: str, probability: float) -> Picked:
    return Picked(choice=choice, confidence=probability, probabilities={choice: probability})


def _logo(number: int, x: float, **fields: Any) -> LogoCandidate:
    box = Box(x=x, y=10, width=160, height=60)
    return LogoCandidate(number=number, kind="img", url=f"{URL}logo{number}.png", box=box, **fields)


async def _logo_context(decider: FakeDecider) -> Any:
    files = MemoryFiles()
    await files.save("example-cafe.ca/screenshot.jpg", screenshot_with_logo(20, 10, 160, 60))
    downloads = {f"{URL}logo{n}.png": picture(160, 60) for n in (1, 2)}
    return replace(fake_context(downloads=downloads, files=files), decider=decider)


EV = Evidence(
    page=PageInfo(url=URL, final_url=URL, kind=PageKind.OWN_WEBSITE),
    meta=PageMeta(title="Example Cafe | Coffee"),
    logo_candidates=(_logo(1, 20, points=6), _logo(2, 400, points=5)),
    screenshot_file="example-cafe.ca/screenshot.jpg",
)


async def test_a_model_that_agrees_with_the_rules_makes_the_logo_sure() -> None:
    decider = FakeDecider(logo=_pick("1", 0.9))
    answer = await logo_by_decider(EV, await _logo_context(decider))
    assert isinstance(answer, Resolved)
    assert answer.value.url == f"{URL}logo1.png"
    assert answer.confidence > 0.85
    asked = decider.asked[0]
    assert set(asked.images) == {"screenshot"}
    question = asked.questions["logo"]
    assert isinstance(question, Choice)
    assert list(question.options) == ["1", "2", NONE]


async def test_a_logo_a_model_picks_over_the_rules_needs_a_high_probability() -> None:
    unsure = await logo_by_decider(EV, await _logo_context(FakeDecider(logo=_pick("2", 0.7))))
    sure = await logo_by_decider(EV, await _logo_context(FakeDecider(logo=_pick("2", 0.95))))
    assert isinstance(unsure, Resolved)
    assert isinstance(sure, Resolved)
    assert unsure.value.url == sure.value.url == f"{URL}logo2.png"
    assert unsure.confidence < 0.85 <= sure.confidence


async def test_a_model_that_sees_no_logo_passes_and_the_rules_answer_stands() -> None:
    ctx = await _logo_context(FakeDecider(logo=_pick(NONE, 0.8)))
    result = await resolve_logo(EV, ctx)
    assert result.value is not None
    assert result.value.url == f"{URL}logo1.png"
    assert "no box is the logo" in result.steps[1].detail


async def test_without_a_model_the_ai_steps_pass() -> None:
    no_model = replace(await _logo_context(FakeDecider()), decider=None)
    result = await resolve_logo(EV, no_model)
    assert [step.detail for step in result.steps[1:]] == [
        NO_MODEL,
        "no second model to ask: it takes both a Jev and a Gemini key",
    ]


def test_boxes_in_the_same_place_are_numbered_once() -> None:
    boxes = [(1, Box(x=10, y=10, width=100, height=40)), (2, Box(x=12, y=11, width=98, height=38))]
    image, drawn = number_boxes(screenshot_with_logo(10, 10, 100, 40), boxes)
    assert drawn == [1]
    with Image.open(io.BytesIO(image)) as opened:
        assert opened.format == "JPEG"


NAMED = Evidence(
    page=PageInfo(url=URL, final_url=URL, kind=PageKind.OWN_WEBSITE),
    meta=PageMeta(title="Coffee and Pastries | Example Cafe", site_name="Example Cafe Shop"),
    structured=StructuredData(name="Example Cafe"),
)


async def test_a_model_picks_the_name_from_the_ones_the_page_gives() -> None:
    decider = FakeDecider(name=_pick("Example Cafe", 0.8))
    answer = await name_by_decider(NAMED, replace(fake_context(), decider=decider))
    assert answer.value == "Example Cafe"  # type: ignore[union-attr]
    question = decider.asked[0].questions["name"]
    assert isinstance(question, Choice)
    assert "Example Cafe" in question.options
    assert NONE in question.options


async def test_a_name_an_llm_reads_must_be_in_the_evidence() -> None:
    quoted = FakeLlm({"name": "Example Cafe", "quote": "Example Cafe Shop", "from_image": False})
    answer = await name_by_llm(NAMED, replace(fake_context(), llm=quoted))
    assert answer.value == "Example Cafe"  # type: ignore[union-attr]
    made_up = FakeLlm({"name": "Other Bakery", "quote": "Other Bakery", "from_image": False})
    with pytest.raises(ModelUnavailable, match="doesn't show"):
        await name_by_llm(NAMED, replace(fake_context(), llm=made_up))


def _contacts(
    phones: dict[str, tuple[str, ...]] | None = None,
    emails: dict[str, tuple[str, ...]] | None = None,
) -> Contacts:
    phones, emails = phones or {}, emails or {}
    return Contacts(
        phones=tuple(phones), phone_places=phones, emails=tuple(emails), email_places=emails
    )


async def test_one_number_is_confirmed_by_a_yes_or_no_question() -> None:
    ev = Evidence(
        page=PageInfo(url=URL, final_url=URL, kind=PageKind.OWN_WEBSITE),
        contact_page=ContactPage(
            url=f"{URL}contact", contacts=_contacts({"+14165550123": ("main text",)})
        ),
    )
    doubtful = FakeDecider(phone=Agreed(probability=0.7))
    answer = await phone_by_decider(ev, replace(fake_context(), decider=doubtful))
    assert isinstance(doubtful.asked[0].questions["phone"], YesNo)
    assert answer.confidence == 0.75  # type: ignore[union-attr]
    no = await phone_by_decider(
        ev, replace(fake_context(), decider=FakeDecider(phone=Agreed(probability=0.2)))
    )
    assert "doubts" in no.reason  # type: ignore[union-attr]


async def test_a_model_judges_which_address_is_the_general_one() -> None:
    contacts = _contacts(
        emails={
            "press@example-cafe.ca": ("footer",),
            "hello@example-cafe.ca": ("footer",),
            "sam@example-cafe.ca": ("main text",),
        }
    )
    ev = Evidence(
        page=PageInfo(url=URL, final_url=URL, kind=PageKind.OWN_WEBSITE), contacts=contacts
    )
    decider = FakeDecider(email=_pick("hello@example-cafe.ca", 0.9))
    answer = await email_by_decider(ev, replace(fake_context(), decider=decider))
    assert answer.value == "hello@example-cafe.ca"  # type: ignore[union-attr]
    question = decider.asked[0].questions["email"]
    assert isinstance(question, Choice)
    assert "press@example-cafe.ca" not in question.options  # one purpose, never the answer
