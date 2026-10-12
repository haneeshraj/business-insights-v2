"""The business's name, from the places its page names it.

A name the page gives in several places, such as its structured data, its site name and its
title, is the business's. A name that turns up once, in part of a title, needs review.
"""

from typing import Final

from bi2.core.context import RunContext
from bi2.core.models import CompanyName, Evidence, NameResult
from bi2.core.text import normalize_company_name
from bi2.core.urls import registrable_domain
from bi2.evidence.names import name_candidates
from bi2.resolvers.cascade import Escalate, Resolved, run_cascade

# How much each place counts toward a name. The business stating its own name, in structured
# data or as its profile's name, counts the most.
_WEIGHT: Final = {
    "profile name": 3, "structured data": 3, "structured data legal name": 2, "site name": 2,
    "og:title": 2, "title": 2, "copyright line": 2, "part of the og:title": 1,
    "part of the title": 1, "logo alt text": 1,
}  # fmt: skip

# Which spelling to show when places agree on a name: the business's own first.
_SPELLING_ORDER: Final = (
    "profile name", "structured data", "site name", "copyright line", "og:title", "title",
    "structured data legal name", "part of the og:title", "part of the title", "logo alt text",
)  # fmt: skip

# How sure a name is, by the total weight of the places that give it.
_SURE: Final = {1: 0.5, 2: 0.7, 3: 0.85, 4: 0.9}


def _matches_address(key: str, domain: str) -> bool:
    """Whether a name is the one in the web address: "Bellwoods Brewery" and
    bellwoodsbrewery.com, or "Best Buy Canada" and bestbuy.ca. A long title that merely
    starts with the name doesn't count."""
    squashed = key.replace(" ", "")
    if len(squashed) < 3 or not domain:
        return False
    return squashed in domain or (domain in squashed and len(squashed) - len(domain) <= 8)


# Matching the web address counts as much as the site name: it's rarely a coincidence.
_ADDRESS_WEIGHT: Final = 2


def _weight(key: str, places: list[tuple[str, str]], domain: str) -> int:
    total = sum(_WEIGHT.get(where, 1) for where in dict.fromkeys(w for w, _ in places))
    return total + _ADDRESS_WEIGHT * _matches_address(key, domain)


def _confidence(weight: int, runner_up: int) -> float:
    sure = _SURE.get(weight, 0.95 if weight > 4 else 0.0)
    if runner_up and runner_up >= weight - 1:
        sure -= 0.1  # another name is almost as well supported
    return sure


async def name_from_the_page(ev: Evidence, ctx: RunContext) -> Resolved[CompanyName] | Escalate:
    """The name the page gives most, in the places that count most."""
    groups: dict[str, list[tuple[str, str]]] = {}
    for where, name in name_candidates(ev):
        key = normalize_company_name(name)
        if key:
            groups.setdefault(key, []).append((where, name))
    if not groups:
        return Escalate("the page doesn't name the business anywhere")
    # On a platform's page, the web address is the platform's, so it says nothing.
    domain = "" if ev.page.platform else registrable_domain(ev.page.url).split(".")[0]
    domain = domain.replace("-", "")
    weights = {key: _weight(key, places, domain) for key, places in groups.items()}
    ranked = sorted(groups, key=lambda key: -weights[key])  # ties go to the first one found
    best = ranked[0]
    runner_up = weights[ranked[1]] if len(ranked) > 1 else 0
    places = groups[best]
    order = {where: rank for rank, where in enumerate(_SPELLING_ORDER)}
    spelling = min(places, key=lambda place: order.get(place[0], len(order)))[1]
    sources = list(dict.fromkeys(where for where, _ in places))
    return Resolved(
        value=spelling,
        confidence=_confidence(weights[best], runner_up),
        source=" + ".join(sources[:3]),
        evidence=tuple(f"{where}: {name}" for where, name in places[:5]),
    )


async def resolve_name(ev: Evidence, ctx: RunContext) -> NameResult:
    """The business's name. Search and a model join as later steps."""
    return await run_cascade("company_name", [name_from_the_page], ev, ctx)
