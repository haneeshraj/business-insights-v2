"""Tests for the HTML report `bi2 dev evidence` writes."""

from pathlib import Path

from bi2.cli.report import ReportSite, write_report
from bi2.core.models import Box, Evidence, LogoCandidate, PageInfo, PageKind, PageMeta
from bi2.evaluation.coverage import evidence_coverage, summarize
from bi2.evaluation.gold import GoldSite

URL = "https://example-cafe.ca/"
GOLD = GoldSite(
    url=URL,
    category="cafe",
    company_names=("Example Cafe",),
    logo_urls=(f"{URL}logo.png",),
    phones=("+14165550123",),
)
EVIDENCE = Evidence(
    page=PageInfo(url=URL, final_url=URL, kind=PageKind.OWN_WEBSITE),
    meta=PageMeta(title="Example Cafe <script>alert(1)</script>", site_name="Example Cafe"),
    logo_candidates=(
        LogoCandidate(
            number=1,
            kind="img",
            url=f"{URL}logo.png",
            box=Box(x=20, y=10, width=160, height=60),
            in_header=True,
            links_home=True,
        ),
        LogoCandidate(
            number=2,
            kind="img",
            url=f"{URL}footer-logo.png",
            box=Box(x=20, y=3000, width=80, height=30),
        ),
    ),
)


def _report(tmp_path: Path) -> str:
    screenshot = tmp_path / "pages" / "example-cafe.ca" / "screenshot.jpg"
    screenshot.parent.mkdir(parents=True)
    screenshot.write_bytes(b"\xff\xd8")
    checks = evidence_coverage(GOLD, EVIDENCE)
    site = ReportSite(EVIDENCE, 200, "chromium-shell", screenshot, GOLD, checks)
    report = tmp_path / "out" / "report.html"
    write_report(report, [site], source="pages", summary=summarize([checks]))
    return report.read_text(encoding="utf-8")


def test_text_from_the_page_is_escaped(tmp_path: Path) -> None:
    html = _report(tmp_path)
    assert "<script>alert" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_logo_candidates_are_shown_as_pictures(tmp_path: Path) -> None:
    html = _report(tmp_path)
    # The first is cut out of the screenshot, found by a path relative to the report.
    assert 'class="crop"' in html
    assert "../pages/example-cafe.ca/screenshot.jpg" in html
    # The second is below the first screen, so its own image is shown instead.
    assert f'<img src="{URL}footer-logo.png"' in html
    assert "&check; gold" in html  # the first is the gold set's logo


def test_gold_checks_and_the_summary_are_shown(tmp_path: Path) -> None:
    html = _report(tmp_path)
    assert "What the evidence already holds" in html
    assert 'data-misses="1"' in html  # the phone isn't in this evidence
    assert "+14165550123" in html
