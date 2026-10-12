"""Tests for recognizing pages on platforms."""

import pytest

from bi2.evidence.platforms import (
    Profile,
    find_profile,
    page_profile,
    platform_of,
    platforms,
    profile_name,
    unwrap_link,
)


def test_every_platform_entry_is_valid() -> None:
    loaded = platforms()
    assert {"instagram", "facebook", "x", "linkedin", "youtube", "tiktok", "pinterest"} <= set(
        loaded
    )
    for key in loaded:
        find_profile(f"https://{loaded[key].domains[0].replace('*', 'com')}/example")


def test_platforms_are_known_by_any_of_their_domains() -> None:
    assert platform_of("https://twitter.com/examplecafe") == "x"
    assert platform_of("https://www.pinterest.co.uk/examplecafe/") == "pinterest"
    assert platform_of("https://pinterest.example.com/") is None
    assert platform_of("https://example-cafe.ca/") is None


@pytest.mark.parametrize(
    ("url", "profile"),
    [
        ("https://www.instagram.com/examplecafe/", Profile("instagram", "examplecafe")),
        ("https://m.facebook.com/ExampleCafe", Profile("facebook", "ExampleCafe")),
        ("https://facebook.com/pg/ExampleCafe/about/", Profile("facebook", "ExampleCafe")),
        ("https://x.com/examplecafe", Profile("x", "examplecafe")),
        (
            "https://ca.linkedin.com/company/example-cafe/",
            Profile("linkedin", "company/example-cafe"),
        ),
        ("https://www.youtube.com/@ExampleCafe/videos", Profile("youtube", "@ExampleCafe")),
        ("https://youtube.com/examplecafe", Profile("youtube", "examplecafe")),
        ("https://www.tiktok.com/@examplecafe", Profile("tiktok", "@examplecafe")),
        ("https://untappd.com/brewery/12345", Profile("untappd", "brewery/12345")),
    ],
)
def test_finds_business_profiles(url: str, profile: Profile) -> None:
    assert find_profile(url) == profile


@pytest.mark.parametrize(
    "url",
    [
        "https://www.facebook.com/sharer/sharer.php?u=https://example-cafe.ca",
        "https://twitter.com/intent/tweet?text=hi",
        "https://www.instagram.com/p/C1a2b3c4/",
        "https://www.instagram.com/explore/",
        "https://help.instagram.com/581066165581870",
        "https://www.pinterest.com/pin/123456/",
        "https://www.youtube.com/watch?v=abc",
        "https://www.linkedin.com/in/some-person",
        "https://www.instagram.com/",
        "https://example-cafe.ca/instagram",
    ],
)
def test_other_links_are_not_profiles(url: str) -> None:
    assert find_profile(url) is None


def test_non_social_platforms_have_profiles_too() -> None:
    assert find_profile("https://www.yelp.ca/biz/example-cafe-toronto") == Profile(
        "yelp", "example-cafe-toronto"
    )
    assert find_profile("https://www.ubereats.com/ca/store/example-cafe/abc123") == Profile(
        "ubereats", "example-cafe"
    )
    assert not platforms()["yelp"].social


def test_a_page_sent_to_a_login_page_is_still_the_profile_asked_for() -> None:
    login = "https://www.instagram.com/accounts/login/?next=%2Fexamplecafe%2F"
    profile = page_profile("https://www.instagram.com/examplecafe/", login)
    assert profile == Profile("instagram", "examplecafe")


@pytest.mark.parametrize(
    ("title", "platform", "name"),
    [
        ("Example Cafe (@examplecafe) • Instagram photos and videos", "instagram", "Example Cafe"),
        ("Starbucks (starbucks) - Profile | Pinterest", "pinterest", "Starbucks"),
        ("Example Cafe | Toronto ON | Facebook", "facebook", "Example Cafe"),
        ("Saint-Germain Bakery - Updated 2026 - Yelp", "yelp", "Saint-Germain Bakery"),
        ("Instagram", "instagram", None),  # a login page names only the platform
    ],
)
def test_profile_names_come_from_the_title(title: str, platform: str, name: str | None) -> None:
    assert profile_name(title, platform) == name


def test_outside_links_are_unwrapped_from_the_platforms_link_wrapper() -> None:
    wrapped = "https://l.instagram.com/?u=https%3A%2F%2Fexample-cafe.ca%2F&e=AT0"
    assert unwrap_link(wrapped, "instagram") == "https://example-cafe.ca/"
    assert unwrap_link("https://example-cafe.ca/", "instagram") is None
