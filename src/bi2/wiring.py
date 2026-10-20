"""Builds a RunContext from real implementations: `local_context` for the terminal app, and
later `hosted_context` for the website's workers.

This is where infrastructure is chosen and connected to the ports. Only entry points import
this module; logic and infrastructure never do.
"""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from bi2.adapters.local.answers import (
    CallLog,
    KeptDecisions,
    KeptGenerations,
    LoggedDecider,
    LoggedModel,
)
from bi2.adapters.local.downloads import KeptDownloads
from bi2.adapters.local.files import LocalFiles
from bi2.adapters.local.keys import with_keychain
from bi2.adapters.local.lookups import KeptLookups, KeptPlaces
from bi2.adapters.local.snapshots import SavedPages
from bi2.core.context import RunContext
from bi2.core.errors import FetchError
from bi2.core.models import PageSnapshot
from bi2.core.ports import Decider, Downloader, Fetcher, Geocoder, KnowledgeBase, LanguageModel
from bi2.core.settings import Keys, Settings, keys_from_environment
from bi2.decide.jev import Jev
from bi2.decide.llm import LlmDecider, WithBackup
from bi2.fetch.browser import BrowserChoice, BrowserFetcher
from bi2.fetch.http import HttpDownloader
from bi2.llm.gemini import Gemini
from bi2.llm.limits import FreeTier
from bi2.services.nominatim import Nominatim
from bi2.services.wikidata import Wikidata


class _NoPages:
    """The fetcher for a run that loads no pages and has none saved."""

    async def fetch(self, url: str) -> PageSnapshot:
        raise FetchError(f"this run loads no pages, so {url} isn't loaded")


@asynccontextmanager
async def local_context(
    out: Path,
    *,
    load_pages: bool = True,
    browser: BrowserChoice = "auto",
    timeout_s: float = 20.0,
    allow_private: bool = False,  # only for tests that serve pages from this machine
    kept_downloads: Path | None = None,
    saved_pages: Path | None = None,
    kept_lookups: Path | None = None,
    kept_answers: Path | None = None,
    usage_file: Path | None = None,
    call_log: CallLog | None = None,
    keys: Keys | None = None,
    settings: Settings | None = None,
) -> AsyncIterator[RunContext]:
    """A RunContext for the terminal app: a browser, a downloader, Wikidata, and files under
    `out`. With `saved_pages` instead of loading pages, the pages saved in that folder are read,
    such as each site's contact page. With `kept_downloads`, every file downloaded is kept in
    that folder and reused on later runs, and with `kept_lookups`, every Wikidata answer.

    Models join when there's a key for them and model calls aren't turned off: Jev as the
    Decider, with Gemini as its backup, or Gemini alone. Their answers are kept in
    `kept_answers`, their calls logged in `call_log`, and their day's requests counted in
    `usage_file`, so the free tiers' limits hold across runs. The browser closes when the
    block ends."""
    settings = settings or Settings()
    keys = keys or with_keychain(keys_from_environment())[0]
    async with AsyncExitStack() as stack:
        fetcher: Fetcher = SavedPages(saved_pages) if saved_pages is not None else _NoPages()
        if load_pages:
            fetcher = await stack.enter_async_context(
                BrowserFetcher(timeout_s=timeout_s, browser=browser, allow_private=allow_private)
            )
        downloader: Downloader = await stack.enter_async_context(
            HttpDownloader(allow_private=allow_private)
        )
        if kept_downloads is not None:
            downloader = KeptDownloads(downloader, kept_downloads)
        knowledge: KnowledgeBase = await stack.enter_async_context(Wikidata())
        geocoder: Geocoder = await stack.enter_async_context(Nominatim())
        if kept_lookups is not None:
            knowledge = KeptLookups(knowledge, kept_lookups)
            geocoder = KeptPlaces(geocoder, kept_lookups / "places")
        decider, llm, second = await _models(
            stack, settings, keys, kept_answers, usage_file, call_log
        )
        yield RunContext(
            settings=settings,
            fetcher=fetcher,
            downloader=downloader,
            files=LocalFiles(out),
            knowledge=knowledge,
            geocoder=geocoder,
            decider=decider,
            llm=llm,
            second=second,
        )


async def _models(
    stack: AsyncExitStack,
    settings: Settings,
    keys: Keys,
    kept: Path | None,
    usage_file: Path | None,
    log: CallLog | None,
) -> tuple[Decider | None, LanguageModel | None, Decider | None]:
    """The Decider, the LLM and the second opinion a run uses, from the keys it has: with both
    keys, Jev decides, with Gemini as its backup and its second opinion."""
    ai = settings.ai
    if not ai.enabled:
        return None, None, None
    limits = FreeTier(usage_file, share=ai.daily_share)
    llm: LanguageModel | None = None
    if keys.gemini is not None and ai.gemini:
        gemini = Gemini(
            keys.gemini.get_secret_value(),
            limits=limits,
            model=ai.llm_model,
            backup=ai.backup_model,
        )
        llm = await stack.enter_async_context(gemini)
        if kept is not None:
            llm = KeptGenerations(llm, kept / "gemini", model=ai.llm_model)
        if log is not None:
            llm = LoggedModel(llm, log)
    decider: Decider | None = None
    if keys.jev is not None:
        jev = Jev(keys.jev.get_secret_value(), limits=limits, model=ai.jev_model)
        decider = await stack.enter_async_context(jev)
        if kept is not None:
            decider = KeptDecisions(decider, kept / "jev", model=ai.jev_model)
        if log is not None:
            decider = LoggedDecider(decider, log)
    second: Decider | None = None
    if llm is not None:
        backup = LlmDecider(llm)
        if decider is None:
            decider = backup
        else:
            decider, second = WithBackup(decider, backup), backup
    return decider, llm, second
