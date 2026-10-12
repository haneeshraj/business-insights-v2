"""`bi2 dev evidence`: extract a page's evidence and show it, or check the evidence of saved
pages against the gold set. Either way it writes an HTML report to look through."""

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from bi2.cli.dev.options import AllowPrivate, Browser, Timeout
from bi2.cli.dev.report import ReportSite, write_report
from bi2.cli.dev.saved import load_snapshot, save_snapshot, saved_folders
from bi2.core.errors import BrowserUnavailable, FetchError
from bi2.core.models import Evidence, PageSnapshot
from bi2.evaluation.coverage import evidence_coverage, summarize
from bi2.evaluation.gold import load_gold_set, site_key
from bi2.evidence.build import build_evidence
from bi2.fetch.browser import BrowserFetcher


def _short(text: str, limit: int = 200) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "\N{HORIZONTAL ELLIPSIS}"


def _rows(ev: Evidence) -> list[tuple[str, str]]:
    page = ev.page.kind.value + (f" ({ev.page.platform})" if ev.page.platform else "")
    data = ev.structured
    return [
        ("Page", page),
        ("Profile name", ev.page.profile_name or ""),
        ("Own website", ev.page.own_website or ""),
        ("Title", ev.meta.title),
        ("Site name", ev.meta.site_name),
        ("og:title", ev.meta.og_title),
        ("Description", ev.meta.description),
        ("og:image", ev.meta.og_image or ""),
        ("Schema types", ", ".join(data.types)),
        ("Schema name", data.name or ""),
        ("Legal name", data.legal_name or ""),
        ("Schema phone", data.telephone or ""),
        ("Schema address", data.address.text if data.address else ""),
        ("Schema logo", data.logo_url or ""),
        ("sameAs", " | ".join(data.same_as)),
        ("Countries", ", ".join(ev.countries)),
        ("Phones", ", ".join(ev.contacts.phones)),
        ("Emails", ", ".join(ev.contacts.emails)),
        ("Postcodes", ", ".join(ev.contacts.postcodes)),
        ("Copyright", ev.contacts.copyright_line or ""),
        ("Social links", " | ".join(profile.url for profile in ev.social_links)),
        *(
            (f"Logo {c.number}", f"{c.kind}: {c.url or c.alt or '(inline image)'}")
            for c in ev.logo_candidates[:5]
        ),
        ("Contact pages", " | ".join(ev.contact_pages)),
        ("Header text", ev.text.header),
        ("Main text", ev.text.main),
        ("Footer text", ev.text.footer),
    ]


def _evidence_table(ev: Evidence) -> Table:
    table = Table(show_header=False, title=f"Evidence for {ev.page.url}")
    table.add_column(style="bold")
    table.add_column(overflow="fold")
    for label, value in _rows(ev):
        if value:
            table.add_row(label, _short(value))
    return table


def _save_evidence(ev: Evidence, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "evidence.json").write_text(ev.model_dump_json(indent=2), encoding="utf-8")


def _report_site(snapshot: PageSnapshot, ev: Evidence, folder: Path) -> ReportSite:
    screenshot = folder / "screenshot.jpg"
    return ReportSite(
        ev, snapshot.status_code, snapshot.loaded_with, screenshot if screenshot.exists() else None
    )


async def _load(fetcher: BrowserFetcher, url: str) -> PageSnapshot:
    async with fetcher:
        return await fetcher.fetch(url)


def _from_url(url: str, out: Path, fetcher: BrowserFetcher, console: Console) -> Path | None:
    try:
        snapshot = asyncio.run(_load(fetcher, url))
    except BrowserUnavailable:
        raise
    except FetchError as exc:
        typer.echo(f"Couldn't load {url}: {exc}", err=True)
        return None
    folder = save_snapshot(snapshot, out)  # so the page can be tried again with --saved
    ev = build_evidence(snapshot)
    _save_evidence(ev, folder)
    console.print(_evidence_table(ev))
    console.print(f"Saved to {folder}", markup=False)
    report = out / "report.html"
    write_report(report, [_report_site(snapshot, ev, folder)], source=url)
    return report


def _with_gold(sites: list[ReportSite], gold_file: Path) -> tuple[list[ReportSite], int]:
    """The sites with their gold-set entries and checks, and how many gold-set sites have no
    saved page."""
    gold = {site_key(entry.url): entry for entry in load_gold_set(gold_file).sites}
    checked = []
    for site in sites:
        entry = gold.get(site_key(site.evidence.page.url))
        if entry is not None:
            site = site._replace(gold=entry, checks=evidence_coverage(entry, site.evidence))
        checked.append(site)
    return checked, len(gold) - sum(1 for site in checked if site.gold is not None)


def _print_coverage(
    sites: list[ReportSite], missing: int, out: Path, console: Console
) -> dict[str, tuple[int, int]]:
    """Print how much of the gold set the evidence holds, and save each site's checks."""
    checked = [site for site in sites if site.gold is not None]
    summary = summarize(site.checks for site in checked)
    table = Table(title=f"What the evidence already holds, on {len(checked)} gold-set sites")
    for column in ("Check", "Found", "Share"):
        table.add_column(column, justify="left" if column == "Check" else "right")
    for check, (found, total) in summary.items():
        table.add_row(check, f"{found} of {total}", f"{found / total:.0%}")
    console.print(table)
    if missing:
        console.print(f"{missing} gold-set sites have no saved page.", markup=False)
    details = [
        {"url": site.evidence.page.url, "checks": [check.model_dump() for check in site.checks]}
        for site in checked
    ]
    (out / "coverage.json").write_text(json.dumps(details, indent=2), encoding="utf-8")
    return summary


def _from_saved(saved: Path, gold: Path | None, out: Path, console: Console) -> Path | None:
    folders = saved_folders(saved)
    if not folders:
        typer.echo(f"error: no pages saved by `bi2 dev fetch` in {saved}", err=True)
        return None
    sites: list[ReportSite] = []
    for folder in folders:
        snapshot = load_snapshot(folder)
        ev = build_evidence(snapshot)
        _save_evidence(ev, out / folder.name)
        sites.append(_report_site(snapshot, ev, folder))
    console.print(f"Built evidence for {len(sites)} saved pages, in {out}", markup=False)
    summary = None
    if gold is not None:
        sites, missing = _with_gold(sites, gold)
        summary = _print_coverage(sites, missing, out, console)
    report = out / "report.html"
    write_report(report, sites, source=str(saved), summary=summary)
    return report


def evidence(
    url: Annotated[str | None, typer.Argument(help="The page to load.")] = None,
    saved: Annotated[
        Path | None,
        typer.Option(
            help="Use the pages `bi2 dev fetch` saved in this folder, instead of loading any.",
            exists=True,
            file_okay=False,
        ),
    ] = None,
    gold: Annotated[
        Path | None,
        typer.Option(
            help="With --saved: check the evidence against this gold file.",
            exists=True,
            dir_okay=False,
        ),
    ] = None,
    out: Annotated[
        Path, typer.Option(help="Where to save the evidence and the report (git ignores it).")
    ] = Path("bi2-results/dev/evidence"),
    open_report: Annotated[
        bool, typer.Option("--open", help="Open the HTML report in your browser when it's done.")
    ] = False,
    browser: Browser = "auto",
    timeout: Timeout = 20.0,
    allow_private: AllowPrivate = False,
) -> None:
    """Extract a page's evidence, the facts gathered before any model runs, and show it."""
    if (url is None) == (saved is None):
        typer.echo("error: give either a URL or --saved, not both", err=True)
        raise typer.Exit(code=2)
    if gold is not None and saved is None:
        typer.echo("error: --gold needs --saved", err=True)
        raise typer.Exit(code=2)
    console = Console()
    if saved is not None:
        report = _from_saved(saved, gold, out, console)
    else:
        assert url is not None
        fetcher = BrowserFetcher(timeout_s=timeout, browser=browser, allow_private=allow_private)
        try:
            report = _from_url(url, out, fetcher, console)
        except BrowserUnavailable as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
    if report is None:
        raise typer.Exit(code=1)
    console.print(f"Report: {report.resolve()}", markup=False, highlight=False)
    if open_report:
        typer.launch(str(report.resolve()))
