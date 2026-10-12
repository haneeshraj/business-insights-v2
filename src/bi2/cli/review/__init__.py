"""`bi2 review`: check a run's answers in your browser. Mark each one right or wrong, with a
note about what you saw; the page shows what the checks teach as you go.

Belongs here: the command, the review page's state (session.py) and its server (server.py).
"""

import webbrowser
from pathlib import Path
from typing import Annotated

import typer

from bi2.cli.review.server import ReviewServer
from bi2.cli.review.session import ReviewSession
from bi2.evaluation.gold import load_gold_set, site_key


def review(
    results: Annotated[
        Path,
        typer.Argument(
            help="The folder a `bi2 analyze` run saved its results in.",
            exists=True,
            file_okay=False,
        ),
    ] = Path("bi2-results/analyze"),
    gold: Annotated[
        Path,
        typer.Option(
            help="The gold set. Its answers count as checked; skipped when the file isn't there.",
            dir_okay=False,
        ),
    ] = Path("eval/gold.toml"),
    checks: Annotated[
        Path, typer.Option(help="Where your checks and notes are kept.", dir_okay=False)
    ] = Path("eval/verifications.jsonl"),
    port: Annotated[
        int, typer.Option(help="The port to serve the page on; 0 picks a free one.", min=0)
    ] = 0,
    open_page: Annotated[
        bool, typer.Option("--open/--no-open", help="Open the page in your browser.")
    ] = True,
) -> None:
    """Check a run's answers in your browser: right or wrong, with a note."""
    if not (results / "results.jsonl").is_file():
        typer.echo(f"error: there are no results in {results}; run `bi2 analyze` first", err=True)
        raise typer.Exit(code=1)
    try:
        entries = (
            {site_key(site.url): site for site in load_gold_set(gold).sites}
            if gold.is_file()
            else {}
        )
        session = ReviewSession(results, entries, checks)
    except (OSError, ValueError) as exc:  # a results, gold or checks file that can't be read
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    try:
        server = ReviewServer(session, port)
    except OSError as exc:
        typer.echo(f"error: can't serve the page on port {port}: {exc.strerror or exc}", err=True)
        raise typer.Exit(code=1) from exc
    answers, checked, yours = session.counts()
    typer.echo(f"Reviewing {session.sites} sites from {results}")
    typer.echo(f"Checked so far: {checked} of {answers} answers, {yours} by you")
    typer.echo(f"Your checks and notes are saved to {checks}")
    typer.echo(f"Review page: {server.url}  (Ctrl+C stops it)")
    if open_page:
        webbrowser.open(server.url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        typer.echo("Stopped.")
    finally:
        server.server_close()
