"""Tests for the scoring rules."""

from typing import Any

from bi2.core.models import Address, PageKind
from bi2.evaluation.gold import ExpectedAddress, GoldSite
from bi2.evaluation.scoring import (
    Verdict,
    address_matches,
    image_key,
    score_site,
    social_key,
)
from tests.factories import answered, site_result

CAFE = GoldSite(
    url="https://example-cafe.ca/",
    category="cafe",
    company_names=("Example Cafe", "Example Café Ltd."),
    logo_urls=("https://www.example-cafe.ca/images/logo.png",),
    mcc_codes=("5814", "5812"),
    address=ExpectedAddress(street="128a Sterling Rd", city="Toronto", postal_code="M6R 2B7"),
    phones=("+14165550123",),
    social_links=("https://instagram.com/examplecafe",),
)


def _verdicts(
    gold: GoldSite, url: str = "https://example-cafe.ca/", **fields: Any
) -> dict[str, Verdict]:
    return {score.field: score.verdict for score in score_site(gold, site_result(url, **fields))}


def test_correct_answers_in_different_spellings() -> None:
    verdicts = _verdicts(
        CAFE,
        company_name=answered("EXAMPLE CAFE LTD"),
        logo=answered({"url": "http://example-cafe.ca/images/logo.png?v=17"}),
        mcc=answered({"code": "5812", "description": "Eating Places and Restaurants"}),
        address=answered({"text": "128A Sterling Road, Toronto, ON M6R2B7, Canada"}),
        phone=answered("+14165550123"),
        social_links=answered(
            [{"platform": "instagram", "url": "https://www.instagram.com/ExampleCafe/"}]
        ),
    )
    assert set(verdicts.values()) == {Verdict.CORRECT}


def test_wrong_and_missed_answers() -> None:
    verdicts = _verdicts(
        CAFE,
        company_name=answered("Pinterest"),
        mcc=answered({"code": "5992", "description": "Florists"}),
    )
    assert verdicts["company_name"] is Verdict.WRONG
    assert verdicts["mcc"] is Verdict.WRONG
    assert verdicts["logo"] is Verdict.MISSED
    assert verdicts["address"] is Verdict.MISSED


def test_none_means_finding_nothing_is_correct() -> None:
    online_shop = GoldSite(url="https://example-shop.ca/", category="shop", address="none")
    assert _verdicts(online_shop)["address"] is Verdict.CORRECT
    found = _verdicts(online_shop, address=answered({"text": "1 Main St"}))
    assert found["address"] is Verdict.UNEXPECTED


def test_fields_the_gold_set_doesnt_check_are_not_scored() -> None:
    unchecked = GoldSite(url="https://example-shop.ca/", category="shop")
    verdicts = _verdicts(unchecked, company_name=answered("Example Shop"))
    assert verdicts["company_name"] is Verdict.NOT_SCORED
    assert verdicts["page_kind"] is Verdict.CORRECT


def test_a_platform_profile_must_be_recognized() -> None:
    profile = GoldSite(
        url="https://www.pinterest.com/examplecafe/",
        category="cafe",
        page_kind=PageKind.PLATFORM_PROFILE,
        platform="pinterest",
    )
    treated_as_own_site = _verdicts(profile, url="https://www.pinterest.com/examplecafe/")
    assert treated_as_own_site["page_kind"] is Verdict.WRONG


def test_a_site_with_no_result_misses_everything_checked() -> None:
    scores = {score.field: score.verdict for score in score_site(CAFE, None)}
    assert set(scores.values()) == {Verdict.MISSED}


def test_image_key_ignores_cdn_size_tags_and_transforms() -> None:
    shop = "https://shop.example.ca/cdn/shop/files/logo2"
    assert image_key(f"{shop}_150x.png?v=1") == image_key(f"{shop}_300x300.png")
    assert image_key(f"{shop}_{{width}}x.png") == image_key(f"http://www.{shop[8:]}.PNG")
    assert image_key("https://example.ca/wp-content/logo-300x100.png") == image_key(
        "https://example.ca/wp-content/logo.png"
    )
    wix = "https://static.wixstatic.com/media/5ef73e_5d6c~mv2.png"
    assert image_key(f"{wix}/v1/fill/w_240,h_63/logo.png") == image_key(wix)
    assert image_key(f"{shop}.png") != image_key(f"{shop}-white.png")


def test_phone_must_be_an_accepted_number() -> None:
    bar = GoldSite(
        url="https://example-bar.ca/", category="bar", phones=("+14165550123", "+16475550199")
    )
    assert _verdicts(bar, phone=answered("+16475550199"))["phone"] is Verdict.CORRECT
    assert _verdicts(bar, phone=answered("+14165550000"))["phone"] is Verdict.WRONG


def test_social_links_must_include_every_expected_profile() -> None:
    bar = GoldSite(
        url="https://example-bar.ca/",
        category="bar",
        social_links=("https://www.instagram.com/examplebar/", "https://twitter.com/ExampleBar"),
    )
    instagram = {"platform": "instagram", "url": "https://instagram.com/examplebar"}
    x = {"platform": "x", "url": "https://x.com/examplebar"}
    tiktok = {"platform": "tiktok", "url": "https://tiktok.com/@examplebar"}
    everything = _verdicts(bar, social_links=answered([instagram, x, tiktok]))
    assert everything["social_links"] is Verdict.CORRECT
    assert _verdicts(bar, social_links=answered([instagram]))["social_links"] is Verdict.WRONG


def test_social_key_names_the_profile() -> None:
    assert social_key("https://m.facebook.com/BarVolo/posts/123") == social_key(
        "https://facebook.com/barvolo"
    )
    assert (
        social_key("https://www.linkedin.com/company/acme/mycompany") == "linkedin.com/company/acme"
    )
    assert social_key("https://pinterest.ca/roots") == social_key(
        "https://www.pinterest.com/roots/"
    )
    assert social_key("https://facebook.com/profile.php?id=42") != social_key(
        "https://facebook.com/profile.php?id=7"
    )


def test_address_needs_the_right_house_number() -> None:
    want = ExpectedAddress(street="225 Delaware Avenue", postal_code="14202")
    assert address_matches(Address(text="225 Delaware Ave, Buffalo, NY 14202"), want)
    assert not address_matches(Address(text="25 Delaware Ave, Buffalo, NY 14202"), want)
    assert not address_matches(Address(text="225 Delaware Ave, Buffalo, NY 14203"), want)


def test_address_without_a_postal_code_compares_the_city() -> None:
    want = ExpectedAddress(street="5 Market Square", city="Dublin")
    assert address_matches(Address(text="5 Market Square, Dublin"), want)
    assert not address_matches(Address(text="5 Market Square, Cork"), want)
