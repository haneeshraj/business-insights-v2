"""`bi2 analyze`: find businesses' details from their websites, and save the results."""

import asyncio
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Final, NamedTuple

import typer
from rich.console import Console
from rich.table import Table

from bi2.cli.dev.saved import load_snapshot, saved_folders
from bi2.cli.options import AllowPrivate, Browser, Timeout
from bi2.cli.report import ReportSite, write_report
from bi2.core.errors import BrowserUnavailable
from bi2.core.models import FIELD_NAMES, Evidence, SiteResult, Status
from bi2.core.urls import site_folder
from bi2.evaluation.gold import GoldSite, load_gold_set, site_key
from bi2.evaluation.scoring import SCORED_FIELDS, FieldScore, Verdict, score_site
from bi2.fetch.browser import BrowserChoice
from bi2.pipeline import analyze_snapshot, analyze_url, failed_result
from bi2.wiring import local_context

_SHORT: Final = {
    Status.OK: "ok",
    Status.NEEDS_REVIEW: "review",
    Status.NOT_FOUND: "none",
    Status.ERROR: "error",
}
_SHOWN: Final = (
    ("company_name", "name"),
    ("logo", "logo"),
    ("phone", "phone"),
    ("social_links", "social"),
)


class _Analyzed(NamedTuple):
    result: SiteResult
    evidence: Evidence | None
    status_code: int | None = None
    loaded_with: str = ""


class _Run(NamedTuple):
    out: Path
    browser: BrowserChoice
    timeout: float
    concurrency: int
    allow_private: bool
    saved: Path | None = None  # the folder of saved pages, when the run uses them


def _progress(done: int, total: int, site: _Analyzed) -> str:
    result = site.result
    if result.error:
        return f"[{done}/{total}] failed  {result.page.url}  {result.error}"
    fields = "  ".join(
        f"{label} {_SHORT[result.field_results[name].status]}" for name, label in _SHOWN
    )
    return f"[{done}/{total}] {result.page.url}  {fields}  {result.seconds:.1f} s"


async def _analyze_all(
    sources: Sequence[str | Path], run: _Run, console: Console
) -> list[_Analyzed]:
    """Analyze every source, a few at a time, in the order given."""
    saved = bool(sources) and isinstance(sources[0], Path)
    async with local_context(
        run.out,
        load_pages=not saved,
        browser=run.browser,
        timeout_s=run.timeout,
        allow_private=run.allow_private,
        # Runs on saved pages keep what they download beside the pages, so reruns match.
        kept_downloads=run.saved / "downloads" if run.saved is not None else None,
    ) as ctx:
        limit = asyncio.Semaphore(run.concurrency)

        async def one(index: int, source: str | Path) -> tuple[int, _Analyzed]:
            async with limit:
                if isinstance(source, Path):
                    snapshot = await asyncio.to_thread(load_snapshot, source)
                    result, ev = await analyze_snapshot(snapshot, ctx)
                    return index, _Analyzed(result, ev, snapshot.status_code, snapshot.loaded_with)
                result, found = await analyze_url(source, ctx)
                return index, _Analyzed(result, found)

        analyzed: list[_Analyzed | None] = [None] * len(sources)
        tasks = [one(index, source) for index, source in enumerate(sources)]
        for finished, task in enumerate(asyncio.as_completed(tasks), start=1):
            index, site = await task
            analyzed[index] = site
            console.print(_progress(finished, len(sources), site), markup=False, highlight=False)
    return [site for site in analyzed if site is not None]


def _totals(results: list[SiteResult], console: Console) -> None:
    table = Table(title=f"Answers for {len(results)} sites")
    table.add_column("Field")
    for status in _SHORT.values():
        table.add_column(status, justify="right")
    for name in FIELD_NAMES:
        counts = Counter(result.field_results[name].status for result in results)
        table.add_row(name, *(str(counts[status] or "") for status in _SHORT))
    console.print(table)


def _right_answers(scores: list[tuple[FieldScore, ...]]) -> dict[str, tuple[int, int]]:
    """For each field, how many answers the gold set marks right, out of those it checks."""
    totals: dict[str, tuple[int, int]] = {}
    for field in SCORED_FIELDS:
        verdicts = [s.verdict for site in scores for s in site if s.field == field]
        checked = [v for v in verdicts if v is not Verdict.NOT_SCORED]
        if checked:
            totals[field] = (checked.count(Verdict.CORRECT), len(checked))
    return totals


def _print_right_answers(totals: dict[str, tuple[int, int]], console: Console) -> None:
    table = Table(title="Right answers, by the gold set")
    for column in ("Field", "Right", "Share"):
        table.add_column(column, justify="left" if column == "Field" else "right")
    for field, (right, checked) in totals.items():
        table.add_row(field, f"{right} of {checked}", f"{right / checked:.0%}")
    console.print(table)


def _sources(
    urls: list[str] | None, gold: Path | None, saved: Path | None
) -> list[str] | list[Path]:
    if urls:
        return [url if "://" in url else f"https://{url}" for url in urls]
    if saved is not None:
        return saved_folders(saved)
    assert gold is not None
    return [site.url for site in load_gold_set(gold).sites]


def _unsaved(gold: Path, saved: Path) -> list[_Analyzed]:
    """A failed result for each gold-file site whose page wasn't saved, so a run on saved pages
    still counts every site: a page that wouldn't load is part of the sample too."""
    have = {folder.name for folder in saved_folders(saved)}
    return [
        _Analyzed(failed_result(site.url, "its page wasn't saved, since it didn't load", 0.0), None)
        for site in load_gold_set(gold).sites
        if site_folder(site.url) not in have
    ]


def _report_site(site: _Analyzed, out: Path, gold: dict[str, GoldSite]) -> ReportSite:
    ev = site.evidence
    entry = gold.get(site_key(site.result.page.url))
    screenshot = out / ev.screenshot_file if ev is not None and ev.screenshot_file else None
    return ReportSite(
        ev,
        site.status_code,
        site.loaded_with,
        screenshot,
        gold=entry,
        result=site.result,
        scores=score_site(entry, site.result) if entry is not None else (),
    )


def analyze(
    urls: Annotated[list[str] | None, typer.Argument(help="The pages to analyze.")] = None,
    gold: Annotated[
        Path | None,
        typer.Option(
            help="Analyze every site in this gold file, or with --saved, check the answers "
            "against it.",
            exists=True,
            dir_okay=False,
        ),
    ] = None,
    saved: Annotated[
        Path | None,
        typer.Option(
            help="Analyze the pages `bi2 dev fetch` saved in this folder, instead of loading them.",
            exists=True,
            file_okay=False,
        ),
    ] = None,
    out: Annotated[
        Path, typer.Option(help="Where to save the results, logos and report (git ignores it).")
    ] = Path("bi2-results/analyze"),
    open_report: Annotated[
        bool, typer.Option("--open", help="Open the HTML report in your browser when it's done.")
    ] = False,
    concurrency: Annotated[int, typer.Option(help="Sites analyzed at once.")] = 4,
    browser: Browser = "auto",
    timeout: Timeout = 20.0,
    allow_private: AllowPrivate = False,
) -> None:
    """Find each business's name, logo, phone number and social media links from its website."""
    if urls and saved is not None:
        typer.echo("error: give URLs or --saved, not both", err=True)
        raise typer.Exit(code=2)
    if not urls and gold is None and saved is None:
        typer.echo("error: give the pages to analyze: URLs, --gold or --saved", err=True)
        raise typer.Exit(code=2)
    sources = _sources(urls, gold, saved)
    if not sources:
        typer.echo("error: there are no pages to analyze", err=True)
        raise typer.Exit(code=1)
    console = Console()
    run = _Run(out, browser, timeout, concurrency, allow_private, saved)
    try:
        analyzed = asyncio.run(_analyze_all(sources, run, console))
    except BrowserUnavailable as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if saved is not None and gold is not None:
        analyzed += _unsaved(gold, saved)
    results = [site.result for site in analyzed]
    out.mkdir(parents=True, exist_ok=True)
    lines = (result.model_dump_json() for result in results)
    (out / "results.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _totals(results, console)
    entries = {site_key(entry.url): entry for entry in load_gold_set(gold).sites} if gold else {}
    sites = [_report_site(site, out, entries) for site in analyzed]
    right = _right_answers([site.scores for site in sites if site.gold is not None])
    if right:
        _print_right_answers(right, console)
    report = out / "report.html"
    write_report(
        report,
        sites,
        source=str(saved or gold or "the command line"),
        title="Analysis report",
        summary=right or None,
        summary_title="Right answers, by the gold set",
        root=out,
    )
    console.print(f"Results: {(out / 'results.jsonl').resolve()}", markup=False, highlight=False)
    console.print(f"Report: {report.resolve()}", markup=False, highlight=False)
    if open_report:
        typer.launch(str(report.resolve()))
