"""Tests for the cascade every field follows."""

from bi2.core.context import RunContext
from bi2.core.errors import FetchError
from bi2.core.models import Evidence, PageInfo, PageKind, Status, StepOutcome
from bi2.core.routing import Group, Routing
from bi2.resolvers.cascade import Escalate, Resolved, not_built_yet, run_cascade
from tests.fakes import fake_context

URL = "https://example-cafe.ca/"
EV = Evidence(page=PageInfo(url=URL, final_url=URL, kind=PageKind.OWN_WEBSITE))


async def sure(ev: Evidence, ctx: RunContext) -> Resolved[str] | Escalate:
    return Resolved("Example Cafe", 0.9, "structured data", ("structured data: Example Cafe",))


async def unsure(ev: Evidence, ctx: RunContext) -> Resolved[str] | Escalate:
    return Resolved("Example", 0.6, "part of the title")


async def nothing(ev: Evidence, ctx: RunContext) -> Resolved[str] | Escalate:
    return Escalate("no names on the page")


async def broken(ev: Evidence, ctx: RunContext) -> Resolved[str] | Escalate:
    raise FetchError("the search service is down")


async def test_the_first_sure_answer_is_kept_and_later_steps_dont_run() -> None:
    result = await run_cascade("company_name", [nothing, sure, unsure], EV, fake_context())
    assert result.status is Status.OK
    assert (result.value, result.confidence, result.source) == (
        "Example Cafe",
        0.9,
        "structured data",
    )
    assert result.evidence == ("structured data: Example Cafe",)
    assert [(s.step, s.outcome) for s in result.steps] == [
        ("nothing", StepOutcome.ESCALATED),
        ("sure", StepOutcome.RESOLVED),
    ]


async def test_without_a_sure_answer_the_surest_one_needs_review() -> None:
    result = await run_cascade("company_name", [unsure, nothing], EV, fake_context())
    assert result.status is Status.NEEDS_REVIEW
    assert (result.value, result.confidence) == ("Example", 0.6)
    assert result.steps[0].detail == "not sure enough: 0.60, below 0.85"


async def test_with_no_answer_the_field_is_not_found_and_never_guessed() -> None:
    result = await run_cascade("company_name", [nothing], EV, fake_context())
    assert result.status is Status.NOT_FOUND
    assert result.value is None


async def test_failures_are_recorded_and_the_next_step_still_runs() -> None:
    assert (await run_cascade("company_name", [broken], EV, fake_context())).status is Status.ERROR
    recovered = await run_cascade("company_name", [broken, sure], EV, fake_context())
    assert recovered.status is Status.OK
    assert recovered.steps[0].outcome is StepOutcome.FAILED
    assert recovered.steps[0].detail == "the search service is down"
    mixed = await run_cascade("company_name", [broken, nothing], EV, fake_context())
    assert mixed.status is Status.NOT_FOUND


async def test_the_threshold_comes_from_the_settings() -> None:
    result = await run_cascade("company_name", [unsure], EV, fake_context(accept=0.5))
    assert result.status is Status.OK


async def test_a_learned_decision_overrides_the_threshold_both_ways() -> None:
    routing = Routing(
        groups={
            "company_name": (
                Group(confidence=0.9, checked=6, right=3),
                Group(confidence=0.6, checked=8, right=8),
            )
        }
    )
    doubted = await run_cascade("company_name", [sure], EV, fake_context(routing=routing))
    assert doubted.status is Status.NEEDS_REVIEW
    assert doubted.steps[0].detail == "answers like this were right only 3 of 6 times"
    trusted = await run_cascade("company_name", [unsure], EV, fake_context(routing=routing))
    assert trusted.status is Status.OK
    assert trusted.steps[0].detail == "answers like this were right 8 of 8 times"


def test_fields_not_built_yet_say_so() -> None:
    result = not_built_yet()
    assert result.status is Status.NOT_FOUND
    assert result.steps[0].detail == "this field isn't built yet"
