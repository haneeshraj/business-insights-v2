"""Tests for recognizing pages on platforms."""

import pytest

from bi2.evidence.platforms import Profile, find_profile, platform_of, platforms


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
