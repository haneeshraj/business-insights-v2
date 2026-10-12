"""Platforms where businesses have pages, from data/platforms.toml, and recognizing a
business's profile on one."""

import re
import tomllib
from functools import cache
from importlib.resources import files
from typing import NamedTuple
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field

from bi2.core.text import clean_space, fold
from bi2.core.urls import host, registrable_domain


class Platform(BaseModel):
    """One entry in data/platforms.toml."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    social: bool = False  # a profile here is one of the business's social media links
    domains: tuple[str, ...] = Field(min_length=1)
    profiles: tuple[str, ...] = ()  # patterns for a profile page's path
    not_handles: tuple[str, ...] = ()  # handles that are the platform's own pages
    link_wrappers: tuple[str, ...] = ()  # hosts the platform sends outside links through


class Profile(NamedTuple):
    """A business's page on a platform."""

    platform: str  # the platform's key in data/platforms.toml, like "instagram"
    handle: str  # the part of the URL that names the profile, like "examplecafe"


@cache
def platforms() -> dict[str, Platform]:
    """Every platform in data/platforms.toml, by key."""
    text = files("bi2.data").joinpath("platforms.toml").read_text(encoding="utf-8")
    data = tomllib.loads(text)
    data.pop("version")
    return {key: Platform.model_validate(entry) for key, entry in data.items()}


@cache
def _profile_patterns(key: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(pattern) for pattern in platforms()[key].profiles)


@cache
def _not_handles(key: str) -> frozenset[str]:
    return frozenset(handle.casefold() for handle in platforms()[key].not_handles)


def platform_of(url: str) -> str | None:
    """The key of the platform a URL is on, or None for any other site."""
    domain = registrable_domain(url).casefold()
    name = domain.split(".", 1)[0]
    for key, platform in platforms().items():
        for pattern in platform.domains:
            if domain == pattern or (pattern.endswith(".*") and name == pattern[:-2]):
                return key
    return None


def _main_host(url: str) -> bool:
    """Whether the URL is on the platform's main site, rather than one like help.instagram.com.
    Mobile ("m.") and country ("ca.linkedin.com") versions count as the main site."""
    sub = host(url).removesuffix(registrable_domain(url)).rstrip(".")
    return sub in ("", "m", "mobile") or (len(sub) == 2 and sub.isalpha())


def find_profile(url: str) -> Profile | None:
    """The business profile a URL points to, or None when it isn't one: another site, or a
    platform page that isn't a profile, such as a share button, a post or a help page."""
    key = platform_of(url)
    if key is None or not _main_host(url):
        return None
    path = urlsplit(url).path.rstrip("/")
    for pattern in _profile_patterns(key):
        match = pattern.match(path)
        if match and match.group("handle").casefold() not in _not_handles(key):
            return Profile(key, match.group("handle"))
    return None


def page_profile(url: str, final_url: str) -> Profile | None:
    """The profile a loaded page is: where the page ended up or, failing that, the URL asked
    for, since platforms often send visitors who aren't signed in to a login page."""
    return find_profile(final_url) or find_profile(url)


# Where a profile page's title stops naming the business: at " (@handle)", " | Facebook",
# " - Profile | Pinterest", " / X", or a bullet or middle dot before the platform's name.
_TITLE_END = re.compile(r"\s+[(|\-/\N{BULLET}\N{MIDDLE DOT}]")


def profile_name(title: str, platform: str) -> str | None:
    """The business's name in a profile page's title: "Starbucks" from "Starbucks (starbucks)
    - Profile | Pinterest". None when the title names only the platform, as login pages'
    titles do."""
    name = clean_space(_TITLE_END.split(title, maxsplit=1)[0])
    if not name or fold(name) == fold(platforms()[platform].name):
        return None
    return name


def unwrap_link(url: str, platform: str) -> str | None:
    """The outside address in a link the platform sends through one of its link wrappers, such
    as l.instagram.com/?u=..., or None for any other link."""
    if host(url) not in platforms()[platform].link_wrappers:
        return None
    query = parse_qs(urlsplit(url).query)
    for key in ("u", "url", "q"):
        for target in query.get(key, []):
            if target.startswith(("http://", "https://")):
                return target
    return None
