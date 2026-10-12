"""The per-site workflow: fetch the site, build its Evidence, run the resolvers and return a
SiteResult.

It depends only on core, evidence and resolvers, and gets everything else from the RunContext.
"""

import asyncio
import time
import tomllib
from datetime import UTC, datetime
from functools import cache
from importlib.resources import files
from typing import Any

from bi2 import __version__
from bi2.core.context import RunContext
from bi2.core.errors import FetchError
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
from bi2.core.urls import site_folder
from bi2.evidence.build import build_evidence
from bi2.resolvers import RESOLVERS
from bi2.resolvers.cascade import not_built_yet


@cache
def _data_versions() -> dict[str, str]:
    """The version of each data file the evidence is built with."""
    versions = {}
    for name in ("countries", "platforms"):
        text = files("bi2.data").joinpath(f"{name}.toml").read_text(encoding="utf-8")
        versions[name] = str(tomllib.loads(text)["version"])
    return versions


def _versions() -> Versions:
    return Versions(pipeline=__version__, data=_data_versions())


async def analyze_snapshot(snapshot: PageSnapshot, ctx: RunContext) -> tuple[SiteResult, Evidence]:
    """Everything v2 can tell about a loaded page. Saves the screenshot, the evidence and the
    result in the site's folder, along with the logo when one is found."""
    started = time.monotonic()
    ev = build_evidence(snapshot)
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
    """Load a page and analyze it. A page that can't be loaded gives a failed result."""
    started = time.monotonic()
    try:
        snapshot = await ctx.fetcher.fetch(url)
    except FetchError as exc:
        return failed_result(url, str(exc), time.monotonic() - started), None
    result, ev = await analyze_snapshot(snapshot, ctx)
    return result.model_copy(update={"seconds": round(time.monotonic() - started, 2)}), ev
