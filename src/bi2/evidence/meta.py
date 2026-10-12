"""The page's title and meta tags."""

from bi2.core.models import PageMeta
from bi2.core.text import clean_space
from bi2.core.urls import absolute_url
from bi2.evidence.document import Document, attribute


def _meta(doc: Document, *keys: str) -> str:
    """The first non-empty content among meta tags with these names or properties."""
    for key in keys:
        for node in doc.css(f'meta[property="{key}" i], meta[name="{key}" i]'):
            content = clean_space(attribute(node, "content"))
            if content:
                return content
    return ""


def _title(doc: Document) -> str:
    for node in doc.css("title"):
        parent = node.parent
        if parent is None or parent.tag != "svg":  # an SVG's <title> labels the image only
            return clean_space(node.text())
    return ""


def extract_meta(doc: Document, base_url: str) -> PageMeta:
    """Read the page's title, description, site name and sharing image."""
    image = _meta(doc, "og:image", "og:image:url", "og:image:secure_url", "twitter:image")
    return PageMeta(
        title=_title(doc),
        description=_meta(doc, "description", "og:description", "twitter:description"),
        site_name=_meta(doc, "og:site_name", "application-name", "apple-mobile-web-app-title"),
        og_title=_meta(doc, "og:title", "twitter:title"),
        og_image=absolute_url(base_url, image) if image else None,
    )
