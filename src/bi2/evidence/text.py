"""The page's visible text, split into the header, the main content and the footer."""

from typing import Final

from bi2.core.models import PageSnapshot, TextRegions
from bi2.evidence.document import Document, Node, visible_text

# The same regions the browser reads, in bi2/fetch/browser.py.
_HEADER: Final = "header, [role=banner], #header, #site-header, .site-header"
_FOOTER: Final = "footer, [role=contentinfo], #footer, #site-footer, .site-footer"
_MAIN: Final = "main, [role=main]"

# How many characters of each region the evidence keeps for models to read. Contact details
# are taken from the full text before it's cut.
_KEPT: Final = {"header": 2_000, "main": 10_000, "footer": 4_000}


def _outermost(doc: Document, selector: str) -> list[Node]:
    """Elements that match, leaving out those inside another match or inside an article
    (a blog post's own header isn't the site's)."""
    matches = doc.css(selector)
    matched = {node.mem_id for node in matches}
    found = []
    for node in matches:
        parent = node.parent
        while parent is not None and parent.tag not in ("html", "article"):
            if parent.mem_id in matched:
                break
            parent = parent.parent
        if parent is None or parent.tag == "html":
            found.append(node)
    return found


def _joined(nodes: list[Node]) -> str:
    return "\n".join(text for node in nodes if (text := visible_text(node)))


def _from_html(doc: Document) -> TextRegions:
    header = _joined(_outermost(doc, _HEADER))
    footer = _joined(_outermost(doc, _FOOTER))
    mains = _outermost(doc, _MAIN)
    if mains:
        main = _joined(mains)
    else:
        main = visible_text(doc.body) if doc.body else ""
        for part in (header, footer):
            if part:
                main = main.replace(part, "")
    return TextRegions(header=header, main=main.strip(), footer=footer)


def extract_text_regions(snapshot: PageSnapshot, doc: Document) -> TextRegions:
    """The page's full visible text by region: what the browser showed, or else what the
    HTML holds."""
    return snapshot.text if snapshot.text is not None else _from_html(doc)


def shorten(text: TextRegions) -> TextRegions:
    """The text the evidence keeps, with each region cut to a length models read cheaply.
    Footers keep their end, where the address and the copyright line usually are."""
    return TextRegions(
        header=text.header[: _KEPT["header"]],
        main=text.main[: _KEPT["main"]],
        footer=text.footer[-_KEPT["footer"] :],
    )
