"""Every name in a page's evidence that could be the business's, with where it was found."""

import re
from typing import Final

from bi2.core.models import Evidence
from bi2.core.text import clean_space, fold, names_match
from bi2.evidence.contacts import copyright_holder
from bi2.evidence.platforms import platforms

# Where page titles split into parts, as in "Menu | Example Cafe - Toronto".
_TITLE_PARTS: Final = re.compile(r"\s+[|\-:\N{EN DASH}\N{EM DASH}\N{MIDDLE DOT}\N{BULLET}]\s+")

# Title parts that name a page or a section, not a business.
_NOT_NAMES: Final = frozenset(
    {
        "home", "homepage", "home page", "welcome", "official site", "official website",
        "online store", "online shop", "shop", "shop online", "store", "menu", "contact",
        "contact us", "about", "about us", "profile", "blog", "news", "page not found", "404",
        "access denied", "just a moment...", "log in", "login", "sign in",
    }
)  # fmt: skip


def name_candidates(ev: Evidence) -> list[tuple[str, str]]:
    """Every name in the evidence that could be the business's, as (where, name), the places
    that tell the most first. A title made of parts gives its parts, not the whole title."""
    found = [
        ("profile name", ev.page.profile_name or ""),
        ("structured data", ev.structured.name or ""),
        ("structured data legal name", ev.structured.legal_name or ""),
        ("site name", ev.meta.site_name),
    ]
    for where, title in (("og:title", ev.meta.og_title), ("title", ev.meta.title)):
        parts = _TITLE_PARTS.split(title)
        found += (
            [(f"part of the {where}", part) for part in parts]
            if len(parts) > 1
            else [(where, title)]
        )
    if ev.contacts.copyright_line:
        found.append(("copyright line", copyright_holder(ev.contacts.copyright_line)))
    found += [("logo alt text", candidate.alt) for candidate in ev.logo_candidates]
    platform = platforms()[ev.page.platform].name if ev.page.platform in platforms() else None
    names = []
    for where, name in found:
        name = clean_space(name)
        if not name or fold(name) in _NOT_NAMES:
            continue
        if platform and names_match(name, platform):  # on a platform's page, its own name
            continue
        names.append((where, name))
    return names
