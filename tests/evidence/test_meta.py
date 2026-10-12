"""Tests for reading the title and meta tags."""

from bi2.core.models import PageMeta
from bi2.evidence.document import parse_html
from bi2.evidence.meta import extract_meta

BASE = "https://example-cafe.ca/"

PAGE = """<!doctype html>
<html><head>
<title> Example Cafe | Coffee in Toronto </title>
<meta name="Description" content="Coffee and pastries on Queen St.">
<meta property="og:site_name" content="Example Cafe">
<meta property="og:title" content="Example Cafe">
<meta property="og:image" content="/images/share.png">
</head><body><p>Hello</p></body></html>"""


def test_reads_the_title_and_meta_tags() -> None:
    meta = extract_meta(parse_html(PAGE), BASE)
    assert meta.title == "Example Cafe | Coffee in Toronto"
    assert meta.description == "Coffee and pastries on Queen St."
    assert meta.site_name == "Example Cafe"
    assert meta.og_title == "Example Cafe"
    assert meta.og_image == "https://example-cafe.ca/images/share.png"


def test_a_page_without_tags_has_empty_meta() -> None:
    html = "<html><body><svg><title>Menu icon</title></svg></body></html>"
    assert extract_meta(parse_html(html), BASE) == PageMeta()


def test_falls_back_to_other_tags_and_skips_unusable_images() -> None:
    html = """<head>
    <meta name="application-name" content="Example Cafe">
    <meta name="twitter:title" content="Example Cafe, Toronto">
    <meta property="og:image" content="data:image/png;base64,AAAA">
    </head>"""
    meta = extract_meta(parse_html(html), BASE)
    assert meta.site_name == "Example Cafe"
    assert meta.og_title == "Example Cafe, Toronto"
    assert meta.og_image is None
