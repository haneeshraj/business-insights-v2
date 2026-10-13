"""Tests for the email address."""

from bi2.core.models import (
    ContactPage,
    Contacts,
    Evidence,
    PageInfo,
    PageKind,
    Status,
    StepOutcome,
)
from bi2.resolvers.email import resolve_email
from tests.fakes import fake_context

URL = "https://example-cafe.ca/"


def _evidence(
    emails: dict[str, tuple[str, ...]],
    contact_page: ContactPage | None = None,
    page: PageInfo | None = None,
) -> Evidence:
    return Evidence(
        page=page or PageInfo(url=URL, final_url=URL, kind=PageKind.OWN_WEBSITE),
        contacts=Contacts(emails=tuple(emails), email_places=emails),
        contact_page=contact_page,
    )


async def test_a_general_address_on_the_sites_own_domain_is_the_one() -> None:
    emails: dict[str, tuple[str, ...]] = {
        "jobs@example-cafe.ca": ("email link",),
        "hello@example-cafe.ca": ("email link",),
    }
    result = await resolve_email(_evidence(emails), fake_context())
    assert (result.value, result.status) == ("hello@example-cafe.ca", Status.OK)


async def test_a_general_address_comes_before_a_persons_or_a_stores() -> None:
    emails: dict[str, tuple[str, ...]] = {
        "margarida@example-cafe.ca": ("email link", "main text"),
        "lojachiado@example-cafe.ca": ("email link", "main text"),
        "escritorio@example-cafe.ca": ("email link",),  # Portuguese for "office"
    }
    result = await resolve_email(_evidence(emails), fake_context())
    assert (result.value, result.status) == ("escritorio@example-cafe.ca", Status.OK)


async def test_one_of_several_stores_needs_review() -> None:
    emails: dict[str, tuple[str, ...]] = {
        "newyork@example-cafe.ca": ("email link", "main text"),
        "toronto@example-cafe.ca": ("email link", "main text"),
    }
    result = await resolve_email(_evidence(emails), fake_context())
    assert (result.value, result.status) == ("newyork@example-cafe.ca", Status.NEEDS_REVIEW)
    assert result.confidence == 0.7


async def test_an_address_for_one_purpose_is_never_the_answer() -> None:
    emails: dict[str, tuple[str, ...]] = {
        "privacy@example-cafe.ca": ("email link",),
        "imprensa@example-cafe.ca": ("email link",),  # Portuguese for "press"
        "ap.inquiries@example-cafe.ca": ("email link",),  # accounts payable
        "examplecafeinvestors@example-cafe.ca": ("footer",),
    }
    result = await resolve_email(_evidence(emails), fake_context())
    assert result.status is Status.NOT_FOUND
    assert result.steps[0].detail == (
        "no address on the page could be the business's general one: "
        "privacy@example-cafe.ca, imprensa@example-cafe.ca"
    )


async def test_a_plainly_general_address_comes_before_one_naming_a_place() -> None:
    emails: dict[str, tuple[str, ...]] = {
        "help.campus@example-cafe.ca": ("email link",),
        "customer.care@example-cafe.ca": ("footer",),
    }
    result = await resolve_email(_evidence(emails), fake_context())
    assert (result.value, result.status) == ("customer.care@example-cafe.ca", Status.OK)
    alone = _evidence({"help.campus@example-cafe.ca": ("email link",)})
    result = await resolve_email(alone, fake_context())
    assert (result.status, result.confidence) == (Status.NEEDS_REVIEW, 0.7)
    for plain in ("enquiries@example-cafe.ca", "servicioalcliente@example-cafe.ca"):
        result = await resolve_email(_evidence({plain: ("email link",)}), fake_context())
        assert result.status is Status.OK, plain  # whole words, with nothing left over


async def test_another_domain_named_for_the_same_business_is_its_own() -> None:
    url = "https://www.northbrewing.ca/"
    page = PageInfo(url=url, final_url=url, kind=PageKind.OWN_WEBSITE)
    emails: dict[str, tuple[str, ...]] = {
        "sam@northbrewing.ca": ("email link",),
        "info@northbrewery.ca": ("email link", "main text"),
    }
    result = await resolve_email(_evidence(emails, page=page), fake_context())
    assert (result.value, result.status) == ("info@northbrewery.ca", Status.OK)


async def test_the_domain_given_counts_as_the_businesss_after_a_redirect() -> None:
    page = PageInfo(url="https://old-name-cafe.ca/", final_url=URL, kind=PageKind.OWN_WEBSITE)
    emails: dict[str, tuple[str, ...]] = {"hello@old-name-cafe.ca": ("email link",)}
    result = await resolve_email(_evidence(emails, page=page), fake_context())
    assert result.status is Status.OK


async def test_hidden_text_counts_only_for_a_general_address_on_the_sites_domain() -> None:
    emails: dict[str, tuple[str, ...]] = {
        "kim@example-cafe.ca": ("email link",),
        "info@example-cafe.ca": ("hidden text",),
    }
    result = await resolve_email(_evidence(emails), fake_context())
    assert (result.value, result.status) == ("info@example-cafe.ca", Status.NEEDS_REVIEW)
    for hidden in ("orders@example-cafe.ca", "support@chat-vendor.com"):
        result = await resolve_email(_evidence({hidden: ("hidden text",)}), fake_context())
        assert result.status is Status.NOT_FOUND


async def test_a_platforms_own_addresses_are_never_the_business() -> None:
    page = PageInfo(
        url="https://www.instagram.com/examplecafe/",
        final_url="https://www.instagram.com/examplecafe/",
        kind=PageKind.PLATFORM_PROFILE,
        platform="Instagram",
        own_website=URL,
    )
    emails: dict[str, tuple[str, ...]] = {
        "help@instagram.com": ("main text",),
        "hello@example-cafe.ca": ("main text",),
    }
    result = await resolve_email(_evidence(emails, page=page), fake_context())
    assert result.value == "hello@example-cafe.ca"
    assert result.steps[0].outcome is StepOutcome.ESCALATED  # in the bio's text: needs review


async def test_an_address_on_another_domain_needs_review() -> None:
    result = await resolve_email(_evidence({"examplecafe@gmail.com": ("footer",)}), fake_context())
    assert (result.value, result.status) == ("examplecafe@gmail.com", Status.NEEDS_REVIEW)


async def test_an_address_nobody_reads_is_never_the_answer() -> None:
    result = await resolve_email(
        _evidence({"noreply@example-cafe.ca": ("email link",)}), fake_context()
    )
    assert result.status is Status.NOT_FOUND


async def test_the_contact_page_is_used_when_the_homepage_has_none() -> None:
    page = ContactPage(
        url=f"{URL}contact",
        contacts=Contacts(
            emails=("info@example-cafe.ca",), email_places={"info@example-cafe.ca": ("footer",)}
        ),
    )
    result = await resolve_email(_evidence({}, page), fake_context())
    assert (result.value, result.status) == ("info@example-cafe.ca", Status.OK)
    assert result.source == "contact page: footer"
