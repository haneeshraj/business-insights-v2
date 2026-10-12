"""Options that several commands share."""

from typing import Annotated

import typer

from bi2.fetch.browser import BrowserChoice

Browser = Annotated[
    BrowserChoice,
    typer.Option(
        help="Which browser to use. auto loads pages in chromium-shell, and loads pages it's "
        "refused again in a full browser."
    ),
]
Timeout = Annotated[float, typer.Option(help="Seconds to wait for each page.")]
AllowPrivate = Annotated[bool, typer.Option(hidden=True)]  # for tests that serve pages locally
