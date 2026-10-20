"""Tests for the answers taken from what Wikidata knows, for pages that couldn't be read."""

import pytest

from bi2.core.errors import FetchError
from bi2.core.models import Evidence, KnownBusiness, PageInfo, SocialProfile
from bi2.resolvers.known import (
    email_from_wikidata,
    logo_from_wikidata,
    name_from_wikidata,
    phone_from_wikidata,
    social_from_wikidata,
)
from tests.fakes import fake_context
from tests.resolvers.images import picture

LOGO = "https://commons.wikimedia.org/wiki/Special:FilePath/No_Frills_logo.png"


def _evidence(url: str = "https://www.nofrills.ca/", **known: object) -> Evidence:
    business = KnownBusiness.model_validate({"item": "Q3342407", **known})
    return Evidence(page=PageInfo(url=url), unreadable="a bot check", known=business)


async def test_a_name_that_matches_the_domain_is_sure() -> None:
    answer = await name_from_wikidata(_evidence(name="No Frills"), fake_context())
    assert (answer.value, answer.confidence) == ("No Frills", 0.85)
    assert answer.source == "Wikidata Q3342407: its name"


async def test_a_name_that_doesnt_match_the_domain_needs_review() -> None:
    answer = await name_from_wikidata(
        _evidence("https://www.roots.com/", name="Roots Canada"), fake_context()
    )
    assert answer.confidence == 0.7


async def test_the_logo_is_downloaded_and_checked() -> None:
    ctx = fake_context(downloads={LOGO: picture(300, 100)})
    answer = await logo_from_wikidata(_evidence(logo_url=LOGO), ctx)
    assert answer.value.url == LOGO
    assert answer.value.image_file == "nofrills.ca/logo.png"


async def test_a_logo_that_isnt_a_logo_fails() -> None:
    ctx = fake_context(downloads={LOGO: b"not an image"})
    with pytest.raises(FetchError, match="the logo Wikidata names"):
        await logo_from_wikidata(_evidence(logo_url=LOGO), ctx)


async def test_contact_details_need_review_since_they_can_be_out_of_date() -> None:
    ev = _evidence(
        phone="+1 866-987-6453",
        email="Contact@NoFrills.ca",
        social_links=(SocialProfile(platform="x", url="https://x.com/nofrills"),),
    )
    phone = await phone_from_wikidata(ev, fake_context())
    email = await email_from_wikidata(ev, fake_context())
    social = await social_from_wikidata(ev, fake_context())
    assert (phone.value, phone.confidence) == ("+18669876453", 0.7)
    assert email.value == "contact@nofrills.ca"
    assert social.confidence == 0.7


async def test_a_field_wikidata_doesnt_know_fails() -> None:
    with pytest.raises(FetchError, match="no phone"):
        await phone_from_wikidata(_evidence(name="No Frills"), fake_context())
    ev = Evidence(page=PageInfo(url="https://example-cafe.ca/"), unreadable="a bot check")
    with pytest.raises(FetchError, match="doesn't know"):
        await name_from_wikidata(ev, fake_context())
