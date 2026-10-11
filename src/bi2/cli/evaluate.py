"""`bi2 eval`: measure accuracy, cost and speed against the gold set (for contributors)."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from bi2.evaluation.gold import load_gold_set
from bi2.evaluation.report import Report, build_report, load_results
from bi2.evaluation.scoring import Verdict

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
