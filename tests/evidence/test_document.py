"""Tests for the helpers that read a parsed page."""

from bi2.evidence.document import attribute, parse_html, visible_text


def test_visible_text_skips_scripts_and_keeps_blocks_apart() -> None:
    doc = parse_html(
        "<body><div>Call <b>416</b>-555-0123<script>var hidden = 1;</script></div>"
        "<p>Open<br>daily</p><style>p { color: red }</style></body>"
    )
    assert doc.body is not None
    assert visible_text(doc.body) == "Call 416-555-0123\nOpen\ndaily"


def test_attribute_is_trimmed_and_empty_when_missing() -> None:
    link = parse_html('<a href=" /menu " download>Menu</a>').css_first("a")
    assert link is not None
    assert attribute(link, "href") == "/menu"
    assert attribute(link, "download") == ""
    assert attribute(link, "title") == ""
