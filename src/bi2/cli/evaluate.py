"""`bi2 eval`: measure accuracy, cost and speed against the gold set (for contributors)."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from bi2.evaluation.compare import Comparison, Totals, compare_runs
from bi2.evaluation.gold import load_gold_set, site_key
from bi2.evaluation.report import Report, build_report, load_results
from bi2.evaluation.scoring import Verdict
from bi2.evaluation.verifications import load_verifications

eval_app = typer.Typer(
    no_args_is_help=True,
    help="Measure accuracy, cost and speed against the gold set (for contributors).",
)

_PROBLEMS = (Verdict.WRONG, Verdict.MISSED, Verdict.UNEXPECTED)


def _percent(share: float | None) -> str:
    return "n/a" if share is None else f"{share:.0%}"


def _summary_table(report: Report) -> Table:
    table = Table(title="Accuracy by field")
    for column in ("Field", "Accuracy", "Correct", "Wrong", "Missed", "Unexpected", "Review"):
        table.add_column(column, justify="left" if column == "Field" else "right")
    for summary in report.fields:
        table.add_row(
            summary.field,
            _percent(summary.accuracy),
            str(summary.correct),
            str(summary.wrong),
            str(summary.missed),
            str(summary.unexpected),
            str(summary.needs_review),
        )
    return table


def _problems_table(report: Report) -> Table | None:
    table = Table(title="Answers that weren't correct")
    for column in ("Site", "Field", "Verdict", "Got", "Expected"):
        table.add_column(column, overflow="fold")
    # Sites with no result would list every field; the totals line already counts them.
    for site in (site for site in report.sites if site.ran):
        for score in site.fields:
            if score.verdict in _PROBLEMS:
                table.add_row(site.url, score.field, score.verdict, score.got, score.expected)
    return table if table.row_count else None


def _totals_line(report: Report) -> str:
    cost_per_site = report.cost_per_site
    parts = [
        f"{report.sites_run} of {len(report.sites)} sites ran",
        f"${report.cost.usd:.4f} total" if report.cost.usd else "cost not recorded",
        f"${cost_per_site:.4f} per site" if cost_per_site else "",
        f"{report.cost.input_tokens + report.cost.output_tokens:,} tokens",
        f"{report.cost.model_calls} model calls",
        f"{report.seconds_per_site:.1f} s per site" if report.seconds_per_site else "",
    ]
    line = ", ".join(part for part in parts if part)
    if report.unconfirmed_sites:
        line += f"\n{report.unconfirmed_sites} sites have answers no one has confirmed yet."
    if report.extra_results:
        line += f"\n{report.extra_results} results were for sites not in the gold set."
    return line


@eval_app.command()
def score(
    gold: Annotated[
        Path, typer.Argument(help="The gold-set TOML file.", exists=True, dir_okay=False)
    ],
    results: Annotated[
        Path,
        typer.Argument(
            help="Results to score: one SiteResult per line.", exists=True, dir_okay=False
        ),
    ],
    confirmed_only: Annotated[
        bool, typer.Option(help="Score only sites whose answers a person has confirmed.")
    ] = False,
    json_out: Annotated[
        Path | None, typer.Option("--json", help="Also save the full report as JSON here.")
    ] = None,
) -> None:
    """Score saved results against the gold set."""
    try:
        report = build_report(
            load_gold_set(gold), load_results(results), confirmed_only=confirmed_only
        )
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    console = Console()
    console.print(_summary_table(report))
    console.print(_totals_line(report))
    problems = _problems_table(report)
    if problems:
        console.print(problems)
    if json_out:
        json_out.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"Saved the full report to {json_out}")


def _results_file(path: Path) -> Path:
    """A run's results: the folder `bi2 analyze` wrote them to, or the results file itself."""
    return path / "results.jsonl" if path.is_dir() else path


def _short(text: str, limit: int = 70) -> str:
    """Long answers, like logo addresses, cut in the middle so both ends still show."""
    if len(text) <= limit:
        return text
    return text[: limit // 2] + "\N{HORIZONTAL ELLIPSIS}" + text[-(limit // 2 - 1) :]


def _share(totals: Totals | None, count: int) -> str:
    return "" if totals is None or not totals.checked else f"{count} of {totals.checked}"


def _totals_table(comparison: Comparison) -> Table:
    table = Table(title="Checked answers that were right")
    for column in ("Field", "Before", "After", "Right and sure, before", "After"):
        table.add_column(column, justify="left" if column == "Field" else "right")
    for field in dict.fromkeys([*comparison.before, *comparison.after]):
        then, now = comparison.before.get(field), comparison.after.get(field)
        table.add_row(
            field,
            _share(then, then.right if then else 0),
            _share(now, now.right if now else 0),
            _share(then, then.right_and_sure if then else 0),
            _share(now, now.right_and_sure if now else 0),
        )
    return table


_GROUPS = (
    ("worse", "Answers that got worse", "red"),
    ("better", "Answers that got better", "green"),
    ("not checked", "Answers that changed, but no one has checked", "yellow"),
    ("the same", "Answers that changed, and are as good as before", "dim"),
)


@eval_app.command()
def compare(
    before: Annotated[
        Path,
        typer.Argument(help="The earlier run: its results folder or results file.", exists=True),
    ],
    after: Annotated[Path, typer.Argument(help="The later run, given the same way.", exists=True)],
    gold: Annotated[
        Path | None,
        typer.Option(help="A gold-set file to judge answers by.", exists=True, dir_okay=False),
    ] = None,
    checks: Annotated[
        Path, typer.Option(help="Your checks from the review page.", dir_okay=False)
    ] = Path("eval/verifications.jsonl"),
) -> None:
    """Compare two runs of the same sites: what got better, and what got worse.

    Exits with 1 when anything got worse, so a script can stop a change that breaks answers,
    and with 2 when a file can't be read."""
    try:
        entries = {site_key(site.url): site for site in load_gold_set(gold).sites} if gold else {}
        comparison = compare_runs(
            load_results(_results_file(before)),
            load_results(_results_file(after)),
            entries,
            load_verifications(checks),
        )
    except (OSError, ValueError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    console = Console()
    if comparison.before or comparison.after:
        console.print(_totals_table(comparison))
    else:
        console.print("No answers in these runs are checked yet; check them with `bi2 review`.")
    for verdict, title, style in _GROUPS:
        changes = [change for change in comparison.changes if change.verdict == verdict]
        if not changes:
            continue
        table = Table(title=title, title_style=style)
        for column in ("Site", "Field", "Before", "After"):
            table.add_column(column, overflow="fold")
        for change in changes:
            table.add_row(change.site, change.field, _short(change.before), _short(change.after))
        console.print(table)
    if comparison.failed_now:
        console.print("No longer loads: " + ", ".join(comparison.failed_now), style="red")
    if comparison.loaded_now:
        console.print("Loads now: " + ", ".join(comparison.loaded_now), style="green")
    if not (comparison.changes or comparison.failed_now or comparison.loaded_now):
        console.print("No answers changed.")
    if comparison.worse:
        raise typer.Exit(code=1)
