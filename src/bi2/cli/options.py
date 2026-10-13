"""Options that several commands share."""

import os
from typing import Annotated

import typer

from bi2.fetch.browser import BrowserChoice


def default_concurrency(cores: int | None) -> int:
    """How many sites load at once unless told otherwise. Drawing pages keeps the CPU busy, so
    it's one site for every two cores, up to 8, the fastest measured on a 20-core laptop."""
    return max(2, min(8, (cores or 4) // 2))


DEFAULT_CONCURRENCY = default_concurrency(os.cpu_count())

Browser = Annotated[
    BrowserChoice,
    typer.Option(
        help="Which browser to use. auto loads pages in chromium-shell, and loads a page again "
        "in a full browser when the shell is refused it or times out."
    ),
]
Timeout = Annotated[float, typer.Option(help="Seconds to wait for each page.")]
AllowPrivate = Annotated[bool, typer.Option(hidden=True)]  # for tests that serve pages locally
