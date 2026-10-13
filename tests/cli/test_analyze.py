"""Tests for `bi2 analyze`."""

from pathlib import Path

from typer.testing import CliRunner

from bi2.cli.dev.saved import save_snapshot
from bi2.cli.main import app
from bi2.core.models import Box, RenderedImage, SiteResult, Status
from tests.factories import page_snapshot

runner = CliRunner()

PAGE = """<html><head><title>Example Cafe | Coffee in Toronto</title>
<meta property="og:site_name" content="Example Cafe"></head>
<body><main><p>Coffee.</p></main>
<footer><a href="tel:+14165550123">Call us</a></footer></body></html>"""


def test_saved_pages_are_analyzed_checked_and_reported(tmp_path: Path, site: str) -> None:
    logo = RenderedImage(
        kind="img",
        url=f"{site}/images/brand.png",  # served by the local test website
        alt="Example Cafe logo",
        box=Box(x=20, y=10, width=160, height=60),
        in_header=True,
        links_home=True,
    )
    saved = tmp_path / "saved"
    save_snapshot(page_snapshot(PAGE, images=(logo,)), saved)
    gold = tmp_path / "gold.toml"
    gold.write_text(
        '[[site]]\nurl = "https://example-cafe.ca/"\ncategory = "cafe"\n'
        'company_names = ["Example Cafe"]\nphones = ["+14165550123"]\n',
        encoding="utf-8",
    )
    out = tmp_path / "out"
    outcome = runner.invoke(
        app,
        [
            "analyze",
            "--saved",
            str(saved),
            "--gold",
            str(gold),
            "--out",
            str(out),
            "--allow-private",
        ],
    )
    assert outcome.exit_code == 0, outcome.output
    assert "Right answers, by the gold set" in outcome.output
    lines = (out / "results.jsonl").read_text(encoding="utf-8").splitlines()
    result = SiteResult.model_validate_json(lines[0])
    assert (result.company_name.value, result.phone.value) == ("Example Cafe", "+14165550123")
    assert result.logo.status is Status.OK
    assert (out / "example-cafe.ca" / "logo.png").exists()
    report = (out / "report.html").read_text(encoding="utf-8")
    assert "Analysis report" in report
    assert 'class="answer-logo"' in report


def test_analyze_needs_something_to_analyze() -> None:
    outcome = runner.invoke(app, ["analyze"])
    assert outcome.exit_code == 2
    assert "give the pages to analyze" in outcome.output


def test_a_gold_site_with_no_saved_page_counts_as_failed(tmp_path: Path) -> None:
    saved = tmp_path / "saved"
    save_snapshot(page_snapshot(PAGE), saved)
    gold = tmp_path / "gold.toml"
    gold.write_text(
        '[[site]]\nurl = "https://example-cafe.ca/"\ncategory = "cafe"\n\n'
        '[[site]]\nurl = "https://slow-site.ca/"\ncategory = "shop"\n',
        encoding="utf-8",
    )
    out = tmp_path / "out"
    args = ["analyze", "--saved", str(saved), "--gold", str(gold), "--out", str(out)]
    outcome = runner.invoke(app, args)
    assert outcome.exit_code == 0, outcome.output
    lines = (out / "results.jsonl").read_text(encoding="utf-8").splitlines()
    results = {r.page.url: r for r in map(SiteResult.model_validate_json, lines)}
    assert results["https://slow-site.ca/"].error == "its page wasn't saved, since it didn't load"
    assert results["https://example-cafe.ca/"].error is None
