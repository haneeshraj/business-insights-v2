"""Tests for the page's text by region."""

from bi2.core.models import TextRegions
from bi2.evidence.document import parse_html
from bi2.evidence.text import extract_text_regions, shorten
from tests.factories import page_snapshot

PAGE = """<html><body>
<header><a href="/">Example Cafe</a><nav><a href="/menu">Menu</a></nav></header>
<main>
  <p>Coffee and pastries.</p>
  <article><header>Our new roast</header><p>Tasting notes.</p></article>
</main>
<footer><p>128a Sterling Rd, Toronto</p><p>&copy; 2026 Example Cafe Ltd.</p></footer>
</body></html>"""


def _regions(html: str) -> TextRegions:
    return extract_text_regions(page_snapshot(html), parse_html(html))


def test_splits_the_page_into_header_main_and_footer() -> None:
    text = _regions(PAGE)
    assert text.header == "Example Cafe\nMenu"  # an article's own header isn't the site's
    assert text.main == "Coffee and pastries.\nOur new roast\nTasting notes."
    assert text.footer == "128a Sterling Rd, Toronto\n© 2026 Example Cafe Ltd."


def test_without_a_main_element_the_rest_of_the_page_is_the_main_text() -> None:
    html = (
        "<body><div class='site-header'>Example Cafe</div><p>Coffee.</p><footer>Bye</footer></body>"
    )
    assert _regions(html) == TextRegions(header="Example Cafe", main="Coffee.", footer="Bye")


def test_text_the_browser_read_is_used_when_there_is_some() -> None:
    from_browser = TextRegions(header="Shown", main="Only what was visible", footer="")
    snapshot = page_snapshot(PAGE, text=from_browser)
    assert extract_text_regions(snapshot, parse_html(PAGE)) == from_browser


def test_shortening_keeps_the_end_of_the_footer() -> None:
    long = TextRegions(header="h" * 3_000, main="m" * 20_000, footer="links " * 2_000 + "(c) 2026")
    short = shorten(long)
    assert len(short.header) == 2_000
    assert len(short.main) == 10_000
    assert short.footer.endswith("(c) 2026")
    assert len(short.footer) == 4_000
