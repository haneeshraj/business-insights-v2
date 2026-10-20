"""Tests for the business's address and its place on the map."""

from dataclasses import replace

from bi2.core.models import (
    Address,
    ContactPage,
    Coordinates,
    Evidence,
    GeocodedPlace,
    KnownBusiness,
    PageInfo,
    PageKind,
    StructuredData,
    TextRegions,
)
from bi2.resolvers.address import address_lines, resolve_address, street_lines
from tests.fakes import fake_context

URL = "https://www.barvolo.com/"
PAGE = PageInfo(url=URL, final_url=URL, kind=PageKind.OWN_WEBSITE)


class OneMap:
    """Places every address at one point, with the given postcode."""

    def __init__(self, postcode: str) -> None:
        self.postcode = postcode
        self.asked: list[str] = []

    async def locate(self, address: Address) -> GeocodedPlace | None:
        self.asked.append(address.text)
        return GeocodedPlace(
            coordinates=Coordinates(latitude=43.66, longitude=-79.38),
            postal_code=self.postcode,
            city="Toronto",
            source="OpenStreetMap: test",
        )


def test_address_lines_are_found_by_their_postcodes() -> None:
    text = "Bar Volo\n17 St Nicholas Street, Toronto, ON M4Y 3G4 | Tel 416-928-0018\nOpen daily"
    assert address_lines(text) == [("17 St Nicholas Street, Toronto, ON M4Y 3G4", "M4Y 3G4", "CA")]
    assert address_lines("Free shipping to M4Y 3G4") == []  # no house number, no address


def test_lines_with_a_street_word_count_where_the_postcode_isnt_known() -> None:
    text = "Kontakt\nHauptstraße 5, 1010 Wien\nÖffnungszeiten 9-17"
    assert street_lines(text) == ["Hauptstraße 5, 1010 Wien"]


async def test_one_footer_address_is_the_business_and_it_goes_on_the_map() -> None:
    ev = Evidence(page=PAGE, text=TextRegions(footer="17 St Nicholas Street, Toronto, ON M4Y 3G4"))
    result = await resolve_address(ev, replace(fake_context(), geocoder=OneMap("M4Y 3G4")))
    assert result.status.value == "ok"
    assert result.value is not None
    assert result.value.postal_code == "M4Y 3G4"
    assert result.value.coordinates == Coordinates(latitude=43.66, longitude=-79.38)
    assert result.value.geocode_agrees is True


async def test_a_map_that_disagrees_on_the_postcode_is_flagged() -> None:
    ev = Evidence(page=PAGE, text=TextRegions(footer="17 St Nicholas Street, Toronto, ON M4Y 3G4"))
    result = await resolve_address(ev, replace(fake_context(), geocoder=OneMap("M5V 1A1")))
    assert result.value is not None
    assert result.value.geocode_agrees is False


async def test_structured_data_comes_first() -> None:
    address = Address(text="17 St Nicholas St, Toronto", street="17 St Nicholas St", city="Toronto")
    ev = Evidence(page=PAGE, structured=StructuredData(address=address))
    result = await resolve_address(ev, fake_context())
    assert (result.source, result.status.value) == ("structured data", "ok")


async def test_wikidata_gives_a_big_brands_head_office() -> None:
    known = KnownBusiness(
        item="Q165684",
        name="Rogers Communications",
        head_office="333 Bloor Street East",
        head_office_postcode="M4W 1G9",
        head_office_city="Toronto",
    )
    ev = Evidence(
        page=PAGE, known=known, contact_page=ContactPage(url=f"{URL}contact", text="M4W 1G9")
    )
    result = await resolve_address(ev, fake_context())
    assert result.value is not None
    assert result.value.text == "333 Bloor Street East, Toronto M4W 1G9"
    assert result.status.value == "ok"  # the pages show the same postcode
