"""The `bi2` command.

Running `bi2` with no command will open the interactive session once it's built. Until then,
it shows the help.
"""

from typing import Annotated

import typer

from bi2 import __version__
from bi2.cli.analyze import analyze
from bi2.cli.dev import dev_app
from bi2.cli.evaluate import eval_app
from bi2.cli.review import review

app = typer.Typer(name="bi2", no_args_is_help=True, add_completion=False)
app.command()(analyze)
app.command()(review)
app.add_typer(eval_app, name="eval")
app.add_typer(dev_app, name="dev")


@app.command(name="mcp")
def mcp_server() -> None:
    """Run v2 as an MCP server over standard input and output, for AI assistants such as
    Claude. Needs the mcp extra: pip install "business-insights[mcp]"."""
    try:
        from bi2.mcp.server import serve
    except ImportError as exc:
        typer.echo(
            'error: the MCP server needs the mcp extra: pip install "business-insights[mcp]"',
            err=True,
        )
        raise typer.Exit(code=1) from exc
    serve()


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"bi2 {__version__}")
        raise typer.Exit()


@app.callback()
def main(
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
    from its website."""
