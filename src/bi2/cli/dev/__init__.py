"""`bi2 dev`: try one part of the pipeline on real websites (for contributors).

Each part of the pipeline gets a command here, so it can be checked on real sites on its own.

Belongs here: commands that show what one part of the pipeline does. Doesn't belong here:
anything a user needs to analyze sites.
"""

import typer

from bi2.cli.dev.evidence import evidence
from bi2.cli.dev.fetch import fetch

dev_app = typer.Typer(
    no_args_is_help=True,
    help="Try one part of the pipeline on real websites (for contributors).",
)
dev_app.command()(fetch)
dev_app.command()(evidence)
