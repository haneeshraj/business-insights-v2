"""Tests for reading schema.org data."""

import json
from typing import Any

from bi2.core.models import StructuredData
from bi2.evidence.document import parse_html
from bi2.evidence.structured import extract_structured_data

BASE = "https://example-cafe.ca/"


def _read(*blocks: Any, raw: str = "") -> StructuredData:
    scripts = "".join(
        f'<script type="application/ld+json">{json.dumps(block)}</script>' for block in blocks
    )
    html = f"<html><head>{scripts}{raw}</head><body></body></html>"
    return extract_structured_data(parse_html(html), BASE)


def test_reads_an_organization() -> None:
    data = _read(
        {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": "Example Cafe &amp; Bakery",
            "legalName": "Example Cafe Ltd.",
            "logo": {"@type": "ImageObject", "url": "/images/logo.png"},
            "contactPoint": {"@type": "ContactPoint", "telephone": "+1 416-555-0123"},
            "address": {
                "@type": "PostalAddress",
                "streetAddress": "128a Sterling Rd",
                "addressLocality": "Toronto",
                "addressRegion": "ON",
                "postalCode": "M6R 2B7",
                "addressCountry": "Canada",
            },
            "sameAs": ["https://instagram.com/examplecafe", "mailto:hi@example-cafe.ca"],
        }
    )
    assert data.types == ("Organization",)
    assert data.name == "Example Cafe & Bakery"
    assert data.legal_name == "Example Cafe Ltd."
    assert data.logo_url == "https://example-cafe.ca/images/logo.png"
    assert data.telephone == "+1 416-555-0123"
    assert data.address is not None
    assert data.address.text == "128a Sterling Rd, Toronto, ON M6R 2B7, Canada"
    assert (data.address.city, data.address.postal_code) == ("Toronto", "M6R 2B7")
    assert data.address.country == "CA"
    assert data.same_as == ("https://instagram.com/examplecafe",)


def test_picks_the_business_out_of_a_graph_and_fills_in_from_its_other_nodes() -> None:
    data = _read(
        {
            "@graph": [
                {"@type": "WebSite", "name": "Example Brewing", "url": BASE},
                {"@type": "Organization", "name": "Example Brewing", "logo": "/logo.svg"},
                {
                    "@type": "https://schema.org/Brewery",
                    "name": "Example Brewing Co.",
                    "telephone": "416-555-0199",
                    "address": "1 Main St, Toronto",
                },
                {"@type": "Person", "name": "Sam Brewer", "telephone": "416-555-0000"},
            ]
        }
    )
    assert data.types == ("Brewery", "Organization")
    assert data.name == "Example Brewing Co."
    assert data.telephone == "416-555-0199"
    assert data.logo_url == "https://example-cafe.ca/logo.svg"
    assert data.address is not None
    assert data.address.text == "1 Main St, Toronto"


def test_pages_without_the_business_have_no_structured_data() -> None:
    data = _read(
        {"@type": "WebSite", "name": "Example"},
        {"@type": "Product", "name": "Mug", "brand": {"@type": "Brand", "name": "Acme"}},
    )
    assert data == StructuredData()


def test_broken_blocks_are_skipped_and_trailing_commas_forgiven() -> None:
    broken = '<script type="application/ld+json">{"@type": "Organization", </script>'
    trailing = (
        '<script type="application/ld+json">'
        '{"@type": "CafeOrCoffeeShop", "name": "Example Cafe",}</script>'
    )
    data = _read(raw=broken + trailing)
    assert data.name == "Example Cafe"


def test_several_addresses_mean_several_locations() -> None:
    data = _read(
        {
            "@type": "LocalBusiness",
            "name": "Example Cafe",
            "address": [
                {"@type": "PostalAddress", "streetAddress": "1 Main St", "addressCountry": "UK"},
                {"@type": "PostalAddress", "streetAddress": "2 High St"},
            ],
        }
    )
    assert data.address is not None
    assert data.address.street == "1 Main St"
    assert data.address.country == "GB"
    assert data.address.multiple_locations
