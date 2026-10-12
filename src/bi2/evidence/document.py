"""The parsed page, and small helpers for reading it."""

from selectolax.lexbor import LexborHTMLParser, LexborNode

from bi2.core.text import clean_space

Document = LexborHTMLParser
Node = LexborNode

# Elements whose content is never shown as text on the page.
_NOT_SHOWN = ["script", "style", "noscript", "template", "iframe", "object"]

# Elements that start a new line of text when the page is drawn.
_BLOCKS = frozenset(
    {
        "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt",
        "figcaption", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr",
        "li", "main", "nav", "ol", "p", "pre", "section", "table", "td", "th", "tr", "ul",
    }
)  # fmt: skip


def parse_html(html: str) -> Document:
    """Parse a page's HTML."""
    return LexborHTMLParser(html)


def attribute(node: Node, name: str) -> str:
    """An attribute's value with whitespace trimmed, or "" when it's missing."""
    return (node.attributes.get(name) or "").strip()


def visible_text(node: Node) -> str:
    """The node's text as a reader would see it: without scripts and styles, and with a line
    break between blocks such as paragraphs and list items.

    Pages loaded in the browser get their text from the browser itself, which also leaves out
    text that CSS hides. This is for pages that weren't.
    """
    copy = node.clone()
    copy.strip_tags(_NOT_SHOWN, recursive=True)
    parts: list[str] = []
    for child in copy.traverse(include_text=True):
        if child.tag == "-text":
            parts.append(child.text_content or "")
        elif child.tag in _BLOCKS:
            parts.append("\n")
    lines = (clean_space(line) for line in "".join(parts).splitlines())
    return "\n".join(line for line in lines if line)
