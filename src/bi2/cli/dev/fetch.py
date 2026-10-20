"""`bi2 dev fetch`: load pages in the browser and show what it captured."""

import asyncio
import time
from collections import Counter
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel, ConfigDict
from rich.console import Console
from rich.table import Table

from bi2.adapters.local.snapshots import save_extra_page, save_snapshot
from bi2.cli.options import DEFAULT_CONCURRENCY, AllowPrivate, Browser, Timeout
from bi2.core.errors import BrowserUnavailable, FetchError, PageTimeout, UnsafeUrl
from bi2.core.models import PageSnapshot, RenderedImage
from bi2.evaluation.gold import load_gold_set
from bi2.evidence.build import build_evidence
from bi2.fetch.browser import BrowserFetcher


class FetchCheck(BaseModel):
    """How loading one site went."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str
    outcome: str  # loaded, refused, timed out, unsafe or failed
    status_code: int | None = None
    seconds: float
    images: int = 0
    final_url: str = ""
    browser: str = ""  # the browser that loaded it
    detail: str = ""
    contact_page: str = ""  # the contact page saved with it, if any


def _possible_logos(images: tuple[RenderedImage, ...]) -> list[RenderedImage]:
    # A rough filter so the output is useful; the real ranking comes with the evidence step.
    def mentions_logo(image: RenderedImage) -> bool:
        text = f"{image.url} {image.alt} {image.css_class} {image.element_id}".lower()
        return "logo" in text

    likely = [i for i in images if i.links_home or i.in_header or mentions_logo(i)]
    likely.sort(key=lambda i: (not i.links_home, not mentions_logo(i), not i.in_header))
    return likely[:5]


def _logo_table(images: tuple[RenderedImage, ...]) -> Table:
    table = Table(title="Images that could be the logo")
    for column in ("Kind", "In header", "Links home", "Size", "URL or label"):
        table.add_column(column, overflow="fold")
    for image in _possible_logos(images):
        size = f"{image.box.width:.0f}x{image.box.height:.0f}" if image.box else ""
        table.add_row(
            image.kind,
            "yes" if image.in_header else "",
            "yes" if image.links_home else "",
            size,
            image.url or image.alt,
        )
    return table


def _summary_table(
    snapshot: PageSnapshot, seconds: float, first_browser: str, folder: Path
) -> Table:
    table = Table(show_header=False, title=f"Loaded {snapshot.url}")
    table.add_column(style="bold")
    table.add_column(overflow="fold")
    browser = f"{snapshot.loaded_with} (headless)"
    if snapshot.loaded_with != first_browser:
        browser += f", after {first_browser} was refused or timed out"
    table.add_row("Browser", browser)
    table.add_row("Final URL", snapshot.final_url)
    table.add_row("Status", str(snapshot.status_code or "unknown"))
    table.add_row("Time", f"{seconds:.1f} s")
    table.add_row("HTML", f"{len(snapshot.html) / 1024:.0f} KB")
    table.add_row("Images", str(len(snapshot.images)))
    table.add_row("Saved to", str(folder))
    return table


async def _save_contact_page(fetcher: BrowserFetcher, snapshot: PageSnapshot, site: Path) -> str:
    """Save the contact page the homepage links, which a run reads when the homepage doesn't
    show a phone number or an email address. Returns its address, or "" when there's none or
    it won't load."""
    pages = build_evidence(snapshot).contact_pages
    if not pages:
        return ""
    try:
        contact = await fetcher.fetch(pages[0])
    except FetchError:
        return ""
    await asyncio.to_thread(save_extra_page, contact, site)
    return pages[0]


async def _save_legal_page(fetcher: BrowserFetcher, snapshot: PageSnapshot, site: Path) -> None:
    """Save the site's first legal page, usually its privacy policy, which a run reads when no
    other page gives a street address."""
    pages = build_evidence(snapshot).legal_pages
    if not pages:
        return
    try:
        legal = await fetcher.fetch(pages[0])
    except FetchError:
        return
    await asyncio.to_thread(save_extra_page, legal, site)


async def _check(fetcher: BrowserFetcher, url: str, out: Path) -> FetchCheck:
    started = time.monotonic()
    try:
        snapshot = await fetcher.fetch(url)
    except PageTimeout as exc:
        return FetchCheck(
            url=url, outcome="timed out", seconds=time.monotonic() - started, detail=str(exc)
        )
    except UnsafeUrl as exc:
        return FetchCheck(
            url=url, outcome="unsafe", seconds=time.monotonic() - started, detail=str(exc)
        )
    except FetchError as exc:
        return FetchCheck(
            url=url, outcome="failed", seconds=time.monotonic() - started, detail=str(exc)
        )
    folder = await asyncio.to_thread(save_snapshot, snapshot, out)  # so others keep loading
    contact_page = await _save_contact_page(fetcher, snapshot, folder)
    await _save_legal_page(fetcher, snapshot, folder)
    status = snapshot.status_code
    return FetchCheck(
        url=url,
        outcome="refused" if status and status >= 400 else "loaded",
        status_code=status,
        seconds=time.monotonic() - started,
        images=len(snapshot.images),
        final_url=snapshot.final_url if snapshot.final_url != url else "",
        browser=snapshot.loaded_with,
        contact_page=contact_page,
    )


async def _fetch_one(fetcher: BrowserFetcher, url: str, out: Path, console: Console) -> int:
    async with fetcher:
        started = time.monotonic()
        try:
            snapshot = await fetcher.fetch(url)
        except FetchError as exc:
            typer.echo(f"Couldn't load {url}: {exc}", err=True)
            return 1
        seconds = time.monotonic() - started
        folder = await asyncio.to_thread(save_snapshot, snapshot, out)
        await _save_contact_page(fetcher, snapshot, folder)
        console.print(_summary_table(snapshot, seconds, fetcher.browser_name or "", folder))
        console.print(_logo_table(snapshot.images))
    return 0


async def _fetch_gold(
    fetcher: BrowserFetcher, urls: list[str], out: Path, concurrency: int, console: Console
) -> list[FetchCheck]:
    async with fetcher:
        limit = asyncio.Semaphore(concurrency)

        async def check(url: str) -> FetchCheck:
            async with limit:
                return await _check(fetcher, url, out)

        checks: list[FetchCheck] = []
        for done in asyncio.as_completed([check(url) for url in urls]):
            result = await done
            checks.append(result)
            status = f" ({result.status_code})" if result.status_code else ""
            again = ""
            if result.browser and result.browser != fetcher.browser_name:
                again = f"  (loaded again in {result.browser})"
            console.print(
                f"[{len(checks)}/{len(urls)}] {result.outcome}{status}  {result.url}  "
                f"{result.seconds:.1f} s{again}",
                markup=False,
                highlight=False,
            )
    return checks


def _report_gold(checks: list[FetchCheck], out: Path, first_browser: str, console: Console) -> None:
    """Save every site's outcome to summary.json and print the totals."""
    out.mkdir(parents=True, exist_ok=True)
    summary = "[\n" + ",\n".join(c.model_dump_json(indent=2) for c in checks) + "\n]\n"
    (out / "summary.json").write_text(summary, encoding="utf-8")
    counts = Counter(check.outcome for check in checks)
    loaded_times = [check.seconds for check in checks if check.outcome == "loaded"]
    average = sum(loaded_times) / len(loaded_times) if loaded_times else 0.0
    totals = ", ".join(f"{count} {outcome}" for outcome, count in counts.most_common())
    console.print(f"\n{totals}. Loaded pages took {average:.1f} s on average.", markup=False)
    contact_pages = sum(1 for check in checks if check.contact_page)
    console.print(f"Contact pages saved with them: {contact_pages}.", markup=False)
    again = sum(1 for check in checks if check.browser and check.browser != first_browser)
    if again:
        console.print(
            f"Loaded again in a full browser after {first_browser} was refused or timed out: "
            f"{again}.",
            markup=False,
        )
    console.print(f"Details for each site are in {out}", markup=False)


def fetch(
    url: Annotated[str | None, typer.Argument(help="The page to load.")] = None,
    gold: Annotated[
        Path | None,
        typer.Option(
            help="Load every site in this gold file instead.", exists=True, dir_okay=False
        ),
    ] = None,
    out: Annotated[
        Path, typer.Option(help="Where to save screenshots, HTML and details (git ignores it).")
    ] = Path("bi2-results/dev/fetch"),
    browser: Browser = "auto",
    timeout: Timeout = 20.0,
    concurrency: Annotated[
        int, typer.Option(help="Pages loaded at once with --gold.")
    ] = DEFAULT_CONCURRENCY,
    allow_private: AllowPrivate = False,
) -> None:
    """Load pages in the headless browser and show what it captured."""
    if (url is None) == (gold is None):
        typer.echo("error: give either a URL or --gold, not both", err=True)
        raise typer.Exit(code=2)
    fetcher = BrowserFetcher(timeout_s=timeout, browser=browser, allow_private=allow_private)
    console = Console()
    try:
        if gold is not None:
            urls = [site.url for site in load_gold_set(gold).sites]
            checks = asyncio.run(_fetch_gold(fetcher, urls, out, concurrency, console))
            _report_gold(checks, out, fetcher.browser_name or "", console)
            code = 0
        else:
            assert url is not None
            code = asyncio.run(_fetch_one(fetcher, url, out, console))
    except BrowserUnavailable as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    raise typer.Exit(code=code)
