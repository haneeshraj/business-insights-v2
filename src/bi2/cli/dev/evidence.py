"""`bi2 dev evidence`: extract a page's evidence and show it, or check the evidence of saved
pages against the gold set."""

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from bi2.cli.dev.options import AllowPrivate, Browser, Timeout
from bi2.cli.dev.saved import load_snapshot, save_snapshot, saved_folders
from bi2.core.errors import BrowserUnavailable, FetchError
from bi2.core.models import Evidence, PageSnapshot
from bi2.evaluation.coverage import FieldCoverage, evidence_coverage, summarize
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


async def _load(fetcher: BrowserFetcher, url: str) -> PageSnapshot:
    async with fetcher:
        return await fetcher.fetch(url)


def _from_url(url: str, out: Path, fetcher: BrowserFetcher, console: Console) -> int:
    try:
        snapshot = asyncio.run(_load(fetcher, url))
    except BrowserUnavailable:
        raise
    except FetchError as exc:
        typer.echo(f"Couldn't load {url}: {exc}", err=True)
        return 1
    folder = save_snapshot(snapshot, out)  # so the page can be tried again with --saved
    ev = build_evidence(snapshot)
    _save_evidence(ev, folder)
    console.print(_evidence_table(ev))
    console.print(f"Saved to {folder}", markup=False)
    return 0


def _report_coverage(
    evidence: list[Evidence], gold_file: Path, out: Path, console: Console
) -> None:
    sites = {site_key(site.url): site for site in load_gold_set(gold_file).sites}
    checked: list[tuple[str, tuple[FieldCoverage, ...]]] = []
    for ev in evidence:
        site = sites.get(site_key(ev.page.url))
        if site is not None:
            checked.append((ev.page.url, evidence_coverage(site, ev)))
    table = Table(title=f"What the evidence already holds, on {len(checked)} gold-set sites")
    for column in ("Check", "Found", "Share"):
        table.add_column(column, justify="left" if column == "Check" else "right")
    for check, (found, total) in summarize(coverage for _, coverage in checked).items():
        table.add_row(check, f"{found} of {total}", f"{found / total:.0%}")
    console.print(table)
    missing = len(sites) - len(checked)
    if missing:
        console.print(f"{missing} gold-set sites have no saved page.", markup=False)
    details = [
        {"url": url, "checks": [check.model_dump() for check in coverage]}
        for url, coverage in checked
    ]
    (out / "coverage.json").write_text(json.dumps(details, indent=2), encoding="utf-8")


def _from_saved(saved: Path, gold: Path | None, out: Path, console: Console) -> int:
    folders = saved_folders(saved)
    if not folders:
        typer.echo(f"error: no pages saved by `bi2 dev fetch` in {saved}", err=True)
        return 1
    evidence: list[Evidence] = []
    for folder in folders:
        ev = build_evidence(load_snapshot(folder))
        _save_evidence(ev, out / folder.name)
        evidence.append(ev)
    console.print(f"Built evidence for {len(evidence)} saved pages, in {out}", markup=False)
    if gold is not None:
        _report_coverage(evidence, gold, out, console)
    return 0


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
    out: Annotated[Path, typer.Option(help="Where to save the evidence (git ignores it).")] = Path(
        "bi2-results/dev/evidence"
    ),
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
        raise typer.Exit(code=_from_saved(saved, gold, out, console))
    assert url is not None
    fetcher = BrowserFetcher(timeout_s=timeout, browser=browser, allow_private=allow_private)
    try:
        code = _from_url(url, out, fetcher, console)
    except BrowserUnavailable as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    raise typer.Exit(code=code)
