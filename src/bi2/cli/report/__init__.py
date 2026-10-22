"""The HTML report that `bi2 analyze` and `bi2 dev evidence` write, for looking through every
site in a browser: the answers, the evidence behind them, the logo candidates as pictures, and
how it all compares with the gold set. `bi2 review` serves the same page with a check on every
answer.

Belongs here: turning results and evidence into the report page. Everything a page supplied is
escaped before it's written, since it comes from other sites.
"""

import re
import webbrowser
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

from bi2.cli.report.answers import label_html
from bi2.cli.report.cards import ReportSite, site_card
from bi2.cli.report.html import e
from bi2.cli.report.learned import learned_section
from bi2.cli.report.page import PAGE, REVIEW_SCRIPT, UNCHECKED_FILTER

__all__ = [
    "ReportSite",
    "ReviewPage",
    "label_html",
    "learned_section",
    "open_in_browser",
    "render_report",
    "write_report",
]

# Filled in one pass, so text from a site that looks like a placeholder is never filled.
_PLACEHOLDER = re.compile(r"\{(title|subtitle|summary|controls|sites|nonce|review)\}")


class ReviewPage(NamedTuple):
    """What turns the report into the review page."""

    token: str  # sent with every check, so only this page can save checks
    nonce: str  # lets this page's own scripts run, and no others
    learned: str  # the summary of what the checks teach, from `learned_section`


def _summary(title: str, summary: dict[str, tuple[int, int]]) -> str:
    body = "".join(
        f'<tr><td>{e(check)}</td><td class="count">{found} of {total}</td>'
        f'<td class="share"><div class="bar"><span style="width:{found / total:.0%}"></span></div>{found / total:.0%}</td></tr>'
        for check, (found, total) in summary.items()
    )
    return (
        f'<section class="card"><h2>{e(title)}</h2>'
        f"<table><tr><th>Check</th><th>Found</th><th>Share</th></tr>{body}</table></section>"
    )


def render_report(
    path: Path,
    sites: list[ReportSite],
    *,
    source: str,
    title: str = "Evidence report",
    summary: dict[str, tuple[int, int]] | None = None,
    summary_title: str = "What the evidence already holds",
    root: Path | None = None,
    review: ReviewPage | None = None,
) -> str:
    """The report page. `path` is where it's served from, since it points to the results'
    files relative to it, and `root` is the folder those files, like logos, are in."""
    when = datetime.now(UTC).astimezone().strftime("%Y-%m-%d %H:%M")
    values = {
        "title": e(title),
        "subtitle": e(f"{len(sites)} pages from {source}, built {when}"),
        "summary": _summary(summary_title, summary) if summary else "",
        "controls": "",
        "sites": "".join(site_card(site, path, root) for site in sites),
        "nonce": "",
        "review": "",
    }
    if review is not None:
        nonce = e(review.nonce)
        values |= {
            "summary": review.learned,
            "controls": UNCHECKED_FILTER,
            "nonce": nonce,
            "review": REVIEW_SCRIPT.replace("{nonce}", nonce).replace("{token}", e(review.token)),
        }
    return _PLACEHOLDER.sub(lambda match: values[match[1]], PAGE)


def write_report(
    path: Path,
    sites: list[ReportSite],
    *,
    source: str,
    title: str = "Evidence report",
    summary: dict[str, tuple[int, int]] | None = None,
    summary_title: str = "What the evidence already holds",
    root: Path | None = None,
) -> None:
    """Write the report as one HTML file that opens in any browser, with no server."""
    html = render_report(
        path,
        sites,
        source=source,
        title=title,
        summary=summary,
        summary_title=summary_title,
        root=root,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def open_in_browser(path: Path) -> bool:
    """Open a written report in the default browser, or say False when none would start.
    `typer.launch` isn't used for this: on Windows, Typer's copy of Click runs `start`, which is
    only a command inside cmd.exe, without a shell, so it fails without a word."""
    return webbrowser.open(path.resolve().as_uri())
