"""Tests for the merchant category code, with a stand-in for Jev."""

from dataclasses import replace

from bi2.core.asking import Answer, Ask, Decision, Picked
from bi2.core.models import Evidence, PageInfo, PageKind, PageMeta, StructuredData, TextRegions
from bi2.resolvers.asking import NONE
from bi2.resolvers.mcc import chain_codes, hinted_codes, mcc_codes, resolve_mcc
from tests.fakes import fake_context

URL = "https://www.bellwoodsbrewery.com/"
EV = Evidence(
    page=PageInfo(url=URL, final_url=URL, kind=PageKind.OWN_WEBSITE),
    meta=PageMeta(title="Bellwoods Brewery | Toronto taproom and bottle shop"),
    structured=StructuredData(types=("Brewery",)),
    text=TextRegions(main="Craft beer brewed in Toronto. Visit our taproom."),
)


class Rounds:
    """Answers the first round with the given picks, and the final round with the given code."""

    name = "jev"

    def __init__(self, low: str, high: str, final: str, probability: float) -> None:
        self.low, self.high, self.final, self.probability = low, high, final, probability
        self.asked: list[Ask] = []

    async def decide(self, ask: Ask) -> Decision:
        self.asked.append(ask)
        if ask.task == "mcc_round_1":
            answers: dict[str, Answer] = {
                "low": Picked(choice=self.low, confidence=0.9, probabilities={self.low: 0.9}),
                "high": Picked(choice=self.high, confidence=0.9, probabilities={self.high: 0.8}),
            }
        else:
            # Asked again with the options reversed, it's surer of the same pick.
            p = 0.7 if ask.task == "mcc_final_reversed" else self.probability
            answers = {
                "mcc": Picked(choice=self.final, confidence=p, probabilities={self.final: p})
            }
        return Decision(answers=answers, model="jev-test")


async def test_the_code_is_picked_in_two_rounds() -> None:
    jev = Rounds(low=NONE, high="5813", final="5813", probability=0.9)
    result = await resolve_mcc(EV, replace(fake_context(), decider=jev))
    assert result.value is not None
    assert (result.value.code, result.status.value) == ("5813", "ok")
    first = jev.asked[0].questions
    assert set(first) == {"low", "high"}
    assert all(len(q.options) <= 255 for q in first.values())  # type: ignore[union-attr]
    assert not any("3000" <= code <= "3999" for q in first.values() for code in q.options)  # type: ignore[union-attr]


async def test_an_unsure_pick_is_asked_again_with_the_options_reversed() -> None:
    jev = Rounds(low="5921", high="5813", final="5813", probability=0.4)
    result = await resolve_mcc(EV, replace(fake_context(), decider=jev))
    assert [ask.task for ask in jev.asked] == ["mcc_round_1", "mcc_final", "mcc_final_reversed"]
    first_order = list(jev.asked[1].questions["mcc"].options)  # type: ignore[union-attr]
    assert list(jev.asked[2].questions["mcc"].options) == first_order[::-1]  # type: ignore[union-attr]
    assert result.status.value == "ok"  # the same pick both ways


def test_schema_types_hint_codes_and_chains_get_their_own() -> None:
    assert hinted_codes(EV) == ("5813", "5921")
    air = Evidence(
        page=PageInfo(url="https://www.aircanada.com/", kind=PageKind.OWN_WEBSITE),
        meta=PageMeta(site_name="Air Canada"),
    )
    assert chain_codes(air) == ["3009"]
    assert mcc_codes()["3009"] == "Air Canada"


async def test_a_chain_is_filed_under_its_own_code() -> None:
    air = Evidence(
        page=PageInfo(url="https://www.aircanada.com/", kind=PageKind.OWN_WEBSITE),
        meta=PageMeta(site_name="Air Canada", title="Air Canada | Book flights"),
    )
    jev = Rounds(low="4511", high=NONE, final="4511", probability=0.9)
    result = await resolve_mcc(air, replace(fake_context(), decider=jev))
    assert result.value is not None
    assert result.value.code == "3009"
    assert "3009" in jev.asked[1].questions["mcc"].options  # type: ignore[union-attr]


class Decisive:
    """A first round that settles the code: one list sure of it, the other sure of none."""

    name = "jev"

    def __init__(self) -> None:
        self.asked: list[str] = []

    async def decide(self, ask: Ask) -> Decision:
        self.asked.append(ask.task)
        answers: dict[str, Answer] = {
            "low": Picked(choice=NONE, confidence=0.95, probabilities={NONE: 0.95}),
            "high": Picked(choice="5813", confidence=0.95, probabilities={"5813": 0.95}),
        }
        return Decision(answers=answers, model="jev-test")


async def test_a_decisive_first_round_needs_no_final_round() -> None:
    jev = Decisive()
    result = await resolve_mcc(EV, replace(fake_context(), decider=jev))
    assert jev.asked == ["mcc_round_1"]
    assert result.value is not None
    assert (result.value.code, result.status.value) == ("5813", "ok")


async def test_a_blocked_page_is_judged_by_wikidatas_description() -> None:
    from bi2.core.models import KnownBusiness

    known = KnownBusiness(item="Q1867036", name="Loblaws", description="Canadian supermarket chain")
    blocked = Evidence(
        page=PageInfo(url="https://www.loblaws.ca/"), unreadable="a bot check", known=known
    )
    jev = Rounds(low="5411", high=NONE, final="5411", probability=0.95)
    result = await resolve_mcc(blocked, replace(fake_context(), decider=jev))
    assert result.value is not None
    assert result.value.code == "5411"
    assert "Canadian supermarket chain" in jev.asked[0].state
