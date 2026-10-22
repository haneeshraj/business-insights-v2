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
from bi2.core.providers import ModelRef
from bi2.core.settings import Keys, Settings, keys_from_environment
from bi2.decide.jev import Jev
from bi2.decide.llm import LlmDecider, WithBackup
from bi2.fetch.browser import BrowserChoice, BrowserFetcher
from bi2.fetch.http import HttpDownloader
from bi2.llm.clients import client_for
from bi2.llm.limits import FreeTier
from bi2.llm.routing import Fallback, Searching
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
    Decider, with the configured LLM as its backup, or the LLM alone, on whichever provider
    the settings name. Their answers are kept in
    `kept_answers`, their calls logged in `call_log`, and their day's requests counted in
    `usage_file`, so the free tiers' limits hold across runs. The browser closes when the
    block ends."""
    settings = settings or Settings()
    known = settings.all_providers()
    keys = keys or with_keychain(keys_from_environment(known), known)[0]
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
    """The Decider, the LLM and the second opinion a run uses, from its settings and the keys
    it has: with Jev's key, Jev decides, with the LLM as its backup and its second opinion;
    without it, the LLM decides too."""
    ai = settings.ai
    if not ai.enabled:
        return None, None, None
    limits = FreeTier(usage_file, share=ai.daily_share)
    llm = await _llm(stack, settings, keys, limits, kept, log) if ai.llm else None
    decider: Decider | None = None
    if ai.jev and keys.jev is not None:
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


async def _llm(
    stack: AsyncExitStack,
    settings: Settings,
    keys: Keys,
    limits: FreeTier,
    kept: Path | None,
    log: CallLog | None,
) -> LanguageModel | None:
    """The run's LLM: the model, then its backup, each on its own provider when they differ,
    with web searches sent to the search model when one is set. A model whose provider needs
    a key the run doesn't have is left out."""
    known = settings.all_providers()
    named = settings.llm_models()
    refs = [named[setting] for setting in ("llm_model", "backup_model") if setting in named]
    # Two Gemini models share one client, which asks the second when the first is busy or out
    # of requests, as v2 always has; any other pair is a chain of clients.
    gemini = [ref for ref in refs if known[ref.provider].api == "gemini"]
    pairs: list[tuple[ModelRef, ModelRef | None]]
    if len(refs) == 2 and len(gemini) == 2 and refs[0].provider == refs[1].provider:
        pairs = [(refs[0], refs[1])]
    else:
        pairs = [(ref, None) for ref in refs]
    chain = [
        model
        for ref, backup in pairs
        if (model := await _client(stack, ref, backup, settings, keys, limits, kept, log))
    ]
    main: LanguageModel | None = chain[0] if len(chain) == 1 else Fallback(chain) if chain else None
    if main is not None and "search_model" in named:
        search = await _client(
            stack, named["search_model"], None, settings, keys, limits, kept, log
        )
        if search is not None:
            main = Searching(main, search)
    return main


async def _client(
    stack: AsyncExitStack,
    ref: ModelRef,
    backup: ModelRef | None,
    settings: Settings,
    keys: Keys,
    limits: FreeTier,
    kept: Path | None,
    log: CallLog | None,
) -> LanguageModel | None:
    """One model's client, with its answers kept and its calls logged, or None when its
    provider needs a key the run doesn't have."""
    provider = settings.all_providers()[ref.provider]
    key = keys.get(ref.provider)
    if key is None and provider.needs_key:
        return None
    client = client_for(
        ref,
        provider=provider,
        key=key.get_secret_value() if key else None,
        settings=settings,
        limits=limits,
        backup=backup,
    )
    model: LanguageModel = await stack.enter_async_context(client)
    if kept is not None:
        # Gemini's answers stay where they always were, under the model's bare name, so the
        # answers kept before still match; other providers' go under "provider:model".
        if provider.api == "gemini":
            model = KeptGenerations(model, kept / "gemini", model=ref.model)
        else:
            model = KeptGenerations(model, kept / ref.provider, model=str(ref))
    if log is not None:
        model = LoggedModel(model, log)
    return model
