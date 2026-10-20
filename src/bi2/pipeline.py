"""The per-site workflow: fetch the site, build its Evidence, run the resolvers and return a
SiteResult.

It depends only on core, evidence and resolvers, and gets everything else from the RunContext.
"""

import asyncio
import time
import tomllib
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from functools import cache
from importlib.resources import files
from typing import Any, Final

from bi2 import __version__
from bi2.core.context import RunContext
from bi2.core.errors import FetchError, LookupUnavailable, UnsafeUrl
from bi2.core.models import (
    FIELD_NAMES,
    Evidence,
    FieldResult,
    PageInfo,
    PageSnapshot,
    SiteResult,
    Status,
    StepOutcome,
    StepRecord,
    Versions,
)
from bi2.core.ports import Downloader
from bi2.core.urls import site_folder
from bi2.evidence.build import build_contact_page, build_evidence
from bi2.resolvers import RESOLVERS
from bi2.resolvers.address import address_lines
from bi2.resolvers.cascade import Escalate, Resolved, Step, not_built_yet, run_cascade
from bi2.resolvers.email import shows_an_email
from bi2.resolvers.known import KNOWN_STEPS

# Statuses a site answers with when it won't give its page, like a bot check's "Access
# denied". A missing page (404) can still show the site's own header and footer.
_REFUSED: Final = frozenset({401, 403, 429})


@cache
def _data_versions() -> dict[str, str]:
    """The version of each data file the evidence is built with."""
    versions = {}
    for name in ("countries", "platforms", "schema_types", "mcc_synonyms", "models"):
        text = files("bi2.data").joinpath(f"{name}.toml").read_text(encoding="utf-8")
        versions[name] = str(tomllib.loads(text)["version"])
    return versions


def _versions() -> Versions:
    return Versions(pipeline=__version__, data=_data_versions())


class _BrowserCopiesFirst:
    """Gives the browser's copy of an image when it kept one, and downloads it otherwise. Some
    sites refuse a separate download of an image they gave the browser to show the page."""

    def __init__(self, copies: Mapping[str, bytes], downloader: Downloader) -> None:
        self._copies = copies
        self._downloader = downloader

    async def download(self, url: str, *, max_bytes: int, referer: str | None = None) -> bytes:
        copy = self._copies.get(url)
        if copy is not None and len(copy) <= max_bytes:
            return copy
        return await self._downloader.download(url, max_bytes=max_bytes, referer=referer)


async def _with_contact_page(ev: Evidence, ctx: RunContext) -> Evidence:
    """The evidence with the contact page's details too, when the homepage doesn't show a
    phone number, an email address that could be the business's general one and a street
    address, and links a contact page. A contact page that won't load is left out, and the
    homepage's evidence stands on its own."""
    has_address = ev.structured.address is not None or bool(
        address_lines(ev.text.footer) or address_lines(ev.text.main)
    )
    if (ev.contacts.phones and shows_an_email(ev) and has_address) or not ev.contact_pages:
        return ev
    try:
        snapshot = await ctx.fetcher.fetch(ev.contact_pages[0])
    except FetchError:
        return ev
    page = build_contact_page(snapshot)
    return ev.model_copy(update={"contact_page": page, "extra_pages": (*ev.extra_pages, page.url)})


def _page_couldnt_be_read(why: str) -> Step[Any]:
    """A first step that fails with why the page couldn't be read, for the audit trail."""

    async def load_page(ev: Evidence, ctx: RunContext) -> Resolved[Any] | Escalate:
        raise FetchError(why)

    return load_page


async def analyze_unreadable(
    url: str,
    why: str,
    ctx: RunContext,
    *,
    final_url: str | None = None,
    screenshot: bytes | None = None,
) -> tuple[SiteResult, Evidence]:
    """The result for a page that couldn't be read, like one behind a bot check.

    Each field comes from what Wikidata knows about the business, when it knows it, and is
    otherwise an error that says why the page couldn't be read. A site Wikidata doesn't know
    fails as a whole."""
    started = time.monotonic()
    try:
        known = await ctx.knowledge.business_with_website(final_url or url)
    except LookupUnavailable:
        known = None
    ev = Evidence(page=PageInfo(url=url, final_url=final_url), unreadable=why, known=known)
    folder = site_folder(url)
    if screenshot:
        saved = await ctx.files.save(f"{folder}/screenshot.jpg", screenshot)
        ev = ev.model_copy(update={"screenshot_file": saved})
    first = _page_couldnt_be_read(why)
    fields: dict[str, FieldResult[Any]] = {}
    for name in FIELD_NAMES:
        steps = [first, KNOWN_STEPS[name]] if known and name in KNOWN_STEPS else [first]
        fields[name] = await run_cascade(steps, ev, ctx)
    if all(field.status is Status.ERROR for field in fields.values()):
        return failed_result(url, why, time.monotonic() - started), ev
    result = SiteResult.model_validate(
        {
            "page": ev.page,
            "analyzed_at": datetime.now(UTC),
            "seconds": round(time.monotonic() - started, 2),
            **fields,
            "versions": _versions(),
        }
    )
    await ctx.files.save(f"{folder}/evidence.json", ev.model_dump_json(indent=2).encode())
    await ctx.files.save(f"{folder}/result.json", result.model_dump_json(indent=2).encode())
    return result, ev


async def analyze_snapshot(snapshot: PageSnapshot, ctx: RunContext) -> tuple[SiteResult, Evidence]:
    """Everything v2 can tell about a loaded page. Saves the screenshot, the evidence and the
    result in the site's folder, along with the logo when one is found. A page the site
    refused, like a bot check's "Access denied", is analyzed as one that couldn't be read."""
    started = time.monotonic()
    if snapshot.status_code in _REFUSED:
        why = f"the site refused the page ({snapshot.status_code}), likely a bot check"
        return await analyze_unreadable(
            snapshot.url, why, ctx, final_url=snapshot.final_url, screenshot=snapshot.screenshot
        )
    if snapshot.image_copies:
        ctx = replace(ctx, downloader=_BrowserCopiesFirst(snapshot.image_copies, ctx.downloader))
    ev = await _with_contact_page(build_evidence(snapshot), ctx)
    # What Wikidata knows about the business: free facts, like a big brand's head office and
    # logo file, for when the page doesn't give them.
    try:
        known = await ctx.knowledge.business_with_website(snapshot.final_url or snapshot.url)
    except LookupUnavailable:
        known = None
    if known is not None:
        ev = ev.model_copy(update={"known": known})
    folder = site_folder(snapshot.url)
    if snapshot.screenshot:
        saved = await ctx.files.save(f"{folder}/screenshot.jpg", snapshot.screenshot)
        ev = ev.model_copy(update={"screenshot_file": saved})
    # The fields don't depend on each other, so they're resolved at the same time.
    names = list(RESOLVERS)
    answers = await asyncio.gather(*(RESOLVERS[name](ev, ctx) for name in names))
    fields: dict[str, FieldResult[Any]] = dict(zip(names, answers, strict=True))
    for name in FIELD_NAMES:
        fields.setdefault(name, not_built_yet())
    result = SiteResult.model_validate(
        {
            "page": ev.page,
            "analyzed_at": datetime.now(UTC),
            "seconds": round(time.monotonic() - started, 2),
            **fields,
            "versions": _versions(),
        }
    )
    await ctx.files.save(f"{folder}/evidence.json", ev.model_dump_json(indent=2).encode())
    await ctx.files.save(f"{folder}/result.json", result.model_dump_json(indent=2).encode())
    return result, ev


def failed_result(url: str, error: str, seconds: float) -> SiteResult:
    """The result for a site that couldn't be analyzed at all: every field is an error."""
    step = StepRecord(step="load_page", outcome=StepOutcome.FAILED, detail=error)
    failed = FieldResult[Any](status=Status.ERROR, steps=(step,))
    return SiteResult.model_validate(
        {
            "page": PageInfo(url=url),
            "analyzed_at": datetime.now(UTC),
            "seconds": round(seconds, 2),
            **dict.fromkeys(FIELD_NAMES, failed),
            "error": error,
            "versions": _versions(),
        }
    )


async def analyze_url(url: str, ctx: RunContext) -> tuple[SiteResult, Evidence | None]:
    """Load a page and analyze it. A page that can't be loaded is analyzed as one that couldn't
    be read: from what Wikidata knows, or else as a failed result."""
    started = time.monotonic()
    try:
        snapshot = await ctx.fetcher.fetch(url)
    except UnsafeUrl as exc:  # nothing v2 refuses to visit is looked up either
        return failed_result(url, str(exc), time.monotonic() - started), None
    except FetchError as exc:
        result, ev = await analyze_unreadable(url, str(exc), ctx)
        seconds = round(time.monotonic() - started, 2)
        return result.model_copy(update={"seconds": seconds}), None if result.error else ev
    result, ev = await analyze_snapshot(snapshot, ctx)
    return result.model_copy(update={"seconds": round(time.monotonic() - started, 2)}), ev
