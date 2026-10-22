"""The `bi2` command.

Running `bi2` with no command opens the interactive session when a person is at the terminal,
and shows the help otherwise, so a script or a CI job never waits for input.
"""

import asyncio
import sys
from typing import Annotated

import typer

from bi2 import __version__
from bi2.cli.analyze import analyze
from bi2.cli.config import config_app
from bi2.cli.dev import dev_app
from bi2.cli.doctor import check_models, doctor, keys_app
from bi2.cli.evaluate import eval_app
from bi2.cli.review import review
from bi2.core.settings import Settings

app = typer.Typer(name="bi2", invoke_without_command=True, add_completion=False)
app.command()(analyze)
app.command()(review)
app.add_typer(eval_app, name="eval")
app.add_typer(dev_app, name="dev")
app.command()(doctor)
app.add_typer(keys_app, name="keys")
app.add_typer(config_app, name="config")


@app.command(name="mcp")
def mcp_server(
    model: Annotated[
        str | None,
        typer.Option(
            "--model", help='The LLM, as "provider:model", instead of the configured one.'
        ),
    ] = None,
    backup_model: Annotated[
        str | None,
        typer.Option(
            "--backup-model", help='The backup LLM, as "provider:model"; "none" for none.'
        ),
    ] = None,
) -> None:
    r"""Run v2 as an MCP server over standard input and output, for AI assistants such as
    Claude. Needs the mcp extra: pip install "business-insights\[mcp]"."""
    try:
        from bi2.mcp.server import serve
    except ImportError as exc:
        typer.echo(
            'error: the MCP server needs the mcp extra: pip install "business-insights[mcp]"',
            err=True,
        )
        raise typer.Exit(code=1) from exc
    told = {"llm_model": model} if model else {}
    if backup_model is not None:
        told["backup_model"] = backup_model
    check_models(Settings(ai=told) if told else Settings())  # type: ignore[arg-type]
    serve(told)


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"bi2 {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    context: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_show_version,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Find a business's name, logo, MCC, headquarters address, phone, email and social links
    from its website. With no command, at a terminal, opens an interactive session."""
    if context.invoked_subcommand is not None:
        return
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        typer.echo(context.get_help())
        raise typer.Exit()
    from rich.console import Console

    from bi2.cli.interactive.session import run_session

    check_models(Settings())
    asyncio.run(run_session(Console()))
