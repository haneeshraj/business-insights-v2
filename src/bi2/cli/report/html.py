"""Small helpers for writing the report's HTML. Everything a page supplied goes through `e`."""

import os
from collections.abc import Iterable
from html import escape
from pathlib import Path


def e(text: object) -> str:
    """Text made safe to put in HTML, attributes included."""
    return escape(str(text), quote=True)


def link(url: str, text: str | None = None) -> str:
    """A link that opens in a new tab and tells the site nothing about the report."""
    return f'<a href="{e(url)}" target="_blank" rel="noopener noreferrer">{e(text or url)}</a>'


def file_url(path: Path, page: Path) -> str:
    """How the report points to a saved file: relative when possible, so the folder can move."""
    try:
        return Path(os.path.relpath(path, page.parent)).as_posix()
    except ValueError:  # on another drive
        return path.resolve().as_uri()


def rows(pairs: Iterable[tuple[str, str]]) -> str:
    """Table rows of label and value, leaving out empty values."""
    return "".join(
        f"<tr><th>{e(label)}</th><td>{value}</td></tr>" for label, value in pairs if value
    )


def lines(values: Iterable[str]) -> str:
    return "<br>".join(values)


def tick(found: bool) -> str:
    return " <span class=ok>&check;</span>" if found else ""
