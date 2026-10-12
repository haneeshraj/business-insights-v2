"""Tests for finding the business's name."""

from typing import Any

from bi2.core.models import (
    Contacts,
    Evidence,
    NameResult,
    PageInfo,
    PageKind,
    PageMeta,
    Status,
    StructuredData,
)
from bi2.resolvers.name import resolve_name
from tests.fakes import fake_context

URL = "https://example-cafe.ca/"


async def _resolve(url: str = URL, **parts: Any) -> NameResult:
    page = parts.pop("page", PageInfo(url=url, final_url=url, kind=PageKind.OWN_WEBSITE))
    return await resolve_name(Evidence.model_validate({"page": page, **parts}), fake_context())


async def test_a_name_given_in_several_places_is_accepted() -> None:
    result = await _resolve(
        structured=StructuredData(name="Example Cafe Ltd."),
        meta=PageMeta(site_name="Example Cafe", title="Menu | Example Cafe"),
    )
    assert result.status is Status.OK
    assert result.value == "Example Cafe Ltd."  # the business's own spelling
    assert result.source == "structured data + site name + part of the title"
    assert result.confidence == 0.95


async def test_page_words_in_titles_arent_names() -> None:
    result = await _resolve(meta=PageMeta(title="Home | Example Cafe"))
    assert result.value == "Example Cafe"
    assert result.status is Status.OK  # a title part that matches the web address


async def test_a_name_found_once_needs_review() -> None:
    result = await _resolve(
        "https://shop.example.com/", meta=PageMeta(title="Northside Roasters | Shop")
    )
    assert result.status is Status.NEEDS_REVIEW
    assert result.value == "Northside Roasters"


async def test_a_rival_name_lowers_the_confidence() -> None:
    result = await _resolve(
        "https://example.com/",
        meta=PageMeta(site_name="Northside Roasters"),
        contacts=Contacts(copyright_line="© 2026 Parent Holdings Inc."),
    )
    assert result.status is Status.NEEDS_REVIEW
    assert result.confidence == 0.6


async def test_on_a_platform_the_profile_gives_the_name_not_the_platform() -> None:
    url = "https://www.pinterest.com/starbucks/"
    page = PageInfo(
        url=url,
        final_url=url,
        kind=PageKind.PLATFORM_PROFILE,
        platform="pinterest",
        profile_name="Starbucks",
    )
    result = await _resolve(
        url, page=page, meta=PageMeta(title="Starbucks (starbucks) - Profile | Pinterest")
    )
    assert result.value == "Starbucks"
    assert result.status is Status.OK


async def test_a_page_that_names_nothing_has_no_name() -> None:
    result = await _resolve(meta=PageMeta(title="Home"))
    assert result.status is Status.NOT_FOUND
    assert result.steps[0].detail == "the page doesn't name the business anywhere"
