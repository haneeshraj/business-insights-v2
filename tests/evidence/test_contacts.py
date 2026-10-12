"""Tests for finding contact details."""

from bi2.core.models import TextRegions
from bi2.evidence.contacts import (
    copyright_holder,
    extract_contacts,
    find_copyright_line,
    find_emails,
    find_phones,
    phone_countries,
)
from bi2.evidence.document import parse_html

LINKS = parse_html(
    '<a href="tel:+1-416-555-0199">Call</a>'
    '<a href="mailto:Hello@Example-Cafe.ca?subject=Hi">Email</a>'
    '<img src="logo@2x.png">'
)
TEXT = TextRegions(
    header="Call us at (416) 555-0123",
    main="Order 12345 ships in 2-3 days. Questions? 1-800-555-0100",
    footer="128a Sterling Rd, Toronto ON M6R 2B7\n© 2026 Example Cafe Ltd. All rights reserved.\n"
    "info@example-cafe.ca | logo@2x.png",
)


def test_phones_come_out_in_e164_most_telling_first() -> None:
    phones = find_phones(LINKS, TEXT, structured="416.555.0123", region="CA")
    assert phones == {
        "+14165550123": ["structured data", "header"],
        "+14165550199": ["call link"],
        "+18005550100": ["main text"],
    }


def test_phone_countries_skip_toll_free_numbers() -> None:
    assert phone_countries(["+14165550123", "+18005550100", "+442079460018"]) == ["CA", "GB"]


def test_numbers_without_a_country_code_are_read_as_the_regions() -> None:
    london = TextRegions(footer="Ring us on 020 7946 0018")
    assert list(find_phones(parse_html(""), london, structured=None, region="GB")) == [
        "+442079460018"
    ]
    assert find_phones(parse_html(""), london, structured=None, region=None) == {}


def test_emails_come_from_links_and_text_without_image_names() -> None:
    assert find_emails(LINKS, TEXT) == ["hello@example-cafe.ca", "info@example-cafe.ca"]


def test_the_copyright_line_and_its_holder() -> None:
    line = find_copyright_line(TEXT)
    assert line == "© 2026 Example Cafe Ltd. All rights reserved."
    assert copyright_holder(line) == "Example Cafe Ltd"
    assert copyright_holder("Copyright © 2019-2026 Bar Volo | Powered by Squarespace") == "Bar Volo"
    worded = TextRegions(footer="Copyright Policy\nCopyright 2025 Example Brewing")
    assert find_copyright_line(worded) == "Copyright 2025 Example Brewing"


def test_extract_contacts_puts_it_all_together() -> None:
    contacts = extract_contacts(
        LINKS, TEXT, structured_phone=None, region="CA", postcodes=["M6R 2B7", "M6R 2B7"]
    )
    assert contacts.phones[0] == "+14165550199"
    assert contacts.postcodes == ("M6R 2B7",)
    assert contacts.copyright_line is not None
