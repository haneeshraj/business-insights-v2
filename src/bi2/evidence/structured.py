"""What the page's schema.org data says about the business.

Sites add this data for search engines, and it often states the business's name, logo, phone
number, address and social profiles outright. Only JSON-LD is read, the format nearly every
site uses.
"""

import html
import json
import re
from collections.abc import Callable, Iterator
from typing import Any, Final

from bi2.core.models import Address, StructuredData
from bi2.core.text import clean_space, names_match
from bi2.core.urls import absolute_url
from bi2.evidence.countries import country_code
from bi2.evidence.document import Document

# schema.org types that describe something other than the business itself.
_NOT_THE_BUSINESS: Final = frozenset(
    {
        "AggregateOffer", "AggregateRating", "Answer", "Article", "BlogPosting", "Brand",
        "BreadcrumbList", "CollectionPage", "ContactPage", "ContactPoint", "Country",
        "EntryPoint", "Event", "FAQPage", "GeoCoordinates", "ImageObject", "ItemList",
        "ListItem", "Menu", "MenuItem", "MenuSection", "NewsArticle", "Offer",
        "OpeningHoursSpecification", "Person", "PostalAddress", "Product", "ProfilePage",
        "Question", "Rating", "ReadAction", "Recipe", "Review", "SearchAction", "Service",
        "SiteNavigationElement", "VideoObject", "WebPage", "WebSite",
    }
)  # fmt: skip

# schema.org types for businesses and organizations: Organization and its many subtypes.
_BUSINESS_TYPE: Final = re.compile(
    r"(Organization|Corporation|Business|Store|Shop|Restaurant|Brewery|Winery|Distillery|"
    r"Bakery|CafeOrCoffeeShop|BarOrPub|Hotel|Motel|Resort|Salon|Spa|Gym|HealthClub|Club|"
    r"Agency|Service|Clinic|Dentist|Physician|Pharmacy|Attorney|Plumber|Electrician|Airline|"
    r"CollegeOrUniversity|School|Library|Museum|Theater|Center|Dealer|Repair|BodyShop)$"
)

# Trailing commas, which some sites leave in their JSON-LD and the JSON parser rejects.
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def _blocks(doc: Document) -> Iterator[Any]:
    """Each JSON-LD block on the page that can be read."""
    for script in doc.css('script[type="application/ld+json" i]'):
        source = script.text().strip().removeprefix("<!--").removesuffix("-->")
        for attempt in (source, _TRAILING_COMMA.sub(r"\1", source)):
            try:
                yield json.loads(attempt, strict=False)
                break
            except json.JSONDecodeError:
                continue


def _nodes(value: Any) -> Iterator[dict[str, Any]]:
    """Every object in a JSON-LD block, including objects nested in others or in @graph."""
    if isinstance(value, list):
        for item in value:
            yield from _nodes(item)
    elif isinstance(value, dict):
        yield value
        for item in value.values():
            if isinstance(item, dict | list):
                yield from _nodes(item)


def _types(node: dict[str, Any]) -> tuple[str, ...]:
    raw = node.get("@type")
    values = raw if isinstance(raw, list) else [raw]
    # Types can be written as URLs or with a prefix: "https://schema.org/Brewery", "schema:Brewery".
    return tuple(
        value.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
        for value in values
        if isinstance(value, str) and value
    )


def _text(value: Any) -> str:
    """A text value, which JSON-LD may write as a string, a list or an object."""
    if isinstance(value, str):
        return clean_space(html.unescape(value))
    if isinstance(value, list):
        return next((text for item in value if (text := _text(item))), "")
    if isinstance(value, dict):
        return _text(value.get("@value") or value.get("name") or "")
    return ""


def _url(value: Any, base: str) -> str | None:
    if isinstance(value, str):
        return absolute_url(base, value)
    if isinstance(value, list):
        return next((url for item in value if (url := _url(item, base))), None)
    if isinstance(value, dict):  # an ImageObject
        return _url(value.get("url") or value.get("contentUrl") or "", base)
    return None


def _score(node: dict[str, Any]) -> int:
    """How likely the node is to describe the business; 0 when it can't be the business."""
    types = _types(node)
    if not types or any(kind in _NOT_THE_BUSINESS for kind in types):
        return 0
    if not _name(node):
        return 0
    business = any(_BUSINESS_TYPE.search(kind) for kind in types)
    details = ("logo", "telephone", "address", "sameAs", "url", "legalName", "contactPoint")
    return 1 + 3 * business + sum(1 for key in details if node.get(key))


def _telephone(node: dict[str, Any]) -> str:
    phone = _text(node.get("telephone"))
    if phone:
        return phone
    points = node.get("contactPoint")
    for point in points if isinstance(points, list) else [points]:
        if isinstance(point, dict) and (phone := _text(point.get("telephone"))):
            return phone
    return ""


def _address(value: Any) -> Address | None:
    if isinstance(value, list):
        found = [address for item in value if (address := _address(item))]
        if len(found) > 1:
            return found[0].model_copy(update={"multiple_locations": True})
        return found[0] if found else None
    if isinstance(value, str):
        text = clean_space(html.unescape(value))
        return Address(text=text) if text else None
    if not isinstance(value, dict):
        return None
    street = _text(value.get("streetAddress"))
    city = _text(value.get("addressLocality"))
    region = _text(value.get("addressRegion"))
    postal_code = _text(value.get("postalCode"))
    country = _text(value.get("addressCountry"))
    text = ", ".join(
        part
        for part in (street, city, " ".join(filter(None, (region, postal_code))), country)
        if part
    )
    if not text:
        return None
    return Address(
        text=text,
        street=street or None,
        city=city or None,
        region=region or None,
        postal_code=postal_code or None,
        country=country_code(country) if country else None,
    )


def _same_as(node: dict[str, Any], base: str) -> list[str]:
    raw = node.get("sameAs")
    values = raw if isinstance(raw, list) else [raw]
    return [
        url for value in values if isinstance(value, str) and (url := absolute_url(base, value))
    ]


def _name(node: dict[str, Any]) -> str:
    return _text(node.get("name")) or _text(node.get("legalName"))


def _first[T](nodes: list[dict[str, Any]], read: Callable[[dict[str, Any]], T]) -> T | None:
    """The first non-empty value read from these nodes."""
    return next((found for node in nodes if (found := read(node))), None)


def extract_structured_data(doc: Document, base_url: str) -> StructuredData:
    """Read what the page's JSON-LD says about the business.

    The node most likely to be the business is used, and details it lacks are taken from
    other nodes with the same name, such as an Organization with the logo and a LocalBusiness
    with the address.
    """
    nodes = [node for block in _blocks(doc) for node in _nodes(block) if _score(node)]
    if not nodes:
        return StructuredData()
    best = max(nodes, key=_score)  # the first of the best, in page order
    same = [best] + [n for n in nodes if n is not best and names_match(_name(n), _name(best))]
    types = list(dict.fromkeys(kind for node in same for kind in _types(node)))
    same_as = list(dict.fromkeys(url for node in same for url in _same_as(node, base_url)))
    return StructuredData(
        types=tuple(types),
        name=_text(best.get("name")) or None,
        legal_name=_first(same, lambda node: _text(node.get("legalName"))) or None,
        logo_url=_first(same, lambda node: _url(node.get("logo"), base_url)),
        telephone=_first(same, _telephone) or None,
        address=_first(same, lambda node: _address(node.get("address"))),
        same_as=tuple(same_as),
    )
