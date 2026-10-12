"""The HTML report that `bi2 analyze` and `bi2 dev evidence` write, for looking through every
site in a browser: the answers, the evidence behind them, the logo candidates as pictures, and
how it all compares with the gold set.

Belongs here: turning results and evidence into the report page. Everything a page supplied is
escaped before it's written, since it comes from other sites.
"""

from datetime import UTC, datetime
from pathlib import Path

from bi2.cli.report.cards import ReportSite, site_card
from bi2.cli.report.html import e
from bi2.cli.report.page import PAGE

__all__ = ["ReportSite", "write_report"]


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
    """Write the report as one HTML file that opens in any browser, with no server. `root` is
    the folder the results' files, like logos, are in."""
    when = datetime.now(UTC).astimezone().strftime("%Y-%m-%d %H:%M")
    body = "".join(site_card(site, path, root) for site in sites)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        PAGE.replace("{title}", e(title))
        .replace("{subtitle}", e(f"{len(sites)} pages from {source}, built {when}"))
        .replace("{summary}", _summary(summary_title, summary) if summary else "")
        .replace("{sites}", body),
        encoding="utf-8",
    )
