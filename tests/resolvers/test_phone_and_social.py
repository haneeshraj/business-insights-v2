"""Tests for the phone number and the social media profiles."""

from typing import Any

from bi2.core.models import (
    Contacts,
    Evidence,
    PageInfo,
    PageKind,
    PageMeta,
    SocialProfile,
    Status,
)
from bi2.resolvers.phone import resolve_phone
from bi2.resolvers.social import resolve_social_links
from tests.fakes import fake_context

URL = "https://example-cafe.ca/"
PAGE = PageInfo(url=URL, final_url=URL, kind=PageKind.OWN_WEBSITE)


def _evidence(**parts: Any) -> Evidence:
    return Evidence.model_validate({"page": PAGE, **parts})


def _contacts(places: dict[str, tuple[str, ...]]) -> Contacts:
    return Contacts(phones=tuple(places), phone_places=places)


async def test_a_number_shown_in_several_places_is_accepted() -> None:
    contacts = _contacts({"+14165550123": ("call link", "footer")})
    result = await resolve_phone(_evidence(contacts=contacts), fake_context())
    assert (result.status, result.value, result.confidence) == (Status.OK, "+14165550123", 0.95)
    assert result.source == "call link + footer"


async def test_a_clearer_place_beats_coming_first() -> None:
    contacts = _contacts({"+18005550100": ("main text",), "+14165550199": ("footer",)})
    result = await resolve_phone(_evidence(contacts=contacts), fake_context())
    assert (result.status, result.value) == (Status.OK, "+14165550199")


async def test_a_number_only_in_the_main_text_needs_review() -> None:
    contacts = _contacts({"+14165550123": ("main text",)})
    result = await resolve_phone(_evidence(contacts=contacts), fake_context())
    assert result.status is Status.NEEDS_REVIEW


async def test_no_number_is_not_found() -> None:
    result = await resolve_phone(_evidence(), fake_context())
    assert result.status is Status.NOT_FOUND


def _profile(platform: str, url: str) -> SocialProfile:
    return SocialProfile(platform=platform, url=url)


async def test_one_profile_per_platform_unless_named_after_the_business() -> None:
    profiles = (
        _profile("instagram", "https://instagram.com/examplecafe"),
        _profile("instagram", "https://instagram.com/our_coffee_supplier"),
        _profile("instagram", "https://instagram.com/examplecafe_events"),
        _profile("facebook", "https://facebook.com/ExampleCafeTO"),
    )
    ev = _evidence(social_links=profiles, meta=PageMeta(site_name="Example Cafe"))
    result = await resolve_social_links(ev, fake_context())
    assert result.status is Status.OK
    assert [profile.url for profile in result.value or ()] == [
        "https://instagram.com/examplecafe",
        "https://instagram.com/examplecafe_events",
        "https://facebook.com/ExampleCafeTO",
    ]


async def test_a_platform_page_is_the_business_profile_itself() -> None:
    url = "https://www.instagram.com/examplecafe/"
    page = PageInfo(url=url, final_url=url, kind=PageKind.PLATFORM_PROFILE, platform="instagram")
    ev = Evidence(page=page, social_links=(_profile("instagram", url),))
    result = await resolve_social_links(ev, fake_context())
    assert (result.status, result.confidence) == (Status.OK, 0.95)


async def test_no_profiles_are_not_found() -> None:
    assert (await resolve_social_links(_evidence(), fake_context())).status is Status.NOT_FOUND
