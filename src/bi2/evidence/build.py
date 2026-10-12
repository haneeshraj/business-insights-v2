"""Puts a page's evidence together, from what loading the page captured."""

from bi2.core.models import Evidence, PageInfo, PageKind, PageSnapshot
from bi2.evidence.document import parse_html
from bi2.evidence.meta import extract_meta


def build_evidence(snapshot: PageSnapshot) -> Evidence:
    """Everything the field resolvers need from a loaded page, gathered without model calls."""
    doc = parse_html(snapshot.html)
    base = snapshot.final_url
    refused = snapshot.status_code is not None and snapshot.status_code >= 400
    return Evidence(
        page=PageInfo(
            url=snapshot.url,
            final_url=snapshot.final_url,
            kind=PageKind.UNKNOWN if refused else PageKind.OWN_WEBSITE,
        ),
        meta=extract_meta(doc, base),
    )
