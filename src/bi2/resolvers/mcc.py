"""The business's merchant category code (MCC): what card networks file its sales under.

v1 matched keywords, so "eat" matched "great" and most sites were told they were restaurants.
v2 asks Jev, which reads the page's own words in any language, to pick from the official code
list, in two rounds:

1. The 319 codes that aren't for one named chain go in two lists, too many for one question,
   and Jev picks the best of each, or none of its list, in one call.
2. Jev then picks among the leaders of both lists, with their descriptions, in a second call.

Codes in 3000 to 3999 name one chain each, like Air Canada's 3009, and card networks file that
chain's sales under them. One joins the final round only when the business's name, as the page
gives it, matches the chain's. The schema.org type the page declares, like BarOrPub, is a free
hint: an answer that agrees with it is surer. When Jev is unsure of its final pick, it's asked
again with the options in the other order; the same pick both ways is sure.
"""

import csv
import io
import re
import tomllib
from functools import cache
from importlib.resources import files
from typing import Final

from bi2.core.asking import Ask, Choice, Decision, Question
from bi2.core.context import RunContext
from bi2.core.errors import ModelUnavailable
from bi2.core.models import Evidence, Mcc, MccResult
from bi2.core.text import fold, names_match
from bi2.evidence.names import name_candidates
from bi2.resolvers.asking import NONE, ask_decider, site_lines
from bi2.resolvers.cascade import Escalate, Resolved, run_cascade

_VERSION: Final = "2"
_QUESTION: Final = (
    "Which merchant category code fits the main business this website is for: what it sells "
    "or does for its own customers? Judge by the business itself, not by the products of "
    "other companies it mentions, its job ads, or the website's own technology."
)
_SPLIT: Final = "5800"  # the two lists of the first round: codes below this, and the rest
_LEADERS: Final = 3  # from each list, into the final round
_MOST_TEXT: Final = 1200  # characters of the page's main text in the state


@cache
def mcc_codes() -> dict[str, str]:
    """Every code and its official description, from data/mcc_codes.csv."""
    text = files("bi2.data").joinpath("mcc_codes.csv").read_text(encoding="utf-8")
    return {row["MCC"]: row["Description"].strip() for row in csv.DictReader(io.StringIO(text))}


@cache
def _synonyms() -> dict[str, str]:
    text = files("bi2.data").joinpath("mcc_synonyms.toml").read_text(encoding="utf-8")
    return dict(tomllib.loads(text)["codes"])


def _shown(code: str) -> str:
    """A code's description as a model sees it: the official words, and plain ones."""
    plain = _synonyms().get(code)
    return f"{mcc_codes()[code]} ({plain})" if plain else mcc_codes()[code]


# The generic code for each family of chain codes. A chain's own code replaces its family's
# generic one, since card networks file the chain's sales under it.
_CHAIN_FAMILIES: Final = (
    ("3000", "3299", "4511"),
    ("3351", "3500", "7512"),
    ("3501", "3999", "7011"),
)


def _chain_family(code: str) -> str | None:
    return next((generic for low, high, generic in _CHAIN_FAMILIES if low <= code <= high), None)


@cache
def _schema_hints() -> dict[str, tuple[str, ...]]:
    text = files("bi2.data").joinpath("schema_types.toml").read_text(encoding="utf-8")
    return {name: tuple(codes) for name, codes in tomllib.loads(text)["types"].items()}


def _is_chain(code: str) -> bool:
    return "3000" <= code <= "3999"


def hinted_codes(ev: Evidence) -> tuple[str, ...]:
    """The codes the page's schema.org types point to, likeliest first."""
    hints = _schema_hints()
    found = [code for kind in ev.structured.types for code in hints.get(kind, ())]
    return tuple(dict.fromkeys(found))


# Words that say what kind of business a chain is, rather than which one: "WestJet" is the
# chain "Westjet Airlines", and "Budget Car Rental Canada" the chain "Budget Rent-A-Car".
_KIND_WORDS: Final = frozenset(
    [
        "airlines",
        "airline",
        "airways",
        "air",
        "hotels",
        "hotel",
        "resorts",
        "resort",
        "inns",
        "inn",
        "suites",
        "rent",
        "a",
        "car",
        "cars",
        "rental",
        "rentals",
        "corporation",
        "corp",
        "company",
        "co",
        "inc",
        "ltd",
        "canada",
        "international",
        "group",
        "the",
        "and",
        "of",
        "official",
        "site",
    ]
)


def _chain_core(name: str) -> str:
    """A name without the words that say what kind of business it is, to match a chain by."""
    words = re.sub(r"[^a-z0-9]+", " ", fold(name)).split()
    core = [word for word in words if word not in _KIND_WORDS]
    return " ".join(core) or " ".join(words)


def chain_codes(ev: Evidence) -> list[str]:
    """The chain codes whose chain is the business, by the names the page gives it."""
    names = [name for _, name in name_candidates(ev)][:8]
    if ev.page.profile_name:
        names.insert(0, ev.page.profile_name)
    cores = {_chain_core(name) for name in names if name}
    return [
        code
        for code, chain in mcc_codes().items()
        if _is_chain(code)
        and (any(names_match(name, chain) for name in names) or _chain_core(chain) in cores)
    ][:3]


def _state(ev: Evidence) -> str:
    if ev.unreadable and ev.known is not None:
        # A page that blocks us says nothing, but Wikidata knows big brands.
        known = ev.known
        return "\n".join(
            [f"Business: {known.name}", f"Wikidata describes it as: {known.description}"]
        )
    lines = site_lines(ev)
    if ev.structured.types:
        lines.append("Its structured data calls it: " + ", ".join(ev.structured.types[:6]))
    if ev.text.header:
        lines.append(f"Top of the page: {ev.text.header[:400]}")
    if ev.text.main:
        lines.append(f"Main text: {ev.text.main[:_MOST_TEXT]}")
    return "\n".join(lines)


def _first_round(state: str) -> Ask:
    codes = {code: _shown(code) for code in mcc_codes() if not _is_chain(code)}
    lists = {
        "low": {code: text for code, text in codes.items() if code < _SPLIT},
        "high": {code: text for code, text in codes.items() if code >= _SPLIT},
    }
    questions: dict[str, Question] = {
        name: Choice(
            instructions=f"{_QUESTION} Pick from this list, or none if no code in it fits.",
            options={**options, NONE: "No code in this list fits the business"},
        )
        for name, options in lists.items()
    }
    return Ask(task="mcc_round_1", version=_VERSION, state=state, questions=questions)


def _leaders(decision: Decision) -> list[str]:
    """The likeliest codes of each list of the first round."""
    leaders: list[tuple[float, str]] = []
    for name in ("low", "high"):
        picked = decision.picked(name)
        ranked = sorted(picked.probabilities.items(), key=lambda item: -item[1])
        leaders += [(p, code) for code, p in ranked[:_LEADERS] if code != NONE and p >= 0.02]
    return [code for _, code in sorted(leaders, reverse=True)]


_DECISIVE: Final = 0.9  # a first-round pick this likely, with the other list fitting none


def _decided_in_round_one(decision: Decision) -> tuple[str, float] | None:
    """The code the first round already settles, with no final round needed: one list's pick
    at 0.9 or more, and the other list fitting none at 0.9 or more."""
    low, high = decision.picked("low"), decision.picked("high")
    for mine, other in ((low, high), (high, low)):
        if (
            mine.choice != NONE
            and mine.probability(mine.choice) >= _DECISIVE
            and other.probability(NONE) >= _DECISIVE
        ):
            return mine.choice, mine.probability(mine.choice)
    return None


def _final_round(state: str, codes: list[str], *, reversed_order: bool = False) -> Ask:
    """The final round. Reversed, the same question with the options in the other order: Jev
    leans toward the first option, so the same pick both ways is a sure one."""
    ordered = sorted(set(codes), reverse=reversed_order)
    question = Choice(instructions=_QUESTION, options={code: _shown(code) for code in ordered})
    task = "mcc_final_reversed" if reversed_order else "mcc_final"
    return Ask(task=task, version=_VERSION, state=state, questions={"mcc": question})


def _sure(probability: float, *, hinted: bool) -> float:
    if probability >= 0.75:
        return 0.92 if hinted else 0.88
    if probability >= 0.5:
        return 0.86 if hinted else 0.75
    return 0.6


async def mcc_by_decider(ev: Evidence, ctx: RunContext) -> Resolved[Mcc] | Escalate:
    """The code Jev picks from the official list, in two rounds. When it isn't sure of the
    final pick, a second model picks among the same finalists: the same pick makes it sure,
    and a different one leaves the likelier of the two for review."""
    if ev.unreadable and (ev.known is None or not ev.known.description):
        return Escalate("the page couldn't be read, so there's nothing to judge its business by")
    state = _state(ev)
    first = await ask_decider(_first_round(state), ctx)
    if isinstance(first, str):
        return Escalate(first)
    chains = chain_codes(ev)
    finalists = _leaders(first) + chains
    if not finalists:
        return Escalate(f"{first.model} found no code that fits", cost=first.cost)
    if (decided := _decided_in_round_one(first)) is not None and not chains:
        code, probability = decided
        return Resolved(
            value=Mcc(code=code, description=mcc_codes()[code]),
            confidence=_sure(probability, hinted=code in hinted_codes(ev)),
            source=f"{first.model}: picked in the first round ({probability:.2f}), the other "
            "list fitting none",
            evidence=tuple(f"{c} {mcc_codes()[c]}" for c in sorted(set(finalists))),
            cost=first.cost,
        )
    final_round = _final_round(state, finalists)
    final = await ask_decider(final_round, ctx)
    if isinstance(final, str):
        return Escalate(final, cost=first.cost)
    cost = first.cost + final.cost
    picked = final.picked("mcc")
    code, probability = picked.choice, picked.probability(picked.choice)
    sure = _sure(probability, hinted=code in hinted_codes(ev))
    source = f"{final.model}: picked from the official codes ({probability:.2f})"
    if sure < ctx.settings.thresholds.accept and len(set(finalists)) > 1:
        try:
            again = await ask_decider(_final_round(state, finalists, reversed_order=True), ctx)
        except ModelUnavailable:
            again = None
        if isinstance(again, Decision):
            cost += again.cost
            other = again.picked("mcc")
            if other.choice == code and other.probability(code) >= 0.5:
                sure, source = 0.88, f"{source}, and the same with the options reversed"
            elif other.choice != code:
                sure = min(sure, 0.6)
                source = f"{source}; {other.choice} with the options reversed"
    chain = next((c for c in chains if _chain_family(c) == code), None)
    if chain is not None:  # the chain itself, like Air Canada, rather than any airline
        code, source = chain, f"{source}, filed under the chain's own code"
    return Resolved(
        value=Mcc(code=code, description=mcc_codes()[code]),
        confidence=sure,
        source=source,
        evidence=tuple(f"{c} {mcc_codes()[c]}" for c in sorted(set(finalists))),
        cost=cost,
    )


async def resolve_mcc(ev: Evidence, ctx: RunContext) -> MccResult:
    """The business's merchant category code."""
    return await run_cascade([mcc_by_decider], ev, ctx)
