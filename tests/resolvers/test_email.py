"""Tests for the email address."""

from bi2.core.models import ContactPage, Contacts, Evidence, PageInfo, PageKind, Status
from bi2.resolvers.email import resolve_email
from tests.fakes import fake_context

URL = "https://example-cafe.ca/"


def _evidence(
    emails: dict[str, tuple[str, ...]], contact_page: ContactPage | None = None
) -> Evidence:
    return Evidence(
        page=PageInfo(url=URL, final_url=URL, kind=PageKind.OWN_WEBSITE),
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
