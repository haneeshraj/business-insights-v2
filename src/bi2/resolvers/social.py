"""The business's social media profiles, from the ones its page links to.

A site links to its own profiles, usually one per platform, from its header or footer. A second
profile on the same platform counts only when its handle has the business's name in it, since
sites also link to partners and suppliers.
"""

import re
from typing import Final

from bi2.core.context import RunContext
from bi2.core.models import Evidence, PageKind, SocialLinks, SocialProfile, SocialResult
from bi2.core.text import normalize_company_name
from bi2.core.urls import registrable_domain
from bi2.evidence.platforms import find_profile
from bi2.resolvers.cascade import Escalate, Resolved, run_cascade

_NOT_LETTERS: Final = re.compile(r"[^a-z0-9]")

# How sure the profiles are: a platform page is itself the business's profile.
_SURE_ON_OWN_SITE, _SURE_ON_PROFILE = 0.9, 0.95


def _brand_words(ev: Evidence) -> set[str]:
    """Parts of the business's name to look for in a handle."""
    names = [ev.structured.name or "", ev.meta.site_name, ev.page.profile_name or ""]
    if ev.page.kind is PageKind.OWN_WEBSITE:
        names.append(registrable_domain(ev.page.url).split(".")[0])
    words = {word for name in names for word in normalize_company_name(name).split()}
    return {_NOT_LETTERS.sub("", word) for word in words if len(word) >= 4}


def _named_after(profile: SocialProfile, words: set[str]) -> bool:
    found = find_profile(profile.url)
    handle = _NOT_LETTERS.sub("", found.handle.lower()) if found else ""
    return any(word in handle for word in words)


async def social_links_from_the_page(
    ev: Evidence, ctx: RunContext
) -> Resolved[SocialLinks] | Escalate:
    """The profiles the business's own page links to, one per platform unless named after it."""
    if not ev.social_links or ev.page.kind is PageKind.UNKNOWN:
        return Escalate("the page doesn't link to any social media profiles")
    words = _brand_words(ev)
    kept: list[SocialProfile] = []
    for profile in ev.social_links:
        first_here = all(other.platform != profile.platform for other in kept)
        if first_here or _named_after(profile, words):
            kept.append(profile)
    on_profile = ev.page.kind is PageKind.PLATFORM_PROFILE
    return Resolved(
        value=tuple(kept),
        confidence=_SURE_ON_PROFILE if on_profile else _SURE_ON_OWN_SITE,
        source="the profile itself" if on_profile else "links on the business's page",
        evidence=tuple(profile.url for profile in kept),
    )


async def resolve_social_links(ev: Evidence, ctx: RunContext) -> SocialResult:
    """The business's social media profiles."""
    return await run_cascade("social_links", [social_links_from_the_page], ev, ctx)
