"""URL helpers: absolute links, registrable domains, and keys for comparing image and profile
URLs however they're written."""

import re
from functools import cache
from typing import Final
from urllib.parse import parse_qs, urljoin, urlsplit

import tldextract

_NOT_FOLDER_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_IMAGE_EXTENSION = re.compile(r"\.(png|jpe?g|gif|svg|webp|avif|ico)", re.IGNORECASE)
# Size tags that image CDNs add to file names: logo_400x.png, logo_300x300.png, logo-300x100.png
_SIZE_TAG = re.compile(r"(?:[_-](?:\d+x\d*|\{width\}x))+$", re.IGNORECASE)

# Social profile URLs whose first two path parts name the profile, such as linkedin.com/company/x.
_TWO_PART_PATHS: Final = {"company", "school", "showcase", "channel", "c", "user"}
_SOCIAL_HOST_ALIASES: Final = {"twitter.com": "x.com", "fb.com": "facebook.com"}


@cache
def _domains() -> tldextract.TLDExtract:
    # The public suffix list bundled with tldextract, so nothing is downloaded or cached on disk.
    return tldextract.TLDExtract(cache_dir=None, suffix_list_urls=())


def absolute_url(base: str, href: str) -> str | None:
    """The http or https URL a link points to, or None for any other kind of link, such as
    mailto:, tel:, javascript: or data:."""
    href = href.strip()
    if not href or href.startswith("#"):
        return None
    url = urljoin(base, href)
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return url


def host(url: str) -> str:
    """The URL's host name, lowercased and without "www."."""
    return (urlsplit(url).hostname or "").removeprefix("www.")


def registrable_domain(url: str) -> str:
    """The part of the host that's registered: `shop.example.co.uk` gives `example.co.uk`.
    Hosts without a public suffix, such as IP addresses, are returned whole."""
    return _domains()(url).top_domain_under_public_suffix or host(url)


def public_suffix(url: str) -> str:
    """The host's public suffix, such as "com", "ca" or "co.uk"; empty for IP addresses."""
    return _domains()(url).suffix


def site_folder(url: str) -> str:
    """A folder name for a page's files, such as `example-cafe.ca_menu`."""
    parts = urlsplit(url)
    name = (parts.netloc.removeprefix("www.") + parts.path).strip("/")
    return _NOT_FOLDER_SAFE.sub("_", name) or "page"


def same_site(a: str, b: str) -> bool:
    """Whether two URLs are on the same registrable domain."""
    return registrable_domain(a) == registrable_domain(b)


def image_key(url: str) -> str:
    """A key under which the same image matches however its URL is written.

    Ignores the scheme, "www.", query strings, CDN size tags in the file name, and anything a
    CDN appends after the file name (such as Wix's `/v1/fill/...`).
    """
    parts = urlsplit(url)
    path = parts.path
    extension = _IMAGE_EXTENSION.search(path)
    if extension:
        stem = _SIZE_TAG.sub("", path[: extension.start()])
        path = f"{stem}.{extension.group(1).lower()}"
    return parts.netloc.casefold().removeprefix("www.") + path.casefold()


def social_key(url: str) -> str:
    """A key under which the same social profile matches however its URL is written.

    Ignores the scheme, "www." and "m.", treats twitter.com as x.com and every pinterest.* as
    pinterest.com, and keeps only the part of the path that names the profile.
    """
    parts = urlsplit(url)
    name = parts.netloc.casefold().removeprefix("www.").removeprefix("m.")
    name = (
        "pinterest.com" if name.startswith("pinterest.") else _SOCIAL_HOST_ALIASES.get(name, name)
    )
    segments = [segment for segment in parts.path.split("/") if segment]
    if not segments:
        return name
    keep = 2 if len(segments) > 1 and segments[0].casefold() in _TWO_PART_PATHS else 1
    key = f"{name}/{'/'.join(segments[:keep])}"
    if segments[0] == "profile.php":  # Facebook's numbered profiles keep the number in the query
        key += "?id=" + parse_qs(parts.query).get("id", [""])[0]
    return key.casefold()
